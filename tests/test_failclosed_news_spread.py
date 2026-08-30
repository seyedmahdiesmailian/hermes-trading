"""b30 — news/spread gates on the signal path must FAIL CLOSED.

Audit found three fail-open holes (all verified against the old code):
1. fetch_economic_calendar() swallowed a total fetch failure as
   {'source':'unavailable','events':[]} and evaluate_macro_filter scored
   that allowed=True → a dead calendar = no news blackout, and the empty
   payload was cached as 'no news' for 6h.
2. evaluate_signal treated the blackout as a -2.0 penalty: a
   high-confidence aligned signal (7.5 → 5.5... but 8.0+ signals stayed
   above 6.0) could still execute straight through FOMC.
3. run_signal_check's staleness+spread block ended in
   `except Exception: pass` → a failed tick read skipped BOTH guards and
   the order went out unchecked.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/home/ai/hermes-trading')
sys.path.insert(0, '/home/ai/hermes-trading/tests')

import hermetic  # noqa: E402  (shared temp-root switch)


class CalendarStalenessTests(unittest.TestCase):
    def setUp(self):
        self.root = hermetic.use_temp_data_root()
        import engines.economic_calendar as ec
        self.ec = ec
        self._ff = ec._fetch_forexfactory
        self._tv = ec._fetch_investing_com

    def tearDown(self):
        self.ec._fetch_forexfactory = self._ff
        self.ec._fetch_investing_com = self._tv
        hermetic.release()

    def _write_cache(self, age_hours: float, events=None):
        import json
        from engines import paths
        data = {"source": "forexfactory",
                "events": events if events is not None else
                [{"title": "CPI", "currency": "USD", "impact": "high",
                  "date": "2026-08-28T12:00:00+00:00"}]}
        data["cached_at"] = (datetime.now(timezone.utc)
                             - timedelta(hours=age_hours)).isoformat()
        f = paths.calendar_cache()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data), encoding="utf-8")

    def test_failed_fetch_does_not_poison_cache(self):
        """A dead fetch must never overwrite a good cache with events=[]."""
        self._write_cache(0.1)
        self.ec._fetch_forexfactory = lambda: None
        self.ec._fetch_investing_com = lambda: None
        self.ec._save_cache({"source": "unavailable", "events": []})
        import json
        from engines import paths
        on_disk = json.loads(paths.calendar_cache().read_text())
        self.assertTrue(on_disk["events"], "empty payload must not replace cache")

    def test_stale_cache_serves_when_fetch_dead(self):
        """Within the staleness budget, last known-good calendar is used."""
        self._write_cache(8.0)  # past 6h refresh, inside 24h budget
        self.ec._fetch_forexfactory = lambda: None
        self.ec._fetch_investing_com = lambda: None
        cal = self.ec.fetch_economic_calendar()
        self.assertTrue(cal.get("events"))
        self.assertTrue(cal.get("stale"))
        self.assertNotEqual(cal.get("source"), "unavailable")

    def test_beyond_budget_is_explicitly_unavailable(self):
        self._write_cache(30.0)  # past HARD_STALE_HOURS
        self.ec._fetch_forexfactory = lambda: None
        self.ec._fetch_investing_com = lambda: None
        cal = self.ec.fetch_economic_calendar()
        self.assertTrue(cal.get("unavailable"))
        self.assertEqual(cal.get("source"), "unavailable")

    def test_no_cache_no_fetch_is_unavailable(self):
        self.ec._fetch_forexfactory = lambda: None
        self.ec._fetch_investing_com = lambda: None
        cal = self.ec.fetch_economic_calendar()
        self.assertTrue(cal.get("unavailable"))


class MacroFilterFailClosedTests(unittest.TestCase):
    def test_unavailable_calendar_blocks(self):
        from engines.macro_filter import evaluate_macro_filter
        r = evaluate_macro_filter(
            {"source": "unavailable", "events": []},
            "2026-08-28T11:30:00+00:00")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["reason"], "calendar_unavailable")

    def test_unavailable_flag_blocks(self):
        from engines.macro_filter import evaluate_macro_filter
        r = evaluate_macro_filter(
            {"source": "forexfactory", "events": [], "unavailable": True},
            "2026-08-28T11:30:00+00:00")
        self.assertFalse(r["allowed"])

    def test_real_calendar_still_allows_when_clear(self):
        from engines.macro_filter import evaluate_macro_filter
        r = evaluate_macro_filter(
            {"source": "forexfactory",
             "events": [{"impact": "high", "currency": "USD",
                         "date": "2026-08-28T18:00:00+00:00"}]},
            "2026-08-28T11:30:00+00:00")
        self.assertTrue(r["allowed"])


class SignalNewsHardBlockTests(unittest.TestCase):
    """Blackout must be a hard skip, not a -2.0 score penalty."""

    def _strong_sig(self):
        return {"symbol": "XAUUSD", "side": "BUY", "entry": 2595, "sl": 2590,
                "tp": 2620, "confidence": 0.9, "rr_ratio": 5.0, "warnings": []}

    def _pol(self):
        return {"trade_allowed": True, "regime": "normal", "open_positions": 0}

    def test_blackout_blocks_even_perfect_signal(self):
        from engines.signal_decision import evaluate_signal
        d = evaluate_signal(self._strong_sig(), {"bias": "bullish"}, self._pol(),
                            macro_filter={"allowed": False,
                                          "reason": "high_impact_news_blackout"})
        self.assertEqual(d["verdict"], "skip")
        self.assertFalse(d["trade_allowed"])

    def test_calendar_unavailable_blocks_signal(self):
        from engines.signal_decision import evaluate_signal
        d = evaluate_signal(self._strong_sig(), {"bias": "bullish"}, self._pol(),
                            macro_filter={"allowed": False,
                                          "reason": "calendar_unavailable"})
        self.assertEqual(d["verdict"], "skip")

    def test_clear_macro_still_executes(self):
        """Control: fail-closed must not become fail-everything."""
        from engines.signal_decision import evaluate_signal
        d = evaluate_signal(self._strong_sig(), {"bias": "bullish"}, self._pol(),
                            macro_filter={"allowed": True, "reason": None})
        self.assertEqual(d["verdict"], "execute")


class SignalTickFailClosedTests(unittest.TestCase):
    """A dead tick read must SKIP the signal — never trade unchecked."""

    def _run(self, tick_mode):
        from engines import signal_listener as sl
        import engines.storage as st
        import engines.economic_calendar as ec
        now = int(datetime.now(timezone.utc).timestamp())
        msgs = [{"update_id": 1, "chat_id": "-100test", "chat_title": "t",
                 "from": "x", "text": "SELL XAUUSD 4450 SL 4440 TP 4420",
                 "date": now - 30}]
        calls = {"sent": 0}

        class FakeBridge:
            def get_tick(self, symbol="XAUUSD"):
                if tick_mode == "raise":
                    raise ConnectionError("bridge down")
                if tick_mode == "empty":
                    return {"ok": True}
                return {"ok": True, "ask": 4450.10, "bid": 4450.00}

            def get_account(self):
                return {"data": {"balance": 5000.0, "equity": 5000.0,
                                 "margin": 0.0, "margin_free": 5000.0}}

            def get_positions(self, symbol="XAUUSD"):
                return {"data": []}

            def get_history_deals(self, symbol="XAUUSD", days=7):
                return {"ok": True, "data": []}

            def send_order(self, **kw):
                calls["sent"] += 1
                return {"ok": True}

        orig = {"fetch": sl.fetch_new_messages, "log": sl._log_signal,
                "plan": st.load_current_plan, "cal": ec.fetch_economic_calendar}
        sl.fetch_new_messages = lambda: msgs
        sl._log_signal = lambda *a, **k: None
        st.load_current_plan = lambda p: {"bias": "bearish", "quality": {}}
        ec.fetch_economic_calendar = lambda *a, **k: {"events": []}
        import hermes_runtime
        orig_pp = hermes_runtime._performance_and_policy
        hermes_runtime._performance_and_policy = lambda b, a, n: {
            'performance_state': {'day': n.date().isoformat(), 'daily_pnl': 0.0,
                                  'trades_today': 0, 'loss_streak': 0,
                                  'recent_closed': []},
            'account_policy': {'trade_allowed': True, 'regime': 'normal',
                               'open_positions': 0, 'balance': 5000.0,
                               'max_positions_allowed': 1}}
        orig_exec_log = st.append_execution_log
        st.append_execution_log = lambda *a, **k: None
        orig_group = os.environ.get("TELEGRAM_SIGNAL_GROUP")
        os.environ["TELEGRAM_SIGNAL_GROUP"] = "-100test"
        try:
            res = sl.run_signal_check(FakeBridge(), dry_run=False)
        finally:
            sl.fetch_new_messages, sl._log_signal = orig["fetch"], orig["log"]
            st.load_current_plan, ec.fetch_economic_calendar = orig["plan"], orig["cal"]
            hermes_runtime._performance_and_policy = orig_pp
            st.append_execution_log = orig_exec_log
            if orig_group is None:
                os.environ.pop("TELEGRAM_SIGNAL_GROUP", None)
            else:
                os.environ["TELEGRAM_SIGNAL_GROUP"] = orig_group
        return res, calls

    def test_tick_exception_skips_no_order(self):
        res, calls = self._run("raise")
        self.assertEqual(calls["sent"], 0, "order must NOT reach bridge on tick error")
        self.assertEqual(res["executions"][0]["verdict"], "skip")
        self.assertIn("fail_closed", str(res["executions"][0]["reasons"]))

    def test_tick_missing_prices_skips_no_order(self):
        res, calls = self._run("empty")
        self.assertEqual(calls["sent"], 0, "order must NOT reach bridge on empty tick")
        self.assertEqual(res["executions"][0]["verdict"], "skip")

    def test_healthy_tick_path_unchanged(self):
        """Control: a good tick + tight spread still reaches the gates."""
        res, calls = self._run("good")
        # Whether it executes depends on downstream gates; what matters is the
        # tick block itself did NOT fail-close a healthy read.
        reasons = str(res["executions"][0].get("reasons", []))
        self.assertNotIn("fail_closed", reasons)


class PlanPathMacroFailClosedTests(unittest.TestCase):
    def test_gate_error_blocks_proposal(self):
        """apply_macro_guard with a blocked filter must kill the proposal."""
        from engines.macro_filter import apply_macro_guard
        p = apply_macro_guard({"blueprint": {}},
                              {"allowed": False, "reason": "macro_gate_error"})
        self.assertTrue(p.get("blocked"))
        self.assertEqual(p["reason"], "macro_gate_error")


if __name__ == '__main__':
    unittest.main()
