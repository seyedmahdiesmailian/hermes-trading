#!/usr/bin/env python3
"""Per-run autopilot report → Telegram (separate bot/chat).
Sends ONLY when something happened: new commits, backlog progress, or a
failed run. Silent on idle runs unless the run crashed.
Config: AUTOPILOT_REPORT_CHAT_ID (chat), token from TELEGRAM_BOT_TOKEN.
State: data/ops/autopilot_report_state.json (last seen commit + done count).
"""
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/home/ai/hermes-trading')
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
import os
load_dotenv(ROOT / '.env')

STATE = ROOT / 'data/ops/autopilot_report_state.json'
BACKLOG = ROOT / 'data/ops/autopilot_backlog.md'
LOG = ROOT / 'logs/autopilot.log'
rc = int(sys.argv[1]) if len(sys.argv) > 1 else 0


def git(*args):
    try:
        return subprocess.run(['git', '-C', str(ROOT)] + list(args),
                              capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        return ''


prev = {}
if STATE.exists():
    try:
        prev = json.loads(STATE.read_text())
    except Exception:
        prev = {}

head = git('rev-parse', 'HEAD')
done_now = 0
first_todo = ''
if BACKLOG.exists():
    txt = BACKLOG.read_text()
    done_now = len(re.findall(r'^- \[x\]', txt, re.M))
    m = re.search(r'^- \[ \] (.+)$', txt, re.M)
    first_todo = (m.group(1)[:110] if m else '')

new_commits = []
if prev.get('head') and head != prev['head']:
    log = git('log', '--oneline', f"{prev['head']}..HEAD", '--format=%s')
    new_commits = [l for l in log.splitlines() if l][:6]

progress = done_now > prev.get('done', done_now)
lines = []
if rc != 0:
    lines.append(f'🔴 <b>اجرای autopilot با خطا تمام شد</b> (rc={rc})')
    if LOG.exists():
        tail = LOG.read_text(errors='ignore').splitlines()[-40:]
        errs = [l for l in tail if 'ERROR' in l or 'Traceback' in l][-2:]
        lines += [f'<code>{e[:120]}</code>' for e in errs]
if new_commits:
    lines.append('🛠 <b>تغییرات این اجرا:</b>')
    lines += [f'· {c[:110]}' for c in new_commits]
if progress:
    lines.append(f'📋 پیشرفت بک‌لاگ: {prev.get("done","?")} ← {done_now} انجام‌شده')
if not lines and rc == 0 and (head != prev.get('head') or done_now != prev.get('done')):
    lines.append('✅ اجرا شد، تغییر جدیدی نبود')
if not lines:
    print('nothing to report')
    sys.exit(0)

if first_todo:
    lines.append(f'➡️ بعدی: {first_todo}')
lines.insert(0, f'🤖 <b>گزارش autopilot</b> — {datetime.now(timezone.utc).strftime("%H:%M UTC")}')

token = os.getenv('AUTOPILOT_REPORT_BOT_TOKEN', '') or os.getenv('TELEGRAM_BOT_TOKEN', '')
chat = os.getenv('AUTOPILOT_REPORT_CHAT_ID', os.getenv('TELEGRAM_CHAT_ID', '194015957'))
if token and chat:
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

STATE.write_text(json.dumps({'head': head, 'done': done_now,
                             'ts': datetime.now(timezone.utc).isoformat()}))
