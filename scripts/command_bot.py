#!/usr/bin/env python3
""" scripts/command_bot.py — ربات تلگرامی مدیریت و استعلام وضعیت سیستم معاملاتی هرمس

دستورات:
/status - وضعیت سریع سیستم و موجودی زنده
/panel - داشبورد کامل حساب، مارجین و اتصالات
/positions - پوزیشن‌های باز جاری
/plan - آخرین پلن تحلیلی صادر شده توسط مغز هرمس
/stats - کارنامه و آمار معاملات ثبت‌شده در دیتابیس
/risk - پارامترهای فعال مدیریت ریسک و سرمایه
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# بارگذاری متغیرهای محیطی
ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
BRIDGE_URL = os.getenv("HERMES_BRIDGE_URL", "http://192.168.10.51:5050").rstrip("/")
BRIDGE_TOKEN = os.getenv("HERMES_BRIDGE_TOKEN", "")
DB_PATH = BASE_DIR / "data" / "hermes.db"
CONFIG_PATH = BASE_DIR / "config.yaml"
LOG_FILE = BASE_DIR / "logs" / "command_bot.log"


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def api(method: str, params: dict | None = None) -> dict:
    """فراخوانی تلگرام Bot API."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
        data = urllib.parse.urlencode(params or {}).encode("utf-8") if params else None
        req = urllib.request.Request(url, data=data) if data else urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=35) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        log(f"Telegram API error: {e}")
        return {"ok": False}


def send_message(text: str) -> bool:
    """ارسال پیام با فرمت HTML به چت کاربر."""
    res = api("sendMessage", {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    })
    return bool(res.get("ok"))


def bridge_get(endpoint: str) -> dict:
    """ارسال درخواست به پل ارتباطی متاتریدر روی ویندوز."""
    try:
        url = f"{BRIDGE_URL}{endpoint}"
        req = urllib.request.Request(url)
        if BRIDGE_TOKEN:
            req.add_header("Authorization", f"Bearer {BRIDGE_TOKEN}")
        with urllib.request.urlopen(req, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}


def load_config() -> dict:
    try:
        if CONFIG_PATH.exists():
            return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


# ══════════════════════════════════════════════════════════════════
# هندلرهای دستورات تلگرام
# ══════════════════════════════════════════════════════════════════

def cmd_status() -> str:
    """وضعیت سریع و زنده سیستم."""
    cfg = load_config()
    symbol = cfg.get("symbol", "XAUUSD")
    dry_run = cfg.get("dry_run", True)

    t0 = time.time()
    account = bridge_get("/api/account")
    dt_ms = round((time.time() - t0) * 1000, 1)

    if not account.get("ok"):
        return (
            "❌ <b>خطا در ارتباط با MetaTrader 5</b>\n\n"
            f"پل ارتباطی ({BRIDGE_URL}) پاسخ نداد.\n"
            f"خطا: <code>{account.get('error', 'Unknown')}</code>"
        )

    balance = float(account.get("balance", account.get("data", {}).get("balance", 0.0)))
    equity = float(account.get("equity", account.get("data", {}).get("equity", 0.0)))
    login = account.get("login", "?")

    # پوزیشن‌ها
    positions_resp = bridge_get("/api/positions")
    positions = positions_resp.get("data", [])
    if dry_run and not positions:
        # در حالت dry_run، دفتر شبیه‌سازی را هم بررسی کن
        sim_path = BASE_DIR / "data" / "sim_book.json"
        if sim_path.exists():
            try:
                sim_data = json.loads(sim_path.read_text())
                positions = sim_data.get("positions", [])
            except Exception:
                pass

    tick_resp = bridge_get(f"/api/tick/{symbol}")
    bid = tick_resp.get("bid", 0.0)
    ask = tick_resp.get("ask", 0.0)
    spread = round(ask - bid, 2) if ask and bid else 0.0

    mode_text = "DRY-RUN (شبیه‌ساز)" if dry_run else "LIVE (واقعی)"

    msg = (
        "✅ <b>وضعیت سیستم معاملاتی هرمس</b>\n\n"
        f"🟢 <b>اتصال بروکر:</b> آنلاین (حساب <code>{login}</code>)\n"
        f"⏱ <b>تاخیر پینگ:</b> <code>{dt_ms} ms</code>\n"
        f"💰 <b>موجودی (Balance):</b> <code>${balance:,.2f}</code>\n"
        f"📈 <b>ارزش سرمایه (Equity):</b> <code>${equity:,.2f}</code>\n"
        f"📊 <b>پوزیشن‌های باز:</b> <code>{len(positions)}</code> عدد\n"
        f"🏷 <b>نماد:</b> <code>{symbol}</code>\n"
        f"🎯 <b>قیمت طلا:</b> <code>{bid:,.2f} / {ask:,.2f}</code> (اسپرد: <code>{spread}</code>)\n"
        f"⚙️ <b>حالت اجرا:</b> <code>{mode_text}</code>"
    )
    return msg


