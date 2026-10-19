"""
Email unsubscribe.

Every email the CRM sends carries an "Unsubscribe" button (unsubscribe_footer) with a signed link to
/api/email-unsubscribe/{token}. Nothing is emailed or routed to a mailbox: the page shows one button; pressing
it (POST) records the person in email_unsubscribes, sets Marketing Consent = "No" on all their gifts in that
charity, and logs "email.unsubscribed" so the CRM shows admins who unsubscribed (Email > Unsubscribed, badge).
Later bulk/sponsorship sends skip unsubscribed people.

The token is HMAC-signed (company + email + the email's tracking id), so it can't be forged for someone else and
only ever touches the charity whose email it came from.
"""
import base64
import hashlib
import hmac
import html
import json
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from backend.api.auth import get_current_user, require_company_access
from core.auth import JWT_SECRET
from core.data_processor import LOCAL_DB_PATH
from core.event_log import log_event

public_router = APIRouter(prefix="/api/email-unsubscribe", tags=["Email unsubscribe (public)"])
router = APIRouter(prefix="/api/email/unsubscribes", tags=["Email unsubscribe"])

PUBLIC_BASE = "https://rethink.dpdns.org"
try:
    from backend.api.tracker import _PUBLIC_APP_BASE as PUBLIC_BASE  # noqa: F811
except Exception:
    pass

