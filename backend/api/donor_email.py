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
import re
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Union

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from config.settings import LOCAL_DB_PATH
from backend.api.unsubscribe import is_unsubscribed
from backend.api.tracker import (
    THEME_OWNER_COMPANY, _PLACEHOLDER_RE, _get_outlook_auth_row, _get_template, _get_valid_graph_token,
    _prepare_outgoing_html, _render_text, _resolve_theme, tracker_access_guard,
)

router = APIRouter(prefix="/api/tracker/direct-email", tags=["Direct donor email"],
                   dependencies=[Depends(tracker_access_guard)])

SEND_BATCH_LIMIT = 25
DEFAULT_MESSAGE = "Thank you for your generous support."
MAX_RECIPIENTS = 5000


MESSAGE_COLS = ("id, company_id, campaign_id, donor_id, recipient_email, recipient_name, subject, body_html, template_type, theme, "
                "status, detail, tracking_id, sender_email, sent_at, opened_at, open_count, created_at, extra_json, replied_at, kind")


def _allow_several_per_person(conn: sqlite3.Connection) -> None:
    """A queued campaign can hold several emails for one person (one per sponsorship, "part" = its allocation id):
    the old UNIQUE(campaign_id, recipient_email) becomes UNIQUE(campaign_id, recipient_email, part). SQLite can't
    change a constraint in place, so the table is rebuilt once, inside one transaction (rows and ids kept)."""
    sql = (conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'crm_email_messages'").fetchone() or [""])[0]
    if "part" in sql:
        return
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        sql = (conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'crm_email_messages'").fetchone() or [""])[0]
        if "part" in sql:  # the other worker did it first
            conn.rollback()
            return
        conn.execute("""CREATE TABLE crm_email_messages_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL, campaign_id INTEGER, donor_id TEXT,
            recipient_email TEXT, recipient_name TEXT, subject TEXT, body_html TEXT, template_type TEXT, theme TEXT,
            status TEXT DEFAULT 'pending', detail TEXT, tracking_id TEXT, sender_email TEXT, sent_at TEXT,
            opened_at TEXT, open_count INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            extra_json TEXT, replied_at TEXT, kind TEXT, part TEXT NOT NULL DEFAULT '',
            UNIQUE(campaign_id, recipient_email, part))""")
        conn.execute(f"INSERT INTO crm_email_messages_new ({MESSAGE_COLS}) SELECT {MESSAGE_COLS} FROM crm_email_messages")
        before = conn.execute("SELECT COUNT(*) FROM crm_email_messages").fetchone()[0]
        after = conn.execute("SELECT COUNT(*) FROM crm_email_messages_new").fetchone()[0]
        if before != after:
            raise RuntimeError(f"crm_email_messages rebuild copied {after} of {before} rows")
        conn.execute("DROP TABLE crm_email_messages")
        conn.execute("ALTER TABLE crm_email_messages_new RENAME TO crm_email_messages")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


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
            extra_json TEXT, replied_at TEXT, kind TEXT, part TEXT NOT NULL DEFAULT '',
            UNIQUE(campaign_id, recipient_email, part))""")
        if "message_body" not in {r[1] for r in conn.execute("PRAGMA table_info(crm_email_campaigns)")}:
            conn.execute("ALTER TABLE crm_email_campaigns ADD COLUMN message_body TEXT")
        msg_cols = {r[1] for r in conn.execute("PRAGMA table_info(crm_email_messages)")}
        for col, typ in (("extra_json", "TEXT"), ("replied_at", "TEXT"), ("kind", "TEXT")):
            if col not in msg_cols:
                try:
                    conn.execute(f"ALTER TABLE crm_email_messages ADD COLUMN {col} {typ}")
                except sqlite3.OperationalError:
                    pass  # the other worker added it at the same moment
        _allow_several_per_person(conn)
        # Replies to emails sent from here (Donors / campaigns / single emails); sponsorship replies live in
        # sponsorship_communications. Filled by the tracker's reply sync (tracker._record_inbound_reply).
        conn.execute("""CREATE TABLE IF NOT EXISTS crm_email_replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL, message_id TEXT, conversation_id TEXT,
            reply_to_id INTEGER, sender_email TEXT, subject TEXT, body_preview TEXT, received_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(company_id, message_id))""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_email_replies_sender ON crm_email_replies(company_id, sender_email)")
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
                        "phone": _clean(r.get("phone")) or "",
                        "total": _clean(r.get("total")), "gifts": _clean(r.get("gifts")), "tier": _clean(r.get("tier")),
                        "last_gift": str(_clean(r.get("last_gift")) or "")[:10],
                        # one row per person; what their matching donations were (donation-based search)
                        "matched_gifts": _clean(r.get("matched_gifts")), "matched_total": _clean(r.get("matched_total")),
                        "matched_causes": _clean(r.get("matched_causes")) or "",
                        "matched_sponsorships": _clean(r.get("matched_sponsorships")) or "",
                        "matched_last": _clean(r.get("matched_last")) or "",
                        "allocations": _clean(r.get("allocations")) or 0,
                        "sponsorship_statuses": _clean(r.get("sponsorship_statuses")) or "",
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
    # the name the sender sees for this person (donor panel / recipient list) wins over another spelling on
    # their donations, so the email doesn't say "Dear H" under a header that says "Zakaryya"
    name = (str(recipient.get("name") or "").strip() or str(row.get("name") or "").strip()) or "Friend"
    gifts = dx[dx["key"] == row.get("donor_id")].sort_values("date") if row and not dx.empty else None
    last = gifts.iloc[-1] if gifts is not None and len(gifts) else None
    money = lambda v: f"{float(_clean(v) or 0):,.2f}"  # noqa: E731
    v = {
        "first_name": name.split(" ")[0], "last_name": _last_name(name), "donor_name": name,
        "donor_first_name": name.split(" ")[0], "donor_last_name": _last_name(name), "email": recipient.get("email") or "",
        "recipient_email": recipient.get("email") or "",
        "total_given": money(row.get("total")), "gifts_count": str(int(row.get("gifts") or 0)),
        "average_gift": money(row.get("avg_gift")), "lifetime_tier": str(row.get("tier") or ""),
        "first_gift_date": str(row.get("first_gift") or "")[:10], "last_gift_date": str(row.get("last_gift") or "")[:10],
        "last_gift_amount": money(last["amount"]) if last is not None else "",
        "last_gift_cause": str((last["subheading"] or last["heading"] or "")) if last is not None else "",
        "top_cause": str(row.get("top_heading") or ""), "sponsorship_types": str(row.get("sponsorship_types") or ""),
        "subject": subject_template or "", "message_body": (message_body or "").strip() or DEFAULT_MESSAGE,
        # the donations that matched the filters this email was sent for (one email per person, all of them)
        "matching_gifts_count": str(int(_clean(recipient.get("matched_gifts")) or 0)) if recipient.get("matched_gifts") is not None else "",
        "matching_total": money(recipient.get("matched_total")) if recipient.get("matched_total") is not None else "",
        "matching_causes": str(recipient.get("matched_causes") or ""),
        "matching_sponsorships": str(recipient.get("matched_sponsorships") or ""),
    }
    # Sponsorship placeholders: ALL of the donor's sponsorships in one email. One sponsorship fills the fields as
    # before; several are combined ("Ahmed, Fatima and Bilal") and listed in {sponsorships_list}.
    em = str(recipient.get("email") or "").strip().lower()
    if em:
        allocs = donor_sponsorships(comp, em)
        if allocs:
            v.update(_sponsorship_vars(allocs))
    return v


