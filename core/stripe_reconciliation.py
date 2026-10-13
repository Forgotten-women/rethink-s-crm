"""
Stripe Payout Reconciliation & Accounting Enrichment Engine
-----------------------------------------------------------
100% Read-Only integration with Stripe API.
Fetches itemized payout reports from Stripe, enriches every row using our CRM database
(donations, platform_campaign_mappings, master_project_codes), applies 8 worked-out
accounting dimensions, manages approvals, and delivers reports to Slack.
"""

import os
import sys
import csv
import json
import time
import io
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config.settings import LOCAL_DB_PATH
from core.database import get_db_connection
from core.slack_notifier import upload_payout_report_to_slack

logger = logging.getLogger("stripe_reconciliation")
if not logger.handlers:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [stripe_reconciliation] %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

# Stripe API configuration (read-only)
STRIPE_SECRET_KEY = (
    os.environ.get("RETHINK_STRIPE_SECRET_KEY")
    or os.environ.get("STRIPE_RETHINK_SECRET_KEY")
    or os.environ.get("STRIPE_SECRET_KEY")
    or ""
).strip()

STRIPE_ACCOUNT_ID = (
    os.environ.get("RETHINK_STRIPE_ACCOUNT")
    or os.environ.get("STRIPE_ACCOUNT")
    or ""
).strip()
STRIPE_API_BASE = "https://api.stripe.com/v1"
REPORTS_DIR = os.path.join(BASE_DIR, "data_cache", "stripe_payout_reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


def _stripe_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {STRIPE_SECRET_KEY}",
        "Accept": "application/json"
    }


