import json
import os
import sqlite3
import datetime
import threading
from typing import Optional, Dict, Any

from fastapi import APIRouter, BackgroundTasks, Request, HTTPException, status, Query, Depends
import pandas as pd
import numpy as np

from config.settings import LOCAL_DB_PATH, PARQUET_PATH
from core.data_processor import (
    load_data,
    sanitize_df_dtypes_for_parquet,
    init_classification_db,
    fix_mojibake,
    get_code_to_classification_map,
    atomic_write_parquet
)
from core.utils import classify_donor_amount
from backend.api.events import broadcast_event_sync
from backend.api.auth import require_super_admin

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])

_WEBHOOK_LOCK = threading.Lock()

def init_webhooks_db():
    """Ensures webhook audit log table exists in SQLite database."""
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS givebrite_webhook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id TEXT NOT NULL,
                event_type TEXT,
                event_id TEXT,
                payload TEXT,
                status TEXT DEFAULT 'pending',
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_gb_webhook_event_id ON givebrite_webhook_events(event_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_gb_webhook_company ON givebrite_webhook_events(company_id)")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Webhook DB Init Notice]: {e}")

# Initialize DB on module load
init_webhooks_db()


def _log_webhook_event(company_id: str, event_type: str, event_id: str, payload: dict, status: str = "received", error: str = None):
    """Persists a raw incoming webhook payload to SQLite for 100% audit durability."""
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO givebrite_webhook_events (company_id, event_type, event_id, payload, status, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (company_id, event_type, event_id, json.dumps(payload, default=str), status, error))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Webhook Audit Log Notice]: {e}")


