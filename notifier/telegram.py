#!/usr/bin/env python3
from __future__ import annotations
import os
from datetime import datetime, timezone
from pathlib import Path
import requests

from engines import paths as _paths   # b39: state paths at CALL time

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
    return _send(message, os.getenv('TELEGRAM_BOT_TOKEN'))


def send_ops(message: str) -> bool:
    """b37: system/ops alerts -> dedicated 3rd bot (autopilot, health, backup,
    watchdog). Falls back to the main bot if ops bot is not configured."""
    return _send(message, os.getenv('AUTOPILOT_REPORT_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN'),
                 chat=os.getenv('AUTOPILOT_REPORT_CHAT_ID', '194015957'))


def _send(message: str, token: str | None, chat: str | None = None) -> bool:
    chat_id = chat or os.getenv('TELEGRAM_CHAT_ID','194015957')
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    # review-fix A4 (2026-09-17): the write below used a LITERAL backslash-n,
    # so every record ran together on one line and no line-oriented tool
    # could read the log. A real newline, same as every other log file.
    with (log_dir / 'telegram_messages.log').open('a', encoding='utf-8') as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()}	{message[:1000]}\n")
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
