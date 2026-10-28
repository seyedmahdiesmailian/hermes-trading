import MetaTrader5 as mt5
import sys
result = mt5.initialize()
print(f'init={result}', flush=True)
if result:
    term = mt5.terminal_info()
    print(f'terminal={term}', flush=True)
    acc = mt5.account_info()
    print(f'account={acc.login if acc else None}', flush=True)
    if not acc:
        print(f'err={mt5.last_error()}', flush=True)
else:
    print(f'init_err={mt5.last_error()}', flush=True)