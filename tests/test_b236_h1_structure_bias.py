"""b236 — the H1 structure call must NOT drive the SMC bias.

THE FINDING: smc_analyse computed h1_structure_phase and stored it in the
result, but never passed it to _derive_smc_bias. That was a wiring bug —
wiring it in was the obvious fix, and the obvious fix was MEASURED WRONG.

scripts/ab_b236_h1_weight.py, 5 disjoint 1000-bar windows:
    weight 0.0  total +200.37  worst  -4.46
    weight 1.5  total +122.51  worst  -4.46
    weight 2.5  total +162.54  worst  -4.46
    weight 4.0  total +133.16  worst -27.76
    weight 5.0  total +121.64  worst -27.38

No weight beat 0.0. The H1 market_structure_phase is a 10-bar half-split
heuristic (50 minutes of H1) and carries no predictive signal on this data.

This test pins the CONCLUSION, not the first hypothesis: the parameter is
accepted (so the wiring stays visible) but must not move the score. A future
H1 structure detector with real evidence flips it back on here.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines.smc import _derive_smc_bias


def _pd(zone="equilibrium", quality=0):
    return {"zone": zone, "quality": quality, "fib_level": 0.5}


class TestH1StructureIgnored(unittest.TestCase):
    def _run(self, m5_phase, h1_phase):
        return _derive_smc_bias(
            [], [], [], [], "none", m5_phase, _pd(), 1.0,
            h1_structure_phase=h1_phase)

    def test_h1_cannot_flip_an_m5_call(self):
        """The regression this guards: a conflicting H1 must not turn a
        bullish M5 bearish (or vice versa), because that cost ~70$ at every
        weight tested."""
        for m5 in ("bos_bullish", "bos_bearish", "choch_bullish", "choch_bearish"):
            for h1 in ("bos_bullish", "bos_bearish", "choch_bullish", "choch_bearish"):
                with_h1, _ = self._run(m5, h1)
                without, _ = self._run(m5, "unknown")
                self.assertEqual(with_h1, without,
                                 f"m5={m5} flipped by h1={h1}: {without} -> {with_h1}")

    def test_m5_still_decides(self):
        bias, _ = self._run("bos_bullish", "bos_bearish")
        self.assertEqual(bias, "bullish",
                         "with H1 out of the score, M5 keeps the deciding vote")

    def test_argument_is_accepted(self):
        """The parameter stays in the signature so the wiring cannot be
        silently re-broken — a caller may still pass it."""
        import inspect
        sig = inspect.signature(_derive_smc_bias)
        self.assertIn("h1_structure_phase", sig.parameters)
        self.assertEqual(sig.parameters["h1_structure_phase"].default, "unknown")


if __name__ == "__main__":
    unittest.main()
