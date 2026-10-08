from flask import Flask, request, jsonify
import MetaTrader5 as mt5
from datetime import datetime

app = Flask(__name__)

import os as _os
_BRIDGE_TOKEN = _os.environ.get('HERMES_BRIDGE_TOKEN', '')
@app.before_request
def _check_token():
    if _BRIDGE_TOKEN and request.endpoint != 'health':
        _h = request.headers.get('Authorization', '')
        if _h != 'Bearer ' + _BRIDGE_TOKEN:
            return jsonify({'ok': False, 'error': 'unauthorized'}), 401

def make_json(success, **kwargs):
    return jsonify({'ok': success, **kwargs})

@app.route("/api/account")
def get_account():
    if not mt5.terminal_info():
        mt5.initialize()
        mt5.initialize()
    a = mt5.account_info()
    if not a:
        return make_json(False, error="not_connected")
    return make_json(True, balance=float(a.balance), equity=float(a.equity),
                   margin_free=float(a.margin_free), login=int(a.login))

@app.route("/api/positions")
def get_positions():
    if not mt5.terminal_info():
        mt5.initialize()
    sym = request.args.get("symbol", "XAUUSD")
    pos = mt5.positions_get(symbol=sym)
    out = []
    if pos:
        for p in pos:
            out.append({
                "ticket": int(p.ticket),
                "type": int(p.type),
                "volume": float(p.volume),
                "open_price": float(p.price_open),
                "price_open": float(p.price_open),
                "time": int(p.time),
                "profit": float(p.profit),
                "sl": float(p.sl) if p.sl else None,
                "tp": float(p.tp) if p.tp else None,
            })
    return make_json(True, count=len(out), data=out)

@app.route("/api/tick/<symbol>")
def get_tick(symbol):
    if not mt5.terminal_info():
        mt5.initialize()
    t = mt5.symbol_info_tick(symbol)
    if not t:
        return make_json(False, error="no_tick")
    return make_json(True, bid=float(t.bid), ask=float(t.ask), time=int(t.time))

@app.route("/api/ohlc/<symbol>")
def get_ohlc(symbol):
    if not mt5.terminal_info():
        mt5.initialize()
    tf = request.args.get("timeframe", "M15")
    count = int(request.args.get("count", "50"))
    tf_map = {
        "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1
    }
    mt5_tf = tf_map.get(tf, mt5.TIMEFRAME_M15)
    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, count)
    if rates is None:
        return make_json(False, error="no_data")
    data = []
    for r in rates:
        data.append({
            "time": int(r[0]), "open": float(r[1]),
            "high": float(r[2]), "low": float(r[3]),
            "close": float(r[4]), "tick_volume": int(r[5])
        })
    return make_json(True, symbol=symbol, timeframe=tf, count=len(data), data=data)

@app.route("/api/order", methods=["POST"])
def send_order():
    data = request.get_json() or {}
    if not mt5.terminal_info():
        mt5.initialize()
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": data.get("symbol", "XAUUSD"),
        "volume": float(data.get("volume", 0.01)),
        "type": mt5.ORDER_TYPE_BUY if data.get("type") == "buy" else mt5.ORDER_TYPE_SELL,
        "price": data.get("price", 0.0),
        "deviation": 50,
        "magic": 778899,
        "comment": "Hermes",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    if data.get("sl"):
        req["sl"] = float(data["sl"])
    if data.get("tp"):
        req["tp"] = float(data["tp"])
    res = mt5.order_send(req)
    if res is None:
        return make_json(False, error=str(mt5.last_error()))
    return make_json(
        res.retcode == 10009,
        ticket=int(res.order) if res.order else 0,
        retcode=int(res.retcode),
        comment=str(res.comment)
    )

