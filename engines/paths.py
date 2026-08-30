"""Single source of truth for on-disk state locations.

Why this exists (2026-08-30 audit): every module used to hardcode
Path('/home/ai/hermes-trading/data/...') at IMPORT time. The test suite
therefore wrote straight into live production state — running the tests
overwrote current_plan.json with synthetic 4600-price plans, reset
performance_state.json to a stale day (which silently re-based the daily
loss cap), and rewrote kill_switch_state.json with a fake last_check.
A test run was a production incident.

Fix: resolve paths at CALL time through this module, and let a test (or a
staging box) redirect the whole tree with set_data_root() / $HERMES_DATA_ROOT.
Production default is unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path

PRODUCTION_ROOT = Path("/home/ai/hermes-trading")

_override: Path | None = None


def set_data_root(root: str | Path | None) -> None:
    """Redirect all state paths. Pass None to return to production."""
    global _override
    _override = Path(root) if root else None


def get_data_root() -> Path:
    """Active project root (env var wins, then test override)."""
    env = os.environ.get("HERMES_DATA_ROOT")
    if env:
        return Path(env)
    return _override or PRODUCTION_ROOT


def data_dir() -> Path:
    return get_data_root() / "data"


def plan_dir() -> Path:
    return data_dir() / "xau_plan"


def signals_dir() -> Path:
    return data_dir() / "signals"


def calendar_dir() -> Path:
    return data_dir() / "calendar"


def logs_dir() -> Path:
    return get_data_root() / "logs"


def kill_switch_state() -> Path:
    return data_dir() / "kill_switch_state.json"


def cooldown_state() -> Path:
    return data_dir() / "cooldown_state.json"


def listener_state() -> Path:
    return signals_dir() / "listener_state.json"


def signals_log() -> Path:
    return signals_dir() / "signals_log.json"


def watchdog_state() -> Path:
    return plan_dir() / "watchdog_state.json"


def current_plan() -> Path:
    return plan_dir() / "current_plan.json"


def learning_state() -> Path:
    return plan_dir() / "learning_state.json"


def trade_journal() -> Path:
    return plan_dir() / "trade_journal.csv"


def calendar_cache() -> Path:
    return calendar_dir() / "economic_calendar.json"
