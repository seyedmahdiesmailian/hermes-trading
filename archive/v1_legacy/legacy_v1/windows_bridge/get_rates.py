import MetaTrader5 as mt5, json, sys
mt5.initialize()
rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M15, 0, 10)
data = []
for r in rates:
    data.append({"time":int(r[0]),"o":float(r[1]),"h":float(r[2]),"l":float(r[3]),"c":float(r[4])})
print(json.dumps({"ok":True,"count":len(data),"data":data[:3]}))
mt5.shutdown()
