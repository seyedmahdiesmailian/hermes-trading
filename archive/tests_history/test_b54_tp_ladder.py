"""b54/b55 — TP1 exit ladder locked by the 13-week M5 parity tests.

b54 raised 0.5 -> 0.7 (ab_b54_windows: 13/13 weeks better, +180$/3wk).
b55 went further after the backtest engine learned to simulate the LIVE
trailing stop (b55b found the old sim lied by omission): with honest parity,
scripts/ab_b55c_exit_geometry.py + ab_b55d_windows.py showed closing 100% at
TP1 beats the 70% ladder in 11/13 weeks, +260$/3wk, ZERO big-loss weeks.
So balanced/weak lanes now exit the FULL position at TP1; only the
strong-runner lane (A+ & momentum>=0.8 & rr>=2 & healthy — never fired live)
keeps a 70% runner. MT5 rejects a 100% partial close (retcode 10026), so
evaluate_management_action routes fraction>=1.0 to close_position — pinned
below too.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines.trade_management import (_partial_close_fraction,
                                      _tp1_exit_closes_all)


def _t(**kw):
    base = {"setup_grade": "B", "momentum_strength": 0.5,
            "rr_remaining": 1.5, "structure_state": "healthy"}
    base.update(kw)
    return base


class TestB55TpLadder(unittest.TestCase):
    def test_balanced_exits_full_at_tp1(self):
        share, reason = _partial_close_fraction(_t())
        self.assertEqual((share, reason), (1.0, "balanced_full_exit_at_tp1"))

    def test_weak_follow_through_exits_full(self):
        share, reason = _partial_close_fraction(_t(momentum_strength=0.3))
        self.assertEqual((share, reason), (1.0, "weak_full_exit_at_tp1"))

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

    def test_full_exit_flag(self):
        self.assertTrue(_tp1_exit_closes_all(_t()))
        self.assertFalse(_tp1_exit_closes_all(
            _t(setup_grade="A", momentum_strength=0.9, rr_remaining=2.5)))


class TestB55ExecutorRouting(unittest.TestCase):
    """fraction>=1.0 must CLOSE the ticket — partial_close(100%) dies with
    retcode 10026 on this broker."""

    def _fake_bridge(self):
        class B:
            def __init__(self):
                self.closed = []
                self.partial = []

            def close_position(self, ticket):
                self.closed.append(ticket)
                return {"ok": True}

            def partial_close(self, ticket, percent):
                self.partial.append((ticket, percent))
                return {"ok": True}
        return B()

    def test_full_fraction_routes_to_close(self):
        from engines.auto_executor import evaluate_management_action
        b = self._fake_bridge()
        r = evaluate_management_action(
            {"action": "partial_take_profit", "close_fraction": 1.0}, b, 42)
        self.assertTrue(r["executed"])
        self.assertEqual(b.closed, [42])
        self.assertEqual(b.partial, [])

    def test_partial_fraction_stays_partial(self):
        from engines.auto_executor import evaluate_management_action
        b = self._fake_bridge()
        r = evaluate_management_action(
            {"action": "partial_take_profit", "close_fraction": 0.3}, b, 42)
        self.assertTrue(r["executed"])
        self.assertEqual(b.partial, [(42, 30)])
        self.assertEqual(b.closed, [])


if __name__ == "__main__":
    unittest.main()
