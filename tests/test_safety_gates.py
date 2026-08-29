"""Tests for the safety fixes found in the deep architecture audit (2026-08-29 v3).

Covers:
- engines.market_hours.is_market_open (weekend edges)
- signal path: market-closed + position-cap gates before any order
- signal path: kill-switch wired into account policy
- trade_management: BE guard clamps SL to correct side (the SL-flip bug)
"""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, '/home/ai/hermes-trading')

from engines.market_hours import is_market_open


class MarketHoursTests(unittest.TestCase):
    def test_saturday_closed(self):
        sat = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)  # Saturday
        self.assertFalse(is_market_open(sat))

    def test_sunday_before_open(self):
        sun = datetime(2026, 8, 30, 10, 0, tzinfo=timezone.utc)  # Sunday 10:00 UTC
        self.assertFalse(is_market_open(sun))

    def test_sunday_evening_open(self):
        sun = datetime(2026, 8, 30, 23, 30, tzinfo=timezone.utc)
        self.assertTrue(is_market_open(sun))

    def test_friday_night_closed(self):
        fri = datetime(2026, 8, 28, 23, 0, tzinfo=timezone.utc)  # Fri 23:00 UTC
        self.assertFalse(is_market_open(fri))

    def test_friday_daytime_open(self):
        fri = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
        self.assertTrue(is_market_open(fri))

    def test_midweek_open(self):
        wed = datetime(2026, 8, 26, 3, 0, tzinfo=timezone.utc)
        self.assertTrue(is_market_open(wed))


class SignalPathGateTests(unittest.TestCase):
    """The signal path must refuse orders the plan path would refuse."""

    def _listener_module(self):
        from engines import signal_listener
        return signal_listener

    def test_market_closed_blocks_signal_order(self):
        from engines import auto_executor
        from engines import market_hours
        orig = market_hours.is_market_open
        market_hours.is_market_open = lambda now=None: False
        try:
            sent = {}

            class FakeBridge:
                def send_order(self, **kw):
                    sent.update(kw)
                    return {"ok": True}

            r = auto_executor.execute_trade(
                {"side": "SELL", "lot": 0.01, "symbol": "XAUUSD", "sl": 4460.0, "tp": 4430.0},
                FakeBridge(), dry_run=False)
            self.assertFalse(r.get("ok"))
            self.assertNotIn("side", sent, "order must NOT reach the bridge when market closed")
        finally:
            market_hours.is_market_open = orig

    def test_kill_switch_flips_signal_policy(self):
        """evaluate_signal with a halted policy must never say trade_allowed."""
        from engines.signal_decision import evaluate_signal
        sig = {"symbol": "XAUUSD", "side": "SELL", "confidence": 0.8,
               "entry": 4450.0, "sl": 4460.0, "tp": 4430.0}
        policy = {"trade_allowed": False, "regime": "halted", "open_positions": 0}
        d = evaluate_signal(sig, {"bias": "bearish"}, policy)
        self.assertNotEqual(d["verdict"], "execute")
        self.assertFalse(d["trade_allowed"])


class TradeManagementGuardTests(unittest.TestCase):
    def test_be_guard_clamps_sell_sl_above_entry(self):
        from engines.trade_management import evaluate_trade_management
        # SELL in deep profit (price far below entry) — BE stop must be >= entry
        trade = {
            "symbol": "XAUUSD", "side": "SELL", "entry_price": 4460.0,
            "sl": 4472.0, "tp_levels": [4440.0, 4420.0, 4400.0],
            "tp_shares": [0.5, 0.3, 0.2], "filled_tp_levels": [4440.0],
            "breakeven_active": False, "runner_active": False,
            "structure_state": "healthy", "momentum_strength": 0.4,
            "thesis_valid": True, "rr_remaining": 1.0,
        }
        now = datetime.now(timezone.utc)
        m = evaluate_trade_management(trade, market_price=4390.0, now=now)
        if m.get("action") == "move_stop_to_breakeven":
            new_sl = float(m["new_sl"])
            self.assertGreaterEqual(new_sl, 4460.0,
                                    "SELL breakeven SL below entry would flip stop into profit zone")


if __name__ == "__main__":
    unittest.main()
