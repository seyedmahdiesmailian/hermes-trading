#!/usr/bin/env python3
"""b182 contract tests — the half-at-TP1 exit lane.

Background (full narrative in engines/trade_management.py and
scripts/b182_exit_policy_backtest.py): b55 closed 100% at TP1 on evidence
taken when TP1 was the FINAL target; b60 moved TP1 to the midpoint of the
plan, so the pair amputates every winner at +0.75R of a 1.5R plan. Live
audit: 22 wins avg +$29.7 vs 11 losses avg -$59.9 (payoff 0.50). The fix
takes 50% at the midpoint and lets the rest ride to the broker TP.

These tests pin the SHAPE of the decision, not the backtest numbers:
  1. live ladder geometry (mid + final) and volume >= 0.02 -> half lane
  2. single-target geometry (b55 world / parity backtest) -> 1.0 unchanged
  3. volume 0.01 or unknown -> 1.0 (broker cannot halve a 0.01 lot)
  4. the strong-runner lane still wins when its conditions hold
  5. after TP1 is filled, the remaining target has nothing beyond it -> 1.0
  6. daemon + runtime both feed 'volume' into the trade dict (producer parity)
"""
from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engines.trade_management import (  # noqa: E402
    LADDER_FIELDS, _partial_close_fraction, _tp1_exit_closes_all,
    build_tp_ladder, ladder_fields)


def trade(entry=4400.0, side="SELL", final=4390.0, sl=4406.67, volume=0.03,
          grade="B", aligned=False, trend=1.5, filled=()):
    tp_levels = build_tp_ladder(entry, side, final, [final])
    q = {"alignment": "aligned" if aligned else "mixed",
         "trend_strength": trend}
    return {"side": side, "entry_price": entry, "sl": sl, "tp": final,
            "volume": volume, "tp_levels": tp_levels,
            "filled_tp_levels": list(filled),
            **ladder_fields(q, grade)}


class TestB182HalfLane(unittest.TestCase):
    def test_live_geometry_takes_half(self):
        t = trade()
        self.assertEqual(len(t["tp_levels"]), 2, "ladder must be mid+final")
        share, reason = _partial_close_fraction(t)
        self.assertEqual((share, reason), (0.5, "half_at_tp1_run_rest"))

    def test_unknown_volume_keeps_legacy_full_close(self):
        t = trade()
        t.pop("volume")
        self.assertEqual(_partial_close_fraction(t)[0], 1.0)

    def test_min_lot_keeps_legacy_full_close(self):
        # a 0.01 lot CANNOT be halved: volume_step is 0.01 and a 100%
        # partial close is broker-rejected (retcode 10026, b55's note).
        self.assertEqual(_partial_close_fraction(trade(volume=0.01))[0], 1.0)
        self.assertGreater(_partial_close_fraction(trade(volume=0.02))[0], 0.0)
        self.assertEqual(_partial_close_fraction(trade(volume=0.02))[0], 0.5)

    def test_single_target_geometry_unchanged(self):
        # b55's world (and the parity backtest's shape): TP1 IS the final.
        t = trade()
        t["tp_levels"] = [t["tp_levels"][0]]
        share, reason = _partial_close_fraction(t)
        self.assertEqual(share, 1.0)
        self.assertIn(reason, ("balanced_full_exit_at_tp1",
                               "weak_full_exit_at_tp1"))

    def test_after_last_target_no_further_level(self):
        ladder = build_tp_ladder(4400.0, "SELL", 4390.0, [4390.0])
        t = trade(filled=(ladder[0],))
        share, _ = _partial_close_fraction(t)
        self.assertEqual(share, 1.0, "the final target must still exit full")

    def test_strong_runner_lane_still_first(self):
        t = trade(grade="A", aligned=True, trend=1.7)  # momentum 0.85, A
        self.assertEqual(_partial_close_fraction(t),
                         (0.3, "strong_runner_keep_more"))

    def test_closes_all_flag_follows_the_lane(self):
        self.assertFalse(_tp1_exit_closes_all(trade()))       # half lane
        self.assertTrue(_tp1_exit_closes_all(trade(volume=0.01)))  # full exit


class TestB182ProducerParity(unittest.TestCase):
    def test_both_producers_feed_volume(self):
        """_partial_close_fraction now reads trade['volume']; a producer
        that omits it silently disables the half lane (the b109 drift
        class). Both live producers must carry the key."""
        import hermes_runtime
        import position_daemon
        for fn in (position_daemon.build_trade,):
            src = inspect.getsource(fn)
            self.assertIn("'volume'", src, fn.__name__)
        src = inspect.getsource(hermes_runtime)
        self.assertIn("'volume': p.volume", src.replace('"', "'"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
