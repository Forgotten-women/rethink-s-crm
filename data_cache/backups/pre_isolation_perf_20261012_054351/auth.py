import logging
import os
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from core.event_log import log_event
from core.auth import (
    authenticate_user,
    change_user_password,
    get_user_by_identity,
    create_access_token,
    decode_access_token
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

security_bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger("auth")


def _legacy_auth_fallback_enabled() -> bool:
    """Header/query/body identity fallbacks are spoofable (no password, no signature).
    Off by default; set LEGACY_AUTH_FALLBACK=1 only as a temporary escape hatch."""
    return os.environ.get("LEGACY_AUTH_FALLBACK", "0").strip().lower() in ("1", "true", "yes", "on")


def _user_from_claims(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Builds a session user from verified JWT claims (e.g. Supabase-backed accounts
    that have no row in the local users table)."""
    role = payload.get("role") or "admin"
    is_super = role == "super_admin"
    return {
        "id": None,
        "username": payload.get("username") or str(payload["sub"]).split("@")[0],
        "email": payload["sub"],
        "role": role,
        "can_edit_donors": 1 if is_super else 0,
        "can_edit_matrix": 1 if is_super else 0,
        "can_manage_tags": 1 if is_super else 0,
        "can_purge_data": 1 if is_super else 0,
        "allowed_companies": payload.get("allowed_companies") or ["ALL"],
        "provider": "token",
    }


async def _resolve_legacy_identity(request: Request, user_identity: Optional[str]) -> Optional[Dict[str, Any]]:
    """Pre-JWT identity resolution kept only behind LEGACY_AUTH_FALLBACK."""
    # Fallback 1: Custom Headers
    if request:
        hdr_identity = (
            request.headers.get("x-user-email")
            or request.headers.get("x-user-identity")
            or request.headers.get("x-user-name")
        )
        if hdr_identity and hdr_identity.strip():
            user = get_user_by_identity(hdr_identity.strip())
            if user:
                return user

        hdr_role = request.headers.get("x-user-role")
        if hdr_role:
            clean_role = hdr_role.strip().lower()
            if clean_role == "super_admin":
                user = get_user_by_identity("superadmin@analytics.com") or get_user_by_identity("superadmin")
                if user:
                    return user
            elif clean_role:
                user = get_user_by_identity(f"{clean_role}@analytics.com") or get_user_by_identity(clean_role)
                if user:
                    return user

    # Fallback 2: Query Parameters
    target_param_identity = (
        user_identity
        or (request.query_params.get("user_email") if request else None)
        or (request.query_params.get("user_identity") if request else None)
        or (request.query_params.get("email") if request else None)
    )
    if target_param_identity and str(target_param_identity).strip():
        user = get_user_by_identity(str(target_param_identity).strip())
        if user:
            return user

    # Fallback 3: Request Body (JSON or Form/Multipart for POST/PUT/PATCH requests)
    if request and request.method in ["POST", "PUT", "PATCH"]:
        try:
            content_type = (request.headers.get("content-type") or "").lower()
            if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
                form = await request.form()
                form_id = form.get("user_identity") or form.get("user_email") or form.get("email") or form.get("username")
                if form_id and str(form_id).strip():
                    user = get_user_by_identity(str(form_id).strip())
                    if user:
                        return user
                form_role = form.get("user_role")
                if form_role:
                    clean_role = str(form_role).strip().lower()
                    if clean_role == "super_admin":
                        user = get_user_by_identity("superadmin@analytics.com") or get_user_by_identity("superadmin")
                        if user:
                            return user
                    elif clean_role:
                        user = get_user_by_identity(f"{clean_role}@analytics.com") or get_user_by_identity(clean_role)
                        if user:
                            return user
            else:
                body = await request.json()
                if isinstance(body, dict):
                    body_id = (
                        body.get("user_identity")
                        or body.get("user_email")
                        or body.get("email")
                        or body.get("username")
                    )
                    if body_id and str(body_id).strip():
                        user = get_user_by_identity(str(body_id).strip())
                        if user:
                            return user

                    body_role = body.get("user_role")
                    if body_role:
                        clean_role = str(body_role).strip().lower()
                        if clean_role == "super_admin":
                            user = get_user_by_identity("superadmin@analytics.com") or get_user_by_identity("superadmin")
                            if user:
                                return user
                        elif clean_role:
                            user = get_user_by_identity(f"{clean_role}@analytics.com") or get_user_by_identity(clean_role)
                            if user:
                                return user
        except Exception:
            pass

    return None


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    user_identity: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """
    Dependency that resolves the authenticated user from a signed JWT Bearer token.
    Unsigned identity hints (X-User-* headers, user_identity query/body, user_role)
    are ignored unless LEGACY_AUTH_FALLBACK is enabled.
    """
    token_str = None
    if credentials and credentials.credentials:
        token_str = credentials.credentials
    elif request:
        auth_hdr = request.headers.get("authorization") or request.headers.get("Authorization") or ""
        if auth_hdr.strip().lower().startswith("bearer "):
            token_str = auth_hdr.strip()[7:].strip()

    if token_str:
        payload = decode_access_token(token_str)
        if payload and payload.get("sub"):
            return get_user_by_identity(payload["sub"]) or _user_from_claims(payload)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token has expired or is invalid. Please log in again."
        )

    if _legacy_auth_fallback_enabled():
        user = await _resolve_legacy_identity(request, user_identity)
        if user:
            logger.warning(
                "LEGACY_AUTH_FALLBACK used for %s %s (resolved %s). Send a Bearer token instead.",
                request.method if request else "?", request.url.path if request else "?", user.get("email")
            )
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication credentials were not provided."
    )


def user_company_ids(user: Dict[str, Any]) -> Optional[set]:
    """Companies a user may access; None means all (super admin or ["ALL"])."""
    if user.get("role") == "super_admin":
        return None
    allowed = user.get("allowed_companies") or ["ALL"]
    if isinstance(allowed, str):
        allowed = [allowed]
    normalized = {str(c).strip().lower() for c in allowed if str(c).strip()}
    if not normalized or "all" in normalized:
        return None
    return normalized


def require_company_access(user: Dict[str, Any], company_id: Optional[str]) -> str:
    """Raises 403 unless the user may act for company_id. 'all' requires access to every company.
    Returns the normalized company id."""
    comp = (company_id or "").strip().lower()
    if not comp:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="company_id is required.")
    allowed = user_company_ids(user)
    if allowed is None:
        return comp
    if comp == "all" or comp not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Your account does not have access to company '{comp}'."
        )
    return comp


def require_super_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Dependency that enforces super_admin role."""
    if user.get("role") != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation is restricted to Super Admin accounts."
        )
    return user


class LoginRequest(BaseModel):
    identity: str = ""
    username: str = ""
    email: str = ""
    password: str

    def get_user_identity(self) -> str:
        return (self.identity or self.username or self.email or "").strip()


class ChangePasswordRequest(BaseModel):
    user_identity: str
    current_password: str
    new_password: str


@router.post("/login")
def login_endpoint(payload: LoginRequest):
    user_id = payload.get_user_identity()
    if not user_id or not payload.password.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email/username and password are required."
        )
    user = authenticate_user(user_id, payload.password)
    if not user:
        log_event("auth.login_failed", category="security", level="warning", actor=user_id,
                  message=f"Failed login for {user_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or user not found."
        )

    # Generate JWT Bearer Token
    token_claims = {
        "sub": user["email"],
        "username": user["username"],
        "role": user["role"]
    }
    access_token = create_access_token(token_claims)
    log_event("auth.login", category="security", actor=user["email"], role=user["role"],
              message=f"{user['email']} logged in")

    return {
        "status": "success",
        "user": user,
        "access_token": access_token,
        "token_type": "bearer"
    }


@router.get("/me")
def get_me_endpoint(current_user: Dict[str, Any] = Depends(get_current_user)):
    return {"status": "success", "user": current_user}


@router.post("/change-password")
def change_password_endpoint(payload: ChangePasswordRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    # Verify that the user is changing their own password or is super_admin
    if current_user.get("role") != "super_admin":
        curr_ident = current_user.get("email", "").lower()
        req_ident = payload.user_identity.strip().lower()
        if curr_ident != req_ident and current_user.get("username", "").lower() != req_ident:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You may only change your own password."
            )

    ok, msg = change_user_password(
        payload.user_identity,
        payload.current_password,
        payload.new_password
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg
        )
    return {"status": "success", "message": msg}
