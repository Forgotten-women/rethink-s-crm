"""
Nightly backup of the CRM database (the source of truth - the donations parquet is rebuilt from it).

  1. `VACUUM INTO` a compact, consistent snapshot of the live SQLite file (the app keeps running).
  2. `PRAGMA integrity_check` on the snapshot - a damaged copy is never kept or uploaded.
  3. xz-compress it (about 15 MB today) and keep the last KEEP_LOCAL copies in data_cache/backups/nightly/.
  4. Off-site copy to a PRIVATE Supabase Storage bucket when SUPABASE_SERVICE_ROLE_KEY is set in .env
     (project URL derived from DATABASE_URL, or SUPABASE_URL). Files larger than the free-plan upload limit
     are split into parts. A manifest (sha256, size, row counts) is uploaded with each backup; the last
     KEEP_REMOTE backups are kept.

This replaces pushing the whole donations table into the Supabase *database* (which burned its Disk IO budget):
Storage uploads use no database IO.

Restore:  xz -d crm_YYYYMMDD_HHMMSS.db.xz   (or: cat crm_*.db.xz.part* > x.db.xz first)  ->  a normal SQLite file.
Run now:  venv/bin/python -m core.nightly_backup
"""
import datetime
import glob
import hashlib
import json
import lzma
import os
import re
import shutil
import sqlite3
import time
from typing import Any, Dict, List, Optional

import requests

from config.settings import BASE_DIR, LOCAL_DB_PATH

BACKUP_DIR = os.path.join(BASE_DIR, "data_cache", "backups", "nightly")
STATUS_FILE = os.path.join(BASE_DIR, "data_cache", "backup_status.json")
KEEP_LOCAL = int(os.environ.get("BACKUP_KEEP_LOCAL", "14"))
KEEP_REMOTE = int(os.environ.get("BACKUP_KEEP_REMOTE", "14"))
PART_BYTES = 45 * 1024 * 1024  # stays under Supabase's 50 MB free-plan upload limit
REMOTE_PREFIX = "crm-db"
COUNT_TABLES = ["donations", "sponsorship_allocations", "sponsorship_allocation_donors", "sponsorship_beneficiaries",
                "sponsorship_communications", "payout_settlements", "users"]


def _supabase_config() -> Optional[Dict[str, str]]:
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not key:
        return None
    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    if not url:
        m = re.search(r"db\.([a-z0-9]+)\.supabase\.co", os.environ.get("DATABASE_URL", ""))
        if not m:
            m = re.search(r"postgres\.([a-z0-9]+)[:@]", os.environ.get("DATABASE_URL", ""))  # pooler URL form
        if not m:
            return None
        url = f"https://{m.group(1)}.supabase.co"
    return {"url": url, "key": key, "bucket": os.environ.get("SUPABASE_BACKUP_BUCKET", "crm-backups")}


def _headers(cfg: Dict[str, str], content_type: Optional[str] = None) -> Dict[str, str]:
    h = {"Authorization": f"Bearer {cfg['key']}", "apikey": cfg["key"]}
    if content_type:
        h["Content-Type"] = content_type
    return h


def _ensure_bucket(cfg: Dict[str, str]) -> None:
    r = requests.post(f"{cfg['url']}/storage/v1/bucket", headers=_headers(cfg, "application/json"),
                      json={"id": cfg["bucket"], "name": cfg["bucket"], "public": False}, timeout=30)
    if r.status_code not in (200, 201) and "already exists" not in r.text.lower() and r.status_code not in (400, 409):
        raise RuntimeError(f"Could not create bucket: HTTP {r.status_code} {r.text[:200]}")


def _upload(cfg: Dict[str, str], remote_path: str, data: bytes, content_type: str) -> None:
    r = requests.post(f"{cfg['url']}/storage/v1/object/{cfg['bucket']}/{remote_path}",
                      headers={**_headers(cfg, content_type), "x-upsert": "true"}, data=data, timeout=300)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Upload of {remote_path} failed: HTTP {r.status_code} {r.text[:200]}")


def _list_remote(cfg: Dict[str, str]) -> List[str]:
    r = requests.post(f"{cfg['url']}/storage/v1/object/list/{cfg['bucket']}", headers=_headers(cfg, "application/json"),
                      json={"prefix": f"{REMOTE_PREFIX}/", "limit": 1000, "sortBy": {"column": "name", "order": "asc"}}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Listing backups failed: HTTP {r.status_code} {r.text[:200]}")
    return [f"{REMOTE_PREFIX}/{o['name']}" for o in r.json() if o.get("name")]


def _prune_remote(cfg: Dict[str, str]) -> int:
    names = _list_remote(cfg)
    stamps = sorted({m.group(1) for n in names if (m := re.search(r"crm_(\d{8}_\d{6})", n))})
    old = set(stamps[:-KEEP_REMOTE]) if len(stamps) > KEEP_REMOTE else set()
    doomed = [n for n in names if any(f"crm_{s}" in n for s in old)]
    if doomed:
        r = requests.delete(f"{cfg['url']}/storage/v1/object/{cfg['bucket']}", headers=_headers(cfg, "application/json"),
                            json={"prefixes": doomed}, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"Removing old backups failed: HTTP {r.status_code} {r.text[:200]}")
    return len(doomed)


def _prune_local() -> int:
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "crm_*.db.xz")))
    doomed = files[:-KEEP_LOCAL] if len(files) > KEEP_LOCAL else []
    for f in doomed:
        os.remove(f)
        if os.path.exists(f + ".json"):
            os.remove(f + ".json")
    return len(doomed)


