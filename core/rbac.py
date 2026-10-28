"""
Role-based access control (RBAC). Everything here is decided on the server from the database - nothing the
browser sends (role, permission flags, charity) is ever trusted.

Model
  * Permission catalogue (CATALOGUE below): resource x action, e.g. "donors.edit". Each action is either part of
    the resource's Read level, its Write level, or a separate "extra" switch for risky actions (approve, send,
    delete, export, contact details) - like Stripe's restricted-key editor.
  * Presets (rbac_roles): named permission sets - Finance, Fundraiser, Donor Care, Management, Read-only, ...
    The super admin (or anyone with users.presets) can add, copy and edit them.
  * Access per charity (rbac_user_access): a user gets a preset PER CHARITY ("Finance in Rethink, Read-only in
    Iqra"); company_id '*' = every charity, including ones added later. No row = no access to that charity.
  * Overrides (rbac_user_overrides): grant or deny single permissions for one person, for one charity or '*'.
  * Record scopes (rbac_record_scopes): limit a person to specific records, e.g. only fundraiser X in Rethink.
  * Super admins (users.role = 'super_admin') have every permission everywhere and can't be edited by others.

Effective permissions for (user, charity) = preset permissions + grants - denies. They are recomputed from the
database on every request (cached per version stamp), so a change applies to the user's very next request.
"""
import json
import sqlite3
import threading
from typing import Any, Dict, Iterable, List, Optional, Set

from config.settings import LOCAL_DB_PATH

# ---------------------------------------------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------------------------------------------
READ, WRITE, EXTRA = "read", "write", "extra"
HIDDEN = 0  # rbac_user_access.role_id for "this charity is hidden from the person" (beats a '*' row)

