import io
import os
import sqlite3
from datetime import datetime
from typing import List, Optional
import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel

from config.settings import LOCAL_DB_PATH, PARQUET_PATH
from core.database import get_db_connection, _DB_LOCK
from core.data_processor import (
    get_classification_matrix,
    load_data,
    save_classification_matrix,
    get_paysuite_classification_matrix,
    save_paysuite_classification_matrix,
    get_rethink_website_classification_matrix,
    save_rethink_website_classification_matrix,
    get_givebright_classification_matrix,
    save_givebright_classification_matrix,
    normalize_classification_import_df,
    get_code_to_classification_map,
    sync_matrix_classifications_to_donors,
    save_platform_matrix_rules,
    fix_mojibake,
)
try:
    from backend.api.payouts import invalidate_payouts_cache
except ImportError:
    try:
        from api.payouts import invalidate_payouts_cache
    except ImportError:
        def invalidate_payouts_cache():
            pass

router = APIRouter(prefix="/api/classifications", tags=["Campaign Classifications"])


def sanitize_text(val):
    """Repairs common UTF-8 mojibake and strips zero-width/soft-hyphen characters."""
    if not isinstance(val, str) or pd.isna(val):
        return val
    s = str(val).strip()
    try:
        if any(c in s for c in ["Ä", "Ã", "â", "\xad"]):
            s = s.encode("latin1").decode("utf-8")
    except Exception:
        pass
    s = s.replace("\xad", "").replace("\u200b", "").replace("\ufeff", "")
    return s


