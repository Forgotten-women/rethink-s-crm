"""Treasury, Multi-Currency Bank Accounts & Project Pots Budgeting API.

The baseline is Osman's Fund Position close (31 Oct 2026, archive v69). Every change made in the CRM is written to
treasury_activity together with the exact steps that undo it, so any transfer, entry, reallocation or balance update
can be reversed from the Activity tab."""

import csv
import io
import json
import re
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from config.settings import LOCAL_DB_PATH
from backend.services.fx_engine import convert_amount, get_fx_rates, normalize_currency
from backend.services.treasury_seed import (
    ensure_treasury_extras_schema, seed_treasury_data, seed_treasury_extras,
)

router = APIRouter(prefix="/api/treasury", tags=["Treasury & Project Pots"])

_treasury_initialized = False

# Charities whose treasury has been set up. Every endpoint is scoped to one of these, so a person who only works
# for another charity never sees these balances.
TREASURY_COMPANIES = {"rethink"}

# WEEKLY_PROCESS.md: "UK and Turkey are not zakat-eligible destinations"
ZAKAT_RESTRICTED_COUNTRIES = {"uk", "united kingdom", "turkey", "türkiye"}

# Ledger rows that the fund-position build does not count (kept for the audit trail only).
DUP_FLAGS = ("pre_sep_already_booked", "sep_line_in_aug_file", "oct_line_in_older_file")
_DUP_SQL = "(" + " OR ".join(f"COALESCE(flags,'') LIKE '%{f}%'" for f in DUP_FLAGS) + ")"
_OUTSIDE_SQL = "(COALESCE(flags,'') LIKE '%outside_period%')"
_COUNTED_SQL = f"(NOT {_OUTSIDE_SQL})"
_STATUS_SQL = (f"CASE WHEN {_DUP_SQL} THEN 'duplicate' WHEN {_OUTSIDE_SQL} THEN 'before_period' "
               f"ELSE 'counted' END")


def _get_conn() -> sqlite3.Connection:
    global _treasury_initialized
    if not _treasury_initialized:
        seed_treasury_data(db_path=LOCAL_DB_PATH)
        seed_treasury_extras(db_path=LOCAL_DB_PATH)
        _treasury_initialized = True
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    ensure_treasury_extras_schema(conn)
    return conn


def _company(company_id: Optional[str]) -> str:
    comp = (company_id or "rethink").strip().lower()
    if comp not in TREASURY_COMPANIES:
        raise HTTPException(status_code=404, detail=f"Treasury has not been set up for '{comp}' yet.")
    return comp


def _actor(request: Optional[Request], fallback: Optional[str] = None) -> str:
    user = getattr(getattr(request, "state", None), "api_user", None) or {}
    return user.get("email") or user.get("name") or fallback or "CRM"


def _can_approve_transfers(request: Optional[Request], comp: str) -> bool:
    user = getattr(getattr(request, "state", None), "api_user", None)
    if not user:
        return True
    from core import rbac
    return rbac.user_has(user, "expenses.transfers_approve", comp)


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _clean_date(d: Optional[str]) -> str:
    d = (d or _today()).strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD.")
    return d


def _log(cur: sqlite3.Cursor, actor: str, action: str, summary: str, amount_usd: float,
         payload: Dict[str, Any], undo: List[Dict[str, Any]], company: str = "rethink") -> int:
    cur.execute(
        """INSERT INTO treasury_activity (actor, action, summary, amount_usd, payload_json, undo_json, company_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (actor, action, summary, round(float(amount_usd or 0), 2), json.dumps(payload, default=str),
         json.dumps(undo), company),
    )
    return int(cur.lastrowid)


def _csv(rows: List[Dict[str, Any]], columns: List[str], name: str) -> Response:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in columns})
    safe = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower() or "export"
    return Response(
        content="﻿" + buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe}_{datetime.utcnow():%Y%m%d_%H%M}.csv"'},
    )


def _account_delta(cur: sqlite3.Cursor, acc: sqlite3.Row, native_delta: float) -> Dict[str, Any]:
    """Move an account's balance; the reconciled USD value moves at the account's own period rate."""
    rate = float(acc["reconciled_fx_rate"] or 1.0)
    usd_delta = round(native_delta * rate, 2)
    cur.execute(
        """UPDATE treasury_accounts SET current_balance_native = current_balance_native + ?,
           reconciled_usd = reconciled_usd + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
        (native_delta, usd_delta, acc["id"]),
    )
    return {"op": "account_delta", "id": acc["id"], "native": -native_delta, "usd": -usd_delta}


def _pot_delta(cur: sqlite3.Cursor, pot_id: str, bal: float, inc: float = 0.0, exp: float = 0.0) -> Dict[str, Any]:
    cur.execute(
        """UPDATE treasury_pots SET current_balance_usd = current_balance_usd + ?, inc_jul_oct_usd = inc_jul_oct_usd + ?,
           exp_jul_oct_usd = exp_jul_oct_usd + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
        (bal, inc, exp, pot_id),
    )
    return {"op": "pot_delta", "id": pot_id, "bal": -bal, "inc": -inc, "exp": -exp}


def _pot_month_add(cur: sqlite3.Cursor, pot_id: str, month: str, inc: float, exp: float) -> None:
    row = cur.execute("SELECT months_json FROM treasury_pots WHERE id = ?", (pot_id,)).fetchone()
    months = json.loads((row["months_json"] if row else None) or "{}")
    m = months.setdefault(month, {"inc": 0.0, "exp": 0.0})
    m["inc"] = round(float(m.get("inc") or 0) + inc, 2)
    m["exp"] = round(float(m.get("exp") or 0) + exp, 2)
    if abs(m["inc"]) < 0.005 and abs(m["exp"]) < 0.005:
        months.pop(month, None)
    cur.execute("UPDATE treasury_pots SET months_json = ? WHERE id = ?", (json.dumps(months), pot_id))


def _apply_undo(cur: sqlite3.Cursor, ops: List[Dict[str, Any]]) -> None:
    for op in reversed(ops):
        kind = op.get("op")
        if kind == "account_delta":
            cur.execute(
                """UPDATE treasury_accounts SET current_balance_native = current_balance_native + ?,
                   reconciled_usd = reconciled_usd + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (op["native"], op["usd"], op["id"]),
            )
        elif kind == "account_set":
            cur.execute(
                """UPDATE treasury_accounts SET current_balance_native = ?, reconciled_usd = ?,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (op["native"], op["usd"], op["id"]),
            )
        elif kind == "pot_delta":
            cur.execute(
                """UPDATE treasury_pots SET current_balance_usd = current_balance_usd + ?,
                   inc_jul_oct_usd = inc_jul_oct_usd + ?, exp_jul_oct_usd = exp_jul_oct_usd + ?,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (op["bal"], op["inc"], op["exp"], op["id"]),
            )
        elif kind == "pot_month":
            _pot_month_add(cur, op["id"], op["month"], op["inc"], op["exp"])
        elif kind == "delete_rows":
            table = op["table"]
            if table not in ("treasury_transactions", "treasury_pot_lines", "treasury_adjustments",
                             "treasury_balance_history", "treasury_trust_amanahs", "treasury_receivables",
                             "treasury_accounts", "treasury_pots"):
                raise HTTPException(status_code=400, detail="Unknown undo step.")
            ids = op.get("ids") or []
            if ids:
                cur.execute(f"DELETE FROM {table} WHERE id IN ({','.join('?' * len(ids))})", ids)
        elif kind == "restore_row":
            table = op["table"]
            if table not in ("treasury_trust_amanahs", "treasury_receivables", "treasury_accounts", "treasury_pots"):
                raise HTTPException(status_code=400, detail="Unknown undo step.")
            cols = op["values"]
            sets = ", ".join(f"{k} = ?" for k in cols)
            cur.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*cols.values(), op["id"]])
        else:
            raise HTTPException(status_code=400, detail=f"Unknown undo step '{kind}'.")


# ------------------------------------------------------------------------------------------------ request models
class InternalTransferRequest(BaseModel):
    company_id: str = "rethink"
    from_account_id: str
    to_account_id: str
    from_amount_native: float
    to_amount_native: float
    tx_date: Optional[str] = None
    fee_usd: float = 0.0
    category: Optional[str] = None
    description: Optional[str] = None
    person: Optional[str] = None
    submit_for_approval: bool = False


class BankTransactionRequest(BaseModel):
    company_id: str = "rethink"
    account_id: str
    tx_date: Optional[str] = None
    kind: str  # 'income' | 'expense'
    amount_native: float
    pot_id: Optional[str] = None
    category: Optional[str] = None
    description: str
    zakat_status: Optional[str] = None
    person: Optional[str] = None


class ReallocationMove(BaseModel):
    from_pot_id: str
    to_pot_id: str
    amount_usd: float
    reason: Optional[str] = None


class PotReallocationRequest(BaseModel):
    company_id: str = "rethink"
    from_pot_id: str
    to_pot_id: str
    amount_usd: float
    effective_date: Optional[str] = None
    reason: str
    created_by: Optional[str] = None
    approved_by: Optional[str] = None
    confirm_wall_override: bool = False
    submit_for_approval: bool = False


class ReallocationPlanRequest(BaseModel):
    company_id: str = "rethink"
    moves: List[ReallocationMove] = Field(..., min_length=1, max_length=100)
    effective_date: Optional[str] = None
    reason: str = ""
    approved_by: Optional[str] = None
    confirm_wall_override: bool = False
    submit_for_approval: bool = False


class SubmitApprovalRequest(BaseModel):
    company_id: str = "rethink"
    transfer_type: str  # 'account_transfer' | 'pot_reallocation' | 'expense'
    title: str
    amount_usd: float = 0.0
    amount_native: float = 0.0
    currency: str = "USD"
    source_ref: Optional[str] = None
    source_name: Optional[str] = None
    destination_ref: Optional[str] = None
    destination_name: Optional[str] = None
    details: Dict[str, Any] = {}
    requested_by: Optional[str] = None


class ReviewApprovalRequest(BaseModel):
    action: str  # 'APPROVE' | 'REJECT'
    reason: Optional[str] = None
    company_id: str = "rethink"


class BalanceUpdateRequest(BaseModel):
    company_id: str = "rethink"
    new_balance_native: float
    as_of: Optional[str] = None
    note: Optional[str] = None


class AccountCreateRequest(BaseModel):
    company_id: str = "rethink"
    name: str
    name_ar: Optional[str] = None
    group_name: str
    account_type: str = "bank"
    currency: str = "USD"
    holder: Optional[str] = None
    supervisor: Optional[str] = None
    opening_balance_native: float = 0.0
    reconciled_fx_rate: Optional[float] = None
    note: Optional[str] = None


class AccountUpdateRequest(BaseModel):
    company_id: str = "rethink"
    name: Optional[str] = None
    name_ar: Optional[str] = None
    holder: Optional[str] = None
    supervisor: Optional[str] = None
    note: Optional[str] = None
    is_active: Optional[bool] = None


class TrustRequest(BaseModel):
    company_id: str = "rethink"
    holder: str
    account_id: Optional[str] = None
    native_amount: float
    currency: str = "USD"
    note: Optional[str] = None
    as_of_date: Optional[str] = None
    record_deposit: bool = False


class ReceivableRequest(BaseModel):
    company_id: str = "rethink"
    name: str
    category: str = "other"
    native_amount: float
    currency: str = "USD"
    is_included_in_net_position: bool = True
    note: Optional[str] = None
    as_of_date: Optional[str] = None


class PotCreateRequest(BaseModel):
    company_id: str = "rethink"
    name: str
    code: Optional[str] = None
    portfolio: str = "General"
    program: Optional[str] = None
    country: str = "Unallocated"
    pool: str = "Non-Zakat"
    is_overhead: bool = False


class ConfirmResolveRequest(BaseModel):
    company_id: str = "rethink"
    resolution: str


class ReverseRequest(BaseModel):
    company_id: str = "rethink"
    reason: Optional[str] = None


# ------------------------------------------------------------------------------------------------ read endpoints
@router.get("/fx/rates")
def get_treasury_fx_rates(
    fx_mode: str = Query("live", pattern="^(live|reconciled)$"),
    month: Optional[str] = None,
    company_id: str = Query("rethink"),
):
    """Return active live or reconciled FX rates relative to USD and GBP."""
    _company(company_id)
    return get_fx_rates(mode=fx_mode, month=month)


def _trust_usd(t: Dict[str, Any], fx_mode: str, rates: Dict[str, float]) -> float:
    if fx_mode == "live":
        return convert_amount(float(t["native_amount"] or t["usd_amount"]), t["currency"] or "USD", "USD", rates)
    return float(t["usd_amount"] or 0.0)