def cmd_panel() -> str:
    """داشبورد جامع مالی و مارجین."""
    account = bridge_get("/api/account")
    if not account.get("ok"):
        return "❌ <b>خطا در دریافت اطلاعات حساب از بروکر</b>"

    balance = float(account.get("balance", 0.0))
    equity = float(account.get("equity", 0.0))
    margin = float(account.get("margin", 0.0))
    margin_free = float(account.get("margin_free", balance))
    login = account.get("login", "?")
    currency = account.get("currency", "USD")

    # سود/ضرر شناور جاری
    floating = equity - balance
    floating_emoji = "🟢" if floating >= 0 else "🔴"

    msg = (
        "🛰 <b>داشبورد مالی و حساب هرمس</b>\n\n"
        f"👤 <b>شماره حساب:</b> <code>{login}</code>\n"
        f"💵 <b>موجودی کل (Balance):</b> <code>${balance:,.2f} {currency}</code>\n"
        f"📈 <b>ارزش لحظه‌ای (Equity):</b> <code>${equity:,.2f} {currency}</code>\n"
        f"{floating_emoji} <b>شناوری جاری:</b> <code>{floating:+,.2f} {currency}</code>\n"
        f"🔒 <b>مارجین درگیر:</b> <code>${margin:,.2f}</code>\n"
        f"🔓 <b>مارجین آزاد:</b> <code>${margin_free:,.2f}</code>\n\n"
        f"⏰ <b>زمان سرور:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>"
    )
    return msg


def cmd_positions() -> str:
    """لیست و جزئیات پوزیشن‌های باز جاری."""
    cfg = load_config()
    dry_run = cfg.get("dry_run", True)

    resp = bridge_get("/api/positions")
    positions = resp.get("data", [])

    if dry_run and not positions:
        sim_path = BASE_DIR / "data" / "sim_book.json"
        if sim_path.exists():
            try:
                sim_data = json.loads(sim_path.read_text())
                positions = sim_data.get("positions", [])
            except Exception:
                pass

    if not positions:
        return "📊 <b>پوزیشن‌های باز</b>\n\nدر حال حاضر هیچ پوزیشن بازی وجود ندارد."

    symbol = cfg.get("symbol", "XAUUSD")
    tick_resp = bridge_get(f"/api/tick/{symbol}")
    cur_bid = float(tick_resp.get("bid") or 0.0)
    cur_ask = float(tick_resp.get("ask") or 0.0)

    msg = f"📊 <b>پوزیشن‌های باز ({len(positions)})</b>\n\n"
    for p in positions:
        ticket = p.get("ticket", "?")
        symbol = p.get("symbol", "XAUUSD")
        side_raw = str(p.get("side") or p.get("type", "BUY")).upper()
        is_buy = "BUY" in side_raw or side_raw == "0"
        direction = "🟢 خرید (BUY)" if is_buy else "🔴 فروش (SELL)"
        vol = float(p.get("volume") or 0.0)
        open_p = float(p.get("open_price") or p.get("price_open") or 0.0)
        cur_p = float(p.get("current_price") or p.get("price_current") or (cur_bid if is_buy else cur_ask) or open_p)
        sl = float(p.get("sl") or 0.0)
        tp = float(p.get("tp") or 0.0)
        profit = float(p.get("profit") or 0.0)
        p_emoji = "🟢" if profit >= 0 else "🔴"

        msg += (
            f"🎫 <b>تیکت:</b> <code>#{ticket}</code>\n"
            f"{direction} <code>{symbol}</code> | حجم: <code>{vol} lot</code>\n"
            f"💵 ورود: <code>{open_p:,.2f}</code> | فعلی: <code>{cur_p:,.2f}</code>\n"
            f"{p_emoji} سود/ضرر: <code>${profit:+,.2f}</code>\n"
            f"🛡 SL: <code>{sl:,.2f}</code> | 🎯 TP: <code>{tp:,.2f}</code>\n"
            "───────────────\n"
        )
    return msg


