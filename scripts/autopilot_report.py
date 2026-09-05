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

_SELFCHECK = selfcheck.enabled()

STATE = ROOT / 'data/ops/autopilot_report_state.json'
BACKLOG = ROOT / 'data/ops/autopilot_backlog.md'
rc = int(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else 0
TEHRAN = timezone(timedelta(hours=3, minutes=30))


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

new_commits = []
if prev.get('head') and head != prev['head']:
    log = git('log', '--oneline', f"{prev['head']}..HEAD", '--format=%s')
    new_commits = [l for l in log.splitlines() if l][:6]

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

if rc == 124:
    # timeout, not a crash: the run was cut off by the hard ceiling. If it
    # committed its work, the step still counts as delivered — say so.
    if new_commits:
        lines.append('⏱️ <b>این اجرا به سقف زمانی خورد و قطع شد، '
                     'اما کارش کامیت شده بود (زیانی در میان '
                     'نیست)</b>')
    else:
        lines.append('⏱️ <b>این اجرا به سقف زمانی خورد و قطع شد — '
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

if done_now > prev.get('done', done_now):
    lines.append(f'📋 بک‌لاگ: {prev.get("done", "?")} ← {done_now} آیتم انجام‌شده')

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