@app.route("/api/close", methods=["POST"])
def close_position():
    data = request.get_json() or {}
    if not mt5.terminal_info():
        mt5.initialize()
    ticket = int(data.get("ticket", 0))
    pos = mt5.positions_get(ticket=ticket)
    if not pos or len(pos) == 0:
        return make_json(False, error="position_not_found")
    p = pos[0]
    symbol = p.symbol
    t = mt5.symbol_info_tick(symbol)
    price = t.bid if p.type == 0 else t.ask
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(p.volume),
        "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
        "position": int(ticket),
        "price": float(price),
        "deviation": 50,
        "magic": 778899,
        "comment": "HermesClose",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    res = mt5.order_send(req)
    if res is None:
        return make_json(False, error=str(mt5.last_error()))
    return make_json(
        res.retcode == 10009,
        ticket=ticket,
        retcode=int(res.retcode),
        comment=str(res.comment)
    )


@app.route("/api/modify", methods=["POST"])
def modify_position():
    data = request.get_json() or {}
    if not mt5.terminal_info():
        mt5.initialize()
    ticket = int(data.get("ticket", 0))
    pos = mt5.positions_get(ticket=ticket)
    if not pos or len(pos) == 0:
        return make_json(False, error="position_not_found")
    p = pos[0]
    req = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": int(ticket),
        "symbol": p.symbol,
        "sl": float(data["sl"]) if data.get("sl") else float(p.sl),
        "tp": float(data["tp"]) if data.get("tp") else float(p.tp),
    }
    res = mt5.order_send(req)
    if res is None:
        return make_json(False, error=str(mt5.last_error()))
    return make_json(res.retcode == mt5.TRADE_RETCODE_DONE, retcode=int(res.retcode), sl=req["sl"], tp=req["tp"])

@app.route("/api/partial", methods=["POST"])
def partial_close():
    data = request.get_json() or {}
    if not mt5.terminal_info():
        mt5.initialize()
    ticket = int(data.get("ticket", 0))
    percent = float(data.get("percent", 50))
    pos = mt5.positions_get(ticket=ticket)
    if not pos or len(pos) == 0:
        return make_json(False, error="position_not_found")
    p = pos[0]
    si = mt5.symbol_info(p.symbol)
    step = si.volume_step if si and si.volume_step else 0.01
    close_vol = round(p.volume * percent / 100.0 / step) * step
    close_vol = max(step, min(round(close_vol, 2), p.volume - step))
    t = mt5.symbol_info_tick(p.symbol)
    price = t.bid if p.type == 0 else t.ask
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": p.symbol,
        "volume": float(close_vol),
        "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
        "position": int(ticket),
        "price": float(price),
        "deviation": 50,
        "magic": 778899,
        "comment": "HermesPartial",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    res = mt5.order_send(req)
    if res is None:
        return make_json(False, error=str(mt5.last_error()))
    return make_json(res.retcode == mt5.TRADE_RETCODE_DONE, retcode=int(res.retcode), closed_volume=float(close_vol))

@app.route("/api/history/deals")
def get_history_deals():
    if not mt5.terminal_info():
        mt5.initialize()
    symbol = request.args.get("symbol")
    days = int(request.args.get("days", 3))
    from datetime import timedelta
    deals = mt5.history_deals_get(datetime.utcnow() - timedelta(days=days), datetime.utcnow() + timedelta(days=1))
    if deals is None:
        return make_json(False, error=str(mt5.last_error()))
    out = []
    for d in deals:
        if symbol and d.symbol != symbol:
            continue
        out.append({
            "ticket": int(d.ticket),
            "order": int(d.order),
            "position_id": int(getattr(d, "position_id", 0) or 0),
            "entry": int(d.entry),
            "symbol": d.symbol,
            "type": "BUY" if d.type == 0 else "SELL",
            "volume": float(d.volume), "price": float(d.price),
            "profit": float(d.profit), "swap": float(d.swap),
            "commission": float(d.commission), "time": int(d.time),
            "comment": str(d.comment),
        })
    return make_json(True, count=len(out), data=out)






