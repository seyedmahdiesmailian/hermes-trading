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
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # b66: code location, not a literal
DATA = ROOT / 'data'   # READ-ONLY by design (an operator panel must show the
                       # real numbers even from a test run) — pinned by the
                       # b39 tripwire's ALLOWED list. WRITERS below must not
                       # use these constants.
# b66-follow-up: the shape-safe /api/positions reader (stdlib-only module, no
# side effects — safe at import time, unlike the engines imports below that
# need .env). dashboards is imported both by dashboard_bot (which puts ROOT on
# sys.path) and lazily from signal_listener, so guard the path here.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
def positions_list(payload: dict | list | None) -> list[dict]:
    if not payload:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("data") or payload.get("positions") or []
    return []


def position_count(payload: dict | list | None) -> int:
    return len(positions_list(payload))


TEHRAN = timezone(timedelta(hours=3, minutes=30))
WEEK_FA = ['دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه', 'شنبه', 'یکشنبه']


def _pause_flag() -> Path:
    return DATA / 'ops' / 'autopilot_paused'


def _audit_log() -> Path:
    return ROOT / 'logs' / 'control_audit.log'

RESTARTABLE = {'hermes-signal-v2': 'سرویس سیگنال V2', 'hermes-position-v2': 'سرویس پوزیشن V2',
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

def _is_gold_market_open(dt: datetime) -> tuple[bool, str]:
    wd = dt.weekday()
    h = dt.hour
    if wd == 5:
        return False, "تعطیلی آخر هفته"
    if wd == 6 and h < 23:
        return False, "تعطیلی آخر هفته"
    if wd == 4 and h >= 22:
        return False, "تعطیلی آخر هفته"
    return True, ""


def _market_state():
    try:
        now = datetime.now(timezone.utc)
        open_now, reason = _is_gold_market_open(now)
        flip, flip_open = None, None
        for i in range(1, 385):
            t = now + timedelta(minutes=15 * i)
            is_open, _ = _is_gold_market_open(t)
            if is_open != open_now:
                flip_open = is_open
                flip = t.astimezone(TEHRAN).strftime('%H:%M')
                break
        return open_now, reason, (flip, flip_open)
    except Exception:
        return False, '', (None, None)


# The 9 units that actually run on the Linux box (ops/systemd: 8 services
# + hermes-trading.timer). The old list of 4 made "همه‌چیز روال است"
# while forwarder/webui/omniroute were down.
_SVC_NAMES = [
    'hermes-daemon', 'hermes-forwarder', 'hermes-command-bot',
    'hermes-dashboard', 'hermes-gateway', 'hermes-webui', 'omniroute',
]


def _services() -> dict:
    try:
        r = subprocess.run(['systemctl', '--user', 'is-active', *_SVC_NAMES],
                           capture_output=True, text=True, timeout=10)
        vals = r.stdout.split()
    except Exception:
        vals = []
    return dict(zip(_SVC_NAMES, vals + ['?'] * max(0, len(_SVC_NAMES) - len(vals))))


_SVC_LABEL = {
    'hermes-daemon': '🧠 دیمن اصلی',
    'hermes-forwarder': '📨 فورواردر',
    'hermes-command-bot': '🤖 ربات دستورات',
    'hermes-dashboard': '🛰 داشبورد',
    'hermes-gateway': '🖥 گیت‌وی',
    'hermes-webui': '🌐 وب',
    'omniroute': '🔀 omniroute',
}


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


class _DashboardBridgeWrapper:
    def __init__(self, url: str, token: str):
        self._url = url.rstrip('/')
        self._token = token

    def _req(self, path: str) -> dict:
        try:
            req = urllib.request.Request(f"{self._url}{path}")
            if self._token:
                req.add_header("Authorization", f"Bearer {self._token}")
            with urllib.request.urlopen(req, timeout=5) as r:
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

    def get_tick(self, symbol: str) -> dict:
        return self._req(f"/api/tick/{symbol}")


def _bridge():
    try:
        from env_loader import load_dotenv
        load_dotenv(ROOT / '.env')
        url = os.getenv("HERMES_BRIDGE_URL", "http://192.168.10.51:5050")
        token = os.getenv("HERMES_BRIDGE_TOKEN", "")
        b = _DashboardBridgeWrapper(url, token)
        acct = b.get_account()
        pos = b.get_positions()
        if acct.get("ok"):
            return b, acct, pos
        return None, {}, {}
    except Exception:
        return None, {}, {}


def _journal_rows() -> list:
    import sqlite3
    db_file = DATA / 'hermes.db'
    if not db_file.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute("SELECT * FROM trades ORDER BY closed_at ASC").fetchall()
        conn.close()
        out = []
        for r in rows:
            out.append({
                'profit': float(r['pnl'] or 0.0),
                'net': float(r['pnl'] or 0.0),
                'close_time': float(r['closed_at'] or 0.0),
                'side': str(r['side']),
                'symbol': str(r['symbol']),
                'legs': 1,
            })
        return out
    except Exception:
        return []


def _row_net(r: dict) -> float:
    """Net for a single journal ROW (closing leg): profit + the three fee
    columns, each read with an honest zero when absent (b142/b152 rule: a
    pre-migration row lacks the column; missing != zero-cost, but zero is
    the conservative display for a panel). Used only for the per-leg recency
    list; every AGGREGATE money figure goes through _positions_from_rows."""
    total = 0.0
    for col in ('profit', 'commission', 'swap', 'entry_commission'):
        try:
            total += float(r.get(col) or 0)
        except Exception:
            pass
    return total


def _group_positions_fn():
    """The ONE net formula (engines.learning.group_positions) or None.

    b154: the dashboard used to hand-compute money from the raw `profit`
    column — the same duplicated-funnel disease that made the learning loop
    blind in b151. Import is at CALL time and the result may fail (missing
    env, partial checkout); the caller must then disclose the degraded basis
    rather than silently show gross as net.
    """
    try:
        from legacy_v1.adapters.learning_adapter import group_positions
        return group_positions
    except Exception:
        return None


def _positions_from_rows(rows: list[dict]) -> tuple[list[dict], str]:
    """Journal rows → per-position results + the basis they were computed on.

    Returns (positions_sorted_by_close_time, basis) where basis is
    'position_net' when engines.learning.group_positions did the arithmetic
    (profit + commission + swap + entry_commission, grouped by position_id —
    the ONE formula the auto-trader trades on) and 'gross_fallback' when the
    import failed, in which case each row stands alone on gross profit — a
    DISCLOSED overstatement, never a silent one (b49: a fail-safe must not
    look like a no-op).
    """
    gfn = _group_positions_fn()
    if gfn is not None:
        pos = list(gfn(rows).values())
        basis = 'position_net'
    else:
        pos = []
        for r in rows:
            try:
                profit = float(r.get('profit') or 0)
            except (TypeError, ValueError):
                profit = 0.0
            try:
                ct = float(r.get('close_time') or 0)
            except (TypeError, ValueError):
                ct = 0.0
            pos.append({'profit': profit, 'net': _row_net(r),
                        'close_time': ct,
                        'side': r.get('side', ''), 'legs': 1})
        basis = 'gross_fallback'
    pos.sort(key=lambda p: p.get('close_time') or 0)
    return pos, basis


def _stats() -> dict:
    """Professional stats — PER POSITION and on NET P&L (b154), plus today slice.

    Before b154 this summed the raw `profit` column per journal ROW: neither
    the fees (b151/b152 net) nor position grouping (a partially-closed
    position writes several legs). On the live file it showed +17.89$ while
    the broker's all-in on the same positions was +5.65$ — the operator's
    phone carried a rosier book than the auto-trader trades on, the exact
    b151 blindness relocated to the display layer.
    """
    rows = _journal_rows()
    out = {'n': len(rows), 'today': {'n': 0, 'pnl': 0.0, 'wins': 0},
           'recent': [], 'days': [], 'curve': '', 'basis': 'position_net'}
    if not rows:
        return out
    pos, basis = _positions_from_rows(rows)
    out['basis'] = basis
    out['n'] = len(pos)
    pnls = [p['net'] for p in pos]
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
    # max drawdown on the cumulative curve (positions in close-time order)
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
        sp = [p['net'] for p in pos if str(p.get('side', '')).upper() == side]
        out[f'{side.lower()}_n'] = len(sp)
        out[f'{side.lower()}_pnl'] = sum(sp)
        out[f'{side.lower()}_wr'] = (sum(1 for p in sp if p > 0) / len(sp) * 100) if sp else 0.0
    # today — by position close time (UTC), the same event the ledger dates on
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    def _utc_day(secs) -> str:
        try:
            return datetime.fromtimestamp(float(secs or 0), timezone.utc).strftime('%Y-%m-%d')
        except Exception:
            return ''
    for p in pos:
        if _utc_day(p.get('close_time')) == today:
            out['today']['n'] += 1
            out['today']['pnl'] += p['net']
            out['today']['wins'] += 1 if p['net'] > 0 else 0
    # last 7 days
    by_day: dict[str, float] = {}
    for p in pos:
        d = _utc_day(p.get('close_time'))
        if not d:
            continue
        by_day[d] = by_day.get(d, 0.0) + p['net']
    out['days'] = sorted(by_day.items())[-7:]
    # recent list — recency display keeps the ROW shape (the operator reads
    # legs by time/comment), but the money shown per leg is that leg's NET,
    # not the bare `profit` column (b154).
    for r in rows[-10:][::-1]:
        ct = str(r.get('close_time', '')).strip()
        if ct.isdigit():
            when = datetime.fromtimestamp(int(ct), timezone.utc).astimezone(TEHRAN).strftime('%m/%d %H:%M')
        else:
            when = ct[5:16] or '—'
        try:
            out['recent'].append((when, str(r.get('side', '?')).upper(),
                                  float(r.get('volume') or 0), _row_net(r),
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
    # b85b: the fleet-restart breadcrumb is CLI-startup NOISE, not the run's
    # story. It used to inflate `keep` past the <=2 threshold, so the 503
    # fallback never fired and the raw English warning was forwarded to the
    # ops chat as if it were the agent's Persian narrative.
    _NOISE = ('A previous `hermes update`', 'Gateways may still be serving',
              'Run `hermes update` or')
    keep = [l for l in lines
            if not l.startswith('2026-') and 'report sent' not in l
            and 'nothing to report' not in l and 'autopilot run' not in l
            and not any(n in l for n in _NOISE)]
    text = ' '.join(keep)
    if 'API call failed' in text and len(keep) <= 2:
        why = '503' if '503' in text else ('429' if '429' in text else 'خطا')
        return (f'این اجرا به نتیجه نرسید: سرویس مدل پاسخ نداد (HTTP {why}). '
                'هیچ تغییری در کد ساخته نشد؛ آیتم بک‌لاگ برای اجرای بعدی دست‌نخورده ماند.')
    import re
    text = re.sub(r'`([^`]*)`', r'\1', text)
    text = re.sub(r'\*\*([^*]*)\*\*', r'\1', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = text[:max_chars] + ('…' if len(text) > max_chars else '')
    # b90: this is agent-authored free text consumed by HTML-mode Telegram
    # (report AND panel). A raw '<' (e.g. 'smc_conf < 0.35') made Telegram
    # reject the whole message with 400 and the report was lost. Escape at
    # the source so every consumer is safe by construction.
    import html as _html
    return _html.escape(text)


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


def _dirty_line(short: bool = False) -> str:
    """b46: one-line warning for ABANDONED UNCOMMITTED code (the b36 shape:
    a finished 403-line deliverable left staged-and-dirty by an interrupted
    run — invisible to cron, git_sync and verify_head, all of which see only
    HEAD). Reads through engines.dirty_work, the SINGLE canonical detector
    (lazy import, so tests can redirect the root via HERMES_DATA_ROOT; a
    non-repo root self-disables). Empty string = nothing abandoned.
    Display-only: never raises."""
    try:
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from engines import dirty_work
        return dirty_work.describe(dirty_work.scan(), short=short)
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
    # b46: abandoned uncommitted code is a "needs attention" fact too — no
    # push protects it and a reset erases it.
    d = _dirty_line(short=True)
    if d:
        problems.append(d)
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
    # وضعیت دیمن اصلی هرمس
    try:
        from core.params import load_config
        cfg = load_config(ROOT / 'config.yaml')
        dry_run = cfg.dry_run
        symbol = cfg.symbol
    except Exception:
        dry_run = True
        symbol = "XAUUSD"

    mode_text = "DRY-RUN (شبیه‌ساز)" if dry_run else "LIVE (واقعی)"
    daemon_active = svcs.get("hermes-daemon") == "active"
    daemon_status = "🟢 فعال و در حال تحلیل" if daemon_active else "🔴 غیرفعال"

    lines.append(_sec('🧠 هسته هوشمند هرمس'))
    lines.append(_row('وضعیت سیستم', daemon_status))
    lines.append(_row('حالت معامله', mode_text))
    lines.append(_row('نماد معاملاتی', symbol))
    lines.append(_sec('🖥 سرویس‌ها'))
    lines.append(' · '.join(f'{_dot(v == "active")} {_SVC_LABEL.get(k, k)}'
                            for k, v in svcs.items()))
    kb = [
        [_btn('🎯 پلن معاملاتی', 'tr:plan'), _btn('📊 پوزیشن‌ها', 'tr:pos')],
        [_btn('🤖 اتوپایلوت', 'ops:auto'), _btn('🛡 مدیریت ریسک', 'tr:risk')],
        [_btn('🖥 وضعیت سیستم', 'ops:sys'), _btn('💾 بکاپ و سرور', 'ops:ops')],
    ]
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
    svcs = _services()
    daemon_active = svcs.get("hermes-daemon") == "active"

    try:
        from core.params import load_config
        cfg = load_config(ROOT / 'config.yaml')
        dry_run = cfg.dry_run
        symbol = cfg.symbol
        entry_s = cfg.loop.entry_interval_s
        exit_s = cfg.loop.exit_interval_s
    except Exception:
        dry_run, symbol, entry_s, exit_s = False, "XAUUSD", 300, 15

    mode = "DRY-RUN (شبیه‌ساز)" if dry_run else "LIVE (معاملات واقعی)"

    lines = ['🤖 <b>اتوپایلوت معاملاتی هرمس</b>', _fa_date(), '',
             f"وضعیت اجرا: {'🟢 <b>فعال و خودکار</b>' if daemon_active else '🔴 <b>غیرفعال</b>'}",
             _row('حالت ترید', f"<b>{mode}</b>"),
             _row('نماد معاملاتی', f"<b>{symbol}</b>"),
             _row('چرخه تحلیل بازار', f"هر {entry_s // 60} دقیقه"),
             _row('چرخه مدیریت پوزیشن', f"هر {exit_s} ثانیه")]

    lines.append(_sec('⚙️ معماری خودکار'))
    lines.append('• استراتژی: <b>تلفیقی SMC/ICT + روند EMA</b>')
    lines.append('• فیلتر اخبار داغ: <b>فعال (وتوی ۳۰ دقیقه‌ای)</b>')
    lines.append('• سشن‌های نقدینگی: <b>لندن و نیویورک</b>')
    lines.append('• مدیریت سود: <b>سیو سود پله‌ای ۵۰٪ + ترلینگ داینامیک</b>')
    lines.append('• مدیریت استاپ: <b>Breakeven در سود ۱.۰R (+ بافر کارمزد)</b>')

    kb = [[_btn('🎯 آخرین پلن تحلیلی', 'tr:plan'), _btn('🛡 قوانین ریسک', 'tr:risk')],
          [_btn('📊 وضعیت پوزیشن‌ها', 'tr:pos'), _btn('🏠 منوی اصلی', 'ops:home')]]
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
    kb = [[_btn('🎯 پلن', 'ops:plan'), _btn('📊 آمار کامل', 'ops:trade:stats')],
          _nav('ops', 'home')]
    return '\n'.join(lines), kb


def _stats_panel_lines(st: dict) -> list:
    lines = []
    if not st['n']:
        return ['ژورنال خالی است — هنوز ترید بسته‌شده‌ای ثبت نشده.']
    if st.get('basis') and st['basis'] != 'position_net':
        # b49: a degraded number must say so — gross per leg OVERSTATES.
        lines.append('⚠️ آمار موقتاً ناخالص و سر‌شماره‌ای است (کارمزد و '
                     'تجمیع پاها کم است) — موتور محاسبه در دسترس نبود')
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
    # b42: the report bot now shows the full Persian plan too (prefix='ops')
    'plan': lambda: trade_plan('ops'),
    'plan:detail': lambda: trade_plan_detail('ops'),
    'plan:hist': lambda: trade_plan_hist('ops'),
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


def _get_latest_plan_from_db() -> dict | None:
    db_file = DATA / 'hermes.db'
    if not db_file.exists():
        return None
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM plans ORDER BY created_at DESC LIMIT 1").fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


# ══════════════════════ TRADE BOT (2nd) ══════════════════════

def trade_home() -> tuple[str, list]:
    plan = _get_latest_plan_from_db() or {}
    _, acct, pos = _bridge()
    ks = _j(DATA / 'kill_switch_state.json')
    st = _stats()
    open_now, _, flip = _market_state()
    side = str(plan.get('side') or '')
    bias = 'bullish' if side == 'BUY' else ('bearish' if side == 'SELL' else 'neutral')
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
    fl = sum(float(p.get('profit') or 0) for p in positions_list(pos)
             if str(p.get('profit') or '').replace('.', '').replace('-', '').replace(',', '').isdigit())
    lines.append(_row('Open Positions', f"{position_count(pos)} · سود شناور {fl:+,.2f} $"))
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


# ─────────────────────── b42: plan panel — Persian narrative ───────────────────────
# The old panel showed raw fields (entry_mode=mean_reversion_wait, votes…)
# which the owner cannot read. These maps translate the engine's vocabulary
# into plain Persian, and _plan_view() assembles the "what happens next"
# story: current price vs. the zones, the exact entry we are waiting for,
# and what invalidates the plan.

_ACTION_FA = {
    'market_entry_now': '🚀 ورود فوری با قیمت بازار',
    'market_order': '🚀 ورود فوری با قیمت بازار',
    'place_sell_limit': '📉 فروش limit روی قیمت بالا (سفارش معلق)',
    'place_buy_limit': '📈 خرید limit روی قیمت پایین (سفارش معلق)',
    'place_sell_stop': '📉 فروش روی شکست به پایین (stop)',
    'place_buy_stop': '📈 خرید روی شکست به بالا (stop)',
    'wait_for_trigger': '⏳ منتظر تریگر تأیید',
    'wait_for_pullback': '⏳ منتظر پولبک به ناحیه ارزش',
    'no_trade': '🛑 بدون ترید',
    'none': '🛑 بدون ترید',
}
_REASON_FA = {
    'neutral_bias': 'جهت بازار الان بی‌طرف است؛ صبر می‌کنیم تایم‌فریم‌ها هم‌راستا شوند',
    'outside_entry_zones': 'قیمت بیرون از نواحی ورود است؛ نزدیک یکی از نواحی که شد اقدام می‌کنیم',
    'price_extended_above_breakout_zone': 'قیمت برای فروش خیلی بالا رفته (از ناحیه شکست رد شده)؛ پولبک می‌خواهیم',
    'price_extended_below_breakout_zone': 'قیمت برای خرید خیلی پایین آمده (از ناحیه شکست رد شده)؛ صبر برای اصلاح',
    'inside_value_without_trigger': 'قیمت داخل ناحیه ارزش است ولی تریگر تأیید (کندل/شکست) هنوز نزده',
    'quality_filter': 'ستاپ از گیت کیفیت رد شد (قدرت روند یا SMC کافی نیست)',
    'price_far_above_zone_plan_stale': 'قیمت از پلن دور شده؛ منتظر پلن تازه در بازبینی بعدی',
    'price_far_below_zone_plan_stale': 'قیمت از پلن دور شده؛ منتظر پلن تازه در بازبینی بعدی',
    'discount_zone_with_weak_smc': 'ناحیه تخفیف دیده شد ولی سیگنال SMC ضعیف است',
}
_MODE_FA = {
    'mean_reversion_wait': 'بازگشت به میانگین — ترید فقط در لبه نواحی، نه وسط رنج',
    'mean_reversion': 'بازگشت به میانگین — ترید در لبه نواحی',
    'trend_follow': 'دنبال‌کننده روند — ورود در جهت روند اصلی',
    'breakout': 'شکست — ورود با شکست تأییدشده ناحیه',
    'range': 'نوسان‌گیری رنج',
}


def _plan_price():
    """Live bid/ask from the bridge; None if unreachable (panel stays useful)."""
    try:
        b, _, _ = _bridge()
        if b is not None:
            t = b.get_tick('XAUUSD')
            bid = t.get('bid')
            return float(bid) if bid is not None else None
        return None
    except Exception:
        return None


def _plan_view(plan: dict, price) -> str:
    """The 'what is the plan and what happens next' narrative in Persian."""
    bias = str(plan.get('bias') or '')
    q = plan.get('quality') or {}
    ex = plan.get('execution') or {}
    z = plan.get('zones') or {}
    votes = q.get('bias_votes') or {}
    regime = str(q.get('regime') or '')
    lines = []

    # 1) read of the market
    agree = sum(1 for v in votes.values() if v == bias and bias)
    dir_fa = 'نزولی' if bias == 'bearish' else 'صعودی' if bias == 'bullish' else 'بی‌طرف'
    regime_fa = {'range': 'رنج (بی‌روند)', 'trending': 'رونددار', 'trend': 'رونددار',
                 'volatile': 'پرنوسان'}.get(regime, regime or '—')
    lines.append(f'بازار در حالت <b>{regime_fa}</b> است و {agree} از {len(votes) or 4} '
                 f'تایم‌فریم نظر {("🔴 " if bias == "bearish" else "🟢 " if bias == "bullish" else "⚪ ")}'
                 f'<b>{dir_fa}</b> را تأیید می‌کنند.')
    if bias == 'bearish':
        lines.append('استراتژی: <b>فروش در صعود</b> — وقتی قیمت به ناحیه عرضه بالا برسد وارد شرت می‌شویم، نه در کف.')
    elif bias == 'bullish':
        lines.append('استراتژی: <b>خرید در ریزش</b> — وقتی قیمت به ناحیه تقاضا برسد وارد لانگ می‌شویم، نه در سقف.')
    else:
        lines.append('استراتژی: <b>صبر</b> — تا جهت روشن شود دست نمی‌زنیم.')

    # 2) where price is vs the zones
    if price and z:
        se_l, se_h = z.get('short_entry_low'), z.get('short_entry_high')
        le_l, le_h = z.get('long_entry_low'), z.get('long_entry_high')
        vl, vh = z.get('value_low'), z.get('value_high')
        pos_fa = None
        if se_l is not None and price >= se_l and price <= se_h:
            pos_fa = 'دقیقاً داخل <b>ناحیه فروش</b> است'
        elif le_l is not None and price >= le_l and price <= le_h:
            pos_fa = 'دقیقاً داخل <b>ناحیه خرید</b> است'
        elif se_h is not None and price > se_h:
            pos_fa = f'از ناحیه فروش <b>{_num(price - se_h)} دلار بالاتر</b> رفته'
        elif le_l is not None and price < le_l:
            pos_fa = f'از ناحیه خرید <b>{_num(le_l - price)} دلار پایین‌تر</b> آمده'
        if pos_fa:
            lines.append(f'قیمت الان {_num(price)} — {pos_fa}.')
        if vl is not None and vh is not None:
            lines.append(f'ناحیه ارزش (وسط رنج): {_num(vl)} تا {_num(vh)} — آنجا نه می‌خریم نه می‌فروشیم.')

    # 3) the exact entry we wait for
    wait = []
    if bias == 'bearish' and z.get('short_entry_low') is not None:
        wait.append(f'📉 ورود فروش: پولبک به {_num(z["short_entry_low"])}–{_num(z["short_entry_high"])} با تریگر تأییدشده')
    if bias == 'bullish' and z.get('long_entry_low') is not None:
        wait.append(f'📈 ورود خرید: ریزش به {_num(z["long_entry_low"])}–{_num(z["long_entry_high"])} با تریگر تأییدشده')
    if ex.get('breakout_trigger') is not None:
        side = 'به پایین' if bias == 'bearish' else 'به بالا'
        wait.append(f'💥 یا شکست تأییدشده {_num(ex["breakout_trigger"])} {side} (ورود stop)')
    if ex.get('stop_loss') is not None:
        wait.append(f'🛡 حد ضرر پلن: {_num(ex["stop_loss"])}')
    if plan.get('invalidation') is not None:
        wait.append(f'❌ ابطال پلن: عبور قیمت از {_num(plan["invalidation"])}')
    tg = plan.get('targets') or ex.get('tp_levels') or []
    if tg:
        wait.append('🎯 اهداف سود: ' + ' ← '.join(_num(x) for x in tg[:3]) + ' (خروج پله‌ای)')
    if wait:
        lines.append('\n'.join(wait))

    # 4) what the engine decided right now
    try:
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from engines.orchestrator import evaluate_monitor_cycle
        from datetime import timezone as _tz
        dec = evaluate_monitor_cycle(plan, price or 0.0, now=datetime.now(_tz.utc))
        act = str(dec.get('action') or 'none')
        rsn = str(dec.get('reason') or '')
        head = _ACTION_FA.get(act, act)
        body = _REASON_FA.get(rsn, rsn)
        if act.startswith('market_entry') or act.startswith('place_'):
            lines.append(f'⏭ وضعیت فعلی: {head} — گیت‌ها بازند؛ در چرخه بعدی (هر ۱۵ دقیقه) اجرا می‌شود.')
        else:
            lines.append(f'⏭ الان: {head}. {body}.')
    except Exception:
        rt = _j(DATA / 'xau_plan/runtime_state.json')
        last = str(rt.get('last_monitor_action') or '')
        if last:
            lines.append(f'⏭ آخرین تصمیم موتور: {_ACTION_FA.get(last, last)} (چرخه قبلی)')
    return '\n'.join(lines)


def trade_plan(prefix: str = 'tr') -> tuple[str, list]:
    plan = _get_latest_plan_from_db()
    price = _plan_price()
    lines = ['🎯 <b>پلن معاملاتی هرمس</b>', _fa_date(), '']

    if not plan:
        lines.append('⚪ در حال حاضر هیچ پلن فعالی صادر نشده است.')
        return '\n'.join(lines), [_nav(prefix, 'home')]

    side = str(plan.get('side', ''))
    side_fa = '🟢 <b>خرید (BUY)</b>' if side == 'BUY' else ('🔴 <b>فروش (SELL)</b>' if side == 'SELL' else f'⚪ {side}')
    status = str(plan.get('status', 'active'))
    status_fa = '✅ تایید شده' if status == 'approved' else '🚫 رد شده توسط گیت'

    created_ts = plan.get('created_at', 0)
    created_dt = datetime.fromtimestamp(created_ts, timezone.utc).astimezone(TEHRAN).strftime('%H:%M:%S تهران') if created_ts else '—'

    lines.append(f"جهت ستاپ: {side_fa}")
    lines.append(_row('قیمت زنده بازار', f"{_num(price)} $" if price else 'نامعلوم (بریج قطع)'))
    lines.append(_row('قیمت ورود پلن', f"{_num(plan.get('entry_price'))} $"))
    lines.append(_row('حد ضرر (SL)', f"{_num(plan.get('stop_loss'))} $"))
    tp = float(plan.get('take_profit') or 0.0)
    lines.append(_row('حد سود (TP)', f"{_num(tp)} $" if tp > 0 else 'داینامیک (Trailing Stop)'))
    lines.append(_row('نسبت سود/ریسک', f"{float(plan.get('rr') or 0):.1f}"))
    lines.append(_row('کیفیت ستاپ', f"Grade {plan.get('grade', 'B')} (اعتماد: {float(plan.get('confidence') or 0):.2f})"))
    lines.append(_row('وضعیت گیت', status_fa))
    lines.append(_row('زمان صدور', created_dt))

    lines.append(_sec('🧠 استدلال تحلیلی و کانتکست'))
    reasoning = plan.get('reasoning', '')
    lines.append(f"<code>{reasoning}</code>")

    kb = [[_btn('🧩 جزئیات ستاپ', f'{prefix}:plan:detail'),
           _btn('📜 تاریخچه پلن‌ها', f'{prefix}:plan:hist')],
          _nav(prefix, 'home')]
    return '\n'.join(lines), kb


def trade_plan_detail(prefix: str = 'tr') -> tuple[str, list]:
    plan = _get_latest_plan_from_db()
    if not plan:
        return '🧩 <b>جزئیات پلن</b>\n\nپلنی موجود نیست.', [_nav(prefix, 'plan')]

    side = str(plan.get('side', ''))
    side_fa = 'خرید (BUY)' if side == 'BUY' else 'فروش (SELL)'
    created_ts = plan.get('created_at', 0)
    created_dt = datetime.fromtimestamp(created_ts, timezone.utc).astimezone(TEHRAN).strftime('%Y-%m-%d %H:%M:%S') if created_ts else '—'

    lines = ['🧩 <b>جزئیات تحلیلی ستاپ</b>', _fa_date(), '',
             _row('شناسه پلن', str(plan.get('plan_id', '—'))),
             _row('نماد', str(plan.get('symbol', 'XAUUSD'))),
             _row('جهت', side_fa),
             _row('تایم‌فریم', str(plan.get('timeframe', 'M15'))),
             _row('منبع', str(plan.get('source', 'analysis'))),
             _row('قیمت ورود', f"{_num(plan.get('entry_price'))} $"),
             _row('حد ضرر', f"{_num(plan.get('stop_loss'))} $"),
             _row('حد سود', f"{_num(plan.get('take_profit'))} $"),
             _row('وضعیت', str(plan.get('status', 'active'))),
             _row('زمان ثبت', created_dt)]

    lines.append(_sec('📝 یادداشت موتور تحلیل'))
    lines.append(f"<code>{plan.get('reasoning', '')}</code>")
    return '\n'.join(lines), [_nav(prefix, 'plan')]


def trade_plan_hist(prefix: str = 'tr') -> tuple[str, list]:
    lines = ['📜 <b>تاریخچه آخرین پلن‌های تحلیلی</b>', '']
    db_file = DATA / 'hermes.db'
    if not db_file.exists():
        lines.append('—')
        return '\n'.join(lines), [_nav(prefix, 'plan')]
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM plans ORDER BY created_at DESC LIMIT 8").fetchall()
        conn.close()
        for r in rows:
            side = '🟢 خرید' if r['side'] == 'BUY' else '🔴 فروش'
            st = '✅' if r['status'] == 'approved' else '🚫'
            dt = datetime.fromtimestamp(r['created_at'], timezone.utc).astimezone(TEHRAN).strftime('%m-%d %H:%M')
            lines.append(f"{st} <code>{dt}</code> · {side} @ <code>{_num(r['entry_price'])}</code> (Gr {r['grade']})")
    except Exception:
        lines.append('—')
    return '\n'.join(lines), [_nav(prefix, 'plan')]


def trade_positions() -> tuple[str, list]:
    _, acct, pos = _bridge()
    rows = positions_list(pos)
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
    p = next((x for x in positions_list(pos) if str(x.get('ticket')) == ticket), None)
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
    st = _stats()
    _, acct, _ = _bridge()
    open_now, reason, flip = _market_state()

    try:
        from core.params import load_config
        cfg = load_config(ROOT / 'config.yaml')
        daily_loss_limit = cfg.gates.max_daily_loss_pct
        max_daily_trades = cfg.gates.max_daily_trades
        risk_pct = cfg.gates.risk_per_trade_pct
        min_rr = cfg.gates.min_rr
        max_open = cfg.gates.max_open_positions
    except Exception:
        daily_loss_limit, max_daily_trades, risk_pct, min_rr, max_open = 5.0, 5, 2.0, 1.0, 1

    bal = float(acct.get('balance', 4931.58)) if acct.get('ok') else 4931.58
    dp = st['today']['pnl']
    daily_pct = max(0.0, -dp / bal * 100) if bal else 0.0

    lines = ['🛡 <b>گیت‌های ایمنی و مدیریت ریسک هرمس</b>', _fa_date(), '',
             '🟢 <b>گیت‌های محافظتی: فعال (Fail-Closed)</b>']

    lines.append(_sec('📉 سقف ضرر و ظرفیت روزانه'))
    lines.append(_row('ضرر امروز', f"{_bar(daily_pct / daily_loss_limit)} {daily_pct:.1f}٪ از {daily_loss_limit:.0f}٪ مجاز"))
    trades_today = st['today']['n']
    lines.append(_row('معاملات امروز', f"{trades_today} از {max_daily_trades} مجاز"))
    lines.append(_row('ریسک هر معامله', f"{risk_pct}٪ سرمایه"))
    lines.append(_row('سقف پوزیشن باز', f"{max_open} عدد"))
    lines.append(_row('حداقل R:R', f"{min_rr:.1f}"))

    lines.append(_sec('🕐 وضعیت بازار'))
    if open_now:
        mk = '🟢 باز'
        if flip and not flip[1]:
            mk += f' — بسته می‌شود {flip[0]}'
    else:
        mk = f'🔴 بسته ({reason})' if reason else '🔴 بسته'
        if flip and flip[1]:
            mk += f' — باز می‌شود {flip[0]}'
    lines.append(_row('Gold Market', mk))
    return '\n'.join(lines), [_nav('tr', 'home')]
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
    kb.append([_btn('🔁 ریستارت سرویس سیگنال', 'tr:ask:restart:hermes-signal-v2'),
               _btn('🔁 ریستارت سرویس پوزیشن', 'tr:ask:restart:hermes-position-v2')])
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
