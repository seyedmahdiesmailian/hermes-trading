#!/usr/bin/env python3
"""Hermes Trading CLI — read-only status/report/plan inspection.

Fully autonomous system: there are NO manual trade commands. The scanner and
the signal listener decide and execute on their own; this CLI only shows state.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# b65 (found by the b64 audit): cli.py imported bridge_client but NEVER
# loaded .env — every bridge call went out tokenless (HTTP_401) and the
# status panel showed 'Bridge: OK' next to 'Account: 401', i.e. a dead
# auth looked like a live-but-empty account. Same bug class as b64's
# bridge_health_monitor: a consumer that reads no env is invisible to
# every env-name scan. Shared try-dotenv-except-env_loader pattern.
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing → local fallback
load_dotenv(Path(__file__).resolve().parent / '.env')

from engines import paths as _paths   # b39: resolved at CALL time (see tripwire)

# b39: BASE_DIR import-time constant removed — nothing used it; every state
# path resolves through _report_file()/_plan_file()/_runtime_file() below.


def _report_file() -> Path:
    return _paths.logs_dir() / 'report.txt'


def _plan_file() -> Path:
    return _paths.plan_dir() / 'current_plan.json'


def _runtime_file() -> Path:
    return _paths.plan_dir() / 'runtime_state.json'


def cmd_status(args):
    """Show current trading status."""
    from bridge_client import BridgeClient
    b = BridgeClient()
    health = b.health()
    account = b.get_account()
    tick = b.get_tick('XAUUSD')
    positions = b.get_positions('XAUUSD')

    print("═══════════════════════════════════════════")
    print("  HERMES TRADING STATUS")
    print("═══════════════════════════════════════════")
    print(f"Bridge: {'✅ OK' if health.get('ok') else '❌ BAD'}")

    if isinstance(account, dict) and account.get('ok'):
        print(f"Account: ${account.get('balance', 0):.2f} (Equity: ${account.get('equity', 0):.2f})")
        print(f"Free Margin: ${account.get('margin_free', 0):.2f}")
    else:
        print(f"Account: ❌ {account}")

    if isinstance(tick, dict) and tick.get('ok'):
        print(f"XAUUSD: Bid={tick.get('bid', 0):.2f} Ask={tick.get('ask', 0):.2f}")
    else:
        print(f"XAUUSD: ❌ {tick}")

    # b65: same ok-check as account/tick — a 401 payload has no 'data',
    # which used to print 'Open Positions: 0' and read as an empty account.
    if isinstance(positions, dict) and positions.get('ok'):
        pos_data = positions.get('data', positions.get('positions', []))
        print(f"Open Positions: {len(pos_data) if isinstance(pos_data, list) else '?'}")
    else:
        print(f"Open Positions: ❌ {positions}")

    if _plan_file().exists():
        plan = json.loads(_plan_file().read_text())
        print(f"\nCurrent Plan: {plan.get('plan_id', 'N/A')}")
        print(f"  Bias: {plan.get('bias', 'N/A')}")
        print(f"  Session: {plan.get('session', 'N/A')}")
        q = plan.get('quality', {})
        print(f"  Regime: {q.get('regime', 'N/A')}")
        print(f"  Alignment: {q.get('alignment', 'N/A')}")
        print(f"  Trend Strength: {q.get('trend_strength', 0):.2f}")

    if _runtime_file().exists():
        runtime = json.loads(_runtime_file().read_text())
        print(f"\nRuntime: step={runtime.get('last_step')} action={runtime.get('last_monitor_action')}")

    print("═══════════════════════════════════════════")


def cmd_report(args):
    """Show last report."""
    if _report_file().exists():
        print(_report_file().read_text(encoding='utf-8'))
    else:
        print("❌ No report yet. Run a cycle first.")


def cmd_run(args):
    """Run a cycle manually.

    b65 (found by the b64 audit): the old line was
    `os.environ['HERMES_DRY_RUN'] = str(args.live).lower()` — args.live is a
    store_true flag, so a bare `cli.py run` wrote 'false' (= LIVE) and
    `cli.py run --live` wrote 'true' (= dry run). The flag was INVERTED: the
    safe-looking default command was the one that could execute a real order.
    Now dry-run is the default and only --live flips it, matching
    hermes_master's own parse (default 'true').
    """
    os.environ['HERMES_DRY_RUN'] = 'false' if args.live else 'true'
    from hermes_master import main
    rc = main()
    sys.exit(rc)


def cmd_plan(args):
    """Show current plan details."""
    if not _plan_file().exists():
        print("❌ No plan file found")
        return
    plan = json.loads(_plan_file().read_text())
    print(json.dumps(plan, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description='Hermes Trading CLI')
    sub = parser.add_subparsers(dest='action', required=True)

    sub.add_parser('status', help='Show trading status')
    sub.add_parser('report', help='Show last report')
    sub.add_parser('plan', help='Show current plan')

    p_run = sub.add_parser('run', help='Run a cycle now')
    p_run.add_argument('--live', action='store_true', help='Execute for real (no DRY_RUN)')

    args = parser.parse_args()
    if args.action == 'status': cmd_status(args)
    elif args.action == 'report': cmd_report(args)
    elif args.action == 'run': cmd_run(args)
    elif args.action == 'plan': cmd_plan(args)


if __name__ == '__main__':
    main()
