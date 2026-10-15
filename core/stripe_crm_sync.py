"""
Stripe -> CRM donations (Rethink's Stripe account; website card payments, Direct Debits, subscriptions, Link).

Source: the live ledger (core/stripe_ledger.py, table stripe_balance_transactions) from the charity's crm_start_date on.
  * Sign Pay terminal payments (card_present) are NOT made into CRM donations: they stay in the payout reports,
    labelled "Sign Pay" there.
  * GiveBrite gifts paid through this account are left out: GiveBrite already feeds the CRM (tied back separately).
  * A payment the website export already put in the CRM is LINKED, not duplicated: the website's donation id
    (pmt_...) is the Stripe "Payment Reference Code". Linking adds the Stripe ids, real fee/net and payout,
    and fills an empty date; it never changes the row's donor or classification.
  * Anything else becomes a new donation: Platform "Rethink Website", Donation ID = the website reference when
    Stripe has one (so a later CSV upload of the same gift can't duplicate it), otherwise the Stripe charge id.
    Recurring payments (invoice / Direct Debit / "Subscription ...") are "Recurring Payment".
  * Refunds and failed Direct Debits add a negative "Refund" row against the gift and mark its status, so totals
    stay right and nothing is deleted.
Nothing is written to Stripe (the ledger is read from SQLite; project names of subscriptions use GET only).

  venv/bin/python -m core.stripe_crm_sync              # dry run: prints the plan, writes nothing
  venv/bin/python -m core.stripe_crm_sync --apply      # backup, then one transaction
"""
import json
import logging
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from config.settings import LOCAL_DB_PATH
from core.stripe_accounts import account_setting, is_connected
from core.stripe_reconciliation import _match_crm_classification
from core.utils import classify_donor_amount

logger = logging.getLogger("stripe_crm_sync")

# Per charity (core/stripe_accounts.py): crm_start_date - Rethink 2026-08-01, agreed 15 Oct 2026
PLATFORM = "Rethink Website"
SOURCE = "Stripe Sync"
GIFT_TYPES = ("charge", "payment")
REVERSAL_TYPES = ("refund", "payment_refund", "payment_failure_refund")
NET = "Total Online Donations Net Amount in Settled Currency"
GROSS = "Total Online Donation Gross Amount in Settled Currency"
FEES = "Total Processing Fees Paid by CC In Settled Currency"


def _is_givebrite(row: Dict[str, Any]) -> bool:
    d = (row.get("description") or "").strip()
    return d.startswith("GB-") or "givebrite" in d.lower()


def _is_recurring(row: Dict[str, Any]) -> bool:
    d = (row.get("description") or "").lower()
    return bool(row.get("invoice_id")) or row.get("payment_method_type") == "bacs_debit" \
        or d.startswith(("subscription", "payment for invoice"))


def _split_name(name: str):
    parts = (name or "").strip().split()
    return (parts[0], " ".join(parts[1:])) if parts else ("", "")


def _project_for(conn, row: Dict[str, Any], meta: Dict[str, str], company: str) -> str:
    """Project from the payment's metadata; else the enriched payout line (subscriptions resolved via invoice)."""
    if meta.get("Project Name"):
        return meta["Project Name"]
    hit = conn.execute("""SELECT project_name FROM stripe_payout_items WHERE balance_transaction_id = ?
                          AND COALESCE(project_name, '') != ''""", (row["id"],)).fetchone()
    if hit:
        return hit[0]
    if row.get("invoice_id"):
        try:  # GET only: the invoice line's product name, as the payout reconciliation does
            import requests
            from core.stripe_reconciliation import STRIPE_API_BASE, _stripe_headers
            inv = requests.get(f"{STRIPE_API_BASE}/invoices/{row['invoice_id']}", headers=_stripe_headers(company),
                               params={"expand[]": "lines.data.price.product"}, timeout=15).json()
            line = ((inv.get("lines") or {}).get("data") or [{}])[0]
            lm = line.get("metadata") or {}
            prod = (line.get("price") or {}).get("product")
            return lm.get("Project Name") or (prod.get("name") if isinstance(prod, dict) else "") or ""
        except Exception as e:
            logger.debug(f"Invoice lookup for {row['id']}: {e}")
    return ""