def _sponsorship_vars(allocs: List[Dict[str, Any]]) -> Dict[str, str]:
    """Sponsorship placeholders for these sponsorships (all of a donor's, or the ones picked for this email).
    One fills the fields with its own values; several are combined ("Ahmed, Fatima and Bilal") and listed in
    {sponsorships_list}."""
    a = allocs[0]  # latest - its links / dates fill the single-value fields
    days_rem = ""
    if a.get("end_date"):
        try:
            days_diff = (datetime.datetime.strptime(str(a["end_date"])[:10], "%Y-%m-%d").date() - datetime.date.today()).days
            days_rem = f"{days_diff} days" if days_diff >= 0 else f"{-days_diff} days overdue"
        except Exception:
            pass
    v = {
        "beneficiary_name": a.get("beneficiary_name") or "",
        "beneficiary_first_name": _first_name(a.get("beneficiary_name")),
        "beneficiary_last_name": _last_name(a.get("beneficiary_name")),
        "sponsorship_type": a.get("b_type") or a.get("sponsorship_type") or "",
        "location": a.get("b_location") or "", "project_code": a.get("b_code") or "",
        "profile_link": a.get("b_profile") or a.get("profile_link") or "", "video_link": a.get("b_video") or "",
        "report_link": a.get("b_profile") or "", "donor_folder_link": a.get("b_folder") or a.get("b_profile") or "",
        "folder_link": a.get("b_folder") or a.get("b_profile") or "",
        "campaign_name": a.get("campaign_name") or "", "community_name": a.get("community_name") or "",
        "renewal_deadline": str(a.get("end_date") or "")[:10],
        "days_remaining": days_rem,
        "sponsorship_year": (str(a.get("start_date") or ""))[:4],
    }
    combined = _combined_sponsorship_vars(allocs)
    if len(allocs) == 1:  # one sponsorship: keep its own values, add the list/count
        combined = {k: combined[k] for k in ("beneficiary_names", "beneficiary_first_names", "sponsorships_count", "sponsorships_list", "video_buttons")}
    v.update(combined)
    return v


def _selected_ids(sel: Any) -> List[int]:
    """The sponsorships picked for one email: an id, a list of ids, or nothing (= all of them)."""
    items = sel if isinstance(sel, (list, tuple)) else ([sel] if sel not in (None, "") else [])
    out = []
    for x in items:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            pass
    return out


def _separate_selections(comp: str, email: str, sel: Any) -> List[List[int]]:
    """For "one email per sponsorship": a selection per email - each ticked sponsorship (or each of the donor's
    sponsorships when none is ticked). Empty when the donor has fewer than two, so they just get the one email."""
    allocs = donor_sponsorships(comp, email) if email else []
    if len(allocs) < 2:
        return []
    picked = _selected_ids(sel)
    ids = [a["id"] for a in allocs if not picked or a["id"] in picked]
    return [[i] for i in ids] if len(ids) > 1 else []


def _person_emails(comp: str, email: str, cust: Dict[str, Any], template_type: str, subject_tpl: Optional[str],
                   body_tpl: Optional[str], separate_default: bool = False) -> List[Dict[str, Any]]:
    """Every email one person gets, in order: the main one (or one per sponsorship when "separate"), then any extra
    emails the sender added. Each can use its own template: cust["templates"] maps a sponsorship id ("all" for the
    combined email) to a template, cust["extra_emails"] is [{template_type, selected_allocation_id}].
    part identifies the email within a campaign ('' / allocation id / 'extra1', ...)."""
    def tpl(t: Optional[str]):  # the composer's (possibly edited) text applies only to its own template
        t = t or template_type
        return (t, subject_tpl, body_tpl) if t == template_type else (t, None, None)
    sel = cust.get("selected_allocation_id")
    separate = cust["separate"] if cust.get("separate") is not None else separate_default
    templates = {str(k): v for k, v in (cust.get("templates") or {}).items() if v}
    parts = separate and _separate_selections(comp, email, sel)
    out = ([{"template": tpl(templates.get(str(p[0]))), "sel": p, "part": str(p[0])} for p in parts] if parts
           else [{"template": tpl(templates.get("all")), "sel": sel, "part": ""}])
    for i, x in enumerate(cust.get("extra_emails") or []):
        if isinstance(x, dict):
            out.append({"template": tpl(x.get("template_type")), "sel": x.get("selected_allocation_id"), "part": f"extra{i + 1}"})
    return out


def donor_sponsorships(comp: str, email: str) -> List[Dict[str, Any]]:
    """Every sponsorship (allocation) this address is a donor on, latest first, with its beneficiary and status."""
    from backend.api.donors import sponsorship_cycle_status
    conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute("""
            SELECT DISTINCT a.*, b.name AS beneficiary_name, b.sponsorship_type AS b_type, b.location AS b_location,
                   b.profile_link AS b_profile, b.video_link AS b_video, b.project_code AS b_code, b.donor_folder_link AS b_folder
            FROM sponsorship_allocation_donors d JOIN sponsorship_allocations a ON a.id = d.allocation_id
            LEFT JOIN sponsorship_beneficiaries b ON b.id = a.beneficiary_id
            WHERE LOWER(a.company_id) = ? AND LOWER(TRIM(d.donor_email)) = ?
            ORDER BY COALESCE(a.start_date, '') DESC, a.id DESC""", (comp, (email or "").strip().lower()))]
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    seen, out = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        r["cycle_status"] = sponsorship_cycle_status(r.get("start_date"), r.get("end_date"))
        out.append(r)
    return out


def _first_name(name: Optional[str]) -> str:
    """The beneficiary's first name ("Ahmed Ali Hassan" -> "Ahmed")."""
    parts = str(name or "").split()
    return parts[0] if parts else ""


def _last_name(name: Optional[str]) -> str:
    """Everything after the first name ("Ahmed Ali Hassan" -> "Ali Hassan"); empty for a single-word name."""
    parts = str(name or "").split()
    return " ".join(parts[1:])


def _join_names(names: List[str]) -> str:
    names = [n for n in dict.fromkeys(n.strip() for n in names if n and n.strip())]
    return names[0] if len(names) == 1 else (", ".join(names[:-1]) + " and " + names[-1]) if names else ""


