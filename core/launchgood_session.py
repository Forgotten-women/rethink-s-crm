"""
LaunchGood session renewal.

LaunchGood's sign-in (auth.launchgood.com) issues a 15-minute access JWT plus a refresh JWT that the site keeps
in localStorage ("refreshToken"). The site renews with POST https://api.launchgood.com/v4/auth/refresh
{"refreshToken": ...} -> {"accessToken", "refreshToken"} (the refresh token rotates). We do the same, so a
session captured once keeps working until the refresh token itself expires or is signed out.

Only the platform sync service renews (ensure_fresh_session); the CRM backend only reads the file, so two
processes never spend the same rotating refresh token. A file lock guards it anyway.
"""
import base64
import fcntl
import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

import requests

from core.launchgood_accounts import get_token_file_path

logger = logging.getLogger("launchgood_session")

REFRESH_URL = os.environ.get("LAUNCHGOOD_REFRESH_URL", "https://api.launchgood.com/v4/auth/refresh")
RENEW_WHEN_LEFT_S = 5 * 60
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def jwt_exp(token: Optional[str]) -> float:
    try:
        part = str(token or "").replace("Bearer ", "").strip().split(".")[1]
        return float(json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("exp", 0))
    except Exception:
        return 0.0


def _read(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _write(path: str, data: Dict[str, Any]) -> None:
    tmp = f"{path}.tmp.{os.getpid()}.{int(time.time() * 1000)}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def session_state(company_id: str) -> Dict[str, Any]:
    """What the saved session can still do: access minutes left, refresh token present / minutes left."""
    data = _read(get_token_file_path(company_id))
    now = time.time()
    a_exp = jwt_exp(data.get("bearerToken") or data.get("accessToken"))
    r_tok = data.get("refreshToken")
    r_exp = jwt_exp(r_tok) if r_tok else 0.0
    return {
        "present": bool(data.get("bearerToken") or data.get("accessToken")),
        "access_left_s": (a_exp - now) if a_exp else None,
        "has_refresh": bool(r_tok),
        # a refresh token that isn't a JWT (no exp) is treated as usable until LaunchGood refuses it
        "refresh_left_s": (r_exp - now) if r_exp else (None if r_tok else 0),
        "renew_failed": data.get("renewFailedAt"),
        "renewed_at": data.get("renewedAt"),
    }


def renew_with_refresh_token(refresh: str, headers: Optional[Dict[str, str]] = None) -> Tuple[str, Optional[str]]:
    """Exchanges a LaunchGood refresh token for (new access token, new refresh token). Raises ValueError."""
    h = {k: v for k, v in (headers or {}).items() if k.lower() in ("user-agent", "accept-language")}  # no browser cookies: Cloudflare ties cf_clearance to the browser's own connection and challenges it from here
    h.update({"Content-Type": "application/json", "Accept": "application/json",
              "Origin": "https://www.launchgood.com", "Referer": "https://www.launchgood.com/"})
    h.setdefault("user-agent", DEFAULT_UA)
    for wait in (0, 3, 7):  # Cloudflare sometimes holds a request for a few seconds: two quick retries
        if wait:
            time.sleep(wait)
        r = requests.post(REFRESH_URL, headers=h, json={"refreshToken": refresh.replace("Bearer ", "").strip()}, timeout=20)
        if "json" in (r.headers.get("content-type") or ""):
            break
    try:
        body = r.json() or {}
    except ValueError:
        body = {}
    res = body.get("result") if isinstance(body.get("result"), dict) else body
    access = res.get("accessToken") or res.get("access_token")
    if r.status_code != 200 or not access:
        if "json" not in (r.headers.get("content-type") or ""):
            raise ValueError(f"LaunchGood's firewall blocked the request for a moment ({r.status_code}) - try again in a minute")
        raise ValueError(f"LaunchGood refused the refresh token ({r.status_code}: {str(body.get('message') or r.text)[:120]})")
    return access, (res.get("refreshToken") or res.get("refresh_token"))


def ensure_fresh_session(company_id: str, force: bool = False) -> Tuple[bool, str]:
    """Renews the saved access token when it has under 5 minutes left. Returns (usable, message)."""
    path = get_token_file_path(company_id)
    if not os.path.exists(path):
        return False, "no LaunchGood session saved"
    with open(f"{path}.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = _read(path)
            access = str(data.get("bearerToken") or data.get("accessToken") or "")
            left = jwt_exp(access) - time.time()
            if not force and left > RENEW_WHEN_LEFT_S:
                return True, f"access token valid for {int(left // 60)} more min"
            refresh = str(data.get("refreshToken") or "").replace("Bearer ", "").strip()
            if not refresh:
                return left > 0, ("access token still valid, but no refresh token - it can't be renewed"
                                  if left > 0 else "signed out: the session expired and has no refresh token - paste LaunchGood's refreshToken in Ops > Sessions")
            headers = {k: v for k, v in (data.get("headers") or {}).items()
                       if k.lower() in ("user-agent", "accept-language")}  # no browser cookies: Cloudflare ties cf_clearance to the browser's own connection and challenges it from here
            headers.update({"Content-Type": "application/json", "Accept": "application/json",
                            "Origin": "https://www.launchgood.com", "Referer": "https://www.launchgood.com/"})
            headers.setdefault("user-agent", DEFAULT_UA)
            try:
                r = requests.post(REFRESH_URL, headers=headers, json={"refreshToken": refresh}, timeout=20)
            except requests.RequestException as e:
                return left > 0, f"renewal request failed ({str(e)[:120]}) - will retry"
            body: Dict[str, Any] = {}
            try:
                body = r.json() or {}
            except ValueError:
                pass
            res = body.get("result") if isinstance(body.get("result"), dict) else body
            new_access = res.get("accessToken") or res.get("access_token")
            if r.status_code != 200 or not new_access:
                is_json = "json" in (r.headers.get("content-type") or "")
                if not is_json:
                    # Cloudflare's "Just a moment" page (or an outage) - not a verdict on the token: retry next cycle
                    return left > 0, f"LaunchGood's firewall delayed the renewal ({r.status_code}) - retrying next minute"
                if r.status_code in (400, 401):
                    # LaunchGood refused the refresh token itself: signed out for good until a new capture
                    data["renewFailedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    data["renewFailedDetail"] = f"{r.status_code}: {str(body.get('message') or r.text)[:160]}"
                    _write(path, data)
                return left > 0, f"LaunchGood refused the renewal ({r.status_code})"
            bearer = new_access if new_access.startswith("Bearer ") else f"Bearer {new_access}"
            hdrs = {k: v for k, v in (data.get("headers") or {}).items() if k.lower() != "authorization"}
            hdrs["authorization"] = bearer
            data.update({"bearerToken": bearer, "accessToken": bearer, "headers": hdrs,
                         "renewedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            new_refresh = res.get("refreshToken") or res.get("refresh_token")
            if new_refresh:
                data["refreshToken"] = new_refresh
            # the site cookie "token" carries the access JWT as well; keep it in step
            raw = data.get("rawCookie") or ""
            if raw and "token=" in raw:
                parts = [p.strip() for p in raw.split(";") if p.strip()]
                parts = [f"token={bearer.replace('Bearer ', '')}" if p.split("=", 1)[0] == "token" else p for p in parts]
                data["rawCookie"] = "; ".join(parts)
                hdrs["cookie"] = data["rawCookie"]
            data.pop("renewFailedAt", None)
            data.pop("renewFailedDetail", None)
            _write(path, data)
            logger.info("LaunchGood %s session renewed (valid %d min)", company_id, int((jwt_exp(bearer) - time.time()) // 60))
            return True, "renewed"
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
