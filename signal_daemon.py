#!/usr/bin/env python3
"""Instant Telegram signal daemon.

Long-polls the signal group and reacts to signals within seconds
(instead of waiting for the 5-minute cron cycle).
Runs as systemd user service 'hermes-signal'.
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

# Load .env (shared loader with python-dotenv fallback)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing → local fallback
load_dotenv(BASE / '.env')

from bridge_client import BridgeClient
from engines.signal_listener import run_signal_check

LOG_FILE = BASE / 'logs' / 'signal_daemon.log'
DRY_RUN = os.getenv('HERMES_DRY_RUN', 'true').lower() not in {'0', 'false', 'no'}


def log(msg: str):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open('a', encoding='utf-8') as f:
        f.write(line + '\n')


def send_telegram(text: str):
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat = os.getenv('TELEGRAM_CHAT_ID', '194015957')
    if not token:
        return
    import urllib.request, urllib.parse
    try:
        url = f'https://api.telegram.org/bot{token}/sendMessage'
        data = urllib.parse.urlencode({
            'chat_id': chat, 'text': text,
            'disable_web_page_preview': 'true',
        }).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except Exception as e:
        log(f'telegram send failed: {e}')


def main():
    log(f'Signal daemon started (dry_run={DRY_RUN})')
    bridge = BridgeClient()
    consecutive_errors = 0

    while True:
        try:
            result = run_signal_check(bridge, dry_run=DRY_RUN)
            found = result.get('signals_found', 0)
            if found > 0:
                log(f'{found} signal(s) processed')
                for se in result.get('executions', []):
                    sig = se.get('signal', {})
                    verdict = se.get('verdict', '?')
                    log(f'  {sig.get("side")} {sig.get("symbol")} @ {sig.get("entry")} '
                        f'sl={sig.get("sl")} tp={sig.get("tp")} -> {verdict} '
                        f'(executed={se.get("executed")})')
                    # Instant Telegram report
                    if se.get('executed'):
                        send_telegram(
                            f"📡 SIGNAL TRADE ✅\n"
                            f"{sig.get('side')} {sig.get('symbol')} @ {sig.get('entry')}\n"
                            f"SL: {sig.get('sl')} | TP: {sig.get('tp')}\n"
                            f"lot: {se.get('lot', sig.get('lot', '?'))}"
                        )
                    elif verdict == 'skip':
                        reasons = ', '.join(se.get('reasons', [])[:3])
                        send_telegram(
                            f"🚫 SIGNAL SKIP\n"
                            f"{sig.get('side')} {sig.get('symbol')} @ {sig.get('entry')}\n"
                            f"دلیل: {reasons}"
                        )
            consecutive_errors = 0
            time.sleep(2)
        except KeyboardInterrupt:
            log('Stopped by user')
            break
        except Exception:
            consecutive_errors += 1
            err = traceback.format_exc().strip().splitlines()[-1]
            log(f'ERROR ({consecutive_errors}): {err}')
            if consecutive_errors >= 5:
                send_telegram(f'⚠️ Signal daemon: {consecutive_errors} خطای متوالی\n{err[:150]}')
                time.sleep(60)
            else:
                time.sleep(5)


if __name__ == '__main__':
    main()
