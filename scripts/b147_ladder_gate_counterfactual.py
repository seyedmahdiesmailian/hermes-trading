"""b147 counterfactual: what if the signal gate scored RR on the TP LADDER
instead of rung 1 only?

WHY: the parser computes `ladder_rr` (mean distance of all TP rungs / risk) but
`evaluate_signal` reads `rr_ratio`, which is TP1-only. Channels write
"TP1 4397 / TP2 4394 / ... / TP7 4370", so a signal whose real payoff is 3R is
scored as 0.2R and dies as `poor_rr_0.2`.

This script does NOT touch the live gate. It re-scores the replay ledger by
swapping the RR band contribution, which is deterministic given the recorded
score.

RR band contribution (engines/signal_decision.py Check 5):
    rr >= 2.0 -> +1.5 | rr >= 1.5 -> +1.0 | rr >= 1.0 -> +0.5 | else -> -1.0
Execute threshold: score >= 6.0 AND account_policy.trade_allowed.

Two views, deliberately separated by rigour:
  VIEW 1 (rigorous)  — legs with a LOGGED bias and a recorded score. Swap the
                       RR band and see who crosses 6.0.
  VIEW 2 (indicative) — every leg, ASSUMING the bias had been aligned
                       (score = 5.0 + rr_contrib, the ceiling a channel signal
                       can reach). Answers "how much of the whole 90-day stream
                       would ladder scoring have let through", but it is an
                       assumption, not a measurement.

Read-only. Usage: python3 scripts/b147_ladder_gate_counterfactual.py
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LEDGER = REPO / 'data' / 'radin' / 'replay.csv'
THRESHOLD = 6.0
# symbol(1.0) + high_confidence(2.0) + valid direction(1.0) + aligned(2.0)
ALIGNED_BASE = 5.0


def rr_contrib(rr: float) -> float:
    if rr >= 2.0:
        return 1.5
    if rr >= 1.5:
        return 1.0
    if rr >= 1.0:
        return 0.5
    return -1.0


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def agg(legs, label):
    if not legs:
        print('   %-26s n=0' % label)
        return (0.0, 0.0)
    a = sum(num(x['pnl_tp1']) or 0.0 for x in legs)
    l = sum(num(x['pnl_ladder']) or 0.0 for x in legs)
    w = sum(1 for x in legs if (num(x['pnl_tp1']) or 0.0) > 0)
    print('   %-26s n=%4d | TP1 %8.1f$ (win %3.0f%%) | ladder %8.1f$'
          % (label, len(legs), a, 100 * w / len(legs), l))
    return (a, l)


def by_month(legs, label):
    per = defaultdict(lambda: [0, 0.0])
    for x in legs:
        k = (x.get('date') or '')[:7]
        per[k][0] += 1
        per[k][1] += num(x['pnl_tp1']) or 0.0
    print('   %s by month:' % label)
    for k in sorted(per):
        n, a = per[k]
        print('      %-9s n=%4d  TP1 %+8.1f$' % (k, n, a))


def main() -> int:
    if not LEDGER.exists():
        print('missing ledger:', LEDGER, file=sys.stderr)
        return 1
    all_rows = list(csv.DictReader(open(LEDGER)))
    legs = [r for r in all_rows if not (r.get('skip') or '').strip()]
    scored = [r for r in legs
              if num(r.get('score')) is not None
              and num(r.get('rr_tp1')) is not None
              and num(r.get('rr_ladder')) is not None]
    print('legs in ledger: %d | with a recorded score+bias: %d | without: %d'
          % (len(legs), len(scored), len(legs) - len(scored)))

    # ── VIEW 1: rigorous, logged bias only ────────────────────────────────
    print('\n=== VIEW 1 — legs with LOGGED bias (rigorous) ===')
    acc_now, flips, still = [], [], []
    for r in scored:
        base = num(r['score']) or 0.0
        r1 = num(r['rr_tp1']) or 0.0
        rl = num(r['rr_ladder']) or 0.0
        alt = round(base - rr_contrib(r1) + rr_contrib(rl), 2)
        if base >= THRESHOLD:
            acc_now.append(r)
        elif alt >= THRESHOLD:
            flips.append(r)
        else:
            still.append(r)
    agg(acc_now, 'accepted today')
    agg(flips, 'NEWLY accepted')
    agg(still, 'still rejected')
    if flips:
        print('   flipped legs in full:')
        for x in flips:
            print('      %s %-10s %-4s rr_tp1=%-5s rr_lad=%-5s score %s->%s  TP1 %+6.1f$  ladder %+6.1f$'
                  % ((x.get('date') or '')[:16], x.get('channel') or '?', x.get('side') or '?',
                     x.get('rr_tp1'), x.get('rr_ladder'), x.get('score'),
                     round((num(x['score']) or 0) - rr_contrib(num(x['rr_tp1']) or 0)
                           + rr_contrib(num(x['rr_ladder']) or 0), 2),
                     num(x['pnl_tp1']) or 0, num(x['pnl_ladder']) or 0))
        by_month(flips, 'flipped')

    # ── VIEW 2: indicative, aligned-bias ceiling on every leg ─────────────
    print('\n=== VIEW 2 — ALL legs assuming aligned bias (indicative) ===')
    v2_acc, v2_flip = [], []
    for r in legs:
        r1 = num(r.get('rr_tp1'))
        rl = num(r.get('rr_ladder'))
        if r1 is None or rl is None:
            continue
        if ALIGNED_BASE + rr_contrib(r1) >= THRESHOLD:
            v2_acc.append(r)
        elif ALIGNED_BASE + rr_contrib(rl) >= THRESHOLD:
            v2_flip.append(r)
    agg(v2_acc, 'accepted today')
    agg(v2_flip, 'NEWLY accepted')
    agg([r for r in legs if r not in v2_acc and r not in v2_flip], 'still rejected')
    per = defaultdict(lambda: [0, 0.0, 0.0])
    for x in v2_flip:
        k = x.get('channel') or '?'
        per[k][0] += 1
        per[k][1] += num(x['pnl_tp1']) or 0.0
        per[k][2] += num(x['pnl_ladder']) or 0.0
    print('   flipped by channel:')
    for k, (n, a, l) in sorted(per.items(), key=lambda y: -y[1][0]):
        print('      %-12s n=%4d  TP1 %+8.1f$  ladder %+8.1f$' % (k, n, a, l))
    by_month(v2_flip, 'flipped')

    worst = sorted(v2_flip, key=lambda x: num(x['pnl_tp1']) or 0.0)[:6]
    print('   worst flipped legs (what loosening costs):')
    for x in worst:
        print('      %s %-10s %-4s rr_tp1=%-5s TP1 %+7.1f$  %s'
              % ((x.get('date') or '')[:16], x.get('channel') or '?', x.get('side') or '?',
                 x.get('rr_tp1'), num(x['pnl_tp1']) or 0, str(x.get('text') or '')[:34].replace('\n', ' ')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
