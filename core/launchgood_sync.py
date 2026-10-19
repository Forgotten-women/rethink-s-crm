"""
LaunchGood Ingestion Engine
---------------------------
Automated ingestion of LaunchGood donations into CRM database (launchgood_donations.db):
  1. Requests and downloads asynchronous donor exports from LaunchGood v4 API.
  2. Parses itemized donor contributions (donor name, email, phone, campaign, giving level, gross/fees/net).
  3. Applies 8-dimension accounting classification using platform_campaign_mappings and master_project_codes.
  4. Performs atomic upserts into SQLite 'donations' table with strict company_id isolation ('rethink' vs 'iqra').
  5. Refreshes data cache and parquet layer for fast dashboard access.
"""
import csv
import io
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from config.settings import LOCAL_DB_PATH
from core.data_processor import canonical_campaign_key, fix_mojibake, invalidate_data_cache
from core.database import get_db_connection
from core.event_log import log_event
from core.launchgood_client import LaunchGoodClient

logger = logging.getLogger("launchgood_sync")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [launchgood_sync] %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


def _load_classification_rules(company_id: str, conn: sqlite3.Connection) -> Dict[str, Dict[str, str]]:
    """Loads active LaunchGood classification rules for the specific charity."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COALESCE(p.campaign_name, p.community_name), p.giving_level, p.code,
               m.department, m.office, m.portfolio, m.country, m.programme_fund, m.fund_code, m.zakat_eligibility, p.special_case
        FROM platform_campaign_mappings p
        LEFT JOIN master_project_codes m ON UPPER(TRIM(p.code)) = UPPER(TRIM(m.code))
        WHERE p.platform = 'launchgood' AND LOWER(COALESCE(p.company_id, 'rethink')) = ?
    """, (company_id.lower(),))
    
    rules = {}
    for row in cursor.fetchall():
        c_name = str(row[0] or "").strip().lower()
        g_level = str(row[1] or "").strip().lower()
        meta = {
            "code": row[2] or "Unassigned",
            "department": row[3] or "",
            "office": row[4] or "",
            "portfolio": row[5] or "",
            "country": row[6] or "",
            "programme_fund": row[7] or "",
            "fund_code": row[8] or "",
            "zakat_eligibility": row[9] or "Zakat",
            "special_case": row[10] or "",
        }
        if c_name:
            rules[c_name] = meta
            rules[canonical_campaign_key(c_name)] = meta
            if g_level:
                rules[f"{c_name}::{g_level}"] = meta
                rules[f"{canonical_campaign_key(c_name)}::{g_level}"] = meta
    return rules


def match_campaign_classification(
    campaign_name: str,
    giving_level: str,
    rules: Dict[str, Dict[str, str]]
) -> Dict[str, str]:
    """Matches a LaunchGood campaign and giving level against the loaded classification rules."""
    cn = str(campaign_name or "").strip().lower()
    gl = str(giving_level or "").strip().lower()
    cn_canon = canonical_campaign_key(cn)

    # 1. Exact Campaign + Giving Level match
    if gl and f"{cn}::{gl}" in rules:
        return rules[f"{cn}::{gl}"]
    if gl and f"{cn_canon}::{gl}" in rules:
        return rules[f"{cn_canon}::{gl}"]

    # 2. Campaign Exact match
    if cn in rules:
        return rules[cn]
    if cn_canon in rules:
        return rules[cn_canon]

    # 3. Base Campaign title match (before | or -)
    for sep in ["|", " - ", " – ", " — "]:
        if sep in cn:
            base_part = cn.split(sep)[0].strip()
            if base_part in rules:
                return rules[base_part]
            base_canon = canonical_campaign_key(base_part)
            if base_canon in rules:
                return rules[base_canon]

    # Default unassigned
    return {
        "code": "Unassigned",
        "department": "Unassigned",
        "office": "Unassigned",
        "portfolio": "Unassigned",
        "country": "Unassigned",
        "programme_fund": "Unassigned",
        "fund_code": "Unassigned",
        "zakat_eligibility": "Unassigned",
        "special_case": "",
    }


