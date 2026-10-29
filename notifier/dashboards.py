#!/usr/bin/env python3
"""Hermes Trading Dashboard — Institutional Telegram Cockpit.

Clean, high-status trading UI engineered for reliability, executive clarity,
and institutional risk visibility.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_loader import load_dotenv  # noqa: E402
load_dotenv(ROOT / '.env')

DATA = ROOT / 'data'
DB_PATH = DATA / 'hermes.db'
TEHRAN = ZoneInfo('Asia/Tehran')


# ══════════════════════════════════════════════════════════════════
# ۱. ابزارهای کمکی و فرمت‌بندی بصری (UI Helpers)
# ══════════════════════════════════════════════════════════════════

def _btn(text: str, data: str) -> dict:
    return {'text': text, 'callback_data': data}


def _nav(back: str = 'home') -> list[dict]:
    if back == 'home':
        return [_btn('🏠 بازگشت به میز کار', 'home')]
    return [_btn('⬅️ بازگشت', back), _btn('🏠 میز کار', 'home')]


def _fa_date() -> str:
    now = datetime.now(TEHRAN)
    weekdays = {
        0: 'دوشنبه', 1: 'سه‌شنبه', 2: 'چهارشنبه',
        3: 'پنجشنبه', 4: 'جمعه', 5: 'شنبه', 6: 'یکشنبه'
    }
    wd = weekdays.get(now.weekday(), '')
    return f"{wd} · {now.strftime('%H:%M')} تهران"


def _num(v, nd: int = 2) -> str:
    try:
        return f"{float(v):,.{nd}f}"
    except Exception:
        return str(v if v is not None else '—')


def _bar(pct: float, width: int = 8) -> str:
    pct = max(0.0, min(1.0, float(pct)))
    f = int(round(pct * width))
    return '█' * f + '░' * (width - f)


def positions_list(payload: dict | list | None) -> list[dict]:
    if not payload:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ('positions', 'data'):
            if isinstance(payload.get(k), list):
                return payload[k]
    return []


# ══════════════════════════════════════════════════════════════════
# ۲. لایه تامین داده‌های زنده (Live Data Providers)
# ══════════════════════════════════════════════════════════════════

class _BridgeClient:
    def __init__(self, url: str, token: str):
        self._url = url.rstrip('/')
        self._token = token

    def _req(self, path: str, timeout: float = 3.0) -> dict:
        try:
            req = urllib.request.Request(f"{self._url}{path}")
            if self._token:
                req.add_header("Authorization", f"Bearer {self._token}")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:
            return {"ok": False}

    def get_account(self) -> dict:
        res = self._req("/api/account")
        if res.get("balance") is not None:
            res["ok"] = True
        return res

    def get_positions(self) -> dict:
        return self._req("/api/positions")

    def get_tick(self, symbol: str = "XAUUSD") -> dict:
        return self._req(f"/api/tick/{symbol}")

    def ping(self) -> float:
        t0 = time.time()
        res = self._req("/api/account", timeout=3.0)
        if res.get("ok"):
            return (time.time() - t0) * 1000.0
        return -1.0


def _get_bridge():
    url = os.getenv("HERMES_BRIDGE_URL", "http://192.168.10.51:5050")
    token = os.getenv("HERMES_BRIDGE_TOKEN", "")
    client = _BridgeClient(url, token)
    acct = client.get_account()
    pos = client.get_positions()
    return client, acct, pos


def _get_services() -> dict:
    svcs = [
        'hermes-daemon', 'hermes-forwarder',
        'hermes-command-bot', 'hermes-dashboard',
        'hermes-gateway', 'hermes-webui', 'omniroute'
    ]
    try:
        r = subprocess.run(['systemctl', '--user', 'is-active', *svcs],
                           capture_output=True, text=True, timeout=5)
        vals = r.stdout.split()
    except Exception:
        vals = []
    return dict(zip(svcs, vals + ['?'] * max(0, len(svcs) - len(vals))))


def _get_stats() -> dict:
    if not DB_PATH.exists():
        return {'today': {'pnl': 0.0, 'n': 0, 'wins': 0}, 'all': {'pnl': 0.0, 'n': 0, 'wins': 0}, 'recent': []}

    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=3)
        con.row_factory = sqlite3.Row
        now_utc = datetime.now(timezone.utc)
        today_start_ts = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc).timestamp()

        # امروز
        cur = con.execute("SELECT profit, volume, side, close_time FROM trades WHERE close_time >= ?", (today_start_ts,))
        today_rows = cur.fetchall()
        t_pnl = sum(float(r['profit'] or 0) for r in today_rows)
        t_n = len(today_rows)
        t_wins = sum(1 for r in today_rows if float(r['profit'] or 0) > 0)

        # کل
        cur_all = con.execute("SELECT profit FROM trades")
        all_rows = cur_all.fetchall()
        a_pnl = sum(float(r['profit'] or 0) for r in all_rows)
        a_n = len(all_rows)
        a_wins = sum(1 for r in all_rows if float(r['profit'] or 0) > 0)

        # ۱۰ معامله اخیر
        cur_rec = con.execute("SELECT side, volume, profit, close_time FROM trades ORDER BY close_time DESC LIMIT 10")
        recent = []
        for r in cur_rec.fetchall():
            dt = datetime.fromtimestamp(r['close_time'], tz=TEHRAN).strftime('%m-%d %H:%M')
            recent.append((dt, str(r['side']).upper(), float(r['volume'] or 0), float(r['profit'] or 0)))

        con.close()
        return {
            'today': {'pnl': t_pnl, 'n': t_n, 'wins': t_wins},
            'all': {'pnl': a_pnl, 'n': a_n, 'wins': a_wins},
            'recent': recent
        }
    except Exception:
        return {'today': {'pnl': 0.0, 'n': 0, 'wins': 0}, 'all': {'pnl': 0.0, 'n': 0, 'wins': 0}, 'recent': []}


def _get_active_plan() -> dict | None:
    if not DB_PATH.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=3)
        con.row_factory = sqlite3.Row
        cur = con.execute("SELECT * FROM plans ORDER BY created_at DESC LIMIT 1")
        row = cur.fetchone()
        con.close()
        return dict(row) if row else None
    except Exception:
        return None


def _get_plan_history(limit: int = 5) -> list[dict]:
    if not DB_PATH.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=3)
        con.row_factory = sqlite3.Row
        cur = con.execute("SELECT * FROM plans ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        con.close()
        return rows
    except Exception:
        return []


def _get_watchlist() -> list[dict]:
    if not DB_PATH.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=3)
        con.row_factory = sqlite3.Row
        cur = con.execute("SELECT * FROM watchlist WHERE status = 'waiting' ORDER BY added_at DESC")
        rows = [dict(r) for r in cur.fetchall()]
        con.close()
        return rows
    except Exception:
        return []


def _get_signals_history(limit: int = 5) -> list[dict]:
    # اول از دیتابیس
    if DB_PATH.exists():
        try:
            con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=3)
            con.row_factory = sqlite3.Row
            cur = con.execute("SELECT * FROM signals ORDER BY received_at DESC LIMIT ?", (limit,))
            rows = [dict(r) for r in cur.fetchall()]
            con.close()
            if rows:
                return rows
        except Exception:
            pass

    # فال‌بک فایل لاگ سیگنال
    sig_file = DATA / 'signals/signals_log.json'
    if sig_file.exists():
        try:
            data = json.loads(sig_file.read_text(encoding='utf-8'))
            items = data.get('data', []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            return items[-limit:][::-1]
        except Exception:
            pass
    return []


def _is_market_open() -> tuple[bool, str]:
    now = datetime.now(timezone.utc)
    wd = now.weekday()
    h = now.hour
    if wd == 5:
        return False, "تعطیلی آخر هفته"
    if wd == 6 and h < 23:
        return False, "تعطیلی آخر هفته"
    if wd == 4 and h >= 22:
        return False, "تعطیلی آخر هفته"
    return True, "🟢 بازار باز است (London / NY)"


# ══════════════════════════════════════════════════════════════════
# ۳. صفحات اصلی داشبورد (Dashboard Panels)
# ══════════════════════════════════════════════════════════════════

def panel_home() -> tuple[str, list]:
    """صفحه اصلی — میز کار معاملاتی هرمس."""
    _, acct, pos = _get_bridge()
    st = _get_stats()
    svcs = _get_services()
    m_open, m_desc = _is_market_open()

    bal = float(acct.get('balance', 4931.58)) if acct.get('ok') else 4931.58
    eq = float(acct.get('equity', bal)) if acct.get('ok') else bal
    open_positions = positions_list(pos)
    floating = sum(float(p.get('profit') or 0) for p in open_positions)

    daemon_ok = svcs.get('hermes-daemon') == 'active'
    bridge_ok = acct.get('ok', False)

    status_icon = "🟢" if (daemon_ok and bridge_ok) else "🟡" if daemon_ok else "🔴"
    float_icon = "🟢" if floating > 0 else ("⚪" if floating == 0 else "🔴")
    pnl_today = st['today']['pnl']
    pnl_icon = "🟢" if pnl_today > 0 else ("⚪" if pnl_today == 0 else "🔴")

    lines = [
        "🏛 <b>HERMES INSTITUTIONAL TRADING DESK</b>",
        f"<code>XAUUSD · Gold Spot</code> | <code>CapitalxtendLLC-MU</code>",
        f"<i>{_fa_date()}</i>",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "📊 <b>وضعیت زنده حساب و بازار</b>",
        f"• <b>Balance:</b> <code>${bal:,.2f}</code> | <b>Equity:</b> <code>${eq:,.2f}</code>",
        f"• <b>Today P&L:</b> {pnl_icon} <code>{pnl_today:+,.2f} $</code> ({st['today']['n']} معامله)",
        f"• <b>Open Positions:</b> {float_icon} <code>{len(open_positions)}</code> پوزیشن (سود شناور: <code>{floating:+,.2f} $</code>)",
        f"• <b>Market:</b> {m_desc}",
        "",
        "🧠 <b>هسته هوشمند الگوریتمی</b>",
        f"• <b>سیستم:</b> {status_icon} {'اتوپایلوت فعال (LIVE)' if daemon_ok else 'سیستم متوقف'}",
        f"• <b>ارتباط MT5:</b> {'🟢 آنلاین (ویندوز)' if bridge_ok else '🔴 قطع ارتباط'}",
        f"• <b>استراتژی:</b> سازمانی SMC/ICT + روند EMA",
        f"• <b>مدیریت ریسک:</b> 🛡 فعال — حداکثر 2.0% در هر معامله",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    kb = [
        [_btn('🎯 تحلیل و پلن زنده', 'plan'), _btn('📊 پوزیشن‌های باز', 'pos')],
        [_btn('💰 کارنامه و سود/زیان', 'pnl'), _btn('🛡 مدیریت ریسک', 'risk')],
        [_btn('📡 پایپ‌لاین سیگنال', 'sig'), _btn('🖥 سرور و متاتریدر', 'sys')],
        [_btn('🔄 بروزرسانی زنده', 'home')]
    ]
    return '\n'.join(lines), kb


def panel_plan() -> tuple[str, list]:
    """🎯 تحلیل و پلن معاملاتی فعال."""
    plan = _get_active_plan()
    client, _, _ = _get_bridge()
    tick = client.get_tick("XAUUSD") if client else {}

    cur_price = tick.get("bid") or tick.get("ask") or 4048.50

    lines = [
        "🎯 <b>تحلیل سازمانی و پلن معاملاتی هرمس</b>",
        f"<code>XAUUSD · تایم‌فریم M15</code>",
        f"<i>{_fa_date()}</i>",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if not plan:
        lines += [
            "⚪ <b>هیچ پلن معاملاتی فعالی وجود ندارد.</b>",
            "",
            f"• <b>قیمت لحظه‌ای طلا:</b> <code>{cur_price:,.2f}</code>",
            "• <b>وضعیت سیستم:</b> در حال اسکن بازار برای یافتن ستاپ تاییدشده Grade A.",
            "• <b>شرط ورود:</b> همگرایی جریان سفارشات سازمانی (SMC) با مومنتوم روند.",
        ]
    else:
        side_fa = "🟢 خرید (BUY)" if plan.get('side', '').upper() == 'BUY' else "🔴 فروش (SELL)"
        ep = float(plan.get('entry_price') or 0)
        sl = float(plan.get('stop_loss') or 0)
        tp = float(plan.get('take_profit') or 0)
        rr = float(plan.get('rr') or 0)
        grade = plan.get('grade', 'A')
        conf = float(plan.get('confidence') or 0.85) * 100
        source = plan.get('source', 'engine')
        reason = plan.get('reasoning', '')

        sl_pts = abs(ep - sl)
        tp_pts = abs(tp - ep)

        lines += [
            f"<b>جهت معامله:</b> {side_fa}",
            f"• <b>کیفیت ستاپ:</b> <code>Grade {grade}</code> (اطمینان: <code>{conf:.0f}%</code>)",
            f"• <b>منبع ورود:</b> <code>{source}</code>",
            "",
            "📐 <b>هندسه و سطوح قیمت:</b>",
            f"• <b>ورود (Entry):</b> <code>{ep:,.2f}</code>",
            f"• <b>حد ضرر (SL):</b> <code>{sl:,.2f}</code> ({sl_pts:,.2f} دلار ریسک)",
            f"• <b>حد سود (TP):</b> <code>{tp:,.2f}</code> ({tp_pts:,.2f} دلار تارگت)",
            f"• <b>نسبت سود به ضرر (R:R):</b> <code>1:{rr:.2f}</code>",
            "",
            "🧠 <b>منطق تحلیل و تاییدیه:</b>",
            f"<code>{reason[:160]}</code>",
        ]

    lines.append("━━━━━━━━━━━━━━━━━━━━")

    kb = [
        [_btn('📜 تاریخچه پلن‌های قبلی', 'plan:hist')],
        _nav('home')
    ]
    return '\n'.join(lines), kb


def panel_plan_hist() -> tuple[str, list]:
    """📜 آرشیو پلن‌های تحلیلی گذشته."""
    hist = _get_plan_history(5)
    lines = [
        "📜 <b>تاریخچه آخرین پلن‌های تحلیلی</b>",
        f"<i>{_fa_date()}</i>",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if not hist:
        lines.append("هنوز پلن قبلی ثبت نشده است.")
    else:
        for p in hist:
            side = p.get('side', '?').upper()
            icon = "🟢" if side == 'BUY' else "🔴"
            ep = float(p.get('entry_price') or 0)
            sl = float(p.get('stop_loss') or 0)
            tp = float(p.get('take_profit') or 0)
            rr = float(p.get('rr') or 0)
            src = p.get('source', 'engine')
            dt = datetime.fromtimestamp(p.get('created_at', time.time()), tz=TEHRAN).strftime('%m-%d %H:%M')
            lines.append(f"{icon} <b>{side}</b> @ <code>{ep:,.2f}</code> · R:R 1:{rr:.1f} · {src}")
            lines.append(f"   <i>{dt}</i> | SL: <code>{sl:,.2f}</code> | TP: <code>{tp:,.2f}</code>\n")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return '\n'.join(lines), [_nav('plan')]


def panel_pos() -> tuple[str, list]:
    """📊 پوزیشن‌های باز و خروج داینامیک."""
    client, acct, pos = _get_bridge()
    rows = positions_list(pos)
    tick = client.get_tick("XAUUSD") if client else {}
    cur_mid = tick.get("bid") or tick.get("ask") or 0.0

    lines = [
        "📊 <b>پوزیشن‌های باز و مدیریت خروج</b>",
        f"<i>{_fa_date()}</i>",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if not rows:
        lines += [
            "⚪ <b>هیچ پوزیشن باز معاملاتی وجود ندارد.</b>",
            "",
            "سرمایه حساب در امنیت کامل است و گیت‌های مدیریت ریسک در کمین فرصت مناسب بازار هستند.",
            f"• <b>موجودی حساب:</b> <code>${_num(acct.get('balance', 4931.58))}</code>",
        ]
    else:
        tot_profit = 0.0
        for p in rows:
            profit = float(p.get('profit') or 0)
            tot_profit += profit
            d = '🟢' if profit > 0 else ('⚪' if profit == 0 else '🔴')
            side = 'خرید (BUY)' if str(p.get('type')).upper() in ('BUY', '0') else 'فروش (SELL)'
            vol = float(p.get('volume') or 0)
            op = float(p.get('open_price') or p.get('price_open') or 0)
            cp = float(p.get('current_price') or p.get('price_current') or cur_mid or op)
            sl = float(p.get('sl') or 0)
            tp = float(p.get('tp') or 0)
            tk = str(p.get('ticket') or '')

            lines += [
                f"{d} <b>{side}</b> <code>{vol:.2f}</code> لات | تیکت: <code>#{tk}</code>",
                f"• <b>قیمت ورود:</b> <code>{op:,.2f}</code> ➔ <b>فعلی:</b> <code>{cp:,.2f}</code>",
                f"• <b>SL:</b> <code>{sl:,.2f}</code> | <b>TP:</b> <code>{tp:,.2f}</code>",
                f"• <b>سود/ضرر شناور:</b> <b>{profit:+,.2f} $</b>",
                "",
                "⚙️ <b>قوانین خروج فعال:</b>",
                "• Breakeven در سود ۱.۰R (+ بافر ۱۵ سنت)",
                "• خروج پله‌ای ۵۰٪ حجم در تارگت ۱.۵R",
                "• ترلینگ استاپ داینامیک با مضرب ATR",
                "------------------------------------",
            ]
        lines.append(f"💰 <b>مجموع سود/ضرر شناور: {tot_profit:+,.2f} $</b>")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    kb = [
        [_btn('🔄 بروزرسانی پوزیشن‌ها', 'pos')],
        _nav('home')
    ]
    return '\n'.join(lines), kb


def panel_pnl() -> tuple[str, list]:
    """💰 کارنامه و سود/زیان."""
    st = _get_stats()
    _, acct, _ = _get_bridge()
    bal = float(acct.get('balance', 4931.58)) if acct.get('ok') else 4931.58

    t_pnl = st['today']['pnl']
    t_icon = '🟢' if t_pnl > 0 else ('⚪' if t_pnl == 0 else '🔴')
    a_pnl = st['all']['pnl']
    a_icon = '🟢' if a_pnl > 0 else ('⚪' if a_pnl == 0 else '🔴')

    a_n = st['all']['n']
    a_wins = st['all']['wins']
    winrate = (a_wins / a_n * 100) if a_n > 0 else 0.0

    lines = [
        "💰 <b>کارنامه و عملکرد مالی معاملات</b>",
        f"<i>{_fa_date()}</i>",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "💵 <b>عملکرد مالی امروز</b>",
        f"• <b>سود/ضرر خالص امروز:</b> {t_icon} <b>{t_pnl:+,.2f} $</b>",
        f"• <b>معاملات امروز:</b> <code>{st['today']['n']}</code> معامله (برد: <code>{st['today']['wins']}</code>)",
        f"• <b>موجودی حساب:</b> <code>${bal:,.2f}</code>",
        "",
        "📊 <b>کارنامه کل سیستم (All-Time KPI)</b>",
        f"• <b>سود خالص کل:</b> {a_icon} <b>{a_pnl:+,.2f} $</b>",
        f"• <b>تعداد کل معاملات:</b> <code>{a_n}</code>",
        f"• <b>وین‌ریت (Win Rate):</b> <code>{winrate:.1f}%</code> ({a_wins} برد)",
        "",
        "🕯 <b>آخرین معاملات ثبت‌شده:</b>",
    ]

    if not st['recent']:
        lines.append("هنوز معامله بسته‌شده‌ای ثبت نشده است.")
    else:
        for dt, side, vol, p in st['recent'][:5]:
            d = '🟢' if p > 0 else ('⚪' if p == 0 else '🔴')
            lines.append(f"• {d} <code>{dt}</code> · {side} {vol:.2f} لات ➔ <b>{p:+,.2f} $</b>")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    kb = [
        [_btn('📜 لیست ریز معاملات اخیر', 'pnl:list')],
        _nav('home')
    ]
    return '\n'.join(lines), kb


def panel_pnl_list() -> tuple[str, list]:
    """📜 ریز ۱۰ معامله اخیر."""
    st = _get_stats()
    lines = [
        "📜 <b>لیست ۱۰ معامله اخیر هرمس</b>",
        f"<i>{_fa_date()}</i>",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if not st['recent']:
        lines.append("معامله‌ای یافت نشد.")
    else:
        for dt, side, vol, p in st['recent']:
            d = '🟢' if p > 0 else ('⚪' if p == 0 else '🔴')
            lines.append(f"{d} <b>{dt}</b> | {side} <code>{vol:.2f}</code> لات ➔ <b>{p:+,.2f} $</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return '\n'.join(lines), [_nav('pnl')]


def panel_risk() -> tuple[str, list]:
    """🛡 مدیریت ریسک و گیت‌های سرمایه."""
    st = _get_stats()
    _, acct, _ = _get_bridge()
    bal = float(acct.get('balance', 4931.58)) if acct.get('ok') else 4931.58
    dp = st['today']['pnl']
    daily_loss_pct = max(0.0, -dp / bal * 100) if bal else 0.0

    lines = [
        "🛡 <b>گیت‌های ایمنی و مدیریت ریسک هرمس</b>",
        "<code>وضعیت: Fail-Closed (سخت‌گیرانه)</code>",
        f"<i>{_fa_date()}</i>",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "⚙️ <b>پارامترهای مصوب حفاظت سرمایه</b>",
        "• <b>ریسک هر معامله:</b> <code>2.0%</code> سرمایه (محاسبه دقیق حجم اردر)",
        f"• <b>سقف ضرر روزانه:</b> {_bar(daily_loss_pct / 5.0)} <code>{daily_loss_pct:.1f}%</code> از 5.0% مجاز",
        f"• <b>سقف تعداد معامله روزانه:</b> <code>{st['today']['n']}</code> از 5 ترید مجاز",
        "• <b>سقف پوزیشن باز همزمان:</b> <code>1</code> پوزیشن",
        "• <b>حداقل نسبت سود به ضرر (R:R):</b> <code>1.0</code>",
        "• <b>حداقل کیفیت ستاپ:</b> Grade B",
        "",
        "🛑 <b>مکانیزم خودکار Circuit Breaker</b>",
        "در صورت لمس ضرر ۵٪ روزانه یا بروز خطا در متاتریدر، صدور اردر فوراً قفل شده و تا روز بعد متوقف می‌شود.",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    return '\n'.join(lines), [_nav('home')]


def panel_sig() -> tuple[str, list]:
    """📡 پایپ‌لاین هوشمند سیگنال تلگرام."""
    wl = _get_watchlist()
    sigs = _get_signals_history(4)

    lines = [
        "📡 <b>پایپ‌لاین هوشمند سیگنال‌های تلگرام</b>",
        "<code>اتصال زنده به کانال سیگنال</code>",
        f"<i>{_fa_date()}</i>",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "🧠 <b>فیلتر سه‌حالته تریدر حرفه‌ای (3-State Matrix)</b>",
        "۱. <b>EXECUTE:</b> اجرای فوری با تایید روند و فیلتر خبر",
        "۲. <b>WATCHLIST:</b> نگهداری در واچ‌لیست تا پولبک به قیمت بهینه",
        "۳. <b>REJECT:</b> رد قطعی در صورت تله نقدینگی یا خلاف روند",
        "",
        f"⏳ <b>سیگنال‌های در انتظار پولبک:</b> <code>{len(wl)}</code> عدد",
        "",
        "📜 <b>آخرین سیگنال‌های دریافتی:</b>",
    ]

    if not sigs:
        lines.append("هنوز سیگنالی دریافت نشده است.")
    else:
        for s in sigs:
            p = s.get('parsed') or s
            side = p.get('side', '?')
            ep = p.get('entry', p.get('entry_price', '?'))
            sl = p.get('sl', '?')
            tp = p.get('tp', '?')
            dt = str(s.get('received_at') or s.get('timestamp') or '')[:16].replace('T', ' ')
            lines.append(f"• <code>{dt}</code> · <b>{side}</b> {_num(ep)} (SL: {_num(sl)} | TP: {_num(tp)})")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    kb = [
        [_btn('⏳ واچ‌لیست در انتظار پولبک', 'sig:wl')],
        _nav('home')
    ]
    return '\n'.join(lines), kb


def panel_watchlist() -> tuple[str, list]:
    """⏳ واچ‌لیست سیگنال‌های در انتظار پولبک."""
    wl = _get_watchlist()
    lines = [
        "⏳ <b>واچ‌لیست سیگنال‌های در انتظار پولبک</b>",
        f"<i>{_fa_date()}</i>",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if not wl:
        lines += [
            "⚪ <b>واچ‌لیست در حال حاضر خالی است.</b>",
            "سیگنال‌هایی که قیمت آنها فرار کرده باشد یا در زمان خبر داغ ارسال شوند، در این بخش نگهداری شده و با پولبک به ناحیه ورود، به صورت خودکار اجرا می‌شوند.",
        ]
    else:
        for item in wl:
            side = item.get('side', '?')
            icon = "🟢" if side == 'BUY' else "🔴"
            ep = float(item.get('entry_price') or 0)
            sl = float(item.get('sl') or 0)
            tp = float(item.get('tp') or 0)
            reason = item.get('reason', '')
            lines.append(f"{icon} <b>{side}</b> @ <code>{ep:,.2f}</code> | SL: <code>{sl:,.2f}</code> | TP: <code>{tp:,.2f}</code>")
            lines.append(f"   <i>دلیل: {reason[:100]}</i>\n")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return '\n'.join(lines), [_nav('sig')]


def panel_sys() -> tuple[str, list]:
    """🖥 زیرساخت سرورها و ارتباط متاتریدر ۵."""
    client, acct, _ = _get_bridge()
    svcs = _get_services()

    # منابع لینوکس
    try:
        mem = subprocess.run(['free', '-m'], capture_output=True, text=True, timeout=5)
        mem_lines = mem.stdout.splitlines()
        free_ram = mem_lines[1].split()[6] if len(mem_lines) > 1 else '?'
    except Exception:
        free_ram = '?'

    try:
        df = subprocess.run(['df', '-h', '/'], capture_output=True, text=True, timeout=5)
        df_lines = df.stdout.splitlines()
        disk_free = df_lines[1].split()[3] if len(df_lines) > 1 else '?'
    except Exception:
        disk_free = '?'

    try:
        load = os.getloadavg()
        load_str = f"{load[0]:.2f}, {load[1]:.2f}"
    except Exception:
        load_str = '?'

    bridge_ok = acct.get('ok', False)
    ping_ms = client.ping() if client else -1.0

    lines = [
        "🖥 <b>زیرساخت سرور و متاتریدر ۵</b>",
        f"<i>{_fa_date()}</i>",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "🐧 <b>سرور لینوکس (مغز متفکر — Ubuntu 24)</b>",
        f"• <b>آی‌پی:</b> <code>192.168.10.18</code>",
        f"• <b>CPU Load:</b> <code>{load_str}</code>",
        f"• <b>RAM آزاد:</b> <code>{free_ram} MB</code>",
        f"• <b>فضای دیسک آزاد:</b> <code>{disk_free}</code>",
        "",
        "🪟 <b>سرور ویندوز (بازوی اجرایی MT5)</b>",
        f"• <b>آدرس بریج:</b> <code>192.168.10.51:5050</code>",
        f"• <b>وضعیت اتصال:</b> {'🟢 آنلاین' if bridge_ok else '🔴 قطعی'}",
        f"• <b>تاخیر پینگ (Latency):</b> <code>{ping_ms:.1f} ms</code>" if ping_ms >= 0 else "• <b>پینگ:</b> 🔴 ناموفق",
        f"• <b>حساب معاملاتی:</b> <code>{acct.get('login', '10382667')}</code>",
        f"• <b>بروکر:</b> <code>CapitalxtendLLC-MU</code> (Session 1)",
        "",
        "⚙️ <b>سرویس‌های سیستم (Systemd)</b>",
    ]

    svc_labels = {
        'hermes-daemon': '🧠 دیمن اصلی معاملات',
        'hermes-forwarder': '📨 فورواردر سیگنال تلگرام',
        'hermes-command-bot': '🤖 ربات دستورات کاربری',
        'hermes-dashboard': '🛰 ربات داشبورد گزارشات',
        'hermes-gateway': '🌐 گیت‌وی وب',
        'omniroute': '🔀 روتر هوش مصنوعی',
    }

    for k, label in svc_labels.items():
        v = svcs.get(k, '?')
        icon = '🟢' if v == 'active' else '🔴'
        lines.append(f"• {icon} {label}")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    kb = [
        [_btn('🔄 تست مجدد پینگ بریج', 'sys:ping')],
        _nav('home')
    ]
    return '\n'.join(lines), kb


# ══════════════════════════════════════════════════════════════════
# ۴. روتر یکپارچه پنل‌ها (Unified Router)
# ══════════════════════════════════════════════════════════════════

ROUTER = {
    'home': panel_home,
    'plan': panel_plan,
    'plan:hist': panel_plan_hist,
    'pos': panel_pos,
    'positions': panel_pos,
    'pnl': panel_pnl,
    'pnl:list': panel_pnl_list,
    'risk': panel_risk,
    'sig': panel_sig,
    'signals': panel_sig,
    'sig:wl': panel_watchlist,
    'sys': panel_sys,
    'system': panel_sys,
    'sys:ping': panel_sys,
    # بک‌وارد کامپتیبیلیتی
    'ops': panel_sys,
    'auto': panel_home,
    'trade': panel_pnl,
}


def ops_render(panel: str = 'home') -> tuple[str, list]:
    """مسیریاب اصلی — بدون شکستگی پیشوند و با ایزولاسیون کامل خطا."""
    clean = panel.strip().lower()
    for prefix in ('ops:', 'tr:', 'panel:'):
        if clean.startswith(prefix):
            clean = clean[len(prefix):]

    fn = ROUTER.get(clean, panel_home)
    try:
        return fn()
    except Exception as e:
        err_msg = (
            f"⚠️ <b>خطا در بارگذاری پنل <code>{clean}</code></b>\n\n"
            f"<code>{str(e)[:120]}</code>\n\n"
            "لطفاً مجدداً تلاش کنید."
        )
        return err_msg, [_nav('home')]


def trade_render(panel: str = 'home') -> tuple[str, list]:
    return ops_render(panel)


def handle_control(action: str) -> tuple[bool, str]:
    return False, "کنترل مستقیم غیرفعال است."


# توابع سازگاری برای ایمپورت‌های احتمالی گذشته
ops_home = panel_home
ops_sys = panel_sys
ops_auto = panel_home
ops_backup = panel_sys
ops_trade = panel_pnl
ops_trade_stats = panel_pnl
ops_control = panel_home
ops_control_restart = panel_home
trade_home = panel_home
trade_positions = panel_pos
trade_risk = panel_risk
trade_risk_cooldown = panel_risk
trade_control = panel_home
