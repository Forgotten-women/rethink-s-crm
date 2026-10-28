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
    decode_access_token,
    user_from_token,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

security_bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger("auth")


def _legacy_auth_fallback_enabled() -> bool:
    """Header/query/body identity fallbacks are spoofable (no password, no signature).
    Off by default; set LEGACY_AUTH_FALLBACK=1 only as a temporary escape hatch."""
    return os.environ.get("LEGACY_AUTH_FALLBACK", "0").strip().lower() in ("1", "true", "yes", "on")


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
        # the account as it is NOW: removed/disabled accounts and sessions ended by "sign out everywhere"
        # (token_version bumped) are refused
        user = user_from_token(token_str)
        if user:
            return user
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
    if "all" in normalized:
        return None
    return normalized  # empty = no charity at all (never "everything")


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


def _route_company_default(request: Request) -> tuple:
    """(has_company_param, default) for the matched endpoint, so a request that leaves company_id out is
    checked against the company the endpoint will actually use (e.g. Query("rethink"))."""
    import inspect
    endpoint = request.scope.get("endpoint")
    route = request.scope.get("route")
    if endpoint is None and route is not None:
        endpoint = getattr(route, "endpoint", None)
    if endpoint is None:
        return False, None
    target = inspect.unwrap(endpoint)
    try:
        params = inspect.signature(target).parameters
    except (TypeError, ValueError):
        return False, None
    param = params.get("company_id")
    if param is not None:
        default = param.default
        if default is inspect.Parameter.empty:
            return True, None
        value = getattr(default, "default", default)  # Query("rethink") -> "rethink"
        return True, (value if isinstance(value, str) else None)  # Query(...) (required) -> None
    # a JSON body model with a company_id field (e.g. company_id: str = "rethink") left out of the request
    from pydantic import BaseModel as _BaseModel
    for p in params.values():
        ann = p.annotation
        if inspect.isclass(ann) and issubclass(ann, _BaseModel) and "company_id" in ann.model_fields:
            field = ann.model_fields["company_id"]
            return True, (field.default if not field.is_required() and isinstance(field.default, str) else None)
    return False, None


async def _request_inputs(request: Request) -> tuple:
    """(query+path params, JSON body dict, form) of the request. Body/form parsing is cached on the request,
    so the endpoint reads the very same values."""
    body, form = {}, None
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        content_type = (request.headers.get("content-type") or "").lower()
        try:
            if content_type.startswith("application/json"):
                parsed = await request.json()
                body = parsed if isinstance(parsed, dict) else {}
            elif content_type.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
                form = await request.form()
        except Exception:
            pass
    return request.query_params, body, form


def _all_values(name: str, query, body: dict, form, path_params: dict) -> list:
    values = list(query.getlist(name))
    if name in path_params:
        values.append(path_params[name])
    if body.get(name) not in (None, ""):
        values.append(body[name])
    if form is not None:
        values.extend(v for v in form.getlist(name) if isinstance(v, str))
    return [v for v in values if str(v).strip()]


def _requested_companies(query, body: dict, form, path_params: dict) -> list:
    """Every company the request names - including a company an edit would MOVE a record into."""
    found = [str(c) for c in _all_values("company_id", query, body, form, path_params)]
    updated = body.get("updated_fields")
    if isinstance(updated, dict) and str(updated.get("company_id") or "").strip():
        found.append(str(updated["company_id"]))
    columns, values = body.get("target_columns"), body.get("new_values")
    if isinstance(columns, list) and isinstance(values, list):
        found.extend(str(v) for c, v in zip(columns, values) if str(c).strip().lower() == "company_id" and str(v).strip())
    return found


# --- Records addressed by ID ------------------------------------------------------------------------------
# request key -> (table, id column). The owner of the record must be a charity the user may access and, when
# the request names a charity, that same charity; otherwise the record is reported as not found.
_OWNED_RECORDS = {
    "fundraiser_id": ("fundraisers", "id"),
    "expense_id": ("expense_requests", "id"),
    "transfer_id": ("code_transfers", "id"),
    "donation_id": ("donations", '"Donation ID"'),
}


def _record_owners(key: str, value) -> set:
    import sqlite3
    from core.auth import LOCAL_DB_PATH
    table, column = _OWNED_RECORDS[key]
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        rows = conn.execute(f"SELECT DISTINCT LOWER(TRIM(COALESCE(company_id, 'rethink'))) FROM {table} "
                            f"WHERE CAST({column} AS TEXT) = ?", (str(value).strip(),)).fetchall()
    except sqlite3.OperationalError:
        return set()
    finally:
        conn.close()
    return {r[0] for r in rows}


def _check_record_ownership(request: Request, user: Dict[str, Any], query, body: dict, form, named: list) -> set:
    allowed = user_company_ids(user)
    found: set = set()
    named_set = {str(c).strip().lower() for c in named if str(c).strip().lower() != "all"}
    for key in _OWNED_RECORDS:
        for value in _all_values(key, query, body, form, dict(request.path_params)):
            owners = _record_owners(key, value)
            if not owners:
                continue  # unknown id: the endpoint returns its own 404
            found |= owners
            if key == "donation_id" and named_set:
                ok = bool(owners & named_set)  # the same Donation ID may exist in both charities
            else:
                ok = (allowed is None or owners <= allowed) and (not named_set or owners <= named_set)
            if not ok:
                log_event("access.cross_company_blocked", category="security", level="warning", actor=user.get("email"),
                          path=request.url.path, record=f"{key}={value}", record_company=",".join(sorted(owners)),
                          message=f"Blocked {request.method} {request.url.path}: {key}={value} belongs to "
                                  f"{','.join(sorted(owners))}")
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found for this charity.")
    return found


