"""
MT5 HTTP Bridge Server (Windows) — v2
Exposes MetaTrader5 via HTTP REST API.
Hermes Brain (Linux) connects via HTTP to control MT5.
"""
from flask import Flask, request, jsonify
import MetaTrader5 as mt5
import logging
from datetime import datetime

app = Flask(__name__)

# Logging
log_file = 'C:/Hermes_MT5_Bridge/mt5_http_server.log'
fh = logging.FileHandler(log_file, encoding='utf-8', errors='replace')
fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logging.getLogger().setLevel(logging.INFO)
logging.getLogger().addHandler(fh)
logging.getLogger().addHandler(logging.StreamHandler())
log = logging.getLogger(__name__)

TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1
}

# ─── Core Endpoints ───────────────────────────────────────────────────────────

@app.route('/')
def index():
    return jsonify({"ok": True, "status": "Hermes MT5 Bridge", "time": datetime.utcnow().isoformat()})

@app.route('/health')
def health():
    if mt5.terminal_info() is None:
        return jsonify({"ok": False, "error": "mt5_not_connected"}), 503
    return jsonify({"ok": True, "mt5_connected": True, "time": datetime.utcnow().isoformat()})

@app.route('/api/account')
def get_account():
    if not mt5.terminal_info():
        return jsonify({"ok": False, "error": "mt5_not_connected"}), 503
    info = mt5.account_info()
    if info is None:
        return jsonify({"ok": False, "error": str(mt5.last_error())}), 500
    return jsonify({
        "ok": True,
        "balance": float(info.balance),
        "equity": float(info.equity),
        "margin": float(info.margin),
        "margin_free": float(info.margin_free),
        "login": info.login,
        "server": info.server,
        "currency": info.currency,
    })

@app.route('/api/tick/<symbol>')
def get_tick(symbol):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return jsonify({"ok": False, "error": "symbol_not_found"}), 404
    return jsonify({
        "ok": True,
        "symbol": symbol,
        "ask": float(tick.ask),
        "bid": float(tick.bid),
        "last": float(tick.last),
        "volume": int(tick.volume),
        "time": int(tick.time),
    })

@app.route('/api/positions')
def get_positions():
    symbol = request.args.get('symbol')
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    if positions is None:
        return jsonify({"ok": False, "error": str(mt5.last_error())}), 500
    data = []
    for p in positions:
        data.append({
            "ticket": int(p.ticket),
            "symbol": p.symbol,
            "type": "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
            "volume": float(p.volume),
            "price_open": float(p.price_open),
            "sl": float(p.sl),
            "tp": float(p.tp),
            "price_current": float(p.price_current),
            "profit": float(p.profit),
            "swap": float(p.swap),
            "comment": p.comment,
            "time": int(p.time),
        })
    return jsonify({"ok": True, "data": data, "count": len(data)})

# ─── Historical OHLC (old endpoint, still used by Linux client) ────────────────

@app.route('/api/ohlc/<symbol>')
def get_ohlc(symbol):
    tf_str = request.args.get('timeframe', 'H1')
    count = int(request.args.get('count', 100))
    tf = TIMEFRAME_MAP.get(tf_str, mt5.TIMEFRAME_H1)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None:
        return jsonify({"ok": False, "error": str(mt5.last_error())}), 500
    data = [{
        "time": int(r['time']),
        "open": float(r['open']),
        "high": float(r['high']),
        "low": float(r['low']),
        "close": float(r['close']),
        "tick_volume": int(r['tick_volume']),
    } for r in rates]
    return jsonify({"ok": True, "data": data, "timeframe": tf_str, "count": len(data)})

# ─── New standard rates endpoint ─────────────────────────────────────────────

@app.route('/api/rates/<symbol>')
def get_rates(symbol):
    tf_str = request.args.get('tf', request.args.get('timeframe', 'H1'))
    count = int(request.args.get('count', 100))
    tf = TIMEFRAME_MAP.get(tf_str, mt5.TIMEFRAME_H1)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None:
        return jsonify({"ok": False, "error": str(mt5.last_error())}), 500
    data = [{
        "time": int(r['time']),
        "open": float(r['open']),
        "high": float(r['high']),
        "low": float(r['low']),
        "close": float(r['close']),
        "tick_volume": int(r['tick_volume']),
    } for r in rates]
    return jsonify({"ok": True, "data": data, "timeframe": tf_str, "count": len(data)})

# ─── History Deals ────────────────────────────────────────────────────────────

@app.route('/api/history/deals')
def get_history_deals():
    symbol = request.args.get('symbol')
    days = int(request.args.get('days', 7))
    from datetime import datetime, timedelta
    from_date = datetime.utcnow() - timedelta(days=days)
    deals = mt5.history_deals_get(from_date, datetime.utcnow())
    if deals is None:
        return jsonify({"ok": False, "error": str(mt5.last_error())}), 500
    data = []
    for d in deals:
        if symbol and d.symbol != symbol:
            continue
        data.append({
            "ticket": int(d.ticket),
            "order": int(d.order),
            "position_id": int(getattr(d, "position_id", 0) or 0),
            "entry": int(d.entry),          # 0=IN 1=OUT 2=INOUT
            "symbol": d.symbol,
            "type": "BUY" if d.type == mt5.ORDER_TYPE_BUY else "SELL",
            "volume": float(d.volume),
            "price": float(d.price),
            "profit": float(d.profit),
            "swap": float(d.swap),
            "commission": float(d.commission),
            "time": int(d.time),
            "comment": d.comment,
        })
    return jsonify({"ok": True, "data": data, "count": len(data)})

