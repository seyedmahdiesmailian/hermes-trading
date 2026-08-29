#!/usr/bin/env python3
"""Hermes Trading CLI — send commands and check status."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path('/home/ai/hermes-trading')
CMD_FILE = BASE_DIR / 'data' / 'commands' / 'hermes_command.txt'
REPORT_FILE = BASE_DIR / 'logs' / 'report.txt'
PLAN_FILE = BASE_DIR / 'data' / 'xau_plan' / 'current_plan.json'
RUNTIME_FILE = BASE_DIR / 'data' / 'xau_plan' / 'runtime_state.json'


def cmd_send(args):
    """Send a command to Hermes."""
    CMD_FILE.parent.mkdir(parents=True, exist_ok=True)
    CMD_FILE.write_text(args.command, encoding='utf-8')
    print(f"✅ Command sent: {args.command}")
    print(f"   Will be consumed on next cron cycle (within 15 min)")
    print(f"   Or run: python3 hermes_master.py")


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

    pos_data = positions.get('data', []) if isinstance(positions, dict) else []
    print(f"Open Positions: {len(pos_data)}")

    if PLAN_FILE.exists():
        plan = json.loads(PLAN_FILE.read_text())
        print(f"\nCurrent Plan: {plan.get('plan_id', 'N/A')}")
        print(f"  Bias: {plan.get('bias', 'N/A')}")
        print(f"  Session: {plan.get('session', 'N/A')}")
        q = plan.get('quality', {})
        print(f"  Regime: {q.get('regime', 'N/A')}")
        print(f"  Alignment: {q.get('alignment', 'N/A')}")
        print(f"  Trend Strength: {q.get('trend_strength', 0):.2f}")

    if RUNTIME_FILE.exists():
        runtime = json.loads(RUNTIME_FILE.read_text())
        print(f"\nRuntime: step={runtime.get('last_step')} action={runtime.get('last_monitor_action')}")

    print("═══════════════════════════════════════════")


def cmd_report(args):
    """Show last report."""
    if REPORT_FILE.exists():
        print(REPORT_FILE.read_text(encoding='utf-8'))
    else:
        print("❌ No report yet. Run a cycle first.")


def cmd_run(args):
    """Run a cycle manually."""
    os.environ['HERMES_DRY_RUN'] = str(args.live).lower()
    from hermes_master import main
    rc = main()
    sys.exit(rc)


def cmd_plan(args):
    """Show current plan details."""
    if not PLAN_FILE.exists():
        print("❌ No plan file found")
        return
    plan = json.loads(PLAN_FILE.read_text())
    print(json.dumps(plan, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description='Hermes Trading CLI')
    sub = parser.add_subparsers(dest='action', required=True)

    sub.add_parser('status', help='Show trading status')
    sub.add_parser('report', help='Show last report')
    sub.add_parser('plan', help='Show current plan')

    p_send = sub.add_parser('send', help='Send a command')
    p_send.add_argument('command', help='Command: /trade BUY 0.05 4590 4620, /close TICKET, /partial TICKET 50, /modify TICKET sl=4600, /skip')

    p_run = sub.add_parser('run', help='Run a cycle now')
    p_run.add_argument('--live', action='store_true', help='Execute for real (no DRY_RUN)')

    args = parser.parse_args()
    if args.action == 'status': cmd_status(args)
    elif args.action == 'report': cmd_report(args)
    elif args.action == 'send': cmd_send(args)
    elif args.action == 'run': cmd_run(args)
    elif args.action == 'plan': cmd_plan(args)


if __name__ == '__main__':
    main()
