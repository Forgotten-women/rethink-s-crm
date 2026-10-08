"""
Shared, version-keyed response cache.

Invalidation never deletes entries. Every cache key embeds the current *version* of each data scope
the endpoint depends on, so the moment the data changes the key changes and the old entry is simply
never asked for again (it ages out via TTL/LRU).

Where versions come from (no writer has to remember anything):
  * SQLite triggers on the source tables bump a counter in `data_versions` inside the *same transaction*
    as the write - from any process (API workers, platform-sync, scripts). Per company where the table
    has a company_id column.
  * File-backed data (the donations / payouts parquet files) uses the file's mtime as its version.
  * A trigger self-check runs on every lookup: if a table was dropped/recreated (e.g. pandas
    `to_sql(if_exists="replace")`), its triggers are reinstalled and a global epoch is bumped, so
    nothing stale can be served.

Storage: gzip-compressed JSON in data_cache/cache.db (separate SQLite file, WAL) shared by every worker,
plus a small in-process LRU. Concurrent identical requests compute once (file lock per key).
"""
import contextvars
import fcntl
import functools
import gzip
import hashlib
import json
import os
import sqlite3
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from config.settings import BASE_DIR, LOCAL_DB_PATH, PARQUET_PATH, PAYOUTS_PARQUET_PATH, PAYSUITE_PAYOUTS_PARQUET_PATH

CACHE_DB_PATH = os.path.join(BASE_DIR, "data_cache", "cache.db")
LOCK_DIR = os.path.join(BASE_DIR, "data_cache", "cache_locks")
MAX_DB_BYTES = int(os.environ.get("CACHE_MAX_MB", "300")) * 1024 * 1024
MAX_MEM_BYTES = 96 * 1024 * 1024

# scope -> tables whose writes change it (trigger-maintained, per company when possible)
SCOPE_TABLES: Dict[str, List[str]] = {
    "classification": ["master_project_codes", "platform_campaign_mappings", "code_transfers"],
    "fundraisers": ["fundraisers", "fundraiser_campaigns"],
    "tracker": ["sponsorship_beneficiaries", "sponsorship_allocations", "sponsorship_allocation_donors",
                "sponsorship_manual_donors", "sponsorship_targets", "sponsorship_alert_dismissals",
                "sponsorship_alert_settings"],
    "tracker_comms": ["sponsorship_communications", "sponsorship_email_queue", "sponsorship_email_templates",
                      "sponsorship_feedbacks"],
    "payouts": ["payout_settlements", "paysuite_payout_settlements"],
    "expenses": ["expense_requests"],
    "donations": ["donations"],
}
# scopes whose version also includes a file mtime
SCOPE_FILES: Dict[str, List[str]] = {
    "donations": [PARQUET_PATH],
    "payouts": [PAYOUTS_PARQUET_PATH, PAYSUITE_PAYOUTS_PARQUET_PATH],
}
# huge tables: one global counter instead of per-company (cheaper per-row trigger)
GLOBAL_ONLY_TABLES = {"donations", "payout_settlements", "paysuite_payout_settlements"}

current_request: contextvars.ContextVar = contextvars.ContextVar("current_request", default=None)

_mem: "OrderedDict[str, bytes]" = OrderedDict()
_mem_bytes = 0
_mem_lock = threading.Lock()
_stats: Dict[str, Dict[str, float]] = {}
_stats_lock = threading.Lock()
_triggers_checked_at = 0.0


