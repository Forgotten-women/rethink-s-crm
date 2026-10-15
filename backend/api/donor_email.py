"""
Direct donor email: write to any donor (not only donors on a sponsorship allocation), chosen by hand or by a
segment (backend/api/donors.py apply_segment), with a saved template of the charity's own themes.

  * Recipients come from the Donors directory of ONE charity (company_id); mail goes from that charity's own
    connected mailbox only (the tracker's Outlook connection).
  * Templates are the tracker's templates (sponsorship_email_templates) for a theme of that charity.
  * Placeholders: donor-level ones always work ({first_name}, {total_given}, {last_gift_date}, ...); sponsorship
    ones ({beneficiary_name}, {sponsorship_type}, ...) are filled from the donor's latest sponsorship allocation and
    a recipient without one is skipped with the reason, never sent a half-filled email.
  * Campaigns ("email queue" by segment): each campaign = one segment + one template. Its recipients are fixed when
    it is created (pending messages), then sent in batches. Several campaigns = several segments with different
    templates. A person already in another campaign can be excluded, and anyone emailed in the last N days too.
History lives in crm_email_campaigns / crm_email_messages; opens are tracked by the tracker's pixel.
"""
import datetime
import json
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from config.settings import LOCAL_DB_PATH
from backend.api.tracker import (
    THEME_OWNER_COMPANY, _PLACEHOLDER_RE, _get_outlook_auth_row, _get_template, _get_valid_graph_token,
    _prepare_outgoing_html, _render_text, _resolve_theme, tracker_access_guard,
)

router = APIRouter(prefix="/api/tracker/direct-email", tags=["Direct donor email"],
                   dependencies=[Depends(tracker_access_guard)])

SEND_BATCH_LIMIT = 25
DEFAULT_MESSAGE = "Thank you for your generous support."
MAX_RECIPIENTS = 5000


def init_tables() -> None:
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=15.0)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS crm_email_campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL, name TEXT, segment_json TEXT,
            template_type TEXT, theme TEXT, subject TEXT, body_html TEXT, status TEXT DEFAULT 'queued',
            created_by TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS crm_email_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL, campaign_id INTEGER, donor_id TEXT,
            recipient_email TEXT, recipient_name TEXT, subject TEXT, body_html TEXT, template_type TEXT, theme TEXT,
            status TEXT DEFAULT 'pending', detail TEXT, tracking_id TEXT, sender_email TEXT, sent_at TEXT,
            opened_at TEXT, open_count INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(campaign_id, recipient_email))""")
        if "message_body" not in {r[1] for r in conn.execute("PRAGMA table_info(crm_email_campaigns)")}:
            conn.execute("ALTER TABLE crm_email_campaigns ADD COLUMN message_body TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_email_messages_company ON crm_email_messages(company_id, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_email_messages_email ON crm_email_messages(company_id, recipient_email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_email_messages_tracking ON crm_email_messages(tracking_id)")
        conn.commit()
    finally:
        conn.close()


init_tables()


def _company(company_id: Optional[str]) -> str:
    comp = str(company_id or "").strip().lower()
    if not comp or comp == "all" or comp not in set(THEME_OWNER_COMPANY.values()):
        raise HTTPException(status_code=400, detail="Choose one charity to email from.")
    return comp


def _user(request: Request) -> Dict[str, Any]:
    return getattr(request.state, "tracker_user", None) or {}


# ------------------------------------------------------------------ recipients & personalisation
def _clean(v):
    """JSON-safe value: NaN / NaT / pandas NA become None, numpy numbers become plain numbers."""
    try:
        import pandas as pd
        if v is None or (not isinstance(v, (list, dict, str)) and pd.isna(v)):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        try:
            return v.item()
        except (ValueError, AttributeError):
            pass
    return v


def _resolve_recipients(comp: str, segment: Optional[Dict[str, Any]], donor_ids: Optional[List[str]],
                        extra: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Segment matches + hand-picked donors + typed addresses, one row per email address (first wins)."""
    from backend.api.donors import _directory_data, apply_segment
    frame, dx = _directory_data(comp)
    picked = []
    if frame is not None and not frame.empty:
        if segment:
            picked.append(apply_segment(frame, dx, segment))
        if donor_ids:
            ids = {str(d).strip().lower() for d in donor_ids if str(d).strip()}
            picked.append(frame[frame["donor_id"].str.lower().isin(ids) | frame["email"].fillna("").str.lower().isin(ids)])
    out, seen = [], set()
    for part in picked:
        for r in part.to_dict(orient="records"):
            em = str(r.get("email") or "").strip()
            if "@" not in em or em.lower() in seen:
                continue
            seen.add(em.lower())
            out.append({"donor_id": _clean(r.get("donor_id")), "email": em, "name": _clean(r.get("name")) or "",
                        "total": _clean(r.get("total")), "gifts": _clean(r.get("gifts")), "tier": _clean(r.get("tier")),
                        "last_gift": str(_clean(r.get("last_gift")) or "")[:10], "matched_total": _clean(r.get("matched_total")),
                        "sponsorship_types": _clean(r.get("sponsorship_types"))})
    for e in extra or []:
        em = str((e or {}).get("email") or "").strip()
        if "@" in em and em.lower() not in seen:
            seen.add(em.lower())
            out.append({"donor_id": em.lower(), "email": em, "name": str(e.get("name") or "").strip()})
    return out[:MAX_RECIPIENTS]


