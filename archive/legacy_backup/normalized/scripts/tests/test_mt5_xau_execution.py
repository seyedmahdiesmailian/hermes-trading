from datetime import datetime, timezone

from mt5_xau_orchestrator import execute_trade_blueprint


class DummyRunner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        return self.result


def test_execute_trade_blueprint_builds_open_command_for_buy():
    runner = DummyRunner({"ok": True, "result": {"retcode": 10009}})
    blueprint = {
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry_price": 4230.0,
        "sl": 4220.0,
        "tp": 4250.0,
    }
    out = execute_trade_blueprint(blueprint, lot=0.01, point=0.01, command_runner=runner, now=datetime(2026, 8, 7, 6, 30, tzinfo=timezone.utc))
    assert out["ok"] is True
    assert runner.calls
    argv = runner.calls[0]
    assert argv[0] == "open"
    assert argv[1] == "XAUUSD"
    assert argv[2] == "BUY"
    assert argv[3] == "0.01"


def test_execute_trade_blueprint_rejects_invalid_stop_distance():
    runner = DummyRunner({"ok": True})
    blueprint = {
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry_price": 4230.0,
        "sl": 4230.0,
        "tp": 4250.0,
    }
    out = execute_trade_blueprint(blueprint, lot=0.01, point=0.01, command_runner=runner, now=datetime(2026, 8, 7, 6, 30, tzinfo=timezone.utc))
    assert out["ok"] is False
    assert out["error"] == "invalid_stop_distance"
    assert runner.calls == []