def cmd_plan() -> str:
    """نمایش آخرین پلن معاملاتی صادر شده از دیتابیس."""
    if not DB_PATH.exists():
        return "📋 <b>پلن معاملاتی</b>\n\nهنوز هیچ پلنی ثبت نشده است."

    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        plan = conn.execute("SELECT * FROM plans ORDER BY created_at DESC LIMIT 1").fetchone()
        conn.close()

        if not plan:
            return "📋 <b>پلن معاملاتی</b>\n\nهیچ پلنی در دیتابیس یافت نشد."

        side = plan["side"]
        side_fa = "🟢 خرید (BUY)" if side == "BUY" else "🔴 فروش (SELL)"
        status = plan["status"]
        status_badge = "✅ تایید شده" if status == "approved" else "🚫 رد شده توسط گیت"

        created_dt = datetime.fromtimestamp(plan["created_at"], timezone.utc).strftime("%H:%M:%S UTC")

        msg = (
            f"📋 <b>آخرین پلن تحلیلی مغز هرمس</b>\n\n"
            f"🆔 <b>شناسه:</b> <code>{plan['plan_id']}</code>\n"
            f"🏷 <b>نماد:</b> <code>{plan['symbol']}</code> ({plan['timeframe']})\n"
            f"📊 <b>جهت:</b> {side_fa}\n"
            f"⭐ <b>درجه کیفی (Grade):</b> <code>Grade {plan['grade']}</code>\n"
            f"💵 <b>قیمت ورود:</b> <code>{plan['entry_price']:,.2f}</code>\n"
            f"🛡 <b>حد ضرر (SL):</b> <code>{plan['stop_loss']:,.2f}</code>\n"
            f"🎯 <b>حد سود (TP):</b> <code>{plan['take_profit']:,.2f}</code> (RR: <code>{plan['rr']}</code>)\n"
            f"🚦 <b>وضعیت:</b> {status_badge}\n"
            f"⏰ <b>زمان صدور:</b> <code>{created_dt}</code>\n\n"
            f"📝 <b>دلیل و کانتکست:</b>\n<code>{plan['reasoning']}</code>"
        )
        return msg
    except Exception as e:
        return f"❌ خطا در خواندن پلن از دیتابیس: {e}"


