#!/usr/bin/env python3
"""Daily autopilot digest → Telegram (trading bot token, chat from .env).

b49 SELF-CHECK: `python3 scripts/autopilot_digest.py --self-check` (or
HERMES_SELFCHECK=1) turns the guarded `except Exception` sections into
loud failures AND suppresses the Telegram send, so a digest that prints
nothing because its machinery is broken can never be mistaken for one that
printed nothing because everything is fine. Normal (cron) behaviour is
byte-identical to before.  (b197 added the sizing-epoch section — the
b49 test counts handlers dynamically; never trust a literal in a docstring.)
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing → local fallback
load_dotenv(Path(__file__).resolve().parent.parent / '.env')

# b49: leaf seam (os/sys only) imported OUTSIDE the guard blocks below, so
# `selfcheck.fail` is always resolvable inside an except handler.
# engines moved to legacy_v1 (dead tree) — live scripts must NOT import it.
# Same behaviour, self-contained (mirrors legacy engines/selfcheck.py):
def _selfcheck_enabled() -> bool:
    return ((os.environ.get('HERMES_SELFCHECK') or '').strip().lower()
            in ('1', 'true', 'yes', 'on')) or '--self-check' in sys.argv[1:]


def _selfcheck_fail(section: str, exc: BaseException | None = None) -> None:
    if _selfcheck_enabled():
        raise RuntimeError(
            f'selfcheck: fail-safe section "{section}" raised — '
            f'{exc!r}')


def _ops_token() -> str:
    return os.getenv('AUTOPILOT_REPORT_BOT_TOKEN', '') or os.getenv('TELEGRAM_BOT_TOKEN', '')


def _ops_chat() -> str:
    return os.getenv('AUTOPILOT_REPORT_CHAT_ID', '') or os.getenv('TELEGRAM_CHAT_ID', '194015957')


_SELFCHECK = _selfcheck_enabled()

ROOT = Path(__file__).resolve().parent.parent  # b66: code location, not a literal
# b46: the uncommitted-work scan needs a GIT REPO (unlike the read-only data
# paths above). HERMES_REPO_ROOT lets a test point it at a throwaway repo
# instead of the live tree — the digest must never make its output depend on
# whether production happens to be mid-edit.
REPO = Path(os.getenv('HERMES_REPO_ROOT', str(ROOT)))
BACKLOG = ROOT / 'data/ops/autopilot_backlog.md'
STATE = ROOT / 'data/ops/autopilot_state.json'
LOG = ROOT / 'logs/autopilot.log'

lines = ['🤖 <b>گزارش خودکار سیستم معامله‌گر</b>', '']

# backlog progress
if BACKLOG.exists():
    txt = BACKLOG.read_text()
    todo = len(re.findall(r'^- \[ \]', txt, re.M))
    done = len(re.findall(r'^- \[x\]', txt, re.M))
    first_todo = re.search(r'^- \[ \] (.+)$', txt, re.M)
    lines.append(f'📋 بک‌لاگ: {done} انجام‌شده / {todo} باقی‌مانده')
    if first_todo:
        lines.append(f'➡️ بعدی: {first_todo.group(1)[:120]}')

# recent autopilot commits
try:
    commits = subprocess.run(['git', '-C', str(ROOT), 'log', '--oneline', '-6',
                              '--format=%s'], capture_output=True, text=True, timeout=10).stdout
    work = [c for c in commits.splitlines() if c.startswith('autopilot:')]
    if work:
        lines.append('')
        lines.append('🛠 کارهای این دوره:')
        lines += [f'· {c[len("autopilot:"):].strip()[:110]}' for c in work]
except Exception as e:
    _selfcheck_fail('git commits section', e)

# last run status
if STATE.exists():
    try:
        st = json.loads(STATE.read_text())
        lines.append('')
        lines.append(f'🕐 آخرین اجرا: {st.get("last_run_utc", "?")[:16]}')
    except Exception as e:
        _selfcheck_fail('last-run state section', e)

# b40: guard-degradation alert state (written by legacy hermes_master — now
# read self-contained; engines moved to legacy_v1, live scripts don't import it)
try:
    _g_file = ROOT / 'data' / 'ops' / 'guard_alert_state.json'
    _g = json.loads(_g_file.read_text(encoding='utf-8')) if _g_file.exists() else None
    if isinstance(_g, dict) and _g.get('state'):
        _gl = (f"گاردهای ایمنی مدیریت ضعیف شده [{_g.get('state')}]"
               f" · آخرین مشاهده {_g.get('at') or '?'}")
        lines.append('')
        lines.append(f'🛑 <b>{_gl}</b>')
except Exception as e:
    _selfcheck_fail('guard_status section', e)

# b46: ABANDONED UNCOMMITTED code — compact self-contained `git status` scan
# (engines.dirty_work moved to legacy_v1; live scripts don't import it).
try:
    _r = subprocess.run(['git', 'status', '--porcelain=v1', '-z', '--untracked-files=all'],
                        cwd=REPO, capture_output=True, timeout=15)
    _fields = [f for f in _r.stdout.decode('utf-8', 'replace').split('\0') if f]
    _dirty = []
    _i = 0
    while _i < len(_fields):
        _ln = _fields[_i]; _i += 1
        if len(_ln) < 4 or _ln[2] != ' ':
            continue
        _st, _p = _ln[:2], _ln[3:]
        if _st[0] in ('R', 'C'):
            _i += 1
        if _p.endswith(('.py', '.sh')) and ('/' not in _p
                       or _p.startswith(('tests/', 'scripts/', 'notifier/'))):
            _dirty.append((_st, _p))
    if _dirty:
        _names = '، '.join(p for _s, p in _dirty[:3]) + \
            (f' (+{len(_dirty)-3} دیگر)' if len(_dirty) > 3 else '')
        _dl = f"کد commitنشده رهاشده در working tree — {_names}"
        lines.append('')
        lines.append(f'📦 <b>{_dl}</b>')
except Exception as e:
    _selfcheck_fail('dirty_work section', e)

# b197: sizing-epoch line from the risk ledger. b196 wired the account's
# tiered base_risk_pct into entry sizing, so the FIRST >=5000-balance entry
# runs a 25% smaller lot than every pre-fix trade — without a note, that
# looks like a defect. Read through the CANONICAL reader
# (scripts/b143_risk_ledger_reader, imported not re-parsed): the classifier,
# the counts and the sentence all live there, one definition (b109 rule).
try:
    from scripts import b143_risk_ledger_reader as _b143
    _sz = _b143.sizing_epoch_summary(_b143.read_ledger())
    _szl = _b143.persian_sizing_line(_sz)
    if _szl:
        lines.append('')
        lines.append(f'⚖️ {_szl}')
except Exception as e:
    _selfcheck_fail('sizing epoch section', e)

# errors in autopilot log (last 200 lines)
if LOG.exists():
    try:
        tail = LOG.read_text(errors='ignore').splitlines()[-200:]
        errs = [l for l in tail if 'ERROR' in l or 'Traceback' in l][-3:]
        if errs:
            lines.append('⚠️ خطاها:')
            lines += [f'<code>{e[:120]}</code>' for e in errs]
    except Exception as exc:
        _selfcheck_fail('log-errors section', exc)

# system health one-liner (post-reset: ONE daemon — hermes-daemon owns trading)
try:
    svc = subprocess.run(['systemctl', '--user', 'is-active', 'hermes-daemon'],
                         capture_output=True, text=True, timeout=10).stdout.split()
    lines.append('')
    lines.append('🟢 دایمون ترید فعال' if all(s == 'active' for s in svc) else f'🔴 وضعیت دایمون: {svc}')
except Exception as e:
    _selfcheck_fail('systemctl health section', e)

text = '\n'.join(lines)
token = _ops_token()
chat = _ops_chat()
# b49: a self-check run must NEVER page Telegram — it prints the digest
# instead, so probing the machinery can't spam the ops chat.
if token and not _SELFCHECK:
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/sendMessage',
        data=json.dumps({'chat_id': chat, 'text': text, 'parse_mode': 'HTML'}).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req, timeout=15).read()
        print('digest sent')
    except Exception as e:
        print('send failed:', e)
else:
    print(text)