def _lookup_givebrite_classification(campaign_name: str, company_id: str = "rethink", giving_level: str = "") -> Dict[str, str]:
    """
    Looks up the master classification details for a GiveBrite campaign by querying:
    1. platform_campaign_mappings for (campaign_name, giving_level) match first, then campaign default
    2. master_project_codes (via get_code_to_classification_map) to retrieve official
       Department, Office, Portfolio, Country, and Zakat Eligibility.
    3. Keyword fallback rules if brand new / unassigned.
    """
    comp = str(company_id or "rethink").strip().lower()
    cname_clean = str(campaign_name or "").strip()
    gl_clean = str(giving_level or "").strip().lower()
    if not cname_clean or cname_clean.lower() in ["nan", "none", "n/a", ""]:
        return {
            "Department": "Unassigned",
            "Office": "Unassigned",
            "Portfolio": "",
            "Programme Fund": "",
            "Heading": "Unassigned",
            "Sub-Heading": "Unassigned",
            "Country": "Unassigned",
            "Target Country": "Unassigned",
            "Code": "Unassigned",
            "Zakat Eligibility": "Unassigned"
        }

    # 1. Check if (campaign_name, giving_level) or campaign default has an assigned code in platform_campaign_mappings
    assigned_code = None
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        cur = conn.cursor()
        if gl_clean and gl_clean not in ["nan", "none", "n/a", "unassigned", ""]:
            cur.execute("""
                SELECT code FROM platform_campaign_mappings
                WHERE LOWER(COALESCE(company_id, 'rethink')) = ? 
                  AND platform IN ('givebright', 'givebrite') 
                  AND LOWER(campaign_name) = ?
                  AND LOWER(COALESCE(giving_level, '')) = ?
                LIMIT 1
            """, (comp, cname_clean.lower(), gl_clean))
            row = cur.fetchone()
            if row and row[0] and str(row[0]).strip().lower() not in ["", "unassigned", "nan", "none"]:
                assigned_code = str(row[0]).strip().upper()

        if not assigned_code:
            cur.execute("""
                SELECT code FROM platform_campaign_mappings
                WHERE LOWER(COALESCE(company_id, 'rethink')) = ? 
                  AND platform IN ('givebright', 'givebrite') 
                  AND LOWER(campaign_name) = ?
                  AND (LOWER(COALESCE(giving_level, '')) = '' OR is_primary = 1)
                ORDER BY is_primary DESC
                LIMIT 1
            """, (comp, cname_clean.lower()))
            row = cur.fetchone()
            if row and row[0] and str(row[0]).strip().lower() not in ["", "unassigned", "nan", "none"]:
                assigned_code = str(row[0]).strip().upper()
        conn.close()
    except Exception as e:
        print(f"[Campaign Mapping Lookup Notice]: {e}")

    # 2. If assigned code exists, resolve full classification from master_project_codes
    if assigned_code:
        code_map = get_code_to_classification_map(company_id=comp)
        if assigned_code.lower() in code_map:
            m = code_map[assigned_code.lower()]
            dept = m.get("Department") or m.get("Heading") or "Unassigned"
            off = m.get("Office") or m.get("Sub-Heading") or "Unassigned"
            cntry = m.get("Country") or "Unassigned"
            zkt = m.get("Zakat Eligibility") or "Unassigned"
            return {
                "Code": assigned_code,
                "Department": dept,
                "Office": off,
                "Portfolio": m.get("Portfolio", ""),
                "Programme Fund": m.get("Programme Fund", ""),
                "Heading": dept,
                "Sub-Heading": off,
                "Country": cntry,
                "Target Country": cntry,
                "Zakat Eligibility": zkt
            }

    # 3. Keyword-based initial guess if not yet assigned
    cname_lower = cname_clean.lower()
    kw = cname_lower
    code = "Unassigned"
    dept = "Unassigned"
    off = "Unassigned"
    country = "Unassigned"
    zakat = "Unassigned"

    if "orphan" in kw:
        code = "SHAM-EDU-SPN-ORP" if comp == "rethink" else "IQRA-SPN-ORP"
        dept = "Sponsorships"
        off = "Orphan Sponsorship"
        country = "Shaam" if comp == "rethink" else "Bangladesh"
        zakat = "Zakat"
    elif "hafiz" in kw or "hafidh" in kw:
        code = "SHAM-EDU-SPN-HUF" if comp == "rethink" else "IQRA-SPN-HUF"
        dept = "Sponsorships"
        off = "Huffaz Sponsorships"
        country = "Shaam" if comp == "rethink" else "Bangladesh"
        zakat = "Non-Zakat"
    elif "rising star" in kw or "school" in kw or "classroom" in kw or "nursery" in kw:
        code = "SHAM-INF-VIL-SCH" if comp == "rethink" else "IQRA-EDU-SCH"
        dept = "Village"
        off = "Village School"
        country = "Shaam" if comp == "rethink" else "Bangladesh"
        zakat = "Non-Zakat"
    elif "gaza" in kw or "palestine" in kw:
        code = "GAZ-SOC-EMR-GEN"
        dept = "Emergency Response"
        off = "General Emergency Aid"
        country = "Gaza"
        zakat = "Zakat"
    elif "widow" in kw or "family" in kw:
        code = "SHAM-EDU-SPN-WID" if comp == "rethink" else "IQRA-SOC-WID"
        dept = "Sponsorships"
        off = "Widow Sponsorship"
        country = "Shaam" if comp == "rethink" else "Bangladesh"
        zakat = "Zakat"

    # Attempt to resolve full master details for keyword code if found
    if code != "Unassigned":
        code_map = get_code_to_classification_map(company_id=comp)
        if code.lower() in code_map:
            m = code_map[code.lower()]
            dept = m.get("Department") or dept
            off = m.get("Office") or off
            country = m.get("Country") or country
            zakat = m.get("Zakat Eligibility") or zakat

    return {
        "Code": code,
        "Department": dept,
        "Office": off,
        "Portfolio": "",
        "Programme Fund": "",
        "Heading": dept,
        "Sub-Heading": off,
        "Country": country,
        "Target Country": country,
        "Zakat Eligibility": zakat
    }


