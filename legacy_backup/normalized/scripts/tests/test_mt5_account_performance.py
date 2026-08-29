from mt5_account_risk import compute_performance_state


def test_compute_performance_state_resets_day_and_baseline_when_new_day():
    current = {"day": "2026-08-06", "starting_balance": 980.0, "loss_streak": 2}
    out = compute_performance_state(current, today="2026-08-07", balance=1000.0, closed_trades=[])
    assert out["day"] == "2026-08-07"
    assert out["starting_balance"] == 1000.0
    assert out["daily_pnl"] == 0.0
    assert out["loss_streak"] == 0


def test_compute_performance_state_updates_daily_pnl_and_loss_streak_from_closed_trades():
    current = {"day": "2026-08-07", "starting_balance": 1000.0, "last_closed_ticket": 10, "loss_streak": 1}
    closed_trades = [
        {"ticket": 11, "profit": -4.0},
        {"ticket": 12, "profit": -3.0},
        {"ticket": 13, "profit": 6.0},
    ]
    out = compute_performance_state(current, today="2026-08-07", balance=999.0, closed_trades=closed_trades)
    assert out["daily_pnl"] == -1.0
    assert out["loss_streak"] == 0
    assert out["last_closed_ticket"] == 13
