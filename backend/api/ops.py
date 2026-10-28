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

import re
import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from backend.api.auth import require_super_admin
from config.settings import LOCAL_DB_PATH, GIVEBRITE_CHARITY_IDS
from core.event_log import log_event, query_axiom, query_local, shipping_status

async def _ops_access(request: Request) -> Dict[str, Any]:
    """Super admins: the whole console. People given the activity log (logs.view, granted only by a super admin):
    the log view only, limited to their charities."""
    from backend.api.auth import get_current_user
    from core.rbac import companies_with
    user = await get_current_user(request, None, None)
    request.state.api_user = user
    if user.get("role") == "super_admin":
        return user
    endpoint = request.scope.get("endpoint")
    name = getattr(endpoint, "__name__", "")
    if name == "ops_logs" and companies_with(user, "logs.view"):
        return user
    if name == "ops_status" and companies_with(user, "status.view"):
        return user
    raise HTTPException(status_code=403, detail="This operation is restricted to Super Admin accounts.")


router = APIRouter(prefix="/api/ops", tags=["Ops Console"], dependencies=[Depends(_ops_access)])
sync_router = APIRouter(prefix="/api/ops/sync-helper", tags=["Ops Sync Helper"])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOKEN_FILES = {
    "givebrite": os.path.join(BASE_DIR, ".givebrite_token.json"),
    "givebrite_iqra": os.path.join(BASE_DIR, ".givebrite_token.json"),
    "givebrite_rethink": os.path.join(BASE_DIR, ".givebrite_rethink_token.json"),
    "madinah": os.path.join(BASE_DIR, ".madinah_token.json"),
    "launchgood_rethink": os.path.join(BASE_DIR, "config", "launchgood_tokens_rethink.json"),
    "launchgood_iqra": os.path.join(BASE_DIR, "config", "launchgood_tokens_iqra.json"),
}
HEALTH_FILE = os.path.join(BASE_DIR, "data_cache", "platform_health.json")
SYNC_FILE = os.path.join(BASE_DIR, "data_cache", "platform_sync_data.json")
GIVEBRITE_CHARITY_ID = GIVEBRITE_CHARITY_IDS.get("iqra", "")
# Madinah moved off Azure API Management (md-backend-prod-api.azure-api.net stopped resolving on 27 Oct 2026);
# each server now has its own host, as used by www.madinah.com.
MADINAH_MAIN_API = "https://api-main.madinah.com/api/v1"
MADINAH_CAMPAIGN_API = "https://api-campaigns.madinah.com/api/v1"
MADINAH_DASHBOARD_API = "https://api-dashboard.madinah.com/api/v1"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _jwt_claims(token: str) -> Dict[str, Any]:
    try:
        part = (token or "").replace("Bearer ", "").strip().split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))) or {}
    except Exception:
        return {}


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
    has_cookies = bool(data.get("rawCookie") or data.get("cookies") or data.get("authCookies"))
    info: Dict[str, Any] = {
        "present": bool(data.get("accessToken") or data.get("bearerToken")),
        "retrieved_at": data.get("retrievedAt") or data.get("savedAt"),
        "captured_by": data.get("capturedBy"),
        "has_refresh": bool(data.get("refreshToken")),
    }
    for key, label in (("accessToken", "access"), ("refreshToken", "refresh")):
        token_val = data.get(key) or (data.get("bearerToken") if key == "accessToken" else None)
        if token_val:
            exp = _jwt_exp(token_val)
            left_m = round((exp - _now()).total_seconds() / 60, 1) if exp else None
            info[f"{label}_expires_at"] = exp.isoformat() if exp else None
            info[f"{label}_minutes_left"] = left_m
    return info


