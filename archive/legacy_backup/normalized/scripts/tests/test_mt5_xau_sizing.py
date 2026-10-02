from datetime import datetime, timezone

from mt5_xau_orchestrator import compute_xau_position_size, execute_trade_blueprint


class DummyRunner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        return self.result


def test_compute_xau_position_size_targets_meaningful_size_for_1000_balance():
    sizing = compute_xau_position_size(
        balance=1000.0,
        risk_pct=0.02,
        stop_distance_price=4.0,
        point=0.01,
        point_value_per_lot=1.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
    )
    assert sizing["lot"] == 0.05
    assert sizing["risk_usd"] == 20.0
    assert sizing["meaningful"] is True


def test_compute_xau_position_size_rejects_tiny_trade_when_risk_is_not_meaningful():
    sizing = compute_xau_position_size(
        balance=300.0,
        risk_pct=0.01,
        stop_distance_price=10.0,
        point=0.01,
        point_value_per_lot=1.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
    )
    assert sizing["lot"] == 0.0
    assert sizing["meaningful"] is False
    assert sizing["reason"] == "below_min_meaningful_lot"


def test_compute_xau_position_size_caps_risk_when_raw_size_is_too_large():
    sizing = compute_xau_position_size(
        balance=1000.0,
        risk_pct=0.02,
        stop_distance_price=1.0,
        point=0.01,
        point_value_per_lot=1.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=0.10,
    )
    assert sizing["lot"] == 0.1
    assert sizing["capped"] is True


def test_execute_trade_blueprint_uses_dynamic_sizing_result():
    runner = DummyRunner({"ok": True, "result": {"retcode": 10009}})
    blueprint = {
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry_price": 4230.0,
        "sl": 4226.0,
        "tp": 4238.0,
    }
    out = execute_trade_blueprint(
        blueprint,
        lot=0.05,
        point=0.01,
        command_runner=runner,
        now=datetime(2026, 8, 7, 6, 30, tzinfo=timezone.utc),
    )
    assert out["ok"] is True
    assert runner.calls[0][3] == "0.05"
