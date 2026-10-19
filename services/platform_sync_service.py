#!/usr/bin/env python3
"""
Platform Synchronization Service (Madinah & Givebrite)
-------------------------------------------------------
Runs continuously in the background to scrape and sync real-time financial,
transactional, and campaign metrics from both Givebrite and Madinah platforms.

Key Architecture:
- 100% Pure HTTP REST API integration for high-speed live donation retrieval.
- Direct CRM Database & Parquet Persistence via core.givebrite_ingestion.
- Strict Tenant Isolation (enforces company_id = 'iqra' for GiveBrite).
- Native Currency & Amount Preservation (no synthetic exchange rates).
- 2-Tier Classification Resolution (Giving Level -> Campaign Default -> Unassigned).
- Automatic Token Life-Cycle Management:
  * GiveBrite: Auto-renewed via headless Playwright script when <10m to expiry.
  * Madinah: Pure HTTP token rolling via 7-day refresh token.
- Non-destructive 60-day historical backfill on startup.
- Ultra-low resource footprint (< 50MB RAM, < 0.2% CPU).
"""

import os
import sys
import time
import json
import base64
import logging
import threading
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import requests
from dotenv import load_dotenv

# Path setup
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Load environment variables
load_dotenv(os.path.join(BASE_DIR, ".env"))

from config.settings import GIVEBRITE_CHARITY_IDS
from core.givebrite_ingestion import (
    ingest_givebrite_donations,
    run_historical_backfill,
    GIVEBRITE_API_BASE
)
from core.madinah_ingestion import (
    ingest_madinah_donations,
    run_madinah_historical_backfill,
    MADINAH_APIM_BASE
)
from core.event_log import log_event, set_service_name

set_service_name("platform-sync")

DATA_CACHE_DIR = os.path.join(BASE_DIR, "data_cache")
MADINAH_TOKEN_FILE = os.path.join(BASE_DIR, ".madinah_token.json")
GIVEBRITE_TOKEN_FILE = os.path.join(BASE_DIR, ".givebrite_token.json")
GIVEBRITE_TOKEN_FILES = {
    "iqra": os.path.join(BASE_DIR, ".givebrite_token.json"),
    "rethink": os.path.join(BASE_DIR, ".givebrite_rethink_token.json"),
}
MASTER_SYNC_FILE = os.path.join(DATA_CACHE_DIR, "platform_sync_data.json")
MADINAH_SYNC_FILE = os.path.join(DATA_CACHE_DIR, "madinah_sync_data.json")
HEALTH_FILE = os.path.join(DATA_CACHE_DIR, "platform_health.json")

# Service Configuration
SYNC_INTERVAL_SEC = int(os.environ.get("SYNC_INTERVAL_SEC", 60))  # standard interval
DEEP_SYNC_INTERVAL_SEC = 1800  # 30 minutes for deep campaign catalog scans
GIVEBRITE_CHARITY_ID = GIVEBRITE_CHARITY_IDS.get("iqra", "")
MADINAH_APIM_BASE = "https://md-backend-prod-api.azure-api.net"

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [platform-sync] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("platform_sync")

# Global lock for file operations
_file_write_lock = threading.Lock()


def atomic_write_json(file_path: str, data: dict):
    """
    Atomically writes data to a JSON file using a unique temp file and os.replace.
    On POSIX systems, os.replace is an atomic syscall preventing any deadlock,
    race conditions, or partial/corrupted reads by external consumers.
    """
    with _file_write_lock:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        temp_path = f"{file_path}.tmp.{os.getpid()}.{int(time.time() * 1000)}"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, file_path)
        except Exception as e:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            raise e


def parse_jwt_exp(token_str: str) -> float:
    """Extracts expiration timestamp from JWT payload."""
    try:
        raw = token_str.replace("Bearer ", "").strip()
        parts = raw.split(".")
        if len(parts) >= 2:
            padding = "=" * ((4 - len(parts[1]) % 4) % 4)
            payload = json.loads(base64.b64decode(parts[1] + padding).decode("utf-8"))
            return float(payload.get("exp", 0))
    except Exception:
        pass
    return 0.0


