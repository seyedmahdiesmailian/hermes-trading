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
    token = os.getenv('AUTOPILOT_REPORT_BOT_TOKEN', '') or os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat = os.getenv('AUTOPILOT_REPORT_CHAT_ID', os.getenv('TELEGRAM_CHAT_ID', '194015957'))
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


def _daemon_check() -> str | None:
    """b31: who watches the watchdog? Returns alert text if a critical daemon
    is dead or its heartbeat is stale (>120s) while the market is open."""
    import subprocess
    try:
        r = subprocess.run(['systemctl', '--user', 'is-active',
                            'hermes-position', 'hermes-signal'],
                           capture_output=True, text=True, timeout=10)
        states = r.stdout.split()
        if states != ['active', 'active']:
            return f'دمون‌ها: position={states[0] if states else "?"} signal={states[1] if len(states) > 1 else "?"}'
    except Exception as e:
        return f'بررسی systemctl ناموفق: {e}'
    # heartbeat freshness (position daemon writes every ~5s when alive)
    try:
        from datetime import datetime, timezone
        hb = BASE / 'data' / 'xau_plan' / 'watchdog_heartbeat'
        if hb.exists():
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(hb.read_text().strip())).total_seconds()
            if age > 120:
                return f'heartbeat دایمون موقعیت {int(age)}s قدیمی است'
    except Exception:
        pass  # unreadable heartbeat file: systemctl already passed, don't false-alarm
    return None


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
        # keep daemon_alerted_at (b31) — dedup window must survive healthy ticks
        _save_state({'fails': 0, 'alerted': False,
                     'daemon_alerted_at': st.get('daemon_alerted_at', 0)})
    else:
        st['fails'] = int(st.get('fails', 0)) + 1
        log(f'Bridge BAD ({st["fails"]}x consecutive) health={text[:150]}')
        if st['fails'] >= FAIL_THRESHOLD and not st.get('alerted'):
            send_telegram(f'⚠️ بریج MT5 قطع است ({st["fails"]} بررسی متوالی ناموفق)\n{datetime.now(timezone.utc).strftime("%H:%M UTC")}\nبررسی: ترمینال MT5 روی ویندوز / C:\\Temp\\bridge.py')
            st['alerted'] = True
        _save_state(st)

    # b31: daemon liveness + heartbeat (market-hours only, deduped 6h)
    try:
        import sys
        sys.path.insert(0, str(BASE))
        from engines.market_hours import is_market_open
        if is_market_open():
            problem = _daemon_check()
            now_ts = datetime.now(timezone.utc).timestamp()
            last_alert = float(st.get('daemon_alerted_at', 0) or 0)
            if problem and (now_ts - last_alert) > 6 * 3600:
                send_telegram(f'🔴 دایمون هرمس: {problem}\n{datetime.now(timezone.utc).strftime("%H:%M UTC")}')
                st['daemon_alerted_at'] = now_ts
                _save_state(st)
                log(f'Daemon alert: {problem}')
    except Exception as e:
        log(f'daemon check skipped: {e}')

    return 0 if healthy else 1


if __name__ == '__main__':
    raise SystemExit(main())
