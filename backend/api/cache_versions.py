"""Cheap 'has the data changed?' check for the frontend (any logged-in user, own company only)."""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from backend.api.auth import get_current_user, require_company_access
from core.cache import version_token

router = APIRouter(prefix="/api/cache", tags=["Cache"])

_SCOPES = ["donations", "classification", "tracker", "payouts", "fundraisers", "expenses"]


@router.get("/versions")
def data_versions(company_id: Optional[str] = Query("rethink"), user: dict = Depends(get_current_user)):
    comp = require_company_access(user, company_id or "rethink")
    return {"company_id": comp, "token": version_token(_SCOPES, comp)}
