from fastapi import APIRouter, Query, HTTPException, Response
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import sqlite3
import pandas as pd
import numpy as np
import math
import os
import io
import re
from datetime import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from core.data_processor import (
    LOCAL_DB_PATH,
    PAYOUTS_PARQUET_PATH,
    PAYSUITE_PAYOUTS_PARQUET_PATH,
    PARQUET_PATH,
    load_data,
    load_payouts_data,
    load_paysuite_payouts_data,
    fix_mojibake,
    get_code_to_classification_map,
    sync_matrix_classifications_to_donors,
    get_classification_matrix,
    get_paysuite_classification_matrix,
    save_classification_matrix,
    save_paysuite_classification_matrix,
    invalidate_data_cache,
    invalidate_payouts_cache as _core_invalidate_payouts_cache,
    invalidate_paysuite_payouts_cache as _core_invalidate_paysuite_payouts_cache
)
from core.database import get_db_connection, _DB_LOCK

router = APIRouter(prefix="/api/payouts", tags=["Payouts Reconciliation"])


_CLASSIFIED_PAYOUTS_CACHE = {}
_CLASSIFIED_PAYSUITE_CACHE = {}
_CLASSIFICATION_MATRIX_CACHE = {}
_PAYSUITE_MATRIX_CACHE = {}

def invalidate_payouts_cache(company_id: Optional[str] = None):
    """Invalidates the in-memory cache for payout reconciliation."""
    global _CLASSIFIED_PAYOUTS_CACHE, _CLASSIFIED_PAYSUITE_CACHE, _CLASSIFICATION_MATRIX_CACHE, _PAYSUITE_MATRIX_CACHE
    if company_id:
        cid = str(company_id).strip().lower()
        _CLASSIFIED_PAYOUTS_CACHE.pop(cid, None)
        _CLASSIFIED_PAYSUITE_CACHE.pop(cid, None)
        _CLASSIFICATION_MATRIX_CACHE.pop(cid, None)
        _PAYSUITE_MATRIX_CACHE.pop(cid, None)
    else:
        _CLASSIFIED_PAYOUTS_CACHE = {}
        _CLASSIFIED_PAYSUITE_CACHE = {}
        _CLASSIFICATION_MATRIX_CACHE = {}
        _PAYSUITE_MATRIX_CACHE = {}
    _core_invalidate_payouts_cache()
    _core_invalidate_paysuite_payouts_cache()

def clean_mojibake_text(text: Any) -> str:
    """Repairs common UTF-8 mojibake, curly quotes, and unwanted encoding artifacts."""
    return fix_mojibake(text)

def _clean_str(val: Any, default: str = "") -> str:
    if hasattr(val, 'default'):
        val = val.default
    if val is None or val is ...:
        return default
    return str(val).strip()

def _get_classification_matrix_dict(platform: str = "launchgood", company_id: Optional[str] = "rethink") -> Dict[Any, Dict[str, str]]:
    global _CLASSIFICATION_MATRIX_CACHE, _PAYSUITE_MATRIX_CACHE
    p_clean = _clean_str(platform, "launchgood").lower()
    cid = _clean_str(company_id, "rethink").lower()
    
    if p_clean == "paysuite":
        if cid in _PAYSUITE_MATRIX_CACHE:
            return _PAYSUITE_MATRIX_CACHE[cid]
        try:
            conn = get_db_connection(timeout=10.0)
            if cid == "all":
                matrix_df = pd.read_sql_query("""
                    SELECT campaign_name, heading, sub_heading, country, code, zakat_eligibility, is_primary 
                    FROM paysuite_classifications
                """, conn)
            else:
                matrix_df = pd.read_sql_query("""
                    SELECT campaign_name, heading, sub_heading, country, code, zakat_eligibility, is_primary 
                    FROM paysuite_classifications WHERE company_id = ?
                """, conn, params=(cid,))
            conn.close()
            if not matrix_df.empty:
                for c in ["campaign_name", "heading", "sub_heading", "country", "code", "zakat_eligibility"]:
                    if c in matrix_df.columns:
                        matrix_df[c] = matrix_df[c].apply(fix_mojibake)
                cache = {}
                for _, r in matrix_df.iterrows():
                    c_clean = fix_mojibake(r["campaign_name"]).strip().lower()
                    code_clean = str(r["code"]).strip().lower()
                    if c_clean:
                        cache[(c_clean, code_clean)] = r.to_dict()
                        if c_clean not in cache or bool(r.get("is_primary") in [1, True, "1", "true"]):
                            cache[c_clean] = r.to_dict()
                _PAYSUITE_MATRIX_CACHE[cid] = cache
                return _PAYSUITE_MATRIX_CACHE[cid]
        except Exception as e:
            print(f"[Paysuite Matrix Overlay Notice]: {e}")
        return {}
    else:
        if cid in _CLASSIFICATION_MATRIX_CACHE:
            return _CLASSIFICATION_MATRIX_CACHE[cid]
        try:
            conn = get_db_connection(timeout=10.0)
            if cid == "all":
                matrix_df = pd.read_sql_query("""
                    SELECT campaign_name, heading, sub_heading, country, code, zakat_eligibility, is_primary 
                    FROM campaign_classifications
                """, conn)
            else:
                matrix_df = pd.read_sql_query("""
                    SELECT campaign_name, heading, sub_heading, country, code, zakat_eligibility, is_primary 
                    FROM campaign_classifications WHERE company_id = ?
                """, conn, params=(cid,))
            conn.close()
            if not matrix_df.empty:
                for c in ["campaign_name", "heading", "sub_heading", "country", "code", "zakat_eligibility"]:
                    if c in matrix_df.columns:
                        matrix_df[c] = matrix_df[c].apply(fix_mojibake)
                cache = {}
                for _, r in matrix_df.iterrows():
                    c_clean = fix_mojibake(r["campaign_name"]).strip().lower()
                    code_clean = str(r["code"]).strip().lower()
                    if c_clean:
                        cache[(c_clean, code_clean)] = r.to_dict()
                        if c_clean not in cache or bool(r.get("is_primary") in [1, True, "1", "true"]):
                            cache[c_clean] = r.to_dict()
                _CLASSIFICATION_MATRIX_CACHE[cid] = cache
                return _CLASSIFICATION_MATRIX_CACHE[cid]
        except Exception as e:
            print(f"[LaunchGood Matrix Overlay Notice]: {e}")
        return {}