@router.get("/overview")
def get_treasury_overview(
    fx_mode: str = Query("live", pattern="^(live|reconciled)$"),
    display_currency: str = Query("USD", pattern="^(USD|GBP)$"),
    month: Optional[str] = None,
    company_id: str = Query("rethink"),
):
    """Cash − held for others + owed to us = fund balances, with the tie-out, regional split and monthly flow."""
    comp = _company(company_id)
    fx_info = get_fx_rates(mode=fx_mode, month=month)
    rates: Dict[str, float] = fx_info["rates"]  # type: ignore[assignment]
    disp = normalize_currency(display_currency)
    cv = lambda usd: round(convert_amount(usd, "USD", disp, rates), 2)  # noqa: E731

    conn = _get_conn()
    try:
        cur = conn.cursor()
        accounts = [dict(r) for r in cur.execute(
            "SELECT * FROM treasury_accounts WHERE is_active = 1 AND company_id = ?", (comp,)).fetchall()]
        trust_items = [dict(r) for r in cur.execute(
            "SELECT * FROM treasury_trust_amanahs WHERE COALESCE(is_active, 1) = 1 ORDER BY usd_amount DESC").fetchall()]
        rec_items = [dict(r) for r in cur.execute(
            """SELECT * FROM treasury_receivables WHERE COALESCE(is_active, 1) = 1
               ORDER BY is_included_in_net_position DESC, usd_amount DESC""").fetchall()]
        pots = [dict(r) for r in cur.execute(
            "SELECT country, current_balance_usd, months_json FROM treasury_pots WHERE COALESCE(is_active, 1) = 1 AND company_id = ?",
            (comp,)).fetchall()]
        pots_total_usd = sum(float(p["current_balance_usd"] or 0) for p in pots)

        gross_cash_usd = 0.0
        by_region_map: Dict[str, Dict[str, Any]] = {}
        by_type_map: Dict[str, Dict[str, Any]] = {}
        by_currency_map: Dict[str, Dict[str, Any]] = {}
        for acc in accounts:
            bal_nat = float(acc["current_balance_native"] or 0.0)
            usd_val = convert_amount(bal_nat, acc["currency"], "USD", rates) if fx_mode == "live" else float(acc["reconciled_usd"] or 0.0)
            gross_cash_usd += usd_val
            for key, mp, label in ((acc["group_name"], by_region_map, "region"), (acc["account_type"], by_type_map, "account_type"),
                                   (normalize_currency(acc["currency"]), by_currency_map, "currency")):
                if key not in mp:
                    mp[key] = {label: key, "accounts_count": 0, "usd_total": 0.0, "native_total": 0.0}
                mp[key]["accounts_count"] += 1
                mp[key]["usd_total"] += usd_val
                mp[key]["native_total"] += bal_nat
        for mp in (by_region_map, by_type_map, by_currency_map):
            for v in mp.values():
                v["usd_total"] = round(v["usd_total"], 2)
                v["native_total"] = round(v["native_total"], 2)
                v["display_total"] = cv(v["usd_total"])

        trust_total_usd = 0.0
        for t in trust_items:
            t_usd = _trust_usd(t, fx_mode, rates)
            t["active_usd"] = round(t_usd, 2)
            t["active_display"] = cv(t_usd)
            trust_total_usd += t_usd

        receivables_total_usd = 0.0
        accrued_liabilities_usd = 0.0
        for r in rec_items:
            r_usd = _trust_usd(r, fx_mode, rates)
            r["active_usd"] = round(r_usd, 2)
            r["active_display"] = cv(r_usd)
            if r["is_included_in_net_position"]:
                receivables_total_usd += r_usd
            else:
                accrued_liabilities_usd += r_usd

        net_cash_usd = gross_cash_usd - trust_total_usd
        net_position_usd = net_cash_usd + receivables_total_usd
        gap_usd = round(pots_total_usd - net_position_usd, 2)

        # Fund-position flow (what the pots report: ledger + Syria field reports + approved corrections)
        fund_months: Dict[str, Dict[str, float]] = {}
        fund_by_country: Dict[str, float] = {}
        for p in pots:
            fund_by_country[p["country"] or "Unallocated"] = fund_by_country.get(p["country"] or "Unallocated", 0.0) + float(p["current_balance_usd"] or 0)
            for m, v in json.loads(p["months_json"] or "{}").items():
                fm = fund_months.setdefault(m, {"inc": 0.0, "exp": 0.0})
                fm["inc"] += float(v.get("inc") or 0)
                fm["exp"] += float(v.get("exp") or 0)
        fund_flow = [{
            "month": m, "income_usd": round(v["inc"], 2), "expense_usd": round(v["exp"], 2),
            "net_usd": round(v["inc"] - v["exp"], 2),
            "income_display": cv(v["inc"]), "expense_display": cv(v["exp"]), "net_display": cv(v["inc"] - v["exp"]),
        } for m, v in sorted(fund_months.items())]

        # Raw bank/cash ledger flow (counted rows only)
        monthly_rows = cur.execute(
            f"""SELECT tx_month,
                   SUM(CASE WHEN kind = 'income' THEN amount_usd ELSE 0 END) AS income_usd,
                   SUM(CASE WHEN kind = 'expense' THEN ABS(amount_usd) ELSE 0 END) AS expense_usd,
                   SUM(CASE WHEN kind = 'internal' THEN ABS(amount_usd) ELSE 0 END) AS internal_usd,
                   COUNT(*) AS tx_count
            FROM treasury_transactions
            WHERE tx_month LIKE '20__-__' AND {_COUNTED_SQL}
            GROUP BY tx_month ORDER BY tx_month ASC"""
        ).fetchall()
        monthly_flow = [{
            "month": mr["tx_month"],
            "income_usd": round(float(mr["income_usd"] or 0.0), 2),
            "expense_usd": round(float(mr["expense_usd"] or 0.0), 2),
            "internal_usd": round(float(mr["internal_usd"] or 0.0), 2),
            "income_display": cv(float(mr["income_usd"] or 0.0)),
            "expense_display": cv(float(mr["expense_usd"] or 0.0)),
            "internal_display": cv(float(mr["internal_usd"] or 0.0)),
            "tx_count": mr["tx_count"],
        } for mr in monthly_rows]

        open_confirm = cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(usd), 0) FROM treasury_confirm_items WHERE status = 'open' AND company_id = ?",
            (comp,)).fetchone()
        excluded = cur.execute(
            f"SELECT SUM({_DUP_SQL}), SUM({_OUTSIDE_SQL} AND NOT {_DUP_SQL}) FROM treasury_transactions").fetchone()
        last_source = cur.execute("SELECT MAX(last_date) FROM treasury_sources WHERE company_id = ? AND last_date <= ?",
                                  (comp, _today())).fetchone()[0]
        future_rows = cur.execute("SELECT COUNT(*) FROM treasury_transactions WHERE tx_date > ?", (_today(),)).fetchone()[0]

        return {
            "fx": {**fx_info, "display_currency": disp, "gbp_usd": rates.get("GBP", 1.33)},
            "equation": {
                "gross_cash_usd": round(gross_cash_usd, 2), "gross_cash_display": cv(gross_cash_usd),
                "trust_amanahs_usd": round(trust_total_usd, 2), "trust_amanahs_display": cv(trust_total_usd),
                "net_charity_cash_usd": round(net_cash_usd, 2), "net_charity_cash_display": cv(net_cash_usd),
                "receivables_usd": round(receivables_total_usd, 2), "receivables_display": cv(receivables_total_usd),
                "net_fund_position_usd": round(net_position_usd, 2), "net_fund_position_display": cv(net_position_usd),
                "pots_total_balance_usd": round(pots_total_usd, 2), "pots_total_balance_display": cv(pots_total_usd),
                "accrued_liabilities_usd": round(accrued_liabilities_usd, 2), "accrued_liabilities_display": cv(accrued_liabilities_usd),
                "gap_usd": gap_usd, "gap_display": cv(gap_usd), "ties": abs(gap_usd) < 1.0,
                "trust_items": trust_items,
                "receivables_items": rec_items,
            },
            "by_region": sorted(by_region_map.values(), key=lambda x: x["usd_total"], reverse=True),
            "by_type": sorted(by_type_map.values(), key=lambda x: x["usd_total"], reverse=True),
            "by_currency": sorted(by_currency_map.values(), key=lambda x: x["usd_total"], reverse=True),
            "fund_by_country": sorted(
                [{"country": k, "usd_total": round(v, 2), "display_total": cv(v)} for k, v in fund_by_country.items()],
                key=lambda x: x["usd_total"], reverse=True),
            "fund_flow": fund_flow,
            "monthly_flow": monthly_flow,
            "health": {
                "open_confirm_count": open_confirm[0], "open_confirm_usd": round(open_confirm[1] or 0, 2),
                "duplicate_rows": int(excluded[0] or 0), "before_period_rows": int(excluded[1] or 0),
                "latest_source_date": last_source, "future_dated_rows": future_rows,
            },
        }
    finally:
        conn.close()


def _accounts_query(cur, comp, region, account_type, search, include_inactive=False):
    sql = "SELECT * FROM treasury_accounts WHERE company_id = ?"
    params: List[Any] = [comp]
    if not include_inactive:
        sql += " AND is_active = 1"
    if region and region != "ALL":
        sql += " AND group_name = ?"
        params.append(region)
    if account_type and account_type != "ALL":
        sql += " AND account_type = ?"
        params.append(account_type)
    if search:
        q = f"%{search.strip().lower()}%"
        sql += " AND (LOWER(name) LIKE ? OR LOWER(COALESCE(name_ar, '')) LIKE ? OR LOWER(COALESCE(holder, '')) LIKE ? OR LOWER(currency) LIKE ?)"
        params.extend([q, q, q, q])
    sql += " ORDER BY reconciled_usd DESC"
    return [dict(r) for r in cur.execute(sql, params).fetchall()]


@router.get("/accounts")
def get_treasury_accounts(
    fx_mode: str = Query("live", pattern="^(live|reconciled)$"),
    display_currency: str = Query("USD", pattern="^(USD|GBP)$"),
    region: Optional[str] = None,
    account_type: Optional[str] = None,
    month: Optional[str] = None,
    search: Optional[str] = None,
    include_inactive: bool = False,
    company_id: str = Query("rethink"),
):
    """All bank accounts, safes, crypto wallets and platform balances with FX conversions and activity counts."""
    comp = _company(company_id)
    fx_info = get_fx_rates(mode=fx_mode, month=month)
    rates: Dict[str, float] = fx_info["rates"]  # type: ignore[assignment]
    disp = normalize_currency(display_currency)

    conn = _get_conn()
    try:
        cur = conn.cursor()
        accounts = _accounts_query(cur, comp, region, account_type, search, include_inactive)

        tx_where = f"WHERE {_COUNTED_SQL}"
        tx_params: List[Any] = []
        if month and month != "ALL":
            tx_where += " AND tx_month = ?"
            tx_params.append(month)
        stats_rows = cur.execute(
            f"""SELECT account_id, COUNT(*) AS tx_count,
                   SUM(CASE WHEN amount_native > 0 THEN amount_native ELSE 0 END) AS inflow_native,
                   SUM(CASE WHEN amount_native < 0 THEN ABS(amount_native) ELSE 0 END) AS outflow_native,
                   SUM(CASE WHEN kind = 'internal' THEN 1 ELSE 0 END) AS internal_count,
                   SUM(CASE WHEN kind = 'income' THEN 1 ELSE 0 END) AS income_count,
                   SUM(CASE WHEN kind = 'expense' THEN 1 ELSE 0 END) AS expense_count,
                   MAX(tx_date) AS last_tx_date
            FROM treasury_transactions {tx_where} GROUP BY account_id""",
            tx_params,
        ).fetchall()
        stats_by_acc = {r["account_id"]: dict(r) for r in stats_rows}
        excluded_by_acc = {r[0]: r[1] for r in cur.execute(
            f"SELECT account_id, COUNT(*) FROM treasury_transactions WHERE {_OUTSIDE_SQL} GROUP BY account_id").fetchall()}
        source_by_acc = {r[0]: r[1] for r in cur.execute(
            "SELECT account_id, MAX(last_date) FROM treasury_sources WHERE account_id IS NOT NULL GROUP BY account_id").fetchall()}
        last_update = {r[0]: r[1] for r in cur.execute(
            "SELECT account_id, MAX(as_of) FROM treasury_balance_history GROUP BY account_id").fetchall()}

        amanahs_by_acc: Dict[str, List[Dict[str, Any]]] = {}
        for ar in cur.execute(
                "SELECT account_id, holder, usd_amount FROM treasury_trust_amanahs WHERE COALESCE(is_active, 1) = 1").fetchall():
            if ar["account_id"]:
                amanahs_by_acc.setdefault(ar["account_id"], []).append({"holder": ar["holder"], "usd_amount": ar["usd_amount"]})

        enriched = []
        for acc in accounts:
            bal_nat = float(acc["current_balance_native"] or 0.0)
            usd_val = convert_amount(bal_nat, acc["currency"], "USD", rates) if fx_mode == "live" else float(acc["reconciled_usd"] or 0.0)
            st = stats_by_acc.get(acc["id"], {})
            acc_amanahs = amanahs_by_acc.get(acc["id"], [])
            amanah_usd_val = round(sum(a["usd_amount"] for a in acc_amanahs), 2)
            in_nat = round(float(st.get("inflow_native") or 0.0), 2)
            out_nat = round(float(st.get("outflow_native") or 0.0), 2)
            in_usd = round(convert_amount(in_nat, acc["currency"], "USD", rates), 2)
            out_usd = round(convert_amount(out_nat, acc["currency"], "USD", rates), 2)
            enriched.append({
                **acc,
                "active_usd": round(usd_val, 2),
                "active_display": round(convert_amount(usd_val, "USD", disp, rates), 2),
                "active_fx_to_usd": rates.get(normalize_currency(acc["currency"]), 1.0),
                "tx_count": st.get("tx_count", 0),
                "excluded_count": excluded_by_acc.get(acc["id"], 0),
                "inflow_native": in_nat,
                "outflow_native": out_nat,
                "inflow_usd": in_usd,
                "outflow_usd": out_usd,
                "inflow_display": round(convert_amount(in_usd, "USD", disp, rates), 2),
                "outflow_display": round(convert_amount(out_usd, "USD", disp, rates), 2),
                "internal_count": st.get("internal_count", 0),
                "income_count": st.get("income_count", 0),
                "expense_count": st.get("expense_count", 0),
                "last_tx_date": st.get("last_tx_date"),
                "source_last_date": source_by_acc.get(acc["id"]),
                "balance_as_of": last_update.get(acc["id"]) or "2026-10-31",
                "amanahs": acc_amanahs,
                "amanah_usd": amanah_usd_val,
                "amanah_display": round(convert_amount(amanah_usd_val, "USD", disp, rates), 2),
            })
        return {"fx": {**fx_info, "display_currency": disp}, "count": len(enriched), "accounts": enriched}
    finally:
        conn.close()


