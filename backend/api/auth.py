from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from core.auth import (
    authenticate_user,
    change_user_password,
    get_user_by_identity,
    create_access_token,
    decode_access_token
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

security_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    user_identity: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """
    Dependency that resolves the authenticated user.
    1. Verifies JWT Bearer token when provided (via credentials or Authorization header).
    2. Fallback to X-User-Email / X-User-Identity header.
    3. Fallback to user_identity query parameter.
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
        if payload and "sub" in payload:
            user = get_user_by_identity(payload["sub"])
            if user:
                return user

    # Fallback to Custom Headers
    if request:
        hdr_identity = request.headers.get("x-user-email") or request.headers.get("x-user-identity")
        if hdr_identity and hdr_identity.strip():
            user = get_user_by_identity(hdr_identity.strip())
            if user:
                return user

    # Fallback to Query Parameter
    if user_identity and user_identity.strip():
        user = get_user_by_identity(user_identity.strip())
        if user:
            return user

    if token_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token has expired or is invalid. Please log in again."
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication credentials were not provided."
    )


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