CHARITY_NAMES = {"rethink": "Rethink Charity", "iqra": "IQRA", "sp": "Sisters' Project"}
_KEY = hashlib.sha256(f"unsubscribe:{JWT_SECRET}".encode()).digest()


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS email_unsubscribes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL, email TEXT NOT NULL, name TEXT,
        unsubscribed_at TEXT DEFAULT CURRENT_TIMESTAMP, tracking_id TEXT, subject TEXT, ip TEXT, user_agent TEXT,
        gifts_updated INTEGER DEFAULT 0, seen_at TEXT, seen_by TEXT, resubscribed_at TEXT, resubscribed_by TEXT,
        UNIQUE(company_id, email))""")
    return conn


def _owner(company_id: str) -> str:
    c = str(company_id or "").strip().lower()
    return "iqra" if c in ("iqra", "sp") else c  # Sisters' Project is Iqra's brand


# ------------------------------------------------------------------ links / footer
def _sign(data: bytes) -> str:
    return base64.urlsafe_b64encode(hmac.new(_KEY, data, hashlib.sha256).digest()[:16]).decode().rstrip("=")


def make_token(company_id: str, email: str, tracking_id: Optional[str] = None) -> str:
    raw = json.dumps({"c": _owner(company_id), "e": str(email or "").strip().lower(), "t": tracking_id or ""},
                     separators=(",", ":")).encode()
    return f"{base64.urlsafe_b64encode(raw).decode().rstrip('=')}.{_sign(raw)}"


def read_token(token: str) -> Optional[Dict[str, str]]:
    try:
        body, sig = token.rsplit(".", 1)
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        if not hmac.compare_digest(sig, _sign(raw)):
            return None
        d = json.loads(raw)
        return d if d.get("c") and "@" in (d.get("e") or "") else None
    except Exception:
        return None


def unsubscribe_url(company_id: str, email: str, tracking_id: Optional[str] = None) -> str:
    return f"{PUBLIC_BASE}/api/email-unsubscribe/{make_token(company_id, email, tracking_id)}"


def unsubscribe_footer(company_id: str, email: str, tracking_id: Optional[str] = None) -> str:
    """The Unsubscribe button appended to every outgoing email (and shown in previews)."""
    if not email or "@" not in str(email):
        return ""
    name = html.escape(CHARITY_NAMES.get(str(company_id).lower(), CHARITY_NAMES.get(_owner(company_id), "us")))
    url = html.escape(unsubscribe_url(company_id, email, tracking_id))
    return (
        '<div data-crm-unsubscribe="1" style="max-width:600px;margin:24px auto 8px;padding:14px 16px;text-align:center;'
        'font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:18px;color:#64748b;border-top:1px solid #e2e8f0;">'
        f'You are receiving this email because you supported {name}.<br/>'
        f'<a href="{url}" target="_blank" style="display:inline-block;margin-top:8px;padding:6px 16px;border:1px solid #cbd5e1;'
        'border-radius:6px;color:#475569;text-decoration:none;font-weight:bold;font-size:12px;">Unsubscribe</a></div>'
    )


UNSUBSCRIBE_TOKEN = "%%UNSUBSCRIBE_URL%%"  # what the email builder puts in its footer's Unsubscribe link
_MAILTO_UNSUB_RE = re.compile(r'href="mailto:[^"]*\?subject=unsubscribe[^"]*"', re.I)


def add_footer(body_html: str, company_id: str, email: str, tracking_id: Optional[str] = None) -> str:
    """Puts this person's unsubscribe link into the email: the template's own Unsubscribe link (builder token, or an
    old "mailto:...?subject=Unsubscribe" link, which would only have emailed us) or, if it has none, our footer."""
    body = body_html or ""
    if 'data-crm-unsubscribe="1"' in body:
        return body
    has_mail = bool(email and "@" in str(email))
    if UNSUBSCRIBE_TOKEN in body or _MAILTO_UNSUB_RE.search(body):
        url = html.escape(unsubscribe_url(company_id, email, tracking_id)) if has_mail else "#"
        body = body.replace(UNSUBSCRIBE_TOKEN, url)
        return _MAILTO_UNSUB_RE.sub(f'href="{url}" target="_blank"', body)
    foot = unsubscribe_footer(company_id, email, tracking_id)
    if not foot:
        return body
    return body.replace("</body>", f"{foot}</body>", 1) if "</body>" in body else f"{body}{foot}"


# ------------------------------------------------------------------ lookups used by the senders
_CACHE: Dict[str, Any] = {"at": 0.0, "by_company": {}}


def unsubscribed_emails(company_id: str) -> set:
    now = time.time()
    if now - _CACHE["at"] > 20:
        by: Dict[str, set] = {}
        try:
            conn = _db()
            try:
                for r in conn.execute("SELECT company_id, email FROM email_unsubscribes WHERE resubscribed_at IS NULL"):
                    by.setdefault(r["company_id"], set()).add(r["email"])
            finally:
                conn.close()
        except sqlite3.Error:
            return _CACHE["by_company"].get(_owner(company_id), set())
        _CACHE.update(at=now, by_company=by)
    return _CACHE["by_company"].get(_owner(company_id), set())


def is_unsubscribed(company_id: str, email: str) -> bool:
    return str(email or "").strip().lower() in unsubscribed_emails(company_id)


# ------------------------------------------------------------------ public page
def _page(title: str, body: str, charity: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/><meta name="robots" content="noindex"/>
<title>{html.escape(title)}</title>
<style>body{{margin:0;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;color:#0f172a}}
.card{{max-width:440px;margin:12vh auto 0;background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:28px 24px;text-align:center}}
h1{{font-size:20px;margin:0 0 10px}}p{{font-size:14px;line-height:21px;color:#475569;margin:0 0 18px}}
button{{background:#0f172a;color:#fff;border:0;border-radius:8px;padding:11px 26px;font-size:14px;font-weight:bold;cursor:pointer}}
small{{display:block;margin-top:18px;color:#94a3b8;font-size:12px}}</style></head>
<body><div class="card">{body}<small>{html.escape(charity)}</small></div></body></html>""",
                        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


def _mask(email: str) -> str:
    user, _, dom = email.partition("@")
    return f"{user[:2]}{'•' * max(1, len(user) - 2)}@{dom}"


@public_router.get("/{token}", response_class=HTMLResponse)
def unsubscribe_page(token: str):
    """Shows the button only - opening the link (or a mail scanner pre-fetching it) changes nothing."""
    d = read_token(token)
    if not d:
        return _page("Link not valid", "<h1>This link isn't valid</h1><p>Please use the Unsubscribe button in the latest email you received.</p>", "")
    charity = CHARITY_NAMES.get(d["c"], d["c"].title())
    if is_unsubscribed(d["c"], d["e"]):
        return _page("Unsubscribed", f"<h1>You're unsubscribed</h1><p>{html.escape(_mask(d['e']))} won't receive further emails from {html.escape(charity)}.</p>", charity)
    return _page("Unsubscribe", f"""<h1>Unsubscribe from {html.escape(charity)} emails?</h1>
<p>Press the button to stop emails to <b>{html.escape(_mask(d['e']))}</b>.</p>
<form method="post"><button type="submit">Unsubscribe</button></form>""", charity)


