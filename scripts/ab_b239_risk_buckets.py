"""b239 part 11 — risk-bucket stability across windows.

Pooled data showed wide entries (>$15 stop distance) losing money
(-10.77, WR 41.7%) while mid entries ($8-15) were the best (+200.30,
65.4%). That was pooled across 1000/2000/3000-bar windows.

Before writing a gate, check the effect is stable and not an artifact of
one window. Run four disjoint 1500-bar windows and report per bucket.
A bucket that only loses in one window is noise; one that loses in all
four is a real defect worth gating.
"""
import sys, json
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import run_backtest
import collections

bc = BridgeClient()
BUCKETS = ((0, 8, 'tight <$8'), (8, 15, 'mid $8-15'), (15, 1e9, 'wide >$15'))
agg = collections.defaultdict(lambda: collections.defaultdict(lambda: {'n': 0, 'wins': 0, 'pnl': 0.0}))

for w in range(4):
    r = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=1500, min_rr=1.5)
    for t in r['trade_log']:
        ent, sl = float(t['entry']), float(t.get('orig_sl') or 0)
        if not sl or abs(ent - sl) <= 0:
            continue
        risk = abs(ent - sl)
        for lo, hi, name in BUCKETS:
            if lo <= risk < hi:
                b = agg[name][w]
                b['n'] += 1
                b['pnl'] += float(t.get('pnl') or 0)
                if float(t.get('pnl') or 0) > 0:
                    b['wins'] += 1
    print(f"window {w} done ({len(r['trade_log'])} trades)")

print("\n=== risk bucket x window ===")
print(f"{'bucket':12s} {'w0':>12s} {'w1':>12s} {'w2':>12s} {'w3':>12s} {'pooled':>14s}")
for name, _, in ((n, 0) for n, _, _ in BUCKETS):
    pass
for _, _, name in BUCKETS:
    cells = []
    totn, totw, totp = 0, 0, 0.0
    for w in range(4):
        b = agg[name][w]
        totn += b['n']; totw += b['wins']; totp += b['pnl']
        cells.append(f"{b['pnl']:+7.1f}/{b['n']}")
    wr = 100 * totw / max(1, totn)
    print(f"{name:12s} {cells[0]:>12s} {cells[1]:>12s} {cells[2]:>12s} {cells[3]:>12s}  {wr:4.1f}% {totp:+8.1f}")

json.dump({name: {str(w): dict(agg[name][w]) for w in range(4)} for _, _, name in BUCKETS},
          open('data/backtest/b239_risk_bucket_stability.json', 'w'), indent=1)
print('\nsaved data/backtest/b239_risk_bucket_stability.json')
