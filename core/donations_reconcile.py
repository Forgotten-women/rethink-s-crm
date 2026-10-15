"""
SQLite `donations` is the source of truth; donations_cache.parquet is a fast copy the dashboards read.

Every writer already updates both, but if one step fails (or a new code path only writes SQLite) the copy
drifts silently - e.g. 1,014 Madinah donations were in SQLite but missing from every dashboard. This module
keeps the copy honest:

  * quick check (every minute): compare the (company, Donation ID) keys of both stores. Rows missing from the
    parquet are copied from SQLite; rows that SQLite no longer has are removed. A difference must be seen on
    two consecutive checks before it is repaired, so a writer that is half-way through (parquet written,
    SQLite not yet committed, or the reverse) is never "repaired" mid-write.
  * deep check (daily): also compares every value of every row and makes the parquet match SQLite.

Repairs keep the parquet's row order (new rows are appended in SQLite insertion order), use the same
append-and-atomic-write path as the platform ingestion, and are skipped if the file changed meanwhile.
"""
import os
import sqlite3
import time
from typing import Any, Dict, Optional, Set, Tuple

import numpy as np
import pandas as pd

from config.settings import LOCAL_DB_PATH, PARQUET_PATH

Key = Tuple[str, str]
_pending: Dict[str, Any] = {"missing": None, "extra": None, "changed": None}


def _sqlite_keys(conn) -> Dict[Key, int]:
    rows = conn.execute("""SELECT rowid, LOWER(TRIM(COALESCE(company_id, 'rethink'))), "Donation ID"
                           FROM donations WHERE "Donation ID" IS NOT NULL AND TRIM("Donation ID") != ''""").fetchall()
    return {(comp, str(did)): rid for rid, comp, did in rows}


def _parquet_keys(df: pd.DataFrame) -> pd.Series:
    comp = df["company_id"].astype(str).str.strip().str.lower() if "company_id" in df.columns else pd.Series("rethink", index=df.index)
    did = df["Donation ID"]
    keys = pd.Series(list(zip(comp, did.astype(str))), index=df.index)
    return keys.where(did.notna() & (did.astype(str).str.strip() != ""), None)


def _read_rows(conn, rowids) -> pd.DataFrame:
    frames = []
    rowids = sorted(rowids)
    for i in range(0, len(rowids), 900):
        chunk = rowids[i:i + 900]
        frames.append(pd.read_sql_query(f"SELECT * FROM donations WHERE rowid IN ({','.join('?' * len(chunk))}) ORDER BY rowid",
                                        conn, params=chunk))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _norm_value(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return "" if np.isnan(v) else repr(round(v, 6))
    s = str(v).strip()
    try:
        return repr(round(float(s), 6))
    except ValueError:
        return "" if s.lower() in ("nan", "none", "null", "<na>", "nat") else s


def _arrow_safe(df: pd.DataFrame) -> pd.DataFrame:
    """A parquet column can't mix numbers and text (e.g. LaunchGood's numeric "Transfer ID" 26571 next to a Stripe
    payout id "po_..."): such columns are written as text, whole numbers without ".0". Values compare the same
    afterwards (_norm_value reads "26571" and 26571.0 alike), so this never causes a repair loop."""
    for col in df.columns:
        if df[col].dtype != object:
            continue
        vals = df[col].dropna()
        has_text = vals.map(lambda v: isinstance(v, str)).any()
        has_num = vals.map(lambda v: isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool)).any()
        if has_text and has_num:
            def as_text(v):
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    return None
                if isinstance(v, (float, np.floating)) and float(v).is_integer():
                    return str(int(v))
                return str(v)
            df[col] = df[col].map(as_text)
    return df


def _changed_keys(df: pd.DataFrame, keys: pd.Series, conn, sq_keys: Dict[Key, int]) -> Set[Key]:
    """Keys whose values differ between parquet and SQLite (deep check)."""
    sq = pd.read_sql_query("SELECT rowid AS _rid, * FROM donations", conn).set_index("_rid")
    valid = keys.dropna()
    rids = valid.map(sq_keys.get)
    have = rids.notna()
    valid, rids = valid[have], rids[have].astype(int)
    if valid.empty:
        return set()
    p_rows = df.loc[valid.index]
    s_rows = sq.loc[rids.to_numpy()]
    changed = np.zeros(len(valid), dtype=bool)
    for col in df.columns:
        if col in s_rows.columns:
            a = p_rows[col].astype(object).map(_norm_value).to_numpy()
            b = s_rows[col].astype(object).map(_norm_value).to_numpy()
            changed |= a != b
    return set(valid.to_numpy()[changed])


