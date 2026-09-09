"""b187 contract: entry trigger requires M5 confirmation, not a zone touch.

Measured (data/backtest/b187_entry_confirmation.json): touching the pullback
zone and entering immediately wins the TP-vs-stop race 25/65 (38%);
waiting for M5_CONFIRM_CLOSES consecutive closes moving WITH the bias
while still in the zone wins 49%, McNemar b01=8 b10=1. These tests pin:
  1. dict-row and tuple-row close extraction (bridge returns dicts;
     the offline backtest cache returns tuples);
  2. monotone-with-bias logic for both sides;
  3. fail-closed: no rows / too few rows / junk rows => never a trigger;
  4. evaluate_monitor_cycle: inside-zone WITHOUT confirmation is
     wait_for_trigger + reason m5_confirmation_pending; with confirmation
     it routes to the entry action as before;
  5. an explicit trigger_ok= argument still bypasses (legacy callers).
"""
import unittest
from datetime import datetime, timezone

from engines.orchestrator import (M5_CONFIRM_CLOSES, evaluate_monitor_cycle,
                                  m5_confirmation, _closes)


def _dict_rows(closes):
    return [{"time": 1000 + 300 * i, "high": c, "low": c, "close": c}
            for i, c in enumerate(closes)]


def _tuple_rows(closes):
    # backtest cache layout: (time, high, low, close)
    return [(1000 + 300 * i, c, c, c) for i, c in enumerate(closes)]


def _plan(bias, lo, hi):
    # Production plans always carry all four zone keys (classify_price_location
    # compares them unconditionally); use real values, None only when the
    # point of the test is the missing-row path.
    zones = {"long_entry_low": lo, "long_entry_high": hi,
             "short_entry_low": lo + 40, "short_entry_high": lo + 45,
             "value_low": lo - 10, "value_high": hi + 10}
    if bias == "bearish":
        zones["short_entry_low"], zones["short_entry_high"] = lo, hi
        zones["long_entry_low"], zones["long_entry_high"] = lo - 45, lo - 40
        zones["value_low"], zones["value_high"] = lo - 10, hi + 10
    return {"plan_id": "t-b187", "symbol": "XAUUSD", "bias": bias, "zones": zones,
            "invalidation": lo - 5 if bias == "bullish" else hi + 5,
            "targets": [lo + 8, lo + 20] if bias == "bullish" else [hi - 8, hi - 20],
            "atr": 4.0, "execution": {}, "quality": {}}


NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


class ClosesExtraction(unittest.TestCase):
    def test_dict_rows(self):
        self.assertEqual(_closes(_dict_rows([1, 2, 3]), 3), [1.0, 2.0, 3.0])

    def test_tuple_rows(self):
        self.assertEqual(_closes(_tuple_rows([1, 2, 3]), 3), [1.0, 2.0, 3.0])

    def test_junk_fails_closed(self):
        self.assertEqual(_closes(_dict_rows([1, None, 3]), 3), [])
        self.assertEqual(_closes([{"close": 5}] * M5_CONFIRM_CLOSES, 3), [5.0] * 3)
        self.assertEqual(_closes(_dict_rows([1, 2]), 3), [])
        self.assertEqual(_closes([], 3), [])
        self.assertEqual(_closes(None, 3), [])


class ConfirmationLogic(unittest.TestCase):
    def test_bullish_needs_rising_closes(self):
        rising = _dict_rows([100, 101, 102])
        self.assertTrue(m5_confirmation(rising, "bullish"))
        self.assertFalse(m5_confirmation(rising, "bearish"))

    def test_bearish_needs_falling_closes(self):
        falling = _dict_rows([102, 101, 100])
        self.assertTrue(m5_confirmation(falling, "bearish"))
        self.assertFalse(m5_confirmation(falling, "bullish"))

    def test_flat_or_neutral_bias_fails_closed(self):
        flat = _dict_rows([100, 100, 100])
        self.assertFalse(m5_confirmation(flat, "bullish"))
        self.assertFalse(m5_confirmation(_dict_rows([100, 101, 102]), "neutral"))
        self.assertFalse(m5_confirmation([], "bullish"))

    def test_tuple_layout_matches_dict_layout(self):
        closes = [100, 101, 102]
        self.assertEqual(m5_confirmation(_tuple_rows(closes), "bullish"),
                         m5_confirmation(_dict_rows(closes), "bullish"))


class MonitorRouting(unittest.TestCase):
    def test_zone_touch_without_confirmation_waits(self):
        plan = _plan("bullish", 100, 101)
        # falling closes while price sits in the long zone = falling knife
        d = evaluate_monitor_cycle(plan, price=100.5, now=NOW,
                                   m5_rows=_dict_rows([103, 102, 101]))
        self.assertEqual(d["action"], "wait_for_trigger")
        self.assertEqual(d["reason"], "m5_confirmation_pending")

    def test_zone_touch_with_confirmation_enters(self):
        plan = _plan("bullish", 100, 101)
        rising = _dict_rows([99, 100, 101])
        d = evaluate_monitor_cycle(plan, price=100.5, now=NOW, m5_rows=rising)
        self.assertNotEqual(d.get("reason"), "m5_confirmation_pending")
        self.assertIn(d["action"], {"market_entry_now", "wait_for_trigger"})
        # quality gate may still downgrade to wait, but NOT for confirmation
        if d["action"] == "wait_for_trigger":
            self.assertEqual(d.get("reason"), "quality_filter")

    def test_missing_rows_fail_closed_inside_zone(self):
        plan = _plan("bearish", 100, 101)
        d = evaluate_monitor_cycle(plan, price=100.5, now=NOW, m5_rows=None)
        self.assertEqual(d["reason"], "m5_confirmation_pending")

    def test_explicit_trigger_ok_bypasses(self):
        plan = _plan("bullish", 100, 101)
        d = evaluate_monitor_cycle(plan, price=100.5, now=NOW,
                                   trigger_ok=False, m5_rows=None)
        self.assertNotEqual(d.get("reason"), "m5_confirmation_pending")

    def test_outside_zone_unchanged(self):
        plan = _plan("bullish", 100, 101)
        d = evaluate_monitor_cycle(plan, price=500, now=NOW, m5_rows=None)
        self.assertNotEqual(d.get("reason"), "m5_confirmation_pending")


if __name__ == "__main__":
    unittest.main()