def _lookup_fundraiser_for_campaign(campaign_name: str, code: str = "", company_id: str = "rethink") -> Optional[str]:
    """
    Determines if an incoming campaign is assigned to a specific fundraiser in our CRM records.
    1. First checks fundraiser_campaigns explicit table assignments.
    2. If not found, checks historical donations dataset for dominant assigned fundraiser (> 10 donations).
    3. If that campaign has no fundraiser assigned in our records, returns None (incoming fundraiser stays).
    """
    comp = str(company_id or "rethink").strip().lower()
    cname_clean = str(campaign_name or "").strip()
    if not cname_clean:
        return None

    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        cur = conn.cursor()
        
        # 1. Explicit assignment in fundraiser_campaigns
        cur.execute("""
            SELECT f.name 
            FROM fundraiser_campaigns fc
            JOIN fundraisers f ON fc.fundraiser_id = f.id
            WHERE LOWER(COALESCE(fc.company_id, 'rethink')) = ?
              AND LOWER(fc.campaign_name) = ?
              AND (LOWER(fc.code) = ? OR fc.code IS NULL OR fc.code = '' OR LOWER(fc.code) = 'all' OR LOWER(fc.code) = 'unassigned')
            LIMIT 1
        """, (comp, cname_clean.lower(), str(code or "").strip().lower()))
        row = cur.fetchone()
        if row and row[0]:
            conn.close()
            return str(row[0]).strip()

        # 2. Check if this campaign already has a primary assigned fundraiser in donations dataset
        cur.execute("""
            SELECT fundraiser_name, COUNT(*) as cnt
            FROM donations
            WHERE LOWER(COALESCE(company_id, 'rethink')) = ?
              AND LOWER("Campaign Name") = ?
              AND fundraiser_name IS NOT NULL
              AND fundraiser_name != ''
              AND LOWER(fundraiser_name) NOT IN ('nan', 'none', 'n/a')
            GROUP BY fundraiser_name
            ORDER BY cnt DESC
            LIMIT 1
        """, (comp, cname_clean.lower()))
        hist_row = cur.fetchone()
        conn.close()
        if hist_row and hist_row[0] and hist_row[1] >= 10:
            return str(hist_row[0]).strip()
    except Exception as e:
        print(f"[Fundraiser Mapping Notice]: {e}")

    return None


def _ensure_campaign_registered(campaign_name: str, campaign_url: str = "", company_id: str = "rethink", giving_level: str = "") -> None:
    """
    Registers a campaign and optional giving_level variant into platform_campaign_mappings if not present.
    If already present, updates campaign_url but STRICTLY PRESERVES all existing assigned codes.
    """
    comp = str(company_id or "rethink").strip().lower()
    cname_clean = str(campaign_name or "").strip()
    if not cname_clean or cname_clean.lower() in ["nan", "none", "n/a", ""]:
        return

    gl_clean = str(giving_level or "").strip()
    if gl_clean.lower() in ["nan", "none", "n/a", "unassigned", "default", "general"]:
        gl_clean = ""

    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        cur = conn.cursor()
        # 1. Primary/General campaign record
        cur.execute("""
            SELECT code FROM platform_campaign_mappings
            WHERE LOWER(COALESCE(company_id, 'rethink')) = ? 
              AND platform IN ('givebright', 'givebrite') 
              AND LOWER(campaign_name) = ?
              AND (LOWER(COALESCE(giving_level, '')) = '' OR is_primary = 1)
            LIMIT 1
        """, (comp, cname_clean.lower()))
        default_row = cur.fetchone()

        if default_row:
            camp_code = default_row[0]
            if campaign_url and str(campaign_url).strip():
                cur.execute("""
                    UPDATE platform_campaign_mappings
                    SET campaign_url = ?
                    WHERE LOWER(COALESCE(company_id, 'rethink')) = ? 
                      AND platform IN ('givebright', 'givebrite') 
                      AND LOWER(campaign_name) = ?
                """, (campaign_url.strip(), comp, cname_clean.lower()))
                conn.commit()
        else:
            class_info = _lookup_givebrite_classification(cname_clean, company_id=comp)
            camp_code = class_info.get("Code") or "Unassigned"
            cur.execute("""
                INSERT INTO platform_campaign_mappings (
                    platform, campaign_name, giving_level, code, community_name, campaign_url, is_primary, company_id
                ) VALUES ('givebright', ?, '', ?, 'GiveBright', ?, 1, ?)
            """, (cname_clean, camp_code, campaign_url.strip() if campaign_url else "", comp))
            conn.commit()
            broadcast_event_sync("MATRIX_UPDATED", {"source": "givebrite_webhook", "company_id": comp, "campaign": cname_clean})

        # 2. Specific giving level variant record if provided
        if gl_clean:
            cur.execute("""
                SELECT code FROM platform_campaign_mappings
                WHERE LOWER(COALESCE(company_id, 'rethink')) = ? 
                  AND platform IN ('givebright', 'givebrite') 
                  AND LOWER(campaign_name) = ? 
                  AND LOWER(COALESCE(giving_level, '')) = ?
                LIMIT 1
            """, (comp, cname_clean.lower(), gl_clean.lower()))
            var_row = cur.fetchone()
            if not var_row:
                var_code = camp_code if camp_code and str(camp_code).lower() not in ["unassigned", "nan", "none", ""] else "Unassigned"
                cur.execute("""
                    INSERT INTO platform_campaign_mappings (
                        platform, campaign_name, giving_level, code, community_name, campaign_url, is_primary, company_id
                    ) VALUES ('givebright', ?, ?, ?, 'GiveBright', ?, 0, ?)
                """, (cname_clean, gl_clean, var_code, campaign_url.strip() if campaign_url else "", comp))
                conn.commit()
                broadcast_event_sync("MATRIX_UPDATED", {"source": "givebrite_webhook", "company_id": comp, "campaign": cname_clean, "giving_level": gl_clean})

        conn.close()
    except Exception as e:
        print(f"[Campaign Auto-Register Notice]: {e}")


