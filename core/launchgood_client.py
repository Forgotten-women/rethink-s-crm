"""
LaunchGood API Client
---------------------
100% Read-Only API client for LaunchGood v4:
  * User & subaccount discovery: POST /api/user/currentUser
  * Financial transfers & payouts: POST /api/account/transfers
  * Asynchronous report generation & donor stream: POST /api/reports/v4_reports
  * Campaign search: GET https://search.launchgood.com/v2/production

Enforces strict charity isolation: every instance is scoped to a specific charity (e.g. 'rethink' or 'iqra').
"""
import io
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
import requests

from core.launchgood_accounts import get_account_config, get_account_id, get_session, is_connected

logger = logging.getLogger("launchgood_client")

API_BASE = os.environ.get("LAUNCHGOOD_API_BASE", "https://www.launchgood.com/api")
SEARCH_API_BASE = os.environ.get("LAUNCHGOOD_SEARCH_API_BASE", "https://search.launchgood.com")


class LaunchGoodClient:
    def __init__(self, company_id: str = "rethink", timeout: int = 30):
        self.company_id = str(company_id or "rethink").strip().lower()
        self.timeout = timeout
        self.account_config = get_account_config(self.company_id)
        self.account_id = get_account_id(self.company_id)
        self._session_data = get_session(self.company_id)

    def is_configured(self) -> bool:
        if not self._session_data:
            return False
        return bool(
            self._session_data.get("bearerToken")
            or self._session_data.get("accessToken")
            or self._session_data.get("headers")
        )

    def _get_headers(self) -> Dict[str, str]:
        if not self.is_configured():
            raise RuntimeError(f"LaunchGood is not connected for charity '{self.company_id}'. Please configure session tokens.")
        
        headers = dict(self._session_data.get("headers", {}))
        bearer = str(
            self._session_data.get("bearerToken")
            or self._session_data.get("accessToken")
            or headers.get("authorization")
            or headers.get("Authorization")
            or ""
        ).strip()

        if bearer:
            auth_val = bearer if bearer.startswith("Bearer ") else f"Bearer {bearer}"
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}
            headers["Authorization"] = auth_val

        cookie_val = (
            self._session_data.get("rawCookie")
            or self._session_data.get("cookie")
            or headers.get("cookie")
            or headers.get("Cookie")
        )
        if not cookie_val and self._session_data.get("cookies"):
            cookie_val = "; ".join(f"{c['name']}={c.get('value', '')}" for c in self._session_data["cookies"] if isinstance(c, dict) and c.get("name"))
        if cookie_val:
            headers = {k: v for k, v in headers.items() if k.lower() != "cookie"}
            headers["Cookie"] = cookie_val

        # Standard browser headers required by Cloudflare WAF
        headers.setdefault("Accept", "application/json, text/plain, */*")
        headers.setdefault("Origin", "https://www.launchgood.com")
        headers.setdefault("Referer", "https://www.launchgood.com/v4/fundraising/dashboard")
        headers.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        return headers

    def get_current_user(self) -> Dict[str, Any]:
        """Calls /api/user/currentUser to verify authentication and fetch corporate subaccounts."""
        url = f"{API_BASE}/user/currentUser"
        r = requests.post(url, headers=self._get_headers(), json={}, timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"LaunchGood /user/currentUser failed ({r.status_code}): {r.text[:200]}")
        return r.json()

    def get_account_transfers(self, account_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Fetches all bank payout transfer batches and constituent campaign breakdowns
        for the charity's account from POST /api/account/transfers.
        """
        target_account = account_id or self.account_id
        if not target_account:
            raise ValueError(f"No LaunchGood account ID configured for '{self.company_id}'.")

        url = f"{API_BASE}/account/transfers"
        payload = {"account_id": target_account}
        logger.info(f"Fetching LaunchGood transfers for {self.company_id} (Account: {target_account})...")

        r = requests.post(url, headers=self._get_headers(), json=payload, timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"LaunchGood /account/transfers failed ({r.status_code}): {r.text[:200]}")

        data = r.json()
        transfers_list = []
        res = data.get("result", {})
        if "transfers" in res and isinstance(res["transfers"], list):
            for group in res["transfers"]:
                if "transfers" in group and isinstance(group["transfers"], list):
                    transfers_list.extend(group["transfers"])

        logger.info(f"Retrieved {len(transfers_list)} transfer batches from LaunchGood for {self.company_id}.")
        return transfers_list

    def create_donors_report(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        settled_donations: bool = True
    ) -> Dict[str, Any]:
        """
        Initiates an asynchronous donor export report on LaunchGood:
        POST /api/reports/v4_reports (type: 'account_donors', fmt: 'csv')
        """
        target_account = self.account_id
        if not target_account:
            raise ValueError(f"No LaunchGood account ID configured for '{self.company_id}'.")

        url = f"{API_BASE}/reports/v4_reports"
        payload = {
            "account_id": str(target_account),
            "type": "account_donors",
            "fmt": "csv",
            "settled_donations": settled_donations
        }
        if start_date:
            payload["start"] = start_date
        if end_date:
            payload["end"] = end_date

        r = requests.post(url, headers=self._get_headers(), json=payload, timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"LaunchGood report creation failed ({r.status_code}): {r.text[:200]}")
        return r.json()

    def generate_report(self, identifier: str) -> Dict[str, Any]:
        """Triggers the compilation of an initiated report: POST /api/reports/action (verb: 'generate')."""
        url = f"{API_BASE}/reports/action"
        payload = {
            "verb": "generate",
            "format": "csv",
            "identifier": identifier
        }
        r = requests.post(url, headers=self._get_headers(), json=payload, timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"LaunchGood report generation failed ({r.status_code}): {r.text[:200]}")
        return r.json()

    def download_report_csv(self, identifier: str) -> str:
        """Downloads the compiled CSV text for a completed report."""
        url = f"{API_BASE}/reports/action"
        payload = {
            "verb": "download",
            "identifier": identifier
        }
        r = requests.post(url, headers=self._get_headers(), json=payload, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"LaunchGood report download failed ({r.status_code}): {r.text[:200]}")
        return r.text

    def search_campaigns(self, query: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        """Queries LaunchGood OpenSearch index for campaign stats, targets, and giving level tiers."""
        url = f"{SEARCH_API_BASE}/v2/production"
        params = {"q": query or "*", "size": limit}
        if self.account_id:
            params["account_id"] = self.account_id

        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        return (data.get("hits") or {}).get("hits", [])
