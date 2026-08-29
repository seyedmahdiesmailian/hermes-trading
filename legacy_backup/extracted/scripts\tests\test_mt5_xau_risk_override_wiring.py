from mt5_xau_runtime import _build_execution_sizing


class FakeInfo:
    point = 0.01
    volume_min = 0.01
    volume_step = 0.01
    volume_max = 10.0


class TestRiskOverrideWiring:
    """When _build_execution_sizing receives a risk_override, it must use it."""

    def test_no_override_uses_budget_risk(self):
        policy = {"balance": 5000.0, "base_risk_pct": 0.02, "risk_multiplier": 1.0, "trade_allowed": True, "max_positions_allowed": 1, "open_positions": 0}
        bp = {"entry_price": 2000, "sl": 1990}  # 10 price = 1000 points
        sizing = _build_execution_sizing(bp, FakeInfo(), policy, "A")
        assert sizing["risk_pct"] == 0.02
        assert sizing["meaningful"] is True

    def test_risk_override_overrides_risk_pct(self):
        policy = {"balance": 5000.0, "base_risk_pct": 0.02, "risk_multiplier": 1.0, "trade_allowed": True, "max_positions_allowed": 1, "open_positions": 0}
        bp = {"entry_price": 2000, "sl": 1990}
        sizing = _build_execution_sizing(bp, FakeInfo(), policy, "A", risk_override=0.01)
        assert sizing["risk_pct"] == 0.01
        assert sizing["meaningful"] is True

    def test_risk_override_reduces_lot(self):
        policy = {"balance": 5000.0, "base_risk_pct": 0.02, "risk_multiplier": 1.0, "trade_allowed": True, "max_positions_allowed": 1, "open_positions": 0}
        bp = {"entry_price": 2000, "sl": 1995}  # 5 price = 500 points
        normal = _build_execution_sizing(bp, FakeInfo(), policy, "A")
        reduced = _build_execution_sizing(bp, FakeInfo(), policy, "A", risk_override=0.005)
        assert reduced["lot"] < normal["lot"]

    def test_risk_override_zero_means_no_trade(self):
        policy = {"balance": 5000.0, "base_risk_pct": 0.02, "risk_multiplier": 1.0, "trade_allowed": True, "max_positions_allowed": 1, "open_positions": 0}
        bp = {"entry_price": 2000, "sl": 1990}
        sizing = _build_execution_sizing(bp, FakeInfo(), policy, "A", risk_override=0.0)
        assert sizing["meaningful"] is False
        assert sizing["risk_pct"] == 0.0
