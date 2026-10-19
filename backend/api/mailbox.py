"""
Charity mailbox: which email service each charity sends from, and the Gmail integration.

Rethink sends from Microsoft 365 (Graph, backend/api/tracker.py); Iqra uses Google - Gmail API with OAuth 2.0.
Every sender in the CRM (bulk / single / sponsorship emails, test email, overdue digest) calls send_email(),
which picks the charity's own mailbox; replies are pulled by sync_replies() (the mailbox loop in main.py).

Gmail: the charity creates an OAuth client in its own Google Cloud project (Gmail API enabled) and saves the
client id/secret here; a super admin then signs in with the charity's Google account on Google's page. We store
the refresh token encrypted. Scopes: gmail.send (send) + gmail.readonly (find replies) - nothing can be deleted.
"""
import base64
import datetime
import hashlib
import hmac
import html as html_lib
import json
import os
import re
import sqlite3
import time
import urllib.parse
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.api.auth import get_current_user, require_company_access, require_super_admin
from core.auth import JWT_SECRET
from core.data_processor import LOCAL_DB_PATH
from core.event_log import log_event
from core.security import decrypt_string, encrypt_string

router = APIRouter(prefix="/api/mailbox", tags=["Charity mailbox"])

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE = "https://oauth2.googleapis.com/revoke"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_SCOPES = "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly"
DEFAULT_PROVIDER = {"iqra": "gmail", "rethink": "outlook"}
PROVIDERS = ("gmail", "outlook")


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS mailbox_settings (
        company_id TEXT PRIMARY KEY, provider TEXT NOT NULL, updated_by TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS mailbox_gmail_auth (
        company_id TEXT PRIMARY KEY, client_id TEXT, client_secret TEXT, refresh_token TEXT, access_token TEXT,
        token_expiry REAL, connected_email TEXT, scopes TEXT, connected_by TEXT, connected_at TEXT,
        last_reply_sync_at TEXT, last_error TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(mailbox_gmail_auth)").fetchall()}
        if "service_account_id" not in cols:
            conn.execute("ALTER TABLE mailbox_gmail_auth ADD COLUMN service_account_id TEXT")
    except Exception:
        pass
    return conn


def _owner(company_id: Optional[str]) -> str:
    c = str(company_id or "").strip().lower()
    return "iqra" if c in ("iqra", "sp") else ("rethink" if c in ("rethink", "sp_rethink") else c)


def _get_env_google_creds(comp: str) -> Dict[str, Optional[str]]:
    prefix = comp.upper()
    return {
        "client_id": (os.environ.get(f"{prefix}_GOOGLE_CLIENT_ID") or os.environ.get(f"GOOGLE_{prefix}_CLIENT_ID") or "").strip() or None,
        "client_secret": (os.environ.get(f"{prefix}_GOOGLE_CLIENT_SECRET") or os.environ.get(f"GOOGLE_{prefix}_CLIENT_SECRET") or "").strip() or None,
        "service_account_id": (os.environ.get(f"{prefix}_GOOGLE_SERVICE_ACCOUNT_ID") or os.environ.get(f"{prefix}_GOOGLE_SERVICE_ACCOUNT_EMAIL") or "").strip() or None,
        "sender_email": (os.environ.get(f"{prefix}_GMAIL_SENDER_EMAIL") or os.environ.get(f"{prefix}_EMAIL_SENDER") or ("donorcare@iqracharity.org" if comp == "iqra" else "")).strip() or None,
        "refresh_token": (os.environ.get(f"{prefix}_GOOGLE_REFRESH_TOKEN") or "").strip() or None,
    }


def provider(company_id: str) -> str:
    comp = _owner(company_id)
    conn = _db()
    try:
        r = conn.execute("SELECT provider FROM mailbox_settings WHERE company_id = ?", (comp,)).fetchone()
    finally:
        conn.close()
    return r["provider"] if r else DEFAULT_PROVIDER.get(comp, "outlook")


def _gmail_row(comp: str) -> Optional[sqlite3.Row]:
    conn = _db()
    try:
        r = conn.execute("SELECT * FROM mailbox_gmail_auth WHERE company_id = ?", (comp,)).fetchone()
        env_creds = _get_env_google_creds(comp)
        if env_creds["client_id"] and env_creds["client_secret"]:
            needs_seed = False
            if not r:
                needs_seed = True
            elif not r["client_id"] or not r["client_secret"]:
                needs_seed = True
            elif "service_account_id" in r.keys() and env_creds["service_account_id"] and not r["service_account_id"]:
                needs_seed = True
            elif env_creds["sender_email"] and not r["connected_email"]:
                needs_seed = True

            if needs_seed:
                with conn:
                    enc_secret = encrypt_string(env_creds["client_secret"])
                    enc_refresh = encrypt_string(env_creds["refresh_token"]) if env_creds.get("refresh_token") else (r["refresh_token"] if r else None)
                    conn.execute("""
                        INSERT INTO mailbox_gmail_auth (company_id, client_id, client_secret, service_account_id, connected_email, refresh_token)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(company_id) DO UPDATE SET
                            client_id = excluded.client_id,
                            client_secret = excluded.client_secret,
                            service_account_id = COALESCE(mailbox_gmail_auth.service_account_id, excluded.service_account_id),
                            connected_email = COALESCE(mailbox_gmail_auth.connected_email, excluded.connected_email),
                            refresh_token = COALESCE(mailbox_gmail_auth.refresh_token, excluded.refresh_token),
                            updated_at = CURRENT_TIMESTAMP
                    """, (comp, env_creds["client_id"], enc_secret, env_creds["service_account_id"], env_creds["sender_email"], enc_refresh))
                r = conn.execute("SELECT * FROM mailbox_gmail_auth WHERE company_id = ?", (comp,)).fetchone()
        return r
    finally:
        conn.close()


def is_connected(company_id: str) -> bool:
    comp = _owner(company_id)
    if provider(comp) == "gmail":
        r = _gmail_row(comp)
        return bool(r and r["refresh_token"])
    from backend.api.tracker import _get_outlook_auth_row
    a = _get_outlook_auth_row(comp)
    return bool(a and a["refresh_token"])


def sender_address(company_id: str) -> Optional[str]:
    comp = _owner(company_id)
    if provider(comp) == "gmail":
        r = _gmail_row(comp)
        if r and r["connected_email"]:
            return r["connected_email"]
        env_creds = _get_env_google_creds(comp)
        return env_creds.get("sender_email")
    from backend.api.tracker import _get_outlook_auth_row
    a = _get_outlook_auth_row(comp)
    return a["connected_email"] if a else None


# ------------------------------------------------------------------ Gmail tokens
def _gmail_token(comp: str) -> str:
    r = _gmail_row(comp)
    if not r or not r["refresh_token"]:
        raise HTTPException(status_code=400, detail="The charity's Gmail account isn't connected. Connect it in Email > Mailbox (Gmail).")
    if r["access_token"] and (r["token_expiry"] or 0) - time.time() > 90:
        return decrypt_string(r["access_token"])
    res = requests.post(GOOGLE_TOKEN, data={
        "client_id": r["client_id"], "client_secret": decrypt_string(r["client_secret"] or ""),
        "refresh_token": decrypt_string(r["refresh_token"]), "grant_type": "refresh_token"}, timeout=20)
    if res.status_code != 200:
        err = (res.json() if res.headers.get("content-type", "").startswith("application/json") else {}).get("error", res.status_code)
        conn = _db()
        try:
            with conn:
                conn.execute("UPDATE mailbox_gmail_auth SET last_error = ?, updated_at = CURRENT_TIMESTAMP WHERE company_id = ?",
                             (f"token refresh failed: {err}", comp))
                if err == "invalid_grant":  # access was revoked or the refresh token expired: needs a new sign-in
                    conn.execute("UPDATE mailbox_gmail_auth SET refresh_token = NULL, access_token = NULL WHERE company_id = ?", (comp,))
        finally:
            conn.close()
        log_event("gmail.token_failed", category="email", level="error", company_id=comp, detail=str(err),
                  message=f"Gmail token refresh failed for {comp}: {err}")
        raise HTTPException(status_code=400, detail=("Google signed the CRM out of the Gmail account - connect it again in Email > Mailbox."
                                                     if err == "invalid_grant" else f"Couldn't refresh the Gmail sign-in ({err})."))
    d = res.json()
    conn = _db()
    try:
        with conn:
            conn.execute("UPDATE mailbox_gmail_auth SET access_token = ?, token_expiry = ?, last_error = NULL, updated_at = CURRENT_TIMESTAMP "
                         "WHERE company_id = ?", (encrypt_string(d["access_token"]), time.time() + int(d.get("expires_in", 3600)), comp))
    finally:
        conn.close()
    return d["access_token"]


# ------------------------------------------------------------------ sending (both providers)
_UNSUB_RE = re.compile(r'https://[^"\s]+/api/email-unsubscribe/[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+')


def _plain_text(html: str) -> str:
    t = re.sub(r"(?is)<(style|head|script|title)[^>]*>.*?</\1>", " ", html or "")
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h[1-6]>|</tr>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html_lib.unescape(t)
    return "\n".join(re.sub(r"[ \t ]+", " ", ln).strip() for ln in t.splitlines() if ln.strip())


def send_email(company_id: str, to: List[Tuple[str, Optional[str]]], subject: str, html: str) -> Dict[str, Any]:
    """Sends one email from the charity's own mailbox. Returns ok, http_status, detail, message_id, thread_id, sender
    (message/thread ids only for Gmail - Microsoft's sendMail doesn't return them)."""
    comp = _owner(company_id)
    to = [(a.strip(), n) for a, n in to if a and "@" in a]
    if not to:
        return {"ok": False, "http_status": None, "detail": "No valid recipient"}
    if provider(comp) == "gmail":
        token = _gmail_token(comp)
        sender = sender_address(comp) or "me"
        msg = MIMEMultipart("alternative")
        msg["To"] = ", ".join(formataddr((str(Header(n, "utf-8")) if n else "", a)) for a, n in to)
        if sender and "@" in sender:
            msg["From"] = sender
        msg["Subject"] = str(Header(subject or "", "utf-8"))
        msg["Date"] = formatdate(localtime=False)
        msg["Message-ID"] = make_msgid(domain=(sender.split("@")[-1] if sender and "@" in sender else None))
        unsub = _UNSUB_RE.search(html or "")
        if unsub and len(to) == 1:  # one-click unsubscribe in Gmail's own UI (posts to the same endpoint)
            msg["List-Unsubscribe"] = f"<{html_lib.unescape(unsub.group(0))}>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        msg.attach(MIMEText(_plain_text(html), "plain", "utf-8"))
        msg.attach(MIMEText(html or "", "html", "utf-8"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        try:
            res = requests.post(f"{GMAIL}/messages/send", headers={"Authorization": f"Bearer {token}"}, json={"raw": raw}, timeout=30)
        except requests.RequestException as e:
            return {"ok": False, "http_status": None, "detail": f"Gmail unreachable: {str(e)[:150]}", "sender": sender}
        if res.status_code != 200:
            detail = res.text[:300]
            try:
                detail = res.json().get("error", {}).get("message", detail)
            except ValueError:
                pass
            if res.status_code == 429 or "limit" in str(detail).lower():
                detail = f"Gmail's daily sending limit was reached ({detail}). It resets within 24 hours."
            return {"ok": False, "http_status": res.status_code, "detail": f"Gmail error {res.status_code}: {detail}", "sender": sender}
        d = res.json()
        return {"ok": True, "http_status": 200, "detail": "", "message_id": d.get("id"), "thread_id": d.get("threadId"), "sender": sender}
    # Microsoft 365
    from backend.api.tracker import _get_outlook_auth_row, _get_valid_graph_token
    token = _get_valid_graph_token(comp)
    auth = _get_outlook_auth_row(comp)
    sender = auth["connected_email"] if auth and auth["connected_email"] else "me"
    res = requests.post("https://graph.microsoft.com/v1.0/me/sendMail", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json={
        "message": {"subject": (subject or "").strip(), "body": {"contentType": "HTML", "content": html},
                    "toRecipients": [{"emailAddress": {"address": a, **({"name": n} if n else {})}} for a, n in to]},
        "saveToSentItems": "true"}, timeout=20)
    if res.status_code not in (200, 202):
        return {"ok": False, "http_status": res.status_code, "detail": f"Microsoft Graph sendMail error {res.status_code}: {res.text[:300]}", "sender": sender}
    return {"ok": True, "http_status": res.status_code, "detail": "", "message_id": None, "thread_id": None, "sender": sender}


# ------------------------------------------------------------------ replies (Gmail)
def sync_gmail_replies(company_id: str) -> Dict[str, Any]:
    """Reads the newest inbox messages (read-only) and records donor replies like the Outlook poll does."""
    comp = _owner(company_id)
    r = _gmail_row(comp)
    if not r or not r["refresh_token"]:
        return {"status": "not_connected"}
    token = _gmail_token(comp)
    me = (r["connected_email"] or "").strip().lower()
    h = {"Authorization": f"Bearer {token}"}
    lst = requests.get(f"{GMAIL}/messages", headers=h, params={"q": "in:inbox newer_than:3d -from:me", "maxResults": 40}, timeout=20)
    if lst.status_code != 200:
        return {"status": "fetch_failed", "http_status": lst.status_code}
    from backend.api.tracker import _record_inbound_reply
    new = 0
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    try:
        cur = conn.cursor()
        for item in lst.json().get("messages", []) or []:
            mid = item.get("id")
            if cur.execute("SELECT 1 FROM sponsorship_communications WHERE message_id = ? AND company_id = ?", (mid, comp)).fetchone():
                continue
            try:
                if cur.execute("SELECT 1 FROM crm_email_replies WHERE message_id = ? AND company_id = ?", (mid, comp)).fetchone():
                    continue
            except sqlite3.OperationalError:
                pass
            m = requests.get(f"{GMAIL}/messages/{mid}", headers=h, params=[("format", "metadata"), ("metadataHeaders", "From"),
                                                                           ("metadataHeaders", "Subject")], timeout=20)
            if m.status_code != 200:
                continue
            md = m.json()
            hdr = {x["name"].lower(): x["value"] for x in (md.get("payload") or {}).get("headers", [])}
            frm = hdr.get("from", "")
            em = (re.search(r"<([^>]+)>", frm).group(1) if "<" in frm else frm).strip().lower()
            if not em or em == me:
                continue
            when = datetime.datetime.utcfromtimestamp(int(md.get("internalDate", "0")) / 1000).strftime("%Y-%m-%dT%H:%M:%S")
            if _record_inbound_reply(cur, comp, mid, md.get("threadId", ""), hdr.get("subject", ""), html_lib.unescape(md.get("snippet", "")),
                                     em, me, when):
                new += 1
        conn.commit()
    finally:
        conn.close()
    c2 = _db()
    try:
        with c2:
            c2.execute("UPDATE mailbox_gmail_auth SET last_reply_sync_at = CURRENT_TIMESTAMP WHERE company_id = ?", (comp,))
    finally:
        c2.close()
    return {"status": "success", "synced_new_replies": new}


def sync_replies(company_id: str) -> Dict[str, Any]:
    comp = _owner(company_id)
    if provider(comp) == "gmail":
        return sync_gmail_replies(comp)
    from backend.api.tracker import sync_inbound_outlook_replies
    return sync_inbound_outlook_replies(comp)


def gmail_companies() -> List[str]:
    conn = _db()
    try:
        rows = conn.execute("SELECT company_id FROM mailbox_gmail_auth WHERE COALESCE(refresh_token, '') != ''").fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows if provider(r[0]) == "gmail"]


# ------------------------------------------------------------------ OAuth (Gmail)
def _state(comp: str) -> str:
    raw = f"gmail:{comp}:{int(time.time())}"
    sig = hmac.new(f"gmail-oauth:{JWT_SECRET}".encode(), raw.encode(), hashlib.sha256).hexdigest()[:24]
    return f"{raw}:{sig}"


def _check_state(state: str, comp: str) -> bool:
    try:
        kind, c, ts, sig = state.split(":")
        raw = f"{kind}:{c}:{ts}"
        good = hmac.new(f"gmail-oauth:{JWT_SECRET}".encode(), raw.encode(), hashlib.sha256).hexdigest()[:24]
        return kind == "gmail" and c == comp and hmac.compare_digest(sig, good) and time.time() - int(ts) < 1800
    except Exception:
        return False


def _company(user: Dict[str, Any], company_id: str) -> str:
    comp = _owner(company_id)
    if comp not in ("rethink", "iqra"):
        raise HTTPException(status_code=400, detail="Choose Rethink or Iqra.")
    return require_company_access(user, comp)


@router.get("/status")
def mailbox_status(company_id: str = Query(...), user: Dict[str, Any] = Depends(get_current_user)):
    comp = _company(user, company_id)
    prov = provider(comp)
    out: Dict[str, Any] = {"company_id": comp, "provider": prov, "connected": is_connected(comp), "connected_email": sender_address(comp)}
    if prov == "gmail":
        r = _gmail_row(comp)
        env_creds = _get_env_google_creds(comp)
        cid = (r["client_id"] if r and r["client_id"] else env_creds.get("client_id"))
        sa = (r["service_account_id"] if r and "service_account_id" in r.keys() and r["service_account_id"] else env_creds.get("service_account_id"))
        out.update({"client_id_set": bool(cid), "client_id": (cid[:16] + "…") if cid else None,
                    "service_account_id": sa,
                    "connected_at": r["connected_at"] if r else None, "connected_by": r["connected_by"] if r else None,
                    "last_reply_sync_at": r["last_reply_sync_at"] if r else None, "last_error": r["last_error"] if r else None,
                    "scopes": "send email, read inbox (to find replies)"})
    return out


class ProviderRequest(BaseModel):
    company_id: str
    provider: str


@router.post("/provider")
def set_provider(payload: ProviderRequest, user: Dict[str, Any] = Depends(require_super_admin)):
    comp = _company(user, payload.company_id)
    prov = payload.provider.strip().lower()
    if prov not in PROVIDERS:
        raise HTTPException(status_code=400, detail="Choose gmail or outlook.")
    conn = _db()
    try:
        with conn:
            conn.execute("""INSERT INTO mailbox_settings (company_id, provider, updated_by) VALUES (?, ?, ?)
                            ON CONFLICT(company_id) DO UPDATE SET provider = excluded.provider, updated_by = excluded.updated_by,
                            updated_at = CURRENT_TIMESTAMP""", (comp, prov, user.get("email")))
    finally:
        conn.close()
    log_event("mailbox.provider_changed", category="email", company_id=comp, actor=user.get("email"), provider=prov,
              message=f"{comp} now sends email with {prov}")
    return {"status": "success", "provider": prov}


class GmailCredentials(BaseModel):
    company_id: str
    client_id: str
    client_secret: str
    service_account_id: Optional[str] = None


@router.post("/gmail/credentials")
def save_gmail_credentials(payload: GmailCredentials, user: Dict[str, Any] = Depends(require_super_admin)):
    comp = _company(user, payload.company_id)
    cid, sec = payload.client_id.strip(), payload.client_secret.strip()
    sa = (payload.service_account_id or "").strip() or None
    if not cid.endswith(".apps.googleusercontent.com"):
        raise HTTPException(status_code=400, detail="That doesn't look like a Google OAuth client ID (it ends in .apps.googleusercontent.com).")
    if not sec:
        raise HTTPException(status_code=400, detail="Enter the client secret.")
    conn = _db()
    try:
        with conn:
            conn.execute("""INSERT INTO mailbox_gmail_auth (company_id, client_id, client_secret, service_account_id) VALUES (?, ?, ?, ?)
                            ON CONFLICT(company_id) DO UPDATE SET client_id = excluded.client_id, client_secret = excluded.client_secret,
                            service_account_id = COALESCE(excluded.service_account_id, mailbox_gmail_auth.service_account_id),
                            refresh_token = CASE WHEN mailbox_gmail_auth.client_id = excluded.client_id THEN mailbox_gmail_auth.refresh_token END,
                            access_token = NULL, token_expiry = NULL, updated_at = CURRENT_TIMESTAMP""",
                         (comp, cid, encrypt_string(sec), sa))
    finally:
        conn.close()
    log_event("gmail.credentials_saved", category="email", company_id=comp, actor=user.get("email"),
              message=f"Google OAuth client saved for {comp}")
    return {"status": "success"}


@router.get("/gmail/auth-url")
def gmail_auth_url(company_id: str = Query(...), redirect_uri: str = Query(...), user: Dict[str, Any] = Depends(require_super_admin)):
    comp = _company(user, company_id)
    r = _gmail_row(comp)
    if not r or not r["client_id"]:
        raise HTTPException(status_code=400, detail="Save the Google OAuth client ID and secret first.")
    q = {"client_id": r["client_id"], "redirect_uri": redirect_uri, "response_type": "code", "scope": GMAIL_SCOPES,
         "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": _state(comp)}
    return {"auth_url": f"{GOOGLE_AUTH}?{urllib.parse.urlencode(q)}"}


class GmailExchange(BaseModel):
    company_id: str
    code: str
    redirect_uri: str
    state: str


@router.post("/gmail/exchange")
def gmail_exchange(payload: GmailExchange, user: Dict[str, Any] = Depends(require_super_admin)):
    comp = _company(user, payload.company_id)
    if not _check_state(payload.state, comp):
        raise HTTPException(status_code=400, detail="That Google sign-in link has expired or wasn't started here - press Connect again.")
    r = _gmail_row(comp)
    if not r or not r["client_id"]:
        raise HTTPException(status_code=400, detail="Save the Google OAuth client ID and secret first.")
    res = requests.post(GOOGLE_TOKEN, data={"code": payload.code.strip(), "client_id": r["client_id"],
                                            "client_secret": decrypt_string(r["client_secret"] or ""),
                                            "redirect_uri": payload.redirect_uri.strip(), "grant_type": "authorization_code"}, timeout=20)
    if res.status_code != 200:
        log_event("gmail.connect_failed", category="email", level="error", company_id=comp, detail=res.text[:300],
                  message=f"Gmail sign-in failed for {comp}")
        raise HTTPException(status_code=400, detail=f"Google refused the sign-in: {res.text[:200]}")
    d = res.json()
    granted = set((d.get("scope") or "").split())
    if not set(GMAIL_SCOPES.split()) <= granted:
        raise HTTPException(status_code=400, detail="Google didn't grant both permissions (send email and read inbox). Connect again and tick both boxes.")
    if not d.get("refresh_token"):
        raise HTTPException(status_code=400, detail="Google didn't return a long-lived sign-in. Remove the CRM's access at myaccount.google.com/permissions and connect again.")
    prof = requests.get(f"{GMAIL}/profile", headers={"Authorization": f"Bearer {d['access_token']}"}, timeout=15)
    email = prof.json().get("emailAddress") if prof.status_code == 200 else None
    conn = _db()
    try:
        with conn:
            conn.execute("""UPDATE mailbox_gmail_auth SET refresh_token = ?, access_token = ?, token_expiry = ?, connected_email = ?,
                            scopes = ?, connected_by = ?, connected_at = CURRENT_TIMESTAMP, last_error = NULL, updated_at = CURRENT_TIMESTAMP
                            WHERE company_id = ?""",
                         (encrypt_string(d["refresh_token"]), encrypt_string(d["access_token"]), time.time() + int(d.get("expires_in", 3600)),
                          email, " ".join(sorted(granted)), user.get("email"), comp))
    finally:
        conn.close()
    log_event("gmail.connected", category="email", company_id=comp, actor=user.get("email"), mailbox=email,
              message=f"Gmail mailbox {email} connected for {comp}")
    return {"status": "success", "connected_email": email}


@router.post("/gmail/disconnect")
def gmail_disconnect(company_id: str = Query(...), user: Dict[str, Any] = Depends(require_super_admin)):
    comp = _company(user, company_id)
    r = _gmail_row(comp)
    if r and r["refresh_token"]:
        try:  # also withdraw the CRM's access at Google
            requests.post(GOOGLE_REVOKE, params={"token": decrypt_string(r["refresh_token"])}, timeout=15)
        except requests.RequestException:
            pass
    conn = _db()
    try:
        with conn:
            conn.execute("""UPDATE mailbox_gmail_auth SET refresh_token = NULL, access_token = NULL, token_expiry = NULL,
                            connected_email = NULL, updated_at = CURRENT_TIMESTAMP WHERE company_id = ?""", (comp,))
    finally:
        conn.close()
    log_event("gmail.disconnected", category="email", level="warning", company_id=comp, actor=user.get("email"),
              message=f"Gmail mailbox disconnected for {comp}")
    return {"status": "success"}


class TestSend(BaseModel):
    company_id: str
    recipient_email: str


@router.post("/test-send")
def mailbox_test_send(payload: TestSend, user: Dict[str, Any] = Depends(require_super_admin)):
    comp = _company(user, payload.company_id)
    to = payload.recipient_email.strip()
    if "@" not in to:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    prov = provider(comp)
    sender = sender_address(comp)
    body = (f"<div style=\"font-family:Arial,sans-serif;max-width:560px;margin:0 auto;padding:20px;border:1px solid #e2e8f0;border-radius:10px\">"
            f"<h2 style=\"margin:0 0 10px\">Mailbox connected</h2><p>This test was sent from <b>{html_lib.escape(sender or '')}</b> "
            f"({'Gmail' if prov == 'gmail' else 'Microsoft 365'}) by the CRM for <b>{comp.upper()}</b>.</p>"
            f"<p style=\"color:#64748b;font-size:12px\">Sent by {html_lib.escape(user.get('email') or '')} at "
            f"{datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}.</p></div>")
    res = send_email(comp, [(to, None)], f"CRM test email - {comp.upper()} mailbox", body)
    if not res["ok"]:
        raise HTTPException(status_code=400, detail=res["detail"])
    log_event("email.test_sent", category="email", company_id=comp, actor=user.get("email"), recipient=to, mailbox=sender,
              message=f"Test email sent from {sender} to {to}")
    return {"status": "success", "message": f"Test email sent from {sender} to {to}.", "sender": sender}


@router.post("/sync-replies")
def mailbox_sync_replies(company_id: str = Query(...), user: Dict[str, Any] = Depends(get_current_user)):
    comp = _company(user, company_id)
    return sync_replies(comp)
