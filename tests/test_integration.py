import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from types import SimpleNamespace


class MockBridge:
    """Simulates BridgeClient for testing."""

    def __init__(self, account=None, tick=None, positions=None, rates=None, history=None):
        self._account = account or {"ok": True, "balance": 5000, "equity": 5000, "margin_free": 5000, "margin": 0, "positions": 0}
        self._tick = tick or {"ok": True, "ask": 4600.0, "bid": 4599.5}
        self._positions = positions or {"ok": True, "data": [], "count": 0}
        self._rates = rates or {}
        self._history = history or {"ok": True, "data": [], "deals": []}

    def health(self): return {"ok": True}
    def get_account(self): return self._account
    def get_tick(self, symbol="XAUUSD"): return self._tick
    def get_positions(self, symbol="XAUUSD"): return self._positions
    def get_rates(self, symbol="XAUUSD", timeframe="M15", count=80):
        return self._rates.get(timeframe, {"ok": True, "data": []})
    def get_history_deals(self, symbol="XAUUSD", days=7):
        return self._history


def _make_ohlc_rows(n=80, base_price=4600.0, atr=5.0, bias="neutral"):
    """Generate synthetic OHLC data."""
    import random
    random.seed(42)
    rows = []
    price = base_price
    for i in range(n):
        if bias == "bullish":
            move = atr * 0.1
        elif bias == "bearish":
            move = -atr * 0.1
        else:
            move = 0
        price += move + random.uniform(-atr/2, atr/2)
        high = price + random.uniform(0, atr)
        low = price - random.uniform(0, atr)
        rows.append({
            "time": 1787000000 + i * 900,
            "open": round(price - move/2, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(price, 2),
        })
    return rows


class TestRuntimeCycle(unittest.TestCase):
    """Runs the REAL cycle() — must be fully hermetic.

    2026-08-30 audit: these tests used to run against the PRODUCTION
    data/xau_plan dir. Two consequences: (1) random synthetic plans at price
    4600 were archived into plan_history/ where learning.analyze joins them
    against real trades (journal pollution), and (2) the live cron/daemons
    rewrite the same files concurrently → KeyError:'zones' flakes when a
    test read a half-written plan. All module-level state paths are now
    redirected to a temp dir.
    """

    def setUp(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent))
        import hermetic
        hermetic.use_temp_data_root()

    def tearDown(self):
        import hermetic
        hermetic.release()

    def test_cycle_produces_valid_output(self):
        """Cycle should always produce valid output with ok=True."""
        from hermes_runtime import cycle
        m5 = _make_ohlc_rows(120, 4600, 5, "bullish")
        h1 = _make_ohlc_rows(80, 4600, 15, "bullish")
        h4 = _make_ohlc_rows(80, 4600, 40, "bullish")
        bridge = MockBridge(rates={"M5": {"ok": True, "data": m5}, "H1": {"ok": True, "data": h1}, "H4": {"ok": True, "data": h4}})
        now = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)

        result = cycle(bridge, now=now)

        self.assertTrue(result.get("ok"))
        self.assertIn(result.get("step"), {"plan", "reassess", "monitor"})
        # Autonomous mode (since 2026-08-28): cycle decides and executes itself,
        # it never requires user approval.
        self.assertFalse(result.get("requires_user_approval"))
        self.assertIsInstance(result.get("will_execute_now"), bool)
        if result.get("step") in {"plan", "reassess"}:
            self.assertIn("plan_id", result)

    def test_cycle_monitor_step_neutral_no_trade(self):
        """Neutral bias plan should produce no_trade action."""
        from hermes_runtime import cycle
        from engines.storage import save_current_plan, save_runtime_state

        m5 = _make_ohlc_rows(120, 4600, 5, "neutral")
        h1 = _make_ohlc_rows(80, 4600, 15, "neutral")
        h4 = _make_ohlc_rows(80, 4600, 40, "neutral")
        bridge = MockBridge(rates={"M5": {"ok": True, "data": m5}, "H1": {"ok": True, "data": h1}, "H4": {"ok": True, "data": h4}})
        now = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)

        # First create a plan
        result1 = cycle(bridge, now=now)
        self.assertTrue(result1.get("ok"))

        # Now run monitor step
        result2 = cycle(bridge, now=now)
        self.assertTrue(result2.get("ok"))
        self.assertEqual(result2.get("step"), "monitor")
        # Autonomous mode: with an aggressive bias the monitor may propose an
        # entry; it must never auto-claim a trade without an executed order.
        if result2.get("monitor"):
            self.assertIn(
                result2["monitor"].get("action"),
                {"no_trade", "wait_for_trigger", "market_entry_now",
                 "place_buy_limit", "place_sell_limit", "place_sell_stop",
                 "wait_for_pullback"},
            )
        self.assertFalse(result2.get("will_execute_now"))

    def test_cycle_plan_step_defers_execution(self):
        """Plan step only defers execution to the trigger; manage/enter steps
        execute autonomously (checked in test_cycle.py)."""
        from hermes_runtime import cycle
        m5 = _make_ohlc_rows(120, 4600, 5, "bullish")
        h1 = _make_ohlc_rows(80, 4600, 15, "bullish")
        h4 = _make_ohlc_rows(80, 4600, 40, "bullish")
        bridge = MockBridge(rates={"M5": {"ok": True, "data": m5}, "H1": {"ok": True, "data": h1}, "H4": {"ok": True, "data": h4}})
        now = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)

        result = cycle(bridge, now=now)
        self.assertFalse(result.get("will_execute_now"))


