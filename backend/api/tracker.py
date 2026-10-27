from core.cache import cached
import os
import re
import time
import base64
import threading
import json
import uuid
import sqlite3
import html
import datetime
import logging
import requests
import pandas as pd
import numpy as np
import urllib.parse
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Depends, Query, status, Request, Response
from pydantic import BaseModel

from core.data_processor import load_data, LOCAL_DB_PATH
from core.security import encrypt_string, decrypt_string
from backend.api.auth import get_current_user, require_super_admin, require_company_access, user_company_ids
from core.event_log import log_event

logger = logging.getLogger(__name__)

# Email themes are stored in the company_id column of sponsorship_email_templates.
# Each theme belongs to exactly one charity's workspace.
THEME_OWNER_COMPANY = {"rethink": "rethink", "sp_rethink": "rethink", "iqra": "iqra", "sp": "iqra"}

# Routes reachable without a session: the open-tracking pixel is loaded by mail clients
# and the Graph webhook is called by Microsoft.
_PUBLIC_TRACKER_PATHS = ("/api/tracker/email-tracking/pixel/", "/api/tracker/outlook/webhook")

# Path-parameter -> (table, id column, owner column) for ownership checks.
_OWNED_RESOURCES = {
    "beneficiary_id": ("sponsorship_beneficiaries", "id", "company_id"),
    "allocation_id": ("sponsorship_allocations", "id", "company_id"),
    "feedback_id": ("sponsorship_feedbacks", "id", "company_id"),
    "donor_id": ("sponsorship_manual_donors", "id", "company_id"),
    "template_id": ("sponsorship_email_templates", "id", "company_id"),
    "tracking_id": ("sponsorship_communications", "tracking_id", "company_id"),
    "allocation_donor_id": ("sponsorship_allocation_donors", "id", "company_id"),
    "queue_id": ("sponsorship_email_queue", "id", "company_id"),
}


def _owner_company(raw_company: Optional[str]) -> str:
    comp = (raw_company or "").strip().lower()
    return THEME_OWNER_COMPANY.get(comp, comp)


def _lookup_owner(param: str, value: str) -> Optional[str]:
    table, id_col, owner_col = _OWNED_RESOURCES[param]
    if param == "donor_id":
        value = str(value).replace("manual_", "")
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        row = conn.execute(f"SELECT {owner_col} FROM {table} WHERE {id_col} = ?", (value,)).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    return _owner_company(row[0]) if row else None


def _allocation_company(allocation_id: Any) -> str:
    owner = _lookup_owner("allocation_id", allocation_id)
    if not owner:
        raise HTTPException(status_code=404, detail="Allocation not found.")
    return owner


async def tracker_access_guard(request: Request) -> Optional[dict]:
    """Router-wide isolation: every tracker call needs a valid session, may only name a
    company the user can access, and may only touch records owned by that company.
    A record from another charity is reported as not found."""
    path = request.url.path
    if path.startswith(_PUBLIC_TRACKER_PATHS):
        return None

    user = await get_current_user(request, None, None)
    allowed = user_company_ids(user)

    body = {}
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        try:
            parsed = await request.json()
            if isinstance(parsed, dict):
                body = parsed
        except Exception:
            pass

    requested = request.query_params.get("company_id") or body.get("company_id")
    requested_owner = _owner_company(requested) if requested else None
    if requested_owner:
        require_company_access(user, requested_owner)

    referenced = dict(request.path_params)
    for key in ("allocation_id", "beneficiary_id", "allocation_donor_id"):
        if body.get(key) not in (None, "") and key not in referenced:
            referenced[key] = body[key]

    for param, value in referenced.items():
        if param not in _OWNED_RESOURCES:
            continue
        owner = _lookup_owner(param, value)
        if owner is None:
            continue  # let the endpoint return its own 404
        if (allowed is not None and owner not in allowed) or (
                requested_owner and requested_owner != "all" and owner != requested_owner):
            log_event("access.cross_company_blocked", category="security", level="warning", actor=user.get("email"),
                      company_id=requested_owner, record=f"{param}={value}", record_company=owner, path=path,
                      message=f"Blocked access to {owner} record {param}={value}")
            raise HTTPException(status_code=404, detail="Record not found for this charity.")

    request.state.tracker_user = user
    return user


router = APIRouter(
    prefix="/api/tracker",
    tags=["Sponsorship Target Tracker & Allocations"],
    dependencies=[Depends(tracker_access_guard)],
)

TRANSPARENT_1PX_GIF = bytes.fromhex(
    "47494638396101000100800000ffffff00000021f90401000000002c00000000010001000002024401003b"
)

_TRACKER_CACHE = None

def clear_tracker_cache():
    global _TRACKER_CACHE

def _ensure_tracker_tables_migrated():
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        cur = conn.cursor()
        
        # 1. sponsorship_allocations migrations
        cur.execute("PRAGMA table_info(sponsorship_allocations)")
        cols = [r[1] for r in cur.fetchall()]
        if "allocation_type" not in cols:
            cur.execute("ALTER TABLE sponsorship_allocations ADD COLUMN allocation_type TEXT NOT NULL DEFAULT 'individual'")
        if "campaign_name" not in cols:
            cur.execute("ALTER TABLE sponsorship_allocations ADD COLUMN campaign_name TEXT")
        if "community_name" not in cols:
            cur.execute("ALTER TABLE sponsorship_allocations ADD COLUMN community_name TEXT")
        if "start_date" not in cols:
            cur.execute("ALTER TABLE sponsorship_allocations ADD COLUMN start_date TEXT")
        if "end_date" not in cols:
            cur.execute("ALTER TABLE sponsorship_allocations ADD COLUMN end_date TEXT")
        if "renewal_status" not in cols:
            cur.execute("ALTER TABLE sponsorship_allocations ADD COLUMN renewal_status TEXT DEFAULT 'active'")
        if "renewal_count" not in cols:
            cur.execute("ALTER TABLE sponsorship_allocations ADD COLUMN renewal_count INTEGER DEFAULT 0")
        if "last_renewed_at" not in cols:
            cur.execute("ALTER TABLE sponsorship_allocations ADD COLUMN last_renewed_at TIMESTAMP")
        if "updated_at" not in cols:
            cur.execute("ALTER TABLE sponsorship_allocations ADD COLUMN updated_at TIMESTAMP")
        if "donor_phone" not in cols:
            cur.execute("ALTER TABLE sponsorship_allocations ADD COLUMN donor_phone TEXT DEFAULT ''")
            
        # 2. sponsorship_communications tracking columns migration
        cur.execute("PRAGMA table_info(sponsorship_communications)")
        comm_cols = [r[1] for r in cur.fetchall()]
        if comm_cols:
            if "tracking_id" not in comm_cols:
                cur.execute("ALTER TABLE sponsorship_communications ADD COLUMN tracking_id TEXT")
            if "delivery_status" not in comm_cols:
                cur.execute("ALTER TABLE sponsorship_communications ADD COLUMN delivery_status TEXT DEFAULT 'sent'")
            if "opened_at" not in comm_cols:
                cur.execute("ALTER TABLE sponsorship_communications ADD COLUMN opened_at TIMESTAMP")
            if "open_count" not in comm_cols:
                cur.execute("ALTER TABLE sponsorship_communications ADD COLUMN open_count INTEGER DEFAULT 0")
            if "last_opened_ip" not in comm_cols:
                cur.execute("ALTER TABLE sponsorship_communications ADD COLUMN last_opened_ip TEXT")
            if "last_opened_user_agent" not in comm_cols:
                cur.execute("ALTER TABLE sponsorship_communications ADD COLUMN last_opened_user_agent TEXT")
            if "replied_at" not in comm_cols:
                cur.execute("ALTER TABLE sponsorship_communications ADD COLUMN replied_at TIMESTAMP")

        # 3. sponsorship_feedbacks multi-year schema migration
        cur.execute("PRAGMA table_info(sponsorship_feedbacks)")
        fb_cols = [r[1] for r in cur.fetchall()]
        if fb_cols:
            if "year_label" not in fb_cols:
                cur.execute("ALTER TABLE sponsorship_feedbacks ADD COLUMN year_label TEXT DEFAULT 'Year 1'")
            if "donor_folder_link" not in fb_cols:
                cur.execute("ALTER TABLE sponsorship_feedbacks ADD COLUMN donor_folder_link TEXT")
            if "progress_summary" not in fb_cols:
                cur.execute("ALTER TABLE sponsorship_feedbacks ADD COLUMN progress_summary TEXT")

        # 4. sponsorship_manual_donors table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sponsorship_manual_donors (
                id TEXT PRIMARY KEY,
                company_id TEXT NOT NULL DEFAULT 'rethink',
                donor_name TEXT NOT NULL,
                donor_email TEXT DEFAULT '',
                donor_phone TEXT DEFAULT '',
                sponsorship_type TEXT NOT NULL,
                total_donated REAL NOT NULL DEFAULT 0.0,
                custom_slots INTEGER DEFAULT NULL,
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 5. sponsorship_alert_settings table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sponsorship_alert_settings (
                company_id TEXT PRIMARY KEY,
                threshold_days INTEGER DEFAULT 30,
                staff_emails TEXT DEFAULT '',
                digest_frequency TEXT DEFAULT 'weekly',
                last_digest_sent_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        for cid in ["rethink", "iqra"]:
            cur.execute("""
                INSERT OR IGNORE INTO sponsorship_alert_settings (company_id, threshold_days, staff_emails, digest_frequency)
                VALUES (?, 30, '', 'weekly')
            """, (cid,))
        # Which overdue records the automatic digest lists (the Overdue Alerts filters, saved)
        if "digest_filters" not in {r[1] for r in cur.execute("PRAGMA table_info(sponsorship_alert_settings)")}:
            try:
                cur.execute("ALTER TABLE sponsorship_alert_settings ADD COLUMN digest_filters TEXT")
            except sqlite3.OperationalError:
                pass  # added by the other worker

        # 6. sponsorship_alert_dismissals table (for false positives / dismissals)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sponsorship_alert_dismissals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                entity_name TEXT,
                sponsorship_type TEXT NOT NULL,
                reason TEXT DEFAULT '',
                dismissed_by TEXT DEFAULT '',
                dismissed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(company_id, entity_type, entity_id, sponsorship_type)
            );
        """)

        # 7. Donors per allocation (collective sponsorships). sponsorship_allocations keeps
        # one row per beneficiary; its donor_* columns mirror the primary donor here.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sponsorship_allocation_donors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                allocation_id INTEGER NOT NULL REFERENCES sponsorship_allocations(id) ON DELETE CASCADE,
                company_id TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'donor',
                donor_id TEXT DEFAULT '',
                donor_name TEXT DEFAULT '',
                donor_email TEXT DEFAULT '',
                donor_phone TEXT DEFAULT '',
                contribution_amount REAL NOT NULL DEFAULT 0.0,
                is_primary INTEGER NOT NULL DEFAULT 0,
                is_manual INTEGER NOT NULL DEFAULT 0,
                source TEXT DEFAULT 'manual',
                needs_review INTEGER NOT NULL DEFAULT 0,
                review_note TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_alloc_donors_alloc ON sponsorship_allocation_donors(allocation_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_alloc_donors_company_email ON sponsorship_allocation_donors(company_id, donor_email)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_alloc_donors_company_donor ON sponsorship_allocation_donors(company_id, donor_id)")

        if comm_cols and "allocation_donor_id" not in comm_cols:
            cur.execute("ALTER TABLE sponsorship_communications ADD COLUMN allocation_donor_id INTEGER")
        if comm_cols and "template_type" not in comm_cols:
            cur.execute("ALTER TABLE sponsorship_communications ADD COLUMN template_type TEXT")

        # 8. Review queue of system-triggered emails (nothing is sent without a person approving it).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sponsorship_email_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id TEXT NOT NULL,
                allocation_id INTEGER NOT NULL,
                allocation_donor_id INTEGER NOT NULL,
                template_type TEXT NOT NULL,
                reason TEXT NOT NULL,
                trigger_key TEXT NOT NULL,
                due_date TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                sent_comm_id INTEGER,
                error_message TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(allocation_donor_id, template_type, trigger_key)
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_email_queue_company_status ON sponsorship_email_queue(company_id, status)")

        cur.execute("PRAGMA table_info(sponsorship_alert_settings)")
        alert_cols = [r[1] for r in cur.fetchall()]
        if "renewal_lead_days" not in alert_cols:
            cur.execute("ALTER TABLE sponsorship_alert_settings ADD COLUMN renewal_lead_days INTEGER DEFAULT 30")

        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Error migrating tracker tables: {e}")

_ensure_tracker_tables_migrated()


# ==========================================
# 1. MODELS & SCHEMAS
# ==========================================

WORKSPACE_ALLOWED_CLASSIFICATIONS = {
    "rethink": ["Rethink Only", "Rethink + SP"],
    "iqra": ["Iqra Only", "Iqra + SP"],
    "all": ["Rethink Only", "Rethink + SP", "Iqra Only", "Iqra + SP"]
}

class DonorClassifyRequest(BaseModel):
    donor_id: str
    classification: str
    company_id: Optional[str] = "rethink"
    donor_email: Optional[str] = None

class CampaignClassifyRequest(BaseModel):
    campaign_name: str
    classification: str
    company_id: Optional[str] = "rethink"

class ManualDonorCreateRequest(BaseModel):
    donor_name: str
    donor_email: Optional[str] = ""
    donor_phone: Optional[str] = ""
    sponsorship_type: str = "Orphan"
    total_donated: Optional[float] = 0.0
    custom_slots: Optional[int] = None
    notes: Optional[str] = ""
    company_id: Optional[str] = "rethink"
    classification: Optional[str] = None

class ManualDonorUpdateRequest(BaseModel):
    donor_name: Optional[str] = None
    donor_email: Optional[str] = None
    donor_phone: Optional[str] = None
    sponsorship_type: Optional[str] = None
    total_donated: Optional[float] = None
    custom_slots: Optional[int] = None
    notes: Optional[str] = None
    classification: Optional[str] = None

class UpdateTargetsRequest(BaseModel):
    user_role: str
    targets: Dict[str, float]
    company_id: Optional[str] = "rethink"

class BeneficiaryCreateRequest(BaseModel):
    sponsorship_type: str
    name: str
    location: Optional[str] = ""
    project_code: str
    donor_folder_link: Optional[str] = ""
    profile_link: Optional[str] = ""
    video_link: Optional[str] = ""
    status: Optional[str] = "Unallocated"
    company_id: Optional[str] = "rethink"

class BeneficiaryUpdateRequest(BaseModel):
    sponsorship_type: Optional[str] = None
    name: Optional[str] = None
    location: Optional[str] = None
    project_code: Optional[str] = None
    donor_folder_link: Optional[str] = None
    profile_link: Optional[str] = None
    video_link: Optional[str] = None
    status: Optional[str] = None

class AllocationDonorInput(BaseModel):
    donor_id: Optional[str] = ""
    donor_name: Optional[str] = ""
    donor_email: Optional[str] = ""
    donor_phone: Optional[str] = ""
    contribution_amount: Optional[float] = 0.0
    is_primary: Optional[bool] = False
    is_manual: Optional[bool] = False
    role: Optional[str] = None  # 'donor' | 'organizer'; defaults from allocation type
    company_id: Optional[str] = None

class AllocationDonorUpdate(BaseModel):
    donor_name: Optional[str] = None
    donor_email: Optional[str] = None
    donor_phone: Optional[str] = None
    contribution_amount: Optional[float] = None
    is_primary: Optional[bool] = None
    needs_review: Optional[bool] = None
    company_id: Optional[str] = None

class AllocationCreateRequest(BaseModel):
    beneficiary_id: int
    donors: Optional[List[AllocationDonorInput]] = None  # several donors share one sponsorship
    donor_email: Optional[str] = ""
    donor_phone: Optional[str] = ""
    donor_name: Optional[str] = "Anonymous Donor"
    donor_id: Optional[str] = ""
    allocation_type: Optional[str] = "individual"  # 'individual' | 'campaign'
    campaign_name: Optional[str] = ""
    community_name: Optional[str] = ""
    allocated_amount: Optional[float] = 0.0
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    admin_notes: Optional[str] = ""
    company_id: Optional[str] = "rethink"
    is_exceptional: Optional[bool] = False

class AllocationUpdateRequest(BaseModel):
    allocated_amount: Optional[float] = None
    communication_status: Optional[str] = None
    admin_notes: Optional[str] = None
    donor_email: Optional[str] = None
    donor_phone: Optional[str] = None
    donor_name: Optional[str] = None
    campaign_name: Optional[str] = None
    community_name: Optional[str] = None

class AllocationDatesUpdateRequest(BaseModel):
    start_date: str
    end_date: str
    renewal_status: Optional[str] = None

class FeedbackCreateRequest(BaseModel):
    feedback_title: str
    feedback_date: str
    year_label: Optional[str] = "Year 1"
    report_link: Optional[str] = ""
    video_link: Optional[str] = ""
    donor_folder_link: Optional[str] = ""
    notes: Optional[str] = ""
    progress_summary: Optional[str] = ""
    company_id: Optional[str] = "rethink"

class OutlookCredentialsRequest(BaseModel):
    client_id: str
    client_secret: str
    tenant_id: Optional[str] = "common"
    company_id: Optional[str] = "rethink"

class OutlookExchangeTokenRequest(BaseModel):
    code: str
    redirect_uri: str
    company_id: Optional[str] = "rethink"

class OutlookSendRequest(BaseModel):
    allocation_id: int
    template_type: Optional[str] = "profile_intro"
    company_id: Optional[str] = "rethink"  # email theme; the mailbox always follows the allocation
    # Per-donor sending (preferred): each listed donor receives their own personalised email.
    allocation_donor_ids: Optional[List[int]] = None
    subject_template: Optional[str] = None  # edited template text with {placeholders}; defaults to the saved template
    body_template: Optional[str] = None
    queue_item_ids: Optional[List[int]] = None
    custom_variables: Optional[Dict[str, str]] = None
    # Legacy single-message fields (pre-rendered by the browser).
    recipient_email: Optional[str] = ""
    recipient_name: Optional[str] = "Donor"
    subject: Optional[str] = ""
    body_html: Optional[str] = ""

class BulkEmailItem(BaseModel):
    allocation_id: int
    allocation_donor_id: int
    subject_template: Optional[str] = None  # per-donor personalised text (placeholders allowed)
    body_template: Optional[str] = None

class BulkEmailRequest(BaseModel):
    company_id: str
    template_type: str
    theme: Optional[str] = None             # branding; the mailbox always follows the allocation's charity
    subject_template: Optional[str] = None  # edited text for everyone (per-donor text wins)
    body_template: Optional[str] = None
    items: List[BulkEmailItem]
    dry_run: bool = False

class EmailPreviewRequest(BaseModel):
    allocation_id: int
    allocation_donor_id: Optional[int] = None
    template_type: Optional[str] = "profile_intro"
    company_id: Optional[str] = None  # email theme
    subject_template: Optional[str] = None
    body_template: Optional[str] = None
    custom_variables: Optional[Dict[str, str]] = None

class OutlookTestEmailRequest(BaseModel):
    company_id: Optional[str] = "rethink"
    recipient_email: Optional[str] = "office@rethinkcharity.org.uk"

class TemplateUpdateRequest(BaseModel):
    id: Optional[int] = None
    original_template_type: Optional[str] = None
    template_type: str
    subject: str
    body_html: str
    company_id: Optional[str] = "rethink"
    builder_json: Optional[Any] = None  # the email builder's document (blocks); body_html is rendered from it


def _ensure_template_builder_columns(conn) -> None:
    for col in ("builder_json", "legacy_html"):
        try:
            conn.execute(f"ALTER TABLE sponsorship_email_templates ADD COLUMN {col} TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # already there (or another worker just added it)

class UpdateAlertSettingsRequest(BaseModel):
    company_id: Optional[str] = "rethink"
    threshold_days: int = 30
    staff_emails: Optional[str] = ""
    digest_frequency: Optional[str] = "weekly"  # daily | weekly | monthly | off
    digest_filters: Optional[Dict[str, Any]] = None  # None = keep the saved ones, {} = everyone
    user_role: Optional[str] = "admin"


DIGEST_FILTER_KEYS = ("sponsorship_type", "target_status", "classification", "severity", "search", "earned_from", "earned_to",
                      "last_gift_from", "last_gift_to", "max_days", "min_slots", "min_amount", "max_amount")


def _clean_digest_filters(f: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {k: v for k, v in (f or {}).items() if k in DIGEST_FILTER_KEYS and v not in (None, "") and str(v).lower() != "all"}


def _last_digest_slot(freq: str, now: datetime.datetime) -> Optional[datetime.datetime]:
    """Most recent scheduled send time (UTC) at or before now: daily 08:00, Mondays 08:00, the 1st at 08:00."""
    slot = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if freq == "daily":
        return slot if slot <= now else slot - datetime.timedelta(days=1)
    if freq == "weekly":
        slot -= datetime.timedelta(days=slot.weekday())
        return slot if slot <= now else slot - datetime.timedelta(days=7)
    if freq == "monthly":
        slot = slot.replace(day=1)
        if slot > now:
            prev = (slot - datetime.timedelta(days=1)).replace(day=1)
            slot = prev
        return slot
    return None


def _next_digest_at(freq: str, now: datetime.datetime) -> Optional[str]:
    last = _last_digest_slot(freq, now)
    if not last:
        return None
    if freq == "daily":
        nxt = last + datetime.timedelta(days=1)
    elif freq == "weekly":
        nxt = last + datetime.timedelta(days=7)
    else:
        nxt = (last.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return nxt.isoformat(timespec="minutes") + "Z"


def run_scheduled_overdue_digests() -> Dict[str, Any]:
    """Background: send each charity's overdue digest when its schedule is due, with its saved filters, from its own
    mailbox. Only the first scheduled time AFTER the settings were saved counts, so saving never sends at once."""
    now = datetime.datetime.utcnow()
    out: Dict[str, Any] = {}
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM sponsorship_alert_settings")]
    finally:
        conn.close()
    for r in rows:
        comp = str(r.get("company_id") or "").lower()
        freq = str(r.get("digest_frequency") or "weekly").lower()
        if freq not in ("daily", "weekly", "monthly") or not str(r.get("staff_emails") or "").strip():
            continue
        slot = _last_digest_slot(freq, now)
        since = str(r.get("last_digest_sent_at") or r.get("updated_at") or "")[:19].replace("T", " ")
        try:
            since_dt = datetime.datetime.strptime(since, "%Y-%m-%d %H:%M:%S") if since else None
        except ValueError:
            since_dt = None
        if not slot or (since_dt and since_dt >= slot) or (now - slot) > datetime.timedelta(hours=20):
            continue  # not due, already sent for this slot, or the slot is long gone (don't send a stale one late)
        from backend.api.mailbox import is_connected as _mailbox_connected
        if not _mailbox_connected(comp):
            out[comp] = "mailbox not connected"
            continue
        try:
            f = json.loads(r.get("digest_filters") or "{}") or {}
        except ValueError:
            f = {}
        try:
            res = send_overdue_digest(SendOverdueDigestRequest(company_id=comp, saved_filters=True, **_digest_request_filters(f)))
            out[comp] = res.get("status")
            log_event("email.overdue_digest_scheduled", category="email", company_id=comp, frequency=freq,
                      status=res.get("status"), message=f"Scheduled {freq} overdue digest for {comp}: {res.get('status')}")
        except Exception as e:
            out[comp] = f"error: {e}"
    return out


def _digest_request_filters(f: Dict[str, Any]) -> Dict[str, Any]:
    f = _clean_digest_filters(f)
    top = {k: f[k] for k in ("sponsorship_type", "target_status", "classification", "severity", "search") if k in f}
    top["filters"] = {k: v for k, v in f.items() if k not in top}
    return top

class SendOverdueDigestRequest(BaseModel):
    company_id: Optional[str] = "rethink"
    threshold_days: Optional[int] = None
    recipient_emails: Optional[str] = None
    dry_run: Optional[bool] = False
    user_role: Optional[str] = "admin"
    # the Overdue Alerts screen's filters: the digest lists exactly what the team sees on screen
    sponsorship_type: Optional[str] = None
    target_status: Optional[str] = None
    classification: Optional[str] = None
    severity: Optional[str] = None
    search: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None  # earned_from/to, last_gift_from/to, max_days, min_slots, min_amount, max_amount
    saved_filters: Optional[bool] = False  # use the filters saved for the automatic digest instead of the ones sent

class DismissOverdueRequest(BaseModel):
    company_id: Optional[str] = "rethink"
    entity_type: str  # 'donor' or 'campaign'
    entity_id: str    # donor_id or campaign_name
    entity_name: Optional[str] = None
    sponsorship_type: str
    reason: Optional[str] = "False positive"
    dismissed_by: Optional[str] = "Staff"

class UndismissOverdueRequest(BaseModel):
    company_id: Optional[str] = "rethink"
    entity_type: str  # 'donor' or 'campaign'
    entity_id: str
    sponsorship_type: str


# ==========================================
# 2. TARGETS API
# ==========================================

@router.get("/targets")
def get_targets(company_id: Optional[str] = Query("rethink")):
    """Returns current target values for each sponsorship type."""
    comp = (company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        if comp != "all":
            cur.execute("SELECT sponsorship_type, target_value FROM sponsorship_targets WHERE company_id = ?", (comp,))
        else:
            cur.execute("SELECT sponsorship_type, target_value FROM sponsorship_targets")
        rows = cur.fetchall()
        if not rows:
            return {"Hafiz": 240.0, "Orphan": 480.0, "Widow": 1080.0, "Ex-Prisoner": 1080.0}
        return {r[0]: r[1] for r in rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/targets")
def update_targets(payload: UpdateTargetsRequest, current_user: dict = Depends(get_current_user)):
    """Updates target values (restricted to super_admin)."""
    if current_user.get("role") != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Updating target values is restricted to Super Admin accounts."
        )
    comp = (payload.company_id or "rethink").strip().lower()
    if comp == "all":
        raise HTTPException(
            status_code=400,
            detail="Cannot set sponsorship targets in All Companies mode. Please select a specific company."
        )
    
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        for s_type, val in payload.targets.items():
            cur.execute("""
                INSERT INTO sponsorship_targets (sponsorship_type, target_value, company_id)
                VALUES (?, ?, ?)
                ON CONFLICT(sponsorship_type, company_id) DO UPDATE SET target_value = excluded.target_value
            """, (s_type, float(val), comp))
        conn.commit()
        clear_tracker_cache()
        invalidate_overdue_cache(comp)
        return {"status": "success", "message": f"Successfully updated targets for {comp.upper()}!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ==========================================
# 3. STATS & ANALYTICS API
# ==========================================

_FILTER_CACHE = {}
_LAST_DATA_MTIME = 0.0

@router.get("/stats")
@cached(scopes=["donations", "classification", "tracker"], ttl=21600)
def get_tracker_stats(
    payment_type: Optional[str] = Query(None),
    tier: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    heading: Optional[str] = Query(None),
    subheading: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    code: Optional[str] = Query(None),
    zakat: Optional[str] = Query(None),
    donor_country: Optional[str] = Query(None),
    campaign_search: Optional[str] = Query(None),
    gift_aid: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    company_id: Optional[str] = Query("rethink")
):
    """Computes high-speed real-time donor target progress stats filtered by criteria."""
    global _FILTER_CACHE, _LAST_DATA_MTIME
    comp = (company_id or "rethink").strip().lower()

    from core.data_processor import _CACHE_MTIME
    if _CACHE_MTIME != _LAST_DATA_MTIME:
        _FILTER_CACHE.clear()
        _LAST_DATA_MTIME = _CACHE_MTIME

    filter_key = (
        payment_type, tier, source, heading, subheading, country, code,
        zakat, donor_country, campaign_search, gift_aid, start_date, end_date, comp
    )
    if filter_key in _FILTER_CACHE:
        return _FILTER_CACHE[filter_key]

    targets = {"Hafiz": 240.0, "Orphan": 480.0, "Widow": 1080.0, "Ex-Prisoner": 1080.0}
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        if comp != "all":
            cur.execute("SELECT sponsorship_type, target_value FROM sponsorship_targets WHERE company_id = ?", (comp,))
        else:
            cur.execute("SELECT sponsorship_type, target_value FROM sponsorship_targets")
        for r in cur.fetchall():
            targets[r[0]] = float(r[1])
    except Exception:
        pass
    finally:
        conn.close()

    df = load_data(company_id=comp)
    if df.empty:
        res = {s: {"target": t, "total_raised": 0.0, "above_count": 0, "near_count": 0, "above": [], "near": []} for s, t in targets.items()}
        return res

    from backend.api.donors import _apply_filters
    df = _apply_filters(
        df,
        payment_type=payment_type,
        tier=tier,
        source=source,
        heading=heading,
        subheading=subheading,
        country=country,
        code=code,
        zakat=zakat,
        donor_country=donor_country,
        campaign_search=campaign_search,
        gift_aid=gift_aid,
        start_date=start_date,
        end_date=end_date
    )

    col_amount = "Total Online Donations Net Amount in Settled Currency"
    if col_amount not in df.columns:
        col_amount = "Donation Amount in Project Currency (May be approx.)"
    if col_amount not in df.columns:
        col_amount = "Donation Amount (in Donation Currency)"

    if col_amount not in df.columns or "Donor ID" not in df.columns or df.empty:
        res = {s: {"target": t, "total_raised": 0.0, "above_count": 0, "near_count": 0, "above": [], "near": []} for s, t in targets.items()}
        _FILTER_CACHE[filter_key] = res
        return res

    amt_series = pd.to_numeric(df[col_amount], errors="coerce").fillna(0.0)
    d_id_series = df["Donor ID"].astype(str)
    code_series = df["Code"].astype(str).str.strip().str.upper() if "Code" in df.columns else pd.Series("", index=df.index)

    masks = {
        "Hafiz": code_series.str.contains("HUF", na=False),
        "Orphan": code_series.str.contains("ORP", na=False),
        "Widow": code_series.str.contains("WID", na=False),
        "Ex-Prisoner": code_series.str.contains("SUR", na=False) | code_series.str.contains("EX-PRISONER", na=False)
    }

    results = {}
    for s_type, target in targets.items():
        mask = masks.get(s_type, pd.Series(False, index=df.index))
        if not mask.any():
            results[s_type] = {
                "target": target,
                "total_raised": 0.0,
                "above_count": 0,
                "near_count": 0,
                "above": [],
                "near": []
            }
            continue

        s_amt = amt_series[mask]
        s_did = d_id_series[mask]
        total_raised = float(s_amt.sum())

        sums = s_amt.groupby(s_did).sum()
        relevant = sums[sums >= (0.8 * target)]

        above_list = []
        near_list = []

        if not relevant.empty:
            rel_ids = set(relevant.index)
            rel_df = df[d_id_series.isin(rel_ids)].drop_duplicates(subset=["Donor ID"], keep="first")

            names = rel_df["Display Name"].fillna("") if "Display Name" in rel_df.columns else pd.Series("Anonymous Donor", index=rel_df.index)
            invalid_mask = names.astype(str).str.strip().str.lower().isin(["", "nan", "none", "null", "anonymous", "anonymous kind soul", "kind soul"])
            if invalid_mask.any() and "First Name" in rel_df.columns and "Last Name" in rel_df.columns:
                fn = rel_df.loc[invalid_mask, "First Name"].fillna("").astype(str).str.strip()
                ln = rel_df.loc[invalid_mask, "Last Name"].fillna("").astype(str).str.strip()
                comb = (fn + " " + ln).str.strip()
                names.loc[invalid_mask] = comb.replace({"": "Anonymous Donor", "nan nan": "Anonymous Donor"})

            names = names.replace({"": "Anonymous Donor", "nan": "Anonymous Donor"})
            emails = rel_df.get("Email", pd.Series("", index=rel_df.index)).fillna("").astype(str).str.strip()

            phone_col = None
            for p_cand in ["Phone", "Phone Number", "Donor Phone", "Telephone", "Mobile", "Contact Phone"]:
                if p_cand in rel_df.columns:
                    phone_col = p_cand
                    break

            if phone_col:
                phones = rel_df[phone_col].fillna("").astype(str).str.lstrip("'").str.strip()
            else:
                phones = pd.Series("", index=rel_df.index)

            # Clean invalid string representations
            phones = phones.apply(lambda p: "" if p.lower() in ["", "nan", "none", "null", "n/a", "undefined"] else p)
            emails = emails.apply(lambda e: "" if e.lower() in ["", "nan", "none", "null", "n/a", "undefined"] else e)

            donor_meta = dict(zip(rel_df["Donor ID"].astype(str), zip(names, emails, phones)))

            for str_id, total in relevant.items():
                total_val = float(total)
                progress = round((total_val / target) * 100.0, 1)
                best_name, email, phone = donor_meta.get(str_id, ("Anonymous Donor", "", ""))

                rec = {
                    "donor_id": str_id,
                    "name": best_name,
                    "email": email,
                    "phone": phone,
                    "total_donated": round(total_val, 2),
                    "target": target,
                    "progress": progress
                }

                if total_val >= target:
                    above_list.append(rec)
                else:
                    near_list.append(rec)

            above_list.sort(key=lambda x: x["total_donated"], reverse=True)
            near_list.sort(key=lambda x: x["total_donated"], reverse=True)

        results[s_type] = {
            "target": target,
            "total_raised": round(total_raised, 2),
            "above_count": len(above_list),
            "near_count": len(near_list),
            "above": above_list,
            "near": near_list
        }

    if len(_FILTER_CACHE) > 64:
        _FILTER_CACHE.clear()
    _FILTER_CACHE[filter_key] = results
    return results


# ==========================================
# 4. BENEFICIARIES DIRECTORY CRUD
# ==========================================

def _attach_donors_and_funding(cur, rows: List[Dict[str, Any]], alloc_key: str) -> None:
    """Adds donors[], funded_amount, target_amount and funding_status to allocation/beneficiary rows."""
    targets_by_company: Dict[str, Dict[str, float]] = {}
    donors_map = _load_allocation_donors(cur, [r.get(alloc_key) for r in rows if r.get(alloc_key)])
    for r in rows:
        comp = (r.get("company_id") or "rethink").lower()
        if comp not in targets_by_company:
            try:
                targets_by_company[comp] = {k: float(v) for k, v in get_targets(company_id=comp).items()}
            except Exception:
                targets_by_company[comp] = {}
        target = float(targets_by_company[comp].get(r.get("sponsorship_type"), 0.0) or 0.0)
        donors = donors_map.get(r.get(alloc_key), []) if r.get(alloc_key) else []
        funded = round(sum(float(d["contribution_amount"] or 0.0) for d in donors), 2)
        r["donors"] = donors
        r["donor_count"] = len(donors)
        r["funded_amount"] = funded
        r["target_amount"] = target
        if not donors:
            r["funding_status"] = "unfunded"
        elif target and funded + 0.005 < target:
            r["funding_status"] = "partial"
        else:
            r["funding_status"] = "full"
        r["needs_review"] = any(d["needs_review"] for d in donors)


@router.get("/beneficiaries")
@cached(scopes=["tracker", "tracker_comms"], ttl=3600)
def get_beneficiaries(
    company_id: Optional[str] = Query("rethink"),
    sponsorship_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    donor: Optional[str] = Query(None),
    campaign: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    funded_status: Optional[str] = Query(None),
    needs_review: Optional[bool] = Query(None),
):
    """Returns list of beneficiaries with allocation status and feedback counts."""
    comp = (company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        query = """
            SELECT 
                b.id,
                b.company_id,
                b.sponsorship_type,
                b.name,
                b.location,
                b.project_code,
                b.donor_folder_link,
                b.profile_link,
                b.video_link,
                b.status,
                b.created_at,
                b.updated_at,
                a.id AS allocation_id,
                a.donor_name,
                a.donor_email,
                a.donor_id,
                a.allocated_amount,
                a.communication_status,
                a.last_contacted_at,
                a.last_replied_at,
                a.admin_notes,
                (SELECT COUNT(*) FROM sponsorship_feedbacks f WHERE f.beneficiary_id = b.id) AS feedbacks_count,
                (SELECT COUNT(*) FROM sponsorship_communications c WHERE c.allocation_id = a.id) AS comms_count
            FROM sponsorship_beneficiaries b
            LEFT JOIN sponsorship_allocations a ON b.id = a.beneficiary_id
            WHERE 1=1
        """
        params = []
        if comp != "all":
            query += " AND b.company_id = ?"
            params.append(comp)
        if sponsorship_type:
            query += " AND b.sponsorship_type = ?"
            params.append(sponsorship_type)
        if status:
            if status.lower() == "allocated":
                query += " AND a.id IS NOT NULL"
            elif status.lower() == "unallocated":
                query += " AND a.id IS NULL"
            else:
                query += " AND b.status = ?"
                params.append(status)
        if search:
            query += (" AND (b.name LIKE ? OR b.project_code LIKE ? OR b.location LIKE ? OR a.donor_name LIKE ? OR a.donor_email LIKE ?"
                      " OR EXISTS (SELECT 1 FROM sponsorship_allocation_donors sd WHERE sd.allocation_id = a.id"
                      " AND (sd.donor_name LIKE ? OR sd.donor_email LIKE ?)))")
            s_param = f"%{search.strip()}%"
            params.extend([s_param] * 7)
        if donor:
            query += (" AND EXISTS (SELECT 1 FROM sponsorship_allocation_donors sd WHERE sd.allocation_id = a.id"
                      " AND (sd.donor_name LIKE ? OR sd.donor_email LIKE ? OR sd.donor_phone LIKE ?))")
            params.extend([f"%{donor.strip()}%"] * 3)
        if campaign:
            query += " AND a.campaign_name LIKE ?"
            params.append(f"%{campaign.strip()}%")
        if location:
            query += " AND b.location LIKE ?"
            params.append(f"%{location.strip()}%")

        query += " ORDER BY b.created_at DESC"
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        _attach_donors_and_funding(cur, rows, alloc_key="allocation_id")
        if funded_status and funded_status != "all":
            rows = [r for r in rows if r["funding_status"] == funded_status]
        if needs_review is not None:
            rows = [r for r in rows if r["needs_review"] == needs_review]
        return {"count": len(rows), "beneficiaries": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/beneficiaries")
def create_beneficiary(payload: BeneficiaryCreateRequest):
    """Creates a new beneficiary record."""
    comp = (payload.company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sponsorship_beneficiaries (
                company_id, sponsorship_type, name, location, project_code,
                donor_folder_link, profile_link, video_link, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            comp,
            payload.sponsorship_type.strip(),
            payload.name.strip(),
            payload.location.strip() if payload.location else "",
            payload.project_code.strip(),
            payload.donor_folder_link.strip() if payload.donor_folder_link else "",
            payload.profile_link.strip() if payload.profile_link else "",
            payload.video_link.strip() if payload.video_link else "",
            payload.status or "Unallocated"
        ))
        b_id = cur.lastrowid
        conn.commit()
        return {"status": "success", "message": "Beneficiary created successfully!", "id": b_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# ---------------------------------------------------------------------------------------------------------
# Beneficiary bulk import (CSV / XLSX) with a downloadable template.
# ---------------------------------------------------------------------------------------------------------
BENEFICIARY_IMPORT_COLUMNS = [
    # (field, header in template, required, help, example)
    ("name", "Name", True, "Beneficiary full name", "Zayd Al-Mansoor"),
    ("project_code", "Project Code", True, "Unique per charity - used to detect existing beneficiaries", "RT-ORP-ABS-07-26-001M"),
    ("sponsorship_type", "Sponsorship Type", True, "Orphan, Widow, Hafiz or Ex-Prisoner", "Orphan"),
    ("location", "Location", False, "Country / town", "Gaza, Palestine"),
    ("status", "Status", False, "Unallocated (default) or Pending Assignment", "Unallocated"),
    ("donor_folder_link", "Donor Folder Link", False, "Link to the donor-facing folder", "https://drive.google.com/..."),
    ("profile_link", "Profile Link", False, "Link to the profile document", "https://drive.google.com/..."),
    ("video_link", "Video Link", False, "Link to an update video", "https://youtube.com/..."),
]
BENEFICIARY_IMPORT_ALIASES = {
    "name": ["name", "beneficiary name", "beneficiary", "full name"],
    "project_code": ["project code", "project_code", "code", "beneficiary code"],
    "sponsorship_type": ["sponsorship type", "sponsorship_type", "type", "sponsorship"],
    "location": ["location", "country", "town", "city"],
    "status": ["status"],
    "donor_folder_link": ["donor folder link", "donor_folder_link", "folder link", "folder"],
    "profile_link": ["profile link", "profile_link", "profile"],
    "video_link": ["video link", "video_link", "video"],
}
BENEFICIARY_IMPORT_TYPES = ["Orphan", "Widow", "Hafiz", "Ex-Prisoner"]
BENEFICIARY_IMPORT_STATUSES = ["Unallocated", "Pending Assignment"]
BENEFICIARY_IMPORT_MAX_ROWS = 5000


@router.get("/beneficiaries/import-template")
def download_beneficiary_import_template(company_id: Optional[str] = Query("rethink"), format: str = Query("xlsx")):
    """Empty upload template (headers only) plus, for XLSX, an Instructions sheet and dropdowns."""
    import io
    from fastapi.responses import StreamingResponse
    headers = [h for _, h, _, _, _ in BENEFICIARY_IMPORT_COLUMNS]
    if (format or "").lower() == "csv":
        body = ",".join(headers) + "\r\n"
        return StreamingResponse(io.BytesIO(body.encode("utf-8-sig")), media_type="text/csv",
                                 headers={"Content-Disposition": 'attachment; filename="beneficiaries_import_template.csv"'})
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
    wb = Workbook()
    ws = wb.active
    ws.title = "Beneficiaries"
    ws.append(headers)
    for i, (_, header, required, _, _) in enumerate(BENEFICIARY_IMPORT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=i)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1D4ED8" if required else "64748B")
        ws.column_dimensions[cell.column_letter].width = max(18, len(header) + 6)
    type_col = [h for _, h, _, _, _ in BENEFICIARY_IMPORT_COLUMNS].index("Sponsorship Type") + 1
    status_col = [h for _, h, _, _, _ in BENEFICIARY_IMPORT_COLUMNS].index("Status") + 1
    for col, values in ((type_col, BENEFICIARY_IMPORT_TYPES), (status_col, BENEFICIARY_IMPORT_STATUSES)):
        letter = ws.cell(row=1, column=col).column_letter
        dv = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{letter}2:{letter}{BENEFICIARY_IMPORT_MAX_ROWS + 1}")
    ws.freeze_panes = "A2"
    info = wb.create_sheet("Instructions")
    info.append(["Column", "Required", "What to enter", "Example"])
    for _, header, required, help_text, example in BENEFICIARY_IMPORT_COLUMNS:
        info.append([header, "Yes" if required else "No", help_text, example])
    info.append([])
    info.append(["Fill the 'Beneficiaries' sheet - one row per beneficiary. Blue headers are required."])
    info.append(["Rows whose Project Code already exists for this charity are skipped, or updated if you choose 'Update existing'."])
    for col, width in zip("ABCD", (20, 10, 60, 32)):
        info.column_dimensions[col].width = width
    for cell in info[1]:
        cell.font = Font(bold=True)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": 'attachment; filename="beneficiaries_import_template.xlsx"'})


def _read_beneficiary_upload(filename: str, content: bytes) -> pd.DataFrame:
    import io
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        xls = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
        sheet = "Beneficiaries" if "Beneficiaries" in xls.sheet_names else xls.sheet_names[0]
        return pd.read_excel(xls, sheet_name=sheet, dtype=str, keep_default_na=False)
    if name.endswith((".csv", ".txt")):
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                return pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False, encoding=encoding)
            except UnicodeDecodeError:
                continue
    raise HTTPException(status_code=400, detail="Please upload a .csv or .xlsx file (use the template).")


@router.post("/beneficiaries/import")
async def import_beneficiaries(
    request: Request,
    company_id: str = Query(...),
    dry_run: bool = Query(True),
    on_duplicate: str = Query("skip"),
):
    """Validates (dry_run=true) or imports a CSV/XLSX of beneficiaries for ONE charity. company_id comes from the
    access-checked query string only - never from the file. The import is all-or-nothing."""
    comp = (company_id or "").strip().lower()
    if comp in ("", "all"):
        raise HTTPException(status_code=400, detail="Choose a specific charity before importing.")
    if on_duplicate not in ("skip", "update"):
        raise HTTPException(status_code=400, detail="on_duplicate must be 'skip' or 'update'.")
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(status_code=400, detail="No file uploaded.")
    content = await upload.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File is larger than 5 MB.")
    df = _read_beneficiary_upload(upload.filename, content)

    # Map headers (case/spacing-insensitive, common aliases)
    normalized = {str(c).strip().lower().replace("_", " "): c for c in df.columns}
    column_for = {}
    for field, aliases in BENEFICIARY_IMPORT_ALIASES.items():
        for alias in aliases:
            if alias.replace("_", " ") in normalized:
                column_for[field] = normalized[alias.replace("_", " ")]
                break
    missing_cols = [h for f, h, req, _, _ in BENEFICIARY_IMPORT_COLUMNS if req and f not in column_for]
    if missing_cols:
        raise HTTPException(status_code=400, detail=f"Missing required column(s): {', '.join(missing_cols)}. Download the template to see the expected headers.")
    rows = [{f: str(r.get(col, "") or "").strip() for f, col in column_for.items()} for r in df.to_dict("records")]
    rows = [(i + 2, r) for i, r in enumerate(rows) if any(r.values())]  # i+2 = spreadsheet row number
    if len(rows) > BENEFICIARY_IMPORT_MAX_ROWS:
        raise HTTPException(status_code=400, detail=f"Too many rows ({len(rows)}); the limit is {BENEFICIARY_IMPORT_MAX_ROWS} per file.")

    type_lookup = {t.lower(): t for t in BENEFICIARY_IMPORT_TYPES}
    type_lookup.update({"ex prisoner": "Ex-Prisoner", "exprisoner": "Ex-Prisoner", "hafidh": "Hafiz", "hifz": "Hafiz"})
    status_lookup = {s.lower(): s for s in BENEFICIARY_IMPORT_STATUSES}

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        existing = {}
        for r in conn.execute("SELECT id, project_code FROM sponsorship_beneficiaries WHERE company_id = ?", (comp,)):
            existing.setdefault((r["project_code"] or "").strip().upper(), r["id"])
        seen_codes = {}
        results = []
        for row_no, r in rows:
            errors = []
            if not r.get("name"):
                errors.append("Name is required")
            if not r.get("project_code"):
                errors.append("Project Code is required")
            s_type = type_lookup.get((r.get("sponsorship_type") or "").strip().lower())
            if not r.get("sponsorship_type"):
                errors.append("Sponsorship Type is required")
            elif not s_type:
                errors.append(f"Unknown Sponsorship Type '{r['sponsorship_type']}' (use {', '.join(BENEFICIARY_IMPORT_TYPES)})")
            status_val = "Unallocated"
            if r.get("status"):
                status_val = status_lookup.get(r["status"].strip().lower())
                if not status_val:
                    errors.append(f"Status '{r['status']}' not allowed (use {' or '.join(BENEFICIARY_IMPORT_STATUSES)}; allocations set 'Allocated')")
            for link in ("donor_folder_link", "profile_link", "video_link"):
                v = r.get(link) or ""
                if v and not (v.startswith("http://") or v.startswith("https://")):
                    errors.append(f"{link.replace('_', ' ').title()} must start with http:// or https://")
            code_key = (r.get("project_code") or "").upper()
            if code_key and code_key in seen_codes:
                errors.append(f"Project Code repeated in this file (row {seen_codes[code_key]})")
            elif code_key:
                seen_codes[code_key] = row_no
            action = "error" if errors else ("update" if code_key in existing and on_duplicate == "update"
                                            else "skip" if code_key in existing else "create")
            results.append({"row": row_no, "action": action, "errors": errors, "existing_id": existing.get(code_key),
                            "data": {**r, "sponsorship_type": s_type or r.get("sponsorship_type"), "status": status_val}})

        summary = {a: sum(1 for x in results if x["action"] == a) for a in ("create", "update", "skip", "error")}
        if dry_run or summary["error"]:
            return {"dry_run": True, "can_import": summary["error"] == 0 and (summary["create"] + summary["update"]) > 0,
                    "summary": summary, "rows": results}

        created_ids = []
        with conn:  # one transaction: all rows or none
            for x in results:
                d = x["data"]
                if x["action"] == "create":
                    cur = conn.execute("""
                        INSERT INTO sponsorship_beneficiaries (company_id, sponsorship_type, name, location, project_code,
                                                               donor_folder_link, profile_link, video_link, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (comp, d["sponsorship_type"], d["name"], d.get("location", ""), d["project_code"],
                         d.get("donor_folder_link", ""), d.get("profile_link", ""), d.get("video_link", ""), d["status"]))
                    created_ids.append(cur.lastrowid)
                elif x["action"] == "update":
                    # only the columns present in the file and non-empty; status is left to the allocation logic
                    fields = {k: d[k] for k in ("name", "sponsorship_type", "location", "donor_folder_link", "profile_link", "video_link")
                              if k in column_for and d.get(k)}
                    if fields:
                        conn.execute(f"UPDATE sponsorship_beneficiaries SET {', '.join(f'{k} = ?' for k in fields)}, "
                                     f"updated_at = CURRENT_TIMESTAMP WHERE id = ? AND company_id = ?",
                                     (*fields.values(), x["existing_id"], comp))
        log_event("beneficiaries.imported", category="tracker", company_id=comp,
                  message=f"Imported beneficiaries for {comp}: {summary['create']} created, {summary['update']} updated, "
                          f"{summary['skip']} skipped", file=upload.filename, **summary)
        return {"dry_run": False, "summary": summary, "created_ids": created_ids}
    finally:
        conn.close()


@router.put("/beneficiaries/{beneficiary_id}")
def update_beneficiary(beneficiary_id: int, payload: BeneficiaryUpdateRequest):
    """Updates an existing beneficiary record."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM sponsorship_beneficiaries WHERE id = ?", (beneficiary_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Beneficiary not found.")

        fields = []
        values = []
        if payload.sponsorship_type is not None:
            fields.append("sponsorship_type = ?")
            values.append(payload.sponsorship_type.strip())
        if payload.name is not None:
            fields.append("name = ?")
            values.append(payload.name.strip())
        if payload.location is not None:
            fields.append("location = ?")
            values.append(payload.location.strip())
        if payload.project_code is not None:
            fields.append("project_code = ?")
            values.append(payload.project_code.strip())
        if payload.donor_folder_link is not None:
            fields.append("donor_folder_link = ?")
            values.append(payload.donor_folder_link.strip())
        if payload.profile_link is not None:
            fields.append("profile_link = ?")
            values.append(payload.profile_link.strip())
        if payload.video_link is not None:
            fields.append("video_link = ?")
            values.append(payload.video_link.strip())
        if payload.status is not None:
            fields.append("status = ?")
            values.append(payload.status.strip())

        if fields:
            fields.append("updated_at = CURRENT_TIMESTAMP")
            values.append(beneficiary_id)
            cur.execute(f"UPDATE sponsorship_beneficiaries SET {', '.join(fields)} WHERE id = ?", values)
            conn.commit()

        return {"status": "success", "message": "Beneficiary updated successfully."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.delete("/beneficiaries/{beneficiary_id}")
def delete_beneficiary(beneficiary_id: int):
    """Deletes a beneficiary and associated allocations/feedbacks."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM sponsorship_beneficiaries WHERE id = ?", (beneficiary_id,))
        conn.commit()
        return {"status": "success", "message": "Beneficiary deleted successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ==========================================
# 5. QUALIFYING DONORS & ALLOCATION CAPACITY
# ==========================================

def _unwrap_param(v, default=""):
    if v is None:
        return default
    if hasattr(v, 'default'):
        val = v.default
        return val if val is not None else default
    return v

def _parse_bool(v, default=False):
    if v is None:
        return default
    if hasattr(v, 'default'):
        v = v.default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ["true", "1", "yes", "t"]:
        return True
    if s in ["false", "0", "no", "f", ""]:
        return False
    return default


def _donor_slot_allocations(cur, comp: str, s_type: Optional[str], targets: Dict[str, float]) -> List[Dict[str, Any]]:
    """One row per (allocation, donor) for this sponsorship type. slot_share is the fraction of a
    beneficiary's target this donor funds, so three donors sharing one orphan use 1 slot between them,
    and an Orphan allocation never consumes a Widow slot."""
    query = """
        SELECT a.id, d.id AS allocation_donor_id, d.donor_email, d.donor_phone, d.donor_id, d.contribution_amount,
               (SELECT COUNT(*) FROM sponsorship_allocation_donors x WHERE x.allocation_id = a.id) AS donor_count,
               a.beneficiary_id, b.name AS beneficiary_name, b.project_code, b.sponsorship_type
        FROM sponsorship_allocation_donors d
        JOIN sponsorship_allocations a ON a.id = d.allocation_id
        JOIN sponsorship_beneficiaries b ON a.beneficiary_id = b.id
        WHERE 1=1
    """
    params: List[Any] = []
    if comp != "all":
        query += " AND a.company_id = ?"
        params.append(comp)
    if s_type and s_type.lower() != "all":
        query += " AND b.sponsorship_type = ?"
        params.append(s_type)
    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        target = float(targets.get(r.get("sponsorship_type"), 0.0) or 0.0)
        contribution = float(r.get("contribution_amount") or 0.0)
        if target > 0 and contribution > 0:
            r["slot_share"] = round(min(1.0, contribution / target), 4)
        else:
            r["slot_share"] = round(1.0 / max(1, int(r.get("donor_count") or 1)), 4)
    return rows


def _slots_used(items: List[Dict[str, Any]]) -> float:
    used = round(sum(float(i.get("slot_share", 1.0)) for i in items), 2)
    return int(used) if float(used).is_integer() else used


def validate_classification_for_company(classification: str, company_id: str) -> None:
    comp = (company_id or "rethink").strip().lower()
    allowed = WORKSPACE_ALLOWED_CLASSIFICATIONS.get(comp, WORKSPACE_ALLOWED_CLASSIFICATIONS["rethink"])
    if classification not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Classification '{classification}' is not permitted in workspace '{comp}'. Allowed options: {', '.join(allowed)}"
        )


def is_sp_campaign_name(name: str) -> bool:
    c_lower = (name or "").lower().strip()
    return (
        any(k in c_lower for k in ["sisters project", "sister's project", "sisters' project", "sp:", "sp -", " sp "])
        or c_lower.startswith("sp ")
        or c_lower.startswith("sp-")
        or c_lower.startswith("sp:")
        or c_lower == "sp"
    )


def suggest_campaign_classification(campaign_name: str, company_id: str) -> str:
    comp = (company_id or "rethink").strip().lower()
    is_sp = is_sp_campaign_name(campaign_name)
    if comp == "iqra":
        return "Iqra + SP" if is_sp else "Iqra Only"
    else:
        return "Rethink + SP" if is_sp else "Rethink Only"


def suggest_donor_classification(campaigns: List[str], company_id: str) -> str:
    comp = (company_id or "rethink").strip().lower()
    if not campaigns:
        return "Iqra Only" if comp == "iqra" else "Rethink Only"
    
    has_sp = any(is_sp_campaign_name(c) for c in campaigns)
    if comp == "iqra":
        return "Iqra + SP" if has_sp else "Iqra Only"
    else:
        return "Rethink + SP" if has_sp else "Rethink Only"


# ---------------------------------------------------------------------------------------------------------
# Per-donor sponsorship totals, precomputed once per charity + sponsorship type.
# Built from the same rows and with the same pandas operations the qualifying-donors page always used, then
# stored as plain dicts so the page no longer does ~100k slow pandas lookups per request. Depends only on the
# charity's donations, so allocation edits, searches and classification filters reuse it; any change to the
# donations (from any worker or the sync service) changes the version token and rebuilds it.
# ---------------------------------------------------------------------------------------------------------
_SPONSORSHIP_BASE: Dict[tuple, Any] = {}
_SPONSORSHIP_BASE_LOCK = threading.Lock()


def _sponsorship_masks(df: pd.DataFrame) -> Dict[str, pd.Series]:
    code_series = df["Code"].astype(str).str.strip().str.upper() if "Code" in df.columns else pd.Series("", index=df.index)
    camp_series = df["Campaign Name"].astype(str).str.strip().str.upper() if "Campaign Name" in df.columns else pd.Series("", index=df.index)
    gl_col = "Giving Level Title" if "Giving Level Title" in df.columns else ("Giving Level" if "Giving Level" in df.columns else None)
    gl_series = df[gl_col].astype(str).str.strip().str.upper() if gl_col else pd.Series("", index=df.index)

    is_orphan_gl = gl_series.str.contains("ORPHAN", na=False)
    is_orphan_camp = camp_series.str.contains("ORPHAN", na=False)
    is_orphan_code = code_series.str.contains("ORP", na=False)

    return {
        "Hafiz": code_series.str.contains(r"HUF|HAF", regex=True, na=False) | camp_series.str.contains(r"HAFIZ|HIFZ", regex=True, na=False) | gl_series.str.contains(r"HAFIZ|HIFZ", regex=True, na=False),
        "Orphan": is_orphan_gl | is_orphan_camp | is_orphan_code,
        "Widow": code_series.str.contains("WID", na=False) | camp_series.str.contains("WIDOW", na=False) | gl_series.str.contains("WIDOW", na=False),
        "Ex-Prisoner": code_series.str.contains(r"SUR|EX-PRISONER", regex=True, na=False) | camp_series.str.contains(r"PRISONER|SURVIVOR", regex=True, na=False) | gl_series.str.contains(r"PRISONER|SURVIVOR", regex=True, na=False)
    }


def _split_by_key(keys: np.ndarray, *columns: np.ndarray) -> Dict[Any, tuple]:
    """keys must already be grouped (sorted). Returns key -> tuple of per-column slices, in row order."""
    if len(keys) == 0:
        return {}
    change = np.flatnonzero(keys[1:] != keys[:-1]) + 1
    starts = np.concatenate(([0], change))
    ends = np.concatenate((change, [len(keys)]))
    return {keys[a]: tuple(col[a:b] for col in columns) for a, b in zip(starts, ends)}


def _build_sponsorship_base(df: pd.DataFrame, s_type: str) -> Optional[Dict[str, Any]]:
    if df.empty or "Donor ID" not in df.columns:
        return None
    col_amount = "Total Online Donations Net Amount in Settled Currency"
    if col_amount not in df.columns:
        col_amount = "Donation Amount in Project Currency (May be approx.)"
    if col_amount not in df.columns:
        col_amount = "Donation Amount (in Donation Currency)"
    if col_amount not in df.columns:
        return None

    amt_series = pd.to_numeric(df[col_amount], errors="coerce").fillna(0.0)
    d_id_series = df["Donor ID"].astype(str)
    mask = _sponsorship_masks(df).get(s_type, pd.Series(False, index=df.index))
    if not mask.any():
        return None

    date_col_cand = None
    for c in ["_parsed_date", "Created Date (UTC)", "Date", "Settled Date (UTC)", "created_at", "Date of collection"]:
        if c in df.columns:
            date_col_cand = c
            break
    s_rows = df[mask]
    unified_dt = (pd.to_datetime(s_rows[date_col_cand], errors="coerce", format="mixed") if date_col_cand
                  else pd.Series(pd.NaT, index=s_rows.index))

    # Group by donor for this sponsorship type ONLY
    sums = amt_series[mask].groupby(d_id_series[mask]).sum()
    valid_did_mask = ~sums.index.astype(str).str.strip().str.lower().isin(["", "nan", "none", "null", "undefined", "<na>"])
    sums = sums[valid_did_mask]

    raw_did = s_rows["Donor ID"]

    # 1. Dates: Min & Max per donor for this sponsorship
    s_dt_agg = unified_dt.groupby(raw_did).agg(["min", "max"])

    # Running total per donor (date order) so we know WHEN each slot threshold was reached:
    # the waiting clock starts at the payment that completed the slot, not the first donation.
    timeline_df = pd.DataFrame({
        "did": raw_did.astype(str),
        "dt": unified_dt,
        "amt": amt_series.reindex(s_rows.index).fillna(0.0),
    }).dropna(subset=["dt"]).sort_values(["did", "dt"])
    timeline_df["cum"] = timeline_df.groupby("did")["amt"].cumsum()
    timelines = _split_by_key(timeline_df["did"].to_numpy(dtype=object), timeline_df["dt"].to_numpy(), timeline_df["cum"].to_numpy())

    # 2. Campaigns involved per donor for this sponsorship (unique, in order of appearance)
    camp_col_name = "Campaign Name" if "Campaign Name" in s_rows.columns else ("Campaign" if "Campaign" in s_rows.columns else None)
    campaigns: Dict[Any, list] = {}
    if camp_col_name:
        camp_frame = pd.DataFrame({"did": raw_did, "camp": s_rows[camp_col_name]}).dropna(subset=["did"])
        camp_frame = camp_frame.drop_duplicates(keep="first")
        order = np.argsort(pd.factorize(camp_frame["did"])[0], kind="stable")
        camp_frame = camp_frame.iloc[order]
        campaigns = {k: list(v[0]) for k, v in _split_by_key(camp_frame["did"].to_numpy(dtype=object),
                                                                camp_frame["camp"].to_numpy(dtype=object)).items()}

    # 3. Donor display names
    fn = s_rows["First Name"].fillna("").astype(str).str.strip() if "First Name" in s_rows.columns else pd.Series("", index=s_rows.index)
    ln = s_rows["Last Name"].fillna("").astype(str).str.strip() if "Last Name" in s_rows.columns else pd.Series("", index=s_rows.index)
    full_n = (fn + " " + ln).str.strip()
    bill_n = s_rows["Billing Name"].fillna("").astype(str).str.strip() if "Billing Name" in s_rows.columns else pd.Series("", index=s_rows.index)
    disp_n = s_rows["Display Name"].fillna("").astype(str).str.strip() if "Display Name" in s_rows.columns else pd.Series("", index=s_rows.index)
    best_n_series = full_n.replace(["", "nan", "none", "nan nan", "none none"], np.nan).fillna(
        bill_n.replace(["", "nan", "none"], np.nan)
    ).fillna(
        disp_n.replace(["", "nan", "none"], np.nan)
    ).fillna("Anonymous Donor")
    names_by_did = best_n_series.groupby(raw_did).first()

    # 4. Donor email & phone
    if "Email" in s_rows.columns:
        emails_by_did = s_rows["Email"].dropna().astype(str).str.strip().groupby(raw_did).first()
    else:
        emails_by_did = pd.Series("N/A", index=names_by_did.index)
    phone_col = None
    for pc in ["Phone Number", "Phone", "phone_number", "Contact Phone"]:
        if pc in s_rows.columns:
            phone_col = pc
            break
    if phone_col:
        phones_by_did = s_rows[phone_col].dropna().astype(str).str.strip().str.lstrip("'").groupby(raw_did).first()
    else:
        phones_by_did = pd.Series("", index=names_by_did.index)

    # 5. Donor LTV across all causes
    ltv_by_did = amt_series.groupby(d_id_series).sum()

    # Allocation e-mail -> donor IDs (any cause), used to pull allocated donors into the list
    email_to_dids: Dict[str, list] = {}
    if "Email" in df.columns:
        em = pd.DataFrame({"email": df["Email"].astype(str).str.strip().str.lower(), "did": df["Donor ID"]}).dropna(subset=["did"])
        em = em.drop_duplicates()
        for e, d in zip(em["email"].to_numpy(dtype=object), em["did"].to_numpy(dtype=object)):
            email_to_dids.setdefault(e, []).append(str(d).strip())

    return {
        "sums": sums.to_dict(),
        "positive_ids": set(sums[sums > 0].index),
        "dt_min": s_dt_agg["min"].to_dict(),
        "dt_max": s_dt_agg["max"].to_dict(),
        "timelines": timelines,
        "campaigns": campaigns,
        "names": names_by_did.to_dict(),
        "emails": emails_by_did.to_dict(),
        "phones": phones_by_did.to_dict(),
        "ltv": ltv_by_did.to_dict(),
        "email_to_dids": email_to_dids,
        "has_email_col": "Email" in df.columns,
    }


def _sponsorship_base(comp: str, s_type: str) -> Optional[Dict[str, Any]]:
    from core.cache import version_token
    token = version_token(["donations"], comp)
    key = (comp, s_type)
    hit = _SPONSORSHIP_BASE.get(key)
    if hit and hit[0] == token:
        return hit[1]
    with _SPONSORSHIP_BASE_LOCK:
        hit = _SPONSORSHIP_BASE.get(key)
        if hit and hit[0] == token:
            return hit[1]
        base = _build_sponsorship_base(load_data(company_id=comp), s_type)
        for stale in [k for k, v in _SPONSORSHIP_BASE.items() if k[0] == comp and v[0] != token]:
            _SPONSORSHIP_BASE.pop(stale, None)
        _SPONSORSHIP_BASE[key] = (token, base)
        return base


def _filter_qualifying(donors_list, comp, s_type, date_from, date_to, min_total, max_total, min_waiting_days, has_email):
    """Left-panel filters of the allocation matrix. Slots and totals stay lifetime figures (they drive allocation);
    a date window only picks donors who gave to this sponsorship type in it and adds what they gave then
    (window_total)."""
    out = donors_list
    if date_from or date_to:
        df = load_data(company_id=comp)
        lo = pd.to_datetime(date_from, errors="coerce") if date_from else None
        hi = pd.to_datetime(date_to, errors="coerce") + pd.Timedelta(days=1) if date_to else None
        totals: Dict[str, float] = {}
        if df is not None and not df.empty and "Donor ID" in df.columns:
            mask = _sponsorship_masks(df).get(s_type, pd.Series(False, index=df.index))
            dcol = next((c for c in ("_parsed_date", "Created Date (UTC)", "Settled Date (UTC)") if c in df.columns), None)
            if dcol:
                dts = pd.to_datetime(df[dcol], errors="coerce", format="mixed")
                sel = mask & dts.notna()
                if lo is not None:
                    sel &= dts >= lo
                if hi is not None:
                    sel &= dts < hi
                amt_col = "Total Online Donations Net Amount in Settled Currency"
                amts = pd.to_numeric(df.loc[sel, amt_col], errors="coerce").fillna(0.0) if amt_col in df.columns else pd.Series(0.0, index=df.index[sel])
                totals = amts.groupby(df.loc[sel, "Donor ID"].astype(str).str.strip()).sum().to_dict()
        kept = []
        for d in out:
            if d.get("is_manual"):
                made = pd.to_datetime((d.get("oldest_donation_date") or "")[:10], errors="coerce")
                ok = not pd.isna(made) and (lo is None or made >= lo) and (hi is None or made < hi)
                if ok:
                    kept.append({**d, "window_total": d.get("total_donated")})
            elif str(d.get("donor_id")).strip() in totals:
                kept.append({**d, "window_total": round(float(totals[str(d.get("donor_id")).strip()]), 2)})
        out = kept
    if min_total is not None:
        out = [d for d in out if float(d.get("total_donated") or 0) >= float(min_total)]
    if max_total is not None:
        out = [d for d in out if float(d.get("total_donated") or 0) <= float(max_total)]
    if min_waiting_days is not None:
        out = [d for d in out if int(d.get("waiting_days") or 0) >= int(min_waiting_days)]
    if has_email in ("yes", "no"):
        out = [d for d in out if ("@" in str(d.get("donor_email") or "")) == (has_email == "yes")]
    return out


@router.get("/qualifying-donors")
@cached(scopes=["donations", "classification", "tracker"], ttl=21600, daily=True)
def get_qualifying_donors(
    company_id: Optional[str] = Query("rethink"),
    sponsorship_type: Optional[str] = Query("Orphan"),
    search: Optional[str] = Query(None),
    classification: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="gave to this sponsorship type on/after"),
    date_to: Optional[str] = Query(None, description="gave to this sponsorship type on/before"),
    min_total: Optional[float] = Query(None),
    max_total: Optional[float] = Query(None),
    min_waiting_days: Optional[int] = Query(None),
    has_email: Optional[str] = Query(None),
):
    """
    Returns qualifying donors for a given sponsorship type along with capacity calculations:
    - total_donated: Total amount donated to this sponsorship type
    - target_amount: Target cost per beneficiary (e.g., 480)
    - max_slots: floor(total_donated / target_amount)
    - allocated_count: Number of beneficiaries currently allocated to this donor
    - remaining_slots: max_slots - allocated_count
    - classification: Donor source classification (Rethink Only, Rethink + SP, Iqra Only, Iqra + SP)
    """
    comp = _unwrap_param(company_id, "rethink").strip().lower()
    s_type = _unwrap_param(sponsorship_type, "Orphan").strip()
    search = _unwrap_param(search, "").strip() or None
    target_class = _unwrap_param(classification, "").strip() or None

    targets = {"Hafiz": 240.0, "Orphan": 480.0, "Widow": 1080.0, "Ex-Prisoner": 1080.0}
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        if comp != "all":
            cur.execute("SELECT sponsorship_type, target_value FROM sponsorship_targets WHERE company_id = ?", (comp,))
        else:
            cur.execute("SELECT sponsorship_type, target_value FROM sponsorship_targets")
        for r in cur.fetchall():
            targets[r["sponsorship_type"]] = float(r["target_value"])

        all_allocs = _donor_slot_allocations(cur, comp, s_type, targets)

        # Query saved donor classifications
        class_query = "SELECT donor_id, donor_email, classification FROM sponsorship_donor_classifications WHERE 1=1"
        class_params = []
        if comp != "all":
            class_query += " AND company_id = ?"
            class_params.append(comp)
        cur.execute(class_query, class_params)
        saved_donor_classes = {}
        for cr in cur.fetchall():
            if cr["donor_id"]:
                saved_donor_classes[str(cr["donor_id"]).strip()] = cr["classification"]
            if cr["donor_email"]:
                saved_donor_classes[str(cr["donor_email"]).strip().lower()] = cr["classification"]

        # Query manual sponsorship donors
        man_query = """
            SELECT id, company_id, donor_name, donor_email, donor_phone,
                   sponsorship_type, total_donated, custom_slots, notes, created_at, classification
            FROM sponsorship_manual_donors
            WHERE 1=1
        """
        man_params = []
        if comp != "all":
            man_query += " AND company_id = ?"
            man_params.append(comp)
        if s_type and s_type.lower() != "all":
            man_query += " AND (sponsorship_type = ? OR sponsorship_type = 'All')"
            man_params.append(s_type)
        man_query += " ORDER BY created_at DESC"
        cur.execute(man_query, man_params)
        manual_donors_rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

    alloc_by_email = {}
    alloc_by_phone = {}
    alloc_by_did = {}
    for a in all_allocs:
        email_key = (a.get("donor_email") or "").strip().lower()
        if email_key and email_key != "n/a":
            alloc_by_email.setdefault(email_key, []).append(a)
        phone_key = "".join([c for c in (a.get("donor_phone") or "") if c.isdigit()])
        if phone_key:
            alloc_by_phone.setdefault(phone_key, []).append(a)
        did_key = str(a.get("donor_id") or "").strip().lower()
        if did_key and did_key != "n/a":
            alloc_by_did.setdefault(did_key, []).append(a)

    target_amount = float(targets.get(s_type, 480.0))

    base = _sponsorship_base(comp, s_type)
    donors_list = []

    if base is not None:
        sums = base["sums"]
        # Include all donors who donated towards this sponsorship type (even if below target threshold)
        relevant_ids = set(base["positive_ids"])

        # Ensure donors with existing allocations for this sponsorship type are retained
        alloc_dids = {str(a.get("donor_id")).strip() for a in all_allocs if a.get("sponsorship_type") == s_type and a.get("donor_id")}
        alloc_dids = {d for d in alloc_dids if d.lower() not in ["", "none", "null", "nan", "undefined"]}
        relevant_ids.update(alloc_dids)

        if base["has_email_col"]:
            alloc_emails = {str(a.get("donor_email")).strip().lower() for a in all_allocs if a.get("sponsorship_type") == s_type and a.get("donor_email")}
            alloc_emails = {e for e in alloc_emails if "@" in e}
            for e in alloc_emails:
                relevant_ids.update(base["email_to_dids"].get(e, ()))

        dt_min, dt_max, timelines = base["dt_min"], base["dt_max"], base["timelines"]
        s_camps_agg, names_by_did, emails_by_did = base["campaigns"], base["names"], base["emails"]
        phones_by_did, ltv_by_did = base["phones"], base["ltv"]

        now_dt = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

        for str_id in relevant_ids:
            s_total_val = float(sums.get(str_id, 0.0))
            d_name = str(names_by_did.get(str_id) or "Anonymous Donor")
            d_email = str(emails_by_did.get(str_id) or "N/A")
            if d_email.lower() in ["n/a", "nan", "none", ""] and "@" in str_id:
                d_email = str_id
            d_phone = str(phones_by_did.get(str_id) or "")
            if d_phone.strip().lower() in ("nan", "none", "null", "n/a"):
                d_phone = ""
            d_ltv = float(ltv_by_did.get(str_id, s_total_val))

            # Dates and campaigns strictly for this sponsorship
            oldest_dt, latest_dt = None, None
            if str_id in dt_min:
                oldest_dt = dt_min[str_id]
                latest_dt = dt_max[str_id]

            raw_camps = s_camps_agg.get(str_id, [])
            campaigns_involved = [c for c in list(raw_camps) if c and str(c).lower() not in ["nan", "none", "n/a", "null"]]

            if hasattr(oldest_dt, 'to_pydatetime'):
                oldest_dt = oldest_dt.to_pydatetime()
            if hasattr(oldest_dt, 'tzinfo') and oldest_dt and oldest_dt.tzinfo:
                oldest_dt = oldest_dt.replace(tzinfo=None)
            if hasattr(latest_dt, 'to_pydatetime'):
                latest_dt = latest_dt.to_pydatetime()
            if hasattr(latest_dt, 'tzinfo') and latest_dt and latest_dt.tzinfo:
                latest_dt = latest_dt.replace(tzinfo=None)

            oldest_str = oldest_dt.strftime("%Y-%m-%d") if oldest_dt and pd.notna(oldest_dt) else "N/A"
            latest_str = latest_dt.strftime("%Y-%m-%d") if latest_dt and pd.notna(latest_dt) else "N/A"

            # Target & slot calculation based strictly on amount toward THIS sponsorship
            slot_threshold = 0.8 * target_amount if target_amount > 0 else 0.0
            max_slots = int(s_total_val // slot_threshold) if slot_threshold > 0 else 0
            pct_raised = round((s_total_val / target_amount) * 100, 1) if target_amount > 0 else 0.0

            is_target_reached = bool(s_total_val >= target_amount)
            is_threshold_reached = bool(s_total_val >= slot_threshold)
            if is_target_reached:
                target_status = "target_reached"
            elif is_threshold_reached:
                target_status = "threshold_reached"
            else:
                target_status = "below_threshold"

            # Collect allocations for this donor
            donor_emails = set()
            if d_email and d_email.lower() != "n/a":
                donor_emails.add(d_email.strip().lower())
            if "@" in str_id:
                donor_emails.add(str_id.strip().lower())

            matched_allocs_dict = {}
            for ek in donor_emails:
                for item in alloc_by_email.get(ek, []):
                    matched_allocs_dict[item.get("id") or item.get("beneficiary_id")] = item
            for item in alloc_by_did.get(str_id.strip().lower(), []):
                matched_allocs_dict[item.get("id") or item.get("beneficiary_id")] = item

            allocated_items = list(matched_allocs_dict.values())
            allocated_count = _slots_used(allocated_items)
            remaining_slots = max(0, round(max_slots - allocated_count, 2))

            # Waiting age = days since the donation that earned the slot they are still waiting for
            # (cumulative giving for this type crossed (slots already used + 1) x 80% of target).
            eligible_since = None
            if slot_threshold > 0 and remaining_slots > 0 and str_id in timelines:
                dts, cums = timelines[str_id]
                needed = (int(allocated_count) + 1) * slot_threshold
                idx = int(np.searchsorted(cums, needed - 1e-6))
                if idx < len(dts):
                    eligible_since = pd.Timestamp(dts[idx]).to_pydatetime().replace(tzinfo=None)
            waiting_days = max(0, (now_dt - eligible_since).days) if eligible_since else 0
            eligible_since_str = eligible_since.strftime("%Y-%m-%d") if eligible_since else None

            if allocated_count > max_slots:
                elig_status = "over_capacity" if max_slots > 0 else "exceptional"
            elif is_threshold_reached and remaining_slots > 0:
                elig_status = "eligible"
            elif is_threshold_reached and remaining_slots == 0:
                elig_status = "at_capacity"
            elif allocated_count > 0:
                elig_status = "exceptional"
            else:
                elig_status = "near_target" if pct_raised >= 50 else "in_progress"

            saved_cls = saved_donor_classes.get(str_id) or (saved_donor_classes.get(d_email.lower()) if d_email else None)
            if saved_cls:
                donor_classification = saved_cls
                is_manually_classified = True
            else:
                donor_classification = suggest_donor_classification(campaigns_involved, comp)
                is_manually_classified = False

            if target_class and target_class.lower() != "all" and donor_classification != target_class:
                continue

            if search:
                s_low = search.strip().lower()
                clean_s = "".join([c for c in s_low if c.isdigit()])
                clean_p = "".join([c for c in d_phone if c.isdigit()])
                matches_phone = (s_low in d_phone.lower()) or (bool(clean_s) and clean_s in clean_p)
                if s_low not in d_name.lower() and s_low not in d_email.lower() and s_low not in str_id.lower() and not matches_phone:
                    continue

            donors_list.append({
                "donor_id": str_id,
                "donor_name": d_name,
                "donor_email": d_email,
                "donor_phone": d_phone,
                "total_donated": round(s_total_val, 2),
                "donor_ltv": round(d_ltv, 2),
                "target_amount": target_amount,
                "pct_raised": pct_raised,
                "target_status": target_status,
                "is_target_reached": is_target_reached,
                "is_threshold_reached": is_threshold_reached,
                "max_slots": max_slots,
                "allocated_count": allocated_count,
                "remaining_slots": remaining_slots,
                "status": elig_status,
                "is_manual": False,
                "classification": donor_classification,
                "is_manually_classified": is_manually_classified,
                "oldest_donation_date": oldest_str,
                "latest_donation_date": latest_str,
                "eligible_since": eligible_since_str,
                "waiting_days": waiting_days,
                "campaigns_involved": campaigns_involved,
                "allocated_beneficiaries": allocated_items
            })

    # Append Manual / Offline Donors into qualifying donors
    now_dt = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    for mr in manual_donors_rows:
        mid = f"manual_{mr['id']}"
        m_name = (mr.get("donor_name") or "Manual Donor").strip()
        m_email = (mr.get("donor_email") or "").strip()
        m_phone = (mr.get("donor_phone") or "").strip()
        m_total = float(mr.get("total_donated") or 0.0)
        c_slots = mr.get("custom_slots")
        if c_slots is not None and int(c_slots) > 0:
            m_max_slots = int(c_slots)
        else:
            slot_threshold = 0.8 * target_amount if target_amount > 0 else 0.0
            m_max_slots = max(1, int(m_total // slot_threshold)) if slot_threshold > 0 and m_total > 0 else 1

        # Match allocations by email, phone, or manual ID
        m_allocs_dict = {}
        if m_email and m_email.lower() != "n/a":
            for item in alloc_by_email.get(m_email.lower(), []):
                m_allocs_dict[item.get("id") or item.get("beneficiary_id")] = item
        clean_mp = "".join([c for c in m_phone if c.isdigit()])
        if clean_mp:
            for item in alloc_by_phone.get(clean_mp, []):
                m_allocs_dict[item.get("id") or item.get("beneficiary_id")] = item
        for item in alloc_by_did.get(mid.lower(), []):
            m_allocs_dict[item.get("id") or item.get("beneficiary_id")] = item
        for item in alloc_by_did.get(str(mr['id']).lower(), []):
            m_allocs_dict[item.get("id") or item.get("beneficiary_id")] = item

        m_allocated_items = list(m_allocs_dict.values())
        m_allocated_count = _slots_used(m_allocated_items)
        m_remaining_slots = max(0, round(m_max_slots - m_allocated_count, 2))

        if m_allocated_count > m_max_slots:
            m_status = "over_capacity"
        elif m_remaining_slots > 0:
            m_status = "eligible"
        else:
            m_status = "at_capacity"

        m_saved_cls = mr.get("classification") or saved_donor_classes.get(mid) or saved_donor_classes.get(str(mr['id'])) or (saved_donor_classes.get(m_email.lower()) if m_email else None)
        if m_saved_cls:
            m_classification = m_saved_cls
            m_manually_classified = True
        else:
            m_classification = "Iqra Only" if comp == "iqra" else "Rethink Only"
            m_manually_classified = False

        if target_class and target_class.lower() != "all" and m_classification != target_class:
            continue

        if search:
            s_low = search.strip().lower()
            clean_s = "".join([c for c in s_low if c.isdigit()])
            clean_p = "".join([c for c in m_phone if c.isdigit()])
            matches_phone = (s_low in m_phone.lower()) or (bool(clean_s) and clean_s in clean_p)
            if s_low not in m_name.lower() and s_low not in m_email.lower() and s_low not in mid.lower() and not matches_phone:
                continue

        m_created = mr.get("created_at")
        m_dt = pd.to_datetime(m_created, errors="coerce", format="mixed") if m_created else None
        m_oldest_str = m_dt.strftime("%Y-%m-%d") if m_dt and pd.notna(m_dt) else "N/A"
        m_waiting_days = max(0, (now_dt - m_dt.replace(tzinfo=None)).days) if m_dt and pd.notna(m_dt) else 0

        pct_raised = round((m_total / target_amount) * 100, 1) if target_amount > 0 else 0.0
        is_target_reached = bool(m_total >= target_amount)
        is_threshold_reached = bool(m_total >= (0.8 * target_amount))
        target_status = "target_reached" if is_target_reached else ("threshold_reached" if is_threshold_reached else "below_threshold")

        donors_list.append({
            "donor_id": mid,
            "raw_id": mr["id"],
            "donor_name": m_name,
            "donor_email": m_email or "N/A",
            "donor_phone": m_phone,
            "sponsorship_type": mr.get("sponsorship_type") or s_type,
            "total_donated": round(m_total, 2),
            "donor_ltv": round(m_total, 2),
            "target_amount": target_amount,
            "pct_raised": pct_raised,
            "target_status": target_status,
            "is_target_reached": is_target_reached,
            "is_threshold_reached": is_threshold_reached,
            "max_slots": m_max_slots,
            "allocated_count": m_allocated_count,
            "remaining_slots": m_remaining_slots,
            "status": m_status,
            "is_manual": True,
            "classification": m_classification,
            "is_manually_classified": m_manually_classified,
            "notes": mr.get("notes") or "",
            "created_at": mr.get("created_at"),
            "oldest_donation_date": m_oldest_str,
            "latest_donation_date": m_oldest_str,
            "eligible_since": m_oldest_str if (m_total >= 0.8 * target_amount and m_oldest_str != "N/A") else None,
            "waiting_days": m_waiting_days if m_total >= 0.8 * target_amount else 0,
            "campaigns_involved": ["Manual Entry"],
            "allocated_beneficiaries": m_allocated_items
        })

    donors_list = _filter_qualifying(donors_list, comp, s_type,
                                     _unwrap_param(date_from, "") or None, _unwrap_param(date_to, "") or None,
                                     _unwrap_param(min_total, None), _unwrap_param(max_total, None),
                                     _unwrap_param(min_waiting_days, None), _unwrap_param(has_email, "") or None)
    donors_list.sort(key=lambda x: (x["remaining_slots"] > 0, x["allocated_count"] > 0, x["total_donated"]), reverse=True)
    return {
        "sponsorship_type": s_type,
        "target_amount": target_amount,
        "count": len(donors_list),
        "donors": donors_list
    }


@router.get("/search-any-donor")
@cached(scopes=["donations", "classification", "tracker"], ttl=1800)
def search_any_donor(
    query: str = Query(..., min_length=1),
    sponsorship_type: Optional[str] = Query("Orphan"),
    company_id: Optional[str] = Query("rethink")
):
    """
    Searches across ALL CRM donors (regardless of cause, campaigns, or donation threshold)
    and manual offline donors to allow exceptional allocations.
    """
    comp = (company_id or "rethink").strip().lower()
    s_type = (sponsorship_type or "Orphan").strip()
    q = query.strip()
    if not q:
        return {"donors": []}

    targets = {"Hafiz": 240.0, "Orphan": 480.0, "Widow": 1080.0, "Ex-Prisoner": 1080.0}
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        if comp != "all":
            cur.execute("SELECT sponsorship_type, target_value FROM sponsorship_targets WHERE company_id = ?", (comp,))
        else:
            cur.execute("SELECT sponsorship_type, target_value FROM sponsorship_targets")
        for r in cur.fetchall():
            targets[r["sponsorship_type"]] = float(r["target_value"])

        all_allocs = _donor_slot_allocations(cur, comp, s_type, targets)

        # Search matching manual donors
        man_query = """
            SELECT id, company_id, donor_name, donor_email, donor_phone,
                   sponsorship_type, total_donated, custom_slots, notes, created_at
            FROM sponsorship_manual_donors
            WHERE (company_id = ? OR ? = 'all')
              AND (donor_name LIKE ? OR donor_email LIKE ? OR donor_phone LIKE ? OR id LIKE ? OR notes LIKE ?)
        """
        like_q = f"%{q}%"
        cur.execute(man_query, (comp, comp, like_q, like_q, like_q, like_q, like_q))
        manual_matches = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

    alloc_by_email = {}
    alloc_by_phone = {}
    alloc_by_did = {}
    for a in all_allocs:
        email_key = (a.get("donor_email") or "").strip().lower()
        if email_key and email_key != "n/a":
            alloc_by_email.setdefault(email_key, []).append(a)
        phone_key = "".join([c for c in (a.get("donor_phone") or "") if c.isdigit()])
        if phone_key:
            alloc_by_phone.setdefault(phone_key, []).append(a)
        did_key = str(a.get("donor_id") or "").strip().lower()
        if did_key and did_key != "n/a":
            alloc_by_did.setdefault(did_key, []).append(a)

    target_amount = float(targets.get(s_type, 480.0))
    results = []

    # Add matching manual donors first
    for mr in manual_matches:
        mid = f"manual_{mr['id']}"
        m_name = (mr.get("donor_name") or "Manual Donor").strip()
        m_email = (mr.get("donor_email") or "").strip()
        m_phone = (mr.get("donor_phone") or "").strip()
        m_total = float(mr.get("total_donated") or 0.0)
        c_slots = mr.get("custom_slots")
        if c_slots is not None and int(c_slots) > 0:
            m_max_slots = int(c_slots)
        else:
            slot_threshold = 0.8 * target_amount if target_amount > 0 else 0.0
            m_max_slots = max(1, int(m_total // slot_threshold)) if slot_threshold > 0 and m_total > 0 else 1

        m_allocs_dict = {}
        if m_email and m_email.lower() != "n/a":
            for item in alloc_by_email.get(m_email.lower(), []):
                m_allocs_dict[item.get("id") or item.get("beneficiary_id")] = item
        clean_mp = "".join([c for c in m_phone if c.isdigit()])
        if clean_mp:
            for item in alloc_by_phone.get(clean_mp, []):
                m_allocs_dict[item.get("id") or item.get("beneficiary_id")] = item
        for item in alloc_by_did.get(mid.lower(), []):
            m_allocs_dict[item.get("id") or item.get("beneficiary_id")] = item

        m_allocated_items = list(m_allocs_dict.values())
        m_allocated_count = _slots_used(m_allocated_items)
        m_remaining_slots = max(0, round(m_max_slots - m_allocated_count, 2))

        results.append({
            "donor_id": mid,
            "raw_id": mr["id"],
            "donor_name": m_name,
            "donor_email": m_email or "N/A",
            "donor_phone": m_phone,
            "total_donated": round(m_total, 2),
            "total_lifetime_donated": round(m_total, 2),
            "causes": [f"Manual Entry ({mr.get('sponsorship_type') or 'General'})"],
            "target_amount": target_amount,
            "max_slots": m_max_slots,
            "allocated_count": m_allocated_count,
            "remaining_slots": m_remaining_slots,
            "status": "eligible" if m_remaining_slots > 0 else "at_capacity",
            "is_manual": True,
            "notes": mr.get("notes") or "",
            "allocated_beneficiaries": m_allocated_items
        })

    df = load_data(company_id=comp)
    if not df.empty and "Donor ID" in df.columns:
        col_amount = "Total Online Donations Net Amount in Settled Currency"
        if col_amount not in df.columns:
            col_amount = "Donation Amount in Project Currency (May be approx.)"
        if col_amount not in df.columns:
            col_amount = "Donation Amount (in Donation Currency)"

        amt_series = pd.to_numeric(df[col_amount], errors="coerce").fillna(0.0) if col_amount in df.columns else pd.Series(0.0, index=df.index)
        code_series = df["Code"].astype(str).str.strip().str.upper() if "Code" in df.columns else pd.Series("", index=df.index)

        masks = {
            "Hafiz": code_series.str.contains("HUF", na=False),
            "Orphan": code_series.str.contains("ORP", na=False),
            "Widow": code_series.str.contains("WID", na=False),
            "Ex-Prisoner": code_series.str.contains("SUR", na=False) | code_series.str.contains("EX-PRISONER", na=False)
        }
        s_mask = masks.get(s_type, pd.Series(False, index=df.index))

        # Search filter
        q_low = q.lower()
        clean_q_digits = "".join([c for c in q_low if c.isdigit()])

        name_col = df["Display Name"].fillna("").astype(str) if "Display Name" in df.columns else pd.Series("", index=df.index)
        email_col = df["Email"].fillna("").astype(str) if "Email" in df.columns else pd.Series("", index=df.index)
        did_col = df["Donor ID"].fillna("").astype(str)

        phone_col_name = None
        for pc in ["Phone Number", "Phone", "phone_number", "Home phone number", "Contact Phone"]:
            if pc in df.columns:
                phone_col_name = pc
                break
        phone_col = df[phone_col_name].fillna("").astype(str).str.lstrip("'") if phone_col_name else pd.Series("", index=df.index)

        id_cols_to_check = [did_col]
        for idc in ["Donation ID", "charge_id", "_id", "subscription_id", "sub_id", "Transfer ID", "campaign_uid"]:
            if idc in df.columns:
                id_cols_to_check.append(df[idc].fillna("").astype(str))

        id_mask = pd.Series(False, index=df.index)
        for icol in id_cols_to_check:
            id_mask |= icol.str.contains(q_low, case=False, na=False)

        search_mask = (
            name_col.str.contains(q_low, case=False, na=False) |
            email_col.str.contains(q_low, case=False, na=False) |
            id_mask
        )
        if clean_q_digits and len(clean_q_digits) >= 3:
            clean_phone_series = phone_col.str.replace(r"\D", "", regex=True)
            search_mask = search_mask | clean_phone_series.str.contains(clean_q_digits, na=False)

        matched_rows = df[search_mask]
        if not matched_rows.empty:
            matched_dids = matched_rows["Donor ID"].dropna().unique()[:50]
            matched_all_rows = df[df["Donor ID"].isin(matched_dids)]

            for did_val, grp in matched_all_rows.groupby("Donor ID"):
                str_did = str(did_val)
                if str_did.lower() in ["", "nan", "none", "null", "undefined"]:
                    continue

                best_name = "Anonymous Donor"
                for _, r in grp.iterrows():
                    fn = str(r.get("First Name") or "").strip()
                    ln = str(r.get("Last Name") or "").strip()
                    comb = (fn + " " + ln).strip()
                    dn = str(r.get("Display Name") or "").strip()
                    bn = str(r.get("Billing Name") or "").strip()
                    cand_name = comb if (comb and comb.lower() not in ["nan nan", "none none", "nan", "none"]) else (bn if bn and bn.lower() not in ["nan", "none"] else dn)
                    if cand_name and cand_name.lower() not in ["", "nan", "none", "null", "anonymous", "anonymous kind soul", "kind soul", "guest user"]:
                        best_name = cand_name
                        break

                best_email = "N/A"
                for ec in ["Email", "Giving Level Email", "Email (for tax receipt)"]:
                    if ec in grp.columns:
                        valid_ems = grp[ec].dropna().astype(str).str.strip()
                        valid_ems = valid_ems[valid_ems.str.contains("@", na=False) & (~valid_ems.str.lower().isin(["nan", "none", "", "null"]))]
                        if not valid_ems.empty:
                            best_email = valid_ems.iloc[0]
                            break
                if best_email == "N/A" and "@" in str_did:
                    best_email = str_did

                best_phone = ""
                for pc in ["Phone Number", "Phone", "phone_number", "Home phone number", "Contact Phone"]:
                    if pc in grp.columns:
                        valid_phs = grp[pc].dropna().astype(str).str.strip().str.lstrip("'")
                        valid_phs = valid_phs[~valid_phs.str.lower().isin(["", "nan", "none", "null", "n/a"])]
                        if not valid_phs.empty:
                            best_phone = valid_phs.iloc[0]
                            break

                grp_indices = grp.index
                ltv = float(amt_series[grp_indices].sum())
                s_indices = grp_indices.intersection(df[s_mask].index)
                s_donated = float(amt_series[s_indices].sum()) if len(s_indices) > 0 else 0.0

                slot_threshold = 0.8 * target_amount if target_amount > 0 else 0.0
                max_slots = int(s_donated // slot_threshold) if slot_threshold > 0 else 0

                # Collect all email keys for this donor across group, email, and ID
                donor_emails = set()
                if best_email and best_email.lower() != "n/a":
                    donor_emails.add(best_email.strip().lower())
                if "@" in str_did:
                    donor_emails.add(str_did.strip().lower())
                for ec in ["Email", "Giving Level Email", "Email (for tax receipt)"]:
                    if ec in grp.columns:
                        for em in grp[ec].dropna().astype(str).str.strip().str.lower().unique():
                            if "@" in em and em not in ["nan", "none", "null"]:
                                donor_emails.add(em)

                matched_allocs_dict = {}
                for ek in donor_emails:
                    for item in alloc_by_email.get(ek, []):
                        matched_allocs_dict[item.get("id") or item.get("beneficiary_id")] = item
                for item in alloc_by_did.get(str_did.strip().lower(), []):
                    matched_allocs_dict[item.get("id") or item.get("beneficiary_id")] = item

                allocated_items = list(matched_allocs_dict.values())
                allocated_count = _slots_used(allocated_items)
                remaining_slots = max(0, round(max_slots - allocated_count, 2))

                if allocated_count > max_slots:
                    elig_status = "over_capacity" if max_slots > 0 else "exceptional"
                elif s_donated >= slot_threshold and remaining_slots > 0:
                    elig_status = "eligible"
                elif s_donated >= slot_threshold and remaining_slots == 0:
                    elig_status = "at_capacity"
                elif allocated_count > 0:
                    elig_status = "exceptional"
                else:
                    elig_status = "ineligible"

                causes = []
                for col_c in ["Heading", "Campaign Title", "Campaign Name", "Programme Fund"]:
                    if col_c in grp.columns:
                        vals = [v for v in grp[col_c].dropna().astype(str).str.strip().unique() if v and v.lower() not in ["nan", "none", "null"]]
                        causes.extend(vals)
                causes = list(dict.fromkeys(causes))[:3]

                results.append({
                    "donor_id": str_did,
                    "donor_name": best_name,
                    "donor_email": best_email,
                    "donor_phone": best_phone,
                    "total_donated": round(s_donated, 2),
                    "total_lifetime_donated": round(ltv, 2),
                    "causes": causes,
                    "target_amount": target_amount,
                    "max_slots": max_slots,
                    "allocated_count": allocated_count,
                    "remaining_slots": remaining_slots,
                    "status": elig_status,
                    "is_manual": False,
                    "allocated_beneficiaries": allocated_items
                })

    results.sort(key=lambda x: (x["remaining_slots"] > 0, x["allocated_count"] > 0, x["total_lifetime_donated"]), reverse=True)
    return {
        "sponsorship_type": s_type,
        "target_amount": target_amount,
        "count": len(results),
        "donors": results
    }


# ==========================================
# MANUAL DONORS CRUD ENDPOINTS
# ==========================================

@router.get("/manual-donors")
def list_manual_donors(
    company_id: Optional[str] = Query("rethink"),
    sponsorship_type: Optional[str] = Query(None)
):
    """Lists all manually created sponsorship donors."""
    comp = (company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        query = "SELECT * FROM sponsorship_manual_donors WHERE 1=1"
        params = []
        if comp != "all":
            query += " AND company_id = ?"
            params.append(comp)
        if sponsorship_type and sponsorship_type.lower() != "all":
            query += " AND sponsorship_type = ?"
            params.append(sponsorship_type)
        query += " ORDER BY created_at DESC"
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        return {"manual_donors": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.post("/manual-donors")
def create_manual_donor(
    payload: ManualDonorCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    """Creates a standalone manual sponsorship donor without requiring beneficiary assignment upfront."""
    name = (payload.donor_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Donor Full Name is required.")

    email = (payload.donor_email or "").strip()
    phone = (payload.donor_phone or "").strip()
    if not email and not phone:
        raise HTTPException(status_code=400, detail="At least an Email or Phone Number is required.")

    donor_id = f"md_{uuid.uuid4().hex[:8]}"
    comp = (payload.company_id or "rethink").strip().lower()

    # Determine and validate classification
    classification = payload.classification
    if classification:
        validate_classification_for_company(classification, comp)
    else:
        classification = "Iqra Only" if comp == "iqra" else "Rethink Only"

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sponsorship_manual_donors (
                id, company_id, donor_name, donor_email, donor_phone,
                sponsorship_type, total_donated, custom_slots, notes, classification
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            donor_id,
            comp,
            name,
            email,
            phone,
            payload.sponsorship_type or "Orphan",
            float(payload.total_donated or 0.0),
            payload.custom_slots,
            payload.notes or "",
            classification
        ))

        # Also register in sponsorship_donor_classifications table
        cur.execute("""
            INSERT INTO sponsorship_donor_classifications (
                donor_id, donor_email, company_id, classification, updated_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(donor_id, company_id) DO UPDATE SET
                classification = excluded.classification,
                company_id = excluded.company_id,
                donor_email = COALESCE(excluded.donor_email, sponsorship_donor_classifications.donor_email),
                updated_by = excluded.updated_by,
                updated_at = CURRENT_TIMESTAMP
        """, (
            f"manual_{donor_id}",
            email.lower() if email else None,
            comp,
            classification,
            current_user.get("username", "admin")
        ))

        conn.commit()
        invalidate_overdue_cache(comp)
        return {
            "status": "success",
            "message": f"Successfully created manual donor '{name}' for {payload.sponsorship_type} sponsorship tracking!",
            "donor_id": donor_id,
            "classification": classification
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.put("/manual-donors/{donor_id}")
def update_manual_donor(
    donor_id: str,
    payload: ManualDonorUpdateRequest,
    current_user: dict = Depends(get_current_user)
):
    """Updates an existing manual sponsorship donor's details."""
    raw_id = donor_id.replace("manual_", "")
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, company_id, donor_email FROM sponsorship_manual_donors WHERE id = ?", (raw_id,))
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Manual donor not found")
        comp = existing["company_id"] or "rethink"
        existing_email = existing["donor_email"]

        fields = []
        params = []
        if payload.donor_name is not None:
            fields.append("donor_name = ?")
            params.append(payload.donor_name.strip())
        if payload.donor_email is not None:
            fields.append("donor_email = ?")
            params.append(payload.donor_email.strip())
            existing_email = payload.donor_email.strip()
        if payload.donor_phone is not None:
            fields.append("donor_phone = ?")
            params.append(payload.donor_phone.strip())
        if payload.sponsorship_type is not None:
            fields.append("sponsorship_type = ?")
            params.append(payload.sponsorship_type.strip())
        if payload.total_donated is not None:
            fields.append("total_donated = ?")
            params.append(float(payload.total_donated))
        if payload.custom_slots is not None:
            fields.append("custom_slots = ?")
            params.append(int(payload.custom_slots))
        if payload.notes is not None:
            fields.append("notes = ?")
            params.append(payload.notes.strip())
        if payload.classification is not None:
            validate_classification_for_company(payload.classification, comp)
            fields.append("classification = ?")
            params.append(payload.classification.strip())

        if not fields:
            return {"status": "no_change"}

        fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(raw_id)
        cur.execute(f"UPDATE sponsorship_manual_donors SET {', '.join(fields)} WHERE id = ?", params)

        if payload.classification is not None:
            cur.execute("""
                INSERT INTO sponsorship_donor_classifications (
                    donor_id, donor_email, company_id, classification, updated_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(donor_id, company_id) DO UPDATE SET
                    classification = excluded.classification,
                    company_id = excluded.company_id,
                    donor_email = COALESCE(excluded.donor_email, sponsorship_donor_classifications.donor_email),
                    updated_by = excluded.updated_by,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                f"manual_{raw_id}",
                existing_email.lower() if existing_email else None,
                comp,
                payload.classification.strip(),
                current_user.get("username", "admin")
            ))

        conn.commit()
        invalidate_overdue_cache(None)
        return {"status": "success", "message": "Manual donor updated successfully."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.delete("/manual-donors/{donor_id}")
def delete_manual_donor(
    donor_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Deletes a manual sponsorship donor."""
    raw_id = donor_id.replace("manual_", "")
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM sponsorship_manual_donors WHERE id = ?", (raw_id,))
        cur.execute("DELETE FROM sponsorship_donor_classifications WHERE donor_id = ? OR donor_id = ?", (f"manual_{raw_id}", raw_id))
        conn.commit()
        invalidate_overdue_cache(None)
        return {"status": "success", "message": "Manual donor deleted successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/classifications/options")
def get_classification_options(company_id: Optional[str] = Query("rethink")):
    """Returns valid source classification options for the active workspace."""
    comp = _unwrap_param(company_id, "rethink").strip().lower()
    options = WORKSPACE_ALLOWED_CLASSIFICATIONS.get(comp, WORKSPACE_ALLOWED_CLASSIFICATIONS["rethink"])
    return {
        "company_id": comp,
        "options": options
    }


@router.post("/donors/classify")
def classify_donor(
    payload: DonorClassifyRequest,
    current_user: dict = Depends(get_current_user)
):
    """Assigns or updates a donor's classification (Rethink Only, Rethink + SP, Iqra Only, Iqra + SP)."""
    comp = (payload.company_id or "rethink").strip().lower()
    validate_classification_for_company(payload.classification, comp)
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        did = payload.donor_id.strip()
        demail = (payload.donor_email or "").strip().lower() or None

        cur.execute("""
            INSERT INTO sponsorship_donor_classifications (
                donor_id, donor_email, company_id, classification, updated_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(donor_id, company_id) DO UPDATE SET
                classification = excluded.classification,
                company_id = excluded.company_id,
                donor_email = COALESCE(excluded.donor_email, sponsorship_donor_classifications.donor_email),
                updated_by = excluded.updated_by,
                updated_at = CURRENT_TIMESTAMP
        """, (did, demail, comp, payload.classification, current_user.get("username", "admin")))

        # If it's a manual donor, also update the sponsorship_manual_donors table
        if did.startswith("manual_") or did.startswith("md_"):
            raw_id = did.replace("manual_", "")
            cur.execute("UPDATE sponsorship_manual_donors SET classification = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (payload.classification, raw_id))

        conn.commit()
        invalidate_overdue_cache(comp)
        return {
            "status": "success",
            "donor_id": did,
            "classification": payload.classification,
            "message": f"Classification updated to '{payload.classification}'"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.post("/campaigns/classify")
def classify_campaign(
    payload: CampaignClassifyRequest,
    current_user: dict = Depends(get_current_user)
):
    """Assigns or updates a campaign's classification (Rethink Only, Rethink + SP, Iqra Only, Iqra + SP)."""
    comp = (payload.company_id or "rethink").strip().lower()
    validate_classification_for_company(payload.classification, comp)
    cname = (payload.campaign_name or "").strip()
    if not cname:
        raise HTTPException(status_code=400, detail="Campaign name is required.")

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sponsorship_campaign_classifications (
                campaign_name, company_id, classification, updated_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(campaign_name, company_id) DO UPDATE SET
                classification = excluded.classification,
                company_id = excluded.company_id,
                updated_by = excluded.updated_by,
                updated_at = CURRENT_TIMESTAMP
        """, (cname, comp, payload.classification, current_user.get("username", "admin")))

        conn.commit()
        invalidate_overdue_cache(comp)
        return {
            "status": "success",
            "campaign_name": cname,
            "classification": payload.classification,
            "message": f"Campaign classification updated to '{payload.classification}'"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


def _call_with_query(fn, query_string: str, comp: str, **fixed):
    """Calls a GET handler the way FastAPI would for `?query_string`, so it shares the same cache entries.
    company_id is always the outer request's (already access-checked) company, never the sub-query's."""
    import inspect
    import typing
    from urllib.parse import parse_qsl
    from core.cache import route_defaults
    params = inspect.signature(inspect.unwrap(fn)).parameters
    kwargs = route_defaults(fn, company_id=comp, **fixed)
    for key, value in parse_qsl(query_string or "", keep_blank_values=False):
        if key == "company_id" or key in fixed or key not in params:
            continue
        kinds = typing.get_args(params[key].annotation) or (params[key].annotation,)
        if bool in kinds:
            value = value.strip().lower() in ("1", "true", "yes", "on")
        elif int in kinds:
            value = int(value)
        elif float in kinds:
            value = float(value)
        kwargs[key] = value
    return fn(**kwargs)


@router.get("/page-data")
async def get_tracker_page_data(
    company_id: Optional[str] = Query("rethink"),
    sponsorship_type: Optional[str] = Query("Orphan"),
    ben: Optional[str] = Query(""),
    alloc: Optional[str] = Query(""),
):
    """Everything the tracker page loads at once, in one round trip. Each section is exactly what its own
    endpoint returns (same handlers, same cache entries): beneficiaries, allocations, qualifying donors and
    campaigns for the selected sponsorship type, Outlook status and email templates."""
    import asyncio
    comp = _unwrap_param(company_id, "rethink").strip().lower()
    s_type = _unwrap_param(sponsorship_type, "Orphan").strip() or "Orphan"
    jobs = {
        "beneficiaries": lambda: _call_with_query(get_beneficiaries, ben, comp),
        "allocations": lambda: _call_with_query(get_allocations, alloc, comp),
        "qualifying_donors": lambda: _call_with_query(get_qualifying_donors, "", comp, sponsorship_type=s_type),
        "qualifying_campaigns": lambda: _call_with_query(get_qualifying_campaigns, "", comp, sponsorship_type=s_type),
        "outlook_status": lambda: get_outlook_status(company_id=comp),
        "email_templates": lambda: get_email_templates(company_id=comp, charity_theme=None),
    }
    results = await asyncio.gather(*(asyncio.to_thread(job) for job in jobs.values()))
    return dict(zip(jobs.keys(), results))


@router.get("/qualifying-campaigns")
@cached(scopes=["donations", "classification", "tracker", "fundraisers"], ttl=21600, daily=True)
def get_qualifying_campaigns(
    company_id: Optional[str] = Query("rethink"),
    sponsorship_type: Optional[str] = Query("Orphan"),
    search: Optional[str] = Query(None),
    classification: Optional[str] = Query(None)
):
    """
    Returns qualifying campaigns/communities for a given sponsorship type with capacity calculations:
    - campaign_name: Name of the campaign
    - community_name: Mapped community name
    - organizer_name: Contact/organizer name from campaign mappings
    - organizer_email: Contact/organizer email(s) from campaign mappings
    - total_raised: Total funds raised for this sponsorship type under this campaign
    - target_amount: Target cost per beneficiary (e.g. 480)
    - max_slots: floor(total_raised / target_amount)
    - allocated_count: Number of beneficiaries currently allocated to this campaign
    - remaining_slots: max_slots - allocated_count
    - status: 'eligible' | 'at_capacity' | 'near_target'
    - classification: Campaign source classification (Rethink Only, Rethink + SP, Iqra Only, Iqra + SP)
    """
    comp = _unwrap_param(company_id, "rethink").strip().lower()
    s_type = _unwrap_param(sponsorship_type, "Orphan").strip()
    search = _unwrap_param(search, "").strip() or None
    target_class = _unwrap_param(classification, "").strip() or None

    targets = {"Hafiz": 240.0, "Orphan": 480.0, "Widow": 1080.0, "Ex-Prisoner": 1080.0}
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        if comp != "all":
            cur.execute("SELECT sponsorship_type, target_value FROM sponsorship_targets WHERE company_id = ?", (comp,))
        else:
            cur.execute("SELECT sponsorship_type, target_value FROM sponsorship_targets")
        for r in cur.fetchall():
            targets[r["sponsorship_type"]] = float(r["target_value"])

        # Fetch saved campaign classifications
        camp_cls_query = "SELECT campaign_name, classification FROM sponsorship_campaign_classifications WHERE 1=1"
        camp_cls_params = []
        if comp != "all":
            camp_cls_query += " AND company_id = ?"
            camp_cls_params.append(comp)
        cur.execute(camp_cls_query, camp_cls_params)
        saved_camp_classes = {str(cr["campaign_name"]).strip().lower(): cr["classification"] for cr in cur.fetchall()}

        # Fetch existing campaign allocations
        alloc_query = """
            SELECT a.campaign_name, a.community_name, a.donor_email, a.beneficiary_id, b.name AS beneficiary_name, b.project_code, b.sponsorship_type
            FROM sponsorship_allocations a
            JOIN sponsorship_beneficiaries b ON a.beneficiary_id = b.id
            WHERE a.allocation_type = 'campaign'
        """
        alloc_params = []
        if comp != "all":
            alloc_query += " AND a.company_id = ?"
            alloc_params.append(comp)
        cur.execute(alloc_query, alloc_params)
        all_allocs = [dict(r) for r in cur.fetchall()]

        # Fetch platform campaign mappings for metadata (organizer info, community name)
        map_query = "SELECT campaign_name, community_name, donor_name, donor_email, campaign_url, code FROM platform_campaign_mappings WHERE 1=1"
        map_params = []
        if comp != "all":
            map_query += " AND company_id = ?"
            map_params.append(comp)
        cur.execute(map_query, map_params)
        mappings = [dict(r) for r in cur.fetchall()]

        # Organizer contacts come only from the Fundraisers registry. The donor_name/donor_email
        # columns of platform_campaign_mappings hold the campaign's last DONOR, not its organizer.
        reg_query = """
            SELECT LOWER(TRIM(fc.campaign_name)) AS ckey, f.id AS fundraiser_id, f.name, f.email, f.phone
            FROM fundraiser_campaigns fc
            JOIN fundraisers f ON f.id = fc.fundraiser_id AND f.company_id = fc.company_id
            WHERE COALESCE(TRIM(f.email), '') != '' OR COALESCE(TRIM(f.phone), '') != ''
        """
        reg_params = []
        if comp != "all":
            reg_query += " AND fc.company_id = ?"
            reg_params.append(comp)
        cur.execute(reg_query, reg_params)
        organizers_by_campaign: Dict[str, List[Dict[str, Any]]] = {}
        for r in cur.fetchall():
            org = {"fundraiser_id": r["fundraiser_id"], "name": (r["name"] or "").strip(),
                   "email": (r["email"] or "").strip(), "phone": (r["phone"] or "").strip()}
            bucket = organizers_by_campaign.setdefault(r["ckey"], [])
            if org not in bucket:
                bucket.append(org)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

    map_by_campaign = {}
    norm_map_by_campaign = {}
    for m in mappings:
        c_name_key = (m.get("campaign_name") or "").strip().lower()
        norm_key = re.sub(r"[^a-z0-9]", "", c_name_key)
        if c_name_key and c_name_key not in map_by_campaign:
            map_by_campaign[c_name_key] = m
        if norm_key:
            # Prefer mapping with non-empty contact or non-Unassigned community
            if norm_key not in norm_map_by_campaign or (m.get("community_name") and m.get("community_name") != "Unassigned") or m.get("donor_email"):
                norm_map_by_campaign[norm_key] = m

    alloc_by_campaign = {}
    for a in all_allocs:
        c_key = (a.get("campaign_name") or "").strip().lower()
        if c_key:
            alloc_by_campaign.setdefault(c_key, []).append(a)

    target_amount = float(targets.get(s_type, 480.0))

    df = load_data(company_id=comp)
    campaign_sums_lower = {}
    campaign_sums_display = {}

    if not df.empty:
        col_amount = "Total Online Donations Net Amount in Settled Currency"
        if col_amount not in df.columns:
            col_amount = "Donation Amount in Project Currency (May be approx.)"
        if col_amount not in df.columns:
            col_amount = "Donation Amount (in Donation Currency)"

        camp_col = "Campaign Name" if "Campaign Name" in df.columns else ("Campaign" if "Campaign" in df.columns else None)
        if col_amount in df.columns and camp_col:
            amt_series = pd.to_numeric(df[col_amount], errors="coerce").fillna(0.0)
            camp_series = df[camp_col].fillna("").astype(str).str.strip()
            code_series = df["Code"].astype(str).str.strip().str.upper() if "Code" in df.columns else pd.Series("", index=df.index)

            masks = {
                "Hafiz": code_series.str.contains("HUF", na=False),
                "Orphan": code_series.str.contains("ORP", na=False),
                "Widow": code_series.str.contains("WID", na=False),
                "Ex-Prisoner": code_series.str.contains("SUR", na=False) | code_series.str.contains("EX-PRISONER", na=False)
            }

            mask = masks.get(s_type, pd.Series(False, index=df.index))
            date_col_cand = None
            for c in ["_parsed_date", "Created Date (UTC)", "Date", "Settled Date (UTC)", "created_at", "Date of collection"]:
                if c in df.columns:
                    date_col_cand = c
                    break
            if date_col_cand:
                df = df.assign(_unified_dt=pd.to_datetime(df[date_col_cand], errors="coerce", format="mixed"))
            else:
                df = df.assign(_unified_dt=pd.NaT)

            if mask.any():
                s_amt = amt_series[mask]
                s_camp = camp_series[mask]
                grouped = s_amt.groupby(s_camp).sum()
                for c_name, tot in grouped.items():
                    c_str = str(c_name).strip()
                    if c_str and c_str.lower() not in ("nan", "none", "null", "n/a") and float(tot) > 0:
                        c_key = c_str.lower()
                        campaign_sums_lower[c_key] = campaign_sums_lower.get(c_key, 0.0) + float(tot)
                        if c_key not in campaign_sums_display:
                            campaign_sums_display[c_key] = c_str

    # Pre-aggregate min and max donation dates per campaign in a single vectorized pass (O(1) lookup)
    campaign_dates = {}
    campaign_timelines = {}
    if not df.empty and camp_col and "_unified_dt" in df.columns and mask.any():
        try:
            valid_dt_df = df[mask & df["_unified_dt"].notna()]
            if not valid_dt_df.empty:
                clean_camps = valid_dt_df[camp_col].fillna("").astype(str).str.strip().str.lower()
                dt_grp = valid_dt_df.groupby(clean_camps)["_unified_dt"].agg(["min", "max"])
                for c_k_idx, row_dt in dt_grp.iterrows():
                    campaign_dates[c_k_idx] = (row_dt["min"], row_dt["max"])
                # Running total per campaign, to date when each slot threshold was reached.
                tl = pd.DataFrame({"c": clean_camps, "dt": valid_dt_df["_unified_dt"],
                                   "amt": amt_series.reindex(valid_dt_df.index).fillna(0.0)}).sort_values(["c", "dt"])
                tl["cum"] = tl.groupby("c")["amt"].cumsum()
                campaign_timelines = {k: (g["dt"].to_numpy(), g["cum"].to_numpy()) for k, g in tl.groupby("c")}
        except Exception as e:
            logger.warning(f"Error vectorizing campaign dates: {e}")

    # Only include campaigns that have actual real-time donations (> £0) OR have active allocations
    all_campaign_keys = set(campaign_sums_lower.keys())
    for c_key in alloc_by_campaign.keys():
        all_campaign_keys.add(c_key)

    search_str = search.strip().lower() if search and isinstance(search, str) and search.strip() else ""

    campaigns_list = []
    now_dt = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    for c_key in all_campaign_keys:
        tot_val = campaign_sums_lower.get(c_key, 0.0)
        norm_key = re.sub(r"[^a-z0-9]", "", c_key)
        mapping_info = map_by_campaign.get(c_key) or norm_map_by_campaign.get(norm_key) or {}

        c_display = campaign_sums_display.get(c_key) or mapping_info.get("campaign_name") or c_key
        comm_name = mapping_info.get("community_name") or ""
        organizers = organizers_by_campaign.get(c_key) or organizers_by_campaign.get(
            (mapping_info.get("campaign_name") or "").strip().lower(), [])
        org_name = ", ".join(o["name"] for o in organizers if o["name"])
        org_email = ", ".join(o["email"] for o in organizers if o["email"])

        # Determine verified Campaign URL
        raw_url = str(mapping_info.get("campaign_url") or "").strip()
        if raw_url.lower() in ["unassigned", "none", "nan", "null", "n/a", ""]:
            clean_url = ""
        elif raw_url.startswith("http://") or raw_url.startswith("https://"):
            clean_url = raw_url
        else:
            clean_url = "https://www.launchgood.com/" + raw_url.lstrip("/")

        fallback_search_url = f"https://www.launchgood.com/campaign/search?q={urllib.parse.quote_plus(c_display)}"
        campaign_url = clean_url if clean_url else fallback_search_url
        has_direct_url = bool(clean_url)

        allocated_items = alloc_by_campaign.get(c_key, [])
        allocated_count = _slots_used(allocated_items)
        slot_threshold = 0.8 * target_amount if target_amount > 0 else 0.0
        max_slots = int(tot_val // slot_threshold) if slot_threshold > 0 else 0
        remaining_slots = max(0, round(max_slots - allocated_count, 2))

        if tot_val >= slot_threshold and remaining_slots > 0:
            elig_status = "eligible"
        elif tot_val >= slot_threshold and remaining_slots == 0:
            elig_status = "at_capacity"
        else:
            elig_status = "near_target"

        saved_cls = saved_camp_classes.get(c_key) or saved_camp_classes.get(c_display.strip().lower())
        if saved_cls:
            c_classification = saved_cls
            is_manually_classified = True
        else:
            c_classification = suggest_campaign_classification(c_display, comp)
            is_manually_classified = False

        if target_class and target_class.lower() != "all" and c_classification != target_class:
            continue

        if search_str:
            if (search_str not in c_display.lower() and 
                search_str not in comm_name.lower() and 
                search_str not in org_name.lower() and 
                search_str not in org_email.lower()):
                continue

        # Extract donation dates for this campaign in O(1) time
        c_oldest_dt, c_latest_dt = campaign_dates.get(c_key, (None, None))
        if hasattr(c_oldest_dt, 'to_pydatetime'):
            c_oldest_dt = c_oldest_dt.to_pydatetime()
        if hasattr(c_oldest_dt, 'tzinfo') and c_oldest_dt and c_oldest_dt.tzinfo:
            c_oldest_dt = c_oldest_dt.replace(tzinfo=None)
        if hasattr(c_latest_dt, 'to_pydatetime'):
            c_latest_dt = c_latest_dt.to_pydatetime()
        if hasattr(c_latest_dt, 'tzinfo') and c_latest_dt and c_latest_dt.tzinfo:
            c_latest_dt = c_latest_dt.replace(tzinfo=None)

        c_oldest_str = c_oldest_dt.strftime("%Y-%m-%d") if c_oldest_dt and pd.notna(c_oldest_dt) else "N/A"
        c_latest_str = c_latest_dt.strftime("%Y-%m-%d") if c_latest_dt and pd.notna(c_latest_dt) else "N/A"
        # Waiting age starts when the campaign's running total earned the slot it is still waiting for.
        c_eligible_since = None
        if slot_threshold > 0 and remaining_slots > 0 and c_key in campaign_timelines:
            dts, cums = campaign_timelines[c_key]
            idx = int(np.searchsorted(cums, (int(allocated_count) + 1) * slot_threshold - 1e-6))
            if idx < len(dts):
                c_eligible_since = pd.Timestamp(dts[idx]).to_pydatetime().replace(tzinfo=None)
        c_waiting_days = max(0, (now_dt - c_eligible_since).days) if c_eligible_since else 0

        pct_raised = round((tot_val / target_amount) * 100, 1) if target_amount > 0 else 0.0
        is_target_reached = bool(tot_val >= target_amount)
        is_threshold_reached = bool(tot_val >= slot_threshold)
        if is_target_reached:
            target_status = "target_reached"
        elif is_threshold_reached:
            target_status = "threshold_reached"
        else:
            target_status = "below_threshold"

        campaigns_list.append({
            "campaign_name": c_display,
            "community_name": comm_name if comm_name != "Unassigned" else "",
            "organizer_name": org_name,
            "organizer_email": org_email,
            "organizers": organizers,
            "organizer_source": "fundraiser_registry" if organizers else "none",
            "campaign_url": campaign_url,
            "has_direct_url": has_direct_url,
            "total_raised": round(tot_val, 2),
            "target_amount": target_amount,
            "pct_raised": pct_raised,
            "target_status": target_status,
            "is_target_reached": is_target_reached,
            "is_threshold_reached": is_threshold_reached,
            "max_slots": max_slots,
            "allocated_count": allocated_count,
            "remaining_slots": remaining_slots,
            "status": elig_status,
            "classification": c_classification,
            "is_manually_classified": is_manually_classified,
            "oldest_donation_date": c_oldest_str,
            "latest_donation_date": c_latest_str,
            "eligible_since": c_eligible_since.strftime("%Y-%m-%d") if c_eligible_since else None,
            "waiting_days": c_waiting_days,
            "allocated_beneficiaries": allocated_items
        })

    campaigns_list.sort(key=lambda x: (x["remaining_slots"] > 0, x["total_raised"]), reverse=True)
    return {
        "sponsorship_type": s_type,
        "target_amount": target_amount,
        "count": len(campaigns_list),
        "campaigns": campaigns_list
    }


# ==========================================
# 6. ALLOCATIONS MANAGEMENT
# ==========================================
def _parse_iso_date(val: Optional[str]) -> Optional[datetime.date]:
    if not val:
        return None
    try:
        s = str(val).strip()[:10]
        return datetime.date.fromisoformat(s)
    except Exception:
        return None


@router.get("/allocations")
@cached(scopes=["tracker", "tracker_comms"], ttl=3600, daily=True)
def get_allocations(
    company_id: Optional[str] = Query("rethink"),
    sponsorship_type: Optional[str] = Query(None),
    allocation_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    renewal_filter: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    donor: Optional[str] = Query(None),
    beneficiary: Optional[str] = Query(None),
    campaign: Optional[str] = Query(None),
    start_from: Optional[str] = Query(None),
    start_to: Optional[str] = Query(None),
    end_from: Optional[str] = Query(None),
    end_to: Optional[str] = Query(None),
    last_emailed_from: Optional[str] = Query(None),
    last_emailed_to: Optional[str] = Query(None),
    never_emailed: Optional[bool] = Query(None),
    funded_status: Optional[str] = Query(None),
    needs_review: Optional[bool] = Query(None),
    classification: Optional[str] = Query(None),
    first_emailed_from: Optional[str] = Query(None),
    first_emailed_to: Optional[str] = Query(None),
    first_emailed_preset: Optional[str] = Query(None),
    first_mail_6_months: Optional[bool] = Query(None),
    email_sequence: Optional[str] = Query(None),
    response_status: Optional[str] = Query(None),
    no_response: Optional[bool] = Query(None),
    contact_status: Optional[str] = Query(None),
    open_status: Optional[str] = Query(None),
):
    """Returns all allocations joined with beneficiary, campaign metadata, communication metrics, and renewal lifecycle stats."""
    def _clean_str(v):
        return v.strip() if isinstance(v, str) and v.strip() else None

    def _clean_bool(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes")
        return None

    company_id = _clean_str(company_id) or "rethink"
    sponsorship_type = _clean_str(sponsorship_type)
    allocation_type = _clean_str(allocation_type)
    status = _clean_str(status)
    renewal_filter = _clean_str(renewal_filter)
    search = _clean_str(search)
    donor = _clean_str(donor)
    beneficiary = _clean_str(beneficiary)
    campaign = _clean_str(campaign)
    start_from = _clean_str(start_from)
    start_to = _clean_str(start_to)
    end_from = _clean_str(end_from)
    end_to = _clean_str(end_to)
    last_emailed_from = _clean_str(last_emailed_from)
    last_emailed_to = _clean_str(last_emailed_to)
    never_emailed = _clean_bool(never_emailed)
    funded_status = _clean_str(funded_status)
    needs_review = _clean_bool(needs_review)
    classification = _clean_str(classification)
    first_emailed_from = _clean_str(first_emailed_from)
    first_emailed_to = _clean_str(first_emailed_to)
    first_emailed_preset = _clean_str(first_emailed_preset)
    first_mail_6_months = _clean_bool(first_mail_6_months)
    email_sequence = _clean_str(email_sequence)
    response_status = _clean_str(response_status)
    no_response = _clean_bool(no_response)
    contact_status = _clean_str(contact_status)
    open_status = _clean_str(open_status)

    comp = company_id.lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        query = """
            SELECT 
                a.id,
                a.company_id,
                a.beneficiary_id,
                a.donor_email,
                a.donor_phone,
                a.donor_name,
                a.donor_id,
                a.allocation_type,
                a.campaign_name,
                a.community_name,
                a.allocated_amount,
                a.start_date,
                a.end_date,
                a.renewal_status,
                a.renewal_count,
                a.last_renewed_at,
                a.communication_status,
                a.last_contacted_at,
                a.last_replied_at,
                a.admin_notes,
                a.created_at,
                b.name AS beneficiary_name,
                b.sponsorship_type,
                b.location,
                b.project_code,
                b.profile_link,
                b.video_link,
                b.donor_folder_link,
                (SELECT COUNT(*) FROM sponsorship_feedbacks f WHERE f.beneficiary_id = b.id) AS feedbacks_count,
                (SELECT COUNT(*) FROM sponsorship_communications c WHERE c.allocation_id = a.id) AS messages_count,
                (SELECT COUNT(*) FROM sponsorship_communications c WHERE c.allocation_id = a.id AND c.direction = 'outbound') AS outbound_emails_count,
                (SELECT COUNT(*) FROM sponsorship_communications c WHERE c.allocation_id = a.id AND c.direction = 'inbound') AS inbound_replies_count,
                (SELECT MIN(c.sent_at) FROM sponsorship_communications c WHERE c.allocation_id = a.id AND c.direction = 'outbound') AS first_email_sent_at,
                (SELECT c.sent_at FROM sponsorship_communications c WHERE c.allocation_id = a.id AND c.direction = 'outbound' ORDER BY c.sent_at ASC LIMIT 1 OFFSET 1) AS second_email_sent_at,
                (SELECT c.delivery_status FROM sponsorship_communications c WHERE c.allocation_id = a.id AND c.direction = 'outbound' ORDER BY c.sent_at DESC LIMIT 1) AS latest_email_status,
                (SELECT c.opened_at FROM sponsorship_communications c WHERE c.allocation_id = a.id AND c.direction = 'outbound' ORDER BY c.sent_at DESC LIMIT 1) AS latest_email_opened_at,
                (SELECT c.open_count FROM sponsorship_communications c WHERE c.allocation_id = a.id AND c.direction = 'outbound' ORDER BY c.sent_at DESC LIMIT 1) AS latest_email_open_count,
                (SELECT c.sent_at FROM sponsorship_communications c WHERE c.allocation_id = a.id AND c.direction = 'outbound' ORDER BY c.sent_at DESC LIMIT 1) AS latest_email_sent_at,
                (SELECT c.subject FROM sponsorship_communications c WHERE c.allocation_id = a.id AND c.direction = 'outbound' ORDER BY c.sent_at DESC LIMIT 1) AS latest_email_subject,
                (SELECT GROUP_CONCAT(DISTINCT c.template_type) FROM sponsorship_communications c WHERE c.allocation_id = a.id AND c.direction = 'outbound') AS templates_sent
            FROM sponsorship_allocations a
            JOIN sponsorship_beneficiaries b ON a.beneficiary_id = b.id
            WHERE 1=1
        """
        params = []
        if comp != "all":
            query += " AND a.company_id = ?"
            params.append(comp)
        if sponsorship_type:
            query += " AND b.sponsorship_type = ?"
            params.append(sponsorship_type)
        if allocation_type and allocation_type.strip().lower() != "all":
            query += " AND a.allocation_type = ?"
            params.append(allocation_type.strip().lower())
        if status:
            query += " AND a.communication_status = ?"
            params.append(status)
        if search:
            query += (" AND (a.donor_name LIKE ? OR a.donor_email LIKE ? OR a.donor_phone LIKE ? OR a.campaign_name LIKE ? OR b.name LIKE ? OR b.project_code LIKE ?"
                      " OR EXISTS (SELECT 1 FROM sponsorship_allocation_donors sd WHERE sd.allocation_id = a.id"
                      " AND (sd.donor_name LIKE ? OR sd.donor_email LIKE ? OR sd.donor_phone LIKE ?)))")
            s_param = f"%{search.strip()}%"
            params.extend([s_param] * 9)
        if donor:
            query += (" AND EXISTS (SELECT 1 FROM sponsorship_allocation_donors sd WHERE sd.allocation_id = a.id"
                      " AND (sd.donor_name LIKE ? OR sd.donor_email LIKE ? OR sd.donor_phone LIKE ?))")
            params.extend([f"%{donor.strip()}%"] * 3)
        if beneficiary:
            query += " AND (b.name LIKE ? OR b.project_code LIKE ?)"
            params.extend([f"%{beneficiary.strip()}%"] * 2)
        if campaign:
            query += " AND (a.campaign_name LIKE ? OR a.community_name LIKE ?)"
            params.extend([f"%{campaign.strip()}%"] * 2)
        for col, op, val in (("a.start_date", ">=", start_from), ("a.start_date", "<=", start_to),
                             ("a.end_date", ">=", end_from), ("a.end_date", "<=", end_to)):
            if val:
                query += f" AND substr({col}, 1, 10) {op} ?"
                params.append(val[:10])
        if last_emailed_from:
            query += " AND substr(a.last_contacted_at, 1, 10) >= ?"
            params.append(last_emailed_from[:10])
        if last_emailed_to:
            query += " AND substr(a.last_contacted_at, 1, 10) <= ?"
            params.append(last_emailed_to[:10])
        if never_emailed:
            query += " AND NOT EXISTS (SELECT 1 FROM sponsorship_communications c WHERE c.allocation_id = a.id AND c.direction = 'outbound')"

        query += " ORDER BY a.created_at DESC"
        cur.execute(query, params)
        raw_rows = [dict(r) for r in cur.fetchall()]

        today = datetime.date.today()
        computed_allocations = []

        for row in raw_rows:
            start_d_str = row.get("start_date") or (row.get("created_at")[:10] if row.get("created_at") else today.isoformat())
            end_d_str = row.get("end_date")
            if not end_d_str:
                try:
                    s_dt = datetime.datetime.strptime(start_d_str[:10], "%Y-%m-%d").date()
                    end_d_str = (s_dt + datetime.timedelta(days=365)).isoformat()
                except Exception:
                    end_d_str = (today + datetime.timedelta(days=365)).isoformat()

            try:
                e_dt = datetime.datetime.strptime(end_d_str[:10], "%Y-%m-%d").date()
                days_remaining = (e_dt - today).days
            except Exception:
                days_remaining = 365

            if days_remaining > 30:
                cycle_status = "active"
            elif 0 <= days_remaining <= 30:
                cycle_status = "due_for_renewal"
            elif -30 <= days_remaining < 0:
                cycle_status = "grace_period"
            else:
                cycle_status = "lapsed"

            ren_count = row.get("renewal_count") or 0
            row["start_date"] = start_d_str
            row["end_date"] = end_d_str
            row["days_remaining"] = days_remaining
            row["cycle_status"] = cycle_status
            row["renewal_count"] = ren_count
            row["sponsorship_year"] = f"Year {ren_count + 1}"
            row["renewal_status"] = row.get("renewal_status") or cycle_status

            if renewal_filter and renewal_filter != "all":
                if renewal_filter != cycle_status and renewal_filter != row.get("renewal_status"):
                    continue

            computed_allocations.append(row)

        _attach_donors_and_funding(cur, computed_allocations, alloc_key="id")

        # Load classifications for allocations
        cur.execute("SELECT donor_id, donor_email, classification FROM sponsorship_donor_classifications")
        d_cls_map = {}
        for cr in cur.fetchall():
            if cr["donor_id"]:
                d_cls_map[str(cr["donor_id"]).strip()] = cr["classification"]
            if cr["donor_email"]:
                d_cls_map[str(cr["donor_email"]).strip().lower()] = cr["classification"]
        cur.execute("SELECT campaign_name, classification FROM sponsorship_campaign_classifications")
        c_cls_map = {str(cr["campaign_name"]).strip().lower(): cr["classification"] for cr in cur.fetchall()}

        for r in computed_allocations:
            alloc_type = (r.get("allocation_type") or "").lower()
            alloc_comp = (r.get("company_id") or comp or "rethink").lower()
            if alloc_type == "campaign":
                cname = (r.get("campaign_name") or "").strip()
                r["classification"] = c_cls_map.get(cname.lower()) or suggest_campaign_classification(cname, alloc_comp)
            else:
                did = str(r.get("donor_id") or "").strip()
                demail = str(r.get("donor_email") or "").strip().lower()
                r["classification"] = d_cls_map.get(did) or d_cls_map.get(demail) or ("Iqra Only" if alloc_comp == "iqra" else "Rethink Only")

            for d in r.get("donors", []):
                sub_did = str(d.get("donor_id") or "").strip()
                sub_email = str(d.get("donor_email") or "").strip().lower()
                d["classification"] = d_cls_map.get(sub_did) or d_cls_map.get(sub_email) or ("Iqra Only" if alloc_comp == "iqra" else "Rethink Only")

        # 1. Classification filter
        if classification and classification.strip().lower() != "all":
            c_target = classification.strip().lower()
            computed_allocations = [
                r for r in computed_allocations
                if (r.get("classification") or "").strip().lower() == c_target
            ]

        # 2. First email date ranges
        if first_emailed_from:
            from_d = _parse_iso_date(first_emailed_from)
            if from_d:
                computed_allocations = [
                    r for r in computed_allocations
                    if _parse_iso_date(r.get("first_email_sent_at")) and _parse_iso_date(r.get("first_email_sent_at")) >= from_d
                ]
        if first_emailed_to:
            to_d = _parse_iso_date(first_emailed_to)
            if to_d:
                computed_allocations = [
                    r for r in computed_allocations
                    if _parse_iso_date(r.get("first_email_sent_at")) and _parse_iso_date(r.get("first_email_sent_at")) <= to_d
                ]

        # 3. First mail sent preset / toggle (6 months ago, 3 months ago, 1 month ago, within 30 days)
        if first_mail_6_months or (first_emailed_preset and first_emailed_preset.lower() == "6_months_ago"):
            cutoff = today - datetime.timedelta(days=180)
            computed_allocations = [
                r for r in computed_allocations
                if _parse_iso_date(r.get("first_email_sent_at")) and _parse_iso_date(r.get("first_email_sent_at")) <= cutoff
            ]
        elif first_emailed_preset and first_emailed_preset.lower() == "3_months_ago":
            cutoff = today - datetime.timedelta(days=90)
            computed_allocations = [
                r for r in computed_allocations
                if _parse_iso_date(r.get("first_email_sent_at")) and _parse_iso_date(r.get("first_email_sent_at")) <= cutoff
            ]
        elif first_emailed_preset and first_emailed_preset.lower() == "1_month_ago":
            cutoff = today - datetime.timedelta(days=30)
            computed_allocations = [
                r for r in computed_allocations
                if _parse_iso_date(r.get("first_email_sent_at")) and _parse_iso_date(r.get("first_email_sent_at")) <= cutoff
            ]
        elif first_emailed_preset and first_emailed_preset.lower() == "last_30_days":
            cutoff = today - datetime.timedelta(days=30)
            computed_allocations = [
                r for r in computed_allocations
                if _parse_iso_date(r.get("first_email_sent_at")) and _parse_iso_date(r.get("first_email_sent_at")) >= cutoff
            ]

        # 4. Response status & no_response toggle
        if no_response or (response_status and response_status.lower() in ("no_response", "unanswered", "no_reply", "awaiting_reply")):
            computed_allocations = [
                r for r in computed_allocations
                if int(r.get("outbound_emails_count") or 0) > 0 and int(r.get("inbound_replies_count") or 0) == 0 and not r.get("last_replied_at")
            ]
        elif response_status and response_status.lower() in ("replied", "has_reply", "responded"):
            computed_allocations = [
                r for r in computed_allocations
                if int(r.get("inbound_replies_count") or 0) > 0 or bool(r.get("last_replied_at"))
            ]

        # 5. Email Sequence / Count ('0', '1', '2', '3_plus')
        if email_sequence and email_sequence.lower() != "all":
            seq = str(email_sequence).strip().lower()
            if seq in ("0", "never", "none"):
                computed_allocations = [r for r in computed_allocations if int(r.get("outbound_emails_count") or 0) == 0]
            elif seq in ("1", "first", "first_mail", "1st"):
                computed_allocations = [r for r in computed_allocations if int(r.get("outbound_emails_count") or 0) == 1]
            elif seq in ("2", "second", "second_mail", "2nd"):
                computed_allocations = [r for r in computed_allocations if int(r.get("outbound_emails_count") or 0) == 2]
            elif seq in ("3_plus", "3+", "three_plus", "3"):
                computed_allocations = [r for r in computed_allocations if int(r.get("outbound_emails_count") or 0) >= 3]

        # 6. Contact Status ('contacted', 'not_contacted')
        if contact_status and contact_status.lower() != "all":
            cs = contact_status.strip().lower()
            contacted_statuses = {
                "contacted", "profile sent", "feedback sent", "welcome sent", 
                "video sent", "replied", "emailed", "completed"
            }
            if cs in ("contacted", "emailed"):
                computed_allocations = [
                    r for r in computed_allocations 
                    if int(r.get("outbound_emails_count") or 0) > 0 or (str(r.get("communication_status") or "").strip().lower() in contacted_statuses)
                ]
            elif cs in ("not_contacted", "never_contacted", "uncontacted"):
                computed_allocations = [
                    r for r in computed_allocations 
                    if int(r.get("outbound_emails_count") or 0) == 0 and (str(r.get("communication_status") or "").strip().lower() not in contacted_statuses)
                ]

        # 7. Email Open Status ('opened', 'unopened')
        if open_status and open_status.lower() != "all":
            os_val = open_status.strip().lower()
            if os_val == "opened":
                computed_allocations = [
                    r for r in computed_allocations
                    if int(r.get("latest_email_open_count") or 0) > 0 or bool(r.get("latest_email_opened_at"))
                ]
            elif os_val == "unopened":
                computed_allocations = [
                    r for r in computed_allocations
                    if int(r.get("outbound_emails_count") or 0) > 0 and int(r.get("latest_email_open_count") or 0) == 0 and not r.get("latest_email_opened_at")
                ]

        if funded_status and funded_status != "all":
            computed_allocations = [r for r in computed_allocations if r["funding_status"] == funded_status]
        if needs_review is not None:
            computed_allocations = [r for r in computed_allocations if r["needs_review"] == needs_review]
        return {"count": len(computed_allocations), "allocations": computed_allocations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# ==========================================
# 6b. DONORS PER ALLOCATION (collective sponsorships)
# ==========================================

_ALLOC_DONOR_COLUMNS = (
    "id, allocation_id, company_id, role, donor_id, donor_name, donor_email, donor_phone, "
    "contribution_amount, is_primary, is_manual, source, needs_review, review_note"
)


def _load_allocation_donors(cur, allocation_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
    """Donor rows per allocation, primary first."""
    out: Dict[int, List[Dict[str, Any]]] = {}
    ids = [int(i) for i in allocation_ids if i is not None]
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        placeholders = ",".join("?" * len(chunk))
        cur.execute(
            f"SELECT {_ALLOC_DONOR_COLUMNS} FROM sponsorship_allocation_donors "
            f"WHERE allocation_id IN ({placeholders}) ORDER BY is_primary DESC, id ASC",
            chunk,
        )
        cols = [c[0] for c in cur.description]
        for r in cur.fetchall():
            row = dict(zip(cols, r))
            row["is_primary"] = bool(row["is_primary"])
            row["is_manual"] = bool(row["is_manual"])
            row["needs_review"] = bool(row["needs_review"])
            out.setdefault(row["allocation_id"], []).append(row)
    return out


def _sync_allocation_from_donors(cur, allocation_id: int) -> None:
    """Mirrors the primary donor into sponsorship_allocations (legacy readers, search, overdue
    alerts) and keeps allocated_amount equal to the sum of contributions."""
    donors = _load_allocation_donors(cur, [allocation_id]).get(allocation_id, [])
    if not donors:
        return
    if not any(d["is_primary"] for d in donors):
        cur.execute("UPDATE sponsorship_allocation_donors SET is_primary = 1 WHERE id = ?", (donors[0]["id"],))
        donors[0]["is_primary"] = True
    primary = next(d for d in donors if d["is_primary"])
    total = round(sum(float(d["contribution_amount"] or 0.0) for d in donors), 2)
    names = [d["donor_name"] for d in donors if d["donor_name"]]
    cur.execute("""
        UPDATE sponsorship_allocations SET
            donor_name = ?, donor_email = ?, donor_phone = ?, donor_id = ?,
            allocated_amount = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        " & ".join(names) if len(names) > 1 else (primary["donor_name"] or ""),
        primary["donor_email"] or "", primary["donor_phone"] or "", primary["donor_id"] or "",
        total, allocation_id,
    ))


def _insert_allocation_donor(cur, allocation_id: int, company_id: str, allocation_type: str,
                             d: AllocationDonorInput, source: str = "manual") -> int:
    email = (d.donor_email or "").strip()
    phone = (d.donor_phone or "").strip()
    if not email and not phone:
        raise HTTPException(status_code=400, detail=f"Donor '{d.donor_name or 'unnamed'}' needs an email or phone number.")
    if email and "@" not in email:
        raise HTTPException(status_code=400, detail=f"'{email}' is not a valid email address.")
    if d.contribution_amount is not None and float(d.contribution_amount) < 0:
        raise HTTPException(status_code=400, detail="Contribution amount cannot be negative.")
    role = (d.role or ("organizer" if allocation_type == "campaign" else "donor")).strip().lower()
    if role not in ("donor", "organizer"):
        raise HTTPException(status_code=400, detail="Donor role must be 'donor' or 'organizer'.")
    donor_id = (d.donor_id or "").strip()
    if email:
        dup = cur.execute(
            "SELECT 1 FROM sponsorship_allocation_donors WHERE allocation_id = ? AND LOWER(donor_email) = LOWER(?)",
            (allocation_id, email)).fetchone()
        if dup:
            raise HTTPException(status_code=400, detail=f"{email} is already on this sponsorship.")
    if d.is_primary:
        cur.execute("UPDATE sponsorship_allocation_donors SET is_primary = 0 WHERE allocation_id = ?", (allocation_id,))
    cur.execute("""
        INSERT INTO sponsorship_allocation_donors (
            allocation_id, company_id, role, donor_id, donor_name, donor_email, donor_phone,
            contribution_amount, is_primary, is_manual, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        allocation_id, company_id, role, donor_id, (d.donor_name or "").strip(), email, phone,
        float(d.contribution_amount or 0.0), 1 if d.is_primary else 0,
        1 if (d.is_manual or donor_id.startswith("manual_")) else 0, source,
    ))
    return cur.lastrowid


@router.get("/allocations/{allocation_id}/donors")
def list_allocation_donors(allocation_id: int):
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        return {"donors": _load_allocation_donors(cur, [allocation_id]).get(allocation_id, [])}
    finally:
        conn.close()


@router.post("/allocations/{allocation_id}/donors")
def add_allocation_donor(allocation_id: int, payload: AllocationDonorInput):
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT company_id, allocation_type FROM sponsorship_allocations WHERE id = ?",
                          (allocation_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Allocation not found.")
        new_id = _insert_allocation_donor(cur, allocation_id, row[0], row[1] or "individual", payload)
        _sync_allocation_from_donors(cur, allocation_id)
        conn.commit()
        log_event("allocation.donor_added", category="allocation", company_id=row[0], allocation_id=allocation_id,
                  allocation_donor_id=new_id, donor=payload.donor_name, donor_email=payload.donor_email,
                  amount=payload.contribution_amount, message=f"Added {payload.donor_name or payload.donor_email} to allocation {allocation_id}")
        invalidate_overdue_cache(row[0])
        return {"status": "success", "allocation_donor_id": new_id,
                "donors": _load_allocation_donors(cur, [allocation_id]).get(allocation_id, [])}
    finally:
        conn.close()


@router.put("/allocation-donors/{allocation_donor_id}")
def update_allocation_donor(allocation_donor_id: int, payload: AllocationDonorUpdate):
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT allocation_id, company_id FROM sponsorship_allocation_donors WHERE id = ?",
                          (allocation_donor_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Donor not found on this sponsorship.")
        allocation_id, comp = row
        fields, values = [], []
        if payload.donor_name is not None:
            fields.append("donor_name = ?"); values.append(payload.donor_name.strip())
        if payload.donor_email is not None:
            email = payload.donor_email.strip()
            if email and "@" not in email:
                raise HTTPException(status_code=400, detail=f"'{email}' is not a valid email address.")
            fields.append("donor_email = ?"); values.append(email)
        if payload.donor_phone is not None:
            fields.append("donor_phone = ?"); values.append(payload.donor_phone.strip())
        if payload.contribution_amount is not None:
            if float(payload.contribution_amount) < 0:
                raise HTTPException(status_code=400, detail="Contribution amount cannot be negative.")
            fields.append("contribution_amount = ?"); values.append(float(payload.contribution_amount))
        if payload.needs_review is not None:
            fields.append("needs_review = ?"); values.append(1 if payload.needs_review else 0)
        if payload.is_primary:
            cur.execute("UPDATE sponsorship_allocation_donors SET is_primary = 0 WHERE allocation_id = ?", (allocation_id,))
            fields.append("is_primary = 1")
        if fields:
            values.append(allocation_donor_id)
            cur.execute(f"UPDATE sponsorship_allocation_donors SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
            check = cur.execute("SELECT donor_email, donor_phone FROM sponsorship_allocation_donors WHERE id = ?",
                                (allocation_donor_id,)).fetchone()
            if not (check[0] or "").strip() and not (check[1] or "").strip():
                raise HTTPException(status_code=400, detail="A donor needs an email or phone number.")
            _sync_allocation_from_donors(cur, allocation_id)
            conn.commit()
            invalidate_overdue_cache(comp)
            log_event("allocation.donor_updated", category="allocation", company_id=comp, allocation_id=allocation_id,
                      allocation_donor_id=allocation_donor_id, changes=payload.dict(exclude_none=True, exclude={"company_id"}),
                      message=f"Updated donor {allocation_donor_id} on allocation {allocation_id}")
        return {"status": "success",
                "donors": _load_allocation_donors(cur, [allocation_id]).get(allocation_id, [])}
    finally:
        conn.close()


@router.delete("/allocation-donors/{allocation_donor_id}")
def remove_allocation_donor(allocation_donor_id: int):
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT allocation_id, company_id FROM sponsorship_allocation_donors WHERE id = ?",
                          (allocation_donor_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Donor not found on this sponsorship.")
        allocation_id, comp = row
        remaining = cur.execute("SELECT COUNT(*) FROM sponsorship_allocation_donors WHERE allocation_id = ?",
                                (allocation_id,)).fetchone()[0]
        if remaining <= 1:
            raise HTTPException(status_code=400, detail="A sponsorship needs at least one donor. Remove the allocation instead.")
        cur.execute("DELETE FROM sponsorship_allocation_donors WHERE id = ?", (allocation_donor_id,))
        log_event("allocation.donor_removed", category="allocation", level="warning", company_id=comp,
                  allocation_id=allocation_id, allocation_donor_id=allocation_donor_id,
                  message=f"Removed donor {allocation_donor_id} from allocation {allocation_id}")
        cur.execute("UPDATE sponsorship_email_queue SET status = 'skipped', error_message = 'Donor removed from sponsorship', "
                    "updated_at = CURRENT_TIMESTAMP WHERE allocation_donor_id = ? AND status = 'pending'", (allocation_donor_id,))
        _sync_allocation_from_donors(cur, allocation_id)
        conn.commit()
        invalidate_overdue_cache(comp)
        return {"status": "success",
                "donors": _load_allocation_donors(cur, [allocation_id]).get(allocation_id, [])}
    finally:
        conn.close()


@router.post("/allocations")
def create_allocation(payload: AllocationCreateRequest):
    """
    Allocates a beneficiary to a donor or a campaign.
    Enforces strict 1-to-1 constraint: A beneficiary cannot be assigned to more than 1 entity.
    Requires at least one contact method (email or phone).
    """
    comp = (payload.company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        
        cur.execute("SELECT id, name, status FROM sponsorship_beneficiaries WHERE id = ?", (payload.beneficiary_id,))
        b_row = cur.fetchone()
        if not b_row:
            raise HTTPException(status_code=404, detail="Beneficiary not found.")

        cur.execute("SELECT id, donor_name, donor_email, campaign_name, allocation_type FROM sponsorship_allocations WHERE beneficiary_id = ?", (payload.beneficiary_id,))
        existing_alloc = cur.fetchone()
        if existing_alloc:
            target_label = existing_alloc[3] if existing_alloc[4] == 'campaign' and existing_alloc[3] else existing_alloc[1]
            raise HTTPException(
                status_code=400,
                detail=f"Beneficiary '{b_row[1]}' is already allocated to {target_label} ({existing_alloc[2]}). Beneficiaries can only be assigned to 1 entity."
            )

        alloc_type = (payload.allocation_type or "individual").strip().lower()
        b_company = cur.execute("SELECT company_id FROM sponsorship_beneficiaries WHERE id = ?",
                                (payload.beneficiary_id,)).fetchone()[0]
        if comp != (b_company or "").strip().lower():
            raise HTTPException(status_code=404, detail="Beneficiary not found for this charity.")

        # Several donors may share one sponsorship; the legacy single-donor fields still work.
        donors_in = list(payload.donors or [])
        if not donors_in:
            donors_in = [AllocationDonorInput(
                donor_id=payload.donor_id, donor_name=payload.donor_name, donor_email=payload.donor_email,
                donor_phone=payload.donor_phone, contribution_amount=payload.allocated_amount, is_primary=True,
            )]
        for d in donors_in:
            if not (d.donor_email or "").strip() and not (d.donor_phone or "").strip():
                raise HTTPException(
                    status_code=400,
                    detail=f"At least one contact method (Email or Phone number) is mandatory for '{d.donor_name or 'each donor'}'."
                )
        if not any(d.is_primary for d in donors_in):
            donors_in[0].is_primary = True
        primary = next(d for d in donors_in if d.is_primary)
        d_email = (primary.donor_email or "").strip()
        d_phone = (primary.donor_phone or "").strip()

        today = datetime.date.today()
        start_d = payload.start_date.strip() if payload.start_date else today.isoformat()
        end_d = payload.end_date.strip() if payload.end_date else (today + datetime.timedelta(days=365)).isoformat()

        adm_notes = payload.admin_notes.strip() if payload.admin_notes else ""
        if payload.is_exceptional:
            if "[Exceptional Allocation]" not in adm_notes:
                adm_notes = f"[Exceptional Allocation] {adm_notes}".strip()

        cur.execute("""
            INSERT INTO sponsorship_allocations (
                company_id, beneficiary_id, donor_email, donor_phone, donor_name, donor_id,
                allocation_type, campaign_name, community_name,
                allocated_amount, start_date, end_date, renewal_status, renewal_count,
                communication_status, admin_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 0, 'Profile Pending', ?)
        """, (
            comp,
            payload.beneficiary_id,
            d_email,
            d_phone,
            (primary.donor_name or "").strip() or ("Campaign Allocation" if alloc_type == 'campaign' else "Anonymous Donor"),
            (primary.donor_id or "").strip(),
            alloc_type,
            payload.campaign_name.strip() if payload.campaign_name else None,
            payload.community_name.strip() if payload.community_name else None,
            float(payload.allocated_amount or 0.0),
            start_d,
            end_d,
            adm_notes
        ))
        alloc_id = cur.lastrowid

        for d in donors_in:
            if d.contribution_amount in (None, 0) and len(donors_in) == 1:
                d.contribution_amount = float(payload.allocated_amount or 0.0)
            _insert_allocation_donor(cur, alloc_id, comp, alloc_type, d)
        _sync_allocation_from_donors(cur, alloc_id)

        cur.execute("UPDATE sponsorship_beneficiaries SET status = 'Allocated', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (payload.beneficiary_id,))

        conn.commit()
        invalidate_overdue_cache(comp)
        log_event("allocation.created", category="allocation", company_id=comp, allocation_id=alloc_id,
                  beneficiary_id=payload.beneficiary_id, allocation_type=alloc_type,
                  donors=[{"name": d.donor_name, "email": d.donor_email, "amount": d.contribution_amount} for d in donors_in],
                  message=f"Allocated beneficiary {b_row[1]}")
        donor_labels = [d.donor_name or d.donor_email or d.donor_phone for d in donors_in]
        assigned_to_label = payload.campaign_name if alloc_type == 'campaign' and payload.campaign_name else " & ".join(donor_labels)
        return {
            "status": "success",
            "message": f"Successfully allocated {b_row[1]} to {assigned_to_label}!",
            "allocation_id": alloc_id,
            "start_date": start_d,
            "end_date": end_d
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.put("/allocations/{allocation_id}")
def update_allocation(allocation_id: int, payload: AllocationUpdateRequest):
    """Updates allocation notes, amount, or communication status."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        fields = []
        values = []
        if payload.allocated_amount is not None:
            fields.append("allocated_amount = ?")
            values.append(float(payload.allocated_amount))
        if payload.communication_status is not None:
            fields.append("communication_status = ?")
            values.append(payload.communication_status.strip())
        if payload.admin_notes is not None:
            fields.append("admin_notes = ?")
            values.append(payload.admin_notes.strip())
        if payload.donor_email is not None:
            fields.append("donor_email = ?")
            values.append(payload.donor_email.strip())
        if payload.donor_phone is not None:
            fields.append("donor_phone = ?")
            values.append(payload.donor_phone.strip())
        if payload.donor_name is not None:
            fields.append("donor_name = ?")
            values.append(payload.donor_name.strip())
        if payload.campaign_name is not None:
            fields.append("campaign_name = ?")
            values.append(payload.campaign_name.strip())
        if payload.community_name is not None:
            fields.append("community_name = ?")
            values.append(payload.community_name.strip())

        if fields:
            values.append(allocation_id)
            cur.execute(f"UPDATE sponsorship_allocations SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
            # Legacy single-contact edits apply to the primary donor row.
            d_fields, d_values = [], []
            for col in ("donor_email", "donor_phone", "donor_name"):
                val = getattr(payload, col)
                if val is not None:
                    d_fields.append(f"{col} = ?"); d_values.append(val.strip())
            if d_fields:
                d_values.append(allocation_id)
                cur.execute(f"UPDATE sponsorship_allocation_donors SET {', '.join(d_fields)}, updated_at = CURRENT_TIMESTAMP "
                            "WHERE allocation_id = ? AND is_primary = 1", d_values)
            conn.commit()
        return {"status": "success", "message": "Allocation updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/allocations/{allocation_id}/renew")
def renew_allocation(allocation_id: int):
    """Extends sponsorship cycle by +12 months from existing end date, increments renewal count, and resets status to active."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, start_date, end_date, renewal_count, created_at, donor_name, donor_email FROM sponsorship_allocations WHERE id = ?", (allocation_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Allocation not found.")

        today = datetime.date.today()
        current_end = row["end_date"]
        if current_end:
            try:
                base_dt = datetime.datetime.strptime(current_end[:10], "%Y-%m-%d").date()
                if base_dt < today:
                    base_dt = today
            except Exception:
                base_dt = today
        else:
            base_dt = today

        new_end = (base_dt + datetime.timedelta(days=365)).isoformat()
        new_count = (row["renewal_count"] or 0) + 1

        cur.execute("""
            UPDATE sponsorship_allocations
            SET end_date = ?,
                renewal_count = ?,
                renewal_status = 'renewed',
                last_renewed_at = CURRENT_TIMESTAMP,
                communication_status = 'Renewal Active',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (new_end, new_count, allocation_id))
        conn.commit()
        return {
            "status": "success",
            "message": f"Sponsorship successfully renewed for Year {new_count + 1} (expires {new_end})!",
            "allocation_id": allocation_id,
            "end_date": new_end,
            "renewal_count": new_count,
            "sponsorship_year": f"Year {new_count + 1}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.put("/allocations/{allocation_id}/dates")
def update_allocation_dates(allocation_id: int, payload: AllocationDatesUpdateRequest):
    """Manually updates start date, end date, and renewal status of an allocation."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE sponsorship_allocations
            SET start_date = ?,
                end_date = ?,
                renewal_status = COALESCE(?, renewal_status),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (payload.start_date.strip(), payload.end_date.strip(), payload.renewal_status, allocation_id))
        conn.commit()
        return {"status": "success", "message": "Allocation dates updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.delete("/allocations/{allocation_id}")
def delete_allocation(allocation_id: int):
    """Deletes an allocation and resets the beneficiary status to Unallocated."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("SELECT beneficiary_id, company_id FROM sponsorship_allocations WHERE id = ?", (allocation_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Allocation not found.")
        
        b_id, c_id = row[0], row[1]
        cur.execute("DELETE FROM sponsorship_allocation_donors WHERE allocation_id = ?", (allocation_id,))
        cur.execute("UPDATE sponsorship_email_queue SET status = 'skipped', error_message = 'Allocation removed', "
                    "updated_at = CURRENT_TIMESTAMP WHERE allocation_id = ? AND status = 'pending'", (allocation_id,))
        cur.execute("DELETE FROM sponsorship_allocations WHERE id = ?", (allocation_id,))
        cur.execute("UPDATE sponsorship_beneficiaries SET status = 'Unallocated', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (b_id,))
        conn.commit()
        invalidate_overdue_cache(c_id)
        log_event("allocation.deleted", category="allocation", level="warning", company_id=c_id,
                  allocation_id=allocation_id, beneficiary_id=b_id, message=f"Allocation {allocation_id} released")
        return {"status": "success", "message": "Allocation removed and beneficiary freed successfully."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ==========================================
# 7. MULTI-YEAR FEEDBACKS TIMELINE
# ==========================================

@router.get("/beneficiaries/{beneficiary_id}/feedbacks")
def get_feedbacks(beneficiary_id: int):
    """Returns chronological multi-year feedback records for a beneficiary."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, beneficiary_id, allocation_id, company_id, feedback_title,
                   feedback_date, year_label, report_link, video_link, donor_folder_link,
                   notes, progress_summary, created_at
            FROM sponsorship_feedbacks
            WHERE beneficiary_id = ?
            ORDER BY feedback_date DESC, created_at DESC
        """, (beneficiary_id,))
        rows = [dict(r) for r in cur.fetchall()]
        return {"beneficiary_id": beneficiary_id, "feedbacks": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/beneficiaries/{beneficiary_id}/feedbacks")
def create_feedback(beneficiary_id: int, payload: FeedbackCreateRequest):
    """Adds a new multi-year annual feedback report entry to the timeline."""
    comp = (payload.company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM sponsorship_allocations WHERE beneficiary_id = ?", (beneficiary_id,))
        alloc_row = cur.fetchone()
        alloc_id = alloc_row[0] if alloc_row else None

        cur.execute("""
            INSERT INTO sponsorship_feedbacks (
                beneficiary_id, allocation_id, company_id, feedback_title,
                feedback_date, year_label, report_link, video_link, donor_folder_link,
                notes, progress_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            beneficiary_id,
            alloc_id,
            comp,
            payload.feedback_title.strip(),
            payload.feedback_date.strip(),
            payload.year_label.strip() if payload.year_label else "Year 1",
            payload.report_link.strip() if payload.report_link else "",
            payload.video_link.strip() if payload.video_link else "",
            payload.donor_folder_link.strip() if payload.donor_folder_link else "",
            payload.notes.strip() if payload.notes else "",
            payload.progress_summary.strip() if payload.progress_summary else ""
        ))
        fb_id = cur.lastrowid
        conn.commit()
        return {"status": "success", "message": "Annual feedback report logged successfully!", "id": fb_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.delete("/feedbacks/{feedback_id}")
def delete_feedback(feedback_id: int):
    """Deletes a feedback record."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM sponsorship_feedbacks WHERE id = ?", (feedback_id,))
        conn.commit()
        return {"status": "success", "message": "Feedback deleted successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ==========================================
# 8. MICROSOFT 365 / OUTLOOK OAUTH & GRAPH API
# ==========================================

def _get_outlook_auth_row(company_id: str):
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM sponsorship_outlook_auth WHERE company_id = ?", (company_id,))
        return cur.fetchone()
    finally:
        conn.close()

def _get_valid_graph_token(company_id: str) -> str:
    """Returns a valid Microsoft Graph access token, refreshing if necessary."""
    auth = _get_outlook_auth_row(company_id)
    if not auth or not auth["refresh_token"]:
        raise HTTPException(
            status_code=400,
            detail="Microsoft 365 / Outlook account is not connected. Please connect via OAuth 2.0 in Settings."
        )

    access_token = auth["access_token"]
    token_expiry = auth["token_expiry"]
    now_ts = datetime.datetime.utcnow().timestamp()

    is_expired = True
    if token_expiry:
        try:
            exp_ts = datetime.datetime.fromisoformat(str(token_expiry)).timestamp()
            if exp_ts - now_ts > 60:
                is_expired = False
        except Exception:
            is_expired = True

    if not is_expired and access_token:
        return access_token

    tenant_id = auth["tenant_id"] or "common"
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    client_sec = decrypt_string(auth["client_secret"]) if auth["client_secret"] else ""
    res = requests.post(token_url, data={
        "client_id": auth["client_id"],
        "client_secret": client_sec,
        "refresh_token": auth["refresh_token"],
        "grant_type": "refresh_token",
        "scope": "https://graph.microsoft.com/.default offline_access"
    }, timeout=15)

    if res.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Failed to refresh Microsoft Graph access token: {res.text}")

    data = res.json()
    new_access_token = data.get("access_token")
    new_refresh_token = data.get("refresh_token", auth["refresh_token"])
    expires_in = data.get("expires_in", 3600)
    new_expiry = (datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_in)).isoformat()

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE sponsorship_outlook_auth 
            SET access_token = ?, refresh_token = ?, token_expiry = ?, updated_at = CURRENT_TIMESTAMP
            WHERE company_id = ?
        """, (new_access_token, new_refresh_token, new_expiry, company_id))
        conn.commit()
    finally:
        conn.close()

    return new_access_token

@router.get("/outlook/status")
def get_outlook_status(company_id: Optional[str] = Query("rethink")):
    """Returns Microsoft 365 / Outlook connection status, connected email, and subscription state."""
    comp = (company_id or "rethink").strip().lower()
    from backend.api.mailbox import _owner, provider, is_connected, sender_address
    if provider(_owner(comp)) == "gmail":  # this charity sends with Gmail: same shape, so every screen's "connected" check works
        return {"provider": "gmail", "connected": is_connected(_owner(comp)), "connected_email": sender_address(_owner(comp)),
                "client_id_set": True, "tenant_id": None, "subscription_active": False, "subscription_expiration": None}
    auth = _get_outlook_auth_row(comp)
    if not auth:
        return {
            "connected": False,
            "connected_email": None,
            "client_id_set": False,
            "tenant_id": "common",
            "subscription_active": False,
            "subscription_expiration": None
        }

    # If account is connected, automatically verify & auto-renew subscription if expiring
    if auth["refresh_token"]:
        try:
            ensure_outlook_subscription(comp)
            auth = _get_outlook_auth_row(comp)
        except Exception:
            pass

    return {
        "connected": bool(auth["refresh_token"]),
        "connected_email": auth["connected_email"],
        "client_id_set": bool(auth["client_id"]),
        "client_id": auth["client_id"][:12] + "..." if auth["client_id"] else None,
        "tenant_id": auth["tenant_id"] or "common",
        "subscription_active": bool(auth["subscription_expiration"]),
        "subscription_expiration": auth["subscription_expiration"]
    }

@router.post("/outlook/save-credentials")
def save_outlook_credentials(payload: OutlookCredentialsRequest, current_user = Depends(require_super_admin)):
    """Saves Microsoft Azure App Client ID, Secret, and Tenant ID."""
    comp = (payload.company_id or "rethink").strip().lower()
    tenant = (payload.tenant_id or "common").strip()
    raw_secret = payload.client_secret.strip() if payload.client_secret else ""
    encrypted_secret = encrypt_string(raw_secret) if raw_secret else ""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sponsorship_outlook_auth (company_id, client_id, client_secret, tenant_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(company_id) DO UPDATE SET
                client_id = excluded.client_id,
                client_secret = excluded.client_secret,
                tenant_id = excluded.tenant_id,
                updated_at = CURRENT_TIMESTAMP
        """, (comp, payload.client_id.strip(), encrypted_secret, tenant))
        conn.commit()
        log_event("outlook.credentials_saved", category="outlook", company_id=comp, actor=current_user.get("email"),
                  message=f"Azure app credentials updated for {comp}")
        return {"status": "success", "message": "Microsoft 365 credentials saved successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.get("/outlook/auth-url")
def get_outlook_auth_url(company_id: Optional[str] = Query("rethink"), redirect_uri: Optional[str] = Query(None), current_user = Depends(get_current_user)):
    """Generates the Microsoft 365 OAuth 2.0 authorization URL."""
    comp = (company_id or "rethink").strip().lower()
    auth = _get_outlook_auth_row(comp)
    if not auth or not auth["client_id"]:
        raise HTTPException(status_code=400, detail="Microsoft Azure Client ID not configured. Please save credentials first.")

    r_uri = redirect_uri if isinstance(redirect_uri, str) and redirect_uri else "http://localhost:5173/sponsorship-tracker"
    scopes = "https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/User.Read offline_access"
    tenant = auth["tenant_id"] or "common"

    auth_url = (
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?"
        f"client_id={auth['client_id']}&"
        f"redirect_uri={urllib.parse.quote(str(r_uri))}&"
        f"response_type=code&"
        f"response_mode=query&"
        f"scope={urllib.parse.quote(str(scopes))}&"
        f"state={comp}&"
        f"prompt=select_account"
    )
    return {"auth_url": auth_url}

@router.post("/outlook/exchange-token")
def exchange_outlook_token(payload: OutlookExchangeTokenRequest, current_user = Depends(require_super_admin)):
    """Exchanges authorization code for tokens and retrieves connected Microsoft 365 email."""
    comp = (payload.company_id or "rethink").strip().lower()
    auth = _get_outlook_auth_row(comp)
    if not auth or not auth["client_id"] or not auth["client_secret"]:
        raise HTTPException(status_code=400, detail="Microsoft Azure credentials missing.")

    tenant = auth["tenant_id"] or "common"
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    client_sec = decrypt_string(auth["client_secret"])

    res = requests.post(token_url, data={
        "code": payload.code.strip(),
        "client_id": auth["client_id"],
        "client_secret": client_sec,
        "redirect_uri": payload.redirect_uri.strip(),
        "grant_type": "authorization_code",
        "scope": "https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/User.Read offline_access"
    }, timeout=15)

    if res.status_code != 200:
        log_event("outlook.connect_failed", category="outlook", level="error", company_id=comp,
                  detail=res.text[:300], message=f"Microsoft 365 token exchange failed for {comp}")
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {res.text}")

    token_data = res.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)
    token_expiry = (datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_in)).isoformat()

    # Get user profile email from Microsoft Graph
    email = "Connected Microsoft 365 Account"
    try:
        user_res = requests.get("https://graph.microsoft.com/v1.0/me", headers={
            "Authorization": f"Bearer {access_token}"
        }, timeout=10)
        if user_res.status_code == 200:
            u_data = user_res.json()
            email = u_data.get("mail") or u_data.get("userPrincipalName") or email
    except Exception:
        pass

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE sponsorship_outlook_auth SET
                access_token = ?,
                refresh_token = COALESCE(?, refresh_token),
                token_expiry = ?,
                connected_email = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE company_id = ?
        """, (access_token, refresh_token, token_expiry, email, comp))
        conn.commit()
        log_event("outlook.connected", category="outlook", company_id=comp, actor=current_user.get("email"),
                  mailbox=email, message=f"Microsoft 365 mailbox {email} connected for {comp}")
        return {"status": "success", "connected_email": email}
    finally:
        conn.close()

@router.post("/outlook/disconnect")
def disconnect_outlook(company_id: Optional[str] = Query("rethink"), current_user = Depends(require_super_admin)):
    """Disconnects Microsoft 365 / Outlook account."""
    comp = (company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE sponsorship_outlook_auth SET
                access_token = NULL,
                refresh_token = NULL,
                token_expiry = NULL,
                connected_email = NULL,
                subscription_id = NULL,
                subscription_expiration = NULL
            WHERE company_id = ?
        """, (comp,))
        conn.commit()
        log_event("outlook.disconnected", category="outlook", level="warning", company_id=comp,
                  actor=current_user.get("email"), message=f"Microsoft 365 disconnected for {comp}")
        return {"status": "success", "message": "Microsoft 365 account disconnected."}
    finally:
        conn.close()

# ==========================================
# 8b. SERVER-SIDE EMAIL RENDERING (one personalised email per donor)
# ==========================================

_DEFAULT_THEME_FOR_COMPANY = {"rethink": "rethink", "iqra": "iqra"}
_STATUS_FOR_TEMPLATE = {"video_update": "Video Sent", "end_year_feedback": "Feedback Sent"}


def _resolve_theme(allocation_company: str, requested_theme: Optional[str]) -> str:
    theme = (requested_theme or "").strip().lower() or _DEFAULT_THEME_FOR_COMPANY.get(allocation_company, allocation_company)
    if _owner_company(theme) != allocation_company:
        raise HTTPException(status_code=400, detail=f"Theme '{theme}' cannot be used for a {allocation_company} sponsorship.")
    return theme


def _get_template(cur, theme: str, template_type: str) -> Dict[str, str]:
    """Template for this theme only; never falls back to another charity's templates.
    If missing from database, auto-populates from defaults or falls back gracefully."""
    theme_key = (theme or "rethink").strip().lower()
    row = cur.execute(
        "SELECT subject, body_html FROM sponsorship_email_templates WHERE LOWER(company_id) = ? AND template_type = ?",
        (theme_key, template_type)).fetchone()
    if row and (row[0] or row[1]):
        return {"subject": row[0] or "", "body_html": row[1] or ""}

    # 1. Look in DEFAULT_TEMPLATES_BY_CHARITY for this theme or rethink
    defaults_dict = globals().get("DEFAULT_TEMPLATES_BY_CHARITY", {})
    theme_defaults = defaults_dict.get(theme_key) or defaults_dict.get("rethink") or []
    default_tpl = next((dt for dt in theme_defaults if dt.get("template_type") == template_type), None)
    if default_tpl:
        try:
            cur.execute("""
                INSERT INTO sponsorship_email_templates (company_id, template_type, subject, body_html)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(company_id, template_type) DO UPDATE SET subject = excluded.subject, body_html = excluded.body_html
            """, (theme_key, default_tpl["template_type"], default_tpl["subject"], default_tpl["body_html"]))
        except Exception:
            pass
        return {"subject": default_tpl["subject"] or "", "body_html": default_tpl["body_html"] or ""}

    # 2. Fall back to any active template for this theme
    fallback_row = cur.execute(
        "SELECT subject, body_html FROM sponsorship_email_templates WHERE LOWER(company_id) = ? ORDER BY id ASC LIMIT 1",
        (theme_key,)).fetchone()
    if fallback_row and (fallback_row[0] or fallback_row[1]):
        return {"subject": fallback_row[0] or "", "body_html": fallback_row[1] or ""}

    # 3. Last-resort fallback wrapper so it NEVER crashes with 404
    wrap_fn = globals().get("_wrap_email_html_template")
    fallback_subject = f"Sponsorship Update | {theme_key.title()}"
    fallback_body = """<p style="margin: 0 0 12px 0;">Dear {First_Name},</p>
<p style="margin: 0 0 12px 0;">Thank you for your generous sponsorship and support for <strong>{beneficiary_name}</strong>.</p>
<p style="margin: 0 0 12px 0;">{message_body}</p>"""
    fallback_html = wrap_fn(fallback_subject, fallback_body, theme_key) if wrap_fn else f"<html><body>{fallback_body}</body></html>"
    return {"subject": fallback_subject, "body_html": fallback_html}


def _allocation_cycle(row: Dict[str, Any]) -> Dict[str, Any]:
    today = datetime.date.today()
    start = row.get("start_date") or (str(row.get("created_at") or "")[:10] or today.isoformat())
    end = row.get("end_date")
    if not end:
        try:
            end = (datetime.datetime.strptime(start[:10], "%Y-%m-%d").date() + datetime.timedelta(days=365)).isoformat()
        except Exception:
            end = (today + datetime.timedelta(days=365)).isoformat()
    try:
        days_remaining = (datetime.datetime.strptime(end[:10], "%Y-%m-%d").date() - today).days
    except Exception:
        days_remaining = None
    return {"start_date": start, "end_date": end, "days_remaining": days_remaining,
            "sponsorship_year": f"Year {(row.get('renewal_count') or 0) + 1}"}


def _load_render_context(cur, allocation_id: int, allocation_donor_id: Optional[int]) -> Dict[str, Any]:
    cur.execute("""
        SELECT a.*, b.name AS beneficiary_name, b.sponsorship_type, b.location, b.project_code,
               b.profile_link, b.video_link, b.donor_folder_link
        FROM sponsorship_allocations a JOIN sponsorship_beneficiaries b ON b.id = a.beneficiary_id
        WHERE a.id = ?
    """, (allocation_id,))
    cols = [c[0] for c in cur.description]
    r = cur.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Allocation not found.")
    alloc = dict(zip(cols, r))
    donors = _load_allocation_donors(cur, [allocation_id]).get(allocation_id, [])
    if not donors:
        raise HTTPException(status_code=400, detail="This sponsorship has no donors to email.")
    if allocation_donor_id is None:
        donor = next((d for d in donors if d["is_primary"]), donors[0])
    else:
        donor = next((d for d in donors if d["id"] == int(allocation_donor_id)), None)
        if donor is None:
            raise HTTPException(status_code=404, detail="That donor is not on this sponsorship.")
    return {"allocation": alloc, "donor": donor, "donors": donors, "cycle": _allocation_cycle(alloc)}


def _template_variables(ctx: Dict[str, Any], subject_template: str) -> Dict[str, str]:
    alloc, donor, cycle = ctx["allocation"], ctx["donor"], ctx["cycle"]
    is_organizer = donor.get("role") == "organizer"
    full_name = (donor.get("donor_name") or "").strip() or (
        alloc.get("campaign_name") if is_organizer else "") or ("Campaign Lead" if is_organizer else "Generous Donor")
    first_name = full_name.split(" ")[0] if full_name else full_name
    co_sponsors = [(d.get("donor_name") or "").split(" ")[0] for d in ctx["donors"]
                   if d["id"] != donor["id"] and (d.get("donor_name") or "").strip()]
    folder = alloc.get("donor_folder_link") or alloc.get("profile_link") or "#"
    amount = float(donor.get("contribution_amount") or 0.0)
    return {
        "first_name": first_name,
        "last_name": " ".join(full_name.split()[1:]),
        "donor_name": full_name,
        "email": donor.get("donor_email") or "",
        "recipient_email": donor.get("donor_email") or "",
        "contribution_amount": f"{amount:,.2f}".rstrip("0").rstrip(".") if amount else "",
        "co_sponsors": ", ".join(co_sponsors),
        "beneficiary_name": alloc.get("beneficiary_name") or "Beneficiary",
        "beneficiary_first_name": ((alloc.get("beneficiary_name") or "").split() or ["Beneficiary"])[0],
        "beneficiary_last_name": " ".join((alloc.get("beneficiary_name") or "").split()[1:]),
        "sponsorship_type": alloc.get("sponsorship_type") or "Sponsorship",
        "sponsorship_year": cycle["sponsorship_year"],
        "renewal_deadline": cycle["end_date"] or "N/A",
        "days_remaining": f"{cycle['days_remaining']} days" if cycle["days_remaining"] is not None else "",
        "location": alloc.get("location") or "",
        "project_code": alloc.get("project_code") or "",
        "donor_folder_link": folder,
        "folder_link": folder,
        "profile_link": alloc.get("profile_link") or "#",
        "video_link": alloc.get("video_link") or "#",
        "report_link": alloc.get("profile_link") or "#",
        "campaign_name": alloc.get("campaign_name") or "Campaign",
        "community_name": alloc.get("community_name") or "Community",
        "subject": subject_template or "Sponsorship Update",
        "message_body": "Thank you for your generous sponsorship and support.",
    }


_PLACEHOLDER_RE = re.compile(r"\{\{?\s*([A-Za-z_]+)\s*\}?\}")


def _render_text(text: str, variables: Dict[str, str]) -> str:
    """Replaces {name} / {{name}} (case-insensitive). Unknown placeholders are left untouched."""
    def repl(m):
        key = m.group(1).lower()
        return variables[key] if key in variables else m.group(0)
    return _PLACEHOLDER_RE.sub(repl, text or "")


def render_email_for_donor(cur, allocation_id: int, allocation_donor_id: Optional[int], template_type: str,
                           theme: Optional[str], subject_template: Optional[str] = None,
                           body_template: Optional[str] = None,
                           custom_variables: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    ctx = _load_render_context(cur, allocation_id, allocation_donor_id)
    comp = _owner_company(ctx["allocation"]["company_id"])
    theme = _resolve_theme(comp, theme)
    if subject_template is None or body_template is None:
        tpl = _get_template(cur, theme, template_type)
        subject_template = tpl["subject"] if subject_template is None else subject_template
        body_template = tpl["body_html"] if body_template is None else body_template
    variables = _template_variables(ctx, subject_template)
    if custom_variables:
        for k, val in custom_variables.items():
            if val is not None and str(val).strip() != "":
                variables[k.lower()] = str(val).strip()
    subject = _render_text(subject_template, variables)
    variables["subject"] = subject
    unresolved = sorted({m.group(1) for m in _PLACEHOLDER_RE.finditer(subject + body_template)
                         if m.group(1).lower() not in {k.lower() for k, val in variables.items() if val not in (None, "")}})

    # Check for multiple beneficiaries for this recipient
    allocs = []
    donor_em = (ctx["donor"].get("donor_email") or "").strip().lower()
    if donor_em:
        try:
            from backend.api.donor_email import donor_sponsorships
            allocs = donor_sponsorships(comp, donor_em)
        except Exception:
            pass

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
    } for a in allocs] if allocs else []

    return {
        "company_id": comp,
        "theme": theme,
        "template_type": template_type,
        "allocation_donor_id": ctx["donor"]["id"],
        "recipient_email": ctx["donor"].get("donor_email") or "",
        "recipient_name": variables["donor_name"],
        "subject": subject,
        "body_html": _render_text(body_template, variables),
        "unresolved_placeholders": unresolved,
        "variables": variables,
        "sponsorships": sponsorships_data,
        "has_multiple_beneficiaries": len(sponsorships_data) > 1,
        "beneficiaries_count": len(sponsorships_data),
        "donors": [{"id": d["id"], "donor_name": d["donor_name"], "donor_email": d["donor_email"],
                    "role": d["role"], "is_primary": d["is_primary"],
                    "contribution_amount": d["contribution_amount"]} for d in ctx["donors"]],
    }


@router.post("/email/preview")
def preview_email(payload: EmailPreviewRequest):
    """Renders exactly what one donor would receive (same code path as sending)."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        out = render_email_for_donor(cur, payload.allocation_id, payload.allocation_donor_id,
                                     payload.template_type or "profile_intro", payload.company_id,
                                     payload.subject_template, payload.body_template,
                                     payload.custom_variables)
        conn.commit()
        if isinstance(out, dict) and out.get("body_html") and out.get("recipient_email"):
            from backend.api.unsubscribe import add_footer, is_unsubscribed  # the Unsubscribe button, as sent
            out["body_html"] = add_footer(out["body_html"], out.get("company_id") or payload.company_id, out["recipient_email"])
            out["unsubscribed"] = is_unsubscribed(out.get("company_id") or payload.company_id, out["recipient_email"])
        return out
    finally:
        conn.close()


def _public_base_url(request: Request) -> str:
    base_url = str(request.base_url).rstrip('/')
    forwarded_proto = request.headers.get("x-forwarded-proto", "http")
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
    if forwarded_host:
        base_url = f"{forwarded_proto}://{forwarded_host}".rstrip('/')
    return base_url


def _prepare_outgoing_html(raw_body: str, tracking_pixel_url: str, company_id: Optional[str] = None,
                           recipient_email: Optional[str] = None, tracking_id: Optional[str] = None) -> str:
    pixel = (f'<div style="display:none;max-height:0px;overflow:hidden;"><img src="{tracking_pixel_url}" width="1" height="1" '
             f'style="display:none;width:1px;height:1px;border:0;outline:none;" alt="" /></div>')
    body = re.sub(r'src=["\']data:image/[^;]+;base64,[^"\']+["\']', f'src="{_RETHINK_EMAIL_LOGO_URI}"', (raw_body or "").strip())
    if "alt=\"Sisters' Project\"" in body:
        body = re.sub(r'(<img[^>]*alt="Sisters\' Project"[^>]*src=")[^"]*(")', r'\1' + _SP_LOGO_URI + r'\2', body)
    if "alt=\"IQRA\"" in body:
        body = re.sub(r'(<img[^>]*alt="IQRA"[^>]*src=")[^"]*(")', r'\1' + _IQRA_EMAIL_LOGO_URI + r'\2', body)
    if company_id and recipient_email:  # the Unsubscribe button (backend/api/unsubscribe.py)
        from backend.api.unsubscribe import add_footer
        body = add_footer(body, company_id, recipient_email, tracking_id)
    return body.replace("</body>", f"{pixel}</body>") if "</body>" in body else f"{body}{pixel}"


def deliver_rendered_email(rendered: Dict[str, Any], allocation_id: int, base_url: str) -> Dict[str, Any]:
    """Sends one rendered email from the allocation's own charity mailbox and logs it against that donor."""
    comp = rendered["company_id"]
    to_email = (rendered["recipient_email"] or "").strip()
    log_ctx = dict(category="email", company_id=comp, allocation_id=allocation_id,
                   allocation_donor_id=rendered["allocation_donor_id"], template=rendered["template_type"],
                   theme=rendered["theme"], recipient=to_email, recipient_name=rendered["recipient_name"],
                   subject=rendered["subject"])
    if not to_email or "@" not in to_email:
        log_event("email.skipped", level="warning", message=f"No email for {rendered['recipient_name']}", **log_ctx)
        return {"allocation_donor_id": rendered["allocation_donor_id"], "recipient_email": to_email,
                "recipient_name": rendered.get("recipient_name", ""), "status": "skipped",
                "detail": "Donor has no email address"}
    if rendered["unresolved_placeholders"]:
        log_event("email.failed", level="error", message="Unknown placeholders in template",
                  placeholders=rendered["unresolved_placeholders"], **log_ctx)
        return {"allocation_donor_id": rendered["allocation_donor_id"], "recipient_email": to_email,
                "recipient_name": rendered.get("recipient_name", ""), "status": "failed",
                "detail": "Unknown placeholders: " + ", ".join(rendered["unresolved_placeholders"])}
    from backend.api.unsubscribe import is_unsubscribed
    if is_unsubscribed(comp, to_email):
        log_event("email.skipped", level="warning", message=f"{to_email} has unsubscribed - not emailed", **log_ctx)
        return {"allocation_donor_id": rendered["allocation_donor_id"], "recipient_email": to_email,
                "recipient_name": rendered.get("recipient_name", ""), "status": "skipped",
                "detail": "Unsubscribed from emails"}
    from backend.api.mailbox import is_connected, provider, send_email
    if not is_connected(comp):
        raise HTTPException(status_code=400, detail=f"{comp.title()}'s {'Gmail' if provider(comp) == 'gmail' else 'Microsoft 365'} mailbox isn't connected - connect it in Email > Mailbox.")
    tracking_id = str(uuid.uuid4())
    html = _prepare_outgoing_html(rendered["body_html"], f"{base_url}/api/tracker/email-tracking/pixel/{tracking_id}",
                                  comp, to_email, tracking_id)
    sent = send_email(comp, [(to_email, rendered["recipient_name"])], rendered["subject"].strip(), html)
    sender_email = sent.get("sender") or "me"
    if not sent["ok"]:
        log_event("email.failed", level="error", message=f"Send failed ({sent.get('http_status')}) to {to_email}",
                  http_status=sent.get("http_status"), detail=sent["detail"][:300], mailbox=sender_email, **log_ctx)
        return {"allocation_donor_id": rendered["allocation_donor_id"], "recipient_email": to_email,
                "recipient_name": rendered.get("recipient_name", ""), "status": "failed", "detail": sent["detail"][:300]}

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sponsorship_communications (
                allocation_id, allocation_donor_id, template_type, company_id, direction, message_id, thread_id,
                subject, body, sender_email, recipient_email, tracking_id, delivery_status, open_count, sent_at
            ) VALUES (?, ?, ?, ?, 'outbound', ?, ?, ?, ?, ?, ?, ?, 'delivered', 0, CURRENT_TIMESTAMP)
        """, (allocation_id, rendered["allocation_donor_id"], rendered["template_type"], comp,
              sent.get("message_id") or f"graph_{int(time.time()*1000)}_{rendered['allocation_donor_id']}",
              sent.get("thread_id") or "", rendered["subject"].strip(),
              rendered["body_html"], sender_email, to_email, tracking_id))
        comm_id = cur.lastrowid
        cur.execute("""
            UPDATE sponsorship_allocations SET communication_status = ?, last_contacted_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (_STATUS_FOR_TEMPLATE.get(rendered["template_type"], "Profile Sent"), allocation_id))
        cur.execute("""
            UPDATE sponsorship_email_queue SET status = 'sent', sent_comm_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE allocation_donor_id = ? AND template_type = ? AND status = 'pending'
        """, (comm_id, rendered["allocation_donor_id"], rendered["template_type"]))
        conn.commit()
    finally:
        conn.close()
    log_event("email.sent", message=f"Sent '{rendered['subject']}' to {to_email} from {sender_email}",
              mailbox=sender_email, tracking_id=tracking_id, communication_id=comm_id, **log_ctx)
    return {"allocation_donor_id": rendered["allocation_donor_id"], "status": "sent",
            "recipient_email": to_email, "tracking_id": tracking_id, "communication_id": comm_id}


def _send_per_donor(payload: OutlookSendRequest, request: Request) -> Dict[str, Any]:
    base_url = _public_base_url(request)
    template_type = payload.template_type or "profile_intro"
    results = []
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        rendered_list = [render_email_for_donor(cur, payload.allocation_id, donor_id, template_type, payload.company_id,
                                                payload.subject_template, payload.body_template, payload.custom_variables)
                         for donor_id in dict.fromkeys(payload.allocation_donor_ids or [])]
    finally:
        conn.close()
    for rendered in rendered_list:
        try:
            results.append(deliver_rendered_email(rendered, payload.allocation_id, base_url))
        except HTTPException as e:
            log_event("email.failed", category="email", level="error", company_id=rendered["company_id"],
                      allocation_id=payload.allocation_id, allocation_donor_id=rendered["allocation_donor_id"],
                      recipient=rendered["recipient_email"], detail=str(e.detail), message=f"Send failed: {e.detail}")
            results.append({"allocation_donor_id": rendered["allocation_donor_id"], "status": "failed", "detail": e.detail})
        except Exception as e:
            log_event("email.failed", category="email", level="error", company_id=rendered["company_id"],
                      allocation_id=payload.allocation_id, allocation_donor_id=rendered["allocation_donor_id"],
                      recipient=rendered["recipient_email"], detail=str(e), message=f"Send failed: {e}")
            results.append({"allocation_donor_id": rendered["allocation_donor_id"], "status": "failed", "detail": str(e)})
    sent = sum(1 for r in results if r["status"] == "sent")
    return {
        "status": "success" if sent == len(results) and results else ("partial" if sent else "failed"),
        "message": f"Sent {sent} of {len(results)} personalised email(s).",
        "results": results,
    }


# ---------------------------------------------------------------------------------------------------------
# Bulk email: pick donors across ALL allocations (filters as the allocation list), choose a template, personalise
# per donor, preview, send in batches. Every email goes through render_email_for_donor + deliver_rendered_email,
# so it is personalised per donor and logged in that donor's history exactly like a single send.
# ---------------------------------------------------------------------------------------------------------
BULK_SEND_BATCH_LIMIT = 25
BULK_PREVIEW_LIMIT = 50
_CYCLE_ALIASES = {"due_for_renewal": "due", "grace_period": "grace"}


@router.get("/bulk-email/recipients")
def get_bulk_email_recipients(request: Request, company_id: str = Query(...), lifecycle: Optional[str] = Query(None),
                              allocation_kind: Optional[str] = Query(None)):
    """One row per donor on every matching allocation (no paging). Accepts the same filters as /allocations."""
    comp = (company_id or "").strip().lower()
    passthrough = "&".join(f"{k}={urllib.parse.quote(v)}" for k, v in request.query_params.multi_items()
                           if k not in ("company_id", "lifecycle", "allocation_kind"))
    allocations = _call_with_query(get_allocations, passthrough, comp)["allocations"]
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        last_by_donor, last_by_email = {}, {}
        for r in conn.execute("""
                SELECT allocation_id, allocation_donor_id, LOWER(TRIM(recipient_email)) AS email, template_type,
                       subject, sent_at, delivery_status
                FROM sponsorship_communications
                WHERE company_id = ? AND direction = 'outbound' ORDER BY sent_at""", (comp,)):
            info = {"sent_at": r["sent_at"], "template_type": r["template_type"], "subject": r["subject"],
                    "status": r["delivery_status"]}
            if r["allocation_donor_id"]:
                last_by_donor[r["allocation_donor_id"]] = info
            last_by_email[(r["allocation_id"], r["email"])] = info
    finally:
        conn.close()
    rows = []
    for a in allocations:
        cycle = _CYCLE_ALIASES.get(a.get("cycle_status"), a.get("cycle_status"))
        if lifecycle and lifecycle != "all" and cycle != lifecycle:
            continue
        kind = "campaign" if a.get("allocation_type") == "campaign" else "individual"
        if allocation_kind and allocation_kind != "all" and kind != allocation_kind:
            continue
        for d in a.get("donors") or []:
            email = (d.get("donor_email") or "").strip()
            last = last_by_donor.get(d["id"]) or last_by_email.get((a["id"], email.lower()))
            rows.append({
                "allocation_id": a["id"], "allocation_donor_id": d["id"],
                "donor_name": d.get("donor_name") or "", "donor_email": email,
                "has_email": "@" in email, "role": d.get("role"), "is_primary": d.get("is_primary"),
                "beneficiary_name": a.get("beneficiary_name"), "project_code": a.get("project_code"),
                "sponsorship_type": a.get("sponsorship_type"), "cycle_status": cycle, "end_date": a.get("end_date"),
                "days_remaining": a.get("days_remaining"), "allocation_kind": kind,
                "campaign_name": a.get("campaign_name"), "last_email": last,
            })
    return {"company_id": comp, "count": len(rows), "with_email": sum(1 for r in rows if r["has_email"]), "recipients": rows}


def _bulk_items_for_company(payload: BulkEmailRequest, limit: int) -> List[BulkEmailItem]:
    comp = (payload.company_id or "").strip().lower()
    if comp in ("", "all"):
        raise HTTPException(status_code=400, detail="Choose a specific charity.")
    items = list({i.allocation_donor_id: i for i in payload.items}.values())  # each donor once
    if not items:
        raise HTTPException(status_code=400, detail="Select at least one donor.")
    if len(items) > limit:
        raise HTTPException(status_code=400, detail=f"At most {limit} donors per request.")
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        ids = sorted({i.allocation_id for i in items})
        owned = {r[0] for r in conn.execute(
            f"SELECT id FROM sponsorship_allocations WHERE company_id = ? AND id IN ({','.join('?' * len(ids))})", (comp, *ids))}
    finally:
        conn.close()
    foreign = [i.allocation_id for i in items if i.allocation_id not in owned]
    if foreign:
        log_event("access.cross_company_blocked", category="security", level="warning", company_id=comp,
                  message=f"Bulk email referenced allocations outside {comp}: {foreign[:10]}")
        raise HTTPException(status_code=404, detail="Some selected sponsorships were not found for this charity.")
    return items


def _render_bulk_item(cur, payload: BulkEmailRequest, item: BulkEmailItem) -> Dict[str, Any]:
    subject = item.subject_template if item.subject_template is not None else payload.subject_template
    body = item.body_template if item.body_template is not None else payload.body_template
    return render_email_for_donor(cur, item.allocation_id, item.allocation_donor_id, payload.template_type,
                                  payload.theme or payload.company_id, subject, body)


@router.post("/bulk-email/preview")
def preview_bulk_email(payload: BulkEmailRequest):
    """Exactly what each selected donor would receive (same rendering as sending). Nothing is sent."""
    items = _bulk_items_for_company(payload, BULK_PREVIEW_LIMIT)
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    out = []
    try:
        cur = conn.cursor()
        for item in items:
            try:
                r = _render_bulk_item(cur, payload, item)
                problem = ("Donor has no email address" if "@" not in (r["recipient_email"] or "") else
                           ("Unknown placeholders: " + ", ".join(r["unresolved_placeholders"])) if r["unresolved_placeholders"] else None)
                out.append({"allocation_id": item.allocation_id, "allocation_donor_id": item.allocation_donor_id,
                            "recipient_email": r["recipient_email"], "recipient_name": r["recipient_name"],
                            "subject": r["subject"], "body_html": r["body_html"], "theme": r["theme"],
                            "personalised": item.subject_template is not None or item.body_template is not None,
                            "ready": problem is None, "problem": problem})
            except HTTPException as e:
                out.append({"allocation_id": item.allocation_id, "allocation_donor_id": item.allocation_donor_id,
                            "ready": False, "problem": str(e.detail)})
    finally:
        conn.close()
    return {"count": len(out), "ready": sum(1 for o in out if o["ready"]), "previews": out}


@router.post("/bulk-email/send")
def send_bulk_email(payload: BulkEmailRequest, request: Request):
    """Sends up to BULK_SEND_BATCH_LIMIT personalised emails (the page sends larger selections batch by batch).
    dry_run=true validates everything without sending."""
    items = _bulk_items_for_company(payload, BULK_SEND_BATCH_LIMIT)
    base_url = _public_base_url(request)
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    rendered = []
    try:
        cur = conn.cursor()
        for item in items:
            try:
                rendered.append((item, _render_bulk_item(cur, payload, item), None))
            except HTTPException as e:
                rendered.append((item, None, str(e.detail)))
    finally:
        conn.close()
    results = []
    for item, r, err in rendered:
        base = {"allocation_id": item.allocation_id, "allocation_donor_id": item.allocation_donor_id}
        if err:
            results.append({**base, "status": "failed", "detail": err})
            continue
        if payload.dry_run:
            problem = ("Donor has no email address" if "@" not in (r["recipient_email"] or "") else
                       ("Unknown placeholders: " + ", ".join(r["unresolved_placeholders"])) if r["unresolved_placeholders"] else None)
            results.append({**base, "status": "ready" if not problem else "skipped", "detail": problem,
                            "recipient_email": r["recipient_email"]})
            continue
        try:
            results.append({**base, **deliver_rendered_email(r, item.allocation_id, base_url)})
        except HTTPException as e:
            results.append({**base, "status": "failed", "detail": str(e.detail)})
        except Exception as e:
            results.append({**base, "status": "failed", "detail": str(e)})
    counts = {k: sum(1 for x in results if x["status"] == k) for k in ("sent", "ready", "skipped", "failed")}
    if not payload.dry_run:
        log_event("email.bulk_batch", category="email", company_id=payload.company_id.strip().lower(),
                  template=payload.template_type, message=f"Bulk email batch: {counts['sent']} sent, "
                  f"{counts['skipped']} skipped, {counts['failed']} failed", **counts)
    return {"dry_run": payload.dry_run, "counts": counts, "results": results}


@router.post("/outlook/send")
def send_outlook_message(payload: OutlookSendRequest, request: Request, current_user = Depends(get_current_user)):
    """Dispatches an email via Microsoft Graph API, embeds real-time open tracking pixel, and logs delivery metadata."""
    if payload.allocation_donor_ids:
        return _send_per_donor(payload, request)
    if not (payload.recipient_email or "").strip() or not (payload.body_html or "").strip():
        raise HTTPException(status_code=400, detail="Choose at least one donor to email.")
    # The sending mailbox always belongs to the charity that owns the allocation.
    # payload.company_id carries the email theme (e.g. 'sp'), which only selects branding.
    comp = _allocation_company(payload.allocation_id)
    theme_owner = _owner_company(payload.company_id) if payload.company_id else comp
    if theme_owner != comp:
        raise HTTPException(status_code=400, detail=f"Theme '{payload.company_id}' cannot be used for a {comp} sponsorship.")
    from backend.api.mailbox import is_connected, sender_address, send_email
    if not is_connected(comp):
        raise HTTPException(status_code=400, detail=f"{comp.title()}'s mailbox isn't connected - connect it in Email > Mailbox.")
    sender_email = sender_address(comp) or "me"

    recipients_raw = payload.recipient_email.replace(";", ",").split(",")
    to_recipients_list = []
    for r in recipients_raw:
        clean_r = r.strip()
        if clean_r and "@" in clean_r:
            to_recipients_list.append({
                "emailAddress": {
                    "address": clean_r,
                    "name": payload.recipient_name if len(recipients_raw) == 1 else clean_r
                }
            })
    if not to_recipients_list:
        to_recipients_list = [{
            "emailAddress": {
                "address": payload.recipient_email.strip(),
                "name": payload.recipient_name or payload.recipient_email.strip()
            }
        }]

    # Generate unique email tracking ID
    tracking_id = str(uuid.uuid4())
    
    # Construct base tracking URL
    base_url = str(request.base_url).rstrip('/')
    forwarded_proto = request.headers.get("x-forwarded-proto", "http")
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
    if forwarded_host:
        base_url = f"{forwarded_proto}://{forwarded_host}".rstrip('/')

    tracking_pixel_url = f"{base_url}/api/tracker/email-tracking/pixel/{tracking_id}"
    tracking_pixel_html = f'<div style="display:none;max-height:0px;overflow:hidden;"><img src="{tracking_pixel_url}" width="1" height="1" style="display:none;width:1px;height:1px;border:0;outline:none;" alt="" /></div>'

    # Sanitize raw body: replace any lingering massive base64 data URIs with public HTTPS logo URLs
    raw_body = payload.body_html.strip()
    raw_body = re.sub(
        r'src=["\']data:image/[^;]+;base64,[^"\']+["\']',
        f'src="{_RETHINK_EMAIL_LOGO_URI}"',
        raw_body
    )
    if "alt=\"Sisters' Project\"" in raw_body:
        raw_body = re.sub(r'(<img[^>]*alt="Sisters\' Project"[^>]*src=")[^"]*(")', r'\1' + _SP_LOGO_URI + r'\2', raw_body)
    if "alt=\"IQRA\"" in raw_body:
        raw_body = re.sub(r'(<img[^>]*alt="IQRA"[^>]*src=")[^"]*(")', r'\1' + _IQRA_EMAIL_LOGO_URI + r'\2', raw_body)

    if len(to_recipients_list) == 1:  # the Unsubscribe button (one person per link)
        from backend.api.unsubscribe import add_footer
        raw_body = add_footer(raw_body, comp, to_recipients_list[0]["emailAddress"]["address"], tracking_id)
    if "</body>" in raw_body:
        email_body_with_pixel = raw_body.replace("</body>", f"{tracking_pixel_html}</body>")
    else:
        email_body_with_pixel = f"{raw_body}{tracking_pixel_html}"

    sent = send_email(comp, [(r["emailAddress"]["address"], r["emailAddress"].get("name")) for r in to_recipients_list],
                      payload.subject.strip(), email_body_with_pixel)
    if not sent["ok"]:
        log_event("email.failed", category="email", level="error", company_id=comp, allocation_id=payload.allocation_id,
                  recipient=payload.recipient_email, http_status=sent.get("http_status"), detail=sent["detail"][:300],
                  message=f"Send failed ({sent.get('http_status')}) (legacy single send)")
        raise HTTPException(status_code=400, detail=sent["detail"])
    log_event("email.sent", category="email", company_id=comp, allocation_id=payload.allocation_id,
              recipient=payload.recipient_email, template=payload.template_type, subject=payload.subject,
              mailbox=sender_email, tracking_id=tracking_id, message=f"Sent (legacy single send) to {payload.recipient_email}")

    # Log in communications database with tracking fields
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sponsorship_communications (
                allocation_id, company_id, direction, message_id, thread_id,
                subject, body, sender_email, recipient_email,
                tracking_id, delivery_status, open_count, sent_at
            ) VALUES (?, ?, 'outbound', ?, ?, ?, ?, ?, ?, ?, 'delivered', 0, CURRENT_TIMESTAMP)
        """, (
            payload.allocation_id,
            comp,
            sent.get("message_id") or f"graph_{int(time.time()*1000)}",
            sent.get("thread_id") or "",
            payload.subject.strip(),
            payload.body_html.strip(),
            sender_email,
            payload.recipient_email.strip(),
            tracking_id
        ))

        new_status = "Profile Sent"
        if payload.template_type == "video_update":
            new_status = "Video Sent"
        elif payload.template_type == "end_year_feedback":
            new_status = "Feedback Sent"

        cur.execute("""
            UPDATE sponsorship_allocations SET
                communication_status = ?,
                last_contacted_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (new_status, payload.allocation_id))

        conn.commit()
        return {
            "status": "success",
            "message": "Email successfully dispatched via Microsoft Graph API!",
            "tracking_id": tracking_id,
            "delivery_status": "delivered"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

def ensure_outlook_subscription(company_id: str, notification_url: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    """
    Checks and auto-renews Microsoft Graph Webhook Subscription.
    Microsoft Graph subscriptions expire in max 4230 mins (< 3 days).
    This automatically extends active subscriptions or creates a new one if expired.
    """
    comp = (company_id or "rethink").strip().lower()
    auth = _get_outlook_auth_row(comp)
    if not auth or not auth["refresh_token"]:
        return {"status": "not_connected"}

    try:
        access_token = _get_valid_graph_token(comp)
    except Exception as e:
        return {"status": "token_error", "detail": str(e)}

    sub_id = auth["subscription_id"]
    sub_exp = auth["subscription_expiration"]
    now = datetime.datetime.utcnow()
    # Microsoft Graph max lifetime for mail is 4230 mins (~70.5 hours). We use 68 hours safely.
    new_exp_dt = now + datetime.timedelta(hours=68)
    new_exp_str = new_exp_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    n_url = notification_url or os.getenv("WEBHOOK_PUBLIC_URL", "https://rethink.dpdns.org/api/tracker/outlook/webhook")

    needs_renewal = True
    if not force and sub_id and sub_exp:
        try:
            exp_clean = str(sub_exp).replace("Z", "").replace("+00:00", "")
            exp_dt = datetime.datetime.fromisoformat(exp_clean)
            # If still valid for more than 24 hours and not force requested, no renewal needed yet
            if (exp_dt - now).total_seconds() > 86400:
                needs_renewal = False
                return {"status": "active", "subscriptionId": sub_id, "expiration": sub_exp}
        except Exception:
            needs_renewal = True

    # 1. Attempt PATCH renewal if we have an existing subscription ID
    if sub_id:
        patch_url = f"https://graph.microsoft.com/v1.0/subscriptions/{sub_id}"
        patch_res = requests.patch(patch_url, headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }, json={"expirationDateTime": new_exp_str}, timeout=15)

        if patch_res.status_code in (200, 201):
            p_data = patch_res.json()
            updated_exp = p_data.get("expirationDateTime", new_exp_str)
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
            try:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE sponsorship_outlook_auth SET
                        subscription_expiration = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE company_id = ?
                """, (updated_exp, comp))
                conn.commit()
            finally:
                conn.close()
            return {"status": "renewed", "subscriptionId": sub_id, "expiration": updated_exp}

    # 2. If PATCH fails or no subscription exists, create fresh subscription via POST
    sub_url = "https://graph.microsoft.com/v1.0/subscriptions"
    sub_payload = {
        "changeType": "created",
        "notificationUrl": n_url,
        "resource": "/me/mailFolders('Inbox')/messages",
        "expirationDateTime": new_exp_str,
        "clientState": f"sponsorship_{comp}"
    }

    res = requests.post(sub_url, headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }, json=sub_payload, timeout=15)

    if res.status_code in (200, 201):
        sub_data = res.json()
        new_sub_id = sub_data.get("id")
        created_exp = sub_data.get("expirationDateTime", new_exp_str)

        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE sponsorship_outlook_auth SET
                    subscription_id = ?,
                    subscription_expiration = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE company_id = ?
            """, (new_sub_id, created_exp, comp))
            conn.commit()
        finally:
            conn.close()

        return {"status": "created", "subscriptionId": new_sub_id, "expiration": created_exp}

    return {"status": "failed", "detail": res.text}

@router.post("/outlook/setup-subscription")
def setup_outlook_subscription(company_id: Optional[str] = Query("rethink"), notification_url: Optional[str] = Query(None), current_user = Depends(require_super_admin)):
    """Creates or manually forces renewal of a Microsoft Graph Webhook Subscription."""
    comp = (company_id or "rethink").strip().lower()
    res = ensure_outlook_subscription(comp, notification_url, force=True)
    if res.get("status") in ("active", "renewed", "created"):
        return {"status": "success", "subscriptionId": res.get("subscriptionId"), "expiration": res.get("expiration")}
    raise HTTPException(status_code=400, detail=f"Failed to setup/renew subscription: {res.get('detail', res.get('status'))}")

@router.post("/outlook/renew-subscription")
def renew_outlook_subscription(company_id: Optional[str] = Query("rethink"), current_user = Depends(require_super_admin)):
    """Background or scheduled endpoint to automatically renew Graph Webhook Subscriptions."""
    comp = (company_id or "rethink").strip().lower()
    res = ensure_outlook_subscription(comp)
    return res

@router.post("/outlook/test-send")
def test_send_outlook_message(payload: OutlookTestEmailRequest, request: Request, current_user = Depends(require_super_admin)):
    """Dispatches a test verification email via Microsoft Graph API. Super Admin only."""
    comp = (payload.company_id or "rethink").strip().lower()
    from backend.api.mailbox import TestSend, mailbox_test_send, provider
    if provider(comp) == "gmail":
        return mailbox_test_send(TestSend(company_id=comp, recipient_email=payload.recipient_email or ""), current_user)
    access_token = _get_valid_graph_token(comp)
    auth = _get_outlook_auth_row(comp)
    sender_email = auth["connected_email"] if auth and auth["connected_email"] else "office@rethinkcharity.org.uk"
    target_email = (payload.recipient_email or "office@rethinkcharity.org.uk").strip()

    test_html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff;">
      <div style="background: linear-gradient(135deg, #0284c7, #0ea5e9); padding: 20px 24px; border-radius: 8px; color: #ffffff; text-align: center;">
        <h2 style="margin: 0; font-size: 20px; font-weight: 700; color: #ffffff;">Microsoft 365 Integration Verified</h2>
        <p style="margin: 6px 0 0; font-size: 14px; color: rgba(255,255,255,0.9);">Rethink Charity CRM</p>
      </div>
      <div style="padding: 24px 8px; color: #334155; line-height: 1.6;">
        <p style="margin-top: 0;">Hello,</p>
        <p>This is a verification test email dispatched directly via the <strong>Microsoft Graph API</strong> from your connected Microsoft 365 mailbox: <strong style="color: #0284c7;">{sender_email}</strong>.</p>
        <div style="background: #f8fafc; border-left: 4px solid #0284c7; padding: 14px 18px; margin: 20px 0; border-radius: 0 8px 8px 0;">
          <p style="margin: 0; font-size: 14px; font-weight: 700; color: #0f172a;">Webhook &amp; Mail Dispatch Operational</p>
          <p style="margin: 4px 0 0; font-size: 13px; color: #64748b;">Two-way sync and donor reply tracking are active for company <code>{comp.upper()}</code>.</p>
        </div>
        <p style="font-size: 13px; color: #94a3b8; margin-top: 24px;">Sent by {current_user.get('email', 'Super Admin')} on {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}.</p>
      </div>
    </div>
    """

    send_payload = {
        "message": {
            "subject": f"✅ [CRM Verified] Microsoft 365 Test Email — {comp.capitalize()}",
            "body": {
                "contentType": "HTML",
                "content": test_html
            },
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": target_email,
                        "name": target_email.split('@')[0]
                    }
                }
            ]
        },
        "saveToSentItems": "true"
    }

    send_url = "https://graph.microsoft.com/v1.0/me/sendMail"
    res = requests.post(send_url, headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }, json=send_payload, timeout=15)

    if res.status_code not in (200, 202):
        raise HTTPException(status_code=400, detail=f"Microsoft Graph sendMail Error ({res.status_code}): {res.text}")

    return {
        "status": "success",
        "message": f"Test email dispatched successfully to {target_email} via Microsoft Graph API ({sender_email})!",
        "sender": sender_email,
        "recipient": target_email
    }

@router.api_route("/outlook/webhook", methods=["GET", "POST"])
async def outlook_graph_webhook(request: Request):
    """
    Microsoft Graph Webhook Endpoint:
    1. Responds to validation handshake with plain text validationToken.
    2. Processes change notifications for incoming donor replies.
    """
    # 1. Handle validation handshake
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        return Response(content=validation_token, media_type="text/plain", status_code=200)

    # 2. Handle change notifications
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=202)

    values = body.get("value", [])
    for item in values:
        resource = item.get("resource", "")
        # Extract message ID
        if "/messages/" not in resource:
            continue
        msg_id = resource.split("/messages/")[-1].replace("'", "").replace(")", "").strip()
        if not msg_id:
            continue

        client_state = item.get("clientState", "")
        company_id = client_state.replace("sponsorship_", "") if client_state else ""
        # Only accept notifications for the subscription we created for that charity.
        sub_auth = _get_outlook_auth_row(company_id) if company_id else None
        if not sub_auth or not sub_auth["subscription_id"] or sub_auth["subscription_id"] != item.get("subscriptionId"):
            logger.warning("Ignoring Graph notification with unknown subscription/clientState")
            continue

        try:
            access_token = _get_valid_graph_token(company_id)
            m_res = requests.get(f"https://graph.microsoft.com/v1.0/me/messages/{msg_id}", headers={
                "Authorization": f"Bearer {access_token}"
            }, timeout=10)

            if m_res.status_code == 200:
                msg_data = m_res.json()
                from_email = msg_data.get("from", {}).get("emailAddress", {}).get("address", "")
                subject = msg_data.get("subject", "")
                body_preview = msg_data.get("bodyPreview", "")
                conv_id = msg_data.get("conversationId", "")

                conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
                try:
                    cur = conn.cursor()
                    auth_row = _get_outlook_auth_row(company_id)
                    mailbox = (auth_row["connected_email"] if auth_row and auth_row["connected_email"] else company_id)
                    if _record_inbound_reply(cur, company_id, msg_id, conv_id, subject, body_preview,
                                             from_email, mailbox, msg_data.get("receivedDateTime")):
                        conn.commit()
                finally:
                    conn.close()
        except Exception:
            pass

    return Response(status_code=202)


def _match_reply_sender(cur, company_id: str, sender_email: str, conv_id: str = "", received_at: Optional[str] = None):
    """(allocation_id, allocation_donor_id) the reply belongs to, most precise evidence first:
      1. the Outlook conversation of an email we sent (exact sponsorship + donor);
      2. the most recent email we sent to this address before the reply arrived;
      3. the most recent sponsorship this sender is a donor on (old behaviour)."""
    sender = (sender_email or "").strip().lower()
    if conv_id:
        row = cur.execute("""
            SELECT allocation_id, allocation_donor_id FROM sponsorship_communications
            WHERE company_id = ? AND direction = 'outbound' AND thread_id = ?
            ORDER BY sent_at DESC LIMIT 1""", (company_id, conv_id)).fetchone()
        if row:
            return row[0], row[1] or _donor_row_for_email(cur, row[0], sender)
    if not sender:
        return None, None
    row = cur.execute("""
        SELECT allocation_id, allocation_donor_id FROM sponsorship_communications
        WHERE company_id = ? AND direction = 'outbound' AND LOWER(TRIM(recipient_email)) = ?
          AND sent_at <= COALESCE(REPLACE(REPLACE(?, 'T', ' '), 'Z', ''), CURRENT_TIMESTAMP)
        ORDER BY sent_at DESC LIMIT 1""", (company_id, sender, received_at)).fetchone()
    if row:
        return row[0], row[1] or _donor_row_for_email(cur, row[0], sender)
    row = cur.execute("""
        SELECT d.allocation_id, d.id FROM sponsorship_allocation_donors d
        WHERE d.company_id = ? AND LOWER(TRIM(d.donor_email)) = ?
        ORDER BY d.allocation_id DESC LIMIT 1
    """, (company_id, sender)).fetchone()
    if row:
        return row[0], row[1]
    # Allocations created before donor rows existed may still hold comma-separated emails.
    for r_id, r_emails in cur.execute(
            "SELECT id, donor_email FROM sponsorship_allocations WHERE company_id = ? ORDER BY created_at DESC",
            (company_id,)).fetchall():
        if r_emails and sender in [e.strip().lower() for e in r_emails.replace(";", ",").split(",")]:
            return r_id, None
    return None, None


def _donor_row_for_email(cur, allocation_id: int, email: str) -> Optional[int]:
    if not email:
        return None
    row = cur.execute("SELECT id FROM sponsorship_allocation_donors WHERE allocation_id = ? AND LOWER(TRIM(donor_email)) = ? LIMIT 1",
                      (allocation_id, email)).fetchone()
    return row[0] if row else None


def _backfill_conversation_ids(company_id: str) -> Dict[str, Any]:
    """Graph's sendMail returns no message id, so after sending we find each email in Sent Items (same recipient,
    same subject, sent within 10 minutes) and store its conversationId. Replies are then matched exactly."""
    comp = (company_id or "").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        pending = [dict(r) for r in conn.execute("""
            SELECT id, recipient_email, subject, sent_at FROM sponsorship_communications
            WHERE company_id = ? AND direction = 'outbound' AND COALESCE(thread_id, '') = ''
              AND sent_at >= datetime('now', '-3 days')""", (comp,))]
    finally:
        conn.close()
    if not pending:
        return {"status": "nothing_to_do"}
    access_token = _get_valid_graph_token(comp)
    oldest = min(p["sent_at"] for p in pending)
    since = (datetime.datetime.strptime(oldest[:19], "%Y-%m-%d %H:%M:%S") - datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = requests.get("https://graph.microsoft.com/v1.0/me/mailFolders('SentItems')/messages", params={
        "$filter": f"sentDateTime ge {since}", "$orderby": "sentDateTime desc", "$top": "200",
        "$select": "conversationId,internetMessageId,subject,toRecipients,sentDateTime"},
        headers={"Authorization": f"Bearer {access_token}"}, timeout=20)
    if res.status_code != 200:
        return {"status": "fetch_failed", "http_status": res.status_code}
    sent_items = []
    for m in res.json().get("value", []):
        to = [((t.get("emailAddress") or {}).get("address") or "").strip().lower() for t in m.get("toRecipients") or []]
        try:
            when = datetime.datetime.strptime(m["sentDateTime"][:19], "%Y-%m-%dT%H:%M:%S")
        except (KeyError, ValueError):
            continue
        sent_items.append((to, (m.get("subject") or "").strip(), when, m.get("conversationId") or ""))
    matched = 0
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        for p in pending:
            sent_at = datetime.datetime.strptime(p["sent_at"][:19], "%Y-%m-%d %H:%M:%S")
            email = (p["recipient_email"] or "").strip().lower()
            candidates = [(abs((when - sent_at).total_seconds()), conv) for to, subj, when, conv in sent_items
                          if conv and email in to and subj == (p["subject"] or "").strip()
                          and abs((when - sent_at).total_seconds()) <= 600]
            if candidates:
                conn.execute("UPDATE sponsorship_communications SET thread_id = ? WHERE id = ?", (min(candidates)[1], p["id"]))
                matched += 1
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "pending": len(pending), "matched": matched}


def _record_direct_reply(cur, company_id: str, msg_id: str, conv_id: str, subject: str, body_preview: str,
                         sender_email: str, received_at: Optional[str]) -> bool:
    """A reply to an email sent from the Email section / Donors (crm_email_messages) rather than a sponsorship
    email: recorded in crm_email_replies so the donor's thread is complete. It belongs to the direct email when
    that is the latest thing we sent this person before the reply and the reply isn't in a sponsorship
    conversation. Returns True when newly recorded, "recorded" when it already was, False when it isn't one."""
    sender = (sender_email or "").strip().lower()
    if not sender or not msg_id:
        return False
    try:
        if cur.execute("SELECT 1 FROM crm_email_replies WHERE company_id = ? AND message_id = ?", (company_id, msg_id)).fetchone():
            return "recorded"
        when = str(received_at or "").replace("T", " ").replace("Z", "")[:19] or datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        if conv_id and cur.execute("""SELECT 1 FROM sponsorship_communications WHERE company_id = ? AND direction = 'outbound'
                                      AND thread_id = ? LIMIT 1""", (company_id, conv_id)).fetchone():
            return False  # a reply in a sponsorship email's conversation
        direct = cur.execute("""SELECT id, REPLACE(sent_at, 'T', ' ') FROM crm_email_messages
                                WHERE company_id = ? AND LOWER(recipient_email) = ? AND status = 'sent'
                                  AND REPLACE(sent_at, 'T', ' ') <= ? ORDER BY sent_at DESC LIMIT 1""",
                             (company_id, sender, when)).fetchone()
    except sqlite3.OperationalError:
        return False
    if not direct:
        return False
    spons = cur.execute("""SELECT MAX(REPLACE(sent_at, 'T', ' ')) FROM sponsorship_communications WHERE company_id = ?
                           AND direction = 'outbound' AND LOWER(TRIM(recipient_email)) = ? AND REPLACE(sent_at, 'T', ' ') <= ?""",
                        (company_id, sender, when)).fetchone()[0]
    if spons and spons > direct[1]:
        return False  # the latest email they got was a sponsorship one
    cur.execute("""INSERT OR IGNORE INTO crm_email_replies (company_id, message_id, conversation_id, reply_to_id, sender_email,
                                                       subject, body_preview, received_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (company_id, msg_id, conv_id, direct[0], sender, subject, body_preview, when))
    cur.execute("UPDATE crm_email_messages SET replied_at = COALESCE(replied_at, ?) WHERE id = ?", (when, direct[0]))
    log_event("email.reply_received", category="email", company_id=company_id, sender=sender, subject=subject,
              message=f"Reply from {sender} (direct email)")
    return True


def _record_inbound_reply(cur, company_id: str, msg_id: str, conv_id: str, subject: str, body_preview: str,
                          sender_email: str, recipient_email: str, received_at: Optional[str]) -> bool:
    """Logs one inbound reply (once per message id) and marks only the outbound email that donor
    was answering as replied - not every email on the sponsorship."""
    if cur.execute("SELECT 1 FROM sponsorship_communications WHERE message_id = ? AND company_id = ?",
                   (msg_id, company_id)).fetchone():
        return False
    direct = _record_direct_reply(cur, company_id, msg_id, conv_id, subject, body_preview, sender_email, received_at)
    if direct:
        return direct is True
    alloc_id, alloc_donor_id = _match_reply_sender(cur, company_id, sender_email, conv_id, received_at)
    if not alloc_id:
        return False
    cur.execute("""
        INSERT INTO sponsorship_communications (
            allocation_id, allocation_donor_id, company_id, direction, message_id,
            thread_id, subject, body, sender_email, recipient_email, sent_at
        ) VALUES (?, ?, ?, 'inbound', ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
    """, (alloc_id, alloc_donor_id, company_id, msg_id, conv_id, subject, body_preview,
          sender_email, recipient_email, received_at))
    cur.execute("""
        UPDATE sponsorship_allocations SET communication_status = 'Donor Replied',
            last_replied_at = COALESCE(?, CURRENT_TIMESTAMP) WHERE id = ?
    """, (received_at, alloc_id))
    log_event("email.reply_received", category="email", company_id=company_id, allocation_id=alloc_id,
              allocation_donor_id=alloc_donor_id, sender=sender_email, subject=subject,
              message=f"Reply from {sender_email}")
    target = cur.execute("""
        SELECT id FROM sponsorship_communications
        WHERE company_id = ? AND direction = 'outbound' AND thread_id = ? AND ? != ''
        ORDER BY sent_at DESC LIMIT 1
    """, (company_id, conv_id or "", conv_id or "")).fetchone() or cur.execute("""
        SELECT id FROM sponsorship_communications
        WHERE allocation_id = ? AND direction = 'outbound'
          AND (allocation_donor_id = ? OR LOWER(TRIM(recipient_email)) = ? OR LOWER(recipient_email) LIKE ?)
          AND sent_at <= COALESCE(REPLACE(REPLACE(?, 'T', ' '), 'Z', ''), CURRENT_TIMESTAMP)
        ORDER BY sent_at DESC LIMIT 1
    """, (alloc_id, alloc_donor_id, (sender_email or '').strip().lower(), f"%{(sender_email or '').strip().lower()}%", received_at)).fetchone()
    if target:
        cur.execute("""
            UPDATE sponsorship_communications SET delivery_status = 'replied',
                replied_at = COALESCE(?, CURRENT_TIMESTAMP) WHERE id = ?
        """, (received_at, target[0]))
    return True


def sync_inbound_outlook_replies(company_id: str) -> Dict[str, Any]:
    """
    Queries Microsoft Graph API for recent inbox emails and syncs donor replies.
    Acts as an instant real-time sync mechanism alongside Webhooks.
    """
    comp = (company_id or "rethink").strip().lower()
    auth = _get_outlook_auth_row(comp)
    if not auth or not auth["refresh_token"]:
        return {"status": "not_connected"}

    try:
        access_token = _get_valid_graph_token(comp)
        connected_email = (auth["connected_email"] or "").strip().lower()

        # Query top 30 recent messages from Inbox
        url = "https://graph.microsoft.com/v1.0/me/mailFolders('Inbox')/messages?$top=30&$orderby=receivedDateTime desc"
        res = requests.get(url, headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
        if res.status_code != 200:
            return {"status": "fetch_failed", "detail": res.text}

        messages = res.json().get("value", [])
        new_synced = 0

        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        try:
            cur = conn.cursor()
            for m in messages:
                from_info = m.get("from", {}).get("emailAddress", {})
                sender_email = (from_info.get("address") or "").strip().lower()
                if not sender_email or sender_email == connected_email:
                    continue
                if _record_inbound_reply(cur, comp, m.get("id"), m.get("conversationId", ""), m.get("subject", ""),
                                         m.get("bodyPreview", ""), sender_email, connected_email,
                                         m.get("receivedDateTime")):
                    new_synced += 1

            conn.commit()
        finally:
            conn.close()

        return {"status": "success", "synced_new_replies": new_synced}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

def run_mailbox_maintenance() -> Dict[str, Any]:
    """Background (every few minutes, one worker): keep each connected charity mailbox's reply webhook alive,
    learn conversation ids of recently sent emails, and pull new replies - so replies are recorded even when
    nobody has the tracker open. Read-only towards Outlook apart from renewing the subscription."""
    out = {}
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        companies = [r[0] for r in conn.execute(
            "SELECT company_id FROM sponsorship_outlook_auth WHERE COALESCE(refresh_token, '') != ''")]
    except sqlite3.OperationalError:
        companies = []
    finally:
        conn.close()
    from backend.api.mailbox import gmail_companies, provider, sync_gmail_replies
    companies = [c for c in companies if provider(c) == "outlook"]
    for comp in gmail_companies():  # Gmail mailboxes: no webhook - pull new replies (read-only)
        try:
            r = sync_gmail_replies(comp)
            out[comp] = {"provider": "gmail", "replies": r.get("status"), **({"new_replies": r["synced_new_replies"]} if r.get("synced_new_replies") else {})}
        except Exception as e:
            out[comp] = {"provider": "gmail", "replies": f"error: {e}"}
    for comp in companies:
        result = {}
        for name, fn in (("subscription", lambda: ensure_outlook_subscription(comp)),
                         ("threads", lambda: _backfill_conversation_ids(comp)),
                         ("replies", lambda: sync_inbound_outlook_replies(comp))):
            try:
                r = fn()
                result[name] = r.get("status") if isinstance(r, dict) else r
                if name == "replies" and isinstance(r, dict) and r.get("synced_new_replies"):
                    result["new_replies"] = r["synced_new_replies"]
            except Exception as e:
                result[name] = f"error: {e}"
        out[comp] = result
    return out


@router.post("/outlook/sync-replies")
def trigger_sync_replies(company_id: Optional[str] = Query("rethink"), current_user = Depends(get_current_user)):
    """On-demand sync of recent donor replies from the charity's mailbox (Microsoft 365 or Gmail)."""
    comp = (company_id or "rethink").strip().lower()
    from backend.api.mailbox import sync_replies
    return sync_replies(comp)
# ==========================================
# 9. TEMPLATES & COMMUNICATIONS HISTORY
# ==========================================

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_LOGOS_CACHE_DIR = os.path.join(_ROOT_DIR, "data_cache", "logos")

_PUBLIC_APP_BASE = os.getenv("WEBHOOK_PUBLIC_URL", "https://rethink.dpdns.org").split("/api")[0].rstrip("/")
if not _PUBLIC_APP_BASE.startswith("http"):
    _PUBLIC_APP_BASE = "https://rethink.dpdns.org"

# Publicly hosted, fast, email-client compliant HTTPS logo URLs (prevents Gmail 102KB clipping & raw text leaks)
_RETHINK_EMAIL_LOGO_URI = f"{_PUBLIC_APP_BASE}/logos/rethink_email_logo.png"
_RETHINK_LOGO_URI = _RETHINK_EMAIL_LOGO_URI
_IQRA_EMAIL_LOGO_URI = f"{_PUBLIC_APP_BASE}/logos/iqra_email_logo.png"
_IQRA_LOGO_URI = _IQRA_EMAIL_LOGO_URI
_SP_LOGO_URI = f"{_PUBLIC_APP_BASE}/logos/sp_logo.png"

# SP Single Unified Header: "Powered by" + Sisters' Project logo ✕ Rethink Charity logo
_SP_COLLAB_HEADER = f'''
<table border="0" cellpadding="0" cellspacing="0" width="100%">
  <tr>
    <td align="center" style="padding: 4px 0;">
      <p style="margin: 0 0 12px 0; font-size: 11px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; color: rgba(255,255,255,0.85); font-family: 'Segoe UI', Arial, sans-serif;">Powered by</p>
      <table border="0" cellpadding="0" cellspacing="0" style="display: inline-table; margin: 0 auto;">
        <tr>
          <td align="center" valign="middle" style="padding: 0 10px;">
            <img src="{_SP_LOGO_URI}" alt="Sisters' Project" width="115" height="auto"
              style="display: block; width: 115px; max-width: 115px; border: 0;" />
          </td>
          <td align="center" valign="middle" style="padding: 0 6px;">
            <div style="display: inline-block; width: 26px; height: 26px; background: rgba(255,255,255,0.22); border-radius: 50%; text-align: center; line-height: 26px; font-size: 14px; font-weight: 900; color: #FFFFFF; font-family: Arial, sans-serif;">&#215;</div>
          </td>
          <td align="center" valign="middle" style="padding: 0 10px;">
            <img src="{_RETHINK_EMAIL_LOGO_URI}" alt="Rethink Charity" width="130" height="auto"
              style="display: block; width: 130px; max-width: 130px; border: 0;" />
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
'''

CHARITY_THEMES_CONFIG = {
    "rethink": {
        "id": "rethink",
        "name": "Rethink Charity",
        "short_name": "Rethink",
        "tagline": "Transparent Impact &bull; Sustainable Change",
        "bg_color": "#A051CF",
        "bg_dark": "#4C1D95",
        "card_bg": "#FFFFFF",
        "card_bg_dark": "#1E293B",
        "card_border": "#E9D5FF",
        "card_border_dark": "#3B0764",
        "head_bg": "#A051CF",
        "head_bg_dark": "#581C87",
        "accent_color": "#A051CF",
        "accent_text": "#A051CF",
        "title_color": "#0F172A",
        "body_color": "#334155",
        "detail_box_bg": "#FAF5FF",
        "detail_box_border": "#E9D5FF",
        "logo_img_tag": f'<img src="{_RETHINK_EMAIL_LOGO_URI}" alt="Rethink Charity" width="220" height="auto" style="display: block; width: 220px; max-width: 100%; border: 0; margin: 0 auto;" />',
        "team_name": "The Rethink Charity Team",
        "contact_email": "info@rethinkcharity.org",
        "website_url": "https://rethinkcharity.org",
        "website_display": "www.rethinkcharity.org",
        "privacy_url": "https://rethinkcharity.org/privacy-policy",
        "footer_link_color": "#FFFFFF",
        "footer_text_color": "#F3E8FF"
    },
    "iqra": {
        "id": "iqra",
        "name": "IQRA",
        "short_name": "IQRA",
        "tagline": "Empowering Through Knowledge &amp; Compassion",
        "bg_color": "#F0F9FF",
        "bg_dark": "#082F49",
        "card_bg": "#FFFFFF",
        "card_bg_dark": "#0C4A6E",
        "card_border": "#BAE6FD",
        "card_border_dark": "#0369A1",
        "head_bg": "#00B6F0",
        "head_bg_dark": "#0284C7",
        "accent_color": "#0284C7",
        "accent_text": "#0284C7",
        "title_color": "#0C4A6E",
        "body_color": "#334155",
        "detail_box_bg": "#F0F9FF",
        "detail_box_border": "#BAE6FD",
        "logo_img_tag": f'<img src="{_IQRA_LOGO_URI}" alt="IQRA" width="160" height="auto" style="display: block; width: 160px; max-width: 100%; border: 0; margin: 0 auto;" />',
        "team_name": "The IQRA Team",
        "contact_email": "info@iqra.org",
        "website_url": "https://iqra.org",
        "website_display": "www.iqra.org",
        "privacy_url": "https://iqra.org/privacy",
        "footer_link_color": "#FFFFFF",
        "footer_text_color": "#BAE6FD"
    },
    "sp": {
        "id": "sp",
        "name": "Sisters' Project",
        "short_name": "SP",
        "tagline": "Supporting Sisters, Strengthening Communities",
        "bg_color": "#FFF1F2",
        "bg_dark": "#4C0519",
        "card_bg": "#FFFFFF",
        "card_bg_dark": "#881337",
        "card_border": "#FECDD3",
        "card_border_dark": "#9F1239",
        "head_bg": "#881337",
        "head_bg_dark": "#70092B",
        "accent_color": "#BE123C",
        "accent_text": "#9F1239",
        "title_color": "#881337",
        "body_color": "#334155",
        "detail_box_bg": "#FFF1F2",
        "detail_box_border": "#FECDD3",
        "logo_img_tag": f'<img src="{_SP_LOGO_URI}" alt="Sisters\' Project" width="130" height="auto" style="display: block; width: 130px; max-width: 100%; border: 0; margin: 0 auto;" />',
        "team_name": "The Sisters' Project Team",
        "contact_email": "info@sistersproject.co.uk",
        "website_url": "https://www.sistersproject.co.uk",
        "website_display": "www.sistersproject.co.uk",
        "privacy_url": "https://www.sistersproject.co.uk/privacy-policy",
        "footer_link_color": "#FFFFFF",
        "footer_text_color": "#FECDD3"
    },
    # SP templates as shown in Rethink's workspace: SP × Rethink collaboration header
    "sp_rethink": {
        "id": "sp_rethink",
        "name": "Sisters' Project",
        "short_name": "SP",
        "tagline": "Supporting Sisters, Strengthening Communities",
        "bg_color": "#FFF1F2",
        "bg_dark": "#4C0519",
        "card_bg": "#FFFFFF",
        "card_bg_dark": "#881337",
        "card_border": "#FECDD3",
        "card_border_dark": "#9F1239",
        "head_bg": "#881337",
        "head_bg_dark": "#70092B",
        "accent_color": "#BE123C",
        "accent_text": "#9F1239",
        "title_color": "#881337",
        "body_color": "#334155",
        "detail_box_bg": "#FFF1F2",
        "detail_box_border": "#FECDD3",
        "logo_img_tag": _SP_COLLAB_HEADER,
        "team_name": "The Sisters' Project Team",
        "contact_email": "info@sistersproject.co.uk",
        "website_url": "https://www.sistersproject.co.uk",
        "website_display": "www.sistersproject.co.uk",
        "privacy_url": "https://www.sistersproject.co.uk/privacy-policy",
        "footer_link_color": "#FFFFFF",
        "footer_text_color": "#FECDD3"
    }
}

def _wrap_email_html_template(subject: str, inner_body: str, charity_theme: str = "rethink") -> str:
    """Wraps an email body with a responsive charity-branded email container for Rethink, IQRA, or Sisters' Project (SP)."""
    theme_key = str(charity_theme or "rethink").lower().strip()
    theme = CHARITY_THEMES_CONFIG.get(theme_key, CHARITY_THEMES_CONFIG["rethink"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="color-scheme" content="light dark" />
<title>{subject}</title>
<style type="text/css">
body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
body {{ margin: 0; padding: 0; width: 100% !important; background-color: {theme['bg_color']}; font-family: 'Segoe UI', Arial, sans-serif; }}
@media (prefers-color-scheme: dark) {{
  body, .bg {{ background-color: {theme['bg_dark']} !important; }}
  .card {{ background-color: {theme['card_bg_dark']} !important; border-color: {theme['card_border_dark']} !important; }}
  .head {{ background-color: {theme['head_bg_dark']} !important; }}
  .t-title {{ color: #FFFFFF !important; }}
  .t-body {{ color: #E2E8F0 !important; }}
  .foot {{ background-color: {theme['head_bg_dark']} !important; }}
}}
@media screen and (max-width: 600px) {{
  .card {{ width: 100% !important; border: none !important; }}
  .p-body {{ padding: 18px 16px !important; }}
}}
</style>
</head>
<body class="bg" style="margin: 0; padding: 16px 0; background-color: {theme['bg_color']};">
<center style="width: 100%; background-color: inherit;">
<table border="0" cellpadding="0" cellspacing="0" width="100%" class="bg" style="background-color: {theme['bg_color']};">
<tr>
<td align="center" style="padding: 4px 6px;">
<table border="0" cellpadding="0" cellspacing="0" width="100%" class="card" style="max-width: 600px; background-color: {theme['card_bg']}; border: 1px solid {theme['card_border']}; border-radius: 8px; overflow: hidden; box-shadow: 0 3px 10px rgba(0,0,0,0.05);">
<tr>
<td align="center" class="head" style="background-color: {theme['head_bg']}; padding: 18px 16px; text-align: center;">
{theme['logo_img_tag']}
</td>
</tr>
<tr>
<td class="p-body" style="padding: 24px 26px;">
<h1 class="t-title" style="margin: 0 0 12px 0; font-size: 21px; font-weight: 800; color: {theme['title_color']};">Dear {{{{First_Name}}}},</h1>
<div class="t-body" style="font-size: 14.5px; line-height: 1.6; color: {theme['body_color']};">
{inner_body}
</div>
<div style="margin-top: 20px; padding-top: 14px; border-top: 1px solid {theme['card_border']}; font-size: 13.5px; line-height: 1.5;">
<p class="t-body" style="margin: 0 0 2px 0; color: {theme['body_color']};">Warm regards,</p>
<p style="margin: 0 0 4px 0; font-weight: 700; color: {theme['accent_text']};">{theme['team_name']}</p>
<p style="margin: 0; font-size: 12px; color: #64748B;"><a href="mailto:{theme['contact_email']}" style="color: {theme['accent_color']}; text-decoration: none;">{theme['contact_email']}</a> &bull; <a href="{theme['website_url']}" target="_blank" style="color: {theme['accent_color']};">{theme['website_display']}</a></p>
</div>
</td>
</tr>
<tr>
<td align="center" class="foot" style="background-color: {theme['head_bg']}; padding: 14px; text-align: center;">
<p style="margin: 0 0 4px 0; font-size: 11.5px; font-weight: 700; color: #FFFFFF;">{theme['tagline']}</p>
<p style="margin: 0; font-size: 10px; color: {theme['footer_text_color']};">This email was sent to <a href="mailto:{{{{Email}}}}" style="color: {theme['footer_link_color']}; text-decoration: underline;">{{{{Email}}}}</a>. &bull; <a href="{theme['privacy_url']}" target="_blank" style="color: {theme['footer_link_color']};">Privacy Policy</a> &bull; <a href="mailto:{theme['contact_email']}?subject=Unsubscribe" style="color: {theme['footer_link_color']};">Unsubscribe</a></p>
</td>
</tr>
</table>
</td>
</tr>
</table>
</center>
</body>
</html>"""

DEFAULT_TEMPLATES_BY_CHARITY = {
    "rethink": [
        {
            "template_type": "profile_intro",
            "subject": "Sponsorship Profile Update: Welcome to Sponsoring {beneficiary_name} | Rethink Charity",
            "body_html": _wrap_email_html_template(
                "Sponsorship Profile Update: Welcome to Sponsoring {beneficiary_name}",
                """<p style="margin: 0 0 12px 0;">Thank you for partnering with Rethink Charity. We are delighted to share the verified sponsorship profile of the beneficiary you are supporting:</p>
<div style="background-color: #FAF5FF; border: 1px solid #E9D5FF; border-radius: 8px; padding: 14px 16px; margin: 14px 0;">
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Beneficiary Name:</strong> {beneficiary_name}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Sponsorship Type:</strong> {sponsorship_type}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Location:</strong> {location}</p>
  <p style="margin: 0; font-size: 14px;"><strong>Project Code:</strong> <span style="font-family: monospace; font-weight: bold; color: #A051CF;">{project_code}</span></p>
</div>
<p style="margin: 14px 0 8px 0;">You can view their official profile document and history below:</p>
<p style="margin: 0 0 16px 0;">
  <a href="{profile_link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #A051CF; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">View Profile Document</a>
</p>
<p style="margin: 0 0 6px 0; font-size: 13px; color: #475569;">Dedicated media &amp; documentation folder:<br/>
  <a href="{donor_folder_link}" target="_blank" style="color: #A051CF; font-weight: 600; text-decoration: underline;">{donor_folder_link}</a>
</p>
<p style="margin: 12px 0 0 0;">Thank you for empowering lives and driving sustainable, measurable impact.</p>""",
                "rethink"
            )
        },
        {
            "template_type": "video_update",
            "subject": "New Field Video Update for {beneficiary_name} | Rethink Charity",
            "body_html": _wrap_email_html_template(
                "New Field Video Update for {beneficiary_name}",
                """<p style="margin: 0 0 12px 0;">We are thrilled to share an exclusive field video update regarding <strong>{beneficiary_name}</strong> ({project_code})!</p>
<div style="background-color: #FAF5FF; border: 1px solid #E9D5FF; border-radius: 8px; padding: 16px; margin: 14px 0; text-align: center;">
  <p style="margin: 0 0 10px 0; font-size: 14px; font-weight: 600; color: #0F172A;">Field Footage Available</p>
  <a href="{video_link}" target="_blank" style="display: inline-block; padding: 10px 22px; background-color: #A051CF; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">&#9658; Watch Video Update</a>
</div>
<p style="margin: 12px 0 0 0;">Your continued dedication makes this transformation possible every day.</p>""",
                "rethink"
            )
        },
        {
            "template_type": "end_year_feedback",
            "subject": "Annual Impact & Progress Report for {beneficiary_name} | Rethink Charity",
            "body_html": _wrap_email_html_template(
                "Annual Impact & Progress Report for {beneficiary_name}",
                """<p style="margin: 0 0 12px 0;">We are pleased to present the annual progress report and verified impact review for <strong>{beneficiary_name}</strong> ({location}).</p>
<div style="background-color: #FAF5FF; border: 1px solid #E9D5FF; border-radius: 8px; padding: 14px 16px; margin: 14px 0;">
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Beneficiary:</strong> {beneficiary_name}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Location:</strong> {location}</p>
  <p style="margin: 0 0 10px 0; font-size: 14px;"><strong>Cycle:</strong> {sponsorship_year}</p>
  <a href="{report_link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #A051CF; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">View Annual Report PDF</a>
</div>
<p style="margin: 12px 0 0 0;">Thank you for standing with us to create transparent, lasting change.</p>""",
                "rethink"
            )
        },
        {
            "template_type": "campaign_update",
            "subject": "Campaign Sponsorship Milestone: {beneficiary_name} ({campaign_name})",
            "body_html": _wrap_email_html_template(
                "Campaign Sponsorship Milestone: {beneficiary_name} ({campaign_name})",
                """<p style="margin: 0 0 12px 0;">We are delighted to share a sponsorship milestone allocated under your campaign <strong>{campaign_name}</strong>!</p>
<div style="background-color: #FAF5FF; border: 1px solid #E9D5FF; border-radius: 8px; padding: 14px 16px; margin: 14px 0;">
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Assigned Beneficiary:</strong> {beneficiary_name}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Type:</strong> {sponsorship_type}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Location:</strong> {location}</p>
  <p style="margin: 0; font-size: 14px;"><strong>Project Code:</strong> <span style="font-family: monospace; font-weight: bold; color: #A051CF;">{project_code}</span></p>
</div>
<p style="margin: 14px 0 8px 0;">Access official profile and documents:</p>
<p style="margin: 0 0 16px 0;">
  <a href="{profile_link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #A051CF; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">View Beneficiary Profile</a>
</p>
<p style="margin: 0 0 6px 0; font-size: 13px; color: #475569;">Media folder:<br/>
  <a href="{donor_folder_link}" target="_blank" style="color: #A051CF; font-weight: 600; text-decoration: underline;">{donor_folder_link}</a>
</p>
<p style="margin: 12px 0 0 0;">Thank you to all organizers and contributors who made this possible.</p>""",
                "rethink"
            )
        },
        {
            "template_type": "renewal_notice",
            "subject": "Upcoming Sponsorship Renewal for {beneficiary_name} ({sponsorship_year})",
            "body_html": _wrap_email_html_template(
                "Upcoming Sponsorship Renewal for {beneficiary_name} ({sponsorship_year})",
                """<p style="margin: 0 0 12px 0;">As we approach the completion of this 12-month sponsorship period, we wanted to express our deepest gratitude for supporting <strong>{beneficiary_name}</strong> ({project_code}).</p>
<p style="margin: 0 0 12px 0;">Your support has provided vital stability, educational opportunities, and essential resources over this past year.</p>
<div style="background-color: #FAF5FF; border: 1px solid #E9D5FF; border-radius: 8px; padding: 14px 16px; margin: 14px 0;">
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Beneficiary:</strong> {beneficiary_name}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Sponsorship Year:</strong> {sponsorship_year}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Renewal Deadline:</strong> {renewal_deadline}</p>
  <p style="margin: 0; font-size: 14px;"><strong>Days Remaining:</strong> <span style="font-weight: bold; color: #DC2626;">{days_remaining}</span></p>
</div>
<p style="margin: 14px 0 8px 0;">You can review their latest annual feedback and media folder below:</p>
<p style="margin: 0 0 16px 0;">
  <a href="{donor_folder_link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #A051CF; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">View Annual Feedback &amp; Media</a>
</p>
<p style="margin: 12px 0 0 0;">To renew your sponsorship for the upcoming year, please reply directly to this email or visit our giving portal.</p>""",
                "rethink"
            )
        },
        {
            "template_type": "general_custom",
            "subject": "Thank You for Your Sponsorship Support | Rethink Charity",
            "body_html": _wrap_email_html_template(
                "Sponsorship Support Update & Thank You",
                """<p style="margin: 0 0 12px 0;">Dear {First_Name},</p>
<p style="margin: 0 0 12px 0;">Thank you for your generous contribution and ongoing support toward <strong>{beneficiary_name}</strong> ({project_code}).</p>
<div style="background-color: #FAF5FF; border: 1px solid #E9D5FF; border-radius: 8px; padding: 14px 16px; margin: 14px 0;">
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Supported Beneficiary:</strong> {beneficiary_name}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Sponsorship Type:</strong> {sponsorship_type}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Location:</strong> {location}</p>
  <p style="margin: 0; font-size: 14px;"><strong>Project Code:</strong> <span style="font-family: monospace; font-weight: bold; color: #A051CF;">{project_code}</span></p>
</div>
<p style="margin: 14px 0 8px 0;">You can view and follow their ongoing progress below:</p>
<p style="margin: 0 0 16px 0;">
  <a href="{donor_folder_link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #A051CF; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">View Sponsorship Folder</a>
</p>
<p style="margin: 12px 0 0 0;">Your compassion brings hope and vital care to those who need it most. Thank you for making a real difference.</p>""",
                "rethink"
            )
        }
    ],
    "iqra": [
        {
            "template_type": "profile_intro",
            "subject": "Sponsorship Profile Update: Welcome to Sponsoring {beneficiary_name} | IQRA",
            "body_html": _wrap_email_html_template(
                "Sponsorship Profile Update: Welcome to Sponsoring {beneficiary_name}",
                """<p style="margin: 0 0 12px 0;">Greetings from IQRA. May your kindness bring peace and blessings. We are honored to share the profile of the beneficiary supported by your generosity:</p>
<div style="background-color: #F0F9FF; border: 1px solid #BAE6FD; border-radius: 8px; padding: 14px 16px; margin: 14px 0;">
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Beneficiary Name:</strong> {beneficiary_name}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Sponsorship Type:</strong> {sponsorship_type}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Location:</strong> {location}</p>
  <p style="margin: 0; font-size: 14px;"><strong>Project Code:</strong> <span style="font-family: monospace; font-weight: bold; color: #0284C7;">{project_code}</span></p>
</div>
<p style="margin: 14px 0 8px 0;">You can view their official profile document and history below:</p>
<p style="margin: 0 0 16px 0;">
  <a href="{profile_link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #0284C7; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">View Profile Document</a>
</p>
<p style="margin: 0 0 6px 0; font-size: 13px; color: #475569;">Dedicated media &amp; documentation folder:<br/>
  <a href="{donor_folder_link}" target="_blank" style="color: #0284C7; font-weight: 600; text-decoration: underline;">{donor_folder_link}</a>
</p>
<p style="margin: 12px 0 0 0;">May your generous sponsorship be a source of lifelong knowledge and empowerment.</p>""",
                "iqra"
            )
        },
        {
            "template_type": "video_update",
            "subject": "New Video Update for {beneficiary_name} | IQRA",
            "body_html": _wrap_email_html_template(
                "New Video Update for {beneficiary_name}",
                """<p style="margin: 0 0 12px 0;">We are delighted to share a heartwarming video update regarding <strong>{beneficiary_name}</strong> ({project_code})!</p>
<div style="background-color: #F0F9FF; border: 1px solid #BAE6FD; border-radius: 8px; padding: 16px; margin: 14px 0; text-align: center;">
  <p style="margin: 0 0 10px 0; font-size: 14px; font-weight: 600; color: #0284C7;">Exclusive Video Footage</p>
  <a href="{video_link}" target="_blank" style="display: inline-block; padding: 10px 22px; background-color: #0284C7; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">&#9658; Watch Video Update</a>
</div>
<p style="margin: 12px 0 0 0;">Thank you for your continuous compassion and commitment to changing lives.</p>""",
                "iqra"
            )
        },
        {
            "template_type": "end_year_feedback",
            "subject": "Annual Progress & Academic Review for {beneficiary_name} | IQRA",
            "body_html": _wrap_email_html_template(
                "Annual Progress & Academic Review for {beneficiary_name}",
                """<p style="margin: 0 0 12px 0;">We are pleased to present the annual progress report and impact review for <strong>{beneficiary_name}</strong> ({location}).</p>
<div style="background-color: #F0F9FF; border: 1px solid #BAE6FD; border-radius: 8px; padding: 14px 16px; margin: 14px 0;">
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Beneficiary:</strong> {beneficiary_name}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Location:</strong> {location}</p>
  <p style="margin: 0 0 10px 0; font-size: 14px;"><strong>Cycle:</strong> {sponsorship_year}</p>
  <a href="{report_link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #0284C7; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">View Annual Report PDF</a>
</div>
<p style="margin: 12px 0 0 0;">Your sustained support brings hope, education, and security to those who need it most.</p>""",
                "iqra"
            )
        },
        {
            "template_type": "campaign_update",
            "subject": "Campaign Sponsorship Allocation: {beneficiary_name} ({campaign_name}) | IQRA",
            "body_html": _wrap_email_html_template(
                "Campaign Sponsorship Allocation: {beneficiary_name} ({campaign_name})",
                """<p style="margin: 0 0 12px 0;">We are delighted to share a sponsorship milestone allocated under your campaign <strong>{campaign_name}</strong>!</p>
<div style="background-color: #F0F9FF; border: 1px solid #BAE6FD; border-radius: 8px; padding: 14px 16px; margin: 14px 0;">
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Assigned Beneficiary:</strong> {beneficiary_name}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Type:</strong> {sponsorship_type}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Location:</strong> {location}</p>
  <p style="margin: 0; font-size: 14px;"><strong>Project Code:</strong> <span style="font-family: monospace; font-weight: bold; color: #0284C7;">{project_code}</span></p>
</div>
<p style="margin: 14px 0 8px 0;">Access official profile and documents:</p>
<p style="margin: 0 0 16px 0;">
  <a href="{profile_link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #0284C7; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">View Beneficiary Profile</a>
</p>
<p style="margin: 0 0 6px 0; font-size: 13px; color: #475569;">Media folder:<br/>
  <a href="{donor_folder_link}" target="_blank" style="color: #0284C7; font-weight: 600; text-decoration: underline;">{donor_folder_link}</a>
</p>
<p style="margin: 12px 0 0 0;">Thank you to all organizers and contributors who made this sponsorship a reality.</p>""",
                "iqra"
            )
        },
        {
            "template_type": "renewal_notice",
            "subject": "Annual Sponsorship Renewal for {beneficiary_name} ({sponsorship_year}) | IQRA",
            "body_html": _wrap_email_html_template(
                "Annual Sponsorship Renewal for {beneficiary_name} ({sponsorship_year})",
                """<p style="margin: 0 0 12px 0;">As we conclude this 12-month sponsorship period, we wanted to express our deepest gratitude for supporting <strong>{beneficiary_name}</strong> ({project_code}).</p>
<p style="margin: 0 0 12px 0;">Your contribution has nurtured education, provided security, and brought immense positive impact over this past year.</p>
<div style="background-color: #F0F9FF; border: 1px solid #BAE6FD; border-radius: 8px; padding: 14px 16px; margin: 14px 0;">
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Beneficiary:</strong> {beneficiary_name}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Sponsorship Year:</strong> {sponsorship_year}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Renewal Deadline:</strong> {renewal_deadline}</p>
  <p style="margin: 0; font-size: 14px;"><strong>Days Remaining:</strong> <span style="font-weight: bold; color: #DC2626;">{days_remaining}</span></p>
</div>
<p style="margin: 14px 0 8px 0;">You can review their latest annual feedback and media folder below:</p>
<p style="margin: 0 0 16px 0;">
  <a href="{donor_folder_link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #0284C7; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">View Annual Feedback &amp; Media</a>
</p>
<p style="margin: 12px 0 0 0;">To continue your sponsorship into the next year, please reply directly to this email or visit our giving portal.</p>""",
                "iqra"
            )
        },
        {
            "template_type": "general_custom",
            "subject": "Important Update from IQRA",
            "body_html": _wrap_email_html_template(
                "Important Update from IQRA",
                """<p style="margin: 0 0 12px 0;">{{Message_Body}}</p>""",
                "iqra"
            )
        }
    ],
    "sp": [
        {
            "template_type": "profile_intro",
            "subject": "Sponsorship Welcome: Meet {beneficiary_name} | Sisters' Project",
            "body_html": _wrap_email_html_template(
                "Sponsorship Welcome: Meet {beneficiary_name}",
                """<p style="margin: 0 0 12px 0;">Thank you for your heartfelt support and sisterhood. We are delighted to share the profile of the beneficiary you are uplifting:</p>
<div style="background-color: #FFF1F2; border: 1px solid #FECDD3; border-radius: 8px; padding: 14px 16px; margin: 14px 0;">
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Beneficiary Name:</strong> {beneficiary_name}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Sponsorship Type:</strong> {sponsorship_type}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Location:</strong> {location}</p>
  <p style="margin: 0; font-size: 14px;"><strong>Project Code:</strong> <span style="font-family: monospace; font-weight: bold; color: #BE123C;">{project_code}</span></p>
</div>
<p style="margin: 14px 0 8px 0;">You can view their official profile document and history below:</p>
<p style="margin: 0 0 16px 0;">
  <a href="{profile_link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #BE123C; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">View Profile Document</a>
</p>
<p style="margin: 0 0 6px 0; font-size: 13px; color: #475569;">Dedicated media &amp; documentation folder:<br/>
  <a href="{donor_folder_link}" target="_blank" style="color: #BE123C; font-weight: 600; text-decoration: underline;">{donor_folder_link}</a>
</p>
<p style="margin: 12px 0 0 0;">Thank you for bringing safety, dignity, and hope into their lives.</p>""",
                "sp"
            )
        },
        {
            "template_type": "video_update",
            "subject": "New Video Update for {beneficiary_name} | Sisters' Project",
            "body_html": _wrap_email_html_template(
                "New Video Update for {beneficiary_name}",
                """<p style="margin: 0 0 12px 0;">We are thrilled to share an exclusive video update regarding <strong>{beneficiary_name}</strong> ({project_code})!</p>
<div style="background-color: #FFF1F2; border: 1px solid #FECDD3; border-radius: 8px; padding: 16px; margin: 14px 0; text-align: center;">
  <p style="margin: 0 0 10px 0; font-size: 14px; font-weight: 600; color: #9F1239;">New Video Footage Available</p>
  <a href="{video_link}" target="_blank" style="display: inline-block; padding: 10px 22px; background-color: #BE123C; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">&#9658; Watch Video Update</a>
</div>
<p style="margin: 12px 0 0 0;">Thank you for your warmth, care, and generosity towards our community.</p>""",
                "sp"
            )
        },
        {
            "template_type": "end_year_feedback",
            "subject": "Annual Progress & Impact Report for {beneficiary_name} | Sisters' Project",
            "body_html": _wrap_email_html_template(
                "Annual Progress & Impact Report for {beneficiary_name}",
                """<p style="margin: 0 0 12px 0;">We are pleased to present the annual progress report and well-being review for <strong>{beneficiary_name}</strong> ({location}).</p>
<div style="background-color: #FFF1F2; border: 1px solid #FECDD3; border-radius: 8px; padding: 14px 16px; margin: 14px 0;">
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Beneficiary:</strong> {beneficiary_name}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Location:</strong> {location}</p>
  <p style="margin: 0 0 10px 0; font-size: 14px;"><strong>Cycle:</strong> {sponsorship_year}</p>
  <a href="{report_link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #BE123C; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">View Annual Report PDF</a>
</div>
<p style="margin: 12px 0 0 0;">Your sisterhood and support provide lifelong transformation and strength.</p>""",
                "sp"
            )
        },
        {
            "template_type": "campaign_update",
            "subject": "Campaign Sponsorship Update: {beneficiary_name} ({campaign_name}) | Sisters' Project",
            "body_html": _wrap_email_html_template(
                "Campaign Sponsorship Update: {beneficiary_name} ({campaign_name})",
                """<p style="margin: 0 0 12px 0;">We are delighted to share a sponsorship milestone allocated under your campaign <strong>{campaign_name}</strong>!</p>
<div style="background-color: #FFF1F2; border: 1px solid #FECDD3; border-radius: 8px; padding: 14px 16px; margin: 14px 0;">
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Assigned Beneficiary:</strong> {beneficiary_name}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Type:</strong> {sponsorship_type}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Location:</strong> {location}</p>
  <p style="margin: 0; font-size: 14px;"><strong>Project Code:</strong> <span style="font-family: monospace; font-weight: bold; color: #BE123C;">{project_code}</span></p>
</div>
<p style="margin: 14px 0 8px 0;">Access official profile and documents:</p>
<p style="margin: 0 0 16px 0;">
  <a href="{profile_link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #BE123C; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">View Beneficiary Profile</a>
</p>
<p style="margin: 0 0 6px 0; font-size: 13px; color: #475569;">Media folder:<br/>
  <a href="{donor_folder_link}" target="_blank" style="color: #BE123C; font-weight: 600; text-decoration: underline;">{donor_folder_link}</a>
</p>
<p style="margin: 12px 0 0 0;">Thank you to all organizers and supporters who made this initiative possible.</p>""",
                "sp"
            )
        },
        {
            "template_type": "renewal_notice",
            "subject": "Upcoming Sponsorship Renewal for {beneficiary_name} ({sponsorship_year}) | Sisters' Project",
            "body_html": _wrap_email_html_template(
                "Upcoming Sponsorship Renewal for {beneficiary_name} ({sponsorship_year})",
                """<p style="margin: 0 0 12px 0;">As we approach the completion of this 12-month sponsorship period, we wanted to express our heartfelt gratitude for supporting <strong>{beneficiary_name}</strong> ({project_code}).</p>
<p style="margin: 0 0 12px 0;">Your generosity has provided essential care, security, and empowerment over this past year.</p>
<div style="background-color: #FFF1F2; border: 1px solid #FECDD3; border-radius: 8px; padding: 14px 16px; margin: 14px 0;">
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Beneficiary:</strong> {beneficiary_name}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Sponsorship Year:</strong> {sponsorship_year}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Renewal Deadline:</strong> {renewal_deadline}</p>
  <p style="margin: 0; font-size: 14px;"><strong>Days Remaining:</strong> <span style="font-weight: bold; color: #DC2626;">{days_remaining}</span></p>
</div>
<p style="margin: 14px 0 8px 0;">You can review their latest annual feedback and media folder below:</p>
<p style="margin: 0 0 16px 0;">
  <a href="{donor_folder_link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #BE123C; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">View Annual Feedback &amp; Media</a>
</p>
<p style="margin: 12px 0 0 0;">To renew your sponsorship for the next year, please reply directly to this email or visit our giving portal.</p>""",
                "sp"
            )
        },
        {
            "template_type": "general_custom",
            "subject": "Important Sponsorship Update from Sisters' Project",
            "body_html": _wrap_email_html_template(
                "Important Sponsorship Update from Sisters' Project",
                """<p style="margin: 0 0 12px 0;">{{Message_Body}}</p>""",
                "sp"
            )
        }
    ],
    "sp_rethink": [
        {
            "template_type": "profile_intro",
            "subject": "Sponsorship Welcome: Meet {beneficiary_name} | Sisters' Project",
            "body_html": _wrap_email_html_template(
                "Sponsorship Welcome: Meet {beneficiary_name}",
                """<p style="margin: 0 0 12px 0;">Thank you for your heartfelt support and sisterhood. We are delighted to share the profile of the beneficiary you are uplifting:</p>
<div style="background-color: #FFF1F2; border: 1px solid #FECDD3; border-radius: 8px; padding: 14px 16px; margin: 14px 0;">
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Beneficiary Name:</strong> {beneficiary_name}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Sponsorship Type:</strong> {sponsorship_type}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Location:</strong> {location}</p>
  <p style="margin: 0; font-size: 14px;"><strong>Project Code:</strong> <span style="font-family: monospace; font-weight: bold; color: #BE123C;">{project_code}</span></p>
</div>
<p style="margin: 14px 0 8px 0;">You can view their official profile document and history below:</p>
<p style="margin: 0 0 16px 0;">
  <a href="{profile_link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #BE123C; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">View Profile Document</a>
</p>
<p style="margin: 0 0 6px 0; font-size: 13px; color: #475569;">Dedicated media &amp; documentation folder:<br/>
  <a href="{donor_folder_link}" target="_blank" style="color: #BE123C; font-weight: 600; text-decoration: underline;">{donor_folder_link}</a>
</p>
<p style="margin: 12px 0 0 0;">Thank you for bringing safety, dignity, and hope into their lives.</p>""",
                "sp_rethink"
            )
        },
        {
            "template_type": "video_update",
            "subject": "New Video Update for {beneficiary_name} | Sisters' Project",
            "body_html": _wrap_email_html_template(
                "New Video Update for {beneficiary_name}",
                """<p style="margin: 0 0 12px 0;">We are thrilled to share an exclusive video update regarding <strong>{beneficiary_name}</strong> ({project_code})!</p>
<div style="background-color: #FFF1F2; border: 1px solid #FECDD3; border-radius: 8px; padding: 16px; margin: 14px 0; text-align: center;">
  <p style="margin: 0 0 10px 0; font-size: 14px; font-weight: 600; color: #9F1239;">New Video Footage Available</p>
  <a href="{video_link}" target="_blank" style="display: inline-block; padding: 10px 22px; background-color: #BE123C; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">&#9658; Watch Video Update</a>
</div>
<p style="margin: 12px 0 0 0;">Thank you for your warmth, care, and generosity towards our community.</p>""",
                "sp_rethink"
            )
        },
        {
            "template_type": "end_year_feedback",
            "subject": "Annual Progress & Impact Report for {beneficiary_name} | Sisters' Project",
            "body_html": _wrap_email_html_template(
                "Annual Progress & Impact Report for {beneficiary_name}",
                """<p style="margin: 0 0 12px 0;">We are pleased to present the annual progress report and well-being review for <strong>{beneficiary_name}</strong> ({location}).</p>
<div style="background-color: #FFF1F2; border: 1px solid #FECDD3; border-radius: 8px; padding: 14px 16px; margin: 14px 0;">
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Beneficiary:</strong> {beneficiary_name}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Location:</strong> {location}</p>
  <p style="margin: 0 0 10px 0; font-size: 14px;"><strong>Cycle:</strong> {sponsorship_year}</p>
  <a href="{report_link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #BE123C; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">View Annual Report PDF</a>
</div>
<p style="margin: 12px 0 0 0;">Your sisterhood and support provide lifelong transformation and strength.</p>""",
                "sp_rethink"
            )
        },
        {
            "template_type": "campaign_update",
            "subject": "Campaign Sponsorship Update: {beneficiary_name} ({campaign_name}) | Sisters' Project",
            "body_html": _wrap_email_html_template(
                "Campaign Sponsorship Update: {beneficiary_name} ({campaign_name})",
                """<p style="margin: 0 0 12px 0;">We are delighted to share a sponsorship milestone allocated under your campaign <strong>{campaign_name}</strong>!</p>
<div style="background-color: #FFF1F2; border: 1px solid #FECDD3; border-radius: 8px; padding: 14px 16px; margin: 14px 0;">
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Assigned Beneficiary:</strong> {beneficiary_name}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Type:</strong> {sponsorship_type}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Location:</strong> {location}</p>
  <p style="margin: 0; font-size: 14px;"><strong>Project Code:</strong> <span style="font-family: monospace; font-weight: bold; color: #BE123C;">{project_code}</span></p>
</div>
<p style="margin: 14px 0 8px 0;">Access official profile and documents:</p>
<p style="margin: 0 0 16px 0;">
  <a href="{profile_link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #BE123C; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">View Beneficiary Profile</a>
</p>
<p style="margin: 0 0 6px 0; font-size: 13px; color: #475569;">Media folder:<br/>
  <a href="{donor_folder_link}" target="_blank" style="color: #BE123C; font-weight: 600; text-decoration: underline;">{donor_folder_link}</a>
</p>
<p style="margin: 12px 0 0 0;">Thank you to all organizers and supporters who made this initiative possible.</p>""",
                "sp_rethink"
            )
        },
        {
            "template_type": "renewal_notice",
            "subject": "Upcoming Sponsorship Renewal for {beneficiary_name} ({sponsorship_year}) | Sisters' Project",
            "body_html": _wrap_email_html_template(
                "Upcoming Sponsorship Renewal for {beneficiary_name} ({sponsorship_year})",
                """<p style="margin: 0 0 12px 0;">As we approach the completion of this 12-month sponsorship period, we wanted to express our heartfelt gratitude for supporting <strong>{beneficiary_name}</strong> ({project_code}).</p>
<p style="margin: 0 0 12px 0;">Your generosity has provided essential care, security, and empowerment over this past year.</p>
<div style="background-color: #FFF1F2; border: 1px solid #FECDD3; border-radius: 8px; padding: 14px 16px; margin: 14px 0;">
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Beneficiary:</strong> {beneficiary_name}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Sponsorship Year:</strong> {sponsorship_year}</p>
  <p style="margin: 0 0 6px 0; font-size: 14px;"><strong>Renewal Deadline:</strong> {renewal_deadline}</p>
  <p style="margin: 0; font-size: 14px;"><strong>Days Remaining:</strong> <span style="font-weight: bold; color: #DC2626;">{days_remaining}</span></p>
</div>
<p style="margin: 14px 0 8px 0;">You can review their latest annual feedback and media folder below:</p>
<p style="margin: 0 0 16px 0;">
  <a href="{donor_folder_link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #BE123C; color: #FFFFFF; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13.5px;">View Annual Feedback &amp; Media</a>
</p>
<p style="margin: 12px 0 0 0;">To renew your sponsorship for the next year, please reply directly to this email or visit our giving portal.</p>""",
                "sp_rethink"
            )
        },
        {
            "template_type": "general_custom",
            "subject": "Important Sponsorship Update from Sisters' Project",
            "body_html": _wrap_email_html_template(
                "Important Sponsorship Update from Sisters' Project",
                """<p style="margin: 0 0 12px 0;">{{Message_Body}}</p>""",
                "sp_rethink"
            )
        }
    ]
}

DEFAULT_EMAIL_TEMPLATES = DEFAULT_TEMPLATES_BY_CHARITY["rethink"]

@router.get("/email-templates")
def get_email_templates(company_id: Optional[str] = Query("rethink"), charity_theme: Optional[str] = Query(None)):
    """Returns saved email templates for the given company and charity theme, seeding defaults and purging any obsolete templates."""
    comp = (company_id or "rethink").strip().lower()
    selected_theme = (charity_theme or "").strip().lower()

    # Determine allowed charity themes based on workspace
    # SP (with Rethink collab) is under Rethink; Plain SP is under Iqra; SP is universal
    if comp == "iqra":
        allowed_themes = ["iqra", "sp"]
    elif comp == "rethink":
        allowed_themes = ["rethink", "sp_rethink"]
    elif comp == "sp":
        allowed_themes = ["sp"]
    elif comp == "all":
        allowed_themes = ["rethink", "iqra", "sp", "sp_rethink"]
    else:
        allowed_themes = [comp, "sp"]

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        
        _ensure_template_builder_columns(conn)
        # 1. Purge legacy Forgotten Women templates completely
        cur.execute("""
            DELETE FROM sponsorship_email_templates 
            WHERE body_html LIKE '%forgottenwomen%' 
               OR subject LIKE '%Forgotten Women%'
               OR body_html LIKE '%Forgotten Women%'
        """)
        conn.commit()

        # 1.5. Clean any bloated base64 data URIs to fast, hosted HTTPS logo URLs
        cur.execute("SELECT id, company_id, body_html FROM sponsorship_email_templates WHERE body_html LIKE '%data:image%'")
        for r_item in cur.fetchall():
            cid = str(r_item["company_id"]).lower()
            h = r_item["body_html"]
            if cid == "sp_rethink":
                h = re.sub(r'(<img[^>]*alt="Sisters\' Project"[^>]*src=")[^"]*(")', r'\1' + _SP_LOGO_URI + r'\2', h)
                h = re.sub(r'(<img[^>]*src=")[^"]*("[^>]*alt="Sisters\' Project")', r'\1' + _SP_LOGO_URI + r'\2', h)
                h = re.sub(r'data:image/[^;]+;base64,[^"\'\s>]+', _RETHINK_EMAIL_LOGO_URI, h)
            elif cid == "sp":
                h = re.sub(r'data:image/[^;]+;base64,[^"\'\s>]+', _SP_LOGO_URI, h)
            elif cid == "iqra":
                h = re.sub(r'data:image/[^;]+;base64,[^"\'\s>]+', _IQRA_EMAIL_LOGO_URI, h)
            else:
                h = re.sub(r'data:image/[^;]+;base64,[^"\'\s>]+', _RETHINK_EMAIL_LOGO_URI, h)
            cur.execute("UPDATE sponsorship_email_templates SET body_html = ? WHERE id = ?", (h, r_item["id"]))
        conn.commit()

        # 2. Seed defaults for any allowed theme that doesn't have templates yet
        for theme_id in allowed_themes:
            if theme_id not in DEFAULT_TEMPLATES_BY_CHARITY:
                continue
            cur.execute("SELECT COUNT(*) FROM sponsorship_email_templates WHERE LOWER(company_id) = ?", (theme_id,))
            cnt = cur.fetchone()[0]
            if cnt == 0:
                for dt in DEFAULT_TEMPLATES_BY_CHARITY[theme_id]:
                    cur.execute("""
                        INSERT INTO sponsorship_email_templates (company_id, template_type, subject, body_html)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(company_id, template_type) DO NOTHING
                    """, (theme_id, dt["template_type"], dt["subject"], dt["body_html"]))
                conn.commit()

        # 3. Query templates
        if selected_theme and selected_theme in allowed_themes:
            cur.execute("""
                SELECT id, company_id, template_type, subject, body_html, builder_json
                FROM sponsorship_email_templates 
                WHERE LOWER(company_id) = ?
                ORDER BY id ASC
            """, (selected_theme,))
        else:
            placeholders = ",".join("?" for _ in allowed_themes)
            cur.execute(f"""
                SELECT id, company_id, template_type, subject, body_html, builder_json
                FROM sponsorship_email_templates 
                WHERE LOWER(company_id) IN ({placeholders})
                ORDER BY CASE LOWER(company_id) WHEN ? THEN 0 ELSE 1 END, id ASC
            """, (*allowed_themes, comp))

        rows = []
        for r in cur.fetchall():
            d = dict(r)
            try:
                d["builder_json"] = json.loads(d["builder_json"]) if d.get("builder_json") else None
            except (TypeError, ValueError):
                d["builder_json"] = None
            cid = str(d.get("company_id", "")).lower()
            if cid == "sp_rethink":
                d["charity_theme"] = "sp"
                d["charity_name"] = "Sisters' Project"
                d["charity_short"] = "SP"
            else:
                theme_meta = CHARITY_THEMES_CONFIG.get(cid, {})
                d["charity_theme"] = cid
                d["charity_name"] = theme_meta.get("name", cid.upper())
                d["charity_short"] = theme_meta.get("short_name", cid.upper())
            rows.append(d)

        themes_meta = []
        for tid in allowed_themes:
            if tid == "sp_rethink":
                themes_meta.append({
                    "id": "sp",
                    "name": "Sisters' Project",
                    "short_name": "SP",
                    "accent_color": CHARITY_THEMES_CONFIG["sp"]["accent_color"],
                    "contact_email": CHARITY_THEMES_CONFIG["sp"]["contact_email"],
                    "website_url": CHARITY_THEMES_CONFIG["sp"]["website_url"],
                    "website_display": CHARITY_THEMES_CONFIG["sp"]["website_display"]
                })
            elif tid in CHARITY_THEMES_CONFIG:
                themes_meta.append({
                    "id": tid, 
                    "name": CHARITY_THEMES_CONFIG[tid]["name"], 
                    "short_name": CHARITY_THEMES_CONFIG[tid]["short_name"],
                    "accent_color": CHARITY_THEMES_CONFIG[tid]["accent_color"],
                    "contact_email": CHARITY_THEMES_CONFIG[tid]["contact_email"],
                    "website_url": CHARITY_THEMES_CONFIG[tid]["website_url"],
                    "website_display": CHARITY_THEMES_CONFIG[tid]["website_display"]
                })

        return {
            "templates": rows,
            "available_themes": themes_meta,
            "active_workspace": comp,
            "selected_theme": selected_theme or (comp if comp in allowed_themes else allowed_themes[0])
        }
    finally:
        conn.close()

@router.post("/email-templates")
def update_email_template(payload: TemplateUpdateRequest):
    """Saves or updates an email template under the specified charity theme."""
    comp = (payload.company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        _ensure_template_builder_columns(conn)
        cur = conn.cursor()
        builder = payload.builder_json
        if builder is not None and not isinstance(builder, str):
            builder = json.dumps(builder, separators=(",", ":"))
        if builder and len(builder) > 2_000_000:
            raise HTTPException(status_code=400, detail="This template is too large to save.")
        new_type = payload.template_type.strip()
        orig_type = (payload.original_template_type or "").strip()

        # If payload.id or original_template_type was provided, find existing row to update
        target_id = payload.id
        if not target_id and orig_type:
            cur.execute("SELECT id FROM sponsorship_email_templates WHERE LOWER(company_id) = ? AND template_type = ?", (comp, orig_type))
            found = cur.fetchone()
            if found:
                target_id = found[0]

        if target_id:
            # Check for conflict if renaming to another template's type in this charity
            cur.execute("SELECT id FROM sponsorship_email_templates WHERE LOWER(company_id) = ? AND template_type = ? AND id != ?", (comp, new_type, target_id))
            conflict = cur.fetchone()
            if conflict:
                raise HTTPException(status_code=400, detail=f"Another template named '{new_type}' already exists for this charity.")

            cur.execute("""
                UPDATE sponsorship_email_templates
                SET template_type = ?,
                    subject = ?,
                    body_html = ?,
                    builder_json = ?
                WHERE id = ? AND LOWER(company_id) = ?
            """, (new_type, payload.subject.strip(), payload.body_html.strip(), builder, target_id, comp))
            conn.commit()
            log_event("template.saved", category="template", company_id=_owner_company(comp), theme=comp,
                      template=new_type, subject=payload.subject,
                      message=f"Template {target_id} updated to '{new_type}' for {comp}")
            return {"status": "success", "message": f"Email template '{new_type}' saved successfully for charity '{comp}'."}
        else:
            # the first time a template is saved from the builder, keep its original HTML (legacy_html) to roll back to
            cur.execute("""
                INSERT INTO sponsorship_email_templates (company_id, template_type, subject, body_html, builder_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(company_id, template_type) DO UPDATE SET
                    legacy_html = COALESCE(sponsorship_email_templates.legacy_html,
                                           CASE WHEN sponsorship_email_templates.builder_json IS NULL AND excluded.builder_json IS NOT NULL
                                                THEN sponsorship_email_templates.body_html END),
                    subject = excluded.subject,
                    body_html = excluded.body_html,
                    builder_json = excluded.builder_json
            """, (comp, new_type, payload.subject.strip(), payload.body_html.strip(), builder))
            conn.commit()
            log_event("template.saved", category="template", company_id=_owner_company(comp), theme=comp,
                      template=new_type, subject=payload.subject,
                      message=f"Template '{new_type}' saved for {comp}")
            return {"status": "success", "message": f"Email template '{new_type}' saved successfully for charity '{comp}'."}
    finally:
        conn.close()

@router.delete("/email-templates/{template_id}")
def delete_email_template(template_id: int):
    """Deletes an email template."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM sponsorship_email_templates WHERE id = ?", (template_id,))
        conn.commit()
        log_event("template.deleted", category="template", level="warning", template_id=template_id,
                  message=f"Template {template_id} deleted")
        return {"status": "success", "message": "Email template deleted."}
    finally:
        conn.close()

@router.post("/email-templates/reset-defaults")
def reset_default_email_templates(company_id: Optional[str] = Query("rethink"), charity_theme: Optional[str] = Query(None)):
    """Resets email templates to standard organization defaults for the specified charity theme or workspace."""
    comp = (company_id or "rethink").strip().lower()
    theme = (charity_theme or "").strip().lower()

    if theme == "sp":
        targets = ["sp_rethink"] if comp == "rethink" else ["sp"]
    elif theme in DEFAULT_TEMPLATES_BY_CHARITY:
        targets = [theme]
    elif comp == "iqra":
        targets = ["iqra", "sp"]
    elif comp == "rethink":
        targets = ["rethink", "sp_rethink"]
    elif comp == "all":
        targets = ["rethink", "iqra", "sp", "sp_rethink"]
    else:
        targets = [comp] if comp in DEFAULT_TEMPLATES_BY_CHARITY else ["rethink"]

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        for target in targets:
            for dt in DEFAULT_TEMPLATES_BY_CHARITY.get(target, []):
                cur.execute("""
                    INSERT INTO sponsorship_email_templates (company_id, template_type, subject, body_html)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(company_id, template_type) DO UPDATE SET
                        subject = excluded.subject,
                        body_html = excluded.body_html
                """, (target, dt["template_type"], dt["subject"], dt["body_html"]))
        conn.commit()
        return {"status": "success", "message": f"Templates reset to default settings for: {', '.join(targets)}."}
    finally:
        conn.close()

@router.get("/allocations/{allocation_id}/communications")
def get_allocation_communications(allocation_id: int):
    """Returns full two-way communication thread for an allocation with live sync and email tracking metrics."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT company_id FROM sponsorship_allocations WHERE id = ?", (allocation_id,))
        a_row = cur.fetchone()
        if a_row:
            sync_inbound_outlook_replies(a_row["company_id"])

        cur.execute("""
            SELECT c.id, c.allocation_id, c.company_id, c.direction, c.message_id,
                   c.thread_id, c.subject, c.body, c.sender_email, c.recipient_email, c.sent_at,
                   c.tracking_id, c.delivery_status, c.opened_at, c.open_count, c.replied_at,
                   c.last_opened_ip, c.last_opened_user_agent,
                   c.allocation_donor_id, c.template_type, d.donor_name
            FROM sponsorship_communications c
            LEFT JOIN sponsorship_allocation_donors d ON d.id = c.allocation_donor_id
            WHERE c.allocation_id = ?
            ORDER BY c.sent_at ASC
        """, (allocation_id,))
        rows = [dict(r) for r in cur.fetchall()]
        return {"allocation_id": allocation_id, "count": len(rows), "messages": rows}
    finally:
        conn.close()

# ==========================================
# 10. REAL-TIME EMAIL TRACKING ENDPOINTS
# ==========================================

@router.get("/email-tracking/pixel/{tracking_id}")
def email_tracking_pixel(tracking_id: str, request: Request):
    """
    Tracking pixel hit by email client when donor opens the email.
    Records delivery_status = 'opened', increments open_count, and sets opened_at.
    """
    client_ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")
    
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE sponsorship_communications
            SET delivery_status = CASE WHEN delivery_status = 'replied' THEN 'replied' ELSE 'opened' END,
                open_count = COALESCE(open_count, 0) + 1,
                opened_at = COALESCE(opened_at, CURRENT_TIMESTAMP),
                last_opened_ip = ?,
                last_opened_user_agent = ?
            WHERE tracking_id = ?
        """, (client_ip, user_agent, tracking_id))
        try:  # direct (non-allocation) emails sent from the Donors / email campaigns screens
            cur.execute("""UPDATE crm_email_messages SET open_count = COALESCE(open_count, 0) + 1,
                               opened_at = COALESCE(opened_at, CURRENT_TIMESTAMP) WHERE tracking_id = ?""", (tracking_id,))
        except sqlite3.OperationalError:
            pass
        
        # Update allocation's communication_status if not yet replied
        cur.execute("""
            SELECT allocation_id, subject FROM sponsorship_communications WHERE tracking_id = ?
        """, (tracking_id,))
        row = cur.fetchone()
        if row:
            alloc_id = row[0]
            first_open = cur.execute("SELECT open_count, company_id, recipient_email FROM sponsorship_communications WHERE tracking_id = ?",
                                     (tracking_id,)).fetchone()
            if first_open and first_open[0] == 1:  # log the first open only; repeats are counted in the table
                log_event("email.opened", category="email", company_id=first_open[1], allocation_id=alloc_id,
                          recipient=first_open[2], subject=row[1], tracking_id=tracking_id,
                          message=f"Email opened by {first_open[2]}")
            cur.execute("""
                UPDATE sponsorship_allocations
                SET communication_status = 'Email Opened'
                WHERE id = ? AND communication_status NOT IN ('Donor Replied', 'In Conversation')
            """, (alloc_id,))
            
        conn.commit()
    except Exception as e:
        logger.error(f"Error recording email open for {tracking_id}: {e}")
    finally:
        conn.close()

    return Response(
        content=TRANSPARENT_1PX_GIF,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

@router.get("/email-tracking/status/{tracking_id}")
def get_email_tracking_status(tracking_id: str):
    """Returns real-time delivery and engagement status for a specific tracking ID."""
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, allocation_id, company_id, subject, sender_email,
                   recipient_email, sent_at, tracking_id, delivery_status,
                   opened_at, open_count, replied_at, last_opened_ip, last_opened_user_agent
            FROM sponsorship_communications
            WHERE tracking_id = ?
        """, (tracking_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tracking record not found")
        return dict(row)
    finally:
        conn.close()


# ==========================================
# 11. SPONSORSHIP OVERDUE ALERTS & ENGINE (WITH IN-MEMORY CACHING & DISMISSALS)
# ==========================================

_OVERDUE_CACHE = {}  # company_id -> { "timestamp": float, "donors": [...], "campaigns": [...] }
_OVERDUE_CACHE_LOCK = threading.Lock()
_OVERDUE_CACHE_TTL = 3600.0  # 1 hour high-performance in-memory cache

def invalidate_overdue_cache(company_id: Optional[str] = None):
    """Invalidates the in-memory cache and persistent SQLite cache across all workers."""
    global _OVERDUE_CACHE
    with _OVERDUE_CACHE_LOCK:
        if company_id:
            cid = str(company_id).strip().lower()
            _OVERDUE_CACHE.pop(cid, None)
            _OVERDUE_CACHE.pop("all", None)
        else:
            _OVERDUE_CACHE.clear()

    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS sponsorship_overdue_cache (company_id TEXT PRIMARY KEY, data_json TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        if company_id:
            cid = str(company_id).strip().lower()
            cur.execute("DELETE FROM sponsorship_overdue_cache WHERE company_id IN (?, 'all')", (cid,))
        else:
            cur.execute("DELETE FROM sponsorship_overdue_cache")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Error clearing sqlite overdue cache: {e}")


def get_all_overdue_data(company_id: str = "rethink", force_refresh: bool = False):
    """
    Computes or retrieves from cache all unallocated donors and campaigns for the company.
    Filters out any dismissed false positives stored in sponsorship_alert_dismissals.
    Subsequent calls execute in < 1ms from memory, and < 3ms across separate uvicorn workers.
    """
    comp = (company_id or "rethink").strip().lower()
    now_ts = time.time()
    # Valid only for the exact data it was built from (any process's writes change the token) and today.
    from core.cache import version_token
    token = version_token(["donations", "classification", "tracker", "fundraisers"], comp) + time.strftime("%Y%m%d", time.gmtime())

    # 1. First-tier fast in-memory cache check (<1ms)
    with _OVERDUE_CACHE_LOCK:
        cached = _OVERDUE_CACHE.get(comp)
        if not force_refresh and cached and cached.get("token") == token and (now_ts - cached["timestamp"] < _OVERDUE_CACHE_TTL):
            return cached["donors"], cached["campaigns"]

    # 2. Second-tier cross-worker persistent SQLite cache (~2ms)
    if not force_refresh:
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS sponsorship_overdue_cache (company_id TEXT PRIMARY KEY, data_json TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            cur.execute("SELECT data_json, strftime('%s', updated_at) AS updated_ts FROM sponsorship_overdue_cache WHERE company_id = ?", (comp,))
            row = cur.fetchone()
            conn.close()
            if row and row["data_json"]:
                up_ts = float(row["updated_ts"] or 0)
                parsed = json.loads(row["data_json"])
                if now_ts - up_ts < _OVERDUE_CACHE_TTL and parsed.get("token") == token:
                    donors_db = parsed.get("donors", [])
                    campaigns_db = parsed.get("campaigns", [])
                    with _OVERDUE_CACHE_LOCK:
                        _OVERDUE_CACHE[comp] = {
                            "token": token,
                            "timestamp": up_ts,
                            "donors": donors_db,
                            "campaigns": campaigns_db
                        }
                    return donors_db, campaigns_db
        except Exception as e:
            logger.warning(f"Error reading sqlite overdue cache: {e}")

    # 3. Cache Miss / Force Refresh: Compute from qualifying datasets
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        if comp != "all":
            cur.execute("SELECT entity_type, entity_id, sponsorship_type FROM sponsorship_alert_dismissals WHERE company_id = ?", (comp,))
        else:
            cur.execute("SELECT entity_type, entity_id, sponsorship_type FROM sponsorship_alert_dismissals")
        dismissed_set = {(r["entity_type"].strip().lower(), str(r["entity_id"]).strip().lower(), str(r["sponsorship_type"]).strip().lower()) for r in cur.fetchall()}
    finally:
        conn.close()

    all_donors = []
    all_campaigns = []
    for st in ["Orphan", "Hafiz", "Widow", "Ex-Prisoner"]:
        try:
            d_res = get_qualifying_donors(company_id=comp, sponsorship_type=st)
            for d in d_res.get("donors", []):
                rem = d.get("remaining_slots", 0)
                tot = d.get("total_donated", 0.0)
                did = str(d.get("donor_id", "")).strip().lower()
                if ("donor", did, st.lower()) in dismissed_set:
                    continue
                # Overdue = earned a slot (cumulative >= 80% of target) that is still not allocated.
                # Donors below the threshold are not owed a beneficiary yet, so they are not overdue.
                is_unallocated = rem > 0 and bool(d.get("is_threshold_reached")) and (
                    d.get("is_manual") or d.get("eligible_since"))
                if is_unallocated:
                    d_copy = dict(d)
                    d_copy["sponsorship_type"] = st
                    w_days = d.get("waiting_days", 0)
                    if w_days >= 90:
                        d_copy["severity"] = "critical"
                    elif w_days >= 60:
                        d_copy["severity"] = "urgent"
                    else:
                        d_copy["severity"] = "warning"
                    all_donors.append(d_copy)
        except Exception as e:
            logger.warning(f"Error fetching qualifying donors for {st}: {e}")

        try:
            c_res = get_qualifying_campaigns(company_id=comp, sponsorship_type=st)
            for c in c_res.get("campaigns", []):
                rem = c.get("remaining_slots", 0)
                tot = c.get("total_raised", 0.0)
                cid = str(c.get("campaign_name", "")).strip().lower()
                if ("campaign", cid, st.lower()) in dismissed_set:
                    continue
                is_unallocated = rem > 0 and bool(c.get("eligible_since"))
                if is_unallocated:
                    c_copy = dict(c)
                    c_copy["sponsorship_type"] = st
                    w_days = c.get("waiting_days", 0)
                    if w_days >= 90:
                        c_copy["severity"] = "critical"
                    elif w_days >= 60:
                        c_copy["severity"] = "urgent"
                    else:
                        c_copy["severity"] = "warning"
                    all_campaigns.append(c_copy)
        except Exception as e:
            logger.warning(f"Error fetching qualifying campaigns for {st}: {e}")

    # Deduplicate in case a donor or campaign appears across multiple queries
    dedup_d = {}
    for d in all_donors:
        k = f"{d.get('donor_id')}_{d.get('sponsorship_type')}"
        if k not in dedup_d or d.get("waiting_days", 0) > dedup_d[k].get("waiting_days", 0):
            dedup_d[k] = d
    final_donors = sorted(list(dedup_d.values()), key=lambda x: x.get("waiting_days", 0), reverse=True)

    dedup_c = {}
    for c in all_campaigns:
        k = f"{c.get('campaign_name')}_{c.get('sponsorship_type')}"
        if k not in dedup_c or c.get("waiting_days", 0) > dedup_c[k].get("waiting_days", 0):
            dedup_c[k] = c
    final_campaigns = sorted(list(dedup_c.values()), key=lambda x: x.get("waiting_days", 0), reverse=True)

    with _OVERDUE_CACHE_LOCK:
        _OVERDUE_CACHE[comp] = {
            "token": token,
            "timestamp": now_ts,
            "donors": final_donors,
            "campaigns": final_campaigns
        }

    # Save to persistent SQLite cache across all worker processes
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS sponsorship_overdue_cache (company_id TEXT PRIMARY KEY, data_json TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        data_str = json.dumps({"token": token, "donors": final_donors, "campaigns": final_campaigns}, default=str)
        cur.execute("""
            INSERT INTO sponsorship_overdue_cache (company_id, data_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(company_id) DO UPDATE SET data_json = excluded.data_json, updated_at = CURRENT_TIMESTAMP
        """, (comp, data_str))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Error saving to sqlite overdue cache: {e}")

    return final_donors, final_campaigns


def _get_all_overdue_donors_data(
    company_id: str = "rethink",
    min_days: int = 30,
    sponsorship_type: Optional[str] = None,
    target_status: Optional[str] = None,
    classification: Optional[str] = None,
    search: Optional[str] = None,
    force_refresh: bool = False
):
    donors, _ = get_all_overdue_data(company_id=company_id, force_refresh=force_refresh)
    st_filter = sponsorship_type.strip().lower() if sponsorship_type and sponsorship_type.lower() != "all" else None
    cls_filter = classification.strip().lower() if classification and classification.lower() != "all" else None
    search_low = search.strip().lower() if search and search.strip() else None

    filtered = []
    for d in donors:
        if d.get("waiting_days", 0) < min_days:
            continue
        if st_filter and d.get("sponsorship_type", "").lower() != st_filter:
            continue
        if cls_filter and str(d.get("classification") or "").strip().lower() != cls_filter:
            continue
        if target_status and target_status.lower() != "all":
            ts = target_status.strip().lower()
            if ts in ["target_reached", "reached"] and not d.get("is_target_reached"):
                continue
            elif ts in ["threshold_reached"] and not d.get("is_threshold_reached"):
                continue
            elif ts in ["below_threshold", "below_target", "partial"] and d.get("is_threshold_reached"):
                continue
        if search_low:
            name = str(d.get("donor_name", "")).lower()
            em = str(d.get("donor_email", "")).lower()
            did = str(d.get("donor_id", "")).lower()
            ph = str(d.get("donor_phone", "")).lower()
            if (search_low not in name and search_low not in em and 
                search_low not in did and search_low not in ph):
                continue
        filtered.append(d)
    return filtered


def _get_all_overdue_campaigns_data(
    company_id: str = "rethink",
    min_days: int = 30,
    sponsorship_type: Optional[str] = None,
    target_status: Optional[str] = None,
    classification: Optional[str] = None,
    search: Optional[str] = None,
    force_refresh: bool = False
):
    _, campaigns = get_all_overdue_data(company_id=company_id, force_refresh=force_refresh)
    st_filter = sponsorship_type.strip().lower() if sponsorship_type and sponsorship_type.lower() != "all" else None
    cls_filter = classification.strip().lower() if classification and classification.lower() != "all" else None
    search_low = search.strip().lower() if search and search.strip() else None

    filtered = []
    for c in campaigns:
        if c.get("waiting_days", 0) < min_days:
            continue
        if st_filter and c.get("sponsorship_type", "").lower() != st_filter:
            continue
        if cls_filter and str(c.get("classification") or "").strip().lower() != cls_filter:
            continue
        if target_status and target_status.lower() != "all":
            ts = target_status.strip().lower()
            if ts in ["target_reached", "reached"] and not c.get("is_target_reached"):
                continue
            elif ts in ["threshold_reached"] and not c.get("is_threshold_reached"):
                continue
            elif ts in ["below_threshold", "below_target", "partial"] and c.get("is_threshold_reached"):
                continue
        if search_low:
            cname = str(c.get("campaign_name", "")).lower()
            comm = str(c.get("community_name", "")).lower()
            org_n = str(c.get("organizer_name", "")).lower()
            org_e = str(c.get("organizer_email", "")).lower()
            if (search_low not in cname and search_low not in comm and 
                search_low not in org_n and search_low not in org_e):
                continue
        filtered.append(c)
    return filtered


@router.get("/overdue-summary")
def get_overdue_summary(
    company_id: Optional[str] = Query("rethink"),
    threshold_days: Optional[int] = Query(None),
    force_refresh: Optional[bool] = Query(False)
):
    """Returns top-level metrics on unallocated sponsorship capacity and age with in-memory caching."""
    comp = (company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT threshold_days FROM sponsorship_alert_settings WHERE company_id = ?", (comp,))
        row = cur.fetchone()
        default_days = row["threshold_days"] if row else 30
        
        if comp != "all":
            cur.execute("SELECT COUNT(*) AS cnt FROM sponsorship_alert_dismissals WHERE company_id = ?", (comp,))
        else:
            cur.execute("SELECT COUNT(*) AS cnt FROM sponsorship_alert_dismissals")
        d_cnt_row = cur.fetchone()
        dismissals_count = d_cnt_row["cnt"] if d_cnt_row else 0
    finally:
        conn.close()

    eff_days = threshold_days if threshold_days is not None and threshold_days > 0 else default_days

    donors = _get_all_overdue_donors_data(company_id=comp, min_days=eff_days, force_refresh=force_refresh)
    campaigns = _get_all_overdue_campaigns_data(company_id=comp, min_days=eff_days, force_refresh=force_refresh)

    total_donors = len(donors)
    total_campaigns = len(campaigns)
    total_slots = sum(d.get("remaining_slots", 0) for d in donors) + sum(c.get("remaining_slots", 0) for c in campaigns)

    max_donor_w = max([d.get("waiting_days", 0) for d in donors], default=0)
    max_camp_w = max([c.get("waiting_days", 0) for c in campaigns], default=0)
    longest_waiting = max(max_donor_w, max_camp_w)

    by_type = {}
    for st in ["Orphan", "Hafiz", "Widow", "Ex-Prisoner"]:
        st_donors = [d for d in donors if d.get("sponsorship_type") == st]
        st_camps = [c for c in campaigns if c.get("sponsorship_type") == st]
        by_type[st] = {
            "donors_count": len(st_donors),
            "campaigns_count": len(st_camps),
            "unallocated_slots": sum(d.get("remaining_slots", 0) for d in st_donors) + sum(c.get("remaining_slots", 0) for c in st_camps)
        }

    by_severity = {
        "critical": len([d for d in donors if d.get("severity") == "critical"]) + len([c for c in campaigns if c.get("severity") == "critical"]),
        "urgent": len([d for d in donors if d.get("severity") == "urgent"]) + len([c for c in campaigns if c.get("severity") == "urgent"]),
        "warning": len([d for d in donors if d.get("severity") == "warning"]) + len([c for c in campaigns if c.get("severity") == "warning"])
    }

    by_target_status = {
        "target_reached": len([d for d in donors if d.get("is_target_reached")]) + len([c for c in campaigns if c.get("is_target_reached")]),
        "threshold_reached": len([d for d in donors if d.get("is_threshold_reached") and not d.get("is_target_reached")]) + len([c for c in campaigns if c.get("is_threshold_reached") and not c.get("is_target_reached")]),
        "below_threshold": len([d for d in donors if not d.get("is_threshold_reached")]) + len([c for c in campaigns if not c.get("is_threshold_reached")])
    }

    return {
        "company_id": comp,
        "threshold_days": eff_days,
        "total_overdue_donors": total_donors,
        "total_overdue_campaigns": total_campaigns,
        "total_unallocated_slots": total_slots,
        "longest_waiting_days": longest_waiting,
        "dismissals_count": dismissals_count,
        "by_type": by_type,
        "by_severity": by_severity,
        "by_target_status": by_target_status
    }


def _overdue_extra_filters(rows: List[Dict[str, Any]], amount_key: str, earned_from=None, earned_to=None, last_gift_from=None,
                           last_gift_to=None, max_days=None, min_slots=None, min_amount=None, max_amount=None) -> List[Dict[str, Any]]:
    """Overdue alerts: when the slot was earned (eligible_since), last gift date, waiting at most N days, minimum
    unallocated slots and amount range. Dates compare as YYYY-MM-DD text."""
    def val(x):
        x = _unwrap_param(x, None)
        return None if x in (None, "") else x
    ef, et, lf, lt = (str(val(v))[:10] if val(v) else None for v in (earned_from, earned_to, last_gift_from, last_gift_to))
    md, ms, mn, mx = (val(v) for v in (max_days, min_slots, min_amount, max_amount))
    out = []
    for r in rows:
        earned = str(r.get("eligible_since") or r.get("oldest_donation_date") or "")[:10]
        last = str(r.get("latest_donation_date") or "")[:10]
        amount = float(r.get(amount_key) or 0)
        if ef and (not earned or earned < ef):
            continue
        if et and (not earned or earned > et):
            continue
        if lf and (not last or last < lf):
            continue
        if lt and (not last or last > lt):
            continue
        if md is not None and int(r.get("waiting_days") or 0) > int(md):
            continue
        if ms is not None and int(r.get("remaining_slots") or 0) < int(ms):
            continue
        if mn is not None and amount < float(mn):
            continue
        if mx is not None and amount > float(mx):
            continue
        out.append(r)
    return out


@router.get("/overdue-donors")
def get_overdue_donors(
    company_id: Optional[str] = Query("rethink"),
    sponsorship_type: Optional[str] = Query("all"),
    target_status: Optional[str] = Query("all"),
    classification: Optional[str] = Query(None),
    min_days: Optional[int] = Query(30),
    severity: Optional[str] = Query("all"),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=50000),
    all_records: Optional[bool] = Query(False),
    force_refresh: Optional[bool] = Query(False),
    earned_from: Optional[str] = Query(None, description="slot earned on/after (YYYY-MM-DD)"),
    earned_to: Optional[str] = Query(None),
    last_gift_from: Optional[str] = Query(None),
    last_gift_to: Optional[str] = Query(None),
    max_days: Optional[int] = Query(None, description="waiting at most this many days"),
    min_slots: Optional[int] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None),
):
    comp = _unwrap_param(company_id, "rethink").strip().lower()
    raw_days = _unwrap_param(min_days, 30)
    try:
        days = int(raw_days) if raw_days is not None and int(raw_days) >= 0 else 30
    except (ValueError, TypeError):
        days = 30
    s_type = _unwrap_param(sponsorship_type, "all")
    t_status = _unwrap_param(target_status, "all")
    cls_param = _unwrap_param(classification, None)
    sev = _unwrap_param(severity, "all")
    srch = _unwrap_param(search, None)
    pg = int(_unwrap_param(page, 1))
    psz = int(_unwrap_param(page_size, 25))
    all_rec = _parse_bool(all_records, False)
    f_ref = _parse_bool(force_refresh, False)

    all_donors = _get_all_overdue_donors_data(
        company_id=comp,
        min_days=days,
        sponsorship_type=s_type,
        target_status=t_status,
        classification=cls_param,
        search=srch,
        force_refresh=f_ref
    )

    if sev and sev.lower() != "all":
        all_donors = [d for d in all_donors if d.get("severity") == sev.lower().strip()]
    all_donors = _overdue_extra_filters(all_donors, "total_donated", earned_from, earned_to, last_gift_from, last_gift_to,
                                        max_days, min_slots, min_amount, max_amount)

    total = len(all_donors)
    if all_rec:
        page_records = all_donors
        return {
            "company_id": comp,
            "total_records": total,
            "page": 1,
            "page_size": total,
            "total_pages": 1,
            "records": page_records
        }

    start_idx = (pg - 1) * psz
    end_idx = start_idx + psz
    page_records = all_donors[start_idx:end_idx]

    return {
        "company_id": comp,
        "total_records": total,
        "page": pg,
        "page_size": psz,
        "total_pages": max(1, (total + psz - 1) // psz),
        "records": page_records
    }


@router.get("/overdue-campaigns")
def get_overdue_campaigns(
    company_id: Optional[str] = Query("rethink"),
    sponsorship_type: Optional[str] = Query("all"),
    target_status: Optional[str] = Query("all"),
    classification: Optional[str] = Query(None),
    min_days: Optional[int] = Query(30),
    severity: Optional[str] = Query("all"),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=50000),
    all_records: Optional[bool] = Query(False),
    force_refresh: Optional[bool] = Query(False),
    earned_from: Optional[str] = Query(None, description="slot earned on/after (YYYY-MM-DD)"),
    earned_to: Optional[str] = Query(None),
    last_gift_from: Optional[str] = Query(None),
    last_gift_to: Optional[str] = Query(None),
    max_days: Optional[int] = Query(None, description="waiting at most this many days"),
    min_slots: Optional[int] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None),
):
    comp = _unwrap_param(company_id, "rethink").strip().lower()
    raw_days = _unwrap_param(min_days, 30)
    try:
        days = int(raw_days) if raw_days is not None and int(raw_days) >= 0 else 30
    except (ValueError, TypeError):
        days = 30
    s_type = _unwrap_param(sponsorship_type, "all")
    t_status = _unwrap_param(target_status, "all")
    cls_param = _unwrap_param(classification, None)
    sev = _unwrap_param(severity, "all")
    srch = _unwrap_param(search, None)
    pg = int(_unwrap_param(page, 1))
    psz = int(_unwrap_param(page_size, 25))
    all_rec = _parse_bool(all_records, False)
    f_ref = _parse_bool(force_refresh, False)

    all_campaigns = _get_all_overdue_campaigns_data(
        company_id=comp,
        min_days=days,
        sponsorship_type=s_type,
        target_status=t_status,
        classification=cls_param,
        search=srch,
        force_refresh=f_ref
    )

    if sev and sev.lower() != "all":
        all_campaigns = [c for c in all_campaigns if c.get("severity") == sev.lower().strip()]
    all_campaigns = _overdue_extra_filters(all_campaigns, "total_raised", earned_from, earned_to, last_gift_from, last_gift_to,
                                           max_days, min_slots, min_amount, max_amount)

    total = len(all_campaigns)
    if all_rec:
        page_records = all_campaigns
        return {
            "company_id": comp,
            "total_records": total,
            "page": 1,
            "page_size": total,
            "total_pages": 1,
            "records": page_records
        }

    start_idx = (pg - 1) * psz
    end_idx = start_idx + psz
    page_records = all_campaigns[start_idx:end_idx]

    return {
        "company_id": comp,
        "total_records": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "records": page_records
    }


@router.post("/overdue-dismiss")
def dismiss_overdue_alert(payload: DismissOverdueRequest):
    """Marks a donor or campaign alert as dismissed / false positive."""
    comp = (payload.company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO sponsorship_alert_dismissals 
            (company_id, entity_type, entity_id, entity_name, sponsorship_type, reason, dismissed_by, dismissed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            comp,
            payload.entity_type.strip().lower(),
            str(payload.entity_id).strip().lower(),
            payload.entity_name or payload.entity_id,
            payload.sponsorship_type.strip(),
            payload.reason or "False positive",
            payload.dismissed_by or "Staff"
        ))
        conn.commit()
    finally:
        conn.close()
    invalidate_overdue_cache(comp)
    return {"status": "success", "message": f"Successfully dismissed {payload.entity_name or payload.entity_id} from overdue alerts."}


@router.post("/overdue-undismiss")
def undismiss_overdue_alert(payload: UndismissOverdueRequest):
    """Restores a previously dismissed alert back into active tracking."""
    comp = (payload.company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM sponsorship_alert_dismissals 
            WHERE company_id = ? AND entity_type = ? AND entity_id = ? AND LOWER(sponsorship_type) = LOWER(?)
        """, (
            comp,
            payload.entity_type.strip().lower(),
            str(payload.entity_id).strip().lower(),
            payload.sponsorship_type.strip()
        ))
        conn.commit()
    finally:
        conn.close()
    invalidate_overdue_cache(comp)
    return {"status": "success", "message": f"Successfully restored {payload.entity_id} to active overdue alerts."}


@router.get("/overdue-dismissals")
def get_overdue_dismissals(company_id: Optional[str] = Query("rethink")):
    """Returns list of dismissed false positives."""
    comp = (company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        if comp != "all":
            cur.execute("SELECT * FROM sponsorship_alert_dismissals WHERE company_id = ? ORDER BY dismissed_at DESC", (comp,))
        else:
            cur.execute("SELECT * FROM sponsorship_alert_dismissals ORDER BY dismissed_at DESC")
        rows = [dict(r) for r in cur.fetchall()]
        return {"company_id": comp, "dismissals": rows, "count": len(rows)}
    finally:
        conn.close()


@router.get("/overdue-settings")
def get_overdue_settings(company_id: Optional[str] = Query("rethink")):
    comp = (company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT company_id, threshold_days, staff_emails, digest_frequency, last_digest_sent_at, digest_filters FROM sponsorship_alert_settings WHERE company_id = ?", (comp,))
        row = cur.fetchone()
        if not row:
            return {
                "company_id": comp,
                "threshold_days": 30,
                "staff_emails": "",
                "digest_frequency": "weekly",
                "last_digest_sent_at": None,
                "digest_filters": {},
                "next_digest_at": None,
            }
        out = dict(row)
        try:
            out["digest_filters"] = _clean_digest_filters(json.loads(out.get("digest_filters") or "{}"))
        except ValueError:
            out["digest_filters"] = {}
        out["staff_emails"] = out.get("staff_emails") or ""
        freq = str(out.get("digest_frequency") or "weekly").lower()
        out["next_digest_at"] = _next_digest_at(freq, datetime.datetime.utcnow()) if out["staff_emails"].strip() else None
        from backend.api.mailbox import is_connected as _mailbox_connected
        out["mailbox_connected"] = _mailbox_connected(comp)
        return out
    finally:
        conn.close()


@router.post("/overdue-settings")
def update_overdue_settings(payload: UpdateAlertSettingsRequest):
    comp = (payload.company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        freq = (payload.digest_frequency or "weekly").strip().lower()
        if freq not in ("daily", "weekly", "monthly", "off"):
            raise HTTPException(status_code=400, detail="Digest frequency must be daily, weekly, monthly or off.")
        cur.execute("""
            INSERT INTO sponsorship_alert_settings (company_id, threshold_days, staff_emails, digest_frequency, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(company_id) DO UPDATE SET
                threshold_days = excluded.threshold_days,
                staff_emails = excluded.staff_emails,
                digest_frequency = excluded.digest_frequency,
                updated_at = CURRENT_TIMESTAMP
        """, (comp, payload.threshold_days, (payload.staff_emails or "").strip(), freq))
        if payload.digest_filters is not None:
            cur.execute("UPDATE sponsorship_alert_settings SET digest_filters = ? WHERE company_id = ?",
                        (json.dumps(_clean_digest_filters(payload.digest_filters)), comp))
        conn.commit()
        return {"status": "success", "message": f"Successfully updated alert settings for {comp.upper()}!"}
    finally:
        conn.close()


@router.post("/send-overdue-digest")
def send_overdue_digest(payload: SendOverdueDigestRequest):
    comp = (payload.company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT threshold_days, staff_emails, digest_filters FROM sponsorship_alert_settings WHERE company_id = ?", (comp,))
        set_row = cur.fetchone()
    finally:
        conn.close()

    threshold = payload.threshold_days or (set_row["threshold_days"] if set_row else 30)
    recipients_raw = payload.recipient_emails or (set_row["staff_emails"] if set_row else "")
    recipients = [e.strip() for e in re.split(r"[,;\s]+", recipients_raw) if "@" in e]

    if not recipients and not payload.dry_run:
        raise HTTPException(
            status_code=400,
            detail="No recipient emails configured. Please provide staff recipient email(s) in settings or in request."
        )

    if payload.saved_filters:  # the automatic digest's own saved filters (also "Send Digest Now" / preview in its settings)
        try:
            saved = json.loads((set_row["digest_filters"] if set_row and "digest_filters" in set_row.keys() else None) or "{}") or {}
        except ValueError:
            saved = {}
        payload = (payload.model_copy if hasattr(payload, "model_copy") else payload.copy)(update=_digest_request_filters(saved))
    sel = dict(sponsorship_type=payload.sponsorship_type or "all", target_status=payload.target_status or "all",
               classification=payload.classification if payload.classification and payload.classification != "all" else None,
               search=(payload.search or "").strip() or None)
    donors = _get_all_overdue_donors_data(company_id=comp, min_days=threshold, **sel)
    campaigns = _get_all_overdue_campaigns_data(company_id=comp, min_days=threshold, **sel)
    sev = (payload.severity or "all").strip().lower()
    if sev != "all":
        donors = [d for d in donors if d.get("severity") == sev]
        campaigns = [c for c in campaigns if c.get("severity") == sev]
    extra = {k: v for k, v in (payload.filters or {}).items()
             if k in ("earned_from", "earned_to", "last_gift_from", "last_gift_to", "max_days", "min_slots", "min_amount", "max_amount")
             and v not in (None, "")}
    donors = _overdue_extra_filters(donors, "total_donated", **extra)
    campaigns = _overdue_extra_filters(campaigns, "total_raised", **extra)
    labels = {"earned_from": "slot earned from", "earned_to": "slot earned to", "last_gift_from": "last gift from",
              "last_gift_to": "last gift to", "max_days": "waiting at most (days)", "min_slots": "unallocated slots ≥",
              "min_amount": "amount ≥ £", "max_amount": "amount ≤ £"}
    applied = [f"{k.replace('_', ' ')}: {v}" for k, v in (("program", sel["sponsorship_type"]), ("target", sel["target_status"]),
                                                          ("source", sel["classification"]), ("severity", sev), ("search", sel["search"]))
               if v and str(v).lower() != "all"] + [f"{labels[k]} {v}" for k, v in extra.items()]
    filters_html = (f'<p style="margin: 6px 0 0 0; font-size: 12px; opacity: 0.9;">Filtered: {html.escape(" · ".join(applied))}</p>'
                    if applied else "")

    total_donors = len(donors)
    total_campaigns = len(campaigns)
    total_slots = sum(d.get("remaining_slots", 0) for d in donors) + sum(c.get("remaining_slots", 0) for c in campaigns)
    critical_donors = [d for d in donors if d.get("severity") == "critical"]

    # Build High-Impact Branded HTML Digest
    brand_title = "Rethink Charity" if comp == "rethink" else "Iqra Charity"
    brand_color = "#3b82f6" if comp == "rethink" else "#10b981"
    now_str = datetime.datetime.now().strftime("%d %B %Y %H:%M UTC")

    # Generate Top 10 overdue donors rows
    donor_rows_html = ""
    for d in donors[:10]:
        sev_color = "#ef4444" if d.get("severity") == "critical" else ("#f97316" if d.get("severity") == "urgent" else "#f59e0b")
        donor_rows_html += f"""
        <tr style="border-bottom: 1px solid #e2e8f0;">
            <td style="padding: 10px 12px; font-weight: 600; color: #1e293b;">{d.get('donor_name')}</td>
            <td style="padding: 10px 12px; color: #64748b;">{d.get('donor_email')}</td>
            <td style="padding: 10px 12px; font-weight: 600; color: #3b82f6;">{d.get('sponsorship_type')}</td>
            <td style="padding: 10px 12px; text-align: center; font-weight: bold; color: #0f172a;">{d.get('remaining_slots')}</td>
            <td style="padding: 10px 12px; color: #64748b;">{d.get('oldest_donation_date')}</td>
            <td style="padding: 10px 12px; text-align: right;">
                <span style="background: {sev_color}18; color: {sev_color}; padding: 3px 8px; border-radius: 9999px; font-weight: bold; font-size: 12px;">
                    {d.get('waiting_days')} days
                </span>
            </td>
        </tr>
        """

    # Generate Top 5 overdue campaigns rows
    camp_rows_html = ""
    for c in campaigns[:5]:
        sev_color = "#ef4444" if c.get("severity") == "critical" else ("#f97316" if c.get("severity") == "urgent" else "#f59e0b")
        camp_rows_html += f"""
        <tr style="border-bottom: 1px solid #e2e8f0;">
            <td style="padding: 10px 12px; font-weight: 600; color: #1e293b;">{c.get('campaign_name')}</td>
            <td style="padding: 10px 12px; font-weight: 600; color: #3b82f6;">{c.get('sponsorship_type')}</td>
            <td style="padding: 10px 12px; text-align: center; font-weight: bold; color: #0f172a;">{c.get('remaining_slots')}</td>
            <td style="padding: 10px 12px; color: #64748b;">{c.get('oldest_donation_date')}</td>
            <td style="padding: 10px 12px; text-align: right;">
                <span style="background: {sev_color}18; color: {sev_color}; padding: 3px 8px; border-radius: 9999px; font-weight: bold; font-size: 12px;">
                    {c.get('waiting_days')} days
                </span>
            </td>
        </tr>
        """

    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f8fafc; padding: 24px; margin: 0;">
        <div style="max-width: 680px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
            <!-- Header -->
            <div style="background: {brand_color}; padding: 24px 28px; color: #ffffff;">
                <h2 style="margin: 0 0 6px 0; font-size: 20px; font-weight: 700;">⚠️ Sponsorship SLA Alert: Overdue Beneficiary Allocations</h2>
                <p style="margin: 0; font-size: 13px; opacity: 0.9;">{brand_title} • Generated on {now_str} • Threshold: {threshold}+ Days</p>
                {filters_html}
            </div>

            <!-- Content Area -->
            <div style="padding: 24px 28px;">
                <p style="color: #334155; font-size: 14px; line-height: 1.6; margin-top: 0;">
                    Hello Sponsorship Operations Team,<br><br>
                    This is an automated SLA alert digest of donors and campaigns who have contributed towards sponsorship funds but have not yet been assigned a beneficiary within the designated SLA window (<strong>{threshold} days</strong>).
                </p>

                <!-- KPI Grid -->
                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin: 20px 0;">
                    <div style="background: #f1f5f9; padding: 14px; border-radius: 8px; text-align: center; border-left: 4px solid #ef4444;">
                        <div style="font-size: 22px; font-weight: 800; color: #0f172a;">{total_donors}</div>
                        <div style="font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 600; margin-top: 2px;">Overdue Donors</div>
                    </div>
                    <div style="background: #f1f5f9; padding: 14px; border-radius: 8px; text-align: center; border-left: 4px solid #f97316;">
                        <div style="font-size: 22px; font-weight: 800; color: #0f172a;">{total_campaigns}</div>
                        <div style="font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 600; margin-top: 2px;">Overdue Campaigns</div>
                    </div>
                    <div style="background: #f1f5f9; padding: 14px; border-radius: 8px; text-align: center; border-left: 4px solid #3b82f6;">
                        <div style="font-size: 22px; font-weight: 800; color: #0f172a;">{total_slots}</div>
                        <div style="font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 600; margin-top: 2px;">Slots Waiting</div>
                    </div>
                </div>

                <!-- Donors Table -->
                <h3 style="font-size: 15px; color: #0f172a; margin: 24px 0 10px 0; border-bottom: 2px solid #f1f5f9; padding-bottom: 6px;">
                    Top Priority Unallocated Donors (Waiting Longest)
                </h3>
                <table style="width: 100%; border-collapse: collapse; font-size: 13px; text-align: left;">
                    <thead>
                        <tr style="background: #f8fafc; color: #64748b; font-size: 11px; text-transform: uppercase;">
                            <th style="padding: 8px 12px;">Donor</th>
                            <th style="padding: 8px 12px;">Email</th>
                            <th style="padding: 8px 12px;">Program</th>
                            <th style="padding: 8px 12px; text-align: center;">Slots</th>
                            <th style="padding: 8px 12px;">Donation Date</th>
                            <th style="padding: 8px 12px; text-align: right;">Age</th>
                        </tr>
                    </thead>
                    <tbody>
                        {donor_rows_html if donor_rows_html else '<tr><td colspan="6" style="padding: 16px; text-align: center; color: #94a3b8;">No overdue donors found!</td></tr>'}
                    </tbody>
                </table>

                {f'''
                <!-- Campaigns Table -->
                <h3 style="font-size: 15px; color: #0f172a; margin: 28px 0 10px 0; border-bottom: 2px solid #f1f5f9; padding-bottom: 6px;">
                    Top Priority Unallocated Campaigns
                </h3>
                <table style="width: 100%; border-collapse: collapse; font-size: 13px; text-align: left;">
                    <thead>
                        <tr style="background: #f8fafc; color: #64748b; font-size: 11px; text-transform: uppercase;">
                            <th style="padding: 8px 12px;">Campaign</th>
                            <th style="padding: 8px 12px;">Program</th>
                            <th style="padding: 8px 12px; text-align: center;">Slots</th>
                            <th style="padding: 8px 12px;">Oldest Date</th>
                            <th style="padding: 8px 12px; text-align: right;">Age</th>
                        </tr>
                    </thead>
                    <tbody>
                        {camp_rows_html}
                    </tbody>
                </table>
                ''' if camp_rows_html else ''}

                <!-- Action Button -->
                <div style="margin: 32px 0 16px 0; text-align: center;">
                    <a href="{_PUBLIC_APP_BASE}/" style="background: {brand_color}; color: #ffffff; padding: 12px 28px; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 14px; display: inline-block;">
                        Open Sponsorship Tracker to Allocate Now &rarr;
                    </a>
                </div>
            </div>

            <!-- Footer -->
            <div style="background: #f8fafc; padding: 16px 28px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #94a3b8; text-align: center;">
                Sent automatically by the Crowdfunding Enterprise CRM • Confidential Internal Staff Alert
            </div>
        </div>
    </body>
    </html>
    """

    if payload.dry_run:
        return {
            "status": "dry_run",
            "message": "Overdue digest generated successfully (dry-run mode).",
            "recipients": recipients,
            "summary": {
                "total_donors": total_donors,
                "total_campaigns": total_campaigns,
                "total_slots": total_slots,
                "critical_donors_count": len(critical_donors)
            },
            "html_preview": body_html
        }

    # Send from the charity's own mailbox (Gmail or Microsoft 365)
    email_sent = False
    error_msg = None
    try:
        from backend.api.mailbox import send_email
        sent = send_email(comp, [(r, None) for r in recipients],
                          f"⚠️ [{brand_title}] Sponsorship SLA Alert: {total_donors} Donors Overdue Allocation ({threshold}+ Days)", body_html)
        email_sent = bool(sent["ok"])
        if not email_sent:
            error_msg = sent["detail"]
    except HTTPException as e:
        error_msg = e.detail
    except Exception as e:
        error_msg = str(e)

    # Update last_digest_sent_at in database. The email has already gone out by now, so a busy database must not
    # turn it into an error (the sender would retry and the team would get the digest twice).
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE sponsorship_alert_settings
                SET last_digest_sent_at = CURRENT_TIMESTAMP
                WHERE company_id = ?
            """, (comp,))
            conn.commit()
        finally:
            conn.close()
    except sqlite3.OperationalError as e:
        logger.warning(f"Overdue digest ({comp}) sent={email_sent} but last_digest_sent_at not saved: {e}")

    return {
        "status": "success" if email_sent else ("warning" if not graph_access_token else "error"),
        "email_sent": email_sent,
        "message": f"Digest generated for {len(recipients)} staff recipient(s)." + (" Sent successfully via Outlook Graph API!" if email_sent else (f" (Notice: Outlook not connected or failed: {error_msg}). Preview generated." if not email_sent else "")),
        "recipients": recipients,
        "summary": {
            "total_donors": total_donors,
            "total_campaigns": total_campaigns,
            "total_slots": total_slots
        },
        "html_preview": body_html if not email_sent else None
    }


# ==========================================
# 12. SHARED DONATION HELPERS (donor details + triggers)
# ==========================================

def _settled_amount_column(df: pd.DataFrame) -> Optional[str]:
    for col in ("Total Online Donations Net Amount in Settled Currency",
                "Donation Amount in Project Currency (May be approx.)",
                "Donation Amount (in Donation Currency)"):
        if col in df.columns:
            return col
    return None


def _native_amounts(df: pd.DataFrame) -> pd.Series:
    """Amount in the donor's own currency; GiveBrite CSV imports leave that column blank and keep the
    native value in the project/net columns, so fall back to those."""
    out = pd.Series(float("nan"), index=df.index)
    for col in ("Donation Amount (in Donation Currency)", "Donation Amount in Project Currency (May be approx.)",
                "Total Online Donations Net Amount in Settled Currency"):
        if col in df.columns:
            out = out.fillna(pd.to_numeric(df[col], errors="coerce"))
    return out


def _sponsorship_type_masks(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """Same rules qualifying-donors uses (code, campaign name, giving level) so totals agree."""
    def col(name):
        return df[name].astype(str).str.strip().str.upper() if name in df.columns else pd.Series("", index=df.index)
    code_s, camp_s = col("Code"), col("Campaign Name")
    gl_s = col("Giving Level Title") if "Giving Level Title" in df.columns else col("Giving Level")
    return {
        "Hafiz": code_s.str.contains(r"HUF|HAF", regex=True, na=False) | camp_s.str.contains(r"HAFIZ|HIFZ", regex=True, na=False) | gl_s.str.contains(r"HAFIZ|HIFZ", regex=True, na=False),
        "Orphan": gl_s.str.contains("ORPHAN", na=False) | camp_s.str.contains("ORPHAN", na=False) | code_s.str.contains("ORP", na=False),
        "Widow": code_s.str.contains("WID", na=False) | camp_s.str.contains("WIDOW", na=False) | gl_s.str.contains("WIDOW", na=False),
        "Ex-Prisoner": code_s.str.contains(r"SUR|EX-PRISONER", regex=True, na=False) | camp_s.str.contains(r"PRISONER|SURVIVOR", regex=True, na=False) | gl_s.str.contains(r"PRISONER|SURVIVOR", regex=True, na=False),
    }


def _donation_dates(df: pd.DataFrame) -> pd.Series:
    for c in ("_parsed_date", "Created Date (UTC)", "Date", "Settled Date (UTC)", "created_at", "Date of collection"):
        if c in df.columns:
            return pd.to_datetime(df[c], errors="coerce", format="mixed")
    return pd.Series(pd.NaT, index=df.index)


def _num(v) -> Optional[float]:
    """Float or None (NaN/blank/garbage become None so JSON stays valid)."""
    try:
        f = float(pd.to_numeric(v, errors="coerce"))
    except (TypeError, ValueError):
        return None
    return None if f != f or f in (float("inf"), float("-inf")) else round(f, 2)


_PLACEHOLDER_IDENTITIES = {"", "missing email", "no email", "noemail", "unknown", "n/a", "na", "none", "nan", "null",
                           "anonymous", "anonymous donor", "-"}


def _is_placeholder_identity(v: Any) -> bool:
    return str(v or "").strip().lower() in _PLACEHOLDER_IDENTITIES


def _clean(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("nan", "none", "null", "nat", "<na>", "n/a") else s


def _consent_for_row(row: pd.Series) -> Optional[str]:
    """Marketing consent per platform rules: GiveBrite 'optin' (CSV/webhook), Madinah hidden donor = No /
    shown = Yes (inferred), otherwise the 'Marketing Consent' column. None when unknown.
    Someone who pressed Unsubscribe in one of our emails is always No."""
    em = _clean(row.get("Email")).lower()
    if em:
        from backend.api.unsubscribe import is_unsubscribed
        if is_unsubscribed(_clean(row.get("company_id")).lower() or "rethink", em):
            return "No"
    platform = _clean(row.get("Platform")).lower()
    optin = _clean(row.get("optin")).lower()
    if platform in ("givebright", "givebrite") and optin in ("true", "false"):
        return "Yes" if optin == "true" else "No"
    if platform == "madinah":
        hidden = _clean(row.get("Anonymous or Public")).lower() == "anonymous" or not _clean(row.get("Email"))
        return "No" if hidden else "Yes (inferred)"
    mc = _clean(row.get("Marketing Consent")).lower()
    if mc in ("yes", "true", "1"):
        return "Yes"
    if mc in ("no", "false", "0") and platform not in ("givebright", "givebrite"):
        return "No"  # GiveBrite sync rows hard-code "No", so it is not evidence there
    return None


# ==========================================
# 13. DONOR DETAILS PANEL
# ==========================================

@router.get("/donors/{donor_key}/details")
def get_sponsorship_donor_details(donor_key: str, company_id: Optional[str] = Query("rethink"),
                                  sponsorship_type: Optional[str] = Query(None)):
    """Everything about one donor for the active charity: contact, consent, giving towards each
    sponsorship type (currency, gift aid, frequency, platforms, slots), their sponsorships,
    email history and the individual donations that count towards sponsorships."""
    comp = (company_id or "rethink").strip().lower()
    if comp == "all":
        raise HTTPException(status_code=400, detail="Choose a charity to view donor details.")
    key = urllib.parse.unquote(donor_key).strip()
    key_l = key.lower()
    pinned_row_id = None  # "ad_<id>": one specific donor row on a sponsorship (donors without a usable email)
    if key_l.startswith("ad_") and key_l[3:].isdigit():
        conn0 = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        try:
            r0 = conn0.execute("SELECT id, donor_email, donor_id, donor_name FROM sponsorship_allocation_donors "
                               "WHERE id = ? AND company_id = ?", (int(key_l[3:]), comp)).fetchone()
        finally:
            conn0.close()
        if not r0:
            raise HTTPException(status_code=404, detail="Donor not found for this charity.")
        email0, id0 = (r0[1] or "").strip().lower(), (r0[2] or "").strip().lower()
        if "@" in email0:
            key = key_l = email0
        elif id0 and not _is_placeholder_identity(id0):
            key = key_l = id0
        else:
            pinned_row_id = r0[0]
            key, key_l = r0[3] or key, f"__row_{r0[0]}__"

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        targets = {k: float(v) for k, v in get_targets(company_id=comp).items()}

        manual = None
        if key_l.startswith("manual_") or key_l.startswith("md_"):
            manual = cur.execute("SELECT * FROM sponsorship_manual_donors WHERE company_id = ? AND id = ?",
                                 (comp, key.replace("manual_", ""))).fetchone()
            if not manual:
                raise HTTPException(status_code=404, detail="Donor not found for this charity.")
            manual = dict(manual)

        df = load_data(company_id=comp)
        rows = pd.DataFrame()
        if manual is None and not df.empty and pinned_row_id is None and not _is_placeholder_identity(key_l):
            email_s = df["Email"].astype(str).str.strip().str.lower() if "Email" in df.columns else pd.Series("", index=df.index)
            did_s = df["Donor ID"].astype(str).str.strip().str.lower() if "Donor ID" in df.columns else pd.Series("", index=df.index)
            rows = df[(email_s == key_l) | (did_s == key_l)]

        emails = set()
        if manual and _clean(manual.get("donor_email")):
            emails.add(manual["donor_email"].strip().lower())
        if not rows.empty and "Email" in rows.columns:
            emails.update(e.strip().lower() for e in rows["Email"].dropna().astype(str) if "@" in e)
        if "@" in key_l:
            emails.add(key_l)
        donor_ids = {key_l}
        if not rows.empty and "Donor ID" in rows.columns:
            donor_ids.update(str(d).strip().lower() for d in rows["Donor ID"].dropna())
        if manual:
            donor_ids.update({f"manual_{manual['id']}".lower(), str(manual["id"]).lower()})
        donor_ids = {d for d in donor_ids if not _is_placeholder_identity(d)}
        emails = {e for e in emails if e and "@" in e}

        # Their sponsorships (as a donor or organizer on any allocation of this charity)
        placeholders_e = ",".join("?" * len(emails)) or "NULL"
        placeholders_d = ",".join("?" * len(donor_ids)) or "NULL"
        cur.execute(f"""
            SELECT d.*, a.beneficiary_id, a.allocation_type, a.campaign_name, a.start_date, a.end_date,
                   a.renewal_count, a.created_at AS allocation_created_at, a.communication_status,
                   b.name AS beneficiary_name, b.sponsorship_type, b.project_code, b.location
            FROM sponsorship_allocation_donors d
            JOIN sponsorship_allocations a ON a.id = d.allocation_id
            JOIN sponsorship_beneficiaries b ON b.id = a.beneficiary_id
            WHERE d.company_id = ? AND (LOWER(d.donor_email) IN ({placeholders_e}) OR LOWER(d.donor_id) IN ({placeholders_d})
                   OR (? NOT LIKE '%@%' AND LOWER(TRIM(d.donor_name)) = ?))
            ORDER BY a.end_date
        """, [comp, *emails, *donor_ids, key_l, key_l])
        my_rows = [dict(r) for r in cur.fetchall()]
        if pinned_row_id is not None:
            cur.execute("""
                SELECT d.*, a.beneficiary_id, a.allocation_type, a.campaign_name, a.start_date, a.end_date,
                       a.renewal_count, a.created_at AS allocation_created_at, a.communication_status,
                       b.name AS beneficiary_name, b.sponsorship_type, b.project_code, b.location
                FROM sponsorship_allocation_donors d
                JOIN sponsorship_allocations a ON a.id = d.allocation_id
                JOIN sponsorship_beneficiaries b ON b.id = a.beneficiary_id
                WHERE d.id = ?
            """, (pinned_row_id,))
            my_rows = [dict(r) for r in cur.fetchall()]
        if manual is None and rows.empty and not my_rows and "@" not in key_l:
            raise HTTPException(status_code=404, detail="Donor not found for this charity.")
        # Imported donors may only be known by name/id on the sponsorship: use their stored contact.
        for r in my_rows:
            if (r.get("donor_email") or "").strip() and "@" in r["donor_email"]:
                emails.add(r["donor_email"].strip().lower())
        co_map = _load_allocation_donors(cur, [r["allocation_id"] for r in my_rows])
        sponsorships = []
        for r in my_rows:
            cycle = _allocation_cycle({"start_date": r["start_date"], "end_date": r["end_date"],
                                       "created_at": r["allocation_created_at"], "renewal_count": r["renewal_count"]})
            target = targets.get(r["sponsorship_type"], 0.0)
            amount = float(r["contribution_amount"] or 0.0)
            sponsorships.append({
                "allocation_id": r["allocation_id"], "allocation_donor_id": r["id"], "role": r["role"],
                "beneficiary_id": r["beneficiary_id"], "beneficiary_name": r["beneficiary_name"],
                "sponsorship_type": r["sponsorship_type"], "project_code": r["project_code"], "location": r["location"],
                "contribution_amount": amount, "target_amount": target,
                "share_percent": round(100.0 * amount / target, 1) if target else None,
                "is_primary": bool(r["is_primary"]), "needs_review": bool(r["needs_review"]),
                "co_sponsors": [{"id": c["id"], "donor_name": c["donor_name"], "donor_email": c["donor_email"],
                                 "contribution_amount": c["contribution_amount"]}
                                for c in co_map.get(r["allocation_id"], []) if c["id"] != r["id"]],
                "communication_status": r["communication_status"], **cycle,
            })

        # Email history + pending triggers for this donor
        alloc_donor_ids = [s["allocation_donor_id"] for s in sponsorships]
        history = []
        if alloc_donor_ids or emails:
            ph_ad = ",".join("?" * len(alloc_donor_ids)) or "NULL"
            # whole-address match (also inside comma/semicolon lists) - never a substring of someone else's email
            like_clauses = " OR ".join(["(',' || REPLACE(REPLACE(LOWER(c.recipient_email), ' ', ''), ';', ',') || ',') LIKE ?"
                                        " OR LOWER(TRIM(c.sender_email)) = ?"] * len(emails)) or "0"
            like_params = [p for e in emails for p in (f"%,{e.strip().lower()},%", e.strip().lower())]
            cur.execute(f"""
                SELECT c.id, c.allocation_id, c.allocation_donor_id, c.direction, c.subject, c.template_type,
                       c.sent_at, c.delivery_status, c.open_count, c.opened_at, c.replied_at, c.recipient_email, c.sender_email
                FROM sponsorship_communications c
                WHERE c.company_id = ? AND (c.allocation_donor_id IN ({ph_ad}) OR {like_clauses})
                ORDER BY c.sent_at DESC LIMIT 200
            """, [comp, *alloc_donor_ids, *like_params])
            history = [dict(r) for r in cur.fetchall()]
        pending = []
        if alloc_donor_ids:
            ph_ad = ",".join("?" * len(alloc_donor_ids))
            cur.execute(f"""SELECT id, allocation_id, allocation_donor_id, template_type, reason, due_date, status
                            FROM sponsorship_email_queue WHERE company_id = ? AND status = 'pending'
                            AND allocation_donor_id IN ({ph_ad}) ORDER BY due_date""", [comp, *alloc_donor_ids])
            pending = [dict(r) for r in cur.fetchall()]
        slot_rows = _donor_slot_allocations(cur, comp, "all", targets)
        manual_q = "SELECT * FROM sponsorship_manual_donors WHERE company_id = ? AND ("
        manual_p: List[Any] = [comp]
        conds = []
        if emails:
            conds.append(f"LOWER(TRIM(donor_email)) IN ({','.join('?' * len(emails))})"); manual_p += list(emails)
        if manual:
            conds.append("id = ?"); manual_p.append(manual["id"])
        manual_entries = []
        if conds:
            cur.execute(manual_q + " OR ".join(conds) + ")", manual_p)
            manual_entries = [{"id": r["id"], "donor_key": f"manual_{r['id']}", "donor_name": r["donor_name"],
                               "sponsorship_type": r["sponsorship_type"], "total_donated": float(r["total_donated"] or 0),
                               "custom_slots": r["custom_slots"], "notes": r["notes"] or ""} for r in cur.fetchall()]
    finally:
        conn.close()

    # Giving towards sponsorships
    giving, donations, consent = [], [], None
    if not rows.empty:
        rows = rows.assign(_dt=_donation_dates(rows))
        amt_col = _settled_amount_column(rows)
        masks = _sponsorship_type_masks(rows)
        any_mask = pd.Series(False, index=rows.index)
        for s_type, mask in masks.items():
            if sponsorship_type and sponsorship_type.lower() != "all" and s_type != sponsorship_type:
                continue
            any_mask |= mask
            sub = rows[mask]
            if sub.empty:
                continue
            settled = pd.to_numeric(sub[amt_col], errors="coerce").fillna(0.0) if amt_col else pd.Series(0.0, index=sub.index)
            native = _native_amounts(sub).fillna(0.0)
            cur_s = sub.get("Donation Currency (DC)", pd.Series("", index=sub.index)).astype(str).str.upper()
            ga_s = sub.get("Gift Aid (yes or no)", pd.Series("", index=sub.index)).astype(str).str.lower()
            target = targets.get(s_type, 0.0)
            total = round(float(settled.sum()), 2)
            threshold = 0.8 * target if target else 0.0
            max_slots = int(total // threshold) if threshold > 0 else 0
            used = _slots_used([r for r in slot_rows if r.get("sponsorship_type") == s_type and (
                (r.get("donor_email") or "").strip().lower() in emails or (r.get("donor_id") or "").strip().lower() in donor_ids)])
            giving.append({
                "sponsorship_type": s_type,
                "total_settled": total,
                "settlement_currencies": sorted({_clean(c) for c in sub.get("Settlement Currency", pd.Series(dtype=str)).dropna() if _clean(c)}),
                "by_currency": {c: round(float(v), 2) for c, v in native.groupby(cur_s).sum().items() if _clean(c)},
                "donation_count": int(len(sub)),
                "gift_aid_count": int((ga_s == "yes").sum()),
                "gift_aid_total": round(float(settled[ga_s == "yes"].sum()), 2),
                "frequencies": sorted({_clean(f) for f in sub.get("Payment Frequency", pd.Series(dtype=str)).dropna() if _clean(f)}),
                "platforms": sorted({_clean(p) for p in sub.get("Platform", pd.Series(dtype=str)).dropna() if _clean(p)}),
                "by_platform": {(_clean(k) or "Unknown"): round(float(v), 2) for k, v in settled.groupby(
                    sub.get("Platform", pd.Series("Unknown", index=sub.index)).astype(str)).sum().items()},
                "manual_total": round(sum(m["total_donated"] for m in manual_entries
                                          if m["sponsorship_type"] in (s_type, "All")), 2),
                "first_donation": str(sub["_dt"].min().date()) if pd.notna(sub["_dt"].min()) else None,
                "last_donation": str(sub["_dt"].max().date()) if pd.notna(sub["_dt"].max()) else None,
                "target_amount": target, "max_slots": max_slots, "slots_used": used,
                "slots_remaining": max(0, round(max_slots - used, 2)),
            })
        rel = rows[any_mask].sort_values("_dt", ascending=False).head(3000)
        rel_native = _native_amounts(rel)
        type_of = pd.Series("", index=rows.index)
        for s_type, mask in masks.items():
            type_of[mask & (type_of == "")] = s_type
        for idx, r in rel.iterrows():
            donations.append({
                "donation_id": _clean(r.get("Donation ID")),
                "date": str(r["_dt"].date()) if pd.notna(r["_dt"]) else _clean(r.get("Created Date (UTC)")),
                "amount": _num(rel_native.get(idx)),
                "currency": _clean(r.get("Donation Currency (DC)")),
                "settled_amount": _num(r.get(amt_col)) if amt_col else None,
                "settlement_currency": _clean(r.get("Settlement Currency")),
                "campaign": _clean(r.get("Campaign Name")),
                "sponsorship_type": type_of.get(idx, ""),
                "gift_aid": _clean(r.get("Gift Aid (yes or no)")),
                "frequency": _clean(r.get("Payment Frequency")),
                "payment_method": _clean(r.get("Payment Type")),
                "platform": _clean(r.get("Platform")),
                "status": _clean(r.get("Status")),
                "code": _clean(r.get("Code")),
                "heading": _clean(r.get("Heading")),
                "sub_heading": _clean(r.get("Sub-Heading")),
                "giving_level": _clean(r.get("Giving Level Title")),
                "fundraiser": _clean(r.get("fundraiser_name")),
            })
        dated = rows.sort_values("_dt", ascending=False)
        for _, r in dated.iterrows():
            consent = _consent_for_row(r)
            if consent:
                break

    def first_val(cols):
        if rows.empty:
            return ""
        for c in cols:
            if c in rows.columns:
                for v in rows.sort_values("_dt", ascending=False)[c] if "_dt" in rows.columns else rows[c]:
                    if _clean(v):
                        return _clean(v)
        return ""

    if manual:
        name, phone, country = manual.get("donor_name") or "", manual.get("donor_phone") or "", ""
    elif rows.empty:
        name = next((r["donor_name"] for r in my_rows if (r["donor_name"] or "").strip()), key)
        phone = next((r["donor_phone"] for r in my_rows if (r["donor_phone"] or "").strip()), "")
        country = ""
    else:
        fn, ln = first_val(["First Name"]), first_val(["Last Name"])
        name = f"{fn} {ln}".strip() or first_val(["Display Name", "Billing Name"]) or key
        phone = first_val(["Phone Number", "Phone", "phone_number"])
        country = first_val(["Billing Country", "Donor Address Country Code", "Country"])
    if (not name or name == key) and my_rows:
        name = next((r["donor_name"] for r in my_rows if (r["donor_name"] or "").strip()), name)

    return {
        "donor_key": key,
        "company_id": comp,
        "donor_type": "manual" if manual else ("crm" if not rows.empty else "contact_only"),
        "is_organizer": any(s["role"] == "organizer" for s in sponsorships),
        "contact": {"name": name, "emails": sorted(emails), "phone": phone, "country": country,
                    "marketing_consent": consent or "Unknown",
                    "manual_total_donated": float(manual["total_donated"]) if manual else None,
                    "notes": manual.get("notes") if manual else ""},
        "giving": giving,
        "manual_entries": manual_entries,
        "sponsorships": sponsorships,
        "email_history": history,
        "pending_emails": pending,
        "donations": donations,
    }


# ==========================================
# 14. TRIGGERED EMAIL QUEUE (review, then send)
# ==========================================

class QueueActionRequest(BaseModel):
    company_id: str
    ids: List[int]
    charity_theme: Optional[str] = None


def generate_email_queue(company_id: str) -> Dict[str, int]:
    """Creates pending queue items (never sends). Idempotent via UNIQUE(allocation_donor_id, template_type, trigger_key).
      - profile_intro: donor added to a sponsorship after the queue launched (migrated rows are skipped)
      - renewal_notice: sponsorship ends within the charity's renewal_lead_days
      - end_year_feedback: sponsorship year has ended (0-30 days ago)
      - general_custom (thank-you): a donor on a sponsorship made a new donation of that sponsorship type
    """
    comp = company_id.strip().lower()
    counts = {"profile_intro": 0, "renewal_notice": 0, "end_year_feedback": 0, "donation_thank_you": 0}
    today = datetime.date.today()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        lead = cur.execute("SELECT COALESCE(renewal_lead_days, 30) FROM sponsorship_alert_settings WHERE company_id = ?",
                           (comp,)).fetchone()
        lead_days = int(lead[0]) if lead else 30
        rows = [dict(r) for r in cur.execute("""
            SELECT d.id AS adid, d.allocation_id, d.donor_email, d.donor_id, d.source, d.created_at AS donor_added,
                   a.start_date, a.end_date, a.created_at, a.renewal_count, b.sponsorship_type
            FROM sponsorship_allocation_donors d
            JOIN sponsorship_allocations a ON a.id = d.allocation_id
            JOIN sponsorship_beneficiaries b ON b.id = a.beneficiary_id
            WHERE d.company_id = ? AND COALESCE(TRIM(d.donor_email), '') LIKE '%@%'
        """, (comp,)).fetchall()]

        def enqueue(r, template_type, reason, trigger_key, due):
            cur.execute("""
                INSERT OR IGNORE INTO sponsorship_email_queue
                    (company_id, allocation_id, allocation_donor_id, template_type, reason, trigger_key, due_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (comp, r["allocation_id"], r["adid"], template_type, reason, trigger_key, due))
            return cur.rowcount

        intro_sent = {row[0] for row in cur.execute(
            "SELECT DISTINCT allocation_donor_id FROM sponsorship_communications WHERE company_id = ? "
            "AND direction = 'outbound' AND template_type = 'profile_intro' AND allocation_donor_id IS NOT NULL", (comp,))}
        for r in rows:
            cycle = _allocation_cycle(r)
            if r["source"] != "migrated" and r["adid"] not in intro_sent:
                counts["profile_intro"] += enqueue(r, "profile_intro", "Added to sponsorship", "intro",
                                                   str(r["donor_added"] or today)[:10])
            days = cycle["days_remaining"]
            if days is not None and 0 <= days <= lead_days:
                counts["renewal_notice"] += enqueue(r, "renewal_notice", f"Sponsorship ends in {days} days",
                                                    f"renewal:{cycle['end_date']}", cycle["end_date"])
            if days is not None and -30 <= days < 0:
                counts["end_year_feedback"] += enqueue(r, "end_year_feedback", "Sponsorship year ended",
                                                       f"feedback:{cycle['end_date']}", cycle["end_date"])

        # New donations (last 30 days) of the same sponsorship type from donors already on a sponsorship
        df = load_data(company_id=comp)
        if not df.empty and "Email" in df.columns and rows:
            df = df.assign(_dt=_donation_dates(df))
            recent = df[df["_dt"] >= pd.Timestamp(today - datetime.timedelta(days=30))]
            if not recent.empty:
                masks = _sponsorship_type_masks(recent)
                email_s = recent["Email"].astype(str).str.strip().str.lower()
                by_email: Dict[str, List[Dict[str, Any]]] = {}
                for r in rows:
                    by_email.setdefault(r["donor_email"].strip().lower(), []).append(r)
                for idx in recent.index[email_s.isin(by_email.keys())]:
                    don = recent.loc[idx]
                    status_v = _clean(don.get("Status")).lower()
                    if status_v and status_v not in ("succeeded", "paid", "success", "completed"):
                        continue
                    for r in by_email[email_s[idx]]:
                        mask = masks.get(r["sponsorship_type"])
                        start = pd.to_datetime(r["start_date"] or r["created_at"], errors="coerce")
                        if mask is None or not bool(mask.get(idx, False)) or (pd.notna(start) and don["_dt"] < start):
                            continue
                        don_id = _clean(don.get("Donation ID")) or f"row{idx}"
                        counts["donation_thank_you"] += enqueue(
                            r, "general_custom", f"New {r['sponsorship_type']} donation on {str(don['_dt'].date())}",
                            f"donation:{don_id}", str(don["_dt"].date()))
        conn.commit()
    finally:
        conn.close()
    if sum(counts.values()):
        log_event("queue.generated", category="queue", company_id=comp, created=counts,
                  message=f"Email queue: {sum(counts.values())} new item(s) to review")
    return counts


@router.post("/email-queue/generate")
def trigger_queue_generation(company_id: str = Query(...)):
    comp = company_id.strip().lower()
    if comp == "all":
        raise HTTPException(status_code=400, detail="Choose a charity.")
    return {"status": "success", "created": generate_email_queue(comp)}


@router.get("/email-queue")
def list_email_queue(company_id: str = Query(...), status: Optional[str] = Query("pending"),
                     template_type: Optional[str] = Query(None), donor: Optional[str] = Query(None),
                     beneficiary: Optional[str] = Query(None), sponsorship_type: Optional[str] = Query(None),
                     due_from: Optional[str] = Query(None), due_to: Optional[str] = Query(None),
                     page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500)):
    comp = company_id.strip().lower()
    where, params = ["q.company_id = ?"], [comp]
    if status and status != "all":
        where.append("q.status = ?"); params.append(status)
    if template_type:
        where.append("q.template_type = ?"); params.append(template_type)
    if donor:
        where.append("(d.donor_name LIKE ? OR d.donor_email LIKE ?)"); params += [f"%{donor}%"] * 2
    if beneficiary:
        where.append("(b.name LIKE ? OR b.project_code LIKE ?)"); params += [f"%{beneficiary}%"] * 2
    if sponsorship_type and sponsorship_type != "all":
        where.append("b.sponsorship_type = ?"); params.append(sponsorship_type)
    if due_from:
        where.append("q.due_date >= ?"); params.append(due_from)
    if due_to:
        where.append("q.due_date <= ?"); params.append(due_to)
    base = f"""
        FROM sponsorship_email_queue q
        JOIN sponsorship_allocation_donors d ON d.id = q.allocation_donor_id
        JOIN sponsorship_allocations a ON a.id = q.allocation_id
        JOIN sponsorship_beneficiaries b ON b.id = a.beneficiary_id
        WHERE {' AND '.join(where)}
    """
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        total = cur.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
        cur.execute(f"""
            SELECT q.*, d.donor_name, d.donor_email, d.role, d.contribution_amount,
                   b.name AS beneficiary_name, b.sponsorship_type, b.project_code
            {base} ORDER BY q.due_date ASC, q.id ASC LIMIT ? OFFSET ?
        """, params + [page_size, (page - 1) * page_size])
        items = [dict(r) for r in cur.fetchall()]
        summary = {r[0]: r[1] for r in cur.execute(
            "SELECT status, COUNT(*) FROM sponsorship_email_queue WHERE company_id = ? GROUP BY status", (comp,))}
        return {"total": total, "page": page, "page_size": page_size, "items": items, "summary": summary}
    finally:
        conn.close()


@router.post("/email-queue/skip")
def skip_email_queue_items(payload: QueueActionRequest):
    comp = payload.company_id.strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        ph = ",".join("?" * len(payload.ids)) or "NULL"
        cur = conn.cursor()
        cur.execute(f"UPDATE sponsorship_email_queue SET status = 'skipped', updated_at = CURRENT_TIMESTAMP "
                    f"WHERE company_id = ? AND status = 'pending' AND id IN ({ph})", [comp, *payload.ids])
        conn.commit()
        log_event("queue.skipped", category="queue", company_id=comp, ids=payload.ids, skipped=cur.rowcount,
                  message=f"Skipped {cur.rowcount} queued email(s)")
        return {"status": "success", "skipped": cur.rowcount}
    finally:
        conn.close()


@router.post("/email-queue/send")
def send_email_queue_items(payload: QueueActionRequest, request: Request):
    """Sends the selected pending items, each rendered for its own donor from the charity's own mailbox."""
    comp = payload.company_id.strip().lower()
    base_url = _public_base_url(request)
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        ph = ",".join("?" * len(payload.ids)) or "NULL"
        items = [dict(r) for r in conn.execute(
            f"""SELECT q.*, d.donor_name, d.donor_email, b.name AS beneficiary_name
                FROM sponsorship_email_queue q
                LEFT JOIN sponsorship_allocation_donors d ON d.id = q.allocation_donor_id
                LEFT JOIN sponsorship_allocations a ON a.id = q.allocation_id
                LEFT JOIN sponsorship_beneficiaries b ON b.id = a.beneficiary_id
                WHERE q.company_id = ? AND q.status = 'pending' AND q.id IN ({ph})""",
            [comp, *payload.ids]).fetchall()]
    finally:
        conn.close()
    results = []
    for item in items:
        to_email = (item.get("donor_email") or "").strip()
        recipient_name = (item.get("donor_name") or "").strip()
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
            try:
                rendered = render_email_for_donor(conn.cursor(), item["allocation_id"], item["allocation_donor_id"],
                                                  item["template_type"], payload.charity_theme)
                conn.commit()
            finally:
                conn.close()
            res = deliver_rendered_email(rendered, item["allocation_id"], base_url)
            if not res.get("recipient_email"):
                res["recipient_email"] = to_email
            if not res.get("recipient_name"):
                res["recipient_name"] = recipient_name
        except HTTPException as e:
            res = {"status": "failed", "detail": e.detail, "recipient_email": to_email, "recipient_name": recipient_name}
        except Exception as e:
            res = {"status": "failed", "detail": str(e), "recipient_email": to_email, "recipient_name": recipient_name}
        if res["status"] != "sent":
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
            try:
                conn.execute("UPDATE sponsorship_email_queue SET status = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP "
                             "WHERE id = ?", ("skipped" if res["status"] == "skipped" else "failed",
                                             str(res.get("detail", ""))[:500], item["id"]))
                conn.commit()
            finally:
                conn.close()
        results.append({
            "queue_id": item["id"],
            "recipient_email": res.get("recipient_email") or to_email,
            "recipient_name": res.get("recipient_name") or recipient_name,
            "beneficiary_name": item.get("beneficiary_name") or "",
            **res
        })
    sent = sum(1 for r in results if r["status"] == "sent")
    sent_emails = [r["recipient_email"] for r in results if r["status"] == "sent" and r.get("recipient_email")]
    sent_emails_str = f" to: {', '.join(sent_emails)}" if sent_emails else ""
    log_event("queue.sent", category="queue", company_id=comp, level="info" if sent == len(results) else "warning",
              requested=len(payload.ids), sent=sent, failed=len(results) - sent,
              message=f"Queue send: {sent} of {len(results)} sent{sent_emails_str}")
    return {
        "status": "success" if results and sent == len(results) else ("partial" if sent else "failed"),
        "message": f"Sent {sent} of {len(results)} queued email(s){sent_emails_str}.",
        "sent_emails": sent_emails,
        "results": results
    }
