#!/usr/bin/env python3
"""b39: Telegram dashboards — managerial redesign.

Two dashboards, one engine:
  OPS   (3rd bot)  -> system status, autopilot narrative, backup/health, trades
  TRADE (2nd bot)  -> balance, plan, positions, PnL, safety gates vs limits

Design rules (user feedback b38: "مدیریتی‌تر، کاربردی‌تر"):
  - one verdict line at the top: is everything OK or what is wrong
  - grouped sections (مالی / ایمنی / سیستم) instead of a flat dump
  - every risk number shown against its LIMIT (0/4 not just 0)
  - countdowns: when the market reopens, when the plan expires
  - plain Persian, no raw JSON keys, no code identifiers
Every section is independently guarded: a missing file or dead bridge
degrades to 'نامعلوم' instead of raising.
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
WEEK_FA = ['دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه', 'شنبه', 'یکشنبه']


def _j(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default if default is not None else {}


def _fa_date(now: datetime | None = None) -> str:
    now = now or datetime.now(TEHRAN)
    return f'{WEEK_FA[now.weekday()]} · {now.strftime("%H:%M")} تهران'


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
        return f'{float(v):,.{nd}f}'
    except Exception:
        return str(v if v is not None else '—')


def _dot(ok: bool) -> str:
    return '🟢' if ok else '🔴'


def _bar(pct: float, width: int = 8) -> str:
    pct = max(0.0, min(1.0, pct))
    f = int(round(pct * width))
    return '█' * f + '░' * (width - f)


def _sec(title: str) -> str:
    return f'\n<b>{title}</b>\n'


def _row(label: str, value: str) -> str:
    return f'{label}: {value}'


def _market_state() -> tuple[bool, str, str]:
    """(open?, reason-if-closed, human countdown to the next change)."""
    try:
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from engines.market_hours import is_market_open, closed_reason
        now = datetime.now(timezone.utc)
        open_now = bool(is_market_open(now))
        # coarse scan (15-min steps, max 4 days), then refine to the minute
        flip, flip_open = '—', None
        for i in range(1, 385):
            t = now + timedelta(minutes=15 * i)
            if bool(is_market_open(t)) != open_now:
                flip_open = bool(is_market_open(t))
                lo = t - timedelta(minutes=15)
                for m in range(1, 16):
                    c = lo + timedelta(minutes=m)
                    if bool(is_market_open(c)) == flip_open:
                        flip = c.astimezone(TEHRAN).strftime('%H:%M')
                        break
                break
        reason = '' if open_now else (closed_reason(now) or '')
        if reason == 'market_closed':
            reason = 'تعطیلی آخر هفته'
        return open_now, reason, (flip, flip_open)
    except Exception:
        return False, '', ('—', None)


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


_SVC_LABEL = {'hermes-signal': 'سیگنال', 'hermes-position': 'پوزیشن',
              'hermes-gateway': 'گیت‌وی', 'hermes-dashboard': 'داشبورد'}


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


def _journal() -> dict:
    """Today + last-10 stats from the trade journal."""
    out = {'trades': 0, 'pnl': 0.0, 'wins': 0, 'recent': [],
           'l10_trades': 0, 'l10_wins': 0, 'l10_pnl': 0.0}
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
    for r in rows[-10:]:
        try:
            p = float(r.get('profit') or 0)
        except Exception:
            p = 0.0
        out['l10_trades'] += 1
        out['l10_pnl'] += p
        out['l10_wins'] += 1 if p > 0 else 0
    for r in rows[-5:]:
        try:
            ct = str(r.get('close_time', '')).strip()
            if ct.isdigit():           # broker epoch seconds
                ts = datetime.fromtimestamp(int(ct), timezone.utc).astimezone(TEHRAN)
                when = ts.strftime('%H:%M')
            elif len(ct) > 16:
                when = ct[11:16]
            else:
                when = '—'
            out['recent'].append((when, r.get('side', '?'), float(r.get('profit') or 0)))
        except Exception:
            continue
    return out


def _backlog() -> dict:
    out = {'todo': [], 'done': []}
    try:
        for ln in (DATA / 'ops/autopilot_backlog.md').read_text(encoding='utf-8').splitlines():
            if ln.startswith('- [ ]'):
                out['todo'].append(ln[5:].strip())
            elif ln.startswith('- [x]'):
                out['done'].append(ln[5:].strip())
    except Exception:
        pass
    return out


def _autopilot_narrative(max_chars: int = 700) -> str:
    """The agent's own final summary of its last completed run, in Persian
    (the prompt requires it). Text between the last two run markers."""
    try:
        txt = (ROOT / 'logs/autopilot.log').read_text(errors='ignore')
    except Exception:
        return ''
    parts = txt.split('=== autopilot run end')
    if len(parts) < 2:
        return ''
    block = parts[-2].split('=== autopilot run start ===')
    body = block[-1]
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    # drop timestamps / report noise, keep the prose
    keep = [l for l in lines
            if not l.startswith('2026-') and 'report sent' not in l
            and 'nothing to report' not in l and 'autopilot run' not in l]
    text = ' '.join(keep)
    # an API-failure run has no narrative — say so plainly in Persian
    if 'API call failed' in text and len(keep) <= 2:
        why = '503' if '503' in text else ('429' if '429' in text else 'خطا')
        return (f'این اجرا به نتیجه نرسید: سرویس مدل پاسخ نداد (HTTP {why}). '
                'هیچ تغییری در کد ساخته نشد؛ آیتم بک‌لاگ برای اجرای بعدی دست‌نخورده ماند.')
    text = re_sub(text)
    return text[:max_chars] + ('…' if len(text) > max_chars else '')


def re_sub(text: str) -> str:
    import re
    text = re.sub(r'`([^`]*)`', r'\1', text)          # strip code ticks
    text = re.sub(r'\*\*([^*]*)\*\*', r'\1', text)    # strip bold markers
    return re.sub(r'\s+', ' ', text).strip()


# ══════════════════════ OPS BOT (3rd) ══════════════════════

OPS_PANELS = {
    'home': '🏠 وضعیت کلی', 'sys': '🖥 سیستم', 'auto': '🤖 اتوپایلوت',
    'ops': '💾 بکاپ', 'trade': '💹 ترید',
}
OPS_KEYBOARD = [[{'text': OPS_PANELS['home'], 'callback_data': 'ops:home'},
                 {'text': OPS_PANELS['sys'], 'callback_data': 'ops:sys'}],
                [{'text': OPS_PANELS['auto'], 'callback_data': 'ops:auto'},
                 {'text': OPS_PANELS['ops'], 'callback_data': 'ops:ops'}],
                [{'text': OPS_PANELS['trade'], 'callback_data': 'ops:trade'}]]


def _verdict() -> tuple[bool, list[str]]:
    """One-line health verdict + the list of whatever is wrong."""
    svcs = _services()
    _, acct, _ = _bridge()
    ks = _j(DATA / 'kill_switch_state.json')
    bh = _j(DATA / 'bridge_health_state.json')
    problems = []
    dead = [k for k, v in svcs.items() if v != 'active']
    if dead:
        problems.append('سرویس خاموش: ' + '، '.join(_SVC_LABEL.get(k, k) for k in dead))
    if not acct.get('ok'):
        problems.append('بریج ویندوز در دسترس نیست')
    if ks.get('halted'):
        problems.append('ترید متوقف شده (kill switch)')
    if (bh.get('fails') or 0) > 0:
        problems.append(f"بریج {bh['fails']} بار پشت سر هم شکست خورد")
    return (not problems), problems


def ops_home() -> tuple[str, list]:
    ok, problems = _verdict()
    svcs = _services()
    _, acct, pos = _bridge()
    ap = _j(DATA / 'ops/autopilot_state.json')
    bl = _backlog()
    jt = _journal()
    open_now, _, flip = _market_state()
    done_n, all_n = len(bl['done']), len(bl['done']) + len(bl['todo'])
    lines = ['🛰 <b>داشبورد عملیات هرمس</b>', _fa_date(), '']
    if ok:
        lines.append('🟢 <b>همه‌چیز روال است</b>')
    else:
        lines.append('🔴 <b>نیاز به توجه</b>')
        lines += [f'· ⚠️ {p}' for p in problems]
    lines.append(_sec('💹 مالی'))
    if acct.get('ok'):
        lines.append(_row('بالانس', f"<b>{_num(acct.get('balance'))} $</b> · دارایی {_num(acct.get('equity'))} $"))
    else:
        lines.append(_row('بالانس', 'نامعلوم — بریج قطع'))
    lines.append(_row('امروز', f"{jt['trades']} ترید · {jt['pnl']:+,.2f} $"))
    lines.append(_row('بازار طلا', '🟢 باز' if open_now else '🔴 بسته'))
    if flip and flip[1] is not None:
        verb = 'باز می‌شود' if flip[1] else 'بسته می‌شود'
        lines.append(_row('تغییر بعدی', f'ساعت {flip[0]} — {verb}'))
    lines.append(_sec('🤖 اتوپایلوت'))
    lines.append(_row('آخرین اجرا', _ago(ap.get('last_run_utc'))))
    lines.append(_row('بک‌لاگ', f'{_bar(done_n / all_n if all_n else 0)} {done_n}/{all_n} انجام شده'))
    lines.append(_sec('🖥 سرویس‌ها'))
    lines.append(' · '.join(f'{_dot(v == "active")} {_SVC_LABEL.get(k, k)}'
                            for k, v in svcs.items()))
    lines.append('\nبرای جزئیات پنل را انتخاب کن 👇')
    return '\n'.join(lines), OPS_KEYBOARD


def ops_system() -> tuple[str, list]:
    svcs = _services()
    ok, problems = _verdict()
    hb = ''
    try:
        hb = (DATA / 'xau_plan/watchdog_heartbeat').read_text().strip()
    except Exception:
        pass
    try:
        disk = subprocess.run(['df', '-h', '--output=pcent,avail', '/'],
                              capture_output=True, text=True, timeout=10).stdout.splitlines()[-1].split()
        disk_pct = disk[0]
    except Exception:
        disk_pct = 'نامعلوم'
    try:
        mem = subprocess.run(['free', '-m'], capture_output=True, text=True, timeout=10).stdout.splitlines()[1].split()
        mem_pct = int(int(mem[2]) / int(mem[1]) * 100)
    except Exception:
        mem_pct = 0
    lines = ['🖥 <b>سلامت سرور</b>', _fa_date(), '']
    lines.append('🟢 <b>سالم</b>' if ok else '🔴 <b>مشکل دارد</b>')
    if problems:
        lines += [f'· ⚠️ {p}' for p in problems]
    lines.append(_sec('🧩 سرویس‌ها'))
    for k, v in svcs.items():
        lines.append(f'{_dot(v == "active")} {_SVC_LABEL.get(k, k)} — '
                     + ('بالا' if v == 'active' else v))
    lines.append(_sec('📊 منابع'))
    lines.append(_row('رمز', f'{_bar(mem_pct / 100)} {mem_pct}٪'))
    lines.append(_row('دیسک', f'{_bar(float(disk_pct.strip("%")) / 100 if disk_pct.strip("%").isdigit() else 0)} {disk_pct}'))
    lines.append(_row('ضربان واتچ‌داگ', _ago(hb) if hb else 'بی‌خبر'))
    return '\n'.join(lines), OPS_KEYBOARD


def ops_autopilot() -> tuple[str, list]:
    ap = _j(DATA / 'ops/autopilot_state.json')
    bl = _backlog()
    done_n, all_n = len(bl['done']), len(bl['done']) + len(bl['todo'])
    lines = ['🤖 <b>اتوپایلوت</b>', _fa_date(), '',
             _row('آخرین اجرا', _ago(ap.get('last_run_utc'))),
             _row('پیشرفت', f'{_bar(done_n / all_n if all_n else 0)} {done_n} از {all_n}')]
    nar = _autopilot_narrative()
    if nar:
        lines.append(_sec('📝 آخرین اجرا چه کرد'))
        lines.append(nar)
    if bl['todo']:
        lines.append(_sec('🔜 کاری که در نوبت است'))
        lines.append('· ' + bl['todo'][0][:160])
    rc = ap.get('recent_commits') or []
    if rc:
        lines.append(_sec('🔨 آخرین تغییرات کد'))
        lines += [f'· {c[:90]}' for c in rc[:3]]
    return '\n'.join(lines), OPS_KEYBOARD


def ops_backup() -> tuple[str, list]:
    bh = _j(DATA / 'bridge_health_state.json')
    last, last_ts = '', None
    try:
        log = ROOT / 'logs/offsite_backup.log'
        for ln in log.read_text(errors='ignore').splitlines()[::-1]:
            if ln.strip():
                last = ln.strip()[:120]
                if ln[:4].isdigit():
                    last_ts = ln[:19]
                break
    except Exception:
        pass
    try:
        r = subprocess.run(['git', '-C', str(ROOT), 'status', '-sb'],
                           capture_output=True, text=True, timeout=15).stdout.splitlines()[0]
        synced = 'ahead' not in r and 'behind' not in r
    except Exception:
        synced = False
    lines = ['💾 <b>نسخه پشتیبان و اتصال‌ها</b>', _fa_date(), '']
    lines.append(_row('گیت‌هاب', _dot(synced) + (' کاملاً همگام' if synced else ' همگام نیست!')))
    lines.append(_row('بریج ویندوز', _dot((bh.get('fails') or 0) == 0)
                      + (f' {bh.get("fails", 0)} شکست متوالی' if bh.get('fails') else ' سالم')))
    lines.append(_sec('🌙 بکاپ شبانه'))
    lines.append('هر شب ۰۳:۱۵ تهران → ویندوز C:\\HermesBackups')
    if last_ts:
        lines.append(_row('آخرین اجرا', _ago(last_ts)))
    if last:
        lines.append(f'<code>{last}</code>')
    lines.append(_sec('🆘 اگر همه‌چیز از دست برود'))
    lines.append('راهنمای بازیابی: docs/DEPLOY.md (۶ قدم کپی‌پیست)')
    return '\n'.join(lines), OPS_KEYBOARD


def ops_trades() -> tuple[str, list]:
    jt = _journal()
    perf = _j(DATA / 'xau_plan/performance_state.json')
    lines = ['💹 <b>تریدها از دید سیستم</b>', _fa_date(), '',
             _row('امروز', f"{jt['trades']} ترید · برد {jt['wins']} · {jt['pnl']:+,.2f} $")]
    if jt['l10_trades']:
        wr = jt['l10_wins'] / jt['l10_trades']
        lines.append(_row('۱۰ ترید اخیر', f'نرخ برد {_bar(wr)} {wr*100:.0f}٪ · {jt["l10_pnl"]:+,.2f} $'))
    lines.append(_row('ضرر متوالی', f"{perf.get('loss_streak', 0)} از ۴ (سقف توقف)"))
    if jt['recent']:
        lines.append(_sec('🕯 آخرین خروج‌ها'))
        for t, side, p in reversed(jt['recent']):
            d = '🟢' if p > 0 else ('⚪' if p == 0 else '🔴')
            lines.append(f'{d} {t} · {side} · {p:+,.2f} $')
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
    'home': '🏠 خلاصه', 'plan': '🎯 پلن', 'pos': '📌 پوزیشن',
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
    jt = _journal()
    open_now, _, flip = _market_state()
    bias = str(plan.get('bias') or '—')
    bias_s = {'bullish': '🟢 صعودی', 'bearish': '🔴 نزولی'}.get(bias, f'⚪ {bias}')
    lines = ['💹 <b>هرمس تریدر</b>', _fa_date(), '']
    if ks.get('halted'):
        lines.append(f'⛔ <b>ترید متوقف است</b> — {ks.get("halt_reason", "دلیل نامعلوم")}')
    elif not open_now:
        lines.append('🌙 <b>بازار بسته است</b> — سیستم آماده و در انتظار')
        if flip and flip[1]:
            lines.append(_row('بازگشایی', f'ساعت {flip[0]} تهران'))
    else:
        lines.append('🟢 <b>ترید فعال</b> — بازار باز، گیت‌ها سبز')
    lines.append(_sec('💰 حساب'))
    if acct.get('ok'):
        lines.append(_row('بالانس', f"<b>{_num(acct.get('balance'))} $</b>"))
        lines.append(_row('دارایی (equity)', _num(acct.get('equity')) + ' $'))
    else:
        lines.append(_row('حساب', 'نامعلوم — بریج قطع'))
    fl = sum(float(p.get('profit') or 0) for p in (pos.get('data') or [])
             if str(p.get('profit') or '').replace('.', '').replace('-', '').isdigit())
    lines.append(_row('پوزیشن باز', f"{pos.get('count', 0)} · سود شناور {fl:+,.2f} $"))
    lines.append(_sec('🎯 پلن فعلی'))
    lines.append(_row('جهت', bias_s))
    q = plan.get('quality') or {}
    if q.get('alignment'):
        al = {'aligned': 'هم‌راستا ✓', 'mixed': 'مخلوط', 'conflicting': 'متناقض ✗'}.get(
            str(q['alignment']), str(q['alignment']))
        lines.append(_row('کیفیت', al))
    lines.append(_row('امروز', f"{jt['trades']} ترید · {jt['pnl']:+,.2f} $"))
    return '\n'.join(lines), TRADE_KEYBOARD


def trade_plan() -> tuple[str, list]:
    plan = _j(DATA / 'xau_plan/current_plan.json')
    ex = plan.get('execution') or {}
    q = plan.get('quality') or {}
    votes = q.get('bias_votes') or {}
    tgts = plan.get('targets') or []
    bias = str(plan.get('bias') or '—')
    lines = [f'🎯 <b>پلن معاملاتی</b>', _fa_date(), '',
             f'جهت: ' + {'bullish': '🟢 <b>صعودی</b>', 'bearish': '🔴 <b>نزولی</b>'}.get(bias, f'⚪ {bias}'),
             _row('سشن', str(plan.get('session', '—'))),
             _row('نوسان (ATR)', _num(plan.get('atr'), 1))]
    lines.append(_sec('🗩 رأی تایم‌فریم‌ها'))
    if votes:
        for tf, v in votes.items():
            d = {'bullish': '🟢 صعودی', 'bearish': '🔴 نزولی'}.get(v, '⚪ بی‌طرف')
            lines.append(_row(tf.upper(), d))
    else:
        lines.append('—')
    lines.append(_sec('⚡ نقطه ورود'))
    lines.append(_row('حالت', str(ex.get('entry_mode', '—'))))
    if ex.get('breakout_trigger'):
        lines.append(_row('شکست', ex['breakout_trigger']))
    if ex.get('pullback_trigger'):
        lines.append(_row('پول‌بک', ex['pullback_trigger']))
    if ex.get('scale_in_levels'):
        lines.append(_row('پله‌ها', ', '.join(str(x) for x in ex['scale_in_levels'])))
    if tgts:
        lines.append(_row('هدف‌ها', ', '.join(str(x) for x in tgts)))
    lines.append(_sec('⏳ اعتبار'))
    lines.append(_row('انقضا', _ago(plan.get('expires_at'))))
    lines.append(_row('بازبینی بعدی', _ago(plan.get('next_reassessment'))))
    return '\n'.join(lines), TRADE_KEYBOARD


def trade_positions() -> tuple[str, list]:
    _, acct, pos = _bridge()
    rows = pos.get('data') or []
    if not acct.get('ok'):
        return ('📌 <b>پوزیشن‌ها</b>\n\n🔴 بریج ویندوز در دسترس نیست — اطلاعات حساب نامعلوم.',
                TRADE_KEYBOARD)
    if not rows:
        open_now, _, flip = _market_state()
        lines = ['📌 <b>پوزیشن‌ها</b>', _fa_date(), '',
                 'هیچ پوزیشن بازی نیست.',
                 _row('بالانس', f"{_num(acct.get('balance'))} $ · دارایی {_num(acct.get('equity'))} $")]
        if not open_now and flip and flip[1]:
            lines.append(_row('بازگشایی بازار', f'ساعت {flip[0]} تهران'))
        return '\n'.join(lines), TRADE_KEYBOARD
    lines = ['📌 <b>پوزیشن‌های باز</b>', _fa_date(), '']
    tot = 0.0
    for p in rows:
        try:
            profit = float(p.get('profit') or 0)
            tot += profit
            d = '🟢' if profit > 0 else ('⚪' if profit == 0 else '🔴')
            side = 'خرید' if str(p.get('type')).upper() in ('BUY', '0') else 'فروش'
            lines.append(f'{d} <b>{side}</b> {_num(p.get("volume"), 2)} لات از {_num(p.get("open_price"))}')
            lines.append(f'   SL {_num(p.get("sl"))} · TP {_num(p.get("tp"))} · قیمت {_num(p.get("current_price"))} → <b>{profit:+,.2f} $</b>')
        except Exception:
            continue
    lines += ['', _row('جمع شناور', f'<b>{tot:+,.2f} $</b>'),
              _row('دارایی', f"{_num(acct.get('equity'))} $")]
    return '\n'.join(lines), TRADE_KEYBOARD


def trade_pnl() -> tuple[str, list]:
    perf = _j(DATA / 'xau_plan/performance_state.json')
    jt = _journal()
    bal = perf.get('starting_balance') or 0
    dp = perf.get('daily_pnl') or 0
    lines = ['💰 <b>سود و ضرر</b>', _fa_date(), '']
    d = '🟢' if dp > 0 else ('⚪' if dp == 0 else '🔴')
    lines.append(f'{d} امروز: <b>{dp:+,.2f} $</b>')
    if bal:
        pct = dp / bal * 100
        lines.append(_row('نسبت به بالانس', f'{pct:+.2f}٪'))
    lines.append(_sec('🗂 ژورنال'))
    lines.append(_row('تریدهای امروز', f"{jt['trades']} · برد {jt['wins']}"))
    if jt['l10_trades']:
        wr = jt['l10_wins'] / jt['l10_trades']
        lines.append(_row('۱۰ ترید اخیر', f'نرخ برد {_bar(wr)} {wr*100:.0f}٪ · {jt["l10_pnl"]:+,.2f} $'))
    if bal:
        lines.append(_row('بالانس شروع روز', f'{_num(bal)} $'))
    if jt['recent']:
        lines.append(_sec('🕯 آخرین خروج‌ها'))
        for t, side, p in reversed(jt['recent']):
            dd = '🟢' if p > 0 else ('⚪' if p == 0 else '🔴')
            lines.append(f'{dd} {t} · {side} · {p:+,.2f} $')
    return '\n'.join(lines), TRADE_KEYBOARD


def trade_risk() -> tuple[str, list]:
    ks = _j(DATA / 'kill_switch_state.json')
    cd = _j(DATA / 'cooldown_state.json')
    perf = _j(DATA / 'xau_plan/performance_state.json')
    open_now, reason, flip = _market_state()
    try:
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from engines.kill_switch import (DAILY_LOSS_LIMIT_PCT, EQUITY_DRAWDOWN_LIMIT_PCT,
                                         CONSECUTIVE_LOSSES_LIMIT)
    except Exception:
        DAILY_LOSS_LIMIT_PCT, EQUITY_DRAWDOWN_LIMIT_PCT, CONSECUTIVE_LOSSES_LIMIT = .05, .10, 4
    bal = perf.get('starting_balance') or 0
    dp = perf.get('daily_pnl') or 0
    daily_pct = max(0.0, -dp / bal * 100) if bal else 0.0
    lines = ['🛡 <b>گیت‌های ایمنی</b>', _fa_date(), '']
    lines.append(_dot(not ks.get('halted')) + (' <b>ترید مجاز</b>' if not ks.get('halted')
                 else f' <b>متوقف</b> — {ks.get("halt_reason", "")}'))
    lines.append(_sec('📉 فاصله تا توقف'))
    lines.append(_row('ضرر روزانه', f'{_bar(daily_pct / (DAILY_LOSS_LIMIT_PCT*100))} '
                      f'{daily_pct:.1f}٪ از {DAILY_LOSS_LIMIT_PCT*100:.0f}٪ سقف'))
    cl = ks.get('consecutive_losses', 0)
    lines.append(_row('ضرر متوالی', f'{_bar(cl / CONSECUTIVE_LOSSES_LIMIT)} '
                      f'{cl} از {CONSECUTIVE_LOSSES_LIMIT}'))
    lines.append(_row('ترید امروز', f"{perf.get('trades_today', 0)}"))
    lines.append(_sec('🕐 بازار'))
    if open_now:
        mk = '🟢 باز'
        if flip and not flip[1]:
            mk += f' — بسته می‌شود ساعت {flip[0]}'
    else:
        mk = f'🔴 بسته ({reason})' if reason else '🔴 بسته'
        if flip and flip[1]:
            mk += f' — باز می‌شود ساعت {flip[0]}'
    lines.append(_row('طلا XAUUSD', mk))
    act = []
    rs = (cd.get('restart') or {}).get('until')
    now = datetime.now(timezone.utc)
    if rs:
        try:
            t = datetime.fromisoformat(str(rs).replace('Z', '+00:00'))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if t > now:
                act.append(f'کول‌داون ریستارت تا {t.astimezone(TEHRAN).strftime("%H:%M")}')
        except Exception:
            pass
    for k, v in cd.items():
        if k.startswith('_') or k == 'restart':
            continue
        until = (v or {}).get('until') if isinstance(v, dict) else None
        if until:
            try:
                t = datetime.fromisoformat(str(until).replace('Z', '+00:00'))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if t > now:
                    act.append(f'{k} تا {t.astimezone(TEHRAN).strftime("%H:%M")}')
            except Exception:
                act.append(f'{k} تا {until}')
    lines.append(_sec('⏸ محدودیت فعال'))
    lines += [f'· {a}' for a in act] if act else ['هیچ — همه گیت‌ها باز هستند']
    return '\n'.join(lines), TRADE_KEYBOARD


TRADE_RENDER = {'home': trade_home, 'plan': trade_plan, 'pos': trade_positions,
                'pnl': trade_pnl, 'risk': trade_risk}


def trade_render(panel: str) -> tuple[str, list]:
    fn = TRADE_RENDER.get(panel, trade_home)
    try:
        return fn()
    except Exception as e:
        return f'🔴 پنل {panel} خطا داد: {str(e)[:120]}', TRADE_KEYBOARD
