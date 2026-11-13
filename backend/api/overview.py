import math
import re
import tempfile
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from core.cache import cached
from core.data_processor import load_data
from core.fast_export import dataframe_to_fast_csv
from backend.api.donors import _apply_filters, _cleanup_temp_file

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


def _filtered(company_id, payment_type, tier, source, heading, subheading, country, code, zakat,
              donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund=None):
    df_raw = load_data(company_id=company_id)
    return _apply_filters(df_raw, payment_type, tier, source, heading, subheading, country, code, zakat,
                          donor_country, campaign_search, gift_aid, start_date, end_date,
                          programme_fund=programme_fund, company_id=company_id)


def _donor_count(df):
    if "Email" in df.columns:
        em = df["Email"].astype(str).str.strip().str.lower()
        return int(em[~em.isin(["", "nan", "none", "null"])].nunique())
    return 0


def _clean_str(s):
    v = s.fillna("").astype(str).str.strip()
    return v.where(~v.str.lower().isin(["", "nan", "none", "null"]), "")


def _donor_name_series(df):
    if "First Name" in df.columns and "Last Name" in df.columns:
        s = (_clean_str(df["First Name"]) + " " + _clean_str(df["Last Name"])).str.strip()
        if "Display Name" in df.columns:
            s = s.where(s != "", _clean_str(df["Display Name"]))
        return s
    if "Display Name" in df.columns:
        return _clean_str(df["Display Name"])
    return pd.Series("", index=df.index)


def _page_label_series(df):
    """Which page a gift came through: the fundraiser page when there is one, otherwise the campaign itself."""
    label = pd.Series("", index=df.index)
    for col in ("fundraiser_name", "Community Name", "Source User Profile"):
        if col in df.columns:
            v = _clean_str(df[col])
            label = label.where(label != "", v)
    return label.where(label != "", "Main campaign page")


def _group_table(df, by, col_amount, label_name, top=None):
    if df.empty:
        return []
    g = df.groupby(by)[col_amount].agg(["sum", "count"]).reset_index()
    g.columns = [label_name, "total_raised", "donation_count"]
    g = g.sort_values("total_raised", ascending=False)
    if top:
        g = g.head(top)
    g["total_raised"] = g["total_raised"].astype(float).round(2)
    g["donation_count"] = g["donation_count"].astype(int)
    return g.to_dict(orient="records")


@router.get("/timeline")
@cached(scopes=["donations", "classification"], ttl=21600)
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
    end_date: Optional[str] = None,
    programme_fund: Optional[str] = None
):
    df = _filtered(company_id, payment_type, tier, source, heading, subheading, country, code, zakat,
                   donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund)
    col_amount = _get_amount_column(df)
    col_date = "_parsed_date" if ("_parsed_date" in df.columns and df["_parsed_date"].dropna().astype(str).str.strip().ne("").any()) else ("Created Date (UTC)" if "Created Date (UTC)" in df.columns else "Date")

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
@cached(scopes=["donations", "classification"], ttl=21600)
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
    end_date: Optional[str] = None,
    programme_fund: Optional[str] = None,
    limit: int = Query(7, ge=0, le=500)
):
    df = _filtered(company_id, payment_type, tier, source, heading, subheading, country, code, zakat,
                   donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund)
    col_amount = _get_amount_column(df)
    if df.empty or not col_amount or "Heading" not in df.columns:
        return []
    rows = _group_table(df, "Heading", col_amount, "category", top=limit or None)
    return rows


@router.get("/campaigns")
@cached(scopes=["donations", "classification"], ttl=21600)
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
    end_date: Optional[str] = None,
    programme_fund: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(8, ge=1, le=100)
):
    df = _filtered(company_id, payment_type, tier, source, heading, subheading, country, code, zakat,
                   donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund)
    col_amount = _get_amount_column(df)
    if df.empty or not col_amount or "Campaign Name" not in df.columns:
        return {"items": [], "total_count": 0, "page": 1, "total_pages": 1, "max_raised": 0.0}

    df_camp = df.groupby("Campaign Name")[col_amount].agg(["sum", "count"]).reset_index()
    df_camp.columns = ["campaign", "total_raised", "donation_count"]
    df_camp = df_camp.sort_values("total_raised", ascending=False)
    total_count = len(df_camp)
    max_raised = float(df_camp["total_raised"].iloc[0]) if total_count else 0.0
    pages = max(1, math.ceil(total_count / page_size))
    page = min(page, pages)
    page_df = df_camp.iloc[(page - 1) * page_size: page * page_size].copy()
    page_df["total_raised"] = page_df["total_raised"].astype(float).round(2)
    page_df["donation_count"] = page_df["donation_count"].astype(int)
    return {
        "items": page_df.to_dict(orient="records"),
        "total_count": total_count,
        "page": page,
        "total_pages": pages,
        "max_raised": round(max_raised, 2)
    }


