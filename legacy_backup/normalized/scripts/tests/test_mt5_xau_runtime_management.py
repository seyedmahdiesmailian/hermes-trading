from datetime import datetime, timezone

from mt5_xau_runtime import _select_management_decision


class _Position:
    def __init__(self, symbol="XAUUSD", ticket=1001, type_=0, volume=0.10, price_open=4300.0, sl=4290.0, tp=4338.0):
        self.symbol = symbol
        self.ticket = ticket
        self.type = type_
        self.volume = volume
        self.price_open = price_open
        self.sl = sl
        self.tp = tp


class _Tick:
    def __init__(self, ask, bid=None):
        self.ask = ask
        self.bid = bid if bid is not None else ask - 0.3


NOW = datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc)


def _plan():
    return {
        "plan_id": "xau-test",
        "symbol": "XAUUSD",
        "bias": "bullish",
        "invalidation": 4290.0,
        "execution": {
            "tp_levels": [4310.0, 4320.0, 4335.0],
            "tp_shares": [0.3, 0.3, 0.4],
            "scale_in_levels": [4298.0, 4295.0],
        },
        "quality": {"regime": "breakout_continuation", "alignment": "aligned", "trend_strength": 18.0},
    }


def test_select_management_decision_partial_take_profit_for_live_position():
    plan = _plan()
    position = _Position()
    tick = _Tick(ask=4310.2, bid=4309.9)

    decision = _select_management_decision(plan, position, tick, runtime_state={}, now=NOW)

    assert decision["action"] == "partial_take_profit"
    assert decision["close_fraction"] == 0.3
    assert decision["position_ticket"] == 1001


def test_select_management_decision_trails_runner_after_second_target():
    plan = _plan()
    position = _Position(sl=4301.0)
    tick = _Tick(ask=4324.0, bid=4323.7)
    runtime_state = {"management": {"1001": {"filled_tp_levels": [4310.0, 4320.0], "breakeven_active": True}}}

    decision = _select_management_decision(plan, position, tick, runtime_state=runtime_state, now=NOW)

    assert decision["action"] == "trail_stop"
    assert decision["new_sl"] > 4300.0


def test_select_management_decision_returns_none_when_no_position_management_event():
    plan = _plan()
    position = _Position()
    tick = _Tick(ask=4304.0, bid=4303.7)

    decision = _select_management_decision(plan, position, tick, runtime_state={}, now=NOW)

    assert decision is None