@public_router.post("/{token}", response_class=HTMLResponse)
def unsubscribe_confirm(token: str, request: Request):
    d = read_token(token)
    if not d:
        return _page("Link not valid", "<h1>This link isn't valid</h1><p>Please use the Unsubscribe button in the latest email you received.</p>", "")
    comp, email, tid = d["c"], d["e"], d.get("t") or None
    charity = CHARITY_NAMES.get(comp, comp.title())
    record_unsubscribe(comp, email, tracking_id=tid, ip=(request.headers.get("x-forwarded-for") or (request.client.host if request.client else ""))[:64],
                       user_agent=request.headers.get("user-agent", "")[:300])
    return _page("Unsubscribed", f"<h1>You've been unsubscribed</h1><p>{html.escape(_mask(email))} won't receive further emails from {html.escape(charity)}.</p>", charity)


def record_unsubscribe(comp: str, email: str, tracking_id: Optional[str] = None, ip: str = "", user_agent: str = "",
                       source: str = "email button") -> Dict[str, Any]:
    comp, email = _owner(comp), str(email).strip().lower()
    conn = _db()
    name, subject, ids = None, None, []
    try:
        if tracking_id:
            for q in ("SELECT recipient_name AS n, subject AS s FROM crm_email_messages WHERE tracking_id = ? AND company_id = ?",
                      "SELECT recipient_name AS n, subject AS s FROM sponsorship_communications WHERE tracking_id = ? AND company_id = ?"):
                try:
                    r = conn.execute(q, (tracking_id, comp)).fetchone()
                except sqlite3.OperationalError:
                    r = None
                if r:
                    name, subject = r["n"], r["s"]
                    break
        rows = conn.execute('SELECT "Donation ID", "First Name", "Last Name" FROM donations WHERE LOWER(company_id) = ? '
                            'AND (LOWER(Email) = ? OR LOWER("Donor ID") = ?)', (comp, email, email)).fetchall()
        ids = [str(r[0]) for r in rows if r[0]]
        if not name and rows:
            name = f"{rows[0][1] or ''} {rows[0][2] or ''}".strip() or None
        with conn:
            # Marketing Consent = No on every gift of theirs in this charity (GiveBrite reads 'optin' first)
            conn.execute('UPDATE donations SET "Marketing Consent" = ? WHERE LOWER(company_id) = ? '
                         'AND (LOWER(Email) = ? OR LOWER("Donor ID") = ?)', ("No", comp, email, email))
            try:
                conn.execute("UPDATE donations SET optin = 'false' WHERE LOWER(company_id) = ? AND (LOWER(Email) = ? OR LOWER(\"Donor ID\") = ?) "
                             "AND LOWER(COALESCE(Platform, '')) IN ('givebrite', 'givebright')", (comp, email, email))
            except sqlite3.OperationalError:
                pass
            existing = conn.execute("SELECT id, resubscribed_at FROM email_unsubscribes WHERE company_id = ? AND email = ?", (comp, email)).fetchone()
            if existing:
                conn.execute("""UPDATE email_unsubscribes SET unsubscribed_at = CURRENT_TIMESTAMP, resubscribed_at = NULL, resubscribed_by = NULL,
                                seen_at = NULL, seen_by = NULL, tracking_id = COALESCE(?, tracking_id), subject = COALESCE(?, subject),
                                name = COALESCE(?, name), ip = ?, user_agent = ?, gifts_updated = ? WHERE id = ?""",
                             (tracking_id, subject, name, ip, user_agent, len(ids), existing["id"]))
            else:
                conn.execute("""INSERT INTO email_unsubscribes (company_id, email, name, tracking_id, subject, ip, user_agent, gifts_updated)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (comp, email, name, tracking_id, subject, ip, user_agent, len(ids)))
    finally:
        conn.close()
    _CACHE["at"] = 0.0
    if ids:
        try:
            from backend.api.donors import _refresh_copy
            _refresh_copy(comp, ids)
        except Exception:
            pass
    log_event("email.unsubscribed", category="email", level="warning", company_id=comp, recipient=email,
              recipient_name=name, subject=subject, tracking_id=tracking_id, gifts=len(ids), source=source,
              message=f"{name or email} unsubscribed from {comp} emails ({source}); marketing consent set to No on {len(ids)} gift(s)")
    try:
        from backend.api.events import broadcast_event_sync
        broadcast_event_sync("EMAIL_UNSUBSCRIBED", {"company_id": comp, "email": email, "name": name})
    except Exception:
        pass
    return {"email": email, "name": name, "gifts_updated": len(ids)}


# ------------------------------------------------------------------ CRM side (signed-in staff)
def _company(user: Dict[str, Any], company_id: str) -> str:
    comp = _owner(company_id)
    if comp not in ("rethink", "iqra"):
        raise HTTPException(status_code=400, detail="Choose Rethink or Iqra.")
    return require_company_access(user, comp)


@router.get("")
def list_unsubscribes(company_id: str = Query(...), include_resubscribed: bool = Query(False),
                      user: Dict[str, Any] = Depends(get_current_user)):
    comp = _company(user, company_id)
    conn = _db()
    try:
        where = "company_id = ?" + ("" if include_resubscribed else " AND resubscribed_at IS NULL")
        rows = [dict(r) for r in conn.execute(f"""SELECT id, email, name, unsubscribed_at, subject, gifts_updated, seen_at, seen_by,
                    resubscribed_at, resubscribed_by FROM email_unsubscribes WHERE {where} ORDER BY unsubscribed_at DESC""", (comp,))]
    finally:
        conn.close()
    return {"items": rows, "unseen": sum(1 for r in rows if not r["seen_at"] and not r["resubscribed_at"])}


@router.get("/unseen")
def unseen_count(company_id: str = Query(...), user: Dict[str, Any] = Depends(get_current_user)):
    comp = _company(user, company_id)
    conn = _db()
    try:
        rows = [dict(r) for r in conn.execute("""SELECT email, name, unsubscribed_at FROM email_unsubscribes WHERE company_id = ?
                     AND seen_at IS NULL AND resubscribed_at IS NULL ORDER BY unsubscribed_at DESC LIMIT 20""", (comp,))]
        n = conn.execute("SELECT COUNT(*) FROM email_unsubscribes WHERE company_id = ? AND seen_at IS NULL AND resubscribed_at IS NULL", (comp,)).fetchone()[0]
    finally:
        conn.close()
    return {"unseen": n, "latest": rows}


class SeenRequest(BaseModel):
    company_id: str
    ids: Optional[List[int]] = None  # none = all


@router.post("/mark-seen")
def mark_seen(payload: SeenRequest, user: Dict[str, Any] = Depends(get_current_user)):
    comp = _company(user, payload.company_id)
    conn = _db()
    try:
        with conn:
            if payload.ids:
                q = f"UPDATE email_unsubscribes SET seen_at = CURRENT_TIMESTAMP, seen_by = ? WHERE company_id = ? AND seen_at IS NULL AND id IN ({','.join('?' * len(payload.ids))})"
                n = conn.execute(q, (user.get("email"), comp, *payload.ids)).rowcount
            else:
                n = conn.execute("UPDATE email_unsubscribes SET seen_at = CURRENT_TIMESTAMP, seen_by = ? WHERE company_id = ? AND seen_at IS NULL",
                                 (user.get("email"), comp)).rowcount
    finally:
        conn.close()
    return {"marked": n}


class ResubscribeRequest(BaseModel):
    company_id: str
    email: str


@router.post("/resubscribe")
def resubscribe(payload: ResubscribeRequest, user: Dict[str, Any] = Depends(get_current_user)):
    """Only when the person has asked to receive emails again: lets the CRM email them; consent is left as No
    (set it on the donor if they gave consent)."""
    if user.get("role") not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Only an admin can resubscribe someone.")
    comp = _company(user, payload.company_id)
    email = payload.email.strip().lower()
    conn = _db()
    try:
        with conn:
            n = conn.execute("UPDATE email_unsubscribes SET resubscribed_at = CURRENT_TIMESTAMP, resubscribed_by = ? WHERE company_id = ? "
                             "AND email = ? AND resubscribed_at IS NULL", (user.get("email"), comp, email)).rowcount
    finally:
        conn.close()
    if not n:
        raise HTTPException(status_code=404, detail="That person isn't unsubscribed.")
    _CACHE["at"] = 0.0
    log_event("email.resubscribed", category="email", company_id=comp, recipient=email, actor=user.get("email"),
              message=f"{email} resubscribed to {comp} emails by {user.get('email')}")
    return {"success": True}
