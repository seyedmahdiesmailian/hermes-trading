from datetime import datetime, timezone

from mt5_xau_orchestrator import compute_xau_position_size


def test_runtime_style_sizing_for_1000_balance_and_4_dollar_stop_is_five_cents():
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
