"""
LaunchGood Multi-Tenant Accounts & Session Registry
---------------------------------------------------
Strict charity isolation for LaunchGood:
  * Rethink Charity: Account ID 31152 (Rethink Corporate Business Account)
  * Iqra: Account ID configured via IQRA_LAUNCHGOOD_ACCOUNT_ID in .env

Credentials and session tokens (Bearer JWT + cookies) are strictly segregated:
  * Rethink: config/launchgood_tokens_rethink.json
  * Iqra:    config/launchgood_tokens_iqra.json
"""
import base64
import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("launchgood_accounts")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
os.makedirs(CONFIG_DIR, exist_ok=True)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"), override=False)
except ImportError:
    pass


def _parse_jwt_exp(token: str) -> float:
    try:
        part = (token or "").replace("Bearer ", "").strip().split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return float(payload.get("exp", 0))
    except Exception:
        return 0.0


def get_account_config(company_id: str = "rethink") -> Dict[str, Any]:
    """Dynamically resolves account configuration from environment variables or defaults."""
    cid = str(company_id or "rethink").strip().lower()
    prefix = cid.upper()

    acc_id_raw = os.environ.get(f"{prefix}_LAUNCHGOOD_ACCOUNT_ID") or os.environ.get(f"LAUNCHGOOD_{prefix}_ACCOUNT_ID")
    sub_id_raw = os.environ.get(f"{prefix}_LAUNCHGOOD_SUBACCOUNT_ID") or os.environ.get(f"LAUNCHGOOD_{prefix}_SUBACCOUNT_ID")
    email_raw = os.environ.get(f"{prefix}_LAUNCHGOOD_EMAIL") or os.environ.get(f"LAUNCHGOOD_{prefix}_EMAIL")
    token_file_raw = os.environ.get(f"{prefix}_LAUNCHGOOD_TOKEN_FILE") or os.environ.get(f"LAUNCHGOOD_{prefix}_TOKEN_FILE")

    account_id = int(acc_id_raw) if acc_id_raw and acc_id_raw.isdigit() else None
    subaccount_id = int(sub_id_raw) if sub_id_raw and sub_id_raw.isdigit() else None
    token_file = token_file_raw if token_file_raw else os.path.join(CONFIG_DIR, f"launchgood_tokens_{cid}.json")
    if not os.path.isabs(token_file):
        token_file = os.path.join(BASE_DIR, token_file)

    fallbacks = []
    if cid == "rethink":
        fallbacks = [
            os.path.join(CONFIG_DIR, "launchgood_tokens.json"),
            "/tmp/launchgood_tokens.json",
        ]

    return {
        "company_id": cid,
        "label": "Rethink Charity" if cid == "rethink" else cid.title(),
        "account_id": account_id,
        "default_subaccount": subaccount_id,
        "user_email": email_raw or "",
        "token_file": token_file,
        "fallback_token_files": fallbacks,
    }


def get_account_id(company_id: str = "rethink") -> Optional[int]:
    """Resolves account ID from .env, or falls back to saved session file."""
    cfg = get_account_config(company_id)
    if cfg.get("account_id"):
        return cfg["account_id"]
    
    session = get_session(company_id)
    if session:
        for k in ("account_id", "accountId", "defaultSubAccount", "subAccount", "subAccountId"):
            val = session.get(k)
            if val and str(val).isdigit():
                return int(val)
    return None


def get_token_file_path(company_id: str = "rethink") -> str:
    return get_account_config(company_id)["token_file"]


def get_session(company_id: str = "rethink") -> Optional[Dict[str, Any]]:
    """Loads authenticated LaunchGood session from .env overrides or designated token file."""
    cid = str(company_id or "rethink").strip().lower()
    prefix = cid.upper()

    # 1. Check direct .env token injection
    env_token = os.environ.get(f"{prefix}_LAUNCHGOOD_BEARER_TOKEN") or os.environ.get(f"LAUNCHGOOD_{prefix}_TOKEN") or os.environ.get(f"{prefix}_LAUNCHGOOD_TOKEN")
    env_cookie = os.environ.get(f"{prefix}_LAUNCHGOOD_COOKIE") or os.environ.get(f"LAUNCHGOOD_{prefix}_COOKIE")
    if env_token:
        bearer = env_token.strip() if env_token.strip().startswith("Bearer ") else f"Bearer {env_token.strip()}"
        return {
            "bearerToken": bearer,
            "accessToken": bearer,
            "rawCookie": env_cookie or "",
            "headers": {
                "authorization": bearer,
                "cookie": env_cookie or "",
                "accept": "application/json",
            },
            "savedAt": "env",
        }

    # 2. Check token file(s)
    cfg = get_account_config(company_id)
    paths = [cfg["token_file"]] + cfg.get("fallback_token_files", [])

    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data and (data.get("bearerToken") or data.get("accessToken") or data.get("headers")):
                    # Smart resolution: compare JWT exp between bearerToken and accessToken
                    b_token = str(data.get("bearerToken") or "").strip()
                    a_token = str(data.get("accessToken") or "").strip()
                    b_exp = _parse_jwt_exp(b_token)
                    a_exp = _parse_jwt_exp(a_token)
                    best = a_token if a_exp > b_exp else (b_token or a_token)

                    if best:
                        best_bearer = best if best.startswith("Bearer ") else f"Bearer {best}"
                        data["bearerToken"] = best_bearer
                        data["accessToken"] = best_bearer
                        headers = dict(data.get("headers") or {})
                        # Keep authorization in sync
                        headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}
                        headers["authorization"] = best_bearer
                        data["headers"] = headers
                    return data
            except Exception as e:
                logger.warning(f"Failed to read LaunchGood token file {p}: {e}")
    return None


def is_connected(company_id: str = "rethink") -> bool:
    session = get_session(company_id)
    return session is not None and bool(
        session.get("bearerToken") or session.get("accessToken") or session.get("headers")
    )


def save_session(company_id: str, session_data: Dict[str, Any]) -> str:
    """Stores a captured LaunchGood session strictly under the target charity's configured token file."""
    cfg = get_account_config(company_id)
    target_path = cfg["token_file"]
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    temp_path = f"{target_path}.tmp.{os.getpid()}"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2)
    os.replace(temp_path, target_path)
    logger.info(f"Saved LaunchGood session for charity '{company_id}' to: {target_path}")
    return target_path


def connected_companies() -> List[str]:
    return [cid for cid in ("rethink", "iqra") if is_connected(cid)]
