#!/usr/bin/env python3
"""Does setup_grade predict PnL? (b14 — grade-gate efficacy audit)

MIN_SETUP_GRADE=B rejects every C setup live. If C trades are NOT worse
than B/A on real data, the gate throws away edge for no reason — exactly
the user's 'funnel too tight' complaint.

Method: slice the same non-overlapping 500-bar M5 windows as
backtest_robustness, run the parity funnel with min_grade=None (grades
recorded, never filtered), bucket realized trades by grade.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines.backtest_real import run_backtest

WINDOW, H1_PAD_BEFORE, H4_PAD_BEFORE = 500, 40, 10
d = json.loads(Path('data/backtest/robustness_data_M5.json').read_text())
m5, h1, h4 = d['M5'], d['H1'], d['H4']

buckets = defaultdict(lambda: {'n': 0, 'wins': 0, 'pnl': 0.0})
for w in range(len(m5) // WINDOW):
    lo, hi = w * WINDOW, (w + 1) * WINDOW
    wm = m5[lo:hi]
    t_end = wm[-1]['time']
    slice_data = {
        'M5': wm,
        'H1': [r for r in h1 if wm[0]['time'] - H1_PAD_BEFORE * 3600 <= r.get('time', 0) <= t_end],
        'H4': [r for r in h4 if wm[0]['time'] - H4_PAD_BEFORE * 4 * 3600 <= r.get('time', 0) <= t_end],
    }
    r = run_backtest(None, timeframe='M5', count=WINDOW, data=slice_data, min_grade=None)
    for t in r.get('trade_log', []):
        g = str(t.get('grade') or '?')
        b = buckets[g]
        b['n'] += 1
        b['pnl'] += t['pnl']
        if t['pnl'] > 0:
            b['wins'] += 1

print(f"{'grade':6} {'trades':>7} {'WR%':>6} {'PnL$':>9} {'avg$':>8}")
for g in sorted(buckets):
    b = buckets[g]
    wr = 100 * b['wins'] / b['n'] if b['n'] else 0
    print(f"{g:6} {b['n']:>7} {wr:>5.1f} {b['pnl']:>9.2f} {b['pnl']/max(1,b['n']):>8.2f}")
