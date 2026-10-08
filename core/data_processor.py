import os
import sqlite3
import threading
import re
from typing import Optional

import numpy as np
import pandas as pd

from config.settings import LOCAL_DB_PATH, PARQUET_PATH, PAYOUTS_PARQUET_PATH, PAYSUITE_PAYOUTS_PARQUET_PATH
from core.database import sync_to_cloud_async, get_db_connection, _DB_LOCK

COUNTRY_ISO_MAP = {
    "GB": "United Kingdom", "UK": "United Kingdom", "GBR": "United Kingdom",
    "US": "United States", "USA": "United States",
    "CA": "Canada", "CAN": "Canada",
    "AU": "Australia", "AUS": "Australia",
    "AE": "United Arab Emirates", "ARE": "United Arab Emirates", "UAE": "United Arab Emirates",
    "SA": "Saudi Arabia", "SAU": "Saudi Arabia",
    "PK": "Pakistan", "PAK": "Pakistan",
    "IN": "India", "IND": "India",
    "MY": "Malaysia", "MYS": "Malaysia",
    "SG": "Singapore", "SGP": "Singapore",
    "NZ": "New Zealand", "NZL": "New Zealand", "DE": "Germany", "DEU": "Germany",
    "FR": "France", "FRA": "France", "NL": "Netherlands", "NLD": "Netherlands",
    "TR": "Turkey", "TUR": "Turkey", "ZA": "South Africa", "ZAF": "South Africa",
    "IE": "Ireland", "IRL": "Ireland", "QA": "Qatar", "QAT": "Qatar",
    "KW": "Kuwait", "KWT": "Kuwait", "BH": "Bahrain", "BHR": "Bahrain",
    "OM": "Oman", "OMN": "Oman", "JO": "Jordan", "JOR": "Jordan",
    "EG": "Egypt", "EGY": "Egypt", "BD": "Bangladesh", "BGD": "Bangladesh"
}

# Global In-Memory Dataset Cache Singleton
_CACHED_DF: Optional[pd.DataFrame] = None
_CACHE_MTIME: float = 0.0
_CACHE_LOCK = threading.Lock()



MOJIBAKE_MAP = {
    # 4-byte Emojis misdecoded as Windows-1252 / latin-1
    "ðŸŽŸ": "🎟",
    "ðŸ †": "🏆",
    "ð\x9f\x8f†": "🏆",
    "ðŸ\x8f†": "🏆",
    "ðŸŒ": "🍬",
    "ðŸŒ™": "🌙",
    "ðŸ\"¥": "🔥",
    "ðŸ’–": "💖",
    "ðŸ™": "🙏",
    "ðŸ•": "🕌",
    "ðŸ“": "📖",
    "ðŸ’": "💧",
    "ðŸ’ª": "💪",
    "ðŸŒŽ": "🌍",
    "ðŸ‡µðŸ‡¸": "🇵🇸",
    "ðŸ‡¸ðŸ‡¾": "🇸🇾",
    "ðŸ‡¦ðŸ‡«": "🇦🇫",
    "â\x9d¤ï¸\x8f": "❤️",
    "â\x9d¤": "❤️",
    "âœ¨": "✨",
    "â­\x90": "⭐",
    "âف": "✨",
    
    # 2 & 3-byte UTF-8 symbols misdecoded
    "â€“": "–",
    "â€”": "–",
    "â€™": "'",
    "â€˜": "'",
    "â€œ": '"',
    "â€\x9d": '"',
    "â€": '"',
    "Â": "",
    "\xa0": " ",
    "\xad": "",
    "\u200b": "",
    "\u200c": "",
    "\u200d": "",
    "\ufeff": "",
    "\ufffd": "",
    
    # Arabic / Transliteration artifacts
    "Qur’Äفn": "Qur'ān",
    "Qur'Äفn": "Qur'ān",
    "QurÄفn": "Qur'ān",
    "Qur'Äفn": "Qur'ān",
    "Qur’Äفn": "Qur'ān",
    "Qur'an": "Qur'ān",
    "Qur’an": "Qur'ān",
    "AshbÄ\xad": "Ashbāl",
    "AshbÄفl": "Ashbāl",
    "Ashbāفl": "Ashbāl",
    "AshbÄفl": "Ashbāl",
    "AshbÄ l": "Ashbāl",
    "AshbÄ": "Ashbāl",
    "AnsÄفrÄ«yyah": "Ansārīyyah",
    "AnsÄفr": "Ansār",
    "Ansāفr": "Ansār",
    "DÄفrul": "Dārul",
    "ImÄفn": "Imān",
    "KunÄفr": "Kunar",
    "KunÄفr": "Kunar",
    "AbÅ«": "Abū",
    "WudÅ«": "Wudū",
    
    # Quotes & Dashes
    "’": "'",
    "‘": "'",
    "`": "'",
    "''": '"',
    '""': "–",
    "“": '"',
    "”": '"',
    "—": "–",
    " - ": " – "
}

def fix_mojibake(text):
    """
    Fixes garbled text encodings (UTF-8 bytes mis-decoded as Windows-1252 / ISO-8859-1).
    Restores multi-lingual characters, Arabic, accents, emojis, and special symbols.
    """
    if not text or not isinstance(text, str):
        return "" if text is None else str(text)
    s = str(text).strip()
    
    for k, v in MOJIBAKE_MAP.items():
        if k in s:
            s = s.replace(k, v)
            
    # Strip variation selectors & zero-width chars
    s = s.replace("\ufe0f", "").replace("Â", "").replace("\xad", "").replace("\xa0", " ")
    import re
    s = re.sub(r'\s+', ' ', s).strip()
    return s


ALL_SHEET10_SPECIAL_CASES = [
    'Zarang bike',
    'Umm Abdullah',
    'Umm Alaa',
    'Umm Habib',
    'Umm Suleiman',
    'Umm Hamza',
    'Aunt Sahr',
    'Umm Lofti',
    'Umm Muhammad',
    'Umm Saeed',
    'Eid Clothes',
    'Eid Party',
    'LUFS',
    'Most Needy',
    'Qurbani',
    'Tent2Home',
    'Special Case'
]


def canonicalize_special_case(sc_str) -> str:
    if not sc_str:
        return ""
    trimmed = str(sc_str).strip()
    if trimmed.lower() in ["unassigned", "none", "none (standard)", "nan", "null", "n/a", ""]:
        return ""
    for known in ALL_SHEET10_SPECIAL_CASES:
        if known.lower() == trimmed.lower():
            return known
    return trimmed


