"""
Hidden operations console API (super admins only): structured logs, platform/session health and
manual session upload for the GiveBrite / Madinah integrations.
"""
import base64
import datetime
import json
import os
import sqlite3
import subprocess
import time
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.api.auth import require_super_admin
from config.settings import LOCAL_DB_PATH
from core.event_log import log_event, query_axiom, query_local, shipping_status

router = APIRouter(prefix="/api/ops", tags=["Ops Console"], dependencies=[Depends(require_super_admin)])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOKEN_FILES = {
    "givebrite": os.path.join(BASE_DIR, ".givebrite_token.json"),
    "madinah": os.path.join(BASE_DIR, ".madinah_token.json"),
}
HEALTH_FILE = os.path.join(BASE_DIR, "data_cache", "platform_health.json")
SYNC_FILE = os.path.join(BASE_DIR, "data_cache", "platform_sync_data.json")
GIVEBRITE_CHARITY_ID = os.environ.get("GIVEBRITE_IQRA_CHARITY_ID", "68625e0d6d1a99441e34e2ea")
MADINAH_APIM_BASE = "https://md-backend-prod-api.azure-api.net"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _jwt_exp(token: str) -> Optional[datetime.datetime]:
    try:
        part = (token or "").replace("Bearer ", "").strip().split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return datetime.datetime.fromtimestamp(float(payload["exp"]), tz=datetime.timezone.utc)
    except Exception:
        return None


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _age_minutes(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return round((_now() - dt).total_seconds() / 60, 1)
    except Exception:
        return None


def _token_info(platform: str) -> Dict[str, Any]:
    data = _read_json(TOKEN_FILES[platform])
    info: Dict[str, Any] = {"present": bool(data.get("accessToken")), "retrieved_at": data.get("retrievedAt"),
                            "captured_by": data.get("capturedBy")}
    for key, label in (("accessToken", "access"), ("refreshToken", "refresh")):
        if data.get(key):
            exp = _jwt_exp(data[key])
            info[f"{label}_expires_at"] = exp.isoformat() if exp else None
            info[f"{label}_minutes_left"] = round((exp - _now()).total_seconds() / 60, 1) if exp else None
    return info


def _live_check(platform: str, token: Optional[str] = None) -> Dict[str, Any]:
    """One read-only request with the given (or stored) token. Never refreshes or logs in."""
    if token is None:
        token = (_read_json(TOKEN_FILES[platform]).get("accessToken") or "").strip()
    if not token:
        return {"ok": False, "detail": "No stored token"}
    auth = token if token.startswith("Bearer ") else f"Bearer {token}"
    try:
        if platform == "madinah":
            r = requests.get(f"{MADINAH_APIM_BASE}/campaign-server/api/v1/campaign/donations/latest?page=1&limit=1",
                             headers={"Authorization": auth, "Accept": "application/json",
                                      "Origin": "https://www.madinah.com"}, timeout=12)
        else:
            r = requests.get("https://api-dashboard.givebrite.com/v1/dashboard/donations",
                             params={"charity_id": GIVEBRITE_CHARITY_ID, "page": 1, "limit": 1},
                             headers={"Authorization": auth, "Accept": "application/json",
                                      "Origin": "https://dashboard.givebrite.com"}, timeout=12)
        return {"ok": r.status_code == 200, "http_status": r.status_code,
                "detail": "API answered normally" if r.status_code == 200 else r.text[:200]}
    except Exception as e:
        return {"ok": False, "detail": str(e)[:200]}


def _service_state(name: str) -> Dict[str, Any]:
    try:
        active = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=5).stdout.strip()
        since = subprocess.run(["systemctl", "show", "-p", "ActiveEnterTimestamp", "--value", name],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return {"name": name, "active": active, "since": since}
    except Exception as e:
        return {"name": name, "active": "unknown", "detail": str(e)[:120]}


def _platform_status(platform: str, health: Dict[str, Any], live: bool) -> Dict[str, Any]:
    h = health.get(platform, {}) if isinstance(health, dict) else {}
    token = _token_info(platform)
    issues: List[str] = []
    state = "ok"
    last_ok_age = _age_minutes(h.get("last_ok_at"))
    if last_ok_age is None:
        issues.append("No successful sync recorded yet")
        state = "warning"
    elif last_ok_age > 15:
        issues.append(f"Last successful sync {int(last_ok_age)} min ago")
        state = "down"
    elif last_ok_age > 5:
        issues.append(f"Last successful sync {int(last_ok_age)} min ago")
        state = "warning"
    if h.get("consecutive_failures", 0) >= 3:
        issues.append(f"{h['consecutive_failures']} failed cycles in a row: {h.get('last_error') or ''}".strip())
        state = "down"
    if not token["present"]:
        issues.append("No session token stored")
        state = "down"
    elif (token.get("access_minutes_left") or 0) <= 0:
        issues.append("Access token expired")
        state = "down" if platform == "givebrite" or (token.get("refresh_minutes_left") or 0) <= 0 else state
    if platform == "madinah" and token.get("refresh_minutes_left") is not None:
        left_h = token["refresh_minutes_left"] / 60
        if left_h <= 0:
            issues.append("Refresh token expired - capture a new Madinah session")
            state = "down"
        elif left_h < 48:
            issues.append(f"Refresh token expires in {left_h:.0f}h (renews automatically if syncing works)")
            state = "warning" if state == "ok" else state
    if h.get("last_token_refresh_error"):
        issues.append(f"Last session renewal failed: {h['last_token_refresh_error']}")
        state = "warning" if state == "ok" else state
    out = {"platform": platform, "state": state, "issues": issues, "token": token, "sync": h}
    if live:
        out["live_check"] = _live_check(platform)
        if not out["live_check"]["ok"]:
            out["state"] = "down"
            out["issues"].append(f"Live API check failed ({out['live_check'].get('http_status', 'error')})")
    return out


def _outlook_status() -> List[Dict[str, Any]]:
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT company_id, connected_email, refresh_token, token_expiry, subscription_expiration "
                            "FROM sponsorship_outlook_auth").fetchall()
        out = []
        for r in rows:
            last_send = conn.execute(
                "SELECT ts, event, message FROM app_event_logs WHERE category = 'email' AND company_id = ? "
                "AND event IN ('email.sent', 'email.failed') ORDER BY ts DESC LIMIT 1", (r["company_id"],)).fetchone() \
                if conn.execute("SELECT name FROM sqlite_master WHERE name = 'app_event_logs'").fetchone() else None
            out.append({
                "company_id": r["company_id"], "connected": bool(r["refresh_token"]),
                "mailbox": r["connected_email"], "subscription_expires": r["subscription_expiration"],
                "last_send": dict(last_send) if last_send else None,
                "state": "ok" if r["refresh_token"] else "down",
            })
        return out
    finally:
        conn.close()


