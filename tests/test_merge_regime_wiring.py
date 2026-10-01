"""review 2026-09-17 row 5 — the merge reads the regime from the key that
exists.

engines.smc.merge_smc_with_classic computed classic_regime from a TOP-LEVEL
"regime" key that no producer ever writes — build_plan_context (the ONE
context producer for both live and backtest) puts it in quality.regime only.
So classic_regime was ALWAYS the "range" default and classic_confidence was
halved for EVERY plan: an aligned 0.7 permanently became 0.35, feeding
merged confidence, apply_smc_merge's RANGE_KILL_CONF veto comparison and the
quality.smc_confidence stamp. engines.plan.apply_smc_merge read the correct
key all along — two consumers, two definitions (the b109/b136 class the
project itself catalogued).

Re-measurement on the committed historical corpus
(scripts/review_2026_09_17_merge_remeasure.py, ledger in
data/backtest/review_2026_09_17_merge_remeasure.json): of 1594 plan
snapshots, 365 (23%) carried a non-range regime (250 breakout_continuation,
115 pullback_continuation) whose classic confidence was silently halved;
mean merged-confidence understatement +0.212, max +0.28. Under a
neutral-SMC replay none of them crosses the RANGE_KILL_CONF boundary or
flips an action — the distortion lands on the confidence stamps downstream
consumers (learning lane, grade context) were calibrated on.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SMC = {"bias": "bearish", "confidence": 0.8, "signal": "sell",
       "smc_weight": 0.6}


def ctx(alignment: str = "aligned", regime: str | None = None,
        bias: str = "bearish", top_level_regime=None) -> dict:
    quality = {"alignment": alignment}
    if regime is not None:
        quality["regime"] = regime
    out = {"bias": bias, "quality": quality}
    if top_level_regime is not None:
        out["regime"] = top_level_regime
    return out


class RegimeReadFromQuality(unittest.TestCase):
    def test_aligned_non_range_regime_keeps_full_confidence(self):
        from engines.smc import merge_smc_with_classic
        merged = merge_smc_with_classic(ctx("aligned", "breakout_continuation"),
                                        dict(SMC))
        self.assertEqual(merged["classic_source"]["confidence"], 0.7,
                         'an aligned plan in a non-range regime is still '
                         'halved — the regime wiring regressed')
        self.assertEqual(merged["classic_source"]["regime"],
                         "breakout_continuation")

    def test_genuine_range_still_halves(self):
        from engines.smc import merge_smc_with_classic
        merged = merge_smc_with_classic(ctx("aligned", "range"), dict(SMC))
        self.assertEqual(merged["classic_source"]["confidence"], 0.35)

    def test_top_level_fallback_still_honoured(self):
        # defensive fallback for hand-built contexts (lab scripts) that put
        # the regime at the top level: it must win over the "range" default
        from engines.smc import merge_smc_with_classic
        merged = merge_smc_with_classic(
            ctx("aligned", regime=None, top_level_regime="trending"),
            dict(SMC))
        self.assertEqual(merged["classic_source"]["regime"], "trending")
        self.assertEqual(merged["classic_source"]["confidence"], 0.7)

    def test_no_regime_anywhere_defaults_to_range(self):
        from engines.smc import merge_smc_with_classic
        merged = merge_smc_with_classic(ctx("aligned"), dict(SMC))
        self.assertEqual(merged["classic_source"]["confidence"], 0.35)

    def test_both_consumers_read_the_same_key(self):
        # the b109/b136 drift class: the two consumers of the regime must
        # not diverge again
        smc_src = (REPO / 'engines' / 'smc.py').read_text(encoding='utf-8')
        plan_src = (REPO / 'engines' / 'plan.py').read_text(encoding='utf-8')
        self.assertIn('classic_quality.get("regime")', smc_src)
        self.assertIn("ctx.get('quality', {}).get('regime'", plan_src)


class RealPlanReplay(unittest.TestCase):
    """The committed live plan (regime breakout_continuation, aligned)
    merges at full classic confidence now."""

    def test_committed_plan_merges_at_full_classic_confidence(self):
        from engines.smc import merge_smc_with_classic
        plan_path = REPO / 'data' / 'xau_plan' / 'current_plan.json'
        if not plan_path.exists():
            self.skipTest('no committed current_plan.json in this tree')
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        regime = (plan.get('quality') or {}).get('regime')
        if not regime or regime == 'range':
            self.skipTest(f'committed plan regime is {regime!r} — replay '
                          f'needs a non-range snapshot')
        self.assertIsNone(plan.get('regime'),
                          'the producer started writing a top-level regime '
                          '— this test (and the bug analysis) is stale')
        merged = merge_smc_with_classic(plan, dict(SMC))
        self.assertEqual(merged["classic_source"]["confidence"], 0.7)


class ReMeasurementLedgerPinned(unittest.TestCase):
    """The blast-radius measurement must stay in the repo (b88 discipline:
    a behaviour change ships with its re-measurement, not a promise)."""

    LEDGER = (REPO / 'data' / 'backtest'
              / 'review_2026_09_17_merge_remeasure.json')

    def test_ledger_exists_and_is_non_vacuous(self):
        self.assertTrue(self.LEDGER.exists(),
                        'the merge re-measurement ledger is gone — the '
                        'behaviour change lost its evidence')
        led = json.loads(self.LEDGER.read_text(encoding='utf-8'))
        self.assertGreaterEqual(led['snapshots'], 1500)
        self.assertGreaterEqual(led['stats']['affected_non_range'], 300,
                                'the corpus shrank dramatically — re-run '
                                'scripts/review_2026_09_17_merge_remeasure.py')
        self.assertGreater(led['delta_mean_non_range'], 0.1)

    def test_the_remeasure_script_still_exists(self):
        self.assertTrue((REPO / 'scripts'
                        / 'review_2026_09_17_merge_remeasure.py').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