def _donor_variables(comp: str, recipient: Dict[str, Any], subject_template: str, message_body: Optional[str] = None) -> Dict[str, str]:
    from backend.api.donors import _directory_data
    frame, dx = _directory_data(comp)
    key = str(recipient.get("donor_id") or recipient.get("email") or "").strip().lower()
    row = {}
    if frame is not None and not frame.empty:
        hit = frame[(frame["donor_id"].str.lower() == key) | (frame["email"].fillna("").str.lower() == str(recipient.get("email") or "").lower())]
        if not hit.empty:
            row = hit.iloc[0].to_dict()
    row = {k: _clean(v) for k, v in row.items()}
    name = (row.get("name") or recipient.get("name") or "").strip() or "Friend"
    gifts = dx[dx["key"] == row.get("donor_id")].sort_values("date") if row and not dx.empty else None
    last = gifts.iloc[-1] if gifts is not None and len(gifts) else None
    money = lambda v: f"{float(_clean(v) or 0):,.2f}"  # noqa: E731
    v = {
        "first_name": name.split(" ")[0], "donor_name": name, "email": recipient.get("email") or "",
        "recipient_email": recipient.get("email") or "",
        "total_given": money(row.get("total")), "gifts_count": str(int(row.get("gifts") or 0)),
        "average_gift": money(row.get("avg_gift")), "lifetime_tier": str(row.get("tier") or ""),
        "first_gift_date": str(row.get("first_gift") or "")[:10], "last_gift_date": str(row.get("last_gift") or "")[:10],
        "last_gift_amount": money(last["amount"]) if last is not None else "",
        "last_gift_cause": str((last["subheading"] or last["heading"] or "")) if last is not None else "",
        "top_cause": str(row.get("top_heading") or ""), "sponsorship_types": str(row.get("sponsorship_types") or ""),
        "subject": subject_template or "", "message_body": (message_body or "").strip() or DEFAULT_MESSAGE,
    }
    # Sponsorship placeholders from the donor's latest allocation (if any)
    em = str(recipient.get("email") or "").strip().lower()
    if em:
        conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            a = conn.execute("""SELECT a.*, b.name AS beneficiary_name, b.sponsorship_type AS b_type, b.location AS b_location,
                                       b.profile_link AS b_profile, b.video_link AS b_video, b.project_code AS b_code, b.donor_folder_link AS b_folder
                                FROM sponsorship_allocation_donors d JOIN sponsorship_allocations a ON a.id = d.allocation_id
                                LEFT JOIN sponsorship_beneficiaries b ON b.id = a.beneficiary_id
                                WHERE LOWER(a.company_id) = ? AND LOWER(TRIM(d.donor_email)) = ?
                                ORDER BY COALESCE(a.start_date, '') DESC LIMIT 1""", (comp, em)).fetchone()
        except sqlite3.OperationalError:
            a = None
        finally:
            conn.close()
        if a:
            a = dict(a)
            v.update({
                "beneficiary_name": a.get("beneficiary_name") or "", "sponsorship_type": a.get("b_type") or a.get("sponsorship_type") or "",
                "location": a.get("b_location") or "", "project_code": a.get("b_code") or "",
                "profile_link": a.get("b_profile") or a.get("profile_link") or "", "video_link": a.get("b_video") or "",
                "report_link": a.get("b_profile") or "", "donor_folder_link": a.get("b_folder") or a.get("b_profile") or "",
                "folder_link": a.get("b_folder") or a.get("b_profile") or "",
                "campaign_name": a.get("campaign_name") or "", "community_name": a.get("community_name") or "",
                "renewal_deadline": a.get("end_date") or "",
                "sponsorship_year": (a.get("start_date") or "")[:4],
            })
    return v


