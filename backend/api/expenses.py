import io
import os
import sqlite3
import uuid
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import List, Optional
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel

from config.settings import (
    LOCAL_DB_PATH, PARQUET_PATH, APP_BASE_URL, APPROVAL_EMAIL,
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_NAME, SMTP_FROM_EMAIL
)
from core.data_processor import load_data, get_classification_matrix
from core.security import encrypt_string, decrypt_string
from backend.api.events import broadcast_event_sync

router = APIRouter(prefix="/api/expenses", tags=["Expense & Payment Tracking"])


def init_expense_db():
    """Initializes expense_requests and system_settings SQLite tables."""
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expense_requests (
                id TEXT PRIMARY KEY,
                code TEXT,
                gl_code TEXT,
                is_zakat INTEGER DEFAULT 0,
                heading TEXT,
                sub_heading TEXT,
                country TEXT,
                title TEXT,
                vendor TEXT,
                amount REAL,
                payment_date TEXT,
                notes TEXT,
                status TEXT DEFAULT 'PENDING_APPROVAL',
                requested_by TEXT,
                reviewed_by TEXT,
                review_notes TEXT,
                approval_token TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Migration safe-guards for existing databases
        for col_def in ["gl_code TEXT", "is_zakat INTEGER DEFAULT 0"]:
            try:
                cursor.execute(f"ALTER TABLE expense_requests ADD COLUMN {col_def};")
            except Exception:
                pass
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_system_settings_key ON system_settings(setting_key);")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS code_transfers (
                id TEXT PRIMARY KEY,
                transfer_date TEXT,
                source_code TEXT NOT NULL,
                destination_code TEXT NOT NULL,
                amount REAL NOT NULL,
                reason TEXT NOT NULL,
                transferred_by TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_code_transfers_src ON code_transfers(source_code);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_code_transfers_dst ON code_transfers(destination_code);")
        
        # Seed SMTP settings from .env as defaults (INSERT OR IGNORE = only on first run)
        smtp_defaults = [
            ('approval_email', APPROVAL_EMAIL),
            ('smtp_host', SMTP_HOST),
            ('smtp_port', str(SMTP_PORT)),
            ('smtp_user', SMTP_USER),
            ('smtp_password', SMTP_PASSWORD),
            ('smtp_from_name', SMTP_FROM_NAME),
            ('smtp_from_email', SMTP_FROM_EMAIL),
        ]
        cursor.executemany("""
            INSERT OR IGNORE INTO system_settings (setting_key, setting_value)
            VALUES (?, ?);
        """, smtp_defaults)

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Expense DB init notice: {e}")


init_expense_db()


class SubmitExpenseRequest(BaseModel):
    code: str
    title: str
    vendor: str
    amount: float
    payment_date: str
    notes: Optional[str] = ""
    requested_by: Optional[str] = "Admin User"
    is_zakat: Optional[bool] = False
    gl_code: Optional[str] = None


class ReviewExpenseRequest(BaseModel):
    expense_id: str
    user_role: str
    action: str  # "APPROVED" or "REJECTED"
    review_notes: Optional[str] = ""
    can_edit_donors: Optional[bool] = False


class UpdateApprovalEmailRequest(BaseModel):
    user_role: str
    approval_email: str


class UpdateSmtpSettingsRequest(BaseModel):
    user_role: Optional[str] = "super_admin"
    can_edit_donors: Optional[bool] = False
    approval_email: str
    smtp_host: Optional[str] = "smtp.gmail.com"
    smtp_port: Optional[int] = 587
    smtp_user: Optional[str] = ""
    smtp_password: Optional[str] = ""  # send empty string to keep existing password unchanged
    smtp_from_name: Optional[str] = "Rethink Charity CRM"
    smtp_from_email: Optional[str] = ""


class TestEmailRequest(BaseModel):
    user_role: str
    can_edit_donors: Optional[bool] = False


class DeleteExpenseRequest(BaseModel):
    expense_id: str
    user_role: str
    can_edit_donors: Optional[bool] = False


class TransferFundsRequest(BaseModel):
    source_code: str
    destination_code: str
    amount: float
    reason: str
    transfer_date: Optional[str] = ""
    user_role: Optional[str] = "super_admin"
    can_edit_donors: Optional[bool] = False
    transferred_by: Optional[str] = "Admin User"


class VoidTransferRequest(BaseModel):
    user_role: Optional[str] = "super_admin"
    can_edit_donors: Optional[bool] = False


def _get_smtp_config():
    """Fetches all SMTP + approval settings from DB. Falls back to .env values."""
    defaults = {
        'approval_email': APPROVAL_EMAIL,
        'smtp_host': SMTP_HOST,
        'smtp_port': str(SMTP_PORT),
        'smtp_user': SMTP_USER,
        'smtp_password': SMTP_PASSWORD,
        'smtp_from_name': SMTP_FROM_NAME,
        'smtp_from_email': SMTP_FROM_EMAIL,
    }
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT setting_key, setting_value FROM system_settings")
        rows = cursor.fetchall()
        conn.close()
        for key, val in rows:
            if key in defaults and val is not None:
                if key == 'smtp_password':
                    defaults[key] = decrypt_string(val)
                else:
                    defaults[key] = val
    except Exception:
        pass
    return defaults


def _get_approval_email():
    """Fetches the current approval email from system settings."""
    return _get_smtp_config().get('approval_email', APPROVAL_EMAIL)


def _send_smtp_email(smtp_cfg: dict, to_email: str, subject: str, html_body: str, plain_body: str):
    """Sends an email using the provided SMTP config dict. Returns (success, error_msg)."""
    smtp_user = smtp_cfg.get('smtp_user', '')
    smtp_password = smtp_cfg.get('smtp_password', '')
    smtp_host = smtp_cfg.get('smtp_host', 'smtp.gmail.com')
    smtp_port = int(smtp_cfg.get('smtp_port', 587))
    smtp_from_name = smtp_cfg.get('smtp_from_name', 'Rethink Charity CRM')
    smtp_from_email = smtp_cfg.get('smtp_from_email', '') or smtp_user

    if not smtp_user or not smtp_password:
        return False, "SMTP credentials not configured. Set SMTP User and Password in Email Settings."

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{smtp_from_name} <{smtp_from_email}>"
        msg["To"] = to_email
        msg["Reply-To"] = smtp_from_email
        msg.attach(MIMEText(plain_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_from_email, [to_email], msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)


def dispatch_approval_email(expense_id: str, title: str, amount: float, code: str, requested_by: str, token: str, gl_code: str = "", is_zakat: bool = False):
    """Generates direct approval links and dispatches approval notification via real SMTP email."""
    smtp_cfg = _get_smtp_config()
    dest_email = smtp_cfg.get('approval_email', APPROVAL_EMAIL)

    approve_url = f"{APP_BASE_URL}/api/expenses/action-email?id={expense_id}&token={token}&action=APPROVED"
    reject_url = f"{APP_BASE_URL}/api/expenses/action-email?id={expense_id}&token={token}&action=REJECTED"

    zakat_label = "Zakat Eligible" if is_zakat else "Non-Zakat"
    gl_display = gl_code if gl_code else "Unassigned"

    html_body = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #0F172A; color: #F8FAFC; border-radius: 16px; overflow: hidden; border: 1px solid rgba(255,255,255,0.1);">
      <div style="background: linear-gradient(135deg, #06B6D4, #0284C7); padding: 24px 32px;">
        <h1 style="margin: 0; font-size: 18px; font-weight: 800; color: #FFFFFF;">⚡ Expense Approval Required</h1>
        <p style="margin: 4px 0 0; font-size: 12px; color: rgba(255,255,255,0.8);">Rethink Charity — CRM Expense Tracker</p>
      </div>
      <div style="padding: 28px 32px;">
        <p style="font-size: 14px; color: #94A3B8; margin: 0 0 20px;">A new project expense request requires your Super Admin approval:</p>
        <table style="width: 100%; border-collapse: collapse; margin-bottom: 24px;">
          <tr><td style="padding: 8px 0; font-size: 12px; color: #64748B; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; width: 40%;">Claim ID</td><td style="padding: 8px 0; font-size: 14px; color: #38BDF8; font-weight: 700; font-family: monospace;">{expense_id}</td></tr>
          <tr><td style="padding: 8px 0; font-size: 12px; color: #64748B; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">Project Code</td><td style="padding: 8px 0; font-size: 14px; color: #8B5CF6; font-weight: 700; font-family: monospace;">{code}</td></tr>
          <tr><td style="padding: 8px 0; font-size: 12px; color: #64748B; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">GL Ledger Code</td><td style="padding: 8px 0; font-size: 14px; color: #F59E0B; font-weight: 700; font-family: monospace;">{gl_display} ({zakat_label})</td></tr>
          <tr><td style="padding: 8px 0; font-size: 12px; color: #64748B; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">Expense Title</td><td style="padding: 8px 0; font-size: 14px; color: #F8FAFC; font-weight: 600;">{title}</td></tr>
          <tr><td style="padding: 8px 0; font-size: 12px; color: #64748B; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">Amount</td><td style="padding: 8px 0; font-size: 20px; color: #10B981; font-weight: 800;">£{amount:,.2f}</td></tr>
          <tr><td style="padding: 8px 0; font-size: 12px; color: #64748B; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">Submitted By</td><td style="padding: 8px 0; font-size: 14px; color: #F8FAFC;">{requested_by}</td></tr>
        </table>
        <div style="display: flex; gap: 12px; margin-top: 8px;">
          <a href="{approve_url}" style="display: inline-block; padding: 12px 28px; background: linear-gradient(135deg, #10B981, #059669); color: #FFFFFF; text-decoration: none; border-radius: 10px; font-weight: 800; font-size: 14px; text-align: center;">✓ APPROVE</a>
          <a href="{reject_url}" style="display: inline-block; padding: 12px 28px; background: linear-gradient(135deg, #F43F5E, #E11D48); color: #FFFFFF; text-decoration: none; border-radius: 10px; font-weight: 800; font-size: 14px; text-align: center;">✗ REJECT</a>
        </div>
      </div>
      <div style="background: rgba(15,23,42,0.5); padding: 16px 32px; border-top: 1px solid rgba(255,255,255,0.05);">
        <p style="margin: 0; font-size: 11px; color: #475569;">This email was generated by the Rethink Charity CRM. If you did not expect this, please contact your system administrator.</p>
      </div>
    </div>
    """
    plain_body = f"""EXPENSE APPROVAL NOTIFICATION\n==============================\nClaim ID: {expense_id}\nProject Code: {code}\nGL Code: {gl_display} ({zakat_label})\nExpense Title: {title}\nAmount: GBP {amount:,.2f}\nSubmitted By: {requested_by}\n\nAPPROVE: {approve_url}\nREJECT: {reject_url}"""

    subject = f"[Action Required] Expense Claim Approval: {expense_id} (GBP {amount:,.2f})"
    email_sent, send_error = _send_smtp_email(smtp_cfg, dest_email, subject, html_body, plain_body)

    print(f"--- Approval Email Log ---")
    print(f"  To: {dest_email} | Sent: {email_sent}")
    print(f"  APPROVE URL: {approve_url}")
    print(f"  REJECT URL:  {reject_url}")
    if send_error:
        print(f"  Error: {send_error}")
    print(f"--------------------------")

    return dest_email, approve_url, reject_url, email_sent, send_error

_CODES_CACHE = None

def clear_expenses_cache():
    global _CODES_CACHE
    _CODES_CACHE = None

@router.get("/codes")
def get_project_codes(force_reload: bool = False):
    """Returns unique list of project codes with gross raised, approved expenses, and net balance aggregated across donations, payouts, and classifications in real-time."""
    global _CODES_CACHE
    if not force_reload and _CODES_CACHE is not None:
        return _CODES_CACHE

    init_expense_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        
        # 1. Fetch approved expenses per code
        cur.execute("SELECT code, SUM(amount) FROM expense_requests WHERE status = 'APPROVED' GROUP BY code")
        approved_expense_map = {str(row[0]).strip().upper(): float(row[1] or 0.0) for row in cur.fetchall() if row[0]}

        # 1b. Fetch internal fund transfers in and out per code
        try:
            cur.execute("""
                SELECT UPPER(TRIM(source_code)), SUM(amount)
                FROM code_transfers
                WHERE source_code IS NOT NULL AND TRIM(source_code) != ''
                GROUP BY UPPER(TRIM(source_code))
            """)
            transfers_out_map = {str(r[0]).strip().upper(): float(r[1] or 0.0) for r in cur.fetchall() if r[0]}

            cur.execute("""
                SELECT UPPER(TRIM(destination_code)), SUM(amount)
                FROM code_transfers
                WHERE destination_code IS NOT NULL AND TRIM(destination_code) != ''
                GROUP BY UPPER(TRIM(destination_code))
            """)
            transfers_in_map = {str(r[0]).strip().upper(): float(r[1] or 0.0) for r in cur.fetchall() if r[0]}
        except Exception:
            transfers_out_map = {}
            transfers_in_map = {}
        
        # 2. Fetch ALL canonical codes from master_project_codes (single source of truth - 190 codes)
        cur.execute("""
            SELECT 
                UPPER(TRIM(code)) as code,
                department,
                office,
                portfolio,
                country,
                zakat_eligibility,
                programme_fund,
                fund_code,
                legacy_non_zakat_code,
                legacy_zakat_code,
                old_codes,
                description,
                is_active
            FROM master_project_codes
            WHERE code IS NOT NULL AND TRIM(code) != ''
            ORDER BY code
        """)
        master_rows = cur.fetchall()

        # 3. Fetch gross raised per code from donations table (for financial enrichment only)
        cur.execute("""
            SELECT 
                UPPER(TRIM(Code)) as code, 
                SUM([Total Online Donations Net Amount in Settled Currency]) 
            FROM donations 
            WHERE Code IS NOT NULL AND TRIM(Code) != '' AND UPPER(TRIM(Code)) NOT IN ('N/A', 'UNASSIGNED', 'NAN', 'NONE', '')
            GROUP BY UPPER(TRIM(Code))
        """)
        gross_from_donations = {str(r[0]).strip().upper(): float(r[1] or 0.0) for r in cur.fetchall() if r[0]}

        # 4. Fetch gross raised per code from payout_settlements (for financial enrichment only)
        try:
            cur.execute("""
                SELECT 
                    UPPER(TRIM(Code)) as code, 
                    SUM([Total Online Donations Net Amount in Settled Currency]) 
                FROM payout_settlements 
                WHERE Code IS NOT NULL AND TRIM(Code) != '' AND UPPER(TRIM(Code)) NOT IN ('N/A', 'UNASSIGNED', 'NAN', 'NONE', '')
                GROUP BY UPPER(TRIM(Code))
            """)
            gross_from_payouts = {str(r[0]).strip().upper(): float(r[1] or 0.0) for r in cur.fetchall() if r[0]}
        except Exception:
            gross_from_payouts = {}

    except Exception as e:
        print(f"Error fetching codes from DB: {e}")
        return []
    finally:
        conn.close()

    code_map = {}

    # Build code list STRICTLY from master_project_codes (canonical 190 codes - single source of truth)
    for (code_val, department, office, portfolio, country, zakat_elig,
         programme_fund, fund_code, legacy_nz, legacy_z, old_codes,
         description, is_active) in master_rows:
        if not code_val:
            continue
        code_str = str(code_val).strip().upper()
        # Financial enrichment: prefer donations gross, fall back to payouts
        gross_val = gross_from_donations.get(code_str, gross_from_payouts.get(code_str, 0.0))
        exp_amt = approved_expense_map.get(code_str, 0.0)
        t_in = transfers_in_map.get(code_str, 0.0)
        t_out = transfers_out_map.get(code_str, 0.0)
        net_t = round(t_in - t_out, 2)
        code_map[code_str] = {
            "code": code_str,
            "heading": str(department or "Unassigned"),
            "sub_heading": str(office or "Unassigned"),
            "portfolio": str(portfolio or ""),
            "country": str(country or "Unassigned"),
            "zakat_eligibility": str(zakat_elig or ""),
            "programme_fund": str(programme_fund or ""),
            "fund_code": str(fund_code or ""),
            "legacy_non_zakat_code": str(legacy_nz or ""),
            "legacy_zakat_code": str(legacy_z or ""),
            "old_codes": str(old_codes or ""),
            "description": str(description or ""),
            "is_active": bool(is_active),
            "campaign_name": "N/A",
            "gross_raised": round(gross_val, 2),
            "approved_expenses": round(exp_amt, 2),
            "transfers_in": round(t_in, 2),
            "transfers_out": round(t_out, 2),
            "net_transfers": net_t,
            "net_balance": round(gross_val - exp_amt + t_in - t_out, 2),
        }

    # Safety net: include any approved expense codes filed against a code not yet in master register
    for exp_code, exp_amt in approved_expense_map.items():
        if exp_code not in code_map:
            gross_val = gross_from_donations.get(exp_code, gross_from_payouts.get(exp_code, 0.0))
            t_in = transfers_in_map.get(exp_code, 0.0)
            t_out = transfers_out_map.get(exp_code, 0.0)
            net_t = round(t_in - t_out, 2)
            code_map[exp_code] = {
                "code": exp_code,
                "heading": "Unassigned",
                "sub_heading": "Unassigned",
                "portfolio": "",
                "country": "Unassigned",
                "zakat_eligibility": "",
                "programme_fund": "",
                "fund_code": "",
                "legacy_non_zakat_code": "",
                "legacy_zakat_code": "",
                "old_codes": "",
                "description": "",
                "is_active": True,
                "campaign_name": "N/A",
                "gross_raised": round(gross_val, 2),
                "approved_expenses": round(exp_amt, 2),
                "transfers_in": round(t_in, 2),
                "transfers_out": round(t_out, 2),
                "net_transfers": net_t,
                "net_balance": round(gross_val - exp_amt + t_in - t_out, 2),
            }

    sorted_codes = sorted(list(code_map.values()), key=lambda x: x["code"])
    _CODES_CACHE = sorted_codes
    return sorted_codes


@router.get("/requests")
def get_expense_requests(status_filter: Optional[str] = "ALL"):
    """Returns list of expense requests and summary metrics."""
    init_expense_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = "SELECT * FROM expense_requests"
    params = []
    if status_filter and status_filter != "ALL":
        query += " WHERE status = ?"
        params.append(status_filter)
    
    query += " ORDER BY created_at DESC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT status, SUM(amount), COUNT(*) FROM expense_requests GROUP BY status")
    kpi_rows = cursor.fetchall()
    
    total_requested = 0.0
    total_approved = 0.0
    total_pending = 0.0
    total_rejected = 0.0

    count_approved = 0
    count_pending = 0
    count_rejected = 0

    for r in kpi_rows:
        st, amt, cnt = r[0], r[1] or 0.0, r[2] or 0
        total_requested += amt
        if st == "APPROVED":
            total_approved += amt
            count_approved += cnt
        elif st == "PENDING_APPROVAL":
            total_pending += amt
            count_pending += cnt
        elif st == "REJECTED":
            total_rejected += amt
            count_rejected += cnt

    conn.close()

    return {
        "summary": {
            "total_requested": round(total_requested, 2),
            "total_approved": round(total_approved, 2),
            "total_pending": round(total_pending, 2),
            "total_rejected": round(total_rejected, 2),
            "count_approved": count_approved,
            "count_pending": count_pending,
            "count_rejected": count_rejected,
            "total_count": len(rows)
        },
        "expenses": rows
    }


@router.get("/export")
def export_expense_requests(
    status_filter: Optional[str] = "ALL",
    format: str = Query("csv", pattern="^(csv|xlsx)$")
):
    """Exports expense requests to CSV or Excel (.xlsx) with GL ledger codes and Zakat indicator."""
    init_expense_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = "SELECT * FROM expense_requests"
    params = []
    if status_filter and status_filter != "ALL":
        query += " WHERE status = ?"
        params.append(status_filter)
    query += " ORDER BY created_at DESC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not rows:
        raise HTTPException(status_code=400, detail="No expense claims available to export for the given filter.")

    df = pd.DataFrame(rows)
    # Map Zakat boolean to human readable
    if "is_zakat" in df.columns:
        df["is_zakat"] = df["is_zakat"].apply(lambda v: "Yes" if v in [1, True, "1"] else "No")

    rename_map = {
        "id": "Claim ID",
        "created_at": "Submission Date",
        "payment_date": "Payment Date",
        "code": "Project Code",
        "gl_code": "GL Ledger Code",
        "is_zakat": "Zakat Eligible",
        "title": "Expense Title",
        "vendor": "Vendor / Payee",
        "amount": "Amount (£)",
        "heading": "Department",
        "sub_heading": "Office",
        "country": "Country",
        "status": "Status",
        "requested_by": "Requested By",
        "reviewed_by": "Reviewed By",
        "notes": "Notes",
        "review_notes": "Review Notes"
    }

    target_cols = [
        "id", "created_at", "payment_date", "code", "gl_code", "is_zakat",
        "title", "vendor", "amount", "heading", "sub_heading", "country",
        "status", "requested_by", "reviewed_by", "notes", "review_notes"
    ]
    df = df[[c for c in target_cols if c in df.columns]]
    df = df.rename(columns=rename_map)

    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    if format.lower() == "xlsx":
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Expense Claims")
        buffer.seek(0)
        headers = {"Content-Disposition": f'attachment; filename="expenses_{status_filter.lower()}_{date_str}.xlsx"'}
        return Response(
            content=buffer.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers
        )
    else:
        csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
        headers = {"Content-Disposition": f'attachment; filename="expenses_{status_filter.lower()}_{date_str}.csv"'}
        return Response(
            content=csv_bytes,
            media_type="text/csv",
            headers=headers
        )


@router.post("/submit")
def submit_expense(payload: SubmitExpenseRequest):
    """Submits a new project expense request with deduplication guard and dispatches approval notification email."""
    init_expense_db()
    
    # ----- Deduplication Guard -----
    # Prevent duplicate submissions with same code + title + amount + payment_date within 60 seconds
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, created_at FROM expense_requests 
        WHERE code = ? AND title = ? AND amount = ? AND payment_date = ?
        AND created_at >= datetime('now', '-60 seconds')
        ORDER BY created_at DESC LIMIT 1
    """, (payload.code.strip(), payload.title.strip(), payload.amount, payload.payment_date))
    
    dup_row = cursor.fetchone()
    conn.close()
    
    if dup_row:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Duplicate expense detected! An identical claim ({dup_row[0]}) was submitted within the last 60 seconds for code '{payload.code}', title '{payload.title}', amount £{payload.amount:,.2f}. Please wait or modify the details."
        )
    
    # ----- Resolve Classification Details & GL Ledger Code -----
    df_raw = load_data()
    matrix_df = get_classification_matrix(df_raw).fillna("Unassigned")
    
    heading, sub_heading, country = "Unassigned", "Unassigned", "Unassigned"
    target_code = payload.code.strip().lower()

    if not df_raw.empty and "Code" in df_raw.columns:
        match_df = df_raw[df_raw["Code"].astype(str).str.strip().str.lower() == target_code]
        if not match_df.empty:
            first_r = match_df.iloc[0]
            heading = str(first_r.get("Heading", "Unassigned"))
            sub_heading = str(first_r.get("Sub-Heading", "Unassigned"))
            country = str(first_r.get("Country", "Unassigned"))

    if heading == "Unassigned" and not matrix_df.empty and "Code" in matrix_df.columns:
        for _, r in matrix_df.iterrows():
            if str(r.get("Code", "")).strip().lower() == target_code:
                heading = str(r.get("Heading", "Unassigned"))
                sub_heading = str(r.get("Sub-Heading", "Unassigned"))
                country = str(r.get("Country", "Unassigned"))
                break

    from core.data_processor import get_code_to_classification_map
    central_map = get_code_to_classification_map()
    c_info = central_map.get(target_code, {})

    is_zkt_bool = bool(payload.is_zakat)
    gl_code = (payload.gl_code or "").strip()
    if not gl_code:
        if is_zkt_bool:
            gl_code = str(c_info.get("Legacy Zakat Code") or c_info.get("Legacy Non-Zakat Code") or "")
        else:
            gl_code = str(c_info.get("Legacy Non-Zakat Code") or c_info.get("Legacy Zakat Code") or "")

    expense_id = f"EXP-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    token = uuid.uuid4().hex

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO expense_requests 
        (id, code, gl_code, is_zakat, heading, sub_heading, country, title, vendor, amount, payment_date, notes, status, requested_by, approval_token)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_APPROVAL', ?, ?)
    """, (
        expense_id, payload.code.strip(), gl_code, 1 if is_zkt_bool else 0, heading, sub_heading, country,
        payload.title.strip(), payload.vendor.strip(), payload.amount, payload.payment_date,
        payload.notes, payload.requested_by, token
    ))
    conn.commit()
    conn.close()
    clear_expenses_cache()

    dest_email, approve_url, reject_url, email_sent, send_error = dispatch_approval_email(
        expense_id, payload.title.strip(), payload.amount, payload.code.strip(), payload.requested_by, token,
        gl_code=gl_code, is_zakat=is_zkt_bool
    )

    broadcast_event_sync("EXPENSE_SUBMITTED", {
        "id": expense_id, 
        "code": payload.code.strip(), 
        "gl_code": gl_code,
        "is_zakat": is_zkt_bool,
        "amount": payload.amount
    })

    result = {
        "status": "success",
        "expense_id": expense_id,
        "gl_code": gl_code,
        "is_zakat": is_zkt_bool,
        "approval_email_sent_to": dest_email,
        "email_actually_sent": email_sent,
        "approve_url": approve_url,
        "reject_url": reject_url,
        "message": f"Expense claim {expense_id} submitted (GL: {gl_code or 'N/A'})! Approval notification dispatched to '{dest_email}'."
    }
    if not email_sent:
        result["email_warning"] = f"Email could not be sent: {send_error}. Configure SMTP_USER and SMTP_PASSWORD in .env to enable email delivery."
    
    return result


@router.post("/review")
def review_expense(payload: ReviewExpenseRequest):
    """Approve or Reject an expense request from Super Admin UI."""
    if payload.user_role != "super_admin" and not payload.can_edit_donors:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Approving/Rejecting expense requests is restricted to Super Admins."
        )

    action_status = payload.action.upper()
    if action_status not in ["APPROVED", "REJECTED"]:
        raise HTTPException(status_code=400, detail="Invalid action. Must be APPROVED or REJECTED.")

    init_expense_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE expense_requests 
        SET status = ?, reviewed_by = ?, review_notes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (action_status, payload.user_role, payload.review_notes, payload.expense_id))
    
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    clear_expenses_cache()

    if rows_affected == 0:
        raise HTTPException(status_code=404, detail="Expense request ID not found.")

    broadcast_event_sync("EXPENSE_REVIEWED", {"id": payload.expense_id, "action": action_status})

    return {
        "status": "success",
        "message": f"Expense request {payload.expense_id} has been {action_status}!"
    }


@router.post("/delete")
def delete_expense(payload: DeleteExpenseRequest):
    """Delete an expense request. Only Super Admins can delete."""
    if payload.user_role != "super_admin" and not payload.can_edit_donors:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Deleting expense requests is restricted to Super Admins."
        )

    init_expense_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    
    # Fetch the expense first to return info
    cursor.execute("SELECT id, code, title, amount, status FROM expense_requests WHERE id = ?", (payload.expense_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Expense request '{payload.expense_id}' not found.")
    
    exp_id, exp_code, exp_title, exp_amount, exp_status = row
    
    cursor.execute("DELETE FROM expense_requests WHERE id = ?", (payload.expense_id,))
    conn.commit()
    conn.close()
    clear_expenses_cache()

    broadcast_event_sync("EXPENSE_DELETED", {"id": payload.expense_id, "code": exp_code})

    return {
        "status": "success",
        "message": f"Expense '{exp_id}' (Code: {exp_code}, £{exp_amount:,.2f}) has been permanently deleted.",
        "deleted_expense": {
            "id": exp_id,
            "code": exp_code,
            "title": exp_title,
            "amount": exp_amount,
            "previous_status": exp_status
        }
    }


@router.get("/action-email")
def handle_email_approval(id: str, token: str, action: str):
    """Handles email link approval/rejection sync."""
    action_status = action.upper()
    if action_status not in ["APPROVED", "REJECTED"]:
        raise HTTPException(status_code=400, detail="Invalid action.")

    init_expense_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE expense_requests 
        SET status = ?, reviewed_by = 'Super Admin (via Email Link)', updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND approval_token = ?
    """, (action_status, id, token))
    
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    clear_expenses_cache()

    if rows_affected == 0:
        return {"status": "error", "message": "Invalid link or token expired."}

    broadcast_event_sync("EXPENSE_REVIEWED", {"id": id, "action": action_status, "source": "email_link"})

    return {
        "status": "success",
        "message": f"Expense request {id} has been marked as {action_status} via email sync!"
    }


