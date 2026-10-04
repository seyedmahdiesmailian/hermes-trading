"""b232 — closed-market planning is a wasted cycle (AUDIT-2026-10-04).

Measured on live data: the plan step fired on a closed market anyway — 517
plans on Saturday, 355 on Sunday, every one grade C, all built on a tick that
had been frozen at 4139.19 across 80 consecutive plans. None could ever trade
(execute_trade gates on is_market_open) and none ever changed, so the work was
pure CPU and plan_history churn.

The fix skips only the plan/reassess step. Position management must keep
running on a closed market: a position held over the weekend still needs its
trail and TP manager alive. This test pins both halves of that contract.
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hermetic
from hermes_runtime import cycle


class FakeBridge:
    def __init__(self):
        self.calls = []

    def get_account(self):
        self.calls.append("account")
        return {"ok": True, "balance": 5000.0, "equity": 5000.0,
                "margin": 0.0, "margin_free": 5000.0, "login": 1,
                "server": "test", "currency": "USD"}

    def get_tick(self, symbol="XAUUSD"):
        self.calls.append("tick")
        return {"ok": True, "symbol": symbol, "ask": 4139.52, "bid": 4139.19,
                "last": 4139.19, "volume": 0}

    def get_positions(self, symbol="XAUUSD"):
        self.calls.append("positions")
        return {"ok": True, "data": [], "count": 0}

    def get_rates(self, symbol="XAUUSD", timeframe="M5", count=120):
        self.calls.append("rates")
        # Empty list is enough: the open-market path only needs the call to
        # not blow up; grading is not under test here.
        return {"ok": True, "data": [], "count": 0}


class TestClosedMarketPlanning(unittest.TestCase):
    def setUp(self):
        self._root = hermetic.use_temp_data_root()
        self.addCleanup(hermetic.release)
        self._market_patched = False

    def _run(self, market_open: bool):
        bridge = FakeBridge()
        with patch("hermes_runtime.is_market_open", return_value=market_open):
            r = cycle(bridge,
                      now=datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc))
        return r, bridge

    def test_closed_market_skips_plan_step(self):
        r, bridge = self._run(market_open=False)
        self.assertTrue(r.get("ok"))
        self.assertTrue(r.get("market_closed"))
        self.assertFalse(r.get("will_execute_now"))

    def test_closed_market_still_reads_positions(self):
        """Skipping planning must not skip the position read — the fallback
        manager above depends on it."""
        r, bridge = self._run(market_open=False)
        self.assertIn("positions", bridge.calls)
        self.assertIn("account", bridge.calls)

    def test_open_market_still_plans(self):
        """The gate must not regress the open-market path — the cycle reaches
        the plan step rather than short-circuiting on 'market closed'. With
        empty market data the plan build legitimately errors, so what is pinned
        is that the early return did NOT fire."""
        r, bridge = self._run(market_open=True)
        # the closed-market early return never ran
        self.assertNotIn("market_closed", r)
        # and planning was actually attempted
        self.assertIn("rates", bridge.calls)

    def test_kill_switch_takes_precedence_over_gate(self):
        """The kill switch is checked BEFORE the market gate; a halt must not
        be turned into a harmless 'market closed' reply."""
        bridge = FakeBridge()
        with patch("hermes_runtime.is_market_open", return_value=False), \
                patch("hermes_runtime.check_kill_switch",
                      return_value={"halted": True, "reason": "test"}):
            r = cycle(bridge, now=datetime(2026, 10, 4, 12, 0,
                                           tzinfo=timezone.utc))
        self.assertNotIn("market_closed", r)


if __name__ == "__main__":
    unittest.main()
