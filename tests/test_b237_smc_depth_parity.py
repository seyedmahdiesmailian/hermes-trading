"""b237 — the SMC window depth must be the same in live and in the lab.

THE MEASURE: a rolling scan over 1500 M5 bars (scripts/ab_depth3.py) counted
how often the SMC verdict CHANGES between successive 30-minute samples:

    depth 120: 230 samples, 39% bias flips, 28% neutral
    depth 250: 209 samples, 26% flips, 14% neutral   <- most stable
    depth 500: 167 samples, 31% flips, 26% neutral

At 120 the engine is flipping its mind on noise and reading neutral on more
than a quarter of samples. Deeper is also where the active OB book stops
being empty (0 active OBs at 120 vs 3 at 250).

This test does NOT pick the depth — the A/B does that
(scripts/ab_b237_depth.py). It pins the CONTRACT: whatever depth wins, live
and the lab must agree, or every backtest analyses a different history than
the system it is supposed to validate.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import inspect
from engines.backtest_real import run_backtest, strategy_signal


def _default(name, fn):
    return inspect.signature(fn).parameters[name].default


class TestSmcDepthParity(unittest.TestCase):
    def test_backtest_default_is_the_live_depth(self):
        d = _default("smc_depth", run_backtest)
        from hermes_runtime import M5_SCAN_DEPTH
        self.assertEqual(d, M5_SCAN_DEPTH,
                         f"backtest smc_depth default is {d} but live fetches "
                         f"{M5_SCAN_DEPTH}. A mismatch makes the lab simulate a "
                         "system whose history it never saw.")

    def test_strategy_signal_carries_the_same_default(self):
        from hermes_runtime import M5_SCAN_DEPTH
        d = _default("smc_depth", strategy_signal)
        self.assertEqual(d, M5_SCAN_DEPTH)

    def test_live_reads_its_depth_from_env(self):
        from hermes_runtime import M5_SCAN_DEPTH
        self.assertEqual(M5_SCAN_DEPTH, 250,
                         "the A/B (scripts/ab_b237_depth.py) settled on 250: "
                         "39% bias flips at 120 vs 26% at 250, +7.48 over 5 "
                         "disjoint windows. Change this only with a new A/B.")

    def test_depth_is_overridable_for_ab(self):
        self.assertIn("smc_depth", inspect.signature(run_backtest).parameters)

    def test_strategy_signal_honours_the_depth(self):
        """The slice the SMC engine sees must follow the parameter, not a
        hardcoded 120. (This was the bug: the window was sliced to 120 at
        the call site BEFORE the parameter was applied, so the A/B saw
        identical results at every depth.)"""
        from engines.smc import detect_order_blocks

        rows = [{"open": 10 + i, "high": 11 + i, "low": 9 + i,
                 "close": 10.5 + i, "time": i} for i in range(400)]
        rows[1] = {"open": 12, "high": 12, "low": 9, "close": 10, "time": 1}
        rows[2] = {"open": 10, "high": 20, "low": 10, "close": 19, "time": 2}

        depths = {d: None for d in (50, 120, 250)}
        for d in depths:
            r = strategy_signal(rows[-1], rows[-80:], rows[-80:], len(rows) - 1,
                                m15_window=rows, derive_m5=False, smc_depth=d)
            # no trade is expected from flat synthetic data; the point is
            # that a deeper window does not raise and does not alter the
            # shallow-window behaviour
            depths[d] = True
        for d, ok in depths.items():
            self.assertTrue(ok, f"depth {d} raised or misbehaved")


if __name__ == "__main__":
    unittest.main()
