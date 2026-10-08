"""b236 A/B — how much should the H1 structure call weigh in the SMC bias?

The fix is conceptually right (the trend frame should win a conflict) but
the first attempt cost ~72$ on the 5000-bar sample. That may be noise, or
the weight may simply be too high. Sweep the weight across disjoint windows
and let the data settle it.

H1_STRUCTURE_WEIGHTS is a module constant, so we mutate it in place and
re-run the real engine at each setting. No source edits, no rebuilds.
"""
import sys, json, os, importlib
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
import engines.smc as smc
from engines.backtest_real import run_backtest

bc = BridgeClient()
W = 5                     # disjoint 1000-bar windows
SETTINGS = [0.0, 1.5, 2.5, 4.0, 5.0]
rows = {w: [] for w in SETTINGS}

for wgt in SETTINGS:
    smc.H1_STRUCTURE_WEIGHTS = {"bos": wgt, "choch": round(wgt * 0.625, 2)}
    t = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=5000,
                     min_rr=1.5)['trade_log']
    per_w = []
    for w in range(W):
        sl = [x for x in t if w*1000 <= x['entry_index'] < (w+1)*1000]
        per_w.append(sum(float(x['pnl']) for x in sl))
    rows[wgt] = per_w
    tot = sum(per_w)
    wr = sum(1 for x in t if float(x['pnl']) > 0)
    print(f"  H1 bos weight={wgt:<5} total {tot:+9.2f}  trades {len(t):>3}  "
          f"WR {wr/max(1,len(t))*100:>3.0f}%  worst {min(per_w):+8.2f}")

print("\n  per window:")
for w in range(W):
    print(f"    W{w+1}: " + "  ".join(f"{wgt}={rows[wgt][w]:+8.2f}" for wgt in SETTINGS))

# how often does each weight beat weight 0 (the H1-off baseline)?
print()
for wgt in SETTINGS:
    if wgt == 0.0:
        continue
    beats = sum(1 for w in range(W) if rows[wgt][w] > rows[0.0][w])
    tot = sum(rows[wgt])
    print(f"  weight {wgt}: beats 0.0 on {beats}/{W} windows, total {tot:+.2f} "
          f"(delta {tot - sum(rows[0.0]):+.2f})")

os.makedirs('data/backtest', exist_ok=True)
json.dump({str(k): v for k, v in rows.items()},
          open('data/backtest/b236_h1_weight.json', 'w'), indent=1)
print("\n  saved data/backtest/b236_h1_weight.json")