def _combined_sponsorship_vars(allocs: List[Dict[str, Any]]) -> Dict[str, str]:
    import html as _html
    items, buttons = [], []
    for a in allocs:
        name = a.get("beneficiary_name") or a.get("campaign_name") or "Sponsorship"
        bits = [b for b in (a.get("b_type") or a.get("sponsorship_type"), a.get("b_location")) if b]
        link = a.get("b_profile") or a.get("profile_link") or ""
        video = a.get("b_video") or ""
        line = f"<b>{_html.escape(name)}</b>" + (f" - {_html.escape(', '.join(bits))}" if bits else "")
        if a.get("end_date"):
            line += f" (renewal {_html.escape(str(a['end_date'])[:10])})"
        links = ([f'<a href="{_html.escape(link, quote=True)}">View Profile</a>'] if link else []) + \
                ([f'<a href="{_html.escape(video, quote=True)}">Watch Video</a>'] if video else [])
        if links:
            line += f" ({' &middot; '.join(links)})"
        items.append(f'<li style="margin: 4px 0;">{line}</li>')
        if video:
            label = _first_name(a.get("beneficiary_name")) or name
            buttons.append(
                f'<a href="{_html.escape(video, quote=True)}" target="_blank" style="display: inline-block; '
                'padding: 10px 22px; background-color: #0284C7; color: #FFFFFF; font-family: Arial,Helvetica,sans-serif; '
                'text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px; line-height: 1.2;">'
                f'&#9658; Watch {_html.escape(label)}\'s Video</a>')
    return {
        "beneficiary_name": _join_names([a.get("beneficiary_name") or "" for a in allocs]),
        "beneficiary_names": _join_names([a.get("beneficiary_name") or "" for a in allocs]),
        "beneficiary_first_name": _join_names([_first_name(a.get("beneficiary_name")) for a in allocs]),
        "beneficiary_first_names": _join_names([_first_name(a.get("beneficiary_name")) for a in allocs]),
        "beneficiary_last_name": _join_names([_last_name(a.get("beneficiary_name")) for a in allocs]),
        "sponsorship_type": _join_names([a.get("b_type") or a.get("sponsorship_type") or "" for a in allocs]),
        "location": _join_names([a.get("b_location") or "" for a in allocs]),
        "project_code": _join_names([a.get("b_code") or "" for a in allocs]),
        "sponsorships_count": str(len(allocs)),
        "sponsorships_list": f'<ul style="margin: 8px 0; padding-left: 20px;">{"".join(items)}</ul>',
        # One "Watch ...'s Video" button per beneficiary that has a video (empty = the send is held, like {video_link})
        "video_buttons": _button_rows(buttons) if buttons else "",
        "profile_link": allocs[0].get("b_profile") or allocs[0].get("profile_link") or "",
        "video_link": allocs[0].get("b_video") or "",
        "renewal_deadline": min((str(a.get("end_date"))[:10] for a in allocs if a.get("end_date")), default=""),
    }


_LINK_BUTTON_PLACEHOLDERS = (("profile_link", ("b_profile", "profile_link")), ("video_link", ("b_video",)),
                             ("donor_folder_link", ("b_folder",)), ("folder_link", ("b_folder",)))
# {name} or {{name}}, as _render_text accepts both
def _ph_re(ph: str) -> str:
    return r"\{\{?\s*" + ph + r"\s*\}?\}"


_LINK_BUTTON_RES = {ph: re.compile(r"<a\b[^>]*" + _ph_re(ph) + r"[^>]*>(.*?)</a>", re.I | re.S)
                    for ph, _ in _LINK_BUTTON_PLACEHOLDERS}
# The template's whole button block: the innermost <table> that holds the placeholder anchor (buttons in these
# templates are a coloured <td> around the <a>, so the copy must include it to keep its own rounded background)
_LINK_BUTTON_TABLE_RES = {ph: re.compile(r"<table\b(?:(?!</?table\b)[\s\S])*?" + _ph_re(ph) + r"(?:(?!</?table\b)[\s\S])*?</table>", re.I)
                          for ph, _ in _LINK_BUTTON_PLACEHOLDERS}


def _button_rows(buttons: List[str]) -> str:
    """Stacks buttons with real spacing in email clients: td padding survives where div/table margins are
    stripped (Outlook), so the buttons don't fuse into one solid block."""
    rows = "".join(f'<tr><td style="padding: 6px 0;" align="left">{b}</td></tr>' for b in buttons)
    return f'<table role="presentation" border="0" cellpadding="0" cellspacing="0" style="border-collapse: collapse;">{rows}</table>'


def _beneficiary_links(allocs: List[Dict[str, Any]], keys) -> List[tuple]:
    links = []
    for a in allocs:
        link = str(next((a.get(k) for k in keys if a.get(k)), "") or "").strip()
        if link:
            links.append((link, _first_name(a.get("beneficiary_name")) or str(a.get("beneficiary_name") or "")))
    return links


def _multiply_link_buttons(body: str, allocs: List[Dict[str, Any]]) -> str:
    """A combined email about several beneficiaries: the button/link whose href is {profile_link}, {video_link} or
    {donor_folder_link}/{folder_link} becomes one per beneficiary ("View Profile Document – Joudi"), each with that
    beneficiary's own link and its own styling. With fewer than two distinct links (e.g. everyone shares one video
    or folder) the template is left alone and the single link fills as before."""
    import html as _html

    def anchor_copy(m, ph, link, who):
        head = m.group(0)[:m.start(1) - m.start(0)]
        return (re.sub(_ph_re(ph), _html.escape(link, quote=True), head)
                + m.group(1).strip() + (f" &ndash; {_html.escape(who)}" if who else "") + "</a>")

    for ph, keys in _LINK_BUTTON_PLACEHOLDERS:
        links = _beneficiary_links(allocs, keys)
        if len(links) < 2 or len({l for l, _ in links}) < 2:  # none/one/all-the-same: keep the single link
            continue

        def table_repl(tm, ph=ph):
            t = tm.group(0)
            am = _LINK_BUTTON_RES[ph].search(t)
            if not am:  # placeholder in this table but not inside an <a> (e.g. plain text) - leave it
                return t
            open_tag = re.match(r"<table\b[^>]*>", t).group(0)
            # the copies stack in our own rows: drop the float/margins from the template's button table
            neutral = re.sub(r'\s(?:align|width)="[^"]*"', "", open_tag)
            neutral = re.sub(r'(style="[^"]*?)margin[^;"]*;?', r"\1", neutral)
            copies = [neutral + t[len(open_tag):am.start()] + anchor_copy(am, ph, link, who) + t[am.end():]
                      for link, who in links]
            return _button_rows(copies)

        new = _LINK_BUTTON_TABLE_RES[ph].sub(table_repl, body)
        # a placeholder link outside any table (e.g. the underlined folder link) duplicates as plain stacked links
        body = _LINK_BUTTON_RES[ph].sub(lambda m, ph=ph: _button_rows([anchor_copy(m, ph, l, w) for l, w in links]), new)
    return body


