#!/usr/bin/env python3
"""b59: per-WEEK — does the strong-runner lane earn its keep? (b55 leftover)

b55 made TP1 a full exit EXCEPT the strong-runner lane (A + momentum>=0.8 +
rr>=2 + healthy keeps 70% riding with a 0.5R trail). That lane never fired
live yet and was never isolated in a weekly test. If flat-100 (no runner at
all) matches or beats it week-to-week, we simplify live to always full-exit.

Same 13-window cached slicing as ab_b55d_windows.py.
Decision rule (pre-registered): adopt flat-100 only if it wins the MEDIAN
weekly delta AND loses by >10% in at most 3 of 13 windows.
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
from engines.trade_management import _partial_close_fraction

DATA = json.loads((ROOT / 'data/backtest/robustness_data_M5.json').read_text())
OUT = ROOT / 'data/backtest/ab_b59_runner_lane.json'
WINDOW = 500
H1_PAD_BEFORE = 48
H4_PAD_BEFORE = 12
SYMBOL = 'XAUUSD'


def flat_100(trade):
    return 1.0


ARMS = {
    'b55_default': {'partial_share_fn': _partial_close_fraction, 'trail_after_partial': 0.5},
    'flat_100':    {'partial_share_fn': flat_100, 'trail_after_partial': 0.5},
}
BASE = 'b55_default'


def main() -> None:
    bridge = BridgeClient()
    m5, h1, h4 = DATA['M5'], DATA['H1'], DATA['H4']
    n_windows = len(m5) // WINDOW
    print(f"{n_windows} windows x {len(ARMS)} arms\n", flush=True)

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

    verdict = {}
    base = [r[BASE]['pnl'] for r in rows if r.get(BASE)]
    for arm in ARMS:
        if arm == BASE:
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
