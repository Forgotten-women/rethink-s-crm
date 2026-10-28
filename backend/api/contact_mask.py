"""
Contact details (RBAC permission donors.contact), enforced on the server for every data API.

For a person WITHOUT donors.contact in the charity a request is about, the JSON response is rewritten before it
leaves the server:
  * every email address becomes an opaque id "dk_..." (the same address -> the same id, so links and donor pages
    keep working; for many donors the donor id IS their email),
  * phone numbers and street addresses / postcodes are blanked.
Requests are translated back: a "dk_..." id in the path, query string or JSON body is replaced by the address it
stands for (only ids this server issued, kept in rbac_masked_ids), so opening a donor still works.
File exports that contain contact details need donors.contact as well (backend/api/permissions.py CONTACT_EXPORTS).
Staff screens (sign-in, Users & Access, mailbox connections, ops) are never rewritten.
"""
import gzip
import hashlib
import hmac
import json
import re
import sqlite3
from typing import Any, Dict, Optional
from urllib.parse import quote, unquote

from config.settings import LOCAL_DB_PATH

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TOKEN_RE = re.compile(r"dk_[a-z2-7]{20}")
PHONE_KEY = re.compile(r"phone|mobile|\btel\b|telephone", re.I)
ADDRESS_KEY = re.compile(r"address|street|post_?code|\bzip\b|billing_zip|shipping_zip", re.I)
# keys whose value is the charity's own wording (templates), never donor data
SKIP_KEYS = {"subject_template", "body_template", "body_html_template"}

EXCLUDED_PREFIXES = ("/api/auth/", "/api/rbac/", "/api/ops/", "/api/mailbox/", "/api/admin/users", "/api/admin/companies",
                     "/api/tracker/outlook/status", "/api/stream/", "/api/webhooks/", "/api/email-unsubscribe/",
                     "/api/tracker/email-tracking/pixel/", "/api/tracker/outlook/webhook", "/api/expenses/action-email",
                     "/api/tracker/email-templates")

_secret: Optional[bytes] = None


def _key() -> bytes:
    global _secret
    if _secret is None:
        from core.auth import JWT_SECRET
        _secret = hashlib.sha256(b"contact-mask|" + JWT_SECRET.encode()).digest()
    return _secret


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("CREATE TABLE IF NOT EXISTS rbac_masked_ids (token TEXT PRIMARY KEY, value TEXT NOT NULL)")
    return conn


def token_for(value: str) -> str:
    import base64
    digest = hmac.new(_key(), value.strip().lower().encode(), hashlib.sha256).digest()
    return "dk_" + base64.b32encode(digest).decode().lower().rstrip("=")[:20]


class _Masker:
    def __init__(self):
        self.issued: Dict[str, str] = {}

    def email(self, m) -> str:
        value = m.group(0).strip().lower()
        tok = token_for(value)
        self.issued[tok] = value
        return tok

    def walk(self, obj: Any, key: str = "") -> Any:
        if isinstance(obj, dict):
            return {k: self.walk(v, str(k)) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.walk(v, key) for v in obj]
        if isinstance(obj, str):
            if key in SKIP_KEYS:
                return obj
            if key and (PHONE_KEY.search(key) or ADDRESS_KEY.search(key)) and obj.strip():
                return "•••"
            return EMAIL_RE.sub(self.email, obj) if "@" in obj else obj
        if key and (PHONE_KEY.search(key) or ADDRESS_KEY.search(key)) and isinstance(obj, (int, float)) and obj:
            return "•••"
        return obj

    def save(self) -> None:
        if not self.issued:
            return
        conn = _db()
        try:
            conn.executemany("INSERT OR IGNORE INTO rbac_masked_ids (token, value) VALUES (?, ?)", list(self.issued.items()))
            conn.commit()
        finally:
            conn.close()


def resolve_tokens(text: str, url_encoded: bool = False) -> str:
    """Replaces dk_ ids this server issued with the address they stand for."""
    found = set(TOKEN_RE.findall(text or ""))
    if not found:
        return text
    conn = _db()
    try:
        rows = dict(conn.execute(f"SELECT token, value FROM rbac_masked_ids WHERE token IN ({','.join('?' * len(found))})",
                                 tuple(found)).fetchall())
    finally:
        conn.close()
    return TOKEN_RE.sub(lambda m: (quote(rows[m.group(0)], safe="") if url_encoded else rows[m.group(0)])
                        if m.group(0) in rows else m.group(0), text)


