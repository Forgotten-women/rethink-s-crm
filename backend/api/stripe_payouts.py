"""
FastAPI Router for Stripe Payout Reconciliation & Approval
Endpoints for querying payouts, running read-only reconciliations, re-syncing with CRM,
approving and sending to Slack, and downloading enriched audit files.
"""

from fastapi import APIRouter, Query, HTTPException, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os

from backend.api.auth import require_super_admin
from core.stripe_reconciliation import (
    list_stripe_payouts,
    reconcile_stripe_payout,
    resync_payout_with_crm,
    approve_and_send_to_slack,
    resend_payout_to_slack
)
from core.database import get_db_connection

router = APIRouter(prefix="/api/payouts/stripe", tags=["Stripe Payouts"])


class ReconcileRequest(BaseModel):
    payout_id: str
    company_id: Optional[str] = "rethink"


class ApproveRequest(BaseModel):
    payout_id: str
    approved_by: Optional[str] = "Admin"


class ResendRequest(BaseModel):
    payout_id: str


class ResyncRequest(BaseModel):
    payout_id: str
    company_id: Optional[str] = "rethink"


@router.get("/list")
def get_stripe_payouts(limit: int = Query(25, ge=1, le=100)):
    """Lists Stripe payouts with their current CRM reconciliation and approval states."""
    try:
        payouts = list_stripe_payouts(limit=limit)
        return {"payouts": payouts, "count": len(payouts)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reconcile")
def run_payout_reconciliation(req: ReconcileRequest, current_user = Depends(require_super_admin)):
    """Runs read-only Stripe reconciliation for a payout, matching against CRM data."""
    try:
        summary = reconcile_stripe_payout(payout_id=req.payout_id, company_id=req.company_id or "rethink")
        return {"success": True, "summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resync")
def resync_payout_classifications(req: ResyncRequest, current_user = Depends(require_super_admin)):
    """
    Re-syncs an already reconciled payout against current CRM classifications and donations.
    Prevents discrepancies if someone manually edited a donation code or classification in CRM.
    """
    try:
        result = resync_payout_with_crm(payout_id=req.payout_id, company_id=req.company_id or "rethink")
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approve")
def approve_payout(req: ApproveRequest, current_user = Depends(require_super_admin)):
    """Approves a payout and posts the verified financial breakdown + CSV report to Slack #rt-payouts."""
    try:
        approver = req.approved_by or (current_user.get("email") if isinstance(current_user, dict) else "Admin")
        result = approve_and_send_to_slack(payout_id=req.payout_id, approved_by=approver)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resend")
def resend_to_slack(req: ResendRequest, current_user = Depends(require_super_admin)):
    """Resends an already approved payout report to Slack #rt-payouts."""
    try:
        result = resend_payout_to_slack(payout_id=req.payout_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download")
def download_enriched_csv(payout_id: str = Query(...)):
    """Downloads the audit-ready enriched reconciliation CSV for a payout."""
    conn = get_db_connection(timeout=10.0)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT csv_path FROM stripe_payout_reports WHERE payout_id = ?", (payout_id,))
        row = cursor.fetchone()
        if not row or not row[0] or not os.path.exists(row[0]):
            raise HTTPException(status_code=404, detail="Reconciliation CSV file not found.")
        file_path = row[0]
        return FileResponse(file_path, filename=os.path.basename(file_path), media_type="text/csv")
    finally:
        conn.close()


@router.get("/items")
def get_payout_items(
    payout_id: str = Query(...),
    source_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200)
):
    """Returns itemized transactions for a reconciled Stripe payout."""
    conn = get_db_connection(timeout=10.0)
    try:
        cursor = conn.cursor()
        where_clauses = ["payout_id = ?"]
        params = [payout_id]

        if source_type and source_type != "ALL":
            where_clauses.append("source_type = ?")
            params.append(source_type.lower())

        where_sql = " AND ".join(where_clauses)
        cursor.execute(f"SELECT COUNT(*) FROM stripe_payout_items WHERE {where_sql}", params)
        total = cursor.fetchone()[0]

        offset = (page - 1) * page_size
        cursor.execute(f"""
            SELECT balance_transaction_id, charge_id, payment_intent_id, source_type, donation_id,
                   created_at, gross, fee, net, currency, donor_name, donor_email, project_name,
                   code, COALESCE(heading, department), COALESCE(subheading, office), department, office,
                   portfolio, country, programme_fund, fund_code, zakat_eligibility,
                   location_name, donor_phone, gift_aid, zakat_status
            FROM stripe_payout_items
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, params + [page_size, offset])

        cols = [
            "balance_transaction_id", "charge_id", "payment_intent_id", "source_type", "donation_id",
            "created_at", "gross", "fee", "net", "currency", "donor_name", "donor_email", "project_name",
            "code", "heading", "subheading", "department", "office",
            "portfolio", "country", "programme_fund", "fund_code", "zakat_eligibility",
            "location_name", "donor_phone", "gift_aid", "zakat_status"
        ]
        items = [dict(zip(cols, r)) for r in cursor.fetchall()]

        return {
            "payout_id": payout_id,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "items": items
        }
    finally:
        conn.close()
