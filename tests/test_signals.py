import unittest
from engines.signal_parser import parse_signal, Signal


class TestSignalParser(unittest.TestCase):
    def test_buy_signal_standard(self):
        sig = parse_signal("XAUUSD BUY 2595.50 SL 2590 TP 2605")
        self.assertTrue(sig.is_valid)
        self.assertEqual(sig.symbol, "XAUUSD")
        self.assertEqual(sig.side, "BUY")
        self.assertAlmostEqual(sig.entry, 2595.50)
        self.assertAlmostEqual(sig.sl, 2590)
        self.assertAlmostEqual(sig.tp, 2605)
        self.assertGreater(sig.confidence, 0.5)

    def test_sell_signal_with_emoji(self):
        sig = parse_signal("🔴 SELL XAUUSD @ 2600 | SL: 2605 | TP: 2585")
        self.assertTrue(sig.is_valid)
        self.assertEqual(sig.side, "SELL")
        self.assertEqual(sig.symbol, "XAUUSD")
        self.assertAlmostEqual(sig.entry, 2600)

    def test_persian_buy(self):
        sig = parse_signal("خرید طلا 2595 استاپ 2590 سود 2605")
        self.assertTrue(sig.is_valid)
        self.assertEqual(sig.symbol, "XAUUSD")
        self.assertEqual(sig.side, "BUY")

    def test_gold_alias(self):
        sig = parse_signal("GOLD BUY 2595 SL 2590 TP 2605")
        self.assertTrue(sig.is_valid)
        self.assertEqual(sig.symbol, "XAUUSD")

    def test_invalid_empty(self):
        sig = parse_signal("")
        self.assertFalse(sig.is_valid)

    def test_no_direction(self):
        sig = parse_signal("XAUUSD 2595")
        self.assertFalse(sig.is_valid)

    def test_rr_computed(self):
        sig = parse_signal("XAUUSD BUY 2595 SL 2590 TP 2605")
        self.assertAlmostEqual(sig.computed_rr, 2.0)

    def test_order_type_limit(self):
        sig = parse_signal("XAUUSD BUY LIMIT 2590 SL 2585 TP 2610")
        self.assertTrue(sig.is_valid)
        self.assertEqual(sig.order_type, "limit")

    def test_silver_symbol(self):
        sig = parse_signal("XAGUSD SELL 31.50 SL 32.00 TP 30.50")
        self.assertTrue(sig.is_valid)
        self.assertEqual(sig.symbol, "XAGUSD")

    def test_multi_tp(self):
        sig = parse_signal("XAUUSD BUY 2595 SL 2590 TP 2605 TP2 2620")
        self.assertTrue(sig.is_valid)
        self.assertAlmostEqual(sig.tp, 2605)
        self.assertAlmostEqual(sig.tp2, 2620)


class TestSignalDecision(unittest.TestCase):
    def test_skip_unsupported_symbol(self):
        from engines.signal_decision import evaluate_signal
        result = evaluate_signal(
            {"symbol": "BTCUSD", "side": "BUY", "entry": 50000, "sl": 49000, "tp": 52000, "confidence": 0.8, "rr_ratio": 2.0, "warnings": []},
            {"bias": "bullish"}, {"trade_allowed": True, "regime": "normal", "open_positions": 0}
        )
        self.assertEqual(result["verdict"], "skip")

    def test_execute_aligned_signal(self):
        from engines.signal_decision import evaluate_signal
        result = evaluate_signal(
            {"symbol": "XAUUSD", "side": "BUY", "entry": 2595, "sl": 2590, "tp": 2610, "confidence": 0.8, "rr_ratio": 3.0, "warnings": []},
            {"bias": "bullish"}, {"trade_allowed": True, "regime": "normal", "open_positions": 0}
        )
        self.assertEqual(result["verdict"], "execute")

    def test_skip_conflict_signal(self):
        from engines.signal_decision import evaluate_signal
        result = evaluate_signal(
            {"symbol": "XAUUSD", "side": "BUY", "entry": 2595, "sl": 2590, "tp": 2610, "confidence": 0.8, "rr_ratio": 3.0, "warnings": []},
            {"bias": "bearish"}, {"trade_allowed": True, "regime": "normal", "open_positions": 0}
        )
        # Autonomous: a signal fighting our own trend read is skipped, not escalated.
        self.assertEqual(result["verdict"], "skip")

    def test_skip_when_account_locked(self):
        from engines.signal_decision import evaluate_signal
        result = evaluate_signal(
            {"symbol": "XAUUSD", "side": "BUY", "entry": 2595, "sl": 2590, "tp": 2610, "confidence": 0.9, "rr_ratio": 3.0, "warnings": []},
            {"bias": "bullish"}, {"trade_allowed": False, "regime": "locked", "open_positions": 0}
        )
        self.assertEqual(result["verdict"], "skip")

    def test_no_sl_blocks_execute(self):
        from engines.signal_decision import evaluate_signal
        result = evaluate_signal(
            {"symbol": "XAUUSD", "side": "BUY", "entry": 2595, "sl": 0, "tp": 2610, "confidence": 0.9, "rr_ratio": 0, "warnings": ["missing_sl"]},
            {"bias": "bullish"}, {"trade_allowed": True, "regime": "normal", "open_positions": 0}
        )
        # Autonomous: a signal missing its stop-loss is skipped outright,
        # never escalated to a human.
        self.assertEqual(result["verdict"], "skip")


class TestEconomicCalendar(unittest.TestCase):
    def test_fetch_doesnt_crash(self):
        from engines.economic_calendar import fetch_economic_calendar
        result = fetch_economic_calendar()
        self.assertIn("events", result)

    def test_blackout_check_doesnt_crash(self):
        from engines.economic_calendar import get_news_blackout_check
        result = get_news_blackout_check()
        self.assertIn("allowed", result)


if __name__ == "__main__":
    unittest.main()
