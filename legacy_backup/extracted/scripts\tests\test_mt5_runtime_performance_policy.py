from mt5_account_risk import compute_performance_state


def test_performance_state_keeps_loss_streak_when_new_losses_arrive_same_day():
    current = {"day": "2026-08-07", "starting_balance": 1000.0, "last_closed_ticket": 20, "loss_streak": 1, "daily_pnl": -2.0}
    closed_trades = [
        {"ticket": 21, "profit": -3.0},
        {"ticket": 22, "profit": -4.0},
    ]
    out = compute_performance_state(current, today="2026-08-07", balance=991.0, closed_trades=closed_trades)
    assert out["loss_streak"] == 3
    assert out["daily_pnl"] == -9.0
    assert out["last_closed_ticket"] == 22
