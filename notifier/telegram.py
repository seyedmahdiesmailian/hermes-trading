#!/usr/bin/env python3
from __future__ import annotations
import os
from datetime import datetime, timezone
from pathlib import Path
import requests

BASE_DIR = Path('/home/ai/hermes-trading')
from engines import paths as _paths
LOG_DIR = _paths.logs_dir()

def send_telegram(message: str) -> bool:
    return _send(message, os.getenv('TELEGRAM_BOT_TOKEN'))


def send_ops(message: str) -> bool:
    """b37: system/ops alerts -> dedicated 3rd bot (autopilot, health, backup,
    watchdog). Falls back to the main bot if ops bot is not configured."""
    return _send(message, os.getenv('AUTOPILOT_REPORT_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN'),
                 chat=os.getenv('AUTOPILOT_REPORT_CHAT_ID', '194015957'))


def _send(message: str, token: str | None, chat: str | None = None) -> bool:
    chat_id = chat or os.getenv('TELEGRAM_CHAT_ID','194015957')
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / 'telegram_messages.log').open('a', encoding='utf-8') as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()}	{message[:1000]}\\n")
    if not token:
        print('[TELEGRAM SKIP] token not set')
        return False
    try:
        r=requests.post(f'https://api.telegram.org/bot{token}/sendMessage', data={'chat_id':chat_id,'text':message}, timeout=10)
        print(f'[TELEGRAM] {r.status_code}')
        return r.status_code == 200
    except Exception as e:
        print(f'[TELEGRAM FAIL] {e}')
        return False
