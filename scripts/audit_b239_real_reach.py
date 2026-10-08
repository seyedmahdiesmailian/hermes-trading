"""b239 part 2 — the real reachability of ICT detectors.

Part 1 was too coarse: it flagged everything but smc_analyse as ORPHAN
because the detectors are called INSIDE smc_analyse, not by the entry
decision directly. The right question is: does the output of each detector
reach a field that decide_execution_action / evaluate_proposal reads?

smc_analyse computes a dict. Only fields propagating into
plan['quality']['smc_*'] or the bias/signal actually move the entry.
This script instruments smc_analyse to record which detector outputs
survive into the returned dict, then checks each returned field against
the fields the entry decision reads.
"""
import sys, json, ast, pathlib
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')

REPO = pathlib.Path('.')

# ── what fields does the entry decision actually READ? ──
plan_src = (REPO / 'engines/plan.py').read_text()
orch_src = (REPO / 'engines/orchestrator.py').read_text()
ae_src = (REPO / 'engines/auto_executor.py').read_text()
rt_src = (REPO / 'hermes_runtime.py').read_text()
tm_src = (REPO / 'engines/trade_management.py').read_text()

# find every string literal used as a dict key in the decision path
READERS = {
    'plan.py': plan_src, 'orchestrator.py': orch_src,
    'auto_executor.py': ae_src, 'hermes_runtime.py': rt_src,
    'trade_management.py': tm_src,
}

# what does smc_analyse RETURN? run it and capture keys at each stage
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.smc import smc_analyse
from engines.backtest_real import fetch_all_ohlc

bc = BridgeClient()
rows = fetch_all_ohlc(bc, 'XAUUSD', 'M15', 400)
print('candles:', len(rows))

from datetime import datetime, timezone
res = smc_analyse(rows[-250:], now=datetime.now(timezone.utc))
print('\n=== top-level fields smc_analyse returns ===')
for k in sorted(res.keys()):
    v = res[k]
    tag = type(v).__name__
    if isinstance(v, (str, int, float, bool)):
        print(f'  {k:28s} = {v!r:24s} ({tag})')
    elif isinstance(v, dict):
        print(f'  {k:28s} = <dict {len(v)} keys>')
    elif isinstance(v, list):
        print(f'  {k:28s} = <list {len(v)}>')
    else:
        print(f'  {k:28s} = <{tag}>')

# ── which of these reach the entry decision? ──
def _reads(src, token):
    return token in src

# the entry path reads plan['quality'] which is built from the merged context.
# trace: smc_analyse -> merge_smc_with_classic -> plan['quality'] -> decide
from engines.smc import merge_smc_with_classic
from engines.context import build_plan_context
h1 = fetch_all_ohlc(bc, 'XAUUSD', 'H1', 200)
h4 = fetch_all_ohlc(bc, 'XAUUSD', 'H4', 200)
ctx = build_plan_context(rows[-120:], h1[-80:], h4[-80:], 'london')
merged = merge_smc_with_classic(ctx, res)
q = merged.get('quality') or {}
print('\n=== plan["quality"] fields (what the entry decision sees) ===')
for k in sorted(q.keys()):
    v = q[k]
    if isinstance(v, (str, int, float, bool)):
        print(f'  {k:28s} = {v!r}')
    else:
        print(f'  {k:28s} = <{type(v).__name__}>')

print('\n=== smc_analyse fields LOST before the entry decision ===')
lost = set(res.keys()) - set(k for k in q.keys())
for k in sorted(lost):
    print(f'  LOST  {k}')
