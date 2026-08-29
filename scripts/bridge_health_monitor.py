#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import urllib.request
import sys

LOG_FILE = Path('/home/ai/hermes-trading/logs/bridge_health.log')
HEALTH_URL = 'http://192.168.10.51:5050/health'
ROOT_URL = 'http://192.168.10.51:5050/'


def log(msg: str):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line=f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with LOG_FILE.open('a', encoding='utf-8') as f: f.write(line+'\n')


def fetch(url: str, timeout=5) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            text=r.read(800).decode('utf-8','replace')
        return True, text
    except Exception as e:
        return False, str(e)


def main():
    ok, text = fetch(HEALTH_URL)
    if ok and ('true' in text.lower() or 'ok' in text.lower()):
        log('Bridge health OK')
        return 0
    ok2, text2 = fetch(ROOT_URL)
    if ok2 and 'Hermes' in text2:
        log('Bridge root OK but /health unavailable or weak')
        return 0
    log(f'Bridge BAD health={text[:200]} root={text2[:200]}')
    return 1

if __name__ == '__main__':
    sys.exit(main())
