from core.cache import cached
import os
import math
import sqlite3
import threading
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from config.settings import LOCAL_DB_PATH, PARQUET_PATH, PAYOUTS_PARQUET_PATH
from core.data_processor import load_data, load_payouts_data, get_code_to_classification_map
from backend.api.events import broadcast_event_sync

router = APIRouter(prefix="/api/fundraisers", tags=["Fundraiser Tracking"])


def _extract_fundraiser_series(df: pd.DataFrame) -> pd.Series:
    """Extracts a normalized, lowercase fundraiser name series across all possible column aliases."""
    res = pd.Series("", index=df.index)
    for col in ["fundraiser_name", "Fundraiser Name", "fundraiser", "Fundraiser", "fundraiser_by"]:
        if col in df.columns:
            s = df[col].fillna("").astype(str).str.strip().str.lower()
            res = res.where(res != "", s)
    return res


# ---------------------------------------------------------------------------------------------------------
# Attribution: which fundraiser each donation counts towards (computed when read - donation rows are not edited)
#
# Explicit assignments win over the platform's own fundraiser name, and the NARROWEST page wins - the matching
# assignment whose page has the fewest donations (platform-neutral: on GiveBrite a person's page sits inside a team
# inside a campaign, on LaunchGood a person's campaign sits inside a community). Equal size: fundraiser page >
# community > campaign link > campaign name, then the older fundraiser.
# Same page assigned to two fundraisers (only possible for campaign names; links are unique per charity):
# the older fundraiser keeps it. Results are cached per charity on the donations version, so a new donation
# (any process) or a changed assignment shows up on the next request.
# ---------------------------------------------------------------------------------------------------------
LINK_MATCH_TYPES = {"fundraiser_url": "fundraiser", "community_url": "community", "campaign_url": "campaign"}
MATCH_PRECEDENCE = ["campaign_name", "campaign_url", "community_url", "fundraiser_url"]  # applied in order; later wins
MATCH_LABELS = {"campaign_name": "Campaign name", "campaign_url": "Campaign link",
                "community_url": "Community / team page", "fundraiser_url": "Fundraiser page"}
_UNASSIGNED_NAMES = ["", "unassigned", "none", "nan", "null", "no one claimed", "<na>"]
_LINK_KEYS_CACHE: Dict[str, Any] = {}
_LINK_KEYS_LOCK = threading.Lock()


def _norm_campaign_name(series: pd.Series) -> pd.Series:
    return (series.fillna("").astype(str).str.strip().str.lower()
            .str.replace("–", "-", regex=False).str.replace("—", "-", regex=False))


def _donation_keys(df: pd.DataFrame, comp: str) -> pd.DataFrame:
    """Link keys + normalised campaign name/code per donation, cached on the charity's donations version."""
    from core.cache import version_token
    from core.page_links import donation_link_keys
    token = version_token(["donations"], comp)
    hit = _LINK_KEYS_CACHE.get(comp)
    if hit and hit[0] == token and hit[1].index.equals(df.index):
        return hit[1]
    with _LINK_KEYS_LOCK:
        from core.page_links import learn_host_platforms
        keys = donation_link_keys(df)
        keys["cname"] = _norm_campaign_name(df["Campaign Name"]) if "Campaign Name" in df.columns else ""
        keys["code"] = df["Code"].fillna("").astype(str).str.strip().str.lower() if "Code" in df.columns else ""
        keys.attrs["host_platforms"] = learn_host_platforms(df)
        _LINK_KEYS_CACHE[comp] = (token, keys)
        return keys


def _host_platforms(comp: str) -> Dict[str, str]:
    """website -> platform learned from this charity's donations (works for any future platform too)."""
    df = load_data(company_id=comp)
    if df is None or df.empty:
        return {}
    return _donation_keys(df, comp).attrs.get("host_platforms", {})


_SP_NAME_RE = __import__("re").compile(r"(^|[^a-z])(sp|sisters'? ?project)([^a-z]|$)|^sp[_-]", __import__("re").I)


def is_sp_text(text: str) -> bool:
    """SP (Sisters' Project) marker in a fundraiser name, campaign name or page link: 'SP-Khawlah', 'SP: ...',
    'Sisters Project ...', LaunchGood pages named sp_xxx."""
    t = str(text or "").strip().lower()
    if not t:
        return False
    slug = t.rstrip("/").split("/")[-1].split("?")[0]
    return bool(_SP_NAME_RE.search(t)) or slug.startswith(("sp_", "sp-"))


def resolve_page_group(explicit: Optional[str], name: str, campaigns: List[str]) -> str:
    """'SP' or 'MAIN'. An explicit choice wins; otherwise SP when the name or any assigned page/campaign is SP."""
    e = str(explicit or "").strip().upper()
    if e in ("SP", "MAIN"):
        return e
    return "SP" if is_sp_text(name) or any(is_sp_text(c) for c in campaigns) else "MAIN"


def page_group_label(group: str, comp: str) -> str:
    return "SP" if group == "SP" else ("Iqra" if comp == "iqra" else "Rethink")


def platform_label(platform: str) -> str:
    known = {"launchgood": "LaunchGood", "givebrite": "GiveBrite", "givebright": "GiveBrite", "madinah": "Madinah"}
    return known.get(platform, platform.title() if platform and platform != "*" else "Any platform")


def _load_assignments(comp: str) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        q = """SELECT fc.id AS assignment_id, fc.fundraiser_id, f.name AS fundraiser_name, f.created_at AS f_created,
                      fc.campaign_name, fc.code, fc.platform, COALESCE(NULLIF(fc.match_type, ''), 'campaign_name') AS match_type,
                      COALESCE(fc.match_value, '') AS match_value, COALESCE(fc.match_key, '') AS match_key, fc.company_id
               FROM fundraiser_campaigns fc JOIN fundraisers f ON f.id = fc.fundraiser_id"""
        rows = conn.execute(q + (" WHERE fc.company_id = ?" if comp != "all" else ""), (comp,) if comp != "all" else ()).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def attribute_donations(df: pd.DataFrame, comp: str, assignments: Optional[List[Dict[str, Any]]] = None):
    """Returns (fundraiser_lower, assignment_id, match_type) Series aligned to df."""
    if assignments is None:
        assignments = _load_assignments(comp)
    fn = _extract_fundraiser_series(df)
    aid = pd.Series(None, index=df.index, dtype=object)
    mtype = pd.Series(None, index=df.index, dtype=object)
    if df.empty or not assignments:
        return fn, aid, mtype
    keys = _donation_keys(df, comp)
    import numpy as np
    # Row positions per key, computed once (fast dictionary lookups instead of a scan per assignment)
    index_of = {}

    def positions(col: str, value) -> np.ndarray:
        if col not in index_of:
            index_of[col] = keys[col].reset_index(drop=True).groupby(keys[col].reset_index(drop=True), sort=False).indices
        return index_of[col].get(value, np.empty(0, dtype=np.int64))

    if "cname_code" not in keys.columns:
        keys["cname_code"] = keys["cname"] + "::" + keys["code"]
    generic_code = keys["code"].isin(["", "all"]).to_numpy()

    matched = []  # (assignment, row positions)
    for a in assignments:
        name = str(a["fundraiser_name"] or "").strip().lower()
        if not name:
            continue
        if a["match_type"] == "campaign_name":
            cname = str(a.get("campaign_name") or "").strip().lower().replace("–", "-").replace("—", "-")
            code = str(a.get("code") or "ALL").strip().lower()
            if not cname:
                continue
            if code in ("all", "unassigned", ""):
                pos = positions("cname", cname)
            else:
                same_name = positions("cname", cname)
                pos = np.union1d(positions("cname_code", f"{cname}::{code}"), same_name[generic_code[same_name]])
        else:
            key = a.get("match_key") or ""
            kind = LINK_MATCH_TYPES.get(a["match_type"])
            if not key or not kind:
                continue
            pos = positions(f"{kind}_slug_key" if key.split("|")[1] == "*" else f"{kind}_key", key)
        matched.append((a, pos))

    # The NARROWEST page wins: a donation goes to the matching assignment whose page has the fewest donations
    # (a person's page inside a team inside a campaign - whatever the platform's hierarchy). Applied widest
    # first so narrower ones overwrite. Equal size: fundraiser page > community > campaign link > campaign name,
    # then the older fundraiser.
    rank = {t: i for i, t in enumerate(MATCH_PRECEDENCE)}
    matched.sort(key=lambda m: str(m[0].get("f_created") or ""), reverse=True)  # newest first -> older applied later
    matched.sort(key=lambda m: (-len(m[1]), rank.get(m[0]["match_type"], 0)))      # stable: widest first
    fn_arr, aid_arr, type_arr = fn.to_numpy(dtype=object).copy(), aid.to_numpy(dtype=object).copy(), mtype.to_numpy(dtype=object).copy()
    for a, pos in matched:
        if len(pos):
            fn_arr[pos] = str(a["fundraiser_name"]).strip().lower()
            aid_arr[pos] = a["assignment_id"]
            type_arr[pos] = a["match_type"]
    idx = df.index
    return pd.Series(fn_arr, index=idx), pd.Series(aid_arr, index=idx, dtype=object), pd.Series(type_arr, index=idx, dtype=object)


TRANSACTIONS_LIMIT = 2000


def clean_val(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "null", "n/a", "<na>", "nat") else s


def platform_raised_amount(df: pd.DataFrame) -> pd.Series:
    """What each donation adds to the page total SHOWN ON THE PLATFORM, in the charity's settlement currency,
    so fundraiser totals match the platforms (the CRM elsewhere reports the net amount received after fees):
      1. the platform's own per-page amount when it provides one (GiveBrite: amount_fundraiser / amount_campaign,
         converted by the platform itself),
      2. else the gross amount in the page's currency when that is the settlement currency (LaunchGood),
      3. else the gross amount in the settlement currency,
      4. else the net amount."""
    def num(col):
        return pd.to_numeric(df[col], errors="coerce") if col in df.columns else pd.Series(float("nan"), index=df.index)
    out = num("Total Online Donations Net Amount in Settled Currency")
    gross_settled = num("Total Online Donation Gross Amount in Settled Currency")
    out = out.where(~(gross_settled > 0), gross_settled)
    proj = num("Donation Amount in Project Currency (May be approx.)")
    pcur = df["Project Currency"].astype(str).str.strip().str.upper() if "Project Currency" in df.columns else pd.Series("", index=df.index)
    scur = df["Settlement Currency"].astype(str).str.strip().str.upper() if "Settlement Currency" in df.columns else pd.Series("", index=df.index)
    out = out.where(~((proj > 0) & pcur.str.len().between(3, 3) & (pcur == scur)), proj)
    for col in ("amount_campaign", "amount_fundraiser"):  # fundraiser page amount wins over campaign amount
        v = num(col)
        out = out.where(~(v > 0), v)
    return out.fillna(0.0)


