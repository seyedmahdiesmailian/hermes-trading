#!/usr/bin/env python3
"""Trade Notifier V2 — Telegram notifications for trades.

Sends real-time notifications when:
- Trade opened
- Trade closed
- Analysis completed
"""
import os
import sys
import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"

# Load from environment
sys.path.insert(0, str(BASE_DIR))
from env_loader import load_dotenv
load_dotenv(BASE_DIR / '.env')

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send_telegram(message: str):
    """Send message to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM] Token or Chat ID not configured")
        return
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }).encode('utf-8')
        
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get("ok"):
                print(f"[TELEGRAM SENT] OK")
            else:
                print(f"[TELEGRAM ERROR] {result}")
    except Exception as e:
        print(f"[TELEGRAM FAIL] {e}")
    
    # Always save to log
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "telegram_trades.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()}\t{message[:500]}\n")
    except Exception as e:
        print(f"[LOG FAIL] {e}")


def notify_trade_opened(symbol: str, direction: str, volume: float, price: float, 
                        sl: float, tp: float, ticket: int):
    """Notify when trade is opened."""
    msg = (
        f"🟢 <b>معامله باز شد</b>\n\n"
        f"📈 نماد: {symbol}\n"
        f"📊 جهت: {'خرید' if direction.upper() == 'BUY' else 'فروش'}\n"
        f"📦 حجم: {volume}\n"
        f"💵 ورود: {price:.2f}\n"
        f"🛡 SL: {sl:.2f}\n"
        f"🎯 TP: {tp:.2f}\n"
        f"🎫 تیکت: {ticket}\n"
        f"⏰ زمان: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )
    send_telegram(msg)


def notify_trade_closed(ticket: int, symbol: str, profit: float, reason: str):
    """Notify when trade is closed."""
    emoji = "🟢" if profit > 0 else "🔴"
    result = "سود" if profit > 0 else "ضرر"
    msg = (
        f"{emoji} <b>معامله بسته شد</b>\n\n"
        f"📈 نماد: {symbol}\n"
        f"🎫 تیکت: {ticket}\n"
        f"💰 {result}: ${abs(profit):.2f}\n"
        f"📋 دلیل: {reason}\n"
        f"⏰ زمان: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )
    send_telegram(msg)


def notify_analysis(symbol: str, decision: str, quality: float, confidence: float, reasoning: str):
    """Notify analysis result."""
    msg = (
        f"📊 <b>تحلیل بازار</b>\n\n"
        f"📈 نماد: {symbol}\n"
        f"🤖 تصمیم: {decision}\n"
        f"⭐ کیفیت: {quality:.0%}\n"
        f"💪 اطمینان: {confidence:.0%}\n"
        f"📝 دلیل: {reasoning[:100]}..."
    )
    send_telegram(msg)


def notify_error(error_msg: str):
    """Notify errors."""
    msg = f"❌ <b>خطا:</b>\n\n{error_msg[:500]}"
    send_telegram(msg)


if __name__ == "__main__":
    # Test
    send_telegram("🤖 <b>Hermes Trading V2</b> آنلاین است!\n\nاتصال به MT5 برقرار شد.")