CATALOGUE: List[Dict[str, Any]] = [
    {"key": "dashboard", "label": "Dashboard & analytics", "description": "Dashboard, Lifetime LTV, Kanban pipeline",
     "actions": [("view", "View dashboards and charts", READ)]},
    {"key": "explorer", "label": "Data Explorer (donations)", "description": "Every donation row across platforms",
     "actions": [("view", "View donations", READ), ("edit", "Edit a donation row", WRITE),
                 ("bulk_edit", "Bulk edit donations", WRITE), ("export", "Export donations", EXTRA)]},
    {"key": "donors", "label": "Donors", "description": "Donor directory, profiles, history and notes",
     "actions": [("view", "View donors, totals and history", READ),
                 ("contact", "See contact details (email, phone, address)", EXTRA),
                 ("edit", "Edit donor profiles and notes", WRITE),
                 ("create", "Add donors and manual donations", WRITE),
                 ("delete", "Delete manual donations and notes", EXTRA),
                 ("export", "Export donors", EXTRA)]},
    {"key": "fundraisers", "label": "Fundraisers", "description": "Fundraiser pages, links and Ramadan periods",
     "actions": [("view", "View fundraisers", READ), ("edit", "Create and edit fundraisers, links, assign donations", WRITE),
                 ("sync", "Sync discovered fundraisers", WRITE), ("delete", "Delete fundraisers", EXTRA)]},
    {"key": "payouts", "label": "Payout reconciliation", "description": "Platform payouts, ledgers, PaySuite",
     "actions": [("view", "View payouts and ledgers", READ), ("classify", "Classify payout lines", WRITE),
                 ("sync", "Run PaySuite sync", EXTRA), ("export", "Export payouts", EXTRA)]},
    {"key": "stripe", "label": "Stripe reconciliation", "description": "Stripe payouts, lines and approvals",
     "actions": [("view", "View Stripe payouts", READ), ("reconcile", "Reconcile, resync and classify lines", WRITE),
                 ("approve", "Approve payouts and send to Slack", EXTRA), ("export", "Download / export", EXTRA)]},
    {"key": "classifications", "label": "Classifications", "description": "Classification matrix and project codes",
     "actions": [("view", "View the matrix and codes", READ), ("edit", "Edit classification rules", WRITE),
                 ("import", "Import rules from a file", EXTRA), ("delete", "Delete rules / clear a platform", EXTRA),
                 ("master_codes", "Manage master project codes", EXTRA), ("export", "Export the matrix", EXTRA)]},
    {"key": "expenses", "label": "Expenses & transfers", "description": "Expense requests and fund transfers",
     "actions": [("view", "View expenses and balances", READ), ("submit", "Submit expense requests", WRITE),
                 ("approve", "Approve or reject expenses", EXTRA), ("transfers", "Transfer and void funds between codes", EXTRA),
                 ("delete", "Delete expense requests", EXTRA), ("export", "Export expenses and transfers", EXTRA)]},
    {"key": "tracker", "label": "Sponsorship Tracker", "description": "Beneficiaries, allocations, feedback, overdue",
     "actions": [("view", "View sponsorships", READ), ("edit", "Add and edit beneficiaries, allocations, feedback", WRITE),
                 ("import", "Import beneficiaries", EXTRA), ("delete", "Delete beneficiaries / allocations", EXTRA),
                 ("settings", "Targets and overdue settings", EXTRA)]},
    {"key": "email", "label": "Email", "description": "Templates, queue, campaigns, sending, unsubscribes",
     "actions": [("view", "View email history, threads and unsubscribes", READ),
                 ("templates", "Edit templates and the email queue", WRITE),
                 ("send", "Send emails to donors", EXTRA), ("campaigns", "Create and run segment campaigns", EXTRA),
                 ("resubscribe", "Resubscribe someone who unsubscribed", EXTRA)]},
    {"key": "mailbox", "label": "Mailbox connections", "description": "Outlook / Gmail sending accounts",
     "actions": [("view", "View connection status", READ), ("sync", "Sync replies", WRITE),
                 ("configure", "Connect, disconnect, test-send", EXTRA)]},
    {"key": "data", "label": "Data import & maintenance", "description": "File uploads, dataset tags, purge",
     "actions": [("view", "View dataset status and tags", READ), ("upload", "Upload donation / payout files", WRITE),
                 ("tags", "Rename and delete dataset tags", EXTRA), ("purge", "Purge data (destructive)", EXTRA)]},
    {"key": "charities", "label": "Charity settings", "description": "Charity names, colours, logos",
     "actions": [("edit", "Edit charity settings and logos", EXTRA)]},
    {"key": "logs", "label": "Activity log", "description": "Who did what (Ops console log view). Only a super admin can give this.",
     "actions": [("view", "See the activity log of their charities", EXTRA)]},
    {"key": "users", "label": "Users & access", "description": "People, presets and access levels",
     "actions": [("view", "View users and their access", READ),
                 ("manage", "Create users, assign presets and overrides", EXTRA),
                 ("presets", "Create and edit presets", EXTRA)]},
]

# Only a super admin may grant (or take away) these - in presets or for a person.
SUPER_ONLY_PERMISSIONS = {"logs.view"}

ALL_PERMISSIONS: List[str] = [f"{r['key']}.{a[0]}" for r in CATALOGUE for a in r["actions"]]
_PERMISSION_SET = set(ALL_PERMISSIONS)
ACTION_LEVEL: Dict[str, str] = {f"{r['key']}.{a[0]}": a[2] for r in CATALOGUE for a in r["actions"]}
ACTION_LABEL: Dict[str, str] = {f"{r['key']}.{a[0]}": a[1] for r in CATALOGUE for a in r["actions"]}


def is_permission(name: str) -> bool:
    return name in _PERMISSION_SET


def _level(*resources: str, level: str = READ) -> List[str]:
    """Every action of the resources up to the level (read ⊂ write); extras are never included."""
    want = {READ} if level == READ else {READ, WRITE}
    return [p for p in ALL_PERMISSIONS if p.split(".")[0] in resources and ACTION_LEVEL[p] in want]


_ALL_RESOURCES = [r["key"] for r in CATALOGUE if r["key"] not in ("users", "charities", "logs")]

