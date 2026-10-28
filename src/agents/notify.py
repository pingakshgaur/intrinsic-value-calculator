# FILE: src/agents/notify.py
"""
Optional Telegram alert after a run - only the changes, never the full report.

Off unless alerts.telegram is true AND both TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID are set. Create a bot with @BotFather, send it one message,
then read your chat id from https://api.telegram.org/bot<token>/getUpdates.
"""

import os

import requests

from agents import settings as S


def _wanted(change):
    if change.startswith("label changed"):
        return S.get("alerts.on_label_change", True)
    if change.startswith("NEW red flag"):
        return S.get("alerts.on_new_red_flag", True)
    if "buy-below" in change:
        return S.get("alerts.on_price_crossing_buy_below", True)
    return False


def send_changes(verdicts, meta):
    if not S.get("alerts.telegram", False):
        return ""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return "Telegram alerts on but TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set - nothing sent"
    lines = []
    for v in verdicts:
        for c in v.get("changes", []):
            if _wanted(c):
                lines.append(f"- {v['company']}: {c}")
    if not lines:
        return "no alert-worthy changes"
    text = f"Market intelligence run #{meta['run_id']} ({meta['mode']})\n" + "\n".join(lines[:30])
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text[:3900]}, timeout=20)
        return f"Telegram alert sent ({len(lines)} change(s))" if r.ok else f"Telegram returned HTTP {r.status_code}"
    except requests.RequestException as e:
        return f"Telegram alert failed: {type(e).__name__}"