def cmd_stats() -> str:
    """کارنامه آماری و عملکرد معاملات از دیتابیس."""
    if not DB_PATH.exists():
        return "📊 <b>آمار معاملات</b>\n\nدیتابیسی موجود نیست."

    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT 
                count(*) as total,
                sum(case when pnl > 0 then 1 else 0 end) as wins,
                sum(case when pnl <= 0 then 1 else 0 end) as losses,
                sum(pnl) as total_pnl
            FROM trades"""
        ).fetchone()
        conn.close()

        total = row["total"] or 0
        wins = row["wins"] or 0
        losses = row["losses"] or 0
        pnl = row["total_pnl"] or 0.0
        win_rate = (wins / total * 100.0) if total > 0 else 0.0

        pnl_emoji = "🟢" if pnl >= 0 else "🔴"

        msg = (
            "📊 <b>کارنامه و آمار معاملات هرمس</b>\n\n"
            f"🔢 <b>تعداد کل معاملات ثبت‌شده:</b> <code>{total}</code>\n"
            f"✅ <b>معاملات برنده:</b> <code>{wins}</code>\n"
            f"❌ <b>معاملات بازنده:</b> <code>{losses}</code>\n"
            f"📈 <b>نرخ برد (Win Rate):</b> <code>{win_rate:.1f}%</code>\n"
            f"{pnl_emoji} <b>سود/ضرر خالص کل:</b> <code>${pnl:+,.2f}</code>\n\n"
            f"<i>ثبت‌شده در دفتر کل شفاف data/hermes.db</i>"
        )
        return msg
    except Exception as e:
        return f"❌ خطا در خواندن آمار: {e}"


def cmd_risk() -> str:
    """نمایش تنظیمات و قوانین مدیریت ریسک و سرمایه."""
    cfg = load_config()
    gates = cfg.get("gates", {})
    pos_cfg = cfg.get("position", {})

    max_open = gates.get("max_open_positions", 1)
    max_daily_trades = gates.get("max_daily_trades", 5)
    risk_pct = gates.get("risk_per_trade_pct", 2.0)
    max_daily_loss = gates.get("max_daily_loss_pct", 5.0)
    min_rr = gates.get("min_rr", 1.0)
    max_spread = gates.get("max_spread_points", 3.0)

    partial_en = pos_cfg.get("partial_enabled", False)
    partial_rr = pos_cfg.get("partial_tp_rr", 1.5)
    be_rr = pos_cfg.get("breakeven_rr", 0.8)

    # خواندن وضعیت یادگیری تطبیقی از دیتابیس
    learning_min_rr = min_rr
    learning_grade = gates.get("min_grade", "B")
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            cur = conn.cursor()
            val_rr = cur.execute("SELECT value FROM params WHERE key='min_rr'").fetchone()
            val_gr = cur.execute("SELECT value FROM params WHERE key='min_grade'").fetchone()
            conn.close()
            if val_rr and val_rr[0]:
                learning_min_rr = float(val_rr[0])
            if val_gr and val_gr[0]:
                learning_grade = val_gr[0]
        except Exception:
            pass

    msg = (
        "🛡 <b>دروازه‌های امنیت و مدیریت ریسک هرمس (Fail-Closed)</b>\n\n"
        f"📊 <b>ریسک هر معامله:</b> <code>{risk_pct}% از اکوییتی حساب</code>\n"
        f"📉 <b>سقف ضرر مجاز روزانه:</b> <code>{max_daily_loss}%</code> (توقف کامل در صورت عبور)\n"
        f"🔢 <b>حداکثر ترید روزانه:</b> <code>{max_daily_trades} معامله</code>\n"
        f"📦 <b>حداکثر پوزیشن همزمان:</b> <code>{max_open} عدد</code>\n"
        f"🎯 <b>حداقل Risk/Reward:</b> <code>{learning_min_rr:.1f}</code> (کف: {min_rr})\n"
        f"⭐ <b>حداقل گرید ستاپ:</b> <code>Grade {learning_grade}</code>\n"
        f"⚡ <b>حداکثر اسپرد مجاز:</b> <code>{max_spread} دلار</code>\n"
        f"🎯 <b>سیو سود پله‌ای:</b> <code>{'فعال (۵۰٪ در سود ' + str(partial_rr) + 'R)' if partial_en else 'غیرفعال'}</code>\n"
        f"🔒 <b>انتقال به Breakeven:</b> <code>در سود {be_rr}R (+ بافر کارمزد)</code>"
    )
    return msg


def handle_command(command: str) -> str:
    handlers = {
        "/status": cmd_status,
        "/panel": cmd_panel,
        "/positions": cmd_positions,
        "/plan": cmd_plan,
        "/stats": cmd_stats,
        "/risk": cmd_risk,
        "/start": lambda: (
            "🤖 <b>سیستم معاملاتی هوشمند هرمس</b>\n\n"
            "دستورات در دسترس:\n"
            "• /status - استعلام سریع وضعیت، موجودی و اتصال\n"
            "• /panel - داشبورد مالی، مارجین و سود/ضرر\n"
            "• /positions - پوزیشن‌های باز جاری\n"
            "• /plan - آخرین پلن تحلیلی صادر شده\n"
            "• /stats - آمار و کارنامه معاملات\n"
            "• /risk - تنظیمات فعال مدیریت ریسک"
        ),
    }
    handler = handlers.get(command)
    if handler:
        return handler()
    return "❌ دستور نامعتبر است. از /start برای دیدن لیست دستورات استفاده کنید."


def main() -> None:
    log("Command bot started")

    api("setMyCommands", {
        "commands": json.dumps([
            {"command": "status", "description": "وضعیت سریع و موجودی"},
            {"command": "panel", "description": "داشبورد مالی و مارجین"},
            {"command": "positions", "description": "پوزیشن‌های باز جاری"},
            {"command": "plan", "description": "آخرین پلن معاملاتی"},
            {"command": "stats", "description": "آمار و کارنامه معاملات"},
            {"command": "risk", "description": "پارامترهای مدیریت ریسک"},
        ])
    })

    offset = 0
    while True:
        try:
            result = api("getUpdates", {"offset": offset + 1, "timeout": 25})
            if not result.get("ok"):
                time.sleep(1)
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

                text = message.get("text", "").strip()
                if not text.startswith("/"):
                    continue

                cmd = text.split()[0].lower()
                log(f"Handling command: {cmd}")
                reply = handle_command(cmd)
                send_message(reply)

        except KeyboardInterrupt:
            log("Command bot stopped")
            break
        except Exception as e:
            log(f"Loop error: {e}")
            time.sleep(1)


if __name__ == "__main__":
    main()