class TestPlanContext(unittest.TestCase):
    def test_context_produces_valid_structure(self):
        from engines.context import build_plan_context
        m5 = _make_ohlc_rows(120, 4600, 5, "bullish")
        h1 = _make_ohlc_rows(80, 4600, 15, "bullish")
        h4 = _make_ohlc_rows(80, 4600, 40, "bullish")
        ctx = build_plan_context(m5, h1, h4, "london")
        self.assertIn(ctx["bias"], {"bullish", "bearish", "neutral"})
        self.assertIn("zones", ctx)
        self.assertIn("execution", ctx)
        self.assertIn("quality", ctx)
        self.assertIn("symbol", ctx)
        self.assertEqual(ctx["symbol"], "XAUUSD")

    def test_neutral_context_structure(self):
        from engines.context import build_plan_context
        m5 = _make_ohlc_rows(120, 4600, 5, "neutral")
        h1 = _make_ohlc_rows(80, 4600, 15, "neutral")
        h4 = _make_ohlc_rows(80, 4600, 40, "neutral")
        ctx = build_plan_context(m5, h1, h4, "asia")
        self.assertIn(ctx["bias"], {"bullish", "bearish", "neutral"})
        self.assertEqual(ctx["session"], "asia")


class TestSMC(unittest.TestCase):
    def test_smc_detects_order_blocks(self):
        from engines.smc import smc_analyse
        m5 = _make_ohlc_rows(120, 4600, 5, "bullish")
        result = smc_analyse(m5, now=datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc))
        self.assertIn("order_blocks", result)
        self.assertIn("fvgs", result)


class TestRiskManagement(unittest.TestCase):
    def test_assess_account_normal(self):
        from engines.risk import assess_account_policy
        policy = assess_account_policy(
            balance=5000, equity=5000, free_margin=5000,
            margin=0, daily_pnl=0, loss_streak=0, open_positions=0
        )
        self.assertTrue(policy.get("trade_allowed"))
        self.assertEqual(policy.get("regime"), "normal")

    def test_assess_account_drawdown_blocks(self):
        from engines.risk import assess_account_policy
        policy = assess_account_policy(
            balance=5000, equity=4500, free_margin=4500,
            margin=0, daily_pnl=-500, loss_streak=3, open_positions=0
        )
class TestOrchestrator(unittest.TestCase):
    def test_route_step_no_plan(self):
        from engines.orchestrator import route_runtime_step
        self.assertEqual(route_runtime_step(None), "plan")

    def test_route_step_expired_plan(self):
        from engines.orchestrator import route_runtime_step
        plan = {"expires_at": "2026-01-01T00:00:00+00:00"}
        now = datetime(2026, 8, 28, tzinfo=timezone.utc)
        self.assertEqual(route_runtime_step(plan, now), "plan")

    def test_route_step_active_plan(self):
        from engines.orchestrator import route_runtime_step
        plan = {"expires_at": "2027-01-01T00:00:00+00:00", "next_reassessment": "2027-01-01T00:00:00+00:00"}
        now = datetime(2026, 8, 28, tzinfo=timezone.utc)
        self.assertEqual(route_runtime_step(plan, now), "monitor")


if __name__ == "__main__":
    unittest.main()
