"""
Classification by platform campaign / giving-level ID (with names as the fallback).

A donation's campaign is identified by the platform's own reference, so a renamed campaign (or a donation whose
name is spelt slightly differently) still finds its rule:
  GiveBrite  - campaign API id (campaign_uid; older rows: numeric campaign_id -> id, or the page slug)
  Madinah    - campaignId (campaign_id; uploaded rows: their page link -> id via the catalogue)
  LaunchGood - the campaign page key from Campaign URL (LaunchGood exports have no id)
Giving levels: GiveBrite impact id (by name within the campaign) or "title:<normalised title>".

Rules carry campaign_ref / giving_level_ref (scripts/build_campaign_id_catalogue.py). For a donation:
  1. a rule tied to its campaign ID whose campaign name is exactly the donation's (fundraisers can share their parent
     campaign's page) - at its giving level, else its default
  2. the ID's rule for that giving level
  3. the ID's default rule (primary / no giving level)
Donor-specific rules (donor name / email) are not used here - they keep working as before.
Rows without an ID match get None, so the existing name matching fills them.
"""
import re
import sqlite3
import threading
import time
import unicodedata
from collections import Counter, defaultdict
from typing import Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

import pandas as pd

_CACHE: Dict[Tuple[str, str], Tuple[float, dict]] = {}
_LOCK = threading.Lock()
_TTL = 120


def nkey(s) -> str:
    s = str(s or "")
    try:
        from core.data_processor import fix_mojibake
        s = fix_mojibake(s).replace("\x81", "")
    except Exception:
        pass
    a = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    a = re.sub(r"&amp;|&", " and ", a)
    k = re.sub(r"[^a-z0-9]+", " ", a).strip()
    return k or re.sub(r"\s+", " ", s.casefold()).strip()


def slug_of(url) -> str:
    u = str(url or "").strip()
    if not u or u.lower() in ("nan", "none"):
        return ""
    if not u.lower().startswith("http"):
        return u.strip("/").lower()
    p = urlparse(u)
    q = dict(x.split("=", 1) for x in p.query.split("&") if "=" in x)
    if re.search(r"/(preview|campaign/edit)", p.path.lower()) and q.get("id"):
        return unquote(q["id"]).lower()
    parts = [x for x in p.path.split("/") if x]
    return unquote(parts[-1]).lower() if parts else ""


def _blank(v) -> bool:
    return v is None or str(v).strip().lower() in ("", "nan", "none", "n/a", "null")


def _plat(platform: str) -> str:
    return "givebrite" if platform == "givebright" else platform  # old spelling of GiveBrite


def _catalogue(conn: sqlite3.Connection, platform: str, company_id: str) -> dict:
    platform = _plat(platform)
    key = (platform, company_id)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and time.time() - hit[0] < _TTL:
            return hit[1]
    data = {"slug": {}, "level": {}, "num": {}}
    try:
        for ref, slug in conn.execute("SELECT campaign_ref, slug FROM platform_campaign_catalog WHERE platform = ? AND company_id = ?",
                                      (platform, company_id)):
            if slug:
                data["slug"][slug.lower()] = ref
        for ref, lref, name in conn.execute("""SELECT campaign_ref, level_ref, current_name FROM platform_giving_level_catalog
                                               WHERE platform = ? AND company_id = ?""", (platform, company_id)):
            if lref and not str(lref).startswith("title:"):
                data["level"][(ref, nkey(name))] = lref
        if platform in ("givebright", "givebrite"):
            cnt = defaultdict(Counter)
            for uid, num in conn.execute("""SELECT campaign_uid, campaign_id FROM donations WHERE Platform IN ('GiveBright', 'GiveBrite') AND company_id = ?
                                            AND COALESCE(campaign_uid,'') NOT IN ('','nan') AND COALESCE(campaign_id,'') NOT IN ('','nan')""",
                                         (company_id,)):
                cnt[str(num).split(".")[0]][uid] += 1
            data["num"] = {k: v.most_common(1)[0][0] for k, v in cnt.items()}
    except sqlite3.OperationalError:
        pass  # catalogue not built yet: everything falls back to names
    with _LOCK:
        _CACHE[key] = (time.time(), data)
    return data


def invalidate() -> None:
    with _LOCK:
        _CACHE.clear()


def donation_refs(df: pd.DataFrame, platform: str, company_id: str, conn: sqlite3.Connection) -> Tuple[pd.Series, pd.Series]:
    """(campaign_ref, giving_level_ref) for every row; None where the campaign can't be identified."""
    platform = _plat(platform)
    cat = _catalogue(conn, platform, company_id)
    col = lambda c: df[c] if c in df.columns else pd.Series([None] * len(df), index=df.index)
    url = col("Campaign URL").where(col("Campaign URL").notna(), col("campaign_url"))
    refs = []
    if platform in ("givebright", "givebrite"):
        for uid, num, u in zip(col("campaign_uid"), col("campaign_id"), url):
            r = None if _blank(uid) else str(uid)
            if not r and not _blank(num):
                n = str(num).split(".")[0]
                r = n if re.fullmatch(r"[0-9a-f]{24}", n) else cat["num"].get(n)  # API sync stores the hex id here
            refs.append(r or cat["slug"].get(slug_of(u)))
    elif platform == "madinah":
        for cid, u in zip(col("campaign_id"), url):
            refs.append((None if _blank(cid) else str(cid)) or cat["slug"].get(slug_of(u)))
    elif platform == "launchgood":
        refs = [slug_of(u) or None for u in url]
    else:
        refs = [None] * len(df)
    lvl_src = col("impact_name").where(col("impact_name").notna(), col("Giving Level Title")) if platform in ("givebright", "givebrite") else col("Giving Level Title")
    lrefs = []
    for r, gl in zip(refs, lvl_src):
        if not r or _blank(gl):
            lrefs.append("")
            continue
        lrefs.append(cat["level"].get((r, nkey(gl))) or f"title:{nkey(gl)}")
    return pd.Series(refs, index=df.index, dtype=object), pd.Series(lrefs, index=df.index, dtype=object)