def _live_check(platform: str, token: Optional[str] = None) -> Dict[str, Any]:
    """One read-only request with the given (or stored) token. Never refreshes or logs in."""
    if platform == "paysuite":
        try:
            from core.paysuite_client import PaySuiteClient
            # One quick attempt: the sync client's 30 s x 3 retries could hold the Ops page for ~90 s
            client = PaySuiteClient(timeout=8, max_retries=1)
            if not client.is_configured():
                return {"ok": False, "detail": "PaySuite API key not configured in environment"}
            info = client.get_client_info()
            return {
                "ok": bool(info),
                "http_status": 200 if info else 500,
                "detail": f"Access PaySuite DDCMS v3 answered normally (Client: {client.client_code})" if info else "Empty response"
            }
        except Exception as e:
            return {"ok": False, "detail": str(e)[:200]}

    if platform in ("launchgood_rethink", "launchgood_iqra"):
        cid = "rethink" if "rethink" in platform else "iqra"
        try:
            from core.launchgood_client import LaunchGoodClient
            client = LaunchGoodClient(company_id=cid)
            if not client.is_configured():
                return {"ok": False, "detail": f"LaunchGood session not configured for {cid.title()}"}
            user_info = client.get_current_user()
            if not _lg_signed_in(user_info):
                return {"ok": False, "http_status": 401, "detail": "LaunchGood answered as a signed-out guest - the saved session has expired"}
            name = (user_info.get("result") or {}).get("name") or "Connected"
            return {"ok": True, "http_status": 200, "detail": f"LaunchGood API answered normally ({name})"}
        except Exception as e:
            return {"ok": False, "detail": str(e)[:200]}

    if token is None:
        token = (_read_json(TOKEN_FILES.get(platform, "")).get("accessToken") or "").strip()
    if not token:
        return {"ok": False, "detail": "No stored token"}
    auth = token if token.startswith("Bearer ") else f"Bearer {token}"
    try:
        if platform == "madinah":
            r = requests.get(f"{MADINAH_CAMPAIGN_API}/campaign/donations/latest?page=1&limit=1",
                             headers={"Authorization": auth, "Accept": "application/json",
                                      "Origin": "https://www.madinah.com"}, timeout=12)
        else:
            cid = "rethink" if "rethink" in platform else "iqra"
            charity_id = GIVEBRITE_CHARITY_IDS.get(cid, GIVEBRITE_CHARITY_ID)
            r = requests.get("https://api-dashboard.givebrite.com/v1/dashboard/donations",
                             params={"charity_id": charity_id, "page": 1, "limit": 1},
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


def _lg_signed_in(user_info: Dict[str, Any]) -> bool:
    """LaunchGood answers /user/currentUser with 200 even when signed out - then the result holds only site settings
    (application, environment, currencies...) and no user. Only a result with the user's own fields is signed in."""
    res = (user_info or {}).get("result") or {}
    return isinstance(res, dict) and any(k in res for k in ("id", "userId", "user_id", "email", "user", "firstName", "first_name", "name", "accounts"))


LG_CAPTURE_HINT = "paste LaunchGood's `refreshToken` (browser > F12 > Application > Local storage) in Ops > Sessions, or run `node scripts/capture_platform_session.js {platform}` on your PC"


def _platform_status(platform: str, health: Dict[str, Any], live: bool) -> Dict[str, Any]:
    if platform == "paysuite":
        from core.paysuite_client import get_paysuite_client
        from core.paysuite_sync import get_sync_state
        client = get_paysuite_client()
        configured = client.is_configured()
        h = health.get("paysuite", {}) if isinstance(health, dict) else {}
        issues: List[str] = []
        state = "ok"
        if not configured:
            issues.append("ACCESSPAYSUITE_API_KEY not configured in .env")
            state = "down"

        try:
            last_sync = get_sync_state("last_sync_at") or h.get("last_ok_at")
        except Exception as e:  # one card must never take the whole status page down (was a 500)
            last_sync = h.get("last_ok_at")
            issues.append(f"Sync state unreadable: {str(e)[:120]}")
            state = "warning" if state == "ok" else state
        last_ok_age = _age_minutes(last_sync)
        if last_ok_age is None:
            issues.append("No sync recorded yet")
            state = "warning" if state == "ok" else state
        elif last_ok_age > 180:  # Hourly schedule -> warning after 3 hours
            issues.append(f"Last successful sync {int(last_ok_age)} min ago")
            state = "warning" if state == "ok" else state

        if h.get("consecutive_failures", 0) >= 3:
            issues.append(f"{h['consecutive_failures']} failed sync cycles in a row")
            state = "down"

        try:
            if get_sync_state("crm_apply_approved_rethink") != "true":
                issues.append("Collections are synced but not yet added to the CRM (awaiting migration approval)")
                state = "warning" if state == "ok" else state
        except Exception:
            pass

        # Check for unassigned mandates in needs classification
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=2.0)
            unassigned_count = conn.execute("""
                SELECT COUNT(*) FROM platform_campaign_mappings 
                WHERE platform = 'paysuite' AND LOWER(COALESCE(company_id, 'rethink')) = 'rethink'
                  AND UPPER(TRIM(COALESCE(code, ''))) IN ('', 'UNASSIGNED', 'NONE', 'NAN')
            """).fetchone()[0]
            conn.close()
            if unassigned_count > 0:
                issues.append(f"{unassigned_count} PaySuite mandate(s) need classification")
        except Exception:
            pass

        sync_data = dict(h)
        if last_sync:
            sync_data["last_sync_at"] = last_sync

        out = {
            "platform": "paysuite",
            "name": "Access PaySuite (Rethink)",
            "state": state,
            "issues": issues,
            "token": {"present": configured, "captured_by": "API Key (.env)"},
            "sync": sync_data
        }
        if live:
            out["live_check"] = _live_check("paysuite")
            if not out["live_check"]["ok"]:
                out["state"] = "down"
                out["issues"].append(f"Live API check failed ({out['live_check'].get('http_status', 'error')})")
        return out

    if platform in ("stripe", "stripe_rethink"):
        from core.stripe_accounts import is_connected, stripe_key
        configured = is_connected("rethink")
        issues: List[str] = []
        state = "ok" if configured else "down"
        if not configured:
            issues.append("RETHINK_STRIPE_SECRET_KEY missing in .env")

        last_sync = None
        # The ledger poll's own health record (runs every minute); the payout report time is shown separately
        sync_data = dict((health.get("stripe") or {}) if isinstance(health, dict) else {})
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=2.0)
            row = conn.execute("""
                SELECT MAX(created_at) FROM stripe_payout_reports WHERE LOWER(COALESCE(company_id, 'rethink')) = 'rethink'
            """).fetchone()
            if row and row[0]:
                last_sync = row[0]
                sync_data["last_payout_reconciled_at"] = last_sync

            unassigned_count = conn.execute("""
                SELECT COUNT(*) FROM platform_campaign_mappings 
                WHERE platform = 'stripe' AND LOWER(COALESCE(company_id, 'rethink')) = 'rethink'
                  AND UPPER(TRIM(COALESCE(code, ''))) IN ('', 'UNASSIGNED', 'NONE', 'NAN')
            """).fetchone()[0]
            if unassigned_count > 0:
                issues.append(f"{unassigned_count} Stripe link(s) need classification")
            conn.close()
        except Exception:
            pass

        out = {
            "platform": "stripe_rethink",
            "name": "Stripe (Rethink)",
            "state": state,
            "issues": issues,
            "token": {"present": configured, "captured_by": "API Key (.env)"},
            "sync": sync_data
        }
        if live and configured:
            try:
                import stripe
                stripe.api_key = stripe_key("rethink")
                stripe.Balance.retrieve()
                out["live_check"] = {"ok": True, "detail": "Stripe API reachable, credentials valid"}
            except Exception as e:
                out["live_check"] = {"ok": False, "detail": str(e)[:120]}
                out["state"] = "down"
                out["issues"].append(f"Live Stripe check failed: {str(e)[:80]}")
        return out

    if platform in ("launchgood_rethink", "launchgood_iqra"):
        cid = "rethink" if "rethink" in platform else "iqra"
        from core.launchgood_accounts import get_session, is_connected, get_account_id
        session = get_session(cid)
        configured = is_connected(cid)
        account_id = get_account_id(cid)
        issues: List[str] = []
        token_info = {"present": configured}
        
        hint = LG_CAPTURE_HINT.format(platform=platform)
        if not configured:
            if cid == "iqra":
                state = "not_configured"
                issues.append(f"Not set up: Iqra's LaunchGood donations come from uploaded files. To sync them automatically, {hint}.")
            else:
                state = "down"
                issues.append(f"No LaunchGood session saved - {hint}.")
        else:
            from core.launchgood_session import session_state
            st = session_state(cid)
            token_info["captured_at"] = (session or {}).get("savedAt")
            token_info["renewed_at"] = st.get("renewed_at")
            token_info["has_refresh"] = bool(st["has_refresh"]) and not st.get("renew_failed")
            a_left = st.get("access_left_s")
            token_info["access_minutes_left"] = round(a_left / 60, 1) if a_left is not None else None
            refresh_ok = token_info["has_refresh"] and (st.get("refresh_left_s") is None or st["refresh_left_s"] > 0)
            r_left = st.get("refresh_left_s")
            if token_info["has_refresh"] and r_left:
                token_info["refresh_expires_at"] = (_now() + datetime.timedelta(seconds=r_left)).isoformat()
                if 0 < r_left < 25 * 86400:  # each renewal issues a fresh 30-day token: < 25 days left means renewals stopped
                    issues.append(f"LaunchGood renewals have stopped - the saved sign-in ends in {int(r_left // 86400)} days {int(r_left % 86400 // 3600)} h. Check the error below, or paste a fresh refreshToken.")
            if a_left is not None and a_left > 0:
                state = "ok"
                token_info["status_text"] = "Active (renews itself)" if refresh_ok else f"{int(a_left // 60)} min left"
                if not refresh_ok:
                    issues.append(f"This session can't renew itself, so it stops in {int(a_left // 60)} min. For a lasting connection, {hint}.")
            elif refresh_ok:
                state = "warning"
                token_info["status_text"] = "Renewing"
                issues.append("The 15-minute access token ran out; the sync service renews it on its next cycle (within a minute).")
            else:
                state = "down"
                token_info["status_text"] = "Signed out"
                when = ""
                exp = _jwt_exp((session or {}).get("bearerToken") or "")
                if exp:
                    when = f" since {exp.strftime('%d %b %H:%M')} UTC"
                why = " (LaunchGood refused the renewal)" if st.get("renew_failed") else ""
                issues.append(f"Signed out of LaunchGood{when}{why} - donations aren't syncing. To reconnect, {hint}.")

        last_sync = None
        sync_data = {}
        conn = None
        try:
            conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=1.0)
            row = conn.execute("""
                SELECT MAX("Created Date (UTC)"), MAX("Created Time (UTC)")
                FROM donations 
                WHERE company_id = ? 
                  AND (Platform = 'LaunchGood' OR Source LIKE '%LaunchGood%')
                  AND "Created Date (UTC)" LIKE '20%'
            """, (cid,)).fetchone()
            if row and row[0] and "nan" not in str(row[0]).lower():
                d_val = str(row[0]).strip()
                t_val = str(row[1] or "00:00:00").strip()
                sync_data["last_ingested_at"] = f"{d_val}T{t_val}Z"
        except Exception:
            pass
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        h = health.get(platform, {}) if isinstance(health, dict) else {}
        if isinstance(h, dict) and h:
            for k, v in h.items():
                if v is not None:
                    if k == "last_ingested_at" and (not v or str(v).lower() in ("nan", "none", "")):
                        continue
                    sync_data[k] = v
            if h.get("last_ok_at"):
                last_sync = h["last_ok_at"]
                sync_data["last_ok_at"] = h["last_ok_at"]
            elif h.get("last_sync_at"):
                last_sync = h["last_sync_at"]
                sync_data["last_sync_at"] = h["last_sync_at"]
            if configured and state == "ok" and h.get("consecutive_failures", 0) >= 3:
                state = "warning"
                issues.append(f"Donation sync failed {h['consecutive_failures']} times in a row: {h.get('last_error') or ''}".strip())

        out = {
            "platform": platform,
            "name": f"LaunchGood ({cid.title()})",
            "state": state,
            "issues": issues,
            "token": token_info,
            "sync": sync_data
        }
        if live and configured:
            try:
                from core.launchgood_client import LaunchGoodClient
                client = LaunchGoodClient(company_id=cid)
                user_info = client.get_current_user()
                if not _lg_signed_in(user_info):
                    raise RuntimeError("LaunchGood answered as a signed-out guest (session expired)")
                name = (user_info.get("result") or {}).get("name") or "Connected"
                out["live_check"] = {"ok": True, "detail": f"LaunchGood API connected ({name})"}
            except Exception as e:
                out["live_check"] = {"ok": False, "detail": str(e)[:120]}
                out["state"] = "down"
                out["issues"].append(f"Live API check failed: {str(e)[:80]}")
        return out

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
        state = "down" if "givebrite" in platform or (token.get("refresh_minutes_left") or 0) <= 0 else state
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
    sync_data = dict(h)
    if not sync_data.get("last_ingested_at") or str(sync_data.get("last_ingested_at")).lower() in ("nan", "none", ""):
        try:
            cid = "rethink" if "rethink" in platform else "iqra"
            src = "givebrite" if "givebrite" in platform else "madinah"
            conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=1.0)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT MAX("Created Date (UTC)"), MAX("Created Time (UTC)")
                FROM donations
                WHERE company_id = ? AND Source LIKE ?
            """, (cid, f"%{src}%"))
            row = cursor.fetchone()
            if row and row[0] and "nan" not in str(row[0]).lower():
                d_val = str(row[0]).strip()
                t_val = str(row[1] or "00:00:00").strip()
                sync_data["last_ingested_at"] = f"{d_val}T{t_val}Z"
            conn.close()
        except Exception:
            pass

    platform_names = {
        "givebrite_iqra": "GiveBrite (Iqra)",
        "givebrite_rethink": "GiveBrite (Rethink)",
        "madinah": "Madinah (Iqra)",
    }
    p_name = platform_names.get(platform, platform)
    out = {"platform": platform, "name": p_name, "state": state, "issues": issues, "token": token, "sync": sync_data}
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
        from backend.api.mailbox import _gmail_row, provider
        rows = [dict(r) for r in conn.execute("SELECT company_id, connected_email, refresh_token, token_expiry, subscription_expiration "
                                              "FROM sponsorship_outlook_auth").fetchall()]
        have = {r["company_id"] for r in rows}
        rows += [{"company_id": c, "connected_email": None, "refresh_token": None, "subscription_expiration": None}
                 for c in ("rethink", "iqra") if c not in have]
        for r in rows:  # a charity on Gmail: show its Gmail mailbox instead
            r["provider"] = provider(r["company_id"])
            if r["provider"] == "gmail":
                g = _gmail_row(r["company_id"])
                r.update(connected_email=g["connected_email"] if g else None, refresh_token=g["refresh_token"] if g else None,
                         subscription_expiration=None, last_error=g["last_error"] if g else None)
        out = []
        for r in rows:
            last_send = conn.execute(
                "SELECT ts, event, message FROM app_event_logs WHERE category = 'email' AND company_id = ? "
                "AND event IN ('email.sent', 'email.failed') ORDER BY ts DESC LIMIT 1", (r["company_id"],)).fetchone() \
                if conn.execute("SELECT name FROM sqlite_master WHERE name = 'app_event_logs'").fetchone() else None
            out.append({
                "company_id": r["company_id"], "provider": r["provider"], "connected": bool(r["refresh_token"]),
                "last_error": r.get("last_error"),
                "mailbox": r["connected_email"], "subscription_expires": r["subscription_expiration"],
                "last_send": dict(last_send) if last_send else None,
                "state": "ok" if r["refresh_token"] else "down",
            })
        return out
    finally:
        conn.close()


# which charity each platform integration belongs to (for people who only see their own charities' status)
PLATFORM_COMPANY = {"givebrite_iqra": "iqra", "givebrite_rethink": "rethink", "madinah": "iqra", "paysuite": "rethink",
                    "stripe_rethink": "rethink", "launchgood_rethink": "rethink", "launchgood_iqra": "iqra"}


@router.get("/status")
def ops_status(request: Request, live: bool = Query(False)):
    health = _read_json(HEALTH_FILE)
    sync = _read_json(SYNC_FILE)
    user = getattr(request.state, "api_user", None) or {}
    visible = None  # None = every charity (super admin)
    if user.get("role") != "super_admin":
        from core.rbac import companies_with
        visible = companies_with(user, "status.view") or set()
    names = [p for p in PLATFORM_COMPANY if visible is None or PLATFORM_COMPANY[p] in visible]
    platforms = [_platform_status(p, health, live) for p in names]
    services = [_service_state("platform-sync.service")]
    for s in services:
        if s["active"] != "active":
            for p in platforms:
                p["state"] = "down"
                p["issues"].insert(0, "platform-sync service is not running")
    errors_24h = query_local(level="error", since=(_now() - datetime.timedelta(hours=24)).isoformat(), limit=1)["total"]
    active_platforms = [p for p in platforms if p.get("state") != "not_configured"]
    overall = "down" if any(p["state"] == "down" for p in active_platforms) else (
        "warning" if any(p["state"] == "warning" for p in active_platforms) else "ok")
    return {
        "checked_at": _now().isoformat(),
        "overall": overall,
        "platforms": platforms,
        "services": services,
        "sync_heartbeat": (sync.get("meta") or {}).get("last_synced_at"),
        "outlook": [o for o in _outlook_status() if visible is None or str(o.get("company_id") or "").lower() in visible],
        "logging": {**shipping_status(), "errors_last_24h": errors_24h},
        "backup": _backup_status(),
    }


def _backup_status() -> dict:
    """Nightly backup health: last run, last good local copy, last off-site copy (core/nightly_backup.py)."""
    from core.nightly_backup import STATUS_FILE, _supabase_config
    st = _read_json(STATUS_FILE)
    last_ok = st.get("last_success") or {}
    last_off = st.get("last_offsite_success") or {}
    age_h = None
    if last_ok.get("finished_at"):
        try:
            age_h = round((_now() - datetime.datetime.fromisoformat(last_ok["finished_at"])).total_seconds() / 3600, 1)
        except ValueError:
            pass
    return {
        "offsite_configured": _supabase_config() is not None,
        "last_run_status": (st.get("last_run") or {}).get("status"),
        "last_run_error": (st.get("last_run") or {}).get("error"),
        "last_success_at": last_ok.get("finished_at"),
        "last_success_age_hours": age_h,
        "last_success_mb": round(last_ok["bytes"] / 2**20, 1) if last_ok.get("bytes") else None,
        "last_offsite_at": last_off.get("finished_at"),
        "stale": age_h is None or age_h > 26,
    }


@router.get("/logs")
def ops_logs(request: Request, category: Optional[str] = None, level: Optional[str] = None, company_id: Optional[str] = None,
             actor: Optional[str] = None,
             search: Optional[str] = None, event: Optional[str] = None, since: Optional[str] = None,
             until: Optional[str] = None, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
             source: str = Query("local"), apl: Optional[str] = None, since_hours: int = Query(24, ge=1, le=720)):
    user = getattr(request.state, "api_user", None) or {}
    visible_companies = visible_actors = None
    if user.get("role") != "super_admin":
        from core.rbac import companies_with
        visible_companies = sorted(companies_with(user, "logs.view") or [])
        if source == "axiom":
            raise HTTPException(status_code=403, detail="Only super admins can query Axiom directly.")
        if company_id and company_id != "all" and company_id.strip().lower() not in visible_companies:
            raise HTTPException(status_code=403, detail="You can't see that charity's log.")
        visible_actors = _staff_of(visible_companies)
    if source == "axiom":
        if not apl:
            raise HTTPException(status_code=400, detail="Provide an APL query for the Axiom source.")
        try:
            return {"source": "axiom", "result": query_axiom(apl, since_hours)}
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e))
    return {"source": "local", **query_local(category, level, company_id, search, since, until, event, limit, offset,
                                             actor=actor, visible_companies=visible_companies,
                                             visible_actors=visible_actors)}


def _staff_of(companies: List[str]) -> List[str]:
    """Emails of the non-super accounts that can open any of these charities (their sign-ins etc. are visible)."""
    from core.rbac import effective_access
    conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=10)
    try:
        rows = conn.execute("SELECT id, email FROM users WHERE role != 'super_admin'").fetchall()
    finally:
        conn.close()
    wanted = set(companies)
    return [em for uid, em in rows if wanted & set(effective_access(uid, False)["companies"])]


class SessionUpload(BaseModel):
    accessToken: Optional[str] = ""  # LaunchGood: may be left empty when a refresh token is given
    refreshToken: Optional[str] = None
    account: Optional[str] = None
    source: Optional[str] = "manual-capture"
    rawCookie: Optional[str] = None
    # LaunchGood: the browser's cookies for *.launchgood.com (including httpOnly ones from the sign-in site),
    # [{name, value, domain}] - what a future automatic renewal needs
    cookies: Optional[List[Dict[str, Any]]] = None


def _launchgood_candidate(existing: Dict[str, Any], access: str, payload: "SessionUpload") -> Dict[str, Any]:
    """A captured LaunchGood session in the format core/launchgood_client reads (bearerToken + browser headers +
    cookie header). The old Authorization/Cookie headers are dropped - keeping them sent the expired token."""
    headers = {k: v for k, v in (existing.get("headers") or {}).items() if k.lower() not in ("authorization", "cookie")}
    headers["authorization"] = access
    # a new sign-in replaces the old session entirely: its refresh token and renewal notes no longer apply
    cand = {k: v for k, v in existing.items() if k not in ("headers", "bearerToken", "rawCookie", "refreshToken",
                                                           "renewedAt", "renewFailedAt", "renewFailedDetail")}
    cand.update({"bearerToken": access, "accessToken": access, "headers": headers, "savedAt": _now().strftime("%Y-%m-%dT%H:%M:%SZ")})
    jar = [c for c in (payload.cookies or []) if isinstance(c, dict) and c.get("name") and "launchgood.com" in str(c.get("domain") or "")]
    if payload.rawCookie and payload.rawCookie.strip():
        raw = payload.rawCookie.strip()
        headers["cookie"] = raw
        cand["rawCookie"] = raw
    elif jar:
        site = [c for c in jar if not str(c.get("domain") or "").lstrip(".").startswith("auth.")]
        raw = "; ".join(f"{c['name']}={c.get('value', '')}" for c in site)
        headers["cookie"] = raw
        cand["rawCookie"] = raw
        cand["authCookies"] = [{"name": c["name"], "value": c.get("value", ""), "domain": c.get("domain")}
                               for c in jar if str(c.get("domain") or "").lstrip(".").startswith("auth.")]
    elif existing.get("rawCookie"):
        cand["rawCookie"] = existing["rawCookie"]
        headers["cookie"] = existing["rawCookie"]
        cand["rawCookie"] = existing["rawCookie"]
    if payload.refreshToken:
        cand["refreshToken"] = payload.refreshToken.replace("Bearer ", "").strip()
    # the site cookie "token" carries the access JWT too: an old one there would contradict the new header
    raw = cand.get("rawCookie") or ""
    if "token=" in raw:
        parts = [p.strip() for p in raw.split(";") if p.strip()]
        raw = "; ".join(f"token={access.replace('Bearer ', '')}" if p.split("=", 1)[0] == "token" else p for p in parts)
        cand["rawCookie"] = raw
        headers["cookie"] = raw
    return cand


def _launchgood_check(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Verifies a candidate LaunchGood session itself (not the saved one): signed in, not a guest."""
    headers = dict(candidate.get("headers") or {})
    headers.setdefault("Accept", "application/json, text/plain, */*")
    headers.setdefault("Origin", "https://www.launchgood.com")
    headers.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    try:
        r = requests.post("https://www.launchgood.com/api/user/currentUser", headers=headers, json={}, timeout=20)
    except requests.RequestException as e:
        return {"ok": False, "detail": str(e)[:160]}
    if r.status_code != 200:
        return {"ok": False, "http_status": r.status_code, "detail": r.text[:160]}
    try:
        info = r.json()
    except ValueError:
        return {"ok": False, "http_status": 200, "detail": "Unexpected reply"}
    if not _lg_signed_in(info):
        return {"ok": False, "http_status": 401, "detail": "LaunchGood treated this session as signed out"}
    return {"ok": True, "http_status": 200}


