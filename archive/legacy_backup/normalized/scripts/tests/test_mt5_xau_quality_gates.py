from datetime import datetime, timezone

from mt5_xau_orchestrator import build_plan_from_context, evaluate_monitor_cycle


def _ctx(bias="bullish", alignment="aligned", trend_strength=18.0):
    return {
        "symbol": "XAUUSD",
        "session": "london",
        "bias": bias,
        "atr": 12.0,
        "zones": {
            "value_low": 4230.0,
            "value_high": 4240.0,
            "long_entry_low": 4226.0,
            "long_entry_high": 4232.0,
            "short_entry_low": 4252.0,
            "short_entry_high": 4258.0,
        },
        "invalidation": 4218.0,
        "targets": [4256.0, 4272.0],
        "quality": {
            "trend_strength": trend_strength,
            "alignment": alignment,
            "distance_to_value_low_atr": 0.3,
            "distance_to_value_high_atr": 1.1,
            "bias_votes": {"m15": bias, "h1": bias, "h4": bias},
        },
        "context": {"m15_last": 4231.0, "h1_last": 4234.0, "h4_last": 4248.0},
    }


def test_build_plan_from_context_preserves_quality_block():
    plan = build_plan_from_context(_ctx(), now=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc))
    assert plan["quality"]["alignment"] == "aligned"
    assert plan["quality"]["trend_strength"] == 18.0


def test_evaluate_monitor_cycle_blocks_market_order_when_alignment_is_mixed():
    plan = build_plan_from_context(_ctx(alignment="mixed"), now=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc))
    result = evaluate_monitor_cycle(plan, price=4229.0, now=datetime(2026, 8, 7, 9, 5, tzinfo=timezone.utc), trigger_ok=True)
    assert result["action"] == "wait_for_trigger"
    assert result["reason"] == "quality_filter"


def test_evaluate_monitor_cycle_blocks_market_order_when_trend_strength_is_weak():
    plan = build_plan_from_context(_ctx(trend_strength=1.2), now=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc))
    result = evaluate_monitor_cycle(plan, price=4229.0, now=datetime(2026, 8, 7, 9, 5, tzinfo=timezone.utc), trigger_ok=True)
    assert result["action"] == "wait_for_trigger"
    assert result["reason"] == "quality_filter"
