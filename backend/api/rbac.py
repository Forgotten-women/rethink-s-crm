"""
Access management API (RBAC, see core/rbac.py): presets, people, per-charity access, overrides, record scopes.

Rules (all enforced here, on the server):
  * users.view to list, users.manage to change people, users.presets to change presets (router guard +
    backend/api/permissions.py).
  * Super admins can only be changed by super admins; only a super admin can make someone a super admin; the
    last active super admin can't be removed, disabled or demoted.
  * A non-super admin manages only the charities where they hold users.manage ('*' needs it in every charity),
    can't grant a permission they don't hold themselves in that charity, and can't change their own access.
  * Every change bumps the person's version, so their open browser refreshes its access within seconds, and is
    written to the audit log with what changed.
"""
import json
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from config.settings import LOCAL_DB_PATH
from core import rbac
from core.auth import hash_password, init_user_db
from core.event_log import log_event

router = APIRouter(prefix="/api/rbac", tags=["Access control"])


def _actor(request: Request) -> Dict[str, Any]:
    user = getattr(request.state, "api_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return user


def _db() -> sqlite3.Connection:
    init_user_db()
    rbac.init_rbac()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.row_factory = sqlite3.Row
    return conn


def _is_super(user: Dict[str, Any]) -> bool:
    return user.get("role") == "super_admin"


def _managed_companies(actor: Dict[str, Any]) -> Optional[set]:
    """Charities the actor may manage people in; None = all (super admin)."""
    return None if _is_super(actor) else rbac.companies_with(actor, "users.manage")


def _check_can_manage(actor: Dict[str, Any], company: str) -> None:
    managed = _managed_companies(actor)
    if managed is None:
        return
    if company == "*":
        if set(rbac._all_company_ids()) <= managed:
            return
        raise HTTPException(status_code=403, detail="Only someone who manages users in every charity can give access to all charities.")
    if company not in managed:
        raise HTTPException(status_code=403, detail=f"You don't manage users for '{company}'.")


def _actor_perms(actor: Dict[str, Any], company: str) -> Optional[set]:
    """What the actor may hand out in this charity ('*' = what they hold in every charity); None = anything."""
    if _is_super(actor):
        return None
    companies = (actor.get("access") or {}).get("companies") or {}
    if company == "*":
        sets = [set(companies.get(c, [])) for c in rbac._all_company_ids()]
        return set.intersection(*sets) if sets else set()
    return set(companies.get(company, []))


def _target(conn, user_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT id, username, email, role, COALESCE(is_active, 1) AS is_active, display_name "
                       "FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found.")
    return row


def _guard_target(actor: Dict[str, Any], target: sqlite3.Row, allow_self: bool = False) -> None:
    if target["role"] == "super_admin" and not _is_super(actor):
        raise HTTPException(status_code=403, detail="Only a super admin can change a super admin.")
    if not allow_self and target["id"] == actor.get("id") and not _is_super(actor):
        raise HTTPException(status_code=403, detail="You can't change your own access.")


def _active_supers(conn) -> List[int]:
    return [r[0] for r in conn.execute("SELECT id FROM users WHERE role = 'super_admin' AND COALESCE(is_active, 1) = 1")]


def _role_perms(conn, role_id: Optional[int]) -> set:
    if not role_id:
        return set()
    row = conn.execute("SELECT permissions FROM rbac_roles WHERE id = ?", (role_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail=f"Preset {role_id} doesn't exist.")
    return set(json.loads(row[0] or "[]"))


def _user_payload(conn, row: sqlite3.Row) -> Dict[str, Any]:
    uid = row["id"]
    access = [dict(r) for r in conn.execute(
        "SELECT a.company_id, a.role_id, r.name AS role_name FROM rbac_user_access a LEFT JOIN rbac_roles r ON r.id = a.role_id "
        "WHERE a.user_id = ? ORDER BY a.company_id", (uid,))]
    overrides = [dict(r) for r in conn.execute(
        "SELECT company_id, permission, effect FROM rbac_user_overrides WHERE user_id = ? ORDER BY company_id, permission", (uid,))]
    scopes = [dict(r) for r in conn.execute(
        "SELECT company_id, resource, record_id FROM rbac_record_scopes WHERE user_id = ? ORDER BY company_id, resource", (uid,))]
    effective = rbac.effective_access(uid, row["role"] == "super_admin")
    return {"id": uid, "username": row["username"], "email": row["email"], "display_name": row["display_name"] or "",
            "is_super_admin": row["role"] == "super_admin", "is_active": bool(row["is_active"]),
            "access": access, "overrides": overrides, "scopes": scopes,
            "effective": {c: len(p) for c, p in effective["companies"].items()}}


# --- Catalogue & presets ---------------------------------------------------------------------------------------
@router.get("/catalogue")
def get_catalogue():
    return {"resources": rbac.catalogue_for_ui(), "levels": {"read": "Read", "write": "Write", "extra": "Extra switch"}}


@router.get("/roles")
def list_roles():
    conn = _db()
    try:
        usage = {r[0]: r[1] for r in conn.execute("SELECT role_id, COUNT(DISTINCT user_id) FROM rbac_user_access GROUP BY role_id")}
        roles = [{"id": r["id"], "name": r["name"], "description": r["description"] or "", "is_system": bool(r["is_system"]),
                  "permissions": json.loads(r["permissions"] or "[]"), "users": usage.get(r["id"], 0),
                  "updated_at": r["updated_at"], "updated_by": r["updated_by"]}
                 for r in conn.execute("SELECT * FROM rbac_roles ORDER BY is_system DESC, name")]
    finally:
        conn.close()
    return {"roles": roles}


class RoleBody(BaseModel):
    name: str
    description: Optional[str] = ""
    permissions: List[str] = []


def _check_super_only(actor: Dict[str, Any], before: set, after: set) -> None:
    """Super-admin-only permissions (e.g. the activity log) can't be added or removed by anyone else."""
    if _is_super(actor):
        return
    changed = (before ^ after) & rbac.SUPER_ONLY_PERMISSIONS
    if changed:
        raise HTTPException(status_code=403, detail="Only a super admin can change: " + ", ".join(sorted(changed)))


def _check_preset_perms(actor: Dict[str, Any], perms: List[str], before: Optional[set] = None) -> List[str]:
    try:
        clean = rbac.validate_permissions(perms)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _check_super_only(actor, before or set(), set(clean))
    own = _actor_perms(actor, "*")
    if own is not None and not set(clean) <= own:
        raise HTTPException(status_code=403, detail="A preset can't include permissions you don't hold in every charity: "
                                                    + ", ".join(sorted(set(clean) - own)))
    return clean


@router.post("/roles")
def create_role(body: RoleBody, request: Request):
    actor = _actor(request)
    perms = _check_preset_perms(actor, body.permissions)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="A preset needs a name.")
    conn = _db()
    try:
        try:
            rid = conn.execute("INSERT INTO rbac_roles (name, description, permissions, is_system, updated_by) VALUES (?, ?, ?, 0, ?)",
                               (name, (body.description or "").strip(), json.dumps(perms), actor.get("email"))).lastrowid
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail=f"A preset called '{name}' already exists.")
        conn.commit()
    finally:
        conn.close()
    log_event("rbac.role_created", category="security", actor=actor.get("email"), role=name, permissions=perms,
              message=f"Preset '{name}' created with {len(perms)} permissions")
    return {"status": "success", "id": rid}


