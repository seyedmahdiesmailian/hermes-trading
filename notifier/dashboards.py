#!/usr/bin/env python3
"""b40: Telegram dashboards — nested menus, deeper data, operator controls.

Research-backed layout (prop-firm dashboards + Telegram multi-level UX):
  - verdict-first home, drill-down sub-panels, ⬅️ بازگشت + 🏠 خانه everywhere
  - pro stats: profit factor, expectancy, avg win/loss, max drawdown,
    streaks, equity sparkline, day-by-day P&L
  - 🎛 کنترل: pause autopilot, halt/resume trading, restart daemons —
    every destructive action goes through a ✅/❌ confirmation step and is
    written to logs/control_audit.log. Owner-chat only (enforced upstream).

Callback grammar:  ops:<path...>   tr:<path...>
                   ask:<action> -> confirm panel ; cfm:<action> -> execute
"""
from __future__ import annotations

import csv
import json
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path('/home/ai/hermes-trading')
DATA = ROOT / 'data'   # READ-ONLY by design (an operator panel must show the
                       # real numbers even from a test run) — pinned by the
                       # b39 tripwire's ALLOWED list. WRITERS below must not
                       # use these constants.
TEHRAN = timezone(timedelta(hours=3, minutes=30))
WEEK_FA = ['دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه', 'شنبه', 'یکشنبه']


# b39: PAUSE_FLAG / AUDIT_LOG were import-time constants under the production
# root. They are WRITTEN by handle_control()/_audit(), so a test (or a
# staging run) that exercised an operator action would toggle the REAL
# autopilot pause flag and append to the REAL audit log. Resolved at call
# time through engines.paths, like every other state writer.
def _pause_flag() -> Path:
    from engines import paths as _paths
    return _paths.data_dir() / 'ops' / 'autopilot_paused'


def _audit_log() -> Path:
    from engines import paths as _paths
    return _paths.logs_dir() / 'control_audit.log'

RESTARTABLE = {'hermes-signal': 'سرویس سیگنال', 'hermes-position': 'سرویس پوزیشن',
               'hermes-dashboard': 'سرویس داشبورد'}


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
        if m < 0:
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


def _spark(vals) -> str:
    blocks = '▁▂▃▄▅▆▇█'
    vals = [float(v) for v in vals]
    if not vals:
        return '—'
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return blocks[4] * len(vals)
    return ''.join(blocks[int((v - lo) / (hi - lo) * 7)] for v in vals)


def _sec(title: str) -> str:
    return f'\n<b>{title}</b>\n'


def _row(label: str, value: str) -> str:
    return f'{label}: {value}'


def _btn(text: str, data: str) -> dict:
    return {'text': text, 'callback_data': data}


def _nav(prefix: str, back: str | None, home: str = 'home') -> list:
    row = []
    if back is not None:
        row.append(_btn('⬅️ بازگشت', f'{prefix}:{back}'))
    row.append(_btn('🏠 خانه', f'{prefix}:{home}'))
    return row


# ─────────────────────────── shared sources ───────────────────────────

def _market_state():
    try:
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from engines.market_hours import is_market_open, closed_reason
        now = datetime.now(timezone.utc)
        open_now = bool(is_market_open(now))
        flip, flip_open = None, None
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
        return False, '', (None, None)


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


_SVC_LABEL = {'hermes-signal': '📡 سیگنال', 'hermes-position': '📌 پوزیشن',
              'hermes-gateway': '🖥 گیت‌وی', 'hermes-dashboard': '🛰 داشبورد'}