@router.get("/accounts/export")
def export_treasury_accounts(
    fx_mode: str = Query("reconciled", pattern="^(live|reconciled)$"),
    region: Optional[str] = None,
    account_type: Optional[str] = None,
    search: Optional[str] = None,
    company_id: str = Query("rethink"),
):
    """CSV of the accounts list as filtered on screen."""
    data = get_treasury_accounts(fx_mode=fx_mode, display_currency="USD", region=region, account_type=account_type,
                                 month=None, search=search, company_id=company_id)
    rows = [{**a, "type": a["account_type"], "region": a["group_name"]} for a in data["accounts"]]
    return _csv(rows, ["account_number", "name", "name_ar", "region", "type", "currency", "current_balance_native",
                       "active_fx_to_usd", "active_usd", "holder", "supervisor", "amanah_usd", "balance_as_of",
                       "source_last_date", "tx_count", "note"], "treasury_accounts")


def _statement_where(account_id, kind, month, search, status):
    where = ["t.account_id = ?"]
    params: List[Any] = [account_id]
    if kind and kind != "ALL":
        where.append("t.kind = ?")
        params.append(kind)
    if month and month != "ALL":
        where.append("t.tx_month = ?")
        params.append(month)
    if search:
        q = f"%{search.strip().lower()}%"
        where.append("(LOWER(COALESCE(t.description, '')) LIKE ? OR LOWER(COALESCE(t.category, '')) LIKE ? OR LOWER(COALESCE(t.allocation, '')) LIKE ?)")
        params.extend([q, q, q])
    st = (status or "counted").lower()
    if st == "counted":
        where.append(_COUNTED_SQL.replace("flags", "t.flags"))
    elif st == "duplicate":
        where.append(_DUP_SQL.replace("flags", "t.flags"))
    elif st == "before_period":
        where.append(f"({_OUTSIDE_SQL} AND NOT {_DUP_SQL})".replace("flags", "t.flags"))
    return " AND ".join(where), params


@router.get("/accounts/{account_id}/transactions")
def get_account_transactions(
    account_id: str,
    kind: Optional[str] = None,
    month: Optional[str] = None,
    search: Optional[str] = None,
    status: str = Query("counted", pattern="^(counted|duplicate|before_period|all)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=200),
    company_id: str = Query("rethink"),
):
    """Statement for one account. By default only rows the fund position counts; duplicates and pre-July rows on request."""
    comp = _company(company_id)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        acc = cur.execute("SELECT * FROM treasury_accounts WHERE id = ? AND company_id = ?", (account_id, comp)).fetchone()
        if not acc:
            raise HTTPException(status_code=404, detail="Treasury account not found")
        where_sql, params = _statement_where(account_id, kind, month, search, status)
        total = cur.execute(f"SELECT COUNT(*) FROM treasury_transactions t WHERE {where_sql}", params).fetchone()[0]
        totals_row = cur.execute(
            f"""SELECT COALESCE(SUM(CASE WHEN amount_native > 0 THEN amount_native ELSE 0 END), 0) AS total_in,
                   COALESCE(SUM(CASE WHEN amount_native < 0 THEN ABS(amount_native) ELSE 0 END), 0) AS total_out,
                   COALESCE(SUM(CASE WHEN kind = 'internal' THEN 1 ELSE 0 END), 0) AS internal_count,
                   COALESCE(SUM(CASE WHEN kind = 'income' THEN 1 ELSE 0 END), 0) AS income_count,
                   COALESCE(SUM(CASE WHEN kind = 'expense' THEN 1 ELSE 0 END), 0) AS expense_count
            FROM treasury_transactions t WHERE {where_sql}""", params).fetchone()
        status_counts = {r[0]: r[1] for r in cur.execute(
            f"SELECT {_STATUS_SQL} AS st, COUNT(*) FROM treasury_transactions WHERE account_id = ? GROUP BY st",
            (account_id,)).fetchall()}
        rows = cur.execute(
            f"""SELECT t.*, cp.name AS counterparty_name, {_STATUS_SQL.replace('flags', 't.flags')} AS status
                FROM treasury_transactions t LEFT JOIN treasury_accounts cp ON cp.id = t.counterparty_account_id
                WHERE {where_sql} ORDER BY t.tx_date DESC, t.id DESC LIMIT ? OFFSET ?""",
            [*params, page_size, (page - 1) * page_size]).fetchall()
        history = [dict(r) for r in cur.execute(
            "SELECT * FROM treasury_balance_history WHERE account_id = ? ORDER BY as_of DESC, id DESC LIMIT 12",
            (account_id,)).fetchall()]
        monthly = [dict(r) for r in cur.execute(
            f"""SELECT tx_month AS month,
                   ROUND(SUM(CASE WHEN amount_native > 0 THEN amount_native ELSE 0 END), 2) AS inflow_native,
                   ROUND(SUM(CASE WHEN amount_native < 0 THEN -amount_native ELSE 0 END), 2) AS outflow_native
                FROM treasury_transactions WHERE account_id = ? AND {_COUNTED_SQL} AND tx_month LIKE '20__-__'
                GROUP BY tx_month ORDER BY tx_month""", (account_id,)).fetchall()]
        return {
            "account": dict(acc),
            "summary": dict(totals_row) if totals_row else {},
            "status_counts": {"counted": status_counts.get("counted", 0), "duplicate": status_counts.get("duplicate", 0),
                              "before_period": status_counts.get("before_period", 0)},
            "monthly": monthly,
            "balance_history": history,
            "total": total, "page": page, "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "transactions": [dict(r) for r in rows],
        }
    finally:
        conn.close()


@router.get("/accounts/{account_id}/transactions/export")
def export_account_transactions(
    account_id: str,
    kind: Optional[str] = None,
    month: Optional[str] = None,
    search: Optional[str] = None,
    status: str = Query("counted", pattern="^(counted|duplicate|before_period|all)$"),
    company_id: str = Query("rethink"),
):
    comp = _company(company_id)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        acc = cur.execute("SELECT name FROM treasury_accounts WHERE id = ? AND company_id = ?", (account_id, comp)).fetchone()
        if not acc:
            raise HTTPException(status_code=404, detail="Treasury account not found")
        where_sql, params = _statement_where(account_id, kind, month, search, status)
        rows = [dict(r) for r in cur.execute(
            f"""SELECT t.*, cp.name AS counterparty_name, {_STATUS_SQL.replace('flags', 't.flags')} AS status
                FROM treasury_transactions t LEFT JOIN treasury_accounts cp ON cp.id = t.counterparty_account_id
                WHERE {where_sql} ORDER BY t.tx_date, t.id""", params).fetchall()]
        return _csv(rows, ["tx_date", "description", "currency", "amount_native", "amount_usd", "fx_rate", "kind", "category",
                           "allocation", "zakat_status", "country", "counterparty_name", "person", "status", "flags",
                           "source_file", "source_tab", "source_row"], f"statement_{acc['name']}")
    finally:
        conn.close()


@router.get("/internal-transfers")
def get_internal_transfers(
    month: Optional[str] = None,
    account_id: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=200),
    company_id: str = Query("rethink"),
):
    """Internal transfers across accounts (counted rows only) with the routing aliases."""
    _company(company_id)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        where = ["t.kind = 'internal'", _COUNTED_SQL.replace("flags", "t.flags")]
        params: List[Any] = []
        if month and month != "ALL":
            where.append("t.tx_month = ?")
            params.append(month)
        if account_id and account_id != "ALL":
            where.append("(t.account_id = ? OR t.counterparty_account_id = ?)")
            params.extend([account_id, account_id])
        if search:
            q = f"%{search.strip().lower()}%"
            where.append("(LOWER(COALESCE(t.description, '')) LIKE ? OR LOWER(COALESCE(t.category, '')) LIKE ? OR LOWER(COALESCE(src.name, '')) LIKE ? OR LOWER(COALESCE(dst.name, '')) LIKE ?)")
            params.extend([q, q, q, q])
        where_sql = " AND ".join(where)
        joins = """FROM treasury_transactions t
            LEFT JOIN treasury_accounts src ON src.id = t.account_id
            LEFT JOIN treasury_accounts dst ON dst.id = t.counterparty_account_id"""
        total = cur.execute(f"SELECT COUNT(*) {joins} WHERE {where_sql}", params).fetchone()[0]
        rows = cur.execute(
            f"""SELECT t.*, src.name AS account_name, src.currency AS account_currency,
                   dst.name AS counterparty_name, dst.currency AS counterparty_currency {joins}
                WHERE {where_sql} ORDER BY t.tx_date DESC, t.id DESC LIMIT ? OFFSET ?""",
            [*params, page_size, (page - 1) * page_size]).fetchall()
        top_routes = cur.execute(
            f"""SELECT COALESCE(src.name, t.account_id) AS source_name,
                   COALESCE(dst.name, NULLIF(t.category, ''), 'FX / Unmapped') AS target_name,
                   COUNT(*) AS tx_count, ROUND(SUM(ABS(t.amount_usd)), 2) AS total_usd {joins}
                WHERE t.kind = 'internal' AND {_COUNTED_SQL.replace('flags', 't.flags')}
                GROUP BY source_name, target_name ORDER BY total_usd DESC LIMIT 12""").fetchall()
        aliases = cur.execute(
            """SELECT a.alias, a.account_id, a.transfer_type, acc.name AS account_name, acc.currency
               FROM treasury_account_aliases a LEFT JOIN treasury_accounts acc ON acc.id = a.account_id
               ORDER BY a.transfer_type, a.alias""").fetchall()
        return {
            "total": total, "page": page, "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "transfers": [dict(r) for r in rows],
            "top_routes": [dict(r) for r in top_routes],
            "aliases": [dict(r) for r in aliases],
        }
    finally:
        conn.close()