def _must_mask(user: Optional[Dict[str, Any]], company: Optional[str]) -> bool:
    if not user or user.get("role") == "super_admin":
        return False
    from core.rbac import user_has
    comp = (company or "").strip().lower()
    if comp and comp != "all":
        return not user_has(user, "donors.contact", comp)
    companies = (user.get("access") or {}).get("companies") or {}
    return not companies or not all("donors.contact" in p for p in companies.values())


class ContactMaskMiddleware:
    """Pure ASGI: rewrites dk_ ids in the request, and masks contact details in JSON responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/") or path.startswith(EXCLUDED_PREFIXES):
            return await self.app(scope, receive, send)

        # --- request: dk_ ids back to addresses (path, query, JSON body) ---
        if "dk_" in path:
            new_path = resolve_tokens(path)
            scope = dict(scope, path=new_path, raw_path=quote(new_path).encode())
        qs = scope.get("query_string", b"").decode("latin-1")
        if "dk_" in qs:
            scope = dict(scope, query_string=resolve_tokens(qs, url_encoded=True).encode("latin-1"))
        if scope.get("method") in ("POST", "PUT", "PATCH", "DELETE"):
            body_parts = []
            more = True
            while more:
                message = await receive()
                if message["type"] != "http.request":
                    break
                body_parts.append(message.get("body", b""))
                more = message.get("more_body", False)
            body = b"".join(body_parts)
            if b"dk_" in body and b"json" in dict(scope.get("headers") or []).get(b"content-type", b""):
                body = resolve_tokens(body.decode("utf-8")).encode("utf-8")
            sent = False

            async def receive():  # noqa: F811 - replays the (translated) body to the app
                nonlocal sent
                if sent:
                    return {"type": "http.disconnect"}
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}

        # --- response: mask JSON for people without donors.contact ---
        start: Dict[str, Any] = {}
        chunks = []
        buffering = False

        async def send_wrapper(message):
            nonlocal buffering
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers") or [])
                ctype = headers.get(b"content-type", b"")
                if b"application/json" in ctype:
                    buffering = True
                    start.update(message)
                    return
                return await send(message)
            if message["type"] == "http.response.body" and buffering:
                chunks.append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                await self._finish(scope, start, b"".join(chunks), send)
                return
            return await send(message)

        await self.app(scope, receive, send_wrapper)

    async def _finish(self, scope, start, body: bytes, send):
        import asyncio
        state = scope.get("state") or {}
        user = state.get("api_user") or state.get("tracker_user")
        qs = dict(p.split("=", 1) if "=" in p else (p, "") for p in scope.get("query_string", b"").decode("latin-1").split("&") if p)
        company = unquote(qs.get("company_id", "")) or None
        headers = [(k, v) for k, v in (start.get("headers") or [])]
        if _must_mask(user, company) and body:
            raw = body
            encoded = dict(headers).get(b"content-encoding", b"") == b"gzip"
            try:
                text = gzip.decompress(raw) if encoded else raw
                data = json.loads(text)
                masker = _Masker()
                masked = await asyncio.to_thread(masker.walk, data)
                await asyncio.to_thread(masker.save)
                body = json.dumps(masked, default=str).encode("utf-8")
                # new body: no stale length / encoding / ETag (the cached ETag is for the unmasked payload)
                headers = [(k, v) for k, v in headers if k not in (b"content-length", b"content-encoding", b"etag")]
                headers.append((b"content-length", str(len(body)).encode()))
            except Exception:
                body = b'{"detail": "This response could not be prepared without contact details."}'
                headers = [(k, v) for k, v in headers if k not in (b"content-length", b"content-encoding", b"etag")]
                headers.append((b"content-length", str(len(body)).encode()))
                start = dict(start, status=500)
        await send(dict(start, headers=headers))
        await send({"type": "http.response.body", "body": body, "more_body": False})