def _new_record(conn, row: Dict[str, Any], meta: Dict[str, str], table_cols: List[str], register: bool, company: str) -> Dict[str, Any]:
    ref = (meta.get("Payment Reference Code") or "").strip()
    project = _project_for(conn, row, meta, company)
    cls = _match_crm_classification(project, company_id=company, cursor=conn.cursor(), register_unknown=register)
    first, last = _split_name(meta.get("Donor Name") or row.get("donor_name") or "")
    email = (meta.get("Donor Email") or row.get("donor_email") or "").strip()
    gift_aid = "Yes" if str(meta.get("Gift Aid?") or "").strip().lower() in ("yes", "true", "1") else "No"
    zakat_word = str(meta.get("Zakat?") or "").strip().lower()
    is_zakat = zakat_word in ("zakat", "yes", "true")
    gross, fee, net = float(row["amount"]), float(row["fee"]), float(row["net"])
    date, time_ = (row["created_at"] + " ").split(" ")[:2]
    recurring = _is_recurring(row)
    rec = {
        "Donation ID": ref or row["charge_id"] or row["id"],
        "Created Date (UTC)": date, "Created Time (UTC)": time_, "Settled Date (UTC)": date,
        "Created At": row["created_at"], "_parsed_date": date,
        "Status": "COMPLETED", "Transaction Type": "Donation", "Offline or online donation": "online",
        "First Name": first, "Last Name": last, "Display Name": (first + " " + last).strip(),
        "Billing Name": (first + " " + last).strip(), "Email": email, "Email (for tax receipt)": email,
        "Phone Number": meta.get("Donor Phone") or "", "Billing Address": meta.get("Donor Address") or "",
        "Gift Aid (yes or no)": gift_aid, "Gift Aid?": gift_aid,
        "Zakat (yes or no)": "Yes" if is_zakat else "No", "Zakat Status": zakat_word or "",
        "Anonymous or Public": "Public",
        "Donation Currency (DC)": row["currency"], "Currency": row["currency"], "Settlement Currency": row["currency"],
        "Project Currency": row["currency"],
        "Donation Amount (in Donation Currency)": str(gross), "Donation Amount in Project Currency (May be approx.)": str(gross),
        "Amount": gross, GROSS: str(gross), FEES: fee, NET: net, "fee_amount": str(fee),
        "Campaign Name": project or (row.get("description") or ""), "Giving Level Title": meta.get("Location Name") or "",
        "Comments": meta.get("Appeal") or "",
        "Payment Type": "Direct Debit / Stripe" if row.get("payment_method_type") == "bacs_debit" else "Card / Stripe",
        "Payment Frequency": "Recurring Payment" if recurring else "One-Time Payment",
        "Subscription Type": "Subscription" if recurring else "",
        "Platform": PLATFORM, "Source": SOURCE, "gateway": "stripe",
        "charge_id": row["charge_id"], "Customer Ref": row.get("payment_intent_id") or "",
        "Subscription Reference": row.get("invoice_id") or "",
        "Transfer ID": row.get("payout_id") or None, "Payout Settled": "Yes" if row.get("payout_id") else "No",
        "Donation Payout Flag": "Paid" if row.get("payout_id") else "Unpaid",
        "Donor ID": email or (row["charge_id"] or row["id"]),
        "Total LTV": gross, "Lifetime Donor Classification": classify_donor_amount(gross),
        "Transaction Donor Classification": classify_donor_amount(gross),
        "Code": cls["code"], "New Code": cls["code"], "Heading": cls.get("heading") or "", "Sub-Heading": cls.get("subheading") or "",
        "Department": cls.get("department") or "", "Office": cls.get("office") or "", "Portfolio": cls.get("portfolio") or "",
        "Country": cls.get("country") or "", "Target Country": cls.get("country") or "",
        "Programme Fund": cls.get("programme_fund") or "", "Fund Code": cls.get("fund_code") or "",
        "Zakat Eligibility": cls.get("zakat_eligibility") or "",
        "company_id": company,
    }
    return {k: v for k, v in rec.items() if k in table_cols}


