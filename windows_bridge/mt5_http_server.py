from flask import Flask, request, jsonify
import MetaTrader5 as mt5
import logging
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

@app.route("/")
def index():
    return jsonify({"status": "Hermes MT5 Bridge", "time": datetime.utcnow().isoformat()})

@app.route("/api/account")
def get_account():
    info = mt5.account_info()
    if info is None:
        return jsonify({"ok": False, "error": "not_connected"}), 500
    return jsonify({"ok": True, "data": {
        "login": info.login, "balance": float(info.balance),
        "equity": float(info.equity), "margin_level": float(info.margin_level) if info.margin_level else 0,
        "currency": info.currency, "name": info.name, "server": info.server,
    }})

@app.route("/api/positions")
def get_positions():
    symbol = request.args.get("symbol")
    if symbol:
        mt5.symbol_select(symbol, True)
        positions = mt5.positions_get(symbol=symbol)
    else:
        positions = mt5.positions_get()
    if not positions:
        return jsonify({"ok": True, "count": 0, "data": []})
    data = []
    for p in positions:
        data.append({
            "ticket": p.ticket, "type": p.type,
            "volume": float(p.volume), "price_open": float(p.price_open),
            "price_current": float(p.price_current),
            "sl": float(p.sl), "tp": float(p.tp),
            "profit": float(p.profit), "swap": float(p.swap),
        })
    return jsonify({"ok": True, "count": len(data), "data": data})

@app.route("/api/ohlc/<symbol>")
def get_ohlc(symbol):
    tf = request.args.get("timeframe", "M15")
    count = int(request.args.get("count", "50"))
    tf_map = {
        "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1,
    }
    mt5_tf = tf_map.get(tf, mt5.TIMEFRAME_M15)
    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, count)
    if rates is None:
        return jsonify({"ok": False, "error": "no_data"})
    data = []
    for r in rates:
        data.append({
            "time": int(r[0]), "open": float(r[1]), "high": float(r[2]),
            "low": float(r[3]), "close": float(r[4]),
            "tick_volume": int(r[5]), "spread": int(r[6]),
        })
    return jsonify({"ok": True, "symbol": symbol, "timeframe": tf, "count": len(data), "data": data})

@app.route("/api/tick/<symbol>")
def get_tick(symbol):
    mt5.symbol_select(symbol, True)
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return jsonify({"ok": False, "error": "no_tick"})
    return jsonify({"ok": True, "data": {
        "bid": float(tick.bid), "ask": float(tick.ask),
        "spread": round((tick.ask - tick.bid) * 100, 1)
    }})

@app.route("/api/close", methods=["POST"])
def close_position():
    req = request.get_json(force=True)
    ticket = int(req["ticket"])
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return jsonify({"ok": False, "error": "not_found"})
    p = pos[0]
    symbol = p.symbol
    mt5.symbol_select(symbol, True)
    tick = mt5.symbol_info_tick(symbol)
    if p.type == 0:
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
    else:
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask
    for dev in [20, 50, 100, 200]:
        request = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
            "volume": float(p.volume), "type": order_type,
            "position": ticket, "price": float(price),
            "deviation": dev, "magic": 1107,
            "comment": "HERMES", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result.retcode == 10009:
            return jsonify({"ok": True, "ticket": ticket, "price": float(result.price)})
        if result.retcode == 10004:
            tick = mt5.symbol_info_tick(symbol)
            price = tick.bid if p.type == 0 else tick.ask
    return jsonify({"ok": False, "error": "close_failed", "retcode": result.retcode})

@app.route("/api/order", methods=["POST"])
def send_order():
    req = request.get_json(force=True)
    action = req["action"]
    symbol = req["symbol"]
    volume = float(req["volume"])
    sl = float(req.get("sl", 0)) if req.get("sl") else 0
    tp = float(req.get("tp", 0)) if req.get("tp") else 0
    mt5.symbol_select(symbol, True)
    tick = mt5.symbol_info_tick(symbol)
    price = tick.ask if action == 0 else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if action == 0 else mt5.ORDER_TYPE_SELL
    result = mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": volume,
        "type": order_type, "price": float(price), "sl": sl, "tp": tp,
        "deviation": 50, "magic": 1107, "comment": "HERMES",
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
    })
    if result and result.retcode == 10009:
        return jsonify({"ok": True, "ticket": result.order, "price": float(result.price)})
    return jsonify({"ok": False, "error": result.comment if result else "unknown"})

@app.route("/api/modify", methods=["POST"])
def modify_position():
    req = request.get_json(force=True)
    ticket = int(req["ticket"])
    sl = req.get("sl")
    tp = req.get("tp")
    request_dict = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket}
    if sl is not None: request_dict["sl"] = float(sl)
    if tp is not None: request_dict["tp"] = float(tp)
    result = mt5.order_send(request_dict)
    if result and result.retcode == 10009:
        return jsonify({"ok": True, "ticket": ticket})
    return jsonify({"ok": False, "error": result.comment if result else "unknown", "retcode": result.retcode if result else None})

if __name__ == "__main__":
    mt5.initialize()
    app.run(host="0.0.0.0", port=5050)