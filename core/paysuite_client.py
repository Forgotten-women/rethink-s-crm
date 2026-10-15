"""
Access PaySuite (DDCMS v3) Read-Only API Client.

Connects to Access PaySuite BACS Direct Debit Management System REST API.
Enforces a strict READ-ONLY allow-list: only GET requests and the read-only POST search
endpoint (/client/{clientCode}/payments) are permitted. Any other method/endpoint raises.

Credentials (configured in .env):
  ACCESSPAYSUITE_BASE_URL    - default: https://ddcms.accesspaysuite.com/api/v3
  ACCESSPAYSUITE_CLIENT_CODE - default: REC
  ACCESSPAYSUITE_API_KEY     - API key header
"""
import logging
import os
import time
from typing import Any, Dict, Generator, List, Optional
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

logger = logging.getLogger("paysuite_client")

DEFAULT_BASE_URL = "https://ddcms.accesspaysuite.com/api/v3"
DEFAULT_CLIENT_CODE = "REC"
# Cloudflare-safe User-Agent (Cloudflare blocks generic python/urllib with Error 1010)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 (RethinkCRM/1.0)"

# Strict allow-list of paths/methods allowed in read-only mode
ALLOWED_READ_ENDPOINTS = {
    ("GET", "/info"),
    ("GET", "/schedules"),
    ("GET", "/paymentdate"),
    ("GET", "/customer"),          # Prefix match for /customer/{id} and /customer/{id}/contract
    ("POST", "/payments"),         # Search/query endpoint only
}


class PaySuiteSecurityError(RuntimeError):
    """Raised when an attempt is made to call a non-allowlisted or write endpoint."""
    pass