SESSION_PLATFORMS = ["givebrite_iqra", "givebrite_rethink", "madinah", "launchgood_rethink", "launchgood_iqra"]


@router.get("/platform-sessions")
def list_sessions():
    return {p: _token_info(p) for p in SESSION_PLATFORMS}


@router.post("/platform-sessions/{platform}")
def upload_session(platform: str, payload: SessionUpload, user: dict = Depends(require_super_admin)):
    """Stores a manually captured session after proving it works against the platform API."""
    platform = platform.lower()
    if platform == "givebrite":
        platform = "givebrite_iqra"
    if platform not in TOKEN_FILES:
        raise HTTPException(status_code=404, detail="Unknown platform")
    access = (payload.accessToken or "").strip()
    if platform.startswith("launchgood"):
        # Whatever was pasted (one token, both, a JSON blob, a whole localStorage dump): pick out LaunchGood's JWTs
        # and tell them apart by their "type" claim. An access token alone lasts 15 minutes - saving it is what kept
        # signing the CRM out - so without a refresh token the paste is refused with directions.
        blob = " ".join(x for x in (payload.accessToken, payload.refreshToken) if x)
        found_access, found_refresh = None, None
        for tok in re.findall(r"eyJ[\w-]+\.[\w-]+\.[\w-]+", blob):
            claims = _jwt_claims(tok)
            if "launchgood" not in str(claims.get("iss", "")):
                continue
            kind = str(claims.get("type") or "").lower()
            if kind == "refresh" or (kind != "access" and "refresh" in str(claims.get("jti", ""))):
                found_refresh = tok
            elif kind == "access":
                found_access = tok
        if found_refresh:
            payload.refreshToken = found_refresh
        elif payload.refreshToken and _jwt_claims(payload.refreshToken).get("type") == "access":
            payload.refreshToken = None  # an access token pasted into the refresh box
        if not (payload.refreshToken and payload.refreshToken.strip()):
            raise HTTPException(status_code=400, detail=(
                "That's LaunchGood's 15-minute access token - on its own the CRM is signed out again within 15 minutes. "
                "Paste the refreshToken instead: on launchgood.com press F12 > Console, run  copy(localStorage.refreshToken)  "
                "and paste here." if found_access or access else "Paste LaunchGood's refreshToken (see the steps above)."))
        access = found_access or access
    if platform.startswith("launchgood") and payload.refreshToken and payload.refreshToken.strip():
        # LaunchGood's access token only lives 15 minutes: with the refresh token (browser > Local Storage >
        # "refreshToken") we get a fresh one now, and the sync service keeps renewing it from then on
        from core.launchgood_session import renew_with_refresh_token
        try:
            new_access, new_refresh = renew_with_refresh_token(payload.refreshToken, (_read_json(TOKEN_FILES[platform]).get("headers") or {}))
        except (ValueError, requests.RequestException) as e:
            if "firewall" in str(e) or isinstance(e, requests.RequestException):
                # Cloudflare is only holding the request for a while: keep the refresh token (it is still valid) and
                # let the sync service finish the renewal on its next cycles - no need to paste it again
                existing = _read_json(TOKEN_FILES[platform])
                rt = payload.refreshToken.replace("Bearer ", "").strip()
                pending = {k: v for k, v in existing.items() if k not in ("refreshToken", "renewedAt", "renewFailedAt", "renewFailedDetail")}
                pending.update({"refreshToken": rt, "savedAt": _now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "capturedBy": f"{user.get('email')} via {payload.source} (renewal pending)"})
                fd_path = f"{TOKEN_FILES[platform]}.tmp.{os.getpid()}.{int(time.time() * 1000)}"
                fd = os.open(fd_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(pending, f, indent=2)
                os.replace(fd_path, TOKEN_FILES[platform])
                log_event("session.uploaded", category="session", actor=user.get("email"), platform=platform, has_refresh=True,
                          source=payload.source, message=f"{platform} refresh token saved; renewal pending (LaunchGood firewall)")
                return {"status": "pending", "platform": platform, "has_refresh": True, "verified": False,
                        "message": "Saved. LaunchGood's firewall is holding requests for a moment, so the CRM will finish connecting by itself within a few minutes - no need to paste again."}
            raise HTTPException(status_code=400, detail=f"{e}. Copy the refreshToken again from a browser where you're signed in to LaunchGood.")
        access = new_access
        payload.refreshToken = new_refresh or payload.refreshToken.replace("Bearer ", "").strip()
    if not access:
        raise HTTPException(status_code=400, detail="Paste the access token" + (" or the refresh token" if platform.startswith("launchgood") else "") + ".")
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
    if platform.startswith("launchgood"):
        candidate = _launchgood_candidate(existing, access, payload)
        candidate["capturedBy"] = f"{user.get('email')} via {payload.source}"
        check = _launchgood_check(candidate)
        if not check["ok"]:
            log_event("session.upload_rejected", category="session", level="warning", actor=user.get("email"),
                      platform=platform, http_status=check.get("http_status"), detail=check.get("detail"))
            raise HTTPException(status_code=400, detail=f"{platform} rejected that session ({check.get('http_status')}): {check.get('detail')}")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd_path = f"{path}.tmp.{os.getpid()}.{int(time.time() * 1000)}"
        fd = os.open(fd_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(candidate, f, indent=2)
        os.replace(fd_path, path)
        log_event("session.uploaded", category="session", actor=user.get("email"), platform=platform, expires_at=exp.isoformat(),
                  has_refresh=bool(candidate.get("refreshToken") or candidate.get("authCookies")), source=payload.source)
        return {"status": "success", "platform": platform, "access_expires_at": exp.isoformat(), "verified": True,
                "auth_cookies": [c["name"] for c in candidate.get("authCookies") or []], "has_refresh": bool(candidate.get("refreshToken"))}
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


# ---------------------------------------------------------------------------
# Response cache visibility / control
# ---------------------------------------------------------------------------
@router.get("/cache")
def ops_cache_status():
    from core.cache import stats, versions
    scopes = ["donations", "classification", "tracker", "tracker_comms", "payouts", "fundraisers", "expenses"]
    return {**stats(), "versions": {c: versions(scopes, c) for c in ("rethink", "iqra")}}


@router.post("/cache/clear")
def ops_cache_clear(user: dict = Depends(require_super_admin)):
    from core.cache import clear_all
    clear_all()
    log_event("cache.cleared", category="performance", level="warning", actor=user.get("email"),
              message="Response cache cleared from the ops console")
    return {"status": "success"}


# ---------------------------------------------------------------------------
# 1-Click Browser Bookmarklet & Direct CSV Sync Helper Routes
# ---------------------------------------------------------------------------
_SYNC_KEY_FILE = os.path.join(BASE_DIR, "data_cache", ".sync_helper_key")


def _sync_key() -> str:
    """The bookmarklet's shared key: LAUNCHGOOD_SYNC_KEY if set, otherwise a random key kept (0600) on the
    server. Never a value written in the source - the old hard-coded key was in the public JS bundle."""
    env_key = (os.environ.get("LAUNCHGOOD_SYNC_KEY") or "").strip()
    if env_key:
        return env_key
    try:
        with open(_SYNC_KEY_FILE, "r", encoding="utf-8") as f:
            existing = f.read().strip()
            if existing:
                return existing
    except FileNotFoundError:
        pass
    import secrets
    new_key = secrets.token_urlsafe(32)
    os.makedirs(os.path.dirname(_SYNC_KEY_FILE), exist_ok=True)
    try:
        fd = os.open(_SYNC_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:  # the other worker created it first
        with open(_SYNC_KEY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(new_key)
    return new_key


def _sync_authorized(request: Request, sent_key: Optional[str]) -> bool:
    """The sync key, or a signed-in super admin's session. (Previously ANY Authorization header was accepted.)"""
    import hmac
    if sent_key and hmac.compare_digest(sent_key.strip().encode(), _sync_key().encode()):
        return True
    auth_hdr = (request.headers.get("Authorization") or "").strip()
    if auth_hdr.lower().startswith("bearer "):
        from core.auth import user_from_token
        user = user_from_token(auth_hdr)
        return bool(user and user.get("role") == "super_admin")
    return False


@router.get("/sync-helper-key")
def sync_helper_key():
    """For the Sessions tab's bookmarklet (super admins only, via the router dependency)."""
    return {"key": _sync_key()}


class BookmarkletPayload(BaseModel):
    accessToken: str
    rawCookie: Optional[str] = None
    refreshToken: Optional[str] = None
    syncKey: Optional[str] = None
    source: Optional[str] = "bookmarklet-1click"


@sync_router.post("/{platform}")
def sync_helper_upload(platform: str, payload: BookmarkletPayload, request: Request):
    """Receives active session tokens pushed by the 1-click LaunchGood browser bookmarklet."""
    if not _sync_authorized(request, payload.syncKey):
        log_event("access.sync_helper_refused", category="security", level="warning", path=request.url.path,
                  message="Refused session upload: wrong or missing sync key")
        raise HTTPException(status_code=401, detail="Invalid sync key or missing authentication")

    platform = platform.lower()
    if platform not in ("launchgood_rethink", "launchgood_iqra"):  # the bookmarklet only carries LaunchGood sessions
        raise HTTPException(status_code=404, detail="Unknown platform")

    access = (payload.accessToken or "").strip()
    access = access if access.startswith("Bearer ") else f"Bearer {access}"
    exp = _jwt_exp(access)
    if not exp or exp <= _now():
        raise HTTPException(status_code=400, detail="Provided token is not a valid or unexpired JWT")

    path = TOKEN_FILES[platform]
    existing = _read_json(path)
    # Reuse candidate builder so headers & cookies are formatted consistently
    dummy_upload = SessionUpload(
        accessToken=access,
        refreshToken=payload.refreshToken,
        rawCookie=payload.rawCookie,
        source=payload.source
    )
    candidate = _launchgood_candidate(existing, access, dummy_upload)
    candidate["capturedBy"] = f"1-Click Bookmarklet via {payload.source}"

    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd_path = f"{path}.tmp.{os.getpid()}.{int(time.time() * 1000)}"
    fd = os.open(fd_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(candidate, f, indent=2)
    os.replace(fd_path, path)

    cid = "rethink" if "rethink" in platform else "iqra"
    try:
        from core.cache import invalidate_data_cache
        invalidate_data_cache(cid)
    except Exception:
        pass

    log_event("session.bookmarklet_synced", category="session", level="info",
              platform=platform, expires_at=exp.isoformat(), source=payload.source)
    return {
        "ok": True,
        "status": "success",
        "platform": platform,
        "access_expires_at": exp.isoformat(),
        "message": "LaunchGood session synced successfully to CRM"
    }


@sync_router.post("/csv/{company_id}")
async def sync_helper_csv(company_id: str, request: Request):
    """Directly ingests LaunchGood donor export CSV downloaded by browser."""
    if not _sync_authorized(request, request.headers.get("X-Sync-Key") or request.query_params.get("sync_key")):
        log_event("access.sync_helper_refused", category="security", level="warning", path=request.url.path,
                  message="Refused CSV upload: wrong or missing sync key")
        raise HTTPException(status_code=401, detail="Invalid sync key")
    company_id = (company_id or "").strip().lower()
    conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=10)
    try:
        known = conn.execute("SELECT 1 FROM companies WHERE LOWER(id) = ?", (company_id,)).fetchone()
    finally:
        conn.close()
    if not known:
        raise HTTPException(status_code=404, detail="Unknown charity")

    body = await request.body()
    csv_text = body.decode("utf-8", errors="replace")
    if not csv_text.strip():
        raise HTTPException(status_code=400, detail="Empty CSV body")

    from core.launchgood_sync import ingest_launchgood_csv_text
    res = ingest_launchgood_csv_text(csv_text, company_id)
    return res