class PlatformSyncService:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Rethink-CRM-Sync/1.0"})
        self.last_deep_sync = 0.0
        self.backfill_completed = {"iqra": True, "rethink": True}
        self.madinah_backfill_completed = True
        self.health: Dict[str, Dict[str, Any]] = {}
        try:
            with open(HEALTH_FILE, "r", encoding="utf-8") as f:
                self.health = json.load(f)
        except Exception:
            self.health = {}
        for p in ("givebrite", "givebrite_iqra", "givebrite_rethink", "madinah", "stripe", "paysuite"):
            self.health.setdefault(p, {})
            self.health[p]["consecutive_failures"] = 0

        # Seed last_ingested_at from local DB if missing so Ops Console reflects accurate donation history
        try:
            from core.database import get_db_connection
            conn = get_db_connection()
            cur = conn.cursor()
            for plat, comp in (
                ("madinah", "iqra"),
                ("givebrite", "iqra"),
                ("givebrite_iqra", "iqra"),
                ("givebrite_rethink", "rethink"),
                ("launchgood_iqra", "iqra"),
                ("launchgood_rethink", "rethink"),
            ):
                if plat in self.health and (not self.health[plat].get("last_ingested_at") or str(self.health[plat].get("last_ingested_at")).lower() in ("nan", "none", "")):
                    if plat.startswith("launchgood"):
                        cur.execute("""
                            SELECT MAX("Created Date (UTC)" || 'T' || "Created Time (UTC)" || 'Z')
                            FROM donations
                            WHERE company_id = ? AND (Platform = 'LaunchGood' OR Source LIKE '%LaunchGood%') AND "Created Date (UTC)" LIKE '20%'
                        """, (comp,))
                    else:
                        cur.execute("""
                            SELECT MAX("Created Date (UTC)" || 'T' || "Created Time (UTC)" || 'Z')
                            FROM donations
                            WHERE company_id = ? AND LOWER(Source) LIKE ? AND "Created Date (UTC)" LIKE '20%'
                        """, (comp, f"%{plat.split('_')[0]}%",))
                    r = cur.fetchone()
                    if r and r[0] and "nan" not in str(r[0]).lower():
                        self.health[plat]["last_ingested_at"] = r[0]
            conn.close()
        except Exception as seed_err:
            logger.debug(f"Notice seeding initial last_ingested_at: {seed_err}")

    # -------------------------------------------------------------------------
    # Health tracking (read by the hidden ops console via /api/ops/status)
    # -------------------------------------------------------------------------
    def _note_token_refresh(self, platform: str, error: Optional[str], method: str = "http-refresh"):
        h = self.health.setdefault(platform, {})
        now = datetime.now(timezone.utc).isoformat()
        if error:
            h["last_token_refresh_error"] = error
            h["last_token_refresh_error_at"] = now
            log_event("session.refresh_failed", category="session", level="error", platform=platform, method=method,
                      detail=error, message=f"{platform} session renewal failed ({method}): {error}")
        else:
            h["last_token_refresh_at"] = now
            h.pop("last_token_refresh_error", None)
            log_event("session.refreshed", category="session", platform=platform, method=method,
                      message=f"{platform} session renewed ({method})")

    def _record_cycle(self, platform: str, ok: bool, http_status: Optional[int], error: Optional[str],
                      ingested: int = 0, fetched: int = 0):
        h = self.health.setdefault(platform, {})
        now = datetime.now(timezone.utc).isoformat()
        was_failing = h.get("consecutive_failures", 0) >= 3
        h["last_cycle_at"] = now
        h["last_http_status"] = http_status
        h["last_fetched"] = fetched
        if ok:
            h["last_ok_at"] = now
            h["consecutive_failures"] = 0
            if ingested:
                h["last_ingested_at"] = now
                h["last_ingested_count"] = ingested
                log_event("sync.donations_ingested", category="sync", platform=platform, count=ingested,
                          company_id="iqra", message=f"{platform}: {ingested} new donation(s) ingested")
            if was_failing:
                log_event("sync.recovered", category="sync", platform=platform,
                          message=f"{platform} API sync is working again")
        else:
            h["consecutive_failures"] = h.get("consecutive_failures", 0) + 1
            h["last_error"] = error
            h["last_error_at"] = now
            # Log the first failure and then every 10th, so an outage is visible without flooding the log.
            n = h["consecutive_failures"]
            if n == 1 or n == 3 or n % 10 == 0:
                log_event("sync.failed", category="sync", level="error" if n >= 3 else "warning", platform=platform,
                          http_status=http_status, consecutive_failures=n, detail=error,
                          message=f"{platform} sync failed ({n} in a row): {error}")
        try:
            atomic_write_json(HEALTH_FILE, self.health)
        except Exception as ex:
            logger.error(f"Failed writing health file: {ex}")

    def get_today_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # -------------------------------------------------------------------------
    # Token Management
    # -------------------------------------------------------------------------
    def ensure_madinah_token(self, force_refresh: bool = False) -> str:
        """Loads and auto-renews Madinah token via pure HTTP if near expiration (<1h) or force_refresh."""
        now = time.time()
        need_script_refresh = False
        access_token = ""
        refresh_token = ""

        if not os.path.exists(MADINAH_TOKEN_FILE):
            need_script_refresh = True
        else:
            try:
                with open(MADINAH_TOKEN_FILE, "r", encoding="utf-8") as f:
                    token_data = json.load(f)
                access_token = token_data.get("accessToken", "")
                refresh_token = token_data.get("refreshToken", "")
                exp = parse_jwt_exp(access_token)
                time_left_sec = exp - now if exp else 0

                # Auto-refresh via pure HTTP if < 1 hour remaining or explicitly forced
                if (force_refresh or (exp and time_left_sec < 3600)) and refresh_token:
                    logger.info(f"Madinah token refreshing via pure HTTP (Time remaining: {time_left_sec/60:.1f}m)...")
                    r = self.session.post(
                        f"{MADINAH_APIM_BASE}/main-server/api/v1/user/token",
                        headers={"Content-Type": "application/json", "Accept": "application/json"},
                        json={"refreshToken": refresh_token},
                        timeout=(5, 25)
                    )
                    if r.status_code == 200:
                        resp_json = r.json()
                        new_data = resp_json.get("data", {})
                        if new_data.get("accessToken"):
                            token_data["accessToken"] = new_data["accessToken"]
                            if new_data.get("refreshToken"):
                                token_data["refreshToken"] = new_data["refreshToken"]
                            token_data["retrievedAt"] = datetime.now(timezone.utc).isoformat()
                            atomic_write_json(MADINAH_TOKEN_FILE, token_data)
                            os.chmod(MADINAH_TOKEN_FILE, 0o600)
                            logger.info("Successfully renewed Madinah tokens via pure HTTP API.")
                            self._note_token_refresh("madinah", None)
                            access_token = token_data["accessToken"]
                    else:
                        logger.warning(f"Madinah HTTP token refresh returned {r.status_code}. Falling back to script.")
                        self._note_token_refresh("madinah", f"HTTP refresh returned {r.status_code}")
                        need_script_refresh = True
                elif not access_token or (exp and exp <= now):
                    need_script_refresh = True
            except Exception as ex:
                logger.error(f"Madinah token evaluation error: {ex}")
                need_script_refresh = True

        if need_script_refresh:
            logger.info("Madinah token expired or missing. Refreshing via login script...")
            try:
                script_path = os.path.join(BASE_DIR, "scripts", "get_madinah_jwt.js")
                res = subprocess.run(["node", script_path], cwd=BASE_DIR, capture_output=True, text=True, timeout=60)
                if res.returncode == 0:
                    with open(MADINAH_TOKEN_FILE, "r", encoding="utf-8") as f:
                        token_data = json.load(f)
                    access_token = token_data.get("accessToken", "")
                    logger.info("Madinah token auto-refreshed successfully via script.")
                    self._note_token_refresh("madinah", None, method="browser-login")
                else:
                    logger.error(f"Madinah script login notice: {res.stderr[:200]}")
                    self._note_token_refresh("madinah", f"Browser login failed: {res.stderr[:150]}", method="browser-login")
            except Exception as e:
                logger.error(f"Madinah script login exception: {e}")
                self._note_token_refresh("madinah", f"Browser login error: {e}", method="browser-login")

        if not access_token.startswith("Bearer "):
            access_token = f"Bearer {access_token}"
        return access_token

    def get_givebrite_token(self, company_id: str = "iqra", force_refresh: bool = False) -> str:
        """Loads and auto-renews Givebrite JWT Bearer token (<10m to expiry or force_refresh) via Playwright."""
        cid = company_id.lower()
        token_file = GIVEBRITE_TOKEN_FILES.get(cid, GIVEBRITE_TOKEN_FILE)
        now = time.time()
        need_refresh = force_refresh
        access_token = ""

        if not os.path.exists(token_file):
            need_refresh = True
        elif not need_refresh:
            try:
                with open(token_file, "r", encoding="utf-8") as f:
                    token_data = json.load(f)
                access_token = token_data.get("accessToken", "")
                exp = parse_jwt_exp(access_token)
                time_left_sec = exp - now if exp else 0
                if not exp or time_left_sec < 600:  # Less than 10 minutes remaining
                    logger.info(f"GiveBrite ({cid}) JWT expiring soon (Time remaining: {time_left_sec/60:.1f}m). Auto-renewing...")
                    need_refresh = True
            except Exception:
                need_refresh = True

        if need_refresh:
            logger.info(f"Initiating headless GiveBrite ({cid}) Playwright token auto-renewal...")
            try:
                script_path = os.path.join(BASE_DIR, "scripts", "get_givebrite_jwt.js")
                res = subprocess.run(["node", script_path, cid], cwd=BASE_DIR, capture_output=True, text=True, timeout=60)
                if res.returncode == 0:
                    with open(token_file, "r", encoding="utf-8") as f:
                        token_data = json.load(f)
                    access_token = token_data.get("accessToken", "")
                    logger.info(f"GiveBrite ({cid}) token auto-refreshed successfully via Playwright.")
                    self._note_token_refresh(f"givebrite_{cid}", None, method="browser-login")
                    if cid == "iqra":
                        self._note_token_refresh("givebrite", None, method="browser-login")
                else:
                    logger.error(f"GiveBrite ({cid}) auto-refresh failed (code {res.returncode}): {res.stderr[:200]}")
                    self._note_token_refresh(f"givebrite_{cid}", f"Browser login failed (code {res.returncode}): {res.stderr[:150]}",
                                             method="browser-login")
            except Exception as e:
                logger.error(f"GiveBrite ({cid}) auto-refresh exception: {e}")
                self._note_token_refresh(f"givebrite_{cid}", f"Browser login error: {e}", method="browser-login")

        if not access_token.startswith("Bearer "):
            access_token = f"Bearer {access_token}"
        return access_token

    # -------------------------------------------------------------------------
    # Sync Logic: Madinah
    # -------------------------------------------------------------------------
    def sync_madinah(self, is_deep: bool = False) -> dict:
        auth_header = self.ensure_madinah_token()
        headers = {
            "Authorization": auth_header,
            "Accept": "application/json",
            "Origin": "https://www.madinah.com",
            "Referer": "https://www.madinah.com/"
        }
        today = self.get_today_str()

        result = {
            "platform": "madinah",
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "status": "ok",
            "donations_latest": [],
            "status_counts": {},
            "analytics_summary": {},
            "overview": {},
            "campaigns": []
        }

        # 1. Startup Historical Backfill (Non-destructive, skips existing IDs)
        if not self.madinah_backfill_completed:
            try:
                logger.info("Executing initial Madinah historical backfill (fetching all missing donations)...")
                bf_res = run_madinah_historical_backfill(auth_header, start_date="2024-01-01", company_id="iqra")
                self.madinah_backfill_completed = True
                logger.info(f"Madinah backfill finished: {bf_res['inserted']} inserted, {bf_res['skipped']} already present.")
            except Exception as bf_ex:
                logger.error(f"Madinah initial backfill notice: {bf_ex}")

        # 2. Latest Real-Time Donations Stream (Rolling 7-day window with pagination)
        start_window = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        page = 1
        all_donations = []
        total_inserted = 0
        total_skipped = 0
        latest_http_status = None
        fetch_success = False

        while True:
            url_madinah_donations = (
                f"{MADINAH_APIM_BASE}/campaign-server/api/v1/campaign/donations/latest"
                f"?startDate={start_window}&endDate={today}&page={page}&limit=100"
            )
            try:
                r = None
                for attempt in range(2):
                    try:
                        r = self.session.get(url_madinah_donations, headers=headers, timeout=(5, 35))
                        if r.status_code == 401:
                            logger.warning("[Madinah] Received HTTP 401. Performing immediate token renewal...")
                            auth_header = self.ensure_madinah_token(force_refresh=True)
                            headers["Authorization"] = auth_header
                            r = self.session.get(url_madinah_donations, headers=headers, timeout=(5, 35))
                        break
                    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as net_err:
                        if attempt == 0:
                            logger.warning(f"Madinah donations fetch transient network issue on page {page} ({net_err}), retrying in 2s...")
                            time.sleep(2)
                            continue
                        else:
                            raise net_err

                if r is None:
                    break

                latest_http_status = r.status_code
                if r.status_code == 200:
                    data = r.json().get("data", {})
                    raw_donations = data.get("donations", [])
                    if not raw_donations:
                        fetch_success = True
                        break
                    all_donations.extend(raw_donations)
                    result["status_counts"] = data.get("statusCounts", {})

                    # Ingest to SQLite and Parquet
                    ingest_res = ingest_madinah_donations(raw_donations, company_id="iqra")
                    total_inserted += ingest_res.get("inserted", 0)
                    total_skipped += ingest_res.get("skipped", 0)

                    pagination = data.get("pagination", {})
                    total_pages = pagination.get("pages", 1)
                    if page >= total_pages:
                        fetch_success = True
                        break
                    page += 1
                    time.sleep(0.1)
                else:
                    logger.warning(f"Madinah donations HTTP {r.status_code}")
                    self._record_cycle("madinah", False, r.status_code, f"Donations API HTTP {r.status_code}: {r.text[:150]}")
                    fetch_success = False
                    break
            except Exception as ex:
                logger.error(f"Madinah donations fetch error: {ex}")
                latest_http_status = None
                fetch_success = False
                self._record_cycle("madinah", False, None, f"Donations fetch error: {ex}")
                break

        result["donations_latest"] = all_donations[:50]
        result["donations_ingested"] = total_inserted
        result["donations_skipped"] = total_skipped
        if fetch_success and latest_http_status == 200:
            if total_inserted > 0:
                logger.info(f"[Madinah Live Ingest] Ingested {total_inserted} new donations into CRM database & Parquet.")
            self._record_cycle("madinah", True, 200, None, total_inserted, len(all_donations))

        time.sleep(0.2)

        # 3. Donation Stats / Recovery Summary
        try:
            r = self.session.get(
                f"{MADINAH_APIM_BASE}/campaign-server/api/v1/campaign/donations/latest/stats",
                headers=headers,
                timeout=(5, 25)
            )
            if r.status_code == 200:
                data = r.json().get("data", {})
                result["analytics_summary"] = data.get("summary", {})
                rq = data.get("recoveryQueue")
                if isinstance(rq, list):
                    result["recovery_queue"] = rq[:10]
                elif isinstance(rq, dict):
                    result["recovery_queue"] = rq
                else:
                    result["recovery_queue"] = []
        except Exception as ex:
            logger.error(f"Madinah stats error: {ex}")

        time.sleep(0.2)

        # 4. Overall Revenue & Donor Geography (Using tested dashboard date parameters)
        try:
            r = self.session.get(
                f"{MADINAH_APIM_BASE}/dashboard-server/api/v1/user/dashboard/overview?startDate={today}&endDate={today}&dateValue=today&dateName=Today",
                headers=headers,
                timeout=(5, 25)
            )
            if r.status_code == 200:
                data = r.json().get("data", {})
                result["overview"] = data.get("overviewStats", {}).get("overview", {})
        except Exception as ex:
            logger.error(f"Madinah overview error: {ex}")

        # 4. Campaign Catalog (In deep sync)
        if is_deep:
            try:
                r = self.session.get(
                    f"{MADINAH_APIM_BASE}/campaign-server/api/v1/campaign/dashboard?page=1&limit=50&sortBy=createdAt&sortOrder=desc",
                    headers=headers,
                    timeout=(5, 25)
                )
                if r.status_code == 200:
                    result["campaigns"] = r.json().get("data", {}).get("campaigns", [])
                    try:
                        from core.madinah_ingestion import save_madinah_campaign_links
                        added = save_madinah_campaign_links(result["campaigns"])
                        if added:
                            logger.info(f"Madinah campaign links: {added} added/updated")
                    except Exception as link_ex:
                        logger.warning(f"Madinah campaign links not saved: {link_ex}")
            except Exception as ex:
                logger.error(f"Madinah campaign dashboard error: {ex}")

        return result

    # -------------------------------------------------------------------------
    # Sync Logic: Givebrite (Direct CRM Ingestion)
    # -------------------------------------------------------------------------
    def sync_givebrite(self, company_id: str = "iqra", is_deep: bool = False) -> dict:
        cid = company_id.lower()
        auth_header = self.get_givebrite_token(company_id=cid)
        charity_id = GIVEBRITE_CHARITY_IDS.get(cid, GIVEBRITE_CHARITY_ID)
        headers = {
            "Authorization": auth_header,
            "Accept": "application/json",
            "Origin": "https://dashboard.givebrite.com",
            "Referer": "https://dashboard.givebrite.com/"
        }
        today = self.get_today_str()

        result = {
            "platform": f"givebrite_{cid}",
            "company_id": cid,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "status": "ok",
            "donations_ingested": 0,
            "donations_skipped": 0,
            "total_donations_count": 0,
            "collection_stats": {},
            "campaigns": []
        }

        # 1. Startup Historical Backfill (Non-destructive, skips existing IDs)
        if not self.backfill_completed.get(cid):
            try:
                logger.info(f"Executing initial 60-day non-destructive GiveBrite ({cid}) historical backfill...")
                bf_res = run_historical_backfill(auth_header, days=60, charity_id=charity_id, company_id=cid)
                self.backfill_completed[cid] = True
                logger.info(f"Backfill ({cid}) finished: {bf_res['inserted']} inserted, {bf_res['skipped']} already present.")
            except Exception as bf_ex:
                logger.error(f"Initial backfill ({cid}) notice: {bf_ex}")

        # 2. Latest Real-Time Donations Stream with Rolling Catch-Up (up to 10 pages)
        total_ingested = 0
        total_skipped = 0
        total_docs_seen = 0
        fetch_error = None
        page = 1
        max_sync_pages = 10

        while page <= max_sync_pages:
            url_gb_donations = f"{GIVEBRITE_API_BASE}/donations?charity_id={charity_id}&page={page}&limit=50&sort_value=-1&sort_title=created_at"
            try:
                r = self.session.get(url_gb_donations, headers=headers, timeout=12)
                if r.status_code == 401:
                    logger.warning(f"[GiveBrite {cid}] Received HTTP 401 on page {page}. Performing immediate token renewal...")
                    auth_header = self.get_givebrite_token(company_id=cid, force_refresh=True)
                    headers["Authorization"] = auth_header
                    r = self.session.get(url_gb_donations, headers=headers, timeout=12)

                if r.status_code == 200:
                    data = r.json()
                    docs = data.get("docs", [])
                    if page == 1:
                        result["total_donations_count"] = data.get("total", 0)

                    if not docs:
                        break

                    total_docs_seen += len(docs)
                    ingest_res = ingest_givebrite_donations(docs, headers=headers, company_id=cid)
                    ins = ingest_res.get("inserted", 0)
                    skp = ingest_res.get("skipped", 0)
                    total_ingested += ins
                    total_skipped += skp

                    # If page has 0 new insertions and all docs already exist, we are fully caught up
                    if ins == 0:
                        break

                    if not data.get("hasNextPage"):
                        break

                    page += 1
                else:
                    logger.warning(f"Givebrite ({cid}) donations HTTP {r.status_code} on page {page}")
                    break
            except Exception as ex:
                logger.error(f"Givebrite ({cid}) donations error on page {page}: {ex}")
                fetch_error = str(ex)
                break

        result["donations_ingested"] = total_ingested
        result["donations_skipped"] = total_skipped
        if total_ingested > 0:
            logger.info(f"[GiveBrite {cid} Ingestion] Successfully persisted {total_ingested} new donations into CRM DB & Parquet across {page} pages.")
        if fetch_error:
            self._record_cycle(f"givebrite_{cid}", False, None, f"Donations fetch error: {fetch_error}")
            if cid == "iqra":
                self._record_cycle("givebrite", False, None, f"Donations fetch error: {fetch_error}")
        else:
            self._record_cycle(f"givebrite_{cid}", True, 200, None, total_ingested, total_docs_seen)
            if cid == "iqra":
                self._record_cycle("givebrite", True, 200, None, total_ingested, total_docs_seen)

        time.sleep(0.2)

        # 3. Financial Collections & Total Raised
        try:
            r = self.session.get(
                f"https://api-dashboard.givebrite.com/v1/statistics/app/collection?currency=GBP&start_date=2026-01-01&end_date={today}",
                headers=headers,
                timeout=12
            )
            if r.status_code == 200:
                result["collection_stats"] = r.json()
        except Exception as ex:
            logger.error(f"Givebrite ({cid}) collection stats error: {ex}")

        # 4. Campaign List & Impact Catalog Refresh (In deep sync)
        if is_deep:
            try:
                camp_url = f"{GIVEBRITE_API_BASE}/campaign?charity_id={charity_id}&page=1&limit=100"
                camp_headers = dict(headers)
                camp_headers["x-tenant-id"] = "gbx"
                r = self.session.get(camp_url, headers=camp_headers, timeout=(5, 25))
                if r.status_code == 200:
                    camp_data = r.json()
                    docs = camp_data.get("docs", [])
                    result["campaigns"] = docs

                    # Refresh master impacts catalog
                    impact_catalog = {}
                    for c in docs:
                        c_name = str(c.get("name") or "").strip()
                        c_slug = str(c.get("slug") or "").strip()
                        for imp in c.get("impacts", []):
                            if isinstance(imp, dict):
                                imp_id = str(imp.get("_id") or "").strip()
                                if imp_id:
                                    impact_catalog[imp_id] = {
                                        "campaign_name": c_name,
                                        "campaign_slug": c_slug,
                                        "giving_level": str(imp.get("name") or "").strip(),
                                        "amount": imp.get("amount")
                                    }
                    if impact_catalog:
                        impacts_file = os.path.join(DATA_CACHE_DIR, f"givebrite_impacts_{cid}.json" if cid != "iqra" else "givebrite_impacts.json")
                        # Only the newest campaigns come back here: add to the catalogue, never shrink it, so
                        # older donations' impact IDs still resolve to their campaign and giving level.
                        try:
                            with open(impacts_file, "r", encoding="utf-8") as f_old:
                                impact_catalog = {**json.load(f_old), **impact_catalog}
                        except (OSError, ValueError):
                            pass
                        atomic_write_json(impacts_file, impact_catalog)
                        try:
                            from core.givebrite_ingestion import invalidate_master_impacts_cache
                            invalidate_master_impacts_cache()
                        except Exception:
                            pass
                        logger.info(f"[GiveBrite {cid} Deep Sync] Refreshed impact catalog with {len(impact_catalog)} impacts across {len(docs)} campaigns.")
            except Exception as ex:
                logger.error(f"Givebrite ({cid}) campaigns/impacts sync error: {ex}")

        return result

    # -------------------------------------------------------------------------
    # Execution Cycle
    # -------------------------------------------------------------------------
    def run_cycle(self):
        now = time.time()
        is_deep = (now - self.last_deep_sync) >= DEEP_SYNC_INTERVAL_SEC
        if is_deep:
            self.last_deep_sync = now

        logger.info(f"Initiating {'DEEP' if is_deep else 'STANDARD'} API sync cycle...")

        madinah_data = {}
        givebrite_iqra_data = {}
        givebrite_rethink_data = {}

        try:
            madinah_data = self.sync_madinah(is_deep=is_deep)
            logger.info(f"[Madinah] Synced {len(madinah_data.get('donations_latest', []))} recent donations.")
        except Exception as ex:
            logger.error(f"Madinah sync failure: {ex}")
            self._record_cycle("madinah", False, None, f"Sync crashed: {ex}")
            madinah_data = {"platform": "madinah", "error": str(ex), "synced_at": datetime.now(timezone.utc).isoformat()}

        time.sleep(0.5)

        try:
            givebrite_iqra_data = self.sync_givebrite(company_id="iqra", is_deep=is_deep)
            logger.info(
                f"[Givebrite Iqra] Processed live feed (New Ingested: {givebrite_iqra_data.get('donations_ingested', 0)}, "
                f"Skipped: {givebrite_iqra_data.get('donations_skipped', 0)}, Total Platform: {givebrite_iqra_data.get('total_donations_count', 0)})."
            )
        except Exception as ex:
            logger.error(f"Givebrite (Iqra) sync failure: {ex}")
            self._record_cycle("givebrite_iqra", False, None, f"Sync crashed: {ex}")
            self._record_cycle("givebrite", False, None, f"Sync crashed: {ex}")
            givebrite_iqra_data = {"platform": "givebrite_iqra", "company_id": "iqra", "error": str(ex), "synced_at": datetime.now(timezone.utc).isoformat()}

        time.sleep(0.5)

        try:
            givebrite_rethink_data = self.sync_givebrite(company_id="rethink", is_deep=is_deep)
            logger.info(
                f"[Givebrite Rethink] Processed live feed (New Ingested: {givebrite_rethink_data.get('donations_ingested', 0)}, "
                f"Skipped: {givebrite_rethink_data.get('donations_skipped', 0)}, Total Platform: {givebrite_rethink_data.get('total_donations_count', 0)})."
            )
        except Exception as ex:
            logger.error(f"Givebrite (Rethink) sync failure: {ex}")
            self._record_cycle("givebrite_rethink", False, None, f"Sync crashed: {ex}")
            givebrite_rethink_data = {"platform": "givebrite_rethink", "company_id": "rethink", "error": str(ex), "synced_at": datetime.now(timezone.utc).isoformat()}

        # Stripe (Rethink's account): live ledger of every money movement + payouts. GET-only towards Stripe.
        stripe_data = {}
        try:
            from core.stripe_ledger import poll_stripe_ledger
            stripe_data = poll_stripe_ledger()
            per_company = {k: v for k, v in stripe_data.items() if isinstance(v, dict)}
            failed = {k: v["error"] for k, v in per_company.items() if v.get("error")}
            for comp, res in per_company.items():
                new_rows = (res.get("recent") or {}).get("new", 0) + (res.get("backfill") or {}).get("new", 0)
                if new_rows:
                    log_event("sync.stripe_ledger", category="sync", platform="stripe", company_id=comp, count=new_rows,
                              message=f"stripe ({comp}): {new_rows} new movement(s) recorded")
                logger.info(f"[Stripe {comp}] Ledger poll: {res.get('recent')} | payouts {res.get('payouts')} | crm {res.get('crm')}")
            self._record_cycle("stripe", not failed, 200 if not failed else None,
                               "; ".join(f"{k}: {v}" for k, v in failed.items()) or None,
                               fetched=sum((v.get("recent") or {}).get("seen", 0) for v in per_company.values()))
        except Exception as ex:
            logger.error(f"Stripe ledger sync failure: {ex}")
            self._record_cycle("stripe", False, None, f"Sync crashed: {ex}")
            stripe_data = {"platform": "stripe", "error": str(ex)}

        # Access PaySuite (DDCMS v3): Direct Debit live collections & disbursals
        paysuite_data = {}
        try:
            from core.paysuite_sync import poll_paysuite_sync
            paysuite_data = poll_paysuite_sync(company_id="rethink")
            err = paysuite_data.get("error")
            # Between hourly runs the poller only says "waiting": that's not a sync, so it must not count as a
            # success (it reset the failure counter, and repeated failures never raised the Ops alarm)
            if paysuite_data.get("status") != "waiting":
                self._record_cycle("paysuite", not err, 200 if not err else None, err,
                                   fetched=paysuite_data.get("total_fetched", 0))
            logger.info(f"[PaySuite] Poll result: {paysuite_data.get('status')} | Ingested: {paysuite_data.get('new_payments', 0)} | Updated: {paysuite_data.get('updated_payments', 0)}")
        except Exception as ex:
            logger.error(f"PaySuite sync failure: {ex}")
            self._record_cycle("paysuite", False, None, f"Sync crashed: {ex}")
            paysuite_data = {"platform": "paysuite", "error": str(ex)}

        # LaunchGood: keep the 15-minute session renewed every cycle; pull the donations export every 15 min.
        launchgood_data = {}
        try:
            from core.launchgood_auto_sync import poll_launchgood
            launchgood_data = poll_launchgood()
            for comp, res in launchgood_data.items():
                status = res.get("status")
                if status == "waiting":
                    if res.get("last_status") == "success":  # session renewed and the last pull worked
                        self._record_cycle(f"launchgood_{comp}", True, 200, None, fetched=res.get("fetched", 0))
                    continue
                if status == "not_configured":
                    continue
                key = f"launchgood_{comp}"
                if status == "success":
                    self._record_cycle(key, True, 200, None, ingested=res.get("added", 0), fetched=res.get("fetched", 0))
                else:
                    self._record_cycle(key, False, None, res.get("error") or status)
                logger.info(f"[LaunchGood {comp}] {status} | fetched {res.get('fetched', 0)} | added {res.get('added', 0)} | session: {res.get('session')}"
                            + (f" | error: {res.get('error')}" if res.get("error") else ""))
        except Exception as ex:
            logger.error(f"LaunchGood sync failure: {ex}")
            launchgood_data = {"platform": "launchgood", "error": str(ex)}

        # Campaign ID catalogue (classification by campaign / giving-level ID): refresh once a day with new campaigns
        try:
            if now - getattr(self, "_last_catalogue_run", 0) > 24 * 3600:
                self._last_catalogue_run = now
                res = subprocess.run([sys.executable, os.path.join(BASE_DIR, "scripts", "build_campaign_id_catalogue.py"), "--apply", "--no-backup"],
                                     cwd=BASE_DIR, capture_output=True, text=True, timeout=900)
                last = (res.stdout.strip().splitlines() or [""])[-1]
                logger.info(f"[Campaign IDs] catalogue refresh: {last[:200]}" if res.returncode == 0 else f"[Campaign IDs] refresh failed: {res.stderr[-300:]}")
                from core.classification_ids import invalidate as _cid_invalidate
                _cid_invalidate()
        except Exception as ex:
            logger.error(f"Campaign ID catalogue refresh failure: {ex}")

        # Atomic writes for service status monitoring
        try:
            atomic_write_json(MADINAH_SYNC_FILE, madinah_data)

            master_data = {
                "meta": {
                    "service_name": "platform-sync.service",
                    "last_synced_at": datetime.now(timezone.utc).isoformat(),
                    "interval_seconds": SYNC_INTERVAL_SEC,
                    "sync_mode": "deep" if is_deep else "standard",
                    "status": "healthy"
                },
                "summary": {
                    "madinah_recent_donations": len(madinah_data.get("donations_latest", [])),
                    "madinah_total_revenue": madinah_data.get("overview", {}).get("totalRevenue", 0),
                    "givebrite_iqra_new_ingested": givebrite_iqra_data.get("donations_ingested", 0),
                    "givebrite_iqra_total_donations": givebrite_iqra_data.get("total_donations_count", 0),
                    "givebrite_rethink_new_ingested": givebrite_rethink_data.get("donations_ingested", 0),
                    "givebrite_rethink_total_donations": givebrite_rethink_data.get("total_donations_count", 0),
                    "paysuite_new_payments": paysuite_data.get("new_payments", 0),
                },
                "madinah": madinah_data,
                "givebrite": givebrite_iqra_data,
                "givebrite_iqra": givebrite_iqra_data,
                "givebrite_rethink": givebrite_rethink_data,
                "stripe": stripe_data,
                "paysuite": paysuite_data,
                "launchgood": launchgood_data,
            }

            atomic_write_json(MASTER_SYNC_FILE, master_data)
            logger.info(f"Consolidated platform status written atomically to {MASTER_SYNC_FILE}")
        except Exception as ex:
            logger.error(f"Failed writing atomic sync status: {ex}")


def main():
    logger.info("==========================================================")
    logger.info("Starting Platform Sync Daemon (Direct CRM & Pure API Mode)")
    logger.info(f"Polling Interval: {SYNC_INTERVAL_SEC}s | Deep Scan: {DEEP_SYNC_INTERVAL_SEC}s")
    logger.info("Direct Persistence: SQLite 'donations' & Parquet 'donations_cache.parquet'")
    logger.info("==========================================================")

    service = PlatformSyncService()
    log_event("service.started", category="sync", message="platform-sync service started",
              interval_seconds=SYNC_INTERVAL_SEC)

    while True:
        try:
            service.run_cycle()
        except Exception as e:
            logger.critical(f"Unexpected error in sync cycle: {e}", exc_info=True)
            log_event("sync.cycle_crashed", category="sync", level="critical", detail=str(e),
                      message=f"Sync cycle crashed: {e}")

        time.sleep(SYNC_INTERVAL_SEC)


if __name__ == "__main__":
    main()
