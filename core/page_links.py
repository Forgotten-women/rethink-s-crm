"""
Turns fundraising-page links into stable keys so a link pasted by staff matches the links stored on donations,
whatever form either side is in:

    https://www.launchgood.com/v4/campaign/iqra_for_the_liberated_lands        -> campaign  | lg | iqra_for_the_liberated_lands
    https://www.launchgood.com/communitypage/team_7th_goodmayes                -> community | lg | team_7th_goodmayes
    https://donate.iqracharity.org/fundraiser/isa-greater-shaam-project        -> fundraiser| gb | isa-greater-shaam-project
    onewithgaza   (GiveBrite stores campaign links as a bare slug)              -> campaign  | gb | onewithgaza
    https://www.madinah.com/give2gain-campaign?src=internal_website            -> campaign  | md | give2gain-campaign
    https://www.madinah.com/preview?id=zcubed                                  -> campaign  | md | zcubed

Scheme, www., query strings (tracking parameters), fragments, trailing slashes and letter case are ignored.
A key is "<kind>|<family>|<slug>"; family is the platform (lg / gb / md) or "*" when a bare slug was pasted,
which then matches that slug on any platform.
"""
import re
import urllib.parse
from typing import Optional, Tuple

import pandas as pd

KINDS = ("fundraiser", "community", "campaign")
_FUNDRAISER_SEGMENTS = {"fundraiser", "fundraisers", "f", "p", "page"}
_COMMUNITY_SEGMENTS = {"communitypage", "community", "team", "teams"}
_CAMPAIGN_SEGMENTS = {"campaign", "campaigns", "project", "projects", "c", "v4", "donate"}
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_.~%-]*$")

PLATFORM_FAMILY = {"launchgood": "lg", "launchgood payout": "lg", "givebright": "gb", "givebrite": "gb", "madinah": "md"}


def family_for_host(host: str) -> str:
    host = (host or "").lower()
    if "launchgood" in host:
        return "lg"
    if "madinah" in host:
        return "md"
    return "gb" if host else "*"  # GiveBrite runs on the charities' own donate.* domains


def parse_page_link(raw: str, default_family: str = "*") -> Optional[Tuple[str, str, str]]:
    """(kind, family, slug) for a link or bare slug, or None if it isn't one."""
    text = (raw or "").strip().strip("<>\"'")
    if not text or text.lower() in ("nan", "none", "null", "<na>"):
        return None
    if " " in text:
        return None
    if "://" not in text and ("/" in text or "." in text.split("/")[0]):
        text = "https://" + text
    if "://" not in text:  # bare slug, e.g. GiveBrite's stored campaign link
        slug = urllib.parse.unquote(text).strip("/").lower()
        return ("campaign", default_family, slug) if _SLUG_RE.match(slug) else None
    parsed = urllib.parse.urlparse(text)
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    family = family_for_host(host)
    segments = [urllib.parse.unquote(s).lower() for s in parsed.path.split("/") if s.strip()]
    query = urllib.parse.parse_qs(parsed.query)

    if segments and segments[-1] == "preview" and query.get("id"):
        return "campaign", family, query["id"][0].strip().lower()
    for i, seg in enumerate(segments[:-1]):
        nxt = segments[i + 1]
        if seg in _FUNDRAISER_SEGMENTS:
            return "fundraiser", family, nxt
        if seg in _COMMUNITY_SEGMENTS:
            return "community", family, nxt
    meaningful = [s for s in segments if s not in _CAMPAIGN_SEGMENTS]
    if not meaningful:
        return None
    return "campaign", family, meaningful[-1]


def page_key(kind: str, family: str, slug: str) -> str:
    return f"{kind}|{family}|{slug}"


def key_for(raw: str, default_family: str = "*") -> Optional[str]:
    parsed = parse_page_link(raw, default_family)
    return page_key(*parsed) if parsed else None


def donation_link_keys(df: pd.DataFrame) -> pd.DataFrame:
    """Per donation: the page keys it was made through (campaign / community / fundraiser page), each as a full
    key and as a platform-agnostic slug key (for links pasted without a domain)."""
    out = pd.DataFrame(index=df.index)
    families = (df["Platform"].astype(str).str.strip().str.lower().map(PLATFORM_FAMILY).fillna("*")
                if "Platform" in df.columns else pd.Series("*", index=df.index))
    sources = {
        "fundraiser": ["Fundraiser URL", "fundraiser_url"],
        "community": ["Community URL", "team_url"],
        "campaign": ["Campaign URL", "campaign_url"],
    }
    for kind, cols in sources.items():
        full = pd.Series(None, index=df.index, dtype=object)
        slug_only = pd.Series(None, index=df.index, dtype=object)
        for col in cols:
            if col not in df.columns:
                continue
            need = full.isna() & df[col].notna()
            if not need.any():
                continue
            pairs = pd.Series(list(zip(df.loc[need, col].astype(str), families[need])), index=df.index[need])
            parsed_by_pair = {}
            for raw, fam in pd.unique(pairs):  # each distinct link is parsed once
                parsed = parse_page_link(raw, fam)
                if parsed and parsed[0] != kind and kind != "campaign":
                    parsed = (kind, parsed[1], parsed[2])  # e.g. a team slug stored on its own
                if parsed:
                    fam_final = parsed[1] if parsed[1] != "*" else fam
                    parsed_by_pair[(raw, fam)] = (page_key(parsed[0], fam_final, parsed[2]), page_key(parsed[0], "*", parsed[2]))
            mapped = pairs.map(parsed_by_pair)
            ok = mapped.notna()
            full.loc[ok[ok].index] = mapped[ok].map(lambda t: t[0])
            slug_only.loc[ok[ok].index] = mapped[ok].map(lambda t: t[1])
        out[f"{kind}_key"] = full
        out[f"{kind}_slug_key"] = slug_only
    return out