def reconcile(deep: bool = False, apply: bool = True, require_confirmation: bool = True,
              only_keys: Optional[Set[Key]] = None) -> Dict[str, Any]:
    """Returns a summary. With apply=False it only reports. Never raises for an ordinary mismatch.
    only_keys: (company, Donation ID) rows a writer just changed in SQLite - refreshed in the copy without the
    full value comparison of a deep check (seconds instead of minutes); new rows are still appended."""
    from core.data_processor import atomic_write_parquet, invalidate_data_cache
    started = time.time()
    if not os.path.exists(PARQUET_PATH):
        return {"status": "no_parquet"}
    stat_before = os.stat(PARQUET_PATH).st_mtime_ns
    df = pd.read_parquet(PARQUET_PATH)
    keys = _parquet_keys(df)
    conn = sqlite3.connect(f"file:{LOCAL_DB_PATH}?mode=ro", uri=True, timeout=30)
    try:
        sq_keys = _sqlite_keys(conn)
        pq_keyset = set(keys.dropna())
        missing = set(sq_keys) - pq_keyset
        extra = pq_keyset - set(sq_keys)
        if only_keys is not None:
            changed = {k for k in only_keys if k in pq_keyset and k in sq_keys}
        else:
            changed = _changed_keys(df, keys, conn, sq_keys) if deep else set()
        summary = {"status": "in_sync", "missing": len(missing), "extra": len(extra), "changed": len(changed),
                   "deep": deep, "parquet_rows": len(df), "sqlite_rows": len(sq_keys)}
        if not (missing or extra or changed):
            _pending.update(missing=None, extra=None, changed=None)
            return summary
        if require_confirmation and not deep:
            # repair only what was ALSO different on the previous check (writers mid-way are left alone)
            prev_m, prev_e = _pending["missing"], _pending["extra"]
            _pending.update(missing=missing, extra=extra)
            missing = missing & (prev_m or set())
            extra = extra & (prev_e or set())
            if not (missing or extra):
                summary["status"] = "drift_seen_waiting_for_confirmation"
                return summary
        if not apply:
            summary["status"] = "drift_found"
            return summary

        out = df
        if changed:
            fresh = _read_rows(conn, [sq_keys[k] for k in changed])
            fresh_keys = _parquet_keys(fresh)
            by_key = {k: i for i, k in fresh_keys.items() if k is not None}
            for idx, k in keys.items():
                if k in by_key:
                    row = fresh.loc[by_key[k]]
                    for col in out.columns:
                        if col in fresh.columns:
                            try:
                                out.at[idx, col] = row[col]
                            except (TypeError, ValueError):
                                # e.g. a column that was always empty (float NaN) now holds text: widen it
                                widened = out[col].astype(object)
                                out[col] = widened.where(widened.notna(), None)  # NaN -> null so it can hold text
                                out.at[idx, col] = row[col]
        if extra:
            out = out[~keys.isin(extra)]
        if missing:
            df_new = _read_rows(conn, [sq_keys[k] for k in missing])
            for col in out.columns:
                if col not in df_new.columns:
                    df_new[col] = None
            df_new = df_new[out.columns]
            out = pd.concat([out, df_new], ignore_index=True)
    finally:
        conn.close()

    if os.stat(PARQUET_PATH).st_mtime_ns != stat_before:
        summary["status"] = "skipped_file_changed"  # another writer got there first; check again next time
        return summary
    atomic_write_parquet(_arrow_safe(out), PARQUET_PATH)
    invalidate_data_cache()
    _pending.update(missing=None, extra=None, changed=None)
    summary.update(status="repaired", added=len(missing), removed=len(extra), updated=len(changed),
                   parquet_rows_after=len(out), seconds=round(time.time() - started, 1))
    try:
        from core.event_log import log_event
        log_event("data.reconciled", category="data", level="warning",
                  message=f"Donations copy repaired from SQLite: +{len(missing)} added, -{len(extra)} removed, "
                          f"{len(changed)} updated", **{k: v for k, v in summary.items() if k != "status"})
    except Exception:
        pass
    return summary


if __name__ == "__main__":
    import json
    import sys
    deep = "--deep" in sys.argv
    print(json.dumps(reconcile(deep=deep, apply="--apply" in sys.argv, require_confirmation=False), indent=1, default=str))
