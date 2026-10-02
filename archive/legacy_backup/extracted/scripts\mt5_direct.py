import json
import sys
from dataclasses import asdict, is_dataclass
from decimal import Decimal, ROUND_DOWN

import MetaTrader5 as mt5

DEFAULT_DEVIATION = 20
MAGIC = 20260806
FILLING_CANDIDATES = [
    mt5.ORDER_FILLING_IOC,
    getattr(mt5, "ORDER_FILLING_RETURN", mt5.ORDER_FILLING_IOC),
    getattr(mt5, "ORDER_FILLING_FOK", mt5.ORDER_FILLING_IOC),
]


def to_jsonable(obj):
    if obj is None:
        return None
    if hasattr(obj, '_asdict'):
        return {k: to_jsonable(v) for k, v in obj._asdict().items()}
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    return obj


def fail(msg, **extra):
    out = {"ok": False, "error": msg, **extra}
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(1)


def ensure_init():
    if not mt5.initialize():
        fail("mt5 initialize failed", last_error=mt5.last_error())


def shutdown():
    try:
        mt5.shutdown()
    except Exception:
        pass


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
    min_vol = info.volume_min
    max_vol = info.volume_max
    vol = max(min_vol, min(max_vol, float(volume)))
    step_dec = Decimal(str(step))
    vol_dec = (Decimal(str(vol)) / step_dec).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_dec
    return float(vol_dec)


def get_tick(symbol):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        fail("tick unavailable", symbol=symbol, last_error=mt5.last_error())
    return tick


def account_status():
    acc = mt5.account_info()
    if acc is None:
        fail("account info unavailable", last_error=mt5.last_error())
    positions = mt5.positions_get()
    symbols = sorted({p.symbol for p in positions}) if positions else []
    print(json.dumps({
        "ok": True,
        "account": to_jsonable(acc),
        "positions_total": len(positions or []),
        "symbols_with_positions": symbols,
        "positions": to_jsonable(positions or []),
    }, ensure_ascii=False))


def calc_levels(info, side, price, sl_points, tp_points):
    point = info.point
    digits = info.digits
    sl = 0.0
    tp = 0.0
    if side == "BUY":
        if sl_points > 0:
            sl = round(price - sl_points * point, digits)
        if tp_points > 0:
            tp = round(price + tp_points * point, digits)
    else:
        if sl_points > 0:
            sl = round(price + sl_points * point, digits)
        if tp_points > 0:
            tp = round(price - tp_points * point, digits)
    return sl, tp


def build_request(symbol, side, lot, sl_points=0, tp_points=0, comment="Hermes direct", filling=None, position=None, include_stops=True):
    info = symbol_info(symbol)
    tick = get_tick(symbol)
    if side == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask
    elif side == "SELL":
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
    else:
        fail("side must be BUY or SELL", side=side)

    sl = tp = 0.0
    if include_stops:
        sl, tp = calc_levels(info, side, price, sl_points, tp_points)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": normalize_volume(symbol, lot),
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": DEFAULT_DEVIATION,
        "magic": MAGIC,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling if filling is not None else mt5.ORDER_FILLING_IOC,
    }
    if position is not None:
        request["position"] = position
    return request


def validate_with_fallbacks(symbol, side, lot, sl_points, tp_points, comment, position=None):
    attempts = []
    seen = set()
    for include_stops in (True, False):
        for filling in FILLING_CANDIDATES:
            key = (include_stops, filling)
            if key in seen:
                continue
            seen.add(key)
            request = build_request(symbol, side, lot, sl_points, tp_points, comment, filling=filling, position=position, include_stops=include_stops)
            check = mt5.order_check(request)
            check_data = to_jsonable(check)
            attempts.append({
                "include_stops": include_stops,
                "filling": filling,
                "request": request,
                "check": check_data,
            })
            if check is not None and check.retcode == 0:
                return {
                    "ok": True,
                    "request": request,
                    "check": check_data,
                    "attempts": attempts,
                    "last_error": mt5.last_error(),
                }
    return {
        "ok": False,
        "error": "all order attempts failed validation",
        "attempts": attempts,
        "last_error": mt5.last_error(),
    }


