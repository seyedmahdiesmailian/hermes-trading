from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

from mt5_xau_runtime import _update_performance_state


class _Account:
    def __init__(self, balance=1341.75, equity=1341.75, margin_free=1341.75, margin=0.0):
        self.balance = balance
        self.equity = equity
        self.margin_free = margin_free
        self.margin = margin


def test_update_performance_state_uses_real_deal_history(monkeypatch, tmp_path):
    fake_deals = [
        {"ticket": 10, "time": int((datetime.now(timezone.utc) - timedelta(minutes=20)).timestamp()), "profit": -5.0, "symbol": "XAUUSD", "entry": mt5.DEAL_ENTRY_OUT},
        {"ticket": 11, "time": int((datetime.now(timezone.utc) - timedelta(minutes=10)).timestamp()), "profit": 7.0, "symbol": "XAUUSD", "entry": mt5.DEAL_ENTRY_OUT},
    ]

    monkeypatch.setattr("mt5_xau_runtime._load_closed_trade_snapshots", lambda days=7: fake_deals)
    monkeypatch.setattr("mt5_xau_runtime.load_performance_state", lambda: {
        "day": datetime.now(timezone.utc).date().isoformat(),
        "last_closed_ticket": 5,
        "daily_pnl": 0.0,
        "loss_streak": 0,
    })
    monkeypatch.setattr("mt5_xau_runtime.save_performance_state", lambda _, state: None)

    state = _update_performance_state(_Account(), datetime.now(timezone.utc))

    assert state["daily_pnl"] == 2.0
    assert state["loss_streak"] == 0
    assert state["last_closed_ticket"] == 11
