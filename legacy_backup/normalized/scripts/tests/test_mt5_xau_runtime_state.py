from datetime import datetime, timezone

from mt5_xau_storage import (
    load_performance_state,
    load_runtime_state,
    save_performance_state,
    save_runtime_state,
)


def test_save_and_load_runtime_state_round_trip(tmp_path):
    state = {"active_plan_id": "p1", "last_action": "monitor"}
    save_runtime_state(tmp_path, state)
    loaded = load_runtime_state(tmp_path)
    assert loaded == state


def test_load_runtime_state_defaults_when_missing(tmp_path):
    assert load_runtime_state(tmp_path) == {}


def test_save_and_load_performance_state_round_trip(tmp_path):
    state = {
        "day": "2026-08-07",
        "starting_balance": 1000.0,
        "daily_pnl": -12.5,
        "loss_streak": 2,
        "last_closed_ticket": 123,
    }
    save_performance_state(tmp_path, state)
    assert load_performance_state(tmp_path) == state


def test_load_performance_state_defaults_when_missing(tmp_path):
    assert load_performance_state(tmp_path) == {}
