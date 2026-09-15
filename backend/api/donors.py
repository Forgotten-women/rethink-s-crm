import io
import math
import os
import sqlite3
import tempfile
from datetime import datetime
from typing import List, Optional
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from config.settings import LOCAL_DB_PATH, PARQUET_PATH, PAYOUTS_PARQUET_PATH
from core.data_processor import load_data, load_payouts_data, sync_donor_classifications_to_matrix
from core.fast_export import dataframe_to_fast_xlsx, dataframe_to_fast_csv

def _cleanup_temp_file(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

router = APIRouter(prefix="/api/donors", tags=["Donors & Explorer"])


class BulkEditDonorsRequest(BaseModel):
    user_role: str
    target_columns: List[str]
    new_values: List[str]
    filter_search: Optional[str] = ""
    filter_search_fields: Optional[str] = None
    filter_payment_type: Optional[str] = None
    filter_tier: Optional[str] = None
    filter_source: Optional[str] = None
    filter_programme_fund: Optional[str] = None
    filter_heading: Optional[str] = None
    filter_subheading: Optional[str] = None
    filter_country: Optional[str] = None
    filter_code: Optional[str] = None
    filter_zakat: Optional[str] = None
    filter_donor_country: Optional[str] = None
    filter_campaign_search: Optional[str] = None
    filter_campaign: Optional[str] = None
    filter_gift_aid: Optional[str] = None
    filter_start_date: Optional[str] = None
    filter_end_date: Optional[str] = None
    can_edit_donors: Optional[bool] = False


class UpdateSingleDonorRequest(BaseModel):
    user_role: str
    row_id: Optional[int] = None
    donation_id: Optional[str] = None
    donor_identifier: Optional[str] = None
    column_name: Optional[str] = None
    new_value: Optional[str] = None
    updated_fields: Optional[dict] = None
    can_edit_donors: Optional[bool] = False


@router.post("/update-record")
def update_single_donor_record(payload: UpdateSingleDonorRequest):
    if payload.user_role != "super_admin" and not payload.can_edit_donors:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Editing records is restricted to authorized accounts."
        )

    df_donations = load_data()
    df_payouts = load_payouts_data()

    is_payout_target = False
    if payload.updated_fields and str(payload.updated_fields.get("Platform", "")).lower() == "launchgood payout":
        is_payout_target = True
    elif payload.updated_fields and str(payload.updated_fields.get("Source", "")).lower() == "launchgood payout":
        is_payout_target = True
    elif payload.donation_id and str(payload.donation_id).upper().startswith("PAYOUT-"):
        is_payout_target = True
    elif payload.donation_id and not df_payouts.empty and "Donation ID" in df_payouts.columns:
        d_id_str = str(payload.donation_id).strip().lower()
        if (df_payouts["Donation ID"].astype(str).str.strip().str.lower() == d_id_str).any():
            if df_donations.empty or not (df_donations["Donation ID"].astype(str).str.strip().str.lower() == d_id_str).any():
                is_payout_target = True

    df_raw = df_payouts if is_payout_target else df_donations
    if df_raw.empty:
        raise HTTPException(status_code=400, detail="Target dataset is empty.")

    target_idx = None

    # 1. Exact Row Index targeting (100% precision guarantee)
    if payload.row_id is not None and payload.row_id in df_raw.index:
        target_idx = payload.row_id
    elif payload.donation_id and "Donation ID" in df_raw.columns:
        d_id_str = str(payload.donation_id).strip().lower()
        matches = df_raw.index[df_raw["Donation ID"].astype(str).str.strip().str.lower() == d_id_str].tolist()
        if len(matches) > 0:
            target_idx = matches[0]

    if target_idx is None:
        raise HTTPException(status_code=404, detail="Specific record could not be uniquely identified for editing.")

    # Apply changes strictly to ONE single row
    if payload.updated_fields and isinstance(payload.updated_fields, dict):
        for col, val in payload.updated_fields.items():
            if col in df_raw.columns and not col.startswith("_"):
                df_raw.loc[target_idx, col] = val
    elif payload.column_name and payload.new_value is not None:
        if payload.column_name in df_raw.columns and not payload.column_name.startswith("_"):
            df_raw.loc[target_idx, payload.column_name] = payload.new_value

    # Auto-fill classification metadata from Code dictionary if Code was set
    new_code_val = None
    if payload.updated_fields and "Code" in payload.updated_fields:
        new_code_val = str(payload.updated_fields["Code"]).strip().lower()
    elif payload.column_name == "Code" and payload.new_value is not None:
        new_code_val = str(payload.new_value).strip().lower()

    if new_code_val and new_code_val not in ["unassigned", "nan", "none", "n/a", ""]:
        from core.data_processor import get_code_to_classification_map
        c_map = get_code_to_classification_map()
        if new_code_val in c_map:
            c_info = c_map[new_code_val]
            for col in ["Department", "Office", "Portfolio", "Heading", "Sub-Heading", "Country", "Zakat Eligibility", "Programme Fund", "Fund Code"]:
                if col in df_raw.columns:
                    val = c_info.get(col, "Unassigned" if col not in ["Portfolio", "Programme Fund", "Fund Code"] else "")
                    if val != "Unassigned" and val != "":
                        if payload.updated_fields:
                            if payload.updated_fields.get(col) in [None, "", "Unassigned"]:
                                df_raw.loc[target_idx, col] = val
                        else:
                            df_raw.loc[target_idx, col] = val

    from core.data_processor import sanitize_df_dtypes_for_parquet
    df_raw = sanitize_df_dtypes_for_parquet(df_raw)

    if is_payout_target:
        from core.data_processor import invalidate_payouts_cache
        df_raw.to_parquet(PAYOUTS_PARQUET_PATH, index=False)
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
        df_raw.to_sql("payout_settlements", con=conn, if_exists="replace", index=False)
        conn.close()
        invalidate_payouts_cache()
    else:
        from core.data_processor import invalidate_data_cache, sync_donors_to_classification_matrix
        df_raw.to_parquet(PARQUET_PATH, index=False)
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
        df_raw.to_sql("donations", con=conn, if_exists="replace", index=False)
        conn.close()
        invalidate_data_cache()
        sync_donors_to_classification_matrix(df_raw)

    try:
        from backend.api.expenses import clear_expenses_cache
        clear_expenses_cache()
        from backend.api.events import broadcast_event_sync
        broadcast_event_sync("DONORS_UPDATED", {"source": "single_edit", "column": payload.column_name})
        broadcast_event_sync("FUNDRAISER_UPDATED", {"source": "single_edit", "column": payload.column_name})
    except Exception:
        pass

    return {
        "status": "success",
        "message": f"Successfully updated record #{target_idx}."
    }


