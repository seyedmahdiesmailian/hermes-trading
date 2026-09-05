#!/usr/bin/env python3
"""Per-run autopilot report → Telegram (ops bot), Persian narrative.

b39 redesign: instead of a bare commit list, the report tells WHAT HAPPENED:
the agent's own Persian summary of the run (required by the autopilot
prompt), backlog progress, and the next queued item. Falls back to commit
subjects when the agent produced no narrative (e.g. model API failure).
Sends ONLY when something happened: new commits, backlog progress, or a
failed run. Silent on idle runs unless the run crashed.
Config: AUTOPILOT_REPORT_BOT_TOKEN / AUTOPILOT_REPORT_CHAT_ID.
State: data/ops/autopilot_report_state.json (last seen commit + done count).

b49 SELF-CHECK: `python3 scripts/autopilot_report.py 0 --self-check` (or
HERMES_SELFCHECK=1) re-raises inside the swallow blocks (git helper, state
read, narrative import) instead of degrading to ''/{} — so "nothing to
report" can never mean "the git call is broken". Self-check mode also
suppresses the Telegram send AND the STATE write: probing the machinery
must not consume the pending report or page the ops chat.
"""
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # b66: code location, not a literal
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
import os
load_dotenv(ROOT / '.env')

# b49: leaf seam imported outside the guard blocks (os/sys only).
from engines import selfcheck
from engines.autopilot_report_lib import classify_commits, run_start_from_log

_SELFCHECK = selfcheck.enabled()

STATE = ROOT / 'data/ops/autopilot_report_state.json'
BACKLOG = ROOT / 'data/ops/autopilot_backlog.md'
rc = int(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else 0
TEHRAN = timezone(timedelta(hours=3, minutes=30))


LOG = ROOT / 'logs/autopilot.log'  # b85: run-start markers

def git(*args):
    try:
        return subprocess.run(['git', '-C', str(ROOT)] + list(args),
                              capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception as e:
        selfcheck.fail('git helper', e)
        return ''


prev = {}
if STATE.exists():
    try:
        prev = json.loads(STATE.read_text())
    except Exception as e:
        selfcheck.fail('report state read', e)
        prev = {}

head = git('rev-parse', 'HEAD')
done_now = 0
first_todo = ''
if BACKLOG.exists():
    txt = BACKLOG.read_text()
    done_now = len(re.findall(r'^- \[x\]', txt, re.M))
    m = re.search(r'^- \[ \] (.+)$', txt, re.M)
    first_todo = (m.group(1)[:150] if m else '')

new_commits, other_commits = [], []
if prev.get('head') and head != prev['head']:
    raw = git('log', f"{prev['head']}..HEAD", '--format=%ct\x1f%s')
    started = None
    try:
        # a MISSING log is normal (fresh checkout, rotation) — that is 'no
        # marker', not a broken check. Only a real read error is loud.
        if LOG.exists():
            started = run_start_from_log(LOG.read_text(errors='replace'))
    except Exception as e:
        selfcheck.fail('run start log read', e)
    new_commits, other_commits = classify_commits(raw, started)
    new_commits, other_commits = new_commits[:6], other_commits[:4]

# the agent's own Persian narrative of this run (from autopilot.log)
narrative = ''
try:
    from notifier.dashboards import _autopilot_narrative
    narrative = _autopilot_narrative(max_chars=900)
except Exception as e:
    selfcheck.fail('narrative import', e)
    narrative = ''

lines = [f'🤖 <b>گزارش اتوپایلوت هرمس</b>',
         datetime.now(TEHRAN).strftime('%A · %H:%M تهران'), '']

if rc in (124, 143):
    # Neither is a crash: 124 = our own hard ceiling; 143 = SIGTERM from
    # OUTSIDE (the agent harness's stale-stream guard during a provider/
    # network stall — seen once, 2026-09-05, mid Telegram outage). If the
    # run committed its work before dying, the step still counts.
    why = ('به سقف زمانی خورد' if rc == 124
           else 'سیگنال حذف (SIGTERM) از بیرون گرفت')
    if new_commits:
        lines.append(f'⏱️ <b>این اجرا {why} و قطع شد، '
                     'اما کارش کامیت شده بود (زیانی در میان '
                     'نیست)</b>')
    else:
        lines.append(f'⏱️ <b>این اجرا {why} و قطع شد — '
                     'بیرون از این اجرا چیزی ثبت نشد؛ '
                     'آیتم در نوبت می‌ماند</b>')
elif rc != 0:
    lines.append(f'🔴 <b>این اجرا با خطا تمام شد (کد {rc})</b>')

if narrative:
    lines.append(narrative)
    lines.append('')
elif new_commits:
    lines.append('🛠 <b>تغییرات این اجرا:</b>')
    lines += [f'· {c[:110]}' for c in new_commits]

if new_commits:
    lines.append(f'📌 {len(new_commits)} تغییر کد کامیت و روی گیت‌هاب ثبت شد')

if other_commits:
    # b85: commits made OUTSIDE this run window (a manual fix between two
    # runs) are reported as such — never as this run's achievement.
    lines.append('🧹 ثبت‌شده بیرون از این اجرا (دستی/سایر):')
    lines += [f'· {c[:110]}' for c in other_commits]

if done_now > prev.get('done', done_now):
    # b85: a tick counted from the WORKING TREE is only banked once it is
    # committed. b85b: check the file against git, not against THIS run's
    # commits — the 15:13 report said 'هنوز ثبت نشده' about a tick that a
    # manual commit had already banked minutes earlier.
    dirty = git('status', '--porcelain', '--', str(BACKLOG))
    note = '' if not dirty else ' <i>(هنوز ثبت نشده — دور بعد)</i>'
    lines.append(f'📋 بک‌لاگ: {prev.get("done", "?")} ← {done_now} '
                 f'آیتم انجام‌شده{note}')

if first_todo:
    lines.append(f'➡️ در نوبت بعدی: {first_todo[:130]}')

if not new_commits and done_now == prev.get('done', done_now) and rc == 0:
    print('nothing to report')
    sys.exit(0)

token = os.getenv('AUTOPILOT_REPORT_BOT_TOKEN', '') or os.getenv('TELEGRAM_BOT_TOKEN', '')
chat = os.getenv('AUTOPILOT_REPORT_CHAT_ID', os.getenv('TELEGRAM_CHAT_ID', '194015957'))
if token and chat and not _SELFCHECK:
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/sendMessage',
        data=json.dumps({'chat_id': chat, 'text': '\n'.join(lines),
                         'parse_mode': 'HTML'}).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req, timeout=15).read()
        print('report sent to', chat)
    except Exception as e:
        print('send failed:', e)
        sys.exit(1)
else:
    print('\n'.join(lines))

# b49: a self-check probe must not consume the pending report state.
if not _SELFCHECK:
    STATE.write_text(json.dumps({'head': head, 'done': done_now,
                                 'ts': datetime.now(timezone.utc).isoformat()}))
