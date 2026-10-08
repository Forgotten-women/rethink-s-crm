"""
Structured event logging for the CRM (backend + platform-sync service).

    from core.event_log import log_event
    log_event("email.sent", category="email", company_id="iqra", recipient="a@b.c", template="profile_intro")

Every event is written to the local SQLite table `app_event_logs` (so the hidden ops console works even
when Axiom is unreachable) and shipped to Axiom in the background. Logging never raises into callers.
Values under sensitive keys (passwords, tokens, secrets, authorization headers) are redacted.
"""
import datetime
import json
import logging
import os
import queue
import re
import socket
import sqlite3
import threading
import time
from typing import Any, Dict, Optional

import requests

from config.settings import LOCAL_DB_PATH

_logger = logging.getLogger("event_log")

AXIOM_DATASET = os.environ.get("AXIOM_DATASET", "rethink_crm_app_logs")
_AXIOM_URL = f"https://api.axiom.co/v1/datasets/{AXIOM_DATASET}/ingest"
_SERVICE = os.environ.get("CRM_SERVICE_NAME", "crm-backend")
_HOST = socket.gethostname()
_LOCAL_RETENTION_DAYS = 90
_SENSITIVE_KEY = re.compile(r"pass(word)?|secret|token|authorization|api[_-]?key|cookie|refresh|jwt|credential", re.I)

_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=20000)
_state = {"axiom_last_ok": None, "axiom_last_error": None, "axiom_shipped": 0, "axiom_dropped": 0, "started": False}
_lock = threading.Lock()
_table_ready = False


def _axiom_token() -> str:
    return (os.environ.get("AXIOM_Rethink_CRM_API_token") or os.environ.get("AXIOM_TOKEN") or "").strip()


def set_service_name(name: str) -> None:
    global _SERVICE
    _SERVICE = name


def _redact(value: Any, key: str = "") -> Any:
    if key and _SENSITIVE_KEY.search(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {k: _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value][:50]
    if isinstance(value, str):
        # Bearer/JWT-looking strings never belong in logs, whatever the key is called.
        if value.startswith("Bearer ") or re.fullmatch(r"eyJ[\w-]+\.[\w-]+\.[\w-]+", value):
            return "[redacted]"
        return value[:2000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:2000]


def _ensure_table(conn: sqlite3.Connection) -> None:
    global _table_ready
    if _table_ready:
        return
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_event_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            level TEXT NOT NULL,
            category TEXT NOT NULL,
            event TEXT NOT NULL,
            message TEXT,
            company_id TEXT,
            actor TEXT,
            service TEXT,
            data_json TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_app_event_logs_ts ON app_event_logs(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_app_event_logs_cat ON app_event_logs(category, ts)")
    conn.execute("DELETE FROM app_event_logs WHERE ts < ?", (
        (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=_LOCAL_RETENTION_DAYS)).isoformat(),))
    _table_ready = True


def log_event(event: str, category: str = "app", level: str = "info", message: str = "",
              company_id: Optional[str] = None, actor: Optional[str] = None, **fields: Any) -> None:
    """Records one structured event. Safe to call from anywhere; failures are swallowed."""
    try:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        data = _redact(fields)
        record = {
            "_time": now, "level": level, "category": category, "event": event,
            "message": message or event, "company_id": company_id, "actor": actor,
            "service": _SERVICE, "host": _HOST, **(data if isinstance(data, dict) else {}),
        }
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=5.0)
            try:
                _ensure_table(conn)
                conn.execute(
                    "INSERT INTO app_event_logs (ts, level, category, event, message, company_id, actor, service, data_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (now, level, category, event, record["message"], company_id, actor, _SERVICE,
                     json.dumps(data, default=str)))
                conn.commit()
            finally:
                conn.close()
        except Exception as db_err:
            _logger.warning("event_log local write failed: %s", db_err)
        if _axiom_token():
            _start_shipper()
            try:
                _queue.put_nowait(record)
            except queue.Full:
                with _lock:
                    _state["axiom_dropped"] += 1
        log_fn = _logger.error if level in ("error", "critical") else (_logger.warning if level == "warning" else _logger.info)
        log_fn("[%s] %s %s", category, event, message or "")
    except Exception:
        pass