@router.post("/bulk-edit")
def bulk_edit_donors(payload: BulkEditDonorsRequest):
    if payload.user_role != "super_admin" and not payload.can_edit_donors:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Editing records is restricted to authorized accounts."
        )

    is_payout_bulk = bool(payload.filter_source and str(payload.filter_source).strip().lower() in ["launchgood payout", "payout", "payouts"])
    df_raw = load_payouts_data() if is_payout_bulk else load_data()
    if df_raw.empty:
        raise HTTPException(status_code=400, detail="Target dataset is empty.")

    # 1. Apply global filters to scope target dataframe
    filtered_df = _apply_filters(
        df_raw,
        payload.filter_payment_type,
        payload.filter_tier,
        payload.filter_source,
        payload.filter_heading,
        payload.filter_subheading,
        payload.filter_country,
        payload.filter_code,
        payload.filter_zakat,
        payload.filter_donor_country,
        payload.filter_campaign_search,
        payload.filter_gift_aid,
        payload.filter_start_date,
        payload.filter_end_date,
        programme_fund=payload.filter_programme_fund,
        campaign=payload.filter_campaign
    )

    # 2. Apply search filter with multi-Donation ID support
    if payload.filter_search and str(payload.filter_search).strip():
        filtered_df = _apply_search_to_df(filtered_df, payload.filter_search, search_fields=payload.filter_search_fields)

    matching_indices = filtered_df.index
    if len(matching_indices) == 0:
        return {"status": "success", "message": "No matching records found to edit."}

    for col, val in zip(payload.target_columns, payload.new_values):
        if col and col in df_raw.columns:
            df_raw.loc[matching_indices, col] = val

    # If 'Code' was among target columns, auto-fill Department, Office, Portfolio, Heading, Sub-Heading, Country, Zakat Eligibility, Programme Fund, Fund Code
    if "Code" in payload.target_columns:
        c_idx = payload.target_columns.index("Code")
        new_c_val = str(payload.new_values[c_idx] or "").strip().lower()
        if new_c_val and new_c_val not in ["unassigned", "nan", "none", "n/a", ""]:
            from core.data_processor import get_code_to_classification_map
            c_map = get_code_to_classification_map()
            if new_c_val in c_map:
                c_info = c_map[new_c_val]
                for tc in ["Department", "Office", "Portfolio", "Heading", "Sub-Heading", "Country", "Zakat Eligibility", "Programme Fund", "Fund Code"]:
                    if tc in df_raw.columns and tc not in payload.target_columns:
                        t_val = c_info.get(tc, "Unassigned" if tc not in ["Portfolio", "Programme Fund", "Fund Code"] else "")
                        if t_val != "Unassigned" and t_val != "":
                            df_raw.loc[matching_indices, tc] = t_val

    from core.data_processor import sanitize_df_dtypes_for_parquet
    df_raw = sanitize_df_dtypes_for_parquet(df_raw)

    if is_payout_bulk:
        from core.data_processor import invalidate_payouts_cache
        df_raw.to_parquet(PAYOUTS_PARQUET_PATH, index=False)
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
        df_raw.to_sql("payout_settlements", con=conn, if_exists="replace", index=False)
        conn.close()
        invalidate_payouts_cache()
    else:
        from core.data_processor import invalidate_data_cache, sync_donors_to_classification_matrix
        df_raw.to_parquet(PARQUET_PATH, index=False)
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
        df_raw.to_sql("donations", con=conn, if_exists="replace", index=False)
        conn.close()
        invalidate_data_cache()
        sync_donors_to_classification_matrix(df_raw)

        from core.database import sync_to_cloud_async
        sync_to_cloud_async(df_raw, mode="replace")

    try:
        from backend.api.expenses import clear_expenses_cache
        clear_expenses_cache()
        from backend.api.events import broadcast_event_sync
        broadcast_event_sync("DONORS_UPDATED", {"source": "bulk_edit", "columns": payload.target_columns})
        broadcast_event_sync("FUNDRAISER_UPDATED", {"source": "bulk_edit", "columns": payload.target_columns})
    except Exception:
        pass

    return {
        "status": "success",
        "message": f"Successfully updated {len(matching_indices):,} record(s) and synchronized classification matrix."
    }


def _parse_search_query(search_str: str):
    """
    Parses user search query into:
    - id_tokens: list of numeric or clean ID strings if comma/space/newline separated
    - raw_text: clean general search string
    """
    if not search_str or not str(search_str).strip():
        return [], ""
    s = str(search_str).strip()
    import re
    raw_tokens = [t.strip() for t in re.split(r'[,;\n\r\|]+|\s+', s) if t.strip()]
    id_tokens = []
    for t in raw_tokens:
        clean_t = t.lstrip('#')
        if clean_t:
            id_tokens.append(clean_t)
    return id_tokens, s


def _apply_search_to_df(df: pd.DataFrame, search_str: str, search_fields: str = None) -> pd.DataFrame:
    """Applies multi-Donation ID and targeted or universal text search across scoped fields."""
    if not search_str or not str(search_str).strip() or df.empty:
        return df

    id_tokens, raw_text = _parse_search_query(search_str)
    mask = pd.Series(False, index=df.index)

    active_targets = set([f.strip().lower() for f in search_fields.split(",") if f.strip()]) if search_fields else set()
    search_all = not active_targets or "all" in active_targets

    # 1. Multi Donation ID match
    if (search_all or "donation_id" in active_targets or "id" in active_targets) and id_tokens:
        for id_col in ["Donation ID", "Donor ID", "Transaction ID", "ID", "Transfer ID"]:
            if id_col in df.columns:
                id_series = df[id_col].astype(str).str.strip().str.lstrip('#')
                mask |= id_series.isin(id_tokens)

    # 2. General text match across selected targets
    term = raw_text.strip().lower()
    target_cols = []
    if search_all or "name" in active_targets or "donor" in active_targets:
        target_cols.extend(["First Name", "Last Name", "Display Name"])
    if search_all or "campaign" in active_targets or "campaigns" in active_targets:
        target_cols.extend(["Campaign Name"])
    if search_all or "community" in active_targets:
        target_cols.extend(["Community Name"])
    if search_all or "email" in active_targets:
        target_cols.extend(["Email"])
    if search_all or "fundraiser" in active_targets:
        target_cols.extend(["fundraiser_name", "Fundraiser Name"])
    if search_all or "code" in active_targets:
        target_cols.extend(["Code"])
    if search_all:
        target_cols.extend(["Donation ID", "Donor ID", "Transfer ID"])

    search_cols = [c for c in dict.fromkeys(target_cols) if c in df.columns]
    for sc in search_cols:
        mask |= df[sc].astype(str).str.lower().str.contains(term, na=False, regex=False)

    return df.loc[mask]