def _render(comp: str, theme: str, template_type: str, subject_tpl: Optional[str], body_tpl: Optional[str],
            recipient: Dict[str, Any], message_body: Optional[str] = None,
            custom_variables: Optional[Dict[str, str]] = None,
            selected_allocation_id: Any = None) -> Dict[str, Any]:
    if subject_tpl is None or body_tpl is None:
        conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=10)
        try:
            tpl = _get_template(conn.cursor(), theme, template_type)
        finally:
            conn.close()
        subject_tpl = tpl["subject"] if subject_tpl is None else subject_tpl
        body_tpl = tpl["body_html"] if body_tpl is None else body_tpl
    variables = _donor_variables(comp, recipient, subject_tpl, message_body)

    # The sender may pick which of the donor's sponsorships this email is about (one, several or all)
    em = str(recipient.get("email") or "").strip().lower()
    allocs = donor_sponsorships(comp, em) if em else []
    picked_ids = _selected_ids(selected_allocation_id)
    picked = [al for al in allocs if al.get("id") in picked_ids]
    if picked and len(picked) < len(allocs):
        for k in ("beneficiary_names", "beneficiary_first_names", "sponsorships_count", "sponsorships_list", "video_buttons"):
            variables.pop(k, None)
        variables.update(_sponsorship_vars(picked))
    about = picked if picked and len(picked) < len(allocs) else allocs
    if len(about) > 1:  # one profile / video button per beneficiary instead of one shared one
        body_tpl = _multiply_link_buttons(body_tpl, about)

    # Apply sender-provided custom variables so missing fields are not skipped
    if custom_variables:
        for k, val in custom_variables.items():
            if val is not None and str(val).strip() != "":
                variables[k.lower()] = str(val).strip()

    subject = _render_text(subject_tpl, variables)
    variables["subject"] = subject
    unresolved = sorted({m.group(1) for m in _PLACEHOLDER_RE.finditer(subject_tpl + body_tpl)
                         if m.group(1).lower() not in {k.lower() for k, val in variables.items() if val not in (None, "")}})

    sponsorships_data = [{
        "id": a["id"],
        "allocation_id": a["id"],
        "beneficiary_name": a.get("beneficiary_name") or a.get("campaign_name") or "Sponsorship",
        "sponsorship_type": a.get("b_type") or a.get("sponsorship_type") or "",
        "location": a.get("b_location") or "",
        "project_code": a.get("b_code") or "",
        "profile_link": a.get("b_profile") or a.get("profile_link") or "",
        "video_link": a.get("b_video") or "",
        "start_date": str(a.get("start_date") or "")[:10],
        "end_date": str(a.get("end_date") or "")[:10],
        "cycle_status": a.get("cycle_status") or ""
    } for a in allocs]

    return {
        "recipient_email": recipient.get("email") or "",
        "recipient_name": variables["donor_name"],
        "subject": subject,
        "body_html": _render_text(body_tpl, variables),
        "unresolved_placeholders": unresolved,
        "variables": variables,
        "sponsorships": sponsorships_data,
        "selected_allocation_ids": [a["id"] for a in picked] if picked and len(picked) < len(allocs) else [],
        "has_multiple_beneficiaries": len(sponsorships_data) > 1,
        "beneficiaries_count": len(sponsorships_data)
    }


MATCH_FIELDS = ("matched_gifts", "matched_total", "matched_causes", "matched_sponsorships")


def _deliver(comp: str, theme: str, template_type: str, rendered: Dict[str, Any], base_url: str,
             campaign_id: Optional[int], donor_id: Optional[str], message_id: Optional[int] = None,
             kind: Optional[str] = None) -> Dict[str, Any]:
    to = (rendered["recipient_email"] or "").strip()
    result = {"recipient_email": to, "status": "sent", "detail": ""}
    if "@" not in to:
        result.update(status="skipped", detail="No email address")
    elif rendered["unresolved_placeholders"]:
        result.update(status="skipped", detail="Template needs: " + ", ".join(rendered["unresolved_placeholders"]))
    elif is_unsubscribed(comp, to):
        result.update(status="skipped", detail="Unsubscribed from emails")
    tracking_id, sender = None, None
    if result["status"] == "sent":
        # this charity's own mailbox (Gmail or Microsoft 365); Sisters' Project templates go from SP's own mailbox
        from backend.api.mailbox import is_connected, mailbox_for, mailbox_label, provider, send_email
        mbx = mailbox_for(comp, theme)
        if not is_connected(mbx):  # stop the whole send, as before, rather than failing every person
            raise HTTPException(status_code=400, detail=f"{mailbox_label(mbx)}'s {'Gmail' if provider(mbx) == 'gmail' else 'Microsoft 365'} mailbox isn't connected - connect it in Email > Mailbox.")
        tracking_id = str(uuid.uuid4())
        html = _prepare_outgoing_html(rendered["body_html"], f"{base_url}/api/tracker/email-tracking/pixel/{tracking_id}",
                                      comp, to, tracking_id)
        try:
            res = send_email(mbx, [(to, rendered["recipient_name"])], rendered["subject"].strip(), html)
        except HTTPException as e:
            res = {"ok": False, "detail": str(e.detail)}
        sender = res.get("sender")
        result["sender_email"] = sender
        if not res["ok"]:
            result.update(status="failed", detail=res["detail"][:300])
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
                                    template_type, theme, subject, body_html, status, detail, tracking_id, sender_email, sent_at, kind)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                             (comp, campaign_id, donor_id, to, rendered["recipient_name"], template_type, theme, *vals,
                              kind or ("campaign" if campaign_id else "bulk")))
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


class EmailLookupRequest(BaseModel):
    company_id: str
    emails: Union[List[str], str]


@router.post("/lookup-emails")
def lookup_emails(req: EmailLookupRequest):
    """Batch parses comma/newline/space-separated emails, checks them against CRM donors/sponsorships,
    and returns matched donors, missing emails, and malformed/problem entries."""
    comp = _company(req.company_id)
    raw_tokens = []
    if isinstance(req.emails, str):
        raw_tokens = re.split(r"[\s,;\n\r]+", req.emails)
    elif isinstance(req.emails, list):
        for item in req.emails:
            raw_tokens.extend(re.split(r"[\s,;\n\r]+", str(item or "")))

    cleaned_tokens = [t.strip() for t in raw_tokens if t and t.strip()]

    # Deduplicate while preserving order
    seen = set()
    unique_tokens = []
    for t in cleaned_tokens:
        lower = t.lower()
        if lower not in seen:
            seen.add(lower)
            unique_tokens.append(t)

    valid_emails = []
    invalid_items = []

    for t in unique_tokens:
        # Check basic email validity
        if "@" in t and "." in t.split("@")[-1] and len(t) >= 5:
            if re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", t):
                valid_emails.append(t)
            else:
                invalid_items.append({"raw": t, "reason": "Invalid email format"})
        else:
            invalid_items.append({"raw": t, "reason": "Invalid email syntax"})

    from backend.api.donors import _directory_data
    frame, dx = _directory_data(comp)

    matched = []
    missing = []
    matched_emails_lower = set()

    if frame is not None and not frame.empty and valid_emails:
        norm_map = {e.lower(): e for e in valid_emails}
        hits = frame[frame["email"].fillna("").str.lower().isin(norm_map.keys())]
        for r in hits.to_dict(orient="records"):
            em = str(r.get("email") or "").strip()
            em_lower = em.lower()
            if em_lower in norm_map and em_lower not in matched_emails_lower:
                matched_emails_lower.add(em_lower)
                matched.append({
                    "donor_id": _clean(r.get("donor_id")),
                    "email": norm_map[em_lower],
                    "name": _clean(r.get("name")) or "",
                    "phone": _clean(r.get("phone")) or "",
                    "total": _clean(r.get("total")),
                    "gifts": _clean(r.get("gifts")),
                    "allocations": _clean(r.get("allocations")) or 0,
                    "sponsorship_types": _clean(r.get("sponsorship_types")) or "",
                    "last_gift": str(_clean(r.get("last_gift")) or "")[:10]
                })

    # Check database sponsorship_allocations fallback if any are still missing
    still_missing = [e for e in valid_emails if e.lower() not in matched_emails_lower]
    if still_missing:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            placeholders = ",".join("?" for _ in still_missing)
            cur = conn.execute(
                f"""SELECT donor_id, donor_name, donor_email, donor_phone, COUNT(*) as alloc_count
                    FROM sponsorship_allocations
                    WHERE LOWER(donor_email) IN ({placeholders})
                    GROUP BY LOWER(donor_email)""",
                [e.lower() for e in still_missing]
            )
            for row in cur.fetchall():
                em = row["donor_email"]
                em_lower = em.lower()
                if em_lower not in matched_emails_lower:
                    matched_emails_lower.add(em_lower)
                    matched.append({
                        "donor_id": row["donor_id"] or em,
                        "email": em,
                        "name": row["donor_name"] or "",
                        "phone": row["donor_phone"] or "",
                        "total": None,
                        "gifts": None,
                        "allocations": row["alloc_count"],
                        "sponsorship_types": "Sponsorship",
                        "last_gift": ""
                    })
        except Exception:
            pass
        finally:
            conn.close()

    # Remaining valid emails are missing from CRM
    for e in valid_emails:
        if e.lower() not in matched_emails_lower:
            missing.append({"email": e, "reason": "Not found in CRM database"})

    return {
        "total": len(unique_tokens),
        "matched_count": len(matched),
        "missing_count": len(missing),
        "invalid_count": len(invalid_items),
        "matched": matched,
        "missing": missing,
        "invalid": invalid_items
    }


