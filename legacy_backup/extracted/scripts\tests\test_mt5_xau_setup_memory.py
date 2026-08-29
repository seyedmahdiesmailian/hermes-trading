from datetime import datetime, timezone

from mt5_xau_runtime import _classify_closed_trade


class _Deal:
    def __init__(self, ticket, profit, comment, magic=20260806, time=None):
        self.ticket = ticket
        self.profit = profit
        self.comment = comment
        self.magic = magic
        self.time = time or int(datetime.now(timezone.utc).timestamp())


def test_classify_closed_trade_as_sl_hit():
    out = _classify_closed_trade(_Deal(1, -2.20, "[sl 4336.80]"))
    assert out["exit_type"] == "sl"
    assert out["pnl"] == -2.20
    assert out["managed"] is False


def test_classify_closed_trade_as_tp_hit():
    out = _classify_closed_trade(_Deal(2, 26.55, "[tp 4336.20]"))
    assert out["exit_type"] == "tp"
    assert out["pnl"] == 26.55
    assert out["managed"] is False


def test_classify_closed_trade_as_managed_partial():
    out = _classify_closed_trade(_Deal(3, 1.02, "Hermes manage partial"))
    assert out["exit_type"] == "partial"
    assert out["pnl"] == 1.02
    assert out["managed"] is True


def test_classify_closed_trade_as_managed_runner():
    out = _classify_closed_trade(_Deal(4, -0.36, "Hermes manage partial", time=10))
    assert out["exit_type"] == "partial"
    assert out["pnl"] == -0.36
    assert out["managed"] is True


def test_classify_closed_trade_maintains_ticket_order():
    deals = [
        _Deal(10, -0.78, "[sl 4337.30]"),
        _Deal(11, 5.0, "Hermes manage partial"),
        _Deal(12, -1.5, "[sl 4336.80]"),
        _Deal(13, 3.0, "[tp 4340.00]"),
    ]
    results = [_classify_closed_trade(d) for d in deals]

    exit_sequence = [r["exit_type"] for r in results]
    assert exit_sequence == ["sl", "partial", "sl", "tp"]
    assert all(isinstance(r["pnl"], float) for r in results)
