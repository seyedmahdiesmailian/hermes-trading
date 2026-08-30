#!/usr/bin/env python3
"""b38: shared Telegram dashboard renderer (inline-keyboard panels).

Two dashboards, one engine:
  OPS   (3rd bot)  -> system status, autopilot, backup/health, trades
  TRADE (2nd bot)  -> active plan, positions, today's PnL, safety gates

Every section is independently guarded: a missing file or dead bridge
degrades to 'نامعلوم' instead of raising, because these panels are read by
an operator who needs an answer even when things are broken.
"""
from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path('/home/ai/hermes-trading')
DATA = ROOT / 'data'
TEHRAN = timezone(timedelta(hours=3, minutes=30))


def _j(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default if default is not None else {}


def _ago(iso: str | None) -> str:
    if not iso:
        return '—'
    try:
        t = datetime.fromisoformat(str(iso).replace('Z', '+00:00'))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        m = (datetime.now(timezone.utc) - t).total_seconds() / 60
        if m < 0:                      # future timestamp -> countdown
            m = -m
            if m < 60:
                return f'{m:.0f} دقیقه دیگر'
            if m < 2880:
                return f'{m/60:.1f} ساعت دیگر'
            return f'{m/1440:.1f} روز دیگر'
        if m < 1:
            return 'همین الان'
        if m < 60:
            return f'{m:.0f} دقیقه پیش'
        if m < 2880:
            return f'{m/60:.1f} ساعت پیش'
        return f'{m/1440:.1f} روز پیش'
    except Exception:
        return '—'


def _num(v, nd: int = 2) -> str:
    try:
        return f'{float(v):.{nd}f}'
    except Exception:
        return str(v if v is not None else '—')


def _dot(ok: bool) -> str:
    return '🟢' if ok else '🔴'


def _bar(pct: float, width: int = 10) -> str:
    pct = max(0.0, min(1.0, pct))
    f = int(round(pct * width))
    return '█' * f + '░' * (width - f)


def _services() -> dict:
    try:
        r = subprocess.run(['systemctl', '--user', 'is-active',
                            'hermes-signal', 'hermes-position', 'hermes-gateway',
                            'hermes-dashboard'],
                           capture_output=True, text=True, timeout=10)
        vals = r.stdout.split()
    except Exception:
        vals = []
    names = ['hermes-signal', 'hermes-position', 'hermes-gateway', 'hermes-dashboard']
    return dict(zip(names, vals + ['?'] * max(0, len(names) - len(vals))))


def _bridge():
    try:
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from env_loader import load_dotenv
        load_dotenv(ROOT / '.env')
        from bridge_client import BridgeClient
        b = BridgeClient()
        return b, b.get_account(), b.get_positions()
    except Exception:
        return None, {}, {}


def _journal_today() -> dict:
    out = {'trades': 0, 'pnl': 0.0, 'wins': 0, 'recent': []}
    try:
        with (DATA / 'xau_plan/trade_journal.csv').open(encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return out
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    for r in rows:
        if str(r.get('journaled_at', '')).startswith(today):
            try:
                p = float(r.get('profit') or 0)
            except Exception:
                p = 0.0
            out['trades'] += 1
            out['pnl'] += p
            out['wins'] += 1 if p > 0 else 0
    for r in rows[-3:]:
        try:
            out['recent'].append((str(r.get('close_time', ''))[-8:-2] if len(str(r.get('close_time', ''))) > 8 else '—',
                                  r.get('side', '?'), float(r.get('profit') or 0)))
        except Exception:
            continue
    return out


# ══════════════════════ OPS BOT (3rd) ══════════════════════

OPS_PANELS = {
    'home': '🏠 خانه', 'sys': '🖥 سیستم', 'auto': '🤖 اتوپایلوت',
    'ops': '💾 بکاپ/سلامت', 'trade': '📊 ترید',
}
OPS_KEYBOARD = [[{'text': OPS_PANELS['home'], 'callback_data': 'ops:home'},
                 {'text': OPS_PANELS['sys'], 'callback_data': 'ops:sys'}],
                [{'text': OPS_PANELS['auto'], 'callback_data': 'ops:auto'},
                 {'text': OPS_PANELS['ops'], 'callback_data': 'ops:ops'}],
                [{'text': OPS_PANELS['trade'], 'callback_data': 'ops:trade'}]]


def _fmt_ts(t: datetime | None) -> str:
    return t.astimezone(TEHRAN).strftime('%H:%M:%S') if t else '—'


def ops_home() -> tuple[str, list]:
    svcs = _services()
    _, acct, _ = _bridge()
    ap = _j(DATA / 'ops/autopilot_state.json')
    bl = (DATA / 'ops/autopilot_backlog.md')
    done = todo = 0
    try:
        txt = bl.read_text(encoding='utf-8')
        done = txt.count('- [x]')
        todo = txt.count('- [ ]')
    except Exception:
        pass
    ks = _j(DATA / 'kill_switch_state.json')
    lines = [
        '🛰 <b>داشبورد هرمس</b>',
        f'<i>{datetime.now(TEHRAN).strftime("%A %d %B — %H:%M تهران")}</i>',
        '',
        f'{_dot(all(v == "active" for v in svcs.values()))} سرویس‌ها: '
        + ' · '.join(f'{k.replace("hermes-","")}={v}' for k, v in svcs.items()),
        f'{_dot(bool(acct.get("ok")))} بریج: '
        + (f'بالانس {acct.get("balance", "?")} $' if acct.get('ok') else 'دسترس نیست'),
        f'{_dot(not ks.get("halted"))} ترید: ' + ('متوقف (kill switch)' if ks.get('halted') else 'فعال'),
        f'🤖 اتوپایلوت: آخرین اجرا {_ago(ap.get("last_run_utc"))} · بک‌لاگ {done}/{done+todo}',
        '',
        'پنل را انتخاب کن 👇',
    ]
    return '\n'.join(lines), OPS_KEYBOARD


def ops_system() -> tuple[str, list]:
    svcs = _services()
    hb = ''
    try:
        hb = (DATA / 'xau_plan/watchdog_heartbeat').read_text().strip()
    except Exception:
        pass
    try:
        disk = subprocess.run(['df', '-h', '--output=pcent,avail', '/'],
                              capture_output=True, text=True, timeout=10).stdout.splitlines()[-1].split()
        disk_s = f'{disk[0]} استفاده · {disk[1]} آزاد'
    except Exception:
        disk_s = 'نامعلوم'
    try:
        mem = subprocess.run(['free', '-m'], capture_output=True, text=True, timeout=10).stdout.splitlines()[1].split()
        mem_s = f'{mem[2]}/{mem[1]} MB رمز مصرف'
    except Exception:
        mem_s = 'نامعلوم'
    lines = [
        '🖥 <b>وضعیت سیستم</b>',
        '',
        '🧩 <b>سرویس‌ها (systemd user)</b>',
    ]
    for k, v in svcs.items():
        lines.append(f'{_dot(v == "active")} <code>{k}</code> — {v}')
    lines += [
        '',
        f'💓 ضربان واتچ‌داگ: {_ago(hb) if hb else "بی‌خبر"}',
        f'💽 دیسک ریشه: {disk_s}',
        f'🧠 RAM: {mem_s}',
        f'🕐 ساعت سرور: {datetime.now(TEHRAN).strftime("%H:%M:%S")} تهران',
    ]
    return '\n'.join(lines), OPS_KEYBOARD


def ops_autopilot() -> tuple[str, list]:
    ap = _j(DATA / 'ops/autopilot_state.json')
    bl = DATA / 'ops/autopilot_backlog.md'
    todo, done = [], []
    try:
        for ln in bl.read_text(encoding='utf-8').splitlines():
            if ln.startswith('- [ ]'):
                todo.append(ln[5:].strip())
            elif ln.startswith('- [x]'):
                done.append(ln[5:].strip())
    except Exception:
        pass
    lines = ['🤖 <b>اتوپایلوت</b>', '',
             f'⏱ آخرین اجرا: {_ago(ap.get("last_run_utc"))}',
             f'📈 بک‌لاگ: {len(done)} انجام‌شده · {len(todo)} در صف', '']
    if todo:
        lines.append('🔜 <b>صف بعدی:</b>')
        lines += [f'· {t[:100]}' for t in todo[:4]]
    if done:
        lines += ['', '✅ <b>تازه انجام‌شده:</b>']
        lines += [f'· {d[:100]}' for d in done[-3:]]
    rc = ap.get('recent_commits') or []
    if rc:
        lines += ['', '🔨 <b>آخرین کامیت‌ها:</b>']
        lines += [f'<code>{c[:95]}</code>' for c in rc[:4]]
    return '\n'.join(lines), OPS_KEYBOARD


def ops_backup() -> tuple[str, list]:
    bh = _j(DATA / 'bridge_health_state.json')
    log = DATA.parent.parent / 'hermes-trading/logs/offsite_backup.log'
    last = ''
    try:
        for ln in log.read_text(errors='ignore').splitlines()[::-1]:
            if 'backup' in ln.lower() or 'OK' in ln:
                last = ln.strip()[:120]
                break
    except Exception:
        pass
    try:
        r = subprocess.run(['git', '-C', str(ROOT), 'status', '-sb'],
                           capture_output=True, text=True, timeout=15).stdout.splitlines()[0]
        sync = 'کاملاً سینک ✓' if 'ahead' not in r and 'behind' not in r else r.replace('## ', '')
    except Exception:
        sync = 'نامعلوم'
    lines = [
        '💾 <b>بکاپ و سلامت</b>',
        '',
        f'🌙 بکاپ آفشور: هر شب ۰۳:۱۵ تهران → ویندوز C:\\HermesBackups',
        f'📄 آخرین خط لاگ: <code>{last or "—"}</code>',
        f'🔗 گیت‌هاب: {sync}',
        f'🩺 بریج: {bh.get("fails", 0)} شکست متوالی',
        '',
        '📌 بازیابی فاجعه: <code>docs/DEPLOY.md</code> (۶ مرحله، کپی‌پیست)',
    ]
    return '\n'.join(lines), OPS_KEYBOARD


def ops_trades() -> tuple[str, list]:
    jt = _journal_today()
    perf = _j(DATA / 'xau_plan/performance_state.json')
    lines = [
        '📊 <b>تریدها (از دید سیستم)</b>',
        '',
        f'🗓 امروز: {jt["trades"]} ترید · PnL {jt["pnl"]:+.2f}$ · برد {jt["wins"]}',
        f'📉 ضرر متوالی: {perf.get("loss_streak", 0)} · بالانس شروع روز: {perf.get("starting_balance", "?")} $',
    ]
    if jt['recent']:
        lines += ['', '🕯 آخرین خروج‌ها:']
        for t, side, p in jt['recent']:
            lines.append(f'· {t} {side} → {p:+.2f}$')
    return '\n'.join(lines), OPS_KEYBOARD


OPS_RENDER = {'home': ops_home, 'sys': ops_system, 'auto': ops_autopilot,
              'ops': ops_backup, 'trade': ops_trades}


def ops_render(panel: str) -> tuple[str, list]:
    fn = OPS_RENDER.get(panel, ops_home)
    try:
        return fn()
    except Exception as e:
        return f'🔴 پنل {panel} خطا داد: {str(e)[:120]}', OPS_KEYBOARD


# ══════════════════════ TRADE BOT (2nd) ══════════════════════

TRADE_PANELS = {
    'home': '🏠 خانه', 'plan': '🎯 پلن', 'pos': '📌 پوزیشن',
    'pnl': '💰 سود/ضرر', 'risk': '🛡 ریسک',
}
TRADE_KEYBOARD = [[{'text': TRADE_PANELS['home'], 'callback_data': 'tr:home'},
                   {'text': TRADE_PANELS['plan'], 'callback_data': 'tr:plan'}],
                  [{'text': TRADE_PANELS['pos'], 'callback_data': 'tr:pos'},
                   {'text': TRADE_PANELS['pnl'], 'callback_data': 'tr:pnl'}],
                  [{'text': TRADE_PANELS['risk'], 'callback_data': 'tr:risk'}]]


def trade_home() -> tuple[str, list]:
    plan = _j(DATA / 'xau_plan/current_plan.json')
    _, acct, pos = _bridge()
    ks = _j(DATA / 'kill_switch_state.json')
    rt = _j(DATA / 'xau_plan/runtime_state.json')
    q = plan.get('quality') or {}
    jt = _journal_today()
    lines = [
        '📈 <b>هرمس تریدر — داشبورد</b>',
        f'<i>{datetime.now(TEHRAN).strftime("%A %d %B — %H:%M تهران")}</i>',
        '',
        f'{_dot(bool(acct.get("ok")))} بالانس: '
        + (f'<b>{acct.get("balance")} $</b> · equity {acct.get("equity")}' if acct.get('ok') else 'بریج قطع'),
        f'{_dot(not ks.get("halted"))} وضعیت: ' + ('⛔ متوقف' if ks.get('halted') else '✅ فعال'),
        f'🎯 بایز پلن: <b>{plan.get("bias", "—")}</b> · کیفیت {q.get("alignment", "—")}',
        f'📌 پوزیشن باز: {pos.get("count", 0)}',
        f'💰 امروز: {jt["trades"]} ترید · {jt["pnl"]:+.2f}$',
        f'🔄 آخرین گام: <code>{rt.get("last_step", "—")}</code>',
        '',
        'جزئیات را انتخاب کن 👇',
    ]
    return '\n'.join(lines), TRADE_KEYBOARD


def trade_plan() -> tuple[str, list]:
    plan = _j(DATA / 'xau_plan/current_plan.json')
    ex = plan.get('execution') or {}
    q = plan.get('quality') or {}
    votes = q.get('bias_votes') or {}
    tgts = plan.get('targets') or []
    lines = [
        f'🎯 <b>پلن فعال</b> <code>{plan.get("plan_id", "—")}</code>',
        '',
        f'جهت: <b>{plan.get("bias", "—")}</b> · سشن: {plan.get("session", "—")} · ATR {_num(plan.get("atr"))}',
        f'حالت ورود: <code>{ex.get("entry_mode", "—")}</code>',
    ]
    if ex.get('breakout_trigger'):
        lines.append(f'⚡ تریگر بریک‌اوت: {ex["breakout_trigger"]}')
    if ex.get('pullback_trigger'):
        lines.append(f'↩️ تریگر پول‌بک: {ex["pullback_trigger"]}')
    if ex.get('scale_in_levels'):
        lines.append(f'🪜 پله‌های ورود: {", ".join(str(x) for x in ex["scale_in_levels"])}')
    if tgts:
        lines.append(f'🎏 TPها: {", ".join(str(x) for x in tgts)}')
    if votes:
        lines += ['', '🗩 رأی تایم‌فریم‌ها:']
        for tf, v in votes.items():
            d = {'bullish': '🟢', 'bearish': '🔴'}.get(v, '⚪')
            lines.append(f'{d} {tf.upper()}: {v}')
    lines += ['', f'⏳ اعتبار تا: {_ago(plan.get("expires_at"))}',
              f'🔁 بازبینی بعدی: {_ago(plan.get("next_reassessment"))}']
    return '\n'.join(lines), TRADE_KEYBOARD


def trade_positions() -> tuple[str, list]:
    _, acct, pos = _bridge()
    rows = pos.get('data') or []
    if not rows:
        return ('📌 <b>پوزیشن‌ها</b>\n\nهیچ پوزیشن بازی نیست.\n\n'
                f'💵 بالانس: {acct.get("balance", "?")} $ · equity {acct.get("equity", "?")} $',
                TRADE_KEYBOARD)
    lines = ['📌 <b>پوزیشن‌های باز</b>', '']
    tot = 0.0
    for p in rows:
        try:
            profit = float(p.get('profit') or 0)
            tot += profit
            sl = p.get('sl') or '—'
            tp = p.get('tp') or '—'
            lines.append(
                f'#{p.get("ticket")} · <b>{p.get("type")}</b> {p.get("volume")} لات @ {p.get("open_price")}\n'
                f'   SL {sl} | TP {tp} | فعلی {p.get("current_price")} → <b>{profit:+.2f}$</b>')
        except Exception:
            continue
    lines += ['', f'🧮 جمع شناور: <b>{tot:+.2f}$</b>',
              f'💵 equity: {acct.get("equity", "?")} $']
    return '\n'.join(lines), TRADE_KEYBOARD


def trade_pnl() -> tuple[str, list]:
    perf = _j(DATA / 'xau_plan/performance_state.json')
    jt = _journal_today()
    bal = perf.get('starting_balance') or 0
    dp = perf.get('daily_pnl') or 0
    lines = [
        '💰 <b>سود و ضرر</b>',
        '',
        f'🗓 PnL امروز: <b>{dp:+.2f}$</b>',
        f'📊 ژورنال امروز: {jt["trades"]} ترید · برد {jt["wins"]} · {jt["pnl"]:+.2f}$',
        f'🏦 بالانس شروع روز: {bal} $',
        f'🔻 ضرر متوالی: {perf.get("loss_streak", 0)}',
    ]
    if bal:
        pct = max(-1.0, min(1.0, dp / bal))
        lines += ['', f'{_bar(0.5 + pct/2)}  {pct*100:+.2f}% از بالانس']
    if jt['recent']:
        lines += ['', '🕯 آخرین خروج‌ها:']
        for t, side, p in jt['recent']:
            lines.append(f'· {t} {side} → {p:+.2f}$')
    return '\n'.join(lines), TRADE_KEYBOARD


def trade_risk() -> tuple[str, list]:
    ks = _j(DATA / 'kill_switch_state.json')
    cd = _j(DATA / 'cooldown_state.json')
    perf = _j(DATA / 'xau_plan/performance_state.json')
    try:
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from engines.market_hours import is_market_open, closed_reason
        mk = f'🟢 باز' if is_market_open() else '🔴 بسته'
        if not is_market_open():
            mk += f' ({closed_reason()})'
    except Exception:
        mk = 'نامعلوم'
    lines = [
        '🛡 <b>گیت‌های ایمنی</b>',
        '',
        f'{_dot(not ks.get("halted"))} Kill Switch: '
        + (f'<b>متوقف</b> — {ks.get("halt_reason")}' if ks.get('halted') else 'فعال (ترید مجاز)'),
        f'🔻 ضرر متوالی: {ks.get("consecutive_losses", 0)} · امروز {perf.get("trades_today", 0)} ترید',
        f'🕐 بازار طلا: {mk}',
    ]
    rs = (cd.get('restart') or {}).get('until')
    if rs:
        try:
            t = datetime.fromisoformat(str(rs).replace('Z', '+00:00'))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if t > datetime.now(timezone.utc):
                lines.append(f'⏸ کول‌داون ریستارت تا: {t.astimezone(TEHRAN).strftime("%H:%M")} تهران')
            else:
                lines.append('⏸ کول‌داون ریستارت: تمام شده')
        except Exception:
            pass
    for k, v in cd.items():
        if k.startswith('_') or k == 'restart':
            continue
        until = (v or {}).get('until') if isinstance(v, dict) else None
        if until:
            lines.append(f'⏳ {k}: تا {_ago(until)}')
    return '\n'.join(lines), TRADE_KEYBOARD


TRADE_RENDER = {'home': trade_home, 'plan': trade_plan, 'pos': trade_positions,
                'pnl': trade_pnl, 'risk': trade_risk}


def trade_render(panel: str) -> tuple[str, list]:
    fn = TRADE_RENDER.get(panel, trade_home)
    try:
        return fn()
    except Exception as e:
        return f'🔴 پنل {panel} خطا داد: {str(e)[:120]}', TRADE_KEYBOARD