def sanitize_matrix_df(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorized sanitizer for matrix tables in < 2ms."""
    if df.empty:
        return df
    clean_df = df.copy()
    for col in clean_df.columns:
        if clean_df[col].dtype == object or pd.api.types.is_string_dtype(clean_df[col]):
            clean_df[col] = clean_df[col].apply(fix_mojibake)
    return clean_df



class SaveRulesRequest(BaseModel):
    user_role: str
    platform: str  # "launchgood", "givebright", "paysuite", or "website"
    rules: List[dict]
    company_id: Optional[str] = "rethink"
    can_edit_matrix: Optional[bool] = False


class DeleteRuleRequest(BaseModel):
    user_role: str
    platform: str
    campaign_name: str
    company_id: Optional[str] = "rethink"
    code: Optional[str] = None
    community_name: Optional[str] = None


class ClearPlatformRequest(BaseModel):
    user_role: str
    platform: str
    company_id: Optional[str] = "rethink"


class MasterProjectCodeRequest(BaseModel):
    user_role: Optional[str] = "super_admin"
    code: str
    department: str
    office: str
    company_id: Optional[str] = "rethink"
    portfolio: Optional[str] = ""
    country: str
    zakat_eligibility: Optional[str] = "Zakat"
    description: Optional[str] = ""
    is_active: Optional[int] = 1
    programme_fund: Optional[str] = ""
    fund_code: Optional[str] = ""
    legacy_non_zakat_code: Optional[str] = ""
    legacy_zakat_code: Optional[str] = ""
    old_codes: Optional[str] = ""


class DeleteMasterCodeRequest(BaseModel):
    user_role: str
    code: str
    company_id: Optional[str] = "rethink"


def _enrich_rules_metadata(df: pd.DataFrame) -> pd.DataFrame:
    """Enriches rules DataFrame with variants_count, status ('single_code' | 'multi_code' | 'unassigned'), and is_primary boolean flag."""
    if df.empty:
        return df

    # Normalize column is_primary
    if "is_primary" not in df.columns:
        df["is_primary"] = 0

    # Count distinct valid codes per campaign name
    c_series = df["Campaign Name"].astype(str).str.strip().str.lower()
    code_series = df["Code"].astype(str).str.strip().str.upper()

    camp_code_map = {}
    for c_name, c_code in zip(c_series, code_series):
        if c_name not in ["nan", "none", "n/a", ""]:
            if c_name not in camp_code_map:
                camp_code_map[c_name] = set()
            if c_code not in ["UNASSIGNED", "N/A", "NONE", "NAN", ""]:
                camp_code_map[c_name].add(c_code)

    variants_counts = []
    statuses = []
    is_primary_flags = []
    seen_camps_primary = set()

    for idx, row in df.iterrows():
        c_name = str(row.get("Campaign Name") or "").strip().lower()
        c_code = str(row.get("Code") or "").strip().upper()
        h_val = str(row.get("Heading") or "").strip().lower()

        distinct_codes = camp_code_map.get(c_name, set())
        v_count = len(distinct_codes)
        variants_counts.append(v_count)

        if h_val in ["unassigned", "nan", "none", ""] or c_code in ["UNASSIGNED", "N/A", "NONE", "NAN", ""]:
            statuses.append("unassigned")
        elif v_count > 1:
            statuses.append("multi_code")
        else:
            statuses.append("single_code")

        # Determine is_primary flag
        raw_prim = row.get("is_primary")
        is_prim = bool(raw_prim in [1, True, "1", "true", "True"])
        if is_prim:
            is_primary_flags.append(True)
            seen_camps_primary.add(c_name)
        elif c_name not in seen_camps_primary and c_code not in ["UNASSIGNED", "N/A", "NONE", "NAN", ""]:
            is_primary_flags.append(True)
            seen_camps_primary.add(c_name)
        else:
            is_primary_flags.append(False)

    df["variants_count"] = variants_counts
    df["status"] = statuses
    df["is_primary"] = is_primary_flags
    return df


@router.get("/master-codes")
def get_master_project_codes(company_id: Optional[str] = Query("rethink")):
    """Returns all master project codes with Department, Office, Portfolio, linked campaigns count, and total gross raised for a company."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    comp = str(company_id or "rethink").lower().strip()
    try:
        cur = conn.cursor()
        # Verify master_project_codes table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_project_codes'")
        if not cur.fetchone():
            return {"status": "success", "total_codes": 0, "codes": []}

        where_clause = " WHERE LOWER(COALESCE(company_id, 'rethink')) = ?" if comp != "all" else ""
        params = [comp] if comp != "all" else []

        codes_df = pd.read_sql_query(f"""
            SELECT 
                code, 
                department, 
                office, 
                COALESCE(portfolio, '') AS portfolio, 
                country, 
                zakat_eligibility, 
                COALESCE(description, '') AS description, 
                COALESCE(is_active, 1) AS is_active,
                COALESCE(programme_fund, '') AS programme_fund,
                COALESCE(fund_code, '') AS fund_code,
                COALESCE(legacy_non_zakat_code, '') AS legacy_non_zakat_code,
                COALESCE(legacy_zakat_code, '') AS legacy_zakat_code,
                COALESCE(old_codes, '') AS old_codes,
                created_at,
                updated_at,
                COALESCE(company_id, 'rethink') AS company_id
            FROM master_project_codes
            {where_clause}
            ORDER BY code ASC
        """, conn, params=params)

        # Count linked campaigns per code across platform_campaign_mappings
        links_map = {}
        try:
            links_where = " WHERE LOWER(COALESCE(company_id, 'rethink')) = ?" if comp != "all" else ""
            links_df = pd.read_sql_query(f"""
                SELECT UPPER(TRIM(code)) as code, COUNT(DISTINCT campaign_name) as campaign_count
                FROM platform_campaign_mappings
                {links_where}
                GROUP BY UPPER(TRIM(code))
            """, conn, params=params)
            links_map = dict(zip(links_df["code"], links_df["campaign_count"]))
        except Exception:
            pass

        # Sum total donations raised per code
        raised_map = {}
        try:
            raised_where = " WHERE LOWER(COALESCE(company_id, 'rethink')) = ? AND Code IS NOT NULL AND TRIM(Code) != ''" if comp != "all" else " WHERE Code IS NOT NULL AND TRIM(Code) != ''"
            raised_df = pd.read_sql_query(f"""
                SELECT UPPER(TRIM(Code)) as code, SUM("Total Online Donations Net Amount in Settled Currency") as total_raised
                FROM donations
                {raised_where}
                GROUP BY UPPER(TRIM(Code))
            """, conn, params=params)
            raised_map = dict(zip(raised_df["code"], raised_df["total_raised"].fillna(0).round(2)))
        except Exception:
            pass

        result = []
        for _, r in codes_df.iterrows():
            c_code = str(r["code"]).strip().upper()
            dept = sanitize_text(r["department"])
            off = sanitize_text(r["office"])
            port = sanitize_text(r.get("portfolio", ""))
            result.append({
                "code": c_code,
                "department": dept,
                "office": off,
                "portfolio": port,
                # Backward-compatible aliases:
                "heading": dept,
                "sub_heading": off,
                "country": sanitize_text(r["country"]),
                "zakat_eligibility": sanitize_text(r["zakat_eligibility"]),
                "description": sanitize_text(r.get("description", "")),
                "is_active": int(r.get("is_active", 1)),
                "programme_fund": sanitize_text(r.get("programme_fund", "")),
                "fund_code": sanitize_text(r.get("fund_code", "")),
                "legacy_non_zakat_code": sanitize_text(r.get("legacy_non_zakat_code", "")),
                "legacy_zakat_code": sanitize_text(r.get("legacy_zakat_code", "")),
                "old_codes": sanitize_text(r.get("old_codes", "")),
                "campaign_count": int(links_map.get(c_code, 0)),
                "total_raised": float(raised_map.get(c_code, 0.0)),
                "created_at": str(r.get("created_at", "")),
                "updated_at": str(r.get("updated_at", ""))
            })

        return {
            "status": "success",
            "total_codes": len(result),
            "codes": result,
            "master_codes": result
        }
    finally:
        conn.close()


@router.post("/master-codes")
def save_master_project_code(payload: MasterProjectCodeRequest):
    """Creates or updates a Master Project Code and immediately cascades updates to matching donations for a company."""
    if payload.user_role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Managing master project codes is restricted to Super Admin accounts."
        )

    comp = str(payload.company_id or "rethink").lower().strip()
    if comp == "all":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Modifications are disabled in consolidated 'All Companies' mode. Please select a specific company."
        )

    clean_code = str(payload.code).strip().upper()
    if not clean_code or clean_code in ["UNASSIGNED", "NAN", "NONE", "N/A", ""]:
        raise HTTPException(status_code=400, detail="A valid Code string is required.")

    dept = sanitize_text(payload.department.strip() or "Unassigned")
    off = sanitize_text(payload.office.strip() or "Unassigned")
    port = sanitize_text((payload.portfolio or "").strip())
    cntry = sanitize_text(payload.country.strip() or "Unassigned")
    zkt = sanitize_text(payload.zakat_eligibility.strip() or "Zakat")
    desc = sanitize_text((payload.description or "").strip())
    act = int(payload.is_active if payload.is_active is not None else 1)
    prog_fund = sanitize_text((payload.programme_fund or "").strip())
    f_code = sanitize_text((payload.fund_code or "").strip())
    non_zkt_gl = sanitize_text((payload.legacy_non_zakat_code or "").strip())
    zkt_gl = sanitize_text((payload.legacy_zakat_code or "").strip())
    old_cds = sanitize_text((payload.old_codes or "").strip())

    with _DB_LOCK:
        conn = get_db_connection(timeout=30.0)
        try:
            with conn:
                conn.execute("""
                    INSERT INTO master_project_codes (
                        code, department, office, portfolio, country, zakat_eligibility, 
                        description, is_active, programme_fund, fund_code, 
                        legacy_non_zakat_code, legacy_zakat_code, old_codes, updated_at, company_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                    ON CONFLICT(company_id, code) DO UPDATE SET
                        department = excluded.department,
                        office = excluded.office,
                        portfolio = excluded.portfolio,
                        country = excluded.country,
                        zakat_eligibility = excluded.zakat_eligibility,
                        description = excluded.description,
                        is_active = excluded.is_active,
                        programme_fund = excluded.programme_fund,
                        fund_code = excluded.fund_code,
                        legacy_non_zakat_code = excluded.legacy_non_zakat_code,
                        legacy_zakat_code = excluded.legacy_zakat_code,
                        old_codes = excluded.old_codes,
                        updated_at = CURRENT_TIMESTAMP;
                """, (clean_code, dept, off, port, cntry, zkt, desc, act, prog_fund, f_code, non_zkt_gl, zkt_gl, old_cds, comp))
        finally:
            conn.close()

    # Invalidate cached code map
    get_code_to_classification_map(force_reload=True, company_id=comp)
    invalidate_payouts_cache()

    # Live cascade: sync changes for this code to matching donations in SQLite and Parquet for this company
    try:
        df_raw = load_data(force_reload=True)
        if not df_raw.empty and "Code" in df_raw.columns:
            if "company_id" not in df_raw.columns:
                df_raw["company_id"] = "rethink"
            comp_mask = (df_raw["company_id"].astype(str).str.lower() == comp)
            mask = comp_mask & (df_raw["Code"].astype(str).str.strip().str.upper() == clean_code)
            if mask.any():
                for col_name, col_val in [
                    ("Department", dept),
                    ("Office", off),
                    ("Portfolio", port),
                    ("Heading", dept),
                    ("Sub-Heading", off),
                    ("Country", cntry),
                    ("Zakat Eligibility", zkt),
                    ("Programme Fund", prog_fund),
                    ("Fund Code", f_code)
                ]:
                    if col_name in df_raw.columns:
                        df_raw.loc[mask, col_name] = col_val

                from core.data_processor import sanitize_df_dtypes_for_parquet
                df_raw = sanitize_df_dtypes_for_parquet(df_raw)
                df_raw.to_parquet(PARQUET_PATH, index=False)
                conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
                conn.execute("DELETE FROM donations WHERE LOWER(COALESCE(company_id, 'rethink')) = ?", (comp,))
                df_raw[comp_mask].to_sql("donations", con=conn, if_exists="append", index=False, chunksize=5000)
                conn.commit()
                conn.close()
    except Exception as e:
        print(f"Error cascading master code to donations: {e}")

    try:
        from backend.api.expenses import clear_expenses_cache
        clear_expenses_cache()
        from backend.api.events import broadcast_event_sync
        broadcast_event_sync("MASTER_CODES_UPDATED", {"code": clean_code, "company_id": comp})
    except Exception:
        pass

    return {
        "status": "success",
        "message": f"Successfully saved master project code '{clean_code}'."
    }


