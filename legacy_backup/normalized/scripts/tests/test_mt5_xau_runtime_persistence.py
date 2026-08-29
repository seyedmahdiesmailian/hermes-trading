from datetime import datetime, timezone

import MetaTrader5 as mt5

from mt5_xau_runtime import _build_management_trade


class _Position:
    def __init__(self, ticket=1001, volume=0.05, sl=4329.27, tp=4353.27):
        self.ticket = ticket
        self.volume = volume
        self.sl = sl
        self.tp = tp
        self.type = mt5.POSITION_TYPE_BUY
        self.price_open = 4337.23
        self.symbol = "XAUUSD"


def test_build_management_trade_includes_runtime_state():
    plan = {
        "quality": {"trend_strength": 10.0, "regime": "breakout_continuation"},
        "bias": "bullish",
        "invalidation": 4329.0,
        "execution": {
            "tp_levels": [4340.0, 4345.0],
            "tp_shares": [0.5, 0.5],
            "scale_in_levels": [4330.0],
        },
    }
    runtime = {
        "management": {
            "1001": {
                "filled_tp_levels": [4340.0],
                "breakeven_active": True,
                "runner_active": True,
                "scaled_in_levels": [4330.0],
            }
        }
    }

    out = _build_management_trade(plan, _Position(), runtime)

    assert out["filled_tp_levels"] == [4340.0]
    assert out["breakeven_active"] is True
    assert out["runner_active"] is True
    assert out["scaled_in_levels"] == [4330.0]
    assert out["tp_levels"] == [4340.0, 4345.0]
    assert out["volume"] == 0.05
    assert out["sl"] == 4329.27
