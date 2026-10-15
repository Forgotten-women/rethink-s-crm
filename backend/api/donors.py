from core.cache import cached
import io
import math
import os
import sqlite3
import tempfile
import re
from datetime import datetime
from typing import List, Optional, Dict, Any
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from config.settings import LOCAL_DB_PATH, PARQUET_PATH, PAYOUTS_PARQUET_PATH
from core.data_processor import (
    load_data,
    load_payouts_data,
    sync_donor_classifications_to_matrix,
    atomic_write_parquet,
    sanitize_df_dtypes_for_parquet,
    invalidate_data_cache,
    invalidate_payouts_cache,
    sync_donors_to_classification_matrix,
    get_code_to_classification_map,
    classify_donor_amount,
)
from core.fast_export import dataframe_to_fast_xlsx, dataframe_to_fast_csv
from backend.api.auth import get_current_user

def _cleanup_temp_file(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

router = APIRouter(prefix="/api/donors", tags=["Donors & Explorer"])


class BulkEditDonorsRequest(BaseModel):
    user_role: Optional[str] = "admin"
    user_identity: Optional[str] = None
    user_email: Optional[str] = None
    target_columns: List[str]
    new_values: List[str]
    company_id: Optional[str] = "rethink"
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
    filter_giving_level: Optional[str] = None
    filter_gift_aid: Optional[str] = None
    filter_start_date: Optional[str] = None
    filter_end_date: Optional[str] = None
    can_edit_donors: Optional[bool] = False


class UpdateSingleDonorRequest(BaseModel):
    user_role: Optional[str] = "admin"
    user_identity: Optional[str] = None
    user_email: Optional[str] = None
    company_id: Optional[str] = "rethink"
    row_id: Optional[int] = None
    donation_id: Optional[str] = None
    donor_identifier: Optional[str] = None
    column_name: Optional[str] = None
    new_value: Optional[str] = None
    updated_fields: Optional[dict] = None
    can_edit_donors: Optional[bool] = False


@router.post("/update-record")
def update_single_donor_record(
    payload: UpdateSingleDonorRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    if payload.company_id and str(payload.company_id).strip().lower() == "all":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Modifications are disabled in consolidated 'All Companies' mode. Please select a specific company to edit records."
        )

    # Verify authorization
    user_role = current_user.get("role", "admin")
    can_edit = bool(current_user.get("can_edit_donors") or user_role == "super_admin" or payload.can_edit_donors)
    if not can_edit:
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

    target_table = "payout_settlements" if is_payout_target else "donations"
    target_donation_id = str(payload.donation_id).strip() if payload.donation_id else None

    # Charity isolation: the record must belong to the charity this request acts for (the API guard has
    # already checked the user may act for it). A record of another charity is reported as not found.
    edit_company = str(payload.company_id or "").strip().lower()
    scoped = bool(edit_company) and edit_company != "all" and "company_id" in df_raw.columns
    in_company = (df_raw["company_id"].astype(str).str.strip().str.lower() == edit_company) if scoped else None

    # Resolve target_donation_id from SQLite rowid if donation_id was omitted
    if not target_donation_id and payload.row_id is not None:
        try:
            conn_find = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
            c_find = conn_find.cursor()
            if scoped:
                c_find.execute(f'SELECT "Donation ID" FROM {target_table} WHERE rowid = ? AND LOWER(COALESCE(company_id, \'rethink\')) = ?',
                               (payload.row_id + 1, edit_company))
            else:
                c_find.execute(f'SELECT "Donation ID" FROM {target_table} WHERE rowid = ?', (payload.row_id + 1,))
            r_find = c_find.fetchone()
            conn_find.close()
            if r_find and r_find[0]:
                target_donation_id = str(r_find[0]).strip()
        except Exception:
            pass

    # If still not resolved, attempt dataframe index
    target_idx = None
    if target_donation_id and "Donation ID" in df_raw.columns:
        d_id_lower = target_donation_id.lower()
        id_match = df_raw["Donation ID"].astype(str).str.strip().str.lower() == d_id_lower
        if scoped:
            if id_match.any() and not (id_match & in_company).any():
                raise HTTPException(status_code=404, detail="Record not found for this charity.")
            id_match = id_match & in_company
        matches = df_raw.index[id_match].tolist()
        if len(matches) > 0:
            target_idx = matches[0]
    elif payload.row_id is not None and payload.row_id in df_raw.index and (not scoped or bool(in_company.loc[payload.row_id])):
        target_idx = payload.row_id
        if "Donation ID" in df_raw.columns:
            target_donation_id = str(df_raw.loc[target_idx, "Donation ID"]).strip()

    if target_idx is None and not target_donation_id:
        raise HTTPException(status_code=404, detail="Specific record could not be uniquely identified for editing.")

    # Gather field updates
    update_dict = {}
    if payload.updated_fields and isinstance(payload.updated_fields, dict):
        for col, val in payload.updated_fields.items():
            if not str(col).startswith("_"):
                update_dict[col] = val
    elif payload.column_name and payload.new_value is not None:
        if not str(payload.column_name).startswith("_"):
            update_dict[payload.column_name] = payload.new_value

    old_email = ""
    old_did = ""
    if target_idx is not None:
        old_email = str(df_raw.loc[target_idx, "Email"]).strip().lower() if "Email" in df_raw.columns and pd.notna(df_raw.loc[target_idx, "Email"]) else ""
        old_did = str(df_raw.loc[target_idx, "Donor ID"]).strip().lower() if "Donor ID" in df_raw.columns and pd.notna(df_raw.loc[target_idx, "Donor ID"]) else ""

    # Synchronize email changes
    if "Email" in update_dict:
        new_email = str(update_dict["Email"] or "").strip().lower()
        if new_email and "@" in new_email and new_email != old_email:
            update_dict["Donor ID"] = new_email
            # Only the edited donation's charity: the same email may be a different
            # person's sponsorship record in the other charity.
            row_company = ""
            if target_idx is not None and "company_id" in df_raw.columns and pd.notna(df_raw.loc[target_idx, "company_id"]):
                row_company = str(df_raw.loc[target_idx, "company_id"]).strip().lower()
            try:
                conn_alloc = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
                old_key = old_did if old_did else old_email
                conn_alloc.execute(
                    "UPDATE sponsorship_allocations SET donor_email = ?, donor_id = ? WHERE company_id = ? AND (LOWER(donor_email) = ? OR LOWER(donor_id) = ?)",
                    (new_email, new_email, row_company, old_email, old_key)
                )
                try:
                    conn_alloc.execute(
                        "UPDATE sponsorship_allocation_donors SET donor_email = ?, donor_id = ? WHERE company_id = ? AND (LOWER(donor_email) = ? OR LOWER(donor_id) = ?)",
                        (new_email, new_email, row_company, old_email, old_key)
                    )
                except sqlite3.OperationalError:
                    pass  # table not created yet on this deployment
                conn_alloc.commit()
                conn_alloc.close()
            except Exception as ex:
                print(f"[Allocation Email Sync Notice]: {ex}")

    # Auto-fill classification metadata from Code dictionary if Code was modified
    new_code_val = update_dict.get("Code")
    if new_code_val:
        c_code_clean = str(new_code_val).strip().lower()
        if c_code_clean not in ["unassigned", "nan", "none", "n/a", ""]:
            c_map = get_code_to_classification_map(company_id=str(payload.company_id or "rethink").strip().lower())  # this charity's codes
            if c_code_clean in c_map:
                c_info = c_map[c_code_clean]
                for col in ["Department", "Office", "Portfolio", "Heading", "Sub-Heading", "Country", "Zakat Eligibility", "Programme Fund", "Fund Code"]:
                    if col not in update_dict or update_dict[col] in [None, "", "Unassigned"]:
                        val = c_info.get(col)
                        if val:
                            update_dict[col] = val

    # 1. Targeted, Non-Destructive SQLite UPDATE (Preserves all indexes and constraints)
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({target_table})")
        db_cols = set(r[1] for r in cursor.fetchall())

        valid_updates = {c: v for c, v in update_dict.items() if c in db_cols}
        if valid_updates and target_donation_id:
            set_clauses = [f'"{c}" = ?' for c in valid_updates.keys()]
            params = list(valid_updates.values()) + [target_donation_id]
            where = 'WHERE "Donation ID" = ?'
            if scoped and "company_id" in db_cols:
                where += " AND LOWER(COALESCE(company_id, 'rethink')) = ?"
                params.append(edit_company)
            cursor.execute(f'UPDATE {target_table} SET {", ".join(set_clauses)} {where}', params)
            conn.commit()
        conn.close()
    except Exception as sql_err:
        print(f"[SQL Targeted Update Notice]: {sql_err}")

    # 2. Update In-Memory DataFrame
    if target_idx is not None:
        for col, val in update_dict.items():
            if col in df_raw.columns:
                df_raw.loc[target_idx, col] = val
    elif target_donation_id and "Donation ID" in df_raw.columns:
        mask = df_raw["Donation ID"].astype(str).str.strip().str.lower() == target_donation_id.lower()
        if scoped:
            mask = mask & in_company
        if mask.any():
            for col, val in update_dict.items():
                if col in df_raw.columns:
                    df_raw.loc[mask, col] = val

    df_raw = sanitize_df_dtypes_for_parquet(df_raw)

    # 3. Atomic Parquet Update (Never corrupts file)
    if is_payout_target:
        atomic_write_parquet(df_raw, PAYOUTS_PARQUET_PATH)
        invalidate_payouts_cache()
    else:
        atomic_write_parquet(df_raw, PARQUET_PATH)
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
        "message": f"Successfully updated record (Donation ID: {target_donation_id or target_idx})."
    }


