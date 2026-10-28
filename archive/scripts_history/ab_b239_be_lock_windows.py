"""b239 part 19 — validate be_lock_r=0.75 on disjoint windows.

Tail window: be_lock_r 0.5 (shipped) -> 96.54, 0.75 -> 105.36, 1.0 -> 105.21.
Monotone improvement to 0.75, plateau at 1.0. The shape is real on one
window; the magnitude (+8.82) is one trade's worth at n=39.

CRITICAL CONTEXT: the LIVE system runs plain breakeven (be_lock_r=0.0)
per the b235 comment — "the live _breakeven_stop returns entry". So the
funnel at 0.5 is ALREADY MORE protective than live. Raising it to 0.75
widens that gap further. Any change here must be made in BOTH the funnel
default and trade_management.py, or the backtest stops modelling live.

Run 0.5 vs 0.75 on five disjoint 1200-bar chunks. Report the delta per
window. Only ship if it wins in >=4/5 — a 3/5 result on a single-knob R
conversion is not worth the live/funnel parity risk.
"""
import sys, json
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
print(f"M5 bars={n} chunks={nchunks}")

rows = []
for c in range(nchunks):
    seg = m5[c * CHUNK:(c + 1) * CHUNK]
    if len(seg) < CHUNK:
        continue
    r05 = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=len(seg),
                       data={'M5': seg, 'M15': seg, 'H1': h1, 'H4': h4}, min_rr=1.5,
                       be_lock_r=0.5)
    r075 = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=len(seg),
                        data={'M5': seg, 'M15': seg, 'H1': h1, 'H4': h4}, min_rr=1.5,
                        be_lock_r=0.75)
    n05 = sum(float(t.get('pnl') or 0) for t in r05['trade_log'])
    n075 = sum(float(t.get('pnl') or 0) for t in r075['trade_log'])
    rows.append({'chunk': c, 'be05': round(n05, 2), 'be075': round(n075, 2),
                 'delta': round(n075 - n05, 2),
                 't05': len(r05['trade_log']), 't075': len(r075['trade_log'])})
    print(f"chunk {c}: 0.5={n05:+8.2f}/{len(r05['trade_log'])}  "
          f"0.75={n075:+8.2f}/{len(r075['trade_log'])}  delta={n075-n05:+7.2f}")

wins = sum(1 for r in rows if r['delta'] > 0)
print(f"\nwindows improved: {wins}/{len(rows)}")
print(f"mean delta: {sum(r['delta'] for r in rows)/max(1,len(rows)):+.2f}")
json.dump(rows, open('data/backtest/b239_be_lock_windows.json', 'w'), indent=1)
print('saved data/backtest/b239_be_lock_windows.json')
