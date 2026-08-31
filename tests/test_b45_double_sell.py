"""b45 regression: the 14:15/14:30 UTC double-sell incident.

Two bugs let two counter-trend SELLs into a rising market through, net -56.7$:
1. _infer_setup_grade gave grade B to 'mixed' alignment (contradictory TF
   votes) — the quality gate's whole purpose is to reject coin-flips.
2. _performance_and_policy read open-position count from the bridge account
   payload, which has no `positions` field → always 0 → MAX_OPEN_POSITIONS=1
   never fired and a second position stacked on the first.
"""
import unittest
from datetime import datetime, timezone


class TestGradeMixedBlocked(unittest.TestCase):
    def _grade(self, align, trend, regime="range"):
        from engines.auto_executor import _infer_setup_grade
        return _infer_setup_grade({"quality": {
            "alignment": align, "trend_strength": trend, "regime": regime}})

    def test_mixed_is_C_even_with_decent_trend(self):
        # exact 14:15 UTC plan: mixed, trend 2.2, range
        self.assertEqual(self._grade("mixed", 2.2), "C")
        # exact 14:30 UTC plan: mixed, trend 2.47, range
        self.assertEqual(self._grade("mixed", 2.47), "C")

    def test_aligned_B_kept(self):
        # morning winners: aligned, trend 1.67-2.05, breakout_continuation
        self.assertEqual(self._grade("aligned", 1.67, "breakout_continuation"), "B")
        self.assertEqual(self._grade("aligned", 2.05, "breakout_continuation"), "B")

    def test_aligned_A_kept(self):
        self.assertEqual(self._grade("aligned", 3.5, "pullback_continuation"), "A")

    def test_runtime_copy_matches(self):
        import hermes_runtime
        q = {"quality": {"alignment": "mixed", "trend_strength": 2.2, "regime": "range"}}
        self.assertEqual(hermes_runtime._infer_setup_grade(q), "C")


class _FakeBridge:
    def __init__(self, positions):
        self._positions = positions

    def get_positions(self, symbol="XAUUSD"):
        return {"ok": True, "count": len(self._positions), "data": self._positions}

    def get_history_deals(self, symbol="XAUUSD", days=7):
        return {"ok": True, "data": []}


class TestPositionCount(unittest.TestCase):
    def test_policy_sees_real_open_positions(self):
        import hermes_runtime
        fake = _FakeBridge([
            {"ticket": 1, "type": "SELL", "volume": 0.07},
        ])
        acct = {"ok": True, "balance": 5000.0, "equity": 5000.0,
                "margin_free": 5000.0, "margin": 0.0}  # NO positions field (real shape)
        pp = hermes_runtime._performance_and_policy(
            fake, acct, datetime.now(timezone.utc))
        self.assertGreaterEqual(
            pp["account_policy"]["open_positions"], 1,
            "open_positions must reflect the positions endpoint, not the "
            "missing account field (b45 double-entry bug)")


if __name__ == "__main__":
    unittest.main()
