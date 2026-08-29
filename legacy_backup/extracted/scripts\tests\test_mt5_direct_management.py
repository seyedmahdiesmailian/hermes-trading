from mt5_direct import build_partial_close_request, build_modify_position_price_request


class _Pos:
    def __init__(self, ticket=1001, symbol="XAUUSD", type_=0, volume=0.10):
        self.ticket = ticket
        self.symbol = symbol
        self.type = type_
        self.volume = volume


class _Tick:
    def __init__(self, ask=4336.2, bid=4335.9):
        self.ask = ask
        self.bid = bid


class _Mt5:
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_SLTP = 6
    ORDER_TIME_GTC = 0
    ORDER_FILLING_IOC = 1


class _Info:
    point = 0.01
    digits = 2
    volume_min = 0.01
    volume_max = 100.0
    volume_step = 0.01
    visible = True


def test_build_partial_close_request_for_buy_position():
    req = build_partial_close_request(
        mt5_module=_Mt5,
        position=_Pos(type_=0, volume=0.10),
        tick=_Tick(),
        normalized_volume=0.04,
    )
    assert req["type"] == _Mt5.ORDER_TYPE_SELL
    assert req["position"] == 1001
    assert req["volume"] == 0.04
    assert req["price"] == 4335.9


def test_build_modify_position_price_request_uses_absolute_prices():
    req = build_modify_position_price_request(
        mt5_module=_Mt5,
        position=_Pos(),
        symbol="XAUUSD",
        sl_price=4330.5,
        tp_price=4350.0,
    )
    assert req["action"] == _Mt5.TRADE_ACTION_SLTP
    assert req["position"] == 1001
    assert req["sl"] == 4330.5
    assert req["tp"] == 4350.0