def _render(comp: str, theme: str, template_type: str, subject_tpl: Optional[str], body_tpl: Optional[str],
            recipient: Dict[str, Any], message_body: Optional[str] = None) -> Dict[str, Any]:
    if subject_tpl is None or body_tpl is None:
        conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=10)
        try:
            tpl = _get_template(conn.cursor(), theme, template_type)
        finally:
            conn.close()
        subject_tpl = tpl["subject"] if subject_tpl is None else subject_tpl
        body_tpl = tpl["body_html"] if body_tpl is None else body_tpl
    variables = _donor_variables(comp, recipient, subject_tpl, message_body)
    subject = _render_text(subject_tpl, variables)
    variables["subject"] = subject
    unresolved = sorted({m.group(1) for m in _PLACEHOLDER_RE.finditer(subject_tpl + body_tpl)
                         if m.group(1).lower() not in {k.lower() for k, val in variables.items() if val not in (None, "")}})
    return {"recipient_email": recipient.get("email") or "", "recipient_name": variables["donor_name"], "subject": subject,
            "body_html": _render_text(body_tpl, variables), "unresolved_placeholders": unresolved}


def _deliver(comp: str, theme: str, template_type: str, rendered: Dict[str, Any], base_url: str,
             campaign_id: Optional[int], donor_id: Optional[str], message_id: Optional[int] = None) -> Dict[str, Any]:
    to = (rendered["recipient_email"] or "").strip()
    result = {"recipient_email": to, "status": "sent", "detail": ""}
    if "@" not in to:
        result.update(status="skipped", detail="No email address")
    elif rendered["unresolved_placeholders"]:
        result.update(status="skipped", detail="Template needs: " + ", ".join(rendered["unresolved_placeholders"]))
    tracking_id, sender = None, None
    if result["status"] == "sent":
        access_token = _get_valid_graph_token(comp)  # this charity's own mailbox only
        auth = _get_outlook_auth_row(comp)
        sender = auth["connected_email"] if auth and auth["connected_email"] else "me"
        tracking_id = str(uuid.uuid4())
        html = _prepare_outgoing_html(rendered["body_html"], f"{base_url}/api/tracker/email-tracking/pixel/{tracking_id}")
        res = requests.post("https://graph.microsoft.com/v1.0/me/sendMail", headers={
            "Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}, json={
            "message": {"subject": rendered["subject"].strip(), "body": {"contentType": "HTML", "content": html},
                        "toRecipients": [{"emailAddress": {"address": to, "name": rendered["recipient_name"]}}]},
            "saveToSentItems": "true"}, timeout=15)
        if res.status_code not in (200, 202):
            result.update(status="failed", detail=f"Mail server error {res.status_code}")
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=15.0)
    try:
        with conn:
            vals = (rendered["subject"], rendered["body_html"], result["status"], result["detail"], tracking_id, sender,
                    datetime.datetime.utcnow().isoformat(timespec="seconds") if result["status"] == "sent" else None)
            if message_id:
                conn.execute("""UPDATE crm_email_messages SET subject = ?, body_html = ?, status = ?, detail = ?, tracking_id = ?,
                                       sender_email = ?, sent_at = ? WHERE id = ? AND company_id = ?""", (*vals, message_id, comp))
            else:
                conn.execute("""INSERT INTO crm_email_messages (company_id, campaign_id, donor_id, recipient_email, recipient_name,
                                    template_type, theme, subject, body_html, status, detail, tracking_id, sender_email, sent_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                             (comp, campaign_id, donor_id, to, rendered["recipient_name"], template_type, theme, *vals))
    finally:
        conn.close()
    try:
        from core.event_log import log_event
        log_event(f"email.direct_{result['status']}", category="email", company_id=comp, recipient=to,
                  template=template_type, theme=theme, campaign_id=campaign_id, detail=result["detail"],
                  message=f"Direct email {result['status']} to {to}" + (f": {result['detail']}" if result["detail"] else ""))
    except Exception:
        pass
    return result


def _recently_emailed(comp: str, days: int) -> set:
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat(timespec="seconds")
    conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=10)
    try:
        a = {r[0] for r in conn.execute("""SELECT LOWER(recipient_email) FROM crm_email_messages
                                          WHERE company_id = ? AND status = 'sent' AND sent_at >= ?""", (comp, since))}
        try:
            a |= {r[0] for r in conn.execute("""SELECT LOWER(recipient_email) FROM sponsorship_communications
                                               WHERE LOWER(company_id) = ? AND direction = 'outbound' AND sent_at >= ?""",
                                            (comp, since.replace("T", " ")))}
        except sqlite3.OperationalError:
            pass
    finally:
        conn.close()
    return a


# ------------------------------------------------------------------ endpoints
class RecipientsRequest(BaseModel):
    company_id: str
    segment: Optional[Dict[str, Any]] = None
    donor_ids: Optional[List[str]] = None
    extra: Optional[List[Dict[str, Any]]] = None
    exclude_emailed_days: Optional[int] = None


@router.post("/recipients")
def recipients(req: RecipientsRequest):
    comp = _company(req.company_id)
    rows = _resolve_recipients(comp, req.segment, req.donor_ids, req.extra)
    excluded = 0
    if req.exclude_emailed_days:
        recent = _recently_emailed(comp, int(req.exclude_emailed_days))
        before = len(rows)
        rows = [r for r in rows if r["email"].lower() not in recent]
        excluded = before - len(rows)
    return {"count": len(rows), "excluded_recently_emailed": excluded, "recipients": rows}


class PreviewRequest(BaseModel):
    company_id: str
    theme: Optional[str] = None
    template_type: str = "general_custom"
    subject_template: Optional[str] = None
    body_template: Optional[str] = None
    message_body: Optional[str] = None
    recipient: Dict[str, Any]


@router.post("/preview")
def preview(req: PreviewRequest):
    comp = _company(req.company_id)
    theme = _resolve_theme(comp, req.theme)
    return _render(comp, theme, req.template_type, req.subject_template, req.body_template, req.recipient, req.message_body)


class SendRequest(BaseModel):
    company_id: str
    theme: Optional[str] = None
    template_type: str = "general_custom"
    subject_template: Optional[str] = None
    body_template: Optional[str] = None
    message_body: Optional[str] = None
    recipients: List[Dict[str, Any]]
    dry_run: bool = False


@router.post("/send")
def send(req: SendRequest, request: Request):
    """Sends to up to 25 chosen people now (the screen sends larger selections batch by batch)."""
    comp = _company(req.company_id)
    theme = _resolve_theme(comp, req.theme)
    if len(req.recipients) > SEND_BATCH_LIMIT:
        raise HTTPException(status_code=400, detail=f"Send at most {SEND_BATCH_LIMIT} per batch.")
    base_url = str(request.base_url).rstrip("/")
    out = []
    for r in req.recipients:
        rendered = _render(comp, theme, req.template_type, req.subject_template, req.body_template, r, req.message_body)
        if req.dry_run:
            ok = "@" in rendered["recipient_email"] and not rendered["unresolved_placeholders"]
            out.append({"recipient_email": rendered["recipient_email"], "status": "ok" if ok else "skipped",
                        "detail": "" if ok else ("No email address" if "@" not in rendered["recipient_email"]
                                                 else "Template needs: " + ", ".join(rendered["unresolved_placeholders"]))})
            continue
        out.append(_deliver(comp, theme, req.template_type, rendered, base_url, None, r.get("donor_id")))
    summary = {s: sum(1 for x in out if x["status"] == s) for s in ("sent", "ok", "skipped", "failed")}
    return {"results": out, "summary": summary, "dry_run": req.dry_run}


class CampaignRequest(BaseModel):
    company_id: str
    name: str
    segment: Optional[Dict[str, Any]] = None
    donor_ids: Optional[List[str]] = None
    extra: Optional[List[Dict[str, Any]]] = None
    theme: Optional[str] = None
    template_type: str = "general_custom"
    subject_template: Optional[str] = None
    body_template: Optional[str] = None
    message_body: Optional[str] = None
    exclude_emailed_days: Optional[int] = None
    exclude_other_pending: bool = True


@router.post("/campaigns")
def create_campaign(req: CampaignRequest, request: Request):
    """Queues one segment with one template. Recipients are fixed now (pending), then sent in batches."""
    comp = _company(req.company_id)
    theme = _resolve_theme(comp, req.theme)
    if not (req.name or "").strip():
        raise HTTPException(status_code=400, detail="Give the campaign a name.")
    conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=10)
    try:
        if req.subject_template is None or req.body_template is None:
            _get_template(conn.cursor(), theme, req.template_type)  # 404 if the theme has no such template
    finally:
        conn.close()
    rows = _resolve_recipients(comp, req.segment, req.donor_ids, req.extra)
    skip = set()
    if req.exclude_emailed_days:
        skip |= _recently_emailed(comp, int(req.exclude_emailed_days))
    if req.exclude_other_pending:
        conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=10)
        try:
            skip |= {r[0] for r in conn.execute("""SELECT LOWER(m.recipient_email) FROM crm_email_messages m
                        JOIN crm_email_campaigns c ON c.id = m.campaign_id
                        WHERE m.company_id = ? AND m.status = 'pending' AND c.status = 'queued'""", (comp,))}
        finally:
            conn.close()
    rows = [r for r in rows if r["email"].lower() not in skip]
    if not rows:
        raise HTTPException(status_code=400, detail="Nobody to email: the segment has no one with an email address (after exclusions).")
    user = _user(request)
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=15.0)
    try:
        with conn:
            cur = conn.execute("""INSERT INTO crm_email_campaigns (company_id, name, segment_json, template_type, theme, subject, body_html,
                                      message_body, status, created_by, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, CURRENT_TIMESTAMP)""",
                               (comp, req.name.strip(), json.dumps({"segment": req.segment, "donor_ids": req.donor_ids, "extra": req.extra,
                                                                     "exclude_emailed_days": req.exclude_emailed_days}),
                                req.template_type, theme, req.subject_template, req.body_template, req.message_body, user.get("email")))
            cid = cur.lastrowid
            conn.executemany("""INSERT OR IGNORE INTO crm_email_messages (company_id, campaign_id, donor_id, recipient_email, recipient_name,
                                    template_type, theme, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                             [(comp, cid, r["donor_id"], r["email"], r["name"], req.template_type, theme) for r in rows])
    finally:
        conn.close()
    return {"campaign_id": cid, "queued": len(rows), "excluded": len(skip & {r['email'].lower() for r in rows})}


def _campaign(conn, comp: str, cid: int) -> Dict[str, Any]:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM crm_email_campaigns WHERE id = ? AND company_id = ?", (cid, comp)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Campaign not found for this charity.")
    return dict(row)


