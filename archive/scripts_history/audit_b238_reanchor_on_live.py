"""b238 part 6 — what does reanchor actually DO to a live pullback blueprint?

The comment at plan.py:357-359 says reanchor was tried before and discarded
because it "discarded the 3-level plan and fabricated a 1.5R scalp."
But the live geometry it protects is:
    entry 4154.10  sl 4123.51 ($30.59)  tp 4155.77 ($1.67)  = 0.05R
That is not a "3-level plan" surviving — that is a guaranteed-lose trade.

Feed the ACTUAL live plan geometry through _reanchor_blueprint and show
exactly what it produces, so the decision is on evidence not on a comment
from a version of the code where the zones were different.
"""
import sys, json
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from engines.plan import build_trade_blueprint, _reanchor_blueprint, _plan_atr

for name, pf, entry in [
    ("ticket 111570069 (06:20)", 'data/xau_plan/plan_history/20261005_062002_xau-cc1480bb.json', 4151.67),
    ("ticket 111572408 (06:30)", 'data/xau_plan/plan_history/20261005_063002_xau-eac6936b.json', 4154.10),
]:
    plan = json.load(open(pf))
    bp = build_trade_blueprint(plan, price=entry, trigger_ok=True)
    risk = abs(entry - float(bp['sl']))
    rew = abs(float(bp['tp']) - entry)
    print(f"--- {name}")
    print(f"  RAW : sl={bp['sl']} (${risk:.2f})  tp={bp['tp']} (${rew:.2f})  "
          f"RR={rew/risk:.2f}  tp_levels={bp.get('tp_levels')}")

    atr = _plan_atr(plan)
    ra = _reanchor_blueprint(bp, entry, atr)
    if ra.get('blocked'):
        print(f"  ANCH: BLOCKED ({ra.get('blocked_reason') or 'geometry'})")
        continue
    r2 = abs(entry - float(ra['sl']))
    w2 = abs(float(ra['tp']) - entry)
    print(f"  ANCH: sl={ra['sl']} (${r2:.2f})  tp={ra['tp']} (${w2:.2f})  "
          f"RR={w2/r2:.2f}  tp_levels={ra.get('tp_levels')}  "
          f"tp_shares={ra.get('tp_shares')}  reanchored={ra.get('reanchored')}")
    print(f"        ATR used: {atr:.2f}")