# System presets (seeded once; editable afterwards - edits are kept).
SYSTEM_PRESETS: List[Dict[str, Any]] = [
    {"name": "Read-only", "description": "Sees every section, changes nothing, no contact details or exports.",
     "permissions": _level(*_ALL_RESOURCES)},
    {"name": "Finance", "description": "Payouts, Stripe, expenses, transfers and classifications.",
     "permissions": _level("dashboard", "donors", "fundraisers", "tracker", "email")
     + _level("explorer", "payouts", "stripe", "classifications", "expenses", level=WRITE)
     + ["explorer.export", "payouts.export", "payouts.sync", "stripe.approve", "stripe.export", "expenses.approve",
        "expenses.transfers", "expenses.export", "classifications.export", "data.view", "data.upload"]},
    {"name": "Fundraiser", "description": "Their fundraisers and the donors/donations behind them (combine with "
                                          "a fundraiser scope to limit to specific pages).",
     "permissions": _level("dashboard", "explorer", "donors", "tracker") + _level("fundraisers", level=WRITE)},
    {"name": "Donor Care", "description": "Donors, sponsorships and emailing donors.",
     "permissions": _level("dashboard", "explorer", "fundraisers", "payouts")
     + _level("donors", "tracker", "email", level=WRITE)
     + ["donors.contact", "email.send", "email.campaigns", "email.resubscribe", "mailbox.view", "mailbox.sync"]},
    {"name": "Management", "description": "Sees everything incl. contact details and exports; approves expenses "
                                          "and payouts; doesn't edit data.",
     "permissions": _level(*_ALL_RESOURCES)
     + ["donors.contact", "donors.export", "explorer.export", "payouts.export", "stripe.export", "stripe.approve",
        "expenses.approve", "expenses.export", "classifications.export", "users.view"]},
    # What a plain "admin" account could do before RBAC existed, so moving to RBAC changes nothing for them.
    {"name": "Standard (previous admin)", "description": "Same access as the old 'admin' account had before "
                                                         "access control; review and replace with a preset.",
     "permissions": _level(*_ALL_RESOURCES)
     + ["donors.contact", "explorer.export", "donors.export", "payouts.export", "stripe.export",
        "classifications.export", "expenses.export", "classifications.edit", "payouts.classify", "expenses.submit",
        "expenses.transfers", "tracker.edit", "tracker.import", "tracker.delete", "email.templates", "email.send",
        "email.campaigns", "email.resubscribe", "mailbox.sync", "data.upload", "fundraisers.sync"]},
]

# The old per-user flags, mapped to the permissions they used to unlock (used once, by the migration).
_LEGACY_FLAGS = {
    "can_edit_donors": ["donors.edit", "donors.create", "donors.delete", "explorer.edit", "explorer.bulk_edit",
                        "fundraisers.edit", "expenses.approve", "expenses.delete", "expenses.transfers"],
    "can_edit_matrix": ["classifications.edit"],
    "can_manage_tags": ["data.tags"],
    "can_purge_data": ["data.purge"],
}


# ---------------------------------------------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------------------------------------------
def _connect(readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=30)
    else:
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
    conn.row_factory = sqlite3.Row
    return conn


_init_lock = threading.Lock()
_initialized = False


