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
from engines import selfcheck

_SELFCHECK = selfcheck.enabled()

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
    selfcheck.fail('git commits section', e)

# last run status
if STATE.exists():
    try:
        st = json.loads(STATE.read_text())
        lines.append('')
        lines.append(f'🕐 آخرین اجرا: {st.get("last_run_utc", "?")[:16]}')
    except Exception as e:
        selfcheck.fail('last-run state section', e)

# b40: guard-degradation alert state (written by hermes_master, b37). The
# ops chat gets a page; the daily digest must show it too, because the page
# is deduped to 1/6h and a degraded management path is exactly the kind of
# fact a skimmed digest should not lose. Read through engines.guard_status —
# the single canonical reader (never hand-parse the file again).
try:
    from engines import guard_status
    _gl = guard_status.describe(guard_status.read())
    if _gl:
        lines.append('')
        lines.append(f'🛑 <b>{_gl}</b>')
except Exception as e:
    selfcheck.fail('guard_status section', e)

# b46: ABANDONED UNCOMMITTED code. The b36 incident: a finished 403-line
# deliverable sat staged-and-dirty in the tree, invisible to cron, git_sync
# and verify_head (all see only HEAD), and the backlog still said `todo`.
# The daily digest is the last place that can catch it before a reset erases
# the work. Read through engines.dirty_work — the single canonical detector.
try:
    from engines import dirty_work
    _dl = dirty_work.describe(dirty_work.scan(REPO))
    if _dl:
        lines.append('')
        lines.append(f'📦 <b>{_dl}</b>')
except Exception as e:
    selfcheck.fail('dirty_work section', e)

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
    selfcheck.fail('sizing epoch section', e)

# errors in autopilot log (last 200 lines)
if LOG.exists():
    try:
        tail = LOG.read_text(errors='ignore').splitlines()[-200:]
        errs = [l for l in tail if 'ERROR' in l or 'Traceback' in l][-3:]
        if errs:
            lines.append('⚠️ خطاها:')
            lines += [f'<code>{e[:120]}</code>' for e in errs]
    except Exception as exc:
        selfcheck.fail('log-errors section', exc)

# system health one-liner
try:
    svc = subprocess.run(['systemctl', '--user', 'is-active', 'hermes-signal', 'hermes-position'],
                         capture_output=True, text=True, timeout=10).stdout.split()
    lines.append('')
    lines.append('🟢 دایمون‌ها فعال' if all(s == 'active' for s in svc) else f'🔴 وضعیت دایمون: {svc}')
except Exception as e:
    selfcheck.fail('systemctl health section', e)

text = '\n'.join(lines)
token = os.getenv('AUTOPILOT_REPORT_BOT_TOKEN', '') or os.getenv('TELEGRAM_BOT_TOKEN', '')
chat = os.getenv('AUTOPILOT_REPORT_CHAT_ID', os.getenv('TELEGRAM_CHAT_ID', '194015957'))
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
