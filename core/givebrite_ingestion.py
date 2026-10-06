"""
GiveBrite Real-Time Ingestion and Data Processing Pipeline
===========================================================
Enterprise CRM module for ingesting, classifying, and persisting
GiveBrite live donations directly into SQLite ('launchgood_donations.db')
and the high-speed Parquet cache ('donations_cache.parquet').

Key Principles:
1. Strict Multi-Tenant Isolation: Enforces company_id = 'iqra'. Never affects 'rethink'.
2. Native Currency Preservation: 100% platform-native amounts & fees. Zero synthetic FX conversions.
3. 2-Tier Classification Resolution:
   - Tier 1: (campaign_name, giving_level) lookup in platform_campaign_mappings
   - Tier 2: (campaign_name, '') fallback to campaign default
   - Auto-Discovery: Registers unseen campaigns/giving levels as 'Unassigned'
4. Native Date Parsing: ISO-8601 UTC date extraction ('YYYY-MM-DD' and 'HH:MM:SS')
5. Fundraising Attribution: Preserves native fundraiser/team data + CRM assignments.
6. Direct Persistence: SQLite + Parquet atomic sync (no intermediate JSON cache files).
"""

import os
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple

import requests
import pandas as pd

# Core paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config.settings import LOCAL_DB_PATH, PARQUET_PATH
from core.database import get_db_connection
from core.data_processor import atomic_write_parquet, invalidate_data_cache

logger = logging.getLogger("givebrite_ingestion")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [givebrite_ingestion] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

GIVEBRITE_API_BASE = "https://api-dashboard.givebrite.com/v1/dashboard"
DEFAULT_CHARITY_ID = "68625e0d6d1a99441e34e2ea"  # Iqra Charity GiveBrite ID


def parse_givebrite_date(created_at_str: Optional[str]) -> Tuple[str, str, str]:
    """
    Parses GiveBrite ISO-8601 UTC string (e.g. '2026-10-06T07:39:03.735Z')
    Returns: (created_date_utc, created_time_utc, raw_iso)
    """
    if not created_at_str:
        now_dt = datetime.now(timezone.utc)
        return now_dt.strftime("%Y-%m-%d"), now_dt.strftime("%H:%M:%S"), now_dt.isoformat()

    try:
        clean_str = str(created_at_str).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        # Ensure UTC
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S"), str(created_at_str)
    except Exception as ex:
        logger.warning(f"Error parsing date {created_at_str!r}: {ex}. Falling back to UTC now.")
        now_dt = datetime.now(timezone.utc)
        return now_dt.strftime("%Y-%m-%d"), now_dt.strftime("%H:%M:%S"), str(created_at_str)


