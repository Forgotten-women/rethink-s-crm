"""
Rethink Website (rethinkcharity.org.uk) Real-Time Ingestion and Data Processing Pipeline
========================================================================================
Enterprise CRM module for ingesting, classifying, and persisting
Rethink Website live donations directly into SQLite ('launchgood_donations.db')
and the high-speed Parquet cache ('donations_cache.parquet').

Key Principles:
1. Strict Multi-Tenant Isolation: Enforces company_id = 'rethink'. ZERO access to 'iqra' data.
2. Native Currency Preservation: 100% platform-native amounts & fees (GBP). Zero synthetic FX conversions.
3. Successful Donations Only: Filters exclusively for Confirmed / COMPLETED transactions.
4. Reconciliation by ID: Reconciles on the basis of unique 'Reference' (pmt_...).
5. Automatic Session Cookie Rotation:
   - Uses requests.Session() with s.cookies.update(...) so Laravel's rotated scooda_session
     and XSRF-TOKEN are captured automatically on each response and persisted to system_settings.
6. 2-Tier Classification Resolution:
   - Tier 1: (campaign_name, giving_level) lookup in platform_campaign_mappings for 'website' / 'rethink_website'
   - Tier 2: (campaign_name, '') fallback
   - Enriches metadata from master_project_codes (Heading, Sub-Heading, Code, Fund, Office, Portfolio)
7. Direct Persistence: SQLite + Parquet atomic sync with _arrow_safe serialization.
"""

import os
import sys
import json
import re
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple

import requests
import pandas as pd
from bs4 import BeautifulSoup

# Core paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config.settings import LOCAL_DB_PATH, PARQUET_PATH
from core.database import get_db_connection
from core.data_processor import atomic_write_parquet, invalidate_data_cache, refresh_donor_ltv
from core.donations_reconcile import _arrow_safe
from core.utils import classify_donor_amount, canonical_donor_id

logger = logging.getLogger("rethink_website_ingestion")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [rethink_sync] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

WEBSITE_BASE_URL = "https://rethinkcharity.org.uk"
PAYMENTS_RESOURCE_URL = f"{WEBSITE_BASE_URL}/admin/finance/payments"
LIVEWIRE_UPDATE_URL = f"{WEBSITE_BASE_URL}/livewire/update"
TARGET_COMPANY = "rethink"


def get_stored_website_session() -> Optional[Dict[str, str]]:
    """Retrieves the active website session from SQLite system_settings."""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT setting_value FROM system_settings WHERE setting_key = 'rethink_website_session'")
        row = c.fetchone()
        conn.close()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as e:
        logger.error(f"Failed to load website session from DB: {e}")
    return None


def save_website_session(scooda_session: str, xsrf_token: str) -> None:
    """Updates stored session cookies in system_settings."""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "scooda_session": scooda_session.strip(),
            "xsrf_token": xsrf_token.strip(),
            "updated_at": now
        }
        c.execute("""
            INSERT INTO system_settings (setting_key, setting_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET
                setting_value = excluded.setting_value,
                updated_at = excluded.updated_at
        """, ("rethink_website_session", json.dumps(payload), now))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to save website session: {e}")


def create_website_http_session(stored_session: Dict[str, str]) -> requests.Session:
    """
    Creates a requests.Session initialized with stored session cookies.
    Automatically captures Laravel Set-Cookie rotation on every HTTP response.
    """
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    })
    scooda = stored_session.get("scooda_session", "")
    xsrf = stored_session.get("xsrf_token", "")
    if scooda:
        s.cookies.set("scooda_session", scooda, domain="rethinkcharity.org.uk")
    if xsrf:
        s.cookies.set("XSRF-TOKEN", xsrf, domain="rethinkcharity.org.uk")
    return s


def sync_back_rotated_cookies(http_session: requests.Session, previous_session: Dict[str, str]) -> None:
    """Persists rotated cookies from requests.Session back to system_settings if Laravel issued a new scooda_session."""
    latest_cookies = http_session.cookies.get_dict()
    new_scooda = latest_cookies.get("scooda_session")
    new_xsrf = latest_cookies.get("XSRF-TOKEN")
    old_scooda = previous_session.get("scooda_session")
    old_xsrf = previous_session.get("xsrf_token")

    if (new_scooda and new_scooda != old_scooda) or (new_xsrf and new_xsrf != old_xsrf):
        save_website_session(new_scooda or old_scooda, new_xsrf or old_xsrf)
        logger.debug("Persisted rotated Laravel session cookies to system_settings.")