@router.get("/subheadings")
@cached(scopes=["donations", "classification"], ttl=21600)
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
    end_date: Optional[str] = None,
    programme_fund: Optional[str] = None,
    limit: int = Query(10, ge=0, le=500)
):
    df = _filtered(company_id, payment_type, tier, source, heading, subheading, country, code, zakat,
                   donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund)
    col_amount = _get_amount_column(df)
    if df.empty or not col_amount or "Sub-Heading" not in df.columns:
        return []
    return _group_table(df, "Sub-Heading", col_amount, "sub_heading", top=limit or None)


@router.get("/campaign-breakdown")
@cached(scopes=["donations", "classification"], ttl=21600)
def get_campaign_breakdown(
    campaign: str = Query(..., description="Exact campaign name"),
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
    """Where one campaign's money came from: pages, platforms, payment types, monthly trend and recent gifts."""
    df = _filtered(company_id, payment_type, tier, source, heading, subheading, country, code, zakat,
                   donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund)
    col_amount = _get_amount_column(df)
    if df.empty or not col_amount or "Campaign Name" not in df.columns:
        raise HTTPException(status_code=404, detail="No data for this campaign under the current filters.")
    total_all = float(df[col_amount].sum())
    c_df = df[df["Campaign Name"].astype(str).str.strip().str.lower() == campaign.strip().lower()].copy()
    if c_df.empty:
        raise HTTPException(status_code=404, detail="No data for this campaign under the current filters.")

    total = float(c_df[col_amount].sum())
    c_df["_page"] = _page_label_series(c_df)

    monthly = []
    date_col = "_parsed_date" if "_parsed_date" in c_df.columns else ("Created Date (UTC)" if "Created Date (UTC)" in c_df.columns else None)
    if date_col:
        d = c_df.dropna(subset=[date_col]).copy()
        d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
        d = d.dropna(subset=[date_col])
        if not d.empty:
            m = d.set_index(date_col).resample("MS")[col_amount].agg(["sum", "count"]).reset_index().tail(24)
            monthly = [{"month": r[date_col].strftime("%Y-%m"), "total_raised": round(float(r["sum"]), 2),
                        "donation_count": int(r["count"])} for _, r in m.iterrows()]

    recent = []
    if date_col:
        r_df = c_df.copy()
        r_df["_name"] = _donor_name_series(r_df)
        r_df["_dt"] = pd.to_datetime(r_df[date_col], errors="coerce")
        r_df = r_df.sort_values("_dt", ascending=False).head(100)
        for _, r in r_df.iterrows():
            recent.append({
                "date": r["_dt"].strftime("%Y-%m-%d") if pd.notna(r["_dt"]) else "",
                "donor": str(r["_name"]).strip() or "Anonymous",
                "amount": round(float(r[col_amount]) if pd.notna(r[col_amount]) else 0.0, 2),
                "platform": str(r.get("Platform") or "").strip(),
                "page": str(r.get("_page") or "").strip(),
            })

    return {
        "campaign": campaign,
        "total_raised": round(total, 2),
        "donation_count": int(len(c_df)),
        "donor_count": _donor_count(c_df),
        "pct_of_total": round(total / total_all * 100, 1) if total_all else 0.0,
        "average_gift": round(total / len(c_df), 2) if len(c_df) else 0.0,
        "by_page": _group_table(c_df, "_page", col_amount, "page", top=20),
        "by_platform": _group_table(c_df, "Platform", col_amount, "platform") if "Platform" in c_df.columns else [],
        "by_payment_type": _group_table(c_df, "Payment Frequency", col_amount, "payment_type") if "Payment Frequency" in c_df.columns else [],
        "monthly": monthly,
        "recent_donations": recent,
    }


@router.get("/category-breakdown")
@cached(scopes=["donations", "classification"], ttl=21600)
def get_category_breakdown(
    category: str = Query(..., description="Heading (or Sub-Heading with kind=subheading)"),
    kind: str = Query("heading", pattern="^(heading|subheading)$"),
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
    """Where one category's money came from (campaigns, platforms) and its share of all funds raised."""
    # The clicked category is measured against the other filters, so its own heading filter is left out
    if kind == "heading":
        heading = None
    else:
        subheading = None
    df = _filtered(company_id, payment_type, tier, source, heading, subheading, country, code, zakat,
                   donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund)
    col = "Heading" if kind == "heading" else "Sub-Heading"
    col_amount = _get_amount_column(df)
    if df.empty or not col_amount or col not in df.columns:
        raise HTTPException(status_code=404, detail="No data for this category under the current filters.")
    total_all = float(df[col_amount].sum())
    c_df = df[df[col].astype(str).str.strip().str.lower() == category.strip().lower()].copy()
    if c_df.empty:
        raise HTTPException(status_code=404, detail="No data for this category under the current filters.")
    total = float(c_df[col_amount].sum())
    out = {
        "category": category,
        "kind": kind,
        "total_raised": round(total, 2),
        "donation_count": int(len(c_df)),
        "donor_count": _donor_count(c_df),
        "pct_of_total": round(total / total_all * 100, 1) if total_all else 0.0,
        "total_all_filtered": round(total_all, 2),
        "by_campaign": _group_table(c_df, "Campaign Name", col_amount, "campaign", top=15) if "Campaign Name" in c_df.columns else [],
        "by_platform": _group_table(c_df, "Platform", col_amount, "platform") if "Platform" in c_df.columns else [],
    }
    if kind == "heading" and "Sub-Heading" in c_df.columns:
        out["by_subheading"] = _group_table(c_df, "Sub-Heading", col_amount, "sub_heading", top=15)
    return out


@router.get("/export")
def export_overview_csv(
    section: str = Query(..., pattern="^(campaigns|headings|subheadings|campaign_donations|category_campaigns)$"),
    campaign: Optional[str] = None,
    category: Optional[str] = None,
    kind: str = Query("heading", pattern="^(heading|subheading)$"),
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
    """CSV of a dashboard section under the current filters. Contains aggregates and donor display names only."""
    df = _filtered(company_id, payment_type, tier, source, heading, subheading, country, code, zakat,
                   donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund)
    col_amount = _get_amount_column(df)
    if df.empty or not col_amount:
        raise HTTPException(status_code=400, detail="No data available to export.")

    name = section
    if section == "campaigns":
        export_df = pd.DataFrame(_group_table(df, "Campaign Name", col_amount, "Campaign"))
    elif section == "headings":
        export_df = pd.DataFrame(_group_table(df, "Heading", col_amount, "Category")) if "Heading" in df.columns else pd.DataFrame()
    elif section == "subheadings":
        export_df = pd.DataFrame(_group_table(df, "Sub-Heading", col_amount, "Sub-Category")) if "Sub-Heading" in df.columns else pd.DataFrame()
    elif section == "campaign_donations":
        if not campaign:
            raise HTTPException(status_code=400, detail="campaign is required for this export.")
        c_df = df[df["Campaign Name"].astype(str).str.strip().str.lower() == campaign.strip().lower()].copy()
        date_col = "_parsed_date" if "_parsed_date" in c_df.columns else ("Created Date (UTC)" if "Created Date (UTC)" in c_df.columns else None)
        c_df["_page"] = _page_label_series(c_df)
        export_df = pd.DataFrame({
            "Date": pd.to_datetime(c_df[date_col], errors="coerce").dt.strftime("%Y-%m-%d") if date_col else "",
            "Donor": _donor_name_series(c_df),
            "Amount": c_df[col_amount].astype(float).round(2),
            "Platform": c_df.get("Platform", ""),
            "Page": c_df["_page"],
            "Payment Type": c_df.get("Payment Frequency", ""),
        })
        name = f"campaign_{campaign}"
    else:  # category_campaigns
        if not category:
            raise HTTPException(status_code=400, detail="category is required for this export.")
        col = "Heading" if kind == "heading" else "Sub-Heading"
        c_df = df[df[col].astype(str).str.strip().str.lower() == category.strip().lower()]
        export_df = pd.DataFrame(_group_table(c_df, "Campaign Name", col_amount, "Campaign")) if "Campaign Name" in c_df.columns else pd.DataFrame()
        name = f"category_{category}"

    if export_df.empty:
        raise HTTPException(status_code=400, detail="No rows to export for this section.")

    rename = {"total_raised": "Total Raised", "donation_count": "Gifts"}
    export_df = export_df.rename(columns=rename)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", name.strip().lower()).strip("_") or "overview"
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    temp_file_path = temp_file.name
    temp_file.close()
    dataframe_to_fast_csv(export_df, temp_file_path)
    return FileResponse(
        path=temp_file_path,
        filename=f"overview_{safe}_{date_str}.csv",
        media_type="text/csv",
        background=BackgroundTask(_cleanup_temp_file, temp_file_path)
    )