def resolve_classification(
    cursor,
    campaign_name: str,
    giving_level: str,
    company_id: str = "iqra"
) -> Dict[str, Any]:
    """
    2-Tier Classification Resolution:
    Tier 1: Look up platform_campaign_mappings for (company_id, campaign_name, giving_level) where giving_level != ''
    Tier 2: Look up platform_campaign_mappings for (company_id, campaign_name, '')
    Fallback: Auto-insert into platform_campaign_mappings with code='Unassigned'
    
    Enriches with metadata from master_project_codes.
    """
    c_name = (campaign_name or "").strip()
    g_level = (giving_level or "").strip()

    resolved_code = None
    tier_info = "Fallback (Unassigned)"

    # Tier 1: Exact campaign + giving level
    if g_level:
        cursor.execute("""
            SELECT code FROM platform_campaign_mappings
            WHERE company_id = ? AND TRIM(campaign_name) = TRIM(?) AND TRIM(giving_level) = TRIM(?)
            LIMIT 1
        """, (company_id, c_name, g_level))
        row = cursor.fetchone()
        if row and row[0]:
            resolved_code = row[0].strip()
            tier_info = "Tier 1 (Giving Level)"

    # Tier 2: Campaign default (giving_level is empty)
    if not resolved_code and c_name:
        cursor.execute("""
            SELECT code FROM platform_campaign_mappings
            WHERE company_id = ? AND TRIM(campaign_name) = TRIM(?) AND (giving_level = '' OR giving_level IS NULL)
            LIMIT 1
        """, (company_id, c_name))
        row = cursor.fetchone()
        if row and row[0]:
            resolved_code = row[0].strip()
            tier_info = "Tier 2 (Campaign Default)"

    # Fallback: Auto-Register into platform_campaign_mappings as 'Unassigned'
    if not resolved_code:
        resolved_code = "Unassigned"
        tier_info = "Fallback (Unassigned)"
        if c_name:
            try:
                # Check if this exact pair already exists with Unassigned
                cursor.execute("""
                    SELECT id FROM platform_campaign_mappings
                    WHERE company_id = ? AND TRIM(campaign_name) = TRIM(?) AND TRIM(giving_level) = TRIM(?)
                    LIMIT 1
                """, (company_id, c_name, g_level))
                if not cursor.fetchone():
                    cursor.execute("""
                        INSERT INTO platform_campaign_mappings (
                            company_id, platform, campaign_name, giving_level, code, created_at, updated_at
                        ) VALUES (?, 'givebright', ?, ?, 'Unassigned', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """, (company_id, c_name, g_level))
                    logger.info(f"Auto-registered new unmapped pair in CRM: Campaign='{c_name}' | Level='{g_level}'")
            except Exception as auto_reg_err:
                logger.warning(f"Auto-registration notice for '{c_name}': {auto_reg_err}")

    # Enrich metadata from master_project_codes
    meta = {
        "code": resolved_code,
        "department": "",
        "office": "",
        "portfolio": "",
        "country": "",
        "programme_fund": "",
        "fund_code": "",
        "zakat_eligibility": "",
        "tier": tier_info
    }

    if resolved_code and resolved_code != "Unassigned":
        cursor.execute("""
            SELECT department, office, portfolio, country, programme_fund, fund_code, zakat_eligibility
            FROM master_project_codes
            WHERE company_id = ? AND TRIM(code) = TRIM(?)
            LIMIT 1
        """, (company_id, resolved_code))
        m_row = cursor.fetchone()
        if m_row:
            meta["department"] = m_row[0] or ""
            meta["office"] = m_row[1] or ""
            meta["portfolio"] = m_row[2] or ""
            meta["country"] = m_row[3] or ""
            meta["programme_fund"] = m_row[4] or ""
            meta["fund_code"] = m_row[5] or ""
            meta["zakat_eligibility"] = m_row[6] or ""

    return meta