@router.get("/campaigns")
def list_campaigns(company_id: str = Query(...)):
    comp = _company(company_id)
    conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute("""
            SELECT c.id, c.name, c.template_type, c.theme, c.status, c.created_by, c.created_at, c.segment_json,
                   SUM(m.status = 'pending') AS pending, SUM(m.status = 'sent') AS sent, SUM(m.status = 'failed') AS failed,
                   SUM(m.status = 'skipped') AS skipped, SUM(COALESCE(m.open_count, 0) > 0) AS opened, COUNT(m.id) AS total
            FROM crm_email_campaigns c LEFT JOIN crm_email_messages m ON m.campaign_id = c.id
            WHERE c.company_id = ? GROUP BY c.id ORDER BY c.id DESC LIMIT 200""", (comp,))]
    finally:
        conn.close()
    for r in rows:
        try:
            r["segment"] = (json.loads(r.pop("segment_json") or "{}") or {}).get("segment")
        except ValueError:
            r["segment"] = None
    return {"campaigns": rows}


@router.get("/campaigns/{campaign_id}/messages")
def campaign_messages(campaign_id: int, company_id: str = Query(...), status: Optional[str] = Query(None),
                      page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500)):
    comp = _company(company_id)
    conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=10)
    try:
        _campaign(conn, comp, campaign_id)
        where, params = "campaign_id = ? AND company_id = ?", [campaign_id, comp]
        if status:
            where += " AND status = ?"
            params.append(status)
        total = conn.execute(f"SELECT COUNT(*) FROM crm_email_messages WHERE {where}", params).fetchone()[0]
        rows = [dict(r) for r in conn.execute(f"""SELECT id, donor_id, recipient_email, recipient_name, status, detail, sent_at,
                    opened_at, open_count FROM crm_email_messages WHERE {where} ORDER BY id LIMIT ? OFFSET ?""",
                                              params + [page_size, (page - 1) * page_size])]
    finally:
        conn.close()
    return {"total": total, "page": page, "messages": rows}


