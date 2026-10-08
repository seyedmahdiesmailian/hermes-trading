import MetaTrader5 as mt5, time
ok = mt5.initialize(login=10382667, password='n&aD5G1k)S(8', server='CapitalxtendLLC-MU')
print('init+login:', ok, mt5.last_error())
time.sleep(5)
ai = mt5.account_info()
print('acct:', bool(ai), getattr(ai, 'login', None), getattr(ai, 'balance', None), getattr(ai, 'server', None))
ti = mt5.terminal_info()
print('term connected:', getattr(ti, 'connected', None), 'trade_allowed:', getattr(ti, 'trade_allowed', None))
mt5.shutdown()