@router.put("/roles/{role_id}")
def update_role(role_id: int, body: RoleBody, request: Request):
    actor = _actor(request)
    conn = _db()
    try:
        old = conn.execute("SELECT * FROM rbac_roles WHERE id = ?", (role_id,)).fetchone()
        if not old:
            raise HTTPException(status_code=404, detail="Preset not found.")
        before = set(json.loads(old["permissions"] or "[]"))
        perms = _check_preset_perms(actor, body.permissions, before)
        own = _actor_perms(actor, "*")
        if own is not None and not before - set(perms) <= own:  # can't strip what you couldn't give either
            raise HTTPException(status_code=403, detail="This preset holds permissions you don't have; ask a super admin.")
        try:
            conn.execute("UPDATE rbac_roles SET name = ?, description = ?, permissions = ?, updated_at = CURRENT_TIMESTAMP, "
                         "updated_by = ? WHERE id = ?",
                         (body.name.strip() or old["name"], (body.description or "").strip(), json.dumps(perms),
                          actor.get("email"), role_id))
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail=f"A preset called '{body.name}' already exists.")
        rbac.bump_roles(conn)  # everyone on it gets the change (and their open page refreshes)
        conn.commit()
    finally:
        conn.close()
    log_event("rbac.role_updated", category="security", actor=actor.get("email"), role=old["name"],
              added=sorted(set(perms) - before), removed=sorted(before - set(perms)),
              message=f"Preset '{old['name']}' changed: +{len(set(perms) - before)} / -{len(before - set(perms))}")
    return {"status": "success"}