def _svc_uptime(name: str) -> str:
    try:
        r = subprocess.run(['systemctl', '--user', 'show', name,
                            '-p', 'ActiveEnterTimestamp'],
                           capture_output=True, text=True, timeout=10)
        raw = r.stdout.strip().split('=', 1)[-1].strip()
        if not raw:
            return '—'
        # systemd prints e.g. "Sun 2026-08-30 20:27:27 +0330" — drop the
        # weekday token and normalise the offset before parsing.
        parts = raw.split()
        if len(parts) == 4 and parts[0][:3].isalpha() and parts[1][:2].isdigit():
            parts = parts[1:]
        if len(parts) == 3 and parts[2].startswith(('+', '-')) and ':' not in parts[2]:
            parts[2] = parts[2][:3] + ':' + parts[2][3:]
        t = datetime.fromisoformat(' '.join(parts).replace(' ', 'T', 1))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        d = datetime.now(timezone.utc) - t
        mins = int(d.total_seconds() // 60)
        if mins < 60:
            return f'{mins}m'
        if d.days:
            return f'{d.days}d {d.seconds // 3600}h'
        return f'{mins // 60}h {mins % 60}m'
    except Exception:
        return '—'


def _svc_log(name: str, n: int = 5) -> str:
    try:
        r = subprocess.run(['journalctl', '--user', '-u', name, '-n', str(n),
                            '--no-pager', '-o', 'cat'],
                           capture_output=True, text=True, timeout=15)
        return '\n'.join(l[:110] for l in r.stdout.splitlines()[-n:]) or '—'
    except Exception:
        return '—'


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


def _journal_rows() -> list:
    try:
        with (DATA / 'xau_plan/trade_journal.csv').open(encoding='utf-8-sig') as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _stats() -> dict:
    """Professional stats from the full journal + today slice."""
    rows = _journal_rows()
    out = {'n': len(rows), 'today': {'n': 0, 'pnl': 0.0, 'wins': 0},
           'recent': [], 'days': [], 'curve': ''}
    if not rows:
        return out
    pnls, wins = [], 0
    for r in rows:
        try:
            pnls.append(float(r.get('profit') or 0))
        except Exception:
            pnls.append(0.0)
    out['n'] = len(pnls)
    out['wins'] = sum(1 for p in pnls if p > 0)
    out['losses'] = sum(1 for p in pnls if p < 0)
    gross_w = sum(p for p in pnls if p > 0)
    gross_l = -sum(p for p in pnls if p < 0)
    out['pf'] = (gross_w / gross_l) if gross_l > 0 else float('inf') if gross_w > 0 else 0.0
    out['net'] = sum(pnls)
    out['exp'] = out['net'] / len(pnls) if pnls else 0.0
    ws = [p for p in pnls if p > 0]
    ls = [p for p in pnls if p < 0]
    out['avg_win'] = sum(ws) / len(ws) if ws else 0.0
    out['avg_loss'] = sum(ls) / len(ls) if ls else 0.0
    out['best'] = max(pnls)
    out['worst'] = min(pnls)
    # max drawdown on the cumulative curve
    cum = peak = 0.0
    mdd = 0.0
    curve = []
    for p in pnls:
        cum += p
        curve.append(cum)
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    out['mdd'] = mdd
    out['curve'] = _spark(curve)
    # current streak
    streak, kind = 0, ''
    for p in reversed(pnls):
        k = 'win' if p > 0 else ('loss' if p < 0 else '')
        if not k or (kind and k != kind):
            break
        kind = k
        streak += 1
    out['streak'] = (streak, kind)
    # by side
    for side in ('BUY', 'SELL'):
        sp = [float(r.get('profit') or 0) for r in rows if str(r.get('side', '')).upper() == side]
        out[f'{side.lower()}_n'] = len(sp)
        out[f'{side.lower()}_pnl'] = sum(sp)
        out[f'{side.lower()}_wr'] = (sum(1 for p in sp if p > 0) / len(sp) * 100) if sp else 0.0
    # today
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    for r in rows:
        if str(r.get('journaled_at', '')).startswith(today):
            try:
                p = float(r.get('profit') or 0)
            except Exception:
                p = 0.0
            out['today']['n'] += 1
            out['today']['pnl'] += p
            out['today']['wins'] += 1 if p > 0 else 0
    # last 7 days
    by_day: dict[str, float] = {}
    for r in rows:
        d = str(r.get('journaled_at', ''))[:10]
        try:
            by_day[d] = by_day.get(d, 0.0) + float(r.get('profit') or 0)
        except Exception:
            continue
    out['days'] = sorted(by_day.items())[-7:]
    # recent list
    for r in rows[-10:][::-1]:
        ct = str(r.get('close_time', '')).strip()
        if ct.isdigit():
            when = datetime.fromtimestamp(int(ct), timezone.utc).astimezone(TEHRAN).strftime('%m/%d %H:%M')
        else:
            when = ct[5:16] or '—'
        try:
            out['recent'].append((when, str(r.get('side', '?')).upper(),
                                  float(r.get('volume') or 0), float(r.get('profit') or 0),
                                  str(r.get('comment') or '')))
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
    try:
        txt = (ROOT / 'logs/autopilot.log').read_text(errors='ignore')
    except Exception:
        return ''
    parts = txt.split('=== autopilot run end')
    if len(parts) < 2:
        return ''
    body = parts[-2].split('=== autopilot run start ===')[-1]
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    keep = [l for l in lines
            if not l.startswith('2026-') and 'report sent' not in l
            and 'nothing to report' not in l and 'autopilot run' not in l]
    text = ' '.join(keep)
    if 'API call failed' in text and len(keep) <= 2:
        why = '503' if '503' in text else ('429' if '429' in text else 'خطا')
        return (f'این اجرا به نتیجه نرسید: سرویس مدل پاسخ نداد (HTTP {why}). '
                'هیچ تغییری در کد ساخته نشد؛ آیتم بک‌لاگ برای اجرای بعدی دست‌نخورده ماند.')
    import re
    text = re.sub(r'`([^`]*)`', r'\1', text)
    text = re.sub(r'\*\*([^*]*)\*\*', r'\1', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_chars] + ('…' if len(text) > max_chars else '')


def _autopilot_paused() -> str | None:
    try:
        flag = _pause_flag()
        if flag.exists():
            return flag.read_text().strip()[:80] or 'بله'
    except Exception:
        pass
    return None


def _guard_line(short: bool = False) -> str:
    """b40: one-line description of the guard-degradation alert state that
    hermes_master writes (b37). Until now the file was write-only — a
    degraded management path was visible only in the ops chat. This reads it
    through engines.guard_status, the SINGLE canonical reader (lazy import,
    so tests can redirect the root via HERMES_DATA_ROOT). Empty string =
    nothing degraded / nothing observable. Display-only: never raises."""
    try:
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from engines import guard_status
        return guard_status.describe(guard_status.read(), short=short)
    except Exception:
        return ''


def _verdict() -> tuple[bool, list[str]]:
    svcs = _services()
    _, acct, _ = _bridge()
    ks = _j(DATA / 'kill_switch_state.json')
    bh = _j(DATA / 'bridge_health_state.json')
    problems = []
    dead = [k for k, v in svcs.items() if v != 'active']
    if dead:
        problems.append('سرویس خاموش: ' + '، '.join(_SVC_LABEL.get(k, k).split(' ', 1)[-1] for k in dead))
    if not acct.get('ok'):
        problems.append('بریج ویندوز در دسترس نیست')
    if ks.get('halted'):
        problems.append('ترید متوقف شده (kill switch)')
    if (bh.get('fails') or 0) > 0:
        problems.append(f"بریج {bh['fails']} بار پشت سر هم شکست خورد")
    # b40: a degraded guard state means a live position is being managed
    # with fewer safety guards than usual — that is a "needs attention"
    # fact, not a stat line.
    g = _guard_line(short=True)
    if g:
        problems.append(g)
    return (not problems), problems


# ══════════════════════ OPS BOT (3rd) ══════════════════════

def ops_home() -> tuple[str, list]:
    ok, problems = _verdict()
    svcs = _services()
    _, acct, pos = _bridge()
    ap = _j(DATA / 'ops/autopilot_state.json')
    bl = _backlog()
    st = _stats()
    open_now, _, flip = _market_state()
    done_n, all_n = len(bl['done']), len(bl['done']) + len(bl['todo'])
    paused = _autopilot_paused()
    lines = ['🛰 <b>داشبورد عملیات هرمس</b>', _fa_date(), '']
    if ok:
        lines.append('🟢 <b>همه‌چیز روال است</b>')
    else:
        lines.append('🔴 <b>نیاز به توجه</b>')
        lines += [f'· ⚠️ {p}' for p in problems]
    lines.append(_sec('💹 مالی'))
    if acct.get('ok'):
        lines.append(_row('Balance', f"<b>{_num(acct.get('balance'))} $</b> · دارایی {_num(acct.get('equity'))} $"))
    else:
        lines.append(_row('Balance', 'نامعلوم — بریج قطع'))
    lines.append(_row('Today', f"{st['today']['n']} ترید · {st['today']['pnl']:+,.2f} $"))
    lines.append(_row('Gold Market', '🟢 باز' if open_now else '🔴 بسته'))
    if flip and flip[1]:
        lines.append(_row('Reopens', f'ساعت {flip[0]} تهران'))
    lines.append(_sec('🤖 اتوپایلوت'))
    if paused:
        lines.append(f'⏸ <b>متوقف است</b> — {paused}')
    else:
        lines.append(_row('Last Run', _ago(ap.get('last_run_utc'))))
    lines.append(_row('Backlog', f'{_bar(done_n / all_n if all_n else 0)} {done_n}/{all_n}'))
    lines.append(_sec('🖥 سرویس‌ها'))
    lines.append(' · '.join(f'{_dot(v == "active")} {_SVC_LABEL.get(k, k)}'
                            for k, v in svcs.items()))
    kb = [[_btn('🖥 سیستم', 'ops:sys'), _btn('🤖 اتوپایلوت', 'ops:auto')],
          [_btn('💾 بکاپ/سلامت', 'ops:ops'), _btn('💹 ترید', 'ops:trade')],
          [_btn('🎛 کنترل', 'ops:control')]]
    return '\n'.join(lines), kb


def ops_sys() -> tuple[str, list]:
    svcs = _services()
    try:
        disk = subprocess.run(['df', '-h', '--output=pcent,avail', '/'],
                              capture_output=True, text=True, timeout=10).stdout.splitlines()[-1].split()
        disk_pct = disk[0]
    except Exception:
        disk_pct = '؟'
    try:
        mem = subprocess.run(['free', '-m'], capture_output=True, text=True, timeout=10).stdout.splitlines()[1].split()
        mem_pct = int(int(mem[2]) / int(mem[1]) * 100)
    except Exception:
        mem_pct = 0
    try:
        load = subprocess.run(['cat', '/proc/loadavg'], capture_output=True, text=True, timeout=5).stdout.split()[:3]
        load_s = ' · '.join(load)
    except Exception:
        load_s = '—'
    # b40: CPU % from /proc/stat delta over a short sample window
    # fields: user nice system idle iowait irq softirq steal → idle=t[3]
    def _cpu_times():
        t = [int(x) for x in open('/proc/stat').readline().split()[1:9]]
        return sum(t) - t[3] - t[4], sum(t)   # busy (excl idle+iowait), total
    cpu_pct = 0
    try:
        b1, t1 = _cpu_times()
        time.sleep(0.35)
        b2, t2 = _cpu_times()
        cpu_pct = int((b2 - b1) / max(1, t2 - t1) * 100)
    except Exception:
        pass
    hb = ''
    try:
        hb = (DATA / 'xau_plan/watchdog_heartbeat').read_text().strip()
    except Exception:
        pass
    lines = ['🖥 <b>زیرساخت</b>', _fa_date(), '', _sec('🧩 سرویس‌ها (برای جزئیات بزن)')]
    kb = []
    items = list(svcs.items())
    for i in range(0, len(items), 2):
        row = []
        for k, v in items[i:i + 2]:
            lines.append(f'{_dot(v == "active")} {_SVC_LABEL.get(k, k)} — '
                         + ('بالا' if v == 'active' else v))
            row.append(_btn(f'{_dot(v == "active")} {_SVC_LABEL.get(k, k).split(" ", 1)[-1]}',
                            f'ops:svc:{k}'))
        kb.append(row)
    lines.append(_sec('📊 Resources'))
    lines.append(_row('CPU', f'{_bar(cpu_pct / 100)} {cpu_pct}٪'))
    lines.append(_row('RAM', f'{_bar(mem_pct / 100)} {mem_pct}٪'))
    lines.append(_row('Disk', f'{_bar(float(disk_pct.rstrip("%")) / 100 if disk_pct != "؟" else 0)} '
                              f'{disk_pct.replace("%", "٪")} · {disk[1] if disk_pct != "؟" else "?"} free'))
    lines.append(_row('Load', load_s))
    lines.append(_row('Watchdog', _ago(hb) if hb else 'بی‌خبر'))
    kb.append(_nav('ops', 'home'))
    return '\n'.join(lines), kb


def ops_svc_detail(name: str) -> tuple[str, list]:
    svcs = _services()
    st = svcs.get(name, '?')
    lines = [f'{_SVC_LABEL.get(name, name)} <b>جزئیات سرویس</b>', '',
             _row('Name', f'<code>{name}</code>'),
             _row('Status', ('🟢 بالا' if st == 'active' else f'🔴 {st}')),
             _row('Uptime', _svc_uptime(name)),
             _sec('📜 آخرین خط‌ها')]
    lines.append(f'<code>{_svc_log(name)}</code>')
    kb = []
    if name in RESTARTABLE:
        kb.append([_btn('🔁 ریستارت این سرویس', f'ops:ask:restart:{name}')])
    kb.append(_nav('ops', 'sys'))
    return '\n'.join(lines), kb


def ops_auto() -> tuple[str, list]:
    ap = _j(DATA / 'ops/autopilot_state.json')
    bl = _backlog()
    done_n, all_n = len(bl['done']), len(bl['done']) + len(bl['todo'])
    paused = _autopilot_paused()
    lines = ['🤖 <b>اتوپایلوت</b>', _fa_date(), '']
    if paused:
        lines.append(f'⏸ <b>متوقف است</b> — از: {paused}')
        lines.append('اجراهای ساعتی فعلاً رد می‌شوند؛ هر لحظه می‌توانی ادامه بدهی.')
    else:
        lines.append('🟢 <b>فعال</b> — هر ساعت یک آیتم از بک‌لاگ')
        lines.append(_row('Last Run', _ago(ap.get('last_run_utc'))))
    lines.append(_row('Progress', f'{_bar(done_n / all_n if all_n else 0)} {done_n} از {all_n}'))
    g = _guard_line()
    if g:
        lines.append('')
        lines.append(f'🛑 <b>{g}</b>')
    nar = _autopilot_narrative()
    if nar:
        lines.append(_sec('📝 آخرین اجرا چه کرد'))
        lines.append(nar)
    if bl['todo']:
        lines.append(_sec('🔜 در نوبت'))
        lines.append('· ' + bl['todo'][0][:150])
    kb = [[_btn('📜 بک‌لاگ کامل', 'ops:auto:backlog'), _btn('🔨 تغییرات کد', 'ops:auto:commits')]]
    if paused:
        kb.append([_btn('▶️ ازسرگیری اتوپایلوت', 'ops:ask:auto:resume')])
    else:
        kb.append([_btn('⏸ توقف موقت اتوپایلوت', 'ops:ask:auto:pause')])
    kb.append(_nav('ops', 'home'))
    return '\n'.join(lines), kb


def ops_auto_backlog() -> tuple[str, list]:
    bl = _backlog()
    lines = ['📜 <b>بک‌لاگ اتوپایلوت</b>', '',
             _row('Queue', str(len(bl['todo']))), _row('Done', str(len(bl['done'])))]
    lines.append(_sec('🔜 صف (۶ مورد بعدی)'))
    for i, t in enumerate(bl['todo'][:6], 1):
        lines.append(f'<b>{i}.</b> {t[:130]}')
    lines.append(_sec('✅ تازه انجام‌شده'))
    for d in bl['done'][-4:]:
        lines.append(f'· {d[:110]}')
    return '\n'.join(lines), [_nav('ops', 'auto')]


def ops_auto_commits() -> tuple[str, list]:
    try:
        r = subprocess.run(['git', '-C', str(ROOT), 'log', '--oneline', '-12'],
                           capture_output=True, text=True, timeout=15)
        commits = r.stdout.splitlines()
    except Exception:
        commits = []
    lines = ['🔨 <b>۱۲ تغییر اخیر کد</b>', '']
    lines += [f'<code>{c[:95]}</code>' for c in commits] or ['—']
    return '\n'.join(lines), [_nav('ops', 'auto')]


def ops_backup() -> tuple[str, list]:
    bh = _j(DATA / 'bridge_health_state.json')
    last, last_ts = '', None
    try:
        for ln in (ROOT / 'logs/offsite_backup.log').read_text(errors='ignore').splitlines()[::-1]:
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
    lines = ['💾 <b>پشتیبان و اتصال‌ها</b>', _fa_date(), '',
             _row('GitHub', _dot(synced) + (' کاملاً همگام' if synced else ' همگام نیست!')),
             _row('Windows Bridge', _dot((bh.get('fails') or 0) == 0)
                  + (f' — {bh.get("fails", 0)} شکست متوالی' if bh.get('fails') else ' سالم')),
             _sec('🌙 بکاپ شبانه (۰۳:۱۵ تهران → ویندوز)')]
    if last_ts:
        lines.append(_row('Last Run', _ago(last_ts)))
    if last:
        lines.append(f'<code>{last}</code>')
    lines.append(_sec('🆘 بازیابی فاجعه'))
    lines.append('docs/DEPLOY.md — ۶ قدم کپی‌پیست از صفر')
    return '\n'.join(lines), [_nav('ops', 'home')]


def ops_trade() -> tuple[str, list]:
    st = _stats()
    perf = _j(DATA / 'xau_plan/performance_state.json')
    lines = ['💹 <b>تریدها از دید سیستم</b>', _fa_date(), '',
             _row('Today', f"{st['today']['n']} ترید · برد {st['today']['wins']} · {st['today']['pnl']:+,.2f} $"),
             _row('Loss Streak', f"{perf.get('loss_streak', 0)} از ۴ (سقف توقف)")]
    if st['n']:
        pf = '∞' if st['pf'] == float('inf') else _num(st['pf'], 2)
        lines.append(_sec('📊 کارنامه کل'))
        lines.append(_row('Net P&L', f'{st["net"]:+,.2f} $'))
        lines.append(_row('Profit Factor', f'{pf} (بالای ۱ = سودده)'))
        lines.append(_row('Equity Curve', st['curve']))
    kb = [[_btn('📊 آمار کامل', 'ops:trade:stats')], _nav('ops', 'home')]
    return '\n'.join(lines), kb


def _stats_panel_lines(st: dict) -> list:
    lines = []
    if not st['n']:
        return ['ژورنال خالی است — هنوز ترید بسته‌شده‌ای ثبت نشده.']
    wr = st['wins'] / st['n'] * 100
    pf = '∞' if st['pf'] == float('inf') else _num(st['pf'], 2)
    lines.append(_row('Trades', f"{st['n']} · برد {st['wins']} · باخت {st['losses']} · نرخ برد {wr:.0f}٪ {_bar(wr/100)}"))
    lines.append(_row('Net P&L', f"<b>{st['net']:+,.2f} $</b> · ضریب سود {pf}"))
    lines.append(_row('Avg Win', f'{st["avg_win"]:+,.2f} $ · میانگین باخت {st["avg_loss"]:+,.2f} $'))
    lines.append(_row('Expectancy', f'{st["exp"]:+,.2f} $ در هر ترید'))
    lines.append(_row('Best / Worst', f'{st["best"]:+,.2f} $ · {st["worst"]:+,.2f} $'))
    lines.append(_row('Max Drawdown', f'{st["mdd"]:,.2f} $'))
    sk, kind = st['streak']
    if sk:
        lines.append(_row('Streak', f'{sk} {"برد 🟢" if kind == "win" else "باخت 🔴"}'))
    lines.append(_row('Equity Curve', st['curve']))
    lines.append(_sec('⚖️ خرید در برابر فروش'))
    for side, fa in (('buy', 'خرید'), ('sell', 'فروش')):
        if st.get(f'{side}_n'):
            lines.append(_row(fa, f"{st[f'{side}_n']} ترید · {st[f'{side}_pnl']:+,.2f} $ · برد {st[f'{side}_wr']:.0f}٪"))
    if st['days']:
        lines.append(_sec('🗓 روز به روز'))
        for d, p in st['days']:
            dd = '🟢' if p > 0 else ('⚪' if p == 0 else '🔴')
            lines.append(f'{dd} {d[5:]} · {p:+,.2f} $')
    return lines


def ops_trade_stats() -> tuple[str, list]:
    st = _stats()
    lines = ['📊 <b>کارنامه کامل</b>', _fa_date(), ''] + _stats_panel_lines(st)
    return '\n'.join(lines), [_nav('ops', 'trade')]


def ops_control() -> tuple[str, list]:
    ks = _j(DATA / 'kill_switch_state.json')
    paused = _autopilot_paused()
    svcs = _services()
    lines = ['🎛 <b>کنترل اپراتور</b>', _fa_date(), '',
             'هر دکمه قبل از اجرا تأیید می‌خواهد و در لاگ کنترل ثبت می‌شود.', '']
    lines.append(_sec('🤖 اتوپایلوت'))
    lines.append('⏸ متوقف — ' + str(paused) if paused else '🟢 فعال (هر ساعت اجرا می‌شود)')
    lines.append(_sec('💹 موتور ترید'))
    if ks.get('halted'):
        lines.append(f'⛔ متوقف — {ks.get("halt_reason", "")} {_row("", "(از " + _ago(ks.get("halted_at")) + ")") if ks.get("halted_at") else ""}')
    else:
        lines.append('🟢 مجاز — گیت‌ها باز هستند')
    lines.append(_sec('🖥 سرویس‌ها'))
    lines.append(' · '.join(f'{_dot(v == "active")} {_SVC_LABEL.get(k, k).split(" ", 1)[-1]}'
                            for k, v in svcs.items()))
    kb = []
    if paused:
        kb.append([_btn('▶️ ازسرگیری اتوپایلوت', 'ops:ask:auto:resume')])
    else:
        kb.append([_btn('⏸ توقف موقت اتوپایلوت', 'ops:ask:auto:pause')])
    if ks.get('halted'):
        kb.append([_btn('▶️ ازسرگیری ترید', 'ops:ask:trade:resume')])
    else:
        kb.append([_btn('⛔ توقف فوری ترید', 'ops:ask:trade:halt')])
    kb.append([_btn('🔁 ریستارت سرویس‌ها', 'ops:control:restart')])
    kb.append(_nav('ops', 'home'))
    return '\n'.join(lines), kb


def ops_control_restart() -> tuple[str, list]:
    svcs = _services()
    lines = ['🔁 <b>ریستارت سرویس‌ها</b>', '', 'با تأیید دومرحله‌ای اجرا می‌شود.']
    kb = []
    row = []
    for k, label in RESTARTABLE.items():
        row.append(_btn(f'{_dot(svcs.get(k) == "active")} {label.split(" ", 1)[-1]}',
                        f'ops:ask:restart:{k}'))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append(_nav('ops', 'control'))
    return '\n'.join(lines), kb


def ops_confirm(action: str) -> tuple[str, list]:
    desc = _ACTION_DESC.get(action, action)
    lines = ['⚠️ <b>تأیید عملیات</b>', '', f'{desc}', '', 'مطمئنی؟']
    kb = [[_btn('✅ بله، انجام بده', f'ops:cfm:{action}'),
           _btn('❌ انصراف', 'ops:control')]]
    return '\n'.join(lines), kb


OPS_RENDER = {
    'home': ops_home, 'sys': ops_sys, 'auto': ops_auto, 'auto:backlog': ops_auto_backlog,
    'auto:commits': ops_auto_commits, 'ops': ops_backup, 'trade': ops_trade,
    'trade:stats': ops_trade_stats, 'control': ops_control, 'control:restart': ops_control_restart,
}


def ops_render(panel: str) -> tuple[str, list]:
    try:
        if panel.startswith('svc:'):
            return ops_svc_detail(panel[4:])
        if panel.startswith('ask:'):
            return ops_confirm(panel[4:])
        fn = OPS_RENDER.get(panel, ops_home)
        return fn()
    except Exception as e:
        return f'🔴 پنل {panel} خطا داد: {str(e)[:120]}', [[_btn('🏠 خانه', 'ops:home')]]


# ══════════════════════ TRADE BOT (2nd) ══════════════════════

def trade_home() -> tuple[str, list]:
    plan = _j(DATA / 'xau_plan/current_plan.json')
    _, acct, pos = _bridge()
    ks = _j(DATA / 'kill_switch_state.json')
    st = _stats()
    open_now, _, flip = _market_state()
    bias = str(plan.get('bias') or '—')
    lines = ['💹 <b>هرمس تریدر</b>', _fa_date(), '']
    if ks.get('halted'):
        lines.append(f'⛔ <b>ترید متوقف است</b> — {ks.get("halt_reason", "دلیل نامعلوم")}')
    elif not open_now:
        lines.append('🌙 <b>بازار بسته است</b> — سیستم آماده و در انتظار')
        if flip and flip[1]:
            lines.append(_row('Reopens', f'ساعت {flip[0]} تهران'))
    else:
        lines.append('🟢 <b>ترید فعال</b> — بازار باز، گیت‌ها سبز')
    # b40: entry gates green ≠ management guards healthy. If the fallback
    # path lost news_lock/time_exit, say so on the trader's front page too.
    g = _guard_line(short=True)
    if g:
        lines.append(f'🛑 {g}')
    lines.append(_sec('💰 حساب'))
    if acct.get('ok'):
        lines.append(_row('Balance', f"<b>{_num(acct.get('balance'))} $</b> · دارایی {_num(acct.get('equity'))} $"))
    else:
        lines.append(_row('Account', 'نامعلوم — بریج قطع'))
    fl = sum(float(p.get('profit') or 0) for p in (pos.get('data') or [])
             if str(p.get('profit') or '').replace('.', '').replace('-', '').replace(',', '').isdigit())
    lines.append(_row('Open Positions', f"{pos.get('count', 0)} · سود شناور {fl:+,.2f} $"))
    lines.append(_sec('🎯 پلن'))
    lines.append(_row('Bias', {'bullish': '🟢 صعودی', 'bearish': '🔴 نزولی'}.get(bias, f'⚪ {bias}'))
                 + f" · اعتبار {_ago(plan.get('expires_at'))}")
    lines.append(_row('Today', f"{st['today']['n']} ترید · {st['today']['pnl']:+,.2f} $"))
    if st['n']:
        pf = '∞' if st['pf'] == float('inf') else _num(st['pf'], 2)
        lines.append(_row('Record', f"نرخ برد {st['wins']}/{st['n']} · ضریب سود {pf} · {st['net']:+,.2f} $"))
    kb = [[_btn('🎯 پلن', 'tr:plan'), _btn('📌 پوزیشن', 'tr:pos')],
          [_btn('💰 سود/ضرر', 'tr:pnl'), _btn('📊 آمار', 'tr:stats')],
          [_btn('📡 سیگنال‌ها', 'tr:sig'), _btn('🛡 ریسک', 'tr:risk')],
          [_btn('🎛 کنترل', 'tr:control')]]
    return '\n'.join(lines), kb


def trade_plan() -> tuple[str, list]:
    plan = _j(DATA / 'xau_plan/current_plan.json')
    q = plan.get('quality') or {}
    votes = q.get('bias_votes') or {}
    bias = str(plan.get('bias') or '—')
    lines = ['🎯 <b>پلن معاملاتی</b>', _fa_date(), '',
             'جهت: ' + {'bullish': '🟢 <b>صعودی</b>', 'bearish': '🔴 <b>نزولی</b>'}.get(bias, f'⚪ {bias}'),
             _row('Session', str(plan.get('session', '—'))),
             _row('ATR', _num(plan.get('atr'), 1))]
    lines.append(_sec('🗩 رأی تایم‌فریم‌ها'))
    for tf, v in (votes or {}).items():
        d = {'bullish': '🟢 صعودی', 'bearish': '🔴 نزولی'}.get(v, '⚪ بی‌طرف')
        lines.append(_row(tf.upper(), d))
    al = {'aligned': 'هم‌راستا ✓', 'mixed': 'مخلوط', 'conflicting': 'متناقض ✗'}.get(
        str(q.get('alignment')), str(q.get('alignment', '—')))
    lines.append(_row('Quality', al))
    lines.append(_sec('⏳ اعتبار'))
    lines.append(_row('Expires', _ago(plan.get('expires_at'))))
    lines.append(_row('Reassess', _ago(plan.get('next_reassessment'))))
    kb = [[_btn('🧩 جزئیات ورود', 'tr:plan:detail'), _btn('📜 تاریخچه', 'tr:plan:hist')],
          _nav('tr', 'home')]
    return '\n'.join(lines), kb


def trade_plan_detail() -> tuple[str, list]:
    plan = _j(DATA / 'xau_plan/current_plan.json')
    ex = plan.get('execution') or {}
    tgts = plan.get('targets') or []
    macro = _j(DATA / 'xau_plan/macro_snapshot.json')
    lines = ['🧩 <b>جزئیات اجرای پلن</b>', '',
             _row('Entry Mode', str(ex.get('entry_mode', '—')))]
    if ex.get('breakout_trigger'):
        lines.append(_row('Breakout Trigger', _num(ex['breakout_trigger'])))
    if ex.get('pullback_trigger'):
        lines.append(_row('Pullback Trigger', _num(ex['pullback_trigger'])))
    if ex.get('scale_in_levels'):
        lines.append(_row('Scale-In', ', '.join(_num(x) for x in ex['scale_in_levels'])))
    if tgts:
        lines.append(_row('Targets', ' · '.join(_num(x) for x in tgts)))
    if ex.get('stop_loss'):
        lines.append(_row('Plan SL', _num(ex['stop_loss'])))
    if macro:
        lines.append(_sec('🌍 ماکرو'))
        news = macro.get('high_impact_today') or macro.get('events') or []
        if isinstance(news, list) and news:
            for ev in news[:3]:
                if isinstance(ev, dict):
                    lines.append(f"· {ev.get('currency', '')} {str(ev.get('name', ev.get('event', '')))[:40]}")
        risk = macro.get('risk_bias') or macro.get('bias')
        if risk:
            lines.append(_row('DXY / Risk', str(risk)))
    return '\n'.join(lines), [_nav('tr', 'plan')]


def trade_plan_hist() -> tuple[str, list]:
    lines = ['📜 <b>تاریخچه بازبینی پلن</b>', '']
    try:
        with (DATA / 'xau_plan/reassessment_log.csv').open(encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
    except Exception:
        rows = []
    for r in rows[-8:][::-1]:
        ob, nb = str(r.get('old_bias', '')), str(r.get('new_bias', ''))
        arrow = '🔄' if ob != nb else '➡️'
        at = str(r.get('at', ''))[5:16].replace('T', ' ')
        lines.append(f'{arrow} {at} · {ob} ← {nb}')
    if not rows:
        lines.append('—')
    return '\n'.join(lines), [_nav('tr', 'plan')]


def trade_positions() -> tuple[str, list]:
    _, acct, pos = _bridge()
    rows = pos.get('data') or []
    if not acct.get('ok'):
        return ('📌 <b>پوزیشن‌ها</b>\n\n🔴 بریج ویندوز در دسترس نیست.',
                [_nav('tr', 'home')])
    if not rows:
        open_now, _, flip = _market_state()
        lines = ['📌 <b>پوزیشن‌ها</b>', _fa_date(), '', 'هیچ پوزیشن بازی نیست.',
                 _row('Balance', f"{_num(acct.get('balance'))} $ · دارایی {_num(acct.get('equity'))} $")]
        if not open_now and flip and flip[1]:
            lines.append(_row('Reopens', f'ساعت {flip[0]} تهران'))
        return '\n'.join(lines), [_nav('tr', 'home')]
    lines = ['📌 <b>پوزیشن‌های باز</b>', _fa_date(), '']
    kb = []
    tot = 0.0
    for p in rows:
        try:
            profit = float(p.get('profit') or 0)
            tot += profit
            d = '🟢' if profit > 0 else ('⚪' if profit == 0 else '🔴')
            side = 'خرید' if str(p.get('type')).upper() in ('BUY', '0') else 'فروش'
            lines.append(f'{d} <b>{side}</b> {_num(p.get("volume"), 2)} لات از {_num(p.get("open_price"))}')
            lines.append(f'   SL {_num(p.get("sl"))} · TP {_num(p.get("tp"))} · فعلی {_num(p.get("current_price"))} → <b>{profit:+,.2f} $</b>')
            tk = str(p.get('ticket', ''))
            if tk:
                kb.append([_btn(f'🔍 جزئیات پوزیشن {tk}', f'tr:pos:{tk}')])
        except Exception:
            continue
    lines += ['', _row('Floating P&L', f'<b>{tot:+,.2f} $</b>')]
    kb.append(_nav('tr', 'home'))
    return '\n'.join(lines), kb


def trade_pos_detail(ticket: str) -> tuple[str, list]:
    _, acct, pos = _bridge()
    p = next((x for x in (pos.get('data') or []) if str(x.get('ticket')) == ticket), None)
    if not p:
        return ('🔴 این پوزیشن دیگر باز نیست (بسته شده).', [_nav('tr', 'pos')])
    rt = _j(DATA / 'xau_plan/runtime_state.json')
    mg = (rt.get('management') or {}).get(str(p.get('position_id') or ticket)) or {}
    side = 'خرید' if str(p.get('type')).upper() in ('BUY', '0') else 'فروش'
    try:
        profit = float(p.get('profit') or 0)
        op = float(p.get('open_price') or 0)
        cur = float(p.get('current_price') or 0)
        pts = (cur - op) if side == 'خرید' else (op - cur)
    except Exception:
        profit, pts = 0.0, 0.0
    lines = [f'🔍 <b>پوزیشن {ticket}</b>', '',
             _row('Bias', f'{side} · {_num(p.get("volume"), 2)} لات'),
             _row('Entry', _num(p.get('open_price'))),
             _row('Price', _num(p.get('current_price'))),
             _row('SL / TP', f'{_num(p.get("sl"))} / {_num(p.get("tp"))}'),
             _row('Move', f'{pts:+,.2f} دلار · سود {profit:+,.2f} $')]
    if mg:
        lines.append(_sec('🧠 مدیریت سیستم'))
        for k in ('action', 'reason', 'sl_new', 'updated_at'):
            if mg.get(k):
                lines.append(_row({'action': 'اقدام', 'reason': 'دلیل',
                                   'sl_new': 'حد ضرر جدید', 'updated_at': 'آخرین به‌روزرسانی'}[k],
                                  str(mg[k])[:60]))
    return '\n'.join(lines), [_nav('tr', 'pos')]


def trade_pnl() -> tuple[str, list]:
    perf = _j(DATA / 'xau_plan/performance_state.json')
    st = _stats()
    dp = perf.get('daily_pnl') or 0
    d = '🟢' if dp > 0 else ('⚪' if dp == 0 else '🔴')
    lines = ['💰 <b>سود و ضرر</b>', _fa_date(), '',
             f'{d} امروز: <b>{dp:+,.2f} $</b>',
             _row('Trades Today', f"{st['today']['n']} · برد {st['today']['wins']}"),
             _row('Day Start Balance', f'{_num(perf.get("starting_balance"))} $')]
    if st['recent']:
        lines.append(_sec('🕯 آخرین خروج‌ها'))
        for when, side, vol, p, cm in st['recent'][:5]:
            dd = '🟢' if p > 0 else ('⚪' if p == 0 else '🔴')
            lines.append(f'{dd} {when} · {side} {_num(vol)} · {p:+,.2f} $')
    kb = [[_btn('📊 آمار پیشرفته', 'tr:stats'), _btn('📜 لیست تریدها', 'tr:pnl:list')],
          _nav('tr', 'home')]
    return '\n'.join(lines), kb


def trade_stats() -> tuple[str, list]:
    st = _stats()
    lines = ['📊 <b>کارنامه (KPI حرفه‌ای)</b>', _fa_date(), ''] + _stats_panel_lines(st)
    return '\n'.join(lines), [_nav('tr', 'home')]


def trade_pnl_list() -> tuple[str, list]:
    st = _stats()
    lines = ['📜 <b>۱۰ ترید اخیر</b>', '']
    for when, side, vol, p, cm in st['recent']:
        dd = '🟢' if p > 0 else ('⚪' if p == 0 else '🔴')
        tag = f' <i>{cm[:18]}</i>' if cm else ''
        lines.append(f'{dd} {when} · {side} {_num(vol)} لات · {p:+,.2f} ${tag}')
    if not st['recent']:
        lines.append('—')
    return '\n'.join(lines), [_nav('tr', 'pnl')]


def trade_sig() -> tuple[str, list]:
    sigs = _j(DATA / 'signals/signals_log.json', [])
    lines = ['📡 <b>سیگنال‌های کانال (پروژه ۲)</b>', _fa_date(), '']
    if not sigs:
        lines.append('هنوز سیگنالی ثبت نشده.')
    for s in (sigs or [])[-5:][::-1]:
        dec = s.get('decision') or {}
        p = s.get('parsed') or {}
        v = str(dec.get('verdict', '?'))
        d = {'EXECUTED': '✅ اجرا شد', 'TRADED': '✅ اجرا شد', 'REJECTED': '🚫 رد شد',
             'SKIPPED': '⏭ رد شد', 'FAILED': '🔴 خطا'}.get(v.upper(), f'❓ {v}')
        when = str(s.get('timestamp', ''))[5:16].replace('T', ' ')
        lines.append(f'<b>{when}</b> · {p.get("side", "?")} {_num(p.get("entry"))} → {d}')
        if dec.get('score') is not None:
            lines.append(f'   امتیاز {dec.get("score")}/{dec.get("max_score", 10)} · {str((dec.get("reasons") or [""])[0])[:70]}')
    return '\n'.join(lines), [_nav('tr', 'home')]


def trade_risk() -> tuple[str, list]:
    ks = _j(DATA / 'kill_switch_state.json')
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
    lines = ['🛡 <b>گیت‌های ایمنی</b>', _fa_date(), '',
             _dot(not ks.get('halted')) + (' <b>ترید مجاز</b>' if not ks.get('halted')
              else f' <b>متوقف</b> — {ks.get("halt_reason", "")}')]
    # b40: entry gates can be green while the MANAGEMENT guards (news_lock /
    # time_exit on the fallback path) are degraded — show both on one panel.
    g = _guard_line()
    if g:
        lines.append(f'🛑 {g}')
    lines.append(_sec('📉 فاصله تا توقف'))
    lines.append(_row('Daily Loss', f'{_bar(daily_pct / (DAILY_LOSS_LIMIT_PCT * 100))} '
                      f'{daily_pct:.1f}٪ از {DAILY_LOSS_LIMIT_PCT * 100:.0f}٪'))
    cl = ks.get('consecutive_losses', 0)
    lines.append(_row('Loss Streak', f'{_bar(cl / CONSECUTIVE_LOSSES_LIMIT)} '
                      f'{cl} از {CONSECUTIVE_LOSSES_LIMIT}'))
    lines.append(_row('Trades Today', str(perf.get('trades_today', 0))))
    lines.append(_sec('🕐 بازار'))
    if open_now:
        mk = '🟢 باز'
        if flip and not flip[1]:
            mk += f' — بسته می‌شود {flip[0]}'
    else:
        mk = f'🔴 بسته ({reason})' if reason else '🔴 بسته'
        if flip and flip[1]:
            mk += f' — باز می‌شود {flip[0]}'
    lines.append(_row('XAUUSD', mk))
    kb = [[_btn('⏸ کول‌داون‌ها', 'tr:risk:cooldown')], _nav('tr', 'home')]
    return '\n'.join(lines), kb


def trade_risk_cooldown() -> tuple[str, list]:
    cd = _j(DATA / 'cooldown_state.json')
    now = datetime.now(timezone.utc)
    lines = ['⏸ <b>کول‌داون‌ها و محدودیت‌های زمانی</b>', '']
    act = []
    for k, v in cd.items():
        if k.startswith('_'):
            continue
        until = (v or {}).get('until') if isinstance(v, dict) else None
        if until:
            try:
                t = datetime.fromisoformat(str(until).replace('Z', '+00:00'))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if t > now:
                    act.append(f'· <b>{k}</b> تا {t.astimezone(TEHRAN).strftime("%H:%M")} ({_ago(until)})')
            except Exception:
                act.append(f'· {k} تا {until}')
    lm = cd.get('_last_master_run') or {}
    if lm.get('at'):
        lines.append(_row('Last Cycle', _ago(lm['at'])))
    lines += act if act else ['هیچ محدودیت فعالی نیست — همه گیت‌ها باز هستند']
    return '\n'.join(lines), [_nav('tr', 'risk')]


def trade_control() -> tuple[str, list]:
    ks = _j(DATA / 'kill_switch_state.json')
    lines = ['🎛 <b>کنترل تریدر</b>', _fa_date(), '',
             'عملیات خطرناک با تأیید دومرحله‌ای و ثبت در لاگ.', '']
    if ks.get('halted'):
        lines.append(f'⛔ ترید <b>متوقف</b> — {ks.get("halt_reason", "")} (از {_ago(ks.get("halted_at"))})')
    else:
        lines.append('🟢 ترید فعال — ورود خودکار روشن است')
    kb = []
    if ks.get('halted'):
        kb.append([_btn('▶️ ازسرگیری ترید', 'tr:ask:trade:resume')])
    else:
        kb.append([_btn('⛔ توقف فوری ترید', 'tr:ask:trade:halt')])
    kb.append([_btn('🔁 ریستارت سرویس سیگنال', 'tr:ask:restart:hermes-signal'),
               _btn('🔁 ریستارت سرویس پوزیشن', 'tr:ask:restart:hermes-position')])
    kb.append(_nav('tr', 'home'))
    return '\n'.join(lines), kb


def trade_confirm(action: str) -> tuple[str, list]:
    desc = _ACTION_DESC.get(action, action)
    lines = ['⚠️ <b>تأیید عملیات</b>', '', desc, '', 'مطمئنی؟']
    kb = [[_btn('✅ بله، انجام بده', f'tr:cfm:{action}'),
           _btn('❌ انصراف', 'tr:control')]]
    return '\n'.join(lines), kb


TRADE_RENDER = {
    'home': trade_home, 'plan': trade_plan, 'plan:detail': trade_plan_detail,
    'plan:hist': trade_plan_hist, 'pos': trade_positions, 'pnl': trade_pnl,
    'pnl:list': trade_pnl_list, 'stats': trade_stats, 'sig': trade_sig,
    'risk': trade_risk, 'risk:cooldown': trade_risk_cooldown, 'control': trade_control,
}


def trade_render(panel: str) -> tuple[str, list]:
    try:
        if panel.startswith('pos:'):
            return trade_pos_detail(panel[4:])
        if panel.startswith('ask:'):
            return trade_confirm(panel[4:])
        fn = TRADE_RENDER.get(panel, trade_home)
        return fn()
    except Exception as e:
        return f'🔴 پنل {panel} خطا داد: {str(e)[:120]}', [[_btn('🏠 خانه', 'tr:home')]]


# ══════════════════════ OPERATOR CONTROLS ══════════════════════

_ACTION_DESC = {
    'auto:pause': '⏸ اتوپایلوت موقتاً متوقف می‌شود — اجرای ساعتی تا ازسرگیری دستی رد می‌شود. روی ترید زنده اثری ندارد.',
    'auto:resume': '▶️ اتوپایلوت از اجرای ساعتی بعدی ادامه می‌دهد.',
    'trade:halt': '⛔ <b>kill switch فعال می‌شود</b> — ورود جدید بسته، پوزیشن باز فقط مدیریت می‌شود (بسته نمی‌شود).',
    'trade:resume': '▶️ ترید ازسرگیری می‌شود — گیت‌های خودکار دوباره حاکم‌اند.',
}
for _s, _l in RESTARTABLE.items():
    _ACTION_DESC[f'restart:{_s}'] = f'🔁 سرویس {_l} ریستارت می‌شود (۲-۳ ثانیه قطعی کوتاه).'


def _audit(action: str, result: str):
    try:
        audit_log = _audit_log()
        audit_log.parent.mkdir(parents=True, exist_ok=True)
        with audit_log.open('a', encoding='utf-8') as f:
            f.write(f'{datetime.now(timezone.utc).isoformat()} | {action} | {result}\n')
    except Exception:
        pass


def handle_control(action: str) -> tuple[bool, str]:
    """Execute an operator action (already confirmed + owner-gated).
    Returns (ok, persian_result_line)."""
    ok, msg = False, 'نامعلوم'
    try:
        if action == 'auto:pause':
            flag = _pause_flag()
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text(datetime.now(TEHRAN).strftime('%Y-%m-%d %H:%M تهران'))
            ok, msg = True, '⏸ اتوپایلوت متوقف شد — اجرای ساعتی بعدی رد می‌شود.'
        elif action == 'auto:resume':
            try:
                _pause_flag().unlink()
            except FileNotFoundError:
                pass
            ok, msg = True, '▶️ اتوپایلوت ازسرگیری شد — اجرای ساعتی بعدی فعال است.'
        elif action == 'trade:halt':
            import sys
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            from engines.kill_switch import force_halt
            force_halt('operator_halt_dashboard')
            ok, msg = True, '⛔ ترید متوقف شد (kill switch) — ورود جدید بسته است.'
        elif action == 'trade:resume':
            import sys
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            from engines.kill_switch import force_resume
            force_resume()
            ok, msg = True, '▶️ ترید ازسرگیری شد — گیت‌های خودکار دوباره حاکم‌اند.'
        elif action.startswith('restart:'):
            svc = action.split(':', 1)[1]
            if svc not in RESTARTABLE:
                ok, msg = False, '🔴 سرویس ناشناخته — ریستارت نشد.'
            else:
                r = subprocess.run(['systemctl', '--user', 'restart', svc],
                                   capture_output=True, text=True, timeout=30)
                if r.returncode == 0:
                    ok, msg = True, f'🔁 {RESTARTABLE[svc]} ریستارت شد و بالاست.'
                else:
                    ok, msg = False, f'🔴 ریستارت {RESTARTABLE[svc]} شکست خورد: {r.stderr[:80]}'
        else:
            ok, msg = False, '🔴 عملیات ناشناخته انجام نشد.'
    except Exception as e:
        ok, msg = False, f'🔴 خطا در اجرای عملیات: {str(e)[:100]}'
    _audit(action, 'OK' if ok else msg)
    return ok, msg
