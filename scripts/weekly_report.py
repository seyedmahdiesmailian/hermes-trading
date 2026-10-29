#!/usr/bin/env python3
"""Weekly management report for Hermes Trading System (Persian, Telegram-ready).

Collects: live balance/equity from MT5, 7-day trade stats from SQLite & broker,
funnel activity (plans vs trades), open positions, safety-gate guard activity,
and system changes (git) — prints a clean formatted report to stdout.
Cron-safe: never raises; on partial data failure prints what it has.
"""
import sys
import os
import time
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from core.params import load_config
from adapters.mt5 import Mt5Adapter

DAYS = 7
WEEK_S = DAYS * 86400
FA_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')

def fa(x):
    return str(x).translate(FA_DIGITS)

def money(v):
    sign = '+' if v >= 0 else '−'
    return f"{sign}{fa(f'{abs(v):,.2f}')}$"

def pct(v):
    return fa(f"{v:.1f}") + '٪'

def main():
    now = time.time()
    week_ago = now - WEEK_S
    lines = []

    # ── ۱. اتصال به بریج و استعلام اکانت زنده ──
    token = ""
    env_file = _ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("HERMES_BRIDGE_TOKEN="):
                token = line.split("=", 1)[1].strip()

    cfg = load_config(_ROOT / "config.yaml", bridge_token=token)
    mt5 = Mt5Adapter(cfg.bridge.url, cfg.bridge.token, cfg.bridge.timeout_s, dry_run=False)

    acct = None
    open_pos = []
    try:
        acct = mt5.get_account()
    except Exception as e:
        lines.append(f"⚠️ استعلام حساب از بریج با خطا مواجه شد: {e}")

    try:
        open_pos = mt5.get_open_positions(cfg.symbol)
    except Exception as e:
        lines.append(f"⚠️ استعلام پوزیشن‌های باز با خطا مواجه شد: {e}")

    # ── ۲. استخراج معاملات از SQLite و بروکر ──
    trades = []
    plans_week = 0
    guards_week = {}
    db_path = _ROOT / "data" / "hermes.db"

    if db_path.exists():
        try:
            con = sqlite3.connect(db_path)
            con.row_factory = sqlite3.Row
            # معاملات ۷ روز گذشته
            rows = con.execute(
                "SELECT * FROM trades WHERE closed_at >= ? ORDER BY closed_at ASC",
                (week_ago,)
            ).fetchall()
            trades = [dict(r) for r in rows]

            # تعداد پلن‌های ۷ روز گذشته
            row_p = con.execute(
                "SELECT count(*) FROM plans WHERE created_at >= ?",
                (week_ago,)
            ).fetchone()
            plans_week = row_p[0] if row_p else 0

            # گیت‌های فعال ۷ روز گذشته
            g_rows = con.execute(
                "SELECT reasons FROM guard_log WHERE ts >= ?",
                (week_ago,)
            ).fetchall()
            for gr in g_rows:
                r_txt = gr["reasons"] or ""
                for part in r_txt.replace("[", "").replace("]", "").replace("'", "").replace('"', '').split(","):
                    p = part.strip()
                    if p and p != "ok":
                        key = p.split("(")[0].strip()
                        guards_week[key] = guards_week.get(key, 0) + 1

            con.close()
        except Exception as e:
            lines.append(f"⚠️ خواندن دیتابیس هرمس با خطا مواجه شد: {e}")

    # محاسبه آمار ۷ روز گذشته
    n_trades = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    total_pnl = sum(t["pnl"] for t in trades)
    win_rate = (len(wins) / n_trades * 100) if n_trades > 0 else 0.0
    avg_win = (sum(w["pnl"] for w in wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(l["pnl"] for l in losses) / len(losses)) if losses else 0.0
    best_trade = max((t["pnl"] for t in trades), default=0.0)
    worst_trade = min((t["pnl"] for t in trades), default=0.0)

    # ── ۳. تاریخچه تغییرات سیستم (Git) ──
    git_commits = []
    try:
        cmd = [
            "git", "log", f"--since={DAYS} days", "--oneline",
            "--", "core/", "adapters/", "entry/", "notifier/", "scripts/", "config.yaml"
        ]
        res = subprocess.run(cmd, cwd=str(_ROOT), capture_output=True, text=True, check=True)
        git_commits = [c.strip() for c in res.stdout.strip().splitlines() if c.strip()]
    except Exception:
        pass

    # ── ۴. نگارش و قالب‌بندی نهایی گزارش (Telegram Markdown) ──
    t = time.localtime(now)
    report_lines = [
        f"📊 **گزارش هفتگی سامانه معاملاتی هرمس** — {fa(t.tm_year)}/{fa(f'{t.tm_mon:02d}')}/{fa(f'{t.tm_mday:02d}')}",
        ""
    ]

    # بخش حساب
    if acct:
        bal = acct.balance
        eq = acct.equity
        base = 5000.0
        ret_val = bal - base
        ret_pct = (ret_val / base) * 100.0
        report_lines.append(f"💰 **Balance:** {fa(f'{bal:,.2f}')}$ | **Equity:** {fa(f'{eq:,.2f}')}$")
        report_lines.append(f"📈 **بازدهی کل:** {money(ret_val)} ({pct(ret_pct)})")
    
    # پوزیشن‌های باز
    if open_pos:
        report_lines.append(f"🔓 **پوزیشن‌های باز:** {fa(len(open_pos))}")
        for p in open_pos[:5]:
            report_lines.append(
                f"   • {p.side.value} {fa(f'{p.volume:.2f}')} @ {fa(f'{p.open_price:,.2f}')} | P&L: {money(p.net_profit)}"
            )
    else:
        report_lines.append("🔒 **پوزیشن باز:** صفر (سیستم آماده شکار ستاپ)")

    report_lines.append("")

    # کارنامه ۷ روز اخیر
    report_lines.append(f"— **عملکرد ۷ روز گذشته** ({fa(n_trades)} معامله بسته) —")
    if n_trades > 0:
        report_lines.append(f"✅ برد: {fa(len(wins))} | ❌ باخت: {fa(len(losses))} | **وین‌ریت: {pct(win_rate)}**")
        report_lines.append(f"💵 سود خالص هفته: **{money(total_pnl)}**")
        report_lines.append(f"میانگین برد: {money(avg_win)} | میانگین باخت: {money(avg_loss)}")
        report_lines.append(f"بهترین معامله: {money(best_trade)} | بدترین: {money(worst_trade)}")
    else:
        report_lines.append("در ۷ روز گذشته معامله بسته‌شده‌ای ثبت نشد.")

    report_lines.append("")

    # قیف سیستم
    report_lines.append("— **قیف سیستم (Funnel)** —")
    conv_rate = (n_trades / plans_week * 100) if plans_week > 0 else 0.0
    report_lines.append(f"🧠 ستاپ‌های تحلیل‌شده: {fa(plans_week)} | تبدیل به معامله: {fa(n_trades)} ({pct(conv_rate)})")
    if guards_week:
        g_summary = " | ".join(f"{k} ×{fa(v)}" for k, v in list(guards_week.items())[:4])
        report_lines.append(f"🛡 **گیت‌های ایمنی فعال:** {g_summary}")

    report_lines.append("")

    # تغییرات گیت
    if git_commits:
        report_lines.append(f"— **تغییرات و ارتقای سیستم** ({fa(len(git_commits))} کامیت) —")
        for c in git_commits[:5]:
            report_lines.append(f"• `{c}`")
    
    if lines:
        report_lines.append("")
        report_lines.extend(lines)

    print("\n".join(report_lines))

if __name__ == "__main__":
    main()
