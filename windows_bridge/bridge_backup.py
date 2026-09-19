from flask import Flask, request, jsonify
import MetaTrader5 as mt5
from datetime import datetime

app = Flask(__name__)

def make_json(success, **kwargs):
    return jsonify({"ok": success, **kwargs})

@app.route("/")
def home():
    return make_json(True, status="Hermes MT5 Bridge", time=str(datetime.now()))

@app.route("/api/account")
def get_account():
    if not mt5.terminal_info():
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

if __name__ == "__main__":
    print("Hermes Bridge starting on port 5050")
    print("Connect to MT5...")
    if mt5.initialize():
        print("MT5 init OK")
    else:
        print("MT5 not available")
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)


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
    deals = mt5.history_deals_get(datetime.utcnow() - timedelta(days=days), datetime.utcnow())
    if deals is None:
        return make_json(False, error=str(mt5.last_error()))
    out = []
    for d in deals:
        if symbol and d.symbol != symbol:
            continue
        out.append({
            "ticket": int(d.ticket),
            "symbol": d.symbol,
            "type": "BUY" if d.type == 0 else "SELL",
            "volume": float(d.volume), "price": float(d.price),
            "profit": float(d.profit), "swap": float(d.swap),
            "commission": float(d.commission), "time": int(d.time),
            "comment": str(d.comment),
        })
    return make_json(True, count=len(out), data=out)



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
    deals = mt5.history_deals_get(datetime.utcnow() - timedelta(days=days), datetime.utcnow())
    if deals is None:
        return make_json(False, error=str(mt5.last_error()))
    out = []
    for d in deals:
        if symbol and d.symbol != symbol:
            continue
        out.append({
            "ticket": int(d.ticket),
            "symbol": d.symbol,
            "type": "BUY" if d.type == 0 else "SELL",
            "volume": float(d.volume), "price": float(d.price),
            "profit": float(d.profit), "swap": float(d.swap),
            "commission": float(d.commission), "time": int(d.time),
            "comment": str(d.comment),
        })
    return make_json(True, count=len(out), data=out)


