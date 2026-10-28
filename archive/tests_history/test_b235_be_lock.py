"""b235 — the post-TP1 lock and its backtest/live parity.

The finding: the plain breakeven move left the runner at ENTRY. On 5000 M5
bars, 20 trades hit TP1 (proving the thesis) and then died at BE for a net
0.00R — killed by noise, not by reversal. Locking the stop at entry+0.5R
turns those into +0.5R outcomes.

A/B inside the real engine, 5 disjoint 1000-bar windows:
  K=0.0  total +153.82  worst -9.24
  K=0.5  total +210.36  worst -4.46  (wins 4/5 windows)
The lock never made a window worse.

This test pins TWO things:
1. _breakeven_stop returns the lock, not the raw entry.
2. backtest_real's default be_lock_r EQUALS the live lock, so the lab cannot
   silently simulate the wrong system (the b233b class).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines.trade_management import _breakeven_stop
from engines.backtest_real import run_backtest
import inspect


def _trade(**kw):
    t = {"side": "BUY", "entry_price": 4450.0, "sl": 4440.0,
         "momentum_strength": 0.5, "setup_grade": "C"}
    t.update(kw)
    return t


class TestBreakevenLock(unittest.TestCase):
    def test_buy_locks_above_entry(self):
        sl, reason = _breakeven_stop(_trade())
        self.assertEqual(reason, "lock_half_r")
        self.assertGreater(sl, 4450.0, "BUY lock must be ABOVE entry")
        self.assertAlmostEqual(sl, 4455.0, places=2)  # 0.5 * 10 risk

    def test_sell_locks_below_entry(self):
        sl, reason = _breakeven_stop(_trade(side="SELL"))
        self.assertEqual(reason, "lock_half_r")
        self.assertLess(sl, 4450.0, "SELL lock must be BELOW entry")
        self.assertAlmostEqual(sl, 4445.0, places=2)

    def test_lock_is_half_the_risk_distance(self):
        sl, _ = _breakeven_stop(_trade(entry_price=100.0, sl=92.0))
        # risk = 8, lock = 4 -> 104
        self.assertAlmostEqual(sl, 104.0, places=2)

    def test_the_plain_entry_return_is_gone(self):
        # the old behaviour returned entry verbatim; that is the regression
        sl, reason = _breakeven_stop(_trade())
        self.assertNotEqual(sl, 4450.0)
        self.assertNotEqual(reason, "plain_breakeven")

    def test_strong_lane_keeps_its_own_lock(self):
        # grade B+ and momentum>=0.65 uses the 0.15 lock, unchanged
        sl, reason = _breakeven_stop(
            _trade(setup_grade="B", momentum_strength=0.7))
        self.assertEqual(reason, "lock_in_after_tp1")
        self.assertAlmostEqual(sl, 4451.5, places=2)


class TestBacktestLiveParity(unittest.TestCase):
    """The lab default must equal the live lock (b233b class)."""

    def _default(self, name):
        sig = inspect.signature(run_backtest)
        return sig.parameters[name].default

    def test_default_be_lock_r_matches_live(self):
        d = self._default("be_lock_r")
        self.assertEqual(d, 0.5,
                         f"be_lock_r default is {d}; the live _breakeven_stop "
                         "locks 0.5R. A default != live makes every backtest "
                         "simulate the wrong system.")

    def test_a_b_override_is_still_possible(self):
        # the A/B must be reachable by explicit override, not a source edit
        sig = inspect.signature(run_backtest)
        self.assertIn("be_lock_r", sig.parameters)


if __name__ == "__main__":
    unittest.main()