def _ship(batch) -> bool:
    try:
        r = requests.post(_AXIOM_URL, headers={"Authorization": f"Bearer {_axiom_token()}", "Content-Type": "application/json"},
                          json=batch, timeout=15)
        ok = r.status_code == 200
        with _lock:
            if ok:
                _state["axiom_last_ok"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                _state["axiom_shipped"] += len(batch)
            else:
                _state["axiom_last_error"] = f"HTTP {r.status_code}: {r.text[:200]}"
        return ok
    except Exception as e:
        with _lock:
            _state["axiom_last_error"] = str(e)[:200]
        return False


def _shipper_loop() -> None:
    pending = []
    backoff = 2
    while True:
        try:
            deadline = time.time() + 2
            while len(pending) < 500 and time.time() < deadline:
                try:
                    pending.append(_queue.get(timeout=max(0.05, deadline - time.time())))
                except queue.Empty:
                    break
            if not pending:
                continue
            if _ship(pending):
                pending, backoff = [], 2
            else:
                if len(pending) > 5000:  # keep the newest during a long outage
                    with _lock:
                        _state["axiom_dropped"] += len(pending) - 5000
                    pending = pending[-5000:]
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
        except Exception:
            time.sleep(5)


def _start_shipper() -> None:
    with _lock:
        if _state["started"]:
            return
        _state["started"] = True
    threading.Thread(target=_shipper_loop, name="axiom-shipper", daemon=True).start()


def flush(timeout: float = 5.0) -> None:
    """Best effort: wait for queued events to ship (used by short-lived scripts)."""
    end = time.time() + timeout
    while not _queue.empty() and time.time() < end:
        time.sleep(0.2)
    time.sleep(0.5)


def shipping_status() -> Dict[str, Any]:
    with _lock:
        return {**_state, "configured": bool(_axiom_token()), "dataset": AXIOM_DATASET, "backlog": _queue.qsize()}


def query_local(category: Optional[str] = None, level: Optional[str] = None, company_id: Optional[str] = None,
                search: Optional[str] = None, since: Optional[str] = None, until: Optional[str] = None,
                event: Optional[str] = None, limit: int = 200, offset: int = 0) -> Dict[str, Any]:
    where, params = ["1=1"], []
    if category and category != "all":
        where.append("category = ?"); params.append(category)
    if level and level != "all":
        levels = {"error": ("error", "critical"), "warning": ("warning", "error", "critical")}.get(level, (level,))
        where.append(f"level IN ({','.join('?' * len(levels))})"); params.extend(levels)
    if company_id and company_id != "all":
        where.append("company_id = ?"); params.append(company_id)
    if event:
        where.append("event LIKE ?"); params.append(f"{event}%")
    if search:
        where.append("(message LIKE ? OR event LIKE ? OR actor LIKE ? OR data_json LIKE ?)"); params.extend([f"%{search}%"] * 4)
    if since:
        where.append("ts >= ?"); params.append(since)
    if until:
        where.append("ts <= ?"); params.append(until)
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    try:
        _ensure_table(conn)
        clause = " AND ".join(where)
        total = conn.execute(f"SELECT COUNT(*) FROM app_event_logs WHERE {clause}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT id, ts, level, category, event, message, company_id, actor, service, data_json FROM app_event_logs "
            f"WHERE {clause} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?", params + [limit, offset]).fetchall()
        cats = [r[0] for r in conn.execute("SELECT DISTINCT category FROM app_event_logs ORDER BY category")]
    finally:
        conn.close()
    items = []
    for r in rows:
        try:
            data = json.loads(r[9]) if r[9] else {}
        except Exception:
            data = {"raw": r[9]}
        items.append({"id": r[0], "ts": r[1], "level": r[2], "category": r[3], "event": r[4], "message": r[5],
                      "company_id": r[6], "actor": r[7], "service": r[8], "data": data})
    return {"total": total, "items": items, "categories": cats}


def query_axiom(apl: str, since_hours: int = 24) -> Dict[str, Any]:
    start = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=since_hours)).isoformat()
    r = requests.post("https://api.axiom.co/v1/datasets/_apl?format=legacy",
                      headers={"Authorization": f"Bearer {_axiom_token()}", "Content-Type": "application/json"},
                      json={"apl": apl, "startTime": start}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Axiom query failed: HTTP {r.status_code} {r.text[:300]}")
    return r.json()
