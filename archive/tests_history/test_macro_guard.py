import unittest
from engines.macro_filter import apply_macro_guard


class MacroGuardTests(unittest.TestCase):
    def test_blocked_macro_guard_blocks_trade_proposal(self):
        proposal = {"blocked": False, "side": "BUY"}
        result = apply_macro_guard(proposal, {"allowed": False, "reason": "high_impact_news_blackout"})
        self.assertTrue(result["blocked"])
        self.assertEqual(result["reason"], "high_impact_news_blackout")

    def test_allowed_macro_guard_preserves_proposal(self):
        proposal = {"blocked": False, "side": "BUY"}
        result = apply_macro_guard(proposal, {"allowed": True, "reason": None})
        self.assertEqual(result, proposal)