@router.delete("/master-codes/{code}")
def delete_master_project_code(code: str, user_role: Optional[str] = Query("super_admin"), company_id: Optional[str] = Query("rethink")):
    """Deletes a Master Project Code if confirmed by Super Admin."""
    if user_role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Deleting master project codes is restricted to Super Admin accounts."
        )

    comp = str(company_id or "rethink").lower().strip()
    if comp == "all":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Deleting master project codes is disabled in consolidated 'All Companies' mode."
        )

    clean_code = str(code).strip().upper()
    with _DB_LOCK:
        conn = get_db_connection(timeout=30.0)
        try:
            with conn:
                conn.execute("DELETE FROM master_project_codes WHERE UPPER(code) = ? AND LOWER(COALESCE(company_id, 'rethink')) = ?", (clean_code, comp))
        finally:
            conn.close()

    get_code_to_classification_map(force_reload=True, company_id=comp)
    return {
        "status": "success",
        "message": f"Successfully deleted master project code '{clean_code}'."
    }


@router.get("/campaign-codes")
def get_campaign_codes_lookup(platform: str = "all", company_id: Optional[str] = Query("rethink")):
    """
    Returns a fast lookup mapping every Campaign Name to its list of valid code variant objects:
    { "ashbal orphanage": [ { "code": "GAZ-SPN-ORP", "department": "Sponsorships", "office": "Gaza Orphan Sponsorship", "portfolio": "", "heading": "Sponsorships", "sub_heading": "Gaza Orphan Sponsorship", "country": "Palestine", "zakat_eligibility": "Zakat", "is_primary": true } ] }
    """
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    tables = ["campaign_classifications", "givebright_classifications", "paysuite_classifications", "rethink_website_classifications"]
    if platform.lower() == "launchgood":
        tables = ["campaign_classifications"]
    elif platform.lower() == "givebright":
        tables = ["givebright_classifications"]
    elif platform.lower() == "paysuite":
        tables = ["paysuite_classifications"]
    elif platform.lower() in ["website", "rethink_website"]:
        tables = ["rethink_website_classifications"]

    comp = (company_id or "rethink").strip().lower()
    lookup = {}
    try:
        for tbl in tables:
            try:
                if comp != "all":
                    df = pd.read_sql_query(f"SELECT * FROM {tbl} WHERE company_id = ?", conn, params=(comp,))
                else:
                    df = pd.read_sql_query(f"SELECT * FROM {tbl}", conn)

                for _, r in df.iterrows():
                    c_name = sanitize_text(r.get("campaign_name", ""))
                    c_code = sanitize_text(r.get("code", "Unassigned"))
                    if not c_name or c_name.lower() in ["unassigned", "n/a", "none", "nan", ""]:
                        continue
                    if not c_code or c_code.lower() in ["unassigned", "n/a", "none", "nan", ""]:
                        continue
                    
                    c_key = c_name.strip().lower()
                    if c_key not in lookup:
                        lookup[c_key] = []
                    
                    is_prim = bool(r.get("is_primary") in [1, True, "1", "true", "True"])
                    dept = sanitize_text(r.get("department") or r.get("heading", "Unassigned"))
                    off = sanitize_text(r.get("office") or r.get("sub_heading", "Unassigned"))
                    port = sanitize_text(r.get("portfolio", ""))
                    
                    if not any(item["code"].upper() == c_code.upper() for item in lookup[c_key]):
                        lookup[c_key].append({
                            "campaign_name": c_name,
                            "code": c_code.upper(),
                            "department": dept,
                            "office": off,
                            "portfolio": port,
                            "heading": dept,
                            "sub_heading": off,
                            "country": sanitize_text(r.get("country", "Unassigned")),
                            "zakat_eligibility": sanitize_text(r.get("zakat_eligibility", "Unassigned")),
                            "programme_fund": sanitize_text(r.get("programme_fund", "")),
                            "fund_code": sanitize_text(r.get("fund_code", "")),
                            "is_primary": is_prim
                        })
            except Exception:
                pass
    finally:
        conn.close()

    return lookup


@router.get("/code-map")
def get_code_map(company_id: Optional[str] = Query("rethink")):
    """Returns the central mapping of Code -> {Department, Office, Portfolio, Heading, Sub-Heading, Country, Zakat Eligibility, Programme Fund, Fund Code}."""
    comp = (company_id or "rethink").strip().lower()
    raw_map = get_code_to_classification_map(company_id=comp)
    clean_map = {}
    for code, info in raw_map.items():
        dept = sanitize_text(info.get("Department") or info.get("Heading", "Unassigned"))
        off = sanitize_text(info.get("Office") or info.get("Sub-Heading", "Unassigned"))
        port = sanitize_text(info.get("Portfolio", ""))
        clean_map[code.strip().lower()] = {
            "Department": dept,
            "Office": off,
            "Portfolio": port,
            "Heading": dept,
            "Sub-Heading": off,
            "Country": sanitize_text(info.get("Country", "Unassigned")),
            "Zakat Eligibility": sanitize_text(info.get("Zakat Eligibility", "Unassigned")),
            "Programme Fund": sanitize_text(info.get("Programme Fund", "")),
            "Fund Code": sanitize_text(info.get("Fund Code", "")),
            "Legacy Non-Zakat Code": sanitize_text(info.get("Legacy Non-Zakat Code", "")),
            "Legacy Zakat Code": sanitize_text(info.get("Legacy Zakat Code", "")),
            "Old Code": sanitize_text(info.get("Old Code", ""))
        }
    return clean_map


