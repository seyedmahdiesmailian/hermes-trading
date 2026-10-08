#!/usr/bin/env python3
"""Hermes Trading Command Bot - Telegram bot with slash commands.

Commands:
- /panel - System status dashboard
- /plan - Current trading plan
- /positions - Open positions
- /stats - Trading statistics
- /risk - Risk parameters
- /status - Quick status check
"""
import os
import sys
import json
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
from env_loader import load_dotenv
load_dotenv(BASE_DIR / '.env')

# Telegram config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# MT5 Bridge
BRIDGE_URL = os.getenv("HERMES_BRIDGE_URL", "http://192.168.10.51:5050")
BRIDGE_TOKEN = os.getenv("HERMES_BRIDGE_TOKEN", "")

LOG_FILE = BASE_DIR / "logs" / "command_bot.log"

def log(msg: str):
    """Log message."""
    line = f"[{datetime.now()}] {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def api(method: str, params: dict | None = None) -> dict:
    """Call Telegram API."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
        data = urllib.parse.urlencode(params or {}).encode('utf-8') if params else None
        req = urllib.request.Request(url, data=data) if data else urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        log(f"API error: {e}")
        return {"ok": False}

def bridge_get(endpoint: str) -> dict:
    """Call MT5 bridge."""
    try:
        url = f"{BRIDGE_URL}{endpoint}"
        req = urllib.request.Request(url)
        if BRIDGE_TOKEN:
            req.add_header('Authorization', f'Bearer {BRIDGE_TOKEN}')
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        return {"ok": False, "error": str(e)}

def send_message(text: str):
    """Send message to user."""
    api("sendMessage", {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    })

def cmd_panel():
    """System status dashboard."""
    account = bridge_get("/api/account")
    
    if not account.get("ok"):
        return "❌ خطا در اتصال به MT5"
    
    data = account.get("data", {})
    balance = data.get("balance", 0)
    equity = data.get("equity", 0)
    margin = data.get("margin", 0)
    free_margin = data.get("free_margin", 0)
    
    msg = (
        f"🛰 <b>پنل سیستم</b>\n\n"
        f"💰 موجودی: ${balance:.2f}\n"
        f"📊 ارزش: ${equity:.2f}\n"
        f"📈 مارجین: ${margin:.2f}\n"
        f"💵 مارجین آزاد: ${free_margin:.2f}\n\n"
        f"⏰ زمان: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    return msg

def cmd_positions():
    """Open positions."""
    positions = bridge_get("/api/positions")
    
    if not positions.get("ok"):
        return "❌ خطا در دریافت پوزیشن‌ها"
    
    data = positions.get("data", [])
    
    if not data:
        return "📊 <b>پوزیشن‌ها</b>\n\nهیچ پوزیشن بازی وجود ندارد"
    
    msg = f"📊 <b>پوزیشن‌های باز ({len(data)})</b>\n\n"
    
    for pos in data:
        ticket = pos.get("ticket", "?")
        symbol = pos.get("symbol", "?")
        type_ = pos.get("type", "?")
        volume = pos.get("volume", 0)
        price_open = pos.get("price_open", 0)
        price_current = pos.get("price_current", 0)
        profit = pos.get("profit", 0)
        sl = pos.get("sl", 0)
        tp = pos.get("tp", 0)
        
        direction = "🟢 خرید" if "BUY" in str(type_).upper() else "🔴 فروش"
        profit_emoji = "💚" if profit > 0 else "❤️"
        
        msg += (
            f"🎫 {ticket}\n"
            f"{direction} {symbol} | حجم: {volume}\n"
            f"💵 ورود: {price_open:.2f} | فعلی: {price_current:.2f}\n"
            f"{profit_emoji} سود/ضرر: ${profit:.2f}\n"
            f"🛡 SL: {sl:.2f} | 🎯 TP: {tp:.2f}\n\n"
        )
    
    return msg

def cmd_plan():
    """Current trading plan."""
    plan_file = BASE_DIR / "data" / "plans" / "current_plan.json"
    
    if not plan_file.exists():
        return "📋 <b>پلن فعلی</b>\n\nهیچ پلن فعالی وجود ندارد"
    
    try:
        with open(plan_file, "r", encoding="utf-8") as f:
            plan = json.load(f)
        
        symbol = plan.get("symbol", "?")
        direction = plan.get("direction", "?").upper()
        entry = plan.get("entry_price", 0)
        sl = plan.get("sl", 0)
        tp = plan.get("tp", 0)
        size = plan.get("size", 0)
        grade = plan.get("grade", "?")
        reasoning = plan.get("reasoning", "")[:200]
        
        dir_fa = "خرید" if "BUY" in direction else "فروش"
        
        msg = (
            f"📋 <b>پلن فعلی</b>\n\n"
            f"📈 نماد: {symbol}\n"
            f"📊 جهت: {dir_fa}\n"
            f"💵 ورود: {entry:.2f}\n"
            f"🛡 SL: {sl:.2f}\n"
            f"🎯 TP: {tp:.2f}\n"
            f"📦 حجم: {size}\n"
            f"⭐ درجه: {grade}\n\n"
            f"📝 دلیل: {reasoning}..."
        )
        return msg
    except Exception as e:
        return f"❌ خطا در خواندن پلن: {e}"

def cmd_stats():
    """Trading statistics."""
    # Load from performance state
    perf_file = BASE_DIR / "data" / "state" / "performance.json"
    
    if not perf_file.exists():
        return "📊 <b>آمار</b>\n\nهنوز آماری ثبت نشده است"
    
    try:
        with open(perf_file, "r", encoding="utf-8") as f:
            perf = json.load(f)
        
        total = perf.get("total_trades", 0)
        wins = perf.get("wins", 0)
        losses = perf.get("losses", 0)
        total_profit = perf.get("total_profit", 0)
        win_rate = (wins / total * 100) if total > 0 else 0
        
        msg = (
            f"📊 <b>آمار معاملات</b>\n\n"
            f"🔢 تعداد کل: {total}\n"
            f"✅ برد: {wins}\n"
            f"❌ باخت: {losses}\n"
            f"📈 نرخ برد: {win_rate:.1f}%\n"
            f"💰 سود کل: ${total_profit:.2f}"
        )
        return msg
    except Exception:
        return "❌ خطا در خواندن آمار"

def cmd_risk():
    """Risk parameters."""
    msg = (
        f"🛡 <b>پارامترهای ریسک</b>\n\n"
        f"📊 ریسک هر معامله: 2%\n"
        f"📉 ضرر روزانه مجاز: 5%\n"
        f"🔢 حداکثر معاملات روزانه: 5\n"
        f"📦 حداکثر پوزیشن باز: 1\n"
        f"⚖️ حداکثر حجم: 10.0 لات\n"
        f"🎯 حداقل Risk/Reward: 2.0"
    )
    return msg

def cmd_status():
    """Quick status."""
    account = bridge_get("/api/account")
    positions = bridge_get("/api/positions")
    
    if not account.get("ok"):
        return "❌ سیستم آفلاین است"
    
    balance = account.get("data", {}).get("balance", 0)
    pos_count = len(positions.get("data", []))
    
    msg = (
        f"✅ <b>وضعیت</b>\n\n"
        f"🟢 سیستم آنلاین\n"
        f"💰 موجودی: ${balance:.2f}\n"
        f"📊 پوزیشن باز: {pos_count}"
    )
    return msg

def handle_command(command: str):
    """Handle bot command."""
    handlers = {
        "/panel": cmd_panel,
        "/positions": cmd_positions,
        "/plan": cmd_plan,
        "/stats": cmd_stats,
        "/risk": cmd_risk,
        "/status": cmd_status,
        "/start": lambda: "🤖 <b>Hermes Trading Bot</b>\n\nدستورات:\n/panel - پنل سیستم\n/plan - پلن فعلی\n/positions - پوزیشن‌ها\n/stats - آمار\n/risk - ریسک\n/status - وضعیت",
    }
    
    handler = handlers.get(command)
    if handler:
        return handler()
    return "❌ دستور نامعتبر"

def main():
    """Main bot loop."""
    log("Command bot started")
    
    # Set commands
    api("setMyCommands", {
        "commands": json.dumps([
            {"command": "panel", "description": "پنل سیستم"},
            {"command": "plan", "description": "پلن فعلی"},
            {"command": "positions", "description": "پوزیشن‌های باز"},
            {"command": "stats", "description": "آمار معاملات"},
            {"command": "risk", "description": "پارامترهای ریسک"},
            {"command": "status", "description": "وضعیت سریع"},
        ])
    })
    
    offset = 0
    
    while True:
        try:
            result = api("getUpdates", {"offset": offset + 1, "timeout": 25})
            
            if not result.get("ok"):
                continue
            
            updates = result.get("result", [])
            
            for update in updates:
                offset = max(offset, update.get("update_id", 0))
                
                message = update.get("message", {})
                if not message:
                    continue
                
                chat_id = str(message.get("chat", {}).get("id", ""))
                if chat_id != TELEGRAM_CHAT_ID:
                    continue
                
                text = message.get("text", "")
                if not text.startswith("/"):
                    continue
                
                command = text.split()[0].lower()
                log(f"Command received: {command}")
                
                response = handle_command(command)
                send_message(response)
        
        except KeyboardInterrupt:
            log("Bot stopped")
            break
        except Exception as e:
            log(f"Error: {e}")
            continue

if __name__ == "__main__":
    main()