def _execute_internal_transfer_data(cur: sqlite3.Cursor, comp: str, data: Dict[str, Any], actor: str) -> Dict[str, Any]:
    from_account_id = data["from_account_id"]
    to_account_id = data["to_account_id"]
    from_amount_native = float(data["from_amount_native"])
    to_amount_native = float(data["to_amount_native"])
    fee_usd = float(data.get("fee_usd") or 0.0)
    category = data.get("category")
    description = data.get("description")
    tx_date = _clean_date(data.get("tx_date"))
    tx_month = tx_date[:7]
    group_id = f"tr_{uuid.uuid4().hex[:12]}"

    src = cur.execute("SELECT * FROM treasury_accounts WHERE id = ? AND company_id = ?", (from_account_id, comp)).fetchone()
    dst = cur.execute("SELECT * FROM treasury_accounts WHERE id = ? AND company_id = ?", (to_account_id, comp)).fetchone()
    if not src or not dst:
        raise HTTPException(status_code=404, detail="Account not found.")

    src_usd = round(from_amount_native * float(src["reconciled_fx_rate"] or 1), 2)
    dst_usd = round(to_amount_native * float(dst["reconciled_fx_rate"] or 1), 2)
    realized_rate = round(to_amount_native / from_amount_native, 6)
    desc = description or f"Internal transfer: {src['name']} → {dst['name']} (rate {realized_rate})"
    ins = """INSERT INTO treasury_transactions (tx_date, tx_month, account_id, source_file, source_tab, description,
             currency, amount_native, amount_usd, fx_rate, kind, category, counterparty_account_id, person, linked_transfer_group)
             VALUES (?, ?, ?, 'CRM Manual', 'Treasury Transfer', ?, ?, ?, ?, ?, 'internal', ?, ?, ?, ?)"""
    cur.execute(ins, (tx_date, tx_month, src["id"], desc, src["currency"], -from_amount_native, -src_usd,
                      float(src["reconciled_fx_rate"] or 1), category or dst["name"], dst["id"], actor, group_id))
    tx_ids = [cur.lastrowid]
    cur.execute(ins, (tx_date, tx_month, dst["id"], desc, dst["currency"], to_amount_native, dst_usd,
                      float(dst["reconciled_fx_rate"] or 1), category or src["name"], src["id"], actor, group_id))
    tx_ids.append(cur.lastrowid)
    undo: List[Dict[str, Any]] = [{"op": "delete_rows", "table": "treasury_transactions", "ids": tx_ids}]
    undo.append(_account_delta(cur, src, -from_amount_native))
    undo.append(_account_delta(cur, dst, to_amount_native))

    fee_pot_id = None
    if fee_usd > 0:
        fee_pot = cur.execute(
            """SELECT id FROM treasury_pots WHERE LOWER(name) LIKE '%transfer fees%' AND country = 'Unallocated'
               AND pool = 'Non-Zakat' AND company_id = ? LIMIT 1""", (comp,)).fetchone()
        if fee_pot:
            fee_pot_id = fee_pot["id"]
            cur.execute(
                """INSERT INTO treasury_pot_lines (pot_id, line_date, line_month, source, description, amount_usd, line_kind, created_by)
                   VALUES (?, ?, ?, 'CRM Transfer Fee', ?, ?, 'manual', ?)""",
                (fee_pot_id, tx_date, tx_month, f"Fee / FX loss: {desc}", -fee_usd, actor))
            undo.append({"op": "delete_rows", "table": "treasury_pot_lines", "ids": [cur.lastrowid]})
            undo.append(_pot_delta(cur, fee_pot_id, -fee_usd, exp=fee_usd))
            _pot_month_add(cur, fee_pot_id, tx_month, 0, fee_usd)
            undo.append({"op": "pot_month", "id": fee_pot_id, "month": tx_month, "inc": 0, "exp": -fee_usd})

    act = _log(cur, actor, "transfer", f"{src['name']} → {dst['name']}: {src['currency']} {from_amount_native:,.2f} → "
               f"{dst['currency']} {to_amount_native:,.2f}" + (f" (fee ${fee_usd:,.2f})" if fee_usd else ""),
               src_usd, data, undo, comp)
    return {"status": "ok", "transfer_group": group_id, "activity_id": act, "realized_rate": realized_rate,
            "from_usd": src_usd, "to_usd": dst_usd, "fx_difference_usd": round(src_usd - dst_usd, 2),
            "fee_booked_to": fee_pot_id}


# ------------------------------------------------------------------------------------------------ account writes
@router.post("/transfers")
def create_internal_transfer(payload: InternalTransferRequest, request: Request):
    """Record a paired internal transfer between two accounts, or stage for approval if not pre-authorized."""
    comp = _company(payload.company_id)
    if payload.from_account_id == payload.to_account_id:
        raise HTTPException(status_code=400, detail="Source and destination accounts must be different.")
    if payload.from_amount_native <= 0 or payload.to_amount_native <= 0:
        raise HTTPException(status_code=400, detail="Transfer amounts must be positive.")
    if payload.fee_usd < 0:
        raise HTTPException(status_code=400, detail="The fee cannot be negative.")

    actor = _actor(request, payload.person)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        src = cur.execute("SELECT * FROM treasury_accounts WHERE id = ? AND company_id = ?", (payload.from_account_id, comp)).fetchone()
        dst = cur.execute("SELECT * FROM treasury_accounts WHERE id = ? AND company_id = ?", (payload.to_account_id, comp)).fetchone()
        if not src or not dst:
            raise HTTPException(status_code=404, detail="Account not found.")

        src_usd = round(payload.from_amount_native * float(src["reconciled_fx_rate"] or 1), 2)
        can_approve = _can_approve_transfers(request, comp)

        if payload.submit_for_approval or not can_approve:
            approval_id = f"APV-{datetime.utcnow():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
            title = f"{src['name']} → {dst['name']}: {src['currency']} {payload.from_amount_native:,.2f} → {dst['currency']} {payload.to_amount_native:,.2f}"
            cur.execute("""
                INSERT INTO treasury_approvals (id, company_id, transfer_type, title, status, amount_usd,
                    amount_native, currency, source_ref, source_name, destination_ref, destination_name,
                    details_json, requested_by)
                VALUES (?, ?, 'account_transfer', ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                approval_id, comp, title, src_usd, payload.from_amount_native, src["currency"],
                src["id"], src["name"], dst["id"], dst["name"],
                json.dumps(payload.model_dump(), default=str), actor
            ))
            conn.commit()
            return {
                "status": "pending_approval",
                "approval_id": approval_id,
                "message": f"Transfer of {src['currency']} {payload.from_amount_native:,.2f} submitted for manager approval."
            }

        res = _execute_internal_transfer_data(cur, comp, payload.model_dump(), actor)
        conn.commit()
        return res
    finally:
        conn.close()


@router.post("/transactions")
def create_bank_transaction(payload: BankTransactionRequest, request: Request):
    """Log income or an expense on an account and, when a pot is chosen, on that pot too."""
    comp = _company(payload.company_id)
    if payload.kind not in ("income", "expense"):
        raise HTTPException(status_code=400, detail="Transaction kind must be 'income' or 'expense'.")
    if payload.amount_native <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero.")
    if not (payload.description or "").strip():
        raise HTTPException(status_code=400, detail="Add a description.")

    tx_date = _clean_date(payload.tx_date)
    tx_month = tx_date[:7]
    actor = _actor(request, payload.person)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        acc = cur.execute("SELECT * FROM treasury_accounts WHERE id = ? AND company_id = ?", (payload.account_id, comp)).fetchone()
        if not acc:
            raise HTTPException(status_code=404, detail="Account not found.")
        signed_nat = payload.amount_native if payload.kind == "income" else -payload.amount_native
        rate = float(acc["reconciled_fx_rate"] or 1.0)
        usd_amt = round(signed_nat * rate, 2)

        pot = None
        if payload.pot_id:
            pot = cur.execute("SELECT * FROM treasury_pots WHERE id = ? AND company_id = ?", (payload.pot_id, comp)).fetchone()
            if not pot:
                raise HTTPException(status_code=404, detail="Target pot not found.")
        cur.execute(
            """INSERT INTO treasury_transactions (tx_date, tx_month, account_id, source_file, source_tab, description,
               currency, amount_native, amount_usd, fx_rate, kind, category, allocation, pot_id, zakat_status, country, person)
               VALUES (?, ?, ?, 'CRM Manual', 'Treasury Entry', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tx_date, tx_month, acc["id"], payload.description, acc["currency"], signed_nat, usd_amt, rate, payload.kind,
             payload.category or (pot["name"] if pot else ""), pot["name"] if pot else "", payload.pot_id,
             pot["pool"] if pot else (payload.zakat_status or ""), pot["country"] if pot else "", actor))
        undo: List[Dict[str, Any]] = [{"op": "delete_rows", "table": "treasury_transactions", "ids": [cur.lastrowid]}]
        undo.append(_account_delta(cur, acc, signed_nat))

        if pot:
            cur.execute(
                """INSERT INTO treasury_pot_lines (pot_id, line_date, line_month, source, description, native_note, amount_usd, line_kind, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', ?)""",
                (pot["id"], tx_date, tx_month, f"Bank: {acc['name']}", payload.description,
                 f"{acc['currency']} {signed_nat:,.2f}", usd_amt, actor))
            undo.append({"op": "delete_rows", "table": "treasury_pot_lines", "ids": [cur.lastrowid]})
            if payload.kind == "income":
                undo.append(_pot_delta(cur, pot["id"], abs(usd_amt), inc=abs(usd_amt)))
                _pot_month_add(cur, pot["id"], tx_month, abs(usd_amt), 0)
                undo.append({"op": "pot_month", "id": pot["id"], "month": tx_month, "inc": -abs(usd_amt), "exp": 0})
            else:
                undo.append(_pot_delta(cur, pot["id"], -abs(usd_amt), exp=abs(usd_amt)))
                _pot_month_add(cur, pot["id"], tx_month, 0, abs(usd_amt))
                undo.append({"op": "pot_month", "id": pot["id"], "month": tx_month, "inc": 0, "exp": -abs(usd_amt)})

        act = _log(cur, actor, payload.kind, f"{payload.kind.title()} on {acc['name']}: {acc['currency']} {payload.amount_native:,.2f}"
                   + (f" → {pot['name']} ({pot['country']} · {pot['pool']})" if pot else "") + f" — {payload.description}",
                   usd_amt, payload.model_dump(), undo, comp)
        conn.commit()
        return {"status": "ok", "activity_id": act, "amount_usd": usd_amt, "amount_native": signed_nat}
    finally:
        conn.close()


@router.post("/accounts/{account_id}/balance")
def update_account_balance(account_id: str, payload: BalanceUpdateRequest, request: Request):
    """Month-end balance from the cash position sheet / bank statement. The difference is recorded, not hidden."""
    comp = _company(payload.company_id)
    as_of = _clean_date(payload.as_of)
    actor = _actor(request)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        acc = cur.execute("SELECT * FROM treasury_accounts WHERE id = ? AND company_id = ?", (account_id, comp)).fetchone()
        if not acc:
            raise HTTPException(status_code=404, detail="Account not found.")
        old_nat = float(acc["current_balance_native"] or 0)
        rate = float(acc["reconciled_fx_rate"] or 1)
        new_nat = float(payload.new_balance_native)
        cur.execute(
            """UPDATE treasury_accounts SET current_balance_native = ?, reconciled_usd = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""", (new_nat, round(new_nat * rate, 2), account_id))
        cur.execute(
            """INSERT INTO treasury_balance_history (account_id, as_of, old_native, new_native, fx_rate, note, actor)
               VALUES (?, ?, ?, ?, ?, ?, ?)""", (account_id, as_of, old_nat, new_nat, rate, payload.note, actor))
        hist_id = cur.lastrowid
        undo = [{"op": "account_set", "id": account_id, "native": old_nat, "usd": float(acc["reconciled_usd"] or 0)},
                {"op": "delete_rows", "table": "treasury_balance_history", "ids": [hist_id]}]
        diff = new_nat - old_nat
        act = _log(cur, actor, "balance_update",
                   f"{acc['name']} balance at {as_of}: {acc['currency']} {old_nat:,.2f} → {new_nat:,.2f} (Δ {diff:+,.2f})",
                   diff * rate, payload.model_dump(), undo, comp)
        cur.execute("UPDATE treasury_balance_history SET activity_id = ? WHERE id = ?", (act, hist_id))
        conn.commit()
        return {"status": "ok", "activity_id": act, "difference_native": round(diff, 2), "difference_usd": round(diff * rate, 2)}
    finally:
        conn.close()


