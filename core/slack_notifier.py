"""
Slack Notification Service for Stripe Payout Reconciliation
Posts executive financial summaries and uploads audit-ready CSV reports to #rt-payouts.
"""

import os
import json
import logging
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger("slack_notifier")

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "").strip()
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "").strip()


def post_slack_message(text: str, channel_id: Optional[str] = None) -> Dict[str, Any]:
    """Posts a standard text/markdown message to Slack."""
    channel = channel_id or SLACK_CHANNEL_ID
    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "channel": channel,
        "text": text,
        "mrkdwn": True
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        res = r.json()
        if not res.get("ok"):
            logger.error(f"Slack chat.postMessage failed: {res.get('error')}")
        return res
    except Exception as e:
        logger.error(f"Error posting Slack message: {e}")
        return {"ok": False, "error": str(e)}


def upload_payout_report_to_slack(
    file_path: str,
    payout_id: str,
    summary: Dict[str, Any],
    channel_id: Optional[str] = None,
    approved_by: Optional[str] = None
) -> Dict[str, Any]:
    """
    Uploads the enriched CSV reconciliation report to Slack with a formatted summary card.
    Uses Slack files.uploadV2 API.
    """
    channel = channel_id or SLACK_CHANNEL_ID
    if not os.path.exists(file_path):
        return {"ok": False, "error": f"File not found: {file_path}"}

    total_gross = summary.get("total_gross", 0.0)
    total_fees = summary.get("total_fees", 0.0)
    total_net = summary.get("total_net", 0.0)
    total_rows = summary.get("total_rows", 0)
    enriched_count = summary.get("enriched_count", 0)
    approver_str = f" · Approved by: *{approved_by}*" if approved_by else ""

    comment_lines = [
        f"📊 *Stripe Payout Reconciliation Report (Approved)*{approver_str}",
        f"• *Payout ID*: `{payout_id}`",
        f"• *Total Transactions*: `{total_rows}`",
        f"• *Gross Volume*: `£{total_gross:,.2f}`",
        f"• *Stripe Fees*: `£{total_fees:,.2f}`",
        f"• *Net Payout*: `£{total_net:,.2f}`",
        f"• *Reconciled Transactions*: `{enriched_count}` (GiveBrite + Website + Subscriptions + Terminal)",
    ]

    funds_breakdown = summary.get("funds_breakdown") or {}
    if funds_breakdown:
        comment_lines.append("\n📁 *Worked Out Fund Allocations (Net)*:")
        for fund, amt in funds_breakdown.items():
            comment_lines.append(f"  • *{fund}*: £{amt:,.2f}")

    zakat_breakdown = summary.get("zakat_breakdown") or {}
    if zakat_breakdown:
        comment_lines.append("\n🕌 *Zakat Breakdown (Net)*:")
        for z_type, amt in zakat_breakdown.items():
            comment_lines.append(f"  • *{z_type}*: £{amt:,.2f}")

    comment_lines.append("\n_Audit-ready reconciliation CSV is attached below with all worked-out classification columns._")
    initial_comment = "\n".join(comment_lines)

    # 1. Step 1: get upload URL via files.getUploadURLExternal
    filename = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)

    try:
        url_get = "https://slack.com/api/files.getUploadURLExternal"
        headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
        r_get = requests.get(url_get, headers=headers, params={"filename": filename, "length": file_size}, timeout=15)
        res_get = r_get.json()
        if not res_get.get("ok"):
            logger.warning(f"getUploadURLExternal failed: {res_get.get('error')}. Falling back to chat notification.")
            post_slack_message(initial_comment, channel_id=channel)
            return {"ok": False, "error": res_get.get("error")}

        upload_url = res_get["upload_url"]
        file_id = res_get["file_id"]

        # Step 2: POST file data to upload_url
        with open(file_path, "rb") as f:
            r_post = requests.post(upload_url, data=f, timeout=60)
        if r_post.status_code not in (200, 201):
            logger.error(f"Failed to post file content to upload URL: {r_post.status_code}")
            return {"ok": False, "error": f"Upload failed HTTP {r_post.status_code}"}

        # Step 3: Complete upload via files.completeUploadExternal
        url_complete = "https://slack.com/api/files.completeUploadExternal"
        complete_payload = {
            "files": [{"id": file_id, "title": f"Stripe Payout - {payout_id}"}],
            "channel_id": channel,
            "initial_comment": initial_comment
        }
        r_comp = requests.post(url_complete, headers=headers, json=complete_payload, timeout=20)
        res_comp = r_comp.json()
        if not res_comp.get("ok"):
            logger.error(f"completeUploadExternal failed: {res_comp.get('error')}")
            return res_comp

        logger.info(f"Delivered payout {payout_id} to Slack channel {channel} successfully.")
        return {"ok": True, "file_id": file_id, "channel": channel}
    except Exception as e:
        logger.error(f"Error uploading payout report to Slack: {e}")
        return {"ok": False, "error": str(e)}
