from mt5_account_risk import recommend_risk_budget


def test_recommend_risk_budget_defensive_after_loss_streak():
    policy = {
        "trade_allowed": True,
        "base_risk_pct": 0.015,
        "risk_multiplier": 0.75,
        "balance": 1000.0,
        "open_positions": 0,
        "max_positions_allowed": 1,
        "regime": "defensive",
        "reasons": ["recent_losses"],
    }
    out = recommend_risk_budget(policy, setup_grade="B")
    assert out["trade_allowed"] is True
    assert out["risk_pct"] == round(0.015 * 0.75 * 0.6, 4)