def _get_payout_data_from_db(platform: str = "launchgood", force_reload: bool = False, company_id: Optional[str] = "rethink"):
    global _CLASSIFIED_PAYOUTS_CACHE, _CLASSIFIED_PAYSUITE_CACHE
    p_clean = _clean_str(platform, "launchgood").lower()
    cid = _clean_str(company_id, "rethink").lower()

    if p_clean == "paysuite":
        if not force_reload and cid in _CLASSIFIED_PAYSUITE_CACHE and not _CLASSIFIED_PAYSUITE_CACHE[cid].empty:
            return _CLASSIFIED_PAYSUITE_CACHE[cid]

        try:
            df_p = load_paysuite_payouts_data(force_reload=force_reload, company_id=cid)
            if df_p is None or df_p.empty:
                conn = get_db_connection(timeout=10.0)
                try:
                    if cid == "all":
                        df_p = pd.read_sql_query("SELECT * FROM paysuite_payout_settlements", conn)
                    else:
                        df_p = pd.read_sql_query("SELECT * FROM paysuite_payout_settlements WHERE company_id = ?", conn, params=(cid,))
                except Exception:
                    df_p = pd.DataFrame()
                finally:
                    conn.close()

            if df_p is not None and not df_p.empty:
                df = df_p.copy()
                
                # Exclude auto disbursals completely
                amounts_raw = pd.to_numeric(df.get("Total Online Donation Gross Amount in Settled Currency", df.get("Amount", 0.0)), errors="coerce").fillna(0.0)
                is_disbursal = (df.get("Bank Ref", "") == "REC-DSBE1Q160G") | (df.get("Comments", "") == "Auto disbursal") | (amounts_raw < 0)
                df = df[~is_disbursal].copy()

                c_name = df.get("Bank Ref", df.get("Campaign Name", pd.Series("Unassigned Direct Debit", index=df.index))).fillna("Unassigned Direct Debit").apply(fix_mojibake)
                df["campaign_name"] = c_name
                df["Campaign Name"] = c_name
                df["Bank Ref"] = c_name
                df["row_type"] = "donation"

                gross_series = pd.to_numeric(df.get("Total Online Donation Gross Amount in Settled Currency", df.get("Amount", 0.0)), errors="coerce").fillna(0.0).abs()
                fee_series = pd.to_numeric(df.get("Total Processing Fees Paid by CC In Settled Currency", 0.0), errors="coerce").fillna(0.0)
                
                status_series = df.get("Status", df.get("Paid/Unpaid", pd.Series("Paid", index=df.index))).fillna("Paid").astype(str).str.capitalize()
                status_series = status_series.apply(lambda s: "Unpaid" if s.lower() in ["unpaid", "failed", "cancelled"] else "Paid")
                df["status"] = status_series
                df["Status"] = status_series
                df["Paid/Unpaid"] = status_series

                # Net is gross if paid, else 0
                net_series = np.where(status_series == "Paid", gross_series, 0.0)
                df["gross_amt"] = gross_series
                df["fee_amt"] = fee_series
                df["net_amt"] = net_series

                t_ids = df.get("Transfer ID", df.get("Batch Label", pd.Series("N/A", index=df.index))).fillna("N/A").astype(str).str.strip()
                df["transfer_id"] = t_ids
                df["Transfer ID"] = t_ids
                df["batch_label"] = df.get("Batch Label", df.get("Collection Month", t_ids)).fillna(t_ids).astype(str)

                df["heading"] = df.get("Heading", pd.Series("Unassigned", index=df.index)).fillna("Unassigned").apply(fix_mojibake)
                df["sub_heading"] = df.get("Sub-Heading", pd.Series("Unassigned", index=df.index)).fillna("Unassigned").apply(fix_mojibake)
                df["country"] = df.get("Country", pd.Series("ALL", index=df.index)).fillna("ALL").apply(fix_mojibake)
                df["code"] = df.get("Code", pd.Series("Unassigned", index=df.index)).fillna("Unassigned").apply(fix_mojibake)
                df["zakat"] = df.get("Zakat Eligibility", pd.Series("Non-Zakat", index=df.index)).fillna("Non-Zakat").apply(fix_mojibake)
                df["settlement_currency"] = "GBP"
                df["Settlement Currency"] = "GBP"
                df["Platform"] = "Paysuite"

                # Overlay matrix classifications
                rule_dict = _get_classification_matrix_dict("paysuite", company_id=cid)
                if rule_dict:
                    c_keys = df["campaign_name"].astype(str).str.strip().str.lower().tolist()
                    code_keys = df["code"].astype(str).str.strip().str.lower().tolist()
                    for f, db_f in [("heading", "heading"), ("sub_heading", "sub_heading"), ("country", "country"), ("code", "code"), ("zakat", "zakat_eligibility")]:
                        updated_vals = []
                        for cn, cc in zip(c_keys, code_keys):
                            entry = rule_dict.get((cn, cc), rule_dict.get(cn, {}))
                            val = entry.get(db_f, "")
                            if val and str(val).strip().lower() not in ["", "nan", "none", "unassigned"]:
                                updated_vals.append(fix_mojibake(val))
                            else:
                                updated_vals.append(None)
                        series_updated = pd.Series(updated_vals, index=df.index)
                        mask_valid = series_updated.notna()
                        if mask_valid.any():
                            df.loc[mask_valid, f] = series_updated[mask_valid]

                _CLASSIFIED_PAYSUITE_CACHE[cid] = df
                return _CLASSIFIED_PAYSUITE_CACHE[cid]

            _CLASSIFIED_PAYSUITE_CACHE[cid] = pd.DataFrame()
            return _CLASSIFIED_PAYSUITE_CACHE[cid]
        except Exception as e:
            print(f"[Error] Reading cached paysuite payout data: {e}")
            _CLASSIFIED_PAYSUITE_CACHE[cid] = pd.DataFrame()
            return _CLASSIFIED_PAYSUITE_CACHE[cid]

    else:
        # LaunchGood Payouts
        if not force_reload and cid in _CLASSIFIED_PAYOUTS_CACHE and not _CLASSIFIED_PAYOUTS_CACHE[cid].empty:
            return _CLASSIFIED_PAYOUTS_CACHE[cid]

        try:
            df_p = load_payouts_data(force_reload=force_reload, company_id=cid)
            if df_p is not None and not df_p.empty:
                df = df_p.copy()
                c_name = df.get("Campaign Name", pd.Series("Unassigned Campaign", index=df.index)).fillna("Unassigned Campaign").apply(fix_mojibake)
                df["campaign_name"] = c_name
                df["Campaign Name"] = c_name
                df["row_type"] = df.get("Type", df.get("Transaction Type", pd.Series("donation", index=df.index))).fillna("donation").astype(str).str.lower()
                df["gross_amt"] = pd.to_numeric(df.get("Total Online Donation Gross Amount in Settled Currency", 0.0), errors="coerce").fillna(0.0)
                df["fee_amt"] = pd.to_numeric(df.get("Total Processing Fees Paid by CC In Settled Currency", 0.0), errors="coerce").fillna(0.0)
                df["net_amt"] = pd.to_numeric(df.get("Total Online Donations Net Amount in Settled Currency", 0.0), errors="coerce").fillna(0.0)
                
                t_ids = df.get("Transfer ID", pd.Series("N/A", index=df.index)).fillna("N/A").astype(str).str.replace(".0", "", regex=False).str.strip()
                df["transfer_id"] = t_ids
                df["Transfer ID"] = t_ids
                df["batch_label"] = "Batch #" + t_ids
                df["status"] = "Paid"

                valid_payout_mask = ~df["transfer_id"].str.lower().isin(["n/a", "nan", "none", ""]) & (df["campaign_name"] != "Unassigned Campaign")
                df = df[valid_payout_mask].copy()

                df["heading"] = df.get("Heading", pd.Series("Unassigned", index=df.index)).fillna("Unassigned").apply(fix_mojibake)
                df["sub_heading"] = df.get("Sub-Heading", pd.Series("Unassigned", index=df.index)).fillna("Unassigned").apply(fix_mojibake)
                df["country"] = df.get("Country", pd.Series("Unassigned", index=df.index)).fillna("Unassigned").apply(fix_mojibake)
                df["code"] = df.get("Code", pd.Series("Unassigned", index=df.index)).fillna("Unassigned").apply(fix_mojibake)
                df["zakat"] = df.get("Zakat Eligibility", pd.Series("Unassigned", index=df.index)).fillna("Unassigned").apply(fix_mojibake)
                df["settlement_currency"] = df.get("Settlement Currency", pd.Series("GBP", index=df.index)).fillna("GBP").astype(str).str.strip().str.upper()
                df["Settlement Currency"] = df["settlement_currency"]
                df["Platform"] = "LaunchGood"

                rule_dict = _get_classification_matrix_dict("launchgood", company_id=cid)
                if rule_dict:
                    c_keys = df["campaign_name"].astype(str).str.strip().str.lower().tolist()
                    code_keys = df["code"].astype(str).str.strip().str.lower().tolist()
                    for f, db_f in [("heading", "heading"), ("sub_heading", "sub_heading"), ("country", "country"), ("code", "code"), ("zakat", "zakat_eligibility")]:
                        updated_vals = []
                        for cn, cc in zip(c_keys, code_keys):
                            entry = rule_dict.get((cn, cc), rule_dict.get(cn, {}))
                            val = entry.get(db_f, "")
                            if val and str(val).strip().lower() not in ["", "nan", "none", "unassigned"]:
                                updated_vals.append(fix_mojibake(val))
                            else:
                                updated_vals.append(None)
                        series_updated = pd.Series(updated_vals, index=df.index)
                        mask_valid = series_updated.notna()
                        if mask_valid.any():
                            df.loc[mask_valid, f] = series_updated[mask_valid]

                _CLASSIFIED_PAYOUTS_CACHE[cid] = df
                return _CLASSIFIED_PAYOUTS_CACHE[cid]

            _CLASSIFIED_PAYOUTS_CACHE[cid] = pd.DataFrame()
            return _CLASSIFIED_PAYOUTS_CACHE[cid]
        except Exception as e:
            print(f"[Error] Reading cached launchgood payout data: {e}")
            _CLASSIFIED_PAYOUTS_CACHE[cid] = pd.DataFrame()
            return _CLASSIFIED_PAYOUTS_CACHE[cid]


def _generate_disbursement_summary(df_curr: pd.DataFrame, currency_name: str, platform: str = "launchgood") -> Dict[str, Any]:
    """Generates exact Disbursement Summary matching the Finance Team ledger format."""
    p_clean = platform.lower()
    
    if p_clean == "paysuite":
        paid_df = df_curr[df_curr["status"] == "Paid"]
        unpaid_df = df_curr[df_curr["status"] == "Unpaid"]

        gross_donations = float(df_curr["gross_amt"].sum())
        gross_donations_count = int(len(df_curr))
        
        paid_amt = float(paid_df["gross_amt"].sum())
        paid_count = int(len(paid_df))

        unpaid_amt = float(unpaid_df["gross_amt"].sum())
        unpaid_count = int(len(unpaid_df))

        processing_fees = float(df_curr["fee_amt"].sum())
        total_disbursement = float(paid_amt - processing_fees)

        return {
            "currency": currency_name,
            "gross_donations": round(gross_donations, 2),
            "gross_donations_count": gross_donations_count,
            "paid_amount": round(paid_amt, 2),
            "paid_count": paid_count,
            "unpaid_amount": round(unpaid_amt, 2),
            "unpaid_count": unpaid_count,
            "collection_rate": round((paid_count / gross_donations_count * 100), 1) if gross_donations_count > 0 else 100.0,
            "refunds": 0.0,
            "refunds_count": 0,
            "refunds_failed": 0.0,
            "refunds_failed_count": 0,
            "chargebacks": 0.0,
            "chargebacks_count": 0,
            "chargebacks_reversed": 0.0,
            "chargebacks_reversed_count": 0,
            "net_sales": round(paid_amt, 2),
            "net_sales_count": paid_count,
            "processing_fees": round(-abs(processing_fees) if processing_fees != 0 else 0.0, 2),
            "non_processing_fees": 0.0,
            "manual_adjustments": 0.0,
            "manual_adjustments_count": 0,
            "reserve_adjustment": 0.0,
            "reserve_adjustment_count": 0,
            "foreign_exchange": 0.0,
            "foreign_exchange_count": 0,
            "total_disbursement": round(total_disbursement, 2),
            "total_disbursement_count": paid_count
        }

    donations = df_curr[df_curr["row_type"] == "donation"]
    refunds = df_curr[df_curr["row_type"] == "refund"]
    adjustments = df_curr[df_curr["row_type"] == "adjustment"]
    reserves = df_curr[df_curr["row_type"] == "reserve"]
    fx = df_curr[df_curr["row_type"] == "fx"]
    payouts = df_curr[df_curr["row_type"] == "payout"]

    gross_donations = float(donations["gross_amt"].sum())
    gross_donations_count = int(len(donations))

    refunds_amt = float(refunds["gross_amt"].sum())
    refunds_count = int(len(refunds))

    net_sales = float(gross_donations + refunds_amt)
    net_sales_count = int(gross_donations_count - refunds_count)

    processing_fees = float(df_curr["fee_amt"].sum())
    non_processing_fees = 0.0

    manual_adjustments = float(adjustments["gross_amt"].sum())
    manual_adjustments_count = int(len(adjustments))

    reserve_adjustment = float(reserves["gross_amt"].sum())
    reserve_adjustment_count = int(len(reserves))

    fx_amt = float(fx["gross_amt"].sum())
    fx_count = int(len(fx))

    if not payouts.empty:
        total_disbursement = float(abs(payouts["net_amt"].sum()))
        total_disbursement_count = int(len(payouts))
    else:
        total_disbursement = float(net_sales - processing_fees + manual_adjustments + reserve_adjustment + fx_amt)
        total_disbursement_count = int(len(payouts))

    return {
        "currency": currency_name,
        "gross_donations": round(gross_donations, 2),
        "gross_donations_count": gross_donations_count,
        "refunds": round(refunds_amt, 2),
        "refunds_count": refunds_count,
        "refunds_failed": 0.0,
        "refunds_failed_count": 0,
        "chargebacks": 0.0,
        "chargebacks_count": 0,
        "chargebacks_reversed": 0.0,
        "chargebacks_reversed_count": 0,
        "net_sales": round(net_sales, 2),
        "net_sales_count": net_sales_count,
        "processing_fees": round(-abs(processing_fees) if processing_fees != 0 else 0.0, 2),
        "non_processing_fees": 0.0,
        "manual_adjustments": round(manual_adjustments, 2),
        "manual_adjustments_count": manual_adjustments_count,
        "reserve_adjustment": round(reserve_adjustment, 2),
        "reserve_adjustment_count": reserve_adjustment_count,
        "foreign_exchange": round(fx_amt, 2),
        "foreign_exchange_count": fx_count,
        "total_disbursement": round(total_disbursement, 2),
        "total_disbursement_count": total_disbursement_count
    }