def build_plan(conn, register: bool = False, company: str = "rethink") -> Dict[str, Any]:
    start_date = account_setting(company, "crm_start_date")
    if not start_date:
        raise ValueError(f"No CRM start date is set for {company}'s Stripe account (core/stripe_accounts.py).")
    conn.row_factory = sqlite3.Row
    table_cols = [r[1] for r in conn.execute("PRAGMA table_info(donations)")]
    ledger = [dict(r) for r in conn.execute("""SELECT * FROM stripe_balance_transactions
                                                WHERE company_id = ? AND created_at >= ? ORDER BY created_at""",
                                             (company, start_date))]
    crm = conn.execute("""SELECT "Donation ID", charge_id, Platform, COALESCE("Created Date (UTC)", ''), Status, "{net}"
                          FROM donations WHERE LOWER(company_id) = ?""".format(net=NET), (company,)).fetchall()
    gb_rows = conn.execute("""SELECT "Donation ID", charge_id, "Customer Ref", "Transfer ID", "Payout Settled", "{net}",
                                     COALESCE("Settled Date (UTC)", '')
                              FROM donations WHERE LOWER(company_id) = ? AND Platform IN ('GiveBright', 'GiveBrite')""".format(net=NET),
                           (company,)).fetchall()
    gb_by_id = {str(r[0]): r for r in gb_rows if r[0]}
    gb_by_charge = {str(r[1]): r for r in gb_rows if r[1] and str(r[1]).startswith(("ch_", "py_"))}
    by_id = {str(r[0]): r for r in crm if r[0]}
    by_charge = {str(r[1]): r for r in crm if r[1]}
    plan: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    gift_id_for_charge: Dict[str, str] = {}

    for row in ledger:
        meta = json.loads(row.get("metadata_json") or "{}")
        if row["type"] in GIFT_TYPES:
            if row.get("payment_method_type") == "card_present":
                plan["sign_pay_payouts_only"].append(row); continue
            if _is_givebrite(row):
                # GiveBrite already put the gift in the CRM (API sync): tie it to this Stripe charge and its payout
                gb_id = (row.get("description") or "").replace("GB-donation-", "").strip()
                gift = gb_by_charge.get(row["charge_id"]) or gb_by_id.get(gb_id)
                if not gift:
                    plan["givebrite_not_in_crm_yet"].append(row); continue
                gift_id_for_charge[row["charge_id"]] = gift[0]
                change = {"row": row, "donation_id": gift[0], "crm_net": gift[5],
                          "net_mismatch": abs(float(gift[5] or 0) - float(row["net"])) >= 0.005}
                wanted = (row["charge_id"], row.get("payment_intent_id") or "", row.get("payout_id"),
                          "Yes" if row.get("payout_id") else "No")
                have = (gift[1] or "", gift[2] or "", gift[3], gift[4])
                if tuple(str(x or "") for x in wanted) != tuple(str(x or "") for x in have):
                    plan["givebrite_link"].append(change)
                else:
                    plan["givebrite_already_linked"].append(change)
                if change["net_mismatch"]:
                    plan["givebrite_net_mismatch"].append(change)
                continue
            ref = (meta.get("Payment Reference Code") or "").strip()
            existing = (by_charge.get(row["charge_id"]) if row["charge_id"] else None) or (by_id.get(ref) if ref else None) \
                or by_id.get(row["charge_id"] or "")
            if existing:
                gift_id_for_charge[row["charge_id"]] = existing[0]
                if existing[1] == row["charge_id"]:
                    plan["already_linked"].append(row)
                else:
                    plan["link"].append({"row": row, "donation_id": existing[0], "crm_net": existing[5],
                                         "fill_date": not existing[3]})
            else:
                rec = _new_record(conn, row, meta, table_cols, register, company)
                gift_id_for_charge[row["charge_id"]] = rec["Donation ID"]
                plan["add"].append({"row": row, "record": rec})
        elif row["type"] in REVERSAL_TYPES:
            plan["reversals"].append(row)

    for rv in plan.pop("reversals", []):
        gift = gift_id_for_charge.get(rv["charge_id"]) or (by_charge.get(rv["charge_id"]) or [None])[0]
        if not gift:
            plan["reversal_without_gift"].append(rv); continue
        if str(rv["id"]) in by_id:
            plan["reversal_already_recorded"].append(rv); continue
        plan["reversal"].append({"row": rv, "donation_id": gift})
    plan["_table_cols"] = table_cols  # type: ignore
    plan["_start_date"] = start_date  # type: ignore
    return plan