def build_donation_record(
    doc: Dict[str, Any],
    det: Optional[Dict[str, Any]] = None,
    classification_meta: Optional[Dict[str, Any]] = None,
    company_id: str = "iqra"
) -> Dict[str, Any]:
    """
    Builds a normalized donation dictionary matching the complete SQLite
    'donations' table schema and Parquet cache specifications.
    """
    if det is None:
        det = doc

    doc_id = str(doc.get("_id") or det.get("_id") or "").strip()
    created_at_raw = det.get("created_at") or doc.get("created_at")
    created_date, created_time, iso_raw = parse_givebrite_date(created_at_raw)

    # Financials (strictly native currency, no synthetic FX conversions)
    try:
        amount_val = float(det.get("amount", doc.get("amount", 0.0)) or 0.0)
    except (ValueError, TypeError):
        amount_val = 0.0

    currency = str(det.get("currency") or doc.get("currency") or "GBP").strip().upper()

    fees_obj = det.get("fees") if isinstance(det.get("fees"), dict) else {}
    try:
        fee_amount = float(fees_obj.get("gateway", 0.0) or 0.0)
    except (ValueError, TypeError):
        fee_amount = 0.0

    net_amount = round(amount_val - fee_amount, 2)

    # Donor Identity
    user_obj = det.get("user") if isinstance(det.get("user"), dict) else {}
    first_name = (user_obj.get("first_name") or doc.get("first_name") or "").strip()
    last_name = (user_obj.get("last_name") or doc.get("last_name") or "").strip()
    display_name = f"{first_name} {last_name}".strip()
    email = (user_obj.get("email") or doc.get("email") or "").strip().lower()

    # Gift Aid & Payment Gateway
    is_giftaid = bool(det.get("is_giftaid", doc.get("is_giftaid", False)))
    gift_aid_str = "Yes" if is_giftaid else "No"

    payment_obj = det.get("payment") if isinstance(det.get("payment"), dict) else {}
    gw_obj = det.get("gateway") if isinstance(det.get("gateway"), dict) else (doc.get("gateway") if isinstance(doc.get("gateway"), dict) else {})
    payment_method = str(payment_obj.get("method") or gw_obj.get("name") or "Card").strip()

    gw_resp = det.get("gateway_response") if isinstance(det.get("gateway_response"), dict) else (doc.get("gateway_response") if isinstance(doc.get("gateway_response"), dict) else {})
    status = str(gw_resp.get("status") or ("succeeded" if (det.get("paid") or doc.get("paid")) else "pending")).strip()
    charge_id = str(gw_resp.get("charge_id") or "").strip()

    # Campaign & Giving Level
    camp_obj = det.get("campaign") if isinstance(det.get("campaign"), dict) else (doc.get("campaign") if isinstance(doc.get("campaign"), dict) else {})
    campaign_name = str(camp_obj.get("name", "")).strip()
    campaign_slug = str(camp_obj.get("slug", "")).strip()
    campaign_url = f"https://donate.iqracharity.org/{campaign_slug}" if campaign_slug else ""

    # Giving Level extraction
    giving_level_title = ""
    impacts = camp_obj.get("impacts", []) if isinstance(camp_obj, dict) else []
    if impacts and isinstance(impacts, list) and len(impacts) > 0 and isinstance(impacts[0], dict):
        giving_level_title = str(impacts[0].get("name", "")).strip()

    # Billing Details
    billing = det.get("billing") if isinstance(det.get("billing"), dict) else {}
    b_addr1 = str(billing.get("address_line_1") or "").strip()
    b_city = str(billing.get("town_or_city") or "").strip()
    b_zip = str(billing.get("postcode") or "").strip()
    b_country = str(billing.get("country") or "GB").strip()

    # Fundraiser & Team Attribution
    fundraiser_obj = det.get("fundraiser") if isinstance(det.get("fundraiser"), dict) else (doc.get("fundraiser") if isinstance(doc.get("fundraiser"), dict) else {})
    f_id = str(fundraiser_obj.get("_id") or "").strip() if fundraiser_obj else ""
    f_name = str(fundraiser_obj.get("name") or "").strip() if fundraiser_obj else ""
    f_slug = str(fundraiser_obj.get("slug") or "").strip() if fundraiser_obj else ""
    f_url = f"https://donate.iqracharity.org/{f_slug}" if f_slug else ""

    team_obj = det.get("team") if isinstance(det.get("team"), dict) else (doc.get("team") if isinstance(doc.get("team"), dict) else {})
    t_id = str(team_obj.get("_id") or "").strip() if team_obj else ""
    t_name = str(team_obj.get("name") or "").strip() if team_obj else ""
    t_slug = str(team_obj.get("slug") or "").strip() if team_obj else ""
    t_url = f"https://donate.iqracharity.org/{t_slug}" if t_slug else ""

    offline_flag = bool(det.get("offline", doc.get("offline", False)))

    # Classification fields
    meta = classification_meta or {
        "code": "Unassigned", "department": "", "office": "", "portfolio": "",
        "country": "", "programme_fund": "", "fund_code": "", "zakat_eligibility": ""
    }

    record = {
        "Donation ID": doc_id,
        "Created Date (UTC)": created_date,
        "Created Time (UTC)": created_time,
        "Settled Date (UTC)": created_date,
        "Donation Payout Flag": "Unpaid",
        "Transaction Type": "Donation",
        "Status": status,
        "Offline or online donation": "Offline" if offline_flag else "Online",
        "First Name": first_name,
        "Last Name": last_name,
        "Display Name": display_name,
        "Email": email,
        "Marketing Consent": "No",
        "Gift Aid (yes or no)": gift_aid_str,
        "Tax Receipt requested": "No",
        "Billing Name": display_name,
        "Billing Address": b_addr1,
        "Billing Address 2": "",
        "Billing City": b_city,
        "Billing State": "",
        "Billing Zip": b_zip,
        "Billing Country": b_country,
        "Anonymous or Public": "Anonymous" if det.get("is_anonymous") else "Public",
        "Donation Currency (DC)": currency,
        "Donation Amount (in Donation Currency)": str(amount_val),
        "Project Currency": currency,
        "Donation Amount in Project Currency (May be approx.)": str(amount_val),
        "Settlement Currency": currency,
        "Total Online Donation Gross Amount in Settled Currency": str(amount_val),
        "Total Processing Fees Paid by CC In Settled Currency": fee_amount,
        "Total Online Donations Net Amount in Settled Currency": net_amount,
        "Transfer ID": None,
        "Zakat (yes or no)": "Yes" if "ZAKAT" in (giving_level_title + campaign_name).upper() else "No",
        "Zakat Amount (in Donation Currency)": amount_val if "ZAKAT" in (giving_level_title + campaign_name).upper() else 0.0,
        "Has Giving Level": "Yes" if giving_level_title else "No",
        "Giving Level Title": giving_level_title,
        "Giving Level Description": "",
        "Giving Level Type": "",
        "Giving Level Qty": 1.0,
        "Giving Level Notes": "",
        "Giving Level Email": "",
        "Giving Level Campaign Code": meta.get("code") or "Unassigned",
        "Shipping Name": "",
        "Shipping Address": "",
        "Shipping Address 2": "",
        "Shipping City": "",
        "Shipping State": "",
        "Shipping Zip": "",
        "Shipping Country": "",
        "Campaign Name": campaign_name,
        "Campaign URL": campaign_url,
        "Project Impact Location": meta.get("country") or "",
        "Community Name": "",
        "Community URL": "",
        "UTM / Referral Source": "",
        "Source User Profile": "",
        "Number of Donors": 1.0,
        "Comments": "",
        "Email (for tax receipt)": email,
        "Payment Type": payment_method,
        "Platform": "GiveBright",
        "Source": "GiveBrite Sync",
        "Donor ID": email,
        "Total LTV": amount_val,
        "Lifetime Donor Classification": "Low End",
        "Transaction Donor Classification": "Low End",
        "Payment Frequency": det.get("frequency", "one-off"),
        "subscription_id": gw_resp.get("subscription_id"),
        "_id": doc_id,
        "charge_id": charge_id,
        "fee_amount": str(fee_amount),
        "gateway": "Stripe",
        "is_giftaid": "true" if is_giftaid else "false",
        "created_at": iso_raw,
        "offline": "true" if offline_flag else "false",
        "campaign_id": str(camp_obj.get("_id") or ""),
        "fundraiser_id": f_id,
        "team_id": t_id,
        "campaign_url": campaign_url,
        "fundraiser_name": f_name,
        "fundraiser_url": f_url,
        "team_name": t_name,
        "team_url": t_url,
        "Heading": "",
        "Sub-Heading": "",
        "Country": meta.get("country") or "",
        "Code": meta.get("code") or "Unassigned",
        "Zakat Eligibility": meta.get("zakat_eligibility") or "",
        "Amount": amount_val,
        "Currency": currency,
        "Created At": iso_raw,
        "New Code": meta.get("code") or "Unassigned",
        "Fundraiser URL": f_url,
        "Payout Settled": "No",
        "_parsed_date": created_date,
        "Department": meta.get("department") or "",
        "Office": meta.get("office") or "",
        "Portfolio": meta.get("portfolio") or "",
        "Programme Fund": meta.get("programme_fund") or "",
        "Fund Code": meta.get("fund_code") or "",
        "company_id": company_id,
        "Target Country": meta.get("country") or "",
        "Giving Level Amount": amount_val if giving_level_title else 0.0
    }

    return record


