"""
Madinah Real-Time Ingestion and Data Processing Pipeline
=========================================================
Enterprise CRM module for ingesting, classifying, and persisting
Madinah live donations directly into SQLite ('launchgood_donations.db')
and the high-speed Parquet cache ('donations_cache.parquet').

Key Principles:
1. Strict Multi-Tenant Isolation: Enforces company_id = 'iqra'. Never affects 'rethink'.
2. Native Currency Preservation: 100% platform-native amounts & currencies (GBP, CAD, USD, etc.).
3. Exhaustive Metadata Ingestion:
   - donationId -> 'Donation ID'
   - transactionId -> 'charge_id' (Stripe Charge ID)
   - paymentMethod.label -> 'Payment Type' (Visa, MasterCard, Apple Pay, etc.)
   - donorName / donorEmail -> 'Display Name', 'Email', 'Donor ID'
   - isAnonymous -> 'Anonymous or Public'
   - isRecurring -> 'Payment Frequency'
   - date -> ISO UTC 'Created Date (UTC)' & 'Created Time (UTC)'
4. 2-Tier Classification Resolution against platform_campaign_mappings.
5. Direct Persistence: SQLite + Parquet atomic sync (no intermediate JSON cache files).
"""

import os
import sys
import time
import logging
from datetime import datetime, timezone
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
from core.utils import classify_donor_amount

logger = logging.getLogger("madinah_ingestion")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [madinah_ingestion] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

MADINAH_APIM_BASE = "https://md-backend-prod-api.azure-api.net"


def parse_madinah_date(date_str: Optional[str]) -> Tuple[str, str, str]:
    """
    Parses Madinah ISO-8601 UTC date string (e.g. '2026-10-05T22:44:24.000Z')
    Returns: (created_date_utc, created_time_utc, raw_iso)
    """
    if not date_str:
        now_dt = datetime.now(timezone.utc)
        return now_dt.strftime("%Y-%m-%d"), now_dt.strftime("%H:%M:%S"), now_dt.isoformat()

    try:
        clean_str = str(date_str).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S"), str(date_str)
    except Exception as ex:
        logger.warning(f"Error parsing Madinah date {date_str!r}: {ex}. Falling back to UTC now.")
        now_dt = datetime.now(timezone.utc)
        return now_dt.strftime("%Y-%m-%d"), now_dt.strftime("%H:%M:%S"), str(date_str)


def normalize_campaign_text(s: Optional[str]) -> str:
    """Standardizes punctuation marks, dashes, quotes, and whitespace."""
    if not s or pd.isna(s):
        return ""
    import unicodedata
    s = unicodedata.normalize("NFKC", str(s))
    s = s.replace("’", "'").replace("‘", "'").replace("`", "'").replace("´", "'")
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("‒", "-").replace("―", "-").replace("−", "-")
    return " ".join(s.split()).strip()


