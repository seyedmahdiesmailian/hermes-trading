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


class SignalFreshnessGateTests(unittest.TestCase):
    """getUpdates replays the 24h buffer after any daemon downtime —
    a stale signal executed at today's price is a guaranteed loss."""

    def _found_count(self, ages_sec):
        import os
        from datetime import datetime, timezone
        from engines import signal_listener as sl
        now = int(datetime.now(timezone.utc).timestamp())
        msgs = [{"update_id": 100 + i, "chat_id": "-100test", "chat_title": "t",
                 "from": "x", "text": "BUY XAUUSD 4470 SL 4460 TP 4500",
                 "date": now - a} for i, a in enumerate(ages_sec)]
        orig = {"fetch": sl.fetch_new_messages, "log": sl._log_signal}
        sl.fetch_new_messages = lambda: msgs
        sl._log_signal = lambda *a, **k: None
        os.environ["TELEGRAM_SIGNAL_GROUP"] = "-100test"
        try:
            return len(sl.check_signals(bridge=None))
        finally:
            sl.fetch_new_messages, sl._log_signal = orig["fetch"], orig["log"]

    def test_fresh_signal_passes_stale_dropped(self):
        self.assertEqual(self._found_count([60]), 1)          # 1 min old → live
        self.assertEqual(self._found_count([60, 7200]), 1)    # 2 h old → ghost
        self.assertEqual(self._found_count([900]), 0)         # 15 min → dropped


class SessionLiquidityDetectorTests(unittest.TestCase):
    """compute_session_liquidity swept_* was mathematically always False:
    the last-3 bars were compared against a range that included them."""

    def test_sweep_detected_after_fix(self):
        from engines.smc import compute_session_liquidity
        rows = [{"high": 100 + i, "low": 90 + i} for i in range(10)]
        # last bar spikes above the earlier range → swept_high must fire
        rows.append({"high": 120.0, "low": 99.0})
        r = compute_session_liquidity(rows)
        self.assertTrue(r["swept_high"])
        self.assertFalse(r["swept_low"])

    def test_no_sweep_inside_range(self):
        from engines.smc import compute_session_liquidity
        rows = [{"high": 100.0, "low": 90.0}] * 12
        r = compute_session_liquidity(rows)
        self.assertFalse(r["swept_high"])
        self.assertFalse(r["swept_low"])


class CooldownReArmTests(unittest.TestCase):
    """ensure_startup_cooldown must NOT re-arm on normal 15-min cron ticks:
    master is a fresh process every tick, and a 5-min guard armed at tick
    start killed 100% of that tick's entries (2026-08-30 replay: 27/184)."""

    def test_cron_tick_no_rearm_real_restart_arms(self):
        from datetime import datetime, timedelta, timezone
        import tempfile
        from pathlib import Path
        from engines import cooldown as cd
        tmp = Path(tempfile.mkdtemp()) / 'cd.json'
        orig = cd.STATE_FILE
        try:
            cd.STATE_FILE = tmp
            t0 = datetime(2026, 8, 30, 8, 0, tzinfo=timezone.utc)
            s1 = cd.ensure_startup_cooldown(t0)
            s2 = cd.ensure_startup_cooldown(t0 + timedelta(minutes=15))
            self.assertEqual(s1['restart']['until'], s2['restart']['until'])
            self.assertTrue(cd.check_entry_cooldown(
                t0 + timedelta(minutes=16))['allowed'])
            s3 = cd.ensure_startup_cooldown(t0 + timedelta(minutes=90))
            self.assertNotEqual(s1['restart']['until'], s3['restart']['until'])
            self.assertFalse(cd.check_entry_cooldown(
                t0 + timedelta(minutes=91))['allowed'])
            self.assertTrue(cd.check_entry_cooldown(
                t0 + timedelta(minutes=96))['allowed'])
        finally:
            cd.STATE_FILE = orig