class PaySuiteAPIError(RuntimeError):
    """Raised when the Access PaySuite API returns an error."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class PaySuiteClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        client_code: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        self.base_url = (base_url or os.environ.get("ACCESSPAYSUITE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.client_code = (client_code or os.environ.get("ACCESSPAYSUITE_CLIENT_CODE") or DEFAULT_CLIENT_CODE).strip().upper()
        self.api_key = (api_key or os.environ.get("ACCESSPAYSUITE_API_KEY") or "").strip()
        self.timeout = timeout
        self.max_retries = max_retries

        if not self.api_key:
            logger.warning("[PaySuite] ACCESSPAYSUITE_API_KEY is not set or empty in environment.")

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "apiKey": self.api_key,
        })

    def is_configured(self) -> bool:
        return bool(self.api_key and self.client_code)

    def _validate_allowlist(self, method: str, subpath: str) -> None:
        """Enforces that only permitted read-only endpoints can be invoked."""
        method_up = method.upper()
        clean_subpath = subpath if subpath.startswith("/") else f"/{subpath}"

        for allowed_method, allowed_path in ALLOWED_READ_ENDPOINTS:
            if method_up == allowed_method:
                if clean_subpath == allowed_path or clean_subpath.startswith(f"{allowed_path}/"):
                    return

        raise PaySuiteSecurityError(
            f"PaySuite client blocked disallowed call: {method_up} {clean_subpath}. "
            f"Only read-only queries are permitted by policy."
        )

    def _request(self, method: str, subpath: str, params: Optional[Dict[str, Any]] = None, json_body: Optional[Dict[str, Any]] = None) -> Any:
        if not self.is_configured():
            raise PaySuiteAPIError("Access PaySuite is not configured (missing API key or client code).")

        self._validate_allowlist(method, subpath)

        clean_subpath = subpath.lstrip("/")
        url = f"{self.base_url}/client/{self.client_code}/{clean_subpath}"

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_body,
                    timeout=self.timeout
                )

                # Retry on rate limiting or transient server errors
                if resp.status_code in (429, 502, 503, 504) and attempt < self.max_retries:
                    sleep_sec = 1.5 * attempt
                    logger.warning(f"[PaySuite] Request to {clean_subpath} returned {resp.status_code}. Retrying in {sleep_sec}s (attempt {attempt}/{self.max_retries})...")
                    time.sleep(sleep_sec)
                    continue

                if resp.status_code == 404:
                    return None

                if not (200 <= resp.status_code < 300):
                    err_msg = f"PaySuite {method} {clean_subpath} failed ({resp.status_code}): {resp.text[:250]}"
                    raise PaySuiteAPIError(err_msg, status_code=resp.status_code, response_body=resp.text[:500])

                return resp.json() if resp.text.strip() else {}

            except requests.RequestException as req_err:
                if attempt < self.max_retries:
                    sleep_sec = 1.0 * attempt
                    logger.warning(f"[PaySuite] Network error on {clean_subpath}: {req_err}. Retrying in {sleep_sec}s...")
                    time.sleep(sleep_sec)
                    continue
                raise PaySuiteAPIError(f"PaySuite connection failed after {self.max_retries} attempts: {req_err}")

    # -------------------------------------------------------------------------
    # Public Read-Only API Endpoints
    # -------------------------------------------------------------------------

    def get_client_info(self) -> Dict[str, Any]:
        """GET /client/{clientCode}/info - live health check & configuration."""
        return self._request("GET", "/info") or {}

    def get_schedules(self) -> List[Dict[str, Any]]:
        """GET /client/{clientCode}/schedules - returns all collection schedules."""
        res = self._request("GET", "/schedules")
        if isinstance(res, list):
            return res
        if isinstance(res, dict) and "Schedules" in res:
            return res["Schedules"]
        return []

    def get_payment_dates(self) -> Dict[str, Any]:
        """GET /client/{clientCode}/paymentdate - earliest valid collection dates."""
        return self._request("GET", "/paymentdate") or {}

    def get_customer(self, customer_id: str) -> Optional[Dict[str, Any]]:
        """GET /client/{clientCode}/customer/{customerId} - donor KYC details."""
        if not customer_id:
            return None
        return self._request("GET", f"/customer/{customer_id}")

    def get_customer_contracts(self, customer_id: str) -> List[Dict[str, Any]]:
        """GET /client/{clientCode}/customer/{customerId}/contract - mandate & Gift Aid status."""
        if not customer_id:
            return []
        res = self._request("GET", f"/customer/{customer_id}/contract")
        if isinstance(res, dict) and "Contracts" in res:
            return res["Contracts"]
        if isinstance(res, list):
            return res
        return []

    def search_payments(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        POST /client/{clientCode}/payments - read-only search.
        Verified against the live API (15 Oct 2026): the body takes PageNumber / PageSize / CollectionDateFrom /
        CollectionDateTo ("Page", "Limit" and "FromDate" are silently ignored) and the reply is
        {"Pagination": {Page, PageSize, TotalPages, TotalRecords}, "Data": [payments]}.
        Returned as {"TotalPages", "TotalRecords", "Page", "Payments"}.
        """
        body: Dict[str, Any] = {
            "PageNumber": max(1, int(page)),
            "PageSize": max(1, min(100, int(limit))),
        }
        if from_date:
            body["CollectionDateFrom"] = from_date
        if to_date:
            body["CollectionDateTo"] = to_date
        if status:
            body["Status"] = status

        res = self._request("POST", "/payments", json_body=body) or {}
        pagination = res.get("Pagination") or {}
        return {
            "TotalPages": int(pagination.get("TotalPages") or res.get("TotalPages") or 0),
            "TotalRecords": int(pagination.get("TotalRecords") or res.get("TotalRecords") or 0),
            "Page": int(pagination.get("Page") or page),
            "Payments": res.get("Data") if res.get("Data") is not None else (res.get("Payments") or []),
        }

    def iter_all_payments(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        status: Optional[str] = None,
        page_size: int = 100,
        max_pages: Optional[int] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Yields every payment collected between from_date and to_date (default: today), each exactly once.

        The search has no stable sort order: paging through 898 records returned 40 twice and silently
        skipped 40 others. So the range is fetched in date windows small enough to come back in ONE page
        (a window that holds more is split in half), and each window must return as many distinct records
        as its TotalRecords says, or this raises rather than handing back a partial ledger.
        max_pages caps the number of API calls (testing).
        """
        from datetime import date, timedelta

        start = date.fromisoformat((from_date or "2000-01-01")[:10])
        end = date.fromisoformat(to_date[:10]) if to_date else date.today() + timedelta(days=31)
        size = max(1, min(100, int(page_size)))
        calls = 0
        seen = set()

        windows = []
        cursor = start
        while cursor <= end:  # calendar months first
            month_end = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            windows.append((cursor, min(month_end, end)))
            cursor = month_end + timedelta(days=1)

        while windows:
            w_from, w_to = windows.pop(0)
            if max_pages and calls >= max_pages:
                break
            data = self.search_payments(from_date=w_from.isoformat(), to_date=w_to.isoformat(),
                                        status=status, page=1, limit=size)
            calls += 1
            total = data["TotalRecords"]
            if total > size:
                if w_from == w_to:
                    raise PaySuiteAPIError(f"PaySuite: {total} payments on {w_from} exceed one page of {size}")
                mid = w_from + (w_to - w_from) // 2
                windows[:0] = [(w_from, mid), (mid + timedelta(days=1), w_to)]
                continue
            batch = {p.get("Id"): p for p in data["Payments"] if p.get("Id")}
            if len(batch) != total:
                raise PaySuiteAPIError(f"PaySuite {w_from}..{w_to}: {len(batch)} distinct payments returned, {total} expected")
            for pid, p in batch.items():
                if pid not in seen:
                    seen.add(pid)
                    yield p


# Default module-level client singleton
_client_instance: Optional[PaySuiteClient] = None

def get_paysuite_client() -> PaySuiteClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = PaySuiteClient()
    return _client_instance