def summarise(plan: Dict[str, Any]) -> Dict[str, Any]:
    money = lambda rows, k="amount": round(sum(float((r.get("row") or r)[k]) for r in rows), 2)  # noqa: E731
    add = plan.get("add", [])
    out = {
        "start_date": plan.get("_start_date"),
        "new_donations": {"count": len(add), "gross": money(add), "net": money(add, "net"),
                          "recurring": sum(1 for a in add if a["record"].get("Payment Frequency") == "Recurring Payment"),
                          "unassigned": sum(1 for a in add if a["record"].get("Code") == "Unassigned"),
                          "by_month": dict(Counter(a["row"]["created_at"][:7] for a in add)),
                          "by_method": dict(Counter(a["row"]["payment_method_type"] for a in add))},
        "linked_to_existing_website_rows": {"count": len(plan.get("link", [])),
                                            "net_change": round(sum(float(l["row"]["net"]) - float(l["crm_net"] or 0) for l in plan.get("link", [])), 2),
                                            "dates_filled": sum(1 for l in plan.get("link", []) if l["fill_date"])},
        "already_linked": len(plan.get("already_linked", [])),
        "refunds_and_failed_payments": {"count": len(plan.get("reversal", [])), "amount": money(plan.get("reversal", []))},
        "refunds_without_a_crm_gift": len(plan.get("reversal_without_gift", [])),
        "sign_pay_kept_in_payouts_only": {"count": len(plan.get("sign_pay_payouts_only", [])), "gross": money(plan.get("sign_pay_payouts_only", []))},
        "givebrite": {"linked_to_stripe_now": len(plan.get("givebrite_link", [])),
                      "already_linked": len(plan.get("givebrite_already_linked", [])),
                      "not_in_crm_yet": len(plan.get("givebrite_not_in_crm_yet", [])),
                      "net_differs_from_stripe": len(plan.get("givebrite_net_mismatch", []))},
    }
    out["total_change"] = round(out["new_donations"]["net"] + out["linked_to_existing_website_rows"]["net_change"]
                                        + money(plan.get("reversal", []), "net"), 2)
    return out