def init_rbac() -> None:
    """Creates the RBAC tables, seeds the system presets and moves existing users onto RBAC (once)."""
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        conn = _connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS rbac_roles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT DEFAULT '',
                    permissions TEXT NOT NULL DEFAULT '[]',
                    is_system INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_by TEXT
                );
                CREATE TABLE IF NOT EXISTS rbac_user_access (
                    user_id INTEGER NOT NULL,
                    company_id TEXT NOT NULL,          -- a charity id, or '*' = every charity
                    role_id INTEGER,                   -- NULL = no preset (own grants only), 0 = hidden
                    PRIMARY KEY (user_id, company_id)
                );
                CREATE TABLE IF NOT EXISTS rbac_user_overrides (
                    user_id INTEGER NOT NULL,
                    company_id TEXT NOT NULL,          -- a charity id, or '*'
                    permission TEXT NOT NULL,
                    effect TEXT NOT NULL CHECK (effect IN ('grant', 'deny')),
                    PRIMARY KEY (user_id, company_id, permission)
                );
                CREATE TABLE IF NOT EXISTS rbac_record_scopes (
                    user_id INTEGER NOT NULL,
                    company_id TEXT NOT NULL,
                    resource TEXT NOT NULL,            -- e.g. 'fundraiser'
                    record_id TEXT NOT NULL,
                    PRIMARY KEY (user_id, company_id, resource, record_id)
                );
                CREATE TABLE IF NOT EXISTS rbac_meta (key TEXT PRIMARY KEY, value TEXT);
            """)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
            for col, ddl in (("is_active", "INTEGER DEFAULT 1"), ("perm_version", "INTEGER DEFAULT 0"),
                             ("token_version", "INTEGER DEFAULT 0"), ("display_name", "TEXT")):
                if col not in cols:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
            for p in SYSTEM_PRESETS:
                conn.execute("INSERT OR IGNORE INTO rbac_roles (name, description, permissions, is_system) VALUES (?, ?, ?, 1)",
                             (p["name"], p["description"], json.dumps(sorted(set(p["permissions"])))))
            _migrate_legacy_users(conn)
            conn.commit()
        finally:
            conn.close()
        _initialized = True


def _migrate_legacy_users(conn: sqlite3.Connection) -> None:
    """Users without any RBAC row get the access they had before: their allowed charities with the
    'Standard (previous admin)' preset, plus grants for the old can_* flags. Super admins need nothing."""
    role_id = conn.execute("SELECT id FROM rbac_roles WHERE name = 'Standard (previous admin)'").fetchone()[0]
    has_rows = {r[0] for r in conn.execute("SELECT DISTINCT user_id FROM rbac_user_access")}
    for u in conn.execute("SELECT * FROM users").fetchall():
        if u["role"] == "super_admin" or u["id"] in has_rows:
            continue
        try:
            comps = json.loads(u["allowed_companies"] or '["ALL"]')
        except Exception:
            comps = ["ALL"]
        comps = ["*"] if not comps or any(str(c).strip().upper() == "ALL" for c in comps) else \
            [str(c).strip().lower() for c in comps if str(c).strip()]
        for comp in comps:
            conn.execute("INSERT OR IGNORE INTO rbac_user_access (user_id, company_id, role_id) VALUES (?, ?, ?)",
                         (u["id"], comp, role_id))
        for flag, perms in _LEGACY_FLAGS.items():
            if u[flag]:
                for perm in perms:
                    conn.execute("INSERT OR IGNORE INTO rbac_user_overrides VALUES (?, '*', ?, 'grant')", (u["id"], perm))


# ---------------------------------------------------------------------------------------------------------------
# Effective access
# ---------------------------------------------------------------------------------------------------------------
_cache: Dict[Any, Dict[str, Any]] = {}
_cache_lock = threading.Lock()


def _roles_version(conn) -> int:
    row = conn.execute("SELECT value FROM rbac_meta WHERE key = 'roles_version'").fetchone()
    return int(row[0]) if row else 0


def _company_ids(conn) -> List[str]:
    try:
        return [str(r[0]).strip().lower() for r in conn.execute("SELECT id FROM companies WHERE COALESCE(is_active, 1) = 1")]
    except sqlite3.OperationalError:
        return ["rethink", "iqra"]


def access_stamp(user_id: int) -> str:
    """Changes whenever this user's effective access may have changed (their own edits, or an edit to any
    preset). Used to cache, and to tell an open browser to refresh its permissions."""
    init_rbac()
    conn = _connect(readonly=True)
    try:
        row = conn.execute("SELECT perm_version, token_version, COALESCE(is_active, 1) FROM users WHERE id = ?",
                           (user_id,)).fetchone()
        if not row:
            return "gone"
        return f"{row[0] or 0}.{_roles_version(conn)}.{row[1] or 0}.{row[2]}"
    finally:
        conn.close()


def effective_access(user_id: int, is_super_admin: bool) -> Dict[str, Any]:
    """{'super_admin': bool, 'companies': {charity: sorted permissions}, 'scopes': {charity: {resource: [ids]}}}.
    Only charities with at least one permission are listed: a charity that isn't listed is not accessible."""
    init_rbac()
    conn = _connect(readonly=True)
    try:
        companies = _company_ids(conn)
        if is_super_admin:
            return {"super_admin": True, "companies": {c: list(ALL_PERMISSIONS) for c in companies}, "scopes": {}}
        stamp_row = conn.execute("SELECT perm_version FROM users WHERE id = ?", (user_id,)).fetchone()
        key = (user_id, stamp_row[0] if stamp_row else None, _roles_version(conn), tuple(companies))
        with _cache_lock:
            hit = _cache.get(key)
        if hit is not None:
            return hit
        roles = {r["id"]: set(json.loads(r["permissions"] or "[]")) for r in conn.execute("SELECT id, permissions FROM rbac_roles")}
        access = {r["company_id"]: r["role_id"] for r in conn.execute(
            "SELECT company_id, role_id FROM rbac_user_access WHERE user_id = ?", (user_id,))}
        overrides = conn.execute("SELECT company_id, permission, effect FROM rbac_user_overrides WHERE user_id = ?",
                                 (user_id,)).fetchall()
        scopes_rows = conn.execute("SELECT company_id, resource, record_id FROM rbac_record_scopes WHERE user_id = ?",
                                   (user_id,)).fetchall()
    finally:
        conn.close()

    result: Dict[str, List[str]] = {}
    for comp in companies:
        if comp in access:
            role_id = access[comp]
            if role_id == HIDDEN:
                continue  # hidden: no access at all, even when '*' gives every charity
        elif "*" in access:
            role_id = access["*"]
        else:
            continue  # no access to this charity at all
        perms = set(roles.get(role_id, set())) if role_id else set()
        for scope in ("*", comp):  # applied in this order, so a charity-specific override beats a '*' one
            for o in overrides:
                if o["company_id"] == scope:
                    (perms.add if o["effect"] == "grant" else perms.discard)(o["permission"])
        perms &= _PERMISSION_SET
        if perms:
            result[comp] = sorted(perms)
    scopes: Dict[str, Dict[str, List[str]]] = {}
    for s in scopes_rows:
        scopes.setdefault(s["company_id"], {}).setdefault(s["resource"], []).append(s["record_id"])
    out = {"super_admin": False, "companies": result, "scopes": scopes}
    with _cache_lock:
        if len(_cache) > 500:
            _cache.clear()
        _cache[key] = out
    return out


