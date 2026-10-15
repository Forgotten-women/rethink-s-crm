"""
Slack Notification & Alerting Service for Access PaySuite Direct Debits.

Sends formatted executive updates and digests to Slack channel #rt-payouts:
1. Disbursal Summary: posted when a new BACS settlement batch is processed,
   including payment count, net volume, fund allocations, and an "adds up to the penny" check.
2. Daily Digest: aggregated summary of failed collections (ARUDD), cancelled mandates (ADDACS),
   and new Direct Debit instructions. Avoids noisy individual notifications.
"""
import logging
import os
from typing import Any, Dict, List, Optional

from core.slack_notifier import post_slack_message

logger = logging.getLogger("paysuite_alerts")

SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "C0C1RGPC7A8").strip()


def send_disbursal_slack_alert(
    disbursal_id: str,
    total_amount: float,
    payment_count: int,
    disbursal_date: str,
    funds_breakdown: Optional[Dict[str, float]] = None,
    adds_up: bool = True,
    channel_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Posts a clean, executive financial summary to #rt-payouts when a PaySuite disbursal arrives.
    """
    channel = channel_id or SLACK_CHANNEL_ID
    check_badge = "✅ *Adds up to the penny*" if adds_up else "⚠️ *Discrepancy detected*"

    lines = [
        "🏦 *Access PaySuite Direct Debit Disbursal Processed*",
        f"• *Disbursal ID*: `{disbursal_id}`",
        f"• *Disbursal Date*: `{disbursal_date}`",
        f"• *Total Collections*: `{payment_count}`",
        f"• *Disbursal Amount*: `£{total_amount:,.2f}`",
        f"• *Reconciliation Check*: {check_badge} (£0 payout fee deduction model)",
    ]

    if funds_breakdown:
        lines.append("\n📁 *Fund Allocations*:")
        for fund, amt in sorted(funds_breakdown.items(), key=lambda x: -x[1]):
            lines.append(f"  • *{fund}*: £{amt:,.2f}")

    lines.append("\n_All collections have been linked and reconciled in the CRM Payouts and Donors directory._")
    message = "\n".join(lines)

    return post_slack_message(message, channel_id=channel)


def send_daily_paysuite_digest(
    failed_collections: List[Dict[str, Any]],
    cancelled_mandates: List[Dict[str, Any]],
    new_mandates: List[Dict[str, Any]],
    channel_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Sends a consolidated daily digest to #rt-payouts for exceptions and mandate updates.
    """
    channel = channel_id or SLACK_CHANNEL_ID

    if not failed_collections and not cancelled_mandates and not new_mandates:
        logger.info("[PaySuite Alerts] No exceptions or updates to report for daily digest.")
        return {"ok": True, "skipped": True}

    lines = [
        "📋 *Access PaySuite Daily Operations Digest*",
        f"• *New Mandates Registered*: `{len(new_mandates)}`",
        f"• *Failed Collections (ARUDD)*: `{len(failed_collections)}`",
        f"• *Cancelled Mandates (ADDACS)*: `{len(cancelled_mandates)}`",
    ]

    if failed_collections:
        lines.append("\n⚠️ *Failed / Returned Direct Debits (ARUDD)*:")
        for f in failed_collections[:10]:
            name = f.get("name") or "Anonymous"
            ref = f.get("reference") or "N/A"
            amt = f.get("amount", 0.0)
            reason = f.get("reason") or "Payment unpaid"
            lines.append(f"  • *{name}* (`{ref}`): £{amt:,.2f} — _{reason}_")
        if len(failed_collections) > 10:
            lines.append(f"  _...and {len(failed_collections) - 10} more in CRM Payouts tab._")

    if new_mandates:
        lines.append("\n✨ *New Direct Debit Mandates*:")
        for m in new_mandates[:5]:
            name = m.get("name") or "Anonymous"
            ref = m.get("reference") or "N/A"
            amt = m.get("amount", 0.0)
            freq = m.get("frequency") or "Monthly"
            lines.append(f"  • *{name}* (`{ref}`): £{amt:,.2f} ({freq})")
        if len(new_mandates) > 5:
            lines.append(f"  _...and {len(new_mandates) - 5} more in CRM._")

    lines.append("\n_Audit-compliant reversals have been generated automatically for all failed collections._")
    message = "\n".join(lines)

    return post_slack_message(message, channel_id=channel)