@router.get("/launchgood")
def get_launchgood_matrix(company_id: Optional[str] = Query("rethink")):
    """Returns LaunchGood classification matrix rules with (Campaign Name, Code) granularity."""
    comp = (company_id or "rethink").strip().lower()
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        query = """
            SELECT 
                campaign_name as "Campaign Name",
                COALESCE(code, 'Unassigned') as "Code",
                COALESCE(campaign_url, '') as "Campaign URL",
                COALESCE(community_name, 'N/A') as "Community Name",
                COALESCE(department, heading, 'Unassigned') as "Department",
                COALESCE(office, sub_heading, 'Unassigned') as "Office",
                COALESCE(portfolio, '') as "Portfolio",
                COALESCE(heading, department, 'Unassigned') as "Heading",
                COALESCE(sub_heading, office, 'Unassigned') as "Sub-Heading",
                COALESCE(country, 'Unassigned') as "Country",
                COALESCE(zakat_eligibility, 'Unassigned') as "Zakat Eligibility",
                COALESCE(is_primary, 0) as "is_primary",
                company_id
            FROM campaign_classifications
        """
        if comp != "all":
            query += " WHERE company_id = ?"
            df = pd.read_sql_query(query, conn, params=(comp,))
        else:
            df = pd.read_sql_query(query, conn)
        conn.close()
    except Exception as e:
        print(f"[LaunchGood Matrix Query Notice]: {e}")
        df = get_classification_matrix(company_id=comp).fillna("Unassigned")

    df = sanitize_matrix_df(df)
    df = _enrich_rules_metadata(df)
    unassigned_count = (df["status"] == "unassigned").sum() if "status" in df.columns else 0
    return {
        "platform": "LaunchGood",
        "company_id": comp,
        "total_campaigns": len(df),
        "classified_campaigns": int(len(df) - unassigned_count),
        "unassigned_campaigns": int(unassigned_count),
        "rules": df.to_dict(orient="records")
    }


@router.get("/givebright")
def get_givebright_matrix(company_id: Optional[str] = Query("rethink")):
    """Returns GiveBright classification matrix rules with (Campaign Name, Code) granularity."""
    comp = (company_id or "rethink").strip().lower()
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        query = """
            SELECT 
                campaign_name as "Campaign Name",
                COALESCE(code, 'Unassigned') as "Code",
                COALESCE(campaign_url, '') as "Campaign URL",
                COALESCE(department, heading, 'Unassigned') as "Department",
                COALESCE(office, sub_heading, 'Unassigned') as "Office",
                COALESCE(portfolio, '') as "Portfolio",
                COALESCE(heading, department, 'Unassigned') as "Heading",
                COALESCE(sub_heading, office, 'Unassigned') as "Sub-Heading",
                COALESCE(country, 'Unassigned') as "Country",
                COALESCE(zakat_eligibility, 'Unassigned') as "Zakat Eligibility",
                COALESCE(is_primary, 0) as "is_primary",
                company_id
            FROM givebright_classifications
        """
        if comp != "all":
            query += " WHERE company_id = ?"
            df = pd.read_sql_query(query, conn, params=(comp,))
        else:
            df = pd.read_sql_query(query, conn)
        conn.close()
    except Exception as e:
        print(f"[GiveBright Matrix Query Notice]: {e}")
        df = get_givebright_classification_matrix(company_id=comp).fillna("Unassigned")

    # Strict mapping: Code -> Department, Office, Portfolio, Country, Zakat Eligibility
    code_map = get_code_to_classification_map(company_id=comp)
    if code_map and "Code" in df.columns:
        code_clean = df["Code"].astype(str).str.strip().str.lower()
        for tc in ["Department", "Office", "Portfolio", "Heading", "Sub-Heading", "Country", "Zakat Eligibility"]:
            if tc in df.columns:
                target_map = {k: v[tc] for k, v in code_map.items() if tc in v and v[tc] != "Unassigned"}
                mask_unassigned = df[tc].astype(str).str.strip().str.lower().isin(["", "unassigned", "nan", "none"])
                mapped_vals = code_clean.map(target_map)
                fill_mask = mask_unassigned & mapped_vals.notna()
                if fill_mask.any():
                    df.loc[fill_mask, tc] = mapped_vals[fill_mask]

    df = sanitize_matrix_df(df)
    df = _enrich_rules_metadata(df)
    unassigned_count = (df["status"] == "unassigned").sum() if "status" in df.columns else 0
    return {
        "platform": "GiveBright",
        "company_id": comp,
        "total_campaigns": len(df),
        "classified_campaigns": int(len(df) - unassigned_count),
        "unassigned_campaigns": int(unassigned_count),
        "rules": df.to_dict(orient="records")
    }


@router.get("/paysuite")
def get_paysuite_matrix(company_id: Optional[str] = Query("rethink")):
    """Returns Paysuite classification matrix rules with (Campaign Name, Code) granularity."""
    comp = (company_id or "rethink").strip().lower()
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        query = """
            SELECT 
                campaign_name as "Campaign Name",
                COALESCE(code, 'Unassigned') as "Code",
                COALESCE(community_name, 'N/A') as "Community Name",
                COALESCE(department, heading, 'Unassigned') as "Department",
                COALESCE(office, sub_heading, 'Unassigned') as "Office",
                COALESCE(portfolio, '') as "Portfolio",
                COALESCE(heading, department, 'Unassigned') as "Heading",
                COALESCE(sub_heading, office, 'Unassigned') as "Sub-Heading",
                COALESCE(country, 'Unassigned') as "Country",
                COALESCE(zakat_eligibility, 'Unassigned') as "Zakat Eligibility",
                COALESCE(donor_name, '') as "Donor Name",
                COALESCE(donor_email, '') as "Donor Email",
                COALESCE(is_primary, 0) as "is_primary",
                company_id
            FROM paysuite_classifications
        """
        if comp != "all":
            query += " WHERE company_id = ?"
            df = pd.read_sql_query(query, conn, params=(comp,))
        else:
            df = pd.read_sql_query(query, conn)
        conn.close()
    except Exception as e:
        print(f"[Paysuite Matrix Query Notice]: {e}")
        df = get_paysuite_classification_matrix(company_id=comp).fillna("Unassigned")

    df = sanitize_matrix_df(df)
    df = _enrich_rules_metadata(df)
    unassigned_count = (df["status"] == "unassigned").sum() if "status" in df.columns else 0
    return {
        "platform": "Paysuite",
        "company_id": comp,
        "total_campaigns": len(df),
        "classified_campaigns": int(len(df) - unassigned_count),
        "unassigned_campaigns": int(unassigned_count),
        "rules": df.to_dict(orient="records")
    }