def _apply_filters(df, payment_type=None, tier=None, source=None, heading=None, subheading=None, country=None, code=None, zakat=None, donor_country=None, campaign_search=None, gift_aid=None, start_date=None, end_date=None, programme_fund=None, campaign=None):
    if df is None or df.empty:
        return df

    mask = pd.Series(True, index=df.index)

    if isinstance(programme_fund, str) and programme_fund.strip() and programme_fund != "All Programme Funds" and "Programme Fund" in df.columns:
        mask &= (df["Programme Fund"].astype(str).str.strip().str.lower() == programme_fund.strip().lower())

    if isinstance(campaign, str) and campaign.strip() and campaign != "All Campaigns" and "Campaign Name" in df.columns:
        mask &= (df["Campaign Name"].astype(str).str.strip().str.lower() == campaign.strip().lower())

    if isinstance(payment_type, str) and payment_type.strip() and payment_type != "All Payment Types" and "Payment Frequency" in df.columns:
        norm_type = payment_type.strip()
        p_lower = norm_type.lower()
        if p_lower in ["one-time", "one-time payment"]:
            norm_type = "One-Time Payment"
        elif p_lower in ["monthly", "recurring", "recurring payment"]:
            norm_type = "Recurring Payment"
        mask &= (df["Payment Frequency"].astype(str) == norm_type)

    if isinstance(tier, str) and tier.strip() and tier != "All Classifications" and "Lifetime Donor Classification" in df.columns:
        mask &= (df["Lifetime Donor Classification"].astype(str) == tier.strip())

    if isinstance(source, str) and source.strip() and source != "All Sources (Combined)":
        sources_list = [s.strip().lower() for s in source.split(",") if s.strip()]
        if sources_list:
            src_mask = pd.Series(False, index=df.index)
            if "Platform" in df.columns:
                src_mask |= df["Platform"].astype(str).str.lower().isin(sources_list)
            if "Source" in df.columns:
                src_mask |= df["Source"].astype(str).str.lower().isin(sources_list)
            mask &= src_mask

    if isinstance(heading, str) and heading.strip() and heading != "All Headings" and "Heading" in df.columns:
        mask &= (df["Heading"].astype(str).str.strip().str.lower() == heading.strip().lower())

    if isinstance(subheading, str) and subheading.strip() and subheading != "All Sub-Headings" and "Sub-Heading" in df.columns:
        mask &= (df["Sub-Heading"].astype(str).str.strip().str.lower() == subheading.strip().lower())

    if isinstance(country, str) and country.strip() and country != "All Project Countries" and "Country" in df.columns:
        mask &= df["Country"].astype(str).str.contains(country.strip(), case=False, regex=False, na=False)

    if isinstance(code, str) and code.strip() and code != "All Codes" and "Code" in df.columns:
        mask &= (df["Code"].astype(str).str.strip().str.lower() == code.strip().lower())

    if isinstance(zakat, str) and zakat.strip() and zakat != "All Zakat Status" and "Zakat Eligibility" in df.columns:
        mask &= (df["Zakat Eligibility"].astype(str).str.strip().str.lower() == zakat.strip().lower())

    if isinstance(donor_country, str) and donor_country.strip() and donor_country != "All Donor Countries":
        for dc_col in ["Donor Country", "Billing Country", "Country Code"]:
            if dc_col in df.columns:
                mask &= df[dc_col].astype(str).str.contains(donor_country.strip(), case=False, regex=False, na=False)
                break

    if isinstance(campaign_search, str) and campaign_search.strip():
        term = campaign_search.strip().lower()
        c_mask = pd.Series(False, index=df.index)
        for cs_col in ["Campaign Name", "Community Name"]:
            if cs_col in df.columns:
                c_mask |= df[cs_col].astype(str).str.lower().str.contains(term, na=False)
        mask &= c_mask

    if isinstance(gift_aid, str) and gift_aid.strip() and gift_aid != "All Gift Aid Status":
        ga_col = "Gift Aid (yes or no)" if "Gift Aid (yes or no)" in df.columns else ("is_giftaid" if "is_giftaid" in df.columns else None)
        if ga_col:
            val_str = gift_aid.strip().lower()
            if val_str in ["yes", "1", "true"]:
                mask &= df[ga_col].astype(str).str.lower().isin(["yes", "1", "1.0", "true"])
            elif val_str in ["no", "0", "false"]:
                mask &= df[ga_col].astype(str).str.lower().isin(["no", "0", "0.0", "false"])

    # High-speed ISO Date Filtering (sub-millisecond string comparison)
    if "Created Date (UTC)" in df.columns:
        date_col = df["Created Date (UTC)"].astype(str)
        if isinstance(start_date, str) and start_date.strip():
            s_date = start_date.strip()[:10]
            mask &= (date_col >= s_date)
        if isinstance(end_date, str) and end_date.strip():
            e_date = end_date.strip()[:10]
            mask &= (date_col <= e_date)

    if mask.all():
        return df
    return df[mask]


