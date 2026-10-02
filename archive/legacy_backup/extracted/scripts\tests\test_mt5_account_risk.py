from mt5_account_risk import assess_account_policy, recommend_risk_budget


def test_assess_account_policy_marks_small_clean_account_as_normal():
    policy = assess_account_policy(
        balance=1000.0,
        equity=995.0,
        free_margin=980.0,
        margin=20.0,
        daily_pnl=5.0,
        loss_streak=0,
        open_positions=0,
    )
    assert policy["regime"] == "normal"
    assert policy["trade_allowed"] is True
    assert policy["base_risk_pct"] == 0.015
    assert policy["max_positions_allowed"] == 1


def test_assess_account_policy_moves_to_defensive_after_two_losses():
    policy = assess_account_policy(
        balance=1300.0,
        equity=1270.0,
        free_margin=1250.0,
        margin=25.0,
        daily_pnl=-18.0,
        loss_streak=2,
        open_positions=0,
    )
    assert policy["regime"] == "defensive"
    assert policy["trade_allowed"] is True
    assert policy["risk_multiplier"] == 0.75


def test_assess_account_policy_locks_account_on_large_drawdown():
    policy = assess_account_policy(
        balance=1000.0,
        equity=940.0,
        free_margin=920.0,
        margin=40.0,
        daily_pnl=-45.0,
        loss_streak=3,
        open_positions=0,
    )
    assert policy["regime"] == "locked"
    assert policy["trade_allowed"] is False
    assert "drawdown_limit" in policy["reasons"]


def test_recommend_risk_budget_reduces_b_grade_risk_on_defensive_account():
    policy = assess_account_policy(
        balance=1000.0,
        equity=985.0,
        free_margin=960.0,
        margin=20.0,
        daily_pnl=-8.0,
        loss_streak=2,
        open_positions=0,
    )
    budget = recommend_risk_budget(policy, setup_grade="B")
    assert budget["risk_pct"] == 0.0067
    assert budget["risk_usd"] == 6.7


def test_recommend_risk_budget_blocks_when_position_limit_reached():
    policy = assess_account_policy(
        balance=2000.0,
        equity=1990.0,
        free_margin=1950.0,
        margin=40.0,
        daily_pnl=0.0,
        loss_streak=0,
        open_positions=1,
    )
    budget = recommend_risk_budget(policy, setup_grade="A")
    assert budget["trade_allowed"] is False
    assert budget["reason"] == "position_limit"