def parse_launchgood_csv(
    csv_text: str,
    company_id: str,
    rules: Dict[str, Dict[str, str]]
) -> List[Dict[str, Any]]:
    """Parses raw LaunchGood donor export CSV into standardized CRM donation dictionaries."""
    reader = csv.DictReader(io.StringIO(csv_text))
    parsed_records = []

    for row in reader:
        # Resolve Donation ID
        d_id = (
            row.get("Donation ID")
            or row.get("Order ID")
            or row.get("Transaction ID")
            or row.get("id")
            or ""
        ).strip()
        if not d_id:
            continue

        c_name = fix_mojibake(row.get("Campaign Name") or row.get("Campaign Title") or row.get("Project Name") or "Unassigned Campaign").strip()
        gl_title = fix_mojibake(row.get("Giving Level") or row.get("Giving Level Title") or row.get("Reward") or "").strip()
        
        # Financial amounts
        gross_val = float(row.get("Amount") or row.get("Gross Amount") or row.get("Gross") or 0.0)
        fee_val = float(row.get("Fee") or row.get("Processing Fee") or row.get("Fees") or 0.0)
        net_val = float(row.get("Net Amount") or row.get("Net") or (gross_val - fee_val))
        currency = (row.get("Currency") or row.get("Settlement Currency") or "GBP").strip().upper()

        # Date parsing
        date_str = (row.get("Date") or row.get("Created Date") or row.get("Created At") or "").strip()
        created_date = ""
        created_time = ""
        if date_str:
            try:
                dt = pd.to_datetime(date_str, errors="coerce")
                if pd.notna(dt):
                    created_date = dt.strftime("%Y-%m-%d")
                    created_time = dt.strftime("%H:%M:%S")
            except Exception:
                created_date = date_str[:10]

        # Donor details
        first_name = fix_mojibake(row.get("First Name") or row.get("Donor First Name") or "").strip()
        last_name = fix_mojibake(row.get("Last Name") or row.get("Donor Last Name") or "").strip()
        full_name = f"{first_name} {last_name}".strip() or fix_mojibake(row.get("Donor Name") or row.get("Name") or "Anonymous Donor").strip()
        email = (row.get("Email") or row.get("Donor Email") or "").strip().lower()
        phone = (row.get("Phone") or row.get("Donor Phone") or "").strip()

        # Classification match
        meta = match_campaign_classification(c_name, gl_title, rules)

        record = {
            "Donation ID": d_id,
            "company_id": company_id.lower(),
            "Donor Name": full_name,
            "First Name": first_name,
            "Last Name": last_name,
            "Email": email,
            "Phone": phone,
            "Campaign Name": c_name,
            "Giving Level Title": gl_title,
            "Total Online Donation Gross Amount in Settled Currency": gross_val,
            "Total Processing Fees Paid by CC In Settled Currency": fee_val,
            "Total Online Donations Net Amount in Settled Currency": net_val,
            "Settlement Currency": currency,
            "Created Date (UTC)": created_date,
            "Created Time (UTC)": created_time,
            "Code": meta.get("code", "Unassigned"),
            "Department": meta.get("department", ""),
            "Office": meta.get("office", ""),
            "Portfolio": meta.get("portfolio", ""),
            "Country": meta.get("country", ""),
            "Programme Fund": meta.get("programme_fund", ""),
            "Fund Code": meta.get("fund_code", ""),
            "Zakat Eligibility": meta.get("zakat_eligibility", "Zakat"),
            "Special Case": meta.get("special_case", ""),
            "Platform": "LaunchGood",
            "Source": "LaunchGood Sync",
        }
        parsed_records.append(record)

    return parsed_records


