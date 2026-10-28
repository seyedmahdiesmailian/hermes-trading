"""b79d — ONE GRADE RULE, ONE WORLD.

THE INCONSISTENCY (measured 2026-09-11, data/backtest/b78_grade_parity_census.json
+ a 360-plan live census over Sep 10-11):
  * engines.plan.setup_grade is THE canonical grade (entry gate Check 6,
    runtime ladder, watchdog ladder, lab funnel via b108 parity).
  * engines.orchestrator._passes_quality_gate was a SECOND, looser rule:
    `smc_confidence >= 0.4` passed a plan even when setup_grade said C.
  * Result: the monitor stamped market_entry_now on C-grade plans that the
    executor's Check 6 was guaranteed to kill. 144 of 287 C-grade live plans
    passed the monitor gate; 23 of 36 b78 replay fires died exactly this way.
    Every one of those is a logged "fire" that can never become a trade —
    the same class of sim/live lie as b108/b193, one layer further upstream.

THE FIX (parity, not loosening): _passes_quality_gate now defers to the ONE
rule — a plan passes iff setup_grade(plan) <= MIN_SETUP_GRADE. This can only
REMOVE monitor fires the executor would have killed anyway; no trade that
live takes today is blocked by it. The threshold constant moved to
engines/plan.py (leaf) and auto_executor re-exports it, so the gate and the
monitor can no longer drift apart.

Pins:
  1. C-grade plans (incl. the smc_conf back-door) FAIL the monitor gate.
  2. A/B plans PASS it.
  3. The monitor never returns market_entry_now for a C-grade plan.
  4. auto_executor.MIN_SETUP_GRADE IS engines.plan.MIN_SETUP_GRADE (identity).
  5. The old back-door shape (neutral alignment + smc_conf 0.5) is dead.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engines.orchestrator import _passes_quality_gate, evaluate_monitor_cycle
from engines.plan import setup_grade, MIN_SETUP_GRADE
import engines.auto_executor as ae


def _plan(alignment, trend, regime, smc_conf, zones=None):
    return {
        "plan_id": "x-test", "symbol": "XAUUSD", "bias": "bullish",
        "quality": {"alignment": alignment, "trend_strength": trend,
                    "regime": regime, "smc_confidence": smc_conf},
        "zones": zones or {"long_entry_low": 100.0, "long_entry_high": 101.0,
                           "short_entry_low": 99.0, "short_entry_high": 100.0},
        "targets": [105.0], "invalidation": 99.0, "atr": 1.0,
        "execution": {}, "context": {},
    }


NOW = datetime(2026, 9, 11, 9, 0, tzinfo=timezone.utc)


class OneGradeRule(unittest.TestCase):

    def test_b79d_smc_conf_backdoor_no_longer_passes_c_grade(self):
        # neutral alignment, weak trend => setup_grade C; old rule passed it
        # on smc_conf >= 0.4. The b78 killer cell.
        p = _plan("neutral", 0.5, "range", 0.9)
        self.assertEqual(setup_grade(p), "C")
        self.assertFalse(_passes_quality_gate(p),
                         "smc_conf back-door still alive: C-grade plan "
                         "passes the monitor gate")

    def test_b79d_mixed_alignment_backdoor_dead(self):
        # b45: mixed = coin flip = C. Old gate let mixed+smc_conf through.
        p = _plan("mixed", 2.0, "pullback_continuation", 0.8)
        self.assertEqual(setup_grade(p), "C")
        self.assertFalse(_passes_quality_gate(p))

    def test_b79d_aligned_weak_trend_band_now_waits(self):
        # aligned 1.0 <= trend < 1.2: old gate passed, executor Check 6 kills.
        p = _plan("aligned", 1.1, "pullback_continuation", 0.2)
        self.assertEqual(setup_grade(p), "C")
        self.assertFalse(_passes_quality_gate(p))

    def test_b79d_b_grade_still_passes(self):
        p = _plan("aligned", 1.5, "pullback_continuation", 0.2)
        self.assertEqual(setup_grade(p), "B")
        self.assertTrue(_passes_quality_gate(p))

    def test_b79d_a_grade_still_passes(self):
        p = _plan("aligned", 3.5, "breakout_continuation", 0.2)
        self.assertEqual(setup_grade(p), "A")
        self.assertTrue(_passes_quality_gate(p))

    def test_b79d_threshold_is_one_object_not_two_literals(self):
        self.assertIs(ae.MIN_SETUP_GRADE, MIN_SETUP_GRADE,
                      "auto_executor re-declared its own threshold — the "
                      "drift that created the 144 dead fires is back")

    def test_b79d_monitor_never_fires_c_grade(self):
        # End-to-end shape: even with an explicit trigger, a C-grade plan
        # must not leave the monitor as market_entry_now.
        p = _plan("neutral", 0.5, "range", 0.9)
        d = evaluate_monitor_cycle(p, price=100.5, now=NOW, trigger_ok=True)
        self.assertNotIn(d.get("action"),
                         {"market_entry_now", "market_order"})


if __name__ == "__main__":
    unittest.main()
