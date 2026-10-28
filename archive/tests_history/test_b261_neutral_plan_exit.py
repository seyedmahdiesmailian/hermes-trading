#!/usr/bin/env python3
"""b261 regression: a neutral-bias plan writes plan.targets = [], which used to
collapse build_tp_ladder to []. With no tp_levels, _next_unfilled_target
returned None, _partial_close_fraction fell through to the 1.0
'balanced_full_exit' share, and every winner closed 100% at TP1 while every
loser still took the full SL — payoff 0.50 on a 62% win rate.

The broker_tp set by the executor is a valid final target and must seed the
ladder when the plan supplies no targets of its own.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.trade_management import (
    build_tp_ladder,
    _next_unfilled_target,
    _partial_close_fraction,
)


def _trade(entry, side, broker_tp, levels, volume=0.05):
    return {
        "entry_price": entry,
        "volume": volume,
        "grade": "B",
        "momentum_strength": 0.5,
        "rr_remaining": 1.5,
        "structure_state": "healthy",
        "tp": broker_tp,
        "tp_levels": levels,
        "filled_tp_levels": [],
    }


class TestNeutralPlanTargets(unittest.TestCase):
    def test_sell_neutral_plan_builds_ladder_from_broker_tp(self):
        """A SELL with no plan targets but a valid broker_tp must still build a
        [midpoint, final] ladder, not collapse to []."""
        lvls = build_tp_ladder(4150.0, "SELL", 4130.0, [])
        self.assertEqual(lvls, [4140.0, 4130.0])

    def test_buy_neutral_plan_builds_ladder_from_broker_tp(self):
        lvls = build_tp_ladder(4140.0, "BUY", 4160.0, [])
        self.assertEqual(lvls, [4150.0, 4160.0])

    def test_neutral_plan_position_is_splittable(self):
        """The whole point of the fix: a >=0.02-lot position on a targetless
        plan must now take a HALF close at TP1, not a full exit."""
        lvls = build_tp_ladder(4150.0, "SELL", 4130.0, [])
        t = _trade(4150.0, "SELL", 4130.0, lvls)
        self.assertIsNotNone(_next_unfilled_target(t))
        share, reason = _partial_close_fraction(t)
        self.assertEqual(share, 0.5)
        self.assertEqual(reason, "half_at_tp1_run_rest")

    def test_wrong_side_broker_tp_still_empty(self):
        """A broker_tp on the LOSS side must NOT seed a ladder — that would
        flip an unprofitable level into a 'target'."""
        self.assertEqual(build_tp_ladder(4150.0, "SELL", 4170.0, []), [])

    def test_zero_broker_tp_still_empty(self):
        """The b60 truthiness gate is preserved for falsy broker_tp."""
        self.assertEqual(build_tp_ladder(4150.0, "SELL", 0.0, []), [])
        self.assertEqual(build_tp_ladder(4150.0, "SELL", None, []), [])

    def test_rich_plan_unaffected(self):
        """A plan with real targets still behaves exactly as before."""
        lvls = build_tp_ladder(4150.0, "SELL", 4130.0, [4140.0, 4130.0])
        self.assertEqual(lvls, [4140.0, 4130.0])

    def test_broker_tp_preferred_over_farther_bad_target(self):
        """broker_tp is the real final target even when raw_levels carries a
        farther level on the profit side (it wins max |dist| only among
        candidates, and the executor's TP is authoritative)."""
        lvls = build_tp_ladder(4150.0, "SELL", 4130.0, [4145.0, 4135.0])
        self.assertEqual(lvls[-1], 4130.0)


class TestLearningRatchet(unittest.TestCase):
    """b261: the elif avg<0 branch must not re-subtract risk_mult every cycle
    once it is already at the 0.5 floor — that ratchet crushed position size
    to 0.01 lots (unsplittable) and could never unwind."""

    def _state(self, risk_mult):
        import json
        import os
        import tempfile
        from engines import paths
        p = paths.learning_state()
        backup = None
        if p.exists():
            backup = p.read_bytes()
        try:
            p.write_text(json.dumps(
                {"min_rr": 2.0, "min_grade": "B", "risk_mult": risk_mult}))
            from engines.learning import adjustments
            return adjustments().get("changes") or {}
        finally:
            if backup is not None:
                p.write_bytes(backup)
            elif p.exists():
                p.unlink()

    def test_at_floor_proposes_nothing(self):
        changes = self._state(0.5)
        self.assertNotIn("risk_mult", changes,
                         "learning must not keep ratcheting once at the floor")

    def test_above_floor_tightens_once(self):
        changes = self._state(1.0)
        self.assertAlmostEqual(changes.get("risk_mult", 1.0), 0.9)


if __name__ == "__main__":
    unittest.main()