def canonical_campaign_key(text: Any) -> str:
    """
    Produces a normalized canonical key for campaign name matching:
    - Repairs mojibake
    - Strips accents/diacritics (macrons like ā -> a, é -> e) via NFKD decomposition
    - Strips community/platform suffixes (| ..., - ..., – ..., — ...)
    - Strips all punctuation (!, ?, quotes, periods, commas, colons, brackets, hyphens)
    - Collapses multiple whitespace
    """
    if not text:
        return ""
    import unicodedata
    import re
    s = fix_mojibake(str(text)).strip().lower()
    s = unicodedata.normalize('NFKD', s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    for sep in ["|", " - ", " – ", " — "]:
        if sep in s:
            s = s.split(sep)[0].strip()
    s = s.replace("’", "").replace("‘", "").replace("'", "").replace('"', "")
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def deduplicate_dataframe_columns(df_input):
    """
    Finds and merges duplicate columns case-insensitively.
    """
    if df_input is None or df_input.empty:
        return df_input
    
    # Handle duplicate column names positional-indexed
    res_df = pd.DataFrame(index=df_input.index)
    col_dict = {}
    
    for i, col in enumerate(df_input.columns):
        series = df_input.iloc[:, i]
        norm = str(col).strip()
        norm_key = norm.lower()
        if norm_key not in col_dict:
            col_dict[norm_key] = (norm, series)
        else:
            orig_name, existing_series = col_dict[norm_key]
            col_dict[norm_key] = (orig_name, existing_series.fillna(series))

    for norm_key, (orig_name, s) in col_dict.items():
        res_df[orig_name] = s

    return res_df

# Global In-Memory Code Map Cache per Company
_CACHED_CODE_MAP = {}


def invalidate_code_map(company_id: Optional[str] = None):
    """Invalidates the in-memory code classification map cache for a company or all companies."""
    global _CACHED_CODE_MAP
    if company_id:
        _CACHED_CODE_MAP.pop(str(company_id).lower().strip(), None)
    else:
        _CACHED_CODE_MAP = {}


def get_code_to_classification_map(force_reload: bool = False, company_id: Optional[str] = "rethink"):
    """
    Queries all known classifications from master_project_codes (Two-Tier Model)
    to build a dynamic dictionary mapping a Code (case-insensitive) to its corresponding
    Department, Office, Portfolio, Country, and Zakat Eligibility in < 1ms via in-memory caching.
    Provides backward-compatible aliases for 'Heading' and 'Sub-Heading'.
    Strictly partitioned by company_id.
    """
    global _CACHED_CODE_MAP
    if _CACHED_CODE_MAP is None or not isinstance(_CACHED_CODE_MAP, dict):
        _CACHED_CODE_MAP = {}

    comp = str(company_id or "rethink").lower().strip()
    if not force_reload and comp in _CACHED_CODE_MAP:
        return _CACHED_CODE_MAP[comp]

    code_map = {}
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_project_codes'")
        if cur.fetchone():
            mpc_cols = [r[1] for r in cur.execute("PRAGMA table_info(master_project_codes)").fetchall()]
            select_cols = ["code", "department", "office", "portfolio", "country", "zakat_eligibility"]
            if "programme_fund" in mpc_cols:
                select_cols.extend(["programme_fund", "fund_code", "legacy_non_zakat_code", "legacy_zakat_code", "old_codes"])
            if "special_treatment" in mpc_cols:
                select_cols.append("special_treatment")

            where_clause = ""
            params = []
            if comp != "all" and "company_id" in mpc_cols:
                where_clause = " WHERE LOWER(COALESCE(company_id, 'rethink')) = ?"
                params = [comp]

            df = pd.read_sql_query(f"SELECT {', '.join(select_cols)} FROM master_project_codes{where_clause}", conn, params=params)
            for _, row in df.iterrows():
                code = str(row.get("code") or "").strip()
                if not code or code.lower() in ["unassigned", "nan", "none", ""]:
                    continue
                code_lower = code.lower()
                dept = str(row.get("department") or "Unassigned").strip()
                off = str(row.get("office") or "Unassigned").strip()
                port = str(row.get("portfolio") or "").strip()
                cntry = str(row.get("country") or "Unassigned").strip()
                zkt = str(row.get("zakat_eligibility") or "Unassigned").strip()
                prog_fund = str(row.get("programme_fund") or "").strip()
                fund_code = str(row.get("fund_code") or "").strip()
                non_zakat_gl = str(row.get("legacy_non_zakat_code") or "").strip()
                zakat_gl = str(row.get("legacy_zakat_code") or "").strip()
                old_raw = str(row.get("old_codes") or "").strip()
                spec_treat_raw = str(row.get("special_treatment") or "").strip() if "special_treatment" in mpc_cols else ""
                spec_cases = [s.strip() for s in spec_treat_raw.replace(",", ";").split(";") if s.strip()]

                entry = {
                    "Code": code,
                    "Department": dept if dept.lower() not in ["unassigned", ""] else "Unassigned",
                    "Office": off if off.lower() not in ["unassigned", ""] else "Unassigned",
                    "Portfolio": port,
                    "Programme Fund": prog_fund,
                    "Fund Code": fund_code,
                    "Legacy Non-Zakat Code": non_zakat_gl,
                    "Legacy Zakat Code": zakat_gl,
                    "Old Code": old_raw,
                    "Special Treatment": spec_treat_raw,
                    "Special Case": canonicalize_special_case(spec_cases[0] if spec_cases else spec_treat_raw),
                    "Special Cases": [canonicalize_special_case(s) for s in spec_cases if s],
                    # Backward-compatible aliases
                    "Heading": dept if dept.lower() not in ["unassigned", ""] else "Unassigned",
                    "Sub-Heading": off if off.lower() not in ["unassigned", ""] else "Unassigned",
                    "Country": cntry if cntry.lower() not in ["unassigned", ""] else "Unassigned",
                    "Zakat Eligibility": zkt if zkt.lower() not in ["unassigned", ""] else "Unassigned"
                }

                code_map[code_lower] = entry

                # Register smart variants for special cases: code [special case]
                for sc in spec_cases:
                    variant_key = f"{code_lower} [{sc.lower()}]"
                    variant_entry = dict(entry)
                    variant_entry["Special Case"] = sc
                    variant_entry["Display Code"] = f"{code} [{sc}]"
                    code_map[variant_key] = variant_entry

                # Also alias each legacy code from old_codes to point to this entry
                if old_raw:
                    for tok in [t.strip().lower() for t in old_raw.replace(",", ";").split(";") if t.strip()]:
                        if tok and tok not in code_map:
                            code_map[tok] = entry
        else:
            # Fallback for unmigrated environments
            tables = ["campaign_classifications", "givebright_classifications", "paysuite_classifications", "rethink_website_classifications", "madinah_classifications"]
            for tbl in tables:
                try:
                    df = pd.read_sql_query(f"SELECT code, heading, sub_heading, country, zakat_eligibility FROM {tbl}", conn)
                    for _, row in df.iterrows():
                        code = str(row.get("code") or "").strip()
                        code_lower = code.lower()
                        if not code or code_lower in ["unassigned", "nan", "none", ""]:
                            continue
                        heading = str(row.get("heading") or "Unassigned").strip()
                        sub_heading = str(row.get("sub_heading") or "Unassigned").strip()
                        country = str(row.get("country") or "Unassigned").strip()
                        zakat = str(row.get("zakat_eligibility") or "Unassigned").strip()
                        if code_lower not in code_map:
                            code_map[code_lower] = {
                                "Department": heading,
                                "Office": sub_heading,
                                "Portfolio": "",
                                "Heading": heading,
                                "Sub-Heading": sub_heading,
                                "Country": country,
                                "Zakat Eligibility": zakat
                            }
                except Exception:
                    pass
    except Exception as e:
        print(f"[Warning] Failed to generate code mapping: {e}")
    finally:
        conn.close()

    _CACHED_CODE_MAP[comp] = code_map
    return code_map


def classify_donor_amount(amount):
    """Classify donor based on donation amount."""
    if pd.isna(amount) or amount is None:
        return "Low End"
    try:
        val = float(amount)
    except (ValueError, TypeError):
        return "Low End"

    if val < 200:
        return "Low End"
    elif val < 600:
        return "Medium Low"
    elif val < 1000:
        return "Medium"
    elif val <= 3000:
        return "High"
    else:
        return "Super High"

def _mode_or_last(series):
    clean = series.dropna().astype(str).str.strip()
    clean = clean[clean != ""]
    if clean.empty:
        return series.iloc[-1] if not series.empty else 'Unassigned'
    mode_vals = clean.mode()
    return mode_vals.iloc[0] if not mode_vals.empty else clean.iloc[-1]

def init_classification_db():
    """Ensures that database schema is up-to-date with two-tier architecture."""
    with _DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()

            # 1. Master project codes table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS master_project_codes (
                    code TEXT NOT NULL,
                    company_id TEXT NOT NULL DEFAULT 'rethink',
                    programme_fund TEXT DEFAULT '',
                    fund_code TEXT DEFAULT '',
                    department TEXT DEFAULT 'Unassigned',
                    office TEXT DEFAULT 'Unassigned',
                    portfolio TEXT DEFAULT '',
                    country TEXT DEFAULT 'Unassigned',
                    zakat_eligibility TEXT DEFAULT 'Zakat',
                    legacy_non_zakat_code TEXT DEFAULT '',
                    legacy_zakat_code TEXT DEFAULT '',
                    old_codes TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (company_id, code)
                );
            """)

            # Ensure company_id column exists
            cur.execute("PRAGMA table_info(master_project_codes)")
            cols = [r[1] for r in cur.fetchall()]
            if "company_id" not in cols:
                cur.execute("ALTER TABLE master_project_codes ADD COLUMN company_id TEXT NOT NULL DEFAULT 'rethink'")

            # 2. Platform campaign mappings table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS platform_campaign_mappings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    company_id TEXT NOT NULL DEFAULT 'rethink',
                    campaign_name TEXT NOT NULL,
                    giving_level TEXT NOT NULL DEFAULT '',
                    code TEXT,
                    community_name TEXT DEFAULT 'N/A',
                    campaign_url TEXT DEFAULT '',
                    is_primary INTEGER DEFAULT 0,
                    donor_name TEXT DEFAULT '',
                    donor_email TEXT DEFAULT '',
                    special_case TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (platform, company_id, campaign_name, giving_level, code)
                );
            """)

            cur.execute("PRAGMA table_info(platform_campaign_mappings)")
            map_cols = [r[1] for r in cur.fetchall()]
            if "company_id" not in map_cols:
                cur.execute("ALTER TABLE platform_campaign_mappings ADD COLUMN company_id TEXT NOT NULL DEFAULT 'rethink'")
            if "giving_level" not in map_cols:
                cur.execute("ALTER TABLE platform_campaign_mappings ADD COLUMN giving_level TEXT NOT NULL DEFAULT ''")
            if "special_case" not in map_cols:
                cur.execute("ALTER TABLE platform_campaign_mappings ADD COLUMN special_case TEXT DEFAULT ''")

            # Purge duplicate unassigned ghost rows when an assigned row exists for that same (platform, company_id, campaign_name, giving_level)
            try:
                cur.execute("""
                    DELETE FROM platform_campaign_mappings
                    WHERE LOWER(code) IN ('unassigned', '', 'none', 'nan')
                      AND EXISTS (
                          SELECT 1 FROM platform_campaign_mappings p2
                          WHERE p2.platform = platform_campaign_mappings.platform
                            AND LOWER(COALESCE(p2.company_id, 'rethink')) = LOWER(COALESCE(platform_campaign_mappings.company_id, 'rethink'))
                            AND LOWER(TRIM(p2.campaign_name)) = LOWER(TRIM(platform_campaign_mappings.campaign_name))
                            AND LOWER(TRIM(COALESCE(p2.giving_level, ''))) = LOWER(TRIM(COALESCE(platform_campaign_mappings.giving_level, '')))
                            AND LOWER(COALESCE(p2.code, 'unassigned')) NOT IN ('unassigned', '', 'none', 'nan')
                      );
                """)
                cur.execute("""
                    DELETE FROM platform_campaign_mappings
                    WHERE id NOT IN (
                        SELECT MAX(id)
                        FROM platform_campaign_mappings
                        GROUP BY LOWER(platform), LOWER(COALESCE(company_id, 'rethink')), LOWER(TRIM(campaign_name)), LOWER(TRIM(COALESCE(giving_level, ''))), UPPER(TRIM(COALESCE(code, 'Unassigned')))
                    );
                """)
                cur.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_pcm_p_c_c_g_c 
                    ON platform_campaign_mappings(platform, company_id, campaign_name, giving_level, code);
                """)
                cur.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_pcm_c_p_c_g_c 
                    ON platform_campaign_mappings(company_id, platform, campaign_name, giving_level, code);
                """)
            except Exception:
                pass

            # 3. Create views if they don't exist
            cur.execute("SELECT name, type FROM sqlite_master WHERE name IN ('campaign_classifications', 'givebright_classifications', 'paysuite_classifications', 'rethink_website_classifications', 'madinah_classifications')")
            existing_objects = {row[0]: row[1] for row in cur.fetchall()}

            for tbl in ["campaign_classifications", "givebright_classifications", "paysuite_classifications", "rethink_website_classifications", "madinah_classifications"]:
                if existing_objects.get(tbl) == "table":
                    try:
                        cur.execute(f"DROP TABLE IF EXISTS _legacy_{tbl}")
                        cur.execute(f"ALTER TABLE {tbl} RENAME TO _legacy_{tbl}")
                        existing_objects.pop(tbl, None)
                    except Exception:
                        pass

            # Always drop and recreate views to ensure giving_level column is present
            cur.execute("DROP VIEW IF EXISTS campaign_classifications")
            cur.execute("""
                CREATE VIEW campaign_classifications AS
                SELECT 
                    COALESCE(m.company_id, 'rethink') AS company_id,
                    m.campaign_name,
                    COALESCE(m.giving_level, '') AS giving_level,
                    m.code,
                    COALESCE(m.special_case, '') AS special_case,
                    COALESCE(c.special_treatment, '') AS special_treatment,
                    COALESCE(m.community_name, 'N/A') AS community_name,
                    COALESCE(m.campaign_url, '') AS campaign_url,
                    COALESCE(c.department, 'Unassigned') AS department,
                    COALESCE(c.office, 'Unassigned') AS office,
                    COALESCE(c.portfolio, '') AS portfolio,
                    COALESCE(c.programme_fund, '') AS programme_fund,
                    COALESCE(c.fund_code, '') AS fund_code,
                    COALESCE(c.legacy_non_zakat_code, '') AS legacy_non_zakat_code,
                    COALESCE(c.legacy_zakat_code, '') AS legacy_zakat_code,
                    COALESCE(c.department, 'Unassigned') AS heading,
                    COALESCE(c.office, 'Unassigned') AS sub_heading,
                    COALESCE(c.country, 'Unassigned') AS country,
                    COALESCE(c.zakat_eligibility, 'Unassigned') AS zakat_eligibility,
                    COALESCE(m.is_primary, 0) AS is_primary,
                    COALESCE(m.donor_name, '') AS donor_name,
                    COALESCE(m.donor_email, '') AS donor_email
                FROM platform_campaign_mappings m
                LEFT JOIN master_project_codes c 
                    ON UPPER(TRIM(m.code)) = UPPER(TRIM(c.code))
                   AND COALESCE(m.company_id, 'rethink') = COALESCE(c.company_id, 'rethink')
                WHERE m.platform = 'launchgood';
            """)

            cur.execute("DROP VIEW IF EXISTS givebright_classifications")
            cur.execute("""
                CREATE VIEW givebright_classifications AS
                SELECT 
                    COALESCE(m.company_id, 'rethink') AS company_id,
                    m.campaign_name,
                    COALESCE(m.giving_level, '') AS giving_level,
                    m.code,
                    COALESCE(m.special_case, '') AS special_case,
                    COALESCE(c.special_treatment, '') AS special_treatment,
                    COALESCE(m.community_name, 'N/A') AS community_name,
                    COALESCE(m.campaign_url, '') AS campaign_url,
                    COALESCE(c.department, 'Unassigned') AS department,
                    COALESCE(c.office, 'Unassigned') AS office,
                    COALESCE(c.portfolio, '') AS portfolio,
                    COALESCE(c.programme_fund, '') AS programme_fund,
                    COALESCE(c.fund_code, '') AS fund_code,
                    COALESCE(c.legacy_non_zakat_code, '') AS legacy_non_zakat_code,
                    COALESCE(c.legacy_zakat_code, '') AS legacy_zakat_code,
                    COALESCE(c.department, 'Unassigned') AS heading,
                    COALESCE(c.office, 'Unassigned') AS sub_heading,
                    COALESCE(c.country, 'Unassigned') AS country,
                    COALESCE(c.zakat_eligibility, 'Unassigned') AS zakat_eligibility,
                    COALESCE(m.is_primary, 0) AS is_primary,
                    COALESCE(m.donor_name, '') AS donor_name,
                    COALESCE(m.donor_email, '') AS donor_email
                FROM platform_campaign_mappings m
                LEFT JOIN master_project_codes c 
                    ON UPPER(TRIM(m.code)) = UPPER(TRIM(c.code))
                   AND COALESCE(m.company_id, 'rethink') = COALESCE(c.company_id, 'rethink')
                WHERE m.platform = 'givebright';
            """)

            cur.execute("DROP VIEW IF EXISTS paysuite_classifications")
            cur.execute("""
                CREATE VIEW paysuite_classifications AS
                SELECT 
                    COALESCE(m.company_id, 'rethink') AS company_id,
                    m.campaign_name,
                    COALESCE(m.giving_level, '') AS giving_level,
                    m.code,
                    COALESCE(m.special_case, '') AS special_case,
                    COALESCE(c.special_treatment, '') AS special_treatment,
                    COALESCE(m.community_name, 'N/A') AS community_name,
                    COALESCE(m.campaign_url, '') AS campaign_url,
                    COALESCE(c.department, 'Unassigned') AS department,
                    COALESCE(c.office, 'Unassigned') AS office,
                    COALESCE(c.portfolio, '') AS portfolio,
                    COALESCE(c.programme_fund, '') AS programme_fund,
                    COALESCE(c.fund_code, '') AS fund_code,
                    COALESCE(c.legacy_non_zakat_code, '') AS legacy_non_zakat_code,
                    COALESCE(c.legacy_zakat_code, '') AS legacy_zakat_code,
                    COALESCE(c.department, 'Unassigned') AS heading,
                    COALESCE(c.office, 'Unassigned') AS sub_heading,
                    COALESCE(c.country, 'Unassigned') AS country,
                    COALESCE(c.zakat_eligibility, 'Unassigned') AS zakat_eligibility,
                    COALESCE(m.donor_name, '') AS donor_name,
                    COALESCE(m.donor_email, '') AS donor_email,
                    COALESCE(m.is_primary, 0) AS is_primary
                FROM platform_campaign_mappings m
                LEFT JOIN master_project_codes c 
                    ON UPPER(TRIM(m.code)) = UPPER(TRIM(c.code))
                   AND COALESCE(m.company_id, 'rethink') = COALESCE(c.company_id, 'rethink')
                WHERE m.platform = 'paysuite';
            """)

            cur.execute("DROP VIEW IF EXISTS rethink_website_classifications")
            cur.execute("""
                CREATE VIEW rethink_website_classifications AS
                SELECT 
                    COALESCE(m.company_id, 'rethink') AS company_id,
                    m.campaign_name,
                    COALESCE(m.giving_level, '') AS giving_level,
                    m.code,
                    COALESCE(m.special_case, '') AS special_case,
                    COALESCE(c.special_treatment, '') AS special_treatment,
                    COALESCE(m.community_name, 'N/A') AS community_name,
                    COALESCE(c.department, 'Unassigned') AS department,
                    COALESCE(c.office, 'Unassigned') AS office,
                    COALESCE(c.portfolio, '') AS portfolio,
                    COALESCE(c.programme_fund, '') AS programme_fund,
                    COALESCE(c.fund_code, '') AS fund_code,
                    COALESCE(c.legacy_non_zakat_code, '') AS legacy_non_zakat_code,
                    COALESCE(c.legacy_zakat_code, '') AS legacy_zakat_code,
                    COALESCE(c.department, 'Unassigned') AS heading,
                    COALESCE(c.office, 'Unassigned') AS sub_heading,
                    COALESCE(c.country, 'Unassigned') AS country,
                    COALESCE(c.zakat_eligibility, 'Unassigned') AS zakat_eligibility,
                    COALESCE(m.is_primary, 0) AS is_primary,
                    COALESCE(m.donor_name, '') AS donor_name,
                    COALESCE(m.donor_email, '') AS donor_email
                FROM platform_campaign_mappings m
                LEFT JOIN master_project_codes c 
                    ON UPPER(TRIM(m.code)) = UPPER(TRIM(c.code))
                   AND COALESCE(m.company_id, 'rethink') = COALESCE(c.company_id, 'rethink')
                WHERE m.platform IN ('website', 'rethink_website');
            """)

            cur.execute("DROP VIEW IF EXISTS madinah_classifications")
            cur.execute("""
                CREATE VIEW madinah_classifications AS
                SELECT 
                    COALESCE(m.company_id, 'iqra') AS company_id,
                    m.campaign_name,
                    COALESCE(m.giving_level, '') AS giving_level,
                    m.code,
                    COALESCE(m.special_case, '') AS special_case,
                    COALESCE(c.special_treatment, '') AS special_treatment,
                    COALESCE(m.community_name, 'N/A') AS community_name,
                    COALESCE(m.campaign_url, '') AS campaign_url,
                    COALESCE(c.department, 'Unassigned') AS department,
                    COALESCE(c.office, 'Unassigned') AS office,
                    COALESCE(c.portfolio, '') AS portfolio,
                    COALESCE(c.programme_fund, '') AS programme_fund,
                    COALESCE(c.fund_code, '') AS fund_code,
                    COALESCE(c.legacy_non_zakat_code, '') AS legacy_non_zakat_code,
                    COALESCE(c.legacy_zakat_code, '') AS legacy_zakat_code,
                    COALESCE(c.department, 'Unassigned') AS heading,
                    COALESCE(c.office, 'Unassigned') AS sub_heading,
                    COALESCE(c.country, 'Unassigned') AS country,
                    COALESCE(c.zakat_eligibility, 'Unassigned') AS zakat_eligibility,
                    COALESCE(m.is_primary, 0) AS is_primary,
                    COALESCE(m.donor_name, '') AS donor_name,
                    COALESCE(m.donor_email, '') AS donor_email
                FROM platform_campaign_mappings m
                LEFT JOIN master_project_codes c 
                    ON UPPER(TRIM(m.code)) = UPPER(TRIM(c.code))
                   AND COALESCE(m.company_id, 'iqra') = COALESCE(c.company_id, 'iqra')
                WHERE m.platform = 'madinah';
            """)

            # Ensure sponsorship targets table exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sponsorship_targets (
                    sponsorship_type TEXT,
                    company_id TEXT DEFAULT 'rethink',
                    target_value REAL,
                    PRIMARY KEY(sponsorship_type, company_id)
                );
            """)
            cur.execute("SELECT count(*) FROM sponsorship_targets")
            if cur.fetchone()[0] == 0:
                for comp in ["rethink", "iqra"]:
                    cur.executemany("""
                        INSERT OR IGNORE INTO sponsorship_targets (sponsorship_type, company_id, target_value)
                        VALUES (?, ?, ?)
                    """, [
                        ("Hafiz", comp, 240.0),
                        ("Orphan", comp, 480.0),
                        ("Widow", comp, 1080.0),
                        ("Ex-Prisoner", comp, 1080.0)
                    ])

            # 1. Beneficiaries Directory Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sponsorship_beneficiaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id TEXT NOT NULL DEFAULT 'rethink',
                    sponsorship_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    location TEXT,
                    project_code TEXT NOT NULL,
                    donor_folder_link TEXT,
                    profile_link TEXT,
                    video_link TEXT,
                    status TEXT DEFAULT 'Unallocated',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 2. Donor & Campaign Allocations Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sponsorship_allocations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id TEXT NOT NULL DEFAULT 'rethink',
                    beneficiary_id INTEGER NOT NULL UNIQUE,
                    donor_email TEXT NOT NULL,
                    donor_name TEXT,
                    donor_id TEXT,
                    allocation_type TEXT NOT NULL DEFAULT 'individual',
                    campaign_name TEXT,
                    community_name TEXT,
                    allocated_amount REAL NOT NULL DEFAULT 0.0,
                    communication_status TEXT DEFAULT 'Profile Pending',
                    last_contacted_at TIMESTAMP,
                    last_replied_at TIMESTAMP,
                    admin_notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(beneficiary_id) REFERENCES sponsorship_beneficiaries(id) ON DELETE CASCADE
                );
            """)

            cur.execute("PRAGMA table_info(sponsorship_allocations)")
            s_alloc_cols = [r[1] for r in cur.fetchall()]
            if "allocation_type" not in s_alloc_cols:
                cur.execute("ALTER TABLE sponsorship_allocations ADD COLUMN allocation_type TEXT NOT NULL DEFAULT 'individual'")
            if "campaign_name" not in s_alloc_cols:
                cur.execute("ALTER TABLE sponsorship_allocations ADD COLUMN campaign_name TEXT")
            if "community_name" not in s_alloc_cols:
                cur.execute("ALTER TABLE sponsorship_allocations ADD COLUMN community_name TEXT")

            # 3. Two-Way Gmail Communication Log Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sponsorship_communications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    allocation_id INTEGER NOT NULL,
                    company_id TEXT NOT NULL DEFAULT 'rethink',
                    direction TEXT NOT NULL,
                    message_id TEXT,
                    thread_id TEXT,
                    subject TEXT,
                    body TEXT,
                    sender_email TEXT,
                    recipient_email TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(allocation_id) REFERENCES sponsorship_allocations(id) ON DELETE CASCADE
                );
            """)

            # 4. Multi-Year End-Year Feedbacks Timeline Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sponsorship_feedbacks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    beneficiary_id INTEGER NOT NULL,
                    allocation_id INTEGER,
                    company_id TEXT NOT NULL DEFAULT 'rethink',
                    feedback_title TEXT NOT NULL,
                    feedback_date TEXT NOT NULL,
                    report_link TEXT,
                    video_link TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(beneficiary_id) REFERENCES sponsorship_beneficiaries(id) ON DELETE CASCADE
                );
            """)

            # 5. Microsoft 365 / Outlook OAuth & Graph Webhook Credentials Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sponsorship_outlook_auth (
                    company_id TEXT PRIMARY KEY,
                    client_id TEXT,
                    client_secret TEXT,
                    tenant_id TEXT DEFAULT 'common',
                    refresh_token TEXT,
                    access_token TEXT,
                    token_expiry TIMESTAMP,
                    connected_email TEXT,
                    subscription_id TEXT,
                    subscription_expiration TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Seed default Microsoft Azure App credentials for organizations if configured.
            # Only fills blanks: credentials saved per charity in the tracker UI must survive restarts.
            azure_client_id = os.getenv("AZURE_CLIENT_ID", "")
            azure_client_secret = os.getenv("AZURE_CLIENT_SECRET", "")
            azure_tenant_id = os.getenv("AZURE_TENANT_ID", "common")
            if azure_client_id and azure_client_secret:
                for cid in ["rethink", "iqra"]:
                    cur.execute("""
                        INSERT INTO sponsorship_outlook_auth (company_id, client_id, client_secret, tenant_id)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(company_id) DO UPDATE SET
                            client_id = CASE WHEN COALESCE(client_id, '') = '' THEN excluded.client_id ELSE client_id END,
                            client_secret = CASE WHEN COALESCE(client_secret, '') = '' THEN excluded.client_secret ELSE client_secret END,
                            tenant_id = CASE WHEN COALESCE(tenant_id, '') IN ('', 'common') THEN excluded.tenant_id ELSE tenant_id END
                    """, (cid, azure_client_id, azure_client_secret, azure_tenant_id))

            # 6. Sponsorship Email Templates Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sponsorship_email_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id TEXT NOT NULL,
                    template_type TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body_html TEXT NOT NULL,
                    UNIQUE(company_id, template_type)
                );
            """)

            # 7. Sponsorship Manual / Offline Donors Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sponsorship_manual_donors (
                    id TEXT PRIMARY KEY,
                    company_id TEXT NOT NULL DEFAULT 'rethink',
                    donor_name TEXT NOT NULL,
                    donor_email TEXT DEFAULT '',
                    donor_phone TEXT DEFAULT '',
                    sponsorship_type TEXT NOT NULL,
                    total_donated REAL NOT NULL DEFAULT 0.0,
                    custom_slots INTEGER DEFAULT NULL,
                    notes TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Default email templates for all supported charities
            for cid in ["rethink", "iqra", "sp"]:
                org_name = "Rethink Charity" if cid == "rethink" else ("IQRA" if cid == "iqra" else "Sisters' Project")
                cur.execute("""
                    INSERT OR IGNORE INTO sponsorship_email_templates (company_id, template_type, subject, body_html)
                    VALUES (?, 'profile_intro', ?, ?)
                """, (
                    cid,
                    f"Sponsorship Profile Update: Welcome to Sponsoring {{beneficiary_name}} | {org_name}",
                    f"<p>Dear {{donor_name}},</p><p>Thank you for your generous support of {org_name}. We are delighted to share the profile of the beneficiary you are sponsoring:</p><p><strong>Name:</strong> {{beneficiary_name}}<br/><strong>Location:</strong> {{location}}<br/><strong>Sponsorship Code:</strong> {{project_code}}</p><p>You can view the full profile report here: <a href=\"{{profile_link}}\">View Profile Report</a></p><p>May your support bring immense blessings.</p><p>Warm regards,<br/>{org_name} Sponsorship Team</p>"
                ))

            conn.commit()
        except Exception as e:
            print(f"Classification DB init notice: {e}")
        finally:
            conn.close()

def get_classification_matrix(df_raw=None, company_id: Optional[str] = "rethink"):
    """Returns the campaign_classifications matrix DataFrame with unique (Campaign Name, Giving Level, Code) granularity for a company."""
    init_classification_db()
    target_cols = ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility", "Department", "Office", "Portfolio", "Programme Fund", "Fund Code"]
    comp = str(company_id or "rethink").lower().strip()

    # 1. Read existing saved rules directly from SQLite
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        where_clause = " WHERE LOWER(COALESCE(company_id, 'rethink')) = ?" if comp != "all" else ""
        params = [comp] if comp != "all" else []
        db_matrix = pd.read_sql_query(f"""
            SELECT 
                campaign_name as "Campaign Name",
                COALESCE(giving_level, '') as "Giving Level",
                COALESCE(code, 'Unassigned') as "Code",
                COALESCE(special_case, '') as "Special Case",
                COALESCE(special_treatment, '') as "Special Treatment",
                COALESCE(campaign_url, '') as "Campaign URL",
                COALESCE(community_name, 'N/A') as "Community Name",
                COALESCE(department, heading, 'Unassigned') as "Department",
                COALESCE(office, sub_heading, 'Unassigned') as "Office",
                COALESCE(portfolio, '') as "Portfolio",
                COALESCE(programme_fund, '') as "Programme Fund",
                COALESCE(fund_code, '') as "Fund Code",
                COALESCE(heading, department, 'Unassigned') as "Heading",
                COALESCE(sub_heading, office, 'Unassigned') as "Sub-Heading",
                COALESCE(country, 'Unassigned') as "Country",
                COALESCE(zakat_eligibility, 'Unassigned') as "Zakat Eligibility",
                COALESCE(is_primary, 0) as "is_primary",
                COALESCE(donor_name, '') as "Donor Name",
                COALESCE(donor_email, '') as "Donor Email"
            FROM campaign_classifications
            {where_clause}
        """, conn, params=params)
    except Exception:
        db_matrix = pd.DataFrame(columns=["Campaign Name", "Giving Level", "Code", "Campaign URL", "Community Name"] + [c for c in target_cols if c != "Code"])
    finally:
        conn.close()

    if not db_matrix.empty:
        db_matrix["Campaign Name"] = db_matrix["Campaign Name"].apply(fix_mojibake).str.strip().str.replace("’", "'").str.replace("‘", "'")
        db_matrix["Community Name"] = db_matrix["Community Name"].apply(fix_mojibake).str.strip()
        db_matrix["Giving Level"] = db_matrix["Giving Level"].apply(fix_mojibake).str.strip()

    # 2. Extract distinct (Campaign Name, Giving Level, Code) triples from real donations
    donor_distinct = None
    try:
        from core.analytics_engine import get_duckdb_connection
        con = get_duckdb_connection()
        if con and os.path.exists(PARQUET_PATH):
            company_filter = f"AND LOWER(COALESCE(\"company_id\", 'rethink')) = '{comp}'" if comp != "all" else ""
            has_sc = False
            try:
                cols_check = con.execute(f"DESCRIBE SELECT * FROM '{PARQUET_PATH.replace(chr(92), '/')}' LIMIT 1").df()
                has_sc = "Special Case" in cols_check["column_name"].values
            except Exception:
                has_sc = False
            sc_sql = 'MAX(COALESCE(NULLIF(TRIM("Special Case"), \'\'), \'\')) as "Special Case",' if has_sc else "'' as \"Special Case\","

            donor_distinct = con.execute(f"""
                SELECT 
                    COALESCE(NULLIF(TRIM("Campaign Name"), ''), 'N/A') as "Campaign Name",
                    CASE 
                        WHEN "Giving Level Title" IS NULL OR LOWER(TRIM("Giving Level Title")) IN ('', 'nan', 'none', 'null', 'n/a', 'default (general)') THEN ''
                        ELSE TRIM("Giving Level Title")
                    END as "Giving Level",
                    COALESCE(NULLIF(TRIM("Code"), ''), 'Unassigned') as "Code",
                    MAX(COALESCE(NULLIF(TRIM("Community Name"), ''), 'N/A')) as "Community Name",
                    MAX(COALESCE(NULLIF(TRIM("Campaign URL"), ''), '')) as "Campaign URL",
                    {sc_sql}
                    COUNT(*) as donation_count,
                    SUM(TRY_CAST(REPLACE(REPLACE(COALESCE(CAST("Total Online Donation Gross Amount in Settled Currency" AS VARCHAR), CAST("Donation Amount (in Donation Currency)" AS VARCHAR), '0'), '£', ''), ',', '') AS DOUBLE)) as total_amount
                FROM '{PARQUET_PATH.replace(chr(92), '/')}'
                WHERE LOWER(COALESCE("Platform", '')) NOT IN ('givebright', 'givebrite', 'paysuite', 'madinah')
                  AND "Campaign Name" IS NOT NULL
                  AND LOWER(TRIM(CAST("Campaign Name" AS VARCHAR))) NOT IN ('', 'nan', 'none', 'null', 'n/a', 'unassigned')
                  {company_filter}
                GROUP BY "Campaign Name", "Giving Level", "Code"
            """).df()
    except Exception as e:
        donor_distinct = None

    if donor_distinct is None or donor_distinct.empty:
        df_donations = df_raw if (df_raw is not None and not df_raw.empty) else load_data(company_id=comp)
        if df_donations is not None and not df_donations.empty and "Campaign Name" in df_donations.columns:
            plat_series = df_donations.get("Platform", pd.Series("", index=df_donations.index)).astype(str).str.lower()
            lg_mask = ~plat_series.isin(["givebright", "givebrite", "paysuite", "madinah"])
            lg_df = df_donations[lg_mask] if lg_mask.any() else df_donations.iloc[0:0]

            if not lg_df.empty:
                c_name = lg_df["Campaign Name"].astype(str).str.strip().str.replace("’", "'").str.replace("‘", "'")
                c_name = c_name[~c_name.str.lower().isin(['nan', 'none', 'n/a', '', 'unassigned'])]
                gl_name = lg_df.loc[c_name.index, "Giving Level Title"].fillna("").astype(str).str.strip().replace({'nan': '', 'None': '', 'null': '', 'N/A': '', 'Default (General)': ''}) if "Giving Level Title" in lg_df.columns else pd.Series("", index=c_name.index)
                comm_name = lg_df.loc[c_name.index, "Community Name"].astype(str).str.strip().replace({'nan': 'N/A', '': 'N/A', 'None': 'N/A'}) if "Community Name" in lg_df.columns else pd.Series("N/A", index=c_name.index)
                code_val = lg_df.loc[c_name.index, "Code"].astype(str).str.strip().replace({'nan': 'Unassigned', '': 'Unassigned', 'None': 'Unassigned'}) if "Code" in lg_df.columns else pd.Series("Unassigned", index=c_name.index)
                donor_df = pd.DataFrame({"Campaign Name": c_name, "Giving Level": gl_name, "Code": code_val, "Community Name": comm_name})
                if "Special Case" in lg_df.columns:
                    donor_df["Special Case"] = lg_df.loc[c_name.index, "Special Case"].fillna("").astype(str).str.strip().replace({'nan': '', 'None': '', 'Unassigned': ''})
                else:
                    donor_df["Special Case"] = ""
                donor_distinct = donor_df.drop_duplicates(subset=["Campaign Name", "Giving Level", "Code"])

    if donor_distinct is not None and not donor_distinct.empty:
        donor_distinct["Campaign Name"] = donor_distinct["Campaign Name"].apply(fix_mojibake).str.strip().str.replace("’", "'").str.replace("‘", "'")
        donor_distinct["Community Name"] = donor_distinct["Community Name"].apply(fix_mojibake).str.strip()
        donor_distinct["Giving Level"] = donor_distinct["Giving Level"].apply(fix_mojibake).str.strip().replace({'nan': '', 'None': '', 'null': '', 'N/A': '', 'Default (General)': ''})
        if "Special Case" not in donor_distinct.columns:
            donor_distinct["Special Case"] = ""

        if db_matrix.empty:
            merged_raw = donor_distinct.copy()
            for c in target_cols:
                if c not in merged_raw.columns:
                    merged_raw[c] = "Unassigned" if c not in ["Portfolio", "Programme Fund", "Fund Code", "Special Case"] else ""
        else:
            db_matrix["Campaign Name"] = db_matrix["Campaign Name"].apply(fix_mojibake).str.strip().str.replace("’", "'").str.replace("‘", "'")
            db_matrix["Giving Level"] = db_matrix["Giving Level"].apply(fix_mojibake).str.strip().replace({'nan': '', 'None': '', 'null': '', 'N/A': '', 'Default (General)': ''})

            merged = pd.merge(
                donor_distinct,
                db_matrix,
                on=["Campaign Name", "Giving Level", "Code"],
                how="outer",
                suffixes=('', '_db')
            )
            if "Community Name_db" in merged.columns:
                merged["Community Name"] = merged["Community Name"].replace("N/A", "").combine_first(merged["Community Name_db"]).replace("", "N/A")
                merged.drop(columns=["Community Name_db"], inplace=True)
            if "Campaign URL_db" in merged.columns:
                merged["Campaign URL"] = merged["Campaign URL"].replace("", "").combine_first(merged["Campaign URL_db"])
                merged.drop(columns=["Campaign URL_db"], inplace=True)
            if "Special Case_db" in merged.columns:
                invalid_sc = ["", "unassigned", "none", "none (standard)", "nan", "null", "n/a"]
                sc_db = merged["Special Case_db"].fillna("").astype(str).str.strip()
                sc_donor = merged["Special Case"].fillna("").astype(str).str.strip()
                clean_db = sc_db.replace({v: "" for v in invalid_sc})
                clean_donor = sc_donor.replace({v: "" for v in invalid_sc})
                # db_matrix (user saved rules) takes precedence over donor transactions
                merged["Special Case"] = np.where(clean_db != "", clean_db, clean_donor)
                merged.drop(columns=["Special Case_db"], inplace=True)
            for c in target_cols:
                if c in merged.columns:
                    if c not in ["Portfolio", "Programme Fund", "Fund Code", "Special Case"]:
                        merged[c] = merged[c].fillna("Unassigned")
                    else:
                        merged[c] = merged[c].fillna("")
            merged_raw = merged
    else:
        merged_raw = db_matrix

    # 3. Canonical Deduplication & Ghost Row Purging
    cleaned_rows = []
    if not merged_raw.empty:
        cname_gl_groups = merged_raw.groupby([
            merged_raw["Campaign Name"].astype(str).str.strip().str.lower(),
            merged_raw["Giving Level"].astype(str).str.strip().str.lower()
        ])
        for (c_low, gl_low), grp in cname_gl_groups:
            assigned_rows = grp[~grp["Code"].astype(str).str.strip().str.upper().isin(["UNASSIGNED", "N/A", "NONE", "NAN", ""])]
            rows_to_process = assigned_rows if not assigned_rows.empty else grp.iloc[0:1]

            code_groups = rows_to_process.groupby(rows_to_process["Code"].astype(str).str.upper())
            for code_up, c_grp in code_groups:
                row = c_grp.iloc[0].copy()
                if "Campaign URL" in c_grp.columns:
                    urls = [u for u in c_grp["Campaign URL"] if str(u).strip() and str(u).strip().startswith("http")]
                    if urls:
                        row["Campaign URL"] = urls[0]
                if "Community Name" in c_grp.columns:
                    comms = [c for c in c_grp["Community Name"] if str(c).strip().lower() not in ["n/a", "unassigned", "none", "nan", ""]]
                    if comms:
                        row["Community Name"] = comms[0]
                if "Special Case" in c_grp.columns:
                    scs = [s for s in c_grp["Special Case"] if str(s).strip() and str(s).strip().lower() not in ["unassigned", "none", "none (standard)", "nan", "null", "n/a", ""]]
                    if scs:
                        row["Special Case"] = scs[0]
                    else:
                        grp_scs = [s for s in grp["Special Case"] if str(s).strip() and str(s).strip().lower() not in ["unassigned", "none", "none (standard)", "nan", "null", "n/a", ""]] if "Special Case" in grp.columns else []
                        row["Special Case"] = grp_scs[0] if grp_scs else ""
                # Inherit donation metrics from grp if row was filled from db_matrix without donation metrics
                if (pd.isna(row.get("donation_count")) or row.get("donation_count") == 0) and "donation_count" in grp.columns:
                    d_sum = grp["donation_count"].dropna().sum()
                    if d_sum > 0:
                        row["donation_count"] = int(d_sum)
                if (pd.isna(row.get("total_amount")) or row.get("total_amount") == 0.0) and "total_amount" in grp.columns:
                    t_sum = grp["total_amount"].dropna().sum()
                    if t_sum > 0:
                        row["total_amount"] = round(float(t_sum), 2)
                cleaned_rows.append(row)

    deduped_df = pd.DataFrame(cleaned_rows) if cleaned_rows else merged_raw

    # Dynamic auto-assignment based on Code mapping in < 5ms
    code_map = get_code_to_classification_map(company_id=comp)
    if code_map and "Code" in deduped_df.columns:
        code_clean = deduped_df["Code"].astype(str).str.strip().str.lower()
        for tc in ["Department", "Office", "Portfolio", "Heading", "Sub-Heading", "Country", "Zakat Eligibility", "Programme Fund", "Fund Code"]:
            if tc in deduped_df.columns:
                target_map = {k: v[tc] for k, v in code_map.items() if tc in v and str(v[tc]).lower() != "unassigned"}
                mask_unassigned = deduped_df[tc].astype(str).str.strip().str.lower().isin(["", "unassigned", "nan", "none"])
                mapped_vals = code_clean.map(target_map)
                fill_mask = mask_unassigned & mapped_vals.notna()
                if fill_mask.any():
                    deduped_df.loc[fill_mask, tc] = mapped_vals[fill_mask]

    # Ensure Special Case from platform_campaign_mappings is preserved if deduped row has an assigned code
    if not deduped_df.empty and "Special Case" in deduped_df.columns:
        sc_missing_mask = deduped_df["Special Case"].fillna("").astype(str).str.strip().isin(["", "none", "unassigned", "none (standard)"])
        assigned_mask = ~deduped_df["Code"].astype(str).str.strip().str.upper().isin(["UNASSIGNED", "NONE", "NAN", "", "N/A"])
        to_lookup_mask = sc_missing_mask & assigned_mask
        if to_lookup_mask.any():
            try:
                conn_sc = sqlite3.connect(LOCAL_DB_PATH, timeout=15.0)
                sc_map_df = pd.read_sql_query("""
                    SELECT campaign_name, code, special_case 
                    FROM platform_campaign_mappings 
                    WHERE special_case IS NOT NULL AND TRIM(special_case) NOT IN ('', 'none', 'unassigned', 'none (standard)', 'nan', 'null')
                      AND LOWER(COALESCE(company_id, 'rethink')) = ?
                      AND LOWER(platform) = 'launchgood'
                """, conn_sc, params=(comp,))
                conn_sc.close()
                if not sc_map_df.empty:
                    sc_lookup = {}
                    for _, sc_r in sc_map_df.iterrows():
                        c_canon = canonical_campaign_key(sc_r["campaign_name"])
                        code_up = str(sc_r["code"] or "").strip().upper()
                        val = canonicalize_special_case(fix_mojibake(str(sc_r["special_case"])))
                        if val:
                            sc_lookup[(c_canon, code_up)] = val
                            if c_canon not in sc_lookup:
                                sc_lookup[c_canon] = val
                    for l_idx in deduped_df[to_lookup_mask].index:
                        l_cname = deduped_df.at[l_idx, "Campaign Name"]
                        l_code = str(deduped_df.at[l_idx, "Code"]).strip().upper()
                        l_canon = canonical_campaign_key(l_cname)
                        found_sc = sc_lookup.get((l_canon, l_code), sc_lookup.get(l_canon))
                        if found_sc:
                            deduped_df.at[l_idx, "Special Case"] = found_sc
            except Exception:
                pass

    if "donation_count" in deduped_df.columns:
        deduped_df["donation_count"] = pd.to_numeric(deduped_df["donation_count"], errors="coerce").fillna(0).astype(int)
    else:
        deduped_df["donation_count"] = 0
    if "total_amount" in deduped_df.columns:
        deduped_df["total_amount"] = pd.to_numeric(deduped_df["total_amount"], errors="coerce").fillna(0.0).round(2)
    else:
        deduped_df["total_amount"] = 0.0

    return deduped_df



def sanitize_df_dtypes_for_parquet(df):
    """Sanitizes object/date/datetime/ID columns to string format and eliminates case-insensitive duplicate columns."""
    if df is None or df.empty:
        return df
    
    # 1. Eliminate case-insensitive duplicate columns (e.g. 'title' vs 'Title')
    df = deduplicate_dataframe_columns(df)
    
    # 2. Sanitize column dtypes for PyArrow and SQLite compatibility
    for col in df.columns:
        if df[col].dtype == 'object' or col in ["Created Date (UTC)", "Created Time (UTC)", "Date", "Time", "Donation ID", "Donor ID"]:
            df[col] = df[col].astype(str).replace({'nan': '', 'None': '', 'NaN': '', '<NA>': '', 'NaT': ''})
            
    return df


def sync_donors_to_classification_matrix(df_raw=None):
    """
    Synchronizes updated classifications (Code, Department/Heading, Office/Sub-Heading, Portfolio, Country, Zakat Eligibility)
    from active donor transactions into SQLite master_project_codes and platform_campaign_mappings.
    """
def sync_donors_to_classification_matrix(df_raw=None, company_id: str = "rethink"):
    """
    Synchronizes updated classifications (Code, Department/Heading, Office/Sub-Heading, Portfolio, Country, Zakat Eligibility)
    from active donor transactions into SQLite master_project_codes and platform_campaign_mappings.
    Strictly isolated per company_id.
    """
    comp = str(company_id or "rethink").lower().strip()
    invalidate_code_map(comp)
    
    init_classification_db()
    df = df_raw if (df_raw is not None and not df_raw.empty) else load_data(company_id=comp)
    if df.empty or "Campaign Name" not in df.columns:
        return 0

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    cursor = conn.cursor()
    synced_total = 0

    try:
        platform_s = df.get("Platform", pd.Series("", index=df.index)).astype(str).str.lower()
        source_s = df.get("Source", pd.Series("", index=df.index)).astype(str).str.lower()

        # Partition Platform Masks
        ws_mask = platform_s.isin(["rethink website", "website"]) | source_s.str.contains("rethink|website", na=False)
        gb_mask = platform_s.isin(["givebright", "givebrite"]) | source_s.str.contains("givebright|givebrite|give_bright|give_brite", na=False)
        mad_mask = platform_s.isin(["madinah"]) | source_s.str.contains("madinah", na=False)
        ps_mask = platform_s.isin(["paysuite"]) | source_s.str.contains("paysuite", na=False)
        lg_mask = (~ws_mask) & (~gb_mask) & (~mad_mask) & (~ps_mask)

        platforms_data = [
            ("launchgood", df[lg_mask]),
            ("givebright", df[gb_mask]),
            ("madinah", df[mad_mask]),
            ("paysuite", df[ps_mask]),
            ("website", df[ws_mask])
        ]

        for plat_name, p_df in platforms_data:
            if p_df.empty:
                continue

            agg_cols = {}
            for c_name, fn in [
                ("Community Name", "first"),
                ("Campaign URL", "first"),
                ("Department", "last"),
                ("Office", "last"),
                ("Portfolio", "last"),
                ("Heading", "last"),
                ("Sub-Heading", "last"),
                ("Country", "last"),
                ("Zakat Eligibility", "last"),
                ("First Name", "last"),
                ("Last Name", "last"),
                ("Email", "last")
            ]:
                if c_name in p_df.columns:
                    agg_cols[c_name] = fn

            if agg_cols:
                grouped = p_df.groupby(["Campaign Name", "Code"], as_index=False).agg(agg_cols)
            else:
                grouped = p_df[["Campaign Name", "Code"]].drop_duplicates()

            master_rows = []
            mapping_rows = []

            for _, r in grouped.iterrows():
                cname = str(r["Campaign Name"]).strip()
                code = str(r.get("Code") or "Unassigned").strip().upper()
                if not cname or cname.lower() in ["nan", "none", "n/a", ""]:
                    continue

                dept = str(r.get("Department") or r.get("Heading") or "Unassigned").strip()
                off = str(r.get("Office") or r.get("Sub-Heading") or "Unassigned").strip()
                port = str(r.get("Portfolio") or "").strip()
                country = str(r.get("Country") or "Unassigned").strip()
                zakat = str(r.get("Zakat Eligibility") or "Unassigned").strip()
                if zakat == "Unassigned":
                    zakat = "Zakat"

                if code and code not in ["UNASSIGNED", "NAN", "NONE", "N/A", ""]:
                    master_rows.append((code, dept, off, port, country, zakat, comp))

                comm = str(r.get("Community Name") or "N/A").strip()
                curl = str(r.get("Campaign URL") or "").strip()
                # These rows are aggregated from DONATIONS, so First/Last Name and Email belong to
                # whichever donor gave last - not the campaign's organizer. Never store them as the
                # campaign contact; organizers live in the Fundraisers registry. Empty values leave
                # any existing (manually set) contact untouched via the ON CONFLICT rule below.
                d_name = ""
                d_email = ""

                mapping_rows.append((plat_name, cname, code, comm, curl, d_name, d_email, comp))

            if master_rows:
                cursor.executemany("""
                    INSERT INTO master_project_codes (code, department, office, portfolio, country, zakat_eligibility, company_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(company_id, code) DO UPDATE SET
                        department = CASE WHEN excluded.department != 'Unassigned' THEN excluded.department ELSE master_project_codes.department END,
                        office = CASE WHEN excluded.office != 'Unassigned' THEN excluded.office ELSE master_project_codes.office END,
                        portfolio = CASE WHEN excluded.portfolio != '' THEN excluded.portfolio ELSE master_project_codes.portfolio END,
                        country = CASE WHEN excluded.country != 'Unassigned' THEN excluded.country ELSE master_project_codes.country END,
                        zakat_eligibility = CASE WHEN excluded.zakat_eligibility != 'Unassigned' THEN excluded.zakat_eligibility ELSE master_project_codes.zakat_eligibility END;
                """, master_rows)

            if mapping_rows:
                cursor.executemany("""
                    INSERT INTO platform_campaign_mappings (platform, campaign_name, code, community_name, campaign_url, donor_name, donor_email, company_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(company_id, platform, campaign_name, giving_level, code) DO UPDATE SET
                        community_name = COALESCE(NULLIF(excluded.community_name, 'N/A'), platform_campaign_mappings.community_name),
                        campaign_url = COALESCE(NULLIF(excluded.campaign_url, ''), platform_campaign_mappings.campaign_url),
                        donor_name = CASE WHEN excluded.donor_name != '' THEN excluded.donor_name ELSE platform_campaign_mappings.donor_name END,
                        donor_email = CASE WHEN excluded.donor_email != '' THEN excluded.donor_email ELSE platform_campaign_mappings.donor_email END;
                """, mapping_rows)
                synced_total += len(mapping_rows)

        conn.commit()
    finally:
        conn.close()

    return synced_total


def sync_matrix_classifications_to_donors(matrix_df=None, company_id: str = "rethink"):
    """
    Updates matching donor records and payout settlements in Parquet and SQLite DB
    with saved classification matrix rules using (Campaign Name, Giving Level, Code) precision.
    Strictly partitioned to only update records belonging to company_id.
    """
    comp = str(company_id or "rethink").lower().strip()
    if comp == "all":
        return 0

    df_raw = load_data(force_reload=True)
    if df_raw.empty or "Campaign Name" not in df_raw.columns:
        return 0

    if "company_id" not in df_raw.columns:
        df_raw["company_id"] = "rethink"

    comp_mask = (df_raw["company_id"].astype(str).str.lower() == comp)
    if not comp_mask.any():
        return 0

    def _norm_campaign_title(name_val):
        if not name_val:
            return ""
        return fix_mojibake(str(name_val)).strip().lower().replace("’", "'").replace("‘", "'")

    campaign_series = df_raw["Campaign Name"].apply(_norm_campaign_title)
    base_campaign_series = campaign_series.apply(lambda s: s.split("|")[0].strip() if "|" in s else s)
    gl_series = df_raw["Giving Level Title"].fillna("").astype(str).str.strip().str.lower().str.replace("’", "'").str.replace("‘", "'") if "Giving Level Title" in df_raw.columns else pd.Series("", index=df_raw.index)

    # 1. Load all platform mappings for this company from DB to guarantee complete coverage
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    try:
        db_rules = pd.read_sql_query("""
            SELECT 
                m.campaign_name as "Campaign Name",
                COALESCE(m.giving_level, '') as "Giving Level",
                COALESCE(m.code, 'Unassigned') as "Code",
                COALESCE(m.campaign_url, '') as "Campaign URL",
                COALESCE(m.community_name, 'N/A') as "Community Name",
                COALESCE(m.is_primary, 0) as "is_primary",
                COALESCE(c.department, 'Unassigned') as "Department",
                COALESCE(c.office, 'Unassigned') as "Office",
                COALESCE(c.portfolio, '') as "Portfolio",
                COALESCE(c.department, 'Unassigned') as "Heading",
                COALESCE(c.office, 'Unassigned') as "Sub-Heading",
                COALESCE(c.country, 'Unassigned') as "Country",
                COALESCE(c.zakat_eligibility, 'Unassigned') as "Zakat Eligibility",
                COALESCE(c.programme_fund, '') as "Programme Fund",
                COALESCE(c.fund_code, '') as "Fund Code",
                COALESCE(m.special_case, '') as "Special Case"
            FROM platform_campaign_mappings m
            LEFT JOIN master_project_codes c 
                ON UPPER(TRIM(m.code)) = UPPER(TRIM(c.code)) 
                AND LOWER(COALESCE(m.company_id, 'rethink')) = LOWER(COALESCE(c.company_id, 'rethink'))
            WHERE LOWER(COALESCE(m.company_id, 'rethink')) = ?
        """, conn, params=(comp,))
    except Exception as e:
        print(f"[DB rules query notice]: {e}")
        db_rules = pd.DataFrame()
    finally:
        conn.close()

    if matrix_df is not None and not matrix_df.empty:
        all_rules = pd.concat([db_rules, matrix_df], ignore_index=True)
    else:
        all_rules = db_rules

    # Prepare fast lookup maps
    gl_rule_map = {}
    camp_default_rule_map = {}
    cname_to_rules = {}

    for _, row in all_rules.iterrows():
        cname = _norm_campaign_title(row.get("Campaign Name", ""))
        if not cname or cname in ["n/a", "none", "nan", ""]:
            continue
        cname_to_rules.setdefault(cname, []).append(row.to_dict())
        c_base = cname.split("|")[0].strip() if "|" in cname else cname
        if c_base != cname:
            cname_to_rules.setdefault(c_base, []).append(row.to_dict())
        c_canon = canonical_campaign_key(cname)
        if c_canon:
            cname_to_rules.setdefault(c_canon, []).append(row.to_dict())
        
        r_gl = str(row.get("Giving Level") or row.get("giving_level") or "").strip().lower().replace("’", "'").replace("‘", "'")
        r_dept = str(row.get("Department") or row.get("Heading", "Unassigned"))
        r_off = str(row.get("Office") or row.get("Sub-Heading", "Unassigned"))
        r_port = str(row.get("Portfolio") or "")
        r_cntry = str(row.get("Country", "Unassigned"))
        r_code = str(row.get("Code", "Unassigned"))
        r_zakat = str(row.get("Zakat Eligibility", "Unassigned"))
        r_prog = str(row.get("Programme Fund", ""))
        r_fund = str(row.get("Fund Code", ""))
        r_spec = str(row.get("Special Case") or row.get("special_case") or "").strip()
        if r_spec.lower() in ["unassigned", "none", "none (standard)", "nan", "null", "n/a"]:
            r_spec = ""
        r_url = str(row.get("Campaign URL") or "").strip()

        col_vals = {
            "Department": r_dept, "Office": r_off, "Portfolio": r_port,
            "Heading": r_dept, "Sub-Heading": r_off, "Country": r_cntry,
            "Code": r_code, "Zakat Eligibility": r_zakat,
            "Programme Fund": r_prog, "Fund Code": r_fund,
            "Special Case": r_spec
        }
        if r_url:
            col_vals["Campaign URL"] = r_url

        if r_gl and r_gl not in ["nan", "none", "n/a", "campaign default / general", "campaign default", "default (general)", ""]:
            gl_rule_map[(cname, r_gl)] = col_vals
            if c_base != cname:
                gl_rule_map[(c_base, r_gl)] = col_vals
            if c_canon:
                gl_rule_map[(c_canon, r_gl)] = col_vals
        else:
            def _update_camp_default(key, vals, is_pri):
                if key not in camp_default_rule_map:
                    camp_default_rule_map[key] = dict(vals)
                else:
                    existing = camp_default_rule_map[key]
                    if vals.get("Special Case") and not existing.get("Special Case"):
                        existing["Special Case"] = vals["Special Case"]
                    existing_assigned = str(existing.get("Code", "")).strip().upper() not in ["", "UNASSIGNED", "NONE", "NAN", "N/A"]
                    incoming_assigned = str(vals.get("Code", "")).strip().upper() not in ["", "UNASSIGNED", "NONE", "NAN", "N/A"]
                    if is_pri or (not existing_assigned and incoming_assigned):
                        for k, v in vals.items():
                            if k == "Special Case" and not v and existing.get("Special Case"):
                                continue
                            existing[k] = v

            is_p = bool(row.get("is_primary") in [1, True, "1", "true", "True"])
            _update_camp_default(cname, col_vals, is_p)
            if c_base != cname:
                _update_camp_default(c_base, col_vals, is_p)
            if c_canon:
                _update_camp_default(c_canon, col_vals, is_p)

    # Apply vectorized mapping for this company's donations
    comp_indices = df_raw[comp_mask].index
    c_sub = campaign_series.loc[comp_indices]
    b_sub = base_campaign_series.loc[comp_indices]
    cn_sub = df_raw.loc[comp_indices, "Campaign Name"].apply(canonical_campaign_key)
    g_sub = gl_series.loc[comp_indices]

    keys = list(zip(c_sub, g_sub))
    b_keys = list(zip(b_sub, g_sub))
    cn_keys = list(zip(cn_sub, g_sub))
    
    target_cols = ["Department", "Office", "Portfolio", "Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility", "Programme Fund", "Fund Code", "Special Case"]
    if "Campaign URL" in df_raw.columns:
        target_cols.append("Campaign URL")

    for col in target_cols:
        if col not in df_raw.columns:
            df_raw[col] = "Unassigned" if col not in ["Portfolio", "Programme Fund", "Fund Code", "Special Case"] else ""

        # Giving level specific lookup (exact or base or canonical)
        gl_mapped = [gl_rule_map.get(k, gl_rule_map.get(bk, gl_rule_map.get(cnk, {}))).get(col) for k, bk, cnk in zip(keys, b_keys, cn_keys)]
        # Campaign default lookup (exact or base or canonical)
        camp_mapped = [camp_default_rule_map.get(c, camp_default_rule_map.get(b, camp_default_rule_map.get(cn, {}))).get(col) for c, b, cn in zip(c_sub, b_sub, cn_sub)]

        mapped_series = pd.Series(gl_mapped, index=comp_indices).combine_first(pd.Series(camp_mapped, index=comp_indices))
        if col == "Special Case":
            is_matched = [bool(camp_default_rule_map.get(c) or camp_default_rule_map.get(b) or camp_default_rule_map.get(cn) or gl_rule_map.get(k) or gl_rule_map.get(bk) or gl_rule_map.get(cnk)) for c, b, cn, k, bk, cnk in zip(c_sub, b_sub, cn_sub, keys, b_keys, cn_keys)]
            match_mask = pd.Series(is_matched, index=comp_indices)
            if match_mask.any():
                sc_to_set = mapped_series.fillna("")
                invalid_sc = ["nan", "none", "none (standard)", "unassigned", "null"]
                sc_cleaned = sc_to_set.replace({v: "" for v in invalid_sc})
                df_raw.loc[match_mask[match_mask].index, col] = sc_cleaned.loc[match_mask[match_mask].index]
        else:
            valid_mask = mapped_series.notna() & (~mapped_series.astype(str).str.lower().isin(["", "nan", "none", "unassigned"]))
            if valid_mask.any():
                valid_idx = valid_mask[valid_mask].index
                df_raw.loc[valid_idx, col] = mapped_series.loc[valid_idx]

    df_raw = sanitize_df_dtypes_for_parquet(df_raw)
    df_raw.to_parquet(PARQUET_PATH, index=False)

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    try:
        conn.execute("DELETE FROM donations WHERE LOWER(COALESCE(company_id, 'rethink')) = ?", (comp,))
        df_raw[comp_mask].to_sql("donations", con=conn, if_exists="append", index=False, chunksize=5000)
        conn.commit()
    except Exception as e:
        print(f"[Donations sync to DB notice]: {e}")
    finally:
        conn.close()

    # Also update payouts_cache.parquet & payout_settlements table in SQLite
    try:
        from config.settings import PAYOUTS_PARQUET_PATH
        if os.path.exists(PAYOUTS_PARQUET_PATH):
            pdf = pd.read_parquet(PAYOUTS_PARQUET_PATH)
            if not pdf.empty:
                if "company_id" not in pdf.columns:
                    pdf["company_id"] = "rethink"
                p_comp_mask = (pdf["company_id"].astype(str).str.lower() == comp)
                if p_comp_mask.any():
                    p_cname = pdf.get("Campaign Name", pdf.get("Project Name", pd.Series("", index=pdf.index))).apply(_norm_campaign_title)
                    p_base = p_cname.apply(lambda s: s.split("|")[0].strip() if "|" in s else s)
                    p_canon = pdf.get("Campaign Name", pdf.get("Project Name", pd.Series("", index=pdf.index))).apply(canonical_campaign_key)
                    p_code = pdf.get("Code", pd.Series("unassigned", index=pdf.index)).astype(str).str.strip().str.lower()

                    if "Special Case" not in pdf.columns:
                        pdf["Special Case"] = ""

                    for cname, rules_list in cname_to_rules.items():
                        c_base = cname.split("|")[0].strip() if "|" in cname else cname
                        c_canon = canonical_campaign_key(cname)
                        c_base_canon = canonical_campaign_key(c_base)
                        pc_mask = p_comp_mask & ((p_cname == cname) | (p_cname == c_base) | (p_base == cname) | (p_base == c_base) | (p_canon == c_canon) | (p_canon == c_base_canon))
                        if not pc_mask.any():
                            continue

                        assigned_candidates = [r for r in rules_list if str(r.get("Code", "")).strip().upper() not in ["", "UNASSIGNED", "NONE", "NAN", "N/A", "NULL"]]
                        pri_candidates = [r for r in assigned_candidates if bool(r.get("is_primary") in [1, True, "1", "true", "True"])]
                        primary_row = pri_candidates[0] if pri_candidates else (assigned_candidates[0] if assigned_candidates else next((r for r in rules_list if bool(r.get("is_primary") in [1, True, "1", "true", "True"])), rules_list[0]))

                        spec_candidates = [str(r.get("Special Case") or "").strip() for r in rules_list if str(r.get("Special Case") or "").strip().lower() not in ["", "unassigned", "none", "none (standard)", "nan", "null", "n/a"]]
                        chosen_sc = spec_candidates[0] if spec_candidates else str(primary_row.get("Special Case") or "").strip()
                        if chosen_sc.lower() in ["unassigned", "none", "none (standard)", "nan", "null", "n/a"]:
                            chosen_sc = ""

                        for col in ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility", "Special Case"]:
                            if col in pdf.columns:
                                if col == "Special Case":
                                    pdf.loc[pc_mask, col] = chosen_sc
                                else:
                                    val = primary_row.get(col, "")
                                    if not val or str(val).lower() in ["none", "nan"]:
                                        val = "Unassigned"
                                    pdf.loc[pc_mask, col] = str(val or "")

                    pdf = sanitize_df_dtypes_for_parquet(pdf)
                    atomic_write_parquet(pdf, PAYOUTS_PARQUET_PATH)
                    try:
                        conn_p = sqlite3.connect(LOCAL_DB_PATH, timeout=20.0)
                        conn_p.execute("DELETE FROM payout_settlements WHERE LOWER(COALESCE(company_id, 'rethink')) = ?", (comp,))
                        pdf[p_comp_mask].to_sql("payout_settlements", con=conn_p, if_exists="append", index=False, chunksize=5000)
                        conn_p.commit()
                        conn_p.close()
                    except Exception as e:
                        print(f"[Payout DB update notice]: {e}")
    except Exception as e:
        print(f"[Payout settlement sync notice]: {e}")

    invalidate_data_cache()
    from core.data_processor import invalidate_payouts_cache
    invalidate_payouts_cache()
    return len(comp_indices)
    try:
        from backend.api.expenses import clear_expenses_cache
        clear_expenses_cache()
    except Exception:
        pass
    return updated_count


def save_platform_matrix_rules(platform: str, matrix_df: pd.DataFrame, company_id: str = "rethink") -> int:
    """
    Saves platform classification matrix rules cleanly into two-tier architecture:
    1. Upserts Code -> (department, office, portfolio, country, zakat_eligibility) into master_project_codes.
    2. Synchronizes (platform, campaign_name, giving_level, code) mappings into platform_campaign_mappings.
    3. Synchronizes matching active donor records.
    Strictly isolated per company_id.
    """
    comp = str(company_id or "rethink").lower().strip()
    if comp == "all":
        raise ValueError("Cannot modify matrix rules in consolidated 'All Companies' mode. Select a specific company.")

    init_classification_db()
    if matrix_df.empty:
        return 0

    clean_matrix = matrix_df.copy()

    # Propagate non-empty Special Case across rows with matching canonical campaign key
    canon_to_spec = {}
    for _, r in clean_matrix.iterrows():
        c_name = str(r.get("Campaign Name", "")).strip()
        c_canon = canonical_campaign_key(c_name)
        sc = canonicalize_special_case(r.get("Special Case") or r.get("special_case") or "")
        if sc and c_canon:
            canon_to_spec[c_canon] = sc

    if canon_to_spec:
        for idx in clean_matrix.index:
            c_name = str(clean_matrix.at[idx, "Campaign Name"] or "").strip()
            c_canon = canonical_campaign_key(c_name)
            curr_sc = canonicalize_special_case(clean_matrix.at[idx, "Special Case"] if "Special Case" in clean_matrix.columns else clean_matrix.at[idx, "special_case"])
            if not curr_sc and c_canon in canon_to_spec:
                if "Special Case" in clean_matrix.columns:
                    clean_matrix.at[idx, "Special Case"] = canon_to_spec[c_canon]
                if "special_case" in clean_matrix.columns:
                    clean_matrix.at[idx, "special_case"] = canon_to_spec[c_canon]

    cname_gl_to_codes = {}
    master_code_rows = []
    mapping_rows = []

    for _, row in clean_matrix.iterrows():
        cname = fix_mojibake(str(row.get("Campaign Name", "Unassigned"))).strip().replace("’", "'").replace("‘", "'")
        gl = str(row.get("Giving Level") or row.get("giving_level") or "").strip().replace("’", "'").replace("‘", "'")
        if gl.lower() in ["nan", "none", "n/a", "campaign default / general", "campaign default", "default (general)"]:
            gl = ""
        raw_code = str(row.get("Code", "Unassigned")).strip().upper()
        if not cname or cname.lower() in ["nan", "none", "n/a", "", "campaign_name", "campaign name"]:
            continue

        c_canon = canonical_campaign_key(cname)
        spec_case = canonicalize_special_case(row.get("Special Case") or row.get("special_case") or "")
        if not spec_case and c_canon in canon_to_spec:
            spec_case = canon_to_spec[c_canon]

        # Parse bracket syntax CODE [Special Case]
        code = raw_code
        if "[" in raw_code and raw_code.endswith("]"):
            parts = raw_code.split("[", 1)
            code = parts[0].strip().upper()
            if not spec_case:
                spec_case = canonicalize_special_case(parts[1].rstrip("]").strip())

        cname_gl_to_codes.setdefault((cname.lower(), gl.lower()), set()).add(code.lower())

        dept = str(row.get("Department") or row.get("Heading", "Unassigned")).strip()
        off = str(row.get("Office") or row.get("Sub-Heading", "Unassigned")).strip()
        port = str(row.get("Portfolio", "")).strip()
        country = str(row.get("Country", "Unassigned")).strip()
        zakat = str(row.get("Zakat Eligibility", "Unassigned")).strip()
        if zakat == "Unassigned":
            zakat = "Zakat"

        if code and code not in ["UNASSIGNED", "NAN", "NONE", "N/A", ""]:
            master_code_rows.append((code, dept, off, port, country, zakat, comp))

        comm = fix_mojibake(str(row.get("Community Name", "N/A"))).strip()
        curl = str(row.get("Campaign URL", "") or "").strip()
        is_prim = 1 if row.get("is_primary") in [1, True, "1", "true", "True"] else 0
        d_name = str(row.get("Donor Name", "") or "").strip()
        d_email = str(row.get("Donor Email", "") or "").strip()

        mapping_rows.append((platform.lower(), comp, cname, gl, code, comm, curl, is_prim, d_name, d_email, spec_case))

    import time
    for attempt in range(5):
        try:
            with _DB_LOCK:
                conn = get_db_connection(timeout=60.0)
                with conn:
                    # Clean up any legacy mojibake names in platform_campaign_mappings
                    try:
                        cur_pcm = conn.cursor()
                        cur_pcm.execute("SELECT id, campaign_name FROM platform_campaign_mappings WHERE campaign_name LIKE '%Ä%' OR campaign_name LIKE '%Ã%' OR campaign_name LIKE '%â%' OR campaign_name LIKE '%\xad%'")
                        for m_id, m_cname in cur_pcm.fetchall():
                            fixed_name = fix_mojibake(m_cname).strip()
                            if fixed_name != m_cname:
                                conn.execute("UPDATE OR IGNORE platform_campaign_mappings SET campaign_name = ? WHERE id = ?", (fixed_name, m_id))
                    except Exception:
                        pass

                    # 1. Upsert master project codes
                    if master_code_rows:
                        conn.executemany("""
                            INSERT INTO master_project_codes (code, department, office, portfolio, country, zakat_eligibility, company_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(company_id, code) DO UPDATE SET
                                department = CASE WHEN excluded.department != 'Unassigned' THEN excluded.department ELSE master_project_codes.department END,
                                office = CASE WHEN excluded.office != 'Unassigned' THEN excluded.office ELSE master_project_codes.office END,
                                portfolio = CASE WHEN excluded.portfolio != '' THEN excluded.portfolio ELSE master_project_codes.portfolio END,
                                country = CASE WHEN excluded.country != 'Unassigned' THEN excluded.country ELSE master_project_codes.country END,
                                zakat_eligibility = CASE WHEN excluded.zakat_eligibility != 'Unassigned' THEN excluded.zakat_eligibility ELSE master_project_codes.zakat_eligibility END;
                        """, master_code_rows)

                    # 2. Synchronize platform_campaign_mappings
                    for (cname_lower, gl_lower), codes in cname_gl_to_codes.items():
                        placeholders = ','.join(['?'] * len(codes))
                        conn.execute(f"DELETE FROM platform_campaign_mappings WHERE company_id = ? AND platform = ? AND LOWER(campaign_name) = ? AND LOWER(COALESCE(giving_level, '')) = ? AND LOWER(code) NOT IN ({placeholders})", [comp, platform.lower(), cname_lower, gl_lower] + list(codes))

                    # Deduplicate mapping_rows by (platform, comp, cname, gl, code), preserving non-empty special_case
                    deduped_mapping_rows = {}
                    for row in mapping_rows:
                        m_key = (row[0], row[1], row[2].lower(), row[3].lower(), row[4].upper())
                        if m_key not in deduped_mapping_rows:
                            deduped_mapping_rows[m_key] = row
                        else:
                            existing = deduped_mapping_rows[m_key]
                            if not existing[10] and row[10]:
                                deduped_mapping_rows[m_key] = row
                    mapping_rows = list(deduped_mapping_rows.values())

                    conn.executemany("""
                        INSERT INTO platform_campaign_mappings (platform, company_id, campaign_name, giving_level, code, community_name, campaign_url, is_primary, donor_name, donor_email, special_case)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(platform, company_id, campaign_name, giving_level, code) DO UPDATE SET
                            community_name = COALESCE(NULLIF(excluded.community_name, 'N/A'), platform_campaign_mappings.community_name),
                            campaign_url = COALESCE(NULLIF(excluded.campaign_url, ''), platform_campaign_mappings.campaign_url),
                            is_primary = excluded.is_primary,
                            donor_name = CASE WHEN excluded.donor_name != '' THEN excluded.donor_name ELSE platform_campaign_mappings.donor_name END,
                            donor_email = CASE WHEN excluded.donor_email != '' THEN excluded.donor_email ELSE platform_campaign_mappings.donor_email END,
                            special_case = CASE WHEN excluded.special_case != '' THEN excluded.special_case ELSE platform_campaign_mappings.special_case END,
                            updated_at = CURRENT_TIMESTAMP;
                    """, mapping_rows)

                    # Propagate non-empty special_case to matching campaigns / base campaign titles in platform_campaign_mappings
                    spec_updates = {}
                    for row in mapping_rows:
                        sc_val = row[10]
                        if sc_val and sc_val.lower() not in ["", "none", "none (standard)", "unassigned", "nan", "null"]:
                            c_name = row[2]
                            c_canon = canonical_campaign_key(c_name)
                            if c_canon:
                                spec_updates[c_canon] = sc_val

                    if spec_updates:
                        cur_pcm = conn.cursor()
                        cur_pcm.execute("SELECT id, campaign_name, special_case FROM platform_campaign_mappings WHERE company_id = ? AND platform = ?", (comp, platform.lower()))
                        pcm_rows = cur_pcm.fetchall()
                        for p_id, p_cname, p_sc in pcm_rows:
                            p_canon = canonical_campaign_key(p_cname)
                            if p_canon in spec_updates:
                                target_sc = spec_updates[p_canon]
                                if (p_sc or "").strip() != target_sc:
                                    conn.execute("UPDATE platform_campaign_mappings SET special_case = ? WHERE id = ?", (target_sc, p_id))

                    # Purge ghost unassigned mappings where a valid assigned code exists for the campaign
                    conn.execute("""
                        DELETE FROM platform_campaign_mappings
                        WHERE company_id = ? AND platform = ?
                          AND UPPER(TRIM(COALESCE(code, ''))) IN ('', 'UNASSIGNED', 'NONE', 'NAN', 'N/A', 'NULL')
                          AND LOWER(TRIM(campaign_name)) IN (
                              SELECT LOWER(TRIM(campaign_name))
                              FROM platform_campaign_mappings
                              WHERE company_id = ? AND platform = ?
                                AND UPPER(TRIM(COALESCE(code, ''))) NOT IN ('', 'UNASSIGNED', 'NONE', 'NAN', 'N/A', 'NULL')
                          )
                    """, (comp, platform.lower(), comp, platform.lower()))
                conn.close()
            break
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < 4:
                time.sleep(0.3 * (attempt + 1))
                continue
            raise

    # 3. Synchronize to active donor records in the background so API responds immediately (< 50ms)
    clean_matrix_copy = clean_matrix.copy()
    def _bg_matrix_sync():
        try:
            sync_matrix_classifications_to_donors(clean_matrix_copy, company_id=comp)
        except Exception as e:
            print(f"[Background matrix sync notice]: {e}")

    threading.Thread(target=_bg_matrix_sync, daemon=True).start()
    invalidate_code_map(comp)
    try:
        from backend.api.payouts import invalidate_payouts_cache as _inv_p_cache
        _inv_p_cache(comp)
    except Exception:
        pass
    return len(clean_matrix)


def save_classification_matrix(matrix_df, company_id: str = "rethink"):
    """Saves updated LaunchGood classification matrix into two-tier architecture."""
    return save_platform_matrix_rules("launchgood", matrix_df, company_id=company_id)


def get_paysuite_classification_matrix(df_raw=None, company_id: Optional[str] = "rethink"):
    """Returns the paysuite_classifications matrix DataFrame with (Campaign Name, Code) granularity for a company."""
    init_classification_db()
    target_cols = ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility"]
    comp = str(company_id or "rethink").lower().strip()

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        where_clause = " WHERE LOWER(COALESCE(company_id, 'rethink')) = ?" if comp != "all" else ""
        params = [comp] if comp != "all" else []
        db_matrix = pd.read_sql_query(f"""
            SELECT 
                campaign_name as "Campaign Name",
                COALESCE(code, 'Unassigned') as "Code",
                COALESCE(community_name, 'N/A') as "Community Name",
                COALESCE(heading, 'Unassigned') as "Heading",
                COALESCE(sub_heading, 'Unassigned') as "Sub-Heading",
                COALESCE(country, 'Unassigned') as "Country",
                COALESCE(zakat_eligibility, 'Unassigned') as "Zakat Eligibility",
                COALESCE(donor_name, '') as "Donor Name",
                COALESCE(donor_email, '') as "Donor Email"
            FROM paysuite_classifications
            {where_clause}
        """, conn, params=params)
    except Exception:
        db_matrix = pd.DataFrame(columns=["Campaign Name", "Code", "Community Name"] + [c for c in target_cols if c != "Code"] + ["Donor Name", "Donor Email"])
    finally:
        conn.close()

    df_donations = df_raw if (df_raw is not None and not df_raw.empty) else load_data(company_id=comp)
    if df_donations is not None and not df_donations.empty and "Campaign Name" in df_donations.columns:
        platform_s = df_donations.get("Platform", pd.Series("", index=df_donations.index)).astype(str).str.lower()
        source_s = df_donations.get("Source", pd.Series("", index=df_donations.index)).astype(str).str.lower()
        ps_mask = (platform_s == "paysuite") | source_s.str.contains("paysuite", na=False)
        ps_df = df_donations[ps_mask] if ps_mask.any() else df_donations.iloc[0:0]

        if not ps_df.empty:
            c_name = ps_df["Campaign Name"].astype(str).str.strip()
            c_name = c_name[~c_name.str.lower().isin(['nan', 'none', 'n/a', '', 'unassigned'])]
            comm_name = ps_df.loc[c_name.index, "Community Name"].astype(str).str.strip().replace({'nan': 'N/A', '': 'N/A', 'None': 'N/A'}) if "Community Name" in ps_df.columns else pd.Series("N/A", index=c_name.index)
            code_val = ps_df.loc[c_name.index, "Code"].astype(str).str.strip().replace({'nan': 'Unassigned', '': 'Unassigned', 'None': 'Unassigned'}) if "Code" in ps_df.columns else pd.Series("Unassigned", index=c_name.index)
            
            donor_df = pd.DataFrame({"Campaign Name": c_name, "Code": code_val, "Community Name": comm_name})
            donor_distinct = donor_df.drop_duplicates(subset=["Campaign Name", "Code"])

            if db_matrix.empty:
                return donor_distinct.fillna("Unassigned").reset_index(drop=True)

            merged = pd.merge(
                donor_distinct[["Campaign Name", "Code", "Community Name"]],
                db_matrix,
                on=["Campaign Name", "Code"],
                how="outer",
                suffixes=('', '_db')
            ).fillna("Unassigned")
            return merged.drop_duplicates(subset=["Campaign Name", "Code"]).reset_index(drop=True)

    if not db_matrix.empty:
        return db_matrix.fillna("Unassigned").reset_index(drop=True)

    return pd.DataFrame(columns=["Campaign Name", "Code", "Community Name"] + [c for c in target_cols if c != "Code"])


def save_paysuite_classification_matrix(matrix_df, company_id: str = "rethink"):
    """Saves updated Paysuite classification matrix into two-tier architecture."""
    return save_platform_matrix_rules("paysuite", matrix_df, company_id=company_id)


def get_rethink_website_classification_matrix(df_raw=None, company_id: Optional[str] = "rethink"):
    """Returns the rethink_website_classifications matrix DataFrame with (Campaign Name, Code) granularity for a company."""
    init_classification_db()
    target_cols = ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility"]
    comp = str(company_id or "rethink").lower().strip()

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        where_clause = " WHERE LOWER(COALESCE(company_id, 'rethink')) = ?" if comp != "all" else ""
        params = [comp] if comp != "all" else []
        db_matrix = pd.read_sql_query(f"""
            SELECT 
                campaign_name as "Campaign Name",
                COALESCE(code, 'Unassigned') as "Code",
                COALESCE(community_name, 'N/A') as "Community Name",
                COALESCE(heading, 'Unassigned') as "Heading",
                COALESCE(sub_heading, 'Unassigned') as "Sub-Heading",
                COALESCE(country, 'Unassigned') as "Country",
                COALESCE(zakat_eligibility, 'Unassigned') as "Zakat Eligibility"
            FROM rethink_website_classifications
            {where_clause}
        """, conn, params=params)
    except Exception:
        db_matrix = pd.DataFrame(columns=["Campaign Name", "Code", "Community Name"] + [c for c in target_cols if c != "Code"])
    finally:
        conn.close()

    df_donations = df_raw if (df_raw is not None and not df_raw.empty) else load_data(company_id=comp)
    if df_donations is not None and not df_donations.empty and "Campaign Name" in df_donations.columns:
        platform_s = df_donations.get("Platform", pd.Series("", index=df_donations.index)).astype(str).str.lower()
        ws_mask = platform_s.str.contains("rethink website|website", regex=True, na=False)
        ws_df = df_donations[ws_mask] if ws_mask.any() else df_donations.iloc[0:0]

        if not ws_df.empty:
            c_name = ws_df["Campaign Name"].astype(str).str.strip()
            c_name = c_name[~c_name.str.lower().isin(['nan', 'none', 'n/a', '', 'unassigned'])]
            comm_name = ws_df.loc[c_name.index, "Community Name"].astype(str).str.strip().replace({'nan': 'N/A', '': 'N/A', 'None': 'N/A'}) if "Community Name" in ws_df.columns else pd.Series("N/A", index=c_name.index)
            code_val = ws_df.loc[c_name.index, "Code"].astype(str).str.strip().replace({'nan': 'Unassigned', '': 'Unassigned', 'None': 'Unassigned'}) if "Code" in ws_df.columns else pd.Series("Unassigned", index=c_name.index)
            
            donor_df = pd.DataFrame({"Campaign Name": c_name, "Code": code_val, "Community Name": comm_name})
            donor_distinct = donor_df.drop_duplicates(subset=["Campaign Name", "Code"])

            if db_matrix.empty:
                return donor_distinct.fillna("Unassigned").reset_index(drop=True)

            merged = pd.merge(
                donor_distinct[["Campaign Name", "Code", "Community Name"]],
                db_matrix,
                on=["Campaign Name", "Code"],
                how="outer",
                suffixes=('', '_db')
            ).fillna("Unassigned")
            return merged.drop_duplicates(subset=["Campaign Name", "Code"]).reset_index(drop=True)

    if not db_matrix.empty:
        return db_matrix.fillna("Unassigned").reset_index(drop=True)

    return pd.DataFrame(columns=["Campaign Name", "Code", "Community Name"] + [c for c in target_cols if c != "Code"])


def save_rethink_website_classification_matrix(matrix_df, company_id: str = "rethink"):
    """Saves updated Rethink Website classification matrix into two-tier architecture."""
    return save_platform_matrix_rules("website", matrix_df, company_id=company_id)


def _enrich_dataframe(df, platform="auto", company_id: str = "rethink"):
    """Pre-compute all derived columns (Donor ID, LTV, Classification, Payment Frequency) and apply classifications."""
    if df is None or df.empty:
        return df

    target_cid = str(company_id or "rethink").strip().lower()

    already_multi_platform = "Platform" in df.columns and df["Platform"].dropna().nunique() > 1

    # 1. Platform Detection & Standardization
    is_paysuite = not already_multi_platform and (
        str(platform).lower() == "paysuite" or
        ("Date of collection" in df.columns and ("Bank Ref" in df.columns or "Direct Debit Ref" in df.columns or "Customer Ref" in df.columns)) or
        ("Direct Debit Ref" in df.columns and "Amount" in df.columns) or
        ("Bank Ref" in df.columns and "Amount" in df.columns and ("Due" in df.columns or "Date Due" in df.columns or "Date of collection" in df.columns or "Details" in df.columns))
    )
    is_rethink_website = not already_multi_platform and (("Reference" in df.columns and "Donor First Name" in df.columns and ("Project Name" in df.columns or "Processor" in df.columns)) or (str(platform).lower() in ["rethink website", "website", "rethink_website"]))
    is_madinah = False
    is_givebright = False
    
    if not already_multi_platform and not is_paysuite and not is_rethink_website:
        if str(platform).lower() == "madinah":
            is_madinah = True
        elif str(platform).lower() == "givebright":
            is_givebright = True
        elif str(platform).lower() in ["auto", "none", ""]:
            mad_sig = {"Invoice ID", "Invoice Number", "Announcement Title", "Giving Levels", "Stripe Fees (USD)", "Net Amount (USD)"}
            if len(mad_sig.intersection(set(df.columns))) >= 2:
                is_madinah = True
            else:
                gb_sig = {"donation_id", "campaign_name", "fundraiser_by", "fundraiser_name", "campaign_url", "charge_id", "payment_method_type"}
                if len(gb_sig.intersection(set(df.columns))) >= 2:
                    is_givebright = True

    if is_paysuite:
        # Pre-normalize column aliases
        if "Direct Debit Ref" in df.columns and "Bank Ref" not in df.columns:
            df["Bank Ref"] = df["Direct Debit Ref"]
        if "Date Due" in df.columns and "Due" not in df.columns:
            df["Due"] = df["Date Due"]
        if "Firstname" in df.columns and "First Name" not in df.columns:
            df["First Name"] = df["Firstname"]
        if "Surname" in df.columns and "Last Name" not in df.columns:
            df["Last Name"] = df["Surname"]
        if "Post code" in df.columns and "Postcode" not in df.columns:
            df["Postcode"] = df["Post code"]
        if "Address" in df.columns and "Billing Address" not in df.columns:
            df["Billing Address"] = df["Address"]

        # Classroom rethink village mapping
        if "Code" in df.columns:
            df["Code"] = df["Code"].astype(str).str.strip().replace({
                "classroom rethink village": "SYR-VIL-SCH",
                "classroom rethink village, Rethink Village": "SYR-VIL-SCH",
                "CLASSROOM !!!, Rethink Village": "SYR-VIL-SCH",
                "CLASSROOM !!!": "SYR-VIL-SCH"
            })

        # Rename standard columns
        df = df.rename(columns={
            "Bank Ref": "Donation ID",
            "Comments": "Comments",
            "Billing Address": "Billing Address",
            "Postcode": "Billing Zip",
        })

        if "Amount" in df.columns:
            df["Total Online Donations Net Amount in Settled Currency"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)
            df["Total Online Donation Gross Amount in Settled Currency"] = df["Total Online Donations Net Amount in Settled Currency"]
            df["Donation Amount in Project Currency (May be approx.)"] = df["Total Online Donations Net Amount in Settled Currency"]
            df["Donation Amount (in Donation Currency)"] = df["Total Online Donations Net Amount in Settled Currency"]

        if "Date of collection" in df.columns:
            parsed_dates = pd.to_datetime(df["Date of collection"], dayfirst=True, errors="coerce")
            df["Created Date (UTC)"] = parsed_dates
            df["Created Time (UTC)"] = "00:00:00"
        elif "Due" in df.columns:
            parsed_dates = pd.to_datetime(df["Due"], dayfirst=True, errors="coerce")
            df["Created Date (UTC)"] = parsed_dates
            df["Created Time (UTC)"] = "00:00:00"

        if "Type" in df.columns:
            df["Payment Frequency"] = df["Type"].apply(lambda t: "Recurring Payment" if str(t).lower() in ["regular", "recurring"] else "One-Time Payment")
        else:
            df["Payment Frequency"] = "Recurring Payment"

        df["Platform"] = "Paysuite"
        df["Payment Type"] = "Direct Debit"
        df["Offline or online donation"] = "online"
        
        df["Campaign Name"] = df["Donation ID"]
        df["Community Name"] = "Paysuite"
        
        f_name = df.get("First Name", pd.Series("", index=df.index)).fillna("").astype(str)
        l_name = df.get("Last Name", pd.Series("", index=df.index)).fillna("").astype(str)
        df["Display Name"] = (f_name + " " + l_name).str.strip()

        # Try to look up existing donor details (Email, Billing Address, Billing Zip) and classifications from database by Bank Ref
        existing_map = {}
        df_existing = load_data()
        if not df_existing.empty and "Donation ID" in df_existing.columns:
            ps_existing = df_existing[df_existing.get("Platform", pd.Series("", index=df_existing.index)).astype(str).str.lower() == "paysuite"]
            if not ps_existing.empty:
                mapping_df = ps_existing.drop_duplicates(subset=["Donation ID"], keep="last")
                for _, r in mapping_df.iterrows():
                    existing_map[str(r["Donation ID"]).strip().lower()] = {
                        "Email": r.get("Email") if pd.notna(r.get("Email")) else None,
                        "Billing Address": r.get("Billing Address") if pd.notna(r.get("Billing Address")) else None,
                        "Billing Zip": r.get("Billing Zip") if pd.notna(r.get("Billing Zip")) else None,
                        "Heading": r.get("Heading") if pd.notna(r.get("Heading")) else "Unassigned",
                        "Sub-Heading": r.get("Sub-Heading") if pd.notna(r.get("Sub-Heading")) else "Unassigned",
                        "Country": r.get("Country") if pd.notna(r.get("Country")) else "Unassigned",
                        "Code": r.get("Code") if pd.notna(r.get("Code")) else "Unassigned",
                        "Zakat Eligibility": r.get("Zakat Eligibility") if pd.notna(r.get("Zakat Eligibility")) else "Unassigned",
                    }

        # Apply or initialize classifications database for Paysuite
        init_classification_db()
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
        try:
            db_matrix = pd.read_sql_query("SELECT * FROM paysuite_classifications", conn)
            rule_dict = {str(r["campaign_name"]).strip().lower(): r for _, r in db_matrix.iterrows()}
        except Exception:
            rule_dict = {}
        finally:
            conn.close()

        for col in ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility"]:
            if col not in df.columns:
                df[col] = "Unassigned"

        bank_ref_lower = df["Donation ID"].astype(str).str.strip().str.lower()

        # Vectorized classification lookup from paysuite_classifications (< 5ms)
        for f in ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility"]:
            db_f = f.lower().replace("-", "_").replace(" ", "_")
            mapped_vals = bank_ref_lower.map(lambda b: rule_dict.get(b, {}).get(db_f))
            valid_mask = mapped_vals.notna() & (~mapped_vals.astype(str).str.lower().isin(["", "nan", "none", "unassigned"]))
            if valid_mask.any():
                df.loc[valid_mask, f] = mapped_vals[valid_mask]

        # Seed new Paysuite bank refs into paysuite_classifications database in 1 vectorized pass
        avail_ps_cols = [c for c in ["Donation ID", "Code", "Customer Ref"] if c in df.columns]
        unique_refs = df[avail_ps_cols].drop_duplicates(subset=["Donation ID"]) if "Donation ID" in df.columns else pd.DataFrame()
        new_rules = []
        for _, r in unique_refs.iterrows():
            b_ref = str(r.get("Donation ID", "")).strip()
            b_ref_l = b_ref.lower()
            if b_ref and b_ref_l not in ["nan", "none", "n/a", ""] and b_ref_l not in rule_dict:
                c_code = str(r.get("Code") or "Unassigned").strip()
                if not c_code or c_code.lower() in ["nan", "none"]:
                    c_code = "Unassigned"
                if "hafiz" in str(r.get("Customer Ref") or "").lower():
                    c_code = "SYR-SPN-HUF"
                new_rules.append((b_ref, c_code, "Paysuite", "Unassigned", "Unassigned", "Unassigned", "Unassigned", 0))

        if new_rules:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
            try:
                conn.executemany("""
                    INSERT OR IGNORE INTO paysuite_classifications (campaign_name, code, community_name, heading, sub_heading, country, zakat_eligibility, is_primary)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, new_rules)
                conn.commit()
            except Exception as e:
                print(f"Error seeding new paysuite rules: {e}")
            finally:
                conn.close()

    elif is_rethink_website:
        df["Platform"] = "Rethink Website"
        df["Payment Type"] = "Card / Stripe"
        df["Offline or online donation"] = "online"

        col_map = {
            "Reference": "Donation ID",
            "Donor First Name": "First Name",
            "Donor Last Name": "Last Name",
            "Donor Email": "Email",
            "Donor Phone": "Phone Number",
            "Donor Address Street 1": "Billing Address",
            "Donor Address Street 2": "Billing Address 2",
            "Donor Address City": "Billing City",
            "Donor Address Region": "Billing State",
            "Donor Address Postal Code": "Billing Zip",
            "Project Name": "Campaign Name",
            "Appeal Name": "Community Name",
            "Location": "Country",
            "Fees": "fee_amount",
            "Gross Amount": "Total Online Donation Gross Amount in Settled Currency",
            "Words of Support": "comment",
            "Processor": "gateway"
        }
        df.rename(columns=col_map, inplace=True)

        if "Amount" in df.columns:
            df["Total Online Donations Net Amount in Settled Currency"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)
            df["Donation Amount in Project Currency (May be approx.)"] = df["Total Online Donations Net Amount in Settled Currency"]
            df["Donation Amount (in Donation Currency)"] = df["Total Online Donations Net Amount in Settled Currency"]

        if "Currency" in df.columns:
            df["Donation Currency (DC)"] = df["Currency"]
            df["Settlement Currency"] = df["Currency"]

        if "Subscription Reference" in df.columns:
            df["Payment Frequency"] = df["Subscription Reference"].apply(
                lambda s: "Recurring Payment" if pd.notna(s) and str(s).strip() not in ["", "nan", "None"] else "One-Time Payment"
            )
        else:
            df["Payment Frequency"] = "One-Time Payment"

        if "Gift Aid?" in df.columns:
            df["Gift Aid (yes or no)"] = df["Gift Aid?"].apply(
                lambda g: "Yes" if str(g).strip() in ["1", "true", "yes"] else "No"
            )

        if "Anonymous?" in df.columns:
            df["Anonymous or Public"] = df["Anonymous?"].apply(
                lambda a: "Anonymous" if str(a).strip() in ["1", "true", "yes"] else "Public"
            )

        if "Zakat Status" in df.columns and "Zakat Eligibility" not in df.columns:
            df["Zakat Eligibility"] = df["Zakat Status"].apply(
                lambda z: "Zakat" if str(z).strip().lower() == "zakat" else "Non-Zakat"
            )

        if "Donor Address Country Code" in df.columns:
            def safe_country(c):
                if pd.isna(c) or str(c).strip() in ["", "nan", "None", "NaN"]:
                    return "Unknown"
                c_str = str(c).strip()
                return COUNTRY_ISO_MAP.get(c_str.upper(), c_str)

            df["Billing Country"] = df["Donor Address Country Code"].apply(safe_country)

        if "Created At" in df.columns:
            parsed = pd.to_datetime(df["Created At"], errors="coerce")
            df["Created Date (UTC)"] = parsed.dt.date
            df["Created Time (UTC)"] = parsed.dt.time.astype(str)
        elif "Confirmed At" in df.columns:
            parsed = pd.to_datetime(df["Confirmed At"], errors="coerce")
            df["Created Date (UTC)"] = parsed.dt.date
            df["Created Time (UTC)"] = parsed.dt.time.astype(str)

        # Apply or initialize classifications database for Rethink Website
        init_classification_db()
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
        try:
            db_matrix = pd.read_sql_query("SELECT * FROM rethink_website_classifications", conn)
            rule_dict = {str(r["campaign_name"]).strip().lower(): r for _, r in db_matrix.iterrows()}
        except Exception:
            rule_dict = {}
        finally:
            conn.close()

        for col in ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility"]:
            if col not in df.columns:
                df[col] = "Unassigned"

        cname_series = df["Campaign Name"].astype(str).str.strip()
        cname_lower = cname_series.str.lower()

        # Vectorized classification rule mapping for Rethink Website (< 5ms)
        for f in ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility"]:
            db_f = f.lower().replace("-", "_").replace(" ", "_")
            mapped_vals = cname_lower.map(lambda c: rule_dict.get(c, {}).get(db_f))
            valid_mask = mapped_vals.notna() & (~mapped_vals.astype(str).str.lower().isin(["", "nan", "none", "unassigned"]))
            if valid_mask.any():
                df.loc[valid_mask, f] = mapped_vals[valid_mask]

        # Seed new website projects into rethink_website_classifications
        avail_ws_cols = [c for c in ["Campaign Name", "Community Name", "Country", "Zakat Eligibility", "Code"] if c in df.columns]
        unique_cnames = df[avail_ws_cols].drop_duplicates(subset=["Campaign Name"]) if "Campaign Name" in df.columns else pd.DataFrame()
        new_rules = []
        for _, r in unique_cnames.iterrows():
            cn = str(r.get("Campaign Name", "")).strip()
            cn_l = cn.lower()
            if cn and cn_l not in ["nan", "none", "n/a", ""] and cn_l not in rule_dict:
                cm = str(r.get("Community Name") or "N/A").strip()
                ct = str(r.get("Country") or "Unassigned").strip()
                cd = str(r.get("Code") or "Unassigned").strip()
                zk = str(r.get("Zakat Eligibility") or "Unassigned").strip()
                new_rules.append((cn, cd, cm, "Unassigned", "Unassigned", ct, zk, 0))

        if new_rules:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
            try:
                conn.executemany("""
                    INSERT OR IGNORE INTO rethink_website_classifications (campaign_name, code, community_name, heading, sub_heading, country, zakat_eligibility, is_primary)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, new_rules)
                conn.commit()
            except Exception as e:
                print(f"Error seeding new website rules: {e}")
            finally:
                conn.close()

    elif is_givebright:
        df["Platform"] = "GiveBright"
        gb_aliases = {
            "id": "Donation ID",
            "_id": "Donation ID",
            "donation_id": "Donation ID",
            "donation id": "Donation ID",
            "transaction_id": "Donation ID",
            "transaction id": "Donation ID",
            "reference": "Donation ID",
            "campaign": "Campaign Name",
            "campaign_name": "Campaign Name",
            "campaign name": "Campaign Name",
            "fundraiser_by": "Community Name",
            "fundraiser by": "Community Name",
            "fundraiser_name": "fundraiser_name",
            "fundraiser": "fundraiser_name",
            "campaign_url": "Campaign URL",
            "fundraiser_url": "Fundraiser URL",
            "url": "Campaign URL",
            "amount": "Donation Amount in Project Currency (May be approx.)",
            "gross_amount": "Total Online Donation Gross Amount in Settled Currency",
            "gross amount": "Total Online Donation Gross Amount in Settled Currency",
            "net_amount": "Total Online Donations Net Amount in Settled Currency",
            "net amount": "Total Online Donations Net Amount in Settled Currency",
            "fee": "fee_amount",
            "fees": "fee_amount",
            "fee_amount": "fee_amount",
            "currency": "Donation Currency (DC)",
            "currency_code": "Donation Currency (DC)",
            "currency code": "Donation Currency (DC)",
            "is_anonymous": "Anonymous or Public",
            "anonymous": "Anonymous or Public",
            "anonymous?": "Anonymous or Public",
            "is_giftaid": "Gift Aid (yes or no)",
            "giftaid": "Gift Aid (yes or no)",
            "gift_aid": "Gift Aid (yes or no)",
            "gift aid": "Gift Aid (yes or no)",
            "gift aid?": "Gift Aid (yes or no)",
            "country": "Billing Country",
            "billing_country": "Billing Country",
            "billing country": "Billing Country",
            "first_name": "First Name",
            "first name": "First Name",
            "firstname": "First Name",
            "last_name": "Last Name",
            "last name": "Last Name",
            "lastname": "Last Name",
            "surname": "Last Name",
            "email": "Email",
            "email_address": "Email",
            "email address": "Email",
            "phone": "Phone Number",
            "phone_number": "Phone Number",
            "impact_name": "Giving Level Title",
            "impact_amount": "Giving Level Amount",
            "giving_level": "Giving Level Title",
            "giving_levels": "Giving Level Title",
            "giving level": "Giving Level Title",
            "giving_level_title": "Giving Level Title",
            "giving level title": "Giving Level Title",
            "variant": "Giving Level Title",
            "option": "Giving Level Title",
            "optin": "Marketing Consent",
            "opt_in": "Marketing Consent",
            "opt-in": "Marketing Consent",
            "marketing_consent": "Marketing Consent",
            "frequency": "Payment Frequency",
            "status": "Status"
        }
        rename_map = {}
        for c in df.columns:
            c_norm = str(c).strip().lower()
            if c_norm in gb_aliases and gb_aliases[c_norm] not in df.columns and gb_aliases[c_norm] not in rename_map.values():
                rename_map[c] = gb_aliases[c_norm]
        if rename_map:
            df.rename(columns=rename_map, inplace=True)

        if "Giving Level Title" not in df.columns:
            for cand in ["impact_name", "giving_level", "giving_levels", "giving_level_title", "variant", "option"]:
                if cand in df.columns:
                    df["Giving Level Title"] = df[cand]
                    break

        if "Donation ID" not in df.columns:
            for cand in ["_id", "id", "ID", "donation_id", "Customer Ref"]:
                if cand in df.columns:
                    df["Donation ID"] = df[cand].astype(str)
                    break

        # Standardize Amounts
        if "Total Online Donation Gross Amount in Settled Currency" not in df.columns:
            if "Donation Amount in Project Currency (May be approx.)" in df.columns:
                df["Total Online Donation Gross Amount in Settled Currency"] = pd.to_numeric(df["Donation Amount in Project Currency (May be approx.)"], errors="coerce").fillna(0.0)
            elif "Amount" in df.columns:
                df["Total Online Donation Gross Amount in Settled Currency"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)
                df["Donation Amount in Project Currency (May be approx.)"] = df["Total Online Donation Gross Amount in Settled Currency"]

        if "Total Online Donations Net Amount in Settled Currency" not in df.columns:
            if "fee_amount" in df.columns:
                fees = pd.to_numeric(df["fee_amount"], errors="coerce").fillna(0.0)
                gross = pd.to_numeric(df.get("Total Online Donation Gross Amount in Settled Currency", 0.0), errors="coerce").fillna(0.0)
                df["Total Online Donations Net Amount in Settled Currency"] = gross - fees
            else:
                df["Total Online Donations Net Amount in Settled Currency"] = df.get("Total Online Donation Gross Amount in Settled Currency", 0.0)

        if "Donation Amount (in Donation Currency)" not in df.columns and "Total Online Donation Gross Amount in Settled Currency" in df.columns:
            df["Donation Amount (in Donation Currency)"] = df["Total Online Donation Gross Amount in Settled Currency"]

        # Settlement Currency
        if "Settlement Currency" not in df.columns:
            if "Donation Currency (DC)" in df.columns:
                df["Settlement Currency"] = df["Donation Currency (DC)"]
            else:
                df["Settlement Currency"] = "GBP"

        if "subscription_id" in df.columns:
            df["Payment Frequency"] = df["subscription_id"].apply(
                lambda s: "Recurring Payment" if pd.notna(s) and str(s).strip() not in ["", "nan", "None"] else "One-Time Payment"
            )

        if "Anonymous or Public" in df.columns:
            df["Anonymous or Public"] = df["Anonymous or Public"].apply(
                lambda a: "Anonymous" if pd.notna(a) and str(a).lower() in ["true", "1", "yes"] else "Public"
            )

        if "Billing Country" in df.columns:
            def safe_country(c):
                if pd.isna(c) or str(c).strip() in ["", "nan", "None", "NaN"]:
                    return "Unknown"
                c_str = str(c).strip()
                return COUNTRY_ISO_MAP.get(c_str.upper(), c_str)

            df["Billing Country"] = df["Billing Country"].apply(safe_country)

        # Dates resolution
        date_col = None
        for cand in ["created_at", "Created At", "created at", "Date", "date", "Created Date", "Timestamp"]:
            if cand in df.columns:
                date_col = cand
                break
        if date_col and "Created Date (UTC)" not in df.columns:
            c_at_str = df[date_col].fillna("").astype(str).str.strip()
            slash_m = c_at_str.str.extract(r"^(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?")
            has_slash = slash_m[0].notna() & slash_m[1].notna() & slash_m[2].notna()
            if has_slash.any():
                df.loc[has_slash, "Created Date (UTC)"] = (
                    slash_m.loc[has_slash, 2] + "-" + slash_m.loc[has_slash, 1].str.zfill(2) + "-" + slash_m.loc[has_slash, 0].str.zfill(2)
                )
                time_h = slash_m.loc[has_slash, 3].fillna("00").str.zfill(2)
                time_m = slash_m.loc[has_slash, 4].fillna("00").str.zfill(2)
                time_s = slash_m.loc[has_slash, 5].fillna("00").str.zfill(2)
                df.loc[has_slash, "Created Time (UTC)"] = time_h + ":" + time_m + ":" + time_s
            non_slash = ~has_slash
            if non_slash.any():
                parsed = pd.to_datetime(df.loc[non_slash, date_col], errors="coerce", dayfirst=True)
                df.loc[non_slash, "Created Date (UTC)"] = parsed.dt.date.astype(str)
                df.loc[non_slash, "Created Time (UTC)"] = parsed.dt.time.astype(str)

        # Vectorized classification rule mapping for GiveBright with dual-tier (campaign + giving_level) lookup
        init_classification_db()
        conn = get_db_connection(timeout=60.0)
        try:
            db_matrix = pd.read_sql_query("SELECT * FROM givebright_classifications WHERE LOWER(company_id) = ?", conn, params=(target_cid,))
            rule_dict_gl = {}
            rule_dict_camp = {}
            for _, r in db_matrix.iterrows():
                c_k = str(r["campaign_name"]).strip().lower()
                gl_k = str(r.get("giving_level") or "").strip().lower()
                if gl_k and gl_k not in ["nan", "none", "n/a", "unassigned", ""]:
                    rule_dict_gl[(c_k, gl_k)] = r.to_dict()
                else:
                    if c_k not in rule_dict_camp or r.get("is_primary") in [1, True, "1", "true", "True"]:
                        rule_dict_camp[c_k] = r.to_dict()
        except Exception:
            rule_dict_gl = {}
            rule_dict_camp = {}
        finally:
            conn.close()

        for col in ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility", "Department", "Office", "Portfolio", "Programme Fund", "Fund Code"]:
            if col not in df.columns:
                df[col] = "Unassigned"

        if "Campaign Name" in df.columns:
            cname_series = df["Campaign Name"].astype(str).str.strip().str.lower()
            gl_series = df["Giving Level Title"].fillna("").astype(str).str.strip().str.lower() if "Giving Level Title" in df.columns else pd.Series("", index=df.index)

            for f in ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility", "Department", "Office", "Portfolio", "Programme Fund", "Fund Code"]:
                db_f = f.lower().replace("-", "_").replace(" ", "_")
                mapped_gl = [rule_dict_gl.get((c, g), {}).get(db_f) if g else None for c, g in zip(cname_series, gl_series)]
                mapped_camp = cname_series.map(lambda c: rule_dict_camp.get(c, {}).get(db_f))
                mapped_vals = pd.Series(mapped_gl, index=df.index).combine_first(mapped_camp)
                valid_mask = mapped_vals.notna() & (~mapped_vals.astype(str).str.lower().isin(["", "nan", "none", "unassigned"]))
                if valid_mask.any():
                    df.loc[valid_mask, f] = mapped_vals[valid_mask]

            # Seed new GiveBright campaigns into platform_campaign_mappings database with giving level support
            c_curl_map = {}
            if "Campaign URL" in df.columns:
                for c_u, u_val in zip(df["Campaign Name"], df["Campaign URL"]):
                    if str(u_val).strip() and str(c_u).strip().lower() not in c_curl_map:
                        c_curl_map[str(c_u).strip().lower()] = str(u_val).strip()

            unique_combos = df[["Campaign Name", "Giving Level Title"]].drop_duplicates() if "Giving Level Title" in df.columns else df[["Campaign Name"]].drop_duplicates()
            new_rules = []
            for _, r in unique_combos.iterrows():
                cn = str(r["Campaign Name"]).strip()
                cn_l = cn.lower()
                gl = str(r.get("Giving Level Title") or "").strip() if "Giving Level Title" in r else ""
                gl_l = gl.lower()
                if not cn or cn_l in ["nan", "none", "n/a", ""]:
                    continue

                curl = c_curl_map.get(cn_l, "")
                if gl_l and gl_l not in ["nan", "none", "n/a", ""]:
                    if (cn_l, gl_l) not in rule_dict_gl:
                        new_rules.append((target_cid, "givebright", cn, gl, "Unassigned", curl, 0))
                else:
                    if cn_l not in rule_dict_camp:
                        new_rules.append((target_cid, "givebright", cn, "", "Unassigned", curl, 1))

            if new_rules:
                conn = get_db_connection(timeout=60.0)
                try:
                    conn.executemany("""
                        INSERT OR IGNORE INTO platform_campaign_mappings (company_id, platform, campaign_name, giving_level, code, campaign_url, is_primary)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, new_rules)
                    conn.commit()
                except Exception as e:
                    print(f"Error seeding new givebright rules: {e}")
                finally:
                    conn.close()

    elif is_madinah:
        df["Platform"] = "Madinah"
        col_map = {
            "Invoice ID": "Donation ID",
            "Campaign": "Campaign Name",
            "Name": "Display Name",
            "Email": "Email",
            "Currency Code": "Donation Currency (DC)",
            "Amount": "Donation Amount (in Donation Currency)",
            "Amount (USD)": "Total Online Donation Gross Amount in Settled Currency",
            "Net Amount (USD)": "Total Online Donations Net Amount in Settled Currency",
            "Comment": "Comments",
            "Giving Levels": "Giving Level Title",
            "Status": "Status",
        }
        df.rename(columns=col_map, inplace=True)
        df["Settlement Currency"] = "USD"

        # Processing Fees = Stripe Fees (USD) + Processing Fees (USD)
        sf = pd.to_numeric(df.get("Stripe Fees (USD)", 0.0), errors="coerce").fillna(0.0)
        pf = pd.to_numeric(df.get("Processing Fees (USD)", 0.0), errors="coerce").fillna(0.0)
        df["Total Processing Fees Paid by CC In Settled Currency"] = sf + pf

        # First Name / Last Name split from Display Name
        if "Display Name" in df.columns:
            names = df["Display Name"].fillna("").astype(str).str.strip()
            df["First Name"] = names.apply(lambda n: n.split(" ")[0] if n else "")
            df["Last Name"] = names.apply(lambda n: " ".join(n.split(" ")[1:]) if len(n.split(" ")) > 1 else "")

        # UTM / Referral Source
        utm = df.get("UTM Source", pd.Series("", index=df.index)).fillna("").astype(str)
        ref = df.get("Referral Token", pd.Series("", index=df.index)).fillna("").astype(str)
        df["UTM / Referral Source"] = utm.where(utm != "", ref)

        # Payment Frequency from Subscription Type
        if "Subscription Type" in df.columns:
            df["Payment Frequency"] = df["Subscription Type"].apply(
                lambda s: "Recurring Payment" if pd.notna(s) and str(s).strip().lower() in ["recurring", "subscription", "monthly"] else "One-Time Payment"
            )

        # Parse Date
        if "Date" in df.columns:
            parsed = pd.to_datetime(df["Date"], errors="coerce")
            df["Created Date (UTC)"] = parsed.dt.date.astype(str)
            df["Created Time (UTC)"] = parsed.dt.time.astype(str)
            df["_parsed_date"] = parsed.dt.date.astype(str)

        # Vectorized classification rule mapping for Madinah (< 5ms)
        init_classification_db()
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
        try:
            db_matrix = pd.read_sql_query(
                "SELECT * FROM madinah_classifications WHERE LOWER(company_id) = ?", conn, params=(target_cid,)
            )
            rule_dict = {str(r["campaign_name"]).strip().lower(): r for _, r in db_matrix.iterrows()}
        except Exception:
            rule_dict = {}
        finally:
            conn.close()

        for col in ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility", "Department", "Office", "Portfolio", "Programme Fund", "Fund Code"]:
            if col not in df.columns:
                df[col] = "Unassigned"

        if "Campaign Name" in df.columns:
            cname_series = df["Campaign Name"].astype(str).str.strip()
            cname_lower = cname_series.str.lower()

            for f in ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility", "Department", "Office", "Portfolio", "Programme Fund", "Fund Code"]:
                db_f = f.lower().replace("-", "_").replace(" ", "_")
                mapped_vals = cname_lower.map(lambda c: rule_dict.get(c, {}).get(db_f))
                valid_mask = mapped_vals.notna() & (~mapped_vals.astype(str).str.lower().isin(["", "nan", "none", "unassigned"]))
                if valid_mask.any():
                    df.loc[valid_mask, f] = mapped_vals[valid_mask]

            # Seed new Madinah campaigns into platform_campaign_mappings in 1 vectorized pass
            unique_cnames = df[["Campaign Name"]].drop_duplicates(subset=["Campaign Name"])
            new_rules = []
            for _, r in unique_cnames.iterrows():
                cn = str(r["Campaign Name"]).strip()
                cn_l = cn.lower()
                if cn and cn_l not in ["nan", "none", "n/a", ""] and cn_l not in rule_dict:
                    curl = str(r.get("Campaign URL") or "").strip() if "Campaign URL" in r else ""
                    new_rules.append((target_cid, "madinah", cn, "Unassigned", curl, 1))

            if new_rules:
                conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
                try:
                    conn.executemany("""
                        INSERT OR IGNORE INTO platform_campaign_mappings (company_id, platform, campaign_name, code, campaign_url, is_primary)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, new_rules)
                    conn.commit()
                except Exception as e:
                    print(f"Error seeding new madinah rules: {e}")
                finally:
                    conn.close()

    else:
        has_payout_cols = ("Settlement Gross (SC)" in df.columns or "Transfer Amount (SC)" in df.columns)
        has_donation_cols = ("Donation ID" in df.columns or "Total Online Donation Gross Amount in Settled Currency" in df.columns or "First Name" in df.columns)
        is_payout_file = (has_payout_cols and not has_donation_cols) or str(platform).lower() in ["payout", "launchgood payout", "payouts"]
        if is_payout_file:
            df["Platform"] = "LaunchGood Payout"
            if "Code" in df.columns and "Giving Level Fund Code" in df.columns:
                df.drop(columns=["Giving Level Fund Code"], inplace=True, errors="ignore")
            df.rename(columns={
                "Project Name": "Campaign Name",
                "Settlement Gross (SC)": "Total Online Donation Gross Amount in Settled Currency",
                "Settlement Processing Fees (SC)": "Total Processing Fees Paid by CC In Settled Currency",
                "Transfer Amount (SC)": "Total Online Donations Net Amount in Settled Currency",
                "Transfer ID": "Transfer ID",
                "Type": "Type",
                "Gift Aid": "Gift Aid (yes or no)",
                "Giving Level Fund Code": "Code"
            }, inplace=True)
            df = deduplicate_dataframe_columns(df)

            if "Created Date" in df.columns:
                parsed_d = pd.to_datetime(df["Created Date"], errors="coerce")
                df["Created Date (UTC)"] = parsed_d.dt.date.astype(str)
            if "Created Time" in df.columns:
                df["Created Time (UTC)"] = df["Created Time"].astype(str)

            df["Payout Settled"] = "Yes"

            # Synthetic Donation ID for non-donation summary rows
            if "Donation ID" in df.columns:
                df["Donation ID"] = df["Donation ID"].fillna("").astype(str).str.strip()
                invalid_id_mask = df["Donation ID"].isin(["", "nan", "none", "n/a", "<na>", "0", "0.0"])
                if invalid_id_mask.any():
                    tid_s = df.get("Transfer ID", pd.Series("34579", index=df.index)).fillna("34579").astype(str).str.replace(".0", "", regex=False)
                    synthetic_ids = ["PAYOUT-" + str(tid_s.iloc[idx]) + "-" + str(idx + 1) for idx, is_invalid in enumerate(invalid_id_mask) if is_invalid]
                    df.loc[invalid_id_mask, "Donation ID"] = synthetic_ids

            # Direct Donation ID Classification Mapping from existing database records (< 10ms vectorized)
            try:
                df_existing = load_data()
                if df_existing is not None and not df_existing.empty and "Donation ID" in df_existing.columns:
                    valid_existing = df_existing.dropna(subset=["Donation ID"])
                    if not valid_existing.empty:
                        did_series = df["Donation ID"].astype(str).str.strip().str.lower()
                        existing_dedup = valid_existing.drop_duplicates(subset=["Donation ID"], keep="last").copy()
                        existing_dedup["_did_key"] = existing_dedup["Donation ID"].astype(str).str.strip().str.lower()
                        existing_indexed = existing_dedup.set_index("_did_key")
                        
                        for f in ["Campaign Name", "Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility"]:
                            if f in existing_indexed.columns:
                                col_map = existing_indexed[f].dropna().to_dict()
                                if f not in df.columns:
                                    df[f] = "Unassigned"
                                mapped = did_series.map(col_map)
                                valid_m = mapped.notna() & (~mapped.astype(str).str.lower().isin(["", "nan", "none", "unassigned"]))
                                if valid_m.any():
                                    df.loc[valid_m, f] = mapped[valid_m]
            except Exception as ex:
                print(f"[Notice] Donation ID classification mapping notice: {ex}")
        else:
            df["Platform"] = "LaunchGood"
            df["Payout Settled"] = "No"

    if "Payout Settled" not in df.columns:
        df["Payout Settled"] = "No"

    if "Total Online Donations Net Amount in Settled Currency" in df.columns and "Donation Amount in Project Currency (May be approx.)" in df.columns:
        df["Total Online Donations Net Amount in Settled Currency"] = df["Total Online Donations Net Amount in Settled Currency"].fillna(df["Donation Amount in Project Currency (May be approx.)"])
    elif "Total Online Donations Net Amount in Settled Currency" not in df.columns and "Donation Amount in Project Currency (May be approx.)" in df.columns:
        df["Total Online Donations Net Amount in Settled Currency"] = df["Donation Amount in Project Currency (May be approx.)"]

    col_amount = "Total Online Donations Net Amount in Settled Currency"
    if col_amount not in df.columns:
        col_amount = "Donation Amount in Project Currency (May be approx.)"
    if col_amount not in df.columns:
        col_amount = "Donation Amount (in Donation Currency)"

    GENERIC_DONOR_NAMES = {
        'anonymous', 'anonymous kind soul', 'anonymous donor', 'kind soul', 
        'donation boost', 'unnamed donor', 'nan', 'none', 'null', '', 'unassigned',
        'mr', 'mrs', 'miss', 'dr', 'ms', 'm', 's', 'a', 'n', 'guest user'
    }

    DONOR_TITLE_PREFIXES = {
        'dr', 'dr.', 'mr', 'mr.', 'mrs', 'mrs.', 'ms', 'ms.', 'miss', 
        'prof', 'prof.', 'professor', 'sheikh', 'shaykh', 'shaykha', 'sheikha',
        'haji', 'hajji', 'hajjah', 'haja', 'ustadh', 'ustad', 'ustadha',
        'imam', 'mufti', 'brother', 'sister', 'dr/mr', 'dr/mrs', 'lord', 'lady', 'sir'
    }

    def _normalize_human_name(name_str):
        if pd.isna(name_str):
            return None
        raw = str(name_str).strip()
        if not raw or raw.lower() in GENERIC_DONOR_NAMES:
            return None
        words = raw.split()
        while words and words[0].lower().rstrip('.') in DONOR_TITLE_PREFIXES:
            words.pop(0)
        cleaned = ' '.join(words).strip().lower()
        cleaned = re.sub(r'[^a-z\s]', '', cleaned).strip()
        cleaned = re.sub(r'\s+', ' ', cleaned)
        if cleaned in GENERIC_DONOR_NAMES or len(cleaned) < 3 or ' ' not in cleaned:
            return None
        return cleaned

    def _normalize_phone_number(p_val):
        if pd.isna(p_val):
            return None
        digits = re.sub(r'[^\d]', '', str(p_val).strip())
        digits = re.sub(r'^44', '', digits).lstrip('0')
        if 7 <= len(digits) <= 15:
            return digits
        return None

    # 1. Multi-field Email Resolution (Primary Email, Giving Level Email, Tax Receipt Email)
    email_series_list = []
    for em_col in ["Email", "Giving Level Email", "Email (for tax receipt)"]:
        if em_col in df.columns:
            s_em = df[em_col].fillna("").astype(str).str.strip().str.lower()
            clean_s = s_em.where(~s_em.isin(['nan', 'none', '', 'unassigned', 'null', 'n/a', '<na>']) & s_em.str.contains('@', na=False), None)
            email_series_list.append(clean_s)

    if email_series_list:
        primary_email = email_series_list[0]
        for next_em in email_series_list[1:]:
            primary_email = primary_email.combine_first(next_em)
    else:
        primary_email = pd.Series(None, index=df.index, dtype=object)

    df['email_clean'] = primary_email

    # 2. Normalized Name Extraction (First + Last, and Billing Name)
    fn_s = df['First Name'].fillna("").astype(str).str.strip() if 'First Name' in df.columns else pd.Series("", index=df.index)
    ln_s = df['Last Name'].fillna("").astype(str).str.strip() if 'Last Name' in df.columns else pd.Series("", index=df.index)
    raw_full_name = (fn_s + " " + ln_s).str.strip()
    df['full_name_clean'] = raw_full_name.apply(_normalize_human_name)

    bname_col = df['Billing Name'] if 'Billing Name' in df.columns else pd.Series("", index=df.index, dtype=str)
    df['bname_clean'] = bname_col.apply(_normalize_human_name)

    # 3. Clean Phone Numbers
    phone_series_list = []
    for p_col in ["Phone Number", "Phone", "phone_number", "Home phone number", "Contact Phone"]:
        if p_col in df.columns:
            p_clean = df[p_col].apply(_normalize_phone_number)
            phone_series_list.append(p_clean)
    
    if phone_series_list:
        primary_phone = phone_series_list[0]
        for next_p in phone_series_list[1:]:
            primary_phone = primary_phone.combine_first(next_p)
    else:
        primary_phone = pd.Series(None, index=df.index, dtype=object)
    df['phone_clean'] = primary_phone

    # 4. Cross-Attribute Mapping to Email (Multi-signal relation)
    # Name -> Email map
    valid_name_email = pd.DataFrame({'name': df['full_name_clean'], 'email': df['email_clean']}).dropna()
    name_to_email_map = valid_name_email.groupby('name')['email'].first() if not valid_name_email.empty else pd.Series(dtype=str)

    # Billing Name -> Email map
    valid_bname_email = pd.DataFrame({'bname': df['bname_clean'], 'email': df['email_clean']}).dropna()
    bname_to_email_map = valid_bname_email.groupby('bname')['email'].first() if not valid_bname_email.empty else pd.Series(dtype=str)

    # Phone -> Email map
    valid_phone_email = pd.DataFrame({'phone': df['phone_clean'], 'email': df['email_clean']}).dropna()
    phone_to_email_map = valid_phone_email.groupby('phone')['email'].first() if not valid_phone_email.empty else pd.Series(dtype=str)

    mapped_email_from_name = df['full_name_clean'].map(name_to_email_map) if not name_to_email_map.empty else pd.Series(None, index=df.index)
    mapped_email_from_billing = df['bname_clean'].map(bname_to_email_map) if not bname_to_email_map.empty else pd.Series(None, index=df.index)
    mapped_email_from_phone = df['phone_clean'].map(phone_to_email_map) if not phone_to_email_map.empty else pd.Series(None, index=df.index)

    did_series = df['Donation ID'].astype(str) if 'Donation ID' in df.columns else pd.Series(range(len(df)), index=df.index).astype(str)

    # 5. Canonical Donor ID Assignment (Safe & Guaranteed Non-Null)
    phone_id_series = df['phone_clean'].apply(lambda p: f"phone:{p}" if pd.notna(p) and p else None)
    name_id_series = df['full_name_clean'].apply(lambda n: f"name:{n}" if pd.notna(n) and n else None)
    billing_id_series = df['bname_clean'].apply(lambda b: f"name:{b}" if pd.notna(b) and b else None)

    df['Donor ID'] = df['email_clean'] \
        .combine_first(mapped_email_from_phone) \
        .combine_first(mapped_email_from_name) \
        .combine_first(mapped_email_from_billing) \
        .combine_first(phone_id_series) \
        .combine_first(name_id_series) \
        .combine_first(billing_id_series) \
        .combine_first(did_series)

    # Ensure no NaN, empty string, or literal 'nan' survives in Donor ID
    bad_did_mask = df['Donor ID'].isna() | df['Donor ID'].astype(str).str.strip().str.lower().isin(['nan', 'none', '', 'null', '<na>', 'unassigned'])
    if bad_did_mask.any():
        df.loc[bad_did_mask, 'Donor ID'] = did_series.loc[bad_did_mask]

    df.drop(columns=['email_clean', 'full_name_clean', 'bname_clean', 'phone_clean'], inplace=True, errors='ignore')

    if col_amount in df.columns:
        df[col_amount] = pd.to_numeric(df[col_amount], errors='coerce').fillna(0)
        if 'Status' in df.columns:
            succ_mask = ~df['Status'].astype(str).str.lower().isin(['failed', 'cancelled', 'canceled'])
            valid_amounts = df[col_amount].where(succ_mask, 0.0)
            ltv_map = valid_amounts.groupby(df['Donor ID']).sum()
        else:
            ltv_map = df.groupby('Donor ID')[col_amount].sum()
        df['Total LTV'] = df['Donor ID'].map(ltv_map).fillna(0.0)
        df['Lifetime Donor Classification'] = df['Total LTV'].apply(classify_donor_amount)
        df['Transaction Donor Classification'] = df[col_amount].apply(classify_donor_amount)

    donor_counts = df['Donor ID'].value_counts()
    repeat_donors = set(donor_counts[donor_counts > 1].index)
    df['Payment Frequency'] = df['Donor ID'].map(
        lambda d: 'Recurring Payment' if d in repeat_donors else 'One-Time Payment'
    )

    df = deduplicate_dataframe_columns(df)

    # --- CLASSIFICATIONS MATRIX LOOKUP BY CAMPAIGN NAME (INDEPENDENT PER PLATFORM) ---
    target_cols = ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility", "Department", "Office", "Portfolio", "Programme Fund", "Fund Code"]
    for col in target_cols:
        if col not in df.columns:
            df[col] = "Unassigned"

    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
        tbl_name = (
            "rethink_website_classifications" if is_rethink_website else
            "paysuite_classifications" if is_paysuite else
            "givebright_classifications" if is_givebright else
            "madinah_classifications" if is_madinah else
            "campaign_classifications"
        )
        try:
            db_matrix = pd.read_sql_query(f"SELECT * FROM {tbl_name} WHERE LOWER(company_id) = ?", conn, params=(target_cid,))
        except Exception:
            db_matrix = pd.read_sql_query(f"SELECT * FROM {tbl_name}", conn)
        conn.close()

        if not db_matrix.empty and "campaign_name" in db_matrix.columns and "Campaign Name" in df.columns:
            rule_dict_gl = {}
            rule_dict_camp = {}
            for _, r in db_matrix.iterrows():
                c_k = str(r["campaign_name"]).strip().lower()
                gl_k = str(r.get("giving_level") or "").strip().lower()
                if gl_k and gl_k not in ["nan", "none", "n/a", "unassigned", ""]:
                    rule_dict_gl[(c_k, gl_k)] = r.to_dict()
                else:
                    if c_k not in rule_dict_camp or r.get("is_primary") in [1, True, "1", "true", "True"]:
                        rule_dict_camp[c_k] = r.to_dict()

            cname_series = df["Campaign Name"].astype(str).str.strip().str.lower()
            gl_series = df["Giving Level Title"].fillna("").astype(str).str.strip().str.lower() if "Giving Level Title" in df.columns else pd.Series("", index=df.index)

            for f in target_cols:
                db_f = f.lower().replace("-", "_").replace(" ", "_")
                mapped_gl = [rule_dict_gl.get((c, g), {}).get(db_f) if g else None for c, g in zip(cname_series, gl_series)]
                mapped_camp = cname_series.map(lambda c: rule_dict_camp.get(c, {}).get(db_f))
                mapped_vals = pd.Series(mapped_gl, index=df.index).combine_first(mapped_camp)

                valid_mask = mapped_vals.notna() & (~mapped_vals.astype(str).str.lower().isin(["", "nan", "none", "unassigned"]))
                curr_unassigned = df[f].astype(str).str.strip().str.lower().isin(["", "unassigned", "nan", "none"])
                fill_mask = valid_mask & curr_unassigned
                if fill_mask.any():
                    df.loc[fill_mask, f] = mapped_vals[fill_mask]
    except Exception as e:
        print(f"Error mapping campaign classifications matrix: {e}")

    # Second Pass: Dynamic auto-assignment based on Code mapping across all platforms (< 5ms)
    code_map = get_code_to_classification_map(company_id=target_cid)
    if code_map and "Code" in df.columns:
        code_series = df["Code"].astype(str).str.strip().str.lower()
        for tc in ["Heading", "Sub-Heading", "Country", "Zakat Eligibility", "Department", "Office", "Portfolio", "Programme Fund", "Fund Code"]:
            tc_map = {k: v[tc] for k, v in code_map.items() if tc in v and str(v[tc]).lower() not in ["unassigned", "nan", "none", ""]}
            mapped_vals = code_series.map(tc_map)
            curr_unassigned = df[tc].astype(str).str.strip().str.lower().isin(["", "unassigned", "nan", "none"])
            fill_mask = mapped_vals.notna() & curr_unassigned
            if fill_mask.any():
                df.loc[fill_mask, tc] = mapped_vals[fill_mask]

    for col in df.select_dtypes(include='object').columns:
        df[col] = df[col].astype(str).apply(fix_mojibake)

    return df


def process_and_upload_excel(file_buffer, source_name=None, upload_mode="replace", platform="auto", company_id: str = "rethink"):
    """Reads Excel/CSV, standardizes schema, enriches data, auto-classifies, and saves to database with strict company_id isolation."""
    target_cid = str(company_id or "rethink").strip().lower()
    if not target_cid or target_cid == "all":
        target_cid = "rethink"

    # Detect CSV format defensively
    is_csv = False
    if source_name and str(source_name).lower().endswith('.csv'):
        is_csv = True
    else:
        fname = getattr(file_buffer, 'name', '')
        if isinstance(fname, str) and fname.lower().endswith('.csv'):
            is_csv = True

    df = None
    if is_csv:
        read_success = False
        for enc in ['utf-8-sig', 'utf-8', 'latin1', 'cp1252']:
            try:
                file_buffer.seek(0)
                df = pd.read_csv(file_buffer, encoding=enc, on_bad_lines='skip')
                read_success = True
                break
            except Exception:
                continue
        if not read_success:
            file_buffer.seek(0)
            try:
                sheets_dict = pd.read_excel(file_buffer, sheet_name=None)
                list_of_dfs = [sdf for sdf in sheets_dict.values() if not sdf.empty]
                df = pd.concat(list_of_dfs, ignore_index=True)
            except Exception as ex:
                raise ValueError(f"Could not parse uploaded CSV file: {ex}")
    else:
        try:
            file_buffer.seek(0)
            sheets_dict = pd.read_excel(file_buffer, sheet_name=None)
            list_of_dfs = []
            for sdf in sheets_dict.values():
                if not sdf.empty:
                    sdf.columns = [str(c).strip() for c in sdf.columns]
                    list_of_dfs.append(sdf)
            df = pd.concat(list_of_dfs, ignore_index=True)
        except Exception:
            file_buffer.seek(0)
            for enc in ['utf-8-sig', 'utf-8', 'latin1', 'cp1252']:
                try:
                    file_buffer.seek(0)
                    df = pd.read_csv(file_buffer, encoding=enc, on_bad_lines='skip')
                    break
                except Exception:
                    continue
            if df is None or df.empty:
                raise ValueError("Could not parse uploaded Excel/CSV file.")

    if df is None or df.empty:
        raise ValueError("Uploaded file contains no valid data rows.")

    df = deduplicate_dataframe_columns(df)

    batch_label = str(source_name).strip() if (source_name and str(source_name).strip()) else "Master Dataset"
    df["Source"] = batch_label

    # Tag rows strictly with target company_id
    df["company_id"] = target_cid

    # Check if uploaded file is a Payout report vs Raw Donor report
    is_payout_file = (
        str(platform).lower() == "launchgood payout" or
        "Settlement Gross (SC)" in df.columns or
        "Transfer Amount (SC)" in df.columns or
        ("Transfer ID" in df.columns and "Type" in df.columns)
    )

    if is_payout_file:
        return process_payout_settlement_upload(df, source_name=batch_label, upload_mode=upload_mode)

    # Enrich and Auto-Classify New Raw Data
    df_new = _enrich_dataframe(df, platform=platform, company_id=target_cid)
    df_new["company_id"] = target_cid

    # Sync auto-assigned classifications for new upload batch ONLY (< 10ms)
    sync_donors_to_classification_matrix(df_new, company_id=target_cid)

    # Merge or Replace dataset with strict company isolation (other companies' data is NEVER touched)
    df_to_add = df_new
    if os.path.exists(PARQUET_PATH):
        try:
            existing_df = pd.read_parquet(PARQUET_PATH)
            if existing_df is not None and not existing_df.empty:
                if "company_id" not in existing_df.columns:
                    existing_df["company_id"] = "rethink"

                # Other companies data must always be 100% preserved
                other_comp_df = existing_df[existing_df["company_id"].astype(str).str.lower() != target_cid]
                same_comp_df = existing_df[existing_df["company_id"].astype(str).str.lower() == target_cid]

                if upload_mode in ["merge", "append"]:
                    # Deduplicate within df_new itself
                    if "Donation ID" in df_new.columns:
                        val_m = df_new["Donation ID"].notna() & (~df_new["Donation ID"].astype(str).str.strip().str.lower().isin(["", "nan", "none", "n/a", "<na>"]))
                        df_new_valid = df_new[val_m].drop_duplicates(subset=["Donation ID"], keep="first")
                        df_new_invalid = df_new[~val_m]
                        df_new_dedup = pd.concat([df_new_valid, df_new_invalid], ignore_index=True)

                        existing_ids = set()
                        if not same_comp_df.empty and "Donation ID" in same_comp_df.columns:
                            existing_ids = set(same_comp_df["Donation ID"].dropna().astype(str).str.strip().str.lower())
                            existing_ids = {i for i in existing_ids if i not in ["", "nan", "none", "n/a", "<na>"]}

                        # Existing rows are ignored/preserved, NEVER deleted or overwritten
                        if existing_ids:
                            new_mask = ~df_new_dedup["Donation ID"].astype(str).str.strip().str.lower().isin(existing_ids)
                            df_to_add = df_new_dedup[new_mask].copy()
                        else:
                            df_to_add = df_new_dedup
                    else:
                        df_to_add = df_new

                    if not df_to_add.empty:
                        df_target_final = pd.concat([same_comp_df, df_to_add], ignore_index=True)
                    else:
                        df_target_final = same_comp_df
                else:
                    # Replace mode: replaces ONLY this company's donations
                    df_to_add = df_new
                    df_target_final = df_new

                df_save = pd.concat([other_comp_df, df_target_final], ignore_index=True)
            else:
                df_to_add = df_new
                df_save = df_new
        except Exception as e:
            print(f"[Merge Data Notice]: {e}")
            df_to_add = df_new
            df_save = df_new
    else:
        df_to_add = df_new
        df_save = df_new

    df_save = sanitize_df_dtypes_for_parquet(df_save)
    atomic_write_parquet(df_save, PARQUET_PATH)

    try:
        conn = get_db_connection(timeout=60.0)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='donations'")
        table_exists = cur.fetchone() is not None

        if not table_exists:
            df_save.to_sql("donations", con=conn, if_exists="replace", index=False, chunksize=5000)
        else:
            cur.execute("PRAGMA table_info(donations)")
            existing_cols = {r[1] for r in cur.fetchall()}
            for col in df_new.columns:
                if col not in existing_cols:
                    try:
                        conn.execute(f'ALTER TABLE donations ADD COLUMN [{col}] TEXT;')
                        existing_cols.add(col)
                    except Exception:
                        pass

            if upload_mode in ["merge", "append"]:
                # Existing rows are NOT deleted; duplicate IDs are simply ignored.
                # Only insert new rows that do not already exist in the database.
                if not df_to_add.empty:
                    df_to_add.to_sql("donations", con=conn, if_exists="append", index=False, chunksize=2000)
            else:
                # Replace mode: replaces this company's donations
                conn.execute('DELETE FROM donations WHERE LOWER(COALESCE(company_id, "rethink")) = ?', (target_cid,))
                df_new.to_sql("donations", con=conn, if_exists="append", index=False, chunksize=2000)

        try:
            conn.execute('CREATE INDEX IF NOT EXISTS idx_donations_campaign_name ON donations ([Campaign Name]);')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_donations_fundraiser_name ON donations (fundraiser_name);')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_donations_code ON donations (Code);')
            conn.commit()
        except Exception:
            pass
        conn.close()
    except Exception as e:
        print(f"[Upload SQLite Update Notice]: {e}")

    # Automatically synchronize fundraiser assigned campaigns for newly uploaded donations
    try:
        from backend.api.fundraisers import sync_assigned_campaigns_to_donations
        sync_assigned_campaigns_to_donations(company_id=target_cid)
    except Exception as e:
        print(f"[Upload Fundraiser Auto-Sync Notice]: {e}")

    # Invalidate dataset cache so new rows show up instantly
    load_data(force_reload=True)

    # If this is Paysuite data, also sync into paysuite_payout_settlements and payouts cache
    is_ps_records = False
    if "Platform" in df_new.columns:
        is_ps_records = (df_new["Platform"].astype(str).str.lower() == "paysuite").any()
    if is_ps_records or str(platform).lower() == "paysuite":
        process_paysuite_payout_settlement_upload(df_new, source_name=batch_label, upload_mode=upload_mode, company_id=target_cid)

    return {
        "status": "success",
        "added": len(df_to_add),
        "total_records": len(df_save)
    }

def extract_and_sync_launchgood_payout_classifications(df_raw, sync_donors: bool = True):
    """
    Extracts all Project Name -> Code pairs from a payout file, resolves 5-tier classification
    (Heading, Sub-Heading, Country, Code, Zakat Eligibility) via get_code_to_classification_map(),
    upserts into campaign_classifications SQLite table & campaign_classifications_launchgood.json,
    and optionally auto-syncs raw donor records and payout settlement records in real time.
    """
    if df_raw.empty:
        return 0

    p_col = None
    for candidate in ["Project Name", "Campaign Name"]:
        if candidate in df_raw.columns:
            p_col = candidate
            break

    c_col = None
    for candidate in ["Code", "Giving Level Fund Code"]:
        if candidate in df_raw.columns:
            c_col = candidate
            break

    if not p_col or not c_col:
        return 0

    pairs_df = df_raw[[p_col, c_col]].drop_duplicates().dropna()
    code_map = get_code_to_classification_map()
    
    updated_rules = []
    for _, r in pairs_df.iterrows():
        p_name = str(r[p_col]).strip()
        c_code = str(r[c_col]).strip().lower()
        if not p_name or p_name.lower() in ["nan", "none", "n/a", ""]:
            continue
        if not c_code or c_code.lower() in ["nan", "none", "n/a", "", "unassigned"]:
            continue
        
        info = code_map.get(c_code, {})
        # Only seed into classification matrix if the code is a recognized master code in the dictionary
        if info and any(v not in ["Unassigned", "", None] for v in [info.get("Heading"), info.get("Country")]):
            updated_rules.append({
                "campaign_name": p_name,
                "community_name": "N/A",
                "campaign_url": "",
                "heading": info.get("Heading", "Unassigned"),
                "sub_heading": info.get("Sub-Heading", "Unassigned"),
                "country": info.get("Country", "Unassigned"),
                "code": str(r[c_col]).strip().upper(),
                "zakat_eligibility": info.get("Zakat Eligibility", "Unassigned"),
                "is_primary": 0
            })

    if not updated_rules:
        return 0

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    try:
        df_rules = pd.DataFrame(updated_rules)
        try:
            existing_matrix = pd.read_sql_query("SELECT * FROM campaign_classifications", conn)
            if not existing_matrix.empty and "campaign_name" in existing_matrix.columns:
                existing_dict = {(str(r["campaign_name"]).strip().lower(), str(r.get("code", "Unassigned")).strip().upper()): r.to_dict() for _, r in existing_matrix.iterrows()}
                for r in updated_rules:
                    k = (str(r["campaign_name"]).strip().lower(), str(r.get("code", "Unassigned")).strip().upper())
                    if k not in existing_dict:
                        existing_dict[k] = r
                    else:
                        # Only fill fields that are currently unassigned in existing_dict
                        for f in ["heading", "sub_heading", "country", "zakat_eligibility"]:
                            old_val = str(existing_dict[k].get(f, "")).strip().lower()
                            new_val = str(r.get(f, "")).strip()
                            if old_val in ["", "nan", "none", "unassigned"] and new_val.lower() not in ["", "nan", "none", "unassigned"]:
                                existing_dict[k][f] = new_val
                df_rules = pd.DataFrame(list(existing_dict.values()))
        except Exception:
            pass

        if "is_primary" not in df_rules.columns:
            df_rules["is_primary"] = 0
        if "campaign_url" not in df_rules.columns:
            df_rules["campaign_url"] = ""

        df_rules.to_sql("campaign_classifications", con=conn, if_exists="replace", index=False)
        conn.close()

        # Save to JSON file as well
        json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "campaign_classifications_launchgood.json")
        json_df = df_rules.rename(columns={
            "campaign_name": "Campaign Name",
            "community_name": "Community Name",
            "heading": "Heading",
            "sub_heading": "Sub-Heading",
            "country": "Country",
            "code": "Code",
            "zakat_eligibility": "Zakat Eligibility"
        })
        with open(json_path, "w", encoding="utf-8") as f:
            import json
            json.dump(json_df.to_dict(orient="records"), f, indent=2)

        if sync_donors:
            sync_matrix_classifications_to_donors(json_df)

        return len(updated_rules)
    except Exception as e:
        print(f"Error extracting payout classifications: {e}")
        return 0

def process_payout_settlement_upload(df_raw, source_name="LaunchGood Payout.xlsx", upload_mode="replace"):
    """
    Processes and saves Payout settlement records into the isolated payout_settlements SQLite table
    and payouts_cache.parquet without polluting raw donor contribution data in the donations table.
    """
    df_new = _enrich_dataframe(df_raw, platform="launchgood payout")
    
    # 1. Extract Campaign Code Mappings from Payout File and Update LaunchGood Matrix (without redundant donor loop)
    extract_and_sync_launchgood_payout_classifications(df_raw, sync_donors=False)

    # 2. Save Payout Settlement Dataset independently
    if upload_mode in ["merge", "append"] and os.path.exists(PAYOUTS_PARQUET_PATH):
        try:
            existing_payouts = pd.read_parquet(PAYOUTS_PARQUET_PATH)
            if existing_payouts is not None and not existing_payouts.empty:
                df_combined = pd.concat([existing_payouts, df_new], ignore_index=True)
                if "Donation ID" in df_combined.columns:
                    valid_mask = df_combined["Donation ID"].notna() & (~df_combined["Donation ID"].astype(str).str.strip().str.lower().isin(["", "nan", "none", "n/a", "<na>"]))
                    df_valid = df_combined[valid_mask].drop_duplicates(subset=["Donation ID"], keep="last")
                    df_invalid = df_combined[~valid_mask]
                    df_combined = pd.concat([df_valid, df_invalid], ignore_index=True)
                df_save = df_combined
            else:
                df_save = df_new
        except Exception as e:
            print(f"[Payout Merge Notice]: {e}")
            df_save = df_new
    else:
        df_save = df_new

    df_save = sanitize_df_dtypes_for_parquet(df_save)
    atomic_write_parquet(df_save, PAYOUTS_PARQUET_PATH)

    try:
        conn = get_db_connection(timeout=60.0)
        df_save.to_sql("payout_settlements", con=conn, if_exists="replace", index=False, chunksize=5000)
        conn.close()
    except Exception as e:
        print(f"[Payout Settlement DB Save Notice]: {e}")

    # 3. Fast Vectorized Update on raw donor records in Parquet and SQLite DB (< 0.5s)
    try:
        settled_ids = set(df_new[df_new["Donation ID"].notna()]["Donation ID"].astype(str).str.strip().str.lower())
        if settled_ids and os.path.exists(PARQUET_PATH):
            donations_df = pd.read_parquet(PARQUET_PATH)
            if not donations_df.empty and "Donation ID" in donations_df.columns:
                m = donations_df["Donation ID"].astype(str).str.strip().str.lower().isin(settled_ids)
                if m.any():
                    if "Payout Settled" not in donations_df.columns:
                        donations_df["Payout Settled"] = "No"
                    donations_df.loc[m, "Payout Settled"] = "Yes"
                    donations_df = sanitize_df_dtypes_for_parquet(donations_df)
                    donations_df.to_parquet(PARQUET_PATH, index=False)
                    
                    try:
                        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
                        cursor = conn.cursor()
                        cursor.executemany("UPDATE donations SET \"Payout Settled\" = 'Yes' WHERE \"Donation ID\" = ?", [(sid,) for sid in settled_ids])
                        conn.commit()
                        conn.close()
                    except Exception:
                        pass
            
            load_data(force_reload=True)
    except Exception as e:
        print(f"[Payout Fast Sync Notice]: {e}")

    load_payouts_data(force_reload=True)
    try:
        from backend.api.payouts import invalidate_payouts_cache
        invalidate_payouts_cache()
    except Exception:
        pass

    try:
        from backend.api.expenses import clear_expenses_cache
        clear_expenses_cache()
        from backend.api.events import broadcast_event_sync
        broadcast_event_sync("PAYOUTS_UPDATED", {"source": "upload"})
    except Exception:
        pass

    return {
        "status": "success",
        "added": len(df_new),
        "total_records": len(df_save)
    }

def process_paysuite_payout_settlement_upload(df_enriched, source_name="Paysuite Direct Debit", upload_mode="merge", company_id="rethink"):
    """
    Constructs and persists Paysuite direct debit settlement records into paysuite_payout_settlements
    and paysuite_payouts_cache.parquet with strict company_id isolation, and broadcasts real-time updates.
    """
    if df_enriched is None or df_enriched.empty:
        return 0

    target_cid = str(company_id or "rethink").strip().lower()
    df_ps = pd.DataFrame()

    # 1. Map columns
    b_ref = df_enriched.get("Donation ID", df_enriched.get("Bank Ref", df_enriched.get("Direct Debit Ref", ""))).fillna("").astype(str).str.strip()
    df_ps["Donation ID"] = b_ref
    df_ps["Bank Ref"] = b_ref
    df_ps["Customer Ref"] = df_enriched.get("Customer Ref", pd.Series("", index=df_enriched.index)).fillna("").astype(str).str.strip()

    f_name = df_enriched.get("First Name", df_enriched.get("Firstname", pd.Series("", index=df_enriched.index))).fillna("").astype(str).str.strip()
    l_name = df_enriched.get("Last Name", df_enriched.get("Surname", pd.Series("", index=df_enriched.index))).fillna("").astype(str).str.strip()
    disp_name = (f_name + " " + l_name).str.strip()
    df_ps["Display Name"] = df_enriched.get("Display Name", disp_name).fillna(disp_name)
    df_ps["First Name"] = f_name
    df_ps["Last Name"] = l_name
    df_ps["Email"] = df_enriched.get("Email", pd.Series("", index=df_enriched.index)).fillna("").astype(str).str.strip()
    df_ps["Campaign Name"] = b_ref
    df_ps["Schedule"] = df_enriched.get("Schedule", pd.Series("Direct Debit Collection", index=df_enriched.index)).fillna("Direct Debit Collection")
    df_ps["Type"] = df_enriched.get("Type", pd.Series("Regular", index=df_enriched.index)).fillna("Regular")
    df_ps["Transaction Type"] = "donation"
    df_ps["row_type"] = "donation"

    st = df_enriched.get("Status", df_enriched.get("Paid/Unpaid", pd.Series("Paid", index=df_enriched.index))).fillna("Paid").astype(str).str.capitalize()
    df_ps["Paid/Unpaid"] = st
    df_ps["Status"] = st
    df_ps["Settlement Currency"] = "GBP"
    df_ps["Project Currency"] = "GBP"

    amt_series = pd.to_numeric(df_enriched.get("Amount", df_enriched.get("Total Online Donations Net Amount in Settled Currency", 0.0)), errors="coerce").fillna(0.0)
    df_ps["Donation Amount"] = amt_series
    df_ps["Total Online Donation Gross Amount in Settled Currency"] = amt_series
    df_ps["Total Processing Fees Paid by CC In Settled Currency"] = 0.0
    df_ps["Total Online Donations Net Amount in Settled Currency"] = np.where(st == "Paid", amt_series, 0.0)

    # Dates & Batches
    if "Created Date (UTC)" in df_enriched.columns and df_enriched["Created Date (UTC)"].notna().any():
        parsed_dt = pd.to_datetime(df_enriched["Created Date (UTC)"], errors="coerce")
    elif "Date of collection" in df_enriched.columns:
        parsed_dt = pd.to_datetime(df_enriched["Date of collection"], dayfirst=True, errors="coerce")
    elif "Due" in df_enriched.columns:
        parsed_dt = pd.to_datetime(df_enriched["Due"], dayfirst=True, errors="coerce")
    else:
        parsed_dt = pd.to_datetime(datetime.date.today())

    df_ps["Created Date (UTC)"] = parsed_dt.dt.strftime('%Y-%m-%d')
    df_ps["Date of collection"] = df_enriched.get("Date of collection", parsed_dt.dt.strftime('%d/%m/%Y'))
    df_ps["Due"] = df_enriched.get("Due", df_enriched.get("Date Due", parsed_dt.dt.strftime('%d/%m/%Y')))
    df_ps["Created Time (UTC)"] = "00:00:00"

    df_ps["Transfer ID"] = parsed_dt.dt.strftime('%Y-%m').fillna("Unknown")
    df_ps["Batch Label"] = parsed_dt.dt.strftime('%B %Y Collection').fillna("Collection")
    df_ps["Collection Month"] = parsed_dt.dt.strftime('%B %Y').fillna("Collection")

    df_ps["Platform"] = "Paysuite"
    df_ps["Source"] = source_name or "Paysuite Direct Debit"

    # Classifications
    for col in ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility"]:
        df_ps[col] = df_enriched.get(col, pd.Series("Unassigned", index=df_enriched.index)).fillna("Unassigned")

    df_ps["Payment Frequency"] = df_enriched.get("Payment Frequency", pd.Series("Recurring", index=df_enriched.index)).fillna("Recurring")
    df_ps["Address"] = df_enriched.get("Billing Address", df_enriched.get("Address", pd.Series("", index=df_enriched.index))).fillna("")
    df_ps["Postcode"] = df_enriched.get("Billing Zip", df_enriched.get("Post code", df_enriched.get("Postcode", pd.Series("", index=df_enriched.index)))).fillna("")
    df_ps["Phone"] = df_enriched.get("Phone Number", df_enriched.get("Phone", pd.Series("", index=df_enriched.index))).fillna("")
    df_ps["Comments"] = df_enriched.get("Comments", pd.Series("", index=df_enriched.index)).fillna("")
    df_ps["company_id"] = target_cid

    # Lookup any missing donor info or classifications from paysuite_classifications view
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=15.0)
        ps_matrix = pd.read_sql_query("SELECT * FROM paysuite_classifications WHERE LOWER(company_id) = ?", conn, params=(target_cid,))
        conn.close()
        if not ps_matrix.empty:
            rule_dict = {str(r["campaign_name"]).strip().lower(): r for _, r in ps_matrix.iterrows()}
            for idx, r in df_ps.iterrows():
                bkey = str(r["Bank Ref"]).strip().lower()
                if bkey in rule_dict:
                    entry = rule_dict[bkey]
                    if (not r["Email"] or r["Email"] == "None" or r["Email"] == "nan") and entry.get("donor_email"):
                        df_ps.at[idx, "Email"] = str(entry["donor_email"])
                    if (not r["Display Name"] or r["Display Name"] == "None" or r["Display Name"] == "nan") and entry.get("donor_name"):
                        df_ps.at[idx, "Display Name"] = str(entry["donor_name"])
                    if (r["Code"] == "Unassigned" or not r["Code"]) and entry.get("code"):
                        df_ps.at[idx, "Code"] = str(entry["code"])
                    if (r["Heading"] == "Unassigned" or not r["Heading"]) and entry.get("heading"):
                        df_ps.at[idx, "Heading"] = str(entry["heading"])
                    if (r["Sub-Heading"] == "Unassigned" or not r["Sub-Heading"]) and entry.get("sub_heading"):
                        df_ps.at[idx, "Sub-Heading"] = str(entry["sub_heading"])
                    if (r["Country"] == "Unassigned" or not r["Country"]) and entry.get("country"):
                        df_ps.at[idx, "Country"] = str(entry["country"])
                    if (r["Zakat Eligibility"] == "Unassigned" or not r["Zakat Eligibility"]) and entry.get("zakat_eligibility"):
                        df_ps.at[idx, "Zakat Eligibility"] = str(entry["zakat_eligibility"])
    except Exception as e:
        print(f"[Paysuite Rule Overlay Notice]: {e}")

    # 2. Merge with existing paysuite_payout_settlements
    if upload_mode in ["merge", "append"] and os.path.exists(PAYSUITE_PAYOUTS_PARQUET_PATH):
        try:
            existing_ps = pd.read_parquet(PAYSUITE_PAYOUTS_PARQUET_PATH)
            if existing_ps is not None and not existing_ps.empty:
                if "company_id" not in existing_ps.columns:
                    existing_ps["company_id"] = "rethink"
                other_comp = existing_ps[existing_ps["company_id"].astype(str).str.lower() != target_cid]
                same_comp = existing_ps[existing_ps["company_id"].astype(str).str.lower() == target_cid]

                df_combined_target = pd.concat([same_comp, df_ps], ignore_index=True)
                dedup_cols = [c for c in ["Bank Ref", "Date of collection", "Transfer ID"] if c in df_combined_target.columns]
                if dedup_cols:
                    df_target_final = df_combined_target.drop_duplicates(subset=dedup_cols, keep="last")
                else:
                    df_target_final = df_combined_target
                df_save = pd.concat([other_comp, df_target_final], ignore_index=True)
            else:
                df_save = df_ps
        except Exception as e:
            print(f"[Paysuite Payout Merge Notice]: {e}")
            df_save = df_ps
    else:
        df_save = df_ps

    df_save = sanitize_df_dtypes_for_parquet(df_save)
    atomic_write_parquet(df_save, PAYSUITE_PAYOUTS_PARQUET_PATH)

    try:
        conn = get_db_connection(timeout=60.0)
        df_save.to_sql("paysuite_payout_settlements", con=conn, if_exists="replace", index=False, chunksize=5000)
        conn.close()
    except Exception as e:
        print(f"[Paysuite Payout Settlement DB Save Notice]: {e}")

    invalidate_paysuite_payouts_cache()
    load_paysuite_payouts_data(force_reload=True)
    try:
        from backend.api.payouts import invalidate_payouts_cache
        invalidate_payouts_cache()
    except Exception:
        pass

    try:
        from backend.api.events import broadcast_event_sync
        broadcast_event_sync("PAYOUTS_UPDATED", {"source": "upload", "platform": "paysuite", "company_id": target_cid})
        broadcast_event_sync("DONORS_UPDATED", {"source": "upload", "platform": "paysuite", "company_id": target_cid})
    except Exception:
        pass

    return len(df_ps)

def sync_donor_classifications_to_matrix(df_donations, company_id: str = "rethink"):
    """Synchronizes cell edits from donor records back into campaign classification rules for a company."""
    if df_donations.empty or "Campaign Name" not in df_donations.columns:
        return
    try:
        comp = str(company_id or "rethink").lower().strip()
        target_cols = ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility"]
        available_cols = [c for c in target_cols if c in df_donations.columns]
        if not available_cols:
            return

        c_name = df_donations["Campaign Name"].astype(str).fillna("N/A").replace({'nan': 'N/A', '': 'N/A', 'None': 'N/A'})
        comm_name = df_donations["Community Name"].astype(str).fillna("N/A").replace({'nan': 'N/A', '': 'N/A', 'None': 'N/A'}) if "Community Name" in df_donations.columns else pd.Series("N/A", index=df_donations.index)

        donor_df = pd.DataFrame({"Campaign Name": c_name, "Community Name": comm_name})
        for tc in available_cols:
            donor_df[tc] = df_donations[tc].values

        matrix_df = donor_df.groupby(["Campaign Name", "Community Name"], dropna=False)[available_cols].agg(_mode_or_last).reset_index()
        save_classification_matrix(matrix_df, company_id=comp)
    except Exception as e:
        print(f"Donor to matrix sync notice: {e}")

def purge_all_data():
    """Purges active transaction datasets (donations and payout settlements) while keeping campaign classification rules 100% intact."""
    if os.path.exists(PARQUET_PATH):
        try:
            os.remove(PARQUET_PATH)
        except Exception:
            pass

    if os.path.exists(PAYOUTS_PARQUET_PATH):
        try:
            os.remove(PAYOUTS_PARQUET_PATH)
        except Exception:
            pass

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS donations")
    cursor.execute("DROP TABLE IF EXISTS payout_settlements")
    # NOTE: Classification tables are permanently preserved and never dropped during transaction purge
    conn.commit()
    conn.close()

    invalidate_data_cache()
    invalidate_payouts_cache()
    try:
        from backend.api.payouts import invalidate_payouts_cache as inv_p
        inv_p()
    except Exception:
        pass

def update_source_tag(old_tag, new_tag):
    """Renames an existing dataset source tag across Parquet and SQLite."""
    if not old_tag or not new_tag:
        return 0
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    cursor = conn.cursor()
    cursor.execute("UPDATE donations SET Source = ? WHERE Source = ?", (new_tag, old_tag))
    updated_count = cursor.rowcount
    conn.commit()
    conn.close()

    if os.path.exists(PARQUET_PATH):
        try:
            df = pd.read_parquet(PARQUET_PATH)
            if "Source" in df.columns:
                df["Source"] = df["Source"].replace({old_tag: new_tag})
                df.to_parquet(PARQUET_PATH, index=False)
                sync_to_cloud_async(df, mode="replace")
        except Exception as e:
            print(f"Parquet source tag update notice: {e}")

    return updated_count

def delete_single_dataset(source_tag):
    """Deletes all records matching a specific source tag."""
    if not source_tag:
        return 0

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM donations WHERE Source = ?", (source_tag,))
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()

    if os.path.exists(PARQUET_PATH):
        try:
            df = pd.read_parquet(PARQUET_PATH)
            if "Source" in df.columns:
                df = df[df["Source"] != source_tag]
                df.to_parquet(PARQUET_PATH, index=False)
                sync_to_cloud_async(df, mode="replace")
        except Exception as e:
            print(f"Parquet dataset delete notice: {e}")

    return deleted_count

def invalidate_data_cache():
    """Forces the in-memory dataset cache to be invalidated."""
    global _CACHED_DF, _CACHE_MTIME
    with _CACHE_LOCK:
        _CACHED_DF = None
        _CACHE_MTIME = 0.0


def set_cached_data(df: pd.DataFrame):
    """Sets the in-memory dataset cache directly."""
    global _CACHED_DF, _CACHE_MTIME
    with _CACHE_LOCK:
        _CACHED_DF = df
        _CACHE_MTIME = time.time()


def purge_payout_data():
    """Purges all LaunchGood Payout settlement records from SQLite (payout_settlements) & Parquet cache."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    cursor = conn.cursor()

    # 1. Count and delete from isolated payout_settlements table
    payout_count = 0
    cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='payout_settlements'")
    if cursor.fetchone()[0] > 0:
        cursor.execute("SELECT COUNT(*) FROM payout_settlements")
        payout_count = cursor.fetchone()[0]
        cursor.execute("DROP TABLE IF EXISTS payout_settlements")

    # 2. Also remove any legacy payout rows from donations table
    cursor.execute("""
        DELETE FROM donations 
        WHERE "Platform" LIKE '%Payout%' 
           OR "Source" LIKE '%Payout%' 
           OR "Type" IN ('payout', 'reserve', 'fx', 'adjustment')
    """)
    legacy_donations_deleted = cursor.rowcount
    deleted_count = payout_count + (legacy_donations_deleted if legacy_donations_deleted > 0 else 0)

    # 3. Reset Payout Settled flag on remaining raw donor records if table exists
    cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='donations'")
    if cursor.fetchone()[0] > 0:
        cursor.execute("UPDATE donations SET \"Payout Settled\" = 'No' WHERE \"Payout Settled\" = 'Yes'")
    
    conn.commit()
    conn.close()

    # 4. Remove isolated payouts parquet cache
    if os.path.exists(PAYOUTS_PARQUET_PATH):
        try:
            if payout_count == 0:
                payout_count = len(pd.read_parquet(PAYOUTS_PARQUET_PATH))
                deleted_count = max(deleted_count, payout_count)
            os.remove(PAYOUTS_PARQUET_PATH)
        except Exception as e:
            print(f"Payouts parquet removal notice: {e}")

    # 5. Clean legacy rows and reset Payout Settled in donations parquet
    if os.path.exists(PARQUET_PATH):
        try:
            df = pd.read_parquet(PARQUET_PATH)
            if not df.empty:
                p_mask = pd.Series(False, index=df.index)
                if "Platform" in df.columns:
                    p_mask = p_mask | df["Platform"].astype(str).str.lower().str.contains("payout", na=False)
                if "Source" in df.columns:
                    p_mask = p_mask | df["Source"].astype(str).str.lower().str.contains("payout", na=False)
                if "Type" in df.columns:
                    p_mask = p_mask | df["Type"].astype(str).str.lower().isin(["payout", "reserve", "fx", "adjustment"])
                
                df_clean = df[~p_mask].copy()
                if "Payout Settled" in df_clean.columns:
                    df_clean["Payout Settled"] = "No"
                df_clean = sanitize_df_dtypes_for_parquet(df_clean)
                df_clean.to_parquet(PARQUET_PATH, index=False)
        except Exception as e:
            print(f"Parquet payout purge notice: {e}")

    # 6. Invalidate all caches
    invalidate_data_cache()
    invalidate_payouts_cache()
    load_data(force_reload=True)
    load_payouts_data(force_reload=True)
    try:
        from backend.api.payouts import invalidate_payouts_cache as inv_p
        inv_p()
    except Exception:
        pass

    return deleted_count


def _ensure_two_tier_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ensures Department, Office, Portfolio, Heading, Sub-Heading, Programme Fund, Fund Code, and Old Code columns exist and mirror each other."""
    if df is None or df.empty:
        return df
    if "Heading" in df.columns and "Department" not in df.columns:
        df["Department"] = df["Heading"]
    if "Sub-Heading" in df.columns and "Office" not in df.columns:
        df["Office"] = df["Sub-Heading"]
    if "Portfolio" not in df.columns:
        df["Portfolio"] = ""
    if "Programme Fund" not in df.columns:
        df["Programme Fund"] = ""
    if "Fund Code" not in df.columns:
        df["Fund Code"] = ""
    if "Old Code" not in df.columns:
        df["Old Code"] = ""
    if "company_id" not in df.columns:
        df["company_id"] = "rethink"
    if "Department" in df.columns and "Heading" not in df.columns:
        df["Heading"] = df["Department"]
    if "Office" in df.columns and "Sub-Heading" not in df.columns:
        df["Sub-Heading"] = df["Office"]

    # Giving Level Title resolution across all platform aliases (GiveBright impact_name, Madinah Giving Levels)
    if "Giving Level Title" not in df.columns:
        df["Giving Level Title"] = ""
    for gl_col in ["impact_name", "Giving Levels", "giving_levels", "giving_level", "variant", "option"]:
        if gl_col in df.columns:
            cur_gl = df["Giving Level Title"].fillna("").astype(str).str.strip()
            cand_gl = df[gl_col].fillna("").astype(str).str.strip()
            mask_fill = cur_gl.str.lower().isin(["", "nan", "none", "null", "n/a"]) & (~cand_gl.str.lower().isin(["", "nan", "none", "null", "n/a"]))
            if mask_fill.any():
                df.loc[mask_fill, "Giving Level Title"] = cand_gl[mask_fill]

    # Resilient, High-Speed ISO Date Standardization across all fallback sources (Iqra & Rethink)
    # GiveBright or UK-formatted created_at (D/M/YYYY) ground-truth override
    if "created_at" in df.columns:
        c_at_str = df["created_at"].fillna("").astype(str).str.strip()
        slash_m = c_at_str.str.extract(r"^(\d{1,2})/(\d{1,2})/(\d{4})")
        has_slash = slash_m[0].notna() & slash_m[1].notna() & slash_m[2].notna()
        if has_slash.any():
            corr_d = slash_m.loc[has_slash, 2] + "-" + slash_m.loc[has_slash, 1].str.zfill(2) + "-" + slash_m.loc[has_slash, 0].str.zfill(2)
            df.loc[has_slash, "_parsed_date"] = corr_d
            df.loc[has_slash, "Created Date (UTC)"] = corr_d
            df.loc[has_slash, "Date"] = corr_d

    date_candidates = ["_parsed_date", "Created Date (UTC)", "Date", "created_at", "Settled Date (UTC)", "Date of collection", "Date Due"]
    res_date = pd.Series("", index=df.index, dtype=object)
    for col in date_candidates:
        if col not in df.columns:
            continue
        s = df[col].astype(str).str.strip()
        unresolved = (res_date == "") | res_date.isna()
        if not unresolved.any():
            break
        cur = s[unresolved]
        valid = ~cur.str.lower().isin(["", "nan", "none", "nat", "<na>"])
        if not valid.any():
            continue
        valid_cur = cur[valid]
        # ISO format: YYYY-MM-DD
        iso_mask = valid_cur.str.match(r"^\d{4}-\d{2}-\d{2}")
        if iso_mask.any():
            iso_dates = valid_cur[iso_mask].str.slice(0, 10)
            res_date.loc[iso_dates.index] = iso_dates
        # Slash format: D/M/YYYY or DD/MM/YYYY
        slash_mask = valid_cur.str.match(r"^\d{1,2}/\d{1,2}/\d{4}")
        if slash_mask.any():
            slash_raw = valid_cur[slash_mask]
            parts = slash_raw.str.extract(r"^(\d{1,2})/(\d{1,2})/(\d{4})")
            formatted = parts[2] + "-" + parts[1].str.zfill(2) + "-" + parts[0].str.zfill(2)
            res_date.loc[slash_raw.index] = formatted

    # Always ensure _parsed_date, Created Date (UTC), and Date are populated and synchronized
    df["_parsed_date"] = res_date
    if "Created Date (UTC)" not in df.columns or df["Created Date (UTC)"].isna().all():
        df["Created Date (UTC)"] = res_date
    else:
        cd_str = df["Created Date (UTC)"].astype(str).str.strip()
        invalid_cd = cd_str.str.lower().isin(["", "nan", "none", "nat", "<na>"]) | cd_str.str.contains("/")
        df.loc[invalid_cd & (res_date != ""), "Created Date (UTC)"] = res_date[invalid_cd & (res_date != "")]
    df["Date"] = df["Created Date (UTC)"]
    return df


def load_data(force_reload: bool = False, company_id: Optional[str] = None) -> pd.DataFrame:
    """
    High-Performance Dataset Loader with In-Memory Singleton Caching.
    Returns the cached DataFrame in < 1ms when available and up-to-date on disk.
    Supports strict company_id isolation (defaults to all if None).
    """
    global _CACHED_DF, _CACHE_MTIME

    # Check if Parquet file exists and get its mtime
    current_mtime = 0.0
    if os.path.exists(PARQUET_PATH):
        try:
            current_mtime = os.path.getmtime(PARQUET_PATH)
        except Exception:
            current_mtime = 0.0

    # Return cached DataFrame if valid and not force_reload
    if not force_reload and _CACHED_DF is not None and len(_CACHED_DF) > 0:
        if current_mtime == _CACHE_MTIME or current_mtime == 0.0:
            if company_id is not None:
                cid_clean = str(company_id).strip().lower()
                if cid_clean != "all" and "company_id" in _CACHED_DF.columns:
                    return _CACHED_DF[_CACHED_DF["company_id"].astype(str).str.strip().str.lower() == cid_clean]
            return _CACHED_DF

    with _CACHE_LOCK:
        # Double-check inside lock
        if not force_reload and _CACHED_DF is not None and len(_CACHED_DF) > 0:
            if current_mtime == _CACHE_MTIME or current_mtime == 0.0:
                return _filter_cached_by_company(_CACHED_DF, company_id)

        # 1. Primary: Load from Parquet binary cache (Fast columnar format)
        if os.path.exists(PARQUET_PATH):
            try:
                df = pd.read_parquet(PARQUET_PATH)
                if not df.empty:
                    df = _ensure_two_tier_columns(df)
                    _CACHED_DF = df
                    _CACHE_MTIME = current_mtime
                    return _filter_cached_by_company(_CACHED_DF, company_id)
            except Exception as e:
                print(f"[CACHE NOTICE] Parquet read fallback: {e}")

        # 2. Secondary Fallback: Load from SQLite
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
            df = pd.read_sql_query("SELECT * FROM donations", conn)
            conn.close()
            if not df.empty:
                df = _ensure_two_tier_columns(df)
                try:
                    df.to_parquet(PARQUET_PATH, index=False)
                    if os.path.exists(PARQUET_PATH):
                        _CACHE_MTIME = os.path.getmtime(PARQUET_PATH)
                except Exception:
                    pass
                _CACHED_DF = df
                return _filter_cached_by_company(_CACHED_DF, company_id)
        except Exception as e:
            print(f"[CACHE NOTICE] SQLite read fallback: {e}")

        # 3. Tertiary Fallback: Return empty DataFrame
        return pd.DataFrame()


def atomic_write_parquet(df: pd.DataFrame, target_path: str) -> None:
    """
    Safely writes a pandas DataFrame to Parquet by writing to a temporary file
    in the same directory and atomically replacing the target file via os.replace.
    Ensures readers never encounter partial writes or corrupted headers.
    """
    tmp_path = target_path + f".tmp_{os.getpid()}_{threading.get_ident()}"
    try:
        df.to_parquet(tmp_path, index=False)
        os.replace(tmp_path, target_path)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise e


def _filter_cached_by_company(df, company_id):
    if company_id is not None and df is not None and not df.empty and "company_id" in df.columns:
        cid_clean = str(company_id).strip().lower()
        if cid_clean != "all":
            return df[df["company_id"].astype(str).str.strip().str.lower() == cid_clean].copy()
    return df


_CACHED_PAYOUTS_DF = None
_CACHE_PAYOUTS_MTIME = 0.0
_CACHE_PAYOUTS_LOCK = threading.Lock()

_CACHED_PAYSUITE_PAYOUTS_DF = None
_CACHE_PAYSUITE_PAYOUTS_MTIME = 0.0
_CACHE_PAYSUITE_PAYOUTS_LOCK = threading.Lock()

def invalidate_payouts_cache():
    """Forces the in-memory payouts dataset cache to be invalidated."""
    global _CACHED_PAYOUTS_DF, _CACHE_PAYOUTS_MTIME
    with _CACHE_PAYOUTS_LOCK:
        _CACHED_PAYOUTS_DF = None
        _CACHE_PAYOUTS_MTIME = 0.0

def invalidate_paysuite_payouts_cache():
    """Forces the in-memory paysuite payouts dataset cache to be invalidated."""
    global _CACHED_PAYSUITE_PAYOUTS_DF, _CACHE_PAYSUITE_PAYOUTS_MTIME
    with _CACHE_PAYSUITE_PAYOUTS_LOCK:
        _CACHED_PAYSUITE_PAYOUTS_DF = None
        _CACHE_PAYSUITE_PAYOUTS_MTIME = 0.0

def load_payouts_data(force_reload: bool = False, company_id: Optional[str] = None) -> pd.DataFrame:
    """Thread-safe cached loader for payout settlements dataset with company_id filtering."""
    global _CACHED_PAYOUTS_DF, _CACHE_PAYOUTS_MTIME

    current_mtime = 0.0
    if os.path.exists(PAYOUTS_PARQUET_PATH):
        try:
            current_mtime = os.path.getmtime(PAYOUTS_PARQUET_PATH)
        except Exception:
            current_mtime = 0.0

    if not force_reload and _CACHED_PAYOUTS_DF is not None and len(_CACHED_PAYOUTS_DF) > 0:
        if current_mtime == _CACHE_PAYOUTS_MTIME or current_mtime == 0.0:
            return _filter_cached_by_company(_CACHED_PAYOUTS_DF, company_id)

    with _CACHE_PAYOUTS_LOCK:
        if not force_reload and _CACHED_PAYOUTS_DF is not None and len(_CACHED_PAYOUTS_DF) > 0:
            if current_mtime == _CACHE_PAYOUTS_MTIME or current_mtime == 0.0:
                return _filter_cached_by_company(_CACHED_PAYOUTS_DF, company_id)

        if os.path.exists(PAYOUTS_PARQUET_PATH):
            try:
                df = pd.read_parquet(PAYOUTS_PARQUET_PATH)
                if not df.empty:
                    if "company_id" not in df.columns:
                        df["company_id"] = "rethink"
                    _CACHED_PAYOUTS_DF = df
                    _CACHE_PAYOUTS_MTIME = current_mtime
                    return _filter_cached_by_company(_CACHED_PAYOUTS_DF, company_id)
            except Exception as e:
                print(f"[CACHE NOTICE] Payouts parquet read fallback: {e}")

        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=15.0)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='payout_settlements'")
            if cursor.fetchone():
                df = pd.read_sql_query("SELECT * FROM payout_settlements", conn)
                conn.close()
                if not df.empty:
                    try:
                        df.to_parquet(PAYOUTS_PARQUET_PATH, index=False)
                        if os.path.exists(PAYOUTS_PARQUET_PATH):
                            _CACHE_PAYOUTS_MTIME = os.path.getmtime(PAYOUTS_PARQUET_PATH)
                    except Exception:
                        pass
                    _CACHED_PAYOUTS_DF = df
                    return _CACHED_PAYOUTS_DF
            else:
                conn.close()
        except Exception as e:
            print(f"[CACHE NOTICE] Payouts SQLite read fallback: {e}")

        return pd.DataFrame()


def load_paysuite_payouts_data(force_reload: bool = False, company_id: Optional[str] = None) -> pd.DataFrame:
    """Thread-safe cached loader for Paysuite payout settlements dataset with company_id filtering."""
    global _CACHED_PAYSUITE_PAYOUTS_DF, _CACHE_PAYSUITE_PAYOUTS_MTIME

    current_mtime = 0.0
    if os.path.exists(PAYSUITE_PAYOUTS_PARQUET_PATH):
        try:
            current_mtime = os.path.getmtime(PAYSUITE_PAYOUTS_PARQUET_PATH)
        except Exception:
            current_mtime = 0.0

    if not force_reload and _CACHED_PAYSUITE_PAYOUTS_DF is not None and len(_CACHED_PAYSUITE_PAYOUTS_DF) > 0:
        if current_mtime == _CACHE_PAYSUITE_PAYOUTS_MTIME or current_mtime == 0.0:
            return _filter_cached_by_company(_CACHED_PAYSUITE_PAYOUTS_DF, company_id)

    with _CACHE_PAYSUITE_PAYOUTS_LOCK:
        if not force_reload and _CACHED_PAYSUITE_PAYOUTS_DF is not None and len(_CACHED_PAYSUITE_PAYOUTS_DF) > 0:
            if current_mtime == _CACHE_PAYSUITE_PAYOUTS_MTIME or current_mtime == 0.0:
                return _filter_cached_by_company(_CACHED_PAYSUITE_PAYOUTS_DF, company_id)

        if os.path.exists(PAYSUITE_PAYOUTS_PARQUET_PATH):
            try:
                df = pd.read_parquet(PAYSUITE_PAYOUTS_PARQUET_PATH)
                if not df.empty:
                    if "company_id" not in df.columns:
                        df["company_id"] = "rethink"
                    _CACHED_PAYSUITE_PAYOUTS_DF = df
                    _CACHE_PAYSUITE_PAYOUTS_MTIME = current_mtime
                    return _filter_cached_by_company(_CACHED_PAYSUITE_PAYOUTS_DF, company_id)
            except Exception as e:
                print(f"[CACHE NOTICE] Paysuite payouts parquet read fallback: {e}")

        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=15.0)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='paysuite_payout_settlements'")
            if cursor.fetchone():
                df = pd.read_sql_query("SELECT * FROM paysuite_payout_settlements", conn)
                conn.close()
                if not df.empty:
                    if "company_id" not in df.columns:
                        df["company_id"] = "rethink"
                    try:
                        df.to_parquet(PAYSUITE_PAYOUTS_PARQUET_PATH, index=False)
                        if os.path.exists(PAYSUITE_PAYOUTS_PARQUET_PATH):
                            _CACHE_PAYSUITE_PAYOUTS_MTIME = os.path.getmtime(PAYSUITE_PAYOUTS_PARQUET_PATH)
                    except Exception:
                        pass
                    _CACHED_PAYSUITE_PAYOUTS_DF = df
                    return _filter_cached_by_company(_CACHED_PAYSUITE_PAYOUTS_DF, company_id)
            else:
                conn.close()
        except Exception as e:
            print(f"[CACHE NOTICE] Paysuite Payouts SQLite read fallback: {e}")

        return pd.DataFrame()


def ensure_database_indexes():
    """Ensures database indexes exist on donations, payout_settlements, and paysuite_payout_settlements for instant query performance."""
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_donations_donor_id ON donations(\"Donor ID\")")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_donations_camp_name ON donations(\"Campaign Name\")")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_donations_code ON donations(\"Code\")")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_donations_platform ON donations(\"Platform\")")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_donations_created_date ON donations(\"Created Date (UTC)\")")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_donations_payout_settled ON donations(\"Payout Settled\")")
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='payout_settlements'")
        if cursor.fetchone():
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_payouts_transfer_id ON payout_settlements(\"Transfer ID\")")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_payouts_donation_id ON payout_settlements(\"Donation ID\")")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_payouts_camp_name ON payout_settlements(\"Campaign Name\")")

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='paysuite_payout_settlements'")
        if cursor.fetchone():
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ps_payouts_transfer_id ON paysuite_payout_settlements(\"Transfer ID\")")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ps_payouts_bank_ref ON paysuite_payout_settlements(\"Bank Ref\")")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ps_payouts_code ON paysuite_payout_settlements(\"Code\")")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ps_payouts_status ON paysuite_payout_settlements(\"Status\")")

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Index Notice]: {e}")


def get_givebright_classification_matrix(df_raw=None, company_id: Optional[str] = "rethink"):
    """Returns GiveBright classification matrix DataFrame with unique (Campaign Name, Giving Level, Code) granularity for a company."""
    init_classification_db()
    target_cols = ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility", "Department", "Office", "Portfolio", "Programme Fund", "Fund Code"]
    comp = str(company_id or "rethink").lower().strip()

    # 1. Read existing saved rules directly from SQLite
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        where_clause = " WHERE LOWER(COALESCE(company_id, 'rethink')) = ?" if comp != "all" else ""
        params = [comp] if comp != "all" else []
        db_matrix = pd.read_sql_query(f"""
            SELECT 
                campaign_name as "Campaign Name",
                COALESCE(giving_level, '') as "Giving Level",
                COALESCE(code, 'Unassigned') as "Code",
                COALESCE(special_case, '') as "Special Case",
                COALESCE(special_treatment, '') as "Special Treatment",
                COALESCE(campaign_url, '') as "Campaign URL",
                COALESCE(community_name, 'N/A') as "Community Name",
                COALESCE(department, heading, 'Unassigned') as "Department",
                COALESCE(office, sub_heading, 'Unassigned') as "Office",
                COALESCE(portfolio, '') as "Portfolio",
                COALESCE(programme_fund, '') as "Programme Fund",
                COALESCE(fund_code, '') as "Fund Code",
                COALESCE(heading, department, 'Unassigned') as "Heading",
                COALESCE(sub_heading, office, 'Unassigned') as "Sub-Heading",
                COALESCE(country, 'Unassigned') as "Country",
                COALESCE(zakat_eligibility, 'Unassigned') as "Zakat Eligibility",
                COALESCE(is_primary, 0) as "is_primary",
                COALESCE(donor_name, '') as "Donor Name",
                COALESCE(donor_email, '') as "Donor Email"
            FROM givebright_classifications
            {where_clause}
        """, conn, params=params)
    except Exception:
        db_matrix = pd.DataFrame(columns=["Campaign Name", "Giving Level", "Code", "Campaign URL", "Community Name"] + [c for c in target_cols if c != "Code"])
    finally:
        conn.close()

    if not db_matrix.empty:
        db_matrix["Campaign Name"] = db_matrix["Campaign Name"].apply(fix_mojibake).str.strip()
        db_matrix["Giving Level"] = db_matrix["Giving Level"].apply(fix_mojibake).str.strip()

    # 2. Extract distinct (Campaign Name, Giving Level, Code) triples from real GiveBright donations
    donor_distinct = None
    try:
        from core.analytics_engine import get_duckdb_connection
        con = get_duckdb_connection()
        if con and os.path.exists(PARQUET_PATH):
            company_filter = f"AND LOWER(COALESCE(\"company_id\", 'rethink')) = '{comp}'" if comp != "all" else ""
            donor_distinct = con.execute(f"""
                SELECT 
                    COALESCE(NULLIF(TRIM("Campaign Name"), ''), 'N/A') as "Campaign Name",
                    CASE 
                        WHEN "Giving Level Title" IS NOT NULL AND LOWER(TRIM("Giving Level Title")) NOT IN ('', 'nan', 'none', 'null', 'n/a') THEN TRIM("Giving Level Title")
                        WHEN "impact_name" IS NOT NULL AND LOWER(TRIM("impact_name")) NOT IN ('', 'nan', 'none', 'null', 'n/a') THEN TRIM("impact_name")
                        ELSE ''
                    END as "Giving Level",
                    COALESCE(NULLIF(TRIM("Code"), ''), 'Unassigned') as "Code",
                    MAX(COALESCE(NULLIF(TRIM("Community Name"), ''), 'N/A')) as "Community Name",
                    MAX(COALESCE(NULLIF(TRIM("Campaign URL"), ''), '')) as "Campaign URL",
                    COUNT(*) as donation_count,
                    SUM(TRY_CAST(REPLACE(REPLACE(COALESCE(CAST("Total Online Donation Gross Amount in Settled Currency" AS VARCHAR), CAST("Donation Amount (in Donation Currency)" AS VARCHAR), CAST("Amount" AS VARCHAR), '0'), '£', ''), ',', '') AS DOUBLE)) as total_amount
                FROM '{PARQUET_PATH.replace(chr(92), '/')}'
                WHERE LOWER(COALESCE("Platform", '')) IN ('givebright', 'givebrite')
                  AND "Campaign Name" IS NOT NULL
                  AND LOWER(TRIM(CAST("Campaign Name" AS VARCHAR))) NOT IN ('', 'nan', 'none', 'null', 'n/a', 'unassigned')
                  {company_filter}
                GROUP BY "Campaign Name", "Giving Level", "Code"
            """).df()
    except Exception as e:
        print(f"[GiveBright DuckDB Notice]: {e}")
        donor_distinct = None

    if donor_distinct is None or donor_distinct.empty:
        df_donations = df_raw if (df_raw is not None and not df_raw.empty) else load_data(company_id=comp)
        if df_donations is not None and not df_donations.empty and "Campaign Name" in df_donations.columns:
            plat_series = df_donations.get("Platform", pd.Series("", index=df_donations.index)).astype(str).str.lower()
            source_series = df_donations.get("Source", pd.Series("", index=df_donations.index)).astype(str).str.lower()
            gb_mask = plat_series.isin(["givebright", "givebrite"]) | source_series.str.contains("givebright|givebrite", na=False)
            gb_df = df_donations[gb_mask] if gb_mask.any() else df_donations.iloc[0:0]

            if not gb_df.empty:
                c_name = gb_df["Campaign Name"].astype(str).str.strip()
                c_name = c_name[~c_name.str.lower().isin(['nan', 'none', 'n/a', '', 'unassigned'])]
                gl_col = "Giving Level Title" if "Giving Level Title" in gb_df.columns else ("impact_name" if "impact_name" in gb_df.columns else None)
                gl_name = gb_df.loc[c_name.index, gl_col].fillna("").astype(str).str.strip().replace({'nan': '', 'None': '', 'null': '', 'N/A': ''}) if gl_col else pd.Series("", index=c_name.index)
                comm_name = gb_df.loc[c_name.index, "Community Name"].astype(str).str.strip().replace({'nan': 'N/A', '': 'N/A', 'None': 'N/A'}) if "Community Name" in gb_df.columns else pd.Series("N/A", index=c_name.index)
                code_val = gb_df.loc[c_name.index, "Code"].astype(str).str.strip().replace({'nan': 'Unassigned', '': 'Unassigned', 'None': 'Unassigned'}) if "Code" in gb_df.columns else pd.Series("Unassigned", index=c_name.index)
                donor_df = pd.DataFrame({"Campaign Name": c_name, "Giving Level": gl_name, "Code": code_val, "Community Name": comm_name})
                donor_distinct = donor_df.drop_duplicates(subset=["Campaign Name", "Giving Level", "Code"])

    if donor_distinct is not None and not donor_distinct.empty:
        donor_distinct["Campaign Name"] = donor_distinct["Campaign Name"].apply(fix_mojibake).str.strip()
        donor_distinct["Giving Level"] = donor_distinct["Giving Level"].apply(fix_mojibake).str.strip()

        if db_matrix.empty:
            merged_raw = donor_distinct.fillna("Unassigned").reset_index(drop=True)
        else:
            merged = pd.merge(
                donor_distinct,
                db_matrix,
                on=["Campaign Name", "Giving Level", "Code"],
                how="outer",
                suffixes=('', '_db')
            ).fillna("Unassigned")
            if "Campaign URL_db" in merged.columns:
                merged["Campaign URL"] = merged["Campaign URL"].replace("", "").combine_first(merged["Campaign URL_db"])
                merged.drop(columns=["Campaign URL_db"], inplace=True)
            merged_raw = merged
    else:
        merged_raw = db_matrix

    # 3. Canonical Deduplication & Ghost Row Purging
    cleaned_rows = []
    if not merged_raw.empty:
        cname_gl_groups = merged_raw.groupby([
            merged_raw["Campaign Name"].astype(str).str.strip().str.lower(),
            merged_raw["Giving Level"].astype(str).str.strip().str.lower()
        ])
        for (c_low, gl_low), grp in cname_gl_groups:
            assigned_rows = grp[~grp["Code"].astype(str).str.strip().str.upper().isin(["UNASSIGNED", "N/A", "NONE", "NAN", ""])]
            rows_to_process = assigned_rows if not assigned_rows.empty else grp.iloc[0:1]

            code_groups = rows_to_process.groupby(rows_to_process["Code"].astype(str).str.upper())
            for code_up, c_grp in code_groups:
                row = c_grp.iloc[0].copy()
                if "Campaign URL" in c_grp.columns:
                    urls = [u for u in c_grp["Campaign URL"] if str(u).strip() and str(u).strip().startswith("http")]
                    if urls:
                        row["Campaign URL"] = urls[0]
                if "Community Name" in c_grp.columns:
                    comms = [c for c in c_grp["Community Name"] if str(c).strip().lower() not in ["n/a", "unassigned", "none", "nan", ""]]
                    if comms:
                        row["Community Name"] = comms[0]
                cleaned_rows.append(row)

    deduped_df = pd.DataFrame(cleaned_rows) if cleaned_rows else merged_raw

    # 4. Dynamic auto-assignment based on Code mapping
    code_map = get_code_to_classification_map(company_id=comp)
    if code_map and "Code" in deduped_df.columns:
        code_clean = deduped_df["Code"].astype(str).str.strip().str.lower()
        for tc in ["Department", "Office", "Portfolio", "Heading", "Sub-Heading", "Country", "Zakat Eligibility", "Programme Fund", "Fund Code"]:
            if tc in deduped_df.columns:
                target_map = {k: v[tc] for k, v in code_map.items() if tc in v and str(v[tc]).lower() != "unassigned"}
                mask_unassigned = deduped_df[tc].astype(str).str.strip().str.lower().isin(["", "unassigned", "nan", "none"])
                mapped_vals = code_clean.map(target_map)
                fill_mask = mask_unassigned & mapped_vals.notna()
                if fill_mask.any():
                    deduped_df.loc[fill_mask, tc] = mapped_vals[fill_mask]

    if "donation_count" in deduped_df.columns:
        deduped_df["donation_count"] = pd.to_numeric(deduped_df["donation_count"], errors="coerce").fillna(0).astype(int)
    else:
        deduped_df["donation_count"] = 0
    if "total_amount" in deduped_df.columns:
        deduped_df["total_amount"] = pd.to_numeric(deduped_df["total_amount"], errors="coerce").fillna(0.0).round(2)
    else:
        deduped_df["total_amount"] = 0.0

    text_cols = [c for c in deduped_df.columns if c not in ["donation_count", "total_amount", "is_primary"]]
    deduped_df[text_cols] = deduped_df[text_cols].fillna("Unassigned")
    return deduped_df.reset_index(drop=True)


def get_madinah_classification_matrix(df_raw=None, company_id: Optional[str] = "iqra"):
    """Returns Madinah classification matrix DataFrame with unique (Campaign Name, Giving Level, Code) granularity for Iqra."""
    init_classification_db()
    target_cols = ["Heading", "Sub-Heading", "Country", "Code", "Zakat Eligibility", "Department", "Office", "Portfolio", "Programme Fund", "Fund Code"]
    comp = str(company_id or "iqra").lower().strip()

    # 1. Read existing saved rules directly from SQLite
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        where_clause = " WHERE LOWER(COALESCE(company_id, 'iqra')) = ?" if comp != "all" else ""
        params = [comp] if comp != "all" else []
        db_matrix = pd.read_sql_query(f"""
            SELECT 
                campaign_name as "Campaign Name",
                COALESCE(giving_level, '') as "Giving Level",
                COALESCE(code, 'Unassigned') as "Code",
                COALESCE(campaign_url, '') as "Campaign URL",
                COALESCE(department, heading, 'Unassigned') as "Department",
                COALESCE(office, sub_heading, 'Unassigned') as "Office",
                COALESCE(portfolio, '') as "Portfolio",
                COALESCE(programme_fund, '') as "Programme Fund",
                COALESCE(fund_code, '') as "Fund Code",
                COALESCE(heading, department, 'Unassigned') as "Heading",
                COALESCE(sub_heading, office, 'Unassigned') as "Sub-Heading",
                COALESCE(country, 'Unassigned') as "Country",
                COALESCE(zakat_eligibility, 'Unassigned') as "Zakat Eligibility",
                COALESCE(is_primary, 0) as "is_primary"
            FROM madinah_classifications
            {where_clause}
        """, conn, params=params)
    except Exception:
        db_matrix = pd.DataFrame(columns=["Campaign Name", "Giving Level", "Code", "Campaign URL"] + [c for c in target_cols if c != "Code"])
    finally:
        conn.close()

    if not db_matrix.empty:
        db_matrix["Campaign Name"] = db_matrix["Campaign Name"].apply(fix_mojibake).str.strip()
        db_matrix["Giving Level"] = db_matrix["Giving Level"].apply(fix_mojibake).str.strip()

    # 2. Extract distinct (Campaign Name, Giving Level, Code) triples from real Madinah donations
    donor_distinct = None
    try:
        from core.analytics_engine import get_duckdb_connection
        con = get_duckdb_connection()
        if con and os.path.exists(PARQUET_PATH):
            company_filter = f"AND LOWER(COALESCE(\"company_id\", 'iqra')) = '{comp}'" if comp != "all" else ""
            donor_distinct = con.execute(f"""
                SELECT 
                    COALESCE(NULLIF(TRIM("Campaign Name"), ''), 'N/A') as "Campaign Name",
                    CASE 
                        WHEN "Giving Level Title" IS NOT NULL AND LOWER(TRIM("Giving Level Title")) NOT IN ('', 'nan', 'none', 'null', 'n/a') THEN TRIM("Giving Level Title")
                        ELSE ''
                    END as "Giving Level",
                    COALESCE(NULLIF(TRIM("Code"), ''), 'Unassigned') as "Code",
                    MAX(COALESCE(NULLIF(TRIM("Campaign URL"), ''), '')) as "Campaign URL",
                    COUNT(*) as donation_count,
                    SUM(TRY_CAST(REPLACE(REPLACE(COALESCE(CAST("Total Online Donation Gross Amount in Settled Currency" AS VARCHAR), CAST("Donation Amount (in Donation Currency)" AS VARCHAR), CAST("Amount" AS VARCHAR), '0'), '£', ''), ',', '') AS DOUBLE)) as total_amount
                FROM '{PARQUET_PATH.replace(chr(92), '/')}'
                WHERE LOWER(COALESCE("Platform", '')) LIKE '%madinah%'
                  AND "Campaign Name" IS NOT NULL
                  AND LOWER(TRIM(CAST("Campaign Name" AS VARCHAR))) NOT IN ('', 'nan', 'none', 'null', 'n/a', 'unassigned')
                  {company_filter}
                GROUP BY "Campaign Name", "Giving Level", "Code"
            """).df()
    except Exception as e:
        print(f"[Madinah DuckDB Notice]: {e}")
        donor_distinct = None

    if donor_distinct is not None and not donor_distinct.empty:
        donor_distinct["Campaign Name"] = donor_distinct["Campaign Name"].apply(fix_mojibake).str.strip()
        donor_distinct["Giving Level"] = donor_distinct["Giving Level"].apply(fix_mojibake).str.strip()

        if db_matrix.empty:
            merged_raw = donor_distinct.fillna("Unassigned").reset_index(drop=True)
        else:
            merged = pd.merge(
                donor_distinct,
                db_matrix,
                on=["Campaign Name", "Giving Level", "Code"],
                how="outer",
                suffixes=('', '_db')
            ).fillna("Unassigned")
            if "Campaign URL_db" in merged.columns:
                merged["Campaign URL"] = merged["Campaign URL"].replace("", "").combine_first(merged["Campaign URL_db"])
                merged.drop(columns=["Campaign URL_db"], inplace=True)
            merged_raw = merged
    else:
        merged_raw = db_matrix

    # 3. Canonical Deduplication & Ghost Row Purging
    cleaned_rows = []
    if not merged_raw.empty:
        cname_gl_groups = merged_raw.groupby([
            merged_raw["Campaign Name"].astype(str).str.strip().str.lower(),
            merged_raw["Giving Level"].astype(str).str.strip().str.lower()
        ])
        for (c_low, gl_low), grp in cname_gl_groups:
            assigned_rows = grp[~grp["Code"].astype(str).str.strip().str.upper().isin(["UNASSIGNED", "N/A", "NONE", "NAN", ""])]
            rows_to_process = assigned_rows if not assigned_rows.empty else grp.iloc[0:1]

            code_groups = rows_to_process.groupby(rows_to_process["Code"].astype(str).str.upper())
            for code_up, c_grp in code_groups:
                row = c_grp.iloc[0].copy()
                if "Campaign URL" in c_grp.columns:
                    urls = [u for u in c_grp["Campaign URL"] if str(u).strip() and str(u).strip().startswith("http")]
                    if urls:
                        row["Campaign URL"] = urls[0]
                cleaned_rows.append(row)

    deduped_df = pd.DataFrame(cleaned_rows) if cleaned_rows else merged_raw

    # 4. Dynamic auto-assignment based on Code mapping
    code_map = get_code_to_classification_map(company_id=comp)
    if code_map and "Code" in deduped_df.columns:
        code_clean = deduped_df["Code"].astype(str).str.strip().str.lower()
        for tc in ["Department", "Office", "Portfolio", "Heading", "Sub-Heading", "Country", "Zakat Eligibility", "Programme Fund", "Fund Code"]:
            if tc in deduped_df.columns:
                target_map = {k: v[tc] for k, v in code_map.items() if tc in v and str(v[tc]).lower() != "unassigned"}
                mask_unassigned = deduped_df[tc].astype(str).str.strip().str.lower().isin(["", "unassigned", "nan", "none"])
                mapped_vals = code_clean.map(target_map)
                fill_mask = mask_unassigned & mapped_vals.notna()
                if fill_mask.any():
                    deduped_df.loc[fill_mask, tc] = mapped_vals[fill_mask]

    if "donation_count" in deduped_df.columns:
        deduped_df["donation_count"] = pd.to_numeric(deduped_df["donation_count"], errors="coerce").fillna(0).astype(int)
    else:
        deduped_df["donation_count"] = 0
    if "total_amount" in deduped_df.columns:
        deduped_df["total_amount"] = pd.to_numeric(deduped_df["total_amount"], errors="coerce").fillna(0.0).round(2)
    else:
        deduped_df["total_amount"] = 0.0

    text_cols = [c for c in deduped_df.columns if c not in ["donation_count", "total_amount", "is_primary"]]
    deduped_df[text_cols] = deduped_df[text_cols].fillna("Unassigned")
    return deduped_df.reset_index(drop=True)


def save_givebright_classification_matrix(matrix_df, company_id: str = "rethink"):
    """Saves updated GiveBright classification matrix into two-tier architecture."""
    return save_platform_matrix_rules("givebright", matrix_df, company_id=company_id)


def normalize_classification_import_df(raw_df):
    """Standardizes imported column names and auto-fills missing fields from recognized Codes."""
    col_mapping = {}
    for col in raw_df.columns:
        c_clean = str(col).strip().lower().replace("_", " ").replace("-", " ")
        if c_clean in ["campaign", "campaign name", "fundraiser name", "fundraiser", "bank ref", "direct debit ref", "project", "project name"]:
            col_mapping[col] = "Campaign Name"
        elif c_clean in ["community", "community name", "fundraiser by", "platform source"]:
            col_mapping[col] = "Community Name"
        elif c_clean in ["giving level", "giving level title", "giving levels", "impact name", "impact_name", "variant", "option", "tier", "giving_level", "giving_level_title"]:
            col_mapping[col] = "Giving Level"
        elif c_clean in ["code", "campaign code", "project code", "cost code", "item code", "giving level fund code", "giving level campaign code", "fund code", "accounting code"]:
            col_mapping[col] = "Code"
        elif c_clean in ["heading", "main heading", "category", "main category"]:
            col_mapping[col] = "Heading"
        elif c_clean in ["sub heading", "subheading", "sub category", "subcategory", "sub_heading"]:
            col_mapping[col] = "Sub-Heading"
        elif c_clean in ["country", "beneficiary country", "target country"]:
            col_mapping[col] = "Country"
        elif c_clean in ["zakat eligibility", "zakat", "zakat eligibilty", "zakat status", "zakat_eligibility"]:
            col_mapping[col] = "Zakat Eligibility"
        elif c_clean in ["campaign url", "campaign link", "campaign page", "url", "link"]:
            col_mapping[col] = "Campaign URL"
        elif c_clean in ["fundraiser url", "fundraiser link", "fundraiser page"]:
            col_mapping[col] = "Fundraiser URL"

    df_norm = raw_df.rename(columns=col_mapping).copy()

    # Ensure required Campaign Name column exists
    if "Campaign Name" not in df_norm.columns:
        if len(df_norm.columns) > 0:
            df_norm.rename(columns={df_norm.columns[0]: "Campaign Name"}, inplace=True)

    if "Giving Level" not in df_norm.columns:
        df_norm["Giving Level"] = ""

    if "Campaign URL" not in df_norm.columns:
        df_norm["Campaign URL"] = ""

    if "Community Name" not in df_norm.columns:
        df_norm["Community Name"] = "Unassigned"

    return df_norm