def send_validated(request, attempts):
    result = mt5.order_send(request)
    return {
        "ok": result is not None and result.retcode == mt5.TRADE_RETCODE_DONE,
        "request": request,
        "check": attempts[-1]["check"] if attempts else None,
        "result": to_jsonable(result),
        "attempts": attempts,
        "last_error": mt5.last_error(),
    }


def modify_position_sltp(symbol, ticket, side, sl_points=0, tp_points=0):
    if sl_points <= 0 and tp_points <= 0:
        return {"ok": True, "modified": False, "reason": "no stops requested"}
    info = symbol_info(symbol)
    tick = get_tick(symbol)
    price = tick.bid if side == "BUY" else tick.ask
    sl, tp = calc_levels(info, side, price, sl_points, tp_points)
    request = build_modify_position_price_request(mt5, position=type("P", (), {"ticket": ticket})(), symbol=symbol, sl_price=sl, tp_price=tp)
    result = mt5.order_send(request)
    return {
        "ok": result is not None and result.retcode == mt5.TRADE_RETCODE_DONE,
        "request": request,
        "result": to_jsonable(result),
        "last_error": mt5.last_error(),
    }


def build_partial_close_request(mt5_module, position, tick, normalized_volume):
    close_type = mt5_module.ORDER_TYPE_SELL if int(position.type) == mt5_module.POSITION_TYPE_BUY else mt5_module.ORDER_TYPE_BUY
    close_price = float(tick.bid if int(position.type) == mt5_module.POSITION_TYPE_BUY else tick.ask)
    return {
        "action": mt5_module.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": float(normalized_volume),
        "type": close_type,
        "position": int(position.ticket),
        "price": close_price,
        "deviation": DEFAULT_DEVIATION,
        "magic": MAGIC,
        "comment": "Hermes manage partial",
        "type_time": mt5_module.ORDER_TIME_GTC,
        "type_filling": mt5_module.ORDER_FILLING_IOC,
    }


def build_modify_position_price_request(mt5_module, position, symbol, sl_price=None, tp_price=None):
    request = {
        "action": mt5_module.TRADE_ACTION_SLTP,
        "symbol": symbol,
        "position": int(position.ticket),
        "magic": MAGIC,
    }
    request["sl"] = 0.0 if sl_price is None else float(sl_price)
    request["tp"] = 0.0 if tp_price is None else float(tp_price)
    return request


def execute_partial_close(position, close_volume):
    tick = get_tick(position.symbol)
    normalized = normalize_volume(position.symbol, close_volume)
    if normalized <= 0:
        return {"ok": False, "error": "invalid_close_volume", "requested_volume": close_volume}
    request = build_partial_close_request(mt5, position=position, tick=tick, normalized_volume=normalized)
    result = mt5.order_send(request)
    return {
        "ok": result is not None and result.retcode == mt5.TRADE_RETCODE_DONE,
        "request": request,
        "result": to_jsonable(result),
        "last_error": mt5.last_error(),
    }


def execute_modify_position_prices(position, sl_price=None, tp_price=None):
    request = build_modify_position_price_request(mt5, position=position, symbol=position.symbol, sl_price=sl_price, tp_price=tp_price)
    result = mt5.order_send(request)
    return {
        "ok": result is not None and result.retcode == mt5.TRADE_RETCODE_DONE,
        "request": request,
        "result": to_jsonable(result),
        "last_error": mt5.last_error(),
    }


def execute_market_open(symbol, side, lot, sl_price=None, tp_price=None, comment="Hermes scale in"):
    info = symbol_info(symbol)
    tick = get_tick(symbol)
    if side == "BUY":
        price = float(tick.ask)
        order_type = mt5.ORDER_TYPE_BUY
    else:
        price = float(tick.bid)
        order_type = mt5.ORDER_TYPE_SELL
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": normalize_volume(symbol, lot),
        "type": order_type,
        "price": price,
        "sl": float(sl_price or 0.0),
        "tp": float(tp_price or 0.0),
        "deviation": DEFAULT_DEVIATION,
        "magic": MAGIC,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    return {
        "ok": result is not None and result.retcode == mt5.TRADE_RETCODE_DONE,
        "request": request,
        "result": to_jsonable(result),
        "last_error": mt5.last_error(),
    }


