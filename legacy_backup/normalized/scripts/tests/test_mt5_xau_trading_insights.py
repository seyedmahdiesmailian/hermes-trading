import pytest

from mt5_xau_runtime import _build_trading_insights


class TestTradingInsights:
    """_build_trading_insights(exit_analysis, performance_state, account_policy) -> dict"""

    def test_healthy_trader_all_systems_go(self):
        analysis = {
            "total_closed": 10,
            "sl": {"count": 3, "total_pnl": -15.0},
            "tp": {"count": 7, "total_pnl": 140.0},
            "partial": {"count": 4, "total_pnl": 8.0},
            "sl_dominant": False,
            "sl_ratio": 0.3,
            "avg_sl_loss": -5.0,
            "managed_total_pnl": 8.0,
            "managed_win_ratio": 0.75,
        }
        perf = {"daily_pnl": 20.0, "loss_streak": 0}
        policy = {"regime": "normal", "trade_allowed": True, "base_risk_pct": 0.015, "risk_multiplier": 1.0}

        out = _build_trading_insights(analysis, perf, policy)

        assert out["defcon"] == "green"
        assert out["partial_allowed"] is True
        assert out["runner_allowed"] is True
        assert out["scale_in_allowed"] is True
        assert out["risk_override"] is None

    def test_sl_dominant_forces_defcon_red(self):
        analysis = {
            "total_closed": 8,
            "sl": {"count": 6, "total_pnl": -48.0},
            "tp": {"count": 2, "total_pnl": 20.0},
            "partial": {"count": 0, "total_pnl": 0.0},
            "sl_dominant": True,
            "sl_ratio": 0.75,
            "avg_sl_loss": -8.0,
            "managed_total_pnl": 0.0,
            "managed_win_ratio": 0.0,
        }
        perf = {"daily_pnl": -28.0, "loss_streak": 4}
        policy = {"regime": "normal", "trade_allowed": True, "base_risk_pct": 0.015, "risk_multiplier": 1.0}

        out = _build_trading_insights(analysis, perf, policy)

        assert out["defcon"] == "red"
        assert out["trade_allowed"] is False
        assert out["partial_allowed"] is True
        assert out["runner_allowed"] is False
        assert out["scale_in_allowed"] is False

    def test_managed_exits_negative_disables_runners(self):
        analysis = {
            "total_closed": 6,
            "sl": {"count": 3, "total_pnl": -18.0},
            "tp": {"count": 1, "total_pnl": 15.0},
            "partial": {"count": 2, "total_pnl": -3.0},
            "sl_dominant": False,
            "sl_ratio": 0.5,
            "avg_sl_loss": -6.0,
            "managed_total_pnl": -3.0,
            "managed_win_ratio": 0.0,
        }
        perf = {"daily_pnl": -6.0, "loss_streak": 2}
        policy = {"regime": "defensive", "trade_allowed": True, "base_risk_pct": 0.015, "risk_multiplier": 0.75}

        out = _build_trading_insights(analysis, perf, policy)

        assert out["defcon"] == "yellow"
        assert out["partial_allowed"] is True
        assert out["runner_allowed"] is False
        assert out["scale_in_allowed"] is False

    def test_empty_history_no_penalty(self):
        analysis = {
            "total_closed": 0,
            "sl": {"count": 0, "total_pnl": 0},
            "tp": {"count": 0, "total_pnl": 0},
            "partial": {"count": 0, "total_pnl": 0},
            "sl_dominant": False,
            "sl_ratio": 0.0,
            "avg_sl_loss": 0.0,
            "managed_total_pnl": 0.0,
            "managed_win_ratio": 0.0,
        }
        perf = {"daily_pnl": 0.0, "loss_streak": 0}
        policy = {"regime": "normal", "trade_allowed": True, "base_risk_pct": 0.015, "risk_multiplier": 1.0}

        out = _build_trading_insights(analysis, perf, policy)

        assert out["defcon"] == "green"
        assert out["trade_allowed"] is True
        assert out["partial_allowed"] is True
        assert out["runner_allowed"] is True
        assert out["scale_in_allowed"] is True

    def test_loss_streak_with_good_rr_stays_yellow(self):
        analysis = {
            "total_closed": 5,
            "sl": {"count": 3, "total_pnl": -15.0},
            "tp": {"count": 2, "total_pnl": 80.0},
            "partial": {"count": 0, "total_pnl": 0},
            "sl_dominant": False,
            "sl_ratio": 0.6,
            "avg_sl_loss": -5.0,
            "managed_total_pnl": 0.0,
            "managed_win_ratio": 0.0,
        }
        perf = {"daily_pnl": 65.0, "loss_streak": 3}
        policy = {"regime": "normal", "trade_allowed": True, "base_risk_pct": 0.015, "risk_multiplier": 1.0}

        out = _build_trading_insights(analysis, perf, policy)

        # loss streak exists but RR is strong (avg win 40:loss 5 = 8:1)
        assert out["defcon"] == "yellow"
        assert out["trade_allowed"] is True
        assert out["runner_allowed"] is False
