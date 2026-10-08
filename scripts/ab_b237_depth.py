"""b237: how many M5 bars should the SMC engine see?

Live fetches 120. A rolling scan (scripts/ab_depth3.py) measured:
    depth 120: 39% bias flips, 28% neutral
    depth 250: 26% bias flips, 14% neutral   <- most stable
    depth 500: 31% bias flips, 26% neutral

Stability alone is not edge. This runs the REAL backtest engine with the
window depth as the only variable, on 5 disjoint 1000-bar windows, and
reports PnL + the trade count. The live rule is 120.
"""
import sys, json, os
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import run_backtest

bc = BridgeClient()
W = 5
DEPTHS = [120, 250, 500]
rows = {d: [] for d in DEPTHS}

for d in DEPTHS:
    t = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=5000,
                     min_rr=1.5, smc_depth=d)['trade_log']
    for w in range(W):
        sl = [x for x in t if w*1000 <= x['entry_index'] < (w+1)*1000]
        rows[d].append(sum(float(x['pnl']) for x in sl))
    tot = sum(rows[d])
    wr = sum(1 for x in t if float(x['pnl']) > 0)
    print(f"  depth {d:>4}: {len(t):>3} trades  total {tot:+9.2f}  "
          f"WR {wr/max(1,len(t))*100:>3.0f}%  worst {min(rows[d]):+8.2f}")

print("\n  per window:")
for w in range(W):
    print(f"    W{w+1}: " + "  ".join(f"d{d}={rows[d][w]:+8.2f}" for d in DEPTHS))

print()
for d in DEPTHS:
    if d == 120:
        continue
    beats = sum(1 for w in range(W) if rows[d][w] > rows[120][w])
    print(f"  depth {d} beats 120 on {beats}/{W} windows "
          f"(total delta {sum(rows[d]) - sum(rows[120]):+.2f})")

os.makedirs('data/backtest', exist_ok=True)
json.dump({str(k): v for k, v in rows.items()},
          open('data/backtest/b237_depth.json', 'w'), indent=1)
print("\n  saved data/backtest/b237_depth.json")
