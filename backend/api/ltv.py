from typing import Optional
from fastapi import APIRouter, Query
from config.settings import DONOR_TIER_ORDER
from core.data_processor import load_data

router = APIRouter(prefix="/api/ltv", tags=["Lifetime LTV & Segmentation"])


from backend.api.donors import _apply_filters


def _get_amount_column(df):
    for col in [
        "Total Online Donations Net Amount in Settled Currency",
        "Donation Amount in Project Currency (May be approx.)",
        "Donation Amount (in Donation Currency)"
    ]:
        if col in df.columns:
            return col
    return None


@router.get("/summary")
def get_ltv_summary(
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
    end_date: Optional[str] = None
):
    df_raw = load_data(company_id=company_id)
    df = _apply_filters(
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
        company_id=company_id
    )
    col_amount = _get_amount_column(df)

    if df.empty or not col_amount or "Lifetime Donor Classification" not in df.columns:
        return []

    ltv_summary = df.groupby("Lifetime Donor Classification").agg(
        total_raised=(col_amount, "sum"),
        donation_count=(col_amount, "count"),
        avg_donation=(col_amount, "mean")
    ).reset_index()

    ltv_summary["tier_order"] = ltv_summary["Lifetime Donor Classification"].map(
        {t: i for i, t in enumerate(DONOR_TIER_ORDER)}
    )
    ltv_summary = ltv_summary.sort_values("tier_order").drop(columns=["tier_order"])
    ltv_summary.rename(columns={"Lifetime Donor Classification": "tier"}, inplace=True)

    ltv_summary["total_raised"] = ltv_summary["total_raised"].round(2)
    ltv_summary["avg_donation"] = ltv_summary["avg_donation"].round(2)

    return ltv_summary.to_dict(orient="records")