@router.post("/accounts")
def create_treasury_account(payload: AccountCreateRequest, request: Request):
    """Open a new bank account, cash box, wallet or platform balance."""
    comp = _company(payload.company_id)
    name = payload.name.strip()
    if not name or not payload.group_name.strip():
        raise HTTPException(status_code=400, detail="Name and region are required.")
    cur_code = normalize_currency(payload.currency)
    rate = payload.reconciled_fx_rate or get_fx_rates(mode="reconciled")["rates"].get(cur_code)  # type: ignore[union-attr]
    if not rate:
        raise HTTPException(status_code=400, detail=f"No period rate for {cur_code}; enter the rate to USD.")
    actor = _actor(request)
    acc_id = re.sub(r"[^a-z0-9]+", "_", f"{payload.group_name[:2]}_{name}".lower()).strip("_")[:40] + "_" + uuid.uuid4().hex[:4]
    conn = _get_conn()
    try:
        cur = conn.cursor()
        num = (cur.execute("SELECT MAX(account_number) FROM treasury_accounts").fetchone()[0] or 0) + 1
        cur.execute(
            """INSERT INTO treasury_accounts (id, account_number, name, name_ar, group_name, account_type, holder, supervisor,
               currency, opening_balance_native, current_balance_native, reconciled_usd, reconciled_fx_rate, note, company_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (acc_id, num, name, payload.name_ar, payload.group_name.strip(), payload.account_type, payload.holder,
             payload.supervisor, cur_code, payload.opening_balance_native, payload.opening_balance_native,
             round(payload.opening_balance_native * rate, 2), rate, payload.note or "", comp))
        act = _log(cur, actor, "account_create", f"New account {name} ({cur_code} {payload.opening_balance_native:,.2f})",
                   payload.opening_balance_native * rate, payload.model_dump(),
                   [{"op": "delete_rows", "table": "treasury_accounts", "ids": [acc_id]}], comp)
        conn.commit()
        return {"status": "ok", "id": acc_id, "activity_id": act}
    finally:
        conn.close()


@router.patch("/accounts/{account_id}")
def update_treasury_account(account_id: str, payload: AccountUpdateRequest, request: Request):
    """Edit an account's details or close it (closing needs a zero balance)."""
    comp = _company(payload.company_id)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        acc = cur.execute("SELECT * FROM treasury_accounts WHERE id = ? AND company_id = ?", (account_id, comp)).fetchone()
        if not acc:
            raise HTTPException(status_code=404, detail="Account not found.")
        changes = {k: v for k, v in payload.model_dump(exclude={"company_id"}).items() if v is not None}
        if "is_active" in changes:
            changes["is_active"] = 1 if changes["is_active"] else 0
            if not changes["is_active"] and abs(float(acc["current_balance_native"] or 0)) > 0.005:
                raise HTTPException(status_code=400, detail="Move the balance out (or set it to 0) before closing the account.")
        if not changes:
            return {"status": "ok", "changed": 0}
        before = {k: acc[k] for k in changes}
        cur.execute(f"UPDATE treasury_accounts SET {', '.join(f'{k} = ?' for k in changes)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    [*changes.values(), account_id])
        act = _log(cur, _actor(request), "account_edit", f"{acc['name']}: " + ", ".join(f"{k} → {v}" for k, v in changes.items()),
                   0, payload.model_dump(), [{"op": "restore_row", "table": "treasury_accounts", "id": account_id, "values": before}], comp)
        conn.commit()
        return {"status": "ok", "changed": len(changes), "activity_id": act}
    finally:
        conn.close()


# ------------------------------------------------------------------------------------------------ trusts & receivables
@router.post("/trusts")
def create_trust(payload: TrustRequest, request: Request):
    """Money we hold for someone else (amanah). It is deducted from spendable cash.
       Optionally records a cash deposit entry if new physical money was received."""
    comp = _company(payload.company_id)
    cur_code = normalize_currency(payload.currency)
    usd = round(convert_amount(payload.native_amount, cur_code, "USD", get_fx_rates(mode="reconciled")["rates"]), 2)  # type: ignore[arg-type]
    conn = _get_conn()
    try:
        cur = conn.cursor()
        acc = None
        if payload.account_id:
            acc = cur.execute("SELECT * FROM treasury_accounts WHERE id = ?", (payload.account_id,)).fetchone()
            if not acc:
                raise HTTPException(status_code=404, detail="Account not found.")
        actor = _actor(request)
        clean_date = _clean_date(payload.as_of_date) or _today()
        cur.execute(
            """INSERT INTO treasury_trust_amanahs (holder, account_id, native_amount, currency, usd_amount, note, as_of_date, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (payload.holder.strip(), payload.account_id, payload.native_amount, cur_code, usd, payload.note,
             clean_date, actor))
        tid = cur.lastrowid
        undo: List[Dict[str, Any]] = [{"op": "delete_rows", "table": "treasury_trust_amanahs", "ids": [tid]}]

        tx_id = None
        if payload.record_deposit and acc:
            rate = float(acc["reconciled_fx_rate"] or 1.0)
            usd_amt = round(payload.native_amount * rate, 2)
            desc = f"Amanah received from {payload.holder.strip()}" + (f" ({payload.note})" if payload.note else "")
            cur.execute(
                """INSERT INTO treasury_transactions (tx_date, tx_month, account_id, source_file, source_tab, description,
                   currency, amount_native, amount_usd, fx_rate, kind, category, allocation, pot_id, zakat_status, country, person)
                   VALUES (?, ?, ?, 'CRM Manual', 'Amanah Deposit', ?, ?, ?, ?, ?, 'income', 'amanah_deposit', 'Amanah', NULL, 'Non-Zakat', ?, ?)""",
                (clean_date, clean_date[:7], acc["id"], desc, acc["currency"], payload.native_amount, usd_amt, rate,
                 acc["group_name"] or "", actor))
            tx_id = cur.lastrowid
            undo.append({"op": "delete_rows", "table": "treasury_transactions", "ids": [tx_id]})
            undo.append(_account_delta(cur, acc, payload.native_amount))

        act = _log(cur, actor, "trust_create",
                   f"Held for {payload.holder}: {cur_code} {payload.native_amount:,.2f}" + (" (cash deposited)" if payload.record_deposit else ""),
                   usd, payload.model_dump(), undo, comp)
        conn.commit()
        return {"status": "ok", "id": tid, "usd_amount": usd, "activity_id": act, "transaction_id": tx_id}
    finally:
        conn.close()


@router.patch("/trusts/{trust_id}")
def update_trust(trust_id: int, payload: TrustRequest, request: Request):
    comp = _company(payload.company_id)
    cur_code = normalize_currency(payload.currency)
    usd = round(convert_amount(payload.native_amount, cur_code, "USD", get_fx_rates(mode="reconciled")["rates"]), 2)  # type: ignore[arg-type]
    conn = _get_conn()
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT * FROM treasury_trust_amanahs WHERE id = ?", (trust_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Trust not found.")
        new = {"holder": payload.holder.strip(), "account_id": payload.account_id, "native_amount": payload.native_amount,
               "currency": cur_code, "usd_amount": usd, "note": payload.note, "as_of_date": _clean_date(payload.as_of_date)}
        before = {k: row[k] for k in new}
        cur.execute(f"UPDATE treasury_trust_amanahs SET {', '.join(f'{k} = ?' for k in new)} WHERE id = ?", [*new.values(), trust_id])
        act = _log(cur, _actor(request), "trust_edit", f"Held for {payload.holder}: {row['currency']} {row['native_amount'] or 0:,.2f} → "
                   f"{cur_code} {payload.native_amount:,.2f}", usd - float(row["usd_amount"] or 0), payload.model_dump(),
                   [{"op": "restore_row", "table": "treasury_trust_amanahs", "id": trust_id, "values": before}], comp)
        conn.commit()
        return {"status": "ok", "activity_id": act}
    finally:
        conn.close()


@router.post("/trusts/{trust_id}/settle")
def settle_trust(trust_id: int, request: Request, company_id: str = Query("rethink"), record_withdrawal: bool = Query(False)):
    """Mark an amanah as handed over; it leaves the 'held for others' total (kept for the record).
       Optionally records a cash withdrawal if money physically left the account."""
    comp = _company(company_id)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT * FROM treasury_trust_amanahs WHERE id = ?", (trust_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Trust not found.")
        today_date = _today()
        cur.execute("UPDATE treasury_trust_amanahs SET is_active = 0, settled_at = ? WHERE id = ?", (today_date, trust_id))
        undo: List[Dict[str, Any]] = [{"op": "restore_row", "table": "treasury_trust_amanahs", "id": trust_id,
                                       "values": {"is_active": 1, "settled_at": None}}]

        actor = _actor(request)
        tx_id = None
        if record_withdrawal and row["account_id"]:
            acc = cur.execute("SELECT * FROM treasury_accounts WHERE id = ?", (row["account_id"],)).fetchone()
            if acc:
                rate = float(acc["reconciled_fx_rate"] or 1.0)
                native_amt = float(row["native_amount"] or 0.0)
                usd_amt = round(native_amt * rate, 2)
                desc = f"Amanah handed over to {row['holder'].strip()}" + (f" ({row['note']})" if row['note'] else "")
                cur.execute(
                    """INSERT INTO treasury_transactions (tx_date, tx_month, account_id, source_file, source_tab, description,
                       currency, amount_native, amount_usd, fx_rate, kind, category, allocation, pot_id, zakat_status, country, person)
                       VALUES (?, ?, ?, 'CRM Manual', 'Amanah Settlement', ?, ?, ?, ?, ?, 'expense', 'amanah_settlement', 'Amanah', NULL, 'Non-Zakat', ?, ?)""",
                    (today_date, today_date[:7], acc["id"], desc, acc["currency"], -native_amt, -usd_amt, rate,
                     acc["group_name"] or "", actor))
                tx_id = cur.lastrowid
                undo.append({"op": "delete_rows", "table": "treasury_transactions", "ids": [tx_id]})
                undo.append(_account_delta(cur, acc, -native_amt))

        act = _log(cur, actor, "trust_settle",
                   f"Amanah for {row['holder']} handed over (${row['usd_amount']:,.2f})" + (" (cash withdrawn)" if record_withdrawal else ""),
                   -float(row["usd_amount"] or 0), {"id": trust_id, "record_withdrawal": record_withdrawal},
                   undo, comp)
        conn.commit()
        return {"status": "ok", "activity_id": act, "transaction_id": tx_id}
    finally:
        conn.close()


@router.post("/receivables")
def create_receivable(payload: ReceivableRequest, request: Request):
    """Money owed to us (or, when excluded from the position, an accrued liability memo)."""
    comp = _company(payload.company_id)
    cur_code = normalize_currency(payload.currency)
    usd = round(convert_amount(payload.native_amount, cur_code, "USD", get_fx_rates(mode="reconciled")["rates"]), 2)  # type: ignore[arg-type]
    rid = "rec_" + re.sub(r"[^a-z0-9]+", "_", payload.name.lower()).strip("_")[:30] + "_" + uuid.uuid4().hex[:4]
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO treasury_receivables (id, name, category, native_amount, currency, usd_amount,
               is_included_in_net_position, note, as_of_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rid, payload.name.strip(), payload.category, payload.native_amount, cur_code, usd,
             1 if payload.is_included_in_net_position else 0, payload.note, _clean_date(payload.as_of_date)))
        act = _log(cur, _actor(request), "receivable_create", f"Owed to us: {payload.name} {cur_code} {payload.native_amount:,.2f}",
                   usd, payload.model_dump(), [{"op": "delete_rows", "table": "treasury_receivables", "ids": [rid]}], comp)
        conn.commit()
        return {"status": "ok", "id": rid, "usd_amount": usd, "activity_id": act}
    finally:
        conn.close()


@router.patch("/receivables/{rec_id}")
def update_receivable(rec_id: str, payload: ReceivableRequest, request: Request):
    comp = _company(payload.company_id)
    cur_code = normalize_currency(payload.currency)
    usd = round(convert_amount(payload.native_amount, cur_code, "USD", get_fx_rates(mode="reconciled")["rates"]), 2)  # type: ignore[arg-type]
    conn = _get_conn()
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT * FROM treasury_receivables WHERE id = ?", (rec_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Receivable not found.")
        new = {"name": payload.name.strip(), "category": payload.category, "native_amount": payload.native_amount,
               "currency": cur_code, "usd_amount": usd, "is_included_in_net_position": 1 if payload.is_included_in_net_position else 0,
               "note": payload.note, "as_of_date": _clean_date(payload.as_of_date)}
        before = {k: row[k] for k in new}
        cur.execute(f"UPDATE treasury_receivables SET {', '.join(f'{k} = ?' for k in new)} WHERE id = ?", [*new.values(), rec_id])
        act = _log(cur, _actor(request), "receivable_edit", f"{payload.name}: {row['currency']} {row['native_amount'] or 0:,.2f} → "
                   f"{cur_code} {payload.native_amount:,.2f}", usd - float(row["usd_amount"] or 0), payload.model_dump(),
                   [{"op": "restore_row", "table": "treasury_receivables", "id": rec_id, "values": before}], comp)
        conn.commit()
        return {"status": "ok", "activity_id": act}
    finally:
        conn.close()


@router.post("/receivables/{rec_id}/settle")
def settle_receivable(rec_id: str, request: Request, company_id: str = Query("rethink")):
    """Mark a receivable as received/cleared (book the cash with a bank entry or balance update)."""
    comp = _company(company_id)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT * FROM treasury_receivables WHERE id = ?", (rec_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Receivable not found.")
        cur.execute("UPDATE treasury_receivables SET is_active = 0 WHERE id = ?", (rec_id,))
        act = _log(cur, _actor(request), "receivable_settle", f"{row['name']} cleared (${row['usd_amount']:,.2f})",
                   -float(row["usd_amount"] or 0), {"id": rec_id},
                   [{"op": "restore_row", "table": "treasury_receivables", "id": rec_id, "values": {"is_active": 1}}], comp)
        conn.commit()
        return {"status": "ok", "activity_id": act}
    finally:
        conn.close()


# ------------------------------------------------------------------------------------------------ pots
@router.get("/pots")
def get_treasury_pots(
    portfolio: Optional[str] = None,
    country: Optional[str] = None,
    pool: Optional[str] = None,
    is_overhead: Optional[str] = None,
    health: Optional[str] = None,
    search: Optional[str] = None,
    display_currency: str = Query("USD", pattern="^(USD|GBP)$"),
    fx_mode: str = Query("reconciled", pattern="^(live|reconciled)$"),
    company_id: str = Query("rethink"),
):
    """All project & office running-cost pots with portfolio summaries and filters."""
    comp = _company(company_id)
    fx_info = get_fx_rates(mode=fx_mode)
    rates: Dict[str, float] = fx_info["rates"]  # type: ignore[assignment]
    disp = normalize_currency(display_currency)
    cv = lambda usd: round(convert_amount(usd, "USD", disp, rates), 2)  # noqa: E731

    conn = _get_conn()
    try:
        cur = conn.cursor()
        all_pots = [dict(r) for r in cur.execute(
            "SELECT * FROM treasury_pots WHERE COALESCE(is_active, 1) = 1 AND company_id = ? ORDER BY ABS(current_balance_usd) DESC",
            (comp,)).fetchall()]

        # Grand totals over all pots for reference
        grand_tot = {"bal": 0.0, "jun": 0.0, "inc": 0.0, "exp": 0.0, "z": 0.0, "nz": 0.0, "prog": 0.0, "ovh": 0.0, "deficit_usd": 0.0}
        for p in all_pots:
            bal = float(p["current_balance_usd"] or 0.0)
            grand_tot["bal"] += bal
            grand_tot["jun"] += float(p["bal_jun_usd"] or 0.0)
            grand_tot["inc"] += float(p["inc_jul_oct_usd"] or 0.0)
            grand_tot["exp"] += float(p["exp_jul_oct_usd"] or 0.0)
            grand_tot["z" if p["pool"] == "Zakat" else "nz"] += bal
            grand_tot["ovh" if p["is_overhead"] else "prog"] += bal
            if bal < -0.01:
                grand_tot["deficit_usd"] += bal

        q = (search or "").strip().lower()

        def matches_filter(p, skip_key=None):
            bal = float(p["current_balance_usd"] or 0.0)
            if skip_key != "portfolio" and portfolio and portfolio != "ALL" and p["portfolio"] != portfolio:
                return False
            if skip_key != "country" and country and country != "ALL" and p["country"] != country:
                return False
            if skip_key != "pool" and pool and pool != "ALL" and p["pool"] != pool:
                return False
            if skip_key != "is_overhead":
                if is_overhead == "1" and not p["is_overhead"]:
                    return False
                if is_overhead == "0" and p["is_overhead"]:
                    return False
            if skip_key != "health":
                if health == "surplus" and bal <= 0.01:
                    return False
                if health == "deficit" and bal >= -0.01:
                    return False
            if skip_key != "search" and q:
                if not any(q in (p[k] or "").lower() for k in ("name", "code", "program", "country", "portfolio")):
                    return False
            return True

        # Portfolios faceted for current active non-portfolio filters
        port_map: Dict[str, Dict[str, Any]] = {}
        for p in all_pots:
            if not matches_filter(p, skip_key="portfolio"):
                continue
            bal = float(p["current_balance_usd"] or 0.0)
            pf = p["portfolio"] or "General"
            pm = port_map.setdefault(pf, {"portfolio": pf, "count": 0, "income_usd": 0.0, "expense_usd": 0.0, "balance_usd": 0.0})
            pm["count"] += 1
            pm["income_usd"] += float(p["inc_jul_oct_usd"] or 0.0)
            pm["expense_usd"] += float(p["exp_jul_oct_usd"] or 0.0)
            pm["balance_usd"] += bal

        # Countries faceted for current active non-country filters
        country_map: Dict[str, Dict[str, Any]] = {}
        for p in all_pots:
            if not matches_filter(p, skip_key="country"):
                continue
            bal = float(p["current_balance_usd"] or 0.0)
            ct = p["country"] or "Unallocated"
            cm = country_map.setdefault(ct, {"country": ct, "count": 0, "balance_usd": 0.0, "zakat_usd": 0.0, "non_zakat_usd": 0.0})
            cm["count"] += 1
            cm["balance_usd"] += bal
            cm["zakat_usd" if p["pool"] == "Zakat" else "non_zakat_usd"] += bal

        for mp in (port_map, country_map):
            for v in mp.values():
                for k in list(v):
                    if k.endswith("_usd"):
                        v[k] = round(v[k], 2)
                v["balance_display"] = cv(v["balance_usd"])

        # Filtered pots matching ALL active filters
        filtered = []
        tot = {"bal": 0.0, "jun": 0.0, "inc": 0.0, "exp": 0.0, "z": 0.0, "nz": 0.0, "prog": 0.0, "ovh": 0.0, "deficit_usd": 0.0}
        surplus_cnt = deficit_cnt = 0

        for p in all_pots:
            if not matches_filter(p):
                continue
            bal = float(p["current_balance_usd"] or 0.0)
            tot["bal"] += bal
            tot["jun"] += float(p["bal_jun_usd"] or 0.0)
            tot["inc"] += float(p["inc_jul_oct_usd"] or 0.0)
            tot["exp"] += float(p["exp_jul_oct_usd"] or 0.0)
            tot["z" if p["pool"] == "Zakat" else "nz"] += bal
            tot["ovh" if p["is_overhead"] else "prog"] += bal
            if bal > 0.01:
                surplus_cnt += 1
            elif bal < -0.01:
                deficit_cnt += 1
                tot["deficit_usd"] += bal

            filtered.append({
                **p,
                "display_balance": cv(bal),
                "display_income": cv(float(p["inc_jul_oct_usd"] or 0.0)),
                "display_expense": cv(float(p["exp_jul_oct_usd"] or 0.0)),
                "months": json.loads(p["months_json"] or "{}"),
            })

        return {
            "display_currency": disp,
            "summary": {
                "total_count": len(all_pots),
                "filtered_count": len(filtered),
                "total_bal_jun_usd": round(tot["jun"], 2),
                "total_bal_jun_display": cv(tot["jun"]),
                "total_inc_usd": round(tot["inc"], 2),
                "total_inc_display": cv(tot["inc"]),
                "total_exp_usd": round(tot["exp"], 2),
                "total_exp_display": cv(tot["exp"]),
                "total_balance_usd": round(tot["bal"], 2),
                "total_balance_display": cv(tot["bal"]),
                "zakat_balance_usd": round(tot["z"], 2),
                "non_zakat_balance_usd": round(tot["nz"], 2),
                "programme_balance_usd": round(tot["prog"], 2),
                "overhead_balance_usd": round(tot["ovh"], 2),
                "surplus_count": surplus_cnt,
                "deficit_count": deficit_cnt,
                "deficit_total_usd": round(tot["deficit_usd"], 2),
                "all_pots_balance_usd": round(grand_tot["bal"], 2),
                "all_pots_balance_display": cv(grand_tot["bal"]),
            },
            "portfolios": sorted(port_map.values(), key=lambda x: abs(x["balance_usd"]), reverse=True),
            "countries": sorted(country_map.values(), key=lambda x: abs(x["balance_usd"]), reverse=True),
            "pots": filtered,
        }
    finally:
        conn.close()


@router.get("/pots/export")
def export_treasury_pots(
    portfolio: Optional[str] = None, country: Optional[str] = None, pool: Optional[str] = None,
    is_overhead: Optional[str] = None, health: Optional[str] = None, search: Optional[str] = None,
    company_id: str = Query("rethink"),
):
    data = get_treasury_pots(portfolio=portfolio, country=country, pool=pool, is_overhead=is_overhead, health=health,
                             search=search, display_currency="USD", fx_mode="reconciled", company_id=company_id)
    return _csv(data["pots"], ["code", "fund_num", "name", "portfolio", "program", "country", "pool", "is_overhead",
                               "bal_jun_usd", "inc_jul_oct_usd", "exp_jul_oct_usd", "current_balance_usd"], "project_pots")


@router.get("/pots/{pot_id}")
def get_pot_detail(pot_id: str, company_id: str = Query("rethink")):
    """Full pot breakdown, monthly series, itemised lines and the corrections that touched it."""
    comp = _company(company_id)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        pot = cur.execute("SELECT * FROM treasury_pots WHERE id = ? AND company_id = ?", (pot_id, comp)).fetchone()
        if not pot:
            raise HTTPException(status_code=404, detail="Pot not found")
        lines = [dict(r) for r in cur.execute(
            "SELECT * FROM treasury_pot_lines WHERE pot_id = ? ORDER BY line_date DESC, id DESC", (pot_id,)).fetchall()]
        adjustments = [dict(r) for r in cur.execute(
            """SELECT * FROM treasury_adjustments WHERE company_id = ? AND (
                 (from_fund = ? AND from_country = ? AND from_pool = ?) OR (to_fund = ? AND to_country = ? AND to_pool = ?))
               ORDER BY adj_date DESC, id DESC""",
            (comp, pot["name"], pot["country"], pot["pool"], pot["name"], pot["country"], pot["pool"])).fetchall()]
        p_dict = dict(pot)
        p_dict["months"] = json.loads(p_dict.get("months_json") or "{}")
        p_dict["notes"] = json.loads(p_dict.get("notes_json") or "[]")
        return {"pot": p_dict, "lines": lines, "adjustments": adjustments}
    finally:
        conn.close()


@router.post("/pots")
def create_pot(payload: PotCreateRequest, request: Request):
    """Open a new fund / project pot (starts at zero)."""
    comp = _company(payload.company_id)
    if payload.pool not in ("Zakat", "Non-Zakat"):
        raise HTTPException(status_code=400, detail="Pool must be Zakat or Non-Zakat.")
    conn = _get_conn()
    try:
        cur = conn.cursor()
        if cur.execute("SELECT 1 FROM treasury_pots WHERE LOWER(name) = LOWER(?) AND country = ? AND pool = ? AND company_id = ? AND COALESCE(is_active,1)=1",
                       (payload.name.strip(), payload.country, payload.pool, comp)).fetchone():
            raise HTTPException(status_code=409, detail="A pot with this name, country and pool already exists.")
        n = cur.execute("SELECT COUNT(*) FROM treasury_pots").fetchone()[0] + 1
        pid = f"pot_{n:03d}_" + re.sub(r"[^a-z0-9]+", "_", f"{payload.code or ''}_{payload.name}_{payload.country}_{payload.pool}".lower()).strip("_")[:44]
        cur.execute(
            """INSERT INTO treasury_pots (id, code, name, portfolio, program, country, pool, is_overhead, months_json, notes_json, company_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', '[]', ?)""",
            (pid, payload.code or "", payload.name.strip(), payload.portfolio, payload.program or payload.portfolio,
             payload.country, payload.pool, 1 if payload.is_overhead else 0, comp))
        act = _log(cur, _actor(request), "pot_create", f"New pot {payload.name} ({payload.country} · {payload.pool})", 0,
                   payload.model_dump(), [{"op": "delete_rows", "table": "treasury_pots", "ids": [pid]}], comp)
        conn.commit()
        return {"status": "ok", "id": pid, "activity_id": act}
    finally:
        conn.close()


def _walls(src: sqlite3.Row, dst: sqlite3.Row) -> List[str]:
    """The zakat wall and the country wall (WEEKLY_PROCESS.md) - crossing either needs an approver."""
    w = []
    if src["pool"] == "Zakat" and dst["pool"] != "Zakat":
        w.append(f"Zakat wall: zakat money from '{src['name']}' into non-zakat '{dst['name']}'.")
    if src["pool"] == "Zakat" and (dst["country"] or "").lower() in ZAKAT_RESTRICTED_COUNTRIES:
        w.append(f"Zakat destination: {dst['country']} is not a zakat-eligible destination.")
    if (src["country"] or "") != (dst["country"] or "") and (src["country"] or "Unallocated") != "Unallocated":
        w.append(f"Country wall: {src['country']} → {dst['country']}.")
    return w


def _plan_check(cur: sqlite3.Cursor, comp: str, moves: List[ReallocationMove]) -> Dict[str, Any]:
    pots: Dict[str, Dict[str, Any]] = {}
    lines = []
    for i, mv in enumerate(moves, start=1):
        if mv.amount_usd <= 0:
            raise HTTPException(status_code=400, detail=f"Move {i}: amount must be positive.")
        if mv.from_pot_id == mv.to_pot_id:
            raise HTTPException(status_code=400, detail=f"Move {i}: source and destination are the same pot.")
        for pid in (mv.from_pot_id, mv.to_pot_id):
            if pid not in pots:
                r = cur.execute("SELECT * FROM treasury_pots WHERE id = ? AND company_id = ?", (pid, comp)).fetchone()
                if not r:
                    raise HTTPException(status_code=404, detail=f"Move {i}: pot not found.")
                pots[pid] = {"row": r, "before": float(r["current_balance_usd"] or 0), "after": float(r["current_balance_usd"] or 0)}
        src, dst = pots[mv.from_pot_id], pots[mv.to_pot_id]
        src["after"] -= mv.amount_usd
        dst["after"] += mv.amount_usd
        walls = _walls(src["row"], dst["row"])
        lines.append({"n": i, "from_pot_id": mv.from_pot_id, "to_pot_id": mv.to_pot_id, "amount_usd": round(mv.amount_usd, 2),
                      "from_name": src["row"]["name"], "from_country": src["row"]["country"], "from_pool": src["row"]["pool"],
                      "to_name": dst["row"]["name"], "to_country": dst["row"]["country"], "to_pool": dst["row"]["pool"],
                      "walls": walls, "reason": mv.reason or ""})
    impact = [{"pot_id": k, "name": v["row"]["name"], "country": v["row"]["country"], "pool": v["row"]["pool"],
               "before_usd": round(v["before"], 2), "after_usd": round(v["after"], 2),
               "goes_negative": v["after"] < -0.01 <= v["before"]} for k, v in pots.items()]
    return {"lines": lines, "impact": impact, "total_usd": round(sum(m.amount_usd for m in moves), 2),
            "wall_count": sum(1 for ln in lines if ln["walls"]), "pots": pots}


@router.post("/pots/reallocate/preview")
def preview_reallocation_plan(payload: ReallocationPlanRequest):
    """Dry run: what each move does to each pot and which walls it crosses. Nothing is saved."""
    comp = _company(payload.company_id)
    conn = _get_conn()
    try:
        res = _plan_check(conn.cursor(), comp, payload.moves)
        res.pop("pots")
        return res
    finally:
        conn.close()


def _apply_plan(cur, comp, payload: ReallocationPlanRequest, actor: str) -> Dict[str, Any]:
    chk = _plan_check(cur, comp, payload.moves)
    wall_lines = [ln for ln in chk["lines"] if ln["walls"]]
    if wall_lines and not payload.confirm_wall_override:
        raise HTTPException(status_code=409, detail={
            "message": "Governance wall confirmation required.",
            "warnings": [w for ln in wall_lines for w in ln["walls"]]})
    if wall_lines and not (payload.approved_by or "").strip():
        raise HTTPException(status_code=400, detail="Name who approved crossing the wall (e.g. Osman / HS / Board).")
    eff_date = _clean_date(payload.effective_date)
    eff_month = eff_date[:7]
    undo: List[Dict[str, Any]] = []
    line_ids: List[int] = []
    adj_ids: List[int] = []
    for ln in chk["lines"]:
        src, dst = chk["pots"][ln["from_pot_id"]]["row"], chk["pots"][ln["to_pot_id"]]["row"]
        amt = ln["amount_usd"]
        reason = ln["reason"] or payload.reason
        tag = " [WALL OVERRIDE: " + (payload.approved_by or "") + "]" if ln["walls"] else ""
        cur.execute(
            """INSERT INTO treasury_pot_lines (pot_id, line_date, line_month, source, description, amount_usd, line_kind, created_by)
               VALUES (?, ?, ?, 'CRM Reallocation', ?, ?, 'adj', ?)""",
            (src["id"], eff_date, eff_month, f"→ {dst['name']} ({dst['country']} · {dst['pool']}): {reason}{tag}", -amt, actor))
        line_ids.append(cur.lastrowid)
        cur.execute(
            """INSERT INTO treasury_pot_lines (pot_id, line_date, line_month, source, description, amount_usd, line_kind, created_by)
               VALUES (?, ?, ?, 'CRM Reallocation', ?, ?, 'adj', ?)""",
            (dst["id"], eff_date, eff_month, f"← {src['name']} ({src['country']} · {src['pool']}): {reason}{tag}", amt, actor))
        line_ids.append(cur.lastrowid)
        undo.append(_pot_delta(cur, src["id"], -amt, exp=amt))
        undo.append(_pot_delta(cur, dst["id"], amt, inc=amt))
        _pot_month_add(cur, src["id"], eff_month, 0, amt)
        _pot_month_add(cur, dst["id"], eff_month, amt, 0)
        undo.append({"op": "pot_month", "id": src["id"], "month": eff_month, "inc": 0, "exp": -amt})
        undo.append({"op": "pot_month", "id": dst["id"], "month": eff_month, "inc": -amt, "exp": 0})
        cur.execute(
            """INSERT INTO treasury_adjustments (adj_date, from_fund, from_country, from_pool, to_fund, to_country, to_pool,
               usd, adj_type, approved_by, note, applied_to, source, company_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reallocation', ?, ?, ?, 'crm', ?)""",
            (eff_date, src["name"], src["country"], src["pool"], dst["name"], dst["country"], dst["pool"], amt,
             (payload.approved_by or actor), reason + tag, eff_month, comp))
        adj_ids.append(cur.lastrowid)
    undo.append({"op": "delete_rows", "table": "treasury_pot_lines", "ids": line_ids})
    undo.append({"op": "delete_rows", "table": "treasury_adjustments", "ids": adj_ids})
    n = len(chk["lines"])
    first = chk["lines"][0]
    summary = (f"{first['from_name']} → {first['to_name']}" if n == 1 else f"Reallocation plan: {n} moves") + \
              f" · ${chk['total_usd']:,.2f}" + (f" · {len(wall_lines)} wall crossing(s) approved by {payload.approved_by}" if wall_lines else "")
    act = _log(cur, actor, "reallocation", summary, chk["total_usd"], payload.model_dump(), undo, comp)
    cur.execute(f"UPDATE treasury_adjustments SET activity_id = ? WHERE id IN ({','.join('?' * len(adj_ids))})", [act, *adj_ids])
    return {"status": "ok", "activity_id": act, "moves": n, "total_usd": chk["total_usd"],
            "warnings": [w for ln in wall_lines for w in ln["walls"]]}


@router.post("/pots/reallocate/batch")
def apply_reallocation_plan(payload: ReallocationPlanRequest, request: Request):
    """Apply a whole reallocation plan at once, or stage for approval if not pre-authorized."""
    comp = _company(payload.company_id)
    actor = _actor(request)
    can_approve = _can_approve_transfers(request, comp)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        chk = _plan_check(cur, comp, payload.moves)
        if payload.submit_for_approval or not can_approve:
            approval_id = f"APV-{datetime.utcnow():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
            moves_cnt = len(payload.moves)
            title = f"Pot Reallocation Plan ({moves_cnt} moves) · ${chk['total_usd']:,.2f}"
            first = chk["lines"][0] if chk["lines"] else None
            src_name = first["from_name"] if first else "Multiple Pots"
            dst_name = first["to_name"] if first else "Multiple Pots"
            cur.execute("""
                INSERT INTO treasury_approvals (id, company_id, transfer_type, title, status, amount_usd,
                    amount_native, currency, source_ref, source_name, destination_ref, destination_name,
                    details_json, requested_by)
                VALUES (?, ?, 'pot_reallocation', ?, 'PENDING', ?, ?, 'USD', ?, ?, ?, ?, ?, ?)
            """, (
                approval_id, comp, title, chk["total_usd"], chk["total_usd"],
                payload.moves[0].from_pot_id if payload.moves else "", src_name,
                payload.moves[0].to_pot_id if payload.moves else "", dst_name,
                json.dumps(payload.model_dump(), default=str), actor
            ))
            conn.commit()
            return {
                "status": "pending_approval",
                "approval_id": approval_id,
                "message": f"Reallocation plan (${chk['total_usd']:,.2f}) submitted for manager approval."
            }

        res = _apply_plan(cur, comp, payload, actor)
        conn.commit()
        return res
    finally:
        conn.close()


@router.post("/pots/reallocate")
def reallocate_pot_funds(payload: PotReallocationRequest, request: Request):
    """Move money or correct an attribution between two pots, with the zakat and country walls."""
    plan = ReallocationPlanRequest(
        company_id=payload.company_id,
        moves=[ReallocationMove(from_pot_id=payload.from_pot_id, to_pot_id=payload.to_pot_id, amount_usd=payload.amount_usd,
                                reason=payload.reason)],
        effective_date=payload.effective_date, reason=payload.reason,
        approved_by=payload.approved_by or payload.created_by, confirm_wall_override=payload.confirm_wall_override,
        submit_for_approval=payload.submit_for_approval)
    return apply_reallocation_plan(plan, request)


# ------------------------------------------------------------------------------------------------ approvals workflow
@router.get("/approvals")
def get_treasury_approvals(
    company_id: str = Query("rethink"),
    status: str = Query("ALL"),
    transfer_type: str = Query("ALL"),
    search: Optional[str] = Query(None),
):
    """List approval requests for account transfers, pot reallocations, and outgoing expenses."""
    comp = _company(company_id)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        where = ["company_id = ?"]
        params: List[Any] = [comp]
        if status and status.upper() != "ALL":
            where.append("UPPER(status) = ?")
            params.append(status.upper())
        if transfer_type and transfer_type.lower() != "all":
            where.append("transfer_type = ?")
            params.append(transfer_type.lower())
        if search and search.strip():
            s = f"%{search.strip().lower()}%"
            where.append("(LOWER(id) LIKE ? OR LOWER(title) LIKE ? OR LOWER(source_name) LIKE ? OR LOWER(destination_name) LIKE ? OR LOWER(requested_by) LIKE ?)")
            params.extend([s, s, s, s, s])

        where_sql = " AND ".join(where)
        rows = cur.execute(f"""
            SELECT * FROM treasury_approvals
            WHERE {where_sql}
            ORDER BY requested_at DESC
        """, params).fetchall()

        items = []
        for r in rows:
            d = dict(r)
            try:
                d["details"] = json.loads(d.get("details_json") or "{}")
            except Exception:
                d["details"] = {}
            try:
                d["execution_result"] = json.loads(d.get("execution_result_json") or "{}")
            except Exception:
                d["execution_result"] = {}
            items.append(d)

        # Include pending expense requests if filter permits
        if transfer_type in ("ALL", "expense", "all"):
            exp_where = ["company_id = ?"]
            exp_params: List[Any] = [comp]
            if status and status.upper() == "PENDING":
                exp_where.append("status = 'PENDING_APPROVAL'")
            elif status and status.upper() == "APPROVED":
                exp_where.append("status = 'APPROVED'")
            elif status and status.upper() == "REJECTED":
                exp_where.append("status = 'REJECTED'")
            if search and search.strip():
                s = f"%{search.strip().lower()}%"
                exp_where.append("(LOWER(id) LIKE ? OR LOWER(title) LIKE ? OR LOWER(code) LIKE ? OR LOWER(vendor) LIKE ? OR LOWER(requested_by) LIKE ?)")
                exp_params.extend([s, s, s, s, s])

            try:
                exp_rows = cur.execute(f"""
                    SELECT id, code, title, vendor, amount, payment_date, status, requested_by, reviewed_by, review_notes, created_at
                    FROM expense_requests
                    WHERE {" AND ".join(exp_where)}
                    ORDER BY created_at DESC
                """, exp_params).fetchall()

                for er in exp_rows:
                    items.append({
                        "id": er["id"],
                        "company_id": comp,
                        "transfer_type": "expense",
                        "title": f"Outgoing Expense: {er['title']} ({er['code']})",
                        "status": "PENDING" if er["status"] == "PENDING_APPROVAL" else er["status"],
                        "amount_usd": round(float(er["amount"] or 0) * 1.33, 2),
                        "amount_native": float(er["amount"] or 0),
                        "currency": "GBP",
                        "source_ref": er["code"],
                        "source_name": f"Project {er['code']}",
                        "destination_ref": er["vendor"],
                        "destination_name": er["vendor"] or "Vendor",
                        "details": {"code": er["code"], "vendor": er["vendor"], "payment_date": er["payment_date"]},
                        "requested_by": er["requested_by"],
                        "requested_at": er["created_at"],
                        "reviewed_by": er["reviewed_by"],
                        "rejection_reason": er["review_notes"],
                    })
            except Exception:
                pass

        # Sort combined items by requested_at descending
        items.sort(key=lambda x: str(x.get("requested_at") or ""), reverse=True)

        cnt_pending = cur.execute("SELECT COUNT(*) FROM treasury_approvals WHERE company_id = ? AND status = 'PENDING'", (comp,)).fetchone()[0]
        cnt_approved = cur.execute("SELECT COUNT(*) FROM treasury_approvals WHERE company_id = ? AND status = 'APPROVED'", (comp,)).fetchone()[0]
        cnt_rejected = cur.execute("SELECT COUNT(*) FROM treasury_approvals WHERE company_id = ? AND status = 'REJECTED'", (comp,)).fetchone()[0]

        try:
            exp_pending = cur.execute("SELECT COUNT(*) FROM expense_requests WHERE company_id = ? AND status = 'PENDING_APPROVAL'", (comp,)).fetchone()[0]
            cnt_pending += exp_pending
        except Exception:
            pass

        return {
            "approvals": items,
            "counts": {
                "pending": cnt_pending,
                "approved": cnt_approved,
                "rejected": cnt_rejected,
                "total": cnt_pending + cnt_approved + cnt_rejected,
            }
        }
    finally:
        conn.close()


@router.post("/approvals/submit")
def submit_transfer_approval(payload: SubmitApprovalRequest, request: Request):
    """Explicitly submit any transfer for approval."""
    comp = _company(payload.company_id)
    actor = _actor(request, payload.requested_by)
    approval_id = f"APV-{datetime.utcnow():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO treasury_approvals (id, company_id, transfer_type, title, status, amount_usd,
                amount_native, currency, source_ref, source_name, destination_ref, destination_name,
                details_json, requested_by)
            VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            approval_id, comp, payload.transfer_type, payload.title, payload.amount_usd,
            payload.amount_native, payload.currency, payload.source_ref, payload.source_name,
            payload.destination_ref, payload.destination_name,
            json.dumps(payload.details, default=str), actor
        ))
        conn.commit()
        return {"status": "ok", "approval_id": approval_id, "message": "Transfer submitted for approval."}
    finally:
        conn.close()


