from mt5_account_risk import assess_account_policy, recommend_risk_budget
from mt5_xau_orchestrator import compute_xau_position_size


def _risk_and_size(balance: float):
    policy = assess_account_policy(
        balance=balance,
        equity=balance,
        free_margin=balance,
        margin=0.0,
        daily_pnl=0.0,
        loss_streak=0,
        open_positions=0,
    )
    budget = recommend_risk_budget(policy, setup_grade="A")
    sizing = compute_xau_position_size(
        balance=balance,
        risk_pct=budget["risk_pct"],
        stop_distance_price=4.0,
        point=0.01,
        point_value_per_lot=1.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
    )
    return budget, sizing


def test_multi_account_support_produces_different_risk_budgets_for_same_setup():
    small_budget, small_sizing = _risk_and_size(700.0)
    mid_budget, mid_sizing = _risk_and_size(1000.0)
    large_budget, large_sizing = _risk_and_size(2500.0)

    assert small_budget["risk_usd"] < mid_budget["risk_usd"] < large_budget["risk_usd"]
    assert small_sizing["lot"] <= mid_sizing["lot"] <= large_sizing["lot"]
