#!/usr/bin/env python3
"""Spread/slippage sensitivity on the parity funnel (backlog item).

Runs the EXACT live funnel (engines.backtest_real.run_backtest, data= so every
arm sees byte-identical bars) on the 13 NON-OVERLAPPING 500-bar windows from
the cached robustness dataset, once per spread level: 0.00 (gross, no cost),
0.20 (live assumption), 0.35, 0.50. Question: does the edge survive realistic
XAUUSD costs, and where does it break even?

Read-only: uses the cached dataset only, never fetches, never touches orders.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))

from bridge_client import BridgeClient
from engines.backtest_real import run_backtest

DATA_CACHE = Path(_ROOT) / 'data/backtest/robustness_data.json'
OUT = Path(_ROOT) / 'data/backtest/spread_sensitivity_results.json'
SPREADS = (0.00, 0.20, 0.35, 0.50)
WINDOW = 500


def windows(data: dict):
    m15 = data['M15']
    for k in range(len(m15) // WINDOW):
        seg = m15[k * WINDOW:(k + 1) * WINDOW]
        t_end = seg[-1]['time']
        yield {'M15': seg,
               'H1': [r for r in data['H1'] if r['time'] <= t_end][-WINDOW // 12 - 48:],
               'H4': [r for r in data['H4'] if r['time'] <= t_end][-WINDOW // 240 - 20:]}


def main() -> None:
    data = json.loads(DATA_CACHE.read_text())
    bridge = BridgeClient()
    wins = list(windows(data))
    print(f"{len(wins)} windows x {len(SPREADS)} spread levels")

    results = []
    for spread in SPREADS:
        tot_t = tot_w = tot_l = tot_s = 0
        tot_pnl = 0.0
        prof = 0
        per_window = []
        for sl in wins:
            r = run_backtest(bridge, count=WINDOW, data=sl, spread_override=spread)
            if not r.get('ok'):
                continue
            tot_t += r['trades']; tot_w += r['wins']; tot_l += r['losses']
            tot_s += r.get('scratches', 0)
            tot_pnl += r['net_pnl']
            if r['net_pnl'] > 0:
                prof += 1
            per_window.append({'trades': r['trades'], 'net_pnl': r['net_pnl']})
        decided = max(1, tot_w + tot_l)
        results.append({
            'spread': spread, 'trades': tot_t,
            'win_rate': round(tot_w / decided, 4),
            'net_pnl': round(tot_pnl, 2),
            'pnl_per_trade': round(tot_pnl / max(1, tot_t), 3),
            'scratches': tot_s,
            'profitable_windows': f"{prof}/{len(wins)}",
            'per_window': per_window,
        })
        print(f"spread={spread:.2f}: trades={tot_t} WR={tot_w/decided:.1%} "
              f"pnl={tot_pnl:+.2f}$ per_trade={tot_pnl/max(1,tot_t):+.3f}$ "
              f"prof_windows={prof}/{len(wins)} scratches={tot_s}")

    # break-even spread: linear interpolation between the two levels bracketing 0
    be = None
    for a, b in zip(results, results[1:]):
        if a['net_pnl'] >= 0 > b['net_pnl']:
            frac = a['net_pnl'] / (a['net_pnl'] - b['net_pnl'])
            be = round(a['spread'] + frac * (b['spread'] - a['spread']), 3)
            break
    print(f"break-even spread (total PnL crosses 0): {be}")

    OUT.write_text(json.dumps({'spreads': SPREADS, 'window_bars': WINDOW,
                               'n_windows': len(wins), 'results': results,
                               'break_even_spread': be}, indent=2))
    print(f"saved -> {OUT}")


if __name__ == '__main__':
    main()
