import os
import sqlite3
import pandas as pd
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query, status
from pydantic import BaseModel

from core.data_processor import load_data, LOCAL_DB_PATH

router = APIRouter(prefix="/api/tracker", tags=["Sponsorship Target Tracker"])

_TRACKER_CACHE = None

def clear_tracker_cache():
    global _TRACKER_CACHE
    _TRACKER_CACHE = None

class UpdateTargetsRequest(BaseModel):
    user_role: str
    targets: Dict[str, float]
    company_id: Optional[str] = "rethink"

@router.get("/targets")
def get_targets(company_id: Optional[str] = Query("rethink")):
    """Returns the current target values for each of the 4 sponsorships."""
    comp = (company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        if comp != "all":
            cur.execute("SELECT sponsorship_type, target_value FROM sponsorship_targets WHERE company_id = ?", (comp,))
        else:
            cur.execute("SELECT sponsorship_type, target_value FROM sponsorship_targets")
        rows = cur.fetchall()
        if not rows:
            # Fallback defaults
            return {"Hafiz": 240.0, "Orphan": 480.0, "Widow": 1080.0, "Ex-Prisoner": 1080.0}
        return {r[0]: r[1] for r in rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/targets")
def update_targets(payload: UpdateTargetsRequest):
    """Updates target values (restricted to super_admin)."""
    if payload.user_role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Updating target values is restricted to Super Admin accounts."
        )
    comp = (payload.company_id or "rethink").strip().lower()
    if comp == "all":
        raise HTTPException(
            status_code=400,
            detail="Cannot set sponsorship targets in All Companies mode. Please select a specific company."
        )
    
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        for s_type, val in payload.targets.items():
            cur.execute("""
                INSERT INTO sponsorship_targets (sponsorship_type, target_value, company_id)
                VALUES (?, ?, ?)
                ON CONFLICT(sponsorship_type, company_id) DO UPDATE SET target_value = excluded.target_value
            """, (s_type, float(val), comp))
        conn.commit()
        clear_tracker_cache()
        return {"status": "success", "message": f"Successfully updated targets for {comp.upper()}!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

_FILTER_CACHE = {}
_LAST_DATA_MTIME = 0.0

@router.get("/stats")
def get_tracker_stats(
    payment_type: Optional[str] = Query(None),
    tier: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    heading: Optional[str] = Query(None),
    subheading: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    code: Optional[str] = Query(None),
    zakat: Optional[str] = Query(None),
    donor_country: Optional[str] = Query(None),
    campaign_search: Optional[str] = Query(None),
    gift_aid: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    company_id: Optional[str] = Query("rethink")
):
    """Computes high-speed real-time donor target progress stats filtered by criteria."""
    global _FILTER_CACHE, _LAST_DATA_MTIME
    comp = (company_id or "rethink").strip().lower()

    # Check cache invalidation
    from core.data_processor import _CACHE_MTIME
    if _CACHE_MTIME != _LAST_DATA_MTIME:
        _FILTER_CACHE.clear()
        _LAST_DATA_MTIME = _CACHE_MTIME

    filter_key = (
        payment_type, tier, source, heading, subheading, country, code,
        zakat, donor_country, campaign_search, gift_aid, start_date, end_date, comp
    )
    if filter_key in _FILTER_CACHE:
        return _FILTER_CACHE[filter_key]

    targets = {"Hafiz": 240.0, "Orphan": 480.0, "Widow": 1080.0, "Ex-Prisoner": 1080.0}
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        if comp != "all":
            cur.execute("SELECT sponsorship_type, target_value FROM sponsorship_targets WHERE company_id = ?", (comp,))
        else:
            cur.execute("SELECT sponsorship_type, target_value FROM sponsorship_targets")
        for r in cur.fetchall():
            targets[r[0]] = float(r[1])
    except Exception:
        pass
    finally:
        conn.close()

    df = load_data(company_id=comp)
    if df.empty:
        res = {s: {"target": t, "total_raised": 0.0, "above_count": 0, "near_count": 0, "above": [], "near": []} for s, t in targets.items()}
        return res

    # Apply Filters
    from backend.api.donors import _apply_filters
    df = _apply_filters(
        df,
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
        end_date=end_date
    )

    col_amount = "Total Online Donations Net Amount in Settled Currency"
    if col_amount not in df.columns:
        col_amount = "Donation Amount in Project Currency (May be approx.)"
    if col_amount not in df.columns:
        col_amount = "Donation Amount (in Donation Currency)"

    if col_amount not in df.columns or "Donor ID" not in df.columns or df.empty:
        res = {s: {"target": t, "total_raised": 0.0, "above_count": 0, "near_count": 0, "above": [], "near": []} for s, t in targets.items()}
        _FILTER_CACHE[filter_key] = res
        return res

    # Fast numeric conversion
    amt_series = pd.to_numeric(df[col_amount], errors="coerce").fillna(0.0)
    d_id_series = df["Donor ID"].astype(str)

    # Vectorized Code Masking
    code_series = df["Code"].astype(str).str.strip().str.upper() if "Code" in df.columns else pd.Series("", index=df.index)

    masks = {
        "Hafiz": code_series.str.contains("HUF", na=False),
        "Orphan": code_series.str.contains("ORP", na=False),
        "Widow": code_series.str.contains("WID", na=False),
        "Ex-Prisoner": code_series.str.contains("SUR", na=False) | code_series.str.contains("EX-PRISONER", na=False)
    }

    results = {}
    for s_type, target in targets.items():
        mask = masks[s_type]
        if not mask.any():
            results[s_type] = {
                "target": target,
                "total_raised": 0.0,
                "above_count": 0,
                "near_count": 0,
                "above": [],
                "near": []
            }
            continue

        s_amt = amt_series[mask]
        s_did = d_id_series[mask]
        total_raised = float(s_amt.sum())

        sums = s_amt.groupby(s_did).sum()
        relevant = sums[sums >= (0.8 * target)]

        above_list = []
        near_list = []

        if not relevant.empty:
            rel_ids = set(relevant.index)
            rel_df = df[d_id_series.isin(rel_ids)].drop_duplicates(subset=["Donor ID"], keep="first")

            names = rel_df["Display Name"].fillna("") if "Display Name" in rel_df.columns else pd.Series("Anonymous Donor", index=rel_df.index)
            invalid_mask = names.astype(str).str.strip().str.lower().isin(["", "nan", "none", "null", "anonymous", "anonymous kind soul", "kind soul"])
            if invalid_mask.any() and "First Name" in rel_df.columns and "Last Name" in rel_df.columns:
                fn = rel_df.loc[invalid_mask, "First Name"].fillna("").astype(str).str.strip()
                ln = rel_df.loc[invalid_mask, "Last Name"].fillna("").astype(str).str.strip()
                comb = (fn + " " + ln).str.strip()
                names.loc[invalid_mask] = comb.replace({"": "Anonymous Donor", "nan nan": "Anonymous Donor"})

            names = names.replace({"": "Anonymous Donor", "nan": "Anonymous Donor"})
            emails = rel_df.get("Email", pd.Series("N/A", index=rel_df.index)).fillna("N/A").astype(str)

            donor_meta = dict(zip(rel_df["Donor ID"].astype(str), zip(names, emails)))

            for str_id, total in relevant.items():
                total_val = float(total)
                progress = round((total_val / target) * 100.0, 1)
                best_name, email = donor_meta.get(str_id, ("Anonymous Donor", "N/A"))

                rec = {
                    "donor_id": str_id,
                    "name": best_name,
                    "email": email,
                    "total_donated": round(total_val, 2),
                    "target": target,
                    "progress": progress
                }

                if total_val >= target:
                    above_list.append(rec)
                else:
                    near_list.append(rec)

            above_list.sort(key=lambda x: x["total_donated"], reverse=True)
            near_list.sort(key=lambda x: x["total_donated"], reverse=True)

        results[s_type] = {
            "target": target,
            "total_raised": round(total_raised, 2),
            "above_count": len(above_list),
            "near_count": len(near_list),
            "above": above_list,
            "near": near_list
        }

    if len(_FILTER_CACHE) > 64:
        _FILTER_CACHE.clear()
    _FILTER_CACHE[filter_key] = results
    return results