def open_trade(args):
    symbol = args[2]
    side = args[3].upper()
    lot = float(args[4])
    sl_points = int(args[5]) if len(args) > 5 else 0
    tp_points = int(args[6]) if len(args) > 6 else 0
    comment = args[7] if len(args) > 7 else "Hermes direct"
    validated = validate_with_fallbacks(symbol, side, lot, sl_points, tp_points, comment)
    if not validated.get("ok"):
        print(json.dumps(validated, ensure_ascii=False))
        return
    out = send_validated(validated["request"], validated["attempts"])
    if out.get("ok") and (out["request"].get("sl", 0.0) == 0.0 and out["request"].get("tp", 0.0) == 0.0) and (sl_points > 0 or tp_points > 0):
        positions = mt5.positions_get(symbol=symbol) or []
        target = None
        for p in positions:
            if p.magic == MAGIC:
                if side == "BUY" and p.type == mt5.POSITION_TYPE_BUY:
                    target = p
                elif side == "SELL" and p.type == mt5.POSITION_TYPE_SELL:
                    target = p
        if target is not None:
            out["post_open_sltp"] = modify_position_sltp(symbol, target.ticket, side, sl_points, tp_points)
    print(json.dumps(out, ensure_ascii=False))


def close_symbol(args):
    symbol = args[2]
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        print(json.dumps({"ok": True, "closed": 0, "symbol": symbol, "message": "no open positions"}, ensure_ascii=False))
        return
    out = []
    for p in positions:
        close_side = "SELL" if p.type == mt5.POSITION_TYPE_BUY else "BUY"
        validated = validate_with_fallbacks(p.symbol, close_side, p.volume, 0, 0, "Hermes direct close", position=p.ticket)
        if validated.get("ok"):
            result = send_validated(validated["request"], validated["attempts"])
        else:
            result = validated
        out.append({"ticket": p.ticket, "volume": p.volume, "result": result})
    print(json.dumps({"ok": all(x["result"].get("ok") for x in out), "closed": len(out), "symbol": symbol, "results": out}, ensure_ascii=False))


def build_pending_request(symbol, order_kind, entry_price, lot, sl_price=0.0, tp_price=0.0, comment="Hermes pending"):
    """Build a pending order request (buy_stop/sell_stop/buy_limit/sell_limit).

    order_kind: BUY_STOP, SELL_STOP, BUY_LIMIT, SELL_LIMIT
    entry_price: the price at which the pending order activates
    """
    info = symbol_info(symbol)
    digits = info.digits
    point = info.point

    type_map = {
        "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP,
        "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP,
        "BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT,
        "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
    }
    order_type = type_map.get(order_kind.upper())
    if order_type is None:
        fail(f"Unknown pending order kind: {order_kind}", valid=list(type_map.keys()))

    request = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": normalize_volume(symbol, lot),
        "type": order_type,
        "price": round(float(entry_price), digits),
        "sl": float(sl_price or 0.0),
        "tp": float(tp_price or 0.0),
        "deviation": DEFAULT_DEVIATION,
        "magic": MAGIC,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }
    return request


def place_pending_order(symbol, order_kind, entry_price, lot, sl_price=0.0, tp_price=0.0, comment="Hermes pending"):
    """Place a pending order on MT5."""
    request = build_pending_request(symbol, order_kind, entry_price, lot, sl_price, tp_price, comment)
    check = mt5.order_check(request)
    if check is not None and check.retcode != 0:
        return {"ok": False, "error": f"order_check retcode={check.retcode}", "request": request, "check": to_jsonable(check)}
    result = mt5.order_send(request)
    return {
        "ok": result is not None and result.retcode == mt5.TRADE_RETCODE_DONE,
        "request": request,
        "result": to_jsonable(result),
        "last_error": mt5.last_error(),
    }


def cancel_pending_order(ticket):
    """Cancel a pending order by ticket."""
    request = {
        "action": mt5.TRADE_ACTION_REMOVE,
        "order": int(ticket),
    }
    result = mt5.order_send(request)
    return {
        "ok": result is not None and result.retcode == mt5.TRADE_RETCODE_DONE,
        "request": request,
        "result": to_jsonable(result),
        "last_error": mt5.last_error(),
    }


