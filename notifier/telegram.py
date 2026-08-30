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
    token=os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id=os.getenv('TELEGRAM_CHAT_ID','194015957')
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / 'telegram_messages.log').open('a', encoding='utf-8') as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()}	{message[:1000]}\\n")
    if not token:
        print('[TELEGRAM SKIP] TELEGRAM_BOT_TOKEN not set')
        return False
    try:
        r=requests.post(f'https://api.telegram.org/bot{token}/sendMessage', data={'chat_id':chat_id,'text':message}, timeout=10)
        print(f'[TELEGRAM] {r.status_code}')
        return r.status_code == 200
    except Exception as e:
        print(f'[TELEGRAM FAIL] {e}')
        return False