class ManagementExecutionTests(unittest.TestCase):
    """evaluate_management_action had ZERO coverage and hardcoded executed=True
    on every bridge call — the b7 bug class on the EXIT side. A rejected
    /api/modify (HTTP 400 retcode_*) reported success, so callers set
    breakeven_active/filled_tp_levels while MT5 still held the ORIGINAL stop:
    a winning trade left unprotected with the system believing otherwise."""

    def _bridge(self, resp, raises=False):
        class B:
            def modify_position(self, ticket, sl=None, tp=None):
                if raises:
                    raise RuntimeError("connection reset")
                return resp
            def partial_close(self, ticket, percent):
                if raises:
                    raise RuntimeError("connection reset")
                return resp
            def close_position(self, ticket):
                if raises:
                    raise RuntimeError("connection reset")
                return resp
        return B()

    def test_rejected_modify_is_not_executed(self):
        from engines.auto_executor import evaluate_management_action
        rej = {"ok": False, "error": "modify_failed_10016"}
        r = evaluate_management_action({"action": "move_stop_to_breakeven",
                                        "new_sl": 4460.0}, self._bridge(rej), 1)
        self.assertFalse(r["executed"])
        self.assertFalse(r["ok"])
        self.assertIn("10016", r["error"])

    def test_accepted_modify_is_executed(self):
        from engines.auto_executor import evaluate_management_action
        ok = {"ok": True, "ticket": 1, "sl": 4460.0, "tp": 0}
        r = evaluate_management_action({"action": "trail_stop",
                                        "new_sl": 4460.0}, self._bridge(ok), 1)
        self.assertTrue(r["executed"])
        self.assertTrue(r["ok"])

    def test_exception_is_not_executed(self):
        from engines.auto_executor import evaluate_management_action
        r = evaluate_management_action({"action": "close_trade_early"},
                                       self._bridge(None, raises=True), 1)
        self.assertFalse(r["executed"])
        self.assertIn("connection reset", r["error"])

    def test_dry_run_never_claims_execution(self):
        from engines.auto_executor import evaluate_management_action
        r = evaluate_management_action({"action": "move_stop_to_breakeven",
                                        "new_sl": 4460.0}, self._bridge({"ok": True}),
                                       1, dry_run=True)
        self.assertFalse(r["executed"])
        self.assertTrue(r.get("dry_run"))

    def test_scale_in_stays_disabled(self):
        """Scale-in needs a NEW order — must never reach the bridge."""
        from engines.auto_executor import evaluate_management_action
        called = []
        class B:
            def modify_position(self, *a, **k): called.append("modify")
            def partial_close(self, *a, **k): called.append("partial")
            def close_position(self, *a, **k): called.append("close")
        r = evaluate_management_action({"action": "scale_in_existing_idea",
                                        "scale_level": 4400.0}, B(), 1)
        self.assertFalse(r["executed"])
        self.assertEqual(r["action"], "scale_in_skipped")
        self.assertEqual(called, [])

    def test_insights_hook_applies_effective_action(self):
        """The insights= hook must rewrite the action it actually executes, so
        a caller can trust res['management'] (kept off live — see defcon doc)."""
        from engines.auto_executor import evaluate_management_action
        from engines.defcon import compute_insights
        ins = compute_insights(loss_streak=2, daily_pnl=-10.0, balance=5000.0,
                               classified=[])
        self.assertFalse(ins["runner_allowed"])
        called = []
        class B:
            def close_position(self, ticket):
                called.append(ticket); return {"ok": True, "ticket": ticket}
            def modify_position(self, *a, **k):
                called.append("modify"); return {"ok": True}
        r = evaluate_management_action({"action": "trail_stop", "new_sl": 4500.0},
                                       B(), 7, insights=ins)
        self.assertEqual(r["action"], "close_runner")
        self.assertEqual(r["management"]["action"], "close_runner")
        self.assertEqual(called, [7])


if __name__ == "__main__":
    unittest.main()