def resolve_madinah_classification(
    cursor,
    campaign_name: str,
    giving_level: str = "",
    company_id: str = "iqra"
) -> Dict[str, Any]:
    """
    Resolves project classification code for Madinah campaigns using 2-Tier logic:
    Tier 1: (campaign_name, giving_level) where giving_level != ''
    Tier 2: (campaign_name, '')
    Fallback: Auto-registers unseen campaigns as 'Unassigned'
    All text is strictly standardized (punctuation, dashes, quotes).
    """
    c_name = normalize_campaign_text(campaign_name)
    g_level = normalize_campaign_text(giving_level)
    resolved_code = None

    # Tier 1: Look up exact normalized (campaign_name, giving_level)
    if c_name and g_level:
        cursor.execute("""
            SELECT code FROM platform_campaign_mappings
            WHERE company_id = ? AND LOWER(platform) = 'madinah'
              AND LOWER(TRIM(campaign_name)) = LOWER(TRIM(?))
              AND LOWER(TRIM(giving_level)) = LOWER(TRIM(?))
            ORDER BY CASE WHEN code != 'Unassigned' THEN 0 ELSE 1 END
            LIMIT 1
        """, (company_id, c_name, g_level))
        row = cursor.fetchone()
        if row and row[0] and row[0] != 'Unassigned':
            resolved_code = row[0].strip()

    # Tier 2: Campaign default (giving_level is empty)
    if not resolved_code and c_name:
        cursor.execute("""
            SELECT code FROM platform_campaign_mappings
            WHERE company_id = ? AND LOWER(platform) = 'madinah'
              AND LOWER(TRIM(campaign_name)) = LOWER(TRIM(?))
              AND LOWER(TRIM(COALESCE(giving_level, ''))) = ''
            ORDER BY CASE WHEN code != 'Unassigned' THEN 0 ELSE 1 END
            LIMIT 1
        """, (company_id, c_name))
        row = cursor.fetchone()
        if row and row[0]:
            resolved_code = row[0].strip()

    if not resolved_code:
        resolved_code = "Unassigned"
        if c_name:
            try:
                cursor.execute("""
                    SELECT id FROM platform_campaign_mappings
                    WHERE company_id = ? AND LOWER(platform) = 'madinah'
                      AND LOWER(TRIM(campaign_name)) = LOWER(TRIM(?))
                      AND LOWER(TRIM(COALESCE(giving_level, ''))) = ''
                    LIMIT 1
                """, (company_id, c_name))
                if not cursor.fetchone():
                    cursor.execute("""
                        INSERT INTO platform_campaign_mappings (
                            company_id, platform, campaign_name, giving_level, code, created_at, updated_at
                        ) VALUES (?, 'madinah', ?, '', 'Unassigned', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """, (company_id, c_name))
                    logger.info(f"Auto-registered new Madinah campaign in CRM: '{c_name}'")
            except Exception as reg_err:
                logger.warning(f"Madinah auto-registration notice for '{c_name}': {reg_err}")

    # Enrich from master_project_codes
    meta = {
        "code": resolved_code,
        "department": "",
        "office": "",
        "portfolio": "",
        "country": "",
        "programme_fund": "",
        "fund_code": "",
        "zakat_eligibility": ""
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


def build_madinah_record(
    doc: Dict[str, Any],
    classification_meta: Optional[Dict[str, Any]] = None,
    company_id: str = "iqra"
) -> Dict[str, Any]:
    """
    Builds a normalized donation record from Madinah API payload
    matching the complete SQLite 'donations' table and Parquet schema.
    """
    doc_id = str(doc.get("donationId") or "").strip()
    tx_id = str(doc.get("transactionId") or "").strip()
    created_date, created_time, iso_raw = parse_madinah_date(doc.get("date"))

    # Financials: native currency preserved in DC / Amount, settled currency is USD
    try:
        amount_val = float(doc.get("amount", 0.0) or 0.0)
    except (ValueError, TypeError):
        amount_val = 0.0

    try:
        usd_amount = float(doc.get("usdAmount") if doc.get("usdAmount") is not None else amount_val)
    except (ValueError, TypeError):
        usd_amount = amount_val

    currency = str(doc.get("currencyCode") or "USD").strip().upper()

    # Donor info
    is_anon = bool(doc.get("isAnonymous", False))
    donor_name = str(doc.get("donorName") or ("Anonymous" if is_anon else "")).strip()
    donor_email = str(doc.get("donorEmail") or "").strip().lower()

    name_parts = donor_name.split(" ", 1) if donor_name else ["", ""]
    first_name = name_parts[0] if len(name_parts) > 0 else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    # Payment method
    pm_obj = doc.get("paymentMethod") if isinstance(doc.get("paymentMethod"), dict) else {}
    payment_method = str(pm_obj.get("label") or pm_obj.get("category") or "Credit card").strip()

    status_raw = str(doc.get("status", "pending")).strip().lower()
    status_str = "succeeded" if status_raw == "success" else status_raw
    campaign_name = str(doc.get("campaignName") or "").strip()
    campaign_id = str(doc.get("campaignId") or "").strip()

    is_recurring = bool(doc.get("isRecurring", False))
    frequency = "recurring" if is_recurring else "one-off"

    meta = classification_meta or {
        "code": "Unassigned", "department": "", "office": "", "portfolio": "",
        "country": "", "programme_fund": "", "fund_code": "", "zakat_eligibility": ""
    }

    # Dynamic donor classification
    txn_class = classify_donor_amount(usd_amount)
    lifetime_class = classify_donor_amount(usd_amount)

    raw_gl = doc.get("givingLevelTitle") or (doc.get("givingLevel") if isinstance(doc.get("givingLevel"), dict) else {}).get("title") or doc.get("giving_level") or ""
    gl_title = normalize_campaign_text(str(raw_gl)) if raw_gl else ""
    if gl_title.lower() in ("none", "nan", "null"):
        gl_title = ""

    record = {
        "Donation ID": doc_id,
        "Created Date (UTC)": created_date,
        "Created Time (UTC)": created_time,
        "Settled Date (UTC)": created_date,
        "Donation Payout Flag": "Unpaid",
        "Transaction Type": "Donation",
        "Status": status_str,
        "Offline or online donation": "Online",
        "First Name": first_name,
        "Last Name": last_name,
        "Display Name": donor_name,
        "Email": donor_email,
        "Marketing Consent": "",
        "Gift Aid (yes or no)": "No",
        "Tax Receipt requested": "",
        "Billing Name": donor_name,
        "Billing Address": "",
        "Billing Address 2": "",
        "Billing City": "",
        "Billing State": "",
        "Billing Zip": "",
        "Billing Country": "",
        "Anonymous or Public": "Anonymous" if is_anon else "Public",
        "Donation Currency (DC)": currency,
        "Donation Amount (in Donation Currency)": str(amount_val),
        "Project Currency": currency,
        "Donation Amount in Project Currency (May be approx.)": str(amount_val),
        "Settlement Currency": "USD",
        "Total Online Donation Gross Amount in Settled Currency": str(usd_amount),
        "Total Processing Fees Paid by CC In Settled Currency": 0.0,
        "Total Online Donations Net Amount in Settled Currency": usd_amount,
        "Transfer ID": None,
        "Zakat (yes or no)": "Yes" if "ZAKAT" in campaign_name.upper() else "No",
        "Zakat Amount (in Donation Currency)": amount_val if "ZAKAT" in campaign_name.upper() else 0.0,
        "Has Giving Level": "Yes" if gl_title else "No",
        "Giving Level Title": gl_title,
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
        "Campaign Name": normalize_campaign_text(campaign_name),
        "Campaign URL": "",
        "Project Impact Location": meta.get("country") or "",
        "Community Name": "",
        "Community URL": "",
        "UTM / Referral Source": "",
        "Source User Profile": "",
        "Number of Donors": 1.0,
        "Comments": "",
        "Email (for tax receipt)": donor_email,
        "Payment Type": payment_method,
        "Platform": "Madinah",
        "Source": "Madinah Sync",
        "Donor ID": donor_email or doc_id,
        "Total LTV": usd_amount,
        "Lifetime Donor Classification": lifetime_class,
        "Transaction Donor Classification": txn_class,
        "Payment Frequency": frequency,
        "subscription_id": None,
        "_id": doc_id,
        "charge_id": tx_id,
        "fee_amount": "0.0",
        "gateway": "Stripe",
        "is_giftaid": "false",
        "created_at": iso_raw,
        "offline": "false",
        "campaign_id": campaign_id,
        "fundraiser_id": "",
        "team_id": "",
        "campaign_url": "",
        "fundraiser_name": "",
        "fundraiser_url": "",
        "team_name": "",
        "team_url": "",
        "Heading": "",
        "Sub-Heading": "",
        "Country": meta.get("country") or "",
        "Code": meta.get("code") or "Unassigned",
        "Zakat Eligibility": meta.get("zakat_eligibility") or "",
        "Amount": amount_val,
        "Currency": currency,
        "Created At": iso_raw,
        "New Code": meta.get("code") or "Unassigned",
        "Fundraiser URL": "",
        "Payout Settled": "No",
        "_parsed_date": created_date,
        "Department": meta.get("department") or "",
        "Office": meta.get("office") or "",
        "Portfolio": meta.get("portfolio") or "",
        "Programme Fund": meta.get("programme_fund") or "",
        "Fund Code": meta.get("fund_code") or "",
        "company_id": company_id,
        "Target Country": meta.get("country") or "",
        "Giving Level Amount": 0.0
    }

    return record


def ingest_madinah_donations(
    donations: List[Dict[str, Any]],
    company_id: str = "iqra"
) -> Dict[str, Any]:
    """
    Ingests live Madinah donations into SQLite 'donations' and updates Parquet.
    Filters out records already present via 'Donation ID' or 'charge_id'.
    """
    assert company_id == "iqra", f"Tenant violation: Madinah sync only runs for 'iqra', got: {company_id}"

    if not donations:
        return {"total_incoming": 0, "inserted": 0, "skipped": 0}

    conn = get_db_connection()
    cursor = conn.cursor()

    d_ids = [str(d.get("donationId", "")).strip() for d in donations if d.get("donationId")]
    tx_ids = [str(d.get("transactionId", "")).strip() for d in donations if d.get("transactionId")]

    # Check existing by Donation ID and charge_id
    existing_d_ids = set()
    if d_ids:
        placeholders_d = ",".join(["?"] * len(d_ids))
        cursor.execute(f"""
            SELECT "Donation ID" FROM donations 
            WHERE company_id = ? AND "Donation ID" IN ({placeholders_d})
        """, [company_id] + d_ids)
        existing_d_ids = {r[0] for r in cursor.fetchall()}

    existing_tx_ids = set()
    if tx_ids:
        placeholders_tx = ",".join(["?"] * len(tx_ids))
        cursor.execute(f"""
            SELECT charge_id FROM donations 
            WHERE company_id = ? AND charge_id IN ({placeholders_tx})
        """, [company_id] + tx_ids)
        existing_tx_ids = {r[0] for r in cursor.fetchall()}

    new_donations = []
    updated_records = []

    for d in donations:
        did = str(d.get("donationId", "")).strip()
        txid = str(d.get("transactionId", "")).strip()
        status_val = str(d.get("status", "")).strip().lower()

        # If incoming donation failed or cancelled, do not ingest as active revenue
        if status_val and status_val != "success":
            if did in existing_d_ids:
                try:
                    cursor.execute("""
                        UPDATE donations
                        SET Status = 'failed',
                            "Total Online Donation Gross Amount in Settled Currency" = '0.0',
                            "Total Online Donations Net Amount in Settled Currency" = 0.0,
                            Amount = 0.0
                        WHERE company_id = ? AND "Donation ID" = ?
                    """, (company_id, did))
                    if cursor.rowcount > 0:
                        updated_records.append(did)
                except Exception as f_err:
                    logger.warning(f"Error zeroing out failed donation {did}: {f_err}")
            continue

        if did not in existing_d_ids and txid not in existing_tx_ids:
            new_donations.append(d)
        elif did in existing_d_ids:
            # Check and self-heal any discrepancies in settled currency or usdAmount
            try:
                amt_val = float(d.get("amount", 0.0) or 0.0)
                u_amt = float(d.get("usdAmount") if d.get("usdAmount") is not None else amt_val)
                curr = str(d.get("currencyCode") or "USD").strip().upper()
                t_cls = classify_donor_amount(u_amt)
                cursor.execute("""
                    UPDATE donations
                    SET "Settlement Currency" = 'USD',
                        "Total Online Donation Gross Amount in Settled Currency" = ?,
                        "Total Online Donations Net Amount in Settled Currency" = ?,
                        "Total LTV" = ?,
                        "Lifetime Donor Classification" = ?,
                        "Transaction Donor Classification" = ?,
                        "Donation Currency (DC)" = ?,
                        "Donation Amount (in Donation Currency)" = ?,
                        "Amount" = ?,
                        "Currency" = ?
                    WHERE company_id = ? AND "Donation ID" = ?
                      AND ("Settlement Currency" != 'USD' OR "Total Online Donation Gross Amount in Settled Currency" != ?)
                """, (str(u_amt), u_amt, u_amt, t_cls, t_cls, curr, str(amt_val), amt_val, curr, company_id, did, str(u_amt)))
                if cursor.rowcount > 0:
                    updated_records.append(did)
            except Exception as u_err:
                logger.warning(f"Error checking settled amount for existing {did}: {u_err}")

    if updated_records:
        conn.commit()
        logger.info(f"Self-healed {len(updated_records)} existing Madinah records to settled USD amounts in SQLite.")

    if not new_donations and not updated_records:
        conn.close()
        logger.info(f"All {len(donations)} incoming Madinah donations up-to-date in CRM. Zero insertions needed.")
        return {"total_incoming": len(donations), "inserted": 0, "skipped": len(donations), "updated": 0}

    records_to_insert = []
    for d in new_donations:
        c_name = normalize_campaign_text(d.get("campaignName", ""))
        gl_obj = d.get("givingLevel") if isinstance(d.get("givingLevel"), dict) else {}
        g_level = normalize_campaign_text(str(d.get("givingLevelTitle") or gl_obj.get("title") or d.get("giving_level") or ""))
        cls_meta = resolve_madinah_classification(cursor, c_name, giving_level=g_level, company_id=company_id)
        rec = build_madinah_record(d, classification_meta=cls_meta, company_id=company_id)
        records_to_insert.append(rec)

    if records_to_insert:
        cursor.execute("PRAGMA table_info(donations);")
        table_cols = [c[1] for c in cursor.fetchall()]

        insert_rows = []
        for r in records_to_insert:
            insert_rows.append([r.get(col) for col in table_cols])

        col_placeholders = ",".join(["?"] * len(table_cols))
        quoted_cols = ",".join([f'"{col}"' for col in table_cols])
        sql = f"INSERT INTO donations ({quoted_cols}) VALUES ({col_placeholders})"

        cursor.executemany(sql, insert_rows)
        conn.commit()
        logger.info(f"Successfully committed {len(records_to_insert)} new Madinah donations into SQLite 'donations'.")

    conn.close()

    # Update Parquet cache for both inserted and self-healed records
    all_parquet_sync = list(records_to_insert)
    if updated_records:
        try:
            conn_u = get_db_connection()
            cur_u = conn_u.cursor()
            placeholders_u = ",".join(["?"] * len(updated_records))
            cur_u.execute(f"""
                SELECT * FROM donations
                WHERE company_id = ? AND "Donation ID" IN ({placeholders_u})
            """, [company_id] + updated_records)
            cols = [c[0] for c in cur_u.description]
            for row in cur_u.fetchall():
                all_parquet_sync.append(dict(zip(cols, row)))
            conn_u.close()
        except Exception as u_fetch_err:
            logger.warning(f"Failed fetching updated rows for Parquet: {u_fetch_err}")

    if all_parquet_sync:
        try:
            update_madinah_parquet_cache(all_parquet_sync)
        except Exception as p_err:
            logger.error(f"Failed to update Parquet cache for Madinah: {p_err}")

    # Broadcast WebSocket update
    try:
        from backend.api.events import broadcast_event_sync
        broadcast_event_sync("DONORS_UPDATED", {
            "source": "madinah_live_sync",
            "inserted_count": len(records_to_insert),
            "company_id": company_id
        })
    except Exception:
        pass

    return {
        "total_incoming": len(donations),
        "inserted": len(records_to_insert),
        "skipped": len(donations) - len(records_to_insert)
    }


def update_madinah_parquet_cache(new_records: List[Dict[str, Any]]) -> None:
    """Appends new records to donations_cache.parquet atomically."""
    if not new_records or not os.path.exists(PARQUET_PATH):
        return

    logger.info(f"Appending {len(new_records)} Madinah records to {os.path.basename(PARQUET_PATH)}...")
    df_existing = pd.read_parquet(PARQUET_PATH)
    df_new = pd.DataFrame(new_records)

    for col in df_existing.columns:
        if col not in df_new.columns:
            df_new[col] = None

    df_new = df_new[df_existing.columns]
    df_combined = pd.concat([df_existing, df_new], ignore_index=True)

    # Deduplicate safely: only collapse rows with non-empty Donation IDs
    mask_has_id = df_combined["Donation ID"].notna() & (df_combined["Donation ID"].astype(str).str.strip() != "")
    df_with_id = df_combined[mask_has_id].drop_duplicates(subset=["company_id", "Donation ID"], keep="last")
    df_no_id = df_combined[~mask_has_id]
    df_combined = pd.concat([df_with_id, df_no_id], ignore_index=True)
    atomic_write_parquet(df_combined, PARQUET_PATH)
    invalidate_data_cache()
    logger.info(f"Parquet cache updated successfully with Madinah records. Total rows now: {len(df_combined):,}")