@router.post("/approvals/{approval_id}/review")
def review_transfer_approval(approval_id: str, payload: ReviewApprovalRequest, request: Request):
    """Approve or reject a pending transfer (requires expenses.transfers_approve or expenses.approve)."""
    comp = _company(payload.company_id)
    actor = _actor(request)
    act_upper = payload.action.strip().upper()
    if act_upper not in ("APPROVE", "REJECT"):
        raise HTTPException(status_code=400, detail="Action must be APPROVE or REJECT.")

    conn = _get_conn()
    try:
        cur = conn.cursor()

        # Check if it's an expense request
        if approval_id.startswith("EXP-"):
            row = cur.execute("SELECT * FROM expense_requests WHERE id = ? AND company_id = ?", (approval_id, comp)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Expense request not found.")
            new_st = "APPROVED" if act_upper == "APPROVE" else "REJECTED"
            cur.execute("""
                UPDATE expense_requests SET status = ?, reviewed_by = ?, review_notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_st, actor, payload.reason or "", approval_id))
            conn.commit()
            return {"status": "ok", "action": act_upper, "approval_id": approval_id, "message": f"Expense {new_st.lower()} successfully."}

        # Otherwise it's a treasury approval
        row = cur.execute("SELECT * FROM treasury_approvals WHERE id = ? AND company_id = ?", (approval_id, comp)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Approval request not found.")
        if row["status"] != "PENDING":
            raise HTTPException(status_code=400, detail=f"Request is already {row['status']}.")

        details = json.loads(row["details_json"] or "{}")
        exec_res = {}

        if act_upper == "APPROVE":
            ttype = row["transfer_type"]
            if ttype == "account_transfer":
                exec_res = _execute_internal_transfer_data(cur, comp, details, actor)
            elif ttype == "pot_reallocation":
                plan_req = ReallocationPlanRequest(**details)
                exec_res = _apply_plan(cur, comp, plan_req, actor)
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported transfer type '{ttype}'.")

            cur.execute("""
                UPDATE treasury_approvals
                SET status = 'APPROVED', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP,
                    execution_result_json = ?
                WHERE id = ?
            """, (actor, json.dumps(exec_res, default=str), approval_id))
            conn.commit()
            return {"status": "ok", "action": "APPROVED", "approval_id": approval_id, "execution": exec_res, "message": "Transfer approved and executed."}

        else: # REJECT
            cur.execute("""
                UPDATE treasury_approvals
                SET status = 'REJECTED', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP,
                    rejection_reason = ?
                WHERE id = ?
            """, (actor, payload.reason or "Rejected by manager", approval_id))
            conn.commit()
            return {"status": "ok", "action": "REJECTED", "approval_id": approval_id, "message": "Transfer rejected."}

    finally:
        conn.close()


# ------------------------------------------------------------------------------------------------ fund-position workflow
@router.get("/adjustments")
def get_adjustments(
    adj_type: Optional[str] = None,
    search: Optional[str] = None,
    source: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=500),
    company_id: str = Query("rethink"),
):
    """Corrections register: every approved correction from the fund-position close plus reallocations made here."""
    comp = _company(company_id)
    where = ["company_id = ?"]
    params: List[Any] = [comp]
    if adj_type and adj_type != "ALL":
        where.append("adj_type = ?")
        params.append(adj_type)
    if source and source != "ALL":
        where.append("source = ?")
        params.append(source)
    if date_from:
        where.append("adj_date >= ?")
        params.append(date_from)
    if date_to:
        where.append("adj_date <= ?")
        params.append(date_to)
    if search:
        q = f"%{search.strip().lower()}%"
        where.append("(LOWER(COALESCE(from_fund,'')) LIKE ? OR LOWER(COALESCE(to_fund,'')) LIKE ? OR LOWER(COALESCE(note,'')) LIKE ? OR LOWER(COALESCE(approved_by,'')) LIKE ?)")
        params.extend([q, q, q, q])
    w = " AND ".join(where)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        total, total_usd = cur.execute(f"SELECT COUNT(*), COALESCE(SUM(usd),0) FROM treasury_adjustments WHERE {w}", params).fetchone()
        rows = [dict(r) for r in cur.execute(
            f"SELECT * FROM treasury_adjustments WHERE {w} ORDER BY adj_date DESC, id DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size]).fetchall()]
        types = [dict(r) for r in cur.execute(
            "SELECT adj_type, COUNT(*) AS n, ROUND(SUM(usd),2) AS usd FROM treasury_adjustments WHERE company_id = ? GROUP BY adj_type ORDER BY n DESC",
            (comp,)).fetchall()]
        return {"total": total, "total_usd": round(total_usd, 2), "page": page, "page_size": page_size,
                "total_pages": max(1, (total + page_size - 1) // page_size), "types": types, "adjustments": rows}
    finally:
        conn.close()


@router.get("/adjustments/export")
def export_adjustments(adj_type: Optional[str] = None, search: Optional[str] = None, source: Optional[str] = None,
                       date_from: Optional[str] = None, date_to: Optional[str] = None, company_id: str = Query("rethink")):
    data = get_adjustments(adj_type=adj_type, search=search, source=source, date_from=date_from, date_to=date_to,
                           page=1, page_size=500, company_id=company_id)
    rows = data["adjustments"]
    page = 2
    while len(rows) < data["total"]:
        rows += get_adjustments(adj_type=adj_type, search=search, source=source, date_from=date_from, date_to=date_to,
                                page=page, page_size=500, company_id=company_id)["adjustments"]
        page += 1
    return _csv(rows, ["adj_date", "adj_type", "from_fund", "from_country", "from_pool", "to_fund", "to_country", "to_pool",
                       "usd", "approved_by", "applied_to", "note", "source"], "fund_corrections")


@router.get("/confirm-items")
def get_confirm_items(status: str = Query("open", pattern="^(open|resolved|all)$"), company_id: str = Query("rethink")):
    """Lines the fund-position build could only book with an assumption - waiting for Osman's confirmation."""
    comp = _company(company_id)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        sql = "SELECT * FROM treasury_confirm_items WHERE company_id = ?"
        params: List[Any] = [comp]
        if status != "all":
            sql += " AND status = ?"
            params.append(status)
        items = [dict(r) for r in cur.execute(sql + " ORDER BY status, usd DESC", params).fetchall()]
        for it in items:
            t = it["item"] or ""
            it["category"] = ("Country holds a note" if t.startswith("Country column") else
                              "Parked in 'To be coded'" if "To be coded" in t else
                              "Defaulted to Syria" if "defaulted to Syria" in t else
                              "Holder's country used" if "holder's country" in t or "coded UK" in t else "Other")
        counts = {r[0]: (r[1], round(r[2] or 0, 2)) for r in cur.execute(
            "SELECT status, COUNT(*), SUM(usd) FROM treasury_confirm_items WHERE company_id = ? GROUP BY status", (comp,)).fetchall()}
        return {"items": items, "counts": {k: {"count": v[0], "usd": v[1]} for k, v in counts.items()}}
    finally:
        conn.close()


@router.post("/confirm-items/{item_id}/resolve")
def resolve_confirm_item(item_id: int, payload: ConfirmResolveRequest, request: Request):
    comp = _company(payload.company_id)
    if not payload.resolution.strip():
        raise HTTPException(status_code=400, detail="Say how it was resolved.")
    conn = _get_conn()
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT * FROM treasury_confirm_items WHERE id = ? AND company_id = ?", (item_id, comp)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Item not found.")
        actor = _actor(request)
        cur.execute("UPDATE treasury_confirm_items SET status = 'resolved', resolution = ?, resolved_by = ?, resolved_at = ? WHERE id = ?",
                    (payload.resolution.strip(), actor, _today(), item_id))
        act = _log(cur, actor, "confirm_resolve", f"Confirmed: {row['item'][:90]} — {payload.resolution.strip()[:80]}",
                   float(row["usd"] or 0), payload.model_dump(),
                   [{"op": "confirm_reopen", "id": item_id}], comp)
        conn.commit()
        return {"status": "ok", "activity_id": act}
    finally:
        conn.close()


@router.post("/confirm-items/{item_id}/reopen")
def reopen_confirm_item(item_id: int, request: Request, company_id: str = Query("rethink")):
    comp = _company(company_id)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE treasury_confirm_items SET status = 'open', resolution = NULL, resolved_by = NULL, resolved_at = NULL WHERE id = ? AND company_id = ?",
                    (item_id, comp))
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@router.get("/sources")
def get_sources(company_id: str = Query("rethink")):
    """Every workbook/tab the close was built from, with its last dated line, so stale sources stand out."""
    comp = _company(company_id)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        rows = [dict(r) for r in cur.execute(
            """SELECT s.*, a.name AS account_name FROM treasury_sources s LEFT JOIN treasury_accounts a ON a.id = s.account_id
               WHERE s.company_id = ? ORDER BY s.last_date DESC, s.file""", (comp,)).fetchall()]
        period_end = "2026-10-31"
        for r in rows:
            folder = "October" if "Oct" in (r["file"] or "") else "September" if "Sep" in (r["file"] or "") else "Jul–Aug"
            r["period"] = folder
            r["covers_period_end"] = bool(r["last_date"] and r["last_date"] >= "2026-10-25")
        return {"period_end": period_end, "sources": rows}
    finally:
        conn.close()


