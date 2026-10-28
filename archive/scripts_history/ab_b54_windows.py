#!/usr/bin/env python3
"""b54b: per-WEEK durability check for the two winning arms of ab_b54_sweep.

The 3-week aggregate said partial_tp1_share 0.7 beats 0.5 by +170$, but one
aggregate can hide a single lucky week. This slices the SAME cached M5 bars
into 13 non-overlapping ~1-week windows (same slicing as
backtest_robustness.py) and runs baseline vs each challenger per window.

Decision rule (pre-registered, no post-hoc): adopt only if the challenger wins
the MEDIAN weekly PnL AND loses by more than 10% in at most 3 of 13 windows.

Read-only. Output: ab_b54_windows_results.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from env_loader import load_dotenv
load_dotenv(ROOT / '.env')

from bridge_client import BridgeClient
from engines.backtest_real import run_backtest

DATA = json.loads((ROOT / 'data/backtest/robustness_data_M5.json').read_text())
OUT = ROOT / 'data/backtest/ab_b54_windows_results.json'
WINDOW = 500          # same as backtest_robustness.py
H1_PAD_BEFORE = 48
H4_PAD_BEFORE = 12
SYMBOL = 'XAUUSD'

ARMS = {
    'base_p0.5': {},
    'part_0.7': {'partial_tp1_share': 0.7},
    'part_0.6': {'partial_tp1_share': 0.6},
}


def main() -> None:
    bridge = BridgeClient()
    m5, h1, h4 = DATA['M5'], DATA['H1'], DATA['H4']
    n_windows = len(m5) // WINDOW
    print(f"{n_windows} windows x {len(ARMS)} arms\n")

    rows = []
    for w in range(n_windows):
        lo, hi = w * WINDOW, (w + 1) * WINDOW
        w_m5 = m5[lo:hi]
        t_end = w_m5[-1]['time']
        slice_data = {
            'M5': w_m5,
            'H1': [r for r in h1 if w_m5[0]['time'] - H1_PAD_BEFORE * 3600 <= r.get('time', 0) <= t_end],
            'H4': [r for r in h4 if w_m5[0]['time'] - H4_PAD_BEFORE * 4 * 3600 <= r.get('time', 0) <= t_end],
        }
        row = {'window': f'win{w:02d}'}
        for arm, kw in ARMS.items():
            r = run_backtest(bridge, symbol=SYMBOL, timeframe='M5', count=WINDOW,
                             data=slice_data, **kw)
            if not r.get('ok'):
                row[arm] = None
                continue
            row[arm] = {'pnl': round(r.get('net_pnl', 0), 2), 'n': r.get('trades', 0),
                        'wr': round(r.get('win_rate', 0), 3)}
        rows.append(row)
        line = f"win{w:02d} " + " | ".join(
            f"{a}:{row[a]['pnl']:+8.2f}" if row.get(a) else f"{a}:  err" for a in ARMS)
        print(line, flush=True)

    # ── pre-registered decision rule ──
    verdict = {}
    base = [r['base_p0.5']['pnl'] for r in rows if r.get('base_p0.5')]
    for arm in ARMS:
        if arm == 'base_p0.5':
            continue
        vals = [r[arm]['pnl'] for r in rows if r.get(arm)]
        if len(vals) != len(base):
            verdict[arm] = {'ok': False, 'reason': 'window mismatch'}
            continue
        diffs = [v - b for v, b in zip(vals, base)]
        med = sorted(diffs)[len(diffs) // 2]
        big_losses = sum(1 for v, b in zip(vals, base) if b > 0 and v < b * 0.9)
        verdict[arm] = {'ok': med > 0 and big_losses <= 3, 'median_delta': round(med, 2),
                        'weeks_won': sum(1 for d in diffs if d > 0), 'weeks': len(diffs),
                        'big_loss_weeks': big_losses,
                        'total_delta': round(sum(diffs), 2)}
    print('\nVERDICT:', json.dumps(verdict, indent=2))
    OUT.write_text(json.dumps({'rows': rows, 'verdict': verdict}, indent=2))
    print('saved ->', OUT)


if __name__ == '__main__':
    main()
