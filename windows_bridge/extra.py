

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