@router.get("/settings")
def get_expense_settings():
    """Returns all SMTP + approval email settings. Password is masked."""
    init_expense_db()
    cfg = _get_smtp_config()
    smtp_configured = bool(cfg.get('smtp_user') and cfg.get('smtp_password'))
    password_set = bool(cfg.get('smtp_password'))

    return {
        "approval_email": cfg.get('approval_email', ''),
        "smtp_host": cfg.get('smtp_host', 'smtp.gmail.com'),
        "smtp_port": int(cfg.get('smtp_port', 587)),
        "smtp_user": cfg.get('smtp_user', ''),
        "smtp_password_set": password_set,   # never return the actual password
        "smtp_from_name": cfg.get('smtp_from_name', 'Rethink Charity CRM'),
        "smtp_from_email": cfg.get('smtp_from_email', ''),
        "smtp_configured": smtp_configured,
    }


@router.post("/settings")
def update_expense_settings(payload: UpdateSmtpSettingsRequest):
    """Updates all SMTP + approval email settings. Super Admin only."""
    if payload.user_role not in ["super_admin", "admin"] and not payload.can_edit_donors:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Updating email settings is restricted to Super Admins."
        )

    init_expense_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    cursor = conn.cursor()

    # Ensure unique constraint exists
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_system_settings_key ON system_settings(setting_key);")

    upsert = """
        INSERT INTO system_settings (setting_key, setting_value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(setting_key) DO UPDATE
        SET setting_value = excluded.setting_value, updated_at = CURRENT_TIMESTAMP
    """

    updates = [
        ('approval_email', (payload.approval_email or "").strip()),
        ('smtp_host', (payload.smtp_host or "").strip()),
        ('smtp_port', str(payload.smtp_port or 587)),
        ('smtp_user', (payload.smtp_user or "").strip()),
        ('smtp_from_name', (payload.smtp_from_name or "").strip()),
        ('smtp_from_email', (payload.smtp_from_email or "").strip()),
    ]
    cursor.executemany(upsert, updates)

    # Only update password if a new one was provided (non-empty)
    if payload.smtp_password and payload.smtp_password.strip():
        encrypted_pwd = encrypt_string(payload.smtp_password.strip())
        cursor.execute(upsert, ('smtp_password', encrypted_pwd))

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "message": "Email & SMTP settings saved successfully!"
    }


