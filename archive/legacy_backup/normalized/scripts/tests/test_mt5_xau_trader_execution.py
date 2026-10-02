from datetime import datetime, timezone

from mt5_xau_plan import decide_execution_action


NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


def _base_plan(**overrides):
    plan = {
        "symbol": "XAUUSD",
        "bias": "bullish",
        "zones": {
            "value_low": 4328.0,
            "value_high": 4340.0,
            "long_entry_low": 4324.0,
            "long_entry_high": 4330.0,
            "short_entry_low": 4340.0,
            "short_entry_high": 4346.0,
        },
        "invalidation": 4318.0,
        "targets": [4342.0, 4348.0, 4356.0],
        "execution": {
            "entry_mode": "adaptive",
            "scale_in_levels": [4328.0, 4325.5],
            "tp_levels": [4342.0, 4348.0, 4356.0],
            "tp_shares": [0.5, 0.3, 0.2],
            "breakout_trigger": 4341.0,
            "pullback_trigger": 4330.0,
        },
        "quality": {"alignment": "aligned", "trend_strength": 6.0},
    }
    plan.update(overrides)
    return plan


def test_decide_execution_action_prefers_market_entry_on_confirmed_pullback():
    plan = _base_plan()
    result = decide_execution_action(plan, price=4328.5, trigger_ok=True, now=NOW)
    assert result["action"] == "market_entry_now"
    assert result["execution_style"] == "pullback_continuation"
    assert result["blueprint"]["tp_levels"] == [4342.0, 4348.0, 4356.0]



def test_decide_execution_action_uses_buy_limit_when_discount_without_trigger():
    plan = _base_plan()
    result = decide_execution_action(plan, price=4321.5, trigger_ok=False, now=NOW)
    assert result["action"] == "place_buy_limit"
    assert result["entry_price"] == 4324.0
    assert result["execution_style"] == "pullback_limit"



def test_decide_execution_action_uses_buy_stop_for_breakout_continuation():
    plan = _base_plan()
    result = decide_execution_action(plan, price=4340.5, trigger_ok=False, now=NOW)
    assert result["action"] == "place_buy_stop"
    assert result["entry_price"] == 4341.0
    assert result["execution_style"] == "breakout_continuation"



def test_decide_execution_action_waits_when_premium_is_too_extended():
    plan = _base_plan()
    result = decide_execution_action(plan, price=4352.0, trigger_ok=False, now=NOW)
    assert result["action"] == "wait_for_pullback"
    assert result["reason"] == "price_extended_above_breakout_zone"
