import os
import re
import time
import base64
import threading
import json
import uuid
import sqlite3
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
from backend.api.auth import get_current_user, require_super_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tracker", tags=["Sponsorship Target Tracker & Allocations"])

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

        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Error migrating tracker tables: {e}")

_ensure_tracker_tables_migrated()


# ==========================================
# 1. MODELS & SCHEMAS
# ==========================================

class ManualDonorCreateRequest(BaseModel):
    donor_name: str
    donor_email: Optional[str] = ""
    donor_phone: Optional[str] = ""
    sponsorship_type: str = "Orphan"
    total_donated: Optional[float] = 0.0
    custom_slots: Optional[int] = None
    notes: Optional[str] = ""
    company_id: Optional[str] = "rethink"

class ManualDonorUpdateRequest(BaseModel):
    donor_name: Optional[str] = None
    donor_email: Optional[str] = None
    donor_phone: Optional[str] = None
    sponsorship_type: Optional[str] = None
    total_donated: Optional[float] = None
    custom_slots: Optional[int] = None
    notes: Optional[str] = None

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

class AllocationCreateRequest(BaseModel):
    beneficiary_id: int
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
    recipient_email: str
    recipient_name: Optional[str] = "Donor"
    subject: str
    body_html: str
    company_id: Optional[str] = "rethink"

class OutlookTestEmailRequest(BaseModel):
    company_id: Optional[str] = "rethink"
    recipient_email: Optional[str] = "office@rethinkcharity.org.uk"

class TemplateUpdateRequest(BaseModel):
    template_type: str
    subject: str
    body_html: str
    company_id: Optional[str] = "rethink"

class UpdateAlertSettingsRequest(BaseModel):
    company_id: Optional[str] = "rethink"
    threshold_days: int = 30
    staff_emails: Optional[str] = ""
    digest_frequency: Optional[str] = "weekly"
    user_role: Optional[str] = "admin"

class SendOverdueDigestRequest(BaseModel):
    company_id: Optional[str] = "rethink"
    threshold_days: Optional[int] = None
    recipient_emails: Optional[str] = None
    dry_run: Optional[bool] = False
    user_role: Optional[str] = "admin"

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
def update_targets(payload: UpdateTargetsRequest):
    """Updates target values (restricted to super_admin)."""
    if payload.user_role != "super_admin":
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

