"""b239 part 14 — A/B: raise MIN_SETUP_GRADE to A for aggressive_discount_entry.

Disjoint-window census (part 13):
  aggressive_discount_entry  B: 34 trades, -42.4  (negative in 3 of 5 chunks)
  aggressive_discount_entry  A:  5 trades, +17.7
  aggressive_value_entry     B: 20 trades, +141.2  (best cell)
So the drag is concentrated in ONE style at ONE grade. Killing the style
would also kill its A-grade profit; raising the floor to A for this style
alone keeps the good trades and drops the bad ones.

This is a tightening rule: it can only ever SKIP a trade the current
system would have taken. Run the funnel twice on identical data and check
the removed trades were actually losers.
"""
import sys, json
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import run_backtest
from engines import orchestrator as O
from engines.plan import setup_grade

bc = BridgeClient()
_orig_decide = O.decide_execution_action
STYLE_FLOOR = {'aggressive_discount_entry': 'A'}   # b239: see disjoint census


def _decide_style_aware(plan, price, trigger_ok, now, m5_ok=True):
    d = _orig_decide(plan, price=price, trigger_ok=trigger_ok, now=now, m5_ok=m5_ok)
    if d.get('action') not in {'market_order', 'market_entry_now'}:
        return d
    style = d.get('execution_style')
    want = STYLE_FLOOR.get(style)
    if not want:
        return d
    grade = setup_grade(plan)
    if grade and grade > want:
        return {'action': 'no_trade', 'reason': f'style_grade_floor_{style}',
                'zone': d.get('zone'), 'at': d.get('at')}
    return d


def run_leg(fix):
    O.decide_execution_action = _decide_style_aware if fix else _orig_decide
    try:
        return run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=3000, min_rr=1.5)
    finally:
        O.decide_execution_action = _orig_decide


base = run_leg(False)
fix = run_leg(True)


def summary(label, res):
    tl = res['trade_log']
    net = sum(float(t.get('pnl') or 0) for t in tl)
    wins = sum(1 for t in tl if float(t.get('pnl') or 0) > 0)
    disc_b = [t for t in tl if t.get('style') == 'aggressive_discount_entry' and t.get('grade') == 'B']
    print(f"\n{label}\n  trades={len(tl)}  WR={100*wins/max(1,len(tl)):.1f}%  net={net:+.2f}"
          f"  disc_B_remaining={len(disc_b)}")
    return {'trades': len(tl), 'net': round(net, 2), 'disc_B': len(disc_b)}


sb = summary('BASE (grade B allowed)', base)
sf = summary('FIX (A-only for discount)', fix)
print(f"\nremoved {sb['disc_B']-sf['disc_B']} trades, net delta {sf['net']-sb['net']:+.2f}")
json.dump({'base': sb, 'fix': sf}, open('data/backtest/b239_discount_a_only.json', 'w'), indent=1)
print('saved data/backtest/b239_discount_a_only.json')