class PreviewRequest(BaseModel):
    company_id: str
    theme: Optional[str] = None
    template_type: str = "general_custom"
    subject_template: Optional[str] = None
class PreviewRequest(BaseModel):
    company_id: str
    theme: Optional[str] = None
    template_type: str = "general_custom"
    subject_template: Optional[str] = None
    body_template: Optional[str] = None
    message_body: Optional[str] = None
    recipient: Dict[str, Any]
    custom_variables: Optional[Dict[str, str]] = None
    selected_allocation_id: Optional[Union[int, List[int]]] = None  # one sponsorship, several, or none = all
    separate: bool = False  # one email per (ticked) sponsorship - the preview shows one of them
    preview_allocation_id: Optional[int] = None  # ...this one
    templates: Optional[Dict[str, str]] = None  # own template per email (sponsorship id, or "all" for the combined one)
    extra_emails: Optional[List[Dict[str, Any]]] = None  # more emails to the same person, any template
    preview_part: Optional[str] = None  # which of the person's emails to show


@router.post("/preview")
def preview(req: PreviewRequest):
    comp = _company(req.company_id)
    theme = _resolve_theme(comp, req.theme)
    em = str(req.recipient.get("email") or "").strip().lower()
    plan = _person_emails(comp, em, {"selected_allocation_id": req.selected_allocation_id, "separate": req.separate,
                                     "templates": req.templates, "extra_emails": req.extra_emails},
                          req.template_type, req.subject_template, req.body_template)
    want = req.preview_part if req.preview_part is not None else (str(req.preview_allocation_id) if req.preview_allocation_id else None)
    item = next((x for x in plan if x["part"] == want), plan[0])
    t, s_tpl, b_tpl = item["template"]
    out = _render(comp, theme, t, s_tpl, b_tpl, req.recipient, req.message_body, req.custom_variables, item["sel"])
    names = {a["id"]: a["beneficiary_name"] for a in out["sponsorships"]}
    out["emails"] = [{"part": x["part"], "template_type": x["template"][0],
                      "about": ", ".join(names.get(i, "") for i in _selected_ids(x["sel"]) if names.get(i)) or ("all their sponsorships" if names else "")}
                     for x in plan]
    out["previewing_part"] = item["part"]
    out["template_type"] = t
    out["separate_ids"] = [int(x["part"]) for x in plan if x["part"].isdigit()]
    out["previewing_allocation_id"] = int(item["part"]) if item["part"].isdigit() else None
    from backend.api.unsubscribe import add_footer  # show the Unsubscribe button exactly as it will be sent
    out["body_html"] = add_footer(out.get("body_html") or "", comp, out.get("recipient_email") or "")
    out["unsubscribed"] = is_unsubscribed(comp, out.get("recipient_email") or "")
    from backend.api.mailbox import sending_from
    out["sending_from"] = sending_from(comp, theme)
    return out


@router.get("/sending-from")
def get_sending_from(company_id: str = Query(...), theme: Optional[str] = Query(None)):
    """Which account an email with this theme is sent from (shown on every compose screen)."""
    comp = _company(company_id)
    from backend.api.mailbox import sending_from
    return sending_from(comp, _resolve_theme(comp, theme))


class SendRequest(BaseModel):
    company_id: str
    theme: Optional[str] = None
    template_type: str = "general_custom"
    subject_template: Optional[str] = None
    body_template: Optional[str] = None
    message_body: Optional[str] = None
    recipients: List[Dict[str, Any]]
    dry_run: bool = False
    kind: str = "bulk"  # "single" when written to one person from their donor panel
    custom_variables: Optional[Dict[str, str]] = None
    selected_allocation_id: Optional[Union[int, List[int]]] = None  # one sponsorship, several, or none = all
    separate_per_beneficiary: bool = False  # everyone with several sponsorships gets one email per sponsorship
    recipient_customizations: Optional[Dict[str, Dict[str, Any]]] = None


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
        em = str(r.get("email") or "").strip().lower()
        cust = (req.recipient_customizations or {}).get(em, {})
        c_vars = {**(req.custom_variables or {}), **(cust.get("custom_variables") or {})}
        msg_body = cust.get("message_body") or req.message_body
        plan = _person_emails(comp, em, {**cust, "selected_allocation_id": cust.get("selected_allocation_id") or req.selected_allocation_id},
                              req.template_type, req.subject_template, req.body_template, req.separate_per_beneficiary)
        for item in plan:
            t, s_tpl, b_tpl = item["template"]
            rendered = _render(comp, theme, t, s_tpl, b_tpl, r, msg_body, c_vars, item["sel"])
            if req.dry_run:
                ok = "@" in rendered["recipient_email"] and not rendered["unresolved_placeholders"]
                out.append({"recipient_email": rendered["recipient_email"], "status": "ok" if ok else "skipped",
                            "detail": "" if ok else ("No email address" if "@" not in rendered["recipient_email"]
                                                     else "Template needs: " + ", ".join(rendered["unresolved_placeholders"]))})
                continue
            out.append(_deliver(comp, theme, t, rendered, base_url, None, r.get("donor_id"),
                                kind="single" if req.kind == "single" else "bulk"))
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
    matched: Optional[List[Dict[str, Any]]] = None
    custom_variables: Optional[Dict[str, str]] = None
    separate_per_beneficiary: bool = False
    recipient_customizations: Optional[Dict[str, Dict[str, Any]]] = None


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
    # the screen sends the chosen people with what matched for each (the queue keeps it for {matching_...})
    matched = {str(m.get("email") or "").lower(): m for m in (req.matched or [])}
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
                                    template_type, theme, status, extra_json, kind, part) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, 'campaign', ?)""",
                             [(comp, cid, r["donor_id"], r["email"], r["name"], extra.get("template_type") or req.template_type, theme, json.dumps(extra), part)
                              for r in rows for extra, part in _campaign_parts(comp, r, matched, req)])
            queued = conn.execute("SELECT COUNT(*) FROM crm_email_messages WHERE campaign_id = ?", (cid,)).fetchone()[0]
    finally:
        conn.close()
    return {"campaign_id": cid, "queued": queued, "people": len(rows), "excluded": len(skip & {r['email'].lower() for r in rows})}


def _campaign_parts(comp: str, r: Dict[str, Any], matched: Dict[str, Any], req: "CampaignRequest"):
    """The queued emails for one person: (extra_json, part) per email. What the sender chose for this person in
    Compose (sponsorships ticked, separate emails, filled-in values, own message) is kept with each email."""
    em = r["email"].lower()
    cust = (req.recipient_customizations or {}).get(em, {})
    base = {k: matched.get(em, {}).get(k, r.get(k)) for k in MATCH_FIELDS}
    c_vars = {**(req.custom_variables or {}), **(cust.get("custom_variables") or {})}
    if c_vars:
        base["custom_variables"] = c_vars
    if cust.get("message_body"):
        base["message_body"] = cust["message_body"]
    out = []
    for item in _person_emails(comp, em, cust, req.template_type, None, None, req.separate_per_beneficiary):
        extra = {**base, **({"selected_allocation_id": item["sel"]} if item["sel"] else {})}
        if item["template"][0] != req.template_type:  # this email uses its own (saved) template
            extra["template_type"] = item["template"][0]
        out.append((extra, item["part"]))
    return out


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
                   MAX(m.sender_email) AS sender_email,
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
        rows = [dict(r) for r in conn.execute(f"""SELECT m.id, m.donor_id, m.recipient_email, m.recipient_name, m.status, m.detail, m.sent_at,
                    m.opened_at, m.open_count, m.template_type, b.name AS about FROM crm_email_messages m
                    LEFT JOIN sponsorship_allocations a ON m.part != '' AND a.id = CAST(m.part AS INTEGER)
                    LEFT JOIN sponsorship_beneficiaries b ON b.id = a.beneficiary_id
                    WHERE {where.replace('campaign_id', 'm.campaign_id').replace('company_id', 'm.company_id').replace('status', 'm.status')}
                    ORDER BY m.id LIMIT ? OFFSET ?""",
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
        pending = [dict(r) for r in conn.execute("""SELECT id, donor_id, recipient_email, recipient_name, extra_json FROM crm_email_messages
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
        try:
            extra = json.loads(m.get("extra_json") or "{}") or {}
        except ValueError:
            extra = {}
        c_vars = extra.pop("custom_variables", None)
        sel = extra.pop("selected_allocation_id", None)
        msg_body = extra.pop("message_body", None) or c.get("message_body")
        own_t = extra.pop("template_type", None)
        t = own_t or c["template_type"]
        rendered = _render(comp, c["theme"], t, None if own_t else c["subject"], None if own_t else c["body_html"],
                           {**extra, "donor_id": m["donor_id"], "email": m["recipient_email"], "name": m["recipient_name"]},
                           msg_body, c_vars, sel)
        if req.dry_run:
            ok = not rendered["unresolved_placeholders"]
            out.append({"recipient_email": m["recipient_email"], "status": "ok" if ok else "skipped",
                        "detail": "" if ok else "Template needs: " + ", ".join(rendered["unresolved_placeholders"])})
            continue
        out.append(_deliver(comp, c["theme"], t, rendered, base_url, campaign_id, m["donor_id"], m["id"], kind="campaign"))
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