def _generate_ledger_breakdown(df: pd.DataFrame, platform: str = "launchgood") -> List[Dict[str, Any]]:
    if platform.lower() == "paysuite":
        if df is None or df.empty:
            return []
        breakdown = []
        paid_df = df[df["status"] == "Paid"]
        unpaid_df = df[df["status"] == "Unpaid"]
        
        breakdown.append({
            "row_type": "Paid Collection",
            "count": int(len(paid_df)),
            "gross_amount": round(float(paid_df["gross_amt"].sum()), 2),
            "processing_fees": round(float(paid_df["fee_amt"].sum()), 2),
            "net_amount": round(float(paid_df["net_amt"].sum()), 2),
            "description": "Settled Direct Debit monthly collections successfully collected"
        })
        if not unpaid_df.empty:
            breakdown.append({
                "row_type": "Unpaid / Failed",
                "count": int(len(unpaid_df)),
                "gross_amount": round(float(unpaid_df["gross_amt"].sum()), 2),
                "processing_fees": round(float(unpaid_df["fee_amt"].sum()), 2),
                "net_amount": 0.0,
                "description": "Failed, uncollected, or cancelled Direct Debit collection items"
            })
        return breakdown

    DESCRIPTIONS = {
        "donation": "Gross donor contributions received",
        "payout": "Bank transfer batches paid out to charity account",
        "reserve": "Rolling reserve hold funds",
        "fx": "Foreign exchange conversion adjustments",
        "adjustment": "Settlement / manual account adjustment",
        "refund": "Donor transaction refund deductions"
    }
    TYPE_ORDER = ["donation", "payout", "reserve", "fx", "adjustment", "refund"]

    if df is None or df.empty or "row_type" not in df.columns:
        return []

    breakdown = []
    found_types = set(df["row_type"].unique())
    ordered_types = [t for t in TYPE_ORDER if t in found_types] + [t for t in found_types if t not in TYPE_ORDER]

    for r_type in ordered_types:
        sub = df[df["row_type"] == r_type]
        g_amt = float(sub["gross_amt"].sum())
        f_amt = float(sub["fee_amt"].sum())
        n_amt = float(sub["net_amt"].sum())
        breakdown.append({
            "row_type": r_type.capitalize(),
            "count": int(len(sub)),
            "gross_amount": round(g_amt, 2),
            "processing_fees": round(f_amt, 2),
            "net_amount": round(n_amt, 2),
            "description": DESCRIPTIONS.get(r_type, f"Transaction records for {r_type}")
        })

    return breakdown