# ---- b70: pending (limit) orders for signal entries -------------------
import time as _time
PENDING_TYPES = {2: mt5.ORDER_TYPE_BUY_LIMIT, 3: mt5.ORDER_TYPE_SELL_LIMIT,
                 4: mt5.ORDER_TYPE_BUY_STOP, 5: mt5.ORDER_TYPE_SELL_STOP}


@app.route("/api/pending", methods=["POST"])
def place_pending():
    # NOTE: token auth is enforced globally by the @app.before_request hook;
    # do NOT call _check_token() here (it returns None when auth is OK).
    data = request.get_json(force=True)
    try:
        otype = PENDING_TYPES.get(int(data.get("type", 2)))
        if otype is None:
            return make_json(False, error="type must be 2=BUY_LIMIT 3=SELL_LIMIT")
        symbol = data.get("symbol", "XAUUSD")
        volume = float(data.get("volume", 0.01))
        price = float(data["price"])
        sl = float(data.get("sl", 0) or 0)
        tp = float(data.get("tp", 0) or 0)
        comment = str(data.get("comment", "hermes-sig"))[:27]
        if not mt5.symbol_select(symbol, True):
            return make_json(False, error="symbol select failed: " + symbol)
        req = {"action": mt5.TRADE_ACTION_PENDING, "symbol": symbol,
               "volume": volume, "type": otype, "price": price,
               "sl": sl, "tp": tp, "deviation": 20, "comment": comment,
               "magic": int(data.get("magic", 778899)),
               "type_filling": mt5.ORDER_FILLING_IOC}
        exp = float(data.get("expires_in_hours", 0) or 0)
        if exp > 0:
            req["expiration"] = mt5.ORDER_TIME_SPECIFIED
            req["time_expiration"] = int(_time.time() + exp * 3600)
        res = mt5.order_send(req)
        if res is None:
            return make_json(False, error="order_send None")
        if res.retcode != mt5.TRADE_RETCODE_DONE:
            return make_json(False, error="retcode=%s %s" % (res.retcode, res.comment))
        return make_json(True, order=res.order, price=float(price))
    except Exception as e:
        return make_json(False, error=str(e))


@app.route("/api/pending")
def list_pending():
    try:
        out = []
        for o in (mt5.orders_get() or []):
            out.append({"ticket": int(o.ticket), "type": int(o.type),
                        "symbol": o.symbol, "volume": float(o.volume_current),
                        "price_open": float(o.price_open),
                        "sl": float(o.sl or 0), "tp": float(o.tp or 0),
                        "comment": str(o.comment or ""),
                        "magic": int(o.magic or 0)})
        return make_json(True, orders=out)
    except Exception as e:
        return make_json(False, error=str(e))


@app.route("/api/cancel", methods=["POST"])
def cancel_pending():
    data = request.get_json(force=True)
    try:
        ticket = int(data["ticket"])
        if not mt5.orders_get(ticket=ticket):
            return make_json(True, cancelled=False, gone=True)
        res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": ticket})
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            return make_json(False, error="retcode=%s" % (getattr(res, "retcode", "?")))
        return make_json(True, cancelled=True)
    except Exception as e:
        return make_json(False, error=str(e))


@app.route("/health")
def health():
    if not mt5.terminal_info():
        mt5.initialize()
    a = mt5.account_info()
    return make_json(bool(a), balance=float(a.balance) if a else 0)

import logging
logging.basicConfig(
    filename=r"C:\Temp\bridge_err.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

if __name__ == "__main__":
    print("Hermes Bridge (waitress) starting on port 5050")
    logging.info("Bridge starting (waitress, 8 threads)")
    if not mt5.initialize():
        print("MT5 init FAILED:", mt5.last_error())
        logging.error(f"MT5 init FAILED: {mt5.last_error()}")
    else:
        print("MT5 init OK")
        logging.info("MT5 init OK")
    from waitress import serve
    serve(app, host="0.0.0.0", port=5050, threads=8, connection_limit=100,
          recv_bytes=65536, send_bytes=65536, channel_timeout=30)