def ingest_givebrite_donations(
    docs: List[Dict[str, Any]],
    headers: Optional[Dict[str, str]] = None,
    company_id: str = "iqra"
) -> Dict[str, Any]:
    """
    Main Ingestion Entrypoint:
    - Filters out donations already stored in SQLite.
    - Fetches full details for new donations.
    - Resolves 2-tier classification.
    - Atomically persists into SQLite and updates donations_cache.parquet.
    - Guarantees strict multi-tenancy (company_id = 'iqra').
    """
    assert company_id == "iqra", f"Tenant violation: GiveBrite sync must only run for 'iqra', got: {company_id}"

    if not docs:
        return {"total_incoming": 0, "inserted": 0, "skipped": 0}

    conn = get_db_connection()
    cursor = conn.cursor()

    # Step 1: Identify incoming IDs and query DB for existing records
    incoming_ids = [str(d.get("_id")).strip() for d in docs if d.get("_id")]
    if not incoming_ids:
        conn.close()
        return {"total_incoming": 0, "inserted": 0, "skipped": 0}

    # Query existing IDs using index
    placeholders = ",".join(["?"] * len(incoming_ids))
    cursor.execute(f"""
        SELECT "Donation ID" FROM donations 
        WHERE company_id = ? AND "Donation ID" IN ({placeholders})
    """, [company_id] + incoming_ids)
    existing_ids = {str(row[0]).strip() for row in cursor.fetchall() if row[0]}

    # Also check charge_id to prevent duplicates across webhook & live sync
    incoming_tx_ids = []
    for d in docs:
        gw_resp = d.get("gateway_response") if isinstance(d.get("gateway_response"), dict) else {}
        ch_id = gw_resp.get("charge_id") or d.get("charge_id")
        if ch_id:
            incoming_tx_ids.append(str(ch_id).strip())

    existing_tx_ids = set()
    if incoming_tx_ids:
        tx_placeholders = ",".join(["?"] * len(incoming_tx_ids))
        cursor.execute(f"""
            SELECT charge_id FROM donations 
            WHERE company_id = ? AND charge_id IS NOT NULL AND charge_id != '' AND charge_id IN ({tx_placeholders})
        """, [company_id] + incoming_tx_ids)
        existing_tx_ids = {str(row[0]).strip() for row in cursor.fetchall() if row[0]}

    def _is_existing(d):
        d_id = str(d.get("_id")).strip()
        if d_id in existing_ids:
            return True
        gw_resp = d.get("gateway_response") if isinstance(d.get("gateway_response"), dict) else {}
        ch_id = str(gw_resp.get("charge_id") or d.get("charge_id") or "").strip()
        if ch_id and ch_id in existing_tx_ids:
            return True
        return False

    new_docs = [d for d in docs if not _is_existing(d)]

    if not new_docs:
        conn.close()
        logger.info(f"All {len(docs)} incoming GiveBrite donations already exist in CRM. Zero insertions needed.")
        return {"total_incoming": len(docs), "inserted": 0, "skipped": len(docs)}

    logger.info(f"Found {len(new_docs)} NEW GiveBrite donations to ingest out of {len(docs)} incoming.")

    # Step 2: Enrich new donations with full details if headers provided
    records_to_insert = []
    session = requests.Session()

    for idx, doc in enumerate(new_docs):
        doc_id = str(doc.get("_id")).strip()
        det = None

        if headers:
            try:
                detail_url = f"{GIVEBRITE_API_BASE}/donations/{doc_id}"
                det_resp = session.get(detail_url, headers=headers, timeout=10)
                if det_resp.status_code == 200:
                    det = det_resp.json()
                time.sleep(0.05)  # Polite pacing
            except Exception as det_ex:
                logger.warning(f"Could not fetch detail for {doc_id}: {det_ex}")

        # Extract campaign and giving level
        camp_obj = (det or doc).get("campaign") if isinstance((det or doc).get("campaign"), dict) else {}
        c_name = camp_obj.get("name", "")
        impacts = camp_obj.get("impacts", []) if isinstance(camp_obj, dict) else []
        g_level = impacts[0].get("name", "") if (impacts and isinstance(impacts, list) and isinstance(impacts[0], dict)) else ""

        # Classification resolution
        cls_meta = resolve_classification(cursor, c_name, g_level, company_id=company_id)

        # Build normalized record
        rec = build_donation_record(doc, det=det, classification_meta=cls_meta, company_id=company_id)
        records_to_insert.append(rec)

    # Step 3: Insert new records into SQLite
    if records_to_insert:
        # Get SQLite table columns
        cursor.execute("PRAGMA table_info(donations);")
        table_cols = [c[1] for c in cursor.fetchall()]

        # Prepare parameterized INSERT
        insert_rows = []
        for r in records_to_insert:
            row_vals = [r.get(col) for col in table_cols]
            insert_rows.append(row_vals)

        col_placeholders = ",".join(["?"] * len(table_cols))
        quoted_cols = ",".join([f'"{col}"' for col in table_cols])
        sql = f"INSERT INTO donations ({quoted_cols}) VALUES ({col_placeholders})"

        cursor.executemany(sql, insert_rows)
        conn.commit()
        logger.info(f"Successfully committed {len(records_to_insert)} new GiveBrite donations into SQLite 'donations'.")

    conn.close()

    # Step 4: Update Parquet Cache & Invalidate in-memory cache
    if records_to_insert:
        try:
            update_parquet_cache(records_to_insert)
        except Exception as p_err:
            logger.error(f"Failed to update Parquet cache: {p_err}")

    # Broadcast WebSocket event so the UI refreshes in real-time
    try:
        from backend.api.events import broadcast_event_sync
        broadcast_event_sync("DONORS_UPDATED", {
            "source": "givebrite_live_sync",
            "inserted_count": len(records_to_insert),
            "company_id": company_id
        })
    except Exception:
        pass

    return {
        "total_incoming": len(docs),
        "inserted": len(records_to_insert),
        "skipped": len(existing_ids)
    }