def parse_payment_row(tr) -> Optional[Dict[str, Any]]:
    """Extracts structured fields from a single payments table <tr> element."""
    tds = tr.find_all("td")
    if not tds or len(tds) < 8:
        return None

    # Check for receipt link containing pmt_ reference
    receipt_link = tr.find("a", href=re.compile(r"/donate/payment/(pmt_[a-zA-Z0-9]+)/receipt"))
    reference = None
    if receipt_link:
        m = re.search(r"pmt_[a-zA-Z0-9]+", receipt_link.get("href", ""))
        if m:
            reference = m.group(0)

    # Fallback to any pmt_ text in the row
    if not reference:
        row_text = tr.get_text(" ", strip=True)
        m = re.search(r"pmt_[a-zA-Z0-9]+", row_text)
        if m:
            reference = m.group(0)

    if not reference:
        return None

    # Check for internal numeric ID in edit link
    edit_link = tr.find("a", href=re.compile(r"/admin/finance/payments/(\d+)/edit"))
    item_id = None
    if edit_link:
        m = re.search(r"/admin/finance/payments/(\d+)/edit", edit_link.get("href", ""))
        if m:
            item_id = float(m.group(1))

    # Cell 2: Status (Confirmed, Refunded, Pending, etc.)
    status_text = tds[2].get_text(strip=True) if len(tds) > 2 else "Confirmed"
    
    # Cell 4: Donor Name
    donor_name = tds[4].get_text(strip=True) if len(tds) > 4 else ""
    first_name, last_name = "", ""
    if donor_name:
        parts = donor_name.split()
        first_name = parts[0]
        last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

    # Cell 5: Amount (e.g. "£60")
    amount_str = tds[5].get_text(strip=True) if len(tds) > 5 else "0"
    amount_num = re.sub(r"[^\d.]", "", amount_str)
    try:
        amount = float(amount_num) if amount_num else 0.0
    except ValueError:
        amount = 0.0

    # Cell 6: Project & Appeal
    project_cell = tds[6].get_text(" ", strip=True) if len(tds) > 6 else ""
    project_name = project_cell
    appeal_name = ""
    if "Appeal:" in project_cell:
        p_parts = project_cell.split("Appeal:")
        project_name = p_parts[0].strip()
        appeal_name = p_parts[1].strip()

    # Appeal Link
    appeal_link = tr.find("a", href=re.compile(r"/fundraising/"))
    campaign_url = appeal_link.get("href") if appeal_link else ""

    # Cell 7: Payment type (Sadaqah, Zakat, etc.)
    payment_type = tds[7].get_text(strip=True) if len(tds) > 7 else "Sadaqah"
    
    # Cell 8: Gift Aid Status
    gift_aid_text = tds[8].get_text(strip=True) if len(tds) > 8 else "No"
    gift_aid = "Yes" if "eligible" in gift_aid_text.lower() else "No"

    return {
        "id": item_id,
        "reference": reference,
        "confirmation_status": status_text,
        "first_name": first_name,
        "last_name": last_name,
        "amount": amount,
        "project_name": project_name,
        "appeal_name": appeal_name,
        "campaign_url": campaign_url,
        "payment_type": payment_type,
        "gift_aid": gift_aid
    }


