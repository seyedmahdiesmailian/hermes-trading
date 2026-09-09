"""b193 contract: the aggressive lane must not bypass the M5 confirmation gate.

Measured (data/backtest/b193_aggressive_lane.json, 153d/45 legs, honest P2
walk, serial one-slot): aggressive entries WITHOUT confirmation win 25% and
average -0.67R/trade, turning deployed serial P&L negative; requiring the
same 3 monotone settled M5 closes flips them to 67% / +0.18R. Live parity
(2026-09-08/09): three unconfirmed aggressive entries lost -95/-45/-24$,
the one confirmed pullback won +19$. These tests pin:
  1. evaluate_monitor_cycle: price above the long zone (premium branch) with
     UNSETTLING/bearish M5 closes must NOT produce market_entry_now;
  2. the same geometry with confirmed (rising) closes still enters;
  3. fail-closed: m5_rows=[] means no aggressive entry (visibility, not luck);
  4. explicit trigger_ok= legacy callers keep old behavior for pullback,
     but m5_ok still gates aggressive (default True only for direct
     decide_execution_action callers).
"""
import unittest
from datetime import datetime, timezone

from engines.orchestrator import evaluate_monitor_cycle


def _dict_rows(closes):
    return [{"time": 1000 + 300 * i, "high": c, "low": c, "close": c}
            for i, c in enumerate(closes)]


def _plan(bias="bullish"):
    # mirrors the 2026-09-09 18:15 live plan: zone 4414.3-4415.9, value band up
    zones = {"long_entry_low": 4414.3, "long_entry_high": 4415.9,
             "short_entry_low": 4417.5, "short_entry_high": 4419.1,
             "value_low": 4415.9, "value_high": 4417.5}
    return {"plan_id": "t-b193", "symbol": "XAUUSD", "bias": bias, "zones": zones,
            "invalidation": 4388.5, "targets": [4425.0, 4440.0],
            "atr": 3.15, "quality": {"smc_confidence": 0.9},
            "execution": {"breakout_trigger": 4419.0}}


NOW = datetime(2026, 9, 9, 18, 15, tzinfo=timezone.utc)
PRICE_ABOVE_ZONE = 4420.5   # premium: > value_high -> aggressive lane (real 18:15 tick)


class TestB193AggressiveGate(unittest.TestCase):
    def test_unconfirmed_rising_market_no_aggressive_entry(self):
        # closes falling = against bullish bias; b187 killed pullback lane,
        # b193 must kill the aggressive lane with the same evidence.
        rows = _dict_rows([4418.6, 4395.1, 4391.2, 4389.7])  # real bars pre-18:15
        out = evaluate_monitor_cycle(_plan(), price=PRICE_ABOVE_ZONE, now=NOW,
                                     m5_rows=rows)
        self.assertNotEqual(out.get("action"), "market_entry_now")

    def test_confirmed_rising_allows_aggressive_entry(self):
        rows = _dict_rows([4389.7, 4391.2, 4395.1, 4418.6])  # monotone up
        out = evaluate_monitor_cycle(_plan(), price=PRICE_ABOVE_ZONE, now=NOW,
                                     m5_rows=rows)
        self.assertEqual(out.get("action"), "market_entry_now")
        self.assertEqual(out.get("execution_style"), "aggressive_premium_entry")

    def test_fail_closed_without_rows(self):
        out = evaluate_monitor_cycle(_plan(), price=PRICE_ABOVE_ZONE, now=NOW,
                                     m5_rows=[])
        self.assertNotEqual(out.get("action"), "market_entry_now")

    def test_pullback_lane_behavior_unchanged(self):
        # in-zone without confirmation stays the b187 wait_for_trigger path
        rows = _dict_rows([4418.6, 4395.1, 4391.2, 4389.7])
        out = evaluate_monitor_cycle(_plan(), price=4415.0, now=NOW, m5_rows=rows)
        self.assertEqual(out.get("action"), "wait_for_trigger")
        self.assertEqual(out.get("reason"), "m5_confirmation_pending")


if __name__ == "__main__":
    unittest.main()
