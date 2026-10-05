"""b239 part 15 — validate the A-only discount floor on disjoint chunks.

Part 14 on the tail window: removing all grade-B aggressive_discount_entry
trades lifted net from +96.69 to +137.92 (+41.23) while halving trades
(39 -> 22). One window cannot license a gate.

Run both legs on five disjoint 1200-bar chunks. The question is not
"does it win on average" but "does it win in most windows without a
catastrophic loss anywhere". A rule that wins 3/5 with one big loss is
not the same as one that wins 5/5 small.
"""
import sys, json
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import fetch_all_ohlc, run_backtest
from engines import orchestrator as O
from engines.plan import setup_grade

bc = BridgeClient()
m5 = fetch_all_ohlc(bc, 'XAUUSD', 'M5', 6000)
h1 = fetch_all_ohlc(bc, 'XAUUSD', 'H1', 600)
h4 = fetch_all_ohlc(bc, 'XAUUSD', 'H4', 600)
n = len(m5)
CHUNK = 1200
nchunks = n // CHUNK

_orig = O.decide_execution_action
STYLE_FLOOR = {'aggressive_discount_entry': 'A'}


def _decide_style_aware(plan, price, trigger_ok, now, m5_ok=True):
    d = _orig(plan, price=price, trigger_ok=trigger_ok, now=now, m5_ok=m5_ok)
    if d.get('action') not in {'market_order', 'market_entry_now'}:
        return d
    want = STYLE_FLOOR.get(d.get('execution_style'))
    if not want:
        return d
    grade = setup_grade(plan)
    if grade and grade > want:
        return {'action': 'no_trade', 'reason': 'style_grade_floor',
                'zone': d.get('zone'), 'at': d.get('at')}
    return d


def run_leg(seg, fix):
    O.decide_execution_action = _decide_style_aware if fix else _orig
    try:
        return run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=len(seg),
                            data={'M5': seg, 'M15': seg, 'H1': h1, 'H4': h4}, min_rr=1.5)
    finally:
        O.decide_execution_action = _orig


rows = []
for c in range(nchunks):
    seg = m5[c * CHUNK:(c + 1) * CHUNK]
    if len(seg) < CHUNK:
        continue
    b = run_leg(seg, False)
    f = run_leg(seg, True)
    bn = sum(float(t.get('pnl') or 0) for t in b['trade_log'])
    fn = sum(float(t.get('pnl') or 0) for t in f['trade_log'])
    rows.append({'chunk': c, 'base_net': round(bn, 2), 'fix_net': round(fn, 2),
                 'delta': round(fn - bn, 2),
                 'base_trades': len(b['trade_log']), 'fix_trades': len(f['trade_log'])})
    print(f"chunk {c}: base={bn:+8.2f}/{len(b['trade_log'])}  fix={fn:+8.2f}/{len(f['trade_log'])}  delta={fn-bn:+7.2f}")

wins = sum(1 for r in rows if r['delta'] > 0)
print(f"\nwindows improved: {wins}/{len(rows)}")
print(f"mean delta: {sum(r['delta'] for r in rows)/max(1,len(rows)):+.2f}")
json.dump(rows, open('data/backtest/b239_discount_a_only_windows.json', 'w'), indent=1)
print('saved data/backtest/b239_discount_a_only_windows.json')
