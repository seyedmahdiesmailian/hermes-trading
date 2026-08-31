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
from notifier.telegram import send_telegram, send_ops

# b39: BASE_DIR (import-time Path) removed — nothing used it; logs/reports
# resolve through _log_file()/_report_file() below.
# logs go through paths so a test/staging run (HERMES_DATA_ROOT) can never
# write into production logs (2026-08-30 audit convention: state via engines.paths).
# b37: these were module-level constants bound at IMPORT time — which is
# before hermetic.use_temp_data_root() flips HERMES_DATA_ROOT, so any test
# importing hermes_master wrote straight into production logs/master.log.
# Resolved at CALL time now, like everything else.
from engines import paths as _paths
DRY_RUN = os.getenv('HERMES_DRY_RUN', 'true').lower() not in {'0', 'false', 'no'}


def _log_file():
    return _paths.logs_dir() / 'master.log'


def _report_file():
    return _paths.logs_dir() / 'report.txt'


def log(msg: str):
    path = _log_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    # no print(): cron redirects stdout into the same log → duplicate lines
    with path.open('a', encoding='utf-8') as f:
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
    path = _report_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


# Resolved at CALL time (engines.paths convention): hermetic.use_temp_data_root()
# sets HERMES_DATA_ROOT after this module is imported, so a module-level
# constant would point at PRODUCTION data/ops and a test could unlink it.
def _guard_alert_state():
    return _paths.data_dir() / 'ops' / 'guard_alert_state.json'


# Re-alert interval for an UNCHANGED degradation. The master runs every 15
# min; without this a calendar outage (both feeds failing was measured
# live-reachable in b30) pages the ops channel 4x/hour for the same fact
# until it heals — alert fatigue that gets the next real page ignored.
GUARD_ALERT_COOLDOWN_SEC = 6 * 3600


def alert_degraded_guards(payload: dict, step: str,
                          now: datetime | None = None) -> bool:
    """b37: hermes_runtime.cycle tags the fallback guard merge outcome in
    payload['guards']. 'error' (news_lock/time_exit blew up) and
    'calendar_unavailable' (news_lock could not see the news) mean a live
    position is being managed with FEWER safety guards than usual — that must
    reach the ops channel even on a step that is otherwise silent.

    Deduped: the same (state, detail) re-alerts at most once per
    GUARD_ALERT_COOLDOWN_SEC; a CHANGED failure alerts immediately, and so
    does the same failure recurring after a healthy cycle cleared the state.
    The log line is written every time — only the page is throttled.

    Returns True if an alert was sent (so a test can assert it)."""
    guards = payload.get('guards') or {}
    state = guards.get('state')
    if state not in {'error', 'calendar_unavailable'}:
        if state in {'none', 'applied'}:
            # Guards ran fine this cycle → forget the old degradation so the
            # next one pages immediately, even inside the cooldown window.
            # NOTE: an ABSENT guards key means the watchdog is alive (the
            # runtime did not manage at all), NOT that guards are healthy —
            # so it must not clear the state.
            try:
                _guard_alert_state().unlink(missing_ok=True)
            except OSError:
                pass
        return False
    detail = str(guards.get('detail') or '')[:200]
    key = f"{state}|{detail[:80]}"
    now = now or datetime.now(timezone.utc)
    prev = _paths.read_json_safe(_guard_alert_state(), {},
                                 label='guard_alert') or {}
    if isinstance(prev, dict) and prev.get('key') == key:
        try:
            age = (now - datetime.fromisoformat(str(prev['at']))).total_seconds()
        except (KeyError, TypeError, ValueError):
            age = None
        if age is not None and 0 <= age < GUARD_ALERT_COOLDOWN_SEC:
            log(f"GUARDS DEGRADED [{state}] step={step}: {detail} "
                f"(already paged {int(age)}s ago, suppressed)")
            return False
    log(f"GUARDS DEGRADED [{state}] step={step}: {detail}")
    try:
        _paths.write_json_atomic(_guard_alert_state(),
                                 {'key': key, 'state': state, 'step': step,
                                  'detail': detail, 'at': now.isoformat()})
    except Exception as e:
        log(f"guard alert state write failed: {e}")   # page anyway
    try:
        from notifier.telegram import send_ops
        send_ops(f"🛑 Hermes | گاردهای ایمنی مدیریت ضعیف شد\n"
                 f"step={step} | state={state}\n{detail}")
    except Exception as e:
        log(f"ops alert failed: {e}")
    return True


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
        send_ops(f"🛑 Hermes | Bridge unreachable\n{bridge.url}")
        return

    # ── Run the autonomous trading cycle ──
    log("Cycle start...")
    payload = cycle(bridge, dry_run=DRY_RUN)

    if not payload.get('ok'):
        log(f"Cycle failed: {payload.get('error', 'unknown')}")
        send_ops(f"🛑 Hermes | Cycle Failed\n{payload.get('error', 'unknown')}")
        return

    step = payload.get('step', '?')
    will_execute = payload.get('will_execute_now', False)
    monitor_action = payload.get('monitor', {}).get('action', 'none')
    log(f"Step={step} execute={will_execute} action={monitor_action}")

    # ── Phase 2: signals handled instantly by signal_daemon.py (systemd) ──

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

    # ── b37: safety-guard failures on the fallback management path ──
    # The runtime's news_lock/time_exit merge used to swallow errors in a
    # bare `except Exception: pass` — the trade kept its original stop and
    # nobody knew the guards were skipped. The cycle now tags the outcome;
    # surface it on the ops channel even when the step is otherwise silent.
    alert_degraded_guards(payload, step)

    # ── Telegram: report plan/halt/execute (reassess = silent unless bias flips) ──
    if step == 'reassess':
        prev_bias = payload.get('previous_bias')
        new_bias = (payload.get('plan') or {}).get('bias')
        if prev_bias and new_bias and prev_bias != new_bias:
            send_telegram(f"\u26a1 \u062a\u063a\u06cc\u06cc\u0631 \u0628\u0627\u06cc\u0632: {prev_bias} \u2192 {new_bias}")
    if step in {'plan'}:
        send_telegram(report)
    elif step == 'halted':
        send_ops(payload.get('brief', '\U0001f6d1 Kill Switch'))
    elif will_execute:
        send_telegram(report)
    elif step == 'manage':
        send_telegram(report)

    # no_trade → silent

    log("Cycle complete.")


if __name__ == '__main__':
    main()