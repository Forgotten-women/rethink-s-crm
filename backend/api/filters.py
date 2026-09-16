from typing import Optional
from fastapi import APIRouter, Query
from core.data_processor import load_data, load_payouts_data
from backend.api.donors import _apply_filters

router = APIRouter(prefix="/api/filters", tags=["Filter Controls"])


@router.get("/options")
def get_filter_options(
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
    end_date: Optional[str] = None,
    company_id: Optional[str] = Query("rethink")
):
    comp = (company_id or "rethink").strip().lower()
    df_raw = load_data(company_id=comp)

    if df_raw.empty:
        return {
            "sources": ["GiveBright", "LaunchGood", "Paysuite", "Rethink Website"],
            "programme_funds": [],
            "headings": [],
            "subheadings": [],
            "countries": [],
            "codes": [],
            "zakat_statuses": [],
            "tiers": [],
            "payment_types": [],
            "donor_countries": [],
            "campaigns": [],
            "gift_aid_options": ["All Gift Aid Status"]
        }

    # 1. Sources (Platforms): filter by all active criteria EXCEPT source
    s_df = _apply_filters(df_raw, payment_type, tier, None, heading, subheading, country, code, zakat, donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund=programme_fund, campaign=campaign)
    sources = []
    if "Platform" in s_df.columns:
        sources = sorted([str(p).strip() for p in s_df["Platform"].dropna().unique() if str(p).strip() not in ["", "nan", "None", "LaunchGood Payout", "launchgood payout"]])
    if not sources and "Platform" in df_raw.columns:
        sources = sorted([str(p).strip() for p in df_raw["Platform"].dropna().unique() if str(p).strip() not in ["", "nan", "None", "LaunchGood Payout", "launchgood payout"]])

    # 2. Programme Funds: filter by all active criteria EXCEPT programme_fund itself
    pf_df = _apply_filters(df_raw, payment_type, tier, source, heading, subheading, country, code, zakat, donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund=None)
    programme_funds = []
    if "Programme Fund" in pf_df.columns:
        programme_funds = sorted([str(pf).strip() for pf in pf_df["Programme Fund"].dropna().unique() if str(pf).strip() not in ["", "nan", "None", "Unassigned"]])

    # 3. Headings: filter by all active criteria EXCEPT heading itself
    h_df = _apply_filters(df_raw, payment_type, tier, source, None, subheading, country, code, zakat, donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund=programme_fund)
    headings = []
    if "Heading" in h_df.columns:
        headings = sorted([str(h).strip() for h in h_df["Heading"].dropna().unique() if str(h).strip() not in ["", "nan", "None"]])

    # 4. Sub-headings: filter by all active criteria EXCEPT subheading
    sub_df = _apply_filters(df_raw, payment_type, tier, source, heading, None, country, code, zakat, donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund=programme_fund)
    subheadings = []
    if "Sub-Heading" in sub_df.columns:
        subheadings = sorted([str(sh).strip() for sh in sub_df["Sub-Heading"].dropna().unique() if str(sh).strip() not in ["", "nan", "None"]])

    # 5. Countries: filter by all active criteria EXCEPT country
    c_df = _apply_filters(df_raw, payment_type, tier, source, heading, subheading, None, code, zakat, donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund=programme_fund)
    countries = []
    if "Country" in c_df.columns:
        countries = sorted([str(c).strip() for c in c_df["Country"].dropna().unique() if str(c).strip() not in ["", "nan", "None"]])

    # 6. Codes: filter by all active criteria EXCEPT code
    cd_df = _apply_filters(df_raw, payment_type, tier, source, heading, subheading, country, None, zakat, donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund=programme_fund)
    codes = []
    if "Code" in cd_df.columns:
        codes = sorted([str(cd).strip() for cd in cd_df["Code"].dropna().unique() if str(cd).strip() not in ["", "N/A", "nan", "None", "Unassigned"]])

    # 7. Real-Time Zakat Statuses: strictly from active data matching filters EXCEPT zakat
    zk_df = _apply_filters(df_raw, payment_type, tier, source, heading, subheading, country, code, None, donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund=programme_fund)
    zakat_statuses = []
    if "Zakat Eligibility" in zk_df.columns:
        val_counts = zk_df["Zakat Eligibility"].dropna().value_counts()
        for zk_val, count in val_counts.items():
            zk_clean = str(zk_val).strip()
            if count > 0 and zk_clean not in ["", "nan", "None", "N/A"] and zk_clean not in zakat_statuses:
                zakat_statuses.append(zk_clean)
        zakat_statuses = sorted(zakat_statuses)

    # 8. Real-Time Lifetime Tiers: strictly from active data matching filters EXCEPT tier
    t_df = _apply_filters(df_raw, payment_type, None, source, heading, subheading, country, code, zakat, donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund=programme_fund)
    tiers = []
    tier_col = None
    for tc in ["Lifetime Donor Classification", "Donor Classification", "Tier"]:
        if tc in t_df.columns:
            tier_col = tc
            break
    if tier_col:
        tier_counts = t_df[tier_col].dropna().value_counts()
        standard_order = ["Super High", "High", "Medium", "Medium Low", "Low End"]
        tiers = [t for t in standard_order if t in tier_counts and tier_counts[t] > 0]
        for t, cnt in tier_counts.items():
            t_clean = str(t).strip()
            if cnt > 0 and t_clean not in tiers and t_clean not in ["", "nan", "None"]:
                tiers.append(t_clean)

    # 9. Real-Time Payment Types: strictly from active data matching filters EXCEPT payment_type
    pt_df = _apply_filters(df_raw, None, tier, source, heading, subheading, country, code, zakat, donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund=programme_fund)
    payment_types = []
    pt_col = None
    for pc in ["Payment Type", "Donation Type"]:
        if pc in pt_df.columns:
            pt_col = pc
            break
    if pt_col:
        pt_counts = pt_df[pt_col].dropna().value_counts()
        payment_types = [str(p).strip() for p, cnt in pt_counts.items() if cnt > 0 and str(p).strip() not in ["", "nan", "None"]]
        payment_types = sorted(payment_types)

    # 10. Donor Countries: filter by all active criteria EXCEPT donor_country
    dc_df = _apply_filters(df_raw, payment_type, tier, source, heading, subheading, country, code, zakat, None, campaign_search, gift_aid, start_date, end_date, programme_fund=programme_fund)
    donor_countries = []
    for dc_col in ["Donor Country", "Billing Country", "Country Code"]:
        if dc_col in dc_df.columns:
            donor_countries = sorted([str(dc).strip() for dc in dc_df[dc_col].dropna().unique() if str(dc).strip() not in ["", "N/A", "nan", "None"]])
            break

    # 11. Gift Aid
    ga_df = _apply_filters(df_raw, payment_type, tier, source, heading, subheading, country, code, zakat, donor_country, campaign_search, None, start_date, end_date, programme_fund=programme_fund)
    gift_aid_options = ["All Gift Aid Status"]
    has_yes = False
    has_no = False
    if "Gift Aid (yes or no)" in ga_df.columns:
        ga_vals = set(str(g).strip().lower() for g in ga_df["Gift Aid (yes or no)"].dropna().unique())
        if "yes" in ga_vals or "true" in ga_vals:
            has_yes = True
        if "no" in ga_vals or "false" in ga_vals:
            has_no = True
    if "is_giftaid" in ga_df.columns:
        ga_vals_num = ga_df["is_giftaid"].dropna().unique()
        if 1.0 in ga_vals_num or 1 in ga_vals_num or "1.0" in ga_vals_num or "1" in ga_vals_num:
            has_yes = True
        if 0.0 in ga_vals_num or 0 in ga_vals_num or "0.0" in ga_vals_num or "0" in ga_vals_num:
            has_no = True
            
    if has_yes:
        gift_aid_options.append("Yes")
    if has_no:
        gift_aid_options.append("No")
        
    if len(gift_aid_options) == 1:
        gift_aid_options = ["All Gift Aid Status", "Yes", "No"]

    # 12. Campaigns: filter by all active criteria EXCEPT campaign itself
    camp_df = _apply_filters(df_raw, payment_type, tier, source, heading, subheading, country, code, zakat, donor_country, campaign_search, gift_aid, start_date, end_date, programme_fund=programme_fund, campaign=None)
    campaigns = []
    if "Campaign Name" in camp_df.columns:
        campaigns = sorted([str(c).strip() for c in camp_df["Campaign Name"].dropna().unique() if str(c).strip() not in ["", "nan", "None", "Unassigned"]])

    return {
        "sources": sources,
        "programme_funds": programme_funds,
        "headings": headings,
        "subheadings": subheadings,
        "countries": countries,
        "codes": codes,
        "zakat_statuses": zakat_statuses,
        "tiers": tiers,
        "payment_types": payment_types,
        "donor_countries": donor_countries,
        "campaigns": campaigns,
        "gift_aid_options": gift_aid_options
    }