def _write_status(status: Dict[str, Any]) -> None:
    tmp = STATUS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(status, f, indent=1, default=str)
    os.replace(tmp, STATUS_FILE)


def run_backup() -> Dict[str, Any]:
    started = time.time()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    os.chmod(BACKUP_DIR, 0o700)  # backups hold donor data: app user only
    old_umask = os.umask(0o077)
    snapshot = os.path.join(BACKUP_DIR, f".snapshot_{stamp}.db")
    archive = os.path.join(BACKUP_DIR, f"crm_{stamp}.db.xz")
    result: Dict[str, Any] = {"started_at": stamp, "status": "failed"}
    try:
        src = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=60)
        try:
            src.execute(f"VACUUM INTO '{snapshot}'")
        finally:
            src.close()
        snap = sqlite3.connect(snapshot)
        try:
            check = snap.execute("PRAGMA integrity_check").fetchone()[0]
            counts = {}
            for t in COUNT_TABLES:
                try:
                    counts[t] = snap.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                except sqlite3.OperationalError:
                    pass
        finally:
            snap.close()
        if check != "ok":
            raise RuntimeError(f"Snapshot failed integrity check: {check}")

        sha = hashlib.sha256()
        with open(snapshot, "rb") as f, lzma.open(archive + ".tmp", "wb", preset=6) as out:
            for chunk in iter(lambda: f.read(4 << 20), b""):
                out.write(chunk)
        with open(archive + ".tmp", "rb") as f:
            for chunk in iter(lambda: f.read(4 << 20), b""):
                sha.update(chunk)
        os.replace(archive + ".tmp", archive)
        manifest = {"file": os.path.basename(archive), "created_utc": stamp, "sha256": sha.hexdigest(),
                    "bytes": os.path.getsize(archive), "db_bytes": os.path.getsize(snapshot),
                    "integrity_check": check, "row_counts": counts,
                    "restore": "xz -d <file>.db.xz (join .partNNN files in order first, e.g. cat file.part* > file)"}
        with open(archive + ".json", "w") as f:
            json.dump(manifest, f, indent=1)
        result.update(status="local_only", file=archive, bytes=manifest["bytes"], sha256=manifest["sha256"],
                      row_counts=counts, pruned_local=_prune_local())

        cfg = _supabase_config()
        if cfg is None:
            result["offsite"] = "not configured (add SUPABASE_SERVICE_ROLE_KEY to .env)"
        else:
            _ensure_bucket(cfg)
            name = os.path.basename(archive)
            with open(archive, "rb") as f:
                data = f.read()
            parts = [data[i:i + PART_BYTES] for i in range(0, len(data), PART_BYTES)] or [b""]
            uploaded = []
            for n, part in enumerate(parts, start=1):
                remote = f"{REMOTE_PREFIX}/{name}" if len(parts) == 1 else f"{REMOTE_PREFIX}/{name}.part{n:03d}"
                _upload(cfg, remote, part, "application/x-xz")
                uploaded.append(remote)
            manifest["remote_files"] = uploaded
            _upload(cfg, f"{REMOTE_PREFIX}/{name}.json", json.dumps(manifest, indent=1).encode(), "application/json")
            remote_names = set(_list_remote(cfg))
            missing = [u for u in uploaded if u not in remote_names]
            if missing:
                raise RuntimeError(f"Upload not visible in bucket: {missing}")
            result.update(status="ok", offsite=f"supabase://{cfg['bucket']}/{REMOTE_PREFIX}/{name}",
                          remote_parts=len(uploaded), pruned_remote=_prune_remote(cfg))
    except Exception as e:
        result["error"] = str(e)
    finally:
        os.umask(old_umask)
        if os.path.exists(snapshot):
            os.remove(snapshot)
        if os.path.exists(archive + ".tmp"):
            os.remove(archive + ".tmp")
    result["seconds"] = round(time.time() - started, 1)
    result["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    previous = {}
    try:
        with open(STATUS_FILE) as f:
            previous = json.load(f)
    except (OSError, ValueError):
        pass
    status = {"last_run": result,
              "last_success": result if result["status"] in ("ok", "local_only") else previous.get("last_success"),
              "last_offsite_success": result if result["status"] == "ok" else previous.get("last_offsite_success")}
    _write_status(status)
    try:
        from core.event_log import log_event
        if result["status"] == "failed":
            log_event("backup.failed", category="backup", level="error", message=f"Nightly backup failed: {result.get('error')}",
                      **{k: v for k, v in result.items() if k not in ("row_counts",)})
        else:
            log_event("backup.completed", category="backup",
                      level="info" if result["status"] == "ok" else "warning",
                      message=f"Nightly backup {result['status']}: {round(result['bytes'] / 2**20, 1)} MB"
                              f"{' -> ' + result['offsite'] if result['status'] == 'ok' else ' (' + str(result.get('offsite')) + ')'}",
                      **{k: v for k, v in result.items() if k not in ("row_counts",)})
    except Exception:
        pass
    return result


if __name__ == "__main__":
    print(json.dumps(run_backup(), indent=1, default=str))