def run_launchgood_sync(company_id: str = "rethink", days_back: int = 30) -> Dict[str, Any]:
    """
    Executes an end-to-end sync cycle for LaunchGood for the specified charity:
    1. Downloads recent donor exports from LaunchGood API.
    2. Applies accounting classifications.
    3. Upserts records into SQLite 'donations' table.
    4. Invalidates in-memory and parquet cache.
    """
    company_id = str(company_id or "rethink").strip().lower()
    logger.info(f"Starting LaunchGood sync for charity '{company_id}'...")

    client = LaunchGoodClient(company_id=company_id)
    if not client.is_configured():
        msg = f"LaunchGood is not connected for '{company_id}'. Please capture or configure session tokens."
        logger.warning(msg)
        return {"status": "skipped", "reason": msg, "company_id": company_id}

    conn = get_db_connection(timeout=15.0)
    try:
        rules = _load_classification_rules(company_id, conn)
        logger.info(f"Loaded {len(rules)} active classification rules for {company_id}.")

        # Generate report on LaunchGood
        rep = client.create_donors_report()
        identifier = (rep.get("result") or {}).get("identifier")
        if not identifier:
            raise RuntimeError(f"LaunchGood did not return a report identifier: {rep}")

        client.generate_report(identifier)
        # Small wait for report generation
        time.sleep(3)
        csv_text = client.download_report_csv(identifier)

        parsed_records = parse_launchgood_csv(csv_text, company_id, rules)
        logger.info(f"Parsed {len(parsed_records)} donation records from LaunchGood CSV.")

        if parsed_records:
            cursor = conn.cursor()
            inserted_count = 0
            for r in parsed_records:
                cursor.execute("""
                    INSERT INTO donations (
                        "Donation ID", company_id, "Donor Name", "First Name", "Last Name", "Email", "Phone",
                        "Campaign Name", "Giving Level Title", "Total Online Donation Gross Amount in Settled Currency",
                        "Total Processing Fees Paid by CC In Settled Currency", "Total Online Donations Net Amount in Settled Currency",
                        "Settlement Currency", "Created Date (UTC)", "Created Time (UTC)", "Code", "Department", "Office",
                        "Portfolio", "Country", "Programme Fund", "Fund Code", "Zakat Eligibility", "Special Case", "Platform", "Source"
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT("Donation ID") DO UPDATE SET
                        "Campaign Name" = excluded."Campaign Name",
                        "Giving Level Title" = excluded."Giving Level Title",
                        "Total Online Donation Gross Amount in Settled Currency" = excluded."Total Online Donation Gross Amount in Settled Currency",
                        "Total Processing Fees Paid by CC In Settled Currency" = excluded."Total Processing Fees Paid by CC In Settled Currency",
                        "Total Online Donations Net Amount in Settled Currency" = excluded."Total Online Donations Net Amount in Settled Currency",
                        "Code" = excluded."Code",
                        "Department" = excluded."Department",
                        "Office" = excluded."Office",
                        "Portfolio" = excluded."Portfolio",
                        "Country" = excluded."Country",
                        "Programme Fund" = excluded."Programme Fund",
                        "Fund Code" = excluded."Fund Code",
                        "Zakat Eligibility" = excluded."Zakat Eligibility",
                        "Special Case" = excluded."Special Case"
                """, (
                    r["Donation ID"], r["company_id"], r["Donor Name"], r["First Name"], r["Last Name"], r["Email"], r["Phone"],
                    r["Campaign Name"], r["Giving Level Title"], r["Total Online Donation Gross Amount in Settled Currency"],
                    r["Total Processing Fees Paid by CC In Settled Currency"], r["Total Online Donations Net Amount in Settled Currency"],
                    r["Settlement Currency"], r["Created Date (UTC)"], r["Created Time (UTC)"], r["Code"], r["Department"], r["Office"],
                    r["Portfolio"], r["Country"], r["Programme Fund"], r["Fund Code"], r["Zakat Eligibility"], r["Special Case"],
                    r["Platform"], r["Source"]
                ))
                inserted_count += 1
            conn.commit()
            logger.info(f"Upserted {inserted_count} LaunchGood records into SQLite for {company_id}.")

            invalidate_data_cache(company_id)
            log_event(
                "launchgood.sync_completed",
                category="sync",
                level="info",
                company_id=company_id,
                message=f"Synced {inserted_count} LaunchGood donations for {company_id}."
            )

        return {
            "status": "success",
            "company_id": company_id,
            "total_synced": len(parsed_records),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    finally:
        conn.close()


def ingest_launchgood_csv_text(csv_text: str, company_id: str = "rethink") -> Dict[str, Any]:
    """Parses and upserts a raw LaunchGood donor export CSV string directly into CRM DB & parquet cache."""
    company_id = str(company_id or "rethink").strip().lower()
    conn = get_db_connection(timeout=15.0)
    try:
        rules = _load_classification_rules(company_id, conn)
        parsed_records = parse_launchgood_csv(csv_text, company_id, rules)
        if not parsed_records:
            return {"status": "success", "company_id": company_id, "inserted": 0, "message": "No valid rows found in CSV"}

        cursor = conn.cursor()
        inserted_count = 0
        for r in parsed_records:
            cursor.execute("""
                INSERT INTO donations (
                    "Donation ID", company_id, "Donor Name", "First Name", "Last Name", "Email", "Phone",
                    "Campaign Name", "Giving Level Title", "Total Online Donation Gross Amount in Settled Currency",
                    "Total Processing Fees Paid by CC In Settled Currency", "Total Online Donations Net Amount in Settled Currency",
                    "Settlement Currency", "Created Date (UTC)", "Created Time (UTC)", "Code", "Department", "Office",
                    "Portfolio", "Country", "Programme Fund", "Fund Code", "Zakat Eligibility", "Special Case", "Platform", "Source"
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT("Donation ID") DO UPDATE SET
                    "Campaign Name" = excluded."Campaign Name",
                    "Giving Level Title" = excluded."Giving Level Title",
                    "Total Online Donation Gross Amount in Settled Currency" = excluded."Total Online Donation Gross Amount in Settled Currency",
                    "Total Processing Fees Paid by CC In Settled Currency" = excluded."Total Processing Fees Paid by CC In Settled Currency",
                    "Total Online Donations Net Amount in Settled Currency" = excluded."Total Online Donations Net Amount in Settled Currency",
                    "Code" = excluded."Code",
                    "Department" = excluded."Department",
                    "Office" = excluded."Office",
                    "Portfolio" = excluded."Portfolio",
                    "Country" = excluded."Country",
                    "Programme Fund" = excluded."Programme Fund",
                    "Fund Code" = excluded."Fund Code",
                    "Zakat Eligibility" = excluded."Zakat Eligibility",
                    "Special Case" = excluded."Special Case"
            """, (
                r["Donation ID"], r["company_id"], r["Donor Name"], r["First Name"], r["Last Name"], r["Email"], r["Phone"],
                r["Campaign Name"], r["Giving Level Title"], r["Total Online Donation Gross Amount in Settled Currency"],
                r["Total Processing Fees Paid by CC In Settled Currency"], r["Total Online Donations Net Amount in Settled Currency"],
                r["Settlement Currency"], r["Created Date (UTC)"], r["Created Time (UTC)"], r["Code"], r["Department"], r["Office"],
                r["Portfolio"], r["Country"], r["Programme Fund"], r["Fund Code"], r["Zakat Eligibility"], r["Special Case"],
                r["Platform"], r["Source"]
            ))
            inserted_count += 1
        conn.commit()
        invalidate_data_cache(company_id)
        log_event(
            "launchgood.sync_completed",
            category="sync",
            level="info",
            company_id=company_id,
            message=f"Directly ingested {inserted_count} LaunchGood donations for {company_id} via browser/CSV helper."
        )
        return {
            "status": "success",
            "company_id": company_id,
            "inserted": inserted_count,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    finally:
        conn.close()