def map_fields(df: pd.DataFrame, platform: str, company_id: str, rules: pd.DataFrame, fields, conn: sqlite3.Connection) -> Dict[str, pd.Series]:
    """{field: Series of the ID rule's value (None where no ID rule)} for the classification view columns `fields`."""
    out = {f: pd.Series([None] * len(df), index=df.index, dtype=object) for f in fields}
    if df.empty or rules is None or rules.empty or "campaign_ref" not in rules.columns:
        return out
    r = rules[rules["campaign_ref"].notna()].copy()
    for c in ("donor_name", "donor_email"):
        if c in r.columns:
            r = r[r[c].fillna("").astype(str).str.strip() == ""]
    if r.empty:
        return out
    r["_lref"] = r.get("giving_level_ref", pd.Series("", index=r.index)).fillna("")
    r["_name"] = (r["Campaign Name"] if "Campaign Name" in r.columns else r["campaign_name"]).map(nkey)
    r["_prim"] = pd.to_numeric(r.get("is_primary", 0), errors="coerce").fillna(0)
    r = r.sort_values("_prim", ascending=False)  # primary first, so it wins below
    by_name, by_level, by_camp = {}, {}, {}
    for row in r.to_dict("records"):
        ref, lref, nm = row["campaign_ref"], row["_lref"], row["_name"]
        by_name.setdefault((ref, nm, lref), row)
        if lref:
            by_level.setdefault((ref, lref), row)
        else:
            by_camp.setdefault(ref, row)
    refs, lrefs = donation_refs(df, platform, company_id, conn)
    names = df["Campaign Name"].map(nkey) if "Campaign Name" in df.columns else pd.Series("", index=df.index)
    picked = []
    for ref, lref, nm in zip(refs, lrefs, names):
        if not ref:
            picked.append(None)
            continue
        # ID matching first: specific giving level ref, then campaign default/primary ref
        rule = (by_level.get((ref, lref)) if lref else None) or by_camp.get(ref) \
            or (by_name.get((ref, nm, lref)) if lref else None) or by_name.get((ref, nm, ""))
        picked.append(rule)
    for f in fields:
        out[f] = pd.Series([(p.get(f) if p else None) for p in picked], index=df.index, dtype=object)
    out["_matched"] = pd.Series([p is not None for p in picked], index=df.index)
    out["_campaign_ref"] = refs
    return out


def resolve_code_by_ref(cursor, platform: str, company_id: str, campaign_ref: Optional[str], campaign_name: str = "",
                        giving_level: str = "", conn_for_catalogue: Optional[sqlite3.Connection] = None) -> Tuple[Optional[str], str]:
    """One donation (API syncs): the code of the rule tied to its campaign ID.
    ID matching takes absolute precedence over campaign/giving level text names:
      1. (campaign_ref, giving_level_ref)
      2. (campaign_ref, default / is_primary)
      3. (campaign_ref, exact name + giving level)
      4. (campaign_ref, exact name)
    """
    if not campaign_ref:
        return None, ""
    platform = _plat(platform)
    try:
        rows = cursor.execute("""SELECT campaign_name, COALESCE(giving_level_ref, ''), code, COALESCE(is_primary, 0)
                                 FROM platform_campaign_mappings WHERE platform = ? AND company_id = ? AND campaign_ref = ?
                                 AND COALESCE(donor_name, '') = '' AND COALESCE(donor_email, '') = ''
                                 AND COALESCE(code, '') NOT IN ('', 'Unassigned', 'UNASSIGNED')
                                 ORDER BY COALESCE(is_primary, 0) DESC""", (platform, company_id, campaign_ref)).fetchall()
    except sqlite3.OperationalError:
        return None, ""
    if not rows:
        return None, ""
    lref = ""
    if giving_level and str(giving_level).strip():
        lref = f"title:{nkey(giving_level)}"
        if platform in ("givebright", "givebrite") and conn_for_catalogue is not None:
            lref = _catalogue(conn_for_catalogue, platform, company_id)["level"].get((campaign_ref, nkey(giving_level))) or lref
    nm = nkey(campaign_name)

    # 1. Prioritize ID-based rules (giving level ref, then campaign default)
    # 2. Then name-qualified variants if multiple exist
    for want_name, want_level, tier in (
        (False, True, "ID: giving level"),
        (False, False, "ID: campaign default"),
        (True, True, "ID: exact name + giving level"),
        (True, False, "ID: exact name")
    ):
        if want_level and not lref:
            continue
        for name, lr, code, _p in rows:
            if want_name and nkey(name) != nm:
                continue
            if (lr == lref) if want_level else (lr == ""):
                c_str = code.strip()
                if c_str.startswith("SHAM-"):
                    c_str = "SHM-" + c_str[5:]
                return c_str, tier
    return None, ""

