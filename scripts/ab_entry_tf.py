#!/usr/bin/env python3
"""A/B: entry timeframe M5 (live today) vs M15 (candidate 4th TF).

Runs the EXACT live funnel (backtest_real.strategy_signal -> evaluate_monitor
_cycle) twice on the same H1/H4 history, only swapping the entry-bar stream.
Answers the professional-trader question before touching live code: does an
M15 entry lane add edge, or just fewer, later, redundant signals?

Usage: timeout 300 python3 scripts/ab_entry_tf.py [bars]
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from env_loader import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / '.env')
from bridge_client import BridgeClient
from engines.backtest_real import fetch_all_ohlc, run_backtest

bars = int(sys.argv[1]) if len(sys.argv) > 1 else 900
b = BridgeClient()

# Shared HTF context (identical for both arms)
h1 = fetch_all_ohlc(b, 'XAUUSD', 'H1', bars)
h4 = fetch_all_ohlc(b, 'XAUUSD', 'H4', bars)
m5 = fetch_all_ohlc(b, 'XAUUSD', 'M5', bars * 3)   # 3x bars = same wall-clock span
m15 = fetch_all_ohlc(b, 'XAUUSD', 'M15', bars)

def summarize(tag, res, span_hours):
    if not res.get('ok'):
        print(f"{tag}: FAILED {res.get('error')}"); return None
    t = res.get('trade_log', [])
    n = len(t)
    wins = sum(1 for x in t if x.get('pnl', 0) > 0)
    tot = sum(x.get('pnl', 0) for x in t)
    mean = tot / n if n else 0
    per_1000h = tot / span_hours * 1000 if span_hours else 0
    print(f"{tag}: bars={res.get('bars_tested')} trades={n} "
          f"WR={wins/n*100 if n else 0:.1f}% total={tot:+.2f}$ "
          f"mean={mean:+.2f}$ per1000h={per_1000h:+.1f}$")
    return res

# M5 arm: entry stream = M5 bars
r5 = run_backtest(b, timeframe='M5', count=bars*3, data={'M5': m5, 'H1': h1, 'H4': h4})
# M15 arm: entry stream = M15 bars (run_backtest reads data[timeframe])
r15 = run_backtest(b, timeframe='M15', count=bars, data={'M15': m15, 'H1': h1, 'H4': h4})

span5 = (m5[-1]['time'] - m5[0]['time']) / 3600 if len(m5) > 1 else 0
span15 = (m15[-1]['time'] - m15[0]['time']) / 3600 if len(m15) > 1 else 0
print(f"window: M5 {span5:.0f}h | M15 {span15:.0f}h")
summarize('M5 (live) ', r5, span5)
summarize('M15 (new) ', r15, span15)

# Overlap: do M15 trades fire on the same setups (redundancy) or new ones?
t5 = {(x.get('side'), round(x.get('entry', 0), 0)) for x in (r5.get('trade_log') or [])}
t15 = (r15.get('trade_log') or [])
if t15:
    same = sum(1 for x in t15 if (x.get('side'), round(x.get('entry', 0), 0)) in t5)
    print(f"M15 trades matching an M5 trade (same side/entry±$1): {same}/{len(t15)}")
    uniq = [x for x in t15 if (x.get('side'), round(x.get('entry', 0), 0)) not in t5]
    if uniq:
        uwin = sum(1 for x in uniq if x.get('pnl', 0) > 0)
        utot = sum(x.get('pnl', 0) for x in uniq)
        print(f"M15-UNIQUE trades: {len(uniq)} WR={uwin/len(uniq)*100:.1f}% "
              f"total={utot:+.2f}$ mean={utot/len(uniq):+.2f}$ "
              f"per1000h={utot/span15*1000:+.1f}$")

json.dump({'M5': {k: v for k, v in r5.items() if k != 'trade_log'},
           'M15': {k: v for k, v in r15.items() if k != 'trade_log'}},
          open('/tmp/ab_entry_tf.json', 'w'), indent=1)
print('saved /tmp/ab_entry_tf.json')