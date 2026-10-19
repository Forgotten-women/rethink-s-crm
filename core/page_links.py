"""
Turns fundraising-page links into stable keys so a link pasted by staff matches the links stored on donations,
whatever form either side is in. Platform-neutral: nothing here is specific to LaunchGood, GiveBrite or Madinah,
so new donation platforms work without code changes.

A key is "<kind>|<platform>|<page>":
  kind      fundraiser (a person's page) | community (team / community page) | campaign (the campaign itself)
  platform  the donation platform, normalised from the Platform column ("launchgood", "givebright", ...).
            For a pasted link it is looked up from the link's website, learned from the donations themselves
            (e.g. donate.iqracharity.org, campaigns.givebrite.com, rethink-charity.givebrite.com -> givebright).
            A website not seen in any donation yet gives "*" (matches that page on any platform).
  page      the page's own identifier - the path segment after /fundraiser/, /communitypage/, ... or the
            campaign's last path segment - plus any NON-tracking query parameters. Matching is always exact:
            a fundraiser page whose address starts like its campaign's (donate.x.org/greater-shaam-project vs
            donate.x.org/fundraiser/isa-greater-shaam-project) is a different key, never merged.

Ignored: scheme, www., letter case, trailing slashes, fragments and tracking parameters (utm_*, src, ref, ...).
"""
import re
import urllib.parse
from typing import Dict, Optional, Tuple

import pandas as pd

_FUNDRAISER_SEGMENTS = {"fundraiser", "fundraisers", "f", "p", "page", "peer", "member"}
_COMMUNITY_SEGMENTS = {"communitypage", "community", "communities", "team", "teams", "group", "groups"}
_NOISE_SEGMENTS = {"campaign", "campaigns", "project", "projects", "c", "v1", "v2", "v3", "v4", "donate", "en", "en-gb", "en-us"}
_TRACKING_PARAMS = re.compile(r"^(utm_.*|src|source|ref|referrer|fbclid|gclid|dclid|msclkid|mc_.*|_ga|_gl|igshid|si|share|s)$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_.~%-]*$")
_PLATFORM_ALIASES = {"givebright": "givebrite"}


def normalise_platform(name: str) -> str:
    p = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
    p = re.sub(r"payouts?$", "", p) or p  # "LaunchGood Payout" -> launchgood
    return _PLATFORM_ALIASES.get(p, p) or "*"


def _host(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def parse_page_link(raw: str, default_platform: str = "*",
                    host_platforms: Optional[Dict[str, str]] = None) -> Optional[Tuple[str, str, str]]:
    """(kind, platform, page) for a link or bare page name, or None if it isn't one."""
    text = (raw or "").strip().strip("<>\"'")
    if not text or text.lower() in ("nan", "none", "null", "<na>") or " " in text:
        return None
    if "://" not in text and ("/" in text or "." in text.split("/")[0]):
        text = "https://" + text
    if "://" not in text:  # bare page name, e.g. how GiveBrite stores some campaign links
        page = urllib.parse.unquote(text).strip("/").lower()
        return ("campaign", default_platform, page) if _SLUG_RE.match(page) else None
    parsed = urllib.parse.urlparse(text)
    host = _host(text)
    platform = (host_platforms or {}).get(host) or default_platform
    segments = [urllib.parse.unquote(s).lower() for s in parsed.path.split("/") if s.strip()]
    params = sorted((k.lower(), v[0].lower()) for k, v in urllib.parse.parse_qs(parsed.query).items()
                    if v and not _TRACKING_PARAMS.match(k.lower()))

    def with_params(page: str, skip: Tuple[str, ...] = ()) -> str:
        rest = [(k, v) for k, v in params if k not in skip]
        return page + ("?" + "&".join(f"{k}={v}" for k, v in rest) if rest else "")

    if segments and segments[-1] == "preview" and dict(params).get("id"):  # e.g. madinah.com/preview?id=zcubed
        return "campaign", platform, with_params(dict(params)["id"], ("id",))
    for i, seg in enumerate(segments[:-1]):
        if seg in _FUNDRAISER_SEGMENTS:
            return "fundraiser", platform, with_params(segments[i + 1])
        if seg in _COMMUNITY_SEGMENTS:
            return "community", platform, with_params(segments[i + 1])
    meaningful = [s for s in segments if s not in _NOISE_SEGMENTS]
    if not meaningful:
        return None
    return "campaign", platform, with_params(meaningful[-1])


def page_key(kind: str, platform: str, page: str) -> str:
    return f"{kind}|{platform}|{page}"


def learn_host_platforms(df: pd.DataFrame) -> Dict[str, str]:
    """website -> platform, learned from the full links stored on donations (most common platform per site)."""
    if "Platform" not in df.columns:
        return {}
    platforms = df["Platform"].map(normalise_platform)
    counts: Dict[Tuple[str, str], int] = {}
    for col in ("Fundraiser URL", "fundraiser_url", "Community URL", "team_url", "Campaign URL", "campaign_url"):
        if col not in df.columns:
            continue
        vals = df[col].dropna().astype(str)
        vals = vals[vals.str.contains("://", regex=False)]
        if vals.empty:
            continue
        hosts = vals.map(_host)
        for (h, p), n in pd.DataFrame({"h": hosts, "p": platforms[vals.index]}).value_counts().items():
            counts[(h, p)] = counts.get((h, p), 0) + int(n)
    best: Dict[str, Tuple[str, int]] = {}
    for (h, p), n in counts.items():
        if h and p != "*" and n > best.get(h, ("", 0))[1]:
            best[h] = (p, n)
    return {h: p for h, (p, _n) in best.items()}


def donation_link_keys(df: pd.DataFrame) -> pd.DataFrame:
    """Per donation: the page keys it was made through (campaign / community / fundraiser page), each as a full
    key and as a platform-agnostic key (for links pasted from a website no donation has used yet)."""
    out = pd.DataFrame(index=df.index)
    platforms = df["Platform"].map(normalise_platform) if "Platform" in df.columns else pd.Series("*", index=df.index)
    sources = {
        "fundraiser": ["Fundraiser URL", "fundraiser_url"],
        "community": ["Community URL", "team_url"],
        "campaign": ["Campaign URL", "campaign_url"],
    }
    for kind, cols in sources.items():
        full = pd.Series(None, index=df.index, dtype=object)
        any_platform = pd.Series(None, index=df.index, dtype=object)
        for col in cols:
            if col not in df.columns:
                continue
            need = full.isna() & df[col].notna()
            if not need.any():
                continue
            pairs = pd.Series(list(zip(df.loc[need, col].astype(str), platforms[need])), index=df.index[need])
            keys_by_pair = {}
            for raw, plat in pd.unique(pairs):  # each distinct link is parsed once
                parsed = parse_page_link(raw, plat)
                if not parsed:
                    continue
                k = kind if kind != "campaign" else parsed[0]  # the column says what kind of page it is
                # the donation's own Platform is authoritative (a site can host several platforms' pages)
                keys_by_pair[(raw, plat)] = (page_key(k, plat, parsed[2]), page_key(k, "*", parsed[2]))
            mapped = pairs.map(keys_by_pair)
            ok = mapped.notna()
            full.loc[ok[ok].index] = mapped[ok].map(lambda t: t[0])
            any_platform.loc[ok[ok].index] = mapped[ok].map(lambda t: t[1])
        out[f"{kind}_key"] = full
        out[f"{kind}_slug_key"] = any_platform
    return out