@router.post("/bulk-edit")
def bulk_edit_donors(
    payload: BulkEditDonorsRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    if payload.company_id and str(payload.company_id).strip().lower() == "all":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bulk edits are disabled in consolidated 'All Companies' mode. Please select a specific company to edit records."
        )

    user_role = current_user.get("role", "admin")
    can_edit = bool(current_user.get("can_edit_donors") or user_role == "super_admin" or payload.can_edit_donors)
    if not can_edit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Editing records is restricted to authorized accounts."
        )

    is_payout_bulk = bool(payload.filter_source and str(payload.filter_source).strip().lower() in ["launchgood payout", "payout", "payouts"])
    df_raw = load_payouts_data(company_id=payload.company_id) if is_payout_bulk else load_data(company_id=payload.company_id)
    if df_raw.empty:
        raise HTTPException(status_code=400, detail="Target dataset is empty.")
    # Checked before anything is written: the edited rows must merge back into the full file by index.
    df_full = load_payouts_data(company_id="all") if is_payout_bulk else load_data(company_id="all")
    if not df_full.index.is_unique or not df_raw.index.isin(df_full.index).all():
        raise HTTPException(status_code=500, detail="Could not prepare a safe merge for this edit; nothing was changed.")

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
        campaign=payload.filter_campaign,
        company_id=payload.company_id,
        giving_level=payload.filter_giving_level
    )

    # 2. Apply search filter with multi-Donation ID support
    if payload.filter_search and str(payload.filter_search).strip():
        filtered_df = _apply_search_to_df(filtered_df, payload.filter_search, search_fields=payload.filter_search_fields)

    matching_indices = filtered_df.index
    if len(matching_indices) == 0:
        return {"status": "success", "message": "No matching records found to edit."}

    bulk_updates = {}
    for col, val in zip(payload.target_columns, payload.new_values):
        if col and col in df_raw.columns:
            df_raw.loc[matching_indices, col] = val
            bulk_updates[col] = val

    # If 'Email' was among target columns, update Donor ID as well
    if "Email" in payload.target_columns:
        e_idx = payload.target_columns.index("Email")
        new_email_val = str(payload.new_values[e_idx] or "").strip().lower()
        if "@" in new_email_val and "Donor ID" in df_raw.columns:
            df_raw.loc[matching_indices, "Donor ID"] = new_email_val
            bulk_updates["Donor ID"] = new_email_val

    # If 'Code' was among target columns, auto-fill classification metadata
    if "Code" in payload.target_columns:
        c_idx = payload.target_columns.index("Code")
        new_c_val = str(payload.new_values[c_idx] or "").strip().lower()
        if new_c_val and new_c_val not in ["unassigned", "nan", "none", "n/a", ""]:
            c_map = get_code_to_classification_map(company_id=str(payload.company_id or "rethink").strip().lower())  # this charity's codes
            if new_c_val in c_map:
                c_info = c_map[new_c_val]
                for tc in ["Department", "Office", "Portfolio", "Heading", "Sub-Heading", "Country", "Zakat Eligibility", "Programme Fund", "Fund Code"]:
                    if tc in df_raw.columns and tc not in payload.target_columns:
                        t_val = c_info.get(tc, "Unassigned" if tc not in ["Portfolio", "Programme Fund", "Fund Code"] else "")
                        if t_val != "Unassigned" and t_val != "":
                            df_raw.loc[matching_indices, tc] = t_val
                            bulk_updates[tc] = t_val

    # 1. Non-Destructive Parameterized SQLite Batch UPDATE
    target_table = "payout_settlements" if is_payout_bulk else "donations"
    matching_don_ids = []
    if "Donation ID" in df_raw.columns:
        matching_don_ids = df_raw.loc[matching_indices, "Donation ID"].dropna().astype(str).tolist()

    if matching_don_ids and bulk_updates:
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({target_table})")
            db_cols = set(r[1] for r in cursor.fetchall())

            valid_updates = {c: v for c, v in bulk_updates.items() if c in db_cols}
            if valid_updates:
                set_clauses = [f'"{c}" = ?' for c in valid_updates.keys()]
                set_sql = ", ".join(set_clauses)
                chunk_size = 500
                for i in range(0, len(matching_don_ids), chunk_size):
                    chunk = matching_don_ids[i:i + chunk_size]
                    placeholders = ", ".join(["?"] * len(chunk))
                    company_sql, company_params = "", []
                    if "company_id" in db_cols:
                        company_sql = " AND LOWER(COALESCE(company_id, 'rethink')) = ?"
                        company_params = [str(payload.company_id).strip().lower()]
                    cursor.execute(
                        f'UPDATE {target_table} SET {set_sql} WHERE "Donation ID" IN ({placeholders}){company_sql}',
                        list(valid_updates.values()) + chunk + company_params
                    )
                conn.commit()
            conn.close()
        except Exception as sql_bulk_err:
            print(f"[SQL Bulk Update Notice]: {sql_bulk_err}")

    # df_raw holds only this charity's rows; the parquet file holds every charity. Put the edited rows
    # back into the full dataset (same row order) instead of overwriting the file with one charity.
    df_raw = pd.concat([df_full.drop(index=df_raw.index), df_raw]).sort_index()

    df_raw = sanitize_df_dtypes_for_parquet(df_raw)

    # 2. Atomic Parquet Update
    if is_payout_bulk:
        atomic_write_parquet(df_raw, PAYOUTS_PARQUET_PATH)
        invalidate_payouts_cache()
    else:
        atomic_write_parquet(df_raw, PARQUET_PATH)
        invalidate_data_cache()
        sync_donors_to_classification_matrix(df_raw)

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
        "message": f"Successfully updated {len(matching_indices):,} matching records across columns: {', '.join(payload.target_columns)}."
    }


ALL_ID_COLUMNS = [
    "Donation ID",
    "Donor ID",
    "charge_id",
    "_id",
    "subscription_id",
    "sub_id",
    "Transfer ID",
    "Transaction ID",
    "ID",
    "campaign_id",
    "campaign_uid",
    "Customer Ref",
    "Additional Ref",
    "Subscription Reference",
    "Invoice ID"
]


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
    """Applies multi-ID (Donor ID, charge_id, _id, Donation ID, etc.) and targeted or universal text search across scoped fields."""
    if not search_str or not str(search_str).strip() or df.empty:
        return df

    id_tokens, raw_text = _parse_search_query(search_str)
    mask = pd.Series(False, index=df.index)

    active_targets = set([f.strip().lower() for f in search_fields.split(",") if f.strip()]) if search_fields else set()
    search_all = not active_targets or "all" in active_targets

    is_id_search = search_all or any(k in active_targets for k in ["donation_id", "id", "ids", "donor_id", "charge_id"])

    # 1. Multi ID match (exact token matching across all ID fields, case-insensitive, float/integer normalized)
    if is_id_search and id_tokens:
        lower_tokens = set(t.lower() for t in id_tokens)
        expanded_tokens = set(lower_tokens)
        for t in lower_tokens:
            if t.endswith('.0'):
                expanded_tokens.add(t[:-2])
            elif t.isdigit():
                expanded_tokens.add(f"{t}.0")

        for id_col in ALL_ID_COLUMNS:
            if id_col in df.columns:
                id_series = df[id_col].astype(str).str.strip().str.lstrip('#').str.lower()
                clean_no_dot_zero = id_series.str.replace(r'\.0$', '', regex=True)
                mask |= id_series.isin(expanded_tokens) | clean_no_dot_zero.isin(expanded_tokens)

    # 2. General text match across selected targets (case-insensitive substring)
    clean_term = raw_text.strip().lstrip('#').lower()
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
    if is_id_search:
        target_cols.extend(ALL_ID_COLUMNS)

    search_cols = [c for c in dict.fromkeys(target_cols) if c in df.columns]
    for sc in search_cols:
        mask |= df[sc].astype(str).str.lower().str.contains(clean_term, na=False, regex=False)

    return df.loc[mask]


def _apply_filters(df, payment_type=None, tier=None, source=None, heading=None, subheading=None, country=None, code=None, zakat=None, donor_country=None, campaign_search=None, gift_aid=None, start_date=None, end_date=None, programme_fund=None, campaign=None, company_id=None, giving_level=None):
    if df is None or df.empty:
        return df

    mask = pd.Series(True, index=df.index)

    if company_id and str(company_id).strip().lower() != "all" and "company_id" in df.columns:
        mask &= (df["company_id"].astype(str).str.strip().str.lower() == str(company_id).strip().lower())

    if isinstance(programme_fund, str) and programme_fund.strip() and programme_fund != "All Programme Funds" and "Programme Fund" in df.columns:
        mask &= (df["Programme Fund"].astype(str).str.strip().str.lower() == programme_fund.strip().lower())

    if isinstance(campaign, str) and campaign.strip() and campaign != "All Campaigns" and "Campaign Name" in df.columns:
        mask &= (df["Campaign Name"].astype(str).str.strip().str.lower() == campaign.strip().lower())

    if isinstance(giving_level, str) and giving_level.strip() and giving_level != "All Giving Levels" and "Giving Level Title" in df.columns:
        gl_clean = giving_level.strip()
        if gl_clean.lower() in ["__default__", "default (general)", "default", "none"]:
            mask &= (df["Giving Level Title"].isna() | df["Giving Level Title"].astype(str).str.strip().str.lower().isin(["", "nan", "none", "null", "n/a", "default (general)"]))
        else:
            mask &= (df["Giving Level Title"].astype(str).str.strip().str.lower() == gl_clean.lower())

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

    # High-speed ISO Date Filtering with resilient multi-column fallback
    if (isinstance(start_date, str) and start_date.strip()) or (isinstance(end_date, str) and end_date.strip()):
        s_date = start_date.strip()[:10] if isinstance(start_date, str) and start_date.strip() else None
        e_date = end_date.strip()[:10] if isinstance(end_date, str) and end_date.strip() else None

        date_col = None
        for dcol in ["_parsed_date", "Created Date (UTC)", "Date", "created_at", "Settled Date (UTC)", "Date of collection", "Date Due"]:
            if dcol in df.columns:
                cur_s = df[dcol].astype(str).str.strip()
                valid = ~cur_s.str.lower().isin(["", "nan", "none", "nat", "<na>"])
                if valid.any():
                    valid_cur = cur_s[valid]
                    # If format has slashes DD/MM/YYYY, convert to YYYY-MM-DD
                    slash_mask = valid_cur.str.match(r"^\d{1,2}/\d{1,2}/\d{4}")
                    if slash_mask.any():
                        parts = valid_cur[slash_mask].str.extract(r"^(\d{1,2})/(\d{1,2})/(\d{4})")
                        norm = parts[2] + "-" + parts[1].str.zfill(2) + "-" + parts[0].str.zfill(2)
                        cur_s = cur_s.copy()
                        cur_s.loc[slash_mask.index[slash_mask]] = norm

                    cur_s = cur_s.str.slice(0, 10)
                    if date_col is None:
                        date_col = cur_s.where(valid)
                    else:
                        date_col = date_col.fillna(cur_s.where(valid))

        if date_col is not None:
            valid_mask = date_col.notna() & (~date_col.astype(str).str.lower().isin(["", "nan", "none", "nat", "<na>"]))
            if s_date:
                mask &= (valid_mask & (date_col.astype(str) >= s_date))
            if e_date:
                mask &= (valid_mask & (date_col.astype(str) <= e_date))

    if mask.all():
        return df
    return df[mask]


