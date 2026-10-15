"""
Access PaySuite (DDCMS v3) Historical 2026+ Migration & Audit Script.

Dry-run audit and migration tool:
- Compares existing CRM collections with live Access PaySuite API records from 2026-01-01 onwards.
- Reports exact match rate, missing collections, ARUDD reversals, and monthly revenue deltas.
- Default mode is strictly DRY-RUN (reads only, modifies nothing).
- Pass --apply to create a database backup and execute the migration.

Usage:
  venv/bin/python -m core.paysuite_migration           # Dry-run audit report
  venv/bin/python -m core.paysuite_migration --apply   # Backup & apply migration
"""
import argparse
import logging
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

import pandas as pd

from config.settings import (
    LOCAL_DB_PATH,
    PARQUET_PATH,
    PAYSUITE_PAYOUTS_PARQUET_PATH,
)
from core.database import get_db_connection
from core.paysuite_client import get_paysuite_client
from core.paysuite_sync import (
    HISTORICAL_CUTOFF_DATE,
    sync_paysuite_payments,
    reconcile_paysuite_to_crm,
    set_sync_state,
    _format_date,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("paysuite_migration")


def generate_migration_audit(company_id: str = "rethink") -> Dict[str, Any]:
    """Generates a comprehensive audit of current CRM state vs live PaySuite API for 2026+."""
    client = get_paysuite_client()
    if not client.is_configured():
        raise RuntimeError("Access PaySuite credentials not configured in environment.")

    logger.info(f"[Migration Audit] Querying PaySuite API for collections from {HISTORICAL_CUTOFF_DATE} onwards...")

    # Collections only: IsCredit records are PaySuite's payouts to the bank, not donations
    api_payments: List[Dict[str, Any]] = [
        p for p in client.iter_all_payments(from_date=HISTORICAL_CUTOFF_DATE, page_size=100) if not p.get("IsCredit")
    ]

    logger.info(f"[Migration Audit] Retrieved {len(api_payments)} payment record(s) from API.")

    conn = get_db_connection(timeout=30.0)
    try:
        # Existing payout settlements
        cur = conn.cursor()
        # Uploaded rows hold day-first text dates ("01/09/2026"): parse them, don't compare strings
        payouts = pd.read_sql_query("""
            SELECT "Bank Ref", "Date of collection", "Donation ID", "Donation Amount", "Status"
            FROM paysuite_payout_settlements WHERE LOWER(COALESCE(company_id, 'rethink')) = ?
        """, conn, params=(company_id,))
        raw = payouts["Date of collection"].astype(str).str.strip()
        iso = raw.str.match(r"^\d{4}-\d{2}-\d{2}")
        parsed = pd.to_datetime(raw.where(iso), errors="coerce", format="%Y-%m-%d").fillna(
            pd.to_datetime(raw.where(~iso), errors="coerce", dayfirst=True))
        payouts["_month"] = parsed.dt.strftime("%Y-%m")
        payouts = payouts[parsed >= pd.Timestamp(HISTORICAL_CUTOFF_DATE)]
        crm_payout_rows = payouts.values.tolist()

        # Existing donations
        cur.execute("""
            SELECT "Donation ID", "Created Date (UTC)",
                   CAST("Total Online Donations Net Amount in Settled Currency" AS REAL), "Status"
            FROM donations
            WHERE LOWER(Platform) = 'paysuite' AND "Created Date (UTC)" >= ?
              AND LOWER(COALESCE(company_id, 'rethink')) = ?
        """, (HISTORICAL_CUTOFF_DATE, company_id))
        crm_donation_rows = cur.fetchall()
    finally:
        conn.close()

    # The mandate reference repeats every month, so a collection is "already there" only for the same
    # reference AND collection month
    existing_payout_keys = {(r[0], r[5]) for r in crm_payout_rows if r[0]}
    existing_donation_ids = {r[0] for r in crm_donation_rows if r[0]}
    crm_total_before = round(sum(float(r[2] or 0.0) for r in crm_donation_rows), 2)

    # Categorize API payments
    monthly_breakdown: Dict[str, Dict[str, Any]] = {}
    total_api_gross = 0.0
    total_api_paid_count = 0
    total_api_unpaid_count = 0

    missing_from_crm = 0
    already_in_crm = 0

    for p in api_payments:
        pid = p.get("Id")
        ref = p.get("DirectDebitReference")
        amt = round(int(p.get("Amount") or 0) / 100.0, 2)
        raw_date = p.get("CollectionDate") or p.get("DateOfCollection")
        cdate = _format_date(raw_date)
        status_val = p.get("Status") or "Paid"
        month_key = cdate[:7] if len(cdate) >= 7 else "Unknown"

        if month_key not in monthly_breakdown:
            monthly_breakdown[month_key] = {"api_count": 0, "api_gross": 0.0, "paid": 0, "unpaid": 0}

        monthly_breakdown[month_key]["api_count"] += 1
        monthly_breakdown[month_key]["api_gross"] += amt
        if status_val.lower() == "paid":
            monthly_breakdown[month_key]["paid"] += 1
            total_api_paid_count += 1
            total_api_gross += amt
        else:
            monthly_breakdown[month_key]["unpaid"] += 1
            total_api_unpaid_count += 1

        if pid in existing_donation_ids or (ref, month_key) in existing_payout_keys:
            already_in_crm += 1
        else:
            missing_from_crm += 1

    audit_summary = {
        "cutoff_date": HISTORICAL_CUTOFF_DATE,
        "company_id": company_id,
        "total_api_payments_2026": len(api_payments),
        "total_api_paid_payments": total_api_paid_count,
        "total_api_unpaid_payments": total_api_unpaid_count,
        "total_api_gross_amount": round(total_api_gross, 2),
        "existing_crm_payout_records": len(crm_payout_rows),
        "existing_crm_donation_records": len(crm_donation_rows),
        "estimated_new_donations_to_add": missing_from_crm,
        "already_in_uploads": already_in_crm,
        # After the sync: one donation per Paid collection; a returned (Unpaid) one nets to zero
        "crm_donation_total_before": crm_total_before,
        "crm_donation_total_after": round(total_api_gross, 2),
        "monthly_breakdown": dict(sorted(monthly_breakdown.items())),
    }

    return audit_summary


def print_audit_report(audit: Dict[str, Any]) -> None:
    print("\n" + "=" * 70)
    print("ACCESS PAYSUITE (DDCMS v3) 2026+ MIGRATION AUDIT REPORT")
    print("=" * 70)
    print(f"Historical Cutoff Date : {audit['cutoff_date']}")
    print(f"Target Charity         : {audit['company_id']}")
    print(f"Total API Payments     : {audit['total_api_payments_2026']:,}")
    print(f"  - Paid Collections   : {audit['total_api_paid_payments']:,} (£{audit['total_api_gross_amount']:,.2f})")
    print(f"  - Unpaid / ARUDD     : {audit['total_api_unpaid_payments']:,}")
    print("-" * 70)
    print(f"Current CRM Direct Debit Donations : {audit['existing_crm_donation_records']:,}")
    print(f"Current CRM Payout Rows            : {audit['existing_crm_payout_records']:,}")
    print(f"Collections Missing from uploads   : {audit['estimated_new_donations_to_add']:,}")
    print(f"Collections already in uploads     : {audit['already_in_uploads']:,}")
    print(f"2026+ PaySuite donations total     : £{audit['crm_donation_total_before']:,.2f} -> £{audit['crm_donation_total_after']:,.2f}")
    print("-" * 70)
    print("MONTHLY BREAKDOWN (2026):")
    for m, stats in audit["monthly_breakdown"].items():
        print(f"  • {m}: {stats['api_count']} collections | Paid: {stats['paid']} | Unpaid: {stats['unpaid']} | Gross: £{stats['api_gross']:,.2f}")
    print("=" * 70 + "\n")


def backup_database() -> str:
    """Creates a timestamped snapshot of the local database before migration."""
    now_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(os.path.dirname(os.path.abspath(LOCAL_DB_PATH)), "data_cache", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, f"pre_paysuite_migration_{now_tag}.db")
    # SQLite's backup API, not a file copy: the DB runs in WAL mode and a copy of the .db file alone misses
    # whatever is still in the -wal file.
    src = sqlite3.connect(LOCAL_DB_PATH, timeout=60)
    dst = sqlite3.connect(backup_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.chmod(backup_path, 0o600)
    logger.info(f"Database backed up successfully to: {backup_path}")
    if os.path.exists(PARQUET_PATH):
        p_bak = f"{PARQUET_PATH}.bak_paysuite_{now_tag}"
        shutil.copy2(PARQUET_PATH, p_bak)
        logger.info(f"Parquet cache backed up to: {p_bak}")
    if os.path.exists(PAYSUITE_PAYOUTS_PARQUET_PATH):
        shutil.copy2(PAYSUITE_PAYOUTS_PARQUET_PATH, f"{PAYSUITE_PAYOUTS_PARQUET_PATH}.bak_paysuite_{now_tag}")
    return backup_path


def main():
    parser = argparse.ArgumentParser(description="Access PaySuite 2026+ Migration & Audit")
    parser.add_argument("--apply", action="store_true", help="Apply migration (writes to DB and Parquet)")
    parser.add_argument("--company", default="rethink", help="Target company ID (default: rethink)")
    args = parser.parse_args()

    audit = generate_migration_audit(company_id=args.company)
    print_audit_report(audit)

    if not args.apply:
        print(">> DRY RUN COMPLETED. No database changes were made.")
        print(">> To apply this migration, run: python -m core.paysuite_migration --apply\n")
        return

    print(">> EXECUTING MIGRATION (--apply enabled)...")
    backup_path = backup_database()

    try:
        # Approve the CRM switch-over, then run the full backfill starting from 2026-01-01
        set_sync_state(f"crm_apply_approved_{args.company}", "true")
        set_sync_state(f"crm_reconciled_{args.company}", "false")
        res = sync_paysuite_payments(from_date=HISTORICAL_CUTOFF_DATE, company_id=args.company, is_backfill=True)
        print("\n" + "=" * 70)
        print("MIGRATION APPLIED SUCCESSFULLY!")
        print("=" * 70)
        print(f"Payments Ingested     : {res.get('total_fetched', 0)}")
        print(f"New Payments          : {res.get('new_payments', 0)}")
        print(f"Updated Payments      : {res.get('updated_payments', 0)}")
        crm_res = res.get("crm_reconciliation", {})
        print(f"CRM Donations Added   : {crm_res.get('donations_added', 0)}")
        print(f"Payout Lines Updated  : {crm_res.get('payouts_updated', 0)}")
        print(f"Database Backup Path  : {backup_path}")
        print("=" * 70 + "\n")
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        print(f"\n[ERROR] Migration failed: {e}")
        print(f"[RECOVERY] You can restore the database from: {backup_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
