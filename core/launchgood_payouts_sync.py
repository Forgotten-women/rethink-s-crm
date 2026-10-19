"""
LaunchGood Payouts & Transfers Ingestion Engine
-----------------------------------------------
Automates ingestion of bank payout transfers and campaign allocations from LaunchGood v4 API:
  1. Calls POST /api/account/transfers with charity's Account ID.
  2. Extracts bank transfer IDs, settlement amounts, and complete fee breakdown.
  3. Maps campaign-level disbursements (campaigns[] array).
  4. Stores transfer records in SQLite and refreshes payouts_cache.parquet.
  5. Strictly isolated per charity ('rethink' vs 'iqra').
"""
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from config.settings import LOCAL_DB_PATH, PAYOUTS_PARQUET_PATH
from core.data_processor import invalidate_payouts_cache
from core.database import get_db_connection
from core.event_log import log_event
from core.launchgood_client import LaunchGoodClient

logger = logging.getLogger("launchgood_payouts_sync")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [launchgood_payouts_sync] %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


def init_launchgood_payout_tables() -> None:
    """Ensures database tables exist for LaunchGood API bank payout transfers."""
    conn = get_db_connection(timeout=15.0)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS launchgood_api_transfers (
                transfer_id TEXT PRIMARY KEY,
                company_id TEXT DEFAULT 'rethink',
                account_id INTEGER,
                status TEXT,
                currency TEXT DEFAULT 'GBP',
                sent_at TEXT,
                from_date TEXT,
                to_date TEXT,
                gross_amount REAL,
                gross_count INTEGER,
                processing_fees REAL,
                non_processing_fees REAL,
                chargeback_amount REAL,
                refund_amount REAL,
                net_sales REAL,
                disbursement_amount REAL,
                campaigns_json TEXT,
                synced_at TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


def sync_launchgood_payout_transfers(company_id: str = "rethink") -> Dict[str, Any]:
    """
    Fetches completed bank transfers from LaunchGood API and records them into SQLite.
    Strictly scoped to the given charity.
    """
    company_id = str(company_id or "rethink").strip().lower()
    logger.info(f"Syncing LaunchGood payout transfers for charity '{company_id}'...")

    client = LaunchGoodClient(company_id=company_id)
    if not client.is_configured():
        msg = f"LaunchGood is not connected for '{company_id}'. Please configure session tokens."
        logger.warning(msg)
        return {"status": "skipped", "reason": msg, "company_id": company_id}

    init_launchgood_payout_tables()
    transfers = client.get_account_transfers()
    if not transfers:
        logger.info(f"No transfers returned for {company_id}.")
        return {"status": "success", "company_id": company_id, "new_transfers": 0}

    conn = get_db_connection(timeout=15.0)
    try:
        cursor = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        synced_count = 0

        for t in transfers:
            t_id = str(t.get("id") or "").strip()
            if not t_id:
                continue

            status = str(t.get("status") or "")
            curr = str(t.get("currency") or "GBP").upper()
            sent_at = str(t.get("sent") or "")
            from_dt = str(t.get("from") or "")
            to_dt = str(t.get("to") or "")

            gross = float(t.get("gross_amount") or 0.0)
            gross_cnt = int(t.get("gross_count") or 0)
            p_fees = float(t.get("processing_fees_amount") or 0.0)
            np_fees = float(t.get("non_processing_fees_amount") or 0.0)
            cb = float(t.get("chargeback_amount") or 0.0)
            ref = float(t.get("refund_amount") or 0.0)
            net_sales = float(t.get("net_sales_amount") or 0.0)
            disb = float(t.get("total_disbursement_amount") or 0.0)
            camp_json = json.dumps(t.get("campaigns") or [])

            cursor.execute("""
                INSERT INTO launchgood_api_transfers (
                    transfer_id, company_id, account_id, status, currency, sent_at,
                    from_date, to_date, gross_amount, gross_count, processing_fees,
                    non_processing_fees, chargeback_amount, refund_amount, net_sales,
                    disbursement_amount, campaigns_json, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(transfer_id) DO UPDATE SET
                    status = excluded.status,
                    sent_at = excluded.sent_at,
                    disbursement_amount = excluded.disbursement_amount,
                    campaigns_json = excluded.campaigns_json,
                    synced_at = excluded.synced_at
            """, (
                t_id, company_id, client.account_id, status, curr, sent_at,
                from_dt, to_dt, gross, gross_cnt, p_fees,
                np_fees, cb, ref, net_sales,
                disb, camp_json, now_iso
            ))
            synced_count += 1

        conn.commit()
        logger.info(f"Recorded {synced_count} LaunchGood transfers for {company_id}.")
        invalidate_payouts_cache(company_id)

        log_event(
            "launchgood.payouts_synced",
            category="payouts",
            level="info",
            company_id=company_id,
            message=f"Synced {synced_count} LaunchGood payout transfers for {company_id}."
        )

        return {
            "status": "success",
            "company_id": company_id,
            "transfers_synced": synced_count,
            "timestamp": now_iso
        }
    finally:
        conn.close()
