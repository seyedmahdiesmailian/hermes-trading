"""b239 part 13 — is aggressive_discount_entry a net drag, and is it stable?

Pooled funnel: aggressive_discount_entry B = 21 trades, -43.20 (the worst
cell); the same style at grade A = 3 trades, +46.96. That pattern says the
style is marginal and the grade carries it — but n=3 cannot license a rule.

Run it on disjoint 1200-bar chunks to see whether the drag is stable or a
single-window artifact. Report style x grade per chunk and pooled. If the
B-grade drag repeats in most chunks, raising MIN_SETUP_GRADE for this one
style (A only) is a tightening rule with real evidence behind it.
"""
import sys, json, collections
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import fetch_all_ohlc, run_backtest

bc = BridgeClient()
m5 = fetch_all_ohlc(bc, 'XAUUSD', 'M5', 6000)
h1 = fetch_all_ohlc(bc, 'XAUUSD', 'H1', 600)
h4 = fetch_all_ohlc(bc, 'XAUUSD', 'H4', 600)
n = len(m5)
CHUNK = 1200
nchunks = n // CHUNK
print(f'M5 bars={n} chunks={nchunks}')

agg = collections.defaultdict(lambda: collections.defaultdict(lambda: {'n': 0, 'pnl': 0.0}))

for c in range(nchunks):
    seg = m5[c * CHUNK:(c + 1) * CHUNK]
    if len(seg) < CHUNK:
        continue
    r = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=len(seg),
                     data={'M5': seg, 'M15': seg, 'H1': h1, 'H4': h4}, min_rr=1.5)
    for t in r['trade_log']:
        k = (t.get('style'), t.get('grade'))
        b = agg[k][c]
        b['n'] += 1
        b['pnl'] += float(t.get('pnl') or 0)
    print(f'chunk {c}: {len(r["trade_log"])} trades')

print('\n=== style x grade per disjoint chunk (net/n) ===')
for k in sorted(agg, key=lambda k: -sum(v['pnl'] for v in agg[k].values())):
    cells, tn, tp = [], 0, 0.0
    for c in range(nchunks):
        b = agg[k][c]
        tn += b['n']; tp += b['pnl']
        cells.append(f"{b['pnl']:+6.1f}/{b['n']}" if b['n'] else '-')
    print(f"{str(k):50s} " + " ".join(f"{c:>10s}" for c in cells) + f"  pooled {tp:+7.1f}/{tn}")

json.dump({str(k): {str(c): dict(agg[k][c]) for c in range(nchunks)} for k in agg},
          open('data/backtest/b239_style_grade_stability.json', 'w'), indent=1)
print('\nsaved data/backtest/b239_style_grade_stability.json')
