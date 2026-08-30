#!/usr/bin/env python3
"""b18: were the 90 neutral_bias rejections (49% of all kills) profitable?

For every replay bar whose merged bias came out neutral, take the CLASSIC
(pre-merge) bias direction and measure the forward 1h move. If neutral
rejections systematically missed winners, the gate is too tight; if they
missed coin-flips, it is earning its keep. Read-only."""
import sys
sys.path.insert(0, '/home/ai/hermes-trading')
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv('/home/ai/hermes-trading/.env')
import json
from datetime import datetime, timezone
from collections import Counter
from engines.context import build_plan_context
from engines.smc import smc_analyse, merge_smc_with_classic

d = json.load(open('/home/ai/hermes-trading/data/backtest/robustness_data_M5.json'))
m5, h1, h4 = d['M5'], d['H1'], d['H4']
FWD = 12  # 1 hour ahead

stats = Counter()
pnl_units = []   # neutral bars, signed by classic bias
base_units = []  # NON-neutral bars (same fwd window, same signing) — baseline
for i in range(184, len(m5) - FWD):
    w = m5[max(0, i - 119):i + 1]
    t = w[-1]['time']
    now = datetime.fromtimestamp(t, tz=timezone.utc)
    h1w = [r for r in h1 if r['time'] <= t][-80:]
    h4w = [r for r in h4 if r['time'] <= t][-80:]
    if len(h1w) < 10:
        continue
    sess = "asia" if now.hour < 7 else "london" if now.hour < 13 else "newyork"
    ctx = build_plan_context(w, h1w, h4w, sess)
    classic = ctx.get('bias')
    merged = merge_smc_with_classic(ctx, smc_analyse(w, now=now, h1_rows=h1w))
    if ctx.get('quality', {}).get('regime') == 'range' and merged.get('bias') != 'neutral' and (merged.get('confidence') or 0) < 0.35:
        mb = 'neutral'
        forced = True
    else:
        mb = merged.get('bias', classic)
        forced = False
    if mb != 'neutral':
        if classic in ('bullish', 'bearish'):
            mv = m5[i + FWD]['close'] - w[-1]['close']
            base_units.append(mv if classic == 'bullish' else -mv)
        continue
    stats['neutral_bars'] += 1
    stats['forced_by_range_kill' if forced else 'natural_neutral'] += 1
    if classic not in ('bullish', 'bearish'):
        stats['no_classic_dir'] += 1
        continue
    move = m5[i + FWD]['close'] - w[-1]['close']
    signed = move if classic == 'bullish' else -move
    pnl_units.append(signed)
    stats['would_win' if signed > 0 else 'would_lose'] += 1

n = len(pnl_units)
if n:
    pnl_units.sort()
    wins = sum(1 for x in pnl_units if x > 0)
    print(f"neutral bars: {stats['neutral_bars']} (forced {stats['forced_by_range_kill']}, natural {stats['natural_neutral']})")
    print(f"directional (classic bias present): {n}")
    print(f"WR if entered: {100*wins/n:.1f}%  | mean fwd move: {sum(pnl_units)/n:+.2f}$  median: {pnl_units[n//2]:+.2f}$")
    print(f"sum of missed moves: {sum(pnl_units):+.1f}$ over {n} bars")
    b = len(base_units)
    if b:
        base_units.sort()
        bw = sum(1 for x in base_units if x > 0)
        print(f"BASELINE non-neutral bars: {b} | WR {100*bw/b:.1f}% | mean {sum(base_units)/b:+.2f}$ | median {base_units[b//2]:+.2f}$")
        print(f"=> neutral edge vs baseline: {sum(pnl_units)/n - sum(base_units)/b:+.2f}$/bar")
else:
    print(stats)