@router.get("/summary")
def get_payouts_summary(
    company_id: Optional[str] = Query("rethink"),
    platform: Optional[str] = Query("launchgood", description="Platform: launchgood or paysuite"),
    currency: Optional[str] = Query("GBP", description="Filter by settlement currency: GBP, USD, or ALL"),
    batch: Optional[str] = Query("ALL", description="Filter by specific Transfer ID / Batch"),
    status: Optional[str] = Query("ALL", description="Filter by status: ALL, Paid, Unpaid"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    campaign_search: Optional[str] = None,
    transfer_id: Optional[str] = None
):
    """Returns top KPI metrics, Finance Disbursement Summary, and Accounting Ledger breakdown."""
    plat = _clean_str(platform, "launchgood").lower()
    curr_selected = _clean_str(currency, "GBP").upper()
    target_batch = _clean_str(transfer_id or batch, "ALL")
    status_filter = _clean_str(status, "ALL").capitalize()

    try:
        df_all = _get_payout_data_from_db(platform=plat, company_id=company_id)
        if df_all.empty:
            return {
                "platform": plat,
                "currency": curr_selected,
                "batch": target_batch,
                "total_gross": 0.0,
                "total_fees": 0.0,
                "total_reserves": 0.0,
                "net_payout": 0.0,
                "total_transactions": 0,
                "settled_donations_count": 0,
                "paid_count": 0,
                "unpaid_count": 0,
                "disbursement_summary": {},
                "ledger_breakdown": []
            }

        df = df_all.copy()

        # Currency Filter
        if curr_selected in ["GBP", "USD"]:
            df = df[df["settlement_currency"] == curr_selected]
        else:
            curr_selected = "ALL"

        # Batch / Transfer ID Filter
        if target_batch and target_batch.upper() != "ALL":
            target_clean = target_batch.replace(".0", "").replace("#", "").strip().lower()
            df = df[df["transfer_id"].astype(str).str.replace(".0", "").str.strip().str.lower() == target_clean]

        # Pre-status filter metrics for active batch/cycle
        batch_total_tx = int(len(df))
        batch_paid_count = int((df["status"] == "Paid").sum()) if "status" in df.columns else batch_total_tx
        batch_unpaid_count = int((df["status"] == "Unpaid").sum()) if "status" in df.columns else 0
        batch_paid_amount = float(df[df["status"] == "Paid"]["gross_amt"].sum()) if "status" in df.columns else float(df["gross_amt"].sum())
        batch_unpaid_amount = float(df[df["status"] == "Unpaid"]["gross_amt"].sum()) if "status" in df.columns else 0.0

        # Status Filter
        if status_filter in ["Paid", "Unpaid"]:
            df = df[df["status"] == status_filter]

        # Date Filters
        s_date = _clean_str(start_date)
        e_date = _clean_str(end_date)
        if s_date and "Created Date (UTC)" in df.columns:
            df = df[pd.to_datetime(df["Created Date (UTC)"], errors="coerce") >= pd.to_datetime(s_date)]
        if e_date and "Created Date (UTC)" in df.columns:
            df = df[pd.to_datetime(df["Created Date (UTC)"], errors="coerce") <= pd.to_datetime(e_date)]

        if plat == "paysuite":
            paid_df = df[df["status"] == "Paid"]
            unpaid_df = df[df["status"] == "Unpaid"]
            total_gross = float(df["gross_amt"].sum())
            total_fees = float(df["fee_amt"].sum())
            net_payout = float(paid_df["net_amt"].sum())
            paid_count = int(len(paid_df))
            unpaid_count = int(len(unpaid_df))
            total_tx = int(len(df))
            collection_rate = round((batch_paid_count / batch_total_tx * 100), 1) if batch_total_tx > 0 else 100.0

            disbursement_summary = _generate_disbursement_summary(df, curr_selected, platform="paysuite")
            ledger_breakdown = _generate_ledger_breakdown(df, platform="paysuite")

            return {
                "platform": "paysuite",
                "currency": curr_selected,
                "batch": target_batch,
                "total_gross": round(total_gross, 2),
                "total_fees": round(total_fees, 2),
                "total_reserves": 0.0,
                "net_payout": round(net_payout, 2),
                "total_transactions": total_tx,
                "settled_donations_count": paid_count,
                "paid_count": paid_count,
                "unpaid_count": unpaid_count,
                "paid_amount": round(float(paid_df["gross_amt"].sum()), 2),
                "unpaid_amount": round(float(unpaid_df["gross_amt"].sum()), 2),
                "collection_rate": collection_rate,
                "batch_total_count": batch_total_tx,
                "batch_paid_count": batch_paid_count,
                "batch_unpaid_count": batch_unpaid_count,
                "batch_paid_amount": round(batch_paid_amount, 2),
                "batch_unpaid_amount": round(batch_unpaid_amount, 2),
                "disbursement_summary": disbursement_summary,
                "ledger_breakdown": ledger_breakdown,
                "available_currencies": ["GBP"]
            }

        # LaunchGood Payout Summary
        donations_df = df[df["row_type"] == "donation"]
        payouts_df = df[df["row_type"] == "payout"]
        reserves_df = df[df["row_type"] == "reserve"]

        total_gross = float(donations_df["gross_amt"].sum())
        total_fees = float(df["fee_amt"].sum())
        total_reserves = float(abs(reserves_df["net_amt"].sum()))
        
        net_payout = float(abs(payouts_df["net_amt"].sum())) if not payouts_df.empty else float(donations_df["net_amt"].sum() - total_fees)
        
        disbursement_summary = _generate_disbursement_summary(df, curr_selected, platform="launchgood")
        ledger_breakdown = _generate_ledger_breakdown(df, platform="launchgood")

        return {
            "platform": "launchgood",
            "currency": curr_selected,
            "batch": target_batch,
            "total_gross": round(total_gross, 2),
            "total_fees": round(total_fees, 2),
            "total_reserves": round(total_reserves, 2),
            "net_payout": round(net_payout, 2),
            "total_transactions": len(df),
            "settled_donations_count": len(donations_df),
            "disbursement_summary": disbursement_summary,
            "ledger_breakdown": ledger_breakdown,
            "available_currencies": ["GBP", "USD", "ALL"]
        }

    except Exception as e:
        print(f"[Error] Payout summary error: {e}")
        return {
            "platform": plat,
            "currency": curr_selected,
            "batch": target_batch,
            "total_gross": 0.0,
            "total_fees": 0.0,
            "total_reserves": 0.0,
            "net_payout": 0.0,
            "total_transactions": 0,
            "settled_donations_count": 0,
            "disbursement_summary": {},
            "ledger_breakdown": [],
            "available_currencies": ["GBP", "USD"]
        }


@router.get("/batches")
def get_payout_batches(
    company_id: Optional[str] = Query("rethink"),
    platform: Optional[str] = Query("launchgood", description="Platform: launchgood or paysuite"),
    currency: Optional[str] = Query("GBP", description="Filter by settlement currency"),
    status: Optional[str] = Query("ALL", description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=250),
    search: Optional[str] = ""
):
    """Returns paginated list of payout settlement batches grouped by Transfer ID / Collection Month."""
    plat = _clean_str(platform, "launchgood").lower()
    curr_selected = _clean_str(currency, "GBP").upper()
    search_val = _clean_str(search).lower()
    p_val = int(_clean_str(page, "1")) if _clean_str(page, "1").isdigit() else 1
    ps_val = int(_clean_str(page_size, "25")) if _clean_str(page_size, "25").isdigit() else 25

    try:
        df = _get_payout_data_from_db(platform=plat, company_id=company_id)
        if df.empty:
            return {"platform": plat, "total_batches": 0, "page": p_val, "page_size": ps_val, "batches": [], "currency": curr_selected}

        if curr_selected in ["GBP", "USD"]:
            df = df[df["settlement_currency"] == curr_selected]

        df = df[~df["transfer_id"].astype(str).str.lower().isin(["n/a", "nan", "none", ""])].copy()

        if df.empty:
            return {"platform": plat, "total_batches": 0, "page": p_val, "page_size": ps_val, "batches": [], "currency": curr_selected}

        if search_val:
            mask = df["transfer_id"].astype(str).str.lower().str.contains(search_val, na=False) | \
                   df["batch_label"].astype(str).str.lower().str.contains(search_val, na=False) | \
                   df["campaign_name"].astype(str).str.lower().str.contains(search_val, na=False)
            df = df[mask]

        batch_records = []
        if plat == "paysuite":
            for (t_id, b_label), g in df.groupby(["transfer_id", "batch_label"]):
                c_date = str(g["Created Date (UTC)"].dropna().min() or "N/A")
                g_amt = round(float(g["gross_amt"].sum()), 2)
                f_amt = round(float(g["fee_amt"].sum()), 2)
                t_amt = round(float(g[g["status"] == "Paid"]["gross_amt"].sum()), 2)
                camp_cnt = int(g["campaign_name"].nunique())
                don_cnt = int(len(g))
                paid_cnt = int((g["status"] == "Paid").sum())
                unpaid_cnt = int((g["status"] == "Unpaid").sum())
                batch_records.append({
                    "transfer_id": str(t_id),
                    "batch_label": str(b_label),
                    "created_date": c_date,
                    "gross_amount": g_amt,
                    "processing_fees": f_amt,
                    "transfer_amount": t_amt,
                    "campaigns_count": camp_cnt,
                    "donations_count": don_cnt,
                    "paid_count": paid_cnt,
                    "unpaid_count": unpaid_cnt,
                    "currency": "GBP"
                })
            batch_records.sort(key=lambda x: x["transfer_id"], reverse=True)
        else:
            for t_id, g in df.groupby("transfer_id"):
                c_date = str(g["Created Date (UTC)"].dropna().min() or "N/A")
                g_amt = round(float(g[g["row_type"] == "donation"]["gross_amt"].sum()), 2)
                f_amt = round(float(g["fee_amt"].sum()), 2)
                payout_net = float(abs(g[g["row_type"] == "payout"]["net_amt"].sum()))
                don_net = float(g[g["row_type"] == "donation"]["net_amt"].sum())
                t_amt = round(payout_net or don_net, 2)
                camp_cnt = int(g["campaign_name"].nunique())
                don_cnt = int((g["row_type"] == "donation").sum())
                curr_val = str(g["settlement_currency"].iloc[0] if "settlement_currency" in g.columns else "GBP")
                batch_records.append({
                    "transfer_id": str(t_id),
                    "batch_label": f"Batch #{t_id}",
                    "created_date": c_date,
                    "gross_amount": g_amt,
                    "processing_fees": f_amt,
                    "transfer_amount": t_amt,
                    "campaigns_count": camp_cnt,
                    "donations_count": don_cnt,
                    "currency": curr_val
                })
            batch_records.sort(key=lambda x: (x["created_date"], x["transfer_id"]), reverse=True)

        total_batches = len(batch_records)
        total_pages = max(1, math.ceil(total_batches / ps_val))
        p_val = min(p_val, total_pages)
        start_idx = (p_val - 1) * ps_val
        end_idx = min(start_idx + ps_val, total_batches)

        page_batches = batch_records[start_idx:end_idx]

        return {
            "platform": plat,
            "total_batches": total_batches,
            "page": p_val,
            "page_size": ps_val,
            "total_pages": total_pages,
            "batches": page_batches,
            "currency": curr_selected
        }

    except Exception as e:
        print(f"[Error] Payout batches error: {e}")
        return {"platform": plat, "total_batches": 0, "page": 1, "page_size": 25, "batches": [], "currency": "GBP"}


@router.get("/ledger-breakdown")
def get_payout_ledger_breakdown(
    company_id: Optional[str] = Query("rethink"),
    platform: Optional[str] = Query("launchgood", description="Platform: launchgood or paysuite"),
    currency: Optional[str] = Query("GBP", description="Filter by settlement currency"),
    batch: Optional[str] = Query("ALL", description="Filter by specific Transfer ID / Batch"),
    status: Optional[str] = Query("ALL", description="Filter by status")
):
    """Returns finance disbursement summary and accounting ledger breakdown."""
    sum_data = get_payouts_summary(company_id=company_id, platform=platform, currency=currency, batch=batch, status=status)
    return {
        "disbursement_summary": sum_data.get("disbursement_summary", {}),
        "ledger": sum_data.get("ledger_breakdown", [])
    }


@router.get("/campaign-breakdown")
def get_campaign_payout_breakdown(
    company_id: Optional[str] = Query("rethink"),
    platform: Optional[str] = Query("launchgood", description="Platform: launchgood or paysuite"),
    currency: Optional[str] = Query("GBP", description="Filter by settlement currency"),
    batch: Optional[str] = Query("ALL", description="Filter by specific Transfer ID / Batch"),
    status: Optional[str] = Query("ALL", description="Filter by status"),
    search: Optional[str] = ""
):
    """Returns classification code-level hierarchical breakdown with nested campaigns and individual metrics."""
    plat = _clean_str(platform, "launchgood").lower()
    curr_selected = _clean_str(currency, "GBP").upper()
    target_batch = _clean_str(batch, "ALL")
    status_filter = _clean_str(status, "ALL").capitalize()
    search_val = _clean_str(search).lower()

    try:
        df = _get_payout_data_from_db(platform=plat, company_id=company_id)
        if df.empty:
            return {
                "platform": plat,
                "code_groups": [], 
                "heading_groups": [], 
                "country_groups": [], 
                "campaigns": [], 
                "total_codes": 0, 
                "total_headings": 0, 
                "total_countries": 0, 
                "total_campaigns": 0, 
                "currency": curr_selected, 
                "batch": target_batch
            }

        if curr_selected in ["GBP", "USD"]:
            df = df[df["settlement_currency"] == curr_selected]

        if target_batch and target_batch.upper() != "ALL":
            target_clean = target_batch.replace(".0", "").replace("#", "").strip().lower()
            df = df[df["transfer_id"].astype(str).str.replace(".0", "").str.strip().str.lower() == target_clean]

        # Status filter
        if status_filter in ["Paid", "Unpaid"]:
            df = df[df["status"] == status_filter]

        if plat == "paysuite":
            camp_agg = df.groupby(["campaign_name", "code", "status"]).agg(
                gross=("gross_amt", "sum"),
                fee=("fee_amt", "sum"),
                net=("net_amt", "sum"),
                count=("gross_amt", "count")
            ).reset_index()

            meta = df.groupby(["campaign_name", "code"]).first()[["heading", "sub_heading", "country", "zakat", "Display Name", "Email"]].to_dict('index')

            campaign_records = []
            for (cname, ccode), g in camp_agg.groupby(["campaign_name", "code"]):
                c_meta = meta.get((cname, ccode), {})
                g_amt = round(float(g["gross"].sum()), 2)
                f_amt = round(float(g["fee"].sum()), 2)
                n_amt = round(float(g["net"].sum()), 2)
                cnt = int(g["count"].sum())
                fee_pct = round((f_amt / g_amt * 100.0), 2) if g_amt > 0 else 0.0

                campaign_records.append({
                    "campaign_name": str(cname),
                    "gross_amount": g_amt,
                    "processing_fees": f_amt,
                    "transfer_amount": n_amt,
                    "fee_percentage": fee_pct,
                    "heading": str(c_meta.get("heading", "Unassigned")),
                    "sub_heading": str(c_meta.get("sub_heading", "Unassigned")),
                    "country": str(c_meta.get("country", "ALL")),
                    "code": str(ccode),
                    "zakat": str(c_meta.get("zakat", "Non-Zakat")),
                    "donor_name": str(c_meta.get("Display Name", "")),
                    "donor_email": str(c_meta.get("Email", "")),
                    "donations_count": cnt
                })

        else:
            camp_agg = df.groupby(["campaign_name", "code", "row_type"]).agg(
                gross=("gross_amt", "sum"),
                fee=("fee_amt", "sum"),
                net=("net_amt", "sum"),
                count=("gross_amt", "count")
            ).reset_index()

            meta = df.groupby(["campaign_name", "code"]).first()[["heading", "sub_heading", "country", "zakat"]].to_dict('index')

            campaign_records = []
            for (cname, ccode), g in camp_agg.groupby(["campaign_name", "code"]):
                c_meta = meta.get((cname, ccode), {})
                row_dict = {r["row_type"]: r for _, r in g.iterrows()}
                
                don = row_dict.get("donation", {})
                ref = row_dict.get("refund", {})
                
                don_gross = float(don.get("gross", 0.0))
                ref_gross = float(ref.get("gross", 0.0))
                g_amt = round(don_gross + ref_gross, 2)
                
                f_amt = round(float(g["fee"].sum()), 2)
                
                don_net = float(don.get("net", 0.0))
                ref_net = float(ref.get("net", 0.0))
                fx_net = float(row_dict.get("fx", {}).get("gross", 0.0))
                adj_net = float(row_dict.get("adjustment", {}).get("gross", 0.0))
                res_net = float(row_dict.get("reserve", {}).get("gross", 0.0))
                
                if curr_selected == "USD":
                    t_amt = round(don_net + ref_net, 2)
                else:
                    t_amt = round(don_net + ref_net + fx_net + adj_net + res_net, 2)

                fee_pct = round((f_amt / g_amt * 100.0), 2) if g_amt > 0 else 0.0
                
                don_cnt = int(don.get("count", 0))
                ref_cnt = int(ref.get("count", 0))

                campaign_records.append({
                    "campaign_name": str(cname),
                    "gross_amount": g_amt,
                    "processing_fees": f_amt,
                    "transfer_amount": t_amt,
                    "fee_percentage": fee_pct,
                    "heading": str(c_meta.get("heading", "Unassigned")),
                    "sub_heading": str(c_meta.get("sub_heading", "Unassigned")),
                    "country": str(c_meta.get("country", "Unassigned")),
                    "code": str(ccode),
                    "zakat": str(c_meta.get("zakat", "Unassigned")),
                    "donations_count": don_cnt if don_cnt > 0 else (ref_cnt if ref_cnt > 0 else 0)
                })

        campaign_records.sort(key=lambda x: x["gross_amount"], reverse=True)

        # Build Code Groups from campaign_records
        code_map = {}
        heading_map = {}
        country_map = {}

        for c in campaign_records:
            # Code Grouping
            cd = c["code"]
            if cd not in code_map:
                code_map[cd] = {
                    "code": cd,
                    "heading": c["heading"],
                    "sub_heading": c["sub_heading"],
                    "country": c["country"],
                    "zakat": c["zakat"],
                    "gross_amount": 0.0,
                    "processing_fees": 0.0,
                    "transfer_amount": 0.0,
                    "donations_count": 0,
                    "campaigns": []
                }
            code_map[cd]["gross_amount"] = round(code_map[cd]["gross_amount"] + c["gross_amount"], 2)
            code_map[cd]["processing_fees"] = round(code_map[cd]["processing_fees"] + c["processing_fees"], 2)
            code_map[cd]["transfer_amount"] = round(code_map[cd]["transfer_amount"] + c["transfer_amount"], 2)
            code_map[cd]["donations_count"] += c["donations_count"]
            code_map[cd]["campaigns"].append(c)

            # Heading Grouping
            hd = c["heading"] if c["heading"] and c["heading"] != "Unassigned" else "General Fund"
            if hd not in heading_map:
                heading_map[hd] = {
                    "heading": hd,
                    "gross_amount": 0.0,
                    "processing_fees": 0.0,
                    "transfer_amount": 0.0,
                    "donations_count": 0,
                    "codes": set(),
                    "campaigns": []
                }
            heading_map[hd]["gross_amount"] = round(heading_map[hd]["gross_amount"] + c["gross_amount"], 2)
            heading_map[hd]["processing_fees"] = round(heading_map[hd]["processing_fees"] + c["processing_fees"], 2)
            heading_map[hd]["transfer_amount"] = round(heading_map[hd]["transfer_amount"] + c["transfer_amount"], 2)
            heading_map[hd]["donations_count"] += c["donations_count"]
            heading_map[hd]["codes"].add(c["code"])
            heading_map[hd]["campaigns"].append(c)

            # Country Grouping
            ctry = c["country"] if c["country"] and c["country"] != "Unassigned" else "Global / Various"
            if ctry not in country_map:
                country_map[ctry] = {
                    "country": ctry,
                    "gross_amount": 0.0,
                    "processing_fees": 0.0,
                    "transfer_amount": 0.0,
                    "donations_count": 0,
                    "codes": set(),
                    "campaigns": []
                }
            country_map[ctry]["gross_amount"] = round(country_map[ctry]["gross_amount"] + c["gross_amount"], 2)
            country_map[ctry]["processing_fees"] = round(country_map[ctry]["processing_fees"] + c["processing_fees"], 2)
            country_map[ctry]["transfer_amount"] = round(country_map[ctry]["transfer_amount"] + c["transfer_amount"], 2)
            country_map[ctry]["donations_count"] += c["donations_count"]
            country_map[ctry]["codes"].add(c["code"])
            country_map[ctry]["campaigns"].append(c)

        code_groups = list(code_map.values())
        for cg in code_groups:
            cg["campaigns_count"] = len(cg["campaigns"])
            cg["fee_percentage"] = round((cg["processing_fees"] / cg["gross_amount"] * 100.0), 2) if cg["gross_amount"] > 0 else 0.0
        code_groups.sort(key=lambda x: x["gross_amount"], reverse=True)

        heading_groups = []
        for h_name, h_dict in heading_map.items():
            h_dict["codes_count"] = len(h_dict["codes"])
            h_dict["codes"] = sorted(list(h_dict["codes"]))
            h_dict["campaigns_count"] = len(h_dict["campaigns"])
            h_dict["fee_percentage"] = round((h_dict["processing_fees"] / h_dict["gross_amount"] * 100.0), 2) if h_dict["gross_amount"] > 0 else 0.0
            heading_groups.append(h_dict)
        heading_groups.sort(key=lambda x: x["gross_amount"], reverse=True)

        country_groups = []
        for c_name, c_dict in country_map.items():
            c_dict["codes_count"] = len(c_dict["codes"])
            c_dict["codes"] = sorted(list(c_dict["codes"]))
            c_dict["campaigns_count"] = len(c_dict["campaigns"])
            c_dict["fee_percentage"] = round((c_dict["processing_fees"] / c_dict["gross_amount"] * 100.0), 2) if c_dict["gross_amount"] > 0 else 0.0
            country_groups.append(c_dict)
        country_groups.sort(key=lambda x: x["gross_amount"], reverse=True)

        # Apply Search Filter
        if search_val:
            filtered_camps = [
                c for c in campaign_records 
                if search_val in c["campaign_name"].lower() 
                or search_val in c["code"].lower() 
                or search_val in c["heading"].lower() 
                or search_val in c["sub_heading"].lower()
                or search_val in c["country"].lower()
            ]

            filtered_codes = []
            for cg in code_groups:
                matching_subs = [
                    sc for sc in cg["campaigns"]
                    if search_val in sc["campaign_name"].lower()
                    or search_val in cg["code"].lower()
                    or search_val in cg["heading"].lower()
                    or search_val in cg["sub_heading"].lower()
                    or search_val in cg["country"].lower()
                ]
                if matching_subs:
                    cg_copy = dict(cg)
                    cg_copy["campaigns"] = matching_subs
                    cg_copy["campaigns_count"] = len(matching_subs)
                    filtered_codes.append(cg_copy)

            filtered_headings = []
            for hg in heading_groups:
                matching_subs = [
                    sc for sc in hg["campaigns"]
                    if search_val in sc["campaign_name"].lower()
                    or search_val in sc["code"].lower()
                    or search_val in hg["heading"].lower()
                    or search_val in sc["sub_heading"].lower()
                    or search_val in sc["country"].lower()
                ]
                if matching_subs:
                    hg_copy = dict(hg)
                    hg_copy["campaigns"] = matching_subs
                    hg_copy["campaigns_count"] = len(matching_subs)
                    filtered_headings.append(hg_copy)

            filtered_countries = []
            for ctg in country_groups:
                matching_subs = [
                    sc for sc in ctg["campaigns"]
                    if search_val in sc["campaign_name"].lower()
                    or search_val in sc["code"].lower()
                    or search_val in sc["heading"].lower()
                    or search_val in sc["sub_heading"].lower()
                    or search_val in ctg["country"].lower()
                ]
                if matching_subs:
                    ctg_copy = dict(ctg)
                    ctg_copy["campaigns"] = matching_subs
                    ctg_copy["campaigns_count"] = len(matching_subs)
                    filtered_countries.append(ctg_copy)

            return {
                "platform": plat,
                "code_groups": filtered_codes,
                "heading_groups": filtered_headings,
                "country_groups": filtered_countries,
                "campaigns": filtered_camps,
                "total_codes": len(filtered_codes),
                "total_headings": len(filtered_headings),
                "total_countries": len(filtered_countries),
                "total_campaigns": len(filtered_camps),
                "currency": curr_selected,
                "batch": target_batch
            }

        return {
            "platform": plat,
            "code_groups": code_groups,
            "heading_groups": heading_groups,
            "country_groups": country_groups,
            "campaigns": campaign_records,
            "total_codes": len(code_groups),
            "total_headings": len(heading_groups),
            "total_countries": len(country_groups),
            "total_campaigns": len(campaign_records),
            "currency": curr_selected,
            "batch": target_batch
        }

    except Exception as e:
        print(f"[Error] Campaign payout breakdown error: {e}")
        return {
            "platform": plat,
            "code_groups": [], 
            "heading_groups": [], 
            "country_groups": [], 
            "campaigns": [], 
            "total_codes": 0, 
            "total_headings": 0, 
            "total_countries": 0, 
            "total_campaigns": 0, 
            "currency": currency or "GBP", 
            "batch": batch or "ALL"
        }


@router.get("/donors")
def get_payout_donors(
    company_id: Optional[str] = Query("rethink"),
    platform: Optional[str] = Query("launchgood", description="Platform: launchgood or paysuite"),
    currency: Optional[str] = Query("GBP", description="Filter by settlement currency"),
    batch: Optional[str] = Query("ALL", description="Filter by specific Transfer ID / Batch"),
    status: Optional[str] = Query("ALL", description="Filter by status: ALL, Paid, Unpaid"),
    search: Optional[str] = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=1000),
    sort_by: Optional[str] = "created_date",
    sort_order: Optional[str] = "desc",
    code: Optional[str] = None,
    heading: Optional[str] = None,
    country: Optional[str] = None,
    zakat: Optional[str] = None,
    campaign: Optional[str] = None
):
    """
    Returns rich, paginated donor-level payout transaction records just like Data Explorer.
    """
    plat = _clean_str(platform, "launchgood").lower()
    curr_selected = _clean_str(currency, "GBP").upper()
    target_batch = _clean_str(batch, "ALL")
    status_filter = _clean_str(status, "ALL").capitalize()
    search_val = _clean_str(search).lower()
    sort_col = _clean_str(sort_by, "created_date").lower()
    sort_dir = _clean_str(sort_order, "desc").lower()

    p_val = int(_clean_str(page, "1")) if _clean_str(page, "1").isdigit() else 1
    ps_val = int(_clean_str(page_size, "25")) if _clean_str(page_size, "25").isdigit() else 25

    try:
        df_all = _get_payout_data_from_db(platform=plat, company_id=company_id)
        if df_all.empty:
            return {
                "platform": plat,
                "total_records": 0,
                "page": p_val,
                "page_size": ps_val,
                "total_pages": 1,
                "records": [],
                "summary": {"total_gross": 0.0, "total_fees": 0.0, "total_net": 0.0, "count": 0},
                "currency": curr_selected,
                "batch": target_batch
            }

        df = df_all.copy()

        # Currency Filter
        if curr_selected in ["GBP", "USD"]:
            df = df[df["settlement_currency"] == curr_selected]

        # Batch / Transfer ID Filter
        if target_batch and target_batch.upper() != "ALL":
            target_clean = target_batch.replace(".0", "").replace("#", "").strip().lower()
            df = df[df["transfer_id"].astype(str).str.replace(".0", "").str.strip().str.lower() == target_clean]

        # Status Filter
        if status_filter in ["Paid", "Unpaid"]:
            df = df[df["status"] == status_filter]

        # Code Filter
        code_filter = _clean_str(code)
        if code_filter and code_filter.upper() != "ALL":
            df = df[df["code"].astype(str).str.strip().str.lower() == code_filter.lower()]

        # Heading Filter
        heading_filter = _clean_str(heading)
        if heading_filter and heading_filter.upper() != "ALL":
            df = df[df["heading"].astype(str).str.strip().str.lower() == heading_filter.lower()]

        # Country Filter
        country_filter = _clean_str(country)
        if country_filter and country_filter.upper() != "ALL":
            df = df[df["country"].astype(str).str.strip().str.lower() == country_filter.lower()]

        # Zakat Filter
        zakat_filter = _clean_str(zakat)
        if zakat_filter and zakat_filter.upper() != "ALL":
            df = df[df["zakat"].astype(str).str.strip().str.lower() == zakat_filter.lower()]

        # Campaign / Bank Ref Filter
        camp_filter = _clean_str(campaign)
        if camp_filter:
            df = df[df["campaign_name"].astype(str).str.lower().str.contains(camp_filter.lower(), na=False)]

        # Search Filter (Multi-token or text)
        if search_val:
            mask = (
                df["campaign_name"].astype(str).str.lower().str.contains(search_val, na=False) |
                df["code"].astype(str).str.lower().str.contains(search_val, na=False) |
                df["heading"].astype(str).str.lower().str.contains(search_val, na=False) |
                df["sub_heading"].astype(str).str.lower().str.contains(search_val, na=False) |
                df["country"].astype(str).str.lower().str.contains(search_val, na=False) |
                df["transfer_id"].astype(str).str.lower().str.contains(search_val, na=False)
            )
            for col in ["First Name", "Last Name", "Display Name", "Email", "Donation ID", "Donor ID", "Bank Ref", "Customer Ref"]:
                if col in df.columns:
                    mask |= df[col].astype(str).str.lower().str.contains(search_val, na=False)
            df = df[mask]

        total_records = len(df)
        total_gross = round(float(df["gross_amt"].sum()), 2) if not df.empty else 0.0
        total_fees = round(float(df["fee_amt"].sum()), 2) if not df.empty else 0.0
        total_net = round(float(df["net_amt"].sum()), 2) if not df.empty else 0.0

        if total_records == 0:
            return {
                "platform": plat,
                "total_records": 0,
                "page": p_val,
                "page_size": ps_val,
                "total_pages": 1,
                "records": [],
                "summary": {"total_gross": 0.0, "total_fees": 0.0, "total_net": 0.0, "count": 0},
                "currency": curr_selected,
                "batch": target_batch
            }

        # Sorting
        sort_map = {
            "gross_amount": "gross_amt",
            "gross": "gross_amt",
            "fees": "fee_amt",
            "processing_fees": "fee_amt",
            "net_amount": "net_amt",
            "net": "net_amt",
            "created_date": "Created Date (UTC)",
            "date": "Created Date (UTC)",
            "campaign_name": "campaign_name",
            "campaign": "campaign_name",
            "code": "code",
            "heading": "heading",
            "country": "country",
            "transfer_id": "transfer_id",
            "status": "status"
        }
        target_sort_col = sort_map.get(sort_col, "Created Date (UTC)")
        if target_sort_col in df.columns:
            is_asc = (sort_dir == "asc")
            df = df.sort_values(by=target_sort_col, ascending=is_asc)

        # Pagination
        total_pages = max(1, math.ceil(total_records / ps_val))
        p_val = min(p_val, total_pages)
        start_idx = (p_val - 1) * ps_val
        end_idx = min(start_idx + ps_val, total_records)
        paged_df = df.iloc[start_idx:end_idx]

        records = []
        for idx, r in paged_df.iterrows():
            gross = round(float(r.get("gross_amt", 0.0) or 0.0), 2)
            fee = round(float(r.get("fee_amt", 0.0) or 0.0), 2)
            net = round(float(r.get("net_amt", 0.0) or (gross - fee)), 2)
            fee_pct = round((fee / gross * 100), 2) if gross > 0 else 0.0

            d_id = str(r.get("Donation ID", r.get("Bank Ref", "")) or "").replace(".0", "").strip()
            t_id = str(r.get("transfer_id", "") or "").replace(".0", "").strip()

            fn = str(r.get("First Name", "") or "").strip()
            ln = str(r.get("Last Name", "") or "").strip()
            dn = str(r.get("Display Name", "") or "").strip()
            donor_name = dn if dn and dn.lower() != "nan" else (f"{fn} {ln}".strip() or "Anonymous Donor")

            records.append({
                "row_id": int(idx) if isinstance(idx, (int, float)) else str(idx),
                "donation_id": d_id or f"D-{idx}",
                "donor_name": donor_name,
                "first_name": fn,
                "last_name": ln,
                "display_name": dn,
                "email": str(r.get("Email", "") or "").strip(),
                "campaign_name": str(r.get("campaign_name", "") or "Unassigned"),
                "code": str(r.get("code", "") or "Unassigned"),
                "heading": str(r.get("heading", "") or "Unassigned"),
                "sub_heading": str(r.get("sub_heading", "") or "Unassigned"),
                "country": str(r.get("country", "") or "Unassigned"),
                "zakat": str(r.get("zakat", "") or "Unassigned"),
                "status": str(r.get("status", "Paid")),
                "gross_amount": gross,
                "processing_fees": fee,
                "net_amount": net,
                "fee_percentage": fee_pct,
                "transfer_id": t_id,
                "batch_label": str(r.get("batch_label", t_id)),
                "created_date": str(r.get("Created Date (UTC)", "") or r.get("Created Date", "") or r.get("Date of collection", "") or "N/A")[:10],
                "created_time": str(r.get("Created Time (UTC)", "") or r.get("Created Time", "") or ""),
                "payment_frequency": str(r.get("Payment Frequency", "Recurring" if plat == "paysuite" else "One-Time Payment") or "Recurring"),
                "billing_country": str(r.get("Billing Country", r.get("Country", "United Kingdom")) or "United Kingdom"),
                "currency": str(r.get("settlement_currency", curr_selected) or curr_selected),
                "platform": plat
            })

        return {
            "platform": plat,
            "total_records": total_records,
            "page": p_val,
            "page_size": ps_val,
            "total_pages": total_pages,
            "records": records,
            "summary": {
                "total_gross": total_gross,
                "total_fees": total_fees,
                "total_net": total_net,
                "count": total_records
            },
            "currency": curr_selected,
            "batch": target_batch
        }

    except Exception as e:
        print(f"[Error] get_payout_donors error: {e}")
        return {
            "platform": plat,
            "total_records": 0,
            "page": 1,
            "page_size": 25,
            "total_pages": 1,
            "records": [],
            "summary": {"total_gross": 0.0, "total_fees": 0.0, "total_net": 0.0, "count": 0},
            "currency": curr_selected,
            "batch": target_batch
        }


