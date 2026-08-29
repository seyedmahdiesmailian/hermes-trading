from datetime import datetime, timezone

from mt5_xau_trade_management import evaluate_trade_management


NOW = datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc)


def _base_trade(side="BUY"):
    return {
        "symbol": "XAUUSD",
        "side": side,
        "entry_price": 4300.0,
        "sl": 4290.0 if side == "BUY" else 4310.0,
        "tp_levels": [4310.0, 4320.0, 4335.0] if side == "BUY" else [4290.0, 4280.0, 4265.0],
        "tp_shares": [0.5, 0.3, 0.2],
        "scale_in_levels": [4298.0, 4295.0] if side == "BUY" else [4302.0, 4305.0],
        "filled_tp_levels": [],
        "breakeven_active": False,
        "runner_active": True,
        "scaled_in_levels": [],
        "volume": 0.10,
        "regime": "breakout_continuation",
        "setup_grade": "A",
        "momentum_strength": 0.9,
        "volatility_state": "normal",
        "structure_state": "healthy",
        "session_phase": "london",
        "rr_remaining": 2.4,
        "thesis_valid": True,
        "exposure_fraction": 0.5,
    }


def test_take_smaller_first_partial_on_strong_trend_runner():
    trade = _base_trade("BUY")

    decision = evaluate_trade_management(trade, market_price=4310.2, now=NOW)

    assert decision["action"] == "partial_take_profit"
    assert decision["target_hit"] == 4310.0
    assert decision["close_fraction"] == 0.3
    assert decision["reason"] == "strong_runner_keep_more"


def test_take_larger_first_partial_when_setup_is_weak():
    trade = _base_trade("BUY")
    trade["setup_grade"] = "C"
    trade["momentum_strength"] = 0.35
    trade["rr_remaining"] = 1.1

    decision = evaluate_trade_management(trade, market_price=4310.2, now=NOW)

    assert decision["action"] == "partial_take_profit"
    assert decision["close_fraction"] == 0.7
    assert decision["reason"] == "weak_follow_through_lock_more"


def test_move_stop_beyond_breakeven_when_trade_is_strong():
    trade = _base_trade("BUY")
    trade["filled_tp_levels"] = [4310.0]

    decision = evaluate_trade_management(trade, market_price=4311.0, now=NOW)

    assert decision["action"] == "move_stop_to_breakeven"
    assert decision["new_sl"] > 4300.0
    assert decision["reason"] == "lock_in_after_tp1"


def test_kill_runner_when_structure_breaks_after_targets():
    trade = _base_trade("BUY")
    trade["filled_tp_levels"] = [4310.0, 4320.0]
    trade["breakeven_active"] = True
    trade["structure_state"] = "failing"
    trade["momentum_strength"] = 0.25

    decision = evaluate_trade_management(trade, market_price=4321.0, now=NOW)

    assert decision["action"] == "close_runner"
    assert decision["close_fraction"] == 1.0
    assert decision["reason"] == "runner_structure_failure"


def test_trail_runner_with_tighter_distance_in_high_volatility():
    trade = _base_trade("BUY")
    trade["filled_tp_levels"] = [4310.0, 4320.0]
    trade["breakeven_active"] = True
    trade["volatility_state"] = "high"
    trade["momentum_strength"] = 0.55

    decision = evaluate_trade_management(trade, market_price=4324.0, now=NOW)

    assert decision["action"] == "trail_stop"
    assert decision["trail_distance"] == 3.0
    assert decision["reason"] == "high_volatility_tighter_trail"


def test_scale_in_only_when_thesis_is_still_valid_and_exposure_is_safe():
    trade = _base_trade("BUY")

    decision = evaluate_trade_management(trade, market_price=4297.8, now=NOW)

    assert decision["action"] == "scale_in_existing_idea"
    assert decision["scale_level"] == 4298.0
    assert decision["reason"] == "valid_pullback_add"


def test_block_scale_in_when_exposure_is_already_too_high():
    trade = _base_trade("BUY")
    trade["exposure_fraction"] = 1.05

    decision = evaluate_trade_management(trade, market_price=4297.8, now=NOW)

    assert decision["action"] == "hold"
    assert decision["reason"] == "scale_in_blocked_exposure"


def test_exit_early_when_thesis_is_invalidated_before_targets():
    trade = _base_trade("BUY")
    trade["thesis_valid"] = False
    trade["momentum_strength"] = 0.2

    decision = evaluate_trade_management(trade, market_price=4299.0, now=NOW)

    assert decision["action"] == "close_trade_early"
    assert decision["reason"] == "thesis_invalidated"


def test_hold_when_no_management_event_is_triggered():
    trade = _base_trade("BUY")
    trade["momentum_strength"] = 0.6

    decision = evaluate_trade_management(trade, market_price=4304.0, now=NOW)

    assert decision["action"] == "hold"
    assert decision["reason"] == "no_management_trigger"
