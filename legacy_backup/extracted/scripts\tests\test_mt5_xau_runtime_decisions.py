from datetime import datetime, timezone

from mt5_xau_orchestrator import build_plan_from_context
from mt5_xau_runtime import _infer_setup_grade, _select_execution_decision


class _Tick:
    def __init__(self, ask):
        self.ask = ask


def _bull_breakout_plan():
    ctx = {
        "symbol": "XAUUSD",
        "session": "london",
        "bias": "bullish",
        "atr": 10.0,
        "zones": {
            "value_low": 4320.0,
            "value_high": 4330.0,
            "long_entry_low": 4315.0,
            "long_entry_high": 4320.0,
            "short_entry_low": 4330.0,
            "short_entry_high": 4335.0,
        },
        "invalidation": 4312.0,
        "targets": [4338.0, 4345.0, 4355.0],
        "execution": {
            "entry_mode": "breakout_pullback_hybrid",
            "breakout_trigger": 4331.0,
            "scale_in_levels": [4320.0, 4317.0],
            "tp_levels": [4338.0, 4345.0, 4355.0],
            "tp_shares": [0.5, 0.3, 0.2],
        },
        "quality": {
            "alignment": "aligned",
            "trend_strength": 18.0,
            "regime": "breakout_continuation",
        },
        "context": {"m15_last": 4332.0, "h1_last": 4328.0, "h4_last": 4318.0},
    }
    return build_plan_from_context(ctx, now=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc))


def _bull_pullback_plan():
    ctx = {
        "symbol": "XAUUSD",
        "session": "london",
        "bias": "bullish",
        "atr": 10.0,
        "zones": {
            "value_low": 4320.0,
            "value_high": 4330.0,
            "long_entry_low": 4315.0,
            "long_entry_high": 4320.0,
            "short_entry_low": 4330.0,
            "short_entry_high": 4335.0,
        },
        "invalidation": 4312.0,
        "targets": [4338.0, 4345.0, 4355.0],
        "execution": {
            "entry_mode": "scale_in_pullback",
            "breakout_trigger": 4331.0,
            "scale_in_levels": [4320.0, 4317.0],
            "tp_levels": [4338.0, 4345.0, 4355.0],
            "tp_shares": [0.5, 0.3, 0.2],
        },
        "quality": {
            "alignment": "aligned",
            "trend_strength": 18.0,
            "regime": "pullback_continuation",
        },
        "context": {"m15_last": 4319.0, "h1_last": 4328.0, "h4_last": 4318.0},
    }
    return build_plan_from_context(ctx, now=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc))


def test_select_execution_decision_returns_market_entry_for_breakout_confirmation():
    plan = _bull_breakout_plan()
    monitor = _select_execution_decision(plan, _Tick(ask=4332.5), now=datetime(2026, 8, 7, 9, 5, tzinfo=timezone.utc))
    assert monitor["action"] in {"market_entry_now", "market_order"}
    assert monitor["blueprint"]["tp_levels"] == [4338.0, 4345.0, 4355.0]


def test_select_execution_decision_returns_limit_plan_for_pullback_scale_zone():
    plan = _bull_pullback_plan()
    monitor = _select_execution_decision(plan, _Tick(ask=4314.0), now=datetime(2026, 8, 7, 9, 5, tzinfo=timezone.utc))
    assert monitor["action"] == "place_buy_limit"
    assert monitor["entry_price"] == 4320.0


def test_select_execution_decision_returns_wait_when_range_or_neutral():
    plan = _bull_pullback_plan()
    plan["bias"] = "neutral"
    plan["quality"]["regime"] = "range"
    monitor = _select_execution_decision(plan, _Tick(ask=4325.0), now=datetime(2026, 8, 7, 9, 5, tzinfo=timezone.utc))
    assert monitor["action"] == "no_trade"


def test_infer_setup_grade_treats_breakout_aligned_context_as_grade_a():
    plan = _bull_breakout_plan()
    assert _infer_setup_grade(plan) == "A"