@router.delete("/roles/{role_id}")
def delete_role(role_id: int, request: Request):
    actor = _actor(request)
    conn = _db()
    try:
        old = conn.execute("SELECT * FROM rbac_roles WHERE id = ?", (role_id,)).fetchone()
        if not old:
            raise HTTPException(status_code=404, detail="Preset not found.")
        in_use = conn.execute("SELECT COUNT(DISTINCT user_id) FROM rbac_user_access WHERE role_id = ?", (role_id,)).fetchone()[0]
        if in_use:
            raise HTTPException(status_code=409, detail=f"{in_use} people use this preset; move them to another one first.")
        conn.execute("DELETE FROM rbac_roles WHERE id = ?", (role_id,))
        conn.commit()
    finally:
        conn.close()
    log_event("rbac.role_deleted", category="security", actor=actor.get("email"), role=old["name"],
              message=f"Preset '{old['name']}' deleted")
    return {"status": "success"}


# --- People ----------------------------------------------------------------------------------------------------
@router.get("/users")
def list_users(request: Request):
    """Everyone for a super admin. Others see people of the charities where they hold users.view (plus people
    with no access yet, so they can be set up), and only those charities' rows - never another charity's staff."""
    actor = _actor(request)
    visible = None if _is_super(actor) else rbac.companies_with(actor, "users.view")
    conn = _db()
    try:
        rows = conn.execute("SELECT id, username, email, role, COALESCE(is_active, 1) AS is_active, display_name "
                            "FROM users ORDER BY role = 'super_admin' DESC, LOWER(COALESCE(display_name, username))").fetchall()
        out = []
        for r in rows:
            u = _user_payload(conn, r)
            if visible is not None:
                every = set(rbac._all_company_ids()) <= visible
                keep = lambda c: c in visible or (c == "*" and every)  # noqa: E731
                theirs = {a["company_id"] for a in u["access"]}
                # someone on '*' works in the actor's charities too; someone with no access yet is shown for set-up
                if r["role"] != "super_admin" and theirs and not any(c == "*" or c in visible for c in theirs):
                    continue
                for k in ("access", "overrides", "scopes"):
                    u[k] = [x for x in u[k] if keep(x["company_id"])]
                u["effective"] = {c: n for c, n in u["effective"].items() if c in visible}
            out.append(u)
        return {"users": out}
    finally:
        conn.close()


@router.get("/users/{user_id}/effective")
def user_effective(user_id: int):
    conn = _db()
    try:
        row = _target(conn, user_id)
    finally:
        conn.close()
    return rbac.effective_access(user_id, row["role"] == "super_admin")


class NewUser(BaseModel):
    email: str
    username: Optional[str] = None
    display_name: Optional[str] = ""
    password: str


@router.post("/users")
def create_user(body: NewUser, request: Request):
    actor = _actor(request)
    if _managed_companies(actor) == set():
        raise HTTPException(status_code=403, detail="You don't manage users for any charity.")
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(body.password or "") < 10:
        raise HTTPException(status_code=400, detail="The password must be at least 10 characters.")
    username = (body.username or email.split("@")[0]).strip()
    conn = _db()
    try:
        try:
            uid = conn.execute("INSERT INTO users (username, email, password_hash, role, allowed_companies, display_name) "
                               "VALUES (?, ?, ?, 'admin', '[]', ?)",
                               (username, email, hash_password(body.password), (body.display_name or "").strip())).lastrowid
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="That email or username is already in use.")
        conn.commit()  # no access yet: give them a preset per charity next
    finally:
        conn.close()
    log_event("rbac.user_created", category="security", actor=actor.get("email"), target=email,
              message=f"User {email} created (no access until a preset is assigned)")
    return {"status": "success", "id": uid}