def apply_plan(conn, plan: Dict[str, Any], company: str) -> Dict[str, Any]:
    table_cols = plan["_table_cols"]
    added = linked = reversed_ = gb_linked = 0
    touched = set()
    for a in plan.get("add", []):
        rec = a["record"]
        if conn.execute("SELECT 1 FROM donations WHERE LOWER(company_id) = ? AND \"Donation ID\" = ?",
                        (company, rec["Donation ID"])).fetchone():
            continue
        cols = [c for c in table_cols if c in rec]
        conn.execute(f"INSERT INTO donations ({', '.join(chr(34) + c + chr(34) for c in cols)}) VALUES ({', '.join('?' * len(cols))})",
                     [rec[c] for c in cols])
        added += 1
    for l in plan.get("link", []):
        r = l["row"]
        date, time_ = (r["created_at"] + " ").split(" ")[:2]
        conn.execute(f"""UPDATE donations SET charge_id = ?, "Customer Ref" = ?, "Transfer ID" = ?, "Payout Settled" = ?,
                             "{FEES}" = ?, "{NET}" = ?, fee_amount = ?, gateway = 'stripe',
                             "Created Date (UTC)" = CASE WHEN COALESCE("Created Date (UTC)", '') = '' THEN ? ELSE "Created Date (UTC)" END,
                             "Settled Date (UTC)" = CASE WHEN COALESCE("Settled Date (UTC)", '') = '' THEN ? ELSE "Settled Date (UTC)" END
                         WHERE LOWER(company_id) = ? AND "Donation ID" = ?""",
                     (r["charge_id"], r.get("payment_intent_id") or "", r.get("payout_id"), "Yes" if r.get("payout_id") else "No",
                      float(r["fee"]), float(r["net"]), str(r["fee"]), date, date, company, l["donation_id"]))
        touched.add((company, str(l["donation_id"])))
        linked += 1
    for rv in plan.get("reversal", []):
        r = rv["row"]
        gift = conn.execute("SELECT * FROM donations WHERE LOWER(company_id) = ? AND \"Donation ID\" = ?",
                            (company, rv["donation_id"])).fetchone()
        if not gift:
            continue
        g = dict(zip([d[0] for d in conn.execute("SELECT * FROM donations LIMIT 0").description], gift))
        failed = r["type"] == "payment_failure_refund"
        date, time_ = (r["created_at"] + " ").split(" ")[:2]
        neg = {k: g.get(k) for k in table_cols}
        neg.update({"Donation ID": r["id"], "Created Date (UTC)": date, "Created Time (UTC)": time_, "Settled Date (UTC)": date,
                    "Created At": r["created_at"], "_parsed_date": date, "Transaction Type": "Refund",
                    "Status": "FAILED PAYMENT REVERSED" if failed else "REFUND",
                    "Amount": float(r["amount"]), GROSS: str(r["amount"]), FEES: float(r["fee"]), NET: float(r["net"]),
                    "Donation Amount (in Donation Currency)": str(r["amount"]),
                    "Donation Amount in Project Currency (May be approx.)": str(r["amount"]), "fee_amount": str(r["fee"]),
                    "Source": SOURCE, "Comments": f"{'Failed payment reversed' if failed else 'Refund'} of {rv['donation_id']}",
                    "Transfer ID": r.get("payout_id"), "Payout Settled": "Yes" if r.get("payout_id") else "No",
                    "Total LTV": float(r["amount"])})
        cols = [c for c in table_cols if c in neg]
        conn.execute(f"INSERT INTO donations ({', '.join(chr(34) + c + chr(34) for c in cols)}) VALUES ({', '.join('?' * len(cols))})",
                     [neg[c] for c in cols])
        conn.execute("UPDATE donations SET Status = ? WHERE LOWER(company_id) = ? AND \"Donation ID\" = ?",
                     ("FAILED" if failed else "REFUNDED", company, rv["donation_id"]))
        touched.add((company, str(rv["donation_id"])))
        reversed_ += 1
    for g in plan.get("givebrite_link", []):
        r = g["row"]
        # Only the Stripe side is added: charge, payment intent, payout. GiveBrite's own amounts are kept.
        conn.execute("""UPDATE donations SET charge_id = ?, "Customer Ref" = ?, "Transfer ID" = ?, "Payout Settled" = ?,
                               "Donation Payout Flag" = ?
                        WHERE LOWER(company_id) = ? AND "Donation ID" = ? AND Platform IN ('GiveBright', 'GiveBrite')""",
                     (r["charge_id"], r.get("payment_intent_id") or "", r.get("payout_id"),
                      "Yes" if r.get("payout_id") else "No", "Paid" if r.get("payout_id") else "Unpaid", company, g["donation_id"]))
        touched.add((company, str(g["donation_id"])))
        gb_linked += 1
    return {"added": added, "linked": linked, "reversals": reversed_, "givebrite_linked": gb_linked, "_touched": touched}


