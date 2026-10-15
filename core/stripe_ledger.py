"""
Live Stripe ledger: every money movement on the charity's Stripe account (charges, refunds, disputes, Stripe fees,
payouts), kept up to date between payouts. READ-ONLY towards Stripe - only GET requests are made.

Table stripe_balance_transactions holds one row per Stripe balance transaction with the donation's details
(charge, payment intent, donor, project metadata) and, once paid out, the payout it went in.
stripe_payout_items stays the per-payout enriched view used for approval and Slack.

poll_stripe_ledger() is called every cycle by the platform sync service:
  1. recent movements (a short overlap window, so nothing created during the previous cycle is missed);
  2. a slice of the one-time backfill from BACKFILL_FROM, until it is complete;
  3. payouts: newly paid ones are linked to their lines and reconciled automatically (still 'pending' approval).
Every write is an idempotent upsert, so running it twice changes nothing.

  venv/bin/python -m core.stripe_ledger            # one poll now (prints a summary)
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from core.database import get_db_connection
from core.stripe_accounts import connected_companies
from core.stripe_reconciliation import STRIPE_API_BASE, _stripe_headers

logger = logging.getLogger("stripe_ledger")

BACKFILL_FROM = datetime(2025, 1, 1, tzinfo=timezone.utc)
RECENT_OVERLAP_SEC = 15 * 60          # re-read the last 15 minutes each poll
BACKFILL_PAGES_PER_POLL = 20          # 2,000 movements per poll at most, so a poll never runs long
AUTO_RECONCILE_LIMIT = 3              # payouts reconciled per poll at most
AUTO_RECONCILE_DAYS = 60              # older payouts are reconciled on request (Reconcile button), not automatically
METADATA_KEYS = ("Donor Name", "Donor Email", "Donor Phone", "Donor Address", "Project Name", "Project Reference",
                 "Location Name", "Location Reference", "Gift Aid?", "Zakat?", "Appeal", "Payment Reference Code",
                 "Stripe Data Reference")


def init_stripe_ledger_tables() -> None:
    conn = get_db_connection(timeout=15.0)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stripe_balance_transactions (
                id TEXT PRIMARY KEY,
                company_id TEXT NOT NULL,
                type TEXT,
                reporting_category TEXT,
                created_at TEXT,
                available_on TEXT,
                amount REAL,
                fee REAL,
                net REAL,
                currency TEXT,
                description TEXT,
                source_id TEXT,
                source_object TEXT,
                charge_id TEXT,
                payment_intent_id TEXT,
                invoice_id TEXT,
                customer_id TEXT,
                payment_method_type TEXT,
                donor_name TEXT,
                donor_email TEXT,
                project_name TEXT,
                gift_aid TEXT,
                zakat TEXT,
                metadata_json TEXT,
                charge_status TEXT,
                amount_refunded REAL DEFAULT 0,
                disputed INTEGER DEFAULT 0,
                payout_id TEXT,
                first_seen_at TEXT,
                updated_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sbt_company_created ON stripe_balance_transactions(company_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sbt_charge ON stripe_balance_transactions(charge_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sbt_payout ON stripe_balance_transactions(payout_id)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stripe_sync_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _get(path: str, params: Dict[str, Any], company: str) -> Dict[str, Any]:
    """The only way this module talks to Stripe: GET, with that charity's own key."""
    r = requests.get(f"{STRIPE_API_BASE}/{path}", headers=_stripe_headers(company), params=params, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Stripe GET /{path} failed: {r.status_code}")
    return r.json()


def _skey(company: str, key: str) -> str:
    # Rethink's state keeps its original (unprefixed) names; any other charity's is prefixed "<company>:"
    return key if company == "rethink" else f"{company}:{key}"


def _state(conn, key: str, company: str = "rethink") -> Optional[str]:
    row = conn.execute("SELECT value FROM stripe_sync_state WHERE key = ?", (_skey(company, key),)).fetchone()
    return row[0] if row else None


def _set_state(conn, key: str, value: Any, company: str = "rethink") -> None:
    conn.execute("""INSERT INTO stripe_sync_state (key, value, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
                 (_skey(company, key), str(value), datetime.now(timezone.utc).isoformat()))


def _del_state(conn, key: str, company: str = "rethink") -> None:
    conn.execute("DELETE FROM stripe_sync_state WHERE key = ?", (_skey(company, key),))


def _iso(ts: Optional[int]) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if ts else ""


def _row(bt: Dict[str, Any], now_iso: str, company: str) -> Dict[str, Any]:
    src = bt.get("source") if isinstance(bt.get("source"), dict) else {}
    obj = src.get("object") or ""
    charge = src if obj == "charge" else (src.get("charge") if isinstance(src.get("charge"), dict) else {})
    charge_id = charge.get("id") or (src.get("charge") if isinstance(src.get("charge"), str) else "") or ""
    pi = charge.get("payment_intent") if isinstance(charge.get("payment_intent"), dict) else {}
    pi_id = pi.get("id") or (charge.get("payment_intent") if isinstance(charge.get("payment_intent"), str) else "") \
        or (src.get("payment_intent") if isinstance(src.get("payment_intent"), str) else "")
    meta = {k: v for k, v in (charge.get("metadata") or {}).items() if v}
    if src is not charge:
        meta.update({k: v for k, v in (src.get("metadata") or {}).items() if v})
    meta.update({k: v for k, v in (pi.get("metadata") or {}).items() if v})
    billing = charge.get("billing_details") or {}
    invoice = charge.get("invoice")
    return {
        "id": bt["id"],
        "company_id": company,
        "type": bt.get("type"),
        "reporting_category": bt.get("reporting_category"),
        "created_at": _iso(bt.get("created")),
        "available_on": _iso(bt.get("available_on")),
        "amount": round((bt.get("amount") or 0) / 100.0, 2),
        "fee": round((bt.get("fee") or 0) / 100.0, 2),
        "net": round((bt.get("net") or 0) / 100.0, 2),
        "currency": str(bt.get("currency") or "gbp").upper(),
        "description": bt.get("description") or charge.get("description") or "",
        "source_id": src.get("id") or (bt.get("source") if isinstance(bt.get("source"), str) else ""),
        "source_object": obj,
        "charge_id": charge_id if str(charge_id).startswith(("ch_", "py_")) else "",
        "payment_intent_id": pi_id or "",
        "invoice_id": invoice if isinstance(invoice, str) else ((invoice or {}).get("id") or ""),
        "customer_id": charge.get("customer") if isinstance(charge.get("customer"), str) else "",
        "payment_method_type": (charge.get("payment_method_details") or {}).get("type") or "",
        "donor_name": meta.get("Donor Name") or billing.get("name") or "",
        "donor_email": meta.get("Donor Email") or billing.get("email") or charge.get("receipt_email") or "",
        "project_name": meta.get("Project Name") or "",
        "gift_aid": meta.get("Gift Aid?") or "",
        "zakat": meta.get("Zakat?") or "",
        "metadata_json": json.dumps({k: meta[k] for k in METADATA_KEYS if k in meta}),
        "charge_status": charge.get("status") or "",
        "amount_refunded": round((charge.get("amount_refunded") or 0) / 100.0, 2),
        "disputed": int(bool(charge.get("disputed"))),
        "updated_at": now_iso,
        "first_seen_at": now_iso,
    }


_COLS = ["id", "company_id", "type", "reporting_category", "created_at", "available_on", "amount", "fee", "net",
         "currency", "description", "source_id", "source_object", "charge_id", "payment_intent_id", "invoice_id",
         "customer_id", "payment_method_type", "donor_name", "donor_email", "project_name", "gift_aid", "zakat",
         "metadata_json", "charge_status", "amount_refunded", "disputed", "updated_at", "first_seen_at"]
_UPSERT = (f"INSERT INTO stripe_balance_transactions ({', '.join(_COLS)}) VALUES ({', '.join('?' * len(_COLS))}) "
           "ON CONFLICT(id) DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in _COLS if c not in ("id", "first_seen_at")))


def _ingest_pages(conn, params: Dict[str, Any], max_pages: int, company: str) -> Dict[str, Any]:
    """Pages through GET /balance_transactions with params; upserts every row. Returns counts and whether finished."""
    params = {**params, "limit": 100, "expand[]": ["data.source", "data.source.payment_intent"]}
    seen = new = pages = 0
    finished = False
    now_iso = datetime.now(timezone.utc).isoformat()
    while pages < max_pages:
        page = _get("balance_transactions", params, company)
        pages += 1
        data = page.get("data", [])
        for bt in data:
            row = _row(bt, now_iso, company)
            existed = conn.execute("SELECT company_id FROM stripe_balance_transactions WHERE id = ?", (row["id"],)).fetchone()
            if existed and existed[0] != company:
                raise RuntimeError(f"Stripe movement {row['id']} is already stored for another charity; refusing to overwrite.")
            conn.execute(_UPSERT, [row[c] for c in _COLS])
            seen += 1
            new += 0 if existed else 1
        if not page.get("has_more") or not data:
            finished = True
            break
        params["starting_after"] = data[-1]["id"]
    return {"seen": seen, "new": new, "pages": pages, "finished": finished,
            "resume_after": None if finished else params.get("starting_after")}


def _link_payouts(conn, auto_reconcile: bool, company: str) -> Dict[str, Any]:
    """Marks which payout each movement went in, and reconciles newly paid payouts (they stay 'pending' approval)."""
    start = int(BACKFILL_FROM.timestamp())
    payouts: List[Dict[str, Any]] = []
    params: Dict[str, Any] = {"limit": 100, "created[gte]": start}
    while True:
        page = _get("payouts", params, company)
        payouts.extend(page.get("data", []))
        if not page.get("has_more") or not page.get("data"):
            break
        params["starting_after"] = page["data"][-1]["id"]
    linked_before = set(json.loads(_state(conn, "linked_payouts", company) or "[]"))
    linked_now, to_reconcile = [], []
    for p in payouts:
        if p.get("status") != "paid" or p["id"] in linked_before:
            continue
        if not p.get("automatic"):
            continue  # Stripe can't list the movements of a manual payout
        ids: List[str] = []
        q: Dict[str, Any] = {"payout": p["id"], "limit": 100}
        while True:
            page = _get("balance_transactions", q, company)
            ids.extend(b["id"] for b in page.get("data", []) if b.get("type") != "payout")
            if not page.get("has_more") or not page.get("data"):
                break
            q["starting_after"] = page["data"][-1]["id"]
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            conn.execute(f"UPDATE stripe_balance_transactions SET payout_id = ? WHERE company_id = ? AND id IN ({','.join('?' * len(chunk))})",
                         (p["id"], company, *chunk))
        linked_now.append(p["id"])
        to_reconcile.append(p["id"])
    if linked_now:
        _set_state(conn, "linked_payouts", json.dumps(sorted(linked_before | set(linked_now))), company)
    conn.commit()

    reconciled = []
    if auto_reconcile:
        done = {r[0] for r in conn.execute("""SELECT payout_id FROM stripe_payout_reports
                                               WHERE adds_up IS NOT NULL AND LOWER(COALESCE(company_id, 'rethink')) = ?""", (company,))}
        # Newest first; payouts already reconciled (with the adds-up check) are left alone
        recent_from = time.time() - AUTO_RECONCILE_DAYS * 86400
        pending = [p["id"] for p in sorted(payouts, key=lambda x: x.get("created") or 0, reverse=True)
                   if p.get("status") == "paid" and p.get("automatic") and p["id"] not in done
                   and (p.get("arrival_date") or 0) >= recent_from]
        from core.stripe_reconciliation import reconcile_stripe_payout
        for pid in pending[:AUTO_RECONCILE_LIMIT]:
            try:
                s = reconcile_stripe_payout(pid, company)
                reconciled.append({"payout_id": pid, "adds_up": s.get("adds_up"), "unassigned": s.get("unassigned_lines")})
            except Exception as e:
                logger.warning(f"Auto-reconcile of {pid} failed: {e}")
                reconciled.append({"payout_id": pid, "error": str(e)})
    return {"payouts_seen": len(payouts), "newly_linked": len(linked_now), "reconciled": reconciled}


def _poll_company(conn, company: str, auto_reconcile: bool) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    # 1. Recent movements
    last = _state(conn, "recent_cursor", company)
    since = int(float(last)) - RECENT_OVERLAP_SEC if last else int(time.time()) - 86400
    poll_started = int(time.time())
    result["recent"] = _ingest_pages(conn, {"created[gte]": since}, 50, company)
    if result["recent"]["finished"]:
        _set_state(conn, "recent_cursor", poll_started, company)
    conn.commit()

    # 2. One-time backfill, newest to oldest, a slice per poll
    if _state(conn, "backfill_done", company) != "1":
        upper = _state(conn, "backfill_upper", company) or str(since)
        params: Dict[str, Any] = {"created[gte]": int(BACKFILL_FROM.timestamp()), "created[lt]": int(float(upper))}
        resume = _state(conn, "backfill_resume_after", company)
        if resume:
            params["starting_after"] = resume
        if not _state(conn, "backfill_upper", company):
            _set_state(conn, "backfill_upper", upper, company)
        bf = _ingest_pages(conn, params, BACKFILL_PAGES_PER_POLL, company)
        if bf["finished"]:
            _set_state(conn, "backfill_done", "1", company)
            _del_state(conn, "backfill_resume_after", company)
        else:
            _set_state(conn, "backfill_resume_after", bf["resume_after"], company)
        conn.commit()
        result["backfill"] = bf

    # 3. Payouts
    result["payouts"] = _link_payouts(conn, auto_reconcile, company)

    # 4. CRM donations from Stripe + GiveBrite tie-back - only once switched on for this charity (after its dry run)
    if _state(conn, "crm_sync_enabled", company) == "1":
        try:
            from core.stripe_crm_sync import run as crm_sync
            result["crm"] = crm_sync(apply=True, backup=False, company=company)["applied"]
        except Exception as e:
            logger.warning(f"Stripe -> CRM sync failed for {company}: {e}")
            result["crm"] = {"error": str(e)}
    return result


def poll_stripe_ledger(auto_reconcile: bool = True) -> Dict[str, Any]:
    """One poll for every charity whose Stripe account is connected. Safe to run as often as wanted.
    A failure for one charity never stops the others."""
    companies = connected_companies()
    if not companies:
        return {"skipped": "no Stripe account connected"}
    started = time.time()
    init_stripe_ledger_tables()
    conn = get_db_connection(timeout=30.0)
    out: Dict[str, Any] = {}
    try:
        for company in companies:
            try:
                out[company] = _poll_company(conn, company, auto_reconcile)
            except Exception as e:
                conn.rollback()
                logger.warning(f"Stripe ledger poll failed for {company}: {e}")
                out[company] = {"error": str(e)}
    finally:
        conn.close()
    out["seconds"] = round(time.time() - started, 1)
    return out


init_stripe_ledger_tables()

if __name__ == "__main__":
    print(json.dumps(poll_stripe_ledger(auto_reconcile=False), indent=1, default=str))