@router.get("/activity")
def get_activity(page: int = Query(1, ge=1), page_size: int = Query(30, ge=10, le=200), action: Optional[str] = None,
                 company_id: str = Query("rethink")):
    """Everything changed in Treasury from the CRM, newest first."""
    comp = _company(company_id)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        where = "company_id = ?"
        params: List[Any] = [comp]
        if action and action != "ALL":
            where += " AND action = ?"
            params.append(action)
        total = cur.execute(f"SELECT COUNT(*) FROM treasury_activity WHERE {where}", params).fetchone()[0]
        rows = [dict(r) for r in cur.execute(
            f"""SELECT id, ts, actor, action, summary, amount_usd, reversed_by, reversal_of,
                   (undo_json IS NOT NULL AND undo_json != '[]') AS reversible
                FROM treasury_activity WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?""",
            [*params, page_size, (page - 1) * page_size]).fetchall()]
        return {"total": total, "page": page, "total_pages": max(1, (total + page_size - 1) // page_size), "activity": rows}
    finally:
        conn.close()


@router.post("/activity/{activity_id}/reverse")
def reverse_activity(activity_id: int, payload: ReverseRequest, request: Request):
    """Undo a change exactly (balances, pot lines, corrections); the original and the reversal both stay in the log."""
    comp = _company(payload.company_id)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        act = cur.execute("SELECT * FROM treasury_activity WHERE id = ? AND company_id = ?", (activity_id, comp)).fetchone()
        if not act:
            raise HTTPException(status_code=404, detail="Activity not found.")
        if act["reversed_by"]:
            raise HTTPException(status_code=409, detail="This change has already been reversed.")
        if act["reversal_of"]:
            raise HTTPException(status_code=400, detail="A reversal cannot itself be reversed; redo the original change instead.")
        ops = json.loads(act["undo_json"] or "[]")
        if not ops:
            raise HTTPException(status_code=400, detail="This change cannot be reversed.")
        for op in ops:
            if op.get("op") == "confirm_reopen":
                cur.execute("UPDATE treasury_confirm_items SET status = 'open', resolution = NULL, resolved_by = NULL, resolved_at = NULL WHERE id = ?",
                            (op["id"],))
        _apply_undo(cur, [op for op in ops if op.get("op") != "confirm_reopen"])
        rid = _log(cur, _actor(request), "reversal", f"Reversed #{activity_id}: {act['summary']}" +
                   (f" — {payload.reason}" if payload.reason else ""), -float(act["amount_usd"] or 0),
                   {"reversal_of": activity_id, "reason": payload.reason}, [], comp)
        cur.execute("UPDATE treasury_activity SET reversal_of = ? WHERE id = ?", (activity_id, rid))
        cur.execute("UPDATE treasury_activity SET reversed_by = ? WHERE id = ?", (rid, activity_id))
        conn.commit()
        return {"status": "ok", "reversal_id": rid}
    finally:
        conn.close()