# ─── Trading Endpoints ────────────────────────────────────────────────────────

@app.route('/api/order', methods=['POST'])
def send_order():
    req = request.json or {}
    symbol = req.get('symbol', 'XAUUSD')
    direction = req.get('type', 'BUY').upper()
    volume = float(req.get('volume', 0.01))
    sl = float(req['sl']) if req.get('sl') is not None else 0.0
    tp = float(req['tp']) if req.get('tp') is not None else 0.0
    comment = req.get('comment', 'Hermes')
    deviation = int(req.get('deviation', 10))

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return jsonify({"ok": False, "error": "symbol_tick_unavailable"}), 400

    price = tick.ask if direction == 'BUY' else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if direction == 'BUY' else mt5.ORDER_TYPE_SELL

    request_dict = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "deviation": deviation,
        "magic": req.get('magic', 20260901),
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    if sl > 0:
        request_dict["sl"] = sl
    if tp > 0:
        request_dict["tp"] = tp

    result = mt5.order_send(request_dict)
    if result is None:
        return jsonify({"ok": False, "error": str(mt5.last_error())}), 500
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return jsonify({"ok": False, "error": f"retcode_{result.retcode}", "retcode": result.retcode}), 400

    return jsonify({"ok": True, "ticket": int(result.order), "volume": float(result.volume),
                    "price": float(result.price), "retcode": result.retcode})

@app.route('/api/partial', methods=['POST'])
def partial_close():
    req = request.json or {}
    ticket = int(req['ticket'])
    percent = float(req.get('percent', 50))

    position = mt5.positions_get(ticket=ticket)
    if not position:
        return jsonify({"ok": False, "error": "position_not_found"}), 404
    pos = position[0]

    volume_to_close = round(float(pos.volume) * (percent / 100.0), 2)
    if volume_to_close < 0.01:
        return jsonify({"ok": False, "error": "volume_too_small"}), 400

    tick = mt5.symbol_info_tick(pos.symbol)
    price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
    close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY

    request_dict = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": ticket,
        "symbol": pos.symbol,
        "volume": volume_to_close,
        "type": close_type,
        "price": price,
        "deviation": 50,
        "type_filling": mt5.ORDER_FILLING_IOC,
        "comment": f"Hermes partial {int(percent)}%",
    }
    result = mt5.order_send(request_dict)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        return jsonify({"ok": False, "error": f"partial_close_failed_{result.retcode if result else 'none'}"}), 400
    return jsonify({"ok": True, "closed_volume": float(result.volume), "retcode": result.retcode})

@app.route('/api/modify', methods=['POST'])
def modify_position():
    req = request.json or {}
    ticket = int(req['ticket'])
    sl = float(req['sl']) if req.get('sl') is not None else None
    tp = float(req['tp']) if req.get('tp') is not None else None

    position = mt5.positions_get(ticket=ticket)
    if not position:
        return jsonify({"ok": False, "error": "position_not_found"}), 404
    pos = position[0]

    request_dict = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "symbol": pos.symbol,
        "sl": sl if sl is not None else pos.sl,
        "tp": tp if tp is not None else pos.tp,
    }
    result = mt5.order_send(request_dict)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        return jsonify({"ok": False, "error": f"modify_failed_{result.retcode if result else 'none'}"}), 400
    return jsonify({"ok": True, "ticket": ticket, "sl": request_dict['sl'], "tp": request_dict['tp']})

@app.route('/api/close', methods=['POST'])
def close_position():
    req = request.json or {}
    ticket = int(req['ticket'])
    position = mt5.positions_get(ticket=ticket)
    if not position:
        return jsonify({"ok": False, "error": "position_not_found"}), 404

    pos = position[0]
    tick = mt5.symbol_info_tick(pos.symbol)
    price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
    close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY

    request_dict = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": ticket,
        "symbol": pos.symbol,
        "volume": float(pos.volume),
        "type": close_type,
        "price": price,
        "deviation": 50,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request_dict)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        return jsonify({"ok": False, "error": f"close_failed_{result.retcode if result else 'none'}"}), 400
    return jsonify({"ok": True, "ticket": ticket, "price": float(result.price)})

# ─── Run ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    log.info("MT5 Bridge v2 starting on port 5050...")
    if not mt5.initialize():
        log.error("MT5 init failed: %s", mt5.last_error())
        exit(1)
    log.info("MT5 ready. Balance: %s", mt5.account_info().balance)
    try:
        app.run(host='0.0.0.0', port=5050, threaded=True)
    finally:
        mt5.shutdown()
        log.info("MT5 Bridge shut down.")