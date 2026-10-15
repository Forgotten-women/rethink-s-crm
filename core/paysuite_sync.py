"""
Access PaySuite (DDCMS v3) Direct Debit Synchronization Engine.

Implements Phase 1 of the Access PaySuite Automation Architecture:
1. Raw ledger tables in SQLite (launchgood_donations.db):
   - paysuite_payments
   - paysuite_contracts
   - paysuite_customers (NEVER stores bank account or sort code details)
   - paysuite_disbursals
   - paysuite_sync_state
2. Ingests payments from the API (incremental 30-day rolling window + 2026+ backfill).
3. Enriches donor KYC and contract Gift Aid status per CustomerId / ContractId.
4. Synchronizes to CRM donations table (one per collection, 2026-01-01 onwards).
5. Handles ARUDD failed debits as audit-compliant reversals.
6. Rebuilds paysuite_payout_settlements with genuine DisbursalId batching.
"""
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

from config.settings import (
    LOCAL_DB_PATH,
    PARQUET_PATH,
    PAYSUITE_PAYOUTS_PARQUET_PATH,
)
from core.database import get_db_connection, _DB_LOCK
from core.data_processor import (
    atomic_write_parquet,
    sanitize_df_dtypes_for_parquet,
    invalidate_data_cache,
    invalidate_paysuite_payouts_cache,
)
from core.paysuite_client import get_paysuite_client, PaySuiteClient, PaySuiteAPIError
from core.utils import classify_donor_amount

logger = logging.getLogger("paysuite_sync")

HISTORICAL_CUTOFF_DATE = "2026-01-01"
ROLLING_WINDOW_DAYS = 30
POLL_INTERVAL_SEC = 3600
POLL_RETRY_SEC = 600
PLATFORM = "Paysuite"
SOURCE = "Paysuite Direct Debit"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_date(dt_str: Optional[str]) -> str:
    if not dt_str:
        return ""
    try:
        # Handles 2026-10-01T00:00:00 or 2026-10-01
        clean = str(dt_str).strip()
        if "T" in clean:
            return clean.split("T")[0]
        if " " in clean:
            return clean.split(" ")[0]
        return clean[:10]
    except Exception:
        return str(dt_str)[:10]


