#!/usr/bin/env python3
"""Hermes Master — fully autonomous trading orchestrator.

Phase 1: Analyzes market, builds plan, executes trades, manages positions.
          NO human approval required. Fully autonomous.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing → local fallback
load_dotenv(Path(__file__).parent / '.env')

from bridge_client import BridgeClient
from hermes_runtime import cycle
from engines.signal_listener import run_signal_check
from notifier.telegram import send_telegram

BASE_DIR = Path('/home/ai/hermes-trading')
LOG_FILE = BASE_DIR / 'logs' / 'master.log'
REPORT_FILE = BASE_DIR / 'logs' / 'report.txt'
DRY_RUN = os.getenv('HERMES_DRY_RUN', 'true').lower() not in {'0', 'false', 'no'}


def log(msg: str):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    # no print(): cron redirects stdout into the same log → duplicate lines
    with LOG_FILE.open('a', encoding='utf-8') as f:
        f.write(line + '\n')


def build_report(payload: dict, bridge_health: dict) -> str:
    lines = []
    lines.append('═══════════════════════════════════════════')
    mode = 'DRY_RUN' if DRY_RUN else 'LIVE'
    lines.append(f"HERMES | {datetime.now(timezone.utc).strftime('%H:%M UTC')} | {mode}")
    lines.append('═══════════════════════════════════════════')
    lines.append(f"Bridge: {'✅' if bridge_health.get('ok') else '❌'}")

    step = payload.get('step', '?')
    lines.append(f"Step: {step} | ✅" if payload.get('ok') else f"Step: {step} | ❌")

    if payload.get('brief'):
        lines.append('')
        lines.append(str(payload['brief']))

    p = payload.get('account_policy', {})
    if p:
        lines.append('')
        lines.append(f"💰 Balance: ${p.get('balance', 0):.2f} | Equity: ${p.get('equity', 0):.2f}")
        lines.append(f"⚙️  Regime: {p.get('regime')} | Trade: {'✅' if p.get('trade_allowed') else '🚫'}")
        lines.append(f"📊 Open: {p.get('open_positions', 0)} | DD: {p.get('drawdown_pct', 0):.1%}")

    perf = payload.get('performance_state', {})
    if perf:
        pnl = float(perf.get('daily_pnl', 0) or 0)
        sign = '+' if pnl >= 0 else ''
        lines.append(f"📅 Today: {sign}${pnl:.2f} | Streak: {perf.get('loss_streak', 0)}")

    exec_result = payload.get('execution_result')
    if exec_result:
        if exec_result.get('dry_run'):
            lines.append(f"\n🧪 DRY-RUN: would execute")
        elif exec_result.get('ok'):
            lines.append(f"\n✅ TRADE EXECUTED")
        else:
            lines.append(f"\n❌ Execution failed: {exec_result.get('error')}")

    lines.append('')
    lines.append('— Hermes Brain | Linux | CapitalXtend | XAUUSD')
    return '\n'.join(lines)


def save_report(text: str):
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(text, encoding='utf-8')


def main():
    bridge = BridgeClient()
    bridge_health = bridge.health()

    # Startup cooldown: registered ONCE per process. (Was called inside
    # cycle() every 15 min → each cycle re-armed a 5-min restart cooldown
    # and then blocked its own entries. Measured: 0/51 entries survived.)
    try:
        from engines.cooldown import ensure_startup_cooldown
        ensure_startup_cooldown()
    except Exception:
        pass

    if not bridge_health.get('ok'):
        log(f"Bridge unreachable: {bridge_health}")
        send_telegram(f"🛑 Hermes | Bridge unreachable\n{bridge.url}")
        return

    # ── Run the autonomous trading cycle ──
    log("Cycle start...")
    payload = cycle(bridge, dry_run=DRY_RUN)

    if not payload.get('ok'):
        log(f"Cycle failed: {payload.get('error', 'unknown')}")
        send_telegram(f"🛑 Hermes | Cycle Failed\n{payload.get('error', 'unknown')}")
        return

    step = payload.get('step', '?')
    will_execute = payload.get('will_execute_now', False)
    monitor_action = payload.get('monitor', {}).get('action', 'none')
    log(f"Step={step} execute={will_execute} action={monitor_action}")

    # ── Phase 2: signals handled instantly by signal_daemon.py (systemd) ──
    signal_executions = []

    # ── Phase 2.5: adaptive learning loop (journal → analyze → adjust) ──
    try:
        from engines.learning import run_learning_cycle
        learning = run_learning_cycle(bridge)
        if learning.get('journaled'):
            log(f"Learning: +{learning['journaled']} journaled trades")
        if (learning.get('proposal') or {}).get('changes'):
            log(f"Learning: params adjusted → {learning['proposal']['changes']}")
    except Exception as e:
        log(f"Learning cycle skipped: {e}")
        learning = None

    # ── Build report ──
    report = build_report(payload, bridge_health)
    save_report(report)

    # ── Telegram: report plan/halt/execute (reassess = silent unless bias flips) ──
    if step == 'reassess':
        prev_bias = payload.get('previous_bias')
        new_bias = (payload.get('plan') or {}).get('bias')
        if prev_bias and new_bias and prev_bias != new_bias:
            send_telegram(f"\u26a1 \u062a\u063a\u06cc\u06cc\u0631 \u0628\u0627\u06cc\u0632: {prev_bias} \u2192 {new_bias}")
    if step in {'plan'}:
        send_telegram(report)
    elif step == 'halted':
        send_telegram(payload.get('brief', '\U0001f6d1 Kill Switch'))
    elif will_execute:
        send_telegram(report)
    elif step == 'manage':
        send_telegram(report)

    # ── Telegram: report signal executions AND reviews ──
    for se in signal_executions:
        sig = se.get("signal", {})
        verdict = se.get("verdict", "?")
        if se.get("executed"):
            send_telegram(
                f"\U0001f4e1 SIGNAL TRADE\n"
                f"{sig.get('side')} {sig.get('symbol')} @ {sig.get('entry')}\n"
                f"SL: {sig.get('sl')} | TP: {sig.get('tp')}\n"
                f"Verdict: {verdict}"
            )
        elif verdict == "review":
            reasons = ", ".join(se.get("reasons", [])[:3])
            send_telegram(
                f"\u26a0\ufe0f SIGNAL REVIEW \u2014 \u0646\u06cc\u0627\u0632 \u062a\u0635\u0645\u06cc\u0645 \u0634\u0645\u0627\n"
                f"{sig.get('side')} {sig.get('symbol')} @ {sig.get('entry')}\n"
                f"SL: {sig.get('sl')} | TP: {sig.get('tp')}\n"
                f"\u062f\u0644\u06cc\u0644: {reasons}\n"
                f"\u0627\u06af\u0631 \u0645\u06cc\u062e\u0648\u0627\u06cc \u0628\u0632\u0646\u0645: /trade {sig.get('side','').lower()} {sig.get('entry')} sl:{sig.get('sl')} tp:{sig.get('tp')}"
            )
    # no_trade → silent

    log("Cycle complete.")


if __name__ == '__main__':
    main()