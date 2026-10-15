"""
Which charity owns which Stripe account. Every Stripe feature (payout reconciliation, live ledger, CRM donations,
GiveBrite tie-back) works per charity from here, and only for charities whose key is configured - one charity's
Stripe data is never read with, or stored under, another charity.

Keys live only in .env (never in code, logs or API responses):
  RETHINK_STRIPE_SECRET_KEY   - Rethink's unified account (connected)
  IQRA_STRIPE_SECRET_KEY      - Iqra's account (add when access is granted; nothing else needs to change,
                                except choosing its CRM start date below before switching its CRM sync on)
"""
import os
from typing import Dict, List, Optional

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

ACCOUNTS: Dict[str, Dict[str, object]] = {
    "rethink": {
        "label": "Rethink Charity",
        "key_env": ("RETHINK_STRIPE_SECRET_KEY", "STRIPE_RETHINK_SECRET_KEY", "STRIPE_SECRET_KEY"),
        # Stripe payments become CRM donations from this date (agreed 15 Oct 2026)
        "crm_start_date": "2026-08-01",
        # GiveBrite gifts reach this account from this date; earlier ones went via GiveBrite's Express account
        "givebrite_from": "2026-10-12",
        # Approved payout reports go to this charity's own Slack channel (#rt-payouts)
        "slack_channel_env": "SLACK_CHANNEL_ID",
    },
    "iqra": {
        "label": "Iqra",
        "key_env": ("IQRA_STRIPE_SECRET_KEY",),
        "crm_start_date": None,   # set before switching Iqra's CRM sync on
        "givebrite_from": None,
        "slack_channel_env": "IQRA_SLACK_CHANNEL_ID",  # never Rethink's channel
    },
}


def stripe_key(company_id: str) -> str:
    acct = ACCOUNTS.get(str(company_id or "").strip().lower())
    if not acct:
        return ""
    for name in acct["key_env"]:  # type: ignore[union-attr]
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    return ""


def is_connected(company_id: str) -> bool:
    return bool(stripe_key(company_id))


def connected_companies() -> List[str]:
    return [c for c in ACCOUNTS if is_connected(c)]


def account_setting(company_id: str, name: str) -> Optional[object]:
    return (ACCOUNTS.get(str(company_id or "").strip().lower()) or {}).get(name)


def stripe_headers(company_id: str) -> Dict[str, str]:
    key = stripe_key(company_id)
    if not key:
        raise RuntimeError(f"Stripe isn't connected for '{company_id}'.")
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


def slack_channel(company_id: str) -> str:
    env = account_setting(company_id, "slack_channel_env")
    return (os.environ.get(str(env)) or "").strip() if env else ""
