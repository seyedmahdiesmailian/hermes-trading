"""b239 part 4 — where inside the long zone should the entry fire?

The live trades entered at 4151.67 and 4154.10, near the TOP of the long
zone (4124.81-4155.77), with tp_levels[0] == long_entry_high == 4155.77.
So the "target" was the zone's own ceiling — a 1.67-4.10 dollar move.

This is not a tuning question, it is the entry geometry itself. Measure on
the live-parity funnel: what happens to trades entered in the TOP third of
the zone vs the BOTTOM third? If the top is systematically bad, the entry
rule needs a location condition, not just a trigger.
"""
import sys, json, collections
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import run_backtest

bc = BridgeClient()

buckets = collections.defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0, "rrs": []})
for count in (1000, 2000, 3000):
    r = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=count, min_rr=1.5)
    for t in r['trade_log']:
        ent, sl = float(t['entry']), float(t.get('orig_sl') or 0)
        tp = float(t.get('exit') or 0)
        if not sl or not tp:
            continue
        risk = abs(ent - sl)
        if risk <= 0:
            continue
        rr = abs(tp - ent) / risk
        # bucket by risk taken in dollars — a proxy for how deep in the zone
        for lo, hi, name in ((0, 8, 'tight <$8'), (8, 15, 'mid $8-15'),
                             (15, 999, 'wide >$15')):
            if lo <= risk < hi:
                b = buckets[name]
                b['n'] += 1
                b['pnl'] += float(t['pnl'])
                if float(t['pnl']) > 0:
                    b['wins'] += 1
                b['rrs'].append(rr)

print("=== entry risk vs outcome (all windows pooled) ===")
for name in ('tight <$8', 'mid $8-15', 'wide >$15'):
    b = buckets.get(name)
    if not b or not b['n']:
        continue
    wr = 100 * b['wins'] / b['n']
    mrr = sum(b['rrs']) / len(b['rrs'])
    print(f"  {name:12s} n={b['n']:4d}  WR={wr:5.1f}%  net={b['pnl']:+8.2f}  realisedR={mrr:5.2f}")

# ── the structural question: is tp_levels[0] == the entry-zone ceiling? ──
print("\n=== structural check: does tp_levels[0] sit at the zone ceiling? ===")
from engines.backtest_real import fetch_all_ohlc
from engines.context import build_plan_context
m5 = fetch_all_ohlc(bc, 'XAUUSD', 'M5', 400)
h1 = fetch_all_ohlc(bc, 'XAUUSD', 'H1', 200)
h4 = fetch_all_ohlc(bc, 'XAUUSD', 'H4', 200)
for session in ('asia', 'london', 'newyork'):
    ctx = build_plan_context(m5[-120:], h1[-80:], h4[-80:], session)
    z, ex = ctx['zones'], ctx.get('execution') or {}
    bias = ctx['bias']
    tps = ex.get('tp_levels') or []
    if bias == 'bullish' and tps:
        print(f"  {session:9s} bias={bias:8s} long_zone={z['long_entry_low']}-{z['long_entry_high']}"
              f"  tp1={tps[0]}  ceiling_dist={abs(z['long_entry_high']-tps[0]):.2f}")
    elif bias == 'bearish' and tps:
        print(f"  {session:9s} bias={bias:8s} short_zone={z['short_entry_low']}-{z['short_entry_high']}"
              f"  tp1={tps[0]}  floor_dist={abs(z['short_entry_low']-tps[0]):.2f}")
    else:
        print(f"  {session:9s} bias={bias:8s} regime={ctx.get('quality',{}).get('regime')}")
