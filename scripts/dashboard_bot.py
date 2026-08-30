#!/usr/bin/env python3
"""b38: ops dashboard daemon — the 3rd Telegram bot as an interactive panel.

Polls getUpdates on AUTOPILOT_REPORT_BOT_TOKEN (a token nothing else polls,
so no 409 risk) and serves inline-keyboard panels: system status, autopilot,
backup/health, trades. Read-only: it never touches orders, gates or config.

Access control: only AUTOPILOT_REPORT_CHAT_ID (the owner) is served.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path('/home/ai/hermes-trading')
sys.path.insert(0, str(ROOT))
from env_loader import load_dotenv  # noqa: E402
load_dotenv(ROOT / '.env')

from notifier import dashboards  # noqa: E402
from engines import paths  # noqa: E402

STATE = ROOT / 'data/ops/dashboard_state.json'
PANELS = {'sys': '🖥 سیستم', 'auto': '🤖 اتوپایلوت', 'ops': '💾 بکاپ/سلامت',
          'trade': '📊 ترید', 'home': '🏠 خانه'}


def log(msg: str):
    try:
        paths.logs_dir().mkdir(parents=True, exist_ok=True)
        line = f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}'
        print(line, flush=True)
        with (paths.logs_dir() / 'dashboard.log').open('a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def api(method: str, token: str, params: dict | None = None) -> dict:
    try:
        url = f'https://api.telegram.org/bot{token}/{method}'
        data = urllib.parse.urlencode(params).encode() if params else None
        req = urllib.request.Request(url, data=data, method='POST' if data else 'GET')
        # b38fix: long-poll timeout must exceed the getUpdates 'timeout' param
        # (25s), otherwise every poll dies with a socket read timeout.
        return json.loads(urllib.request.urlopen(req, timeout=40).read().decode())
    except Exception as e:
        log(f'api {method} failed: {e}')
        return {}


def load_offset() -> int:
    try:
        return int(json.loads(STATE.read_text()).get('offset', 0))
    except Exception:
        return 0


def save_offset(off: int):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({'offset': off}))
    except Exception:
        pass


def send_panel(token: str, chat_id: str, panel: str, msg_id=None):
    text, kb = dashboards.ops_render(panel)
    params = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML',
              'reply_markup': json.dumps({'inline_keyboard': kb}, ensure_ascii=False)}
    if msg_id:
        params['message_id'] = msg_id
        r = api('editMessageText', token, params)
        if not r.get('ok'):
            api('sendMessage', token, {k: v for k, v in params.items() if k != 'message_id'})
    else:
        api('sendMessage', token, params)


def main():
    token = os.getenv('AUTOPILOT_REPORT_BOT_TOKEN', '')
    owner = str(os.getenv('AUTOPILOT_REPORT_CHAT_ID', '194015957'))
    if not token:
        log('AUTOPILOT_REPORT_BOT_TOKEN missing — exiting')
        return 1
    me = api('getMe', token).get('result', {})
    log(f'ops dashboard started as @{me.get("username", "?")}')
    try:
        api('deleteWebhook', token, {'drop_pending_updates': False})
    except Exception:
        pass
    offset = load_offset()
    while True:
        try:
            r = api('getUpdates', token, {'offset': offset + 1, 'timeout': 25})
            updates = r.get('result') or []
            if not updates:
                continue
            for up in updates:
                offset = max(offset, int(up.get('update_id', 0)))
                cb = up.get('callback_query')
                if cb:
                    qid = cb.get('id', '')
                    chat = str(((cb.get('message') or {}).get('chat') or {}).get('id', ''))
                    mid = (cb.get('message') or {}).get('message_id')
                    if chat != owner:
                        api('answerCallbackQuery', token,
                            {'callback_query_id': qid, 'text': 'دسترسی نیست', 'show_alert': True})
                        continue
                    data = cb.get('data') or ''
                    panel = data.split(':', 1)[1] if data.startswith('ops:') else 'home'
                    send_panel(token, chat, panel, msg_id=mid)
                    api('answerCallbackQuery', token, {'callback_query_id': qid})
                    continue
                msg = (up.get('message') or up.get('edited_message') or {})
                chat = str((msg.get('chat') or {}).get('id', ''))
                text = (msg.get('text') or '').strip()
                if chat != owner or not text:
                    continue
                if text.startswith('/'):
                    cmd = text.split()[0].lstrip('/').split('@')[0].lower()
                    panel = {'home': 'home', 'start': 'home', 'help': 'home',
                             'system': 'sys', 'sys': 'sys', 'autopilot': 'auto',
                             'auto': 'auto', 'backup': 'ops', 'health': 'ops',
                             'ops': 'ops', 'trades': 'trade', 'trade': 'trade'}.get(cmd, 'home')
                    send_panel(token, chat, panel)
                else:
                    send_panel(token, chat, 'home')
            save_offset(offset)
        except KeyboardInterrupt:
            log('stopped')
            return 0
        except Exception:
            import traceback
            log('loop error: ' + traceback.format_exc().strip().splitlines()[-1])
            time.sleep(5)


if __name__ == '__main__':
    sys.exit(main())
