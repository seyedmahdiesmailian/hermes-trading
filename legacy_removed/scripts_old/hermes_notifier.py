#!/usr/bin/env python3
"""
HERMES NOTIFIER
═══════════════════════════════════════════════
Sends trade reports to Telegram bot
"""

import requests
import os
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path("/home/ai/hermes-trading")
LOG_DIR = BASE_DIR / "logs"

# Load from environment or config
TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "7959188229:AAFocjK-oULzPHZIPMGFjppCjqQo4ifGmkI"
)
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "194015957")


def send_telegram(message: str):
    """Send message to Telegram."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        r = requests.post(url, data=data, timeout=10)
        if r.status_code == 200:
            print(f"[TELEGRAM SENT] {r.json().get('ok', False)}")
        else:
            print(f"[TELEGRAM ERROR] Status: {r.status_code}")
            print(f"Response: {r.text[:200]}")
    except Exception as e:
        print(f"[TELEGRAM FAIL] {e}")
    
    # Always save to log
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / "telegram_messages.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()}\t{message[:500]}\n")


def notify_trade_opened(symbol: str, direction: str, volume: float, price: float, sl: float, tp: float, ticket: int):
    """Notify when trade is opened."""
    msg = (
        f"🟢 <b>Trade OPENED</b>\n\n"
        f"📈 Symbol: {symbol}\n"
        f"📊 Direction: {direction}\n"
        f"📦 Volume: {volume}\n"
        f"💵 Entry: {price:.2f}\n"
        f"🛡 SL: {sl:.2f}\n"
        f"🎯 TP: {tp:.2f}\n"
        f"🎫 Ticket: {ticket}\n"
        f"⏰ Time: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )
    send_telegram(msg)


def notify_trade_closed(ticket: int, profit: float, reason: str):
    """Notify when trade is closed."""
    emoji = "🟢" if profit > 0 else "🔴"
    msg = (
        f"{emoji} <b>Trade CLOSED</b>\n\n"
        f"🎫 Ticket: {ticket}\n"
        f"💰 Profit: ${profit:.2f}\n"
        f"📋 Reason: {reason}\n"
        f"⏰ Time: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )
    send_telegram(msg)


def notify_analysis(price: float, bias: str, smc: str, decision: str):
    """Notify analysis result."""
    msg = (
        f"📊 <b>Market Analysis</b>\n\n"
        f"💵 Price: {price:.2f}\n"
        f"📈 Bias: {bias}\n"
        f"🎯 SMC: {smc}\n"
        f"🤖 Decision: {decision}"
    )
    send_telegram(msg)


def notify_cron_report(mode: str, positions: int, balance: float):
    """Notify cron cycle completion."""
    msg = (
        f"📡 <b>Cron Cycle Complete</b>\n\n"
        f"🤖 Mode: {mode}\n"
        f"📦 Positions: {positions}\n"
        f"💰 Balance: ${balance:.2f}\n"
        f"⏰ Time: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )
    send_telegram(msg)


def notify_error(error_msg: str):
    """Notify errors."""
    msg = f"❌ <b>Error:</b>\n\n{error_msg[:1000]}"
    send_telegram(msg)


if __name__ == "__main__":
    send_telegram("🤖 <b>Hermes Trading Bot</b> is online!\n\nconnected to MT5 bridge.")