@router.get("/website")
def get_rethink_website_matrix(company_id: Optional[str] = Query("rethink")):
    """Returns Website classification matrix rules with (Campaign Name, Code) granularity."""
    comp = (company_id or "rethink").strip().lower()
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        query = """
            SELECT 
                campaign_name as "Campaign Name",
                COALESCE(code, 'Unassigned') as "Code",
                COALESCE(community_name, 'N/A') as "Community Name",
                COALESCE(department, heading, 'Unassigned') as "Department",
                COALESCE(office, sub_heading, 'Unassigned') as "Office",
                COALESCE(portfolio, '') as "Portfolio",
                COALESCE(heading, department, 'Unassigned') as "Heading",
                COALESCE(sub_heading, office, 'Unassigned') as "Sub-Heading",
                COALESCE(country, 'Unassigned') as "Country",
                COALESCE(zakat_eligibility, 'Unassigned') as "Zakat Eligibility",
                COALESCE(is_primary, 0) as "is_primary",
                company_id
            FROM rethink_website_classifications
        """
        if comp != "all":
            query += " WHERE company_id = ?"
            df = pd.read_sql_query(query, conn, params=(comp,))
        else:
            df = pd.read_sql_query(query, conn)
        conn.close()
    except Exception as e:
        print(f"[Website Matrix Query Notice]: {e}")
        df = get_rethink_website_classification_matrix(company_id=comp).fillna("Unassigned")

    df = sanitize_matrix_df(df)
    df = _enrich_rules_metadata(df)
    unassigned_count = (df["status"] == "unassigned").sum() if "status" in df.columns else 0
    return {
        "platform": "Rethink Website",
        "company_id": comp,
        "total_campaigns": len(df),
        "classified_campaigns": int(len(df) - unassigned_count),
        "unassigned_campaigns": int(unassigned_count),
        "rules": df.to_dict(orient="records")
    }


@router.get("/madinah")
def get_madinah_matrix(company_id: Optional[str] = Query("iqra")):
    """Returns Madinah classification matrix rules with (Campaign Name, Code) granularity for Iqra."""
    comp = (company_id or "iqra").strip().lower()
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        query = """
            SELECT 
                campaign_name as "Campaign Name",
                COALESCE(code, 'Unassigned') as "Code",
                COALESCE(campaign_url, '') as "Campaign URL",
                COALESCE(department, heading, 'Unassigned') as "Department",
                COALESCE(office, sub_heading, 'Unassigned') as "Office",
                COALESCE(portfolio, '') as "Portfolio",
                COALESCE(heading, department, 'Unassigned') as "Heading",
                COALESCE(sub_heading, office, 'Unassigned') as "Sub-Heading",
                COALESCE(country, 'Unassigned') as "Country",
                COALESCE(zakat_eligibility, 'Unassigned') as "Zakat Eligibility",
                COALESCE(is_primary, 0) as "is_primary",
                company_id
            FROM madinah_classifications
        """
        if comp != "all":
            query += " WHERE company_id = ?"
            df = pd.read_sql_query(query, conn, params=(comp,))
        else:
            df = pd.read_sql_query(query, conn)
        conn.close()
    except Exception as e:
        print(f"[Madinah Matrix Query Notice]: {e}")
        df = pd.DataFrame(columns=["Campaign Name", "Code", "Campaign URL", "Department", "Office", "Portfolio", "Heading", "Sub-Heading", "Country", "Zakat Eligibility", "is_primary", "company_id"])

    # Strict mapping: Code -> Department, Office, Portfolio, Country, Zakat Eligibility
    code_map = get_code_to_classification_map(company_id=comp)
    if code_map and "Code" in df.columns:
        code_clean = df["Code"].astype(str).str.strip().str.lower()
        for tc in ["Department", "Office", "Portfolio", "Heading", "Sub-Heading", "Country", "Zakat Eligibility"]:
            if tc in df.columns:
                target_map = {k: v[tc] for k, v in code_map.items() if tc in v and v[tc] != "Unassigned"}
                mask_unassigned = df[tc].astype(str).str.strip().str.lower().isin(["", "unassigned", "nan", "none"])
                mapped_vals = code_clean.map(target_map)
                fill_mask = mask_unassigned & mapped_vals.notna()
                if fill_mask.any():
                    df.loc[fill_mask, tc] = mapped_vals[fill_mask]

    df = sanitize_matrix_df(df)
    df = _enrich_rules_metadata(df)
    unassigned_count = (df["status"] == "unassigned").sum() if "status" in df.columns else 0
    return {
        "platform": "Madinah",
        "company_id": comp,
        "total_campaigns": len(df),
        "classified_campaigns": int(len(df) - unassigned_count),
        "unassigned_campaigns": int(unassigned_count),
        "rules": df.to_dict(orient="records")
    }


