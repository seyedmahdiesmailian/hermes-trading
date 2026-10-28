"""b239 part 11b — risk buckets on DISJOINT windows (methodology fix).

Part 11 was invalid: run_backtest(count=1500) always takes the most recent
1500 bars, so "four windows" were the same window four times. Fetch the M5
series once and slice it into genuinely disjoint chunks, then run the
funnel on each via the `data=` entry point.
"""
import sys, json, collections
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import fetch_all_ohlc, run_backtest

bc = BridgeClient()
m5 = fetch_all_ohlc(bc, 'XAUUSD', 'M5', 6000)
n = len(m5)
print('M5 bars available:', n)

CHUNK = 1200
nchunks = n // CHUNK
print('disjoint chunks:', nchunks)

# H1/H4 backdrops are used for HTF structure; one shared slice per chunk
# is wrong (they must cover the same calendar span as the M5 segment).
h1 = fetch_all_ohlc(bc, 'XAUUSD', 'H1', 600)
h4 = fetch_all_ohlc(bc, 'XAUUSD', 'H4', 600)

BUCKETS = ((0, 8, 'tight <$8'), (8, 15, 'mid $8-15'), (15, 1e9, 'wide >$15'))
agg = collections.defaultdict(lambda: collections.defaultdict(lambda: {'n': 0, 'wins': 0, 'pnl': 0.0}))

for c in range(nchunks):
    seg = m5[c * CHUNK:(c + 1) * CHUNK]
    if len(seg) < CHUNK:
        continue
    r = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=len(seg),
                     data={'M5': seg, 'M15': seg, 'H1': h1, 'H4': h4}, min_rr=1.5)
    tl = r['trade_log']
    for t in tl:
        ent, sl = float(t['entry']), float(t.get('orig_sl') or 0)
        if not sl or abs(ent - sl) <= 0:
            continue
        risk = abs(ent - sl)
        for lo, hi, name in BUCKETS:
            if lo <= risk < hi:
                b = agg[name][c]
                b['n'] += 1
                b['pnl'] += float(t.get('pnl') or 0)
                if float(t.get('pnl') or 0) > 0:
                    b['wins'] += 1
    print(f"chunk {c}: {len(tl)} trades")

print("\n=== risk bucket x disjoint chunk ===")
for _, _, name in BUCKETS:
    cells, totn, totw, totp = [], 0, 0, 0.0
    for c in range(nchunks):
        b = agg[name][c]
        totn += b['n']; totw += b['wins']; totp += b['pnl']
        cells.append(f"{b['pnl']:+6.1f}/{b['n']}")
    while len(cells) < 5:
        cells.append('-')
    wr = 100 * totw / max(1, totn)
    print(f"{name:12s} " + " ".join(f"{c:>10s}" for c in cells) + f"  | pooled WR={wr:4.1f}% net={totp:+7.1f} n={totn}")

json.dump({name: {str(c): dict(agg[name][c]) for c in range(nchunks)} for _, _, name in BUCKETS},
          open('data/backtest/b239_risk_bucket_disjoint.json', 'w'), indent=1)
print('\nsaved data/backtest/b239_risk_bucket_disjoint.json')
