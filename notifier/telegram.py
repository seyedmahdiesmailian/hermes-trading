#!/usr/bin/env python3
from __future__ import annotations
import os
from datetime import datetime, timezone
from pathlib import Path
import requests

from engines import paths as _paths   # b39: state paths at CALL time
from engines.config import ops_bot_token as _ops_token  # WP2: canonical
from engines.config import ops_chat_id as _ops_chat
from engines.config import telegram_bot_token as _tg_token
from engines.config import telegram_chat_id as _tg_chat

# b39: BASE_DIR import-time constant removed (unused); the message log
# resolves through _log_dir() below.


def _log_dir() -> Path:
    """b39: was `LOG_DIR = _paths.logs_dir()` bound at IMPORT time, which is
    before hermetic.use_temp_data_root() flips HERMES_DATA_ROOT — so any test
    that reached the real _send() appended to production logs/
    telegram_messages.log. Same bug class b37 found in hermes_master
    (LOG_FILE/REPORT_FILE) and position_daemon (which had already fixed it
    with _log_file()). Resolved per call now."""
    return _paths.logs_dir()


def send_telegram(message: str) -> bool:
    return _send(message, _tg_token())


def send_ops(message: str) -> bool:
    """b37: system/ops alerts -> dedicated 3rd bot (autopilot, health, backup,
    watchdog). Falls back to the main bot if ops bot is not configured."""
    return _send(message, _ops_token(), chat=_ops_chat())


def _send(message: str, token: str | None, chat: str | None = None) -> bool:
    chat_id = chat or _tg_chat()
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / 'telegram_messages.log').open('a', encoding='utf-8') as f:
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
