import unittest
from engines.macro_filter import evaluate_macro_filter


class MacroFilterTests(unittest.TestCase):
    def test_high_impact_event_blocks_trade_inside_blackout(self):
        result = evaluate_macro_filter(
            {"events": [{"impact": "high", "timestamp": "2026-08-28T12:00:00+00:00", "currency": "USD"}]},
            "2026-08-28T11:30:00+00:00",
        )
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "high_impact_news_blackout")

    def test_no_relevant_news_allows_trade(self):
        result = evaluate_macro_filter({"events": []}, "2026-08-28T11:30:00+00:00")
        self.assertTrue(result["allowed"])