@router.get("/ledger")
def get_payout_ledger(
    company_id: Optional[str] = Query("rethink"),
    platform: Optional[str] = Query("launchgood", description="Platform: launchgood or paysuite"),
    currency: Optional[str] = Query("GBP", description="Filter by settlement currency"),
    batch: Optional[str] = Query("ALL", description="Filter by specific Transfer ID / Batch"),
    status: Optional[str] = Query("ALL", description="Filter by status"),
    search: Optional[str] = "",
    row_type: Optional[str] = Query("ALL", description="Filter by row type"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=250),
    sort_by: Optional[str] = "date",
    sort_order: Optional[str] = "desc"
):
    """Returns granular audit ledger rows with search, sorting, and pagination."""
    plat = _clean_str(platform, "launchgood").lower()
    curr_selected = _clean_str(currency, "GBP").upper()
    target_batch = _clean_str(batch, "ALL")
    status_filter = _clean_str(status, "ALL").capitalize()
    search_val = _clean_str(search).lower()
    type_filter = _clean_str(row_type, "ALL").lower()

    p_val = int(_clean_str(page, "1")) if _clean_str(page, "1").isdigit() else 1
    ps_val = int(_clean_str(page_size, "25")) if _clean_str(page_size, "25").isdigit() else 25

    try:
        df = _get_payout_data_from_db(platform=plat, company_id=company_id)
        if df.empty:
            return {"platform": plat, "total_records": 0, "page": p_val, "page_size": ps_val, "total_pages": 1, "records": []}

        if curr_selected in ["GBP", "USD"]:
            df = df[df["settlement_currency"] == curr_selected]

        if target_batch and target_batch.upper() != "ALL":
            target_clean = target_batch.replace(".0", "").replace("#", "").strip().lower()
            df = df[df["transfer_id"].astype(str).str.replace(".0", "").str.strip().str.lower() == target_clean]

        if status_filter in ["Paid", "Unpaid"]:
            df = df[df["status"] == status_filter]

        if type_filter and type_filter != "all":
            df = df[df["row_type"] == type_filter]

        if search_val:
            mask = df["campaign_name"].astype(str).str.lower().str.contains(search_val, na=False) | \
                   df["code"].astype(str).str.lower().str.contains(search_val, na=False) | \
                   df["transfer_id"].astype(str).str.lower().str.contains(search_val, na=False)
            df = df[mask]

        total_records = len(df)
        total_pages = max(1, math.ceil(total_records / ps_val))
        p_val = min(p_val, total_pages)
        start_idx = (p_val - 1) * ps_val
        end_idx = min(start_idx + ps_val, total_records)
        paged_df = df.iloc[start_idx:end_idx]

        records = []
        for idx, r in paged_df.iterrows():
            records.append({
                "row_id": int(idx) if isinstance(idx, (int, float)) else str(idx),
                "transfer_id": str(r.get("transfer_id", "")),
                "batch_label": str(r.get("batch_label", r.get("transfer_id", ""))),
                "campaign_name": str(r.get("campaign_name", "")),
                "code": str(r.get("code", "")),
                "heading": str(r.get("heading", "")),
                "sub_heading": str(r.get("sub_heading", "")),
                "country": str(r.get("country", "")),
                "zakat": str(r.get("zakat", "")),
                "status": str(r.get("status", "Paid")),
                "row_type": str(r.get("row_type", "")).capitalize(),
                "gross_amount": round(float(r.get("gross_amt", 0.0) or 0.0), 2),
                "processing_fees": round(float(r.get("fee_amt", 0.0) or 0.0), 2),
                "net_amount": round(float(r.get("net_amt", 0.0) or 0.0), 2),
                "created_date": str(r.get("Created Date (UTC)", r.get("Date of collection", "N/A")))[:10],
                "donor_name": str(r.get("Display Name", r.get("donor_name", ""))),
                "email": str(r.get("Email", ""))
            })

        return {
            "platform": plat,
            "total_records": total_records,
            "page": p_val,
            "page_size": ps_val,
            "total_pages": total_pages,
            "records": records
        }

    except Exception as e:
        print(f"[Error] get_payout_ledger error: {e}")
        return {"platform": plat, "total_records": 0, "page": 1, "page_size": 25, "total_pages": 1, "records": []}