@router.get("/beneficiaries")
def get_beneficiaries(
    company_id: Optional[str] = Query("rethink"),
    sponsorship_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
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
            query += " AND (b.name LIKE ? OR b.project_code LIKE ? OR b.location LIKE ? OR a.donor_name LIKE ? OR a.donor_email LIKE ?)"
            s_param = f"%{search.strip()}%"
            params.extend([s_param, s_param, s_param, s_param, s_param])

        query += " ORDER BY b.created_at DESC"
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
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


@router.get("/qualifying-donors")
def get_qualifying_donors(
    company_id: Optional[str] = Query("rethink"),
    sponsorship_type: Optional[str] = Query("Orphan"),
    search: Optional[str] = Query(None)
):
    """
    Returns qualifying donors for a given sponsorship type along with capacity calculations:
    - total_donated: Total amount donated to this sponsorship type
    - target_amount: Target cost per beneficiary (e.g., 480)
    - max_slots: floor(total_donated / target_amount)
    - allocated_count: Number of beneficiaries currently allocated to this donor
    - remaining_slots: max_slots - allocated_count
    """
    comp = _unwrap_param(company_id, "rethink").strip().lower()
    s_type = _unwrap_param(sponsorship_type, "Orphan").strip()
    search = _unwrap_param(search, "").strip() or None

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

        alloc_query = """
            SELECT a.donor_email, a.donor_phone, a.donor_id, a.beneficiary_id, b.name AS beneficiary_name, b.project_code, b.sponsorship_type
            FROM sponsorship_allocations a
            JOIN sponsorship_beneficiaries b ON a.beneficiary_id = b.id
            WHERE 1=1
        """
        alloc_params = []
        if comp != "all":
            alloc_query += " AND a.company_id = ?"
            alloc_params.append(comp)
        cur.execute(alloc_query, alloc_params)
        all_allocs = [dict(r) for r in cur.fetchall()]

        # Query manual sponsorship donors
        man_query = """
            SELECT id, company_id, donor_name, donor_email, donor_phone,
                   sponsorship_type, total_donated, custom_slots, notes, created_at
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

    df = load_data(company_id=comp)
    donors_list = []

    if not df.empty and "Donor ID" in df.columns:
        col_amount = "Total Online Donations Net Amount in Settled Currency"
        if col_amount not in df.columns:
            col_amount = "Donation Amount in Project Currency (May be approx.)"
        if col_amount not in df.columns:
            col_amount = "Donation Amount (in Donation Currency)"

        if col_amount in df.columns:
            amt_series = pd.to_numeric(df[col_amount], errors="coerce").fillna(0.0)
            d_id_series = df["Donor ID"].astype(str)
            code_series = df["Code"].astype(str).str.strip().str.upper() if "Code" in df.columns else pd.Series("", index=df.index)

            camp_series = df["Campaign Name"].astype(str).str.strip().str.upper() if "Campaign Name" in df.columns else pd.Series("", index=df.index)
            gl_col = "Giving Level Title" if "Giving Level Title" in df.columns else ("Giving Level" if "Giving Level" in df.columns else None)
            gl_series = df[gl_col].astype(str).str.strip().str.upper() if gl_col else pd.Series("", index=df.index)

            is_orphan_gl = gl_series.str.contains("ORPHAN", na=False)
            is_orphan_camp = camp_series.str.contains("ORPHAN", na=False)
            is_orphan_code = code_series.str.contains("ORP", na=False)

            masks = {
                "Hafiz": code_series.str.contains(r"HUF|HAF", regex=True, na=False) | camp_series.str.contains(r"HAFIZ|HIFZ", regex=True, na=False) | gl_series.str.contains(r"HAFIZ|HIFZ", regex=True, na=False),
                "Orphan": is_orphan_gl | is_orphan_camp | is_orphan_code,
                "Widow": code_series.str.contains("WID", na=False) | camp_series.str.contains("WIDOW", na=False) | gl_series.str.contains("WIDOW", na=False),
                "Ex-Prisoner": code_series.str.contains(r"SUR|EX-PRISONER", regex=True, na=False) | camp_series.str.contains(r"PRISONER|SURVIVOR", regex=True, na=False) | gl_series.str.contains(r"PRISONER|SURVIVOR", regex=True, na=False)
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
                s_did = d_id_series[mask]

                # Group by donor for this sponsorship type ONLY
                sums = s_amt.groupby(s_did).sum()
                valid_did_mask = ~sums.index.astype(str).str.strip().str.lower().isin(["", "nan", "none", "null", "undefined", "<na>"])
                sums = sums[valid_did_mask]

                # Include all donors who donated towards this sponsorship type (even if below target threshold)
                relevant_ids = set(sums[sums > 0].index)

                # Ensure donors with existing allocations for this sponsorship type are retained
                alloc_dids = {str(a.get("donor_id")).strip() for a in all_allocs if a.get("sponsorship_type") == s_type and a.get("donor_id")}
                alloc_dids = {d for d in alloc_dids if d.lower() not in ["", "none", "null", "nan", "undefined"]}
                relevant_ids.update(alloc_dids)

                if "Email" in df.columns:
                    alloc_emails = {str(a.get("donor_email")).strip().lower() for a in all_allocs if a.get("sponsorship_type") == s_type and a.get("donor_email")}
                    alloc_emails = {e for e in alloc_emails if "@" in e}
                    if alloc_emails:
                        matched_alloc_rows = df[df["Email"].astype(str).str.strip().str.lower().isin(alloc_emails)]
                        for d_val in matched_alloc_rows["Donor ID"].dropna().unique():
                            relevant_ids.add(str(d_val).strip())

                # High-performance vectorized metadata & date aggregation
                s_rel_rows = df[mask & d_id_series.isin(relevant_ids)]
                
                # 1. Dates: Min & Max per donor for this sponsorship
                s_dt_agg = s_rel_rows.groupby("Donor ID")["_unified_dt"].agg(["min", "max"])
                
                # 2. Campaigns involved per donor for this sponsorship
                camp_col_name = "Campaign Name" if "Campaign Name" in s_rel_rows.columns else ("Campaign" if "Campaign" in s_rel_rows.columns else None)
                s_camps_agg = s_rel_rows.groupby("Donor ID")[camp_col_name].unique() if camp_col_name else {}

                # 3. Donor display names vectorized
                fn = s_rel_rows["First Name"].fillna("").astype(str).str.strip() if "First Name" in s_rel_rows.columns else pd.Series("", index=s_rel_rows.index)
                ln = s_rel_rows["Last Name"].fillna("").astype(str).str.strip() if "Last Name" in s_rel_rows.columns else pd.Series("", index=s_rel_rows.index)
                full_n = (fn + " " + ln).str.strip()
                bill_n = s_rel_rows["Billing Name"].fillna("").astype(str).str.strip() if "Billing Name" in s_rel_rows.columns else pd.Series("", index=s_rel_rows.index)
                disp_n = s_rel_rows["Display Name"].fillna("").astype(str).str.strip() if "Display Name" in s_rel_rows.columns else pd.Series("", index=s_rel_rows.index)
                
                best_n_series = full_n.replace(["", "nan", "none", "nan nan", "none none"], np.nan).fillna(
                    bill_n.replace(["", "nan", "none"], np.nan)
                ).fillna(
                    disp_n.replace(["", "nan", "none"], np.nan)
                ).fillna("Anonymous Donor")
                
                names_by_did = best_n_series.groupby(s_rel_rows["Donor ID"]).first()
                
                # 4. Donor email & phone vectorized
                if "Email" in s_rel_rows.columns:
                    emails_by_did = s_rel_rows["Email"].dropna().astype(str).str.strip().groupby(s_rel_rows["Donor ID"]).first()
                else:
                    emails_by_did = pd.Series("N/A", index=names_by_did.index)
                
                phone_col = None
                for pc in ["Phone Number", "Phone", "phone_number", "Contact Phone"]:
                    if pc in s_rel_rows.columns:
                        phone_col = pc
                        break
                if phone_col:
                    phones_by_did = s_rel_rows[phone_col].dropna().astype(str).str.strip().str.lstrip("'").groupby(s_rel_rows["Donor ID"]).first()
                else:
                    phones_by_did = pd.Series("", index=names_by_did.index)

                # 5. Donor LTV across all causes
                ltv_by_did = amt_series[d_id_series.isin(relevant_ids)].groupby(d_id_series).sum()

                now_dt = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

                for str_id in relevant_ids:
                    s_total_val = float(sums.get(str_id, 0.0))
                    d_name = str(names_by_did.get(str_id) or "Anonymous Donor")
                    d_email = str(emails_by_did.get(str_id) or "N/A")
                    if d_email.lower() in ["n/a", "nan", "none", ""] and "@" in str_id:
                        d_email = str_id
                    d_phone = str(phones_by_did.get(str_id) or "")
                    d_ltv = float(ltv_by_did.get(str_id, s_total_val))

                    # Dates and campaigns strictly for this sponsorship
                    oldest_dt, latest_dt = None, None
                    if str_id in s_dt_agg.index:
                        oldest_dt = s_dt_agg.loc[str_id, "min"]
                        latest_dt = s_dt_agg.loc[str_id, "max"]
                    
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
                    waiting_days = max(0, (now_dt - oldest_dt).days) if oldest_dt and pd.notna(oldest_dt) else 0

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
                    allocated_count = len(allocated_items)
                    remaining_slots = max(0, max_slots - allocated_count)

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
                        "oldest_donation_date": oldest_str,
                        "latest_donation_date": latest_str,
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
        m_allocated_count = len(m_allocated_items)
        m_remaining_slots = max(0, m_max_slots - m_allocated_count)

        if m_allocated_count > m_max_slots:
            m_status = "over_capacity"
        elif m_remaining_slots > 0:
            m_status = "eligible"
        else:
            m_status = "at_capacity"

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
            "notes": mr.get("notes") or "",
            "created_at": mr.get("created_at"),
            "oldest_donation_date": m_oldest_str,
            "latest_donation_date": m_oldest_str,
            "waiting_days": m_waiting_days,
            "campaigns_involved": ["Manual Entry"],
            "allocated_beneficiaries": m_allocated_items
        })

    donors_list.sort(key=lambda x: (x["remaining_slots"] > 0, x["allocated_count"] > 0, x["total_donated"]), reverse=True)
    return {
        "sponsorship_type": s_type,
        "target_amount": target_amount,
        "count": len(donors_list),
        "donors": donors_list
    }


@router.get("/search-any-donor")
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

        alloc_query = """
            SELECT a.donor_email, a.donor_phone, a.donor_id, a.beneficiary_id, b.name AS beneficiary_name, b.project_code, b.sponsorship_type
            FROM sponsorship_allocations a
            JOIN sponsorship_beneficiaries b ON a.beneficiary_id = b.id
            WHERE 1=1
        """
        alloc_params = []
        if comp != "all":
            alloc_query += " AND a.company_id = ?"
            alloc_params.append(comp)
        cur.execute(alloc_query, alloc_params)
        all_allocs = [dict(r) for r in cur.fetchall()]

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
        m_allocated_count = len(m_allocated_items)
        m_remaining_slots = max(0, m_max_slots - m_allocated_count)

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

        search_mask = (
            name_col.str.contains(q_low, case=False, na=False) |
            email_col.str.contains(q_low, case=False, na=False) |
            did_col.str.contains(q_low, case=False, na=False)
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
                allocated_count = len(allocated_items)
                remaining_slots = max(0, max_slots - allocated_count)

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

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sponsorship_manual_donors (
                id, company_id, donor_name, donor_email, donor_phone,
                sponsorship_type, total_donated, custom_slots, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            donor_id,
            comp,
            name,
            email,
            phone,
            payload.sponsorship_type or "Orphan",
            float(payload.total_donated or 0.0),
            payload.custom_slots,
            payload.notes or ""
        ))
        conn.commit()
        invalidate_overdue_cache(comp)
        return {
            "status": "success",
            "message": f"Successfully created manual donor '{name}' for {payload.sponsorship_type} sponsorship tracking!",
            "donor_id": donor_id
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
    try:
        cur = conn.cursor()
        fields = []
        params = []
        if payload.donor_name is not None:
            fields.append("donor_name = ?")
            params.append(payload.donor_name.strip())
        if payload.donor_email is not None:
            fields.append("donor_email = ?")
            params.append(payload.donor_email.strip())
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

        if not fields:
            return {"status": "no_change"}

        fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(raw_id)
        cur.execute(f"UPDATE sponsorship_manual_donors SET {', '.join(fields)} WHERE id = ?", params)
        conn.commit()
        invalidate_overdue_cache(None)
        return {"status": "success", "message": "Manual donor updated successfully."}
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
        conn.commit()
        invalidate_overdue_cache(None)
        return {"status": "success", "message": "Manual donor deleted successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/qualifying-campaigns")
def get_qualifying_campaigns(
    company_id: Optional[str] = Query("rethink"),
    sponsorship_type: Optional[str] = Query("Orphan"),
    search: Optional[str] = Query(None)
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
    """
    comp = _unwrap_param(company_id, "rethink").strip().lower()
    s_type = _unwrap_param(sponsorship_type, "Orphan").strip()
    search = _unwrap_param(search, "").strip() or None

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
    if not df.empty and camp_col and "_unified_dt" in df.columns and mask.any():
        try:
            valid_dt_df = df[mask & df["_unified_dt"].notna()]
            if not valid_dt_df.empty:
                clean_camps = valid_dt_df[camp_col].fillna("").astype(str).str.strip().str.lower()
                dt_grp = valid_dt_df.groupby(clean_camps)["_unified_dt"].agg(["min", "max"])
                for c_k_idx, row_dt in dt_grp.iterrows():
                    campaign_dates[c_k_idx] = (row_dt["min"], row_dt["max"])
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
        org_name = mapping_info.get("donor_name") or ""
        org_email = mapping_info.get("donor_email") or ""

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
        allocated_count = len(allocated_items)
        slot_threshold = 0.8 * target_amount if target_amount > 0 else 0.0
        max_slots = int(tot_val // slot_threshold) if slot_threshold > 0 else 0
        remaining_slots = max(0, max_slots - allocated_count)

        if tot_val >= slot_threshold and remaining_slots > 0:
            elig_status = "eligible"
        elif tot_val >= slot_threshold and remaining_slots == 0:
            elig_status = "at_capacity"
        else:
            elig_status = "near_target"

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
        c_waiting_days = max(0, (now_dt - c_oldest_dt).days) if c_oldest_dt and pd.notna(c_oldest_dt) else 0

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
            "oldest_donation_date": c_oldest_str,
            "latest_donation_date": c_latest_str,
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
@router.get("/allocations")
def get_allocations(
    company_id: Optional[str] = Query("rethink"),
    sponsorship_type: Optional[str] = Query(None),
    allocation_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    renewal_filter: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
):
    """Returns all allocations joined with beneficiary, campaign metadata, communication metrics, and renewal lifecycle stats."""
    comp = (company_id or "rethink").strip().lower()
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
                (SELECT COUNT(*) FROM sponsorship_communications c WHERE c.allocation_id = a.id AND c.direction = 'inbound') AS inbound_replies_count,
                (SELECT c.delivery_status FROM sponsorship_communications c WHERE c.allocation_id = a.id AND c.direction = 'outbound' ORDER BY c.sent_at DESC LIMIT 1) AS latest_email_status,
                (SELECT c.opened_at FROM sponsorship_communications c WHERE c.allocation_id = a.id AND c.direction = 'outbound' ORDER BY c.sent_at DESC LIMIT 1) AS latest_email_opened_at,
                (SELECT c.open_count FROM sponsorship_communications c WHERE c.allocation_id = a.id AND c.direction = 'outbound' ORDER BY c.sent_at DESC LIMIT 1) AS latest_email_open_count,
                (SELECT c.sent_at FROM sponsorship_communications c WHERE c.allocation_id = a.id AND c.direction = 'outbound' ORDER BY c.sent_at DESC LIMIT 1) AS latest_email_sent_at,
                (SELECT c.subject FROM sponsorship_communications c WHERE c.allocation_id = a.id AND c.direction = 'outbound' ORDER BY c.sent_at DESC LIMIT 1) AS latest_email_subject
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
            query += " AND (a.donor_name LIKE ? OR a.donor_email LIKE ? OR a.donor_phone LIKE ? OR a.campaign_name LIKE ? OR b.name LIKE ? OR b.project_code LIKE ?)"
            s_param = f"%{search.strip()}%"
            params.extend([s_param, s_param, s_param, s_param, s_param, s_param])

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

        return {"count": len(computed_allocations), "allocations": computed_allocations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
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
        d_email = (payload.donor_email or "").strip()
        d_phone = (payload.donor_phone or "").strip()

        if not d_email and not d_phone:
            raise HTTPException(
                status_code=400,
                detail="At least one contact method (Email or Phone number) is mandatory for allocation."
            )

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
            payload.donor_name.strip() if payload.donor_name else ("Campaign Allocation" if alloc_type == 'campaign' else "Anonymous Donor"),
            payload.donor_id.strip() if payload.donor_id else "",
            alloc_type,
            payload.campaign_name.strip() if payload.campaign_name else None,
            payload.community_name.strip() if payload.community_name else None,
            float(payload.allocated_amount or 0.0),
            start_d,
            end_d,
            adm_notes
        ))
        alloc_id = cur.lastrowid

        cur.execute("UPDATE sponsorship_beneficiaries SET status = 'Allocated', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (payload.beneficiary_id,))

        conn.commit()
        invalidate_overdue_cache(comp)
        assigned_to_label = payload.campaign_name if alloc_type == 'campaign' and payload.campaign_name else (payload.donor_name or d_email or d_phone)
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
        cur.execute("DELETE FROM sponsorship_allocations WHERE id = ?", (allocation_id,))
        cur.execute("UPDATE sponsorship_beneficiaries SET status = 'Unallocated', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (b_id,))
        conn.commit()
        invalidate_overdue_cache(c_id)
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

    r_uri = redirect_uri or "http://localhost:5173/sponsorship-tracker"
    scopes = "https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/User.Read offline_access"
    tenant = auth["tenant_id"] or "common"

    auth_url = (
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?"
        f"client_id={auth['client_id']}&"
        f"redirect_uri={requests.utils.quote(r_uri)}&"
        f"response_type=code&"
        f"response_mode=query&"
        f"scope={requests.utils.quote(scopes)}&"
        f"state={comp}"
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
        return {"status": "success", "message": "Microsoft 365 account disconnected."}
    finally:
        conn.close()

@router.post("/outlook/send")
def send_outlook_message(payload: OutlookSendRequest, request: Request, current_user = Depends(get_current_user)):
    """Dispatches an email via Microsoft Graph API, embeds real-time open tracking pixel, and logs delivery metadata."""
    comp = (payload.company_id or "rethink").strip().lower()
    access_token = _get_valid_graph_token(comp)
    auth = _get_outlook_auth_row(comp)
    sender_email = auth["connected_email"] if auth and auth["connected_email"] else "me"

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

    if "</body>" in raw_body:
        email_body_with_pixel = raw_body.replace("</body>", f"{tracking_pixel_html}</body>")
    else:
        email_body_with_pixel = f"{raw_body}{tracking_pixel_html}"

    send_payload = {
        "message": {
            "subject": payload.subject.strip(),
            "body": {
                "contentType": "HTML",
                "content": email_body_with_pixel
            },
            "toRecipients": to_recipients_list
        },
        "saveToSentItems": "true"
    }

    send_url = "https://graph.microsoft.com/v1.0/me/sendMail"
    res = requests.post(send_url, headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }, json=send_payload, timeout=15)

    if res.status_code not in (200, 202):
        raise HTTPException(status_code=400, detail=f"Microsoft Graph sendMail Error: {res.text}")

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
            f"graph_{int(time.time()*1000)}",
            "",
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
        company_id = client_state.replace("sponsorship_", "") if client_state else "rethink"

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
                    cur.execute("""
                        SELECT id, donor_email FROM sponsorship_allocations 
                        WHERE company_id = ? 
                        ORDER BY created_at DESC
                    """, (company_id,))
                    alloc_rows = cur.fetchall()
                    matched_alloc_id = None
                    clean_from = from_email.strip().lower()
                    for r_id, r_emails in alloc_rows:
                        if r_emails:
                            for single_em in r_emails.replace(";", ",").split(","):
                                if single_em.strip().lower() == clean_from:
                                    matched_alloc_id = r_id
                                    break
                        if matched_alloc_id:
                            break

                    if matched_alloc_id:
                        alloc_id = matched_alloc_id
                        cur.execute("""
                            INSERT INTO sponsorship_communications (
                                allocation_id, company_id, direction, message_id,
                                thread_id, subject, body, sender_email, recipient_email
                            ) VALUES (?, ?, 'inbound', ?, ?, ?, ?, ?, ?)
                        """, (
                            alloc_id,
                            company_id,
                            msg_id,
                            conv_id,
                            subject,
                            body_preview,
                            from_email,
                            company_id
                        ))

                        cur.execute("""
                            UPDATE sponsorship_allocations SET
                                communication_status = 'Donor Replied',
                                last_replied_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """, (alloc_id,))
                        conn.commit()
                finally:
                    conn.close()
        except Exception:
            pass

    return Response(status_code=202)


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
            cur.execute("SELECT id, LOWER(donor_email) FROM sponsorship_allocations WHERE company_id = ?", (comp,))
            alloc_map = {}
            for r_id, r_emails in cur.fetchall():
                if r_emails:
                    for single_em in r_emails.replace(";", ",").split(","):
                        clean_em = single_em.strip().lower()
                        if clean_em and clean_em not in alloc_map:
                            alloc_map[clean_em] = r_id

            for m in messages:
                msg_id = m.get("id")
                from_info = m.get("from", {}).get("emailAddress", {})
                sender_email = (from_info.get("address") or "").strip().lower()

                if not sender_email or sender_email == connected_email:
                    continue

                if sender_email in alloc_map:
                    alloc_id = alloc_map[sender_email]
                    subject = m.get("subject", "")
                    body_preview = m.get("bodyPreview", "")
                    conv_id = m.get("conversationId", "")
                    rec_dt = m.get("receivedDateTime")

                    cur.execute("SELECT id FROM sponsorship_communications WHERE message_id = ? AND company_id = ?", (msg_id, comp))
                    if not cur.fetchone():
                        cur.execute("""
                            INSERT INTO sponsorship_communications (
                                allocation_id, company_id, direction, message_id,
                                thread_id, subject, body, sender_email, recipient_email, sent_at
                            ) VALUES (?, ?, 'inbound', ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
                        """, (
                            alloc_id, comp, msg_id, conv_id, subject, body_preview,
                            sender_email, connected_email, rec_dt
                        ))

                        cur.execute("""
                            UPDATE sponsorship_allocations SET
                                communication_status = 'Donor Replied',
                                last_replied_at = COALESCE(?, CURRENT_TIMESTAMP)
                            WHERE id = ?
                        """, (rec_dt, alloc_id))

                        cur.execute("""
                            UPDATE sponsorship_communications SET
                                delivery_status = 'replied',
                                replied_at = COALESCE(?, CURRENT_TIMESTAMP)
                            WHERE allocation_id = ? AND direction = 'outbound'
                        """, (rec_dt, alloc_id))

                        new_synced += 1

            conn.commit()
        finally:
            conn.close()

        return {"status": "success", "synced_new_replies": new_synced}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@router.post("/outlook/sync-replies")
def trigger_sync_replies(company_id: Optional[str] = Query("rethink"), current_user = Depends(get_current_user)):
    """On-demand sync of recent donor replies from Microsoft 365 Inbox."""
    comp = (company_id or "rethink").strip().lower()
    return sync_inbound_outlook_replies(comp)
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
            "subject": "Important Sponsorship Update from Rethink Charity",
            "body_html": _wrap_email_html_template(
                "Important Sponsorship Update from Rethink Charity",
                """<p style="margin: 0 0 12px 0;">{{Message_Body}}</p>""",
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
                SELECT id, company_id, template_type, subject, body_html 
                FROM sponsorship_email_templates 
                WHERE LOWER(company_id) = ?
                ORDER BY id ASC
            """, (selected_theme,))
        else:
            placeholders = ",".join("?" for _ in allowed_themes)
            cur.execute(f"""
                SELECT id, company_id, template_type, subject, body_html 
                FROM sponsorship_email_templates 
                WHERE LOWER(company_id) IN ({placeholders})
                ORDER BY CASE LOWER(company_id) WHEN ? THEN 0 ELSE 1 END, id ASC
            """, (*allowed_themes, comp))

        rows = []
        for r in cur.fetchall():
            d = dict(r)
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
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sponsorship_email_templates (company_id, template_type, subject, body_html)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(company_id, template_type) DO UPDATE SET
                subject = excluded.subject,
                body_html = excluded.body_html
        """, (comp, payload.template_type.strip(), payload.subject.strip(), payload.body_html.strip()))
        conn.commit()
        return {"status": "success", "message": f"Email template '{payload.template_type}' saved successfully for charity '{comp}'."}
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
            SELECT id, allocation_id, company_id, direction, message_id,
                   thread_id, subject, body, sender_email, recipient_email, sent_at,
                   tracking_id, delivery_status, opened_at, open_count, replied_at,
                   last_opened_ip, last_opened_user_agent
            FROM sponsorship_communications
            WHERE allocation_id = ?
            ORDER BY sent_at ASC
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
        
        # Update allocation's communication_status if not yet replied
        cur.execute("""
            SELECT allocation_id, subject FROM sponsorship_communications WHERE tracking_id = ?
        """, (tracking_id,))
        row = cur.fetchone()
        if row:
            alloc_id = row[0]
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
    
    # 1. First-tier fast in-memory cache check (<1ms)
    with _OVERDUE_CACHE_LOCK:
        cached = _OVERDUE_CACHE.get(comp)
        if not force_refresh and cached and (now_ts - cached["timestamp"] < _OVERDUE_CACHE_TTL):
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
                if now_ts - up_ts < _OVERDUE_CACHE_TTL:
                    parsed = json.loads(row["data_json"])
                    donors_db = parsed.get("donors", [])
                    campaigns_db = parsed.get("campaigns", [])
                    with _OVERDUE_CACHE_LOCK:
                        _OVERDUE_CACHE[comp] = {
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
                # Include donors with unallocated slots OR partial/below-threshold donors who have not yet allocated
                is_unallocated = (rem > 0) or (d.get("allocated_count", 0) == 0 and tot > 0)
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
                is_unallocated = (rem > 0) or (c.get("allocated_count", 0) == 0 and tot > 0)
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
            "timestamp": now_ts,
            "donors": final_donors,
            "campaigns": final_campaigns
        }

    # Save to persistent SQLite cache across all worker processes
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS sponsorship_overdue_cache (company_id TEXT PRIMARY KEY, data_json TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        data_str = json.dumps({"donors": final_donors, "campaigns": final_campaigns})
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
    search: Optional[str] = None,
    force_refresh: bool = False
):
    donors, _ = get_all_overdue_data(company_id=company_id, force_refresh=force_refresh)
    st_filter = sponsorship_type.strip().lower() if sponsorship_type and sponsorship_type.lower() != "all" else None
    search_low = search.strip().lower() if search and search.strip() else None

    filtered = []
    for d in donors:
        if d.get("waiting_days", 0) < min_days:
            continue
        if st_filter and d.get("sponsorship_type", "").lower() != st_filter:
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
    search: Optional[str] = None,
    force_refresh: bool = False
):
    _, campaigns = get_all_overdue_data(company_id=company_id, force_refresh=force_refresh)
    st_filter = sponsorship_type.strip().lower() if sponsorship_type and sponsorship_type.lower() != "all" else None
    search_low = search.strip().lower() if search and search.strip() else None

    filtered = []
    for c in campaigns:
        if c.get("waiting_days", 0) < min_days:
            continue
        if st_filter and c.get("sponsorship_type", "").lower() != st_filter:
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


@router.get("/overdue-donors")
def get_overdue_donors(
    company_id: Optional[str] = Query("rethink"),
    sponsorship_type: Optional[str] = Query("all"),
    target_status: Optional[str] = Query("all"),
    min_days: Optional[int] = Query(30),
    severity: Optional[str] = Query("all"),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=50000),
    all_records: Optional[bool] = Query(False),
    force_refresh: Optional[bool] = Query(False)
):
    comp = _unwrap_param(company_id, "rethink").strip().lower()
    raw_days = _unwrap_param(min_days, 30)
    try:
        days = int(raw_days) if raw_days is not None and int(raw_days) >= 0 else 30
    except (ValueError, TypeError):
        days = 30
    s_type = _unwrap_param(sponsorship_type, "all")
    t_status = _unwrap_param(target_status, "all")
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
        search=srch,
        force_refresh=f_ref
    )

    if sev and sev.lower() != "all":
        all_donors = [d for d in all_donors if d.get("severity") == sev.lower().strip()]

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
    min_days: Optional[int] = Query(30),
    severity: Optional[str] = Query("all"),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=50000),
    all_records: Optional[bool] = Query(False),
    force_refresh: Optional[bool] = Query(False)
):
    comp = _unwrap_param(company_id, "rethink").strip().lower()
    raw_days = _unwrap_param(min_days, 30)
    try:
        days = int(raw_days) if raw_days is not None and int(raw_days) >= 0 else 30
    except (ValueError, TypeError):
        days = 30
    s_type = _unwrap_param(sponsorship_type, "all")
    t_status = _unwrap_param(target_status, "all")
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
        search=srch,
        force_refresh=f_ref
    )

    if sev and sev.lower() != "all":
        all_campaigns = [c for c in all_campaigns if c.get("severity") == sev.lower().strip()]

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
        cur.execute("SELECT company_id, threshold_days, staff_emails, digest_frequency, last_digest_sent_at FROM sponsorship_alert_settings WHERE company_id = ?", (comp,))
        row = cur.fetchone()
        if not row:
            return {
                "company_id": comp,
                "threshold_days": 30,
                "staff_emails": "",
                "digest_frequency": "weekly",
                "last_digest_sent_at": None
            }
        return dict(row)
    finally:
        conn.close()


