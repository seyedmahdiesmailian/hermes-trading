"""b238 part 5 (corrected) — A/B: reanchor pullback_continuation.

Root cause (plan.py:355-367): the in-zone pullback entry builds its
blueprint with build_trade_blueprint and returns it RAW — no
_reanchor_blueprint. Every other entry style reanchors (aggressive_premium
410, aggressive_value 425, sell twins at 505/547). So the pullback is the
ONE style that always carries raw structural geometry:
  sl = whole-zone invalidation, tp = tp_levels[0].

Live consequence (Oct 5 06:20, ticket 111570069): BUY 4151.81 with
sl=4123.59 ($28.22) and tp=4155.77 ($3.96) = 0.14R — risking $28 to make $4.

FIRST RUN WAS INVALID: orchestrator.py:7 does
`from engines.plan import decide_execution_action`, binding the name at
import time, so patching P.decide_execution_action was a silent no-op and
both legs ran the baseline. This version patches the bound name inside
engines.orchestrator (the module backtest_real actually calls through) and
VERIFIES the patch took effect before trusting any number.
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
_orig_buy = P._buy_logic
_orig_sell = P._sell_logic
_canary = {"fired": 0}


def _patched_buy(plan, price, trigger_ok, now, m5_ok=True):
    zones = plan["zones"]
    if zones["long_entry_low"] <= price <= zones["long_entry_high"] and trigger_ok:
        d = _orig_buy(plan, price, trigger_ok, now, m5_ok)
        if d.get("execution_style") == "pullback_continuation":
            bp = d.get("blueprint") or {}
            if bp:
                _canary["fired"] += 1
                d["blueprint"] = P._reanchor_blueprint(bp, price, P._plan_atr(plan))
        return d
    return _orig_buy(plan, price, trigger_ok, now, m5_ok)


def _patched_sell(plan, price, trigger_ok, now, m5_ok=True):
    zones = plan["zones"]
    if zones["short_entry_low"] <= price <= zones["short_entry_high"] and trigger_ok:
        d = _orig_sell(plan, price, trigger_ok, now, m5_ok)
        if d.get("execution_style") == "pullback_continuation":
            bp = d.get("blueprint") or {}
            if bp:
                _canary["fired"] += 1
                d["blueprint"] = P._reanchor_blueprint(bp, price, P._plan_atr(plan))
        return d
    return _orig_sell(plan, price, trigger_ok, now, m5_ok)


def _wrap_decide(orig):
    def _d(plan, price, trigger_ok, now, m5_ok=True):
        return orig(plan, price, trigger_ok, now, m5_ok)
    return _d


results = {"baseline": [], "reanchored": []}
for count in (500, 1000, 1500, 2000, 2500):
    # BASELINE
    P._buy_logic, P._sell_logic = _orig_buy, _orig_sell
    base = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=count, min_rr=1.5)

    # FIX — patch the names orchestrator's own namespace references resolve to.
    P._buy_logic, P._sell_logic = _patched_buy, _patched_sell
    _saved = O.decide_execution_action
    O.decide_execution_action = _wrap_decide(P.decide_execution_action)
    fix = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=count, min_rr=1.5)
    O.decide_execution_action = _saved
    P._buy_logic, P._sell_logic = _orig_buy, _orig_sell

    b, f = base['trade_log'], fix['trade_log']
    bn = sum(float(x['pnl']) for x in b); fn = sum(float(x['pnl']) for x in f)
    bpc = [x for x in b if x.get('style') == 'pullback_continuation']
    fpc = [x for x in f if x.get('style') == 'pullback_continuation']
    results["baseline"].append([count, len(b), round(bn, 2)])
    results["reanchored"].append([count, len(f), round(fn, 2)])
    print(f"window {count:5d} | BASE n={len(b):3d} net={bn:+8.2f} (pb {len(bpc)})"
          f" | FIX n={len(f):3d} net={fn:+8.2f} (pb {len(fpc)})")

print(f"\ncanary: reanchor applied to pullback {_canary['fired']} times")
bn_all = sum(x[2] for x in results["baseline"]); fn_all = sum(x[2] for x in results["reanchored"])
print(f"SUM  base={bn_all:+.2f}  fix={fn_all:+.2f}  delta={fn_all-bn_all:+.2f}")
json.dump(results, open('data/backtest/b238_reanchor_ab.json', 'w'), indent=1)
