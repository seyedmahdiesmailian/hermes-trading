"""b238 part 4 — does reanchor reach pullback_continuation?

build_trade_blueprint (plan.py:264) emits raw structural geometry:
  entry = market price,  sl = plan invalidation,  tp = tp_levels[0].
For an in-zone pullback entry the structural stop is the WHOLE zone's
invalidation ($28 away) and tp_levels[0] is the zone boundary ($4 away),
so the blueprint is a 0.14R trade before any gate sees it.

_reanchor_blueprint exists to fix exactly this, but who calls it, and for
which styles? This audit traces the call sites and measures, over the
live-parity funnel, what geometry pullback_continuation actually carries
when the executor sees it.
"""
import sys, json, collections
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import run_backtest

bc = BridgeClient()

# 1. who calls _reanchor_blueprint?
import subprocess
out = subprocess.run(['grep', '-rn', '_reanchor_blueprint(', '--include=*.py', '.'],
                     capture_output=True, text=True).stdout
print("=== _reanchor_blueprint call sites ===")
print('\n'.join(l for l in out.splitlines()
                if 'def _reanchor' not in l and './tests/' not in l))

# 2. geometry at the executor's gate, per style
print("\n=== geometry at the gate (live-parity, min_rr=1.5) ===")
agg = collections.defaultdict(lambda: {"n": 0, "rrs": [], "sl_d": [], "tp_d": []})
for count in (1000, 2000, 3000):
    r = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=count, min_rr=1.5)
    for t in r['trade_log']:
        st = str(t.get('style') or '<none>')
        a = agg[st]; a['n'] += 1
        ent = float(t['entry']); sl = float(t.get('orig_sl') or 0)
        if sl:
            a['sl_d'].append(abs(ent - sl))
            a['tp_d'].append(abs(float(t['exit']) - ent))
            a['rrs'].append(abs(float(t['exit']) - ent) / abs(ent - sl))

for st, a in sorted(agg.items(), key=lambda kv: -kv[1]['n']):
    msl = sum(a['sl_d']) / len(a['sl_d']) if a['sl_d'] else 0
    mtp = sum(a['tp_d']) / len(a['tp_d']) if a['tp_d'] else 0
    mrr = sum(a['rrs']) / len(a['rrs']) if a['rrs'] else 0
    print(f"  {st:28s} n={a['n']:4d}  meanSL=${msl:6.2f}  meanTPdist=${mtp:6.2f}  realisedR={mrr:5.2f}")