def enabled() -> bool:
    return os.environ.get("CACHE_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


# --------------------------------------------------------------------------------------------------
# Version registry (lives in the MAIN database so triggers can write it transactionally)
# --------------------------------------------------------------------------------------------------

def _main_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _table_columns(conn, table) -> List[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info('{table}')")]


def _trigger_specs(conn) -> List[Tuple[str, str]]:
    """(trigger_name, create_sql) for every table that exists."""
    specs = []
    existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for scope, tables in SCOPE_TABLES.items():
        for table in tables:
            if table not in existing:
                continue
            per_company = table not in GLOBAL_ONLY_TABLES and "company_id" in _table_columns(conn, table)

            def bump(row_ref: Optional[str]) -> str:
                key = (f"'{scope}:' || LOWER(TRIM(COALESCE({row_ref}.company_id, 'rethink')))" if row_ref
                       else f"'{scope}:*'")
                return (f"INSERT INTO data_versions(scope, version, updated_at) VALUES ({key}, 1, CURRENT_TIMESTAMP) "
                        f"ON CONFLICT(scope) DO UPDATE SET version = version + 1, updated_at = CURRENT_TIMESTAMP;")
            for op, refs in (("INSERT", ["NEW"]), ("UPDATE", ["NEW", "OLD"]), ("DELETE", ["OLD"])):
                body = " ".join(bump(r if per_company else None) for r in (refs if per_company else refs[:1]))
                name = f"cachever_{table}_{op.lower()}"
                specs.append((name, f"CREATE TRIGGER IF NOT EXISTS {name} AFTER {op} ON {table} BEGIN {body} END"))
    return specs


def install_version_triggers(bump_epoch: bool = False) -> int:
    """Idempotent. Returns how many triggers were (re)created."""
    conn = _main_conn()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS data_versions (
                            scope TEXT PRIMARY KEY, version INTEGER NOT NULL DEFAULT 0, updated_at TIMESTAMP)""")
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'cachever_%'")}
        created = 0
        for name, sql in _trigger_specs(conn):
            if name not in have:
                conn.execute(sql)
                created += 1
        if created or bump_epoch:
            conn.execute("INSERT INTO data_versions(scope, version, updated_at) VALUES ('epoch', 1, CURRENT_TIMESTAMP) "
                         "ON CONFLICT(scope) DO UPDATE SET version = version + 1, updated_at = CURRENT_TIMESTAMP")
        conn.commit()
        return created
    finally:
        conn.close()


def _ensure_triggers(conn) -> None:
    """Cheap self-check (every 5 s per process): a dropped/recreated table loses its triggers."""
    global _triggers_checked_at
    now = time.time()
    if now - _triggers_checked_at < 5:
        return
    expected = {name for name, _ in _trigger_specs(conn)}
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'cachever_%'")}
    if not expected.issubset(have):
        install_version_triggers(bump_epoch=True)
    _triggers_checked_at = now


def bump(scope: str, company_id: Optional[str] = None) -> None:
    """Manual bump (e.g. ops 'clear cache'). Normal writes are covered by triggers."""
    key = f"{scope}:{(company_id or '*').strip().lower()}"
    conn = _main_conn()
    try:
        conn.execute("INSERT INTO data_versions(scope, version, updated_at) VALUES (?, 1, CURRENT_TIMESTAMP) "
                     "ON CONFLICT(scope) DO UPDATE SET version = version + 1, updated_at = CURRENT_TIMESTAMP", (key,))
        conn.commit()
    finally:
        conn.close()


def versions(scopes: Iterable[str], company_id: Optional[str]) -> Dict[str, Any]:
    """Current version vector for the given scopes and company (plus the global epoch)."""
    comp = (company_id or "rethink").strip().lower()
    scopes = list(dict.fromkeys(scopes))
    out: Dict[str, Any] = {}
    conn = _main_conn()
    try:
        _ensure_triggers(conn)
        rows = dict(conn.execute("SELECT scope, version FROM data_versions").fetchall())
    except sqlite3.OperationalError:
        rows = {}
    finally:
        conn.close()
    out["epoch"] = rows.get("epoch", 0)
    for s in scopes:
        if comp == "all":
            v = sum(val for k, val in rows.items() if k.startswith(f"{s}:"))
        else:
            v = rows.get(f"{s}:{comp}", 0) + rows.get(f"{s}:*", 0)
        files = []
        for path in SCOPE_FILES.get(s, []):
            try:
                files.append(os.stat(path).st_mtime_ns)
            except OSError:
                files.append(0)
        out[s] = [v, files] if files else v
    return out


# --------------------------------------------------------------------------------------------------
# Response storage
# --------------------------------------------------------------------------------------------------

def _cache_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(CACHE_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(CACHE_DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS response_cache (
                        key TEXT PRIMARY KEY, endpoint TEXT, created_at REAL, expires_at REAL,
                        last_hit REAL, hits INTEGER DEFAULT 0, size INTEGER, compute_ms INTEGER, blob BLOB)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_response_cache_lru ON response_cache(last_hit)")
    return conn


def _mem_get(key: str) -> Optional[bytes]:
    with _mem_lock:
        val = _mem.get(key)
        if val is not None:
            _mem.move_to_end(key)
        return val


def _mem_put(key: str, payload: bytes) -> None:
    global _mem_bytes
    if len(payload) > MAX_MEM_BYTES // 4:
        return
    with _mem_lock:
        if key in _mem:
            return
        _mem[key] = payload
        _mem_bytes += len(payload)
        while _mem_bytes > MAX_MEM_BYTES and _mem:
            _, old = _mem.popitem(last=False)
            _mem_bytes -= len(old)


def _db_get(key: str) -> Optional[bytes]:
    conn = _cache_conn()
    try:
        row = conn.execute("SELECT blob, expires_at FROM response_cache WHERE key = ?", (key,)).fetchone()
        if not row or row[1] < time.time():
            return None
        conn.execute("UPDATE response_cache SET last_hit = ?, hits = hits + 1 WHERE key = ?", (time.time(), key))
        conn.commit()
        return row[0]  # stays gzip-compressed: sent to the browser as-is
    finally:
        conn.close()


def _db_put(key: str, endpoint: str, blob: bytes, ttl: int, compute_ms: int) -> None:
    """blob is gzip-compressed JSON."""
    now = time.time()
    conn = _cache_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO response_cache (key, endpoint, created_at, expires_at, last_hit, hits, size, compute_ms, blob) "
                     "VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)", (key, endpoint, now, now + ttl, now, len(blob), compute_ms, blob))
        conn.execute("DELETE FROM response_cache WHERE expires_at < ?", (now,))
        total = conn.execute("SELECT COALESCE(SUM(size), 0) FROM response_cache").fetchone()[0]
        if total > MAX_DB_BYTES:  # LRU eviction down to 80% of the cap
            target = int(MAX_DB_BYTES * 0.8)
            for k, size in conn.execute("SELECT key, size FROM response_cache ORDER BY last_hit ASC").fetchall():
                if total <= target:
                    break
                conn.execute("DELETE FROM response_cache WHERE key = ?", (k,))
                total -= size
        conn.commit()
    finally:
        conn.close()


def _record(endpoint: str, field: str, value: float = 1) -> None:
    with _stats_lock:
        s = _stats.setdefault(endpoint, {"hits": 0, "misses": 0, "bypass": 0, "compute_ms": 0, "saved_ms": 0})
        s[field] = s.get(field, 0) + value


def stats() -> Dict[str, Any]:
    conn = _cache_conn()
    try:
        rows = conn.execute("SELECT endpoint, COUNT(*), COALESCE(SUM(size),0), COALESCE(SUM(hits),0), "
                            "COALESCE(AVG(compute_ms),0) FROM response_cache WHERE expires_at >= ? GROUP BY endpoint",
                            (time.time(),)).fetchall()
        total = conn.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM response_cache").fetchone()
    finally:
        conn.close()
    with _stats_lock:
        proc = {k: dict(v) for k, v in _stats.items()}
    return {
        "enabled": enabled(), "entries": total[0], "bytes": total[1], "max_bytes": MAX_DB_BYTES,
        "endpoints": [{"endpoint": r[0], "entries": r[1], "bytes": r[2], "hits": r[3], "avg_compute_ms": round(r[4])} for r in rows],
        "this_worker": proc, "memory_bytes": _mem_bytes, "pid": os.getpid(),
    }


def clear_all() -> None:
    """Invalidate everything by bumping the epoch (entries age out) and drop stored blobs."""
    install_version_triggers(bump_epoch=True)
    with _mem_lock:
        _mem.clear()
    conn = _cache_conn()
    try:
        conn.execute("DELETE FROM response_cache")
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------------------------------
# Decorator
# --------------------------------------------------------------------------------------------------

_SIMPLE = (str, int, float, bool, type(None))


def _request_wants_bypass() -> bool:
    req = current_request.get()
    if req is None or req.query_params.get("nocache") not in ("1", "true"):
        return False
    try:  # only super admins may bypass
        from core.auth import decode_access_token
        hdr = req.headers.get("authorization", "")
        claims = decode_access_token(hdr[7:].strip()) if hdr.lower().startswith("bearer ") else None
        return bool(claims and claims.get("role") == "super_admin")
    except Exception:
        return False


def cached(scopes: List[str], ttl: int = 3600, company_param: str = "company_id", daily: bool = False):
    """Cache a sync FastAPI GET handler's JSON result, keyed by its arguments + data versions.

    The handler must return JSON-serialisable data (dict/list). Responses that are already Response
    objects (files, streams) pass through uncached. `daily=True` adds today's date to the key for
    results that change at midnight (days remaining, waiting days).
    Called as the route itself it returns the raw JSON (with ETag/304); called internally by other
    Python code it returns the normal Python object, so internal callers keep working. Auth/guards run before the handler (and therefore
    before any lookup) because they are route dependencies, so access control is never skipped.
    """
    def deco(fn: Callable):
        endpoint = f"{fn.__module__.split('.')[-1]}.{fn.__name__}"

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            from fastapi.encoders import jsonable_encoder
            from fastapi.responses import Response
            if not enabled() or _request_wants_bypass():
                _record(endpoint, "bypass")
                return fn(*args, **kwargs)
            params = {k: v for k, v in sorted(kwargs.items()) if isinstance(v, _SIMPLE) or (
                isinstance(v, (list, tuple)) and all(isinstance(i, _SIMPLE) for i in v))}
            company = str(kwargs.get(company_param) or "rethink")
            ver = versions(scopes, company)
            if daily:
                ver["day"] = time.strftime("%Y-%m-%d", time.gmtime())
            raw_key = json.dumps({"e": endpoint, "p": params, "v": ver, "fmt": "gz1"}, sort_keys=True, default=str)
            key = hashlib.sha256(raw_key.encode()).hexdigest()
            etag = f'W/"{key[:32]}"'

            req = current_request.get()
            as_route = req is not None and req.scope.get("endpoint") in (wrapper, fn)
            if not as_route:
                req = None
            if req is not None and req.headers.get("if-none-match") == etag:
                _record(endpoint, "hits")
                return Response(status_code=304, headers={"ETag": etag, "X-Cache": "HIT-304"})

            def respond(gz: bytes, state: str):
                """gz = gzip-compressed JSON. Browsers that accept gzip get it untouched (no re-compression);
                internal Python callers get the decoded object."""
                if not as_route:
                    return json.loads(gzip.decompress(gz))
                headers = {"ETag": etag, "X-Cache": state, "Cache-Control": "private, no-cache", "Vary": "Accept-Encoding"}
                if "gzip" in req.headers.get("accept-encoding", "").lower():
                    headers["Content-Encoding"] = "gzip"
                    return Response(content=gz, media_type="application/json", headers=headers)
                return Response(content=gzip.decompress(gz), media_type="application/json", headers=headers)

            payload = _mem_get(key)
            if payload is not None:
                _record(endpoint, "hits")
                return respond(payload, "HIT-MEM")
            payload = _db_get(key)
            if payload is not None:
                _mem_put(key, payload)
                _record(endpoint, "hits")
                return respond(payload, "HIT")

            # Miss: compute once even if several workers ask at the same moment.
            os.makedirs(LOCK_DIR, exist_ok=True)
            with open(os.path.join(LOCK_DIR, f"{key[:40]}.lock"), "w") as lock_file:
                fcntl.flock(lock_file, fcntl.LOCK_EX)
                try:
                    payload = _db_get(key)
                    if payload is not None:
                        _mem_put(key, payload)
                        _record(endpoint, "hits")
                        return respond(payload, "HIT-WAIT")
                    t0 = time.perf_counter()
                    result = fn(*args, **kwargs)
                    compute_ms = int((time.perf_counter() - t0) * 1000)
                    if isinstance(result, Response):
                        _record(endpoint, "bypass")
                        return result
                    if not as_route and not isinstance(result, (dict, list)):
                        return result
                    payload = gzip.compress(json.dumps(jsonable_encoder(result), separators=(",", ":"), default=str).encode(),
                                            compresslevel=6, mtime=0)
                    _db_put(key, endpoint, payload, ttl, compute_ms)
                    _mem_put(key, payload)
                    _record(endpoint, "misses")
                    _record(endpoint, "compute_ms", compute_ms)
                    if compute_ms > 2000:
                        try:
                            from core.event_log import log_event
                            log_event("cache.slow_compute", category="performance", level="warning",
                                      company_id=company, endpoint=endpoint, compute_ms=compute_ms,
                                      message=f"{endpoint} took {compute_ms} ms to compute (now cached)")
                        except Exception:
                            pass
                    return respond(payload, "MISS")
                finally:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
        wrapper.cache_scopes = scopes
        return wrapper
    return deco


def version_token(scopes: Iterable[str], company_id: Optional[str]) -> str:
    """Short fingerprint of the data versions an in-process cache depends on. In-process caches store
    it with their value and recompute when it changes, so a write made by ANY worker or process
    (caught by the DB triggers / file mtimes) invalidates them everywhere."""
    try:
        return hashlib.sha1(json.dumps(versions(scopes, company_id), sort_keys=True, default=str).encode()).hexdigest()[:16]
    except Exception:
        return f"err-{time.time()}"  # never reuse a cached value if versions can't be read


def route_defaults(fn: Callable, **overrides) -> Dict[str, Any]:
    """The kwargs FastAPI would pass for a request that sets only `overrides` (Query defaults resolved),
    so a warm-up call lands on exactly the same cache key as a real request."""
    import inspect
    target = getattr(fn, "__wrapped__", fn)
    kwargs = {}
    for name, p in inspect.signature(target).parameters.items():
        if name in overrides:
            kwargs[name] = overrides[name]
            continue
        default = p.default
        if default is inspect.Parameter.empty:
            continue
        kwargs[name] = getattr(default, "default", default)  # Query(...) -> its default value
    return kwargs


def try_exclusive(name: str):
    """Non-blocking cross-process lock (only one worker runs a background job). Returns the open file
    (keep it open to hold the lock) or None if another process holds it."""
    os.makedirs(LOCK_DIR, exist_ok=True)
    f = open(os.path.join(LOCK_DIR, f"job_{name}.lock"), "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None
