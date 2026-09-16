from typing import Optional
import pandas as pd
from fastapi import APIRouter, Query
from core.data_processor import load_data
from backend.api.donors import _apply_filters

router = APIRouter(prefix="/api/overview", tags=["Executive Overview"])


def _get_amount_column(df):
    for col in [
        "Total Online Donations Net Amount in Settled Currency",
        "Donation Amount in Project Currency (May be approx.)",
        "Donation Amount (in Donation Currency)"
    ]:
        if col in df.columns:
            return col
    return None


@router.get("/timeline")
def get_overview_timeline(
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
    df = _apply_filters(df_raw, payment_type, tier, source, heading, subheading, country, code, zakat, donor_country, campaign_search, gift_aid, start_date, end_date, company_id=company_id)
    col_amount = _get_amount_column(df)
    col_date = "Created Date (UTC)"

    if df.empty or not col_amount or col_date not in df.columns:
        return []

    try:
        df_clean = df.dropna(subset=[col_date]).copy()
        df_clean[col_date] = pd.to_datetime(df_clean[col_date], errors='coerce')
        df_clean = df_clean.dropna(subset=[col_date])

        df_time = df_clean.set_index(col_date).resample('D')[col_amount].agg(['sum', 'count']).reset_index()
        df_time.columns = ["date", "total_raised", "donation_count"]
        df_time["date"] = df_time["date"].dt.strftime('%Y-%m-%d')
        df_time["total_raised"] = df_time["total_raised"].round(2)

        return df_time.to_dict(orient="records")
    except Exception as e:
        print(f"Timeline API notice: {e}")
        return []


@router.get("/headings")
def get_overview_headings(
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
    df = _apply_filters(df_raw, payment_type, tier, source, heading, subheading, country, code, zakat, donor_country, campaign_search, gift_aid, start_date, end_date, company_id=company_id)
    col_amount = _get_amount_column(df)
    col_heading = "Heading"

    if df.empty or not col_amount or col_heading not in df.columns:
        return []

    df_head = df.groupby(col_heading)[col_amount].sum().reset_index()
    df_head = df_head.sort_values(by=col_amount, ascending=False).head(7)
    df_head.columns = ["category", "total_raised"]
    df_head["total_raised"] = df_head["total_raised"].round(2)

    return df_head.to_dict(orient="records")


@router.get("/campaigns")
def get_overview_top_campaigns(
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
    df = _apply_filters(df_raw, payment_type, tier, source, heading, subheading, country, code, zakat, donor_country, campaign_search, gift_aid, start_date, end_date, company_id=company_id)
    col_amount = _get_amount_column(df)
    col_campaign = "Campaign Name"

    if df.empty or not col_amount or col_campaign not in df.columns:
        return []

    df_camp = df.groupby(col_campaign)[col_amount].sum().reset_index()
    df_camp = df_camp.sort_values(by=col_amount, ascending=False).head(10)
    df_camp.columns = ["campaign", "total_raised"]
    df_camp["total_raised"] = df_camp["total_raised"].round(2)

    return df_camp.to_dict(orient="records")


@router.get("/subheadings")
def get_overview_subheadings(
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
    df = _apply_filters(df_raw, payment_type, tier, source, heading, subheading, country, code, zakat, donor_country, campaign_search, gift_aid, start_date, end_date, company_id=company_id)
    col_amount = _get_amount_column(df)
    col_sub = "Sub-Heading"

    if df.empty or not col_amount or col_sub not in df.columns:
        return []

    df_sub = df.groupby(col_sub)[col_amount].sum().reset_index()
    df_sub = df_sub.sort_values(by=col_amount, ascending=False).head(10)
    df_sub.columns = ["sub_heading", "total_raised"]
    df_sub["total_raised"] = df_sub["total_raised"].round(2)

    return df_sub.to_dict(orient="records")
