#!/usr/bin/env python3
"""Re-measure the merge-regime wiring fix (review 2026-09-17, report §1.3).

The bug: engines.smc.merge_smc_with_classic read the regime from a TOP-LEVEL
key that no producer ever writes (build_plan_context puts it in
quality.regime only), so classic_regime was ALWAYS the "range" default and
classic_confidence was halved for EVERY plan — a 0.7 aligned confidence
permanently became 0.35, feeding merged confidence, apply_smc_merge's
RANGE_KILL_CONF (0.35) comparison and the quality.smc_confidence stamp.

Because the backtest runs through the same shared merge, every historical
number is calibrated on the halved values. This script measures the blast
radius on the REAL historical corpus — all committed plan snapshots in
data/xau_plan/plan_history/ — by replaying the merge for each snapshot with
the OLD (buggy) regime read and the NEW one, using a neutral SMC input so
the only difference is the regime key:

  * how many plans carried a non-'range' quality.regime (affected);
  * the merged-confidence delta distribution;
  * how many plans CROSS the RANGE_KILL_CONF=0.35 boundary (behaviour
    change at apply_smc_merge's veto) or flip action (wait <-> long/short).

Output ledger: data/backtest/review_2026_09_17_merge_remeasure.json
(read-only over the corpus; repo lab-script convention).
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from engines.smc import merge_smc_with_classic  # noqa: E402
from engines.plan import RANGE_KILL_CONF  # noqa: E402

HISTORY = BASE / 'data' / 'xau_plan' / 'plan_history'
OUT = BASE / 'data' / 'backtest' / 'review_2026_09_17_merge_remeasure.json'

# Neutral SMC side: no bias, middling confidence — the classic side is the
# only thing that moves between old and new, which is exactly the wiring
# under test.
SMC = {"bias": "neutral", "confidence": 0.5, "signal": "wait",
       "smc_weight": 0.5}


def merge_with_regime(plan: dict, regime: str) -> dict:
    """Replay the merge with a forced regime (old bug = 'range' default)."""
    import copy
    ctx = copy.deepcopy(plan)
    ctx['quality'] = dict(ctx.get('quality') or {})
    ctx['quality']['regime'] = regime
    ctx.pop('regime', None)  # top-level never exists in real plans
    return merge_smc_with_classic(ctx, dict(SMC))


def main() -> int:
    snapshots = sorted(HISTORY.glob('*.json'))
    stats = Counter()
    deltas = []
    boundary_crossings = []
    action_flips = []
    regime_counts = Counter()
    for f in snapshots:
        try:
            plan = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            stats['unreadable'] += 1
            continue
        quality = plan.get('quality') or {}
        real_regime = quality.get('regime')
        regime_counts[real_regime] += 1
        if real_regime is None:
            stats['no_regime'] += 1
            continue
        if real_regime == 'range':
            stats['unaffected_range'] += 1
            continue
        stats['affected_non_range'] += 1
        old = merge_with_regime(plan, 'range')      # the bug: always range
        new = merge_with_regime(plan, real_regime)  # the fix
        d = round(new['confidence'] - old['confidence'], 2)
        deltas.append(d)
        crossed = ((old['confidence'] < RANGE_KILL_CONF <= new['confidence'])
                   or (new['confidence'] < RANGE_KILL_CONF <= old['confidence']))
        if crossed:
            boundary_crossings.append({
                'plan': f.name, 'regime': real_regime,
                'old_conf': old['confidence'], 'new_conf': new['confidence']})
            stats['range_kill_boundary_crossings'] += 1
        if old['action'] != new['action']:
            action_flips.append({
                'plan': f.name, 'regime': real_regime,
                'old': f"{old['action']}@{old['confidence']}",
                'new': f"{new['action']}@{new['confidence']}"})
            stats['action_flips'] += 1

    result = {
        'at': __import__('datetime').datetime.now(
            __import__('datetime').timezone.utc).isoformat(),
        'corpus': 'data/xau_plan/plan_history/*.json',
        'snapshots': len(snapshots),
        'regime_distribution': dict(regime_counts.most_common()),
        'stats': dict(stats),
        'delta_mean_non_range': (round(sum(deltas) / len(deltas), 3)
                                 if deltas else None),
        'delta_min': min(deltas) if deltas else None,
        'delta_max': max(deltas) if deltas else None,
        'boundary_crossings': boundary_crossings[:50],
        'action_flips': action_flips[:50],
        'note': ('replayed with a neutral SMC input so the only variable is '
                 'the regime key; RANGE_KILL_CONF = '
                 f'{RANGE_KILL_CONF} is apply_smc_merge\'s veto threshold'),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ('boundary_crossings', 'action_flips')},
                     indent=1))
    print(f'ledger: {OUT}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