class UserUpdate(BaseModel):
    email: Optional[str] = None
    username: Optional[str] = None
    display_name: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, request: Request):
    actor = _actor(request)
    conn = _db()
    try:
        target = _target(conn, user_id)
        _guard_target(actor, target, allow_self=body.is_active is None)
        changes, sets, args = [], [], []
        for field in ("email", "username", "display_name"):
            val = getattr(body, field)
            if val is not None and val.strip() != (target[field] or ""):
                sets.append(f"{field} = ?"); args.append(val.strip().lower() if field == "email" else val.strip())
                changes.append(field)
        logout = False
        if body.is_active is not None and bool(body.is_active) != bool(target["is_active"]):
            if not body.is_active and target["role"] == "super_admin" and _active_supers(conn) == [target["id"]]:
                raise HTTPException(status_code=409, detail="This is the last active super admin.")
            if target["id"] == actor.get("id"):
                raise HTTPException(status_code=403, detail="You can't disable your own account.")
            sets.append("is_active = ?"); args.append(1 if body.is_active else 0)
            changes.append("enabled" if body.is_active else "disabled")
            logout = not body.is_active
        if body.password:
            if len(body.password) < 10:
                raise HTTPException(status_code=400, detail="The password must be at least 10 characters.")
            sets.append("password_hash = ?"); args.append(hash_password(body.password))
            changes.append("password reset"); logout = True
        if not sets:
            return {"status": "success", "message": "Nothing changed."}
        try:
            conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", (*args, user_id))
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="That email or username is already in use.")
        rbac.bump_user(conn, user_id, logout=logout)
        conn.commit()
    finally:
        conn.close()
    log_event("rbac.user_updated", category="security", actor=actor.get("email"), target=target["email"], changes=changes,
              message=f"User {target['email']}: {', '.join(changes)}")
    return {"status": "success"}


class AccessEntry(BaseModel):
    company_id: str
    role_id: Optional[int] = None


class OverrideEntry(BaseModel):
    company_id: str
    permission: str
    effect: str


class ScopeEntry(BaseModel):
    company_id: str
    resource: str
    record_id: str


class AccessUpdate(BaseModel):
    access: List[AccessEntry] = []
    overrides: List[OverrideEntry] = []
    scopes: List[ScopeEntry] = []


SCOPE_RESOURCES = {"fundraiser"}


@router.put("/users/{user_id}/access")
def set_user_access(user_id: int, body: AccessUpdate, request: Request):
    """Replaces the person's access for the charities the actor manages (other charities are left as they are)."""
    actor = _actor(request)
    conn = _db()
    try:
        target = _target(conn, user_id)
        _guard_target(actor, target)
        if target["role"] == "super_admin":
            raise HTTPException(status_code=400, detail="Super admins already have every permission everywhere.")
        managed = _managed_companies(actor)
        known = set(rbac._all_company_ids()) | {"*"}
        touched = {e.company_id.strip().lower() for e in body.access} | {o.company_id.strip().lower() for o in body.overrides} \
            | {s.company_id.strip().lower() for s in body.scopes}
        for comp in touched:
            if comp not in known:
                raise HTTPException(status_code=400, detail=f"Unknown charity '{comp}'.")
            _check_can_manage(actor, comp)
        for o in body.overrides:
            if o.effect not in ("grant", "deny") or not rbac.is_permission(o.permission):
                raise HTTPException(status_code=400, detail=f"Bad override {o.permission}/{o.effect}.")
        for s in body.scopes:
            if s.resource not in SCOPE_RESOURCES:
                raise HTTPException(status_code=400, detail=f"Records of '{s.resource}' can't be scoped.")
        # what the change grants must be within what the actor holds there
        for e in body.access:
            comp = e.company_id.strip().lower()
            own = _actor_perms(actor, comp)
            grants = _role_perms(conn, e.role_id) | {o.permission for o in body.overrides
                                                     if o.effect == "grant" and o.company_id.strip().lower() in (comp, "*")}
            grants -= rbac.SUPER_ONLY_PERMISSIONS  # checked on their own below (a super admin's grant may stay)
            if own is not None and not grants <= own:
                raise HTTPException(status_code=403, detail=f"You can't give permissions you don't hold in '{comp}': "
                                                            + ", ".join(sorted(grants - own)))
        before = _user_payload(conn, target)
        replaced = None if managed is None else (
            managed | ({"*"} if set(rbac._all_company_ids()) <= managed else set()))  # rows this save rewrites
        old_super_only = {(o["company_id"], o["permission"], o["effect"]) for o in before["overrides"]
                          if o["permission"] in rbac.SUPER_ONLY_PERMISSIONS
                          and (replaced is None or o["company_id"] in replaced)}
        new_super_only = {(o.company_id.strip().lower(), o.permission, o.effect) for o in body.overrides
                          if o.permission in rbac.SUPER_ONLY_PERMISSIONS}
        if not _is_super(actor) and old_super_only != new_super_only:
            raise HTTPException(status_code=403, detail="Only a super admin can change activity-log access.")
        # replace rows only for charities the actor manages
        scope_sql, scope_args = ("", []) if managed is None else (
            f" AND company_id IN ({','.join('?' * len(managed | ({'*'} if set(rbac._all_company_ids()) <= managed else set())))})",
            sorted(managed | ({"*"} if set(rbac._all_company_ids()) <= managed else set())))
        for table in ("rbac_user_access", "rbac_user_overrides", "rbac_record_scopes"):
            conn.execute(f"DELETE FROM {table} WHERE user_id = ?{scope_sql}", (user_id, *scope_args))
        for e in body.access:
            conn.execute("INSERT OR REPLACE INTO rbac_user_access (user_id, company_id, role_id) VALUES (?, ?, ?)",
                         (user_id, e.company_id.strip().lower(), e.role_id))
        for o in body.overrides:
            conn.execute("INSERT OR REPLACE INTO rbac_user_overrides VALUES (?, ?, ?, ?)",
                         (user_id, o.company_id.strip().lower(), o.permission, o.effect))
        for s in body.scopes:
            conn.execute("INSERT OR IGNORE INTO rbac_record_scopes VALUES (?, ?, ?, ?)",
                         (user_id, s.company_id.strip().lower(), s.resource, str(s.record_id).strip()))
        rbac.bump_user(conn, user_id)
        conn.commit()
        after = _user_payload(conn, target)
    finally:
        conn.close()
    log_event("rbac.access_changed", category="security", actor=actor.get("email"), target=target["email"],
              before={k: before[k] for k in ("access", "overrides", "scopes")},
              after={k: after[k] for k in ("access", "overrides", "scopes")},
              message=f"Access changed for {target['email']}")
    return {"status": "success", "user": after}