@router.post("/test-email")
def test_smtp_email(payload: TestEmailRequest):
    """Sends a test email using current SMTP settings. Super Admin only."""
    if payload.user_role != "super_admin" and not payload.can_edit_donors:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sending test emails is restricted to Super Admins."
        )

    init_expense_db()
    smtp_cfg = _get_smtp_config()
    dest_email = smtp_cfg.get('approval_email', APPROVAL_EMAIL)

    html_body = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 560px; margin: 0 auto; background: #0F172A; border-radius: 16px; overflow: hidden; border: 1px solid rgba(255,255,255,0.1);">
      <div style="background: linear-gradient(135deg, #8B5CF6, #06B6D4); padding: 24px 32px;">
        <h1 style="margin: 0; font-size: 18px; font-weight: 800; color: #fff;">✅ SMTP Test Email</h1>
        <p style="margin: 4px 0 0; font-size: 12px; color: rgba(255,255,255,0.8);">Rethink Charity CRM — Email Settings</p>
      </div>
      <div style="padding: 28px 32px; color: #94A3B8; font-size: 14px; line-height: 1.6;">
        <p>Your SMTP configuration is working correctly! 🎉</p>
        <p style="margin-top: 16px; font-size: 12px; color: #475569;">
          Server: <strong style="color: #38BDF8;">{smtp_cfg.get('smtp_host')}:{smtp_cfg.get('smtp_port')}</strong><br>
          Sender: <strong style="color: #38BDF8;">{smtp_cfg.get('smtp_from_name')} &lt;{smtp_cfg.get('smtp_from_email') or smtp_cfg.get('smtp_user')}&gt;</strong>
        </p>
      </div>
    </div>
    """
    plain_body = "SMTP Test Email from Rethink Charity CRM — your configuration is working correctly!"
    subject = "[CRM Test] SMTP Configuration Verified — Rethink Charity"

    success, error = _send_smtp_email(smtp_cfg, dest_email, subject, html_body, plain_body)

    if success:
        return {"status": "success", "message": f"Test email sent successfully to '{dest_email}'! Check your inbox."}
    else:
        raise HTTPException(status_code=500, detail=f"Test email failed: {error}")


# ── Internal Fund Transfers Between Project Codes ───────────────────────

@router.get("/transfers")
def get_code_transfers(code: Optional[str] = None, search: Optional[str] = None, limit: int = 500):
    """Retrieves all internal fund transfer records with optional code and keyword search."""
    init_expense_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    query = "SELECT * FROM code_transfers WHERE 1=1"
    params = []
    if code and code.strip():
        c_clean = code.strip().upper()
        query += " AND (UPPER(source_code) = ? OR UPPER(destination_code) = ?)"
        params.extend([c_clean, c_clean])
    if search and search.strip():
        s_clean = f"%{search.strip().upper()}%"
        query += " AND (UPPER(source_code) LIKE ? OR UPPER(destination_code) LIKE ? OR UPPER(reason) LIKE ? OR UPPER(transferred_by) LIKE ? OR UPPER(id) LIKE ?)"
        params.extend([s_clean, s_clean, s_clean, s_clean, s_clean])

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    total_amount = sum(r.get("amount", 0.0) for r in rows)
    return {
        "transfers": rows,
        "total_count": len(rows),
        "total_amount": round(total_amount, 2)
    }


@router.post("/transfers")
def create_code_transfer(payload: TransferFundsRequest):
    """Transfers funds from one project code to another, validating available balance and Super Admin permissions."""
    if payload.user_role not in ["super_admin", "admin"] and not payload.can_edit_donors:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Transferring funds between project codes is restricted to Super Admins."
        )

    src = payload.source_code.strip().upper()
    dst = payload.destination_code.strip().upper()
    amount = float(payload.amount or 0)
    reason = payload.reason.strip()

    if not src or not dst:
        raise HTTPException(status_code=400, detail="Source and destination project codes are required.")
    if src == dst:
        raise HTTPException(status_code=400, detail="Source and destination project codes cannot be identical.")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Transfer amount must be greater than £0.00.")
    if not reason:
        raise HTTPException(status_code=400, detail="A reason / reference note is required for financial audit tracking.")

    init_expense_db()

    # Verify source code available balance
    all_codes = get_project_codes(force_reload=True)
    src_obj = next((c for c in all_codes if c["code"] == src), None)
    if not src_obj:
        raise HTTPException(status_code=404, detail=f"Source project code '{src}' does not exist.")

    available_balance = src_obj.get("net_balance", 0.0)
    if amount > available_balance:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient funds on '{src}'. Available balance is £{available_balance:,.2f}, but requested transfer is £{amount:,.2f}."
        )

    dst_obj = next((c for c in all_codes if c["code"] == dst), None)
    if not dst_obj:
        raise HTTPException(status_code=404, detail=f"Destination project code '{dst}' does not exist.")

    transfer_id = f"TRF-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    t_date = payload.transfer_date.strip() if payload.transfer_date else datetime.now().strftime("%Y-%m-%d")

    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=15.0)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO code_transfers (id, transfer_date, source_code, destination_code, amount, reason, transferred_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (transfer_id, t_date, src, dst, amount, reason, payload.transferred_by or "Super Admin"))
    conn.commit()
    conn.close()

    clear_expenses_cache()
    broadcast_event_sync("BALANCE_TRANSFERRED", {
        "id": transfer_id,
        "source_code": src,
        "destination_code": dst,
        "amount": amount,
        "reason": reason,
        "transferred_by": payload.transferred_by
    })

    return {
        "status": "success",
        "message": f"Successfully transferred £{amount:,.2f} from '{src}' to '{dst}'.",
        "transfer_id": transfer_id,
        "source_code": src,
        "destination_code": dst,
        "amount": amount
    }


@router.delete("/transfers/{transfer_id}")
def void_code_transfer(transfer_id: str, user_role: str = "super_admin", can_edit_donors: bool = False):
    """Voids / deletes an internal fund transfer, restoring the original balances."""
    if user_role not in ["super_admin", "admin"] and not can_edit_donors:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Voiding fund transfers is restricted to Super Admins."
        )

    init_expense_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    cur = conn.cursor()
    cur.execute("SELECT * FROM code_transfers WHERE id = ?", (transfer_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Transfer ID '{transfer_id}' not found.")

    cur.execute("DELETE FROM code_transfers WHERE id = ?", (transfer_id,))
    conn.commit()
    conn.close()

    clear_expenses_cache()
    broadcast_event_sync("BALANCE_TRANSFERRED", {"id": transfer_id, "action": "VOIDED"})

    return {
        "status": "success",
        "message": f"Transfer '{transfer_id}' has been voided and balances have been restored."
    }


@router.get("/transfers/export")
def export_transfers(format: str = "csv", code: Optional[str] = None):
    """Exports all fund transfers to CSV or Excel format."""
    init_expense_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    query = "SELECT * FROM code_transfers"
    params = []
    if code and code.strip():
        c_clean = code.strip().upper()
        query += " WHERE UPPER(source_code) = ? OR UPPER(destination_code) = ?"
        params.extend([c_clean, c_clean])
    query += " ORDER BY created_at DESC"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    rename_map = {
        "id": "Transfer ID",
        "transfer_date": "Transfer Date",
        "source_code": "Source Code",
        "destination_code": "Destination Code",
        "amount": "Amount (£)",
        "reason": "Reason / Reference Notes",
        "transferred_by": "Transferred By",
        "created_at": "Timestamp"
    }
    df = df.rename(columns=rename_map)
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    if format.lower() == "xlsx":
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Fund Transfers")
        buffer.seek(0)
        headers = {"Content-Disposition": f'attachment; filename="code_transfers_{date_str}.xlsx"'}
        return Response(
            content=buffer.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers
        )
    else:
        csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
        headers = {"Content-Disposition": f'attachment; filename="code_transfers_{date_str}.csv"'}
        return Response(
            content=csv_bytes,
            media_type="text/csv",
            headers=headers
        )