def fetch_livewire_payments_page(
    stored_session: Dict[str, str],
    page: int = 1,
    records_per_page: int = 50,
    http_session: Optional[requests.Session] = None
) -> Tuple[List[Dict[str, Any]], int, Optional[requests.Session]]:
    """
    Fetches a page of payments using Livewire RPC update via requests.Session().
    Automatically handles cookie rotation and preserves session state.
    """
    s = http_session or create_website_http_session(stored_session)

    # 1. Fetch initial HTML to extract CSRF token and snapshot
    resp = s.get(PAYMENTS_RESOURCE_URL, timeout=15)
    if "login" in resp.url.lower():
        raise RuntimeError("Website session has expired. Redirected to /login.")
    html = resp.text
    sync_back_rotated_cookies(s, stored_session)

    csrf_match = re.search(r"data-csrf=[\"']([^'\"]+)[\"']", html) or re.search(r"\"_token\":\s*\"([^\"]+)\"", html)
    csrf_token = csrf_match.group(1) if csrf_match else ""
    if not csrf_token:
        raise RuntimeError("Failed to extract CSRF token from payments page.")

    snapshots = re.findall(r"wire:snapshot=[\"']([^'\"]+)[\"']", html)
    target_snapshot = None
    for sn in snapshots:
        unescaped = sn.replace("&quot;", "\"")
        try:
            parsed = json.loads(unescaped)
            if "payment-resource" in parsed.get("memo", {}).get("name", ""):
                target_snapshot = unescaped
                break
        except Exception:
            pass

    if not target_snapshot:
        raise RuntimeError("Failed to extract payment-resource wire:snapshot from HTML.")

    # 2. Call Livewire update RPC
    post_headers = {
        "Content-Type": "application/json",
        "X-Livewire": "true",
        "X-CSRF-TOKEN": csrf_token,
        "Accept": "text/html, application/xhtml+xml"
    }

    payload = {
        "_token": csrf_token,
        "components": [{
            "snapshot": target_snapshot,
            "updates": {"tableRecordsPerPage": records_per_page},
            "calls": [{"path": "", "method": "gotoPage", "params": [page, "page"]}]
        }]
    }

    rpc_resp = s.post(LIVEWIRE_UPDATE_URL, json=payload, headers=post_headers, timeout=15)
    if rpc_resp.status_code != 200:
        raise RuntimeError(f"Livewire update returned HTTP {rpc_resp.status_code}: {rpc_resp.text[:150]}")
    
    sync_back_rotated_cookies(s, stored_session)
    resp_data = rpc_resp.json()

    components = resp_data.get("components", [])
    if not components:
        return [], 0, s

    c0 = components[0]
    html_chunk = c0.get("effects", {}).get("html", "")

    # Extract total count from pagination summary e.g. "Showing 1 to 50 of 778 results"
    total_count = 0
    cnt_match = re.search(r"of\s+([\d,]+)\s+results", html_chunk)
    if cnt_match:
        total_count = int(cnt_match.group(1).replace(",", ""))

    soup = BeautifulSoup(html_chunk, "html.parser")
    rows = soup.find_all("tr")
    parsed_records = []
    for r in rows:
        rec = parse_payment_row(r)
        if rec:
            parsed_records.append(rec)

    return parsed_records, total_count, s


def resolve_website_classification(cursor, campaign_name: str, campaign_url: str = "") -> Dict[str, Any]:
    """
    2-Tier classification resolution strictly for Rethink Website donations.
    Queries platform_campaign_mappings for platform in ('website', 'rethink_website')
    and company_id = 'rethink'. Enriches with master_project_codes metadata.
    """
    c_name = campaign_name.strip() if campaign_name else ""
    code = None

    if c_name:
        cursor.execute("""
            SELECT code FROM platform_campaign_mappings
            WHERE platform IN ('website', 'rethink_website')
              AND LOWER(company_id) = 'rethink'
              AND LOWER(campaign_name) = LOWER(?)
              AND code IS NOT NULL AND code != '' AND code != 'UNASSIGNED'
            ORDER BY is_primary DESC, id ASC
            LIMIT 1
        """, (c_name,))
        row = cursor.fetchone()
        if row and row[0]:
            code = row[0]

    if not code:
        # Register unknown website campaign into platform_campaign_mappings as UNASSIGNED so it surfaces in Classification Matrix
        if c_name:
            cursor.execute("""
                SELECT id FROM platform_campaign_mappings
                WHERE platform IN ('website', 'rethink_website')
                  AND LOWER(company_id) = 'rethink'
                  AND LOWER(campaign_name) = LOWER(?)
                LIMIT 1
            """, (c_name,))
            if not cursor.fetchone():
                now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("""
                    INSERT INTO platform_campaign_mappings (
                        platform, campaign_name, giving_level, code,
                        community_name, campaign_url, is_primary, company_id,
                        created_at, updated_at
                    ) VALUES (
                        'website', ?, '', 'UNASSIGNED',
                        'N/A', ?, 1, 'rethink',
                        ?, ?
                    )
                """, (c_name, campaign_url or "", now_str, now_str))

        return {
            "Code": "Unassigned",
            "Heading": "Unassigned",
            "Sub-Heading": "Unassigned",
            "Country": "",
            "Department": "",
            "Office": "",
            "Portfolio": "",
            "Programme Fund": "",
            "Fund Code": "Unassigned"
        }

    meta = {
        "Code": code,
        "Heading": "",
        "Sub-Heading": "",
        "Country": "",
        "Department": "",
        "Office": "",
        "Portfolio": "",
        "Programme Fund": "",
        "Fund Code": ""
    }

    cursor.execute("""
        SELECT code, heading, sub_heading, country, department, office, portfolio, programme_fund, fund_code
        FROM master_project_codes
        WHERE UPPER(code) = UPPER(?)
        LIMIT 1
    """, (code,))
    mrow = cursor.fetchone()
    if mrow:
        meta["Code"] = mrow[0]
        meta["Heading"] = mrow[1] or mrow[4] or ""
        meta["Sub-Heading"] = mrow[2] or mrow[5] or ""
        meta["Country"] = mrow[3] or ""
        meta["Department"] = mrow[4] or ""
        meta["Office"] = mrow[5] or ""
        meta["Portfolio"] = mrow[6] or ""
        meta["Programme Fund"] = mrow[7] or ""
        meta["Fund Code"] = mrow[8] or ""

    return meta


