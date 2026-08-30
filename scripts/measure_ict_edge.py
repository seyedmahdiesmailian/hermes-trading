#!/usr/bin/env python3
"""Do the 8 unused ICT concepts carry information?

They are computed in smc_analyse() and dropped on the floor. Before wiring
any of them into the funnel, measure:
  1. fire rate per concept (how often non-empty/true on real M5 bars)
  2. forward-return edge: mean N-bar forward move after concept fires,
     vs baseline — a concept with no edge is decoration, with edge it is
     a candidate signal/confirmation.

Data: cached robustness M5 dataset (6500 bars, real broker history).
"""
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/home/ai/hermes-trading')
from engines.smc import (detect_breaker_blocks, detect_rejection_blocks,
                         detect_power_of_three, detect_turtle_soup,
                         evaluate_silver_bullet_setup,
                         compute_session_liquidity, detect_volume_imbalance)

DATA = json.loads(Path('/home/ai/hermes-trading/data/backtest/robustness_data_M5.json').read_text())
BARS = DATA['M5']
LOOK = 120          # window fed to detectors (live feeds ~120 M5 rows)
FWD = 12            # forward horizon: 12 M5 bars = 1 hour
STEP = 5            # sample every 5 bars

def now_at(i):
    return datetime.fromtimestamp(BARS[i]['time'], tz=timezone.utc)

fires = {k: [] for k in ('breaker', 'rejection', 'pot3_dist', 'turtle_soup',
                         'silver_bullet', 'sess_liq_sweep', 'vol_imb')}
fwd_moves_all = []

for i in range(LOOK, len(BARS) - FWD, STEP):
    rows = BARS[i - LOOK:i + 1]
    last = rows[-1]['close']
    fwd = BARS[i + FWD]['close'] - last
    fwd_moves_all.append(fwd)

    bb = detect_breaker_blocks(rows)
    rb = detect_rejection_blocks(rows)
    p3 = detect_power_of_three(rows)
    ts = detect_turtle_soup(rows)
    sb = evaluate_silver_bullet_setup(now_at(i))
    sl = compute_session_liquidity(rows)
    vi = detect_volume_imbalance(rows)

    if bb: fires['breaker'].append(fwd)
    if rb: fires['rejection'].append(fwd)
    if str(p3.get('phase', '')) == 'distribution': fires['pot3_dist'].append(fwd)
    if ts.get('found'): fires['turtle_soup'].append(fwd)
    if sb.get('active') or sb.get('in_window'): fires['silver_bullet'].append(fwd)
    if isinstance(sl, dict) and (sl.get('swept_high') or sl.get('swept_low')): fires['sess_liq_sweep'].append(fwd)
    if vi: fires['vol_imb'].append(fwd)

n = len(fwd_moves_all)
base_mu = statistics.fmean(fwd_moves_all)
base_sd = statistics.pstdev(fwd_moves_all)
atr = statistics.fmean(b['high'] - b['low'] for b in BARS[LOOK:])
print(f"bars sampled: {n} | ATR(M5)≈{atr:.2f}$ | baseline fwd 1h move: {base_mu:+.3f}$ (sd {base_sd:.2f})")
print(f"{'concept':14s} {'fire%':>6s} {'n':>5s} {'fwd$':>8s} {'edge$':>8s} {'edge/ATR':>8s} {'|t|':>5s}")
for k, mv in fires.items():
    if not mv:
        print(f"{k:14s} {0:5.1f}%     0        —        —        —     —")
        continue
    mu = statistics.fmean(mv)
    edge = mu - base_mu
    t = abs(edge) / (base_sd / (len(mv) ** 0.5)) if len(mv) > 2 else 0
    print(f"{k:14s} {100*len(mv)/n:5.1f}% {len(mv):5d} {mu:+8.3f} {edge:+8.3f} "
          f"{edge/atr:+8.3f} {t:5.1f}")
