from datetime import datetime, timezone

from mt5_xau_plan import (
    build_trade_blueprint,
    classify_price_location,
    decide_execution_action,
    select_reassessment_mode,
)


def test_select_reassessment_mode_uses_morning_for_asia():
    assert select_reassessment_mode("asia") == "morning_plan"


def test_select_reassessment_mode_uses_london_review_for_london():
    assert select_reassessment_mode("london") == "london_reassessment"


def test_classify_price_location_returns_discount_when_price_below_value_zone():
    zones = {
        "value_low": 4230.0,
        "value_high": 4240.0,
        "long_entry_low": 4226.0,
        "long_entry_high": 4232.0,
        "short_entry_low": 4252.0,
        "short_entry_high": 4258.0,
    }
    assert classify_price_location(4228.5, zones) == "long_zone"


def test_build_trade_blueprint_prefers_long_in_discount_with_bull_bias():
    plan = {
        "symbol": "XAUUSD",
        "bias": "bullish",
        "invalidation": 4218.0,
        "targets": [4256.0, 4272.0],
        "zones": {
            "value_low": 4230.0,
            "value_high": 4240.0,
            "long_entry_low": 4226.0,
            "long_entry_high": 4232.0,
            "short_entry_low": 4252.0,
            "short_entry_high": 4258.0,
        },
    }
    blueprint = build_trade_blueprint(plan, price=4229.0, trigger_ok=True)
    assert blueprint["side"] == "BUY"
    assert blueprint["entry_zone"] == "long_zone"
    assert blueprint["tp"] == 4256.0
    assert blueprint["sl"] == 4218.0


def test_decide_execution_action_waits_when_trigger_missing_inside_zone():
    plan = {
        "symbol": "XAUUSD",
        "bias": "bullish",
        "invalidation": 4218.0,
        "targets": [4256.0, 4272.0],
        "zones": {
            "value_low": 4230.0,
            "value_high": 4240.0,
            "long_entry_low": 4226.0,
            "long_entry_high": 4232.0,
            "short_entry_low": 4252.0,
            "short_entry_high": 4258.0,
        },
    }
    action = decide_execution_action(plan, price=4229.5, trigger_ok=False, now=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc))
    assert action["action"] == "wait_for_trigger"
    assert action["zone"] == "long_zone"


def test_decide_execution_action_returns_market_order_when_trigger_confirms():
    plan = {
        "symbol": "XAUUSD",
        "bias": "bullish",
        "invalidation": 4218.0,
        "targets": [4256.0, 4272.0],
        "zones": {
            "value_low": 4230.0,
            "value_high": 4240.0,
            "long_entry_low": 4226.0,
            "long_entry_high": 4232.0,
            "short_entry_low": 4252.0,
            "short_entry_high": 4258.0,
        },
    }
    action = decide_execution_action(plan, price=4229.5, trigger_ok=True, now=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc))
    assert action["action"] in {"market_order", "market_entry_now"}
    assert action["blueprint"]["side"] == "BUY"


def test_decide_execution_action_returns_no_trade_when_price_is_in_middle():
    plan = {
        "symbol": "XAUUSD",
        "bias": "bullish",
        "invalidation": 4218.0,
        "targets": [4256.0, 4272.0],
        "zones": {
            "value_low": 4230.0,
            "value_high": 4240.0,
            "long_entry_low": 4226.0,
            "long_entry_high": 4232.0,
            "short_entry_low": 4252.0,
            "short_entry_high": 4258.0,
        },
    }
    action = decide_execution_action(plan, price=4245.0, trigger_ok=True, now=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc))
    assert action["action"] == "no_trade"
    assert action["reason"] == "outside_entry_zones"
