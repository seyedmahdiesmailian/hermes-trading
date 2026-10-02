from mt5_xau_runtime import _execute_management_action


class _Position:
    def __init__(self, symbol="XAUUSD", ticket=1001, type_=0, volume=0.05, tp=4353.21):
        self.symbol = symbol
        self.ticket = ticket
        self.type = type_
        self.volume = volume
        self.tp = tp


def test_execute_management_action_trail_stop_calls_modify(monkeypatch):
    calls = {}

    def _fake_modify(position, sl_price=None, tp_price=None):
        calls["position"] = position.ticket
        calls["sl_price"] = sl_price
        calls["tp_price"] = tp_price
        return {"ok": True, "kind": "modify"}

    monkeypatch.setattr("mt5_xau_runtime.execute_modify_position_prices", _fake_modify)
    out = _execute_management_action(_Position(), {"action": "trail_stop", "new_sl": 4338.1})

    assert out["ok"] is True
    assert calls == {"position": 1001, "sl_price": 4338.1, "tp_price": 4353.21}


def test_execute_management_action_close_runner_calls_partial_close(monkeypatch):
    calls = {}

    def _fake_close(position, close_volume):
        calls["position"] = position.ticket
        calls["close_volume"] = close_volume
        return {"ok": True, "kind": "close"}

    monkeypatch.setattr("mt5_xau_runtime.execute_partial_close", _fake_close)
    out = _execute_management_action(_Position(volume=0.05), {"action": "close_runner", "close_fraction": 1.0})

    assert out["ok"] is True
    assert calls == {"position": 1001, "close_volume": 0.05}


def test_execute_management_action_scale_in_calls_open(monkeypatch):
    calls = {}

    def _fake_open(symbol, side, lot, sl_price=None, tp_price=None, comment=""):
        calls["symbol"] = symbol
        calls["side"] = side
        calls["lot"] = lot
        calls["sl_price"] = sl_price
        calls["tp_price"] = tp_price
        calls["comment"] = comment
        return {"ok": True, "kind": "open"}

    monkeypatch.setattr("mt5_xau_runtime.execute_market_open", _fake_open)
    position = _Position(volume=0.05)
    out = _execute_management_action(
        position,
        {
            "action": "scale_in_existing_idea",
            "scale_fraction": 0.5,
            "side": "BUY",
            "new_sl": 4335.5,
            "tp_hint": 4350.0,
        },
    )

    assert out["ok"] is True
    assert calls["symbol"] == "XAUUSD"
    assert calls["side"] == "BUY"
    assert calls["lot"] == 0.03
    assert calls["sl_price"] == 4335.5
    assert calls["tp_price"] == 4350.0