class CampaignRenameRequest(BaseModel):
    company_id: str
    name: str


@router.patch("/campaigns/{campaign_id}")
def rename_campaign(campaign_id: int, req: CampaignRenameRequest):
    """Renames a campaign (any time, sent or not - only the label changes)."""
    comp = _company(req.company_id)
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Give the campaign a name.")
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=15.0)
    try:
        _campaign(conn, comp, campaign_id)
        with conn:
            conn.execute("UPDATE crm_email_campaigns SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND company_id = ?",
                         (name, campaign_id, comp))
    finally:
        conn.close()
    return {"campaign_id": campaign_id, "name": name}


# What a campaign's sponsorships can be marked as (same values the Sponsorship Tracker's filters group on)
CAMPAIGN_MARK_STATUSES = ["First Mailed", "Profile Sent", "Welcome Sent", "Update Sent", "Video Sent",
                          "Feedback Sent", "Annual Report Sent", "Renewal Sent", "Donor Replied"]


class CampaignMarkRequest(BaseModel):
    company_id: str
    communication_status: str


@router.post("/campaigns/{campaign_id}/mark-sponsorships")
def mark_campaign_sponsorships(campaign_id: int, req: CampaignMarkRequest):
    """Sets the outreach status (e.g. "Video Sent") on every sponsorship this campaign's SENT emails were about:
    the sponsorship an email was sent for when one was picked, otherwise all of that donor's sponsorships."""
    comp = _company(req.company_id)
    status = (req.communication_status or "").strip()
    if status not in CAMPAIGN_MARK_STATUSES:
        raise HTTPException(status_code=400, detail="Pick a status from: " + ", ".join(CAMPAIGN_MARK_STATUSES))
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        _campaign(conn, comp, campaign_id)
        sent = [dict(r) for r in conn.execute(
            "SELECT recipient_email, part, extra_json FROM crm_email_messages WHERE campaign_id = ? AND company_id = ? AND status = 'sent'",
            (campaign_id, comp))]
        if not sent:
            raise HTTPException(status_code=400, detail="This campaign hasn't sent any emails yet.")
        alloc_ids, no_spons, donors = set(), set(), set()
        for m in sent:
            em = str(m["recipient_email"] or "").strip().lower()
            donors.add(em)
            try:
                extra = json.loads(m.get("extra_json") or "{}") or {}
            except ValueError:
                extra = {}
            picked = _selected_ids(m.get("part") if str(m.get("part") or "").isdigit() else extra.get("selected_allocation_id"))
            theirs = {a["id"] for a in donor_sponsorships(comp, em)}
            ids = (set(picked) & theirs) or theirs  # only sponsorships that are really this donor's, in this charity
            if ids:
                alloc_ids |= ids
            else:
                no_spons.add(em)
        if alloc_ids:
            with conn:
                conn.execute(f"""UPDATE sponsorship_allocations SET communication_status = ?,
                                 last_contacted_at = COALESCE(last_contacted_at, CURRENT_TIMESTAMP), updated_at = CURRENT_TIMESTAMP
                                 WHERE company_id = ? AND id IN ({','.join('?' * len(alloc_ids))})""",
                             (status, comp, *sorted(alloc_ids)))
    finally:
        conn.close()
    try:
        from core.event_log import log_event
        log_event("campaign.sponsorships_marked", category="email", company_id=comp, campaign_id=campaign_id,
                  message=f"Campaign {campaign_id}: {len(alloc_ids)} sponsorship(s) marked '{status}'")
    except Exception:
        pass
    return {"campaign_id": campaign_id, "communication_status": status, "sponsorships_marked": len(alloc_ids),
            "donors_covered": len(donors) - len(no_spons), "donors_without_sponsorships": sorted(no_spons)}


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


class RecipientGiftsRequest(BaseModel):
    company_id: str
    donor_id: str
    segment: Optional[Dict[str, Any]] = None