@router.get("/export")
def export_classifications(
    platform: str = Query("launchgood", pattern="^(launchgood|givebright|madinah|paysuite|website|rethink_website|master)$"),
    format: str = Query("csv", pattern="^(csv|xlsx)$"),
    company_id: Optional[str] = Query("rethink")
):
    """Exports active campaign classification matrix rules or master project codes to CSV or Excel (.xlsx)."""
    p_clean = platform.lower().strip()
    comp = (company_id or "rethink").strip().lower()
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    if p_clean == "master":
        res = get_master_project_codes(company_id=comp)
        matrix_df = pd.DataFrame(res.get("codes", []))
        if matrix_df.empty:
            raise HTTPException(status_code=400, detail="No master project codes available to export.")
        export_cols = [
            "code", "company_id", "programme_fund", "fund_code", "department", "office", "portfolio", 
            "country", "zakat_eligibility", "legacy_non_zakat_code", "legacy_zakat_code", 
            "old_codes", "description", "is_active", "campaign_count", "total_raised"
        ]
        matrix_df = matrix_df[[c for c in export_cols if c in matrix_df.columns]]
        matrix_df = matrix_df.rename(columns={
            "code": "Code",
            "company_id": "Company",
            "programme_fund": "Programme Fund",
            "fund_code": "Fund Code",
            "department": "Department",
            "office": "Office",
            "portfolio": "Portfolio",
            "country": "Country",
            "zakat_eligibility": "Zakat Eligibility",
            "legacy_non_zakat_code": "Legacy Non-Zakat GL Code",
            "legacy_zakat_code": "Legacy Zakat GL Code",
            "old_codes": "Old Code(s)",
            "description": "Description",
            "is_active": "Active",
            "campaign_count": "Linked Campaigns",
            "total_raised": "Total Raised"
        })
    else:
        if p_clean == "givebright":
            res = get_givebright_matrix(company_id=comp)
        elif p_clean == "madinah":
            res = get_madinah_matrix(company_id=comp)
        elif p_clean == "paysuite":
            res = get_paysuite_matrix(company_id=comp)
        elif p_clean in ["website", "rethink_website", "rethink website"]:
            res = get_rethink_website_matrix(company_id=comp)
        else:
            res = get_launchgood_matrix(company_id=comp)

        matrix_df = pd.DataFrame(res.get("rules", []))
        if matrix_df.empty:
            raise HTTPException(status_code=400, detail="No classification rules available to export.")

        matrix_df = sanitize_matrix_df(matrix_df)

        # Rename columns to match the real headers in the frontend UI
        rename_map = {"Code": "Code (Master Link)"}
        if p_clean == "paysuite":
            rename_map["Campaign Name"] = "Direct Debit Ref (Bank Ref)"
            rename_map["Community Name"] = "Platform Source"
        
        matrix_df = matrix_df.rename(columns=rename_map)

        # Reorder columns to match UI exactly
        if p_clean == "paysuite":
            cols = ["Direct Debit Ref (Bank Ref)", "Platform Source", "Code (Master Link)", "Department", "Office", "Portfolio", "Country", "Zakat Eligibility", "Donor Name", "Donor Email"]
            matrix_df = matrix_df[[c for c in cols if c in matrix_df.columns]]
        elif p_clean in ["givebright", "madinah"]:
            cols = ["Campaign Name", "Campaign URL", "Code (Master Link)", "Department", "Office", "Portfolio", "Country", "Zakat Eligibility"]
            matrix_df = matrix_df[[c for c in cols if c in matrix_df.columns]]
        else:
            cols = ["Campaign Name", "Community Name", "Code (Master Link)", "Department", "Office", "Portfolio", "Country", "Zakat Eligibility"]
            matrix_df = matrix_df[[c for c in cols if c in matrix_df.columns]]

    if format.lower() == "xlsx":
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            matrix_df.to_excel(writer, index=False, sheet_name=f"{platform.capitalize()} Rules")
        buffer.seek(0)
        headers = {"Content-Disposition": f'attachment; filename="classifications_{platform}_{comp}_{date_str}.xlsx"'}
        return Response(
            content=buffer.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers
        )
    else:
        csv_bytes = matrix_df.to_csv(index=False).encode('utf-8-sig')
        headers = {"Content-Disposition": f'attachment; filename="classifications_{platform}_{comp}_{date_str}.csv"'}
        return Response(
            content=csv_bytes,
            media_type="text/csv",
            headers=headers
        )