def init_paysuite_tables(conn: Optional[sqlite3.Connection] = None) -> None:
    """Initializes raw PaySuite ledger tables with strict isolation and indexing."""
    should_close = False
    if conn is None:
        conn = get_db_connection(timeout=30.0)
        should_close = True

    try:
        with conn:
            # 1. Raw Payments Ledger
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paysuite_payments (
                    id TEXT PRIMARY KEY,
                    contract_id TEXT,
                    customer_id TEXT,
                    direct_debit_reference TEXT,
                    amount REAL,
                    amount_pence INTEGER,
                    collection_date TEXT,
                    date_of_collection TEXT,
                    status TEXT,
                    type TEXT,
                    method TEXT,
                    is_credit INTEGER DEFAULT 0,
                    is_scheduled INTEGER DEFAULT 1,
                    disbursal_id TEXT,
                    submission_file_id TEXT,
                    rejection_reason TEXT,
                    created_at TEXT,
                    first_seen_at TEXT,
                    updated_at TEXT,
                    company_id TEXT NOT NULL DEFAULT 'rethink'
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_psp_company_date ON paysuite_payments(company_id, collection_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_psp_customer ON paysuite_payments(customer_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_psp_contract ON paysuite_payments(contract_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_psp_disbursal ON paysuite_payments(disbursal_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_psp_reference ON paysuite_payments(direct_debit_reference)")

            # 2. Raw Contracts Ledger
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paysuite_contracts (
                    id TEXT PRIMARY KEY,
                    customer_id TEXT,
                    direct_debit_reference TEXT,
                    schedule_name TEXT,
                    description TEXT,
                    amount REAL,
                    is_gift_aid INTEGER DEFAULT 0,
                    status TEXT,
                    start_date TEXT,
                    next_collection_date TEXT,
                    first_seen_at TEXT,
                    updated_at TEXT,
                    company_id TEXT NOT NULL DEFAULT 'rethink'
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_psc_customer ON paysuite_contracts(customer_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_psc_reference ON paysuite_contracts(direct_debit_reference)")

            # 3. Raw Customers (KYC) Ledger - NEVER stores BankDetail
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paysuite_customers (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    first_name TEXT,
                    surname TEXT,
                    email TEXT,
                    phone TEXT,
                    address_line1 TEXT,
                    address_line2 TEXT,
                    address_line3 TEXT,
                    postcode TEXT,
                    first_seen_at TEXT,
                    updated_at TEXT,
                    company_id TEXT NOT NULL DEFAULT 'rethink'
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pscust_email ON paysuite_customers(email)")

            # 4. Raw Disbursals Ledger
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paysuite_disbursals (
                    id TEXT PRIMARY KEY,
                    disbursal_date TEXT,
                    total_amount REAL DEFAULT 0.0,
                    payment_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'Disbursed',
                    first_seen_at TEXT,
                    updated_at TEXT,
                    company_id TEXT NOT NULL DEFAULT 'rethink'
                )
            """)

            # Bank side of each disbursal: PaySuite's own "Auto disbursal" credit (IsCredit payment) for the batch
            existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(paysuite_disbursals)")}
            for col, col_type in (("bank_amount", "REAL"), ("bank_date", "TEXT"), ("bank_credit_id", "TEXT"),
                                  ("unpaid_amount", "REAL DEFAULT 0.0"), ("unpaid_count", "INTEGER DEFAULT 0")):
                if col not in existing_cols:
                    conn.execute(f"ALTER TABLE paysuite_disbursals ADD COLUMN {col} {col_type}")

            # 5. Sync State
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paysuite_sync_state (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT
                )
            """)
    finally:
        if should_close:
            conn.close()


_tables_ready = False


def _ensure_tables() -> None:
    """Creates the ledger tables once per process. Everything that reads them (the poller's backfill check, the
    Ops status card, the Payouts endpoints) used to run before the sync had ever created them -> 500s."""
    global _tables_ready
    if not _tables_ready:
        init_paysuite_tables()
        _tables_ready = True


def _rejection_text(rejection: Any) -> str:
    """The API's "Rejection" is empty or an object; keep a readable reason."""
    if not rejection:
        return ""
    if isinstance(rejection, dict):
        parts = [str(rejection.get(k)).strip() for k in ("Code", "Reason", "Description", "Message") if rejection.get(k)]
        return " - ".join(parts) or str(rejection)
    return str(rejection)


def _s(value: Any) -> str:
    """Text from a DB/pandas value; NULL/NaN (e.g. a payment whose customer isn't loaded yet) -> ""."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def get_sync_state(key: str, default: Optional[str] = None) -> Optional[str]:
    _ensure_tables()
    conn = get_db_connection(timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM paysuite_sync_state WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else default
    finally:
        conn.close()


def set_sync_state(key: str, value: str) -> None:
    _ensure_tables()
    conn = get_db_connection(timeout=10.0)
    try:
        with conn:
            conn.execute("""
                INSERT INTO paysuite_sync_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """, (key, str(value), _now_iso()))
    finally:
        conn.close()


# -----------------------------------------------------------------------------
# Classification Helper
# -----------------------------------------------------------------------------

def resolve_mandate_classification(
    conn: sqlite3.Connection,
    reference: str,
    donor_email: Optional[str] = None,
    company_id: str = "rethink",
) -> Dict[str, str]:
    """
    Resolves classification for a mandate reference.
    1. Check paysuite_classifications view for exact direct_debit_reference.
    2. Check donor history: if donor previously gave to a classified fund/mandate.
    3. If unknown, register into platform_campaign_mappings as UNASSIGNED so it surfaces on Needs Classification.
    """
    comp = str(company_id or "rethink").lower().strip()
    clean_ref = str(reference or "").strip()
    if not clean_ref:
        return {"code": "Unassigned", "heading": "Unassigned", "sub_heading": "Unassigned", "country": "Unassigned", "zakat_eligibility": "Non-Zakat"}

    cur = conn.cursor()

    # 1. Exact reference in paysuite_classifications
    cur.execute("""
        SELECT code, heading, sub_heading, country, zakat_eligibility 
        FROM paysuite_classifications 
        WHERE LOWER(campaign_name) = LOWER(?) AND LOWER(COALESCE(company_id, 'rethink')) = ?
        LIMIT 1
    """, (clean_ref, comp))
    row = cur.fetchone()
    if row and row[0] and row[0].upper() not in ("", "UNASSIGNED", "NONE", "NAN", "NULL"):
        return {
            "code": row[0],
            "heading": row[1] or "Unassigned",
            "sub_heading": row[2] or "Unassigned",
            "country": row[3] or "ALL",
            "zakat_eligibility": row[4] or "Non-Zakat",
        }

    # 2. Donor history fallback (if donor has another classified gift)
    if donor_email and donor_email.strip():
        cur.execute("""
            SELECT "Code", "Heading", "Sub-Heading", "Country", "Zakat Eligibility"
            FROM donations
            WHERE LOWER(Email) = LOWER(?) AND LOWER(COALESCE(company_id, 'rethink')) = ?
              AND "Code" IS NOT NULL AND UPPER("Code") NOT IN ('', 'UNASSIGNED', 'NONE', 'NAN', 'NULL')
            ORDER BY "Created Date (UTC)" DESC LIMIT 1
        """, (donor_email.strip(), comp))
        d_row = cur.fetchone()
        if d_row and d_row[0]:
            return {
                "code": d_row[0],
                "heading": d_row[1] or "Unassigned",
                "sub_heading": d_row[2] or "Unassigned",
                "country": d_row[3] or "ALL",
                "zakat_eligibility": d_row[4] or "Non-Zakat",
            }

    # 3. Not classified: register into platform_campaign_mappings as UNASSIGNED if not exists
    cur.execute("""
        INSERT OR IGNORE INTO platform_campaign_mappings (
            platform, company_id, campaign_name, giving_level, code, is_primary, community_name
        ) VALUES ('paysuite', ?, ?, '', 'Unassigned', 1, 'PaySuite Direct Debit')
    """, (comp, clean_ref))

    return {
        "code": "Unassigned",
        "heading": "Unassigned",
        "sub_heading": "Unassigned",
        "country": "ALL",
        "zakat_eligibility": "Non-Zakat",
    }


# -----------------------------------------------------------------------------
# Customer & Contract Ingestion
# -----------------------------------------------------------------------------

def ensure_customers_and_contracts(
    client: PaySuiteClient,
    conn: sqlite3.Connection,
    customer_ids: Set[str],
    company_id: str = "rethink",
) -> None:
    """Fetches customer KYC and contracts for newly discovered or stale customer IDs."""
    if not customer_ids:
        return

    cur = conn.cursor()
    # Find which ones are already present and fresh (< 7 days old)
    placeholders = ",".join(["?"] * len(customer_ids))
    cur.execute(f"""
        SELECT id, updated_at FROM paysuite_customers
        WHERE id IN ({placeholders}) AND company_id = ?
    """, list(customer_ids) + [company_id])
    existing_map = {r[0]: r[1] for r in cur.fetchall()}

    now_dt = datetime.now(timezone.utc)
    stale_or_missing = set()
    for cid in customer_ids:
        if cid not in existing_map:
            stale_or_missing.add(cid)
        else:
            try:
                up_dt = datetime.fromisoformat(existing_map[cid].replace("Z", "+00:00"))
                if (now_dt - up_dt).days >= 7:
                    stale_or_missing.add(cid)
            except Exception:
                stale_or_missing.add(cid)

    if not stale_or_missing:
        return

    logger.info(f"[PaySuite] Fetching KYC & contracts for {len(stale_or_missing)} customer(s)...")

    for cid in stale_or_missing:
        try:
            cust_data = client.get_customer(cid)
            if cust_data:
                addr = cust_data.get("AddressDetail") or {}
                # EXPLICIT SECURITY CHECK: BankDetail is completely discarded, never saved
                conn.execute("""
                    INSERT INTO paysuite_customers (
                        id, title, first_name, surname, email, phone,
                        address_line1, address_line2, address_line3, postcode,
                        first_seen_at, updated_at, company_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        first_name = excluded.first_name,
                        surname = excluded.surname,
                        email = excluded.email,
                        phone = excluded.phone,
                        address_line1 = excluded.address_line1,
                        address_line2 = excluded.address_line2,
                        address_line3 = excluded.address_line3,
                        postcode = excluded.postcode,
                        updated_at = excluded.updated_at
                """, (
                    cid,
                    cust_data.get("Title") or "",
                    cust_data.get("FirstName") or "",
                    cust_data.get("Surname") or "",
                    cust_data.get("Email") or "",
                    cust_data.get("HomePhoneNumber") or cust_data.get("MobilePhoneNumber") or "",
                    addr.get("Line1") or "",
                    addr.get("Line2") or "",
                    addr.get("Line3") or "",
                    addr.get("PostCode") or "",
                    _now_iso(),
                    _now_iso(),
                    company_id
                ))

            contracts = client.get_customer_contracts(cid)
            for c in contracts:
                contract_id = c.get("Id")
                if not contract_id:
                    continue
                is_ga = 1 if bool(c.get("IsGiftAid")) else 0
                amount_val = float(c.get("Amount") or 0.0)
                conn.execute("""
                    INSERT INTO paysuite_contracts (
                        id, customer_id, direct_debit_reference, schedule_name,
                        description, amount, is_gift_aid, status,
                        start_date, next_collection_date, first_seen_at, updated_at, company_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        direct_debit_reference = excluded.direct_debit_reference,
                        schedule_name = excluded.schedule_name,
                        description = excluded.description,
                        amount = excluded.amount,
                        is_gift_aid = excluded.is_gift_aid,
                        status = excluded.status,
                        next_collection_date = excluded.next_collection_date,
                        updated_at = excluded.updated_at
                """, (
                    contract_id,
                    cid,
                    c.get("DirectDebitReference") or "",
                    c.get("ScheduleName") or "",
                    c.get("Description") or "",
                    amount_val,
                    is_ga,
                    c.get("Status") or "Active",
                    _format_date(c.get("Start") or c.get("StartDate")),
                    _format_date(c.get("NextPaymentDate")),
                    _now_iso(),
                    _now_iso(),
                    company_id
                ))

            # Small pause between customer lookups to be courteous to API
            time.sleep(0.05)
        except Exception as e:
            logger.warning(f"[PaySuite] Error fetching customer {cid}: {e}")


def _link_disbursal_credits(conn: sqlite3.Connection, comp: str) -> None:
    """Pairs each disbursal batch with the payout credit PaySuite sent to the bank for it: the first unused
    credit dated on/after the batch's collection date, within 35 days. The credit IDs don't reference the
    batch, so this is by date; the amounts are then compared (adds up = Paid total equals the credit)."""
    credits = conn.execute("""
        SELECT id, collection_date, amount FROM paysuite_payments
        WHERE company_id = ? AND COALESCE(is_credit, 0) = 1 AND status = 'Paid'
        ORDER BY collection_date
    """, (comp,)).fetchall()
    batches = conn.execute("""
        SELECT d.id, MIN(p.collection_date) FROM paysuite_disbursals d
        JOIN paysuite_payments p ON p.disbursal_id = d.id AND p.company_id = d.company_id
        WHERE d.company_id = ? GROUP BY d.id ORDER BY 2
    """, (comp,)).fetchall()
    used = set()
    for batch_id, collected_on in batches:
        try:
            c_day = datetime.fromisoformat(str(collected_on)[:10])
        except ValueError:
            continue
        match = None
        for credit_id, credit_on, amount in credits:
            if credit_id in used:
                continue
            try:
                gap = (datetime.fromisoformat(str(credit_on)[:10]) - c_day).days
            except ValueError:
                continue
            if 0 <= gap <= 35:
                match = (credit_id, credit_on, amount)
                break
        if match:
            used.add(match[0])
        conn.execute("UPDATE paysuite_disbursals SET bank_credit_id = ?, bank_date = ?, bank_amount = ? WHERE id = ? AND company_id = ?",
                     (match[0] if match else None, match[1] if match else None, match[2] if match else None, batch_id, comp))


# -----------------------------------------------------------------------------
# Sync Pipeline: Ingest Payments & Rebuild Ledgers
# -----------------------------------------------------------------------------

def sync_paysuite_payments(
    from_date: Optional[str] = None,
    company_id: str = "rethink",
    is_backfill: bool = False,
    page_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Fetches payments from Access PaySuite API and updates raw ledger tables.
    Returns summary stats of new and updated records.
    """
    comp = str(company_id or "rethink").lower().strip()
    client = get_paysuite_client()
    if not client.is_configured():
        return {"status": "error", "message": "Access PaySuite credentials not configured in environment."}

    _ensure_tables()

    # Determine date range
    if not from_date:
        if is_backfill:
            from_date = HISTORICAL_CUTOFF_DATE
        else:
            cutoff = datetime.now(timezone.utc) - timedelta(days=ROLLING_WINDOW_DAYS)
            from_date = cutoff.strftime("%Y-%m-%d")

    logger.info(f"[PaySuite] Starting sync from {from_date} (company: {comp}, backfill: {is_backfill})...")

    conn = get_db_connection(timeout=60.0)
    seen_customers: Set[str] = set()
    total_fetched = 0
    new_payments = 0
    updated_payments = 0

    try:
        cur = conn.cursor()
        cur.execute("SELECT id, status, disbursal_id FROM paysuite_payments WHERE company_id = ?", (comp,))
        existing_payments = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

        payment_rows = []
        for p in client.iter_all_payments(from_date=from_date, page_size=100, max_pages=page_limit):
            total_fetched += 1
            p_id = p.get("Id")
            if not p_id:
                continue

            cust_id = p.get("CustomerId")
            if cust_id:
                seen_customers.add(cust_id)

            amt_pence = int(p.get("Amount") or 0)
            amt_pounds = round(amt_pence / 100.0, 2)
            raw_cdate = p.get("CollectionDate") or p.get("DateOfCollection")
            cdate_iso = _format_date(raw_cdate)
            status_val = p.get("Status") or "Paid"
            disbursal_id = p.get("DisbursalId") or ""

            if p_id in existing_payments:
                prev_status, prev_disb = existing_payments[p_id]
                if prev_status != status_val or prev_disb != disbursal_id:
                    updated_payments += 1
            else:
                new_payments += 1

            payment_rows.append((
                p_id,
                p.get("ContractId") or "",
                cust_id or "",
                p.get("DirectDebitReference") or "",
                amt_pounds,
                amt_pence,
                cdate_iso,
                raw_cdate or cdate_iso,
                status_val,
                p.get("Type") or "Regular",
                p.get("Method") or "BACS",
                1 if p.get("IsCredit") else 0,
                1 if p.get("IsScheduled") else 0,
                disbursal_id,
                p.get("SubmissionFileId") or "",
                _rejection_text(p.get("Rejection") or p.get("RejectionReason")),
                p.get("CreatedAt") or _now_iso(),
                _now_iso(),
                _now_iso(),
                comp
            ))

        # Batch upsert payments
        if payment_rows:
            with conn:
                conn.executemany("""
                    INSERT INTO paysuite_payments (
                        id, contract_id, customer_id, direct_debit_reference,
                        amount, amount_pence, collection_date, date_of_collection,
                        status, type, method, is_credit, is_scheduled,
                        disbursal_id, submission_file_id, rejection_reason,
                        created_at, first_seen_at, updated_at, company_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        contract_id = excluded.contract_id,
                        customer_id = excluded.customer_id,
                        direct_debit_reference = excluded.direct_debit_reference,
                        amount = excluded.amount,
                        amount_pence = excluded.amount_pence,
                        collection_date = excluded.collection_date,
                        date_of_collection = excluded.date_of_collection,
                        status = excluded.status,
                        disbursal_id = excluded.disbursal_id,
                        submission_file_id = excluded.submission_file_id,
                        rejection_reason = excluded.rejection_reason,
                        updated_at = excluded.updated_at
                """, payment_rows)

        # Ingest Customers & Contracts for newly discovered IDs
        ensure_customers_and_contracts(client, conn, seen_customers, company_id=comp)

        # Re-aggregate Disbursals table. A batch pays out only its Paid collections (Unpaid ones keep the
        # DisbursalId but are not in the money sent), verified month by month against PaySuite's credits.
        with conn:
            conn.execute("""
                INSERT INTO paysuite_disbursals (id, disbursal_date, total_amount, payment_count, unpaid_amount, unpaid_count,
                                                 status, first_seen_at, updated_at, company_id)
                SELECT
                    disbursal_id,
                    MAX(collection_date) as disbursal_date,
                    ROUND(SUM(CASE WHEN status = 'Paid' THEN amount ELSE 0 END), 2) as total_amount,
                    SUM(CASE WHEN status = 'Paid' THEN 1 ELSE 0 END) as payment_count,
                    ROUND(SUM(CASE WHEN status != 'Paid' THEN amount ELSE 0 END), 2) as unpaid_amount,
                    SUM(CASE WHEN status != 'Paid' THEN 1 ELSE 0 END) as unpaid_count,
                    'Disbursed' as status,
                    MIN(first_seen_at) as first_seen_at,
                    MAX(updated_at) as updated_at,
                    company_id
                FROM paysuite_payments
                WHERE disbursal_id IS NOT NULL AND TRIM(disbursal_id) != '' AND company_id = ? AND COALESCE(is_credit, 0) = 0
                GROUP BY disbursal_id, company_id
                ON CONFLICT(id) DO UPDATE SET
                    disbursal_date = excluded.disbursal_date,
                    total_amount = excluded.total_amount,
                    payment_count = excluded.payment_count,
                    unpaid_amount = excluded.unpaid_amount,
                    unpaid_count = excluded.unpaid_count,
                    updated_at = excluded.updated_at
            """, (comp,))
            _link_disbursal_credits(conn, comp)

        set_sync_state("last_sync_at", _now_iso())
        if is_backfill and total_fetched > 0:
            set_sync_state("backfill_completed", "true")

    finally:
        conn.close()

    # Rebuild the CRM rows only when the ledger changed (it rewrites donations + the payouts copy and clears
    # every data cache, so doing it on an unchanged ledger slows the whole app down for nothing).
    # Plan 1.5: the CRM rows are switched over only after the dry run is approved (core.paysuite_migration
    # --apply sets this). Until then the sync only keeps the PaySuite ledger tables current.
    if get_sync_state(f"crm_apply_approved_{comp}") != "true":
        reconcile_summary = {"skipped": "awaiting approval (run: venv/bin/python -m core.paysuite_migration --apply)"}
    elif new_payments or updated_payments or is_backfill or get_sync_state(f"crm_reconciled_{comp}") != "true":
        reconcile_summary = reconcile_paysuite_to_crm(company_id=comp)
        set_sync_state(f"crm_reconciled_{comp}", "true")
    else:
        reconcile_summary = {"skipped": "ledger unchanged"}

    return {
        "status": "success",
        "from_date": from_date,
        "total_fetched": total_fetched,
        "new_payments": new_payments,
        "updated_payments": updated_payments,
        "unique_customers": len(seen_customers),
        "crm_reconciliation": reconcile_summary,
        "synced_at": _now_iso(),
    }


# -----------------------------------------------------------------------------
# Reconcile PaySuite Ledger to CRM `donations` and `paysuite_payout_settlements`
# -----------------------------------------------------------------------------

def reconcile_paysuite_to_crm(company_id: str = "rethink") -> Dict[str, Any]:
    """
    Synchronizes the local raw PaySuite ledger into:
    1. `paysuite_payout_settlements` table & parquet cache (with real DisbursalId batching for 2026+).
    2. `donations` table (one row per successful collection in 2026+).
    3. Handles ARUDD returned/failed debits as negative reversals.
    """
    comp = str(company_id or "rethink").lower().strip()
    conn = get_db_connection(timeout=60.0)

    try:
        # Load all 2026+ payments with customer and contract details
        query_2026 = """
            SELECT 
                p.id as payment_id,
                p.contract_id,
                p.customer_id,
                p.direct_debit_reference,
                p.amount,
                p.collection_date,
                p.date_of_collection,
                p.status,
                p.disbursal_id,
                p.rejection_reason,
                p.created_at,
                c.title,
                c.first_name,
                c.surname,
                c.email,
                c.phone,
                c.address_line1,
                c.address_line2,
                c.address_line3,
                c.postcode,
                ct.is_gift_aid,
                ct.description as contract_desc,
                ct.schedule_name
            FROM paysuite_payments p
            LEFT JOIN paysuite_customers c ON p.customer_id = c.id AND c.company_id = p.company_id
            LEFT JOIN paysuite_contracts ct ON p.contract_id = ct.id AND ct.company_id = p.company_id
            WHERE p.collection_date >= ? AND p.company_id = ? AND COALESCE(p.is_credit, 0) = 0
            ORDER BY p.collection_date ASC
        """
        payments_df = pd.read_sql_query(query_2026, conn, params=(HISTORICAL_CUTOFF_DATE, comp))

        if payments_df.empty:
            return {"donations_added": 0, "payouts_updated": 0}

        # Build records for paysuite_payout_settlements (Payouts view)
        payout_rows = []
        crm_donation_rows = []
        only_donation_keys: Set[Tuple[str, str]] = set()

        for _, r in payments_df.iterrows():
            pid = _s(r["payment_id"])
            ref = _s(r["direct_debit_reference"])
            amt = float(pd.to_numeric(r["amount"], errors="coerce") or 0.0) if _s(r["amount"]) else 0.0
            cdate = _format_date(r["collection_date"])
            status_raw = _s(r["status"]) or "Paid"
            disb_id = _s(r["disbursal_id"])
            first = _s(r["first_name"])
            last = _s(r["surname"])
            disp_name = f"{first} {last}".strip()
            email = _s(r["email"])
            phone = _s(r["phone"])
            addr_parts = [_s(p) for p in [r["address_line1"], r["address_line2"], r["address_line3"]] if _s(p)]
            full_addr = ", ".join(addr_parts)
            postcode = _s(r["postcode"])
            is_ga = "Yes" if r["is_gift_aid"] in (1, True, "1", "true") else "No"

            # Batch Label: Real Disbursal ID for 2026+ collections
            batch_id = disb_id if disb_id else f"{cdate[:7]}"
            # Shown as the collection month ("October 2026 Collection", like the uploaded months); the DisbursalId
            # stays in Transfer ID for matching. Not yet disbursed -> "(pending)".
            month_name = datetime.strptime(cdate[:7], "%Y-%m").strftime("%B %Y") if len(cdate) >= 7 else cdate
            batch_label = f"{month_name} Collection" if disb_id else f"{month_name} Collection (pending)"

            # Classification
            cls = resolve_mandate_classification(conn, ref, donor_email=email, company_id=comp)

            # --- A. Payout Settlement Entry ---
            payout_rows.append({
                "Bank Ref": ref,
                "Customer Ref": _s(r["customer_id"]),
                "Donation ID": pid,
                "Campaign Name": ref,
                "Display Name": disp_name,
                "First Name": first,
                "Last Name": last,
                "Email": email,
                "Phone": phone,
                "Address": full_addr,
                "Postcode": postcode,
                "Donation Amount": amt,
                "Gross Amount": amt,
                "Net Amount": amt,
                "Total Online Donation Gross Amount in Settled Currency": amt,
                "Total Processing Fees Paid by CC In Settled Currency": 0.0,
                "Total Online Donations Net Amount in Settled Currency": amt,
                "Date of collection": cdate,
                "Created Date (UTC)": cdate,
                "Created Time (UTC)": "00:00:00",
                "Due": cdate,
                "Transfer ID": batch_id,
                "Batch Label": batch_label,
                "Collection Month": datetime.strptime(cdate[:7], "%Y-%m").strftime("%B %Y") if len(cdate) >= 7 else "Collection",
                "Platform": PLATFORM,
                "Source": SOURCE,
                "Status": status_raw,
                "Heading": cls["heading"],
                "Sub-Heading": cls["sub_heading"],
                "Country": cls["country"],
                "Code": cls["code"],
                "Zakat Eligibility": cls["zakat_eligibility"],
                "Payment Frequency": "Monthly",
                "Gift Aid": is_ga,
                "Comments": _s(r["rejection_reason"]),
                "company_id": comp,
            })

            # --- B. CRM Donations Table Entry ---
            # Paid -> the gift. Returned (ARUDD) -> the gift marked FAILED plus a negative reversal (C), so it
            # nets to zero; totals add every row regardless of Status, so the reversal alone would show -amount.
            returned = status_raw.lower() in ("unpaid", "rejected", "failed")
            if status_raw.lower() == "paid" or returned:
                crm_donation_rows.append({
                    "Donation ID": pid,
                    "Created Date (UTC)": cdate,
                    "Created Time (UTC)": "00:00:00",
                    "Settled Date (UTC)": cdate,
                    "Created At": f"{cdate} 00:00:00",
                    "_parsed_date": cdate,
                    "Status": "FAILED" if returned else "COMPLETED",
                    "Transaction Type": "Donation",
                    "Offline or online donation": "online",
                    "First Name": first,
                    "Last Name": last,
                    "Display Name": disp_name,
                    "Billing Name": disp_name,
                    "Email": email,
                    "Email (for tax receipt)": email,
                    "Phone Number": phone,
                    "Billing Address": full_addr,
                    "Billing Zip": postcode,
                    "Gift Aid (yes or no)": is_ga,
                    "Gift Aid?": is_ga,
                    "Zakat (yes or no)": "Yes" if cls["zakat_eligibility"] == "Zakat" else "No",
                    "Zakat Status": cls["zakat_eligibility"],
                    "Anonymous or Public": "Public",
                    "Donation Currency (DC)": "GBP",
                    "Currency": "GBP",
                    "Settlement Currency": "GBP",
                    "Project Currency": "GBP",
                    "Donation Amount (in Donation Currency)": str(amt),
                    "Donation Amount in Project Currency (May be approx.)": str(amt),
                    "Amount": amt,
                    "Total Online Donation Gross Amount in Settled Currency": str(amt),
                    "Total Processing Fees Paid by CC In Settled Currency": 0.0,
                    "Total Online Donations Net Amount in Settled Currency": amt,
                    "fee_amount": "0.0",
                    "Campaign Name": ref,
                    "Giving Level Title": "",
                    "Comments": _s(r["contract_desc"]),
                    "Payment Type": "Direct Debit / PaySuite",
                    "Payment Frequency": "Recurring Payment",
                    "Subscription Type": "Direct Debit",
                    "Platform": PLATFORM,
                    "Source": SOURCE,
                    "gateway": "paysuite",
                    "Customer Ref": _s(r["customer_id"]),
                    "Bank Ref": ref,
                    "Transfer ID": batch_id,
                    "Payout Settled": "Yes" if disb_id and not returned else "No",
                    "Donation Payout Flag": "Paid" if disb_id and not returned else "Unpaid",
                    "Donor ID": email or pid,
                    "Total LTV": amt,
                    "Lifetime Donor Classification": classify_donor_amount(amt),
                    "Transaction Donor Classification": classify_donor_amount(amt),
                    "Code": cls["code"],
                    "New Code": cls["code"],
                    "Heading": cls["heading"],
                    "Sub-Heading": cls["sub_heading"],
                    "Department": cls["heading"],
                    "Office": cls["sub_heading"],
                    "Country": cls["country"],
                    "Target Country": cls["country"],
                    "Zakat Eligibility": cls["zakat_eligibility"],
                    "company_id": comp,
                })
                only_donation_keys.add((comp, pid))

            # --- C. ARUDD Reversal Entry (for Failed/Returned debits) ---
            if returned:
                reversal_pid = f"{pid}_reversal"
                crm_donation_rows.append({
                    "Donation ID": reversal_pid,
                    "Created Date (UTC)": cdate,
                    "Created Time (UTC)": "00:00:00",
                    "Settled Date (UTC)": cdate,
                    "Created At": f"{cdate} 00:00:00",
                    "_parsed_date": cdate,
                    "Status": "COMPLETED",
                    "Transaction Type": "Refund",
                    "Offline or online donation": "online",
                    "First Name": first,
                    "Last Name": last,
                    "Display Name": disp_name,
                    "Billing Name": disp_name,
                    "Email": email,
                    "Email (for tax receipt)": email,
                    "Phone Number": phone,
                    "Billing Address": full_addr,
                    "Billing Zip": postcode,
                    "Gift Aid (yes or no)": "No",
                    "Gift Aid?": "No",
                    "Zakat (yes or no)": "No",
                    "Zakat Status": "Non-Zakat",
                    "Anonymous or Public": "Public",
                    "Donation Currency (DC)": "GBP",
                    "Currency": "GBP",
                    "Settlement Currency": "GBP",
                    "Project Currency": "GBP",
                    "Donation Amount (in Donation Currency)": str(-amt),
                    "Donation Amount in Project Currency (May be approx.)": str(-amt),
                    "Amount": -amt,
                    "Total Online Donation Gross Amount in Settled Currency": str(-amt),
                    "Total Processing Fees Paid by CC In Settled Currency": 0.0,
                    "Total Online Donations Net Amount in Settled Currency": -amt,
                    "fee_amount": "0.0",
                    "Campaign Name": ref,
                    "Giving Level Title": "",
                    "Comments": f"ARUDD Direct Debit Return: {_s(r['rejection_reason']) or 'Payment unpaid'}",
                    "Payment Type": "Direct Debit / PaySuite",
                    "Payment Frequency": "Recurring Payment",
                    "Subscription Type": "Direct Debit",
                    "Platform": PLATFORM,
                    "Source": SOURCE,
                    "gateway": "paysuite",
                    "Customer Ref": _s(r["customer_id"]),
                    "Bank Ref": ref,
                    "Transfer ID": batch_id,
                    "Payout Settled": "Yes" if disb_id else "No",
                    "Donation Payout Flag": "Unpaid",
                    "Donor ID": email or pid,
                    "Total LTV": -amt,
                    "Lifetime Donor Classification": classify_donor_amount(amt),
                    "Transaction Donor Classification": classify_donor_amount(amt),
                    "Code": cls["code"],
                    "New Code": cls["code"],
                    "Heading": cls["heading"],
                    "Sub-Heading": cls["sub_heading"],
                    "Department": cls["heading"],
                    "Office": cls["sub_heading"],
                    "Country": cls["country"],
                    "Target Country": cls["country"],
                    "Zakat Eligibility": cls["zakat_eligibility"],
                    "company_id": comp,
                })
                only_donation_keys.add((comp, reversal_pid))

        # 1. Update paysuite_payout_settlements: preserve pre-2026 legacy records, replace 2026+ records
        df_payout_new = pd.DataFrame(payout_rows)
        with _DB_LOCK:
            cur = conn.cursor()
            # Read pre-2026 legacy rows or other company rows
            try:
                all_payouts = pd.read_sql_query("SELECT * FROM paysuite_payout_settlements", conn)
            except Exception:
                all_payouts = pd.DataFrame()
            if all_payouts.empty:
                legacy_payouts = all_payouts
            else:
                # Uploaded rows hold "01/09/2026"-style dates (day first) and the API rows ISO dates; a text
                # comparison with "2026-01-01" kept most 2026 uploads too, duplicating them next to the API rows.
                raw_dates = all_payouts["Date of collection"].astype(str).str.strip()
                iso = raw_dates.str.match(r"^\d{4}-\d{2}-\d{2}")
                parsed = pd.to_datetime(raw_dates.where(iso), errors="coerce", format="%Y-%m-%d")
                parsed = parsed.fillna(pd.to_datetime(raw_dates.where(~iso), errors="coerce", dayfirst=True))
                other_charity = all_payouts.get("company_id", pd.Series("rethink", index=all_payouts.index)).fillna("rethink").astype(str).str.lower() != comp
                legacy_payouts = all_payouts[(parsed < pd.Timestamp(HISTORICAL_CUTOFF_DATE)) | other_charity]

            combined_payouts = pd.concat([legacy_payouts, df_payout_new], ignore_index=True)
            combined_payouts = sanitize_df_dtypes_for_parquet(combined_payouts)

            # Persist to Parquet
            atomic_write_parquet(combined_payouts, PAYSUITE_PAYOUTS_PARQUET_PATH)

            # Persist to SQLite: refill the table in place. to_sql(if_exists="replace") would drop and recreate it,
            # losing its index and the cachever_* triggers that tell the Payouts screens to refresh.
            existing_cols = {r[1] for r in conn.execute('PRAGMA table_info("paysuite_payout_settlements")')}
            if existing_cols:
                for col in combined_payouts.columns:
                    if col not in existing_cols:
                        col_type = "REAL" if pd.api.types.is_numeric_dtype(combined_payouts[col]) else "TEXT"
                        conn.execute(f'ALTER TABLE paysuite_payout_settlements ADD COLUMN "{col}" {col_type}')
                conn.commit()
                # Same transaction as the refill (to_sql commits at the end): a failed refill rolls the delete back
                conn.execute("DELETE FROM paysuite_payout_settlements")
            combined_payouts.to_sql("paysuite_payout_settlements", con=conn, if_exists="append", index=False, chunksize=5000)
            conn.commit()

        # 2. Update donations table for 2026+ PaySuite collections
        if crm_donation_rows:
            df_crm_new = pd.DataFrame(crm_donation_rows)
            with _DB_LOCK:
                # Remove any existing 2026+ PaySuite collections in donations table to maintain exact parity
                conn.execute("""
                    DELETE FROM donations
                    WHERE LOWER(Platform) = 'paysuite'
                      AND "Created Date (UTC)" >= ?
                      AND LOWER(COALESCE(company_id, 'rethink')) = ?
                """, (HISTORICAL_CUTOFF_DATE, comp))

                # Align columns with existing donations table
                cur = conn.cursor()
                cur.execute("PRAGMA table_info(donations)")
                table_cols = [r[1] for r in cur.fetchall()]
                aligned_cols = [c for c in df_crm_new.columns if c in table_cols]
                df_crm_new[aligned_cols].to_sql("donations", con=conn, if_exists="append", index=False, chunksize=2000)

            # 3. Synchronize to Parquet cache efficiently using only_keys
            try:
                from core.donations_reconcile import reconcile
                reconcile(deep=False, apply=True, require_confirmation=False, only_keys=only_donation_keys)
            except Exception as rec_err:
                logger.warning(f"[PaySuite] Donations reconcile notice: {rec_err}")

        invalidate_data_cache(comp)
        invalidate_paysuite_payouts_cache()

        logger.info(f"[PaySuite] Reconciled {len(payout_rows)} payout settlement(s) and {len(crm_donation_rows)} donation record(s).")
        return {
            "payouts_updated": len(payout_rows),
            "donations_added": len(crm_donation_rows),
            "cutoff_date": HISTORICAL_CUTOFF_DATE,
        }

    finally:
        conn.close()


# -----------------------------------------------------------------------------
# Background Service Polling Entrypoint
# -----------------------------------------------------------------------------

def poll_paysuite_sync(company_id: str = "rethink") -> Dict[str, Any]:
    """
    Called periodically by platform-sync.service (every hour).
    Performs an incremental 30-day sync, catching any newly settled or ARUDD returned collections.
    """
    comp = str(company_id or "rethink").lower().strip()
    client = get_paysuite_client()
    if not client.is_configured():
        return {"status": "skipped", "reason": "Not configured"}

    # Check if backfill has ever been completed
    is_backfilled = get_sync_state("backfill_completed") == "true"
    is_backfill_run = not is_backfilled

    # The sync service loops every minute; PaySuite runs hourly (agreed plan), a failed run retries after 10 min.
    if is_backfilled:
        try:
            last_at = datetime.fromisoformat(str(get_sync_state(f"last_poll_at_{comp}") or "").replace("Z", "+00:00"))
            wait = POLL_INTERVAL_SEC if get_sync_state(f"last_poll_ok_{comp}") == "true" else POLL_RETRY_SEC
            if (datetime.now(timezone.utc) - last_at).total_seconds() < wait:
                return {"status": "waiting", "total_fetched": 0}
        except ValueError:
            pass
    set_sync_state(f"last_poll_at_{comp}", _now_iso())

    try:
        res = sync_paysuite_payments(
            from_date=HISTORICAL_CUTOFF_DATE if is_backfill_run else None,
            company_id=comp,
            is_backfill=is_backfill_run
        )
        set_sync_state(f"last_poll_ok_{comp}", "true" if res.get("status") == "success" else "false")
        if res.get("status") != "success":
            res.setdefault("error", res.get("message") or "PaySuite sync failed")
        return res
    except Exception as e:
        set_sync_state(f"last_poll_ok_{comp}", "false")
        logger.error(f"[PaySuite] Poll error: {e}")
        return {"status": "error", "error": str(e)}