def _tracked_page_stats(df: pd.DataFrame, aid: pd.Series, assignments: List[Dict[str, Any]],
                        start_date: Optional[str], end_date: Optional[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Per fundraiser: every assignment (campaign name or link) with the donations it brought in."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    work = pd.DataFrame({"aid": aid})
    work["amt"] = platform_raised_amount(df)
    date_col = next((c for c in ["_parsed_date", "Created Date (UTC)", "Date"] if c in df.columns), None)
    work["day"] = df[date_col].fillna("").astype(str).str[:10] if date_col else ""
    work["email"] = df["Email"].fillna("").astype(str).str.strip().str.lower() if "Email" in df.columns else ""
    work = work[work["aid"].notna()]
    grouped = {k: g for k, g in work.groupby("aid")} if not work.empty else {}
    for a in assignments:
        g = grouped.get(a["assignment_id"])
        period = g
        if g is not None and (start_date or end_date):
            m = pd.Series(True, index=g.index)
            if start_date:
                m &= g["day"] >= start_date
            if end_date:
                m &= g["day"] <= end_date
            period = g[m]
        valid_days = g["day"][g["day"].str.len() == 10] if g is not None else pd.Series(dtype=object)
        out.setdefault(a["fundraiser_id"], []).append({
            "assignment_id": a["assignment_id"],
            "match_type": a["match_type"],
            "match_label": MATCH_LABELS.get(a["match_type"], a["match_type"]),
            "value": a["match_value"] or a["campaign_name"],
            "code": a.get("code") or "ALL",
            "raised_all_time": round(float(g["amt"].sum()), 2) if g is not None else 0.0,
            "donations_all_time": int(len(g)) if g is not None else 0,
            "raised_period": round(float(period["amt"].sum()), 2) if period is not None else 0.0,
            "donations_period": int(len(period)) if period is not None else 0,
            "donors": int(g["email"][g["email"] != ""].nunique()) if g is not None else 0,
            "latest_donation_date": str(valid_days.max()) if len(valid_days) else None,
        })
    return out


def sync_assigned_campaigns_to_donations(company_id: str = "rethink") -> int:
    """
    Auto-populates fundraiser_name in donations table for any unassigned donations
    that match active campaigns assigned to registered fundraisers.
    Returns the number of donations updated.
    """
    init_fundraiser_db()
    comp = (company_id or "rethink").strip().lower()
    total_updated = 0
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
        cur = conn.cursor()

        # Fast check: If no unassigned donations exist, skip heavy updates entirely
        if comp != "all":
            cur.execute("""
                SELECT 1 FROM donations
                WHERE (fundraiser_name IS NULL OR TRIM(fundraiser_name) = '' OR LOWER(TRIM(fundraiser_name)) IN ('unassigned', 'none', 'nan', '<na>', 'null', 'no one claimed'))
                  AND LOWER(TRIM(company_id)) = LOWER(TRIM(?))
                LIMIT 1
            """, (comp,))
        else:
            cur.execute("""
                SELECT 1 FROM donations
                WHERE (fundraiser_name IS NULL OR TRIM(fundraiser_name) = '' OR LOWER(TRIM(fundraiser_name)) IN ('unassigned', 'none', 'nan', '<na>', 'null', 'no one claimed'))
                LIMIT 1
            """)
        if not cur.fetchone():
            conn.close()
            return 0

        if comp != "all":
            cur.execute("""
                SELECT f.name, fc.campaign_name, fc.code, fc.company_id
                FROM fundraiser_campaigns fc
                JOIN fundraisers f ON fc.fundraiser_id = f.id
                WHERE fc.company_id = ?
            """, (comp,))
        else:
            cur.execute("""
                SELECT f.name, fc.campaign_name, fc.code, fc.company_id
                FROM fundraiser_campaigns fc
                JOIN fundraisers f ON fc.fundraiser_id = f.id
            """)
        assignments = cur.fetchall()

        for f_name, c_name, c_code, cid in assignments:
            if not f_name or not c_name:
                continue
            code_clean = (c_code or "ALL").strip().upper()
            c_name_clean = c_name.strip()
            c_alt = c_name_clean.replace('–', '-') if '–' in c_name_clean else c_name_clean.replace('-', '–')

            if code_clean in ["ALL", "UNASSIGNED", ""] or not c_code:
                cur.execute("""
                    UPDATE donations
                    SET fundraiser_name = ?
                    WHERE (LOWER(TRIM([Campaign Name])) = LOWER(TRIM(?)) OR LOWER(TRIM([Campaign Name])) = LOWER(TRIM(?)))
                      AND (fundraiser_name IS NULL OR TRIM(fundraiser_name) = '' OR LOWER(TRIM(fundraiser_name)) IN ('unassigned', 'none', 'nan', '<na>', 'null', 'no one claimed'))
                      AND LOWER(TRIM(company_id)) = LOWER(TRIM(?))
                """, (f_name, c_name_clean, c_alt, cid))
            else:
                cur.execute("""
                    UPDATE donations
                    SET fundraiser_name = ?
                    WHERE (LOWER(TRIM([Campaign Name])) = LOWER(TRIM(?)) OR LOWER(TRIM([Campaign Name])) = LOWER(TRIM(?)))
                      AND (Code IS NULL OR TRIM(Code) = '' OR UPPER(TRIM(Code)) = ? OR UPPER(TRIM(Code)) = 'ALL')
                      AND (fundraiser_name IS NULL OR TRIM(fundraiser_name) = '' OR LOWER(TRIM(fundraiser_name)) IN ('unassigned', 'none', 'nan', '<na>', 'null', 'no one claimed'))
                      AND LOWER(TRIM(company_id)) = LOWER(TRIM(?))
                """, (f_name, c_name_clean, c_alt, code_clean, cid))
            total_updated += cur.rowcount

        conn.commit()
        conn.close()

        if total_updated > 0:
            _sync_parquet_and_cache_from_sqlite()
    except Exception as e:
        print(f"[Auto-sync Fundraiser Campaign Donations Notice]: {e}")

    return total_updated


def _sync_parquet_and_cache_from_sqlite():
    """
    Reads the updated donations table from SQLite, applies standard type sanitization,
    writes to PARQUET_PATH, and invalidates the in-memory cache so all endpoints stay synchronized.
    """
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
        df_donations = pd.read_sql("SELECT * FROM donations", conn)
        conn.close()

        from core.data_processor import sanitize_df_dtypes_for_parquet, invalidate_data_cache, atomic_write_parquet
        df_donations = sanitize_df_dtypes_for_parquet(df_donations)
        atomic_write_parquet(df_donations, PARQUET_PATH)
        invalidate_data_cache()
    except Exception as e:
        print(f"[Fundraiser Sync Parquet Notice]: {e}")


def init_fundraiser_db():
    """Initializes fundraisers and fundraiser_campaigns SQLite tables, and purges legacy auto-sync locks."""
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fundraisers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                company_id TEXT DEFAULT 'rethink',
                email TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                target_goal REAL DEFAULT 0.0,
                start_date TEXT DEFAULT '',
                status TEXT DEFAULT 'ACTIVE',
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fundraiser_campaigns (
                id TEXT PRIMARY KEY,
                fundraiser_id TEXT NOT NULL,
                campaign_name TEXT NOT NULL,
                code TEXT NOT NULL DEFAULT 'ALL',
                platform TEXT DEFAULT 'ALL',
                company_id TEXT DEFAULT 'rethink',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (fundraiser_id) REFERENCES fundraisers(id) ON DELETE CASCADE
            );
        """)

        # Migration safe-guards
        for tbl in ["fundraisers", "fundraiser_campaigns"]:
            try:
                cursor.execute(f"ALTER TABLE {tbl} ADD COLUMN company_id TEXT DEFAULT 'rethink';")
            except Exception:
                pass
        # Link-based assignments: match_type campaign_name (legacy) | campaign_url | community_url | fundraiser_url
        for col, ddl in (("match_type", "TEXT DEFAULT 'campaign_name'"), ("match_value", "TEXT DEFAULT ''"),
                         ("match_key", "TEXT DEFAULT ''")):
            try:
                cursor.execute(f"ALTER TABLE fundraiser_campaigns ADD COLUMN {col} {ddl};")
            except Exception:
                pass
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fc_company_key ON fundraiser_campaigns(company_id, match_key)")
        # Page group: 'SP' (Sisters' Project pages) or 'MAIN' (the charity's own Rethink / Iqra pages); '' = automatic
        try:
            cursor.execute("ALTER TABLE fundraisers ADD COLUMN page_group TEXT DEFAULT ''")
        except Exception:
            pass
        
        # Purge legacy auto-sync campaign locks (id starting with fc_) so campaigns are not falsely locked
        # (literal "fc_" prefix: in LIKE an unescaped "_" matches any character, which used to delete ordinary
        #  uuid-id assignments starting with "fc")
        cursor.execute("DELETE FROM fundraiser_campaigns WHERE id LIKE 'fc\\_%' ESCAPE '\\'")

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Fundraiser DB init notice: {e}")


init_fundraiser_db()


def calculate_benchmark_goal(raised_amount: float) -> float:
    """Calculates an intelligent benchmark target goal based on raised amount."""
    if raised_amount <= 500:
        return 500.0
    elif raised_amount <= 1000:
        return 1000.0
    elif raised_amount <= 5000:
        return math.ceil(raised_amount / 1000.0) * 1000.0
    elif raised_amount <= 20000:
        return math.ceil(raised_amount / 5000.0) * 5000.0
    elif raised_amount <= 100000:
        return math.ceil(raised_amount / 10000.0) * 10000.0
    else:
        return math.ceil(raised_amount / 25000.0) * 25000.0


def _page_names_claimed_by_links(cur, comp: str, candidate_lower_names: set) -> set:
    """Platform page names (donations' fundraiser_name) whose page is already assigned to a fundraiser by link.
    Discovery matches by name only, so without this a page-titled fundraiser that was renamed to the person
    would be re-created (empty) every time the Fundraisers page opens."""
    if not candidate_lower_names or comp == "all":
        return set()
    from core.page_links import normalise_platform, page_key, parse_page_link
    assigned = {r[0] for r in cur.execute(
        "SELECT match_key FROM fundraiser_campaigns WHERE company_id = ? AND COALESCE(match_key, '') != ''", (comp,))}
    if not assigned:
        return set()
    cols = {r[1] for r in cur.execute("PRAGMA table_info(donations)")}
    sources = [(c, k) for c, k in (("Fundraiser URL", "fundraiser"), ("fundraiser_url", "fundraiser"), ("Community URL", "community"),
                                   ("team_url", "community"), ("Campaign URL", "campaign"), ("campaign_url", "campaign")) if c in cols]
    if not sources:
        return set()
    select = ", ".join(f'"{c}"' for c, _k in sources)
    claimed = set()
    rows = cur.execute(f"""SELECT DISTINCT LOWER(TRIM(fundraiser_name)), Platform, {select} FROM donations
                           WHERE company_id = ? AND fundraiser_name IS NOT NULL AND TRIM(fundraiser_name) != ''""", (comp,)).fetchall()
    for row in rows:
        lname = row[0]
        if lname not in candidate_lower_names or lname in claimed:
            continue
        plat = normalise_platform(row[1])
        for (col, kind), raw in zip(sources, row[2:]):
            parsed = parse_page_link(str(raw or ""), plat) if raw else None
            if not parsed:
                continue
            k = kind if kind != "campaign" else parsed[0]
            if page_key(k, plat, parsed[2]) in assigned or page_key(k, "*", parsed[2]) in assigned:
                claimed.add(lname)
                break
    return claimed


def sync_discovered_fundraisers_internal(company_id: str = "rethink") -> int:
    """
    Scans the live donations dataset for unique fundraiser_name values not yet present
    in the fundraisers table and auto-registers them without creating false campaign locks.
    """
    init_fundraiser_db()
    comp = (company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    cur = conn.cursor()
    
    if comp != "all":
        cur.execute("SELECT LOWER(TRIM(name)) FROM fundraisers WHERE company_id = ?", (comp,))
    else:
        cur.execute("SELECT LOWER(TRIM(name)) FROM fundraisers")
    existing_lower_names = set(r[0] for r in cur.fetchall() if r[0])
    
    try:
        if comp != "all":
            cur.execute("""
                SELECT 
                    MAX(TRIM(fundraiser_name)) as fundraiser_name,
                    LOWER(TRIM(fundraiser_name)) as lower_name,
                    ROUND(SUM([Total Online Donations Net Amount in Settled Currency]), 2) as total_raised,
                    COUNT(*) as total_donations,
                    MIN([Created Date (UTC)]) as earliest_gift,
                    MAX([Created Date (UTC)]) as latest_gift
                FROM donations
                WHERE fundraiser_name IS NOT NULL AND TRIM(fundraiser_name) != '' AND company_id = ?
                GROUP BY LOWER(TRIM(fundraiser_name))
            """, (comp,))
        else:
            cur.execute("""
                SELECT 
                    MAX(TRIM(fundraiser_name)) as fundraiser_name,
                    LOWER(TRIM(fundraiser_name)) as lower_name,
                    ROUND(SUM([Total Online Donations Net Amount in Settled Currency]), 2) as total_raised,
                    COUNT(*) as total_donations,
                    MIN([Created Date (UTC)]) as earliest_gift,
                    MAX([Created Date (UTC)]) as latest_gift
                FROM donations
                WHERE fundraiser_name IS NOT NULL AND TRIM(fundraiser_name) != ''
                GROUP BY LOWER(TRIM(fundraiser_name))
            """)
        don_fundraisers = cur.fetchall()
    except Exception as e:
        print(f"Sync fundraisers query notice: {e}")
        conn.close()
        return 0
        
    new_fundraisers = []
    claimed_names = _page_names_claimed_by_links(cur, comp, {r[1] for r in don_fundraisers if r[1] not in existing_lower_names})

    for fname, lname, total_raised, total_dons, earliest_gift, latest_gift in don_fundraisers:
        if lname in claimed_names:
            continue  # the page is assigned to a fundraiser by its link (e.g. renamed to the person) - not a new one
        if lname not in existing_lower_names and fname:
            fid = f"fund_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{comp}_{lname}').hex[:16]}"
            raised = float(total_raised or 0.0)
            goal = calculate_benchmark_goal(raised)
            start_dt = str(earliest_gift or "").split("T")[0].split(" ")[0].strip()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            new_fundraisers.append((
                fid, fname, comp if comp != "all" else "rethink", "", "", goal, start_dt, "ACTIVE",
                f"Auto-discovered from donor data. Lifetime raised: £{raised:,.2f}",
                now_str, now_str
            ))
            existing_lower_names.add(lname)
    
    if new_fundraisers:
        cur.executemany("""
            INSERT INTO fundraisers (id, name, company_id, email, phone, target_goal, start_date, status, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, new_fundraisers)
        conn.commit()
        
    conn.close()
    return len(new_fundraisers)


try:
    sync_discovered_fundraisers_internal("rethink")
except Exception as _sync_err:
    pass


class CampaignAssignment(BaseModel):
    campaign_name: str = ""
    code: Optional[str] = "ALL"
    platform: Optional[str] = "ALL"
    # "campaign_name" (default, as before) or a page link: "campaign_url" | "community_url" | "fundraiser_url"
    match_type: Optional[str] = "campaign_name"
    match_value: Optional[str] = None  # the link as pasted


class CreateFundraiserRequest(BaseModel):
    user_role: str
    can_edit_donors: Optional[bool] = False
    name: str
    company_id: Optional[str] = "rethink"
    email: Optional[str] = ""
    phone: Optional[str] = ""
    target_goal: Optional[float] = 0.0
    start_date: Optional[str] = ""
    status: Optional[str] = "ACTIVE"
    notes: Optional[str] = ""
    assigned_campaigns: Optional[List[CampaignAssignment]] = []
    page_group: Optional[str] = ""  # 'SP' | 'MAIN' | '' (automatic)


class UpdateFundraiserRequest(BaseModel):
    user_role: str
    can_edit_donors: Optional[bool] = False
    name: str
    company_id: Optional[str] = "rethink"
    email: Optional[str] = ""
    phone: Optional[str] = ""
    target_goal: Optional[float] = 0.0
    start_date: Optional[str] = ""
    status: Optional[str] = "ACTIVE"
    notes: Optional[str] = ""
    assigned_campaigns: Optional[List[CampaignAssignment]] = []
    page_group: Optional[str] = ""


class AssignDonationsRequest(BaseModel):
    user_role: str
    can_edit_donors: Optional[bool] = False
    fundraiser_name: str
    company_id: Optional[str] = "rethink"
    campaign_name: Optional[str] = None
    code: Optional[str] = None
    donor_emails: Optional[List[str]] = []


_STATUS_RE = __import__("re").compile(r"^[A-Z0-9][A-Z0-9 _-]{0,29}$")


def _clean_status(raw: Optional[str]) -> str:
    """Any short status label (ACTIVE, PAUSED, COMPLETED, RAMADAN, or a custom one), stored upper-case."""
    status_val = " ".join(str(raw or "ACTIVE").strip().upper().split()) or "ACTIVE"
    if not _STATUS_RE.match(status_val):
        raise HTTPException(status_code=400, detail="Status must be 1-30 letters, numbers, spaces, - or _.")
    return status_val


def _prepare_assignments(items: Optional[List["CampaignAssignment"]], comp: str, fundraiser_id: Optional[str], cur) -> List[tuple]:
    """Validates assignments -> rows (campaign_name, code, platform, match_type, match_value, match_key).
    A page link may belong to only one fundraiser per charity."""
    from core.page_links import parse_page_link, page_key
    rows, seen = [], set()
    host_platforms = _host_platforms(comp) if any((c.match_type or "campaign_name") != "campaign_name" for c in items or []) else {}
    for c in items or []:
        match_type = (c.match_type or "campaign_name").strip().lower()
        if match_type == "campaign_name":
            name = (c.campaign_name or "").strip()
            if name:
                rows.append((name, (c.code or "ALL").strip(), (c.platform or "ALL").strip(), "campaign_name", "", ""))
            continue
        if match_type not in LINK_MATCH_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown assignment type '{match_type}'.")
        raw = (c.match_value or c.campaign_name or "").strip()
        parsed = parse_page_link(raw, host_platforms=host_platforms)
        if not parsed:
            raise HTTPException(status_code=400, detail=f"'{raw}' is not a page link (paste the full URL).")
        kind, family, slug = parsed
        if match_type == "fundraiser_url" and kind != "fundraiser":
            kind = "fundraiser"  # staff said it's a fundraiser page; trust the stated type
        elif match_type == "community_url" and kind not in ("community",):
            kind = "community"
        elif match_type == "campaign_url":
            kind = "campaign"
        key = page_key(kind, family, slug)
        if key in seen:
            continue
        seen.add(key)
        owner = cur.execute("""
            SELECT f.name FROM fundraiser_campaigns fc JOIN fundraisers f ON f.id = fc.fundraiser_id
            WHERE fc.company_id = ? AND fc.match_key = ? AND fc.fundraiser_id != ?""",
            (comp, key, fundraiser_id or "")).fetchone()
        if owner:
            raise HTTPException(status_code=409, detail=f"{raw} is already assigned to fundraiser '{owner[0]}'.")
        platform = platform_label(family) if family != "*" else "ALL"
        rows.append((raw, "ALL", platform, match_type, raw, key))
    return rows


def _check_super_admin(user_role: str, can_edit_donors: bool = False):
    """Strictly enforces that only Super Admin accounts can manage fundraisers."""
    role_clean = str(user_role or "").strip().lower()
    if role_clean != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Managing fundraisers is strictly restricted to Super Admin accounts."
        )


@router.get("/campaigns-list")
@cached(scopes=["fundraisers", "payouts", "donations", "classification"], ttl=21600)
def get_available_campaigns_list(company_id: Optional[str] = Query("rethink")):
    """
    Returns unique list of all (Campaign Name, Code, Platform, Heading) combinations
    across donations, payout settlements, and all classification tables in real-time.
    """
    init_fundraiser_db()
    comp = (company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    cur = conn.cursor()
    
    unique_pairs = set()
    campaign_items = []

    try:
        if comp != "all":
            cur.execute("""
                SELECT fc.fundraiser_id, fc.campaign_name, fc.code, f.name 
                FROM fundraiser_campaigns fc 
                JOIN fundraisers f ON fc.fundraiser_id = f.id
                WHERE f.company_id = ?
            """, (comp,))
        else:
            cur.execute("""
                SELECT fc.fundraiser_id, fc.campaign_name, fc.code, f.name 
                FROM fundraiser_campaigns fc 
                JOIN fundraisers f ON fc.fundraiser_id = f.id
            """)
        assigned_map = {}
        for fid, cname, code, fname in cur.fetchall():
            cname_key = str(cname).strip().lower()
            code_key = str(code or "ALL").strip().lower()
            assigned_map[(cname_key, code_key)] = {
                "fundraiser_id": fid,
                "fundraiser_name": fname,
                "code": code
            }

        # 1. From donations cached dataset
        try:
            df_don = load_data(company_id=comp)
            if df_don is not None and not df_don.empty and "Campaign Name" in df_don.columns:
                target_cols = [c for c in ["Campaign Name", "Code", "Platform", "Heading", "Sub-Heading", "Country"] if c in df_don.columns]
                df_unique = df_don[df_don["Campaign Name"].notna() & (df_don["Campaign Name"].astype(str).str.strip() != "")][target_cols].drop_duplicates(subset=["Campaign Name", "Code"] if "Code" in target_cols else ["Campaign Name"])
                for _, r in df_unique.iterrows():
                    cname_str = str(r.get("Campaign Name") or "").strip()
                    code_str = str(r.get("Code") or "Unassigned").strip() if "Code" in r else "Unassigned"
                    plat_str = str(r.get("Platform") or "LaunchGood").strip() if "Platform" in r else "LaunchGood"
                    head = str(r.get("Heading") or "Unassigned").strip() if "Heading" in r else "Unassigned"
                    subhead = str(r.get("Sub-Heading") or "Unassigned").strip() if "Sub-Heading" in r else "Unassigned"
                    country = str(r.get("Country") or "Unassigned").strip() if "Country" in r else "Unassigned"
                    key = (cname_str.lower(), code_str.lower())
                    if key not in unique_pairs and cname_str:
                        unique_pairs.add(key)
                        assigned_info = assigned_map.get(key) or assigned_map.get((cname_str.lower(), "all"))

                        campaign_items.append({
                            "campaign_name": cname_str,
                            "code": code_str,
                            "platform": plat_str,
                            "heading": head,
                            "sub_heading": subhead,
                            "country": country,
                            "is_assigned": False,
                            "assigned_to": assigned_info
                        })
        except Exception as e:
            print(f"[Fundraiser Campaign List Notice]: {e}")

        # 2. From payout_settlements table
        try:
            if comp != "all":
                cur.execute("""
                    SELECT DISTINCT 
                        [Campaign Name], 
                        COALESCE(Code, 'Unassigned'), 
                        'LaunchGood Payout', 
                        COALESCE(Heading, 'Unassigned'),
                        COALESCE([Sub-Heading], 'Unassigned'),
                        COALESCE(Country, 'Unassigned')
                    FROM payout_settlements 
                    WHERE [Campaign Name] IS NOT NULL AND TRIM([Campaign Name]) != '' AND company_id = ?
                """, (comp,))
            else:
                cur.execute("""
                    SELECT DISTINCT 
                        [Campaign Name], 
                        COALESCE(Code, 'Unassigned'), 
                        'LaunchGood Payout', 
                        COALESCE(Heading, 'Unassigned'),
                        COALESCE([Sub-Heading], 'Unassigned'),
                        COALESCE(Country, 'Unassigned')
                    FROM payout_settlements 
                    WHERE [Campaign Name] IS NOT NULL AND TRIM([Campaign Name]) != ''
                """)
            for cname, code, plat, head, subhead, country in cur.fetchall():
                cname_str = str(cname).strip()
                code_str = str(code).strip() if code else "Unassigned"
                key = (cname_str.lower(), code_str.lower())
                if key not in unique_pairs and cname_str:
                    unique_pairs.add(key)
                    assigned_info = assigned_map.get(key) or assigned_map.get((cname_str.lower(), "all"))

                    campaign_items.append({
                        "campaign_name": cname_str,
                        "code": code_str,
                        "platform": "LaunchGood Payout",
                        "heading": str(head or "Unassigned"),
                        "sub_heading": str(subhead or "Unassigned"),
                        "country": str(country or "Unassigned"),
                        "is_assigned": False,
                        "assigned_to": assigned_info
                    })
        except Exception:
            pass

        # 3. From all 4 classification matrix tables
        matrix_tables = [
            ("campaign_classifications", "LaunchGood"),
            ("givebright_classifications", "GiveBrite"),
            ("paysuite_classifications", "Paysuite"),
            ("rethink_website_classifications", "Rethink Website")
        ]
        for tbl, plat_name in matrix_tables:
            try:
                if comp != "all":
                    cur.execute(f"""
                        SELECT DISTINCT 
                            campaign_name, 
                            COALESCE(code, 'Unassigned'), 
                            heading, 
                            sub_heading, 
                            country 
                        FROM {tbl} 
                        WHERE campaign_name IS NOT NULL AND TRIM(campaign_name) != '' AND company_id = ?
                    """, (comp,))
                else:
                    cur.execute(f"""
                        SELECT DISTINCT 
                            campaign_name, 
                            COALESCE(code, 'Unassigned'), 
                            heading, 
                            sub_heading, 
                            country 
                        FROM {tbl} 
                        WHERE campaign_name IS NOT NULL AND TRIM(campaign_name) != ''
                    """)
                for cname, code, head, subhead, country in cur.fetchall():
                    cname_str = str(cname).strip()
                    code_str = str(code).strip() if code else "Unassigned"
                    key = (cname_str.lower(), code_str.lower())
                    if key not in unique_pairs and cname_str:
                        unique_pairs.add(key)
                        assigned_info = assigned_map.get(key) or assigned_map.get((cname_str.lower(), "all"))

                        campaign_items.append({
                            "campaign_name": cname_str,
                            "code": code_str,
                            "platform": plat_name,
                            "heading": str(head or "Unassigned"),
                            "sub_heading": str(subhead or "Unassigned"),
                            "country": str(country or "Unassigned"),
                            "is_assigned": False,
                            "assigned_to": assigned_info
                        })
            except Exception:
                pass
    finally:
        conn.close()

    campaign_items.sort(key=lambda x: (x["campaign_name"].lower(), x["code"].lower()))
    return campaign_items


@router.post("/sync-discovered")
def sync_discovered_fundraisers(company_id: Optional[str] = Query("rethink")):
    """
    On-demand endpoint to scan donations for new unique fundraiser_name entries
    and auto-seed them into fundraisers table, preserving existing admin customizations.
    """
    comp = (company_id or "rethink").strip().lower()
    new_count = sync_discovered_fundraisers_internal(comp)
    
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    cur = conn.cursor()
    if comp != "all":
        cur.execute("SELECT COUNT(*) FROM fundraisers WHERE company_id = ?", (comp,))
    else:
        cur.execute("SELECT COUNT(*) FROM fundraisers")
    total_count = cur.fetchone()[0]
    conn.close()

    if new_count > 0:
        try:
            broadcast_event_sync("FUNDRAISER_UPDATED", {"action": "sync", "company_id": comp, "new_count": new_count})
        except Exception:
            pass

    return {
        "status": "success",
        "company_id": comp,
        "newly_added_count": new_count,
        "total_fundraisers": total_count,
        "message": f"Sync completed. {new_count} new fundraisers discovered and added (Total: {total_count})."
    }


@router.get("")
@cached(scopes=["fundraisers", "payouts", "donations", "classification"], ttl=21600)
def get_fundraisers_list(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    status_filter: Optional[str] = "ALL",
    company_id: Optional[str] = Query("rethink"),
    page_group: Optional[str] = Query(None),
):
    """
    Returns list of all fundraisers with live aggregated metrics for the given company.
    Attribution is strictly derived from the fundraiser_name column in the donor dataset.
    """
    comp = (company_id or "rethink").strip().lower()
    status_clean = str(status_filter or "ALL").strip().upper()
    if status_clean in ["NONE", "", "NAN", "UNDEFINED"]:
        status_clean = "ALL"

    init_fundraiser_db()
    comp = (company_id or "rethink").strip().lower()

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        query = "SELECT * FROM fundraisers WHERE 1=1"
        params = []
        if comp != "all":
            query += " AND company_id = ?"
            params.append(comp)
        if status_clean != "ALL":
            query += " AND status = ?"
            params.append(status_clean)
        query += " ORDER BY created_at DESC"
        cur.execute(query, params)
        fundraiser_rows = [dict(r) for r in cur.fetchall()]

        if comp != "all":
            cur.execute("SELECT fundraiser_id, campaign_name, code, platform FROM fundraiser_campaigns WHERE company_id = ?", (comp,))
        else:
            cur.execute("SELECT fundraiser_id, campaign_name, code, platform FROM fundraiser_campaigns")
        assignments = cur.fetchall()
        f_campaign_map = {}
        for r in assignments:
            fid = r["fundraiser_id"]
            if fid not in f_campaign_map:
                f_campaign_map[fid] = []
            f_campaign_map[fid].append({
                "campaign_name": r["campaign_name"],
                "code": r["code"],
                "platform": r["platform"]
            })
    finally:
        conn.close()

    if not fundraiser_rows:
        return {
            "company_id": comp,
            "summary": {
                "total_fundraisers": 0,
                "total_raised_all_time": 0.0,
                "total_raised_period": 0.0,
                "total_target_goal": 0.0,
                "overall_progress_pct": 0.0,
                "total_donors": 0,
                "total_transactions": 0
            },
            "fundraisers": []
        }

    # Load live transaction data for this company
    df_donations = load_data(company_id=comp)
    assignments_full = _load_assignments(comp)
    tracked_pages_map: Dict[str, List[Dict[str, Any]]] = {}

    if df_donations is not None and not df_donations.empty:
        # Platform fundraiser name, overridden by explicit assignments (links / campaign names) - see attribute_donations
        fn_lower, attr_aid, _attr_type = attribute_donations(df_donations, comp, assignments_full)
        tracked_pages_map = _tracked_page_stats(df_donations, attr_aid, assignments_full, start_date, end_date)
        valid_fn = (fn_lower != "")
        df_named = df_donations[valid_fn].copy()
        df_named["fn_lower"] = fn_lower[valid_fn]
        df_named["net_num"] = platform_raised_amount(df_named)  # page totals as the platforms show them

        if "_parsed_date" not in df_named.columns or df_named["_parsed_date"].dropna().astype(str).str.strip().isin(["", "nan", "none", "nat"]).all():
            date_cand = next((c for c in ["_parsed_date", "Created Date (UTC)", "Date", "created_at", "Settled Date (UTC)"] if c in df_named.columns), None)
            df_named["_parsed_date"] = pd.to_datetime(df_named[date_cand], errors="coerce", dayfirst=True).dt.strftime("%Y-%m-%d").fillna("") if date_cand else ""
        else:
            df_named["_parsed_date"] = df_named["_parsed_date"].fillna("").astype(str).str.strip()

        df_work = df_named
        known_donation_fundraisers = set(df_named["fn_lower"].unique())
        
        # Fast group aggregations
        all_time_group = df_named.groupby("fn_lower")
        all_time_raised_map = all_time_group["net_num"].sum().to_dict()
        all_time_txns_map = all_time_group["net_num"].count().to_dict()
        df_valid_dates = df_named[df_named["_parsed_date"].str.len() >= 8]
        all_time_min_date_map = df_valid_dates.groupby("fn_lower")["_parsed_date"].min().to_dict() if not df_valid_dates.empty else {}
        all_time_max_date_map = df_valid_dates.groupby("fn_lower")["_parsed_date"].max().to_dict() if not df_valid_dates.empty else {}
        
        # Fast email sets
        if "Email" in df_named.columns:
            df_valid_emails = df_named[df_named["Email"].notna() & (~df_named["Email"].astype(str).str.strip().str.lower().isin(["", "nan", "none", "n/a"]))].copy()
            df_valid_emails["em_clean"] = df_valid_emails["Email"].astype(str).str.strip().str.lower()
            all_time_donors_map = df_valid_emails.groupby("fn_lower")["em_clean"].nunique().to_dict()
            all_time_emails_set_map = df_valid_emails.groupby("fn_lower")["em_clean"].apply(set).to_dict()
        else:
            all_time_donors_map = {}
            all_time_emails_set_map = {}

        # Build live campaign mappings from actual donor data for fundraisers without manual overrides
        all_time_campaigns_map = {}
        if not df_named.empty and "Campaign Name" in df_named.columns:
            cols_c = [c for c in ["Campaign Name", "Code", "Platform"] if c in df_named.columns]
            for fn_k, grp in df_named.groupby("fn_lower"):
                seen_c = set()
                c_list_items = []
                for _, r in grp[cols_c].drop_duplicates().iterrows():
                    c_name_val = str(r.get("Campaign Name") or "").strip()
                    c_code_val = str(r.get("Code") or "ALL").strip() if "Code" in r else "ALL"
                    c_plat_val = str(r.get("Platform") or "GiveBrite").strip() if "Platform" in r else "GiveBrite"
                    if c_name_val and (c_name_val.lower(), c_code_val.lower()) not in seen_c:
                        seen_c.add((c_name_val.lower(), c_code_val.lower()))
                        c_list_items.append({
                            "campaign_name": c_name_val,
                            "code": c_code_val,
                            "platform": c_plat_val
                        })
                all_time_campaigns_map[fn_k] = c_list_items

        # Period group aggregations if date filtered
        is_custom_filtered = bool(start_date or end_date)
        if is_custom_filtered:
            date_mask = pd.Series(True, index=df_work.index)
            if start_date:
                date_mask = date_mask & (df_work["_parsed_date"] >= start_date)
            if end_date:
                date_mask = date_mask & (df_work["_parsed_date"] <= end_date)
            
            df_period = df_work[date_mask].copy()
            df_period_named = df_period[df_period["fn_lower"] != ""].copy()
            period_group = df_period_named.groupby("fn_lower")
            period_raised_map = period_group["net_num"].sum().to_dict()
            period_txns_map = period_group["net_num"].count().to_dict()
            
            if "Email" in df_period_named.columns:
                df_p_valid = df_period_named[df_period_named["Email"].notna() & (~df_period_named["Email"].astype(str).str.strip().str.lower().isin(["", "nan", "none", "n/a"]))].copy()
                df_p_valid["em_clean"] = df_p_valid["Email"].astype(str).str.strip().str.lower()
                period_donors_map = df_p_valid.groupby("fn_lower")["em_clean"].nunique().to_dict()
            else:
                period_donors_map = {}
        else:
            df_period = df_work
            period_raised_map = all_time_raised_map
            period_txns_map = all_time_txns_map
            period_donors_map = all_time_donors_map
    else:
        df_work = pd.DataFrame()
        known_donation_fundraisers = set()
        all_time_raised_map = {}
        all_time_txns_map = {}
        all_time_min_date_map = {}
        all_time_max_date_map = {}
        all_time_donors_map = {}
        all_time_emails_set_map = {}
        all_time_campaigns_map = {}
        period_raised_map = {}
        period_txns_map = {}
        period_donors_map = {}
        is_custom_filtered = bool(start_date or end_date)

    fundraisers_result = []
    total_raised_all_time_sum = 0.0
    total_raised_period_sum = 0.0
    total_target_goal_sum = 0.0
    global_donor_emails = set()
    total_txns_sum = 0

    # Map DB fundraisers by lowercase name to preserve custom settings (goal, notes, status, email, phone)
    db_fundraisers_by_name = {str(r.get("name") or "").strip().lower(): r for r in fundraiser_rows if r.get("name")}
    # A fundraiser with assigned pages is listed even before its first donation arrives
    for r in fundraiser_rows:
        lname = str(r.get("name") or "").strip().lower()
        if lname and lname not in all_time_campaigns_map and tracked_pages_map.get(r["id"]):
            all_time_campaigns_map[lname] = [{"campaign_name": p["value"], "code": p["code"], "platform": p["match_label"]}
                                             for p in tracked_pages_map[r["id"]]]

    # Fundraisers exist strictly in real-time based on having active campaigns containing them in live donations
    for fn_k, c_list in all_time_campaigns_map.items():
        if not fn_k or not c_list:
            continue

        f_meta = db_fundraisers_by_name.get(fn_k)
        if f_meta:
            fid = f_meta["id"]
            fname = f_meta.get("name") or fn_k.title()
            target_goal = float(f_meta.get("target_goal") or 0.0)
            status = f_meta.get("status", "ACTIVE")
            notes = f_meta.get("notes", "")
            email = f_meta.get("email", "")
            phone = f_meta.get("phone", "")
            f_start_date = str(f_meta.get("start_date") or "").strip()
            created_at = f_meta.get("created_at", "")
        else:
            fid = f"fund_{uuid.uuid5(uuid.NAMESPACE_DNS, fn_k).hex[:16]}"
            sample_name = df_named[df_named["fn_lower"] == fn_k]["fundraiser_name"].dropna() if not df_named.empty else pd.Series()
            fname = str(sample_name.iloc[0]).strip() if not sample_name.empty else fn_k.title()
            raised_val = float(all_time_raised_map.get(fn_k, 0.0))
            target_goal = calculate_benchmark_goal(raised_val)
            status = "ACTIVE"
            notes = "Auto-discovered in real-time from donor data"
            email = ""
            phone = ""
            f_start_date = ""
            created_at = ""

        if status_clean != "ALL" and status.upper() != status_clean:
            continue
        group = resolve_page_group(f_meta.get("page_group") if f_meta else None, fname,
                                   [c.get("campaign_name", "") for c in c_list]
                                   + [p["value"] for p in (tracked_pages_map.get(fid, []) if f_meta else [])])
        wanted_group = str(getattr(page_group, "default", page_group) or "").strip().upper()
        if wanted_group in ("SP", "MAIN") and group != wanted_group:
            continue

        all_time_raised = float(all_time_raised_map.get(fn_k, 0.0))
        txn_count = int(all_time_txns_map.get(fn_k, 0))
        donor_count = int(all_time_donors_map.get(fn_k, 0))
        first_donation_date = str(all_time_min_date_map.get(fn_k) or "")
        latest_donation_date = str(all_time_max_date_map.get(fn_k) or "")
        
        period_raised = float(period_raised_map.get(fn_k, 0.0))
        period_txns = int(period_txns_map.get(fn_k, 0))
        period_donors = int(period_donors_map.get(fn_k, 0))

        if fn_k in all_time_emails_set_map:
            global_donor_emails.update(all_time_emails_set_map[fn_k])

        inception_date = first_donation_date or f_start_date or "N/A"
        progress_pct = round((all_time_raised / target_goal * 100.0), 1) if target_goal > 0 else (100.0 if all_time_raised > 0 else 0.0)
        period_progress_pct = round((period_raised / target_goal * 100.0), 1) if target_goal > 0 else 0.0
        avg_donation = round(all_time_raised / txn_count, 2) if txn_count > 0 else 0.0

        fundraiser_obj = {
            "id": fid,
            "name": fname,
            "email": email,
            "phone": phone,
            "target_goal": round(target_goal, 2),
            "first_donation_date": first_donation_date or "N/A",
            "latest_donation_date": latest_donation_date or "N/A",
            "inception_date": inception_date,
            "start_date": inception_date,
            "status": status,
            "notes": notes,
            "created_at": created_at,
            "assigned_campaigns": c_list,
            "total_raised_all_time": round(all_time_raised, 2),
            "total_raised_period": round(period_raised, 2),
            "is_custom_filtered": is_custom_filtered,
            "filter_start_date": start_date or "",
            "filter_end_date": end_date or "",
            "progress_percentage": min(progress_pct, 999.9),
            "period_progress_percentage": min(period_progress_pct, 999.9),
            "total_donors": donor_count,
            "period_donors": period_donors,
            "total_donations_count": txn_count,
            "period_donations_count": period_txns,
            "avg_donation": avg_donation,
            "average_donation": avg_donation,
            "tracked_pages": tracked_pages_map.get(fid, []) if f_meta else [],
            "page_group": group,
            "page_group_label": page_group_label(group, comp),
            "page_group_explicit": bool(f_meta and str(f_meta.get("page_group") or "").strip()),
        }

        fundraisers_result.append(fundraiser_obj)
        total_raised_all_time_sum += all_time_raised
        total_raised_period_sum += period_raised
        total_target_goal_sum += target_goal
        total_txns_sum += txn_count

    fundraisers_result.sort(key=lambda x: x["total_raised_all_time"], reverse=True)
    overall_progress = round((total_raised_all_time_sum / total_target_goal_sum * 100.0), 1) if total_target_goal_sum > 0 else 0.0

    return {
        "summary": {
            "total_fundraisers": len(fundraisers_result),
            "total_raised_all_time": round(total_raised_all_time_sum, 2),
            "total_raised_period": round(total_raised_period_sum, 2),
            "total_target_goal": round(total_target_goal_sum, 2),
            "overall_progress_pct": min(overall_progress, 999.9),
            "total_donors": len(global_donor_emails),
            "total_transactions": total_txns_sum,
            "is_custom_filtered": is_custom_filtered,
            "filter_start_date": start_date or "",
            "filter_end_date": end_date or ""
        },
        "fundraisers": fundraisers_result
    }

# ---------------------------------------------------------------------------------------------------------
# Page-link check, statuses and Ramadan date presets (declared before "/{fundraiser_id}")
# ---------------------------------------------------------------------------------------------------------
DEFAULT_STATUSES = ["ACTIVE", "PAUSED", "COMPLETED", "RAMADAN"]
RAMADAN_SETTING_KEY = "fundraiser_ramadan_periods"
# 1st of Ramadan -> last day of Ramadan (Eid al-Fitr is the next day). Editable by super admins, because local
# moon sighting can shift the start/end by a day.
DEFAULT_RAMADAN_PERIODS = [
    {"year": 2024, "start": "2024-03-11", "end": "2024-04-09"},
    {"year": 2025, "start": "2025-03-01", "end": "2025-03-29"},
    {"year": 2026, "start": "2026-02-18", "end": "2026-03-19"},
    {"year": 2027, "start": "2027-02-08", "end": "2027-03-09", "estimated": True},
]


@router.get("/resolve-link")
def resolve_fundraiser_link(company_id: str = Query(...), url: str = Query(...),
                            match_type: Optional[str] = Query(None), exclude_fundraiser_id: Optional[str] = Query(None)):
    """What a pasted page link matches in this charity's donations - before saving it as an assignment."""
    from core.page_links import parse_page_link, page_key
    comp = (company_id or "").strip().lower()
    parsed = parse_page_link(url, host_platforms=_host_platforms(comp))
    if not parsed:
        raise HTTPException(status_code=400, detail="That doesn't look like a page link. Paste the full URL.")
    kind, family, slug = parsed
    forced = LINK_MATCH_TYPES.get((match_type or "").strip().lower())
    if forced:
        kind = forced
    key = page_key(kind, family, slug)
    out = {"kind": kind, "platform": platform_label(family),
           "slug": slug, "match_type": f"{kind}_url", "match_key": key, "donations": 0, "raised": 0.0,
           "latest_donation_date": None, "campaigns": [], "currently_credited_to": [], "assigned_to": None}
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        owner = conn.execute("""SELECT f.name FROM fundraiser_campaigns fc JOIN fundraisers f ON f.id = fc.fundraiser_id
                                WHERE fc.company_id = ? AND fc.match_key = ? AND fc.fundraiser_id != ?""",
                             (comp, key, exclude_fundraiser_id or "")).fetchone()
        out["assigned_to"] = owner[0] if owner else None
    finally:
        conn.close()
    df = load_data(company_id=comp)
    if df is None or df.empty:
        return out
    keys = _donation_keys(df, comp)
    mask = (keys[f"{kind}_slug_key"] == page_key(kind, "*", slug)) if family == "*" else (keys[f"{kind}_key"] == key)
    if not mask.any():
        return out
    sub = df[mask]
    fn, _aid, _t = attribute_donations(df, comp)
    credited = fn[mask].replace("", "(unassigned)").value_counts().head(3)
    date_col = next((c for c in ["_parsed_date", "Created Date (UTC)", "Date"] if c in sub.columns), None)
    days = sub[date_col].fillna("").astype(str).str[:10] if date_col else pd.Series(dtype=object)
    out.update(
        donations=int(mask.sum()),
        raised=round(float(platform_raised_amount(sub).sum()), 2),
        latest_donation_date=str(days[days.str.len() == 10].max()) if len(days) else None,
        campaigns=sub["Campaign Name"].dropna().astype(str).str.strip().value_counts().head(5).index.tolist() if "Campaign Name" in sub.columns else [],
        currently_credited_to=[{"fundraiser": k, "donations": int(v)} for k, v in credited.items()],
    )
    return out


@router.get("/statuses")
def get_fundraiser_statuses(company_id: Optional[str] = Query("rethink")):
    comp = (company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        q = "SELECT DISTINCT UPPER(TRIM(status)) FROM fundraisers WHERE COALESCE(TRIM(status), '') != ''"
        used = [r[0] for r in conn.execute(q + (" AND company_id = ?" if comp != "all" else ""), (comp,) if comp != "all" else ())]
    finally:
        conn.close()
    return {"statuses": DEFAULT_STATUSES + sorted(s for s in set(used) if s not in DEFAULT_STATUSES)}


def _read_ramadan_periods() -> List[Dict[str, Any]]:
    import json as _json
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        row = conn.execute("SELECT setting_value FROM system_settings WHERE setting_key = ?", (RAMADAN_SETTING_KEY,)).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        conn.close()
    try:
        periods = _json.loads(row[0]) if row and row[0] else DEFAULT_RAMADAN_PERIODS
    except ValueError:
        periods = DEFAULT_RAMADAN_PERIODS
    return sorted(periods, key=lambda p: p["year"])


@router.get("/ramadan-periods")
def get_ramadan_periods(company_id: Optional[str] = Query("rethink")):
    """Ramadan start/end per year, used by the 'Ramadan' date presets (incl. 2/3/4 weeks after)."""
    return {"periods": _read_ramadan_periods()}


class RamadanPeriod(BaseModel):
    year: int
    start: str
    end: str
    estimated: Optional[bool] = False


class RamadanPeriodsRequest(BaseModel):
    company_id: Optional[str] = "rethink"
    periods: List[RamadanPeriod]


@router.put("/ramadan-periods")
def update_ramadan_periods(payload: RamadanPeriodsRequest, request: Request):
    import json as _json
    user = getattr(request.state, "api_user", None) or {}
    if user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only Super Admins can change the Ramadan dates.")
    clean = []
    for p in payload.periods:
        try:
            start = datetime.strptime(p.start[:10], "%Y-%m-%d")
            end = datetime.strptime(p.end[:10], "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Dates for {p.year} must be YYYY-MM-DD.")
        if not (0 < (end - start).days <= 31):
            raise HTTPException(status_code=400, detail=f"Ramadan {p.year}: the end must be 1-31 days after the start.")
        clean.append({"year": p.year, "start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"),
                      "estimated": bool(p.estimated)})
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        with conn:
            conn.execute("""INSERT INTO system_settings (setting_key, setting_value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                            ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value,
                            updated_at = CURRENT_TIMESTAMP""", (RAMADAN_SETTING_KEY, _json.dumps(clean)))
    finally:
        conn.close()
    return {"periods": sorted(clean, key=lambda p: p["year"])}


@router.get("/{fundraiser_id}")
@cached(scopes=["fundraisers", "payouts", "donations", "classification"], ttl=21600)
def get_fundraiser_detail(
    fundraiser_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    company_id: Optional[str] = Query("rethink"),
    tx_page: int = Query(1, ge=1),
    tx_page_size: int = Query(100, ge=10, le=500),
    tx_search: Optional[str] = Query(None),
):
    """
    Returns deep drilldown for a single fundraiser:
    individual campaign breakdown, monthly timeline, and recent transactions log.
    Includes both directly stamped donations and live donations matching assigned campaigns.
    """
    init_fundraiser_db()
    comp = (company_id or "rethink").strip().lower()

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    fundraiser = None
    db_assigned_campaigns = []
    try:
        if comp != "all":
            cur.execute("SELECT * FROM fundraisers WHERE id = ? AND company_id = ?", (fundraiser_id, comp))
        else:
            cur.execute("SELECT * FROM fundraisers WHERE id = ?", (fundraiser_id,))
        f_row = cur.fetchone()
        if f_row:
            fundraiser = dict(f_row)
            cur.execute("SELECT campaign_name, code, platform FROM fundraiser_campaigns WHERE fundraiser_id = ?", (fundraiser["id"],))
            db_assigned_campaigns = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    df_donations = load_data(company_id=comp)
    amount_col = "Total Online Donations Net Amount in Settled Currency"

    campaign_breakdown = []
    recent_transactions = []
    monthly_timeline = {}
    first_donation_date = None
    latest_donation_date = None
    total_raised_all_time = 0.0
    total_raised_period = 0.0
    assigned_campaigns = []
    # defaults for a fundraiser whose pages have no donations yet
    first_gift_all_time = latest_gift_all_time = first_gift_period = latest_gift_period = None
    net_received_all_time = 0.0
    transactions_total = 0
    transactions_all = 0
    attr_aid = None
    is_filtered = bool(start_date or end_date)

    tracked_pages: List[Dict[str, Any]] = []
    if df_donations is not None and not df_donations.empty:
        assignments_full = _load_assignments(comp)
        fn_series, attr_aid, _attr_type = attribute_donations(df_donations, comp, assignments_full)

        # If not found in SQLite by ID, resolve real-time fundraiser profile from live donor data
        if not fundraiser:
            for fn_k in fn_series[fn_series != ""].unique():
                synth_id = f"fund_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{comp}_{fn_k}').hex[:16]}"
                if synth_id == fundraiser_id or fn_k == fundraiser_id.lower():
                    sample_name = df_donations[fn_series == fn_k]["fundraiser_name"].dropna() if "fundraiser_name" in df_donations.columns else pd.Series()
                    display_name = str(sample_name.iloc[0]).strip() if not sample_name.empty else fn_k.title()
                    fundraiser = {
                        "id": fundraiser_id,
                        "name": display_name,
                        "company_id": comp,
                        "email": "",
                        "phone": "",
                        "target_goal": 0.0,
                        "status": "ACTIVE",
                        "notes": "Auto-discovered in real-time from donor data",
                        "created_at": ""
                    }
                    break

        if not fundraiser:
            raise HTTPException(status_code=404, detail="Fundraiser not found.")

        fname_clean = str(fundraiser.get("name") or "").strip().lower()
        # Same attribution as the list: explicit page/campaign assignments first, then the platform's name
        claim_mask = (fn_series == fname_clean)
        own_assignments = [a for a in assignments_full if a["fundraiser_id"] == fundraiser.get("id")]
        page_label = {a["assignment_id"]: (a.get("match_value") or a.get("campaign_name") or "") for a in own_assignments}
        tracked_pages = _tracked_page_stats(df_donations, attr_aid, own_assignments, start_date, end_date).get(fundraiser.get("id"), [])
        sub_df = df_donations[claim_mask].copy()
        if sub_df.empty and not own_assignments:
            raise HTTPException(status_code=404, detail="Fundraiser has no active campaigns or donations.")

        # Compute column helpers on the compact sub_df (instant execution)
        sub_df["cname_lower"] = (
            sub_df["Campaign Name"].fillna("").astype(str).str.strip().str.lower()
            .str.replace('–', '-', regex=False).str.replace('—', '-', regex=False)
            if "Campaign Name" in sub_df.columns else ""
        )
        sub_df["code_lower"] = sub_df["Code"].fillna("").astype(str).str.strip().str.lower() if "Code" in sub_df.columns else ""
        sub_df["net_num"] = platform_raised_amount(sub_df)  # as shown on the platform
        net_received_all_time = float(pd.to_numeric(sub_df[amount_col], errors="coerce").fillna(0.0).sum()) if amount_col in sub_df.columns else 0.0

        if "_parsed_date" not in sub_df.columns or sub_df["_parsed_date"].dropna().astype(str).str.strip().isin(["", "nan", "none", "nat"]).all():
            date_cand = next((c for c in ["_parsed_date", "Created Date (UTC)", "Date", "created_at", "Settled Date (UTC)"] if c in sub_df.columns), None)
            if date_cand:
                sub_df["_parsed_date"] = pd.to_datetime(sub_df[date_cand], errors="coerce", dayfirst=True).dt.strftime("%Y-%m-%d").fillna("")
            else:
                sub_df["_parsed_date"] = ""
        else:
            sub_df["_parsed_date"] = sub_df["_parsed_date"].fillna("").astype(str).str.strip()

        # Real-time campaign list combined from DB assignments and active donations
        seen_c = set()
        c_list_items = []
        for ac in db_assigned_campaigns:
            c_name_val = str(ac.get("campaign_name") or "").strip()
            c_code_val = str(ac.get("code") or "ALL").strip()
            c_plat_val = str(ac.get("platform") or "LaunchGood").strip()
            if c_name_val and (c_name_val.lower(), c_code_val.lower()) not in seen_c:
                seen_c.add((c_name_val.lower(), c_code_val.lower()))
                c_list_items.append({
                    "campaign_name": c_name_val,
                    "code": c_code_val,
                    "platform": c_plat_val
                })

        cols_c = [c for c in ["Campaign Name", "Code", "Platform"] if c in sub_df.columns]
        for _, r in sub_df[cols_c].drop_duplicates().iterrows():
            c_name_val = str(r.get("Campaign Name") or "").strip()
            c_code_val = str(r.get("Code") or "ALL").strip() if "Code" in r else "ALL"
            c_plat_val = str(r.get("Platform") or "GiveBrite").strip() if "Platform" in r else "GiveBrite"
            if c_name_val and (c_name_val.lower(), c_code_val.lower()) not in seen_c:
                seen_c.add((c_name_val.lower(), c_code_val.lower()))
                c_list_items.append({
                    "campaign_name": c_name_val,
                    "code": c_code_val,
                    "platform": c_plat_val
                })
        assigned_campaigns = c_list_items

        if not sub_df.empty:
            total_raised_all_time = float(sub_df["net_num"].sum())

            # Unified date series for period calculations and monthly aggregation
            date_series = sub_df["_parsed_date"].copy() if "_parsed_date" in sub_df.columns else pd.Series("", index=sub_df.index)
            if "Created Date (UTC)" in sub_df.columns:
                fallback_dates = pd.to_datetime(sub_df["Created Date (UTC)"], errors="coerce", format="mixed").dt.strftime("%Y-%m-%d").fillna("")
                date_series = date_series.where(date_series != "", fallback_dates)
            sub_df["_calc_date"] = date_series

            # Date filtering for period calculations
            period_sub = sub_df
            if start_date or end_date:
                d_mask = pd.Series(True, index=sub_df.index)
                if start_date:
                    d_mask = d_mask & (sub_df["_calc_date"] >= start_date)
                if end_date:
                    d_mask = d_mask & (sub_df["_calc_date"] <= end_date)
                period_sub = sub_df[d_mask]

            total_raised_period = float(period_sub["net_num"].sum()) if not period_sub.empty else 0.0

            # Group by Campaign Breakdown (case-insensitive & whitespace-deduplicated)
            if "Campaign Name" in sub_df.columns:
                cname_display_map = {}
                for ac in assigned_campaigns:
                    cname_display_map[ac["campaign_name"].strip().lower()] = ac["campaign_name"].strip()
                for c_raw in sub_df["Campaign Name"].dropna().unique():
                    c_clean = str(c_raw).strip()
                    if c_clean.lower() not in cname_display_map:
                        cname_display_map[c_clean.lower()] = c_clean

                c_grouped = sub_df.groupby(["cname_lower", "code_lower"])
                for (cname_key, code_key), c_grp in c_grouped:
                    display_name = cname_display_map.get(cname_key, cname_key.title())
                    code_display = (
                        str(c_grp["Code"].iloc[0]).strip()
                        if "Code" in c_grp.columns and pd.notna(c_grp["Code"].iloc[0]) and str(c_grp["Code"].iloc[0]).strip()
                        else (code_key.upper() if code_key != "all" else "ALL")
                    )
                    gross_all = float(c_grp["net_num"].sum())

                    c_period = period_sub[(period_sub["cname_lower"] == cname_key) & (period_sub["code_lower"] == code_key)] if not period_sub.empty else pd.DataFrame()
                    gross_p = float(c_period["net_num"].sum()) if not c_period.empty else 0.0
                    p_txns = len(c_period) if not c_period.empty else 0
                    p_donors = len(set(c_period["Email"].dropna().astype(str).str.strip().str.lower())) if (not c_period.empty and "Email" in c_period.columns) else 0

                    campaign_breakdown.append({
                        "campaign_name": display_name,
                        "code": code_display,
                        "platform": str(c_grp["Platform"].iloc[0]) if "Platform" in c_grp.columns and not c_grp["Platform"].empty and pd.notna(c_grp["Platform"].iloc[0]) else "GiveBrite",
                        "gross_raised": round(gross_p if (start_date or end_date) else gross_all, 2),
                        "gross_raised_all_time": round(gross_all, 2),
                        "total_donations": p_txns if (start_date or end_date) else len(c_grp),
                        "total_donors": p_donors if (start_date or end_date) else len(set(c_grp["Email"].dropna().astype(str).str.strip().str.lower())) if "Email" in c_grp.columns else 0,
                        "heading": str(c_grp["Heading"].iloc[0]) if "Heading" in c_grp.columns and not c_grp["Heading"].empty and pd.notna(c_grp["Heading"].iloc[0]) else "Unassigned",
                        "country": str(c_grp["Country"].iloc[0]) if "Country" in c_grp.columns and not c_grp["Country"].empty and pd.notna(c_grp["Country"].iloc[0]) else "Unassigned"
                    })

            # Monthly aggregation across verified dates (dynamic for period if filtered)
            is_filtered = bool(start_date or end_date)
            timeline_target = period_sub if is_filtered else sub_df
            for d_val, amt in zip(timeline_target["_calc_date"], timeline_target["net_num"]):
                d_str = str(d_val).strip()
                if d_str and d_str.lower() not in ["nan", "none", "nat", ""]:
                    m_prefix = d_str[:7]
                    if len(m_prefix) == 7 and m_prefix[4] == "-":
                        monthly_timeline[m_prefix] = monthly_timeline.get(m_prefix, 0.0) + float(amt)

            # Recent transactions log
            # every donation in the period (newest first, capped for very large fundraisers), with full detail
            period_sub = period_sub.assign(
                _page=attr_aid.reindex(period_sub.index).map(lambda a: page_label.get(a, "")) if attr_aid is not None else "",
                _net_received=pd.to_numeric(period_sub.get("Total Online Donations Net Amount in Settled Currency"), errors="coerce"),
            )
            sample_cols = [c for c in ["_calc_date", "_parsed_date", "Created Date (UTC)", "Donor Name", "First Name", "Last Name", "Email", "Campaign Name", "Code", "net_num", "Platform",
                                       "Donation ID", "Heading", "Sub-Heading", "Giving Level Title", "Gift Aid (yes or no)", "Status", "fundraiser_name",
                                       "Donation Currency (DC)", "Donation Amount (in Donation Currency)", "_page", "_net_received", "Donor ID"] if c in period_sub.columns]
            sort_cand = "_calc_date" if "_calc_date" in period_sub.columns else ("_parsed_date" if "_parsed_date" in period_sub.columns else "Created Date (UTC)")
            # Paged (and searched) on the server: every donation is reachable, not only the newest 2,000
            tx_frame = period_sub
            transactions_all = int(len(period_sub))
            q = (tx_search or "").strip().lower()
            if q:
                hay = pd.Series("", index=tx_frame.index)
                for c in ("Donor Name", "First Name", "Last Name", "Email", "Campaign Name", "Code", "Heading", "Sub-Heading",
                          "Giving Level Title", "Donation ID", "_page", "Platform"):
                    if c in tx_frame.columns:
                        hay = hay + " " + tx_frame[c].astype(str).str.lower()
                tx_frame = tx_frame[hay.str.contains(q, regex=False, na=False)]
            transactions_total = int(len(tx_frame))
            start = (tx_page - 1) * tx_page_size
            tx_sample = tx_frame[sample_cols].sort_values(sort_cand, ascending=False).iloc[start:start + tx_page_size].to_dict('records')
            for t in tx_sample:
                fn = str(t.get("First Name") or "").strip() if pd.notna(t.get("First Name")) else ""
                ln = str(t.get("Last Name") or "").strip() if pd.notna(t.get("Last Name")) else ""
                raw_name = t.get("Donor Name")
                name = str(raw_name).strip() if pd.notna(raw_name) and str(raw_name).strip() else (f"{fn} {ln}".strip() or "Anonymous")

                email_val = t.get("Email")
                email_str = str(email_val).strip() if pd.notna(email_val) and str(email_val).strip().lower() not in ["nan", "none", ""] else "N/A"

                cname_val = t.get("Campaign Name")
                cname_str = str(cname_val).strip() if pd.notna(cname_val) and str(cname_val).strip() else "General Appeal"

                code_val = t.get("Code")
                code_str = str(code_val).strip() if pd.notna(code_val) and str(code_val).strip() else "ALL"

                plat_val = t.get("Platform")
                plat_str = str(plat_val).strip() if pd.notna(plat_val) and str(plat_val).strip() else "LaunchGood"

                amt_num = float(t.get("net_num") or 0.0)
                dt_val = str(t.get("_calc_date") or t.get("_parsed_date") or t.get("Created Date (UTC)") or "N/A").strip()

                recent_transactions.append({
                    "date": dt_val if dt_val and dt_val.lower() not in ["nan", "none", "nat"] else "N/A",
                    "donor_name": name,
                    "email": email_str,
                    "campaign_name": cname_str,
                    "code": code_str,
                    "amount": round(amt_num, 2),
                    "platform": plat_str,
                    "donation_id": clean_val(t.get("Donation ID")),
                    "donor_id": clean_val(t.get("Donor ID")),
                    "heading": clean_val(t.get("Heading")),
                    "sub_heading": clean_val(t.get("Sub-Heading")),
                    "giving_level": clean_val(t.get("Giving Level Title")),
                    "gift_aid": clean_val(t.get("Gift Aid (yes or no)")),
                    "status": clean_val(t.get("Status")),
                    "platform_fundraiser": clean_val(t.get("fundraiser_name")),
                    "tracked_page": clean_val(t.get("_page")),
                    "donated": clean_val(t.get("Donation Amount (in Donation Currency)")),
                    "donation_currency": clean_val(t.get("Donation Currency (DC)")),
                    "net_received": round(float(t["_net_received"]), 2) if pd.notna(t.get("_net_received")) else None,
                })

            valid_dates_all = sub_df["_calc_date"][(sub_df["_calc_date"] != "") & (~sub_df["_calc_date"].str.lower().isin(["nan", "none", "nat"]))]
            first_gift_all_time = str(valid_dates_all.min()) if not valid_dates_all.empty else "N/A"
            latest_gift_all_time = str(valid_dates_all.max()) if not valid_dates_all.empty else "N/A"

            valid_dates_period = period_sub["_calc_date"][(period_sub["_calc_date"] != "") & (~period_sub["_calc_date"].str.lower().isin(["nan", "none", "nat"]))] if not period_sub.empty else pd.Series(dtype=object)
            first_gift_period = str(valid_dates_period.min()) if not valid_dates_period.empty else "N/A"
            latest_gift_period = str(valid_dates_period.max()) if not valid_dates_period.empty else "N/A"

            first_donation_date = first_gift_period if is_filtered else first_gift_all_time
            latest_donation_date = latest_gift_period if is_filtered else latest_gift_all_time

    fundraiser["first_donation_date"] = first_donation_date or "N/A"
    fundraiser["latest_donation_date"] = latest_donation_date or "N/A"
    fundraiser["first_donation_date_all_time"] = first_gift_all_time or "N/A"
    fundraiser["latest_donation_date_all_time"] = latest_gift_all_time or "N/A"
    fundraiser["first_donation_date_period"] = first_gift_period or "N/A"
    fundraiser["latest_donation_date_period"] = latest_gift_period or "N/A"
    fundraiser["is_custom_filtered"] = is_filtered
    fundraiser["filter_start_date"] = start_date or ""
    fundraiser["filter_end_date"] = end_date or ""
    fundraiser["inception_date"] = first_gift_all_time or fundraiser.get("start_date") or "N/A"
    fundraiser["total_raised_all_time"] = round(total_raised_all_time, 2)
    fundraiser["net_received_all_time"] = round(net_received_all_time, 2)  # after platform fees, in settlement currency
    fundraiser["amount_basis"] = "As shown on the platform (gross); net received after fees shown separately"
    fundraiser["total_raised_period"] = round(total_raised_period, 2)

    timeline_sorted = [{"month": k, "amount": round(v, 2)} for k, v in sorted(monthly_timeline.items())]

    return {
        "fundraiser": fundraiser,
        "assigned_campaigns": assigned_campaigns,
        "campaign_breakdown": sorted(campaign_breakdown, key=lambda x: x["gross_raised"], reverse=True),
        "monthly_timeline": timeline_sorted,
        "recent_transactions": recent_transactions,
        "transactions_total": transactions_total,
        "transactions_all": transactions_all,
        "tx_page": tx_page,
        "tx_page_size": tx_page_size,
        "tx_pages": max(1, -(-transactions_total // tx_page_size)),
        "tracked_pages": tracked_pages,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_fundraiser(payload: CreateFundraiserRequest):
    """Creates a new fundraiser, assigns campaigns, and updates donor records permanently (Super Admin only)."""
    _check_super_admin(payload.user_role, payload.can_edit_donors or False)
    comp = (payload.company_id or "rethink").strip().lower()
    if comp == "all":
        raise HTTPException(
            status_code=400,
            detail="Cannot create fundraisers in 'All Companies (Consolidated)' mode. Please select a specific company."
        )

    f_name = payload.name.strip()
    if not f_name:
        raise HTTPException(status_code=400, detail="Fundraiser name is required.")

    fundraiser_id = f"FR-{uuid.uuid4().hex[:8].upper()}"
    init_fundraiser_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO fundraisers (id, name, company_id, email, phone, target_goal, start_date, status, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (
            fundraiser_id,
            f_name,
            comp,
            payload.email.strip() if payload.email else "",
            payload.phone.strip() if payload.phone else "",
            float(payload.target_goal or 0.0),
            payload.start_date.strip() if payload.start_date else "",
            _clean_status(payload.status),
            payload.notes.strip() if payload.notes else ""
        ))

        cur.execute("UPDATE fundraisers SET page_group = ? WHERE id = ?",
                    ((payload.page_group or "").strip().upper() if (payload.page_group or "").strip().upper() in ("SP", "MAIN") else "",
                     fundraiser_id))
        # Insert campaign assignments and update donor records permanently for this company
        for cname, code, plat, m_type, m_value, m_key in _prepare_assignments(payload.assigned_campaigns, comp, fundraiser_id, cur):
            cur.execute("""
                INSERT INTO fundraiser_campaigns (id, fundraiser_id, campaign_name, code, platform, company_id, created_at,
                                                  match_type, match_value, match_key)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
            """, (str(uuid.uuid4()), fundraiser_id, cname, code, plat, comp, m_type, m_value, m_key))
            if m_type != "campaign_name":
                continue  # page links are attributed live when read; no donation rows are rewritten
            if code.upper() in ["ALL", "UNASSIGNED", ""] or not code:
                cur.execute("""
                    UPDATE donations 
                    SET fundraiser_name = ? 
                    WHERE [Campaign Name] = ? 
                      AND (fundraiser_name IS NULL OR TRIM(fundraiser_name) = '')
                      AND company_id = ?
                """, (f_name, cname, comp))
            else:
                cur.execute("""
                    UPDATE donations 
                    SET fundraiser_name = ? 
                    WHERE [Campaign Name] = ? AND Code = ?
                      AND (fundraiser_name IS NULL OR TRIM(fundraiser_name) = '')
                      AND company_id = ?
                """, (f_name, cname, code, comp))

        conn.commit()
    finally:
        conn.close()

    _sync_parquet_and_cache_from_sqlite()

    try:
        broadcast_event_sync("DONORS_UPDATED", {"source": "fundraiser_create", "fundraiser_name": f_name, "company_id": comp})
        broadcast_event_sync("FUNDRAISER_UPDATED", {"action": "create", "id": fundraiser_id, "name": f_name, "company_id": comp})
    except Exception:
        pass

    return {
        "status": "success",
        "message": f"Successfully created fundraiser '{f_name}' for {comp.upper()}.",
        "fundraiser_id": fundraiser_id,
        "company_id": comp
    }


@router.put("/{fundraiser_id}")
def update_fundraiser(fundraiser_id: str, payload: UpdateFundraiserRequest):
    """Updates an existing fundraiser, synchronizes donor records, and re-assigns campaigns (Super Admin only)."""
    _check_super_admin(payload.user_role, payload.can_edit_donors or False)
    comp = (payload.company_id or "rethink").strip().lower()
    if comp == "all":
        raise HTTPException(
            status_code=400,
            detail="Cannot update fundraisers in 'All Companies' mode. Please select a specific company."
        )

    new_name = payload.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Fundraiser name is required.")

    init_fundraiser_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    cur = conn.cursor()

    try:
        cur.execute("SELECT name FROM fundraisers WHERE id = ?", (fundraiser_id,))
        row = cur.fetchone()
        
        old_name = None
        if row:
            old_name = row[0]
        else:
            cur.execute("SELECT id, name FROM fundraisers WHERE LOWER(TRIM(name)) = LOWER(TRIM(?)) AND company_id = ?", (new_name, comp))
            row_by_name = cur.fetchone()
            if row_by_name:
                fundraiser_id = row_by_name[0]
                old_name = row_by_name[1]
            else:
                cur.execute("SELECT DISTINCT fundraiser_name FROM donations WHERE fundraiser_name IS NOT NULL AND TRIM(fundraiser_name) != '' AND company_id = ?", (comp,))
                don_names = [r[0] for r in cur.fetchall() if r[0]]
                for d_name in don_names:
                    synth_id = f"fund_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{comp}_{d_name.strip().lower()}').hex[:16]}"
                    if synth_id == fundraiser_id or d_name.strip().lower() == fundraiser_id.lower() or d_name.strip().lower() == new_name.lower():
                        old_name = d_name.strip()
                        break

                if not old_name:
                    old_name = new_name

                cur.execute("""
                    INSERT INTO fundraisers (id, name, company_id, email, phone, target_goal, start_date, status, notes, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (
                    fundraiser_id,
                    new_name,
                    comp,
                    payload.email.strip() if payload.email else "",
                    payload.phone.strip() if payload.phone else "",
                    float(payload.target_goal or 0.0),
                    payload.start_date.strip() if payload.start_date else "",
                    _clean_status(payload.status),
                    payload.notes.strip() if payload.notes else ""
                ))

        # Get existing assigned campaigns for diffing
        cur.execute("""SELECT campaign_name, code FROM fundraiser_campaigns WHERE fundraiser_id = ?
                       AND COALESCE(NULLIF(match_type, ''), 'campaign_name') = 'campaign_name'""", (fundraiser_id,))
        old_campaigns = set((r[0].strip().lower(), (r[1] or "ALL").strip().lower()) for r in cur.fetchall())

        # Validates links (and that no other fundraiser already owns them) before anything is changed
        prepared = _prepare_assignments(payload.assigned_campaigns, comp, fundraiser_id, cur)
        new_campaigns_set = set()
        new_campaigns_list = []
        for cn, cd, pl, m_type, _m_value, _m_key in prepared:
            if m_type == "campaign_name":
                new_campaigns_set.add((cn.lower(), cd.lower()))
                new_campaigns_list.append((cn, cd, pl))

        # 1. If name changed, update all existing donations that had the old fundraiser name for this company
        if old_name.strip().lower() != new_name.lower():
            cur.execute("""
                UPDATE donations 
                SET fundraiser_name = ? 
                WHERE LOWER(TRIM(fundraiser_name)) = LOWER(TRIM(?)) AND company_id = ?
            """, (new_name, old_name, comp))

        # 2. Handle unlinked campaigns
        unlinked = old_campaigns - new_campaigns_set
        for u_cname_lower, u_code_lower in unlinked:
            if u_code_lower in ["all", "unassigned", ""]:
                cur.execute("""
                    UPDATE donations
                    SET fundraiser_name = NULL
                    WHERE LOWER(TRIM([Campaign Name])) = ?
                      AND (LOWER(TRIM(fundraiser_name)) = LOWER(TRIM(?)) OR LOWER(TRIM(fundraiser_name)) = LOWER(TRIM(?)))
                      AND company_id = ?
                """, (u_cname_lower, old_name, new_name, comp))
            else:
                cur.execute("""
                    UPDATE donations
                    SET fundraiser_name = NULL
                    WHERE LOWER(TRIM([Campaign Name])) = ? AND LOWER(TRIM(Code)) = ?
                      AND (LOWER(TRIM(fundraiser_name)) = LOWER(TRIM(?)) OR LOWER(TRIM(fundraiser_name)) = LOWER(TRIM(?)))
                      AND company_id = ?
                """, (u_cname_lower, u_code_lower, old_name, new_name, comp))

        # 3. Handle newly assigned campaigns
        for cn, cd, pl in new_campaigns_list:
            if cd.upper() in ["ALL", "UNASSIGNED", ""] or not cd:
                cur.execute("""
                    UPDATE donations
                    SET fundraiser_name = ?
                    WHERE [Campaign Name] = ?
                      AND (fundraiser_name IS NULL OR TRIM(fundraiser_name) = '' OR LOWER(TRIM(fundraiser_name)) = LOWER(TRIM(?)))
                      AND company_id = ?
                """, (new_name, cn, old_name, comp))
            else:
                cur.execute("""
                    UPDATE donations
                    SET fundraiser_name = ?
                    WHERE [Campaign Name] = ? AND Code = ?
                      AND (fundraiser_name IS NULL OR TRIM(fundraiser_name) = '' OR LOWER(TRIM(fundraiser_name)) = LOWER(TRIM(?)))
                      AND company_id = ?
                """, (new_name, cn, cd, old_name, comp))

        # Update fundraisers table
        cur.execute("""
            UPDATE fundraisers 
            SET name = ?, email = ?, phone = ?, target_goal = ?, start_date = ?, status = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            new_name,
            payload.email.strip() if payload.email else "",
            payload.phone.strip() if payload.phone else "",
            float(payload.target_goal or 0.0),
            payload.start_date.strip() if payload.start_date else "",
            _clean_status(payload.status),
            payload.notes.strip() if payload.notes else "",
            fundraiser_id
        ))

        cur.execute("UPDATE fundraisers SET page_group = ? WHERE id = ?",
                    ((payload.page_group or "").strip().upper() if (payload.page_group or "").strip().upper() in ("SP", "MAIN") else "",
                     fundraiser_id))
        # Re-assign campaigns in fundraiser_campaigns
        cur.execute("DELETE FROM fundraiser_campaigns WHERE fundraiser_id = ?", (fundraiser_id,))
        for cn, cd, pl, m_type, m_value, m_key in prepared:
            cur.execute("""
                INSERT INTO fundraiser_campaigns (id, fundraiser_id, campaign_name, code, platform, company_id, created_at,
                                                  match_type, match_value, match_key)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
            """, (str(uuid.uuid4()), fundraiser_id, cn, cd, pl, comp, m_type, m_value, m_key))

        conn.commit()
    finally:
        conn.close()

    _sync_parquet_and_cache_from_sqlite()

    try:
        broadcast_event_sync("DONORS_UPDATED", {"source": "fundraiser_update", "fundraiser_name": new_name, "company_id": comp})
        broadcast_event_sync("FUNDRAISER_UPDATED", {"action": "update", "id": fundraiser_id, "name": new_name, "company_id": comp})
    except Exception:
        pass

    return {
        "status": "success",
        "message": f"Successfully updated fundraiser '{new_name}' in {comp.upper()} and synchronized donor records."
    }


@router.post("/assign-donations")
def assign_unassigned_donations(payload: AssignDonationsRequest):
    """
    Allows Super Admins to manually assign unassigned donations (by campaign, code, or donor emails)
    to a specific fundraiser, writing the fundraiser_name to the SQLite database and parquet cache.
    """
    _check_super_admin(payload.user_role, payload.can_edit_donors or False)
    comp = (payload.company_id or "rethink").strip().lower()
    if comp == "all":
        raise HTTPException(
            status_code=400,
            detail="Cannot assign donations in 'All Companies' mode. Please select a specific company."
        )
    
    target_fname = payload.fundraiser_name.strip()
    if not target_fname:
        raise HTTPException(status_code=400, detail="Target fundraiser name is required.")

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    cur = conn.cursor()
    updated_rows = 0

    try:
        if payload.donor_emails:
            emails_clean = [e.strip().lower() for e in payload.donor_emails if e.strip()]
            placeholders = ",".join("?" for _ in emails_clean)
            cur.execute(f"""
                UPDATE donations 
                SET fundraiser_name = ? 
                WHERE LOWER(TRIM(Email)) IN ({placeholders})
                  AND (fundraiser_name IS NULL OR TRIM(fundraiser_name) = '')
                  AND company_id = ?
            """, [target_fname] + emails_clean + [comp])
            updated_rows = cur.rowcount
        elif payload.campaign_name:
            cname = payload.campaign_name.strip()
            code = (payload.code or "ALL").strip()
            if code.upper() in ["ALL", "UNASSIGNED", ""] or not code:
                cur.execute("""
                    UPDATE donations 
                    SET fundraiser_name = ? 
                    WHERE [Campaign Name] = ? 
                      AND (fundraiser_name IS NULL OR TRIM(fundraiser_name) = '')
                      AND company_id = ?
                """, (target_fname, cname, comp))
            else:
                cur.execute("""
                    UPDATE donations 
                    SET fundraiser_name = ? 
                    WHERE [Campaign Name] = ? AND Code = ?
                      AND (fundraiser_name IS NULL OR TRIM(fundraiser_name) = '')
                      AND company_id = ?
                """, (target_fname, cname, code, comp))
            updated_rows = cur.rowcount

        conn.commit()
    finally:
        conn.close()

    if updated_rows > 0:
        _sync_parquet_and_cache_from_sqlite()
        try:
            broadcast_event_sync("DONORS_UPDATED", {"source": "assign_donations", "fundraiser_name": target_fname, "company_id": comp})
            broadcast_event_sync("FUNDRAISER_UPDATED", {"action": "assign_donations", "fundraiser_name": target_fname, "company_id": comp})
        except Exception:
            pass

    return {
        "status": "success",
        "updated_donations_count": updated_rows,
        "message": f"Successfully assigned {updated_rows} donations to fundraiser '{target_fname}' in {comp.upper()}."
    }


@router.delete("/{fundraiser_id}")
def delete_fundraiser(
    fundraiser_id: str, 
    user_role: str = "guest", 
    can_edit_donors: bool = False,
    company_id: Optional[str] = Query("rethink")
):
    """Deletes a fundraiser, unlinks its campaigns, and clears fundraiser_name on its donations (Super Admin only)."""
    _check_super_admin(user_role, can_edit_donors)
    comp = (company_id or "rethink").strip().lower()

    init_fundraiser_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    cur = conn.cursor()

    try:
        cur.execute("SELECT name FROM fundraisers WHERE id = ?", (fundraiser_id,))
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT DISTINCT fundraiser_name FROM donations WHERE fundraiser_name IS NOT NULL AND TRIM(fundraiser_name) != '' AND company_id = ?", (comp,))
            don_names = [r[0] for r in cur.fetchall() if r[0]]
            matched = None
            for d_name in don_names:
                synth_id = f"fund_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{comp}_{d_name.strip().lower()}').hex[:16]}"
                if synth_id == fundraiser_id or d_name.strip().lower() == fundraiser_id.lower():
                    matched = d_name.strip()
                    break
            if not matched:
                raise HTTPException(status_code=404, detail="Fundraiser not found.")
            f_name = matched
        else:
            f_name = row[0]

        cur.execute("DELETE FROM fundraiser_campaigns WHERE fundraiser_id = ?", (fundraiser_id,))
        cur.execute("DELETE FROM fundraisers WHERE id = ?", (fundraiser_id,))

        # Clear fundraiser_name in donations table for this company so it's permanently unassigned
        cur.execute("""
            UPDATE donations 
            SET fundraiser_name = NULL 
            WHERE LOWER(TRIM(fundraiser_name)) = LOWER(TRIM(?)) AND company_id = ?
        """, (f_name, comp))

        conn.commit()
    finally:
        conn.close()

    _sync_parquet_and_cache_from_sqlite()

    try:
        broadcast_event_sync("DONORS_UPDATED", {"source": "fundraiser_delete", "fundraiser_name": f_name, "company_id": comp})
        broadcast_event_sync("FUNDRAISER_UPDATED", {"action": "delete", "id": fundraiser_id, "name": f_name, "company_id": comp})
    except Exception:
        pass

    return {
        "status": "success",
        "message": f"Successfully deleted fundraiser '{f_name}' in {comp.upper()} and cleared donor assignments."
    }


class AddLinkRequest(BaseModel):
    company_id: str
    match_type: str = "fundraiser_url"   # fundraiser_url / campaign_url / community_url / campaign_name
    value: str


def _require_link_editor(request: Request) -> Dict[str, Any]:
    user = getattr(request.state, "api_user", None) or {}
    if not (user.get("role") == "super_admin" or user.get("can_edit_donors")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your account can't change fundraiser pages.")
    return user


@router.post("/{fundraiser_id}/links")
def add_fundraiser_link(fundraiser_id: str, payload: AddLinkRequest, request: Request):
    """Tracks one more page (link or campaign name) for a fundraiser. A brand-new page with no donations yet is fine:
    its donations are credited to this fundraiser the moment they arrive."""
    _require_link_editor(request)
    comp = str(payload.company_id or "").strip().lower()
    if not comp or comp == "all":
        raise HTTPException(status_code=400, detail="Choose a charity.")
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    try:
        cur = conn.cursor()
        if not cur.execute("SELECT 1 FROM fundraisers WHERE id = ? AND LOWER(company_id) = ?", (fundraiser_id, comp)).fetchone():
            raise HTTPException(status_code=404, detail="Fundraiser not found for this charity.")
        item = CampaignAssignment(campaign_name=payload.value, match_type=payload.match_type, match_value=payload.value)
        rows = _prepare_assignments([item], comp, fundraiser_id, cur)
        if not rows:
            raise HTTPException(status_code=400, detail="Enter a page link or campaign name.")
        cname, code, plat, m_type, m_value, m_key = rows[0]
        if m_key and cur.execute("SELECT 1 FROM fundraiser_campaigns WHERE fundraiser_id = ? AND match_key = ?", (fundraiser_id, m_key)).fetchone():
            return {"success": True, "already_tracked": True}
        link_id = str(uuid.uuid4())
        with conn:
            cur.execute("""INSERT INTO fundraiser_campaigns (id, fundraiser_id, campaign_name, code, platform, company_id, created_at,
                                                         match_type, match_value, match_key)
                           VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)""",
                        (link_id, fundraiser_id, cname, code, plat, comp, m_type, m_value, m_key))
            cur.execute("UPDATE fundraisers SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (fundraiser_id,))
    finally:
        conn.close()
    try:
        from backend.api.events import broadcast_event_sync
        broadcast_event_sync("FUNDRAISER_UPDATED", {"action": "link_added", "company_id": comp, "fundraiser_id": fundraiser_id})
    except Exception:
        pass
    return {"success": True, "link_id": link_id, "match_type": m_type, "platform": plat}


@router.delete("/{fundraiser_id}/links/{link_id}")
def remove_fundraiser_link(fundraiser_id: str, link_id: str, request: Request, company_id: str = Query(...)):
    _require_link_editor(request)
    comp = str(company_id or "").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    try:
        with conn:
            n = conn.execute("DELETE FROM fundraiser_campaigns WHERE id = ? AND fundraiser_id = ? AND LOWER(company_id) = ?",
                             (link_id, fundraiser_id, comp)).rowcount
    finally:
        conn.close()
    if not n:
        raise HTTPException(status_code=404, detail="Page not found for this fundraiser.")
    return {"success": True}