def process_givebrite_webhook_payload(company_id: str, payload: dict) -> Dict[str, Any]:
    """
    Main webhook processing worker for GiveBrite.
    Handles 'donation.create', 'campaign.create', and 'campaign.update'.
    Bypasses and acknowledges 'fundraiser.*' and 'team.*' events.
    """
    target_cid = str(company_id or "rethink").strip().lower()
    event_type = str(payload.get("type") or "unknown").strip()
    event_id = str(payload.get("_id") or "").strip()

    # Log raw event for auditability
    _log_webhook_event(target_cid, event_type, event_id, payload, status="processing")

    # 1. Ignored event types (Fundraiser & Volunteer Tracking unchanged per requirements)
    if event_type in ["fundraiser.create", "fundraiser.update", "team.create", "team.update"]:
        _log_webhook_event(target_cid, event_type, event_id, payload, status="bypassed_acknowledged")
        return {
            "status": "success",
            "action": "bypassed",
            "event": event_type,
            "message": f"Event '{event_type}' acknowledged (volunteer tracking bypassed per config)."
        }

    # 2. Campaign Create / Update
    if event_type in ["campaign.create", "campaign.update"]:
        c_name = str(payload.get("name") or "").strip()
        c_url = str(payload.get("url") or payload.get("slug") or "").strip()
        if c_url and not c_url.startswith("http"):
            c_url = f"https://givebrite.com/{c_url}"

        if c_name:
            _ensure_campaign_registered(c_name, campaign_url=c_url, company_id=target_cid)
            _log_webhook_event(target_cid, event_type, event_id, payload, status="campaign_registered")
            return {
                "status": "success",
                "action": "campaign_synced",
                "event": event_type,
                "campaign": c_name,
                "message": f"Campaign '{c_name}' synced to classification matrix (existing codes preserved)."
            }
        else:
            return {"status": "success", "action": "noop", "message": "Campaign event missing campaign name."}

    # 3. Donation Create
    if event_type == "donation.create" or ("amount" in payload and "email" in payload):
        with _WEBHOOK_LOCK:
            try:
                # Extract fields
                don_id = str(payload.get("_id") or f"GB-{int(datetime.datetime.now().timestamp())}").strip()
                created_raw = payload.get("created_at")
                if created_raw:
                    try:
                        dt = pd.to_datetime(created_raw)
                        created_date = dt.strftime("%Y-%m-%d")
                        created_time = dt.strftime("%H:%M:%S")
                    except Exception:
                        created_date = datetime.date.today().strftime("%Y-%m-%d")
                        created_time = "00:00:00"
                else:
                    created_date = datetime.date.today().strftime("%Y-%m-%d")
                    created_time = "00:00:00"

                first_name = str(payload.get("first_name") or "").strip()
                last_name = str(payload.get("last_name") or "").strip()
                is_anon = bool(payload.get("is_anonymous", False))
                if is_anon:
                    display_name = "Anonymous Donor"
                else:
                    display_name = f"{first_name} {last_name}".strip() or "Anonymous Donor"

                email = str(payload.get("email") or "").strip()
                amount = float(pd.to_numeric(payload.get("amount", 0.0), errors="coerce") or 0.0)
                currency = str(payload.get("currency") or "GBP").upper()

                freq_raw = str(payload.get("frequency") or "one-off").lower()
                payment_freq = "Recurring Payment" if freq_raw in ["monthly", "regular", "recurring"] else "One-Time Payment"

                is_zakat_flag = bool(payload.get("is_zakat", False)) or str(payload.get("donation_type") or "").lower() == "zakat"
                zakat_str = "Yes" if is_zakat_flag else "No"
                giftaid_str = "Yes" if bool(payload.get("is_giftaid", False)) else "No"

                # Campaign & Attribution
                camp_obj = payload.get("campaign") or {}
                if isinstance(camp_obj, dict):
                    camp_name = str(camp_obj.get("name") or "Unassigned").strip()
                    camp_url = str(camp_obj.get("url") or camp_obj.get("slug") or "").strip()
                else:
                    camp_name = str(camp_obj or "Unassigned").strip()
                    camp_url = ""

                if not camp_name or camp_name.lower() in ["nan", "none", "null", "direct donation", "direct donation (unassigned)", ""]:
                    camp_name = "Unassigned"

                impact_val = payload.get("impact_name") or payload.get("impact")
                if isinstance(impact_val, dict):
                    impact_val = impact_val.get("name") or impact_val.get("title") or ""
                giving_level = str(
                    impact_val
                    or payload.get("giving_level")
                    or payload.get("giving_level_title")
                    or payload.get("giving_levels")
                    or payload.get("variant")
                    or payload.get("option")
                    or ""
                ).strip()

                fund_obj = payload.get("fundraiser") or {}
                fund_name = str(fund_obj.get("name") or "").strip() if isinstance(fund_obj, dict) else str(fund_obj or "").strip()

                team_obj = payload.get("team") or {}
                team_name = str(team_obj.get("name") or "").strip() if isinstance(team_obj, dict) else str(team_obj or "").strip()

                # Billing / Geo
                billing = payload.get("billing") or {}
                if isinstance(billing, dict):
                    b_addr1 = str(billing.get("address_line_1") or "").strip()
                    b_addr2 = str(billing.get("address_line_2") or "").strip()
                    b_addr = f"{b_addr1}, {b_addr2}".strip(", ") if b_addr2 else b_addr1
                    b_city = str(billing.get("town") or "").strip()
                    b_zip = str(billing.get("postcode") or "").strip()
                    b_country = str(billing.get("country") or "United Kingdom").strip()
                    phone = str(billing.get("phone_number") or "").strip()
                else:
                    b_addr = ""
                    b_city = ""
                    b_zip = ""
                    b_country = "United Kingdom"
                    phone = ""

                # Comments & Charge ID
                comment = str(payload.get("comment") or "").strip()
                gw_resp = payload.get("gateway_response") or {}
                charge_id = str(gw_resp.get("charge_id") or "").strip() if isinstance(gw_resp, dict) else ""

                # Register campaign and giving level in classification matrix if valid
                if camp_name and camp_name.lower() not in ["unassigned", "nan", "none", ""]:
                    _ensure_campaign_registered(camp_name, campaign_url=camp_url, company_id=target_cid, giving_level=giving_level)

                # Classify donation using stored company matrix
                class_info = _lookup_givebrite_classification(camp_name, company_id=target_cid, giving_level=giving_level)

                # Auto-resolve mapped fundraiser from CRM records if campaign is mapped
                mapped_fund = _lookup_fundraiser_for_campaign(camp_name, code=class_info.get("Code", ""), company_id=target_cid)
                if mapped_fund:
                    fund_name = mapped_fund

                # Calculate Donor ID, LTV and Classifications
                donor_id = email.strip().lower() if email.strip() else (f"{first_name} {last_name}".strip().lower() or don_id)
                txn_class = classify_donor_amount(amount)

                prior_ltv = 0.0
                if os.path.exists(PARQUET_PATH):
                    try:
                        df_chk = pd.read_parquet(PARQUET_PATH, columns=["Donor ID", "Total Online Donations Net Amount in Settled Currency", "Amount", "company_id"])
                        if df_chk is not None and not df_chk.empty:
                            amt_s = pd.to_numeric(df_chk.get("Total Online Donations Net Amount in Settled Currency", df_chk.get("Amount", 0.0)), errors="coerce").fillna(0.0)
                            did_s = df_chk.get("Donor ID", pd.Series("", index=df_chk.index)).astype(str).str.strip().str.lower()
                            cid_s = df_chk.get("company_id", pd.Series("rethink", index=df_chk.index)).astype(str).str.strip().str.lower()
                            prior_ltv = float(amt_s[(did_s == donor_id) & (cid_s == target_cid)].sum())
                    except Exception:
                        prior_ltv = 0.0

                total_ltv = round(prior_ltv + amount, 2)
                lifetime_class = classify_donor_amount(total_ltv)

                # Create standardized record
                row_data = {
                    "Donation ID": don_id,
                    "Created Date (UTC)": created_date,
                    "Created Time (UTC)": created_time,
                    "First Name": first_name,
                    "Last Name": last_name,
                    "Display Name": display_name,
                    "Email": email,
                    "Donor ID": donor_id,
                    "Donation Amount (in Donation Currency)": amount,
                    "Donation Currency (DC)": currency,
                    "Amount": amount,
                    "Total Online Donations Net Amount in Settled Currency": amount,
                    "Total Online Donation Gross Amount in Settled Currency": amount,
                    "Total LTV": total_ltv,
                    "Lifetime Donor Classification": lifetime_class,
                    "Transaction Donor Classification": txn_class,
                    "Settlement Currency": currency,
                    "Platform": "GiveBright",
                    "Payment Type": "Card / Stripe",
                    "Payment Frequency": payment_freq,
                    "Zakat (yes or no)": zakat_str,
                    "Gift Aid (yes or no)": giftaid_str,
                    "Anonymous or Public": "Anonymous" if is_anon else "Public",
                    "Campaign Name": camp_name,
                    "Giving Level Title": giving_level,
                    "Campaign URL": camp_url,
                    "Community Name": "GiveBright",
                    "fundraiser_name": fund_name,
                    "team_name": team_name,
                    "Billing Address": b_addr,
                    "Billing City": b_city,
                    "Billing Zip": b_zip,
                    "Billing Country": b_country,
                    "Phone Number": phone,
                    "Comments": comment,
                    "charge_id": charge_id,
                    "Source": "GiveBrite Webhook",
                    "company_id": target_cid,
                    "Code": class_info.get("Code", "Unassigned"),
                    "Department": class_info.get("Department", class_info.get("Heading", "Unassigned")),
                    "Office": class_info.get("Office", class_info.get("Sub-Heading", "Unassigned")),
                    "Portfolio": class_info.get("Portfolio", ""),
                    "Programme Fund": class_info.get("Programme Fund", ""),
                    "Heading": class_info.get("Heading", class_info.get("Department", "Unassigned")),
                    "Sub-Heading": class_info.get("Sub-Heading", class_info.get("Office", "Unassigned")),
                    "Country": class_info.get("Country", "Unassigned"),
                    "Target Country": class_info.get("Target Country", class_info.get("Country", "Unassigned")),
                    "Zakat Eligibility": class_info.get("Zakat Eligibility", "Unassigned")
                }

                df_new_row = pd.DataFrame([row_data])

                # 1. Thread-safe merge into Parquet cache (deduplicating by Donation ID)
                if os.path.exists(PARQUET_PATH):
                    try:
                        df_existing = pd.read_parquet(PARQUET_PATH)
                        if df_existing is not None and not df_existing.empty:
                            if "Donation ID" in df_existing.columns:
                                df_existing = df_existing[df_existing["Donation ID"].astype(str).str.strip() != don_id]
                            df_save = pd.concat([df_existing, df_new_row], ignore_index=True)
                        else:
                            df_save = df_new_row
                    except Exception:
                        df_save = df_new_row
                else:
                    df_save = df_new_row

                # Sync updated LTV and Lifetime Classification for all records of this donor
                if "Donor ID" in df_save.columns:
                    donor_mask = (df_save["Donor ID"].astype(str).str.strip().str.lower() == donor_id) & (df_save["company_id"].astype(str).str.strip().str.lower() == target_cid)
                    if donor_mask.any():
                        df_save.loc[donor_mask, "Total LTV"] = total_ltv
                        df_save.loc[donor_mask, "Lifetime Donor Classification"] = lifetime_class

                df_save = sanitize_df_dtypes_for_parquet(df_save)
                atomic_write_parquet(df_save, PARQUET_PATH)

                # 2. Fast single-row upsert into SQLite donations table (deduplicating by Donation ID)
                try:
                    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
                    cur = conn.cursor()
                    cur.execute('DELETE FROM donations WHERE "Donation ID" = ?', (don_id,))
                    conn.commit()
                    df_new_row.to_sql("donations", con=conn, if_exists="append", index=False)
                    conn.close()
                except Exception as sqle:
                    print(f"[SQLite Webhook Ingest Notice]: {sqle}")

                # Invalidate in-memory cache so new donation shows instantly
                load_data(force_reload=True)

                # Broadcast WebSocket live event
                broadcast_event_sync("DONORS_UPDATED", {
                    "source": "givebrite_webhook",
                    "company_id": target_cid,
                    "donation_id": don_id,
                    "amount": amount,
                    "campaign": camp_name
                })

                _log_webhook_event(target_cid, event_type, don_id, payload, status="processed_successfully")

                return {
                    "status": "success",
                    "action": "donation_ingested",
                    "donation_id": don_id,
                    "amount": amount,
                    "company_id": target_cid,
                    "campaign": camp_name,
                    "code": class_info["Code"]
                }

            except Exception as e:
                _log_webhook_event(target_cid, event_type, event_id, payload, status="error", error=str(e))
                print(f"[GiveBrite Webhook Processing Error]: {e}")
                return {"status": "error", "message": str(e)}

    # Unrecognized payload fallback
    _log_webhook_event(target_cid, event_type, event_id, payload, status="unrecognized_event")
    return {"status": "success", "action": "ignored", "event": event_type, "message": "Event acknowledged."}


