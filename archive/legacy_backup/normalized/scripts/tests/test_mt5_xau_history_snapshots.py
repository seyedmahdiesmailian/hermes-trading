from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

from mt5_xau_runtime import _load_closed_trade_snapshots


def test_load_closed_trade_snapshots_filters_engine_xau_deals(monkeypatch):
    class _Deal:
        def __init__(self, ticket, symbol, profit, entry, seconds_ago, comment="Hermes", magic=20260806):
            self.ticket = ticket
            self.symbol = symbol
            self.profit = profit
            self.entry = entry
            self.time = int((datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).timestamp())
            self.comment = comment
            self.magic = magic
            self.volume = 0.05
            self.price = 4337.2
            self.order = ticket + 1000
            self.position_id = ticket + 2000

    fake_deals = [
        _Deal(1, "XAUUSD", 5.0, mt5.DEAL_ENTRY_OUT, 100),
        _Deal(2, "EURUSD", 3.0, mt5.DEAL_ENTRY_OUT, 90),
        _Deal(3, "XAUUSD", -4.0, mt5.DEAL_ENTRY_IN, 80),
        _Deal(4, "XAUUSD", 2.5, mt5.DEAL_ENTRY_OUT, 70, comment="manual", magic=0),
    ]
    monkeypatch.setattr("mt5_xau_runtime.mt5.history_deals_get", lambda start, end: fake_deals)

    out = _load_closed_trade_snapshots(days=7)

    assert out == [
        {
            "ticket": 1,
            "symbol": "XAUUSD",
            "profit": 5.0,
            "volume": 0.05,
            "price": 4337.2,
            "time": fake_deals[0].time,
            "comment": "Hermes",
            "magic": 20260806,
            "order": 1001,
            "position_id": 2001,
        }
    ]
