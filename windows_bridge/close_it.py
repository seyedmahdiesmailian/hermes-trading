import MetaTrader5 as mt5
mt5.initialize()

positions = mt5.positions_get(symbol="XAUUSD")
print(f"Positions: {len(positions)}")

for p in positions:
    ticket = p.ticket
    print(f"Closing ticket {ticket}...")
    
    # Get symbol info
    symbol_info = mt5.symbol_info("XAUUSD")
    tick = mt5.symbol_info_tick("XAUUSD")
    
    print(f"  Type: {p.type} (0=BUY, 1=SELL)")
    print(f"  Volume: {p.volume}")
    print(f"  Current bid: {tick.bid}, ask: {tick.ask}")
    
    # Close BUY with SELL (at bid), close SELL with BUY (at ask)
    if p.type == 0:  # BUY position
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
        print(f"  Will SELL at bid={price}")
    else:  # SELL position
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask
        print(f"  Will BUY at ask={price}")
    
    # Try with minimal deviation
    for dev in [20, 50, 100, 200]:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": "XAUUSD",
            "volume": float(p.volume),
            "type": order_type,
            "position": ticket,
            "price": float(price),
            "deviation": dev,
            "magic": 1107,
            "comment": f"HERMES_CLOSE_DEV{dev}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        result = mt5.order_send(request)
        print(f"  Deviation {dev}: retcode={result.retcode}, comment={result.comment}")
        
        if result.retcode == 10009:
            print(f"  ✓ CLOSED!")
            break
        elif result.retcode == 10004:
            # Requote - try again with new price
            tick = mt5.symbol_info_tick("XAUUSD")
            if p.type == 0:
                price = tick.bid
            else:
                price = tick.ask
            print(f"  Requote, new price={price}")
    else:
        print(f"  ✗ All deviations failed")

mt5.shutdown()
