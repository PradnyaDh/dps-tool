#!/usr/bin/env python3
"""
Slack Notifier
==============
Sends a message via Slack webhook URL (preferred) or bot token.

Usage:
    python3 slack_notify.py "Your message here"

Setup — webhook (simplest, ask your Slack admin for this):
    export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../xxx"

Setup — bot token (if you have one):
    export SLACK_TOKEN="xoxb-..."

Your Slack user ID: U08QKDZRGP6
"""

import os
import sys
import json
import urllib.request

SLACK_WEBHOOK_URL  = os.environ.get("SLACK_WEBHOOK_URL", "")
SLACK_TOKEN        = os.environ.get("SLACK_TOKEN", "")
SLACK_DEFAULT_USER = "U08QKDZRGP6"


def send_via_webhook(text: str, webhook_url: str) -> None:
    payload = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        body = resp.read().decode()
        if body != "ok":
            raise RuntimeError(f"Webhook error: {body}")


def send_via_token(text: str, recipient: str, token: str) -> None:
    payload = json.dumps({"channel": recipient, "text": text}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "unknown error"))


def send_slack(text: str, recipient: str = SLACK_DEFAULT_USER) -> None:
    """Send a Slack message. Uses webhook if available, falls back to token."""
    if SLACK_WEBHOOK_URL:
        send_via_webhook(text, SLACK_WEBHOOK_URL)
    elif SLACK_TOKEN:
        send_via_token(text, recipient, SLACK_TOKEN)
    else:
        raise RuntimeError(
            "No Slack credentials configured. "
            "Set SLACK_WEBHOOK_URL or SLACK_TOKEN env var."
        )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 slack_notify.py 'message text'")
        sys.exit(1)
    try:
        send_slack(sys.argv[1])
        print("Message sent.")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
