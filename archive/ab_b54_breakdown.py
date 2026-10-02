#!/usr/bin/env python3
"""b54c: WHERE does the extra profit live? Session (UTC hour) x style x
spread-sensitivity breakdown on the live-parity M5 funnel.

Questions this answers with data instead of vibes:
  1. Is the edge uniform across London/NY/Asia sessions, or is one session
     carrying it (and is Asia — the thin, rangey session behind the 05:30
     discount losses — actually net negative)?
  2. Does partial_tp1_share=0.7 help EVERY style, or only the discount/value
     lanes (i.e. should the live ladder be style-aware instead of a flat 0.7)?
  3. How much spread increase kills the edge (robustness to broker drift)?

Read-only. Output: ab_b54_breakdown_results.json
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from env_loader import load_dotenv
load_dotenv(ROOT / '.env')

from bridge_client import BridgeClient
from engines.backtest_real import run_backtest

DATA = json.loads((ROOT / 'data/backtest/robustness_data_M5.json').read_text())
OUT = ROOT / 'data/backtest/ab_b54_breakdown_results.json'
SYMBOL = 'XAUUSD'
SLICE = {'M5': DATA['M5'], 'H1': DATA['H1'], 'H4': DATA['H4']}


def session_of(ts: float) -> str:
    import datetime as dt
    h = dt.datetime.fromtimestamp(ts, dt.timezone.utc).hour
    if 7 <= h < 13:
        return 'London'
    if 13 <= h < 21:
        return 'NY'
    return 'Asia'


def bucketize(trade_log, bars):
    by_sess = defaultdict(lambda: [0, 0, 0.0])   # n, wins, pnl
    by_style = defaultdict(lambda: [0, 0, 0.0])
    by_cell = defaultdict(lambda: [0, 0, 0.0])   # style x session
    for t in trade_log:
        bar = bars[t['entry_index']]
        sess = session_of(bar['time'])
        pnl = t['pnl']
        for d, k in ((by_sess, sess), (by_style, t['style']), (by_cell, f"{t['style']}|{sess}")):
            d[k][0] += 1
            d[k][1] += 1 if pnl > 0 else 0
            d[k][2] += pnl
    fmt = lambda d: {k: {'n': v[0], 'wr': round(v[1] / v[0], 3), 'pnl': round(v[2], 2)}
                     for k, v in sorted(d.items(), key=lambda kv: -kv[1][2])}
    return fmt(by_sess), fmt(by_style), fmt(by_cell)


def main() -> None:
    bridge = BridgeClient()
    out = {}

    # 1+2: baseline vs 0.7, with per-trade logs
    for arm, kw in (('base_p0.5', {}), ('part_0.7', {'partial_tp1_share': 0.7})):
        r = run_backtest(bridge, symbol=SYMBOL, timeframe='M5', count=len(DATA['M5']),
                         data=SLICE, **kw)
        assert r.get('ok'), r
        sess, style, cell = bucketize(r['trade_log'], DATA['M5'])
        out[arm] = {'net': r['net_pnl'], 'sessions': sess, 'styles': style, 'cells': cell}
        print(f"── {arm} net={r['net_pnl']:+.2f}")
        for k, v in sess.items():
            print(f"   sess {k:8s} n={v['n']:3d} wr={v['wr']:.0%} pnl={v['pnl']:+9.2f}")
        for k, v in style.items():
            print(f"   style {k:28s} n={v['n']:3d} wr={v['wr']:.0%} pnl={v['pnl']:+9.2f}")

    # style-aware candidate: 0.7 only for the no-trigger lanes
    # (approximated by running per-style: discount/value at 0.7, rest at 0.5)
    # backtest engine has no per-trade share, so we MEASURE the cells first and
    # decide from the table above.

    # 3: spread sensitivity on baseline management
    spread_rows = {}
    for sp in (0.20, 0.30, 0.40, 0.55):
        r = run_backtest(bridge, symbol=SYMBOL, timeframe='M5', count=len(DATA['M5']),
                         data=SLICE, spread_override=sp)
        spread_rows[f'spread_{sp}'] = {'n': r['trades'], 'wr': r['win_rate'],
                                       'net': round(r['net_pnl'], 2)}
        print(f"   spread {sp:.2f} n={r['trades']} wr={r['win_rate']:.1%} net={r['net_pnl']:+9.2f}")
    out['spread_sensitivity'] = spread_rows

    OUT.write_text(json.dumps(out, indent=2, default=str))
    print('saved ->', OUT)


if __name__ == '__main__':
    main()