@router.post("/recipient-gifts")
def recipient_gifts(req: RecipientGiftsRequest):
    """One person's donations that match the segment (all of them when it has no gift rules) and their
    sponsorships - shown when a row of the recipient list is opened."""
    from backend.api.donors import _directory_data, filter_gifts, has_gift_rules
    comp = _company(req.company_id)
    frame, dx = _directory_data(comp)
    key = str(req.donor_id or "").strip().lower()
    row = frame[frame["donor_id"].str.lower() == key] if frame is not None and not frame.empty else frame
    if row is None or row.empty:
        raise HTTPException(status_code=404, detail="Donor not found for this charity.")
    person = row.iloc[0]
    gifts = dx[dx["key"] == person["donor_id"]]
    if has_gift_rules(req.segment):
        gifts = filter_gifts(gifts, req.segment or {}, dx.attrs.get("host_platforms") or {})
    gifts = gifts.sort_values("date", ascending=False)
    cols = ["date", "amount", "campaign", "heading", "subheading", "stype", "platform", "fundraiser", "giving_level",
            "donation_id", "zakat", "gift_aid", "recurring"]
    out = []
    for g in gifts[[c for c in cols if c in gifts.columns]].head(300).to_dict(orient="records"):
        g = {k: _clean(v) for k, v in g.items()}
        g["date"] = str(g.get("date") or "")[:10]
        out.append(g)
    allocs = donor_sponsorships(comp, str(person.get("email") or "")) if "@" in str(person.get("email") or "") else []
    return {"donor_id": person["donor_id"], "count": int(len(gifts)), "total": round(float(gifts["amount"].sum()), 2),
            "gifts": out,
            "sponsorships": [{"allocation_id": a["id"], "beneficiary": a.get("beneficiary_name") or a.get("campaign_name"),
                              "type": a.get("b_type") or a.get("sponsorship_type"), "location": a.get("b_location"),
                              "start_date": a.get("start_date"), "end_date": a.get("end_date"), "status": a["cycle_status"]}
                             for a in allocs]}


@router.get("/thread")
def donor_email_thread(company_id: str = Query(...), email: str = Query(...)):
    """Everything this charity has emailed one address and every reply, oldest first: single and bulk emails,
    campaign emails, Sponsorship Tracker emails and the donor's replies to any of them."""
    comp = _company(company_id)
    em = (email or "").strip().lower()
    if "@" not in em:
        raise HTTPException(status_code=400, detail="An email address is needed.")
    items: List[Dict[str, Any]] = []
    conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        for r in conn.execute("""SELECT m.id, m.subject, m.body_html, m.status, m.detail, m.sent_at, m.created_at, m.opened_at,
                                        m.open_count, m.replied_at, m.template_type, m.kind, m.sender_email, c.name AS campaign
                                 FROM crm_email_messages m LEFT JOIN crm_email_campaigns c ON c.id = m.campaign_id
                                 WHERE m.company_id = ? AND LOWER(m.recipient_email) = ? AND m.status != 'pending'""", (comp, em)):
            r = dict(r)
            items.append({"id": f"crm-{r['id']}", "direction": "out", "at": r["sent_at"] or r["created_at"],
                          "source": f"Campaign: {r['campaign']}" if r["campaign"] else ("Email" if r["kind"] == "single" else "Bulk email"),
                          "subject": r["subject"], "body_html": r["body_html"], "status": r["status"], "detail": r["detail"],
                          "opened_at": r["opened_at"], "open_count": r["open_count"] or 0, "replied_at": r["replied_at"],
                          "template_type": r["template_type"], "from": r["sender_email"]})
        for r in conn.execute("""SELECT id, subject, body_preview, received_at, sender_email, reply_to_id FROM crm_email_replies
                                 WHERE company_id = ? AND LOWER(sender_email) = ?""", (comp, em)):
            r = dict(r)
            items.append({"id": f"crmr-{r['id']}", "direction": "in", "at": r["received_at"], "source": "Reply",
                          "subject": r["subject"], "body_text": r["body_preview"], "reply_to": f"crm-{r['reply_to_id']}" if r["reply_to_id"] else None,
                          "from": r["sender_email"]})
        try:
            for r in conn.execute("""SELECT c.id, c.direction, c.subject, c.body, c.sent_at, c.delivery_status, c.opened_at, c.open_count,
                                            c.replied_at, c.template_type, c.sender_email, c.recipient_email, c.thread_id, b.name AS beneficiary
                                     FROM sponsorship_communications c
                                     LEFT JOIN sponsorship_allocations a ON a.id = c.allocation_id
                                     LEFT JOIN sponsorship_beneficiaries b ON b.id = a.beneficiary_id
                                     WHERE LOWER(c.company_id) = ? AND (
                                        (c.direction = 'outbound' AND LOWER(c.recipient_email) LIKE ?) OR
                                        (c.direction = 'inbound' AND LOWER(TRIM(c.sender_email)) = ?))""", (comp, f"%{em}%", em)):
                r = dict(r)
                out = r["direction"] == "outbound"
                to_list = [x.strip() for x in str(r.get("recipient_email") or "").lower().replace(";", ",").split(",")]
                if out and em not in to_list:  # LIKE also matches "xa@b.com" for "a@b.com"
                    continue
                items.append({"id": f"sp-{r['id']}", "direction": "out" if out else "in", "at": r["sent_at"],
                              "source": f"Sponsorship{': ' + r['beneficiary'] if r['beneficiary'] else ''}" if out else "Reply",
                              "subject": r["subject"], ("body_html" if out else "body_text"): r["body"],
                              "status": (r["delivery_status"] or "sent") if out else None,
                              "opened_at": r["opened_at"], "open_count": r["open_count"] or 0, "replied_at": r["replied_at"],
                              "template_type": r["template_type"], "conversation": r["thread_id"], "from": r["sender_email"],
                              **({} if out else {"to": r["recipient_email"]})})
        except sqlite3.OperationalError:
            pass
    finally:
        conn.close()

    # which of the charity's accounts each email went through / came into (e.g. Rethink or Sisters' Project)
    from backend.api.mailbox import mailbox_labels_by_address
    boxes = mailbox_labels_by_address(comp)
    for i in items:
        addr = str(i.get("from") if i["direction"] == "out" else i.get("to") or "").strip().lower()
        if addr in boxes:
            i["mailbox_label"], i["mailbox_separate"], i["mailbox_email"] = boxes[addr]["label"], boxes[addr]["separate"], addr

    def when(i):
        return str(i.get("at") or "").replace("T", " ")[:19]
    items.sort(key=when)
    for i in items:
        i["at"] = when(i)
    # everything that actually went out (sponsorship emails also show as opened / delivered / replied)
    sent = [i for i in items if i["direction"] == "out" and i.get("status") not in ("skipped", "failed", "pending")]
    return {"email": em, "items": items,
            "summary": {"sent": len(sent), "opened": sum(1 for i in sent if (i.get("open_count") or 0) > 0),
                        "replies": sum(1 for i in items if i["direction"] == "in"),
                        "last_contact": items[-1]["at"] if items else None}}