# Opened from emails without a session; each verifies its own single-use token.
_PUBLIC_API_PATHS = {"/api/expenses/action-email"}
# Loaded by <img> tags (which can't send the session token); branding only.
import re as _re
_PUBLIC_GET_PATTERN = _re.compile(r"^/api/admin/companies/[A-Za-z0-9_-]+/logo$")


async def api_access_guard(request: Request) -> Dict[str, Any]:
    """Router-level isolation for every data API: a valid signed session is required, and every company the
    request names (or the endpoint's default company when none is named) must be one the user may access.
    'all' (or an endpoint whose company defaults to None = every charity) needs access to every charity."""
    if request.url.path in _PUBLIC_API_PATHS or (
            request.method == "GET" and _PUBLIC_GET_PATTERN.match(request.url.path)):
        return {}
    user = await get_current_user(request, None, None)
    query, body, form = await _request_inputs(request)
    requested = _requested_companies(query, body, form, dict(request.path_params))
    if not requested:
        has_param, default = _route_company_default(request)
        if has_param:
            requested = [default if default not in (None, "") else "all"]
    for comp in requested:
        try:
            require_company_access(user, comp)
        except HTTPException:
            log_event("access.cross_company_blocked", category="security", level="warning", actor=user.get("email"),
                      company_id=str(comp).strip().lower(), path=request.url.path,
                      message=f"Blocked {request.method} {request.url.path} for company '{comp}'")
            raise
    owners = _check_record_ownership(request, user, query, body, form, requested)
    enforce_route_permission(request, user, list(requested) + sorted(owners))
    request.state.api_user = user
    return user


def _enforce_record_scope(request: Request, user: Dict[str, Any], companies: list, endpoint) -> None:
    """A person limited to specific fundraisers in a charity may only use endpoints that apply that limit there
    (backend/api/permissions.py SCOPE_AWARE), and may only change fundraisers on their list."""
    from backend.api.permissions import SCOPE_AWARE, SCOPED_FUNDRAISER_WRITES, endpoint_key
    from core.rbac import record_scope
    scopes = (user.get("access") or {}).get("scopes") or {}
    if not scopes:
        return
    comps = {str(c).strip().lower() for c in companies if str(c).strip()} or set(scopes)
    if "all" in comps:  # the consolidated view can't apply a per-charity limit
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Your access is limited to specific fundraisers - choose a charity.")
    key = endpoint_key(endpoint) if endpoint else ""
    for comp in comps:
        scope = record_scope(user, comp, "fundraiser")
        if scope is None:
            continue
        fid = str(request.path_params.get("fundraiser_id") or "")
        allowed = key in SCOPE_AWARE or (key in SCOPED_FUNDRAISER_WRITES and fid in scope)
        if not allowed:
            log_event("access.scope_denied", category="security", level="warning", actor=user.get("email"),
                      path=request.url.path, company_id=comp, endpoint=key,
                      message=f"Refused {request.method} {request.url.path}: account is limited to specific fundraisers in {comp}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail=f"Your access in {comp} is limited to specific fundraisers.")


def enforce_route_permission(request: Request, user: Dict[str, Any], companies: list) -> None:
    """RBAC: the endpoint's required permission (backend/api/permissions.py) must be held for every charity the
    request is about. No charity named at all -> held in at least one charity. Unlisted endpoints are refused."""
    from backend.api.permissions import AllOf, PUBLIC, SIGNED_IN, SUPER, describe, endpoint_key, requirement_for
    from core.rbac import user_has
    endpoint = request.scope.get("endpoint") or getattr(request.scope.get("route"), "endpoint", None)
    req = requirement_for(endpoint)
    # for the activity log: which charity the request was about
    request.state.audit_companies = sorted({str(c).strip().lower() for c in companies if str(c).strip()})
    if req in (PUBLIC, SIGNED_IN):
        return
    is_super = user.get("role") == "super_admin"
    if req == SUPER:
        ok = is_super
    elif req is None:
        ok = False  # deny by default: the endpoint has no permission configured
    else:
        comps = sorted({str(c).strip().lower() for c in companies if str(c).strip()})
        perms = req if isinstance(req, tuple) else (req,)

        def holds(perm: str) -> bool:
            if comps:
                return all(user_has(user, perm, c) for c in comps)
            return any(perm in p for p in ((user.get("access") or {}).get("companies") or {}).values()) or is_super

        ok = all(holds(p) for p in perms) if isinstance(req, AllOf) else any(holds(p) for p in perms)
    if ok and not is_super and req not in (SUPER,):
        _enforce_record_scope(request, user, companies, endpoint)
        from backend.api.permissions import CONTACT_EXPORTS
        if endpoint is not None and endpoint_key(endpoint) in CONTACT_EXPORTS:
            comps = sorted({str(c).strip().lower() for c in companies if str(c).strip()})
            if not comps or not all(user_has(user, "donors.contact", c) for c in comps):
                ok, req = False, "donors.contact"  # the file holds emails / phones / addresses
    if not ok:
        what = "this action" if req is None else describe(req)
        where = ", ".join(sorted({str(c).strip().lower() for c in companies if str(c).strip()})) or "any charity"
        log_event("access.permission_denied", category="security", level="warning", actor=user.get("email"),
                  path=request.url.path, permission=what, company_id=where,
                  endpoint=endpoint_key(endpoint) if endpoint else None,
                  message=f"Refused {request.method} {request.url.path}: needs {what} for {where}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"Your access doesn't include {what} for {where}. Ask an admin if you need it.")


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
    # Only the identity goes in the token; role and permissions are read from the database on every request.
    token_claims = {"sub": user["email"], "tv": int(user.get("token_version") or 0)}
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
