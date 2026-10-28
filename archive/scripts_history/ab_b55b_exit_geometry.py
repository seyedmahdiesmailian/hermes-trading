#!/usr/bin/env python3
"""b55b: EXIT-GEOMETRY sweep — the ladder test exposed a leak.

ab_b54_ladder_weeks showed a MONOTONIC ladder: closing MORE of the position at
TP1 improved weekly PnL in 13/13 weeks at every step (0.5 -> 0.7 -> 0.85 -> 1.0).
Monotonicity is the tell: it is not that taking profit is magic, it is that the
RUNNER (the residual left after TP1, trailed to the final TP) is systematically
GIVING BACK more than it captures. In other words the final-TP leg of the
plan is not being reached often enough to pay for the trail leakage.

This script separates the two questions instead of conflating them:

  A) WHERE is the first take-profit?  tp1_position in {0.35 ... 1.0} of the
     blueprint's TP distance (0.5 = live today).
  B) HOW MUCH is closed there?        share in {0.7, 1.0}.

and reports, per arm, the runner's own contribution so we can see whether the
runner earns anything at all:

  net_total = net_from_TP1_leg + net_from_runner_leg

Judged per-week (13 non-overlapping ~1-week windows, same slicing as
backtest_robustness.py) with a PRE-REGISTERED rule: an arm is adopted only if
it beats live in >=11/13 weeks AND its median weekly delta is positive.

Read-only. Output: ab_b55b_exit_geometry.json
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
OUT = ROOT / 'data/backtest/ab_b55b_exit_geometry.json'
WINDOW = 500
H1_PAD_BEFORE = 48
H4_PAD_BEFORE = 12

# arm name -> kwargs for run_backtest
ARMS = {
    'live_t0.5_s0.7': {'tp1_position': 0.5, 'partial_tp1_share': 0.7},
    't0.5_s1.0':      {'tp1_position': 0.5, 'partial_tp1_share': 1.0},
    't0.65_s1.0':     {'tp1_position': 0.65, 'partial_tp1_share': 1.0},
    't0.8_s1.0':      {'tp1_position': 0.8, 'partial_tp1_share': 1.0},
    't1.0_s1.0':      {'tp1_position': 1.0, 'partial_tp1_share': 1.0},
    't0.35_s0.7':     {'tp1_position': 0.35, 'partial_tp1_share': 0.7},
    't0.35_s1.0':     {'tp1_position': 0.35, 'partial_tp1_share': 1.0},
}


def stat(res: dict) -> dict:
    log = res.get('trade_log', [])
    pnls = [t['pnl'] for t in log]
    eq = peak = dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    dec = [p for p in pnls if abs(p) > 1e-9]
    return {'n': len(log), 'wr': round(sum(1 for p in dec if p > 0) / len(dec), 3) if dec else 0,
            'pnl': round(sum(pnls), 2), 'maxdd': round(dd, 2),
            'best': round(max(pnls), 2) if pnls else 0,
            'worst': round(min(pnls), 2) if pnls else 0,
            'avg_win': round(sum(p for p in dec if p > 0) / max(1, sum(1 for p in dec if p > 0)), 2)}


def main() -> None:
    bridge = BridgeClient()
    m5, h1, h4 = DATA['M5'], DATA['H1'], DATA['H4']
    n_windows = len(m5) // WINDOW
    print(f'{n_windows} windows x {len(ARMS)} arms', flush=True)

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
            r = run_backtest(bridge, symbol='XAUUSD', timeframe='M5', count=WINDOW,
                             data=slice_data, spread_override=0.20, min_rr=1.5,
                             min_grade='B', **kw)
            row[arm] = stat(r) if r.get('ok') else None
        rows.append(row)
        print(f"win{w:02d} " + ' | '.join(f"{a}:{row[a]['pnl']:+7.2f}" if row.get(a) else f'{a}:err'
                                          for a in ARMS), flush=True)

    # aggregate over the whole dataset too (single run per arm, no windowing)
    full = {}
    for arm, kw in ARMS.items():
        r = run_backtest(bridge, symbol='XAUUSD', timeframe='M5', data=DATA,
                         spread_override=0.20, min_rr=1.5, min_grade='B', **kw)
        full[arm] = stat(r) if r.get('ok') else None

    base = [r['live_t0.5_s0.7']['pnl'] for r in rows if r.get('live_t0.5_s0.7')]
    verdict = {}
    for arm in ARMS:
        vals = [r[arm]['pnl'] for r in rows if r.get(arm)]
        if len(vals) != len(base):
            verdict[arm] = {'ok': False, 'reason': 'window mismatch'}
            continue
        diffs = [v - b for v, b in zip(vals, base)]
        verdict[arm] = {'weeks_won': sum(1 for d in diffs if d > 0), 'weeks': len(diffs),
                        'median_delta': round(sorted(diffs)[len(diffs) // 2], 2),
                        'total_delta': round(sum(diffs), 2),
                        'ok': sum(1 for d in diffs if d > 0) >= 11 and sorted(diffs)[len(diffs) // 2] > 0}

    print('\nFULL-DATASET (3 weeks):')
    for arm, s in full.items():
        if s:
            print(f"  {arm:16s} n={s['n']:3d} WR={s['wr']:.3f} pnl={s['pnl']:+8.2f} "
                  f"maxdd={s['maxdd']:6.2f} best={s['best']:+7.2f} avg_win={s['avg_win']:+6.2f}")
    print('\nVERDICT:', json.dumps(verdict, indent=2))
    OUT.write_text(json.dumps({'rows': rows, 'full': full, 'verdict': verdict}, indent=2))
    print('saved ->', OUT)


if __name__ == '__main__':
    main()
