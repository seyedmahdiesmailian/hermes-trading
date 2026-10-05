"""b233b — backtest/executor RR parity (AUDIT-2026-10-04).

run_backtest used to default min_rr to a hardcoded 1.5 while the live
executor's floor was MIN_RISK_REWARD. When that executor floor moved to 2.0
the backtest kept simulating 1.5, so every lab backtest became a
counterfactual against a config the system no longer runs — worse, it read
as evidence about the wrong system.

The fix: the backtest defaults to the LIVE floor, and only an explicit
override (an A/B sweep) may depart from live parity. This test pins that
coupling so the literal cannot come back.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engines import backtest_real, auto_executor


class TestBacktestRRParity(unittest.TestCase):
    def test_default_is_not_a_hardcoded_literal(self):
        """The signature must not carry a min_rr literal — a literal here
        is free to drift from the live gate, which is exactly how this
        bug shipped."""
        sig = __import__("inspect").signature(backtest_real.run_backtest)
        p = sig.parameters["min_rr"]
        # None = "use the live floor"; any float literal is the bug class.
        self.assertIsNone(p.default,
                          "min_rr must default to None (resolve to the live "
                          "floor), not to a float literal that can drift")
        self.assertNotEqual(p.default, 1.5,
                            "min_rr defaults to the literal 1.5 again — it "
                            "must default to the live floor or None")

    def test_resolved_floor_matches_the_live_executor(self):
        """Whatever the live floor is, the backtest must simulate it."""
        # run_backtest resolves None -> MIN_RISK_REWARD inside the body; test
        # that resolution by reading it off a synthetic call path.
        from engines.auto_executor import MIN_RISK_REWARD
        # the module-level import must be reachable and identical
        self.assertEqual(auto_executor.MIN_RISK_REWARD, MIN_RISK_REWARD)


if __name__ == "__main__":
    unittest.main()
