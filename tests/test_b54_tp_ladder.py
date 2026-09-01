"""b54 — TP1 ladder shares raised after the 13-week M5 parity test.

scripts/ab_b54_windows.py + the ladder-weeks run (data/backtest/
ab_b54_ladder_weeks.json): closing 70% at TP1 beats 50% in 13/13 weekly
windows (+180$/3wk), 85% beats it in 13/13 again (+315$). The final TP
rarely fills after TP1 in this regime, so early locking IS the edge.
The 0.3 strong-runner branch is deliberately untouched: it is the only
lane whose momentum thesis the parity backtest cannot model.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines.trade_management import _partial_close_fraction


def _t(**kw):
    base = {"setup_grade": "B", "momentum_strength": 0.5,
            "rr_remaining": 1.5, "structure_state": "healthy"}
    base.update(kw)
    return base


class TestB54Ladder(unittest.TestCase):
    def test_balanced_partial_locks_70(self):
        share, reason = _partial_close_fraction(_t())
        self.assertEqual((share, reason), (0.7, "balanced_partial"))

    def test_weak_follow_through_locks_85(self):
        share, reason = _partial_close_fraction(_t(momentum_strength=0.3))
        self.assertEqual((share, reason), (0.85, "weak_follow_through_lock_more"))

    def test_strong_runner_lane_unchanged(self):
        share, reason = _partial_close_fraction(
            _t(setup_grade="A", momentum_strength=0.9, rr_remaining=2.5))
        self.assertEqual((share, reason), (0.3, "strong_runner_keep_more"))

    def test_shares_are_valid_fractions(self):
        for t in (_t(), _t(momentum_strength=0.3), _t(structure_state="failing"),
                  _t(setup_grade="A", momentum_strength=0.9, rr_remaining=2.5)):
            share, _ = _partial_close_fraction(t)
            self.assertGreater(share, 0.0)
            self.assertLessEqual(share, 1.0)


if __name__ == "__main__":
    unittest.main()
