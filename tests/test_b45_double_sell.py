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
    def __init__(self, positions=None, *, positions_resp=None, raise_positions=False):
        self._positions = positions if positions is not None else []
        self._positions_resp = positions_resp
        self._raise_positions = raise_positions

    def get_positions(self, symbol="XAUUSD"):
        if self._raise_positions:
            raise ConnectionError("bridge down")
        if self._positions_resp is not None:
            return self._positions_resp
        return {"ok": True, "count": len(self._positions), "data": self._positions}

    def get_history_deals(self, symbol="XAUUSD", days=7):
        return {"ok": True, "data": []}


class TestPositionCount(unittest.TestCase):
    def setUp(self):
        from tests import hermetic
        self.root = hermetic.use_temp_data_root()

    def tearDown(self):
        from tests import hermetic
        hermetic.release()

    def _acct(self):
        return {"ok": True, "balance": 5000.0, "equity": 5000.0,
                "margin_free": 5000.0, "margin": 0.0}  # NO positions field (real shape)

    def test_policy_sees_real_open_positions(self):
        import hermes_runtime
        fake = _FakeBridge([
            {"ticket": 1, "type": "SELL", "volume": 0.07},
        ])
        pp = hermes_runtime._performance_and_policy(
            fake, self._acct(), datetime.now(timezone.utc))
        self.assertGreaterEqual(
            pp["account_policy"]["open_positions"], 1,
            "open_positions must reflect the positions endpoint, not the "
            "missing account field (b45 double-entry bug)")

    def test_policy_fail_closed_on_positions_exception(self):
        """A dead get_positions must NOT read as 0 (second ticket stacks)."""
        import hermes_runtime
        from engines.auto_executor import MAX_OPEN_POSITIONS
        fake = _FakeBridge(raise_positions=True)
        pp = hermes_runtime._performance_and_policy(
            fake, self._acct(), datetime.now(timezone.utc))
        self.assertGreaterEqual(
            pp["account_policy"]["open_positions"], MAX_OPEN_POSITIONS,
            "unknown count = slot full, never a silent 0")

    def test_policy_fail_closed_on_401(self):
        import hermes_runtime
        from engines.auto_executor import MAX_OPEN_POSITIONS
        fake = _FakeBridge(positions_resp={
            "ok": False, "error": "HTTP_401",
            "data": {"raw": "<html>401 Unauthorized</html>"},
        })
        pp = hermes_runtime._performance_and_policy(
            fake, self._acct(), datetime.now(timezone.utc))
        self.assertGreaterEqual(
            pp["account_policy"]["open_positions"], MAX_OPEN_POSITIONS)

    def test_policy_fail_closed_on_unreadable_shape(self):
        import hermes_runtime
        from engines.auto_executor import MAX_OPEN_POSITIONS
        fake = _FakeBridge(positions_resp={"ok": True, "data": {"a": 1}})
        pp = hermes_runtime._performance_and_policy(
            fake, self._acct(), datetime.now(timezone.utc))
        self.assertGreaterEqual(
            pp["account_policy"]["open_positions"], MAX_OPEN_POSITIONS)

    def test_policy_empty_list_is_genuinely_flat(self):
        """Control: fail-closed must not become fail-everything."""
        import hermes_runtime
        fake = _FakeBridge([])
        pp = hermes_runtime._performance_and_policy(
            fake, self._acct(), datetime.now(timezone.utc))
        self.assertEqual(pp["account_policy"]["open_positions"], 0)


class TestSpreadFailClosed(unittest.TestCase):
    """Plan-path spread gate: unreadable tick used to `except: pass`."""

    def test_healthy_quote_passes(self):
        import hermes_runtime
        self.assertIsNone(hermes_runtime._entry_spread_veto(
            {"ok": True, "ask": 4450.10, "bid": 4450.00}))

    def test_nested_quote_passes(self):
        import hermes_runtime
        self.assertIsNone(hermes_runtime._entry_spread_veto(
            {"ok": True, "data": {"ask": 4450.10, "bid": 4450.00}}))

    def test_wide_spread_blocks(self):
        import hermes_runtime
        v = hermes_runtime._entry_spread_veto(
            {"ok": True, "ask": 4451.50, "bid": 4450.00})
        self.assertEqual(v, 1.5)

    def test_missing_prices_block(self):
        import hermes_runtime
        self.assertEqual(hermes_runtime._entry_spread_veto({"ok": True}),
                         "unreadable")

    def test_non_numeric_prices_block(self):
        import hermes_runtime
        self.assertEqual(
            hermes_runtime._entry_spread_veto({"ask": "n/a", "bid": "n/a"}),
            "unreadable")

    def test_inverted_or_zero_spread_blocks(self):
        import hermes_runtime
        self.assertIsNotNone(hermes_runtime._entry_spread_veto(
            {"ask": 4450.00, "bid": 4450.00}))
        self.assertIsNotNone(hermes_runtime._entry_spread_veto(
            {"ask": 4449.90, "bid": 4450.00}))

    def test_none_tick_blocks(self):
        import hermes_runtime
        self.assertEqual(hermes_runtime._entry_spread_veto(None), "unreadable")


if __name__ == "__main__":
    unittest.main()