def update_parquet_cache(new_records: List[Dict[str, Any]]) -> None:
    """
    Appends newly ingested records to donations_cache.parquet atomically
    and invalidates in-memory data cache.
    """
    if not new_records or not os.path.exists(PARQUET_PATH):
        return

    logger.info(f"Appending {len(new_records)} records to {os.path.basename(PARQUET_PATH)}...")
    df_existing = pd.read_parquet(PARQUET_PATH)
    df_new = pd.DataFrame(new_records)

    # Align columns
    for col in df_existing.columns:
        if col not in df_new.columns:
            df_new[col] = None

    # Reorder to match existing
    df_new = df_new[df_existing.columns]

    # Concatenate, deduplicate and write atomically
    df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    df_combined = df_combined.drop_duplicates(subset=["company_id", "Donation ID"], keep="last")
    atomic_write_parquet(df_combined, PARQUET_PATH)
    invalidate_data_cache()
    logger.info(f"Parquet cache updated successfully. Total rows now: {len(df_combined):,}")


def run_historical_backfill(
    token: str,
    days: int = 60,
    charity_id: str = DEFAULT_CHARITY_ID,
    company_id: str = "iqra"
) -> Dict[str, Any]:
    """
    Performs non-destructive 60-day backfill for GiveBrite donations.
    Paginates backwards until reaching 'from_date', skipping all existing IDs.
    """
    assert company_id == "iqra", "Tenant isolation violation!"
    
    headers = {
        "Authorization": f"Bearer {token.replace('Bearer ', '').strip()}",
        "Accept": "application/json",
        "Origin": "https://dashboard.givebrite.com",
        "Referer": "https://dashboard.givebrite.com/"
    }

    start_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    logger.info(f"Starting {days}-day historical GiveBrite backfill (since {start_date})...")

    page = 1
    total_inserted = 0
    total_skipped = 0
    session = requests.Session()

    while True:
        url = f"{GIVEBRITE_API_BASE}/donations?charity_id={charity_id}&page={page}&limit=50&sort_value=-1&sort_title=created_at&from_date={start_date}"
        try:
            r = session.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                logger.error(f"Backfill page {page} error: HTTP {r.status_code} - {r.text[:200]}")
                break

            data = r.json()
            docs = data.get("docs", [])
            if not docs:
                logger.info(f"Backfill reached end of records at page {page}.")
                break

            res = ingest_givebrite_donations(docs, headers=headers, company_id=company_id)
            total_inserted += res["inserted"]
            total_skipped += res["skipped"]

            has_next = data.get("hasNextPage", False)
            if not has_next:
                break

            page += 1
            time.sleep(0.2)  # Pacing between backfill pages
        except Exception as ex:
            logger.error(f"Backfill exception at page {page}: {ex}")
            break

    logger.info(f"Completed {days}-day backfill. Total Inserted: {total_inserted}, Skipped: {total_skipped}.")
    return {"status": "complete", "inserted": total_inserted, "skipped": total_skipped, "pages_scanned": page}
