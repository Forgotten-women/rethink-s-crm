"""Multi-currency FX engine supporting live daily rates and reconciled period pegs."""

import time
import urllib.request
import json
from typing import Dict, Optional

# Reconciled baseline FX rates (USD per 1 unit of native currency) from fund_position.json
PERIOD_RECONCILED_RATES: Dict[str, Dict[str, float]] = {
    "2026-07": {"USD": 1.0, "USDT": 1.0, "GBP": 1.34, "TRY": 0.021, "TL": 0.021, "EUR": 1.14, "ZAR": 0.061, "RAND": 0.061, "EGP": 0.019, "ILS": 0.27, "SYP": 0.000077},
    "2026-08": {"USD": 1.0, "USDT": 1.0, "GBP": 1.34, "TRY": 0.021, "TL": 0.021, "EUR": 1.14, "ZAR": 0.061, "RAND": 0.061, "EGP": 0.019, "ILS": 0.27, "SYP": 0.000077},
    "2026-09": {"USD": 1.0, "USDT": 1.0, "GBP": 1.31, "TRY": 0.02033, "TL": 0.02033, "EUR": 1.119, "ZAR": 0.06026, "RAND": 0.06026, "EGP": 0.019, "ILS": 0.27, "SYP": 0.000077},
    "2026-10": {"USD": 1.0, "USDT": 1.0, "GBP": 1.33, "TRY": 0.02001, "TL": 0.02001, "EUR": 1.12315, "ZAR": 0.05981, "RAND": 0.05981, "EGP": 0.020, "ILS": 0.27, "SYP": 0.000077},
}

DEFAULT_RECONCILED_RATES = PERIOD_RECONCILED_RATES["2026-10"]

_LIVE_CACHE: Dict[str, object] = {
    "rates": None,
    "fetched_at": 0.0,
    "source_date": None,
    "is_live": False,
}
_CACHE_TTL_SECONDS = 3600  # 1 hour


def normalize_currency(cur: Optional[str]) -> str:
    """Normalize currency aliases such as TL -> TRY and RAND -> ZAR."""
    c = (cur or "USD").strip().upper()
    aliases = {
        "TL": "TRY",
        "RAND": "ZAR",
        "EURO": "EUR",
        "US$": "USD",
        "£": "GBP",
        "₺": "TRY",
        "R": "ZAR",
    }
    return aliases.get(c, c)


def _fetch_frankfurter_rates() -> Optional[Dict[str, object]]:
    """Fetch daily mid-market FX rates relative to USD using Frankfurter (ECB)."""
    url = "https://api.frankfurter.app/latest?from=USD&to=GBP,EUR,TRY,ZAR,ILS"
    req = urllib.request.Request(url, headers={"User-Agent": "RethinkCRM-Treasury/1.0"})
    with urllib.request.urlopen(req, timeout=3) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    raw = payload.get("rates", {})
    # Frankfurter returns units of foreign currency per 1 USD -> invert to USD per 1 unit
    rates: Dict[str, float] = dict(DEFAULT_RECONCILED_RATES)
    for code, per_usd in raw.items():
        if per_usd and per_usd > 0:
            usd_per_unit = round(1.0 / float(per_usd), 6)
            rates[code.upper()] = usd_per_unit
            if code.upper() == "TRY":
                rates["TL"] = usd_per_unit
            elif code.upper() == "ZAR":
                rates["RAND"] = usd_per_unit
    rates["USD"] = 1.0
    rates["USDT"] = 1.0
    return {"rates": rates, "date": payload.get("date")}


def get_fx_rates(mode: str = "live", month: Optional[str] = None) -> Dict[str, object]:
    """Return active USD-per-unit FX rates and metadata for 'live' or 'reconciled' mode."""
    if mode == "reconciled":
        period_key = month if month in PERIOD_RECONCILED_RATES else "2026-10"
        return {
            "mode": "reconciled",
            "is_live": False,
            "as_of": f"{period_key}-31" if period_key != "2026-09" else "2026-09-30",
            "source": f"Period Reconciled Peg ({period_key})",
            "rates": dict(PERIOD_RECONCILED_RATES[period_key]),
        }

    now = time.time()
    if _LIVE_CACHE["rates"] and (now - float(_LIVE_CACHE["fetched_at"])) < _CACHE_TTL_SECONDS:
        return {
            "mode": "live",
            "is_live": bool(_LIVE_CACHE["is_live"]),
            "as_of": _LIVE_CACHE["source_date"],
            "source": "ECB / Frankfurter Daily Rate" if _LIVE_CACHE["is_live"] else "Cached Baseline (Offline Fallback)",
            "rates": dict(_LIVE_CACHE["rates"]),  # type: ignore[arg-type]
        }

    try:
        fetched = _fetch_frankfurter_rates()
        if fetched:
            _LIVE_CACHE["rates"] = fetched["rates"]
            _LIVE_CACHE["source_date"] = fetched["date"]
            _LIVE_CACHE["fetched_at"] = now
            _LIVE_CACHE["is_live"] = True
            return {
                "mode": "live",
                "is_live": True,
                "as_of": fetched["date"],
                "source": "ECB / Frankfurter Daily Rate",
                "rates": dict(fetched["rates"]),  # type: ignore[arg-type]
            }
    except Exception:
        pass

    # Graceful fallback to Oct 31 reconciled peg if external HTTP fails
    _LIVE_CACHE["rates"] = dict(DEFAULT_RECONCILED_RATES)
    _LIVE_CACHE["source_date"] = "2026-10-31"
    _LIVE_CACHE["fetched_at"] = now - (_CACHE_TTL_SECONDS - 300)  # retry in 5m
    _LIVE_CACHE["is_live"] = False
    return {
        "mode": "live",
        "is_live": False,
        "as_of": "2026-10-31",
        "source": "Oct 31 Baseline (Live FX Offline)",
        "rates": dict(DEFAULT_RECONCILED_RATES),
    }


def convert_amount(amount: float, from_cur: str, to_cur: str, rates: Dict[str, float]) -> float:
    """Convert numeric amount between currencies using USD-based rate dictionary."""
    if not amount:
        return 0.0
    fc = normalize_currency(from_cur)
    tc = normalize_currency(to_cur)
    if fc == tc:
        return float(amount)
    from_usd_rate = rates.get(fc, DEFAULT_RECONCILED_RATES.get(fc, 1.0))
    to_usd_rate = rates.get(tc, DEFAULT_RECONCILED_RATES.get(tc, 1.0))
    if to_usd_rate <= 0:
        to_usd_rate = 1.0
    usd_val = float(amount) * float(from_usd_rate)
    return usd_val / float(to_usd_rate)