@router.post("/save")
def save_matrix_rules(payload: SaveRulesRequest):
    comp = (payload.company_id or "rethink").strip().lower()
    if comp == "all":
        raise HTTPException(
            status_code=400,
            detail="Modifications cannot be performed in 'All Companies (Consolidated)' mode. Please select a specific company to save classification rules."
        )

    if payload.user_role not in ["super_admin", "admin"] and not payload.can_edit_matrix:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Modifying campaign classification matrix rules is restricted."
        )

    # 1. Collect non-unassigned classification metadata for every Code from submitted payload and existing map
    code_map = get_code_to_classification_map(force_reload=True, company_id=comp).copy()
    
    for r in payload.rules:
        code_str = str(r.get("Code") or r.get("code") or "").strip().lower()
        if code_str and code_str not in ["unassigned", "nan", "none", "n/a", ""]:
            dept = sanitize_text(r.get("Department") or r.get("department") or r.get("Heading") or r.get("heading", "Unassigned"))
            off = sanitize_text(r.get("Office") or r.get("office") or r.get("Sub-Heading") or r.get("sub_heading", "Unassigned"))
            port = sanitize_text(r.get("Portfolio") or r.get("portfolio", ""))
            c = sanitize_text(r.get("Country") or r.get("country", "Unassigned"))
            z = sanitize_text(r.get("Zakat Eligibility") or r.get("zakat_eligibility", "Unassigned"))

            if any(v != "Unassigned" for v in [dept, off, c, z]) or port != "":
                if code_str not in code_map:
                    code_map[code_str] = {
                        "Department": "Unassigned", 
                        "Office": "Unassigned", 
                        "Portfolio": "", 
                        "Heading": "Unassigned", 
                        "Sub-Heading": "Unassigned", 
                        "Country": "Unassigned", 
                        "Zakat Eligibility": "Unassigned"
                    }
                if dept != "Unassigned":
                    code_map[code_str]["Department"] = dept
                    code_map[code_str]["Heading"] = dept
                if off != "Unassigned":
                    code_map[code_str]["Office"] = off
                    code_map[code_str]["Sub-Heading"] = off
                if port != "":
                    code_map[code_str]["Portfolio"] = port
                if c != "Unassigned":
                    code_map[code_str]["Country"] = c
                if z != "Unassigned":
                    code_map[code_str]["Zakat Eligibility"] = z

    # 2. Build DataFrame and auto-fill any row that has a recognized Code
    rules_dict = []
    for r in payload.rules:
        code_raw = sanitize_text(r.get("Code") or r.get("code", "Unassigned"))
        code_lower = code_raw.strip().lower()
        
        dept = sanitize_text(r.get("Department") or r.get("department") or r.get("Heading") or r.get("heading", "Unassigned"))
        off = sanitize_text(r.get("Office") or r.get("office") or r.get("Sub-Heading") or r.get("sub_heading", "Unassigned"))
        port = sanitize_text(r.get("Portfolio") or r.get("portfolio", ""))
        c = sanitize_text(r.get("Country") or r.get("country", "Unassigned"))
        z = sanitize_text(r.get("Zakat Eligibility") or r.get("zakat_eligibility", "Unassigned"))

        if code_lower in code_map:
            c_info = code_map[code_lower]
            if dept == "Unassigned" and c_info.get("Department") != "Unassigned": dept = c_info["Department"]
            if off == "Unassigned" and c_info.get("Office") != "Unassigned": off = c_info["Office"]
            if not port and c_info.get("Portfolio"): port = c_info["Portfolio"]
            if c == "Unassigned" and c_info.get("Country") != "Unassigned": c = c_info["Country"]
            if z == "Unassigned" and c_info.get("Zakat Eligibility") != "Unassigned": z = c_info["Zakat Eligibility"]

        d_name = sanitize_text(r.get("Donor Name") or r.get("donor_name", ""))
        d_email = sanitize_text(r.get("Donor Email") or r.get("donor_email", ""))

        rules_dict.append({
            "Campaign Name": sanitize_text(r.get("Campaign Name") or r.get("campaign_name", "N/A")),
            "Campaign URL": sanitize_text(r.get("Campaign URL") or r.get("campaign_url", "")),
            "Community Name": sanitize_text(r.get("Community Name") or r.get("community_name", "Unassigned")),
            "Donor Name": d_name,
            "Donor Email": d_email,
            "Department": dept,
            "Office": off,
            "Portfolio": port,
            "Heading": dept,
            "Sub-Heading": off,
            "Country": c,
            "Code": code_raw,
            "Zakat Eligibility": z,
            "is_primary": 1 if r.get("is_primary") in [1, True, "1", "true", "True"] else 0
        })
    matrix_df = pd.DataFrame(rules_dict)
    matrix_df = matrix_df.drop_duplicates(subset=["Campaign Name", "Code"], keep="last")

    plat = payload.platform.lower().strip()
    if plat in ["website", "rethink_website", "rethink website"]:
        plat = "website"

    n_saved = save_platform_matrix_rules(plat, matrix_df, company_id=comp)

    # Reload central code dictionary after save
    get_code_to_classification_map(force_reload=True, company_id=comp)
    invalidate_payouts_cache()

    try:
        from backend.api.expenses import clear_expenses_cache
        clear_expenses_cache()
        from backend.api.events import broadcast_event_sync
        broadcast_event_sync("MATRIX_UPDATED", {"platform": payload.platform, "company_id": comp})
    except Exception:
        pass

    return {
        "status": "success",
        "message": f"Successfully saved {n_saved:,} {payload.platform} classification rules for {comp.upper()} and updated matching records in real time!"
    }


@router.post("/delete-rule")
def delete_single_rule(payload: DeleteRuleRequest):
    """Deletes a single classification rule (Super Admin only)."""
    comp = (payload.company_id or "rethink").strip().lower()
    if comp == "all":
        raise HTTPException(
            status_code=400,
            detail="Deleting classification rules cannot be performed in 'All Companies' mode. Please select a specific company."
        )

    if payload.user_role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Deleting classification rules is restricted to Super Admin accounts."
        )

    cname = sanitize_text(payload.campaign_name.strip())
    code = sanitize_text(payload.code.strip()) if payload.code else None
    platform = payload.platform.lower()
    plat_db = "givebright" if platform == "givebright" else ("madinah" if platform == "madinah" else ("paysuite" if platform == "paysuite" else ("website" if platform in ["website", "rethink_website", "rethink website"] else "launchgood")))

    with _DB_LOCK:
        conn = get_db_connection(timeout=60.0)
        try:
            with conn:
                if code:
                    conn.execute(
                        "DELETE FROM platform_campaign_mappings WHERE company_id = ? AND platform = ? AND LOWER(campaign_name) = ? AND LOWER(code) = ?",
                        (comp, plat_db, cname.lower(), code.lower())
                    )
                else:
                    conn.execute(
                        "DELETE FROM platform_campaign_mappings WHERE company_id = ? AND platform = ? AND LOWER(campaign_name) = ?",
                        (comp, plat_db, cname.lower())
                    )

                # Reset matching donations in DB for this company
                sql_update = """
                    UPDATE donations 
                    SET department='Unassigned', office='Unassigned', portfolio='', 
                        heading='Unassigned', sub_heading='Unassigned', country='Unassigned', 
                        code='Unassigned', zakat_eligibility='Unassigned' 
                    WHERE company_id = ? AND LOWER(campaign_name) = ?
                """
                params = [comp, cname.lower()]
                if code:
                    sql_update += " AND LOWER(code) = ?"
                    params.append(code.lower())
                conn.execute(sql_update, tuple(params))
        finally:
            conn.close()

    # Reset donor records matching this rule in parquet for this company
    if os.path.exists(PARQUET_PATH):
        try:
            df = pd.read_parquet(PARQUET_PATH)
            if not df.empty and "Campaign Name" in df.columns:
                comp_col = "company_id" if "company_id" in df.columns else None
                mask = df["Campaign Name"].astype(str).str.strip().str.lower() == cname.lower()
                if comp_col:
                    mask = mask & (df[comp_col].astype(str).str.strip().str.lower() == comp)
                if code and "Code" in df.columns:
                    mask = mask & (df["Code"].astype(str).str.strip().str.lower() == code.lower())
                if payload.community_name and "Community Name" in df.columns:
                    mask = mask & (df["Community Name"].astype(str).str.strip().str.lower() == payload.community_name.strip().lower())
                
                for f in ["Department", "Office", "Portfolio", "Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility"]:
                    if f in df.columns:
                        df.loc[mask, f] = "Unassigned" if f != "Portfolio" else ""
                
                df.to_parquet(PARQUET_PATH, index=False)
        except Exception as e:
            print(f"Error updating donors parquet on delete: {e}")

    invalidate_payouts_cache()
    try:
        from backend.api.expenses import clear_expenses_cache
        clear_expenses_cache()
        from backend.api.events import broadcast_event_sync
        broadcast_event_sync("MATRIX_UPDATED", {"platform": payload.platform, "action": "delete", "company_id": comp})
    except Exception:
        pass

    return {
        "status": "success",
        "message": f"Successfully deleted rule for '{cname}' ({code or 'all codes'}) in {comp.upper()}"
    }