def ingest_rethink_website_records(records: List[Dict[str, Any]], company_id: str = "rethink") -> Dict[str, Any]:
    """
    Strict Tenant Ingestion & Reconciliation for Rethink Website donations:
    - Multi-tenant assertion: Strictly enforces company_id == 'rethink'. Never touches 'iqra'.
    - Filters exclusively for Confirmed / COMPLETED records.
    - Reconciles by ID (Reference = 'pmt_...').
    - Inserts clean rows into SQLite donations and updates donations_cache.parquet.
    """
    assert company_id == "rethink", f"Tenant violation: Website sync strictly restricted to rethink, got: {company_id}"

    if not records:
        return {"total_incoming": 0, "inserted": 0, "skipped": 0}

    valid_records = [
        r for r in records
        if str(r.get("confirmation_status", "")).strip().lower() in ("confirmed", "completed")
        and r.get("reference")
    ]

    if not valid_records:
        return {"total_incoming": len(records), "inserted": 0, "skipped": len(records)}

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        incoming_refs = [r["reference"] for r in valid_records]
        
        # Check existing IDs strictly within rethink tenant
        placeholders = ",".join(["?"] * len(incoming_refs))
        cursor.execute(f"""
            SELECT [Donation ID] FROM donations
            WHERE company_id = ? AND [Donation ID] IN ({placeholders})
        """, [company_id] + incoming_refs)
        existing_ids = {row[0] for row in cursor.fetchall()}

        to_insert = [r for r in valid_records if r["reference"] not in existing_ids]

        if not to_insert:
            conn.close()
            return {"total_incoming": len(records), "inserted": 0, "skipped": len(valid_records)}

        cursor.execute("PRAGMA table_info(donations)")
        table_cols = [c[1] for c in cursor.fetchall()]

        inserted_rows = []
        now_dt = datetime.now(timezone.utc)
        today_date = now_dt.strftime("%Y-%m-%d")
        now_time = now_dt.strftime("%H:%M:%S")

        for r in to_insert:
            created_at_raw = r.get("created_at") or today_date
            c_date = str(created_at_raw).split()[0] if " " in str(created_at_raw) else str(created_at_raw)[:10]
            c_time = str(created_at_raw).split()[1] if " " in str(created_at_raw) else now_time

            camp_name = r.get("project_name") or r.get("appeal_name") or "Diversify Your Donation"
            camp_url = r.get("campaign_url") or "https://rethinkcharity.org.uk/projects/orphan-widows-hafidh-fund"
            
            clf = resolve_website_classification(cursor, camp_name, camp_url)

            amt = float(r.get("amount") or 0.0)
            fee = float(r.get("fee") or (amt * 0.015 + 0.20))
            gross = float(r.get("gross_amount") or amt)

            donor_email = r.get("email") or ""
            donor_first = r.get("first_name") or ""
            donor_last = r.get("last_name") or ""

            ltv_class = classify_donor_amount(amt)

            row_data = {
                "Donation ID": r["reference"],
                "ID": float(r.get("id") or 0.0),
                "Created Date (UTC)": c_date,
                "Created Time (UTC)": c_time,
                "Settled Date (UTC)": c_date,
                "Status": "COMPLETED",
                "Confirmation Status": "Confirmed",
                "Offline or online donation": "online",
                "First Name": donor_first,
                "Last Name": donor_last,
                "Display Name": f"{donor_first} {donor_last}".strip(),
                "Email": donor_email,
                "Phone Number": r.get("phone") or "",
                "Gift Aid (yes or no)": r.get("gift_aid") or "No",
                "Billing Address": r.get("address_street_1") or "",
                "Billing City": r.get("address_city") or "",
                "Billing Zip": r.get("address_postal_code") or "",
                "Billing Country": r.get("address_country_code") or "United Kingdom",
                "Donor Address Country Code": r.get("address_country_code") or "GB",
                "Anonymous or Public": "Anonymous" if str(r.get("anonymous")).lower() in ("yes", "true", "1") else "Public",
                "Donation Currency (DC)": "GBP",
                "Donation Amount (in Donation Currency)": amt,
                "Donation Amount in Project Currency (May be approx.)": amt,
                "Settlement Currency": "GBP",
                "Total Online Donation Gross Amount in Settled Currency": f"£{gross:.2f}",
                "Total Online Donations Net Amount in Settled Currency": amt,
                "fee_amount": fee,
                "Payment Type": "Card / Stripe",
                "Payment Frequency": "One-Time Payment",
                "gateway": "stripe",
                "Platform": "Rethink Website",
                "Source": "Rethink Website Sync",
                "Donor ID": canonical_donor_id(
                    email=donor_email,
                    first_name=donor_first,
                    last_name=donor_last,
                    fallback_id=r["reference"],
                ),
                "Total LTV": amt,
                "Lifetime Donor Classification": ltv_class,
                "Transaction Donor Classification": ltv_class,
                "Campaign Name": camp_name,
                "Campaign URL": camp_url,
                "Zakat Eligibility": "Zakat" if "zakat" in str(r.get("payment_type", "")).lower() else "Non-Zakat",
                "Payout Settled": "No",
                "company_id": "rethink",
                "Date": c_date,
                "_parsed_date": c_date,
                "Heading": clf["Heading"],
                "Sub-Heading": clf["Sub-Heading"],
                "Country": clf["Country"],
                "Code": clf["Code"],
                "Department": clf["Department"],
                "Office": clf["Office"],
                "Portfolio": clf["Portfolio"],
                "Programme Fund": clf["Programme Fund"],
                "Fund Code": clf["Fund Code"]
            }

            clean_row = {k: v for k, v in row_data.items() if k in table_cols}
            inserted_rows.append(clean_row)

        if inserted_rows:
            cols = list(inserted_rows[0].keys())
            placeholders = ",".join(["?"] * len(cols))
            col_names = ",".join([f"[{c}]" for c in cols])
            sql = f"INSERT INTO donations ({col_names}) VALUES ({placeholders})"

            values = [[row[c] for c in cols] for row in inserted_rows]
            cursor.executemany(sql, values)
            conn.commit()
            logger.info(f"Inserted {len(inserted_rows)} new confirmed website donations into SQLite (Tenant: rethink).")

        conn.close()

        # Update parquet cache safely
        logger.info("Synchronizing donations_cache.parquet with newly ingested records...")
        conn_read = get_db_connection()
        full_df = pd.read_sql_query("SELECT * FROM donations", conn_read)
        conn_read.close()

        df_safe = _arrow_safe(full_df)
        atomic_write_parquet(df_safe, PARQUET_PATH)
        invalidate_data_cache()
        if inserted_rows:
            try:
                refresh_donor_ltv(
                    company_id=company_id,
                    donor_ids=[row.get("Donor ID") for row in inserted_rows if row.get("Donor ID")],
                )
            except Exception as ltv_err:
                logger.warning(f"LTV refresh notice (website ingest): {ltv_err}")
        logger.info("Parquet cache rebuilt and memory cache invalidated successfully.")

        return {
            "total_incoming": len(records),
            "inserted": len(inserted_rows),
            "skipped": len(valid_records) - len(inserted_rows)
        }

    except Exception as e:
        logger.error(f"Error ingesting website records: {e}")
        if conn:
            conn.close()
        raise


def run_website_sync_cycle() -> Dict[str, Any]:
    """
    Executes a single sync cycle for Rethink Website:
    - Loads stored session from system_settings.
    - Uses requests.Session() to query Livewire RPC with automatic cookie rotation.
    - Ingests new records and updates Parquet cache.
    """
    session = get_stored_website_session()
    if not session:
        return {"ok": False, "error": "No stored session in system_settings"}

    try:
        http_s = create_website_http_session(session)
        records, total_count, _ = fetch_livewire_payments_page(
            session, page=1, records_per_page=50, http_session=http_s
        )
        res = ingest_rethink_website_records(records, company_id=TARGET_COMPANY)
        return {
            "ok": True,
            "total_count": total_count,
            "fetched": len(records),
            "inserted": res["inserted"],
            "skipped": res["skipped"]
        }
    except Exception as e:
        logger.error(f"Sync cycle error: {e}")
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    print("Testing rethink_website_ingestion cycle with requests.Session()...")
    out = run_website_sync_cycle()
    print("Sync output:", out)