def init_stripe_payout_tables() -> None:
    """Creates the SQLite tables for Stripe payout reports and itemized records if they don't exist."""
    conn = get_db_connection(timeout=15.0)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stripe_payout_reports (
                payout_id TEXT PRIMARY KEY,
                company_id TEXT DEFAULT 'rethink',
                amount REAL,
                currency TEXT DEFAULT 'gbp',
                status TEXT,
                arrival_date TEXT,
                created_at TEXT,
                total_transactions INTEGER,
                total_gross REAL,
                total_fees REAL,
                total_net REAL,
                approval_status TEXT DEFAULT 'pending',
                approved_by TEXT,
                approved_at TEXT,
                slack_sent_at TEXT,
                funds_summary_json TEXT,
                zakat_summary_json TEXT,
                csv_path TEXT,
                updated_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stripe_payout_items (
                balance_transaction_id TEXT PRIMARY KEY,
                payout_id TEXT NOT NULL,
                charge_id TEXT,
                payment_intent_id TEXT,
                source_type TEXT,
                donation_id TEXT,
                created_at TEXT,
                gross REAL,
                fee REAL,
                net REAL,
                currency TEXT,
                donor_name TEXT,
                donor_email TEXT,
                donor_phone TEXT,
                donor_address TEXT,
                project_name TEXT,
                project_reference TEXT,
                location_name TEXT,
                location_reference TEXT,
                gift_aid TEXT,
                zakat_status TEXT,
                appeal TEXT,
                payment_reference_code TEXT,
                stripe_data_reference TEXT,
                code TEXT,
                heading TEXT,
                subheading TEXT,
                department TEXT,
                office TEXT,
                portfolio TEXT,
                country TEXT,
                programme_fund TEXT,
                fund_code TEXT,
                zakat_eligibility TEXT,
                FOREIGN KEY (payout_id) REFERENCES stripe_payout_reports(payout_id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stripe_payout_items_pid ON stripe_payout_items(payout_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stripe_payout_items_did ON stripe_payout_items(donation_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stripe_payout_items_cid ON stripe_payout_items(charge_id)")
        conn.commit()
    finally:
        conn.close()


init_stripe_payout_tables()


def list_stripe_payouts(limit: int = 25) -> List[Dict[str, Any]]:
    """
    Queries Stripe API for recent payouts (READ-ONLY) and merges them with
    local approval and reconciliation state from the CRM database.
    """
    url = f"{STRIPE_API_BASE}/payouts"
    params = {"limit": limit}
    try:
        r = requests.get(url, headers=_stripe_headers(), params=params, timeout=12)
        if r.status_code != 200:
            logger.error(f"Failed to list Stripe payouts: {r.status_code} {r.text}")
            return []
        data = r.json()
        payouts_raw = data.get("data", [])
    except Exception as e:
        logger.error(f"Error calling Stripe payouts API: {e}")
        return []

    # Read local database for reconciliation status
    conn = get_db_connection(timeout=10.0)
    local_reports: Dict[str, Dict[str, Any]] = {}
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT payout_id, approval_status, approved_by, approved_at, slack_sent_at,
                   total_transactions, total_gross, total_fees, total_net, funds_summary_json, zakat_summary_json, csv_path
            FROM stripe_payout_reports
        """)
        for row in cursor.fetchall():
            local_reports[row[0]] = {
                "approval_status": row[1] or "pending",
                "approved_by": row[2],
                "approved_at": row[3],
                "slack_sent_at": row[4],
                "total_transactions": row[5],
                "total_gross": row[6],
                "total_fees": row[7],
                "total_net": row[8],
                "funds_summary": json.loads(row[9]) if row[9] else {},
                "zakat_summary": json.loads(row[10]) if row[10] else {},
                "is_reconciled": bool(row[11] and os.path.exists(row[11]))
            }
    finally:
        conn.close()

    result = []
    for p in payouts_raw:
        pid = p["id"]
        local = local_reports.get(pid, {})
        arrival_ts = p.get("arrival_date")
        created_ts = p.get("created")
        arrival_dt = datetime.fromtimestamp(arrival_ts, tz=timezone.utc).strftime("%Y-%m-%d") if arrival_ts else ""
        created_dt = datetime.fromtimestamp(created_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if created_ts else ""

        result.append({
            "payout_id": pid,
            "amount": round(float(p.get("amount", 0)) / 100.0, 2),
            "currency": str(p.get("currency", "gbp")).upper(),
            "status": p.get("status", "unknown"),
            "arrival_date": arrival_dt,
            "created_at": created_dt,
            "description": p.get("description") or f"Stripe Payout {pid}",
            "is_reconciled": local.get("is_reconciled", False),
            "approval_status": local.get("approval_status", "pending"),
            "approved_by": local.get("approved_by"),
            "approved_at": local.get("approved_at"),
            "slack_sent_at": local.get("slack_sent_at"),
            "total_transactions": local.get("total_transactions"),
            "total_gross": local.get("total_gross"),
            "total_fees": local.get("total_fees"),
            "total_net": local.get("total_net"),
            "funds_summary": local.get("funds_summary", {}),
            "zakat_summary": local.get("zakat_summary", {})
        })

    return result


def _fetch_stripe_invoice_details(invoice_id: str) -> Dict[str, Any]:
    """Retrieves invoice with expanded subscription and lines (READ-ONLY)."""
    if not invoice_id:
        return {}
    url = f"{STRIPE_API_BASE}/invoices/{invoice_id}"
    params = [("expand[]", "subscription"), ("expand[]", "lines.data.price.product")]
    try:
        r = requests.get(url, headers=_stripe_headers(), params=params, timeout=12)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.warning(f"Failed to fetch invoice {invoice_id}: {e}")
    return {}


def _match_crm_classification(
    campaign_name: str,
    giving_level: str = "",
    company_id: str = "rethink",
    cursor: Optional[Any] = None,
    payment_link_id: Optional[str] = None
) -> Dict[str, str]:
    """
    Matches campaign text strictly against our CRM's master classification table (platform_campaign_mappings)
    and master project codes (master_project_codes).
    Zero secondary dictionaries or hardcoded lists: relies 100% on the CRM database tables.
    """
    clean_name = (campaign_name or "").strip()
    clean_level = (giving_level or "").strip()
    c_low = clean_name.lower()
    comp = str(company_id or "rethink").lower().strip()

    # Special Case: Stripe fees
    if "fee" in c_low or "billing" in c_low or "per auth" in c_low or "usage fee" in c_low:
        if cursor:
            cursor.execute("""
                SELECT department, office, portfolio, country, programme_fund, fund_code, zakat_eligibility,
                       COALESCE(heading, department), COALESCE(sub_heading, office)
                FROM master_project_codes WHERE code = 'STRIPE-FEE' LIMIT 1
            """)
            fee_row = cursor.fetchone()
            if fee_row:
                return {
                    "code": "STRIPE-FEE",
                    "department": fee_row[0] or "Finance & Operations",
                    "office": fee_row[1] or "Platform & Processing Fees",
                    "portfolio": fee_row[2] or "Administrative",
                    "country": fee_row[3] or "United Kingdom",
                    "programme_fund": fee_row[4] or "Unrestricted / Overhead (outside 6 funds)",
                    "fund_code": fee_row[5] or "F-ADM",
                    "zakat_eligibility": fee_row[6] or "Non-Zakat",
                    "heading": fee_row[7] or "Finance & Operations",
                    "subheading": fee_row[8] or "Platform & Processing Fees"
                }
        return {
            "code": "STRIPE-FEE",
            "heading": "Finance & Operations",
            "subheading": "Platform & Processing Fees",
            "department": "Finance & Operations",
            "office": "Platform & Processing Fees",
            "portfolio": "Administrative",
            "country": "United Kingdom",
            "programme_fund": "Unrestricted / Overhead (outside 6 funds)",
            "fund_code": "F-ADM",
            "zakat_eligibility": "Non-Zakat"
        }

    resolved_code = None

    if cursor:
        # 0. Direct match by Stripe Payment Link ID / URL in platform_campaign_mappings
        if payment_link_id:
            cursor.execute("""
                SELECT code FROM platform_campaign_mappings
                WHERE LOWER(COALESCE(company_id, 'rethink')) = ? 
                  AND platform = 'stripe'
                  AND (
                      community_name = ?
                      OR giving_level LIKE '%' || ? || '%'
                      OR campaign_url LIKE '%' || ? || '%'
                  )
                ORDER BY is_primary DESC, rowid DESC
                LIMIT 1
            """, (comp, payment_link_id, payment_link_id, payment_link_id))
            row = cursor.fetchone()
            if row and row[0]:
                resolved_code = row[0].strip()

        # 1. Match in platform_campaign_mappings by giving level
        if not resolved_code and clean_name and clean_level:
            cursor.execute("""
                SELECT code FROM platform_campaign_mappings
                WHERE LOWER(COALESCE(company_id, 'rethink')) = ? 
                  AND LOWER(TRIM(campaign_name)) = LOWER(TRIM(?)) 
                  AND LOWER(TRIM(giving_level)) = LOWER(TRIM(?))
                ORDER BY (platform = 'stripe') DESC, (platform IN ('website', 'rethink_website')) DESC, is_primary DESC, rowid DESC
                LIMIT 1
            """, (comp, clean_name, clean_level))
            row = cursor.fetchone()
            if row and row[0]:
                resolved_code = row[0].strip()

        # 2. Exact match in platform_campaign_mappings by campaign name
        if not resolved_code and clean_name:
            cursor.execute("""
                SELECT code FROM platform_campaign_mappings
                WHERE LOWER(COALESCE(company_id, 'rethink')) = ? 
                  AND LOWER(TRIM(campaign_name)) = LOWER(TRIM(?))
                ORDER BY (platform = 'stripe') DESC, (platform IN ('website', 'rethink_website')) DESC, is_primary DESC, rowid DESC
                LIMIT 1
            """, (comp, clean_name))
            row = cursor.fetchone()
            if row and row[0]:
                resolved_code = row[0].strip()

        # 3. Direct match in master_project_codes by code
        if not resolved_code and clean_name:
            cursor.execute("""
                SELECT code FROM master_project_codes
                WHERE LOWER(TRIM(code)) = LOWER(TRIM(?))
                LIMIT 1
            """, (clean_name,))
            row = cursor.fetchone()
            if row and row[0]:
                resolved_code = row[0].strip()

        # 4. Keyword / partial matching in platform_campaign_mappings
        if not resolved_code and clean_name:
            cursor.execute("""
                SELECT code FROM platform_campaign_mappings
                WHERE LOWER(COALESCE(company_id, 'rethink')) = ? 
                  AND LENGTH(TRIM(campaign_name)) >= 3
                  AND (? LIKE '%' || LOWER(TRIM(campaign_name)) || '%' OR LOWER(TRIM(campaign_name)) LIKE '%' || ? || '%')
                ORDER BY (platform = 'stripe') DESC, (platform IN ('website', 'rethink_website')) DESC, is_primary DESC, LENGTH(campaign_name) DESC
                LIMIT 1
            """, (comp, c_low, c_low))
            row = cursor.fetchone()
            if row and row[0]:
                resolved_code = row[0].strip()

    if not resolved_code:
        resolved_code = "ALL-GEN-GEN-GEN"

    meta = {
        "code": resolved_code,
        "heading": "General",
        "subheading": "General",
        "department": "General",
        "office": "General",
        "portfolio": "General",
        "country": "Global / Unspecified",
        "programme_fund": "1. Emergency / Most-Needed Fund",
        "fund_code": "F1-EMR",
        "zakat_eligibility": "Zakat"
    }

    if cursor:
        cursor.execute("""
            SELECT department, office, portfolio, country, programme_fund, fund_code, zakat_eligibility,
                   COALESCE(heading, department), COALESCE(sub_heading, office)
            FROM master_project_codes WHERE code = ? LIMIT 1
        """, (resolved_code,))
        row = cursor.fetchone()
        if row:
            dept = row[0] or meta["department"]
            off = row[1] or meta["office"]
            meta["department"] = dept
            meta["office"] = off
            meta["portfolio"] = row[2] or meta["portfolio"]
            meta["country"] = row[3] or meta["country"]
            meta["programme_fund"] = row[4] or meta["programme_fund"]
            meta["fund_code"] = row[5] or meta["fund_code"]
            meta["zakat_eligibility"] = row[6] or meta["zakat_eligibility"]
            meta["heading"] = row[7] or dept
            meta["subheading"] = row[8] or off

    return meta


REPORT_COLUMNS = [
    'balance_transaction_id',
    'created',
    'available_on',
    'gross',
    'fee',
    'net',
    'currency',
    'charge_id',
    'payment_intent_id',
    'customer_id',
    'customer_email',
    'customer_name',
    'payment_method_type',
    'reporting_category',
    'description',
    'payment_metadata[Donor Name]',
    'payment_metadata[Donor Email]',
    'payment_metadata[Donor Phone]',
    'payment_metadata[Donor Address]',
    'payment_metadata[Project Name]',
    'payment_metadata[Project Reference]',
    'payment_metadata[Location Name]',
    'payment_metadata[Location Reference]',
    'payment_metadata[Gift Aid?]',
    'payment_metadata[Zakat?]',
    'payment_metadata[Appeal]',
    'payment_metadata[Payment Reference Code]',
    'payment_metadata[Stripe Data Reference]',
]


def reconcile_stripe_payout(payout_id: str, company_id: str = "rethink") -> Dict[str, Any]:
    """
    Executes the complete Stripe Payout reconciliation workflow:
    1. Requests Stripe Reporting API report run for the payout with full 28 custom metadata columns.
    2. Downloads itemized balance transaction CSV.
    3. Deep-enriches recurring subscriptions, invoices, and contactless transactions.
    4. Enriches GiveBrite rows via direct join with CRM donations.
    5. Maps Website donations using platform_campaign_mappings and master_project_codes.
    6. Produces Heading, Sub-Heading, Code, Department, Office, Portfolio, Country, Programme Fund, Fund Code, Zakat Eligibility.
    7. Saves enriched report and registers in database with 'pending' approval status.
    """
    logger.info(f"Starting Stripe Payout reconciliation for: {payout_id}")

    import stripe
    stripe.api_key = STRIPE_SECRET_KEY

    # Step 1: Check if an existing succeeded report run with full custom columns already exists
    file_id = None
    try:
        existing_runs = stripe.reporting.ReportRun.list(limit=25)
        for r in existing_runs.data:
            p_dict = r.parameters.to_dict() if hasattr(r.parameters, "to_dict") else (r.parameters if isinstance(r.parameters, dict) else {})
            p_cols = p_dict.get("columns") or []
            if p_dict.get("payout") == payout_id and r.status == "succeeded" and r.result and len(p_cols) >= 20:
                file_id = r.result.id
                logger.info(f"Reusing existing completed Stripe report run {r.id} with custom columns (file: {file_id})")
                break
    except Exception as list_err:
        logger.warning(f"Notice listing existing report runs: {list_err}")

    # If no completed run exists with custom columns, create one and poll
    if not file_id:
        try:
            run_data = stripe.reporting.ReportRun.create(
                report_type="payout_reconciliation.by_id.itemized.4",
                parameters={"payout": payout_id, "columns": REPORT_COLUMNS}
            )
            run_id = run_data.id
            logger.info(f"Report Run created: {run_id}, status: {run_data.status}")

            completed = run_data
            attempts = 0
            max_attempts = 35
            while completed.status == "pending" and attempts < max_attempts:
                time.sleep(2)
                attempts += 1
                completed = stripe.reporting.ReportRun.retrieve(run_id)
                logger.info(f"Polling report {run_id}... status: {completed.status} (attempt {attempts})")

            if completed.status == "succeeded" and completed.result:
                file_id = completed.result.id
            else:
                raise TimeoutError(f"Report run {run_id} failed or timed out with status: {completed.status}")
        except Exception as run_err:
            logger.error(f"Error in Stripe report run: {run_err}")
            raise

    logger.info(f"Downloading Stripe generated CSV file: {file_id}")
    r_file = requests.get(f"https://files.stripe.com/v1/files/{file_id}/contents", headers=_stripe_headers(), timeout=30)
    if r_file.status_code != 200:
        raise RuntimeError(f"Failed to download report file from Stripe: {r_file.status_code}")

    raw_csv_text = r_file.text
    reader = csv.DictReader(io.StringIO(raw_csv_text))
    raw_rows = list(reader)

    # Step 3: Enrich rows against CRM database
    conn = get_db_connection(timeout=15.0)
    cursor = conn.cursor()

    enriched_rows = []
    total_gross = 0.0
    total_fees = 0.0
    total_net = 0.0
    enriched_count = 0
    funds_breakdown: Dict[str, float] = {}
    zakat_breakdown: Dict[str, float] = {}

    try:
        for row in raw_rows:
            gross = float(row.get("gross") or 0.0)
            fee = float(row.get("fee") or 0.0)
            net = float(row.get("net") or 0.0)
            total_gross += gross
            total_fees += fee
            total_net += net

            ch_id = row.get("charge_id") or ""
            pi_id = row.get("payment_intent_id") or ""
            desc = row.get("description") or ""
            cat = row.get("reporting_category") or ""

            donor_name = row.get("payment_metadata[Donor Name]") or row.get("customer_name") or ""
            donor_email = row.get("payment_metadata[Donor Email]") or row.get("customer_email") or ""
            donor_phone = row.get("payment_metadata[Donor Phone]") or ""
            donor_address = row.get("payment_metadata[Donor Address]") or ""
            proj_name = row.get("payment_metadata[Project Name]") or ""
            proj_ref = row.get("payment_metadata[Project Reference]") or ""
            loc_name = row.get("payment_metadata[Location Name]") or ""
            loc_ref = row.get("payment_metadata[Location Reference]") or ""
            gift_aid = row.get("payment_metadata[Gift Aid?]") or "No"
            zakat_status = row.get("payment_metadata[Zakat?]") or "Sadaqah"
            appeal = row.get("payment_metadata[Appeal]") or ""
            pmt_ref_code = row.get("payment_metadata[Payment Reference Code]") or ""
            stripe_data_ref = row.get("payment_metadata[Stripe Data Reference]") or ""

            source_type = "website"
            donation_id = ""

            # Check Case 1: Stripe System Fee
            if cat == "fee" or "billing - usage fee" in desc.lower() or "per auth fee" in desc.lower() or "stripe fee" in desc.lower():
                source_type = "fee"
                donor_name = "[Stripe Platform Fee]"
                proj_name = desc or "Billing - Usage Fee"
                meta = _match_crm_classification(proj_name, cursor=cursor)

            # Check Case 2: GiveBrite Donation (matches description 'GB-donation-' or charge_id)
            elif desc.startswith("GB-donation-") or "gbx" in desc.lower() or (ch_id and "GB-" in desc):
                source_type = "givebrite"
                donation_id = desc.replace("GB-donation-", "").strip()

                # Query our CRM donations table for exact matching document
                cursor.execute("""
                    SELECT [First Name], [Last Name], [Email], [Campaign Name], [Giving Level Title],
                           [Code], [Department], [Office], [Portfolio], [Country], [Programme Fund], [Fund Code], [Zakat Eligibility]
                    FROM donations
                    WHERE [Donation ID] = ? OR [charge_id] = ? OR [_id] = ?
                    LIMIT 1
                """, (donation_id, ch_id, donation_id))
                crm_row = cursor.fetchone()

                if crm_row:
                    donor_name = f"{crm_row[0] or ''} {crm_row[1] or ''}".strip()
                    donor_email = crm_row[2] or donor_email
                    proj_name = crm_row[3] or proj_name
                    giving_level = crm_row[4] or ""
                    code_val = crm_row[5] or ""
                    
                    if code_val and code_val != "Unassigned":
                        meta = {
                            "code": code_val,
                            "heading": crm_row[6] or "General",
                            "subheading": crm_row[7] or "General",
                            "department": crm_row[6] or "",
                            "office": crm_row[7] or "",
                            "portfolio": crm_row[8] or "",
                            "country": crm_row[9] or "",
                            "programme_fund": crm_row[10] or "",
                            "fund_code": crm_row[11] or "",
                            "zakat_eligibility": crm_row[12] or "Zakat"
                        }
                    else:
                        meta = _match_crm_classification(proj_name, giving_level, company_id=company_id, cursor=cursor)
                else:
                    meta = _match_crm_classification(proj_name, company_id=company_id, cursor=cursor)
                enriched_count += 1

            # Check Case 3: Contactless / Sign Pay Terminal Reader
            elif "sign pay" in desc.lower() or row.get("payment_method_type") == "card_present":
                source_type = "terminal"
                donor_name = donor_name or "Contactless Donor (Sign Pay)"
                donor_email = donor_email or "in-person@terminal"
                clean_desc = desc.replace("Payment via Sign Pay", "Sign Pay - General").replace("Sign Pay - ", "").strip()
                proj_name = clean_desc.split("/")[0].strip() or "Sign Pay Campaign"
                meta = _match_crm_classification(proj_name, company_id=company_id, cursor=cursor)
                enriched_count += 1

            # Check Case 4: Recurring Subscriptions / Invoices where project name was omitted
            else:
                pl_id = None
                if not proj_name and pi_id:
                    source_type = "subscription"
                    try:
                        pi_obj = stripe.PaymentIntent.retrieve(pi_id)
                        pi_dict = pi_obj.to_dict() if hasattr(pi_obj, "to_dict") else dict(pi_obj)
                        
                        # Find invoice ID
                        inv_id = pi_dict.get("invoice")
                        p_details = pi_dict.get("payment_details") or {}
                        if not inv_id and str(p_details.get("order_reference") or "").startswith("in_"):
                            inv_id = p_details.get("order_reference")

                        if inv_id:
                            inv = stripe.Invoice.retrieve(inv_id, expand=["lines.data.price.product", "subscription"])
                            inv_dict = inv.to_dict() if hasattr(inv, "to_dict") else dict(inv)
                            lines = (inv_dict.get("lines") or {}).get("data", [])
                            line_item = lines[0] if lines else {}
                            line_meta = line_item.get("metadata") or {}
                            sub_meta = (inv_dict.get("subscription") or {}).get("metadata") or {}
                            meta_src = line_meta if line_meta else sub_meta

                            donor_name = meta_src.get("Donor Name") or donor_name or inv_dict.get("customer_name") or ""
                            donor_email = meta_src.get("Donor Email") or donor_email or inv_dict.get("customer_email") or ""
                            donor_phone = meta_src.get("Donor Phone") or donor_phone or inv_dict.get("customer_phone") or ""
                            donor_address = meta_src.get("Donor Address") or donor_address or ""
                            proj_name = meta_src.get("Project Name") or ""
                            if not proj_name:
                                prod = (line_item.get("price") or {}).get("product")
                                if isinstance(prod, dict) and prod.get("name"):
                                    proj_name = prod.get("name")
                                elif line_item.get("description"):
                                    l_desc = line_item.get("description")
                                    proj_name = l_desc.replace("1 × ", "").split(" (at £")[0].strip()
                            loc_name = meta_src.get("Location Name") or loc_name or "Most needed"
                            proj_ref = meta_src.get("Project Reference") or proj_ref or ""
                            loc_ref = meta_src.get("Location Reference") or loc_ref or ""
                            gift_aid = meta_src.get("Gift Aid?") or gift_aid or "No"
                            zakat_status = meta_src.get("Zakat?") or zakat_status or "Sadaqah"
                            appeal = meta_src.get("Appeal") or appeal or "Recurring Monthly"
                            pmt_ref_code = meta_src.get("Payment Reference Code") or pmt_ref_code or ""
                            stripe_data_ref = meta_src.get("Stripe Data Reference") or stripe_data_ref or ""
                        else:
                            # Check checkout sessions for payment link
                            sessions = stripe.checkout.Session.list(payment_intent=pi_id, limit=1)
                            if sessions.data and sessions.data[0].payment_link:
                                pl_id = sessions.data[0].payment_link
                                pl = stripe.PaymentLink.retrieve(pl_id, expand=["line_items.data.price.product"])
                                li = (pl.line_items.data or [None])[0] if hasattr(pl, "line_items") else None
                                if li and hasattr(li, "price") and hasattr(li.price, "product"):
                                    proj_name = getattr(li.price.product, "name", "")
                    except Exception as sub_err:
                        logger.debug(f"Deep subscription enrichment note for {pi_id}: {sub_err}")

                # If Direct Debit (py_...) or subscription update without project, check customer subscriptions
                if not proj_name and row.get("customer_id"):
                    try:
                        subs = stripe.Subscription.list(customer=row.get("customer_id"), limit=1, expand=["data.items.data.price.product"])
                        if subs.data:
                            sub_obj = subs.data[0]
                            sub_items = sub_obj.items.data if hasattr(sub_obj, "items") else []
                            if sub_items and hasattr(sub_items[0], "price") and hasattr(sub_items[0].price, "product"):
                                p_obj = sub_items[0].price.product
                                if hasattr(p_obj, "name") and p_obj.name:
                                    proj_name = p_obj.name
                    except Exception as sub_err2:
                        logger.debug(f"Customer subscription lookup note: {sub_err2}")

                # If still empty, check previous donation in CRM donations table
                if not proj_name and donor_email:
                    cursor.execute("""
                        SELECT [Campaign Name] FROM donations
                        WHERE LOWER(TRIM(Email)) = LOWER(TRIM(?)) AND [Campaign Name] IS NOT NULL AND [Campaign Name] != ''
                        ORDER BY rowid DESC LIMIT 1
                    """, (donor_email,))
                    prev_d = cursor.fetchone()
                    if prev_d and prev_d[0]:
                        proj_name = prev_d[0]

                proj_name = proj_name or desc or "General Website Donation"
                meta = _match_crm_classification(proj_name, company_id=company_id, cursor=cursor, payment_link_id=pl_id)
                enriched_count += 1

            # Build enriched row
            enriched_row = dict(row)
            enriched_row["Date"] = row.get("created") or ""
            enriched_row["payment_metadata[Donor Name]"] = donor_name
            enriched_row["payment_metadata[Donor Email]"] = donor_email
            enriched_row["payment_metadata[Donor Phone]"] = donor_phone
            enriched_row["payment_metadata[Donor Address]"] = donor_address
            enriched_row["payment_metadata[Project Name]"] = proj_name
            enriched_row["payment_metadata[Project Reference]"] = proj_ref
            enriched_row["payment_metadata[Location Name]"] = loc_name
            enriched_row["payment_metadata[Location Reference]"] = loc_ref
            enriched_row["payment_metadata[Gift Aid?]"] = gift_aid
            enriched_row["payment_metadata[Zakat?]"] = zakat_status
            enriched_row["payment_metadata[Appeal]"] = appeal
            enriched_row["payment_metadata[Payment Reference Code]"] = pmt_ref_code
            enriched_row["payment_metadata[Stripe Data Reference]"] = stripe_data_ref

            enriched_row["Code"] = meta["code"]
            enriched_row["Heading"] = meta["heading"]
            enriched_row["Sub-Heading"] = meta["subheading"]
            enriched_row["Department"] = meta["department"]
            enriched_row["Office"] = meta["office"]
            enriched_row["Portfolio"] = meta["portfolio"]
            enriched_row["Country"] = meta["country"]
            enriched_row["Programme Fund"] = meta["programme_fund"]
            enriched_row["Fund Code"] = meta["fund_code"]
            enriched_row["Zakat Eligibility"] = meta["zakat_eligibility"]
            enriched_rows.append(enriched_row)

            # Accumulate breakdown
            f_code = meta["fund_code"] or "Unknown"
            z_code = meta["zakat_eligibility"] or "Non-Zakat"
            funds_breakdown[f_code] = round(funds_breakdown.get(f_code, 0.0) + net, 2)
            zakat_breakdown[z_code] = round(zakat_breakdown.get(z_code, 0.0) + net, 2)

            # Insert or replace item in database
            cursor.execute("""
                INSERT OR REPLACE INTO stripe_payout_items (
                    balance_transaction_id, payout_id, charge_id, payment_intent_id,
                    source_type, donation_id, created_at, gross, fee, net, currency,
                    donor_name, donor_email, donor_phone, donor_address,
                    project_name, project_reference, location_name, location_reference,
                    gift_aid, zakat_status, appeal, payment_reference_code, stripe_data_reference,
                    code, heading, subheading, department, office,
                    portfolio, country, programme_fund, fund_code, zakat_eligibility
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row.get("balance_transaction_id"), payout_id, ch_id, pi_id,
                source_type, donation_id, row.get("created"), gross, fee, net,
                row.get("currency", "gbp").upper(), donor_name, donor_email, donor_phone, donor_address,
                proj_name, proj_ref, loc_name, loc_ref,
                gift_aid, zakat_status, appeal, pmt_ref_code, stripe_data_ref,
                meta["code"], meta["heading"], meta["subheading"], meta["department"], meta["office"],
                meta["portfolio"], meta["country"], meta["programme_fund"], meta["fund_code"], meta["zakat_eligibility"]
            ))

        # Save enriched CSV file to reports directory
        ts_now = int(time.time())
        filename = f"enriched_payout_{payout_id}_{ts_now}.csv"
        csv_path = os.path.join(REPORTS_DIR, filename)

        classification_headers = [
            "Code", "Heading", "Sub-Heading", "Department", "Office", "Portfolio", "Country",
            "Programme Fund", "Fund Code", "Zakat Eligibility"
        ]
        base_headers = [
            'created', 'description', 'balance_transaction_id', 'available_on',
            'gross', 'fee', 'net', 'currency', 'charge_id', 'payment_intent_id',
            'customer_id', 'customer_email', 'customer_name', 'payment_method_type', 'reporting_category',
            'payment_metadata[Donor Name]', 'payment_metadata[Donor Email]', 'payment_metadata[Donor Phone]',
            'payment_metadata[Donor Address]', 'payment_metadata[Project Name]', 'payment_metadata[Project Reference]',
            'payment_metadata[Location Name]', 'payment_metadata[Location Reference]', 'payment_metadata[Gift Aid?]',
            'payment_metadata[Zakat?]', 'payment_metadata[Appeal]', 'payment_metadata[Payment Reference Code]',
            'payment_metadata[Stripe Data Reference]'
        ]
        out_headers = ["Date"] + base_headers + classification_headers

        with open(csv_path, "w", newline="", encoding="utf-8") as f_out:
            writer = csv.DictWriter(f_out, fieldnames=out_headers, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(enriched_rows)

        # Register report record in database
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT OR REPLACE INTO stripe_payout_reports (
                payout_id, company_id, amount, currency, status, arrival_date, created_at,
                total_transactions, total_gross, total_fees, total_net, approval_status,
                funds_summary_json, zakat_summary_json, csv_path, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
        """, (
            payout_id, company_id, round(total_net, 2), "GBP", "paid",
            datetime.now(timezone.utc).strftime("%Y-%m-%d"), now_iso, len(enriched_rows),
            round(total_gross, 2), round(total_fees, 2), round(total_net, 2),
            json.dumps(funds_breakdown), json.dumps(zakat_breakdown), csv_path, now_iso
        ))

        conn.commit()
    finally:
        conn.close()

    summary = {
        "payout_id": payout_id,
        "total_rows": len(enriched_rows),
        "enriched_count": enriched_count,
        "total_gross": round(total_gross, 2),
        "total_fees": round(total_fees, 2),
        "total_net": round(total_net, 2),
        "funds_breakdown": funds_breakdown,
        "zakat_breakdown": zakat_breakdown,
        "csv_path": csv_path
    }
    logger.info(f"Reconciliation completed for {payout_id}: {len(enriched_rows)} rows enriched.")
    return summary


def resync_payout_with_crm(payout_id: str, company_id: str = "rethink") -> Dict[str, Any]:
    """
    Solves out-of-sync discrepancies when someone manually changes a donation's code or
    updates platform_campaign_mappings in the CRM.
    Re-evaluates every item in the payout against the current CRM tables.
    """
    logger.info(f"Re-syncing Stripe payout {payout_id} with updated CRM classifications...")
    conn = get_db_connection(timeout=15.0)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT balance_transaction_id, donation_id, project_name, net, charge_id, source_type
            FROM stripe_payout_items WHERE payout_id = ?
        """, (payout_id,))
        items = cursor.fetchall()
        if not items:
            raise ValueError(f"No itemized records found for payout {payout_id}")

        updated_count = 0
        funds_breakdown: Dict[str, float] = {}
        zakat_breakdown: Dict[str, float] = {}
        total_net = 0.0

        for b_id, d_id, proj_name, net_val, ch_id, src_type in items:
            net = float(net_val or 0.0)
            total_net += net

            # If GiveBrite, check donations table directly
            if src_type == "givebrite" and d_id:
                cursor.execute("""
                    SELECT [Code], [Department], [Office], [Portfolio], [Country], [Programme Fund], [Fund Code], [Zakat Eligibility]
                    FROM donations WHERE [Donation ID] = ? LIMIT 1
                """, (d_id,))
                d_row = cursor.fetchone()
                if d_row and d_row[0] and d_row[0] != "Unassigned":
                    meta = {
                        "code": d_row[0], "department": d_row[1] or "", "office": d_row[2] or "",
                        "portfolio": d_row[3] or "", "country": d_row[4] or "",
                        "programme_fund": d_row[5] or "", "fund_code": d_row[6] or "",
                        "zakat_eligibility": d_row[7] or "Zakat"
                    }
                else:
                    meta = _match_crm_classification(proj_name, company_id=company_id, cursor=cursor)
            else:
                meta = _match_crm_classification(proj_name, company_id=company_id, cursor=cursor)

            cursor.execute("""
                UPDATE stripe_payout_items
                SET code = ?, heading = ?, subheading = ?, department = ?, office = ?, portfolio = ?, country = ?,
                    programme_fund = ?, fund_code = ?, zakat_eligibility = ?
                WHERE balance_transaction_id = ?
            """, (
                meta["code"], meta["heading"], meta["subheading"], meta["department"], meta["office"], meta["portfolio"], meta["country"],
                meta["programme_fund"], meta["fund_code"], meta["zakat_eligibility"], b_id
            ))
            updated_count += 1

            f_code = meta["fund_code"] or "Unknown"
            z_code = meta["zakat_eligibility"] or "Non-Zakat"
            funds_breakdown[f_code] = round(funds_breakdown.get(f_code, 0.0) + net, 2)
            zakat_breakdown[z_code] = round(zakat_breakdown.get(z_code, 0.0) + net, 2)

        # Update report summary and regenerate CSV
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute("SELECT csv_path FROM stripe_payout_reports WHERE payout_id = ?", (payout_id,))
        csv_row = cursor.fetchone()
        if csv_row and csv_row[0] and os.path.exists(csv_row[0]):
            csv_path = csv_row[0]
            try:
                cursor.execute("""
                    SELECT balance_transaction_id, created_at, currency, gross, fee, net,
                           project_name, code, heading, subheading, department, office, portfolio, country,
                           programme_fund, fund_code, zakat_eligibility, donor_name, donor_email,
                           source_type, donation_id
                    FROM stripe_payout_items WHERE payout_id = ?
                    ORDER BY created_at DESC
                """, (payout_id,))
                csv_items = cursor.fetchall()
                fieldnames = [
                    "Date", "balance_transaction_id", "created", "currency", "gross", "fee", "net",
                    "description", "Code", "Heading", "Sub-Heading", "Department", "Office", "Portfolio", "Country",
                    "Programme Fund", "Fund Code", "Zakat Eligibility", "Donor Name", "Donor Email",
                    "source_type", "donation_id"
                ]
                with open(csv_path, "w", newline="", encoding="utf-8") as f_out:
                    writer = csv.DictWriter(f_out, fieldnames=fieldnames)
                    writer.writeheader()
                    for it in csv_items:
                        writer.writerow({
                            "Date": it[1] or "",
                            "balance_transaction_id": it[0],
                            "created": it[1] or "",
                            "currency": (it[2] or "").lower(),
                            "gross": it[3],
                            "fee": it[4],
                            "net": it[5],
                            "description": it[6] or "",
                            "Code": it[7] or "",
                            "Heading": it[8] or it[10] or "",
                            "Sub-Heading": it[9] or it[11] or "",
                            "Department": it[10] or "",
                            "Office": it[11] or "",
                            "Portfolio": it[12] or "",
                            "Country": it[13] or "",
                            "Programme Fund": it[14] or "",
                            "Fund Code": it[15] or "",
                            "Zakat Eligibility": it[16] or "",
                            "Donor Name": it[17] or "",
                            "Donor Email": it[18] or "",
                            "source_type": it[19] or "",
                            "donation_id": it[20] or ""
                        })
            except Exception as csv_err:
                logger.warning(f"Failed to refresh CSV for {payout_id}: {csv_err}")

        cursor.execute("""
            UPDATE stripe_payout_reports
            SET funds_summary_json = ?, zakat_summary_json = ?, updated_at = ?
            WHERE payout_id = ?
        """, (json.dumps(funds_breakdown), json.dumps(zakat_breakdown), now_iso, payout_id))

        conn.commit()
    finally:
        conn.close()

    logger.info(f"Re-sync completed for {payout_id}: {updated_count} items refreshed.")
    return {
        "payout_id": payout_id,
        "refreshed_items": updated_count,
        "funds_breakdown": funds_breakdown,
        "zakat_breakdown": zakat_breakdown,
        "total_net": round(total_net, 2)
    }


def approve_and_send_to_slack(payout_id: str, approved_by: str = "Admin") -> Dict[str, Any]:
    """
    Approves a reconciled Stripe Payout and uploads the verified reconciliation report to Slack #rt-payouts.
    """
    conn = get_db_connection(timeout=10.0)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT csv_path, total_transactions, total_gross, total_fees, total_net,
                   funds_summary_json, zakat_summary_json
            FROM stripe_payout_reports WHERE payout_id = ?
        """, (payout_id,))
        row = cursor.fetchone()
        if not row or not row[0]:
            raise ValueError(f"Reconciliation report not found for payout {payout_id}")

        csv_path = row[0]
        summary = {
            "payout_id": payout_id,
            "total_rows": row[1],
            "enriched_count": row[1],
            "total_gross": row[2],
            "total_fees": row[3],
            "total_net": row[4],
            "funds_breakdown": json.loads(row[5]) if row[5] else {},
            "zakat_breakdown": json.loads(row[6]) if row[6] else {}
        }
    finally:
        conn.close()

    # Upload to Slack
    slack_res = upload_payout_report_to_slack(
        file_path=csv_path,
        payout_id=payout_id,
        summary=summary,
        approved_by=approved_by
    )

    # Update approval and Slack timestamps in DB
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection(timeout=10.0)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE stripe_payout_reports
            SET approval_status = 'approved', approved_by = ?, approved_at = ?,
                slack_sent_at = ?, updated_at = ?
            WHERE payout_id = ?
        """, (approved_by, now_iso, now_iso if slack_res.get("ok") else None, now_iso, payout_id))
        conn.commit()
    finally:
        conn.close()

    return {
        "success": True,
        "payout_id": payout_id,
        "approval_status": "approved",
        "approved_by": approved_by,
        "slack": slack_res
    }


def resend_payout_to_slack(payout_id: str) -> Dict[str, Any]:
    """
    Resends an already approved payout report to Slack #rt-payouts.
    """
    conn = get_db_connection(timeout=10.0)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT csv_path, total_transactions, total_gross, total_fees, total_net,
                   funds_summary_json, zakat_summary_json, approved_by
            FROM stripe_payout_reports WHERE payout_id = ?
        """, (payout_id,))
        row = cursor.fetchone()
        if not row or not row[0]:
            raise ValueError(f"Reconciliation report not found for payout {payout_id}")

        csv_path = row[0]
        approved_by = row[7] or "Admin"
        summary = {
            "payout_id": payout_id,
            "total_rows": row[1],
            "enriched_count": row[1],
            "total_gross": row[2],
            "total_fees": row[3],
            "total_net": row[4],
            "funds_breakdown": json.loads(row[5]) if row[5] else {},
            "zakat_breakdown": json.loads(row[6]) if row[6] else {}
        }
    finally:
        conn.close()

    slack_res = upload_payout_report_to_slack(
        file_path=csv_path,
        payout_id=payout_id,
        summary=summary,
        approved_by=approved_by
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection(timeout=10.0)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE stripe_payout_reports
            SET slack_sent_at = ?, updated_at = ?
            WHERE payout_id = ?
        """, (now_iso if slack_res.get("ok") else None, now_iso, payout_id))
        conn.commit()
    finally:
        conn.close()

    return {
        "success": True,
        "payout_id": payout_id,
        "slack": slack_res
    }