def list_pending_orders(symbol=None):
    """List all pending orders, optionally filtered by symbol."""
    orders = mt5.orders_get(symbol=symbol) if symbol else mt5.orders_get()
    if orders is None:
        return {"ok": True, "orders": [], "count": 0}
    out = []
    for o in orders:
        type_map = {2: "BUY_LIMIT", 3: "SELL_LIMIT", 4: "BUY_STOP", 5: "SELL_STOP"}
        out.append({
            "ticket": o.ticket,
            "symbol": o.symbol,
            "type": type_map.get(o.type, str(o.type)),
            "volume": o.volume_current,
            "price_open": o.price_open,
            "sl": o.sl,
            "tp": o.tp,
            "comment": o.comment,
        })
    return {"ok": True, "orders": out, "count": len(out)}


def pending_order_cmd(args):
    """CLI: pending SYMBOL KIND PRICE LOT [SL_PRICE] [TP_PRICE] [COMMENT]"""
    if len(args) < 6:
        fail("usage: pending SYMBOL BUY_STOP|SELL_STOP|BUY_LIMIT|SELL_LIMIT PRICE LOT [SL_PRICE] [TP_PRICE] [COMMENT]")
    symbol = args[2]
    order_kind = args[3].upper()
    entry_price = float(args[4])
    lot = float(args[5])
    sl_price = float(args[6]) if len(args) > 6 and args[6] else 0.0
    tp_price = float(args[7]) if len(args) > 7 and args[7] else 0.0
    comment = args[8] if len(args) > 8 else "Hermes pending"
    out = place_pending_order(symbol, order_kind, entry_price, lot, sl_price, tp_price, comment)
    print(json.dumps(out, ensure_ascii=False))


def cancel_order_cmd(args):
    """CLI: cancel_order TICKET"""
    if len(args) < 3:
        fail("usage: cancel_order TICKET")
    ticket = int(args[2])
    out = cancel_pending_order(ticket)
    print(json.dumps(out, ensure_ascii=False))


def orders_cmd(args):
    """CLI: orders [SYMBOL]"""
    symbol = args[2] if len(args) > 2 else None
    out = list_pending_orders(symbol)
    print(json.dumps(out, ensure_ascii=False))


def order_check_only(args):
    symbol = args[2]
    side = args[3].upper()
    lot = float(args[4])
    sl_points = int(args[5]) if len(args) > 5 else 0
    tp_points = int(args[6]) if len(args) > 6 else 0
    out = validate_with_fallbacks(symbol, side, lot, sl_points, tp_points, "Hermes direct check")
    print(json.dumps(out, ensure_ascii=False))


def symbols_sample(args):
    symbols = mt5.symbols_get()
    names = [s.name for s in symbols[:80]] if symbols else []
    print(json.dumps({"ok": True, "symbols_total": len(symbols or []), "sample": names}, ensure_ascii=False))


def main(args):
    if len(args) < 2:
        fail("usage: status | open SYMBOL BUY|SELL LOT [SL_POINTS] [TP_POINTS] [COMMENT] | close SYMBOL | check SYMBOL BUY|SELL LOT [SL_POINTS] [TP_POINTS] | pending SYMBOL KIND PRICE LOT [SL_PRICE] [TP_PRICE] [COMMENT] | cancel_order TICKET | orders [SYMBOL] | symbols")
    ensure_init()
    try:
        cmd = args[1].lower()
        if cmd == "status":
            account_status()
        elif cmd == "open":
            open_trade(args)
        elif cmd == "close":
            close_symbol(args)
        elif cmd == "check":
            order_check_only(args)
        elif cmd == "pending":
            pending_order_cmd(args)
        elif cmd == "cancel_order":
            cancel_order_cmd(args)
        elif cmd == "orders":
            orders_cmd(args)
        elif cmd == "symbols":
            symbols_sample(args)
        else:
            fail("unknown command", command=cmd)
    finally:
        shutdown()


if __name__ == "__main__":
    main(sys.argv)