class SuperBody(BaseModel):
    is_super_admin: bool


@router.post("/users/{user_id}/super-admin")
def set_super_admin(user_id: int, body: SuperBody, request: Request):
    actor = _actor(request)
    if not _is_super(actor):
        raise HTTPException(status_code=403, detail="Only a super admin can do this.")
    conn = _db()
    try:
        target = _target(conn, user_id)
        if not body.is_super_admin and target["role"] == "super_admin" and _active_supers(conn) == [target["id"]]:
            raise HTTPException(status_code=409, detail="This is the last active super admin.")
        conn.execute("UPDATE users SET role = ? WHERE id = ?", ("super_admin" if body.is_super_admin else "admin", user_id))
        rbac.bump_user(conn, user_id)
        conn.commit()
    finally:
        conn.close()
    log_event("rbac.super_admin_changed", category="security", level="warning", actor=actor.get("email"),
              target=target["email"], value=body.is_super_admin,
              message=f"{target['email']} {'made' if body.is_super_admin else 'no longer'} super admin")
    return {"status": "success"}


@router.post("/users/{user_id}/sign-out")
def sign_out_everywhere(user_id: int, request: Request):
    actor = _actor(request)
    conn = _db()
    try:
        target = _target(conn, user_id)
        _guard_target(actor, target, allow_self=True)
        rbac.bump_user(conn, user_id, logout=True)
        conn.commit()
    finally:
        conn.close()
    log_event("rbac.signed_out", category="security", actor=actor.get("email"), target=target["email"],
              message=f"All sessions of {target['email']} ended")
    return {"status": "success"}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request):
    actor = _actor(request)
    if not _is_super(actor):
        raise HTTPException(status_code=403, detail="Only a super admin can delete accounts (others can disable them).")
    conn = _db()
    try:
        target = _target(conn, user_id)
        if target["id"] == actor.get("id"):
            raise HTTPException(status_code=403, detail="You can't delete your own account.")
        if target["role"] == "super_admin" and _active_supers(conn) == [target["id"]]:
            raise HTTPException(status_code=409, detail="This is the last active super admin.")
        for table in ("rbac_user_access", "rbac_user_overrides", "rbac_record_scopes"):
            conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    log_event("rbac.user_deleted", category="security", level="warning", actor=actor.get("email"), target=target["email"],
              message=f"Account {target['email']} deleted")
    return {"status": "success"}


@router.get("/scope-options")
def scope_options(company_id: str = Query(...), resource: str = Query("fundraiser")):
    """Records that can be picked for a record scope (e.g. the charity's fundraisers)."""
    if resource not in SCOPE_RESOURCES:
        raise HTTPException(status_code=400, detail="Unknown resource.")
    conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=10)
    try:
        rows = conn.execute("SELECT id, name, status FROM fundraisers WHERE LOWER(company_id) = ? ORDER BY name",
                            (company_id.strip().lower(),)).fetchall()
    finally:
        conn.close()
    return {"options": [{"id": r[0], "label": r[1], "status": r[2]} for r in rows]}