# ── API Route Endpoints ────────────────────────────────────────────────────────

def _verify_webhook_secret(request: Request):
    expected_secret = os.getenv("GIVEBRITE_WEBHOOK_SECRET", "").strip()
    if not expected_secret:
        return
    provided = request.headers.get("x-webhook-secret") or request.query_params.get("secret")
    if not provided or provided != expected_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature/secret.")


@router.post("/givebrite/rethink")
async def givebrite_webhook_rethink(request: Request, background_tasks: BackgroundTasks):
    """Dedicated GiveBrite webhook receiver endpoint for Rethink Charity."""
    _verify_webhook_secret(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    # Process in background task for sub-10ms response to GiveBrite
    background_tasks.add_task(process_givebrite_webhook_payload, "rethink", payload)
    return {"status": "success", "company_id": "rethink", "message": "Webhook received and queued for real-time ingestion."}


@router.post("/givebrite/iqra")
async def givebrite_webhook_iqra(request: Request, background_tasks: BackgroundTasks):
    """Dedicated GiveBrite webhook receiver endpoint for Iqra."""
    _verify_webhook_secret(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    background_tasks.add_task(process_givebrite_webhook_payload, "iqra", payload)
    return {"status": "success", "company_id": "iqra", "message": "Webhook received and queued for real-time ingestion."}


@router.post("/givebrite/{company_id}")
async def givebrite_webhook_dynamic(company_id: str, request: Request, background_tasks: BackgroundTasks):
    """Dynamic GiveBrite webhook receiver endpoint for any registered company."""
    _verify_webhook_secret(request)
    cid = company_id.strip().lower()
    if not cid or cid == "all":
        raise HTTPException(status_code=400, detail="Valid charity company_id is required.")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    background_tasks.add_task(process_givebrite_webhook_payload, cid, payload)
    return {"status": "success", "company_id": cid, "message": "Webhook received and queued for real-time ingestion."}


@router.get("/givebrite/logs")
def get_givebrite_webhook_logs(company_id: Optional[str] = Query("all"), limit: int = Query(50, ge=1, le=200), current_user = Depends(require_super_admin)):
    """Inspects recent GiveBrite webhook audit logs for troubleshooting and verification."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    cid = str(company_id or "all").strip().lower()
    if cid != "all":
        cur.execute("""
            SELECT id, company_id, event_type, event_id, status, error_message, created_at
            FROM givebrite_webhook_events
            WHERE LOWER(company_id) = ?
            ORDER BY id DESC LIMIT ?
        """, (cid, limit))
    else:
        cur.execute("""
            SELECT id, company_id, event_type, event_id, status, error_message, created_at
            FROM givebrite_webhook_events
            ORDER BY id DESC LIMIT ?
        """, (limit,))
        
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"status": "success", "total_logs": len(rows), "logs": rows}
