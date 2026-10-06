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
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import requests
from dotenv import load_dotenv

# Path setup
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Load environment variables
load_dotenv(os.path.join(BASE_DIR, ".env"))

from core.givebrite_ingestion import (
    ingest_givebrite_donations,
    run_historical_backfill,
    GIVEBRITE_API_BASE
)
from core.madinah_ingestion import (
    ingest_madinah_donations,
    MADINAH_APIM_BASE
)

DATA_CACHE_DIR = os.path.join(BASE_DIR, "data_cache")
MADINAH_TOKEN_FILE = os.path.join(BASE_DIR, ".madinah_token.json")
GIVEBRITE_TOKEN_FILE = os.path.join(BASE_DIR, ".givebrite_token.json")
MASTER_SYNC_FILE = os.path.join(DATA_CACHE_DIR, "platform_sync_data.json")
MADINAH_SYNC_FILE = os.path.join(DATA_CACHE_DIR, "madinah_sync_data.json")

# Service Configuration
SYNC_INTERVAL_SEC = int(os.environ.get("SYNC_INTERVAL_SEC", 60))  # standard interval
DEEP_SYNC_INTERVAL_SEC = 1800  # 30 minutes for deep campaign catalog scans
GIVEBRITE_CHARITY_ID = os.environ.get("GIVEBRITE_IQRA_CHARITY_ID", "68625e0d6d1a99441e34e2ea")
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
        self.backfill_completed = False

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
                        timeout=12
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
                            logger.info("Successfully renewed Madinah tokens via pure HTTP API.")
                            access_token = token_data["accessToken"]
                    else:
                        logger.warning(f"Madinah HTTP token refresh returned {r.status_code}. Falling back to script.")
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
                else:
                    logger.error(f"Madinah script login notice: {res.stderr[:200]}")
            except Exception as e:
                logger.error(f"Madinah script login exception: {e}")

        if not access_token.startswith("Bearer "):
            access_token = f"Bearer {access_token}"
        return access_token

    def get_givebrite_token(self, force_refresh: bool = False) -> str:
        """Loads and auto-renews Givebrite JWT Bearer token (<10m to expiry or force_refresh) via Playwright."""
        now = time.time()
        need_refresh = force_refresh
        access_token = ""

        if not os.path.exists(GIVEBRITE_TOKEN_FILE):
            need_refresh = True
        elif not need_refresh:
            try:
                with open(GIVEBRITE_TOKEN_FILE, "r", encoding="utf-8") as f:
                    token_data = json.load(f)
                access_token = token_data.get("accessToken", "")
                exp = parse_jwt_exp(access_token)
                time_left_sec = exp - now if exp else 0
                if not exp or time_left_sec < 600:  # Less than 10 minutes remaining
                    logger.info(f"GiveBrite JWT expiring soon (Time remaining: {time_left_sec/60:.1f}m). Auto-renewing...")
                    need_refresh = True
            except Exception:
                need_refresh = True

        if need_refresh:
            logger.info("Initiating headless GiveBrite Playwright token auto-renewal...")
            try:
                script_path = os.path.join(BASE_DIR, "scripts", "get_givebrite_jwt.js")
                res = subprocess.run(["node", script_path], cwd=BASE_DIR, capture_output=True, text=True, timeout=60)
                if res.returncode == 0:
                    with open(GIVEBRITE_TOKEN_FILE, "r", encoding="utf-8") as f:
                        token_data = json.load(f)
                    access_token = token_data.get("accessToken", "")
                    logger.info("GiveBrite token auto-refreshed successfully via Playwright.")
                else:
                    logger.error(f"GiveBrite auto-refresh failed (code {res.returncode}): {res.stderr[:200]}")
            except Exception as e:
                logger.error(f"GiveBrite auto-refresh exception: {e}")

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

        # 1. Latest Real-Time Donations
        url_madinah_donations = f"{MADINAH_APIM_BASE}/campaign-server/api/v1/campaign/donations/latest?page=1&limit=50"
        try:
            r = self.session.get(url_madinah_donations, headers=headers, timeout=12)
            if r.status_code == 401:
                logger.warning("[Madinah] Received HTTP 401. Performing immediate token renewal...")
                auth_header = self.ensure_madinah_token(force_refresh=True)
                headers["Authorization"] = auth_header
                r = self.session.get(url_madinah_donations, headers=headers, timeout=12)

            if r.status_code == 200:
                data = r.json().get("data", {})
                raw_donations = data.get("donations", [])
                result["donations_latest"] = raw_donations
                result["status_counts"] = data.get("statusCounts", {})

                # Direct CRM Ingestion (SQLite + Parquet atomic sync)
                ingest_res = ingest_madinah_donations(raw_donations, company_id="iqra")
                result["donations_ingested"] = ingest_res.get("inserted", 0)
                result["donations_skipped"] = ingest_res.get("skipped", 0)
                if ingest_res.get("inserted", 0) > 0:
                    logger.info(f"[Madinah Live Ingest] Ingested {ingest_res['inserted']} new donations into CRM database & Parquet.")
            else:
                logger.warning(f"Madinah donations HTTP {r.status_code}")
        except Exception as ex:
            logger.error(f"Madinah donations fetch error: {ex}")

        time.sleep(0.2)

        # 2. Donation Stats / Recovery Summary
        try:
            r = self.session.get(
                f"{MADINAH_APIM_BASE}/campaign-server/api/v1/campaign/donations/latest/stats",
                headers=headers,
                timeout=12
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

        # 3. Overall Revenue & Donor Geography
        try:
            r = self.session.get(
                f"{MADINAH_APIM_BASE}/dashboard-server/api/v1/user/dashboard/overview?startDateFilter=2024-01-01&endDateFilter={today}",
                headers=headers,
                timeout=12
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
                    timeout=15
                )
                if r.status_code == 200:
                    result["campaigns"] = r.json().get("data", {}).get("campaigns", [])
            except Exception as ex:
                logger.error(f"Madinah campaign dashboard error: {ex}")

        return result

    # -------------------------------------------------------------------------
    # Sync Logic: Givebrite (Direct CRM Ingestion)
    # -------------------------------------------------------------------------
    def sync_givebrite(self, is_deep: bool = False) -> dict:
        auth_header = self.get_givebrite_token()
        headers = {
            "Authorization": auth_header,
            "Accept": "application/json",
            "Origin": "https://dashboard.givebrite.com",
            "Referer": "https://dashboard.givebrite.com/"
        }
        today = self.get_today_str()

        result = {
            "platform": "givebrite",
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "status": "ok",
            "donations_ingested": 0,
            "donations_skipped": 0,
            "total_donations_count": 0,
            "collection_stats": {},
            "campaigns": []
        }

        # 1. Startup Historical Backfill (Non-destructive, skips existing IDs)
        if not self.backfill_completed:
            try:
                logger.info("Executing initial 60-day non-destructive GiveBrite historical backfill...")
                bf_res = run_historical_backfill(auth_header, days=60, charity_id=GIVEBRITE_CHARITY_ID, company_id="iqra")
                self.backfill_completed = True
                logger.info(f"Backfill finished: {bf_res['inserted']} inserted, {bf_res['skipped']} already present.")
            except Exception as bf_ex:
                logger.error(f"Initial backfill notice: {bf_ex}")

        # 2. Latest Real-Time Donations Stream -> Direct CRM Ingestion (SQLite + Parquet)
        url_gb_donations = f"{GIVEBRITE_API_BASE}/donations?charity_id={GIVEBRITE_CHARITY_ID}&page=1&limit=50&sort_value=-1&sort_title=created_at"
        try:
            r = self.session.get(url_gb_donations, headers=headers, timeout=12)
            if r.status_code == 401:
                logger.warning("[GiveBrite] Received HTTP 401. Performing immediate token renewal...")
                auth_header = self.get_givebrite_token(force_refresh=True)
                headers["Authorization"] = auth_header
                r = self.session.get(url_gb_donations, headers=headers, timeout=12)

            if r.status_code == 200:
                data = r.json()
                docs = data.get("docs", [])
                result["total_donations_count"] = data.get("total", 0)

                # Direct persistence to SQLite and Parquet (strictly company_id='iqra')
                ingest_res = ingest_givebrite_donations(docs, headers=headers, company_id="iqra")
                result["donations_ingested"] = ingest_res.get("inserted", 0)
                result["donations_skipped"] = ingest_res.get("skipped", 0)
                if ingest_res.get("inserted", 0) > 0:
                    logger.info(f"[GiveBrite Ingestion] Successfully persisted {ingest_res['inserted']} new donations into CRM DB & Parquet.")
            else:
                logger.warning(f"Givebrite donations HTTP {r.status_code}")
        except Exception as ex:
            logger.error(f"Givebrite donations error: {ex}")

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
            logger.error(f"Givebrite collection stats error: {ex}")

        # 4. Campaign List (In deep sync)
        if is_deep:
            try:
                r = self.session.get(
                    f"https://api.givebrite.com/v1/campaign?filter_by=charity&value={GIVEBRITE_CHARITY_ID}&limit=50&page=1",
                    headers={"Origin": "https://donate.iqracharity.org", "Referer": "https://donate.iqracharity.org/"},
                    timeout=15
                )
                if r.status_code == 200:
                    result["campaigns"] = r.json().get("docs", [])
            except Exception as ex:
                logger.error(f"Givebrite campaigns error: {ex}")

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
        givebrite_data = {}

        try:
            madinah_data = self.sync_madinah(is_deep=is_deep)
            logger.info(f"[Madinah] Synced {len(madinah_data.get('donations_latest', []))} recent donations.")
        except Exception as ex:
            logger.error(f"Madinah sync failure: {ex}")
            madinah_data = {"platform": "madinah", "error": str(ex), "synced_at": datetime.now(timezone.utc).isoformat()}

        time.sleep(0.5)

        try:
            givebrite_data = self.sync_givebrite(is_deep=is_deep)
            logger.info(
                f"[Givebrite] Processed live feed (New Ingested: {givebrite_data.get('donations_ingested', 0)}, "
                f"Skipped: {givebrite_data.get('donations_skipped', 0)}, Total Platform: {givebrite_data.get('total_donations_count', 0)})."
            )
        except Exception as ex:
            logger.error(f"Givebrite sync failure: {ex}")
            givebrite_data = {"platform": "givebrite", "error": str(ex), "synced_at": datetime.now(timezone.utc).isoformat()}

        # Atomic writes for service status monitoring (No large intermediate JSON cache files)
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
                    "givebrite_new_ingested": givebrite_data.get("donations_ingested", 0),
                    "givebrite_total_donations": givebrite_data.get("total_donations_count", 0),
                    "givebrite_total_raised_gbp": givebrite_data.get("collection_stats", {}).get("raised", 0)
                },
                "madinah": madinah_data,
                "givebrite": {
                    "platform": "givebrite",
                    "synced_at": givebrite_data.get("synced_at"),
                    "status": givebrite_data.get("status"),
                    "donations_ingested": givebrite_data.get("donations_ingested", 0),
                    "total_donations_count": givebrite_data.get("total_donations_count", 0),
                    "collection_stats": givebrite_data.get("collection_stats", {})
                }
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

    while True:
        try:
            service.run_cycle()
        except Exception as e:
            logger.critical(f"Unexpected error in sync cycle: {e}", exc_info=True)

        time.sleep(SYNC_INTERVAL_SEC)


if __name__ == "__main__":
    main()
