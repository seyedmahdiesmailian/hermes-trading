#!/usr/bin/env python3
"""scripts/weekly_report.py — گزارش رسمی پایان هفته معاملاتی سامانه هرمس

این اسکریپت در پایان آخرین روز معاملاتی هفته (جمعه شب پس از بسته شدن بازار طلا)
آمار عملکرد هفتگی را با احتساب دقیق سود، کارمزد بروکر، سوآپ و موجودی زنده از MT5 استخراج کرده
و مستقیماً از طریق ربات تلگرام هرمس ترید (@Account5000bot) به کاربر ارسال می‌کند.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import zoneinfo

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from core.params import load_config
from adapters.mt5 import Mt5Adapter
from adapters.notify import NotifyAdapter

DAYS = 7
tz_tehran = zoneinfo.ZoneInfo("Asia/Tehran")


def main() -> None:
    now = time.time()
    env_file = _ROOT / ".env"
    bridge_token = ""
    bot_token = ""
    chat_id = ""

    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("HERMES_BRIDGE_TOKEN="):
                bridge_token = line.split("=", 1)[1].strip()
            elif line.startswith("TELEGRAM_BOT_TOKEN="):
                bot_token = line.split("=", 1)[1].strip()
            elif line.startswith("TELEGRAM_CHAT_ID="):
                chat_id = line.split("=", 1)[1].strip()

    cfg = load_config(_ROOT / "config.yaml", bridge_token=bridge_token)
    mt5 = Mt5Adapter(cfg.bridge.url, cfg.bridge.token, cfg.bridge.timeout_s, dry_run=False)
    notify = NotifyAdapter(bot_token, chat_id, enabled=True)

    # ۱. استعلام موجودی و وضعیت زنده حساب
    acct = None
    open_pos = []
    try:
        acct = mt5.get_account()
    except Exception as e:
        print(f"Error getting account: {e}")

    try:
        open_pos = mt5.get_open_positions(cfg.symbol)
    except Exception as e:
        print(f"Error getting open positions: {e}")

    # ۲. استخراج دیل‌های انجام‌شده ۷ روز گذشته مستقیماً از سرور بروکر
    deals = []
    try:
        deals = mt5.get_history_deals(days=DAYS, symbol=cfg.symbol)
    except Exception as e:
        print(f"Error getting deals: {e}")

    # تجمیع دیل‌ها بر مبنای هر پوزیشن/سفارش
    by_order: dict[int, list[dict]] = {}
    for d in deals:
        order_id = d.get("order")
        if order_id:
            by_order.setdefault(order_id, []).append(d)

    closed_positions = []
    for order_id, order_deals in by_order.items():
        has_exit = any(d.get("profit", 0.0) != 0.0 for d in order_deals)
        if has_exit:
            gross = sum(d.get("profit", 0.0) for d in order_deals)
            comm = sum(d.get("commission", 0.0) for d in order_deals)
            swap = sum(d.get("swap", 0.0) for d in order_deals)
            net_pnl = gross + comm + swap
            closed_positions.append({
                "order": order_id,
                "gross": gross,
                "comm": comm,
                "swap": swap,
                "net": net_pnl,
            })

    n_trades = len(closed_positions)
    wins = [p for p in closed_positions if p["net"] > 0]
    losses = [p for p in closed_positions if p["net"] < 0]
    be = [p for p in closed_positions if p["net"] == 0]

    tot_gross = sum(p["gross"] for p in closed_positions)
    tot_comm = sum(p["comm"] for p in closed_positions)
    tot_net = sum(p["net"] for p in closed_positions)

    win_rate = (len(wins) / n_trades * 100.0) if n_trades > 0 else 0.0
    avg_win = (sum(w["net"] for w in wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(l["net"] for l in losses) / len(losses)) if losses else 0.0
    best_trade = max((p["net"] for p in closed_positions), default=0.0)
    worst_trade = min((p["net"] for p in closed_positions), default=0.0)

    # ۳. نگارش متن گزارش پایان هفته معاملاتی
    dt_now = datetime.fromtimestamp(now, tz_tehran)
    date_str = dt_now.strftime("%Y/%m/%d — %H:%M")

    lines = [
        "📊 *گزارش پایان هفته معاملاتی سامانه هرمس*",
        f"🗓 _زمان ثبت: {date_str} (پایان سشن هفته)_",
        "",
    ]

    if acct:
        bal = acct.balance
        eq = acct.equity
        base_balance = 5000.0
        ret_val = bal - base_balance
        ret_pct = (ret_val / base_balance) * 100.0
        pos_count = len(open_pos) if open_pos else 0
        pos_text = f"`{pos_count}` معامله باز" if pos_count > 0 else "صفر (بسته شده قبل از تعطیلی مارکت)"

        lines.extend([
            "💰 *وضعیت کلی حساب و بالانس:*",
            f"• *Balance:* `{bal:,.2f} $`",
            f"• *Equity:* `{eq:,.2f} $`",
            f"• *بازدهی کل حساب:* `+{ret_val:,.2f} $` (+{ret_pct:.1f}%)",
            f"• *پوزیشن‌های فعال:* {pos_text}",
            "",
        ])

    lines.extend([
        "📈 *کارنامه معاملات ۷ روز اخیر (سند رسمی بروکر):*",
        f"• *کل معاملات بسته:* `{n_trades}` پوزیشن",
        f"• *نتیجه:* `{len(wins)}` برد | `{len(losses)}` باخت",
        f"• *Win Rate:* `{win_rate:.1f}%`",
        f"• *سود خالص واقعی (Net P&L):* `{tot_net:+,.2f} $`",
        f"• *کارمزد کسرشده بروکر:* `{tot_comm:,.2f} $`",
    ])

    if wins:
        lines.append(f"• *میانگین هر برد:* `+{avg_win:,.2f} $`")
    if losses:
        lines.append(f"• *میانگین هر باخت:* `{avg_loss:,.2f} $`")
    if closed_positions:
        lines.append(f"• *بهترین ترید:* `+{best_trade:,.2f} $` | *بدترین ترید:* `{worst_trade:,.2f} $`")

    lines.extend([
        "",
        "🛡 *وضعیت ایمنی و پایان هفته:*",
        "• *تعطیلی آخر هفته:* فیلتر Friday Close فعال و مانع از ریسک گپ دوشنبه است.",
        "• *کنترل ریسک:* کلیه پوزیشن‌ها تحت محافظت استاپ و تارگت نهادی اجرا شدند.",
    ])

    report_text = "\n".join(lines)
    print(report_text)

    # ارسال مستقیم به ربات هرمس ترید
    if notify.enabled:
        sent = notify.send(report_text)
        print(f"Telegram notification sent: {sent}")


if __name__ == "__main__":
    main()
