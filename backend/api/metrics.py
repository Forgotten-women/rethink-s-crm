from typing import Optional
from fastapi import APIRouter, Query
import pandas as pd
from core.data_processor import load_data
from backend.api.donors import _apply_filters

router = APIRouter(prefix="/api/metrics", tags=["Metrics"])


@router.get("/summary")
def get_metrics_summary(
    company_id: Optional[str] = Query("rethink"),
    payment_type: Optional[str] = None,
    tier: Optional[str] = None,
    source: Optional[str] = None,
    heading: Optional[str] = None,
    subheading: Optional[str] = None,
    country: Optional[str] = None,
    code: Optional[str] = None,
    zakat: Optional[str] = None,
    donor_country: Optional[str] = None,
    campaign_search: Optional[str] = None,
    gift_aid: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    programme_fund: Optional[str] = None
):
    df_raw = load_data(company_id=company_id)
    df = _apply_filters(df_raw, payment_type, tier, source, heading, subheading, country, code, zakat, donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund=programme_fund, company_id=company_id)

    if df.empty:
        return {
            "total_raised": 0.0,
            "total_txns": 0,
            "avg_donation": 0.0,
            "top_category": "N/A",
            "recurring_pct": 0.0,
            "top_donor_seg": "N/A"
        }

    col_amount = "Total Online Donations Net Amount in Settled Currency"
    if col_amount not in df.columns:
        col_amount = "Donation Amount in Project Currency (May be approx.)"

    col_heading = "Heading"

    amount_series = pd.to_numeric(df[col_amount], errors='coerce').fillna(0.0) if col_amount in df.columns else pd.Series(0.0, index=df.index)

    total_raised = float(amount_series.sum())
    total_txns = int(len(df))
    avg_donation = float(total_raised / total_txns) if total_txns > 0 else 0.0

    gift_aid_estimate = 0.0
    if col_amount in df.columns:
        # Check LaunchGood, GiveBright, and Website columns
        mask_lg = pd.Series(False, index=df.index)
        if "Gift Aid (yes or no)" in df.columns:
            mask_lg = df["Gift Aid (yes or no)"].astype(str).str.strip().str.lower().isin(['yes', '1', 'true'])
            
        mask_gb = pd.Series(False, index=df.index)
        if "is_giftaid" in df.columns:
            mask_gb = df["is_giftaid"].astype(str).str.strip().str.lower().isin(['1', '1.0', 'true', 'yes'])
            
        gift_aid_donations = amount_series[mask_lg | mask_gb]
        gift_aid_total_donations = float(gift_aid_donations.sum())
        gift_aid_estimate = gift_aid_total_donations * 0.25

    top_cat = "N/A"
    if col_heading in df.columns and not df[col_heading].dropna().empty:
        modes = df[col_heading].mode()
        if not modes.empty:
            top_cat = str(modes[0])

    recurring_pct = 0.0
    if "Payment Frequency" in df.columns and total_txns > 0:
        rec_count = (df["Payment Frequency"] == "Recurring Payment").sum()
        recurring_pct = float((rec_count / total_txns) * 100.0)

    top_donor_seg = "N/A"
    if "Lifetime Donor Classification" in df.columns and not df["Lifetime Donor Classification"].dropna().empty:
        seg_modes = df["Lifetime Donor Classification"].mode()
        if not seg_modes.empty:
            top_donor_seg = str(seg_modes[0])

    return {
        "total_raised": round(total_raised, 2),
        "total_txns": total_txns,
        "avg_donation": round(avg_donation, 2),
        "gift_aid_estimate": round(gift_aid_estimate, 2),
        "top_category": top_cat,
        "recurring_pct": round(recurring_pct, 1),
        "top_donor_seg": top_donor_seg
    }