class CampaignSendRequest(BaseModel):
    company_id: str
    limit: int = SEND_BATCH_LIMIT
    dry_run: bool = False


@router.post("/campaigns/{campaign_id}/send")
def send_campaign_batch(campaign_id: int, req: CampaignSendRequest, request: Request):
    """Sends the next batch of a campaign's pending messages (the screen repeats until none are left)."""
    comp = _company(req.company_id)
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=15.0)
    try:
        c = _campaign(conn, comp, campaign_id)
        if c["status"] not in ("queued", "sending"):
            raise HTTPException(status_code=400, detail=f"This campaign is {c['status']}.")
        pending = [dict(r) for r in conn.execute("""SELECT id, donor_id, recipient_email, recipient_name FROM crm_email_messages
                       WHERE campaign_id = ? AND company_id = ? AND status = 'pending' ORDER BY id LIMIT ?""",
                                                 (campaign_id, comp, max(1, min(int(req.limit), SEND_BATCH_LIMIT))))]
        if not req.dry_run:
            with conn:
                conn.execute("UPDATE crm_email_campaigns SET status = 'sending', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (campaign_id,))
    finally:
        conn.close()
    base_url = str(request.base_url).rstrip("/")
    out = []
    for m in pending:
        rendered = _render(comp, c["theme"], c["template_type"], c["subject"], c["body_html"],
                           {"donor_id": m["donor_id"], "email": m["recipient_email"], "name": m["recipient_name"]}, c.get("message_body"))
        if req.dry_run:
            ok = not rendered["unresolved_placeholders"]
            out.append({"recipient_email": m["recipient_email"], "status": "ok" if ok else "skipped",
                        "detail": "" if ok else "Template needs: " + ", ".join(rendered["unresolved_placeholders"])})
            continue
        out.append(_deliver(comp, c["theme"], c["template_type"], rendered, base_url, campaign_id, m["donor_id"], m["id"]))
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=15.0)
    try:
        left = conn.execute("SELECT COUNT(*) FROM crm_email_messages WHERE campaign_id = ? AND status = 'pending'", (campaign_id,)).fetchone()[0]
        if not req.dry_run and left == 0:
            with conn:
                conn.execute("UPDATE crm_email_campaigns SET status = 'done', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (campaign_id,))
    finally:
        conn.close()
    return {"results": out, "remaining": left, "summary": {s: sum(1 for x in out if x["status"] == s) for s in ("sent", "ok", "skipped", "failed")}}


class CampaignActionRequest(BaseModel):
    company_id: str


@router.post("/campaigns/{campaign_id}/cancel")
def cancel_campaign(campaign_id: int, req: CampaignActionRequest):
    comp = _company(req.company_id)
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=15.0)
    try:
        _campaign(conn, comp, campaign_id)
        with conn:
            n = conn.execute("UPDATE crm_email_messages SET status = 'skipped', detail = 'Campaign cancelled' "
                             "WHERE campaign_id = ? AND company_id = ? AND status = 'pending'", (campaign_id, comp)).rowcount
            conn.execute("UPDATE crm_email_campaigns SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (campaign_id,))
    finally:
        conn.close()
    return {"cancelled": n}


@router.delete("/campaigns/{campaign_id}")
def delete_campaign(campaign_id: int, company_id: str = Query(...)):
    """Only a campaign that hasn't sent anything can be deleted (sent history is kept)."""
    comp = _company(company_id)
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=15.0)
    try:
        _campaign(conn, comp, campaign_id)
        if conn.execute("SELECT COUNT(*) FROM crm_email_messages WHERE campaign_id = ? AND status = 'sent'", (campaign_id,)).fetchone()[0]:
            raise HTTPException(status_code=400, detail="This campaign has sent emails; cancel it instead (history is kept).")
        with conn:
            conn.execute("DELETE FROM crm_email_messages WHERE campaign_id = ? AND company_id = ?", (campaign_id, comp))
            conn.execute("DELETE FROM crm_email_campaigns WHERE id = ? AND company_id = ?", (campaign_id, comp))
    finally:
        conn.close()
    return {"deleted": campaign_id}


@router.get("/history")
def donor_email_history(company_id: str = Query(...), email: str = Query(...)):
    """Every direct email to one address (for the donor panel)."""
    comp = _company(company_id)
    conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute("""SELECT m.id, m.subject, m.status, m.detail, m.sent_at, m.opened_at, m.open_count,
                       m.template_type, c.name AS campaign FROM crm_email_messages m LEFT JOIN crm_email_campaigns c ON c.id = m.campaign_id
                       WHERE m.company_id = ? AND LOWER(m.recipient_email) = LOWER(?) ORDER BY m.id DESC LIMIT 200""", (comp, email.strip()))]
    finally:
        conn.close()
    return {"emails": rows}
