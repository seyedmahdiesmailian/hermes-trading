import json
import sys
from decimal import Decimal, ROUND_DOWN
import MetaTrader5 as mt5

DEFAULT_DEVIATION = 20
MAGIC = 20260806


def jprint(obj):
    print(json.dumps(obj, ensure_ascii=False))


def fail(msg, **extra):
    jprint({"ok": False, "error": msg, **extra})
    raise SystemExit(1)


def ensure_init():
    if not mt5.initialize():
        fail("mt5 initialize failed", last_error=mt5.last_error())


def symbol_info(symbol):
    info = mt5.symbol_info(symbol)
    if info is None:
        fail("symbol not found", symbol=symbol, last_error=mt5.last_error())
    if not info.visible:
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)
    return info


def normalize_volume(symbol, volume):
    info = symbol_info(symbol)
    step = info.volume_step or 0.01
    vol = max(info.volume_min, min(info.volume_max, float(volume)))
    q = Decimal(str(step))
    return float(Decimal(str(vol)).quantize(q, rounding=ROUND_DOWN))


def status():
    acc = mt5.account_info()
    if acc is None:
        fail("account info unavailable", last_error=mt5.last_error())
    positions = mt5.positions_get() or []
    jprint({
        "ok": True,
        "balance": acc.balance,
        "equity": acc.equity,
        "margin_free": acc.margin_free,
        "positions_total": len(positions),
        "symbols_with_positions": sorted({p.symbol for p in positions}),
    })


def check(symbol, side, lot, sl_points, tp_points):
    info = symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        fail("tick unavailable", symbol=symbol, last_error=mt5.last_error())
    lot = normalize_volume(symbol, lot)
    digits = info.digits
    point = info.point
    if side == "BUY":
        price = tick.ask
        order_type = mt5.ORDER_TYPE_BUY
        sl = round(price - sl_points * point, digits) if sl_points else 0.0
        tp = round(price + tp_points * point, digits) if tp_points else 0.0
    else:
        price = tick.bid
        order_type = mt5.ORDER_TYPE_SELL
        sl = round(price + sl_points * point, digits) if sl_points else 0.0
        tp = round(price - tp_points * point, digits) if tp_points else 0.0
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": DEFAULT_DEVIATION,
        "magic": MAGIC,
        "comment": "Hermes direct",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_check(req)
    jprint({"ok": True, "request": req, "check": result._asdict() if result else None, "last_error": mt5.last_error()})


if __name__ == "__main__":
    ensure_init()
    try:
        cmd = sys.argv[1].lower()
        if cmd == "status":
            status()
        elif cmd == "check":
            check(sys.argv[2], sys.argv[3].upper(), float(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6]))
        else:
            fail("unknown command", command=cmd)
    finally:
        mt5.shutdown()