@router.get("/status")
def ops_status(live: bool = Query(False)):
    health = _read_json(HEALTH_FILE)
    sync = _read_json(SYNC_FILE)
    platforms = [_platform_status(p, health, live) for p in ("givebrite", "madinah")]
    services = [_service_state("platform-sync.service")]
    for s in services:
        if s["active"] != "active":
            for p in platforms:
                p["state"] = "down"
                p["issues"].insert(0, "platform-sync service is not running")
    errors_24h = query_local(level="error", since=(_now() - datetime.timedelta(hours=24)).isoformat(), limit=1)["total"]
    overall = "down" if any(p["state"] == "down" for p in platforms) else (
        "warning" if any(p["state"] == "warning" for p in platforms) else "ok")
    return {
        "checked_at": _now().isoformat(),
        "overall": overall,
        "platforms": platforms,
        "services": services,
        "sync_heartbeat": (sync.get("meta") or {}).get("last_synced_at"),
        "outlook": _outlook_status(),
        "logging": {**shipping_status(), "errors_last_24h": errors_24h},
    }


@router.get("/logs")
def ops_logs(category: Optional[str] = None, level: Optional[str] = None, company_id: Optional[str] = None,
             search: Optional[str] = None, event: Optional[str] = None, since: Optional[str] = None,
             until: Optional[str] = None, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
             source: str = Query("local"), apl: Optional[str] = None, since_hours: int = Query(24, ge=1, le=720)):
    if source == "axiom":
        if not apl:
            raise HTTPException(status_code=400, detail="Provide an APL query for the Axiom source.")
        try:
            return {"source": "axiom", "result": query_axiom(apl, since_hours)}
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e))
    return {"source": "local", **query_local(category, level, company_id, search, since, until, event, limit, offset)}


class SessionUpload(BaseModel):
    accessToken: str
    refreshToken: Optional[str] = None
    account: Optional[str] = None
    source: Optional[str] = "manual-capture"


@router.get("/platform-sessions")
def list_sessions():
    return {p: _token_info(p) for p in TOKEN_FILES}


@router.post("/platform-sessions/{platform}")
def upload_session(platform: str, payload: SessionUpload, user: dict = Depends(require_super_admin)):
    """Stores a manually captured session after proving it works against the platform API."""
    platform = platform.lower()
    if platform not in TOKEN_FILES:
        raise HTTPException(status_code=404, detail="Unknown platform")
    access = payload.accessToken.strip()
    access = access if access.startswith("Bearer ") else f"Bearer {access}"
    exp = _jwt_exp(access)
    if not exp or exp <= _now():
        raise HTTPException(status_code=400, detail="That access token is not a valid, unexpired JWT.")
    refresh = None
    if payload.refreshToken:
        refresh = payload.refreshToken.strip()
        refresh = refresh if refresh.startswith("Bearer ") else f"Bearer {refresh}"

    # Verify before overwriting the working session.
    path = TOKEN_FILES[platform]
    existing = _read_json(path)
    candidate = dict(existing)
    candidate.update({"accessToken": access, "retrievedAt": _now().isoformat(),
                      "capturedBy": f"{user.get('email')} via {payload.source}"})
    if refresh:
        candidate["refreshToken"] = refresh
    if payload.account:
        candidate.setdefault("user", {})["email"] = payload.account
    check = _live_check(platform, access)
    if not check["ok"]:
        log_event("session.upload_rejected", category="session", level="warning", actor=user.get("email"),
                  platform=platform, http_status=check.get("http_status"), detail=check.get("detail"))
        raise HTTPException(status_code=400, detail=f"{platform} rejected that token ({check.get('http_status')}): {check.get('detail')}")

    fd_path = f"{path}.tmp.{os.getpid()}.{int(time.time() * 1000)}"
    fd = os.open(fd_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(candidate, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(fd_path, path)
    log_event("session.uploaded", category="session", actor=user.get("email"), platform=platform,
              expires_at=exp.isoformat(), has_refresh=bool(refresh), source=payload.source)
    return {"status": "success", "platform": platform, "access_expires_at": exp.isoformat(), "verified": True}