def user_has(user: Dict[str, Any], permission: str, company_id: Optional[str]) -> bool:
    """Does the user hold the permission for this charity? company 'all' / None = for EVERY charity."""
    if user.get("role") == "super_admin":
        return True
    acc = user.get("access") or {}
    companies = acc.get("companies") or {}
    comp = (company_id or "").strip().lower()
    if comp in ("", "all"):
        known = set(_all_company_ids())
        return bool(known) and known <= set(companies) and all(permission in companies[c] for c in known)
    return permission in companies.get(comp, [])


def companies_with(user: Dict[str, Any], permission: str) -> Optional[Set[str]]:
    """Charities where the user holds the permission; None = all (super admin)."""
    if user.get("role") == "super_admin":
        return None
    return {c for c, perms in ((user.get("access") or {}).get("companies") or {}).items() if permission in perms}


def record_scope(user: Dict[str, Any], company_id: str, resource: str) -> Optional[Set[str]]:
    """The records of `resource` the user is limited to in this charity, or None = not limited."""
    if user.get("role") == "super_admin":
        return None
    ids = (((user.get("access") or {}).get("scopes") or {}).get((company_id or "").lower()) or {}).get(resource)
    return set(ids) if ids else None


def _all_company_ids() -> List[str]:
    conn = _connect(readonly=True)
    try:
        return _company_ids(conn)
    finally:
        conn.close()