@router.get("")
@cached(scopes=["donations", "classification", "payouts"], ttl=1800)
def get_donors_paginated(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    search: Optional[str] = "",
    search_fields: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = "asc",
    company_id: Optional[str] = Query("rethink"),
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
    giving_level: Optional[str] = None,
    gift_aid: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Ultra-fast SQL Paginated Endpoint (< 100ms) with multi-Donation ID and scoped field text search.
    Strictly queries donations data without payout records, partitioned by company_id.
    """
    page_val = getattr(page, "default", page)
    page_val = int(page_val) if isinstance(page_val, (int, str, float)) and str(page_val).isdigit() else 1
    page = max(1, page_val)

    ps_val = getattr(page_size, "default", page_size)
    ps_val = int(ps_val) if isinstance(ps_val, (int, str, float)) and str(ps_val).isdigit() else 100
    page_size = max(1, min(1000, ps_val))

    cid_val = getattr(company_id, "default", company_id)
    comp = str(cid_val or "rethink").lower().strip()

    is_payout_query = bool(source and str(source).strip().lower() in ["launchgood payout", "payout", "payouts"])
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

            # Partition by company_id
            if comp != "all" and "company_id" in avail_cols:
                where_clauses.append('LOWER(COALESCE("company_id", \'rethink\')) = ?')
                params.append(comp)

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

            if giving_level and str(giving_level).strip() and giving_level != "All Giving Levels" and "Giving Level Title" in avail_cols:
                gl_clean = str(giving_level).strip()
                if gl_clean.lower() in ["__default__", "default (general)", "default", "none"]:
                    where_clauses.append('(LOWER(COALESCE("Giving Level Title", \'\')) IN (\'\', \'nan\', \'none\', \'null\', \'n/a\', \'default (general)\') OR "Giving Level Title" IS NULL)')
                else:
                    where_clauses.append('LOWER(TRIM(COALESCE("Giving Level Title", \'\'))) = ?')
                    params.append(gl_clean.lower())

            if gift_aid and gift_aid != "All Gift Aid Status":
                where_clauses.append('("Gift Aid (yes or no)" LIKE ? OR "is_giftaid" = ?)')
                params.extend([f"%{gift_aid}%", 1 if gift_aid.lower() == "yes" else 0])

            date_col_sql = 'COALESCE(NULLIF("Created Date (UTC)", ""), NULLIF("_parsed_date", ""), NULLIF("Date", ""))'
            if start_date and str(start_date).strip():
                s_clean = str(start_date).strip()[:10]
                where_clauses.append(f'({date_col_sql} >= ? AND {date_col_sql} != \'nan\')')
                params.append(s_clean)

            if end_date and str(end_date).strip():
                e_clean = str(end_date).strip()[:10]
                where_clauses.append(f'({date_col_sql} <= ? AND {date_col_sql} != \'nan\')')
                params.append(e_clean)

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

                is_id_search = search_all or any(k in active_targets for k in ["donation_id", "id", "ids", "donor_id", "charge_id"])

                # Multi-ID match (supports any ID: Donor ID, charge_id, _id, Donation ID, subscription_id, Transfer ID, etc.)
                if id_tokens and is_id_search:
                    id_placeholders = ','.join(['?'] * len(id_tokens))
                    id_cols = [f'"{c}"' for c in ALL_ID_COLUMNS if c in avail_cols]
                    if id_cols:
                        id_clause = " OR ".join([
                            f"(LOWER(CAST({col} AS TEXT)) IN ({id_placeholders}) OR REPLACE(LOWER(CAST({col} AS TEXT)), '.0', '') IN ({id_placeholders}))"
                            for col in id_cols
                        ])
                        search_parts.append(f"({id_clause})")
                        clean_tokens = [t.lower() for t in id_tokens]
                        search_subparams.extend(clean_tokens * (2 * len(id_cols)))

                # General text match across selected target columns
                clean_term = raw_text.strip().lstrip('#')
                text_term = f"%{clean_term}%"
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
                if is_id_search:
                    target_cols.extend([f'"{c}"' for c in ALL_ID_COLUMNS if c in avail_cols])

                search_cols = [col for col in dict.fromkeys(target_cols) if col.strip('"') in avail_cols]
                for col in search_cols:
                    search_parts.append(f"CAST({col} AS TEXT) LIKE ?")
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

    df_raw = load_payouts_data(company_id=comp) if is_payout_query else load_data(company_id=comp)
    if df_raw.empty:
        return {
            "total_records": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 0,
            "records": []
        }

    filtered_df = _apply_filters(df_raw, payment_type, tier, source, heading, subheading, country, code, zakat, donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund=programme_fund, campaign=campaign, company_id=comp, giving_level=giving_level)
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
    company_id: Optional[str] = Query("rethink"),
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
    giving_level: Optional[str] = None,
    gift_aid: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """Exports filtered donor rows with date range, multi-Donation ID, and scoped search support."""
    df_raw = load_data(company_id=company_id)
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
        campaign=campaign,
        company_id=company_id,
        giving_level=giving_level
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
@cached(scopes=["donations", "classification"], ttl=1800)
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
    gift_aid: Optional[str] = None,
    company_id: Optional[str] = Query("rethink")
):
    """Returns donor cards grouped by LTV Tier for the Kanban Pipeline Board with column total sums."""
    df_raw = load_data(company_id=company_id)
    df = _apply_filters(df_raw, payment_type, tier, source, heading, subheading, country, code, zakat, donor_country, campaign_search, gift_aid, programme_fund=programme_fund, company_id=company_id)

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


DONOR_TITLE_PREFIXES = {
    'dr', 'dr.', 'mr', 'mr.', 'mrs', 'mrs.', 'ms', 'ms.', 'miss', 
    'prof', 'prof.', 'professor', 'sheikh', 'shaykh', 'shaykha', 'sheikha',
    'haji', 'hajji', 'hajjah', 'haja', 'ustadh', 'ustad', 'ustadha',
    'imam', 'mufti', 'brother', 'sister', 'dr/mr', 'dr/mrs', 'lord', 'lady', 'sir'
}


def _clean_name_for_match(s):
    if not s or pd.isna(s):
        return ""
    raw = str(s).strip()
    words = raw.split()
    while words and words[0].lower().rstrip('.') in DONOR_TITLE_PREFIXES:
        words.pop(0)
    cleaned = ' '.join(words).strip().lower()
    cleaned = re.sub(r'[^a-z\s]', '', cleaned).strip()
    return re.sub(r'\s+', ' ', cleaned)


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

    # 3. Match by exact Email (across all email-containing fields)
    if "@" in identity:
        mask = pd.Series(False, index=df.index)
        for ec in ["Email", "Giving Level Email", "Email (for tax receipt)", "Donor ID"]:
            if ec in df.columns:
                mask |= (df[ec].astype(str).str.strip().str.lower() == identity)
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

    # 6. Match by Phone Number (if identity formatted as phone or digits)
    clean_digits = re.sub(r'[^\d]', '', identity)
    clean_digits = re.sub(r'^44', '', clean_digits).lstrip('0')
    if identity.startswith("phone:") or (len(clean_digits) >= 7 and "@" not in identity):
        p_mask = pd.Series(False, index=df.index)
        for pc in ["Phone Number", "Phone", "phone_number", "Home phone number", "Contact Phone"]:
            if pc in df.columns:
                cand_digits = df[pc].astype(str).str.replace(r'[^\d]', '', regex=True).str.replace(r'^44', '', regex=True).str.lstrip('0')
                p_mask |= (cand_digits == clean_digits)
        if p_mask.any():
            return p_mask

    # 7. Fallback: Match by authentic Full Name or Billing Name (normalized, with title stripping)
    mask = pd.Series(False, index=df.index)
    clean_ident_name = _clean_name_for_match(identity)
    if clean_ident_name and clean_ident_name not in ANON_PLACEHOLDERS and len(clean_ident_name) >= 3:
        if "First Name" in df.columns and "Last Name" in df.columns:
            raw_full = (df["First Name"].fillna("").astype(str).str.strip() + " " + df["Last Name"].fillna("").astype(str).str.strip()).str.strip()
            clean_full = raw_full.apply(_clean_name_for_match)
            mask |= (clean_full == clean_ident_name)
        if "Billing Name" in df.columns:
            clean_bn = df["Billing Name"].apply(_clean_name_for_match)
            mask |= (clean_bn == clean_ident_name)
        if "Display Name" in df.columns:
            clean_disp = df["Display Name"].apply(_clean_name_for_match)
            mask |= (clean_disp == clean_ident_name)

    return mask


@router.get("/profile/{donor_id_or_email:path}")
def get_donor_360_profile(donor_id_or_email: str, company_id: Optional[str] = Query(None)):
    """Returns complete 360° Donor Profile payload with all donor details, dual classifications, and full transaction history."""
    comp = str(company_id or "").strip().lower()
    df = load_data(company_id=comp if comp and comp != "all" else None)
    match_mask = _get_donor_matching_mask(df, donor_id_or_email) if not df.empty else pd.Series(False, index=df.index)
    donor_txns = df.loc[match_mask] if not df.empty else pd.DataFrame()

    # No fallback to other charities: a donor that isn't in the requested charity is not found.
    # (company_id omitted/'all' already searches every charity, and the API guard only allows that
    # for accounts with access to all of them.)

    manual = _manual_for_identity(comp or "all", donor_id_or_email, donor_txns)
    if donor_txns.empty:
        if not manual:
            raise HTTPException(status_code=404, detail=f"Donor '{donor_id_or_email}' not found.")
        m0 = manual[0]
        manual_total = round(sum(float(m.get("total_donated") or 0.0) for m in manual), 2)
        return {
            "donor_id": m0["key"], "display_name": (m0.get("donor_name") or "").strip() or "Manual donor",
            "email": m0.get("donor_email") or "N/A", "phone": m0.get("donor_phone") or "N/A",
            "lifetime_tier": "Manual entry", "transaction_tier": "Manual entry",
            "total_ltv": manual_total, "avg_donation": round(manual_total / len(manual), 2),
            "total_donations_count": len(manual), "manual_total": manual_total, "manual_records": len(manual),
            "platform": MANUAL_PLATFORM, "source": MANUAL_PLATFORM, "payment_frequency": "N/A", "payment_type": "N/A",
            "gift_aid": "N/A", "marketing_consent": "N/A", "tax_receipt_requested": "N/A", "anonymous_public": "N/A",
            "settlement_currency": "GBP", "billing_city": "N/A", "billing_state": "N/A", "billing_postcode": "N/A",
            "billing_country": "N/A", "history": _manual_history_rows(manual, "Total Online Donations Net Amount in Settled Currency"),
            "category_breakdown": [{"heading": "Sponsorship", "subheading": m.get("sponsorship_type") or "Sponsorship",
                                    "total_amount": round(float(m.get("total_donated") or 0.0), 2), "count": 1,
                                    "percentage": round(float(m.get("total_donated") or 0.0) / manual_total * 100, 1) if manual_total else 0.0}
                                   for m in manual],
        }

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
        col_amount, "Payment Frequency", "Platform", "Source",
        # full detail for the donor panel
        "Donation ID", "Code", "Department", "Office", "Country", "Programme Fund", "Fund Code", "Zakat Eligibility",
        "Giving Level Title", "fundraiser_name", "Status", "Transaction Type", "Payment Type",
        "Total Online Donation Gross Amount in Settled Currency", "Total Processing Fees Paid by CC In Settled Currency",
        "Settlement Currency", "Gift Aid (yes or no)", "Zakat (yes or no)", "Anonymous or Public", "Comments",
    ] if c in donor_txns.columns]
    timeline_cols = list(dict.fromkeys(timeline_cols))

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
    if manual:  # also recorded by hand in the Sponsorship Tracker
        details["manual_total"] = round(sum(float(m.get("total_donated") or 0.0) for m in manual), 2)
        details["manual_records"] = len(manual)
        details["total_donations_count"] = int(details.get("total_donations_count") or 0) + len(manual)
    return details


# ---------------------------------------------------------------------------------------------------------
# Donor directory: one row per donor (not per donation), searchable / sortable / paged. Donations are grouped by
# Donor ID (the same key the donor profile uses); generated placeholders ("anonymous", "name:nan nan") are left
# out so unrelated anonymous gifts are never merged into one fake donor. Built once per charity and reused until
# that charity's donations change.
# ---------------------------------------------------------------------------------------------------------
_DIRECTORY_CACHE: Dict[str, Any] = {}
_DIRECTORY_AMOUNT = "Total Online Donations Net Amount in Settled Currency"
MANUAL_PLATFORM = "Manual (Sponsorship Tracker)"


def _manual_donor_records(comp: str) -> List[Dict[str, Any]]:
    """Donors added by hand in the Sponsorship Tracker (read live; no copy is kept)."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        q = """SELECT id, company_id, donor_name, donor_email, donor_phone, sponsorship_type, total_donated, notes,
                      created_at, classification FROM sponsorship_manual_donors"""
        rows = conn.execute(q + (" WHERE LOWER(company_id) = ?" if comp != "all" else ""), (comp,) if comp != "all" else ()).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    out = []
    for r in rows:
        r = dict(r)
        email = (r.get("donor_email") or "").strip().lower()
        r["key"] = email if "@" in email else f"manual:{r['id']}".lower()
        out.append(r)
    return out


def _manual_for_identity(comp: str, identity: str, donor_txns: Optional[pd.DataFrame] = None) -> List[Dict[str, Any]]:
    """Manual records for this donor: same email (as typed or as on their platform gifts) or a manual:<id> key."""
    ident = str(identity or "").strip().lower()
    if not ident:
        return []
    emails = {ident}
    if donor_txns is not None and not donor_txns.empty and "Email" in donor_txns.columns:
        emails |= set(donor_txns["Email"].dropna().astype(str).str.strip().str.lower())
    return [m for m in _manual_donor_records(comp) if m["key"] in emails or ident == f"manual:{str(m['id']).lower()}"]


def _manual_history_rows(records: List[Dict[str, Any]], col_amount: str) -> List[Dict[str, Any]]:
    rows = []
    for m in records:
        rows.append({
            "Created Date (UTC)": str(m.get("created_at") or "")[:10] or "N/A",
            "Donation ID": m["id"], "Platform": MANUAL_PLATFORM, "Source": MANUAL_PLATFORM,
            "Campaign Name": f"{m.get('sponsorship_type') or 'Sponsorship'} sponsorship (recorded manually)",
            "Heading": "Sponsorship", "Sub-Heading": m.get("sponsorship_type") or "Sponsorship",
            col_amount: round(float(m.get("total_donated") or 0.0), 2), "Settlement Currency": "GBP",
            "Status": "recorded in tracker", "Comments": m.get("notes") or "",
        })
    return rows


def _clean_text(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip()
    return s.mask(s.str.lower().isin(["", "nan", "none", "null", "n/a", "<na>", "nat"]))


SPONSORSHIP_TYPES = ("Orphan", "Hafiz", "Widow", "Ex-Prisoner")


def _donor_directory_frame(comp: str) -> pd.DataFrame:
    return _directory_data(comp)[0]


def _directory_data(comp: str):
    """(donor frame, donation index). The donor frame has one row per donor; the donation index has one row per
    gift (plus manual tracker entries) with the fields segments filter on (date, cause, amount, platform, ...)."""
    from core.cache import version_token
    token = version_token(["donations", "classification", "tracker", "fundraisers"], comp)
    hit = _DIRECTORY_CACHE.get(comp)
    if hit and hit[0] == token:
        return hit[1], hit[2]
    df = load_data(company_id=comp if comp != "all" else None)
    if df is None or df.empty or "Donor ID" not in df.columns:
        frame = pd.DataFrame()
        _DIRECTORY_CACHE[comp] = (token, frame, pd.DataFrame())
        return frame, pd.DataFrame()
    key = df["Donor ID"].astype(str).str.strip().str.lower()
    # Only real placeholders: "name:nan nan" / "name:none" / "name:anonymous …" - never a real name such as
    # "name:nancy refaat" that merely starts with the same letters.
    usable = ~(key.isin(ANON_PLACEHOLDERS) | key.str.fullmatch(r"name:((nan|none|null|n/a)( (nan|none|null|n/a))?)?")
               | key.str.match(r"name:anonymous\b"))

    def col(c):
        return _clean_text(df[c]) if c in df.columns else pd.Series(pd.NA, index=df.index, dtype=object)

    first, last = col("First Name"), col("Last Name")
    full = (first.fillna("") + " " + last.fillna("")).str.strip()
    full = full.mask(full == "").fillna(col("Billing Name")).fillna(col("Display Name"))
    phone = col("Phone Number")
    for pc in ("Phone", "phone_number", "Contact Phone"):
        phone = phone.fillna(col(pc))
    freq = col("Payment Frequency").fillna("").str.lower()
    # Sponsorship type of each gift - the same rules as the Sponsorship Tracker
    try:
        from backend.api.tracker import _sponsorship_masks
        masks = _sponsorship_masks(df)
    except Exception:
        masks = {}
    stype = pd.Series("", index=df.index, dtype=object)
    for t in reversed(SPONSORSHIP_TYPES):
        if t in masks:
            stype = stype.mask(masks[t].fillna(False).astype(bool), t)
    # SP (Sisters' Project): credited to an SP fundraiser (by name, assigned campaign name or tracked page), or the
    # campaign / page itself is an SP page. Look-ups on unique values only, so it stays fast on 100k+ gifts.
    sp = pd.Series(False, index=df.index)
    try:
        from backend.api.fundraisers import is_sp_text, resolve_page_group
        conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=10)
        try:
            frs = conn.execute("SELECT id, name, page_group FROM fundraisers WHERE LOWER(company_id) = ?", (comp,)).fetchall()
            assigned = conn.execute("""SELECT fundraiser_id, COALESCE(campaign_name, ''), COALESCE(match_type, 'campaign_name'),
                                              COALESCE(match_value, '') FROM fundraiser_campaigns WHERE LOWER(company_id) = ?""", (comp,)).fetchall()
        finally:
            conn.close()
        camps: Dict[str, List[str]] = {}
        for fid, cn, mt, mv in assigned:
            camps.setdefault(fid, []).extend([cn, mv])
        sp_ids = {fid for fid, n, pg in frs if resolve_page_group(pg, n or "", camps.get(fid, [])) == "SP"}
        sp_names = {str(n or "").strip().lower() for fid, n, pg in frs if fid in sp_ids}
        sp_campaigns = {cn.strip().lower() for fid, cn, mt, mv in assigned if fid in sp_ids and mt == "campaign_name" and cn.strip()}
        slug = lambda u: str(u or "").strip().lower().split("?")[0].rstrip("/").split("/")[-1]  # noqa: E731
        sp_slugs = {slug(mv) for fid, cn, mt, mv in assigned if fid in sp_ids and mt != "campaign_name" and slug(mv)}

        def flag(series: pd.Series, fn) -> pd.Series:
            vals = series.fillna("").astype(str)
            uniq = {v: bool(fn(v)) for v in vals.unique() if isinstance(v, str) and v and v.lower() not in ("nan", "none")}
            return vals.map(uniq).fillna(False).astype(bool)

        for c in ("fundraiser_name", "Fundraiser Name"):
            if c in df.columns and sp_names:
                sp |= flag(df[c], lambda v: v.strip().lower() in sp_names)
        if "Campaign Name" in df.columns:
            sp |= flag(df["Campaign Name"], lambda v: is_sp_text(v) or v.strip().lower() in sp_campaigns)
        for c in ("Campaign URL", "campaign_url", "fundraiser_url", "Fundraiser URL", "Community URL", "community_url"):
            if c in df.columns:
                sp |= flag(df[c], lambda v: is_sp_text(v) or slug(v) in sp_slugs)
    except Exception as e:
        print(f"[donor directory] SP detection skipped: {e}")

    w = pd.DataFrame({
        "key": key, "name": full, "email": col("Email"), "phone": phone,
        "city": col("Billing City"), "country": col("Billing Country"),
        "amount": pd.to_numeric(df[_DIRECTORY_AMOUNT], errors="coerce").fillna(0.0) if _DIRECTORY_AMOUNT in df.columns else 0.0,
        "date": pd.to_datetime(df["Created Date (UTC)"], errors="coerce", format="mixed") if "Created Date (UTC)" in df.columns else pd.NaT,
        "platform": col("Platform"), "heading": col("Heading"), "subheading": col("Sub-Heading"), "code": col("Code"),
        "campaign": col("Campaign Name"),
        "gift_aid": col("Gift Aid (yes or no)").str.lower().isin(["yes", "true", "1", "y"]),
        "consent": col("Marketing Consent"),
        "recurring": freq.str.contains("recurr", na=False),
        "stype": stype, "sp": sp.astype(bool),
    })[usable]
    unidentified_amount = float(pd.to_numeric(df.loc[~usable, _DIRECTORY_AMOUNT], errors="coerce").fillna(0).sum()) if _DIRECTORY_AMOUNT in df.columns else 0.0
    unidentified_gifts = int((~usable).sum())
    w = w.sort_values("date", kind="stable")
    g = w.groupby("key", sort=False)
    top_heading = (w.dropna(subset=["heading"]).groupby(["key", "heading"]).size()
                   .reset_index(name="n").sort_values("n", ascending=False).drop_duplicates("key").set_index("key")["heading"])
    platforms = _joined_values(w, "platform")
    stypes = _joined_values(w[w["stype"] != ""], "stype")
    frame = pd.DataFrame({
        "name": g["name"].last(), "email": g["email"].last(), "phone": g["phone"].last(),
        "city": g["city"].last(), "country": g["country"].last(),
        "total": g["amount"].sum().round(2), "gifts": g["amount"].size(),
        "first_gift": g["date"].min(), "last_gift": g["date"].max(),
        "gift_aid": g["gift_aid"].any(), "marketing_consent": g["consent"].last(),
        "recurring_gifts": g["recurring"].sum().astype(int), "sp": g["sp"].any(),
    })
    frame["platforms"] = platforms.reindex(frame.index)
    frame["top_heading"] = top_heading.reindex(frame.index)
    frame["sponsorship_types"] = stypes.reindex(frame.index)
    frame["platform_total"] = frame["total"]
    frame["manual_total"] = 0.0
    frame["manual_records"] = 0
    dx = w[["key", "date", "amount", "heading", "subheading", "code", "campaign", "platform", "recurring", "gift_aid",
            "stype", "sp"]].copy()
    manual_rows = []
    # Manual donors from the Sponsorship Tracker: merged into the same person (by email) or listed on their own
    by_email = {}
    for idx, em in frame["email"].items():
        if isinstance(em, str) and em.strip():
            by_email.setdefault(em.strip().lower(), idx)
    for m in _manual_donor_records(comp):
        k, amt = m["key"], round(float(m.get("total_donated") or 0.0), 2)
        k = k if k in frame.index else by_email.get(k, k)
        made = pd.to_datetime(m.get("created_at"), errors="coerce")
        mtype = str(m.get("sponsorship_type") or "").strip()
        manual_rows.append({"key": k, "date": made, "amount": amt, "heading": "Sponsorship", "subheading": mtype or "Sponsorship",
                            "code": None, "campaign": f"{mtype or 'Sponsorship'} sponsorship (manual)", "platform": MANUAL_PLATFORM,
                            "recurring": False, "gift_aid": False, "stype": mtype if mtype in SPONSORSHIP_TYPES else "", "sp": False})
        if k in frame.index:
            frame.at[k, "manual_total"] += amt
            frame.at[k, "manual_records"] += 1
            frame.at[k, "total"] = round(frame.at[k, "total"] + amt, 2)
            if MANUAL_PLATFORM not in str(frame.at[k, "platforms"] or ""):
                frame.at[k, "platforms"] = ", ".join(p for p in [frame.at[k, "platforms"], MANUAL_PLATFORM] if isinstance(p, str) and p)
            if mtype in SPONSORSHIP_TYPES and mtype not in str(frame.at[k, "sponsorship_types"] or ""):
                frame.at[k, "sponsorship_types"] = ", ".join(sorted(t for t in [frame.at[k, "sponsorship_types"], mtype] if isinstance(t, str) and t))
        else:
            frame.loc[k] = {
                "name": (m.get("donor_name") or "").strip() or None, "email": (m.get("donor_email") or "").strip() or None,
                "phone": (m.get("donor_phone") or "").strip() or None, "city": None, "country": None,
                "total": amt, "gifts": 0, "first_gift": made, "last_gift": made, "gift_aid": False, "marketing_consent": None,
                "recurring_gifts": 0, "sp": False,
                "platforms": MANUAL_PLATFORM, "top_heading": m.get("sponsorship_type") or "Sponsorship",
                "sponsorship_types": mtype if mtype in SPONSORSHIP_TYPES else None,
                "platform_total": 0.0, "manual_total": amt, "manual_records": 1,
            }
    if manual_rows:
        dx = pd.concat([dx, pd.DataFrame(manual_rows)], ignore_index=True)
    frame["avg_gift"] = (frame["platform_total"] / frame["gifts"].where(frame["gifts"] > 0)).round(2).fillna(0.0)
    frame["recurring"] = frame["recurring_gifts"] > 0
    frame["tier"] = frame["total"].map(classify_donor_amount)
    # Sponsorship allocations each donor is part of (Sponsorship Tracker), by email
    frame["allocations"] = 0
    try:
        conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=10)
        try:
            alloc = dict(conn.execute("""SELECT LOWER(TRIM(d.donor_email)), COUNT(DISTINCT d.allocation_id)
                                         FROM sponsorship_allocation_donors d JOIN sponsorship_allocations a ON a.id = d.allocation_id
                                         WHERE LOWER(a.company_id) = ? AND COALESCE(d.donor_email, '') LIKE '%@%'
                                         GROUP BY 1""", (comp,)).fetchall())
        finally:
            conn.close()
        em = frame["email"].fillna("").astype(str).str.strip().str.lower()
        frame["allocations"] = em.map(alloc).fillna(0).astype(int)
    except Exception as e:
        print(f"[donor directory] allocation counts skipped: {e}")
    frame = frame.reset_index().rename(columns={"index": "donor_id", "key": "donor_id"})
    frame["search"] = (frame["donor_id"].fillna("") + " " + frame["name"].fillna("").str.lower() + " " +
                       frame["email"].fillna("").str.lower() + " " + frame["phone"].fillna("").str.replace(r"[^0-9]", "", regex=True))
    frame.attrs["unidentified"] = {"gifts": unidentified_gifts, "amount": round(unidentified_amount, 2)}
    _DIRECTORY_CACHE[comp] = (token, frame, dx)
    return frame, dx


def _joined_values(w: pd.DataFrame, column: str) -> pd.Series:
    """Per donor, the distinct values of a low-cardinality column joined with ', ' (alphabetical), vectorised."""
    sub = w.dropna(subset=[column])
    sub = sub[sub[column].astype(str).str.strip() != ""]
    if sub.empty:
        return pd.Series(dtype=object)
    present = pd.crosstab(sub["key"], sub[column].astype(str)) > 0
    out = pd.Series("", index=present.index, dtype=object)
    for value in sorted(present.columns):
        has = present[value]
        out = out.where(~has, out.where(out == "", out + ", ") + value)
    return out


def _as_list(v) -> List[str]:
    if v is None or v == "":
        return []
    if isinstance(v, (list, tuple, set)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v).split(",") if x.strip()]


def apply_segment(frame: pd.DataFrame, dx: pd.DataFrame, seg: Dict[str, Any]) -> pd.DataFrame:
    """Donors matching a segment. Gift rules (date range, cause, sponsorship type, campaign, platform, amount,
    recurring, Gift Aid, SP) pick the gifts that count - a donor matches if at least one gift passes ALL of them
    (and, if set, their matching gifts reach min_matched_gifts / min_matched_total). Donor rules (tier, lifetime
    total, gift count, average, recurring donor, allocations, contact, country, dates) then narrow the donors.
    Lists mean "any of"; different rules combine with AND."""
    seg = seg or {}
    f = frame
    gift_rules = ("date_from", "date_to", "headings", "subheadings", "codes", "campaign", "platforms", "sponsorship_types",
                  "frequency", "gift_aid_gift", "sp_gift", "min_amount", "max_amount", "min_matched_gifts", "min_matched_total")
    if any(seg.get(k) not in (None, "", [], "any") for k in gift_rules) and not dx.empty:
        d = dx
        if seg.get("date_from"):
            d = d[d["date"] >= pd.to_datetime(seg["date_from"], errors="coerce")]
        if seg.get("date_to"):
            d = d[d["date"] < pd.to_datetime(seg["date_to"], errors="coerce") + pd.Timedelta(days=1)]
        for k, c in (("headings", "heading"), ("subheadings", "subheading"), ("codes", "code"), ("platforms", "platform"),
                     ("sponsorship_types", "stype")):
            vals = [v.lower() for v in _as_list(seg.get(k))]
            if vals:
                d = d[d[c].fillna("").astype(str).str.strip().str.lower().isin(vals)]
        if seg.get("campaign"):
            d = d[d["campaign"].fillna("").str.lower().str.contains(re.escape(str(seg["campaign"]).lower()), na=False)]
        if seg.get("frequency") in ("recurring", "one-off"):
            d = d[d["recurring"] == (seg["frequency"] == "recurring")]
        if seg.get("gift_aid_gift") in ("yes", "no"):
            d = d[d["gift_aid"] == (seg["gift_aid_gift"] == "yes")]
        if seg.get("sp_gift") in ("yes", "no"):
            d = d[d["sp"] == (seg["sp_gift"] == "yes")]
        if seg.get("min_amount") not in (None, ""):
            d = d[d["amount"] >= float(seg["min_amount"])]
        if seg.get("max_amount") not in (None, ""):
            d = d[d["amount"] <= float(seg["max_amount"])]
        agg = d.groupby("key")["amount"].agg(["size", "sum"])
        if seg.get("min_matched_gifts") not in (None, ""):
            agg = agg[agg["size"] >= int(seg["min_matched_gifts"])]
        if seg.get("min_matched_total") not in (None, ""):
            agg = agg[agg["sum"] >= float(seg["min_matched_total"])]
        f = f[f["donor_id"].isin(agg.index)].copy()
        f["matched_gifts"] = f["donor_id"].map(agg["size"]).fillna(0).astype(int)
        f["matched_total"] = f["donor_id"].map(agg["sum"]).fillna(0).round(2)
    tiers = _as_list(seg.get("tiers"))
    if tiers:
        f = f[f["tier"].isin(tiers)]
    for k, c, op in (("min_total", "total", "ge"), ("max_total", "total", "le"), ("min_gifts", "gifts", "ge"),
                     ("max_gifts", "gifts", "le"), ("min_avg", "avg_gift", "ge"), ("max_avg", "avg_gift", "le"),
                     ("min_allocations", "allocations", "ge")):
        if seg.get(k) not in (None, ""):
            v = float(seg[k])
            f = f[f[c] >= v] if op == "ge" else f[f[c] <= v]
    yn = lambda k: seg.get(k) in ("yes", "no")  # noqa: E731
    if yn("recurring"):
        f = f[f["recurring"] == (seg["recurring"] == "yes")]
    if yn("sp"):
        f = f[f["sp"] == (seg["sp"] == "yes")]
    if yn("gift_aid"):
        f = f[f["gift_aid"] == (seg["gift_aid"] == "yes")]
    if yn("has_email"):
        has = f["email"].fillna("").astype(str).str.contains("@")
        f = f[has == (seg["has_email"] == "yes")]
    if yn("marketing_consent"):
        ok = f["marketing_consent"].fillna("").astype(str).str.lower().isin(["yes", "true", "1", "y", "opted in"])
        f = f[ok == (seg["marketing_consent"] == "yes")]
    if yn("manual"):
        f = f[(f["manual_records"] > 0) == (seg["manual"] == "yes")]
    countries = [c.lower() for c in _as_list(seg.get("countries"))]
    if countries:
        f = f[f["country"].fillna("").str.lower().isin(countries)]
    if seg.get("city"):
        f = f[f["city"].fillna("").str.lower().str.contains(re.escape(str(seg["city"]).lower()), na=False)]
    for k, c, lo in (("first_gift_from", "first_gift", True), ("first_gift_to", "first_gift", False),
                     ("last_gift_from", "last_gift", True), ("last_gift_to", "last_gift", False)):
        if seg.get(k):
            t = pd.to_datetime(seg[k], errors="coerce")
            f = f[f[c] >= t] if lo else f[f[c] < t + pd.Timedelta(days=1)]
    if seg.get("search"):
        q = str(seg["search"]).strip().lower()
        digits = re.sub(r"[^0-9]", "", q)
        m = f["search"].str.contains(re.escape(q), na=False)
        if len(digits) >= 5:
            m |= f["search"].str.contains(digits, na=False)
        f = f[m]
    return f


@router.get("/segment-options")
def get_segment_options(company_id: Optional[str] = Query("rethink")):
    """Values the segment builder offers (causes, codes, platforms, countries, tiers, sponsorship types)."""
    comp = str(company_id or "rethink").strip().lower()
    frame, dx = _directory_data(comp)
    if frame.empty:
        return {"headings": [], "subheadings": [], "codes": [], "platforms": [], "countries": [], "tiers": [],
                "sponsorship_types": list(SPONSORSHIP_TYPES)}

    def counts(series, top=None):
        vc = series.dropna().astype(str).str.strip()
        vc = vc[(vc != "") & (~vc.str.lower().isin(["nan", "none", "unassigned", "n/a"]))].value_counts()
        if top:
            vc = vc.head(top)
        return [{"value": k, "count": int(v)} for k, v in vc.items()]

    sub = dx.dropna(subset=["subheading"])
    sub = sub[sub["subheading"].astype(str).str.strip() != ""]
    subs = (sub.groupby(["subheading", "heading"]).size().reset_index(name="n").sort_values("n", ascending=False))
    return {
        "headings": counts(dx["heading"]),
        "subheadings": [{"value": r.subheading, "heading": r.heading, "count": int(r.n)} for r in subs.itertuples()],
        "codes": counts(dx["code"], 400),
        "platforms": counts(dx["platform"]),
        "countries": counts(frame["country"], 80),
        "tiers": ["Low End", "Medium Low", "Medium", "High", "Super High"],
        "sponsorship_types": list(SPONSORSHIP_TYPES),
    }


@router.get("/directory")
def get_donor_directory(
    company_id: Optional[str] = Query("rethink"),
    search: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    gift_aid: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    min_total: Optional[float] = Query(None),
    last_gift_from: Optional[str] = Query(None),
    last_gift_to: Optional[str] = Query(None),
    tier: Optional[str] = Query(None),
    recurring: Optional[str] = Query(None),
    sp: Optional[str] = Query(None),
    segment: Optional[str] = Query(None, description="JSON segment (see apply_segment)"),
    sort_by: str = Query("total"),
    sort_dir: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """One row per donor with lifetime totals; clicking a donor uses donor_id with /profile and /history."""
    comp = str(company_id or "rethink").strip().lower()
    frame, dx = _directory_data(comp)
    if frame.empty:
        return {"total_donors": 0, "page": 1, "page_size": page_size, "total_pages": 1, "summary": {}, "donors": []}
    seg: Dict[str, Any] = {}
    if segment:
        try:
            import json as _json
            seg = _json.loads(segment) or {}
        except ValueError:
            raise HTTPException(status_code=400, detail="segment must be JSON")
    if tier:
        seg.setdefault("tiers", _as_list(tier))
    if recurring in ("yes", "no"):
        seg.setdefault("recurring", recurring)
    if sp in ("yes", "no"):
        seg.setdefault("sp", sp)
    f = apply_segment(frame, dx, seg) if seg else frame
    if search and search.strip():
        q = search.strip().lower()
        digits = re.sub(r"[^0-9]", "", q)
        m = f["search"].str.contains(re.escape(q), na=False)
        if len(digits) >= 5:
            m |= f["search"].str.contains(digits, na=False)
        f = f[m]
    if platform and platform.lower() != "all":
        f = f[f["platforms"].fillna("").str.lower().str.contains(re.escape(platform.lower()))]
    if source == "manual":
        f = f[f["manual_records"] > 0]
    elif source == "platform":
        f = f[f["gifts"] > 0]
    if gift_aid in ("yes", "no"):
        f = f[f["gift_aid"] == (gift_aid == "yes")]
    if min_total is not None:
        f = f[f["total"] >= float(min_total)]
    if last_gift_from:
        f = f[f["last_gift"] >= pd.to_datetime(last_gift_from, errors="coerce")]
    if last_gift_to:
        f = f[f["last_gift"] < pd.to_datetime(last_gift_to, errors="coerce") + pd.Timedelta(days=1)]
    column = {"total": "total", "gifts": "gifts", "last_gift": "last_gift", "first_gift": "first_gift", "name": "name",
              "avg_gift": "avg_gift", "recurring_gifts": "recurring_gifts", "allocations": "allocations",
              "matched_total": "matched_total" if "matched_total" in f.columns else "total"}.get(sort_by, "total")
    f = f.sort_values(column, ascending=(sort_dir == "asc"), na_position="last", kind="stable")
    total = len(f)
    pages = max(1, math.ceil(total / page_size))
    page = min(page, pages)
    rows = f.iloc[(page - 1) * page_size: page * page_size].drop(columns=["search"]).copy()
    for c in ("first_gift", "last_gift"):
        rows[c] = rows[c].dt.strftime("%Y-%m-%d")
    rows = rows.astype(object).where(rows.notna(), None)
    # Unfiltered view: include gifts that have no donor details, so the total equals the CRM's total raised.
    unfiltered = f is frame or len(f) == len(frame)
    unidentified = frame.attrs.get("unidentified", {"gifts": 0, "amount": 0.0}) if unfiltered else {"gifts": 0, "amount": 0.0}
    return {
        "total_donors": total, "page": page, "page_size": page_size, "total_pages": pages,
        "summary": {"donors": total, "total_raised": round(float(f["platform_total"].sum()) + unidentified["amount"], 2),
                    "manual_total": round(float(f["manual_total"].sum()), 2), "manual_donors": int((f["manual_records"] > 0).sum()),
                    "gifts": int(f["gifts"].sum()) + unidentified["gifts"],
                    "unidentified_gifts": unidentified["gifts"], "unidentified_amount": unidentified["amount"],
                    "gift_aid_donors": int(f["gift_aid"].sum()),
                    "average_per_donor": round(float(f["total"].mean()), 2) if total else 0.0,
                    "average_gift": round(float(f["platform_total"].sum()) / max(int(f["gifts"].sum()), 1), 2),
                    "recurring_donors": int(f["recurring"].sum()), "sp_donors": int(f["sp"].sum()),
                    "tiers": {k: int(v) for k, v in f["tier"].value_counts().items()},
                    "matched_total": round(float(f["matched_total"].sum()), 2) if "matched_total" in f.columns else None},
        "donors": rows.to_dict(orient="records"),
    }


@router.get("/donation/{donation_id:path}")
def get_donation_detail(donation_id: str, company_id: Optional[str] = Query(None)):
    """Every field of one donation (or of one Sponsorship Tracker manual record), within the requested charity only."""
    comp = str(company_id or "").strip().lower()
    did = str(donation_id or "").strip()
    if not did:
        raise HTTPException(status_code=400, detail="Donation ID is required.")
    df = load_data(company_id=comp if comp and comp != "all" else None)
    rows = pd.DataFrame()
    if df is not None and not df.empty and "Donation ID" in df.columns:
        ids = df["Donation ID"].astype(str).str.strip()
        rows = df.loc[ids == did]
        if rows.empty and did.endswith(".0"):
            rows = df.loc[ids == did[:-2]]
    if rows.empty:
        manual = [m for m in _manual_donor_records(comp or "all") if str(m["id"]) == did]
        if not manual:
            raise HTTPException(status_code=404, detail=f"Donation '{did}' not found.")
        m = manual[0]
        rec = _manual_history_rows([m], _DIRECTORY_AMOUNT)[0]
        rec.update({"Display Name": m.get("donor_name") or "", "Email": m.get("donor_email") or "",
                    "Phone Number": m.get("donor_phone") or "", "Classification": m.get("classification") or "",
                    "company_id": m.get("company_id") or comp})
        return {"donation": rec, "duplicates": 0, "manual": True}

    def plain(v):
        if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return None
        if isinstance(v, pd.Timestamp):
            return None if pd.isna(v) else v.isoformat()
        if hasattr(v, "item"):
            try:
                v = v.item()
            except (ValueError, AttributeError):
                pass
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        text = str(v).strip()
        return None if text.lower() in ("", "nan", "none", "null", "nat", "n/a") else v

    rec = {str(k): plain(v) for k, v in rows.iloc[0].to_dict().items()}
    rec = {k: v for k, v in rec.items() if v is not None}
    return {"donation": rec, "duplicates": int(len(rows) - 1), "manual": False}


@router.get("/history")
def get_donor_history_paginated(
    donor_id: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    heading: Optional[str] = Query(None),
    subheading: Optional[str] = Query(None),
):
    """Paginated transaction history for a donor to handle large transaction counts smoothly.
    Optional filters (applied before paging): date range, cause heading / sub-heading."""
    comp = str(company_id or "").strip().lower()
    df = load_data(company_id=comp if comp and comp != "all" else None)
    match_mask = _get_donor_matching_mask(df, donor_id) if not df.empty else pd.Series(False, index=df.index)
    donor_txns = df.loc[match_mask] if not df.empty else pd.DataFrame()

    # No fallback to other charities: a donor that isn't in the requested charity is not found.
    # (company_id omitted/'all' already searches every charity, and the API guard only allows that
    # for accounts with access to all of them.)

    manual = _manual_for_identity(comp or "all", donor_id, donor_txns)
    if donor_txns.empty and not manual:
        return {"total_records": 0, "page": 1, "page_size": page_size, "total_pages": 1, "records": []}
    if donor_txns.empty:
        rows = sorted(_manual_history_rows(manual, "Total Online Donations Net Amount in Settled Currency"),
                      key=lambda r: r["Created Date (UTC)"], reverse=True)
        return {"total_records": len(rows), "page": 1, "page_size": page_size, "total_pages": 1, "records": rows[:page_size]}

    col_amount = "Total Online Donations Net Amount in Settled Currency"
    if col_amount not in df.columns:
        col_amount = "Donation Amount in Project Currency (May be approx.)"

    timeline_cols = [c for c in [
        "Created Date (UTC)", "Campaign Name", "Heading", "Sub-Heading", 
        "Donation Currency (DC)", "Donation Amount (in Donation Currency)", 
        col_amount, "Payment Frequency", "Platform", "Source",
        # full detail for the donor panel
        "Donation ID", "Code", "Department", "Office", "Country", "Programme Fund", "Fund Code", "Zakat Eligibility",
        "Giving Level Title", "fundraiser_name", "Status", "Transaction Type", "Payment Type",
        "Total Online Donation Gross Amount in Settled Currency", "Total Processing Fees Paid by CC In Settled Currency",
        "Settlement Currency", "Gift Aid (yes or no)", "Zakat (yes or no)", "Anonymous or Public", "Comments",
    ] if c in donor_txns.columns]
    timeline_cols = list(dict.fromkeys(timeline_cols))

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
    if manual:  # records added by hand in the Sponsorship Tracker sit alongside the platform donations
        timeline_df = pd.concat([timeline_df, pd.DataFrame(_manual_history_rows(manual, col_amount))], ignore_index=True)
        timeline_df = timeline_df.sort_values("Created Date (UTC)", ascending=False, kind="stable").fillna("N/A")
    if date_from or date_to:
        d = pd.to_datetime(timeline_df["Created Date (UTC)"], errors="coerce")
        keep = d.notna()
        if date_from:
            keep &= d >= pd.to_datetime(date_from, errors="coerce")
        if date_to:
            keep &= d < pd.to_datetime(date_to, errors="coerce") + pd.Timedelta(days=1)
        timeline_df = timeline_df[keep]
    for val, colname in ((heading, "Heading"), (subheading, "Sub-Heading")):
        if val and colname in timeline_df.columns:
            timeline_df = timeline_df[timeline_df[colname].astype(str).str.strip().str.lower() == str(val).strip().lower()]
    filtered_net = round(float(pd.to_numeric(timeline_df[col_amount], errors="coerce").fillna(0).sum()), 2) if col_amount in timeline_df.columns else 0.0

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
        "records": records,
        "filtered_net": filtered_net,
    }


@router.get("/campaigns")
@cached(scopes=["donations", "classification"], ttl=21600)
def get_campaigns_list(company_id: Optional[str] = Query("rethink")):
    """Returns sorted unique list of campaign names for fast dropdown filtering in Data Explorer."""
    comp = str(company_id or "rethink").lower().strip()
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        cur = conn.cursor()
        where_clause = " WHERE LOWER(COALESCE(company_id, 'rethink')) = ? AND [Campaign Name] IS NOT NULL AND TRIM([Campaign Name]) != ''" if comp != "all" else " WHERE [Campaign Name] IS NOT NULL AND TRIM([Campaign Name]) != ''"
        params = [comp] if comp != "all" else []
        cur.execute(f"""
            SELECT DISTINCT [Campaign Name]
            FROM donations
            {where_clause}
            ORDER BY [Campaign Name] COLLATE NOCASE ASC, [Campaign Name] DESC
        """, params)
        campaigns = [r[0].strip() for r in cur.fetchall() if r[0] and str(r[0]).strip()]
        conn.close()
        return {"campaigns": campaigns}
    except Exception as e:
        df = load_data(company_id=company_id)
        if not df.empty and "Campaign Name" in df.columns:
            campaigns = sorted([str(c).strip() for c in df["Campaign Name"].dropna().unique() if str(c).strip()])
            return {"campaigns": campaigns}
        return {"campaigns": []}


# ---------------------------------------------------------------------------------------------------------------
# Manual / offline donations and donor-level edits (permission: super admin or "can edit donors")
# ---------------------------------------------------------------------------------------------------------------
MANUAL_SOURCE = "Manual Entry"
NET_COL = "Total Online Donations Net Amount in Settled Currency"
GROSS_COL = "Total Online Donation Gross Amount in Settled Currency"
FEES_COL = "Total Processing Fees Paid by CC In Settled Currency"


def _require_editor(current_user: Dict[str, Any]) -> None:
    if not (current_user.get("role") == "super_admin" or current_user.get("can_edit_donors")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Your account can't add or edit donor records (ask a super admin for 'Edit donors').")


def _editable_company(company_id: Optional[str]) -> str:
    comp = str(company_id or "").strip().lower()
    if not comp or comp == "all":
        raise HTTPException(status_code=400, detail="Choose a charity (not 'All') to add or edit records.")
    return comp


def _refresh_copy(comp: str, donation_ids: List[str]) -> None:
    """SQLite is the source of truth: bring the dashboards' copy level for exactly these rows, now."""
    try:
        from core.donations_reconcile import reconcile
        reconcile(deep=False, apply=True, require_confirmation=False, only_keys={(comp, str(d)) for d in donation_ids})
    except Exception as e:
        print(f"[manual donation] copy refresh deferred to the background reconciler: {e}")
    try:
        from backend.api.events import broadcast_event_sync
        broadcast_event_sync("DONORS_UPDATED", {"source": "manual_edit", "company_id": comp, "count": len(donation_ids)})
    except Exception:
        pass


class ManualDonationRequest(BaseModel):
    company_id: str
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    city: str = ""
    postcode: str = ""
    country: str = ""
    amount: float
    currency: str = "GBP"
    settled_amount_gbp: Optional[float] = None   # required when the gift wasn't in GBP
    fee: float = 0.0
    date: str                                    # YYYY-MM-DD
    payment_type: str = "Cash"                   # Cash / Bank transfer / Cheque / Card terminal / Standing order / Other
    frequency: str = "One-Time Payment"          # or "Recurring Payment"
    campaign_name: str = ""
    giving_level: str = ""
    code: str = ""
    gift_aid: bool = False
    zakat: bool = False
    anonymous: bool = False
    marketing_consent: Optional[bool] = None
    platform: str = "Offline / Manual"
    fundraiser_name: str = ""
    notes: str = ""
    reference: str = ""                          # e.g. bank reference / receipt number


@router.post("/donations")
def create_manual_donation(payload: ManualDonationRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Adds one offline/manual donation to the CRM. It behaves like any other gift: Donors page, donor panel,
    classifications (from its Code), fundraisers and - when the Code/campaign is a sponsorship (ORP, HUF, WID, SUR) -
    the Sponsorship Tracker."""
    import uuid as _uuid
    _require_editor(current_user)
    comp = _editable_company(payload.company_id)
    if payload.amount is None or float(payload.amount) == 0:
        raise HTTPException(status_code=400, detail="Enter the donation amount.")
    when = pd.to_datetime(payload.date, errors="coerce")
    if pd.isna(when):
        raise HTTPException(status_code=400, detail="Enter a valid date (YYYY-MM-DD).")
    currency = (payload.currency or "GBP").strip().upper()[:3]
    settled = float(payload.amount) if currency == "GBP" else payload.settled_amount_gbp
    if settled is None:
        raise HTTPException(status_code=400, detail="For a non-GBP gift, enter the amount received in GBP.")
    email = (payload.email or "").strip()
    name = f"{payload.first_name} {payload.last_name}".strip()
    if not email and not name:
        raise HTTPException(status_code=400, detail="Enter the donor's name or email.")
    code = (payload.code or "").strip().upper()
    cls: Dict[str, Any] = {}
    if code and code.lower() not in ("unassigned", "nan", "none", "n/a"):
        cls = get_code_to_classification_map(company_id=comp).get(code.lower()) or {}
        if not cls:
            raise HTTPException(status_code=400, detail=f"'{code}' is not one of {comp}'s project codes.")
    donor_id = email.lower() if "@" in email else f"name:{name.lower()}"
    did = f"MAN-{_uuid.uuid4().hex[:10].upper()}"
    fee = round(float(payload.fee or 0.0), 2)
    net = round(float(settled) - fee, 2)

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    try:
        table_cols = [r[1] for r in conn.execute("PRAGMA table_info(donations)")]
        prior = conn.execute(f'SELECT COALESCE(SUM("{NET_COL}"), 0) FROM donations WHERE LOWER(company_id) = ? AND LOWER("Donor ID") = ?',
                             (comp, donor_id)).fetchone()[0] or 0.0
        ltv = round(float(prior) + net, 2)
        rec = {
            "Donation ID": did, "Created Date (UTC)": when.strftime("%Y-%m-%d"), "Created Time (UTC)": "00:00:00",
            "Settled Date (UTC)": when.strftime("%Y-%m-%d"), "Created At": when.strftime("%Y-%m-%d 00:00:00"),
            "_parsed_date": when.strftime("%Y-%m-%d"), "Status": "COMPLETED", "Transaction Type": "Donation",
            "Offline or online donation": "offline", "First Name": payload.first_name.strip(), "Last Name": payload.last_name.strip(),
            "Display Name": "Anonymous" if payload.anonymous else name, "Billing Name": name, "Email": email,
            "Email (for tax receipt)": email, "Phone Number": payload.phone.strip(), "Billing Address": payload.address.strip(),
            "Billing City": payload.city.strip(), "Billing Zip": payload.postcode.strip(), "Billing Country": payload.country.strip(),
            "Marketing Consent": None if payload.marketing_consent is None else ("yes" if payload.marketing_consent else "no"),
            "Gift Aid (yes or no)": "Yes" if payload.gift_aid else "No", "Zakat (yes or no)": "Yes" if payload.zakat else "No",
            "Anonymous or Public": "Anonymous" if payload.anonymous else "Public",
            "Donation Currency (DC)": currency, "Currency": currency, "Project Currency": currency, "Settlement Currency": "GBP",
            "Donation Amount (in Donation Currency)": str(float(payload.amount)),
            "Donation Amount in Project Currency (May be approx.)": str(float(payload.amount)), "Amount": float(payload.amount),
            GROSS_COL: str(round(float(settled), 2)), FEES_COL: fee, NET_COL: net, "fee_amount": str(fee),
            "Campaign Name": payload.campaign_name.strip(), "Giving Level Title": payload.giving_level.strip(),
            "Has Giving Level": "Yes" if payload.giving_level.strip() else "No", "fundraiser_name": payload.fundraiser_name.strip(),
            "Comments": payload.notes.strip(), "Payment Type": payload.payment_type.strip() or "Cash",
            "Payment Frequency": payload.frequency or "One-Time Payment", "Platform": (payload.platform or "Offline / Manual").strip(),
            "Source": MANUAL_SOURCE, "Customer Ref": payload.reference.strip(), "Donor ID": donor_id,
            "Total LTV": ltv, "Lifetime Donor Classification": classify_donor_amount(ltv),
            "Transaction Donor Classification": classify_donor_amount(net),
            "Code": code or "Unassigned", "New Code": code or "Unassigned",
            "Heading": cls.get("Heading") or cls.get("Department") or "", "Sub-Heading": cls.get("Sub-Heading") or cls.get("Office") or "",
            "Department": cls.get("Department") or "", "Office": cls.get("Office") or "", "Portfolio": cls.get("Portfolio") or "",
            "Country": cls.get("Country") or "", "Target Country": cls.get("Country") or "",
            "Programme Fund": cls.get("Programme Fund") or "", "Fund Code": cls.get("Fund Code") or "",
            "Zakat Eligibility": cls.get("Zakat Eligibility") or "", "Payout Settled": "No", "company_id": comp,
            "Number of Donors": 1.0,
        }
        cols = [c for c in table_cols if c in rec]
        with conn:
            conn.execute(f'INSERT INTO donations ({", ".join(chr(34) + c + chr(34) for c in cols)}) VALUES ({", ".join("?" * len(cols))})',
                         [rec[c] for c in cols])
    finally:
        conn.close()
    _refresh_copy(comp, [did])
    try:
        from core.event_log import log_event
        log_event("donation.manual_added", category="data", company_id=comp, actor=current_user.get("email"),
                  donation_id=did, amount=net, code=code or "Unassigned",
                  message=f"Manual donation {did} £{net:,.2f} added by {current_user.get('email')}")
    except Exception:
        pass
    return {"success": True, "donation_id": did, "donor_id": donor_id, "net": net, "code": code or "Unassigned"}


@router.delete("/donations/{donation_id}")
def delete_manual_donation(donation_id: str, company_id: str = Query(...), current_user: Dict[str, Any] = Depends(get_current_user)):
    """Removes a donation that was added by hand (platform gifts can only be edited, never deleted here)."""
    _require_editor(current_user)
    comp = _editable_company(company_id)
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    try:
        row = conn.execute('SELECT Source FROM donations WHERE LOWER(company_id) = ? AND "Donation ID" = ?', (comp, donation_id)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Donation not found for this charity.")
        if (row[0] or "") != MANUAL_SOURCE:
            raise HTTPException(status_code=400, detail="Only donations added by hand can be deleted. Platform donations can be edited instead.")
        with conn:
            conn.execute('DELETE FROM donations WHERE LOWER(company_id) = ? AND "Donation ID" = ? AND Source = ?', (comp, donation_id, MANUAL_SOURCE))
    finally:
        conn.close()
    try:
        from core.donations_reconcile import reconcile
        reconcile(deep=False, apply=True, require_confirmation=False, only_keys=set())  # drops the row from the copy
    except Exception as e:
        print(f"[manual donation] copy refresh deferred: {e}")
    try:
        from core.event_log import log_event
        log_event("donation.manual_deleted", category="data", company_id=comp, actor=current_user.get("email"),
                  donation_id=donation_id, message=f"Manual donation {donation_id} deleted by {current_user.get('email')}")
    except Exception:
        pass
    return {"success": True, "donation_id": donation_id}


_DONOR_FIELDS = {
    "first_name": "First Name", "last_name": "Last Name", "email": "Email", "phone": "Phone Number",
    "address": "Billing Address", "city": "Billing City", "postcode": "Billing Zip", "country": "Billing Country",
    "marketing_consent": "Marketing Consent", "anonymous": "Anonymous or Public",
}


class DonorUpdateRequest(BaseModel):
    company_id: str
    donor_id: str
    fields: Dict[str, Any]


@router.post("/update-donor")
def update_donor(payload: DonorUpdateRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Edits a donor's details on every one of their gifts in this charity (and on their Sponsorship Tracker records)."""
    _require_editor(current_user)
    comp = _editable_company(payload.company_id)
    key = str(payload.donor_id or "").strip().lower()
    if not key:
        raise HTTPException(status_code=400, detail="donor_id is required")
    updates = {}
    for k, v in (payload.fields or {}).items():
        if k not in _DONOR_FIELDS:
            raise HTTPException(status_code=400, detail=f"'{k}' can't be edited here.")
        if k == "marketing_consent" and isinstance(v, bool):
            v = "yes" if v else "no"
        if k == "anonymous" and isinstance(v, bool):
            v = "Anonymous" if v else "Public"
        updates[_DONOR_FIELDS[k]] = "" if v is None else str(v).strip()
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    new_email = updates.get("Email", "").lower()
    if "Email" in updates and new_email and "@" not in new_email:
        raise HTTPException(status_code=400, detail="That email address isn't valid.")

    if key.startswith("manual:"):  # a Sponsorship Tracker manual donor with no CRM gifts
        mid = key.split(":", 1)[1]
        sets = {"donor_email": updates.get("Email"), "donor_phone": updates.get("Phone Number")}
        if "First Name" in updates or "Last Name" in updates:
            sets["donor_name"] = f"{updates.get('First Name', '')} {updates.get('Last Name', '')}".strip()
        sets = {k: v for k, v in sets.items() if v is not None}
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
        try:
            with conn:
                n = conn.execute(f"UPDATE sponsorship_manual_donors SET {', '.join(k + ' = ?' for k in sets)}, updated_at = CURRENT_TIMESTAMP "
                                 "WHERE LOWER(id) = ? AND LOWER(company_id) = ?", (*sets.values(), mid, comp)).rowcount
        finally:
            conn.close()
        if not n:
            raise HTTPException(status_code=404, detail="Donor not found for this charity.")
        return {"success": True, "updated_gifts": 0, "updated_manual_records": n}

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    try:
        rows = conn.execute('SELECT "Donation ID", LOWER(COALESCE(Email, "")) FROM donations WHERE LOWER(company_id) = ? '
                            'AND (LOWER("Donor ID") = ? OR LOWER(Email) = ?)', (comp, key, key)).fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="Donor not found for this charity.")
        ids = [r[0] for r in rows if r[0]]
        sets = dict(updates)
        if new_email and new_email != key:
            sets["Donor ID"] = new_email
            sets["Email (for tax receipt)"] = updates["Email"]
        with conn:
            conn.execute(f'UPDATE donations SET {", ".join(chr(34) + c + chr(34) + " = ?" for c in sets)} '
                         'WHERE LOWER(company_id) = ? AND (LOWER("Donor ID") = ? OR LOWER(Email) = ?)',
                         (*sets.values(), comp, key, key))
            if new_email and new_email != key:
                old_emails = {r[1] for r in rows if r[1]} | {key}
                for old in old_emails:
                    for t in ("sponsorship_allocations", "sponsorship_allocation_donors"):
                        try:
                            conn.execute(f"UPDATE {t} SET donor_email = ?, donor_id = ? WHERE company_id = ? AND (LOWER(donor_email) = ? OR LOWER(donor_id) = ?)",
                                         (new_email, new_email, comp, old, old))
                        except sqlite3.OperationalError:
                            pass
                    try:
                        conn.execute("UPDATE sponsorship_manual_donors SET donor_email = ? WHERE LOWER(company_id) = ? AND LOWER(donor_email) = ?",
                                     (updates["Email"], comp, old))
                    except sqlite3.OperationalError:
                        pass
    finally:
        conn.close()
    _refresh_copy(comp, ids)
    try:
        from core.event_log import log_event
        log_event("donor.updated", category="data", company_id=comp, actor=current_user.get("email"), donor_id=key,
                  fields=sorted(updates), gifts=len(ids), message=f"Donor {key} updated on {len(ids)} gift(s) by {current_user.get('email')}")
    except Exception:
        pass
    return {"success": True, "updated_gifts": len(ids), "donor_id": new_email or key}
