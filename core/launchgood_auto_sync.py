"""
Automatic LaunchGood donation sync (run by the platform sync service).

Every LAUNCHGOOD_SYNC_INTERVAL_SEC: renew the session if needed -> ask LaunchGood for the account's donations
report for the last few days (the same export as the "account_donations ... .xlsx" files uploaded by hand) ->
keep only donations whose Donation ID this charity doesn't have yet -> add them through the normal upload path
(process_and_upload_excel, merge mode: insert-only, charity-isolated, classified like a manual upload).

Nothing is added unless the export has the real LaunchGood columns, so a changed/odd report can't write junk.
"""
import io
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pandas as pd
import requests

from core.launchgood_session import ensure_fresh_session, session_state

logger = logging.getLogger("launchgood_auto_sync")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "launchgood_donations.db")
STATE_FILE = os.path.join(BASE_DIR, "data_cache", "launchgood_auto_sync.json")
SYNC_INTERVAL_SEC = int(os.environ.get("LAUNCHGOOD_SYNC_INTERVAL_SEC", "900"))
DAYS_BACK = int(os.environ.get("LAUNCHGOOD_SYNC_DAYS_BACK", "10"))
# The hand-uploaded files are "account_donations_<account>_for_..." exports; older code asked for "account_donors"
REPORT_TYPES = [t.strip() for t in os.environ.get("LAUNCHGOOD_REPORT_TYPES", "account_donors").split(",") if t.strip()]
REQUIRED_COLS = {"Donation ID", "Created Date (UTC)", "Total Online Donation Gross Amount in Settled Currency"}
GUEST_ONLY_KEYS = {"application", "country-code", "environment", "ip-state-code", "is-country-eu", "payment-provider-keys",
                   "payment-provider-modes", "payment-provider-types", "profile-is-opt-in", "recaptcha-boolean",
                   "sentry-enabled", "sentry-release", "sentry-tracking", "supported-currencies"}
USER_KEYS = ("id", "userId", "user_id", "email", "user", "firstName", "first_name", "name", "accounts")


def _load_state() -> Dict[str, Any]:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = f"{STATE_FILE}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp, STATE_FILE)


def signed_in(info: Dict[str, Any]) -> bool:
    res = (info or {}).get("result") or {}
    return isinstance(res, dict) and any(res.get(k) for k in USER_KEYS)


def _existing_ids(company_id: str, ids: List[str]) -> set:
    found = set()
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
    try:
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            # any charity: a gift on this LaunchGood account may belong to the other charity (e.g. Iqra's Ramadan
            # Challenge ran on Rethink's account and is recorded as Iqra's) - never add it a second time
            q = f'SELECT "Donation ID" FROM donations WHERE "Donation ID" IN ({",".join("?" * len(chunk))})'
            found.update(str(r[0]).strip() for r in conn.execute(q, chunk))
    finally:
        conn.close()
    return found


def _download_report(client, start: str, end: str) -> pd.DataFrame:
    """The dashboard's own export (same calls as its Export button): create -> generate -> poll "download" until it
    returns the file's link (S3) -> fetch the CSV. Type "account_donors" is the "account_donations_..." donations file."""
    last_err = None
    for rtype in REPORT_TYPES:
        try:
            body = {"account_id": str(client.account_id), "fmt": "csv", "type": rtype, "start": start, "end": end,
                    "settled_donations": False}
            r = requests.post("https://www.launchgood.com/api/reports/v4_reports", headers=client._get_headers(), json=body, timeout=client.timeout)
            j = r.json() if "json" in (r.headers.get("content-type") or "") else {}
            res = j.get("result") if isinstance(j.get("result"), dict) else {}
            ident = res.get("identifier")
            if not ident:
                raise RuntimeError(f"report '{rtype}': {j.get('message') or r.status_code}")
            act = lambda verb: requests.post("https://www.launchgood.com/api/reports/action", headers=client._get_headers(),
                                             json={"verb": verb, "format": "csv", "identifier": ident}, timeout=60)
            act("generate")
            url = None
            for wait in (6, 12, 20, 30, 45, 60, 90):  # spaced out: rapid polling trips LaunchGood's firewall
                time.sleep(wait)
                d = act("download")
                if "json" not in (d.headers.get("content-type") or ""):
                    continue  # firewall page - try again a little later
                dres = (d.json() or {}).get("result") or {}
                if isinstance(dres, dict) and dres.get("state") == "done" and dres.get("url"):
                    url = dres["url"]
                    break
            if not url:
                raise RuntimeError(f"report '{rtype}' wasn't ready in time")
            f = requests.get(url, timeout=120)  # pre-signed S3 link, no credentials sent
            if f.status_code != 200:
                raise RuntimeError(f"report file download failed ({f.status_code})")
            text = f.content.decode("utf-8-sig", errors="replace")
            df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False) if text.strip() else pd.DataFrame()
            df.columns = [str(c).strip() for c in df.columns]
            missing = REQUIRED_COLS - set(df.columns)
            if missing:
                raise RuntimeError(f"report '{rtype}' lacks the LaunchGood donation columns {sorted(missing)} (got {list(df.columns)[:8]}...)")
            return df
        except Exception as e:  # try the next report type
            last_err = e
            logger.warning("LaunchGood report attempt failed: %s", e)
    raise RuntimeError(str(last_err))


