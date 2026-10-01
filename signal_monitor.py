#!/usr/bin/env python3
"""Phase 2: Telegram Signal Monitor (thin wrapper)

Wraps engines/signal_listener for standalone execution.
When run via cron, checks for new signals and executes approved ones.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing → local fallback
load_dotenv(Path(__file__).parent / '.env')

from bridge_client import BridgeClient
from notifier.telegram import send_telegram
from engines import paths as _paths   # b39: log path resolved at CALL time
from engines.config import dry_run as _dry_run  # WP2: canonical parse

DRY_RUN = _dry_run()


def _log_file() -> Path:
    """b39: import-time `LOG_FILE = BASE_DIR / 'logs' / ...` made this log
    unredirectable by HERMES_DATA_ROOT, so importing the module from a test
    wrote into production logs. Resolved per call now; production path
    unchanged."""
    return _paths.logs_dir() / 'signal_monitor.log'


def log(msg: str):
    log_file = _log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with log_file.open('a', encoding='utf-8') as f:
        f.write(line + '\n')


def run():
    """Main signal monitor — delegates to engines.signal_listener."""
    from engines.signal_listener import run_signal_check

    bridge = BridgeClient()
    health = bridge.health()
    if not health.get("ok"):
        log("Bridge unreachable, skipping signal check")
        return

    log("Signal monitor started.")
    result = run_signal_check(bridge, dry_run=DRY_RUN)

    signals_found = result.get("signals_found", 0)
    executions = result.get("executions", [])

    if signals_found == 0:
        log("No new signals.")
        return

    log(f"Found {signals_found} signal(s)")

    for se in executions:
        signal = se.get("signal", {})
        verdict = se.get("verdict", "skip")
        executed = se.get("executed", False)

        if executed:
            report = (
                f"\U0001f4e1 SIGNAL EXECUTED\n"
                f"Side: {signal.get('side')}\n"
                f"Entry: {signal.get('entry')}\n"
                f"SL: {signal.get('sl', 'N/A')} | TP: {signal.get('tp', 'N/A')}\n"
                f"Lot: {signal.get('lot', 0.01)}\n"
                f"Result: {'DRY-RUN' if DRY_RUN else 'LIVE'}"
            )
            send_telegram(report)
            log(f"EXECUTED: {signal.get('side')} @ {signal.get('entry')}")
        else:
            log(f"REJECTED: {verdict} — reasons: {se.get('reasons', [])}")

    log("Signal monitor complete.")


if __name__ == '__main__':
    run()