class UpdatePayoutClassificationRequest(BaseModel):
    user_role: str
    campaign_name: str
    code: str
    company_id: Optional[str] = "rethink"
    heading: Optional[str] = "Unassigned"
    sub_heading: Optional[str] = "Unassigned"
    country: Optional[str] = "Unassigned"
    zakat_eligibility: Optional[str] = "Unassigned"
    platform: Optional[str] = "launchgood"
    can_edit: Optional[bool] = True


@router.post("/update-classification")
def update_payout_classification(payload: UpdatePayoutClassificationRequest):
    """
    Updates classification for a campaign / Direct Debit from Payouts and synchronizes across all tables and caches in real time.
    """
    if payload.company_id and str(payload.company_id).strip().lower() == "all":
        raise HTTPException(
            status_code=400,
            detail="Modifications are disabled in consolidated 'All Companies' mode. Please select a specific company to update classifications."
        )

    if payload.user_role not in ["super_admin", "admin"]:
        raise HTTPException(
            status_code=403,
            detail="Classification edits are restricted to authorized accounts."
        )

    target_cid = _clean_str(payload.company_id, "rethink").lower()
    plat = _clean_str(payload.platform, "launchgood").lower()
    cname = fix_mojibake(payload.campaign_name).strip()
    code = str(payload.code).strip().upper()
    heading = fix_mojibake(payload.heading).strip() if payload.heading else "Unassigned"
    sub_heading = fix_mojibake(payload.sub_heading).strip() if payload.sub_heading else "Unassigned"
    country = fix_mojibake(payload.country).strip() if payload.country else ("ALL" if plat == "paysuite" else "Unassigned")
    zakat = payload.zakat_eligibility if payload.zakat_eligibility else ("Non-Zakat" if plat == "paysuite" else "Unassigned")

    if not cname or not code:
        raise HTTPException(status_code=400, detail="Campaign Name / Bank Ref and Code are required.")

    code_map = get_code_to_classification_map(company_id=target_cid)
    if code_map and code.lower() in code_map:
        cm = code_map[code.lower()]
        if heading in ["", "Unassigned"] and cm.get("Heading"):
            heading = cm["Heading"]
        if sub_heading in ["", "Unassigned"] and cm.get("Sub-Heading"):
            sub_heading = cm["Sub-Heading"]
        if country in ["", "Unassigned", "ALL"] and cm.get("Country"):
            country = cm["Country"]
        if zakat in ["", "Unassigned", "Non-Zakat"] and cm.get("Zakat Eligibility"):
            zakat = cm["Zakat Eligibility"]

    # 1. Update SQLite platform_campaign_mappings
    with _DB_LOCK:
        conn = get_db_connection(timeout=60.0)
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO platform_campaign_mappings (company_id, platform, campaign_name, code, community_name, is_primary)
                    VALUES (?, ?, ?, ?, 'Payouts', 1)
                    ON CONFLICT(company_id, platform, campaign_name, code) DO UPDATE SET
                        is_primary = 1,
                        updated_at = CURRENT_TIMESTAMP
                """, (target_cid, plat, cname, code))
        finally:
            conn.close()

    # 2. Synchronize to donations and payout settlements
    if plat == "paysuite":
        ps_matrix = get_paysuite_classification_matrix(company_id=target_cid)
        sync_matrix_classifications_to_donors(ps_matrix, company_id=target_cid)
    else:
        matrix_df = get_classification_matrix(company_id=target_cid)
        sync_matrix_classifications_to_donors(matrix_df, company_id=target_cid)

    # 3. Invalidate caches
    invalidate_payouts_cache(company_id=target_cid)
    invalidate_data_cache(company_id=target_cid)
    get_code_to_classification_map(force_reload=True, company_id=target_cid)

    try:
        from backend.api.events import broadcast_event_sync
        broadcast_event_sync("MATRIX_UPDATED", {"platform": plat, "campaign": cname, "company_id": target_cid})
    except Exception:
        pass

    return {
        "status": "success",
        "message": f"Successfully updated classification for '{cname}' ({code}) for company '{target_cid}' and synchronized across Payouts, Donations, and Classification Matrix!",
        "updated_rule": {
            "campaign_name": cname,
            "code": code,
            "heading": heading,
            "sub_heading": sub_heading,
            "country": country,
            "zakat_eligibility": zakat,
            "platform": plat,
            "company_id": target_cid
        }
    }


@router.get("/export")
def export_payouts_excel(
    company_id: Optional[str] = Query("rethink"),
    platform: Optional[str] = Query("launchgood", description="Platform: launchgood or paysuite"),
    currency: Optional[str] = Query("ALL", description="Currency filter"),
    batch: Optional[str] = Query("ALL", description="Filter by Transfer ID / Batch"),
    status: Optional[str] = Query("ALL", description="Filter by status"),
    search: Optional[str] = None,
    code: Optional[str] = None
):
    """Generates and exports a comprehensive multi-sheet Excel (.xlsx) reconciliation report respecting all active filters."""
    plat = _clean_str(platform, "launchgood").lower()
    curr_selected = str(currency).strip().upper() if isinstance(currency, str) else "ALL"
    target_batch = str(batch or "ALL").strip()
    status_filter = str(status or "ALL").strip()
    search_val = _clean_str(search)
    code_val = _clean_str(code)

    try:
        summary_data = get_payouts_summary(platform=plat, company_id=company_id, currency=curr_selected, batch=target_batch, status=status_filter)
        camp_data = get_campaign_payout_breakdown(platform=plat, company_id=company_id, currency=curr_selected, batch=target_batch, status=status_filter, search=search_val)
        
        # Batches
        batch_data = get_payout_batches(platform=plat, company_id=company_id, currency=curr_selected, status=status_filter, search=search_val, page_size=1000)
        batches_list = batch_data.get("batches", [])
        if target_batch and target_batch.upper() != "ALL":
            target_clean = target_batch.replace(".0", "").replace("#", "").strip().lower()
            batches_list = [b for b in batches_list if str(b.get("transfer_id", "")).replace(".0", "").strip().lower() == target_clean]

        # Donors
        donors_data = get_payout_donors(
            platform=plat,
            currency=curr_selected,
            batch=target_batch,
            status=status_filter,
            search=search_val,
            code=code_val if code_val and code_val.upper() != "ALL" else None,
            page_size=50000
        )
        disb = summary_data.get("disbursement_summary", {})
        ledger_breakdown = summary_data.get("ledger_breakdown", [])

        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        header_color = "78350F" if plat == "paysuite" else "065F46" # Amber dark vs Emerald dark
        header_fill = PatternFill(start_color=header_color, end_color=header_color, fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        regular_font = Font(name="Calibri", size=11)
        thin_border = Border(
            left=Side(style="thin", color="E5E7EB"),
            right=Side(style="thin", color="E5E7EB"),
            top=Side(style="thin", color="E5E7EB"),
            bottom=Side(style="thin", color="E5E7EB")
        )

        # -----------------------------------------------------------------
        # Sheet 1: Executive / Disbursement Summary
        # -----------------------------------------------------------------
        ws1 = wb.create_sheet(title="Executive Summary")
        filter_subtitle = f"Active Filter: Platform={plat.title()} | Batch/Cycle={target_batch} | Status={status_filter} | Currency={curr_selected}"
        
        if plat == "paysuite":
            ws1.append(["Reconciliation Summary Metric", "Transaction Count", f"Amount Value ({curr_selected})", filter_subtitle])
            disb_rows = [
                ["Total Direct Debit Collections", disb.get("gross_donations_count", 0), disb.get("gross_donations", 0.0), "All Direct Debit collection records presented"],
                ["Paid Collections", disb.get("paid_count", 0), disb.get("paid_amount", 0.0), "Successfully collected and settled Direct Debits"],
                ["Unpaid / Failed Collections", disb.get("unpaid_count", 0), disb.get("unpaid_amount", 0.0), "Failed, uncollected, or cancelled debit items"],
                ["Processing Fees", "", disb.get("processing_fees", 0.0), "Platform processing fees paid"],
                ["Collection Success Rate", "", f"{disb.get('collection_rate', 100.0)}%", "Percentage of successful collections"],
                ["Net Payout / Disbursed Amount", disb.get("total_disbursement_count", 0), disb.get("total_disbursement", 0.0), "Total net funds disbursed into charity account"]
            ]
        else:
            ws1.append(["Disbursement Summary Line Item", "Transaction Count", f"Amount Value ({curr_selected})", filter_subtitle])
            disb_rows = [
                ["Gross Donations / Contributions", disb.get("gross_donations_count", 0), disb.get("gross_donations", 0.0), "Gross donor contributions received"],
                ["Refunds", disb.get("refunds_count", 0), disb.get("refunds", 0.0), "Donor transaction refund deductions"],
                ["Refunds Failed", disb.get("refunds_failed_count", 0), disb.get("refunds_failed", 0.0), "Failed refund attempts"],
                ["Chargebacks", disb.get("chargebacks_count", 0), disb.get("chargebacks", 0.0), "Disputed donor transactions"],
                ["Chargebacks Reversed", disb.get("chargebacks_reversed_count", 0), disb.get("chargebacks_reversed", 0.0), "Resolved / won chargebacks"],
                ["Net Sales", disb.get("net_sales_count", 0), disb.get("net_sales", 0.0), "Gross donations minus refunds"],
                ["Processing Fees", "", disb.get("processing_fees", 0.0), "Credit card and platform processing fees"],
                ["Non Processing Fees", "", disb.get("non_processing_fees", 0.0), "Other non-processing fees"],
                ["Manual Adjustments Total (Zakat donation fees)", disb.get("manual_adjustments_count", 0), disb.get("manual_adjustments", 0.0), "Manual account adjustments and fees"],
                ["Reserve Adjustment", disb.get("reserve_adjustment_count", 0), disb.get("reserve_adjustment", 0.0), "Rolling reserve funds hold and release"],
                ["Foreign Exchange", disb.get("foreign_exchange_count", 0), disb.get("foreign_exchange", 0.0), "Foreign currency conversions into settlement account"],
                ["Total Disbursement", disb.get("total_disbursement_count", 0), disb.get("total_disbursement", 0.0), "Net amount disbursed to charity bank account"]
            ]
        for r in disb_rows:
            ws1.append(r)

        # -----------------------------------------------------------------
        # Sheet 2: Code Breakdown
        # -----------------------------------------------------------------
        ws2 = wb.create_sheet(title="Code Breakdown")
        ws2.append(["Classification Code", "Heading", "Sub-Heading", "Country", "Zakat Eligibility", "Contributing References", "Transactions Count", f"Gross Amount ({curr_selected})", f"Fees ({curr_selected})", "Fee Ratio (%)", f"Net Settlement ({curr_selected})"])
        for cg in camp_data.get("code_groups", []):
            ws2.append([
                cg.get("code", ""),
                cg.get("heading", ""),
                cg.get("sub_heading", ""),
                cg.get("country", ""),
                cg.get("zakat", ""),
                cg.get("campaigns_count", 0),
                cg.get("donations_count", 0),
                cg.get("gross_amount", 0.0),
                cg.get("processing_fees", 0.0),
                f"{cg.get('fee_percentage', 0.0)}%",
                cg.get("transfer_amount", 0.0)
            ])

        # -----------------------------------------------------------------
        # Sheet 3: Campaign / Direct Debit Breakdown
        # -----------------------------------------------------------------
        ws3 = wb.create_sheet(title="Campaign & Ref Breakdown" if plat == "paysuite" else "Campaign Breakdown")
        first_col_title = "Direct Debit Ref (Bank Ref)" if plat == "paysuite" else "Campaign Name"
        ws3.append([first_col_title, "Classification Code", "Heading", "Sub-Heading", "Country", "Zakat Eligibility", "Transactions Count", f"Gross Amount ({curr_selected})", f"Fees ({curr_selected})", "Fee Ratio (%)", f"Net Settlement ({curr_selected})"])
        for c in camp_data.get("campaigns", []):
            ws3.append([
                c.get("campaign_name", ""),
                c.get("code", ""),
                c.get("heading", ""),
                c.get("sub_heading", ""),
                c.get("country", ""),
                c.get("zakat", ""),
                c.get("donations_count", 0),
                c.get("gross_amount", 0.0),
                c.get("processing_fees", 0.0),
                f"{c.get('fee_percentage', 0.0)}%",
                c.get("transfer_amount", 0.0)
            ])

        # -----------------------------------------------------------------
        # Sheet 4: Transfer Batches / Settlement Cycles
        # -----------------------------------------------------------------
        ws4 = wb.create_sheet(title="Monthly Batches" if plat == "paysuite" else "Transfer Batches")
        ws4.append(["Batch ID / Cycle", "Settlement Date", "Currency", "References Count", "Collections Count", "Gross Amount", "Fees", "Net Settlement"])
        for b in batches_list:
            ws4.append([
                b.get("batch_label", f"#{b.get('transfer_id', '')}"),
                b.get("created_date", ""),
                b.get("currency", "GBP"),
                b.get("campaigns_count", 0),
                b.get("donations_count", 0),
                b.get("gross_amount", 0.0),
                b.get("processing_fees", 0.0),
                b.get("transfer_amount", 0.0)
            ])

        # -----------------------------------------------------------------
        # Sheet 5: Donor Transactions
        # -----------------------------------------------------------------
        ws5 = wb.create_sheet(title="Donor Transactions")
        id_title = "Bank Ref / Ref ID" if plat == "paysuite" else "Donation ID"
        ws5.append([id_title, "Donor Name", "Email", "Reference / Campaign", "Code", "Heading", "Country", "Zakat", "Status", f"Gross ({curr_selected})", f"Fees ({curr_selected})", f"Net ({curr_selected})", "Batch", "Date"])
        for d in donors_data.get("records", []):
            ws5.append([
                d.get("donation_id", ""),
                d.get("donor_name", ""),
                d.get("email", ""),
                d.get("campaign_name", ""),
                d.get("code", ""),
                d.get("heading", ""),
                d.get("country", ""),
                d.get("zakat", ""),
                d.get("status", "Paid"),
                d.get("gross_amount", 0.0),
                d.get("processing_fees", 0.0),
                d.get("net_amount", 0.0),
                d.get("transfer_id", ""),
                d.get("created_date", "")
            ])

        # -----------------------------------------------------------------
        # Sheet 6: Ledger Audit
        # -----------------------------------------------------------------
        ws6 = wb.create_sheet(title="Ledger Audit")
        ws6.append(["Row Type", "Description", "Row Count", "Gross Amount", "Processing Fees", "Net Amount"])
        for l in ledger_breakdown:
            ws6.append([
                l.get("row_type", ""),
                l.get("description", ""),
                l.get("count", 0),
                l.get("gross_amount", 0.0),
                l.get("processing_fees", 0.0),
                l.get("net_amount", 0.0)
            ])

        for ws in wb.worksheets:
            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            ws.row_dimensions[1].height = 26

            for row in ws.iter_rows(min_row=2):
                for cell in row:
                    cell.font = regular_font
                    cell.border = thin_border
                    if isinstance(cell.value, float):
                        cell.number_format = "#,##0.00"

            for col in ws.columns:
                max_len = 0
                col_letter = get_column_letter(col[0].column)
                for cell in col:
                    val = str(cell.value or "")
                    if len(val) > max_len:
                        max_len = len(val)
                ws.column_dimensions[col_letter].width = min(max(max_len + 4, 14), 50)

        output = io.BytesIO()
        wb.save(output)
        content_bytes = output.getvalue()

        batch_slug = f"_batch_{target_batch.replace(' ', '_')}" if target_batch != "ALL" else ""
        status_slug = f"_{status_filter.lower()}" if status_filter != "ALL" else ""
        filename = f"{plat}_payout_reconciliation{batch_slug}{status_slug}_{curr_selected.lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return Response(
            content=content_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except Exception as e:
        print(f"[Error] Excel reconciliation export error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate reconciliation report: {str(e)}")