def sync_company(company_id: str, force: bool = False) -> Dict[str, Any]:
    cid = str(company_id).strip().lower()
    state = _load_state()
    cs = state.get(cid) or {}
    now = time.time()
    st = session_state(cid)
    if not st["present"]:
        return {"status": "not_configured", "company_id": cid}

    usable, renew_msg = ensure_fresh_session(cid)
    result: Dict[str, Any] = {"company_id": cid, "session": renew_msg, "checked_at": datetime.now(timezone.utc).isoformat()}
    if not usable:
        result.update(status="signed_out", error=f"LaunchGood session: {renew_msg}")
        state[cid] = {**cs, **result}
        _save_state(state)
        return result
    if not force and cs.get("last_run_ts") and now - float(cs["last_run_ts"]) < SYNC_INTERVAL_SEC:
        # between pulls: report the last pull's outcome too, so the Ops card reflects a pull made outside the service
        return {"status": "waiting", "company_id": cid, "session": renew_msg, "last_status": cs.get("status"),
                "last_error": cs.get("error"), "fetched": cs.get("fetched", 0)}

    from core.launchgood_client import LaunchGoodClient
    client = LaunchGoodClient(company_id=cid)
    try:
        if not signed_in(client.get_current_user()):
            raise RuntimeError("LaunchGood answered as a signed-out guest")
        if not client.account_id:
            raise RuntimeError("no LaunchGood account id for this charity")
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=DAYS_BACK)
        try:  # reach back to the newest LaunchGood donation we already have, so a gap (e.g. a sign-out) is filled
            c0 = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
            last = c0.execute('SELECT MAX("Created Date (UTC)") FROM donations WHERE company_id = ? AND Platform = ?', (cid, "LaunchGood")).fetchone()[0]
            c0.close()
            if last:
                start = min(start, datetime.strptime(str(last)[:10], "%Y-%m-%d").date() - timedelta(days=1))
        except Exception:
            pass
        start = max(start, end - timedelta(days=120))
        df = _download_report(client, start.isoformat(), end.isoformat())
        df["Donation ID"] = df["Donation ID"].astype(str).str.strip()
        df = df[df["Donation ID"].str.match(r"^\d+$")]
        have = _existing_ids(cid, df["Donation ID"].tolist())
        new = df[~df["Donation ID"].isin(have)]
        added = 0
        if not new.empty:
            from core.data_processor import process_and_upload_excel
            buf = io.BytesIO(new.to_csv(index=False).encode("utf-8"))
            process_and_upload_excel(buf, source_name=f"LaunchGood API sync {end.isoformat()}.csv",
                                     upload_mode="merge", platform="launchgood", company_id=cid)
            added = len(new)
        newest = df["Created Date (UTC)"].max() if not df.empty else None
        result.update(status="success", fetched=len(df), added=added, newest_donation=newest, error=None,
                      last_success_at=datetime.now(timezone.utc).isoformat())
        if added:
            try:
                from core.event_log import log_event
                log_event("launchgood.sync_completed", category="sync", platform="launchgood", company_id=cid, count=added,
                          message=f"launchgood ({cid}): {added} new donation(s) added")
            except Exception:
                pass
    except Exception as e:
        result.update(status="error", error=str(e)[:300])
    result["last_run_ts"] = now
    state[cid] = {**cs, **result}
    _save_state(state)
    return result


def poll_launchgood(companies=("rethink", "iqra")) -> Dict[str, Any]:
    return {cid: sync_company(cid) for cid in companies}