@router.post("/clear-platform")
def clear_platform_rules(payload: ClearPlatformRequest):
    """Completely wipes classification rules for a platform (Super Admin only)."""
    comp = (payload.company_id or "rethink").strip().lower()
    if comp == "all":
        raise HTTPException(
            status_code=400,
            detail="Clearing platform rules cannot be performed in 'All Companies' mode. Please select a specific company."
        )

    if payload.user_role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Wiping classification rules is restricted to Super Admin accounts."
        )

    platform = payload.platform.lower()
    plat_db = "givebright" if platform == "givebright" else ("madinah" if platform == "madinah" else ("paysuite" if platform == "paysuite" else ("website" if platform in ["website", "rethink_website", "rethink website"] else "launchgood")))

    with _DB_LOCK:
        conn = get_db_connection(timeout=30.0)
        try:
            with conn:
                conn.execute("DELETE FROM platform_campaign_mappings WHERE company_id = ? AND platform = ?;", (comp, plat_db))
                conn.execute("""
                    UPDATE donations 
                    SET department='Unassigned', office='Unassigned', portfolio='', 
                        heading='Unassigned', sub_heading='Unassigned', country='Unassigned', 
                        code='Unassigned', zakat_eligibility='Unassigned' 
                    WHERE company_id = ? AND LOWER(platform) = ?
                """, (comp, plat_db))
        finally:
            conn.close()

    # Reset platform donor records to Unassigned in parquet for this company
    if os.path.exists(PARQUET_PATH):
        try:
            df = pd.read_parquet(PARQUET_PATH)
            if not df.empty and "Platform" in df.columns:
                comp_col = "company_id" if "company_id" in df.columns else None
                p_mask = df["Platform"].astype(str).str.lower() == platform
                if platform == "launchgood":
                    p_mask = p_mask | (df["Platform"].astype(str).str.lower().isin(["", "none", "nan"]))
                if comp_col:
                    p_mask = p_mask & (df[comp_col].astype(str).str.lower() == comp)
                
                for f in ["Department", "Office", "Portfolio", "Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility"]:
                    if f in df.columns:
                        df.loc[p_mask, f] = "Unassigned" if f != "Portfolio" else ""
                
                df.to_parquet(PARQUET_PATH, index=False)
        except Exception as e:
            print(f"Error resetting donors on clear: {e}")

    invalidate_payouts_cache()
    try:
        from backend.api.expenses import clear_expenses_cache
        clear_expenses_cache()
        from backend.api.events import broadcast_event_sync
        broadcast_event_sync("MATRIX_UPDATED", {"platform": payload.platform, "action": "clear", "company_id": comp})
    except Exception:
        pass

    return {
        "status": "success",
        "message": f"Successfully wiped all classification rules for {payload.platform} in {comp.upper()}"
    }


@router.post("/import")
async def import_classification_file(
    file: UploadFile = File(...),
    platform: str = Form("launchgood"),
    company_id: str = Form("rethink"),
    user_role: str = Form("admin"),
    mode: str = Form("merge")
):
    """Bulk uploads and applies a classification file (.csv or .xlsx) (Super Admin only)."""
    comp = company_id.strip().lower()
    if comp == "all":
        raise HTTPException(
            status_code=400,
            detail="Bulk import cannot be performed in 'All Companies' mode. Please select a specific company."
        )

    if user_role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bulk uploading classification files is restricted to Super Admin accounts."
        )

    contents = await file.read()
    try:
        if file.filename.lower().endswith(".csv"):
            raw_df = pd.read_csv(io.BytesIO(contents))
        else:
            raw_df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse uploaded file: {str(e)}")

    norm_df = normalize_classification_import_df(raw_df)
    norm_df = sanitize_matrix_df(norm_df)
    platform_clean = platform.lower()

    if mode == "merge":
        if platform_clean == "givebright":
            existing = get_givebright_classification_matrix(company_id=comp).fillna("Unassigned")
            merged = pd.concat([existing, norm_df], ignore_index=True).drop_duplicates(subset=["Campaign Name"], keep="last")
        elif platform_clean == "madinah":
            existing_res = get_madinah_matrix(company_id=comp).get("rules", [])
            existing = pd.DataFrame(existing_res).fillna("Unassigned") if existing_res else pd.DataFrame()
            merged = pd.concat([existing, norm_df], ignore_index=True).drop_duplicates(subset=["Campaign Name"], keep="last")
        elif platform_clean == "paysuite":
            existing = get_paysuite_classification_matrix(company_id=comp).fillna("Unassigned")
            merged = pd.concat([existing, norm_df], ignore_index=True).drop_duplicates(subset=["Campaign Name", "Community Name"], keep="last")
        else:
            existing = get_classification_matrix(company_id=comp).fillna("Unassigned")
            merged = pd.concat([existing, norm_df], ignore_index=True).drop_duplicates(subset=["Campaign Name", "Community Name"], keep="last")
    else:
        merged = norm_df

    if platform_clean in ["givebright", "madinah"]:
        # Strict mapping: Code -> Heading, Sub-Heading, Country, Zakat
        code_map = get_code_to_classification_map(company_id=comp)
        for idx, row in merged.iterrows():
            code = str(row.get("Code") or "").strip().lower()
            if code and code not in ["unassigned", "nan", "none", "n/a", ""]:
                if code in code_map:
                    c_info = code_map[code]
                    for tc in ["Heading", "Sub-Heading", "Country", "Zakat Eligibility"]:
                        merged.at[idx, tc] = sanitize_text(c_info[tc])

        merged = merged.drop_duplicates(subset=["Campaign Name"], keep="last")
        n_saved = save_platform_matrix_rules(platform_clean, merged, company_id=comp)
    elif platform_clean == "paysuite":
        n_saved = save_paysuite_classification_matrix(merged, company_id=comp)
        sync_matrix_classifications_to_donors(merged, company_id=comp)
    else:
        n_saved = save_classification_matrix(merged, company_id=comp)
        sync_matrix_classifications_to_donors(merged, company_id=comp)

    invalidate_payouts_cache()

    return {
        "status": "success",
        "count": n_saved,
        "message": f"Successfully imported and applied {n_saved:,} {platform.capitalize()} classification rules for {comp.upper()}!"
    }