@router.get("/activity")
def email_activity(company_id: str = Query(...), direction: Optional[str] = Query(None), search: Optional[str] = Query(None),
                   limit: int = Query(200, ge=1, le=1000)):
    """Latest emails sent and replies received by this charity, from every part of the CRM (Email section, campaigns,
    Sponsorship Tracker), newest first - the Email section's activity feed."""
    comp = _company(company_id)
    q = f"%{(search or '').strip().lower()}%"
    rows: List[Dict[str, Any]] = []
    conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        if direction in (None, "", "out"):
            rows += [dict(r, direction="out") for r in conn.execute("""
                SELECT 'crm-' || m.id AS id, m.recipient_email AS email, m.recipient_name AS name, m.subject, m.status,
                       REPLACE(COALESCE(m.sent_at, m.created_at), 'T', ' ') AS at, m.open_count, m.replied_at,
                       CASE WHEN c.name IS NOT NULL THEN 'Campaign: ' || c.name WHEN m.kind = 'single' THEN 'Email' ELSE 'Bulk email' END AS source
                FROM crm_email_messages m LEFT JOIN crm_email_campaigns c ON c.id = m.campaign_id
                WHERE m.company_id = ? AND m.status != 'pending'
                  AND (LOWER(m.recipient_email) LIKE ? OR LOWER(COALESCE(m.recipient_name, '')) LIKE ? OR LOWER(COALESCE(m.subject, '')) LIKE ?)
                ORDER BY at DESC LIMIT ?""", (comp, q, q, q, limit))]
            try:
                rows += [dict(r, direction="out") for r in conn.execute("""
                    SELECT 'sp-' || c.id AS id, c.recipient_email AS email, d.donor_name AS name, c.subject,
                           COALESCE(c.delivery_status, 'sent') AS status, REPLACE(c.sent_at, 'T', ' ') AS at, c.open_count, c.replied_at,
                           'Sponsorship' || COALESCE(': ' || b.name, '') AS source
                    FROM sponsorship_communications c
                    LEFT JOIN sponsorship_allocation_donors d ON d.id = c.allocation_donor_id
                    LEFT JOIN sponsorship_allocations a ON a.id = c.allocation_id
                    LEFT JOIN sponsorship_beneficiaries b ON b.id = a.beneficiary_id
                    WHERE LOWER(c.company_id) = ? AND c.direction = 'outbound'
                      AND (LOWER(COALESCE(c.recipient_email, '')) LIKE ? OR LOWER(COALESCE(d.donor_name, '')) LIKE ? OR LOWER(COALESCE(c.subject, '')) LIKE ?)
                    ORDER BY at DESC LIMIT ?""", (comp, q, q, q, limit))]
            except sqlite3.OperationalError:
                pass
        if direction in (None, "", "in"):
            rows += [dict(r, direction="in", status="reply") for r in conn.execute("""
                SELECT 'crmr-' || id AS id, sender_email AS email, NULL AS name, subject, REPLACE(received_at, 'T', ' ') AS at,
                       body_preview, 'Reply' AS source FROM crm_email_replies
                WHERE company_id = ? AND (LOWER(sender_email) LIKE ? OR LOWER(COALESCE(subject, '')) LIKE ?)
                ORDER BY at DESC LIMIT ?""", (comp, q, q, limit))]
            try:
                rows += [dict(r, direction="in", status="reply") for r in conn.execute("""
                    SELECT 'sp-' || id AS id, sender_email AS email, NULL AS name, subject, REPLACE(sent_at, 'T', ' ') AS at,
                           body AS body_preview, 'Reply (sponsorship)' AS source FROM sponsorship_communications
                    WHERE LOWER(company_id) = ? AND direction = 'inbound' AND (LOWER(COALESCE(sender_email, '')) LIKE ? OR LOWER(COALESCE(subject, '')) LIKE ?)
                    ORDER BY at DESC LIMIT ?""", (comp, q, q, limit))]
            except sqlite3.OperationalError:
                pass
    finally:
        conn.close()
    rows.sort(key=lambda r: str(r.get("at") or ""), reverse=True)
    for r in rows:
        r["at"] = str(r.get("at") or "")[:19]
        if r.get("body_preview"):
            r["body_preview"] = str(r["body_preview"])[:300]
    return {"items": rows[:limit]}


SPONSORSHIP_PLACEHOLDERS = {"beneficiary_name", "beneficiary_names", "beneficiary_first_name", "beneficiary_first_names", "beneficiary_last_name", "sponsorship_type", "location", "project_code", "profile_link",
                            "video_link", "report_link", "donor_folder_link", "folder_link", "renewal_deadline", "sponsorship_year",
                            "sponsorships_list", "sponsorships_count", "video_buttons", "campaign_name", "community_name"}
LINK_PLACEHOLDERS = {"profile_link", "video_link", "report_link", "donor_folder_link", "folder_link"}


def _issue_text(missing: List[str], has_sponsorship: bool) -> str:
    """Why an email can't be sent, in words the sender can act on."""
    spons = [m for m in missing if m.lower() in SPONSORSHIP_PLACEHOLDERS]
    other = [m for m in missing if m.lower() not in SPONSORSHIP_PLACEHOLDERS]
    parts = []
    if spons and not has_sponsorship:
        parts.append("not on any sponsorship in the Sponsorship Tracker, so " + ", ".join(f"{{{m}}}" for m in spons) + " can't be filled")
    elif spons:
        links = [m for m in spons if m.lower() in LINK_PLACEHOLDERS]
        rest = [m for m in spons if m.lower() not in LINK_PLACEHOLDERS]
        if links:
            parts.append("their beneficiary has no " + ", ".join(f"{{{m}}}" for m in links) + " (add it on the beneficiary in the Tracker)")
        if rest:
            parts.append("their sponsorship has no " + ", ".join(f"{{{m}}}" for m in rest))
    if other:
        parts.append("no value for " + ", ".join(f"{{{m}}}" for m in other))
    return "; ".join(parts)


class CheckRequest(BaseModel):
    company_id: str
    theme: Optional[str] = None
    template_type: str = "general_custom"
    subject_template: Optional[str] = None
    body_template: Optional[str] = None
    message_body: Optional[str] = None
    recipients: List[Dict[str, Any]]
    custom_variables: Optional[Dict[str, str]] = None
    separate_per_beneficiary: bool = False
    recipient_customizations: Optional[Dict[str, Dict[str, Any]]] = None


@router.post("/check")
def check_recipients(req: CheckRequest):
    """Renders the email for each chosen person (up to 200 per call, nothing is sent) and returns only the ones
    that would be skipped, with the reason - so every problem is visible before sending, not just the previewed one."""
    comp = _company(req.company_id)
    theme = _resolve_theme(comp, req.theme)
    if len(req.recipients) > 200:
        raise HTTPException(status_code=400, detail="Check at most 200 people per call.")
    problems = []
    for r in req.recipients:
        em = str(r.get("email") or "").strip()
        if "@" not in em:
            problems.append({"email": em, "name": r.get("name") or "", "issue": "no email address"})
            continue
        if is_unsubscribed(comp, em):
            problems.append({"email": em, "name": r.get("name") or "", "issue": "unsubscribed from emails (pressed Unsubscribe)"})
            continue
        cust = (req.recipient_customizations or {}).get(em.lower(), {})
        c_vars = {**(req.custom_variables or {}), **(cust.get("custom_variables") or {})}
        msg_body = cust.get("message_body") or req.message_body
        plan = _person_emails(comp, em.lower(), cust, req.template_type, req.subject_template, req.body_template,
                              req.separate_per_beneficiary)
        for item in plan:
            t, s_tpl, b_tpl = item["template"]
            rendered = _render(comp, theme, t, s_tpl, b_tpl, r, msg_body, c_vars, item["sel"])
            if rendered["unresolved_placeholders"]:
                missing = rendered["unresolved_placeholders"]
                has_spons = bool(donor_sponsorships(comp, em)) if any(m.lower() in SPONSORSHIP_PLACEHOLDERS for m in missing) else True
                about = (f" ({t.replace('_', ' ')} email)" if item["part"].startswith("extra") else
                         f" (email about {rendered['variables'].get('beneficiary_name') or 'one sponsorship'})" if item["part"] else "")
                problems.append({"email": em, "name": rendered["recipient_name"], "missing": missing, "issue": _issue_text(missing, has_spons) + about})
                break
    return {"checked": len(req.recipients), "ok": len(req.recipients) - len(problems), "problems": problems}