def bump_user(conn: sqlite3.Connection, user_id: int, logout: bool = False) -> None:
    """Mark a user's access as changed (the open browser refreshes; logout=True also ends their sessions)."""
    conn.execute("UPDATE users SET perm_version = COALESCE(perm_version, 0) + 1"
                 + (", token_version = COALESCE(token_version, 0) + 1" if logout else "") + " WHERE id = ?", (user_id,))


def bump_roles(conn: sqlite3.Connection) -> None:
    """A preset changed: everyone on it gets the new permissions (and the change pushed to their browser)."""
    conn.execute("INSERT INTO rbac_meta (key, value) VALUES ('roles_version', '1') "
                 "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1")


def catalogue_for_ui() -> List[Dict[str, Any]]:
    return [{"key": r["key"], "label": r["label"], "description": r["description"],
             "actions": [{"permission": f"{r['key']}.{a[0]}", "action": a[0], "label": a[1], "level": a[2]}
                         for a in r["actions"]]} for r in CATALOGUE]


def validate_permissions(perms: Iterable[str]) -> List[str]:
    bad = [p for p in perms if p not in _PERMISSION_SET]
    if bad:
        raise ValueError(f"Unknown permission(s): {', '.join(bad)}")
    return sorted(set(perms))


# ---------------------------------------------------------------------------------------------------------------
# Record scopes applied to data (e.g. a person limited to specific fundraisers sees only those fundraisers and the
# donations / donors behind them). Read from the request being served (set by the router guards), so background
# jobs and other people are never affected.
# ---------------------------------------------------------------------------------------------------------------
def request_user() -> Optional[Dict[str, Any]]:
    from core.cache import current_request
    req = current_request.get()
    if req is None:
        return None
    return getattr(req.state, "api_user", None) or getattr(req.state, "tracker_user", None)


def request_scope(company_id: Optional[str], resource: str = "fundraiser") -> Optional[Set[str]]:
    """The record ids the current request's user is limited to in this charity, or None (not limited)."""
    user = request_user()
    if not user or not company_id:
        return None
    return record_scope(user, str(company_id).strip().lower(), resource)


def scope_signature() -> str:
    """Part of a cache key: '' for people without record scopes, otherwise their scopes (results differ)."""
    user = request_user()
    if not user or user.get("role") == "super_admin":
        return ""
    scopes = (user.get("access") or {}).get("scopes") or {}
    return json.dumps(scopes, sort_keys=True) if scopes else ""


def scoped_fundraiser_names(company_id: str, ids: Iterable[str]) -> Set[str]:
    conn = _connect(readonly=True)
    try:
        ids = list(ids)
        rows = conn.execute(f"SELECT LOWER(TRIM(name)) FROM fundraisers WHERE LOWER(company_id) = ? AND id IN ({','.join('?' * len(ids))})",
                            (company_id.lower(), *ids)).fetchall() if ids else []
    finally:
        conn.close()
    return {r[0] for r in rows if r[0]}


def scope_donations(df, company_id: Optional[str], scope: Optional[Set[str]] = None):
    """Only the donations attributed (same attribution as the Fundraisers page) to the fundraisers the current
    user is limited to. Unchanged when the user isn't limited."""
    comp = (company_id or "").strip().lower()
    scope = scope if scope is not None else request_scope(comp)
    if scope is None or df is None or getattr(df, "empty", True):
        return df
    from backend.api.fundraisers import attribute_donations
    names = scoped_fundraiser_names(comp, scope)
    if "company_id" in df.columns:
        df = df[df["company_id"].astype(str).str.strip().str.lower() == comp]
    fn, _, _ = attribute_donations(df, comp)
    return df[fn.isin(names)]
