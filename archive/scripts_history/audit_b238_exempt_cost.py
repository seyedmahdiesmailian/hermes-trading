"""b238 part 3 — measure the exemption's true cost.

The live trade was pullback_continuation, which is in RR_FLOOR_EXEMPT_STYLES,
so the RR floor was set to 0.0 and a 0.14R trade executed.

Question: how much of the lab's money rides on exempt styles, and what
happens if the floor applies to them?

Runs live-parity backtests on several windows and reports, per style:
  n, win rate, net pnl, mean realised RR, and net pnl of the trades the
  floor would have refused.
"""
import sys, json, collections
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import run_backtest

bc = BridgeClient()
EXEMPT = {"aggressive_value_entry", "pullback_continuation"}

agg = collections.defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0,
                                       "refused_n": 0, "refused_pnl": 0.0,
                                       "rrs": []})
for count in (500, 1000, 1500, 2000, 2500):
    r = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=count, min_rr=1.5)
    tl = r['trade_log']
    for t in tl:
        st = str(t.get('style') or '<none>')
        a = agg[st]
        a['n'] += 1
        a['pnl'] += float(t['pnl'])
        if float(t['pnl']) > 0:
            a['wins'] += 1
        # realised RR of the trade as it actually played out
        ent, ex = float(t['entry']), float(t['exit'])
        sl = float(t.get('orig_sl') or 0)
        risk = abs(ent - sl) if sl else 0
        if risk:
            a['rrs'].append(abs(ex - ent) / risk)
    print(f"window {count}: {len(tl)} trades, net {sum(float(x['pnl']) for x in tl):+.2f}")

print("\n=== per-style (all windows pooled) ===")
tot_all = tot_ref = 0.0
n_all = n_ref = 0
for st, a in sorted(agg.items(), key=lambda kv: -kv[1]['pnl']):
    wr = 100 * a['wins'] / a['n'] if a['n'] else 0
    mrr = sum(a['rrs']) / len(a['rrs']) if a['rrs'] else 0
    tag = ' [EXEMPT]' if st in EXEMPT else ''
    print(f"  {st:30s} n={a['n']:4d}  WR={wr:5.1f}%  net={a['pnl']:+8.2f}  meanRR={mrr:5.2f}{tag}")
    tot_all += a['pnl']; n_all += a['n']
    if st in EXEMPT:
        tot_ref += a['pnl']; n_ref += a['n']
print(f"\n  TOTAL n={n_all} net={tot_all:+.2f}")
print(f"  EXEMPT styles n={n_ref} ({100*n_ref/max(n_all,1):.0f}%) net={tot_ref:+.2f} "
      f"({100*tot_ref/max(tot_all,1):.0f}% of pnl)")

# What if the floor applied to the exempt styles too?
print("\n=== floor applied to exempt styles (min_rr=2.0) ===")
for count in (1000, 2000):
    r = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=count, min_rr=2.0)
    tl = r['trade_log']
    net = sum(float(x['pnl']) for x in tl)
    ex_n = sum(1 for x in tl if str(x.get('style') or '') in EXEMPT)
    print(f"  window {count}: n={len(tl)} net={net:+.2f} exempt_entries={ex_n}")