@router.post("/overdue-settings")
def update_overdue_settings(payload: UpdateAlertSettingsRequest):
    comp = (payload.company_id or "rethink").strip().lower()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sponsorship_alert_settings (company_id, threshold_days, staff_emails, digest_frequency, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(company_id) DO UPDATE SET
                threshold_days = excluded.threshold_days,
                staff_emails = excluded.staff_emails,
                digest_frequency = excluded.digest_frequency,
                updated_at = CURRENT_TIMESTAMP
        """, (comp, payload.threshold_days, payload.staff_emails.strip(), payload.digest_frequency.strip()))
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
        cur.execute("SELECT threshold_days, staff_emails FROM sponsorship_alert_settings WHERE company_id = ?", (comp,))
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

    donors = _get_all_overdue_donors_data(company_id=comp, min_days=threshold)
    campaigns = _get_all_overdue_campaigns_data(company_id=comp, min_days=threshold)

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
                    <a href="http://127.0.0.1:8000/tracker" style="background: {brand_color}; color: #ffffff; padding: 12px 28px; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 14px; display: inline-block;">
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

    # Attempt Live Email Sending via Outlook Graph API if available
    token_data = _get_valid_graph_token(comp)
    email_sent = False
    error_msg = None

    if token_data and token_data.get("access_token"):
        try:
            to_recipients_list = [{"emailAddress": {"address": r}} for r in recipients]
            send_payload = {
                "message": {
                    "subject": f"⚠️ [{brand_title}] Sponsorship SLA Alert: {total_donors} Donors Overdue Allocation ({threshold}+ Days)",
                    "body": {
                        "contentType": "HTML",
                        "content": body_html
                    },
                    "toRecipients": to_recipients_list
                },
                "saveToSentItems": "true"
            }
            send_res = requests.post(
                "https://graph.microsoft.com/v1.0/me/sendMail",
                headers={
                    "Authorization": f"Bearer {token_data['access_token']}",
                    "Content-Type": "application/json"
                },
                json=send_payload,
                timeout=15
            )
            if send_res.status_code in (200, 202):
                email_sent = True
            else:
                error_msg = f"Graph API error: {send_res.text}"
        except Exception as e:
            error_msg = str(e)

    # Update last_digest_sent_at in database
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
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

    return {
        "status": "success" if email_sent else ("warning" if not token_data else "error"),
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