@router.get("")
def get_donors_paginated(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    search: Optional[str] = "",
    search_fields: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = "asc",
    payment_type: Optional[str] = None,
    tier: Optional[str] = None,
    source: Optional[str] = None,
    programme_fund: Optional[str] = None,
    heading: Optional[str] = None,
    subheading: Optional[str] = None,
    country: Optional[str] = None,
    code: Optional[str] = None,
    zakat: Optional[str] = None,
    donor_country: Optional[str] = None,
    campaign_search: Optional[str] = None,
    campaign: Optional[str] = None,
    gift_aid: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Ultra-fast SQL Paginated Endpoint (< 100ms) with multi-Donation ID and scoped field text search.
    Strictly queries donations data without payout records.
    """
    target_table = "donations"

    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        cursor = conn.cursor()

        # Check if table exists
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{target_table}'")
        if cursor.fetchone():
            # Get available columns
            cursor.execute(f"PRAGMA table_info({target_table})")
            avail_cols = [col[1] for col in cursor.fetchall()]

            where_clauses = []
            params = []

            # Exclude any accidental payout settlement records from Data Explorer
            if "Platform" in avail_cols:
                where_clauses.append('LOWER("Platform") != ?')
                params.append("launchgood payout")

            if programme_fund and programme_fund != "All Programme Funds" and "Programme Fund" in avail_cols:
                where_clauses.append('LOWER("Programme Fund") = ?')
                params.append(programme_fund.strip().lower())

            if payment_type and payment_type != "All Payment Types" and "Payment Frequency" in avail_cols:
                norm_type = payment_type.strip()
                if norm_type.lower() in ["one-time", "one-time payment"]:
                    norm_type = "One-Time Payment"
                elif norm_type.lower() in ["monthly", "recurring", "recurring payment"]:
                    norm_type = "Recurring Payment"
                where_clauses.append('"Payment Frequency" = ?')
                params.append(norm_type)

            if tier and tier != "All Classifications" and "Lifetime Donor Classification" in avail_cols:
                where_clauses.append('"Lifetime Donor Classification" = ?')
                params.append(tier.strip())

            if source and source != "All Sources (Combined)":
                sources_list = [s.strip().lower() for s in source.split(",") if s.strip() and s.strip().lower() not in ["launchgood payout", "payout", "payouts"]]
                if sources_list:
                    p_holders = ','.join(['?'] * len(sources_list))
                    src_clauses = []
                    sub_params = []
                    if "Platform" in avail_cols:
                        src_clauses.append(f'LOWER("Platform") IN ({p_holders})')
                        sub_params.extend(sources_list)
                    if "Source" in avail_cols:
                        src_clauses.append(f'LOWER("Source") IN ({p_holders})')
                        sub_params.extend(sources_list)
                    if src_clauses:
                        where_clauses.append(f"({' OR '.join(src_clauses)})")
                        params.extend(sub_params)

            if heading and heading != "All Headings" and "Heading" in avail_cols:
                where_clauses.append('LOWER("Heading") = ?')
                params.append(heading.strip().lower())

            if subheading and subheading != "All Sub-Headings" and "Sub-Heading" in avail_cols:
                where_clauses.append('LOWER("Sub-Heading") = ?')
                params.append(subheading.strip().lower())

            if country and country != "All Project Countries" and "Country" in avail_cols:
                where_clauses.append('"Country" LIKE ?')
                params.append(f"%{country.strip()}%")

            if code and code != "All Codes" and "Code" in avail_cols:
                where_clauses.append('LOWER("Code") = ?')
                params.append(code.strip().lower())

            if zakat and zakat != "All Zakat Status" and "Zakat Eligibility" in avail_cols:
                where_clauses.append('LOWER("Zakat Eligibility") = ?')
                params.append(zakat.strip().lower())

            if donor_country and donor_country != "All Donor Countries":
                dc_col = next((c for c in ["Donor Country", "Billing Country", "Country Code"] if c in avail_cols), None)
                if dc_col:
                    where_clauses.append(f'"{dc_col}" LIKE ?')
                    params.append(f"%{donor_country.strip()}%")

            if campaign_search and str(campaign_search).strip():
                c_term = f"%{campaign_search.strip()}%"
                c_clauses = []
                c_params = []
                for cs_col in ["Campaign Name", "Community Name", "Project Name"]:
                    if cs_col in avail_cols:
                        c_clauses.append(f'"{cs_col}" LIKE ?')
                        c_params.append(c_term)
                    if c_clauses:
                        where_clauses.append(f"({' OR '.join(c_clauses)})")
                        params.extend(c_params)

            if campaign and str(campaign).strip() and campaign != "All Campaigns" and "Campaign Name" in avail_cols:
                where_clauses.append('LOWER("Campaign Name") = ?')
                params.append(campaign.strip().lower())

            if gift_aid and gift_aid != "All Gift Aid Status":
                where_clauses.append('("Gift Aid (yes or no)" LIKE ? OR "is_giftaid" = ?)')
                params.extend([f"%{gift_aid}%", 1 if gift_aid.lower() == "yes" else 0])

            if start_date and str(start_date).strip():
                where_clauses.append('date("Created Date (UTC)") >= date(?)')
                params.append(start_date)

            if end_date and str(end_date).strip():
                where_clauses.append('date("Created Date (UTC)") <= date(?)')
                params.append(end_date)

            if search and search.strip():
                id_tokens, raw_text = _parse_search_query(search)
                search_parts = []
                search_subparams = []

                search_all = True
                active_targets = []
                if search_fields and str(search_fields).strip():
                    active_targets = [t.strip().lower() for t in search_fields.split(",") if t.strip()]
                    if "all" not in active_targets:
                        search_all = False

                # Multi-Donation ID match
                if id_tokens and (search_all or "donation_id" in active_targets or "id" in active_targets):
                    id_placeholders = ','.join(['?'] * len(id_tokens))
                    id_cols = [c for c in ['"Donation ID"', '"Donor ID"', '"Transfer ID"'] if c.strip('"') in avail_cols]
                    if id_cols:
                        id_clause = " OR ".join([f"{col} IN ({id_placeholders})" for col in id_cols])
                        search_parts.append(f"({id_clause})")
                        search_subparams.extend(id_tokens * len(id_cols))

                # General text match across selected target columns
                text_term = f"%{raw_text.strip()}%"
                target_cols = []
                if search_all or "name" in active_targets or "donor" in active_targets:
                    target_cols.extend(['"First Name"', '"Last Name"', '"Display Name"'])
                if search_all or "campaign" in active_targets or "campaigns" in active_targets:
                    target_cols.extend(['"Campaign Name"'])
                if search_all or "community" in active_targets:
                    target_cols.extend(['"Community Name"'])
                if search_all or "email" in active_targets:
                    target_cols.extend(['"Email"'])
                if search_all or "fundraiser" in active_targets:
                    target_cols.extend(['"fundraiser_name"', '"Fundraiser Name"'])
                if search_all or "code" in active_targets:
                    target_cols.extend(['"Code"'])
                if search_all or "donation_id" in active_targets:
                    target_cols.extend(['"Donation ID"', '"Donor ID"', '"Transfer ID"'])

                search_cols = [col for col in dict.fromkeys(target_cols) if col.strip('"') in avail_cols]
                for col in search_cols:
                    search_parts.append(f"{col} LIKE ?")
                    search_subparams.append(text_term)

                if search_parts:
                    where_clauses.append(f"({' OR '.join(search_parts)})")
                    params.extend(search_subparams)

            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            order_sql = ""
            if sort_by and sort_by in avail_cols:
                order_dir = "DESC" if str(sort_order).lower() == "desc" else "ASC"
                order_sql = f' ORDER BY "{sort_by}" {order_dir}'

            # Count matching records
            count_sql = f"SELECT COUNT(*) FROM {target_table}{where_sql}"
            cursor.execute(count_sql, params)
            total_records = cursor.fetchone()[0]

            total_pages = max(1, math.ceil(total_records / page_size))
            page = min(page, total_pages)
            offset = (page - 1) * page_size

            # Query requested page with LIMIT & OFFSET
            query_sql = f"SELECT rowid as _row_id, * FROM {target_table}{where_sql}{order_sql} LIMIT ? OFFSET ?"
            query_params = params + [page_size, offset]
            page_df = pd.read_sql_query(query_sql, conn, params=query_params)
            conn.close()

            # Make rowid 0-indexed to match dataframe index
            if "_row_id" in page_df.columns:
                page_df["_row_id"] = page_df["_row_id"] - 1

            float_cols = page_df.select_dtypes(include=['float', 'float64']).columns
            for fc in float_cols:
                page_df[fc] = page_df[fc].round(2)

            page_df = page_df.fillna("")
            records = page_df.to_dict(orient="records")

            return {
                "total_records": total_records,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "available_columns": avail_cols,
                "records": records
            }
        conn.close()
    except Exception as e:
        print(f"SQL Pagination fallback notice: {e}")

    df_raw = load_payouts_data() if is_payout_query else load_data()
    if df_raw.empty:
        return {
            "total_records": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 0,
            "records": []
        }

    filtered_df = _apply_filters(df_raw, payment_type, tier, source, heading, subheading, country, code, zakat, donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund=programme_fund, campaign=campaign)
    display_df = _apply_search_to_df(filtered_df, search, search_fields=search_fields)

    total_records = len(display_df)
    total_pages = max(1, math.ceil(total_records / page_size))
    page = min(page, total_pages)

    start_idx = (page - 1) * page_size
    end_idx = min(start_idx + page_size, total_records)

    page_df = display_df.iloc[start_idx:end_idx].copy()
    page_df["_row_id"] = [int(idx) for idx in page_df.index]
    float_cols = page_df.select_dtypes(include=['float', 'float64']).columns
    for fc in float_cols:
        page_df[fc] = page_df[fc].round(2)

    page_df = page_df.fillna("")
    records = page_df.to_dict(orient="records")

    return {
        "total_records": total_records,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "available_columns": df_raw.columns.tolist(),
        "records": records
    }


@router.get("/export")
def export_donors(
    format: str = Query("csv", pattern="^(csv|xlsx)$"),
    search: Optional[str] = "",
    search_fields: Optional[str] = None,
    columns: Optional[str] = None,
    payment_type: Optional[str] = None,
    tier: Optional[str] = None,
    source: Optional[str] = None,
    programme_fund: Optional[str] = None,
    heading: Optional[str] = None,
    subheading: Optional[str] = None,
    country: Optional[str] = None,
    code: Optional[str] = None,
    zakat: Optional[str] = None,
    donor_country: Optional[str] = None,
    campaign_search: Optional[str] = None,
    campaign: Optional[str] = None,
    gift_aid: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """Exports filtered donor rows with date range, multi-Donation ID, and scoped search support."""
    df_raw = load_data()
    if df_raw.empty:
        raise HTTPException(status_code=400, detail="No donor data available to export.")

    if "Platform" in df_raw.columns:
        df_raw = df_raw[~df_raw["Platform"].astype(str).str.lower().isin(["launchgood payout", "payout", "payouts"])]

    filtered_df = _apply_filters(
        df_raw,
        payment_type=payment_type,
        tier=tier,
        source=source,
        heading=heading,
        subheading=subheading,
        country=country,
        code=code,
        zakat=zakat,
        donor_country=donor_country,
        campaign_search=campaign_search,
        gift_aid=gift_aid,
        start_date=start_date,
        end_date=end_date,
        programme_fund=programme_fund,
        campaign=campaign
    )
    display_df = _apply_search_to_df(filtered_df, search, search_fields=search_fields)

    # Column selection: filter to requested columns if provided, otherwise drop all-empty columns
    if columns:
        req_cols = [c.strip() for c in columns.split(",") if c.strip()]
        valid_cols = [c for c in req_cols if c in display_df.columns]
        export_df = display_df[valid_cols] if valid_cols else display_df
    else:
        export_df = display_df.dropna(axis=1, how="all") if not display_df.empty else display_df

    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    if format.lower() == "xlsx":
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
        temp_file_path = temp_file.name
        temp_file.close()

        dataframe_to_fast_xlsx(export_df, temp_file_path, sheet_name="Filtered Donors")

        return FileResponse(
            path=temp_file_path,
            filename=f"filtered_donors_{date_str}.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            background=BackgroundTask(_cleanup_temp_file, temp_file_path)
        )
    else:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        temp_file_path = temp_file.name
        temp_file.close()

        dataframe_to_fast_csv(export_df, temp_file_path)

        return FileResponse(
            path=temp_file_path,
            filename=f"filtered_donors_{date_str}.csv",
            media_type="text/csv",
            background=BackgroundTask(_cleanup_temp_file, temp_file_path)
        )


@router.get("/kanban")
def get_donors_kanban(
    payment_type: Optional[str] = None,
    tier: Optional[str] = None,
    source: Optional[str] = None,
    programme_fund: Optional[str] = None,
    heading: Optional[str] = None,
    subheading: Optional[str] = None,
    country: Optional[str] = None,
    code: Optional[str] = None,
    zakat: Optional[str] = None,
    donor_country: Optional[str] = None,
    campaign_search: Optional[str] = None,
    gift_aid: Optional[str] = None
):
    """Returns donor cards grouped by LTV Tier for the Kanban Pipeline Board with column total sums."""
    df_raw = load_data()
    df = _apply_filters(df_raw, payment_type, tier, source, heading, subheading, country, code, zakat, donor_country, campaign_search, gift_aid, programme_fund=programme_fund)

    if df.empty or "Lifetime Donor Classification" not in df.columns:
        return {}

    df = df.copy()
    
    # Construct Real Name for UI Display
    if "First Name" in df.columns and "Last Name" in df.columns:
        df["_real_name"] = (df["First Name"].astype(str).replace('nan', '') + " " + df["Last Name"].astype(str).replace('nan', '')).str.strip()
        df.loc[df["_real_name"] == "", "_real_name"] = df.get("Display Name", "")
    elif "Billing Name" in df.columns:
        df["_real_name"] = df["Billing Name"].astype(str).replace('nan', '').str.strip()
        df.loc[df["_real_name"] == "", "_real_name"] = df.get("Display Name", "")
    else:
        df["_real_name"] = df.get("Display Name", "")

    col_amount = "Total Online Donations Net Amount in Settled Currency"
    if col_amount not in df.columns:
        col_amount = "Donation Amount in Project Currency (May be approx.)"

    group_col = "Email" if "Email" in df.columns else "Display Name"
    tiers = ["Low End", "Medium Low", "Medium", "High", "Super High"]
    kanban_data = {}
    
    for t in tiers:
        t_df = df[df["Lifetime Donor Classification"] == t]
        total_sum_amount = float(t_df[col_amount].sum()) if (not t_df.empty and col_amount in t_df.columns) else 0.0

        if not t_df.empty:
            donor_summary = t_df.groupby(group_col).agg(
                name=("_real_name", "first"),
                email=("Email", "first") if "Email" in t_df.columns else (group_col, "first"),
                tier=("Lifetime Donor Classification", "first"),
                txn_tier=("Transaction Donor Classification", "first") if "Transaction Donor Classification" in t_df.columns else ("Lifetime Donor Classification", "first"),
                total_ltv=(col_amount, "sum") if col_amount in t_df.columns else (group_col, "count"),
                donation_count=(col_amount, "count") if col_amount in t_df.columns else (group_col, "count")
            ).reset_index()

            donor_summary = donor_summary.sort_values("total_ltv", ascending=False).head(30)

            records = []
            for _, r in donor_summary.iterrows():
                r_name = str(r["name"]).strip() if (pd.notna(r["name"]) and str(r["name"]).strip().lower() not in ["nan", "none", "null", ""]) else "Anonymous Donor"
                r_email = str(r["email"]) if (pd.notna(r["email"]) and str(r["email"]).strip().lower() not in ["nan", "none", "null"]) else ""
                r_tier = str(r["tier"]) if (pd.notna(r["tier"]) and str(r["tier"]).strip().lower() not in ["nan", "none", "null"]) else "Unassigned"
                r_txntier = str(r["txn_tier"]) if (pd.notna(r["txn_tier"]) and str(r["txn_tier"]).strip().lower() not in ["nan", "none", "null"]) else "Unassigned"
                
                records.append({
                    "name": r_name,
                    "email": r_email,
                    "total_ltv": round(float(r.get("total_ltv", 0.0)), 2),
                    "donation_count": int(r.get("donation_count", 1)),
                    "tier": r_tier,
                    "txn_tier": r_txntier
                })
            cards = records
        else:
            cards = []

        kanban_data[t] = {
            "tier_name": t,
            "total_donors": len(t_df),
            "total_sum_amount": round(total_sum_amount, 2),
            "cards": cards
        }

    return kanban_data


NON_NAME_PHRASES = {
    'towards the masjid', 'for orphans', 'in memory of', 'anonymous', 
    'anonymous kind soul', 'kind soul', 'sadaqah', 'zakat', 'general fund', 
    'masjid project', 'may allah accept', 'donation', 'for the sake of allah',
    'bismillah', 'jazaakallah', 'jazakallah', 'food pack', 'water well',
    'gaza appeal', 'iftar', 'orphan sponsorship', 'super village', 'homes'
}


def resolve_best_donor_name(donor_txns, first_row):
    """
    Intelligently determines the authentic person/organization name for a donor,
    prioritizing full legal names (First + Last, Billing Name) over intention messages 
    or campaign phrases that donors sometimes type into the crowdfunding 'Display Name' box.
    """
    # 1. Search for best human First Name + Last Name across all transactions
    name_candidates = []
    for _, row in donor_txns.iterrows():
        fn = str(row.get("First Name") or "").strip()
        ln = str(row.get("Last Name") or "").strip()
        if fn.lower() in ["nan", "none", "null", "anonymous", "kind soul", "n/a", ""]:
            fn = ""
        if ln.lower() in ["nan", "none", "null", "anonymous", "kind soul", "n/a", ""]:
            ln = ""
        
        full = f"{fn} {ln}".strip()
        if full and full.lower() not in NON_NAME_PHRASES and not any(p in full.lower() for p in ["towards the", "in memory of", "for orphans"]):
            words = full.split()
            # Score candidate based on completeness (favor full names like 'Adel Saeed' over 'A S')
            score = sum(len(w) for w in words)
            name_candidates.append((score, full, fn, ln))

    if name_candidates:
        name_candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_full, best_fn, best_ln = name_candidates[0]
        if best_score >= 3:
            return best_full, best_fn, best_ln

    # 2. Check Billing Name
    for _, row in donor_txns.iterrows():
        bn = str(row.get("Billing Name") or "").strip()
        if bn and bn.lower() not in ["nan", "none", "null", "anonymous", "kind soul", "n/a", ""] and bn.lower() not in NON_NAME_PHRASES:
            parts = bn.split()
            fn = parts[0] if parts else ""
            ln = " ".join(parts[1:]) if len(parts) > 1 else ""
            return bn, fn, ln

    # 3. Check Company Name / Customer Ref
    for _, row in donor_txns.iterrows():
        cn = str(row.get("Company name") or row.get("Customer Ref") or "").strip()
        if cn and cn.lower() not in ["nan", "none", "null", "anonymous", "kind soul", "n/a", ""]:
            return cn, "", ""

    # 4. Check Display Name (ignoring donation intentions/messages)
    for _, row in donor_txns.iterrows():
        disp = str(row.get("Display Name") or "").strip()
        disp_lower = disp.lower()
        if disp and disp_lower not in ["nan", "none", "null", "anonymous", "anonymous kind soul", "kind soul", "n/a", ""] and not any(p in disp_lower for p in NON_NAME_PHRASES):
            parts = disp.split()
            fn = parts[0] if parts else ""
            ln = " ".join(parts[1:]) if len(parts) > 1 else ""
            return disp, fn, ln

    # 5. Fallback: single letter initial or Anonymous
    raw_fn = str(first_row.get("First Name") or "").strip()
    raw_ln = str(first_row.get("Last Name") or "").strip()
    if raw_fn or raw_ln:
        return f"{raw_fn} {raw_ln}".strip(), raw_fn, raw_ln

    return "Anonymous Donor", "", ""


ANON_PLACEHOLDERS = {
    "anonymous", "anonymous kind soul", "anonymous donor", "kind soul", 
    "donation boost", "unnamed donor", "nan", "none", "null", "", "unassigned"
}


def _get_donor_matching_mask(df: pd.DataFrame, donor_id_or_email: str) -> pd.Series:
    """Safely matches donor transactions without accidentally grouping 40k+ anonymous records."""
    if not donor_id_or_email or df.empty:
        return pd.Series(False, index=df.index)
        
    identity = str(donor_id_or_email).strip().lower()
    
    # 1. Explicit Donation ID prefix: "ID:23547022" or "donation_id:23547022"
    if identity.startswith("id:") or identity.startswith("donation_id:"):
        clean_id = identity.split(":", 1)[1].strip()
        if "Donation ID" in df.columns:
            return df["Donation ID"].astype(str).str.strip().str.lower() == clean_id
        return pd.Series(False, index=df.index)
        
    # 2. If generic anonymous placeholder, never aggregate 43,000+ records!
    if identity in ANON_PLACEHOLDERS:
        if "Donation ID" in df.columns and (df["Donation ID"].astype(str).str.strip().str.lower() == identity).any():
            return df["Donation ID"].astype(str).str.strip().str.lower() == identity
        if "Display Name" in df.columns:
            sub = df[df["Display Name"].astype(str).str.strip().str.lower() == identity]
            if not sub.empty:
                mask = pd.Series(False, index=df.index)
                mask.loc[sub.index[0]] = True
                return mask
        return pd.Series(False, index=df.index)

    # 3. Match by exact Email
    if "@" in identity:
        mask = pd.Series(False, index=df.index)
        if "Email" in df.columns:
            mask |= (df["Email"].astype(str).str.strip().str.lower() == identity)
        if "Donor ID" in df.columns:
            mask |= (df["Donor ID"].astype(str).str.strip().str.lower() == identity)
        if mask.any():
            return mask

    # 4. Match by Donor ID (excluding generic placeholders)
    if "Donor ID" in df.columns:
        valid_donor_mask = (df["Donor ID"].astype(str).str.strip().str.lower() == identity) & (~df["Donor ID"].astype(str).str.strip().str.lower().isin(ANON_PLACEHOLDERS))
        if valid_donor_mask.any():
            return valid_donor_mask

    # 5. Match by exact Donation ID
    if "Donation ID" in df.columns:
        did_mask = (df["Donation ID"].astype(str).str.strip().str.lower() == identity)
        if did_mask.any():
            return did_mask

    # 6. Fallback: Match by authentic Full Name or Billing Name (only if not generic)
    mask = pd.Series(False, index=df.index)
    if "First Name" in df.columns and "Last Name" in df.columns:
        full_names = (df["First Name"].fillna("").astype(str).str.strip() + " " + df["Last Name"].fillna("").astype(str).str.strip()).str.strip().str.lower()
        mask |= (full_names == identity)
    if "Billing Name" in df.columns:
        mask |= (df["Billing Name"].astype(str).str.strip().str.lower() == identity)
    if "Display Name" in df.columns and identity not in ANON_PLACEHOLDERS:
        mask |= (df["Display Name"].astype(str).str.strip().str.lower() == identity)

    return mask


@router.get("/profile/{donor_id_or_email:path}")
def get_donor_360_profile(donor_id_or_email: str):
    """Returns complete 360° Donor Profile payload with all donor details, dual classifications, and full transaction history."""
    df = load_data()
    if df.empty:
        raise HTTPException(status_code=404, detail="Donor dataset is empty.")

    match_mask = _get_donor_matching_mask(df, donor_id_or_email)
    donor_txns = df.loc[match_mask]
    if donor_txns.empty:
        raise HTTPException(status_code=404, detail=f"Donor '{donor_id_or_email}' not found.")

    col_amount = "Total Online Donations Net Amount in Settled Currency"
    if col_amount not in df.columns:
        col_amount = "Donation Amount in Project Currency (May be approx.)"
    first_row = donor_txns.iloc[0]
    total_ltv = float(donor_txns[col_amount].sum()) if col_amount in donor_txns.columns else 0.0
    avg_donation = float(donor_txns[col_amount].mean()) if col_amount in donor_txns.columns else 0.0

    # Resolve authentic donor name prioritizing real human names over donation intentions
    best_display_name, best_first_name, best_last_name = resolve_best_donor_name(donor_txns, first_row)

    # Dual Classification: Lifetime Donor Tier AND Transaction Donor Tier!
    lifetime_tier = str(first_row.get("Lifetime Donor Classification", "Unassigned"))
    transaction_tier = str(first_row.get("Transaction Donor Classification", "Unassigned"))

    # Extract all details
    details = {
        "donor_id": str(first_row.get("Donor ID", "N/A")),
        "display_name": best_display_name,
        "first_name": best_first_name,
        "last_name": best_last_name,
        "email": str(first_row.get("Email", "N/A")),
        "phone": str(first_row.get("Phone", "N/A")),
        
        # Dual Classification Tiers
        "lifetime_tier": lifetime_tier,
        "transaction_tier": transaction_tier,

        # Billing & Address Details
        "billing_address_1": str(first_row.get("Billing Address Line 1", first_row.get("Billing Address", "N/A"))),
        "billing_address_2": str(first_row.get("Billing Address 2", "N/A")),
        "billing_city": str(first_row.get("Billing City", "N/A")),
        "billing_state": str(first_row.get("Billing State", "N/A")),
        "billing_postcode": str(first_row.get("Billing Post Code", first_row.get("Billing Zip", "N/A"))),
        "billing_country": str(first_row.get("Billing Country", "N/A")),

        # Financial Summary
        "total_ltv": round(total_ltv, 2),
        "avg_donation": round(avg_donation, 2),
        "total_donations_count": len(donor_txns),

        # Marketing, Tax & Metadata
        "marketing_consent": str(first_row.get("Marketing Consent", "N/A")),
        "gift_aid": str(first_row.get("Gift Aid (yes or no)", "N/A")),
        "tax_receipt_requested": str(first_row.get("Tax Receipt requested", "N/A")),
        "anonymous_public": str(first_row.get("Anonymous or Public", "N/A")),

        # Payment Details
        "payment_frequency": str(first_row.get("Payment Frequency", "N/A")),
        "payment_type": str(first_row.get("Payment Type", "N/A")),
        "settlement_currency": str(first_row.get("Settlement Currency", "N/A")),
        "source": str(first_row.get("Source", "N/A")),
        "platform": str(first_row.get("Platform", "N/A"))
    }

    # Format complete transaction timeline (sorted date DESC)
    timeline_cols = [c for c in [
        "Created Date (UTC)", "Campaign Name", "Heading", "Sub-Heading", 
        "Donation Currency (DC)", "Donation Amount (in Donation Currency)", 
        col_amount, "Payment Frequency", "Platform", "Source"
    ] if c in donor_txns.columns]

    timeline_df = donor_txns[timeline_cols].copy()
    if "Created Date (UTC)" in timeline_df.columns:
        parsed_dates = pd.to_datetime(timeline_df["Created Date (UTC)"], errors="coerce", format="mixed")
        timeline_df["_sort_date"] = parsed_dates
        timeline_df = timeline_df.sort_values(by="_sort_date", ascending=False)
        timeline_df["Created Date (UTC)"] = timeline_df["_sort_date"].dt.strftime("%Y-%m-%d").fillna("N/A")
        timeline_df = timeline_df.drop(columns=["_sort_date"], errors="ignore")

    timeline_df = timeline_df.fillna("N/A")
    if col_amount in timeline_df.columns:
        timeline_df[col_amount] = pd.to_numeric(timeline_df[col_amount], errors='coerce').fillna(0.0).round(2)

    # Cap initial embedded history to recent 100 items to prevent DOM overflow crashes on 28k+ records
    history = timeline_df.head(100).to_dict(orient="records")

    # Payment breakdown by Heading & Sub-Heading
    category_breakdown = []
    if "Heading" in donor_txns.columns:
        col_sub = "Sub-Heading" if "Sub-Heading" in donor_txns.columns else "Heading"
        donor_txns_copy = donor_txns.copy()
        donor_txns_copy["Heading"] = donor_txns_copy["Heading"].fillna("Unassigned")
        donor_txns_copy[col_sub] = donor_txns_copy[col_sub].fillna("Unassigned")
        
        b_df = donor_txns_copy.groupby(["Heading", col_sub])[col_amount].agg(["sum", "count"]).reset_index()
        b_df.columns = ["heading", "subheading", "total_amount", "count"]
        b_df["total_amount"] = pd.to_numeric(b_df["total_amount"], errors='coerce').fillna(0.0).round(2)
        b_df["percentage"] = (b_df["total_amount"] / total_ltv * 100).round(1) if total_ltv > 0 else 0.0
        b_df = b_df.sort_values(by="total_amount", ascending=False)
        category_breakdown = b_df.to_dict(orient="records")

    details["history"] = history
    details["category_breakdown"] = category_breakdown
    return details


@router.get("/history")
def get_donor_history_paginated(
    donor_id: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500)
):
    """Paginated transaction history for a donor to handle large transaction counts (e.g., 28,000+ transactions) smoothly."""
    df = load_data()
    if df.empty:
        raise HTTPException(status_code=404, detail="Donor dataset is empty.")

    match_mask = _get_donor_matching_mask(df, donor_id)
    donor_txns = df.loc[match_mask]
    if donor_txns.empty:
        return {"total_records": 0, "page": 1, "page_size": page_size, "total_pages": 1, "records": []}

    col_amount = "Total Online Donations Net Amount in Settled Currency"
    if col_amount not in df.columns:
        col_amount = "Donation Amount in Project Currency (May be approx.)"

    timeline_cols = [c for c in [
        "Created Date (UTC)", "Campaign Name", "Heading", "Sub-Heading", 
        "Donation Currency (DC)", "Donation Amount (in Donation Currency)", 
        col_amount, "Payment Frequency", "Platform", "Source"
    ] if c in donor_txns.columns]

    timeline_df = donor_txns[timeline_cols].copy()
    if "Created Date (UTC)" in timeline_df.columns:
        parsed_dates = pd.to_datetime(timeline_df["Created Date (UTC)"], errors="coerce", format="mixed")
        timeline_df["_sort_date"] = parsed_dates
        timeline_df = timeline_df.sort_values(by="_sort_date", ascending=False)
        timeline_df["Created Date (UTC)"] = timeline_df["_sort_date"].dt.strftime("%Y-%m-%d").fillna("N/A")
        timeline_df = timeline_df.drop(columns=["_sort_date"], errors="ignore")

    timeline_df = timeline_df.fillna("N/A")
    if col_amount in timeline_df.columns:
        timeline_df[col_amount] = pd.to_numeric(timeline_df[col_amount], errors='coerce').fillna(0.0).round(2)

    total_records = len(timeline_df)
    total_pages = max(1, math.ceil(total_records / page_size))
    page = max(1, page)
    page = min(page, total_pages)
    offset = (page - 1) * page_size

    sliced_df = timeline_df.iloc[offset:offset + page_size]
    records = sliced_df.to_dict(orient="records")

    return {
        "total_records": total_records,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "records": records
    }


@router.get("/campaigns")
def get_campaigns_list():
    """Returns sorted unique list of campaign names for fast dropdown filtering in Data Explorer."""
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT [Campaign Name]
            FROM donations
            WHERE [Campaign Name] IS NOT NULL AND TRIM([Campaign Name]) != ''
            ORDER BY [Campaign Name] COLLATE NOCASE ASC
        """)
        campaigns = [r[0].strip() for r in cur.fetchall() if r[0] and str(r[0]).strip()]
        conn.close()
        return {"campaigns": campaigns}
    except Exception as e:
        df = load_data()
        if not df.empty and "Campaign Name" in df.columns:
            campaigns = sorted([str(c).strip() for c in df["Campaign Name"].dropna().unique() if str(c).strip()])
            return {"campaigns": campaigns}
        return {"campaigns": []}
