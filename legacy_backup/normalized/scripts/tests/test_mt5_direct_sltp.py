from mt5_direct import build_modify_position_price_request


def test_build_modify_request_allows_clearing_tp():
    class _Mt5:
        TRADE_ACTION_SLTP = 6

    class _Pos:
        ticket = 1001

    req = build_modify_position_price_request(_Mt5, _Pos(), symbol="XAUUSD", sl_price=4336.8, tp_price=None)
    assert req["sl"] == 4336.8
    assert req["tp"] == 0.0
