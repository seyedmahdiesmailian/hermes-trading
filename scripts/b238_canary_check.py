"""Verify the b238 reanchor patch actually engages.

The A/B delta was ~0.05, which is indistinguishable from noise. Two
possibilities: (a) the patch never fired, (b) pullback entries are rare in
the lab. This checks (a) directly by counting canary hits.
"""
import sys, json
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
import engines.plan as P
import engines.orchestrator as O
from engines.backtest_real import run_backtest

bc = BridgeClient()
_orig_buy, _orig_sell = P._buy_logic, P._sell_logic
canary = {"fired": 0}


def _patched_buy(plan, price, trigger_ok, now, m5_ok=True):
    zones = plan["zones"]
    if zones["long_entry_low"] <= price <= zones["long_entry_high"] and trigger_ok:
        d = _orig_buy(plan, price, trigger_ok, now, m5_ok)
        if d.get("execution_style") == "pullback_continuation":
            bp = d.get("blueprint") or {}
            if bp:
                canary["fired"] += 1
                d["blueprint"] = P._reanchor_blueprint(bp, price, P._plan_atr(plan))
        return d
    return _orig_buy(plan, price, trigger_ok, now, m5_ok)


P._buy_logic = _patched_buy
_saved = O.decide_execution_action
O.decide_execution_action = lambda *a, **k: P.decide_execution_action(*a, **k)
r = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=2500, min_rr=1.5)
O.decide_execution_action = _saved
P._buy_logic = _orig_buy
print("canary fired:", canary["fired"])
pc = [t for t in r['trade_log'] if t.get('style') == 'pullback_continuation']
print("pullback trades in log:", len(pc))