def run(apply: bool = False, backup: bool = True, company: str = "rethink") -> Dict[str, Any]:
    company = str(company or "").strip().lower()
    if not is_connected(company):
        raise ValueError(f"Stripe isn't connected for '{company}'.")
    if not apply:
        conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=30)
        try:
            plan = build_plan(conn, register=False, company=company)
            return {"dry_run": True, "summary": summarise(plan), "plan": plan}
        finally:
            conn.close()
    if backup:
        from core.nightly_backup import BACKUP_DIR
        os.makedirs(BACKUP_DIR, exist_ok=True)
        path = os.path.join(os.path.dirname(BACKUP_DIR), f"pre_stripe_crm_sync_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.db")
        ro = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True)
        ro.execute(f"VACUUM INTO '{path}'")
        ro.close()
        os.chmod(path, 0o600)
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=60)
    try:
        with conn:
            plan = build_plan(conn, register=True, company=company)
            counts = apply_plan(conn, plan, company)
        summary = summarise(plan)
    finally:
        conn.close()
    touched = counts.pop("_touched")
    if touched or counts["added"] or counts["reversals"]:
        # SQLite is the source of truth; bring the dashboards' copy level now: new rows + just the rows changed
        from core.donations_reconcile import reconcile
        reconcile(deep=False, apply=True, require_confirmation=False, only_keys=touched)
    return {"dry_run": False, "applied": counts, "summary": summary}


def _print_dry_run(result: Dict[str, Any]) -> None:
    print(json.dumps(result["summary"], indent=1))
    plan = result["plan"]
    print("\nNew donations:")
    for a in plan.get("add", []):
        r, rec = a["row"], a["record"]
        print(f"  {r['created_at'][:10]}  £{float(r['amount']):>8.2f}  {r['payment_method_type']:<10} {rec.get('Payment Frequency', ''):<17} "
              f"{rec.get('Code', ''):<17} {str(rec.get('Campaign Name', ''))[:34]:<34} {rec.get('Email', '')[:30]}")
    print("\nLinked to existing website rows:")
    for l in plan.get("link", []):
        r = l["row"]
        print(f"  {r['created_at'][:10]}  {l['donation_id']}  gross £{float(r['amount']):.2f}  CRM net £{float(l['crm_net'] or 0):.2f} -> Stripe net £{float(r['net']):.2f}")
    print("\nGiveBrite gifts tied to their Stripe charge / payout:")
    for g in plan.get("givebrite_link", []):
        r = g["row"]
        print(f"  {r['created_at'][:10]}  GiveBrite {g['donation_id']}  £{float(r['amount']):.2f}  charge {r['charge_id'][:14]}…  "
              f"payout {r.get('payout_id') or '(not paid out yet)'}{'  NET DIFFERS: CRM £%.2f vs Stripe £%.2f' % (float(g['crm_net'] or 0), float(r['net'])) if g['net_mismatch'] else ''}")
    for r in plan.get("givebrite_not_in_crm_yet", []):
        print(f"  {r['created_at'][:10]}  {r['description']}  £{float(r['amount']):.2f}  (GiveBrite sync hasn't brought it in yet)")
    print("\nRefunds / failed payments:")
    for rv in plan.get("reversal", []):
        print(f"  {rv['row']['created_at'][:10]}  £{float(rv['row']['amount']):.2f}  {rv['row']['type']}  against {rv['donation_id']}")
    for rv in plan.get("reversal_without_gift", []):
        print(f"  {rv['created_at'][:10]}  £{float(rv['amount']):.2f}  {rv['type']}  (gift not in CRM: before {plan.get('_start_date')} or Sign Pay)")


if __name__ == "__main__":
    comp = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--company=")), "rethink")
    res = run(apply="--apply" in sys.argv, company=comp)
    if res["dry_run"]:
        _print_dry_run(res)
    else:
        print(json.dumps({"applied": res["applied"], "summary": res["summary"]}, indent=1))
