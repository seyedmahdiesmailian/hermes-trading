#!/usr/bin/env python3
"""Bridge health watchdog (cron */5).

- Logs one line per run to logs/bridge_health.log (no stdout print: cron
  redirects stdout into the same file → duplicate lines).
- Alerts Telegram once after 3 consecutive failures, and once on recovery.
  State kept in data/bridge_health_state.json. Silent while healthy.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/home/ai/hermes-trading')
LOG_FILE = BASE / 'logs' / 'bridge_health.log'
STATE_FILE = BASE / 'data' / 'bridge_health_state.json'
HEALTH_URL = 'http://192.168.10.51:5050/health'
ROOT_URL = 'http://192.168.10.51:5050/'
FAIL_THRESHOLD = 3


def _env():
    try:
        from dotenv import load_dotenv
    except ImportError:
        import sys
        sys.path.insert(0, str(BASE))
        from env_loader import load_dotenv
    load_dotenv(BASE / '.env')


def log(msg: str):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    with LOG_FILE.open('a', encoding='utf-8') as f:
        f.write(line + '\n')


def fetch(url: str, timeout=5) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return True, r.read(800).decode('utf-8', 'replace')
    except Exception as e:
        return False, str(e)


def send_telegram(text: str):
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat = os.getenv('TELEGRAM_CHAT_ID', '194015957')
    if not token:
        return
    try:
        data = urllib.parse.urlencode({
            'chat_id': chat, 'text': text,
            'disable_web_page_preview': 'true',
        }).encode()
        urllib.request.urlopen(
            urllib.request.Request(f'https://api.telegram.org/bot{token}/sendMessage', data=data),
            timeout=10)
    except Exception:
        pass  # never loop alerts on send failure


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {'fails': 0, 'alerted': False}


def _save_state(s: dict):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(s), encoding='utf-8')
    except Exception:
        pass


def main():
    _env()
    ok, text = fetch(HEALTH_URL)
    healthy = ok and ('true' in text.lower() or 'ok' in text.lower())
    if not healthy:
        ok2, text2 = fetch(ROOT_URL)
        healthy = ok2 and 'Hermes' in text2

    st = _load_state()
    if healthy:
        log('Bridge health OK')
        if st.get('alerted'):
            send_telegram('✅ بریج MT5 برگشت (health OK)')
        _save_state({'fails': 0, 'alerted': False})
        return 0

    st['fails'] = int(st.get('fails', 0)) + 1
    log(f'Bridge BAD ({st["fails"]}x consecutive) health={text[:150]}')
    if st['fails'] >= FAIL_THRESHOLD and not st.get('alerted'):
        send_telegram(f'⚠️ بریج MT5 قطع است ({st["fails"]} بررسی متوالی ناموفق)\n{datetime.now(timezone.utc).strftime("%H:%M UTC")}\nبررسی: ترمینال MT5 روی ویندوز / C:\\Temp\\bridge.py')
        st['alerted'] = True
    _save_state(st)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
