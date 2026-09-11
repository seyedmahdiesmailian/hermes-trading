"""b211(a)+(b) — the 2026-09-10 re-review's two filed observations, now shipped.

(a) ENGINES THAT FILTER CALENDAR EVENTS BY CURRENCY USED THE TWO-ARG .get()
    PATTERN: str(ev.get("currency", ev.get("country", ""))) — the default only
    fires when the key is MISSING. When a feed emits currency: null (JSON null
    is common in ForexFactory rows), str(None) = "NONE", which is in neither
    the gold-relevant set {USD,XAU,GOLD,""} nor any country code, so the event
    is silently SKIPPED: a real high-impact FOMC/NFP row with a null currency
    field could never fire the news lock (legacy_guards) nor the entry
    blackout (macro_filter). The fix — `ev.get("currency") or
    ev.get("country") or ""` — is the exact pattern economic_calendar's own
    fetcher already uses (line 125) after normalization. Direction of the
    change is strict protection: null/empty fall through to the next field and
    finally to "" (which PASSES the filter as "unknown = assume gold-relevant",
    the documented fail-safe), so only MORE locks/blackouts can fire, never
    fewer. _is_gold_relevant (the high_impact sort order) shares the
    documented-sync filter and gets the same chain.

(b) engines/signal_listener.run_signal_check read bridge.get_account() TWICE
    per signal: once at the top of the function (the line whose value feeds
    the open-positions overlay 3 lines below the second read) and again as
    the argument to hermes_runtime._performance_and_policy — while the
    overlay on the SAME object used the first read. One policy per signal
    must be built from ONE account read (the b207 single-manager lesson);
    the second argument now reuses account_resp, making both consumers see
    the same snapshot. Positions freshness is unaffected:
    _performance_and_policy re-counts live positions from get_positions
    itself (the b45 fix), so no gate gets a staler position view.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines.legacy_guards import evaluate_news_lock
from engines.macro_filter import evaluate_macro_filter
from engines.economic_calendar import _is_gold_relevant
import hermes_runtime  # b41: module-level so the patch window below can
# never leak a fake binding into a lazily-first-imported hermes_runtime.


def _ev(minutes_ahead=10, impact="high", title="FOMC", **kw):
    t = datetime.now(timezone.utc) + timedelta(minutes=minutes_ahead)
    e = {"title": title, "impact": impact, "date": t.isoformat(),
         "time": "", "forecast": "", "previous": ""}
    e.update(kw)
    return e


def _prod_cal(events):
    return {"source": "forexfactory", "high_impact": events,
            "medium_impact": [], "total_events": len(events)}


class TestNullCurrencyStillProtects(unittest.TestCase):
    """RED-first pins for b211(a): currency=null must behave like currency
    absent -> country -> "" (unknown = gold-relevant), never like "NONE"."""

    def _sell(self):
        return {"side": "SELL", "entry_price": 4450.0, "sl": 4460.0, "atr": 5.0}

    def test_null_currency_fires_news_lock(self):
        cal = _prod_cal([_ev(10, currency=None)])
        g = evaluate_news_lock(self._sell(), 4450.0, cal)
        self.assertIsNotNone(
            g, "high-impact event with currency=null must still lock")
        self.assertIn("news_lock", g["reason"])

    def test_null_currency_fires_macro_blackout(self):
        now = datetime.now(timezone.utc)
        r = evaluate_macro_filter(
            {"source": "forexfactory", "events": [_ev(5, currency=None)]},
            now)
        self.assertFalse(r["allowed"],
                         "currency=null high-impact event must block entries")
        self.assertEqual(r["reason"], "high_impact_news_blackout")

    def test_null_currency_falls_back_to_country(self):
        # informative contradiction: currency null but country is a real
        # non-gold block -> the event is skipped on the country, the fix
        # reads MORE fields than before, never fewer.
        self.assertFalse(_is_gold_relevant({"currency": None, "country": "NZD"}))
        self.assertTrue(_is_gold_relevant({"currency": None}))
        self.assertTrue(_is_gold_relevant({"currency": ""}))

    def test_controls_unchanged(self):
        # USD still fires, NZD still does not, on both consumers.
        self.assertIsNotNone(evaluate_news_lock(
            self._sell(), 4450.0, _prod_cal([_ev(10, currency="USD")])))
        self.assertIsNone(evaluate_news_lock(
            self._sell(), 4450.0, _prod_cal([_ev(10, currency="NZD")])))
        now = datetime.now(timezone.utc)
        self.assertFalse(evaluate_macro_filter(
            {"events": [_ev(5, currency="USD")]}, now)["allowed"])
        self.assertTrue(evaluate_macro_filter(
            {"events": [_ev(5, currency="NZD")]}, now)["allowed"])


class TestSingleAccountReadPerSignal(unittest.TestCase):
    """b211(b): exactly ONE bridge.get_account() read inside run_signal_check
    per batch (plus one per message in the check_signals scorer). Pre-fix the
    execution block read it a second time per signal."""

    def _run(self):
        from engines import signal_listener as sl
        import engines.storage as st
        import engines.economic_calendar as ec
        now = int(datetime.now(timezone.utc).timestamp())
        msgs = [{"update_id": 1, "chat_id": "-100test", "chat_title": "t",
                 "from": "x", "text": "SELL XAUUSD 4450 SL 4440 TP 4420",
                 "date": now - 30}]
        counts = {"account": 0, "sent": 0}

        class FakeBridge:
            def get_tick(self, symbol="XAUUSD"):
                return {"ok": True, "ask": 4450.10, "bid": 4450.00}

            def get_account(self):
                counts["account"] += 1
                return {"data": {"balance": 5000.0, "equity": 5000.0,
                                 "margin": 0.0, "margin_free": 5000.0}}

            def get_positions(self, symbol="XAUUSD"):
                return {"data": []}

            def get_history_deals(self, symbol="XAUUSD", days=7):
                return {"ok": True, "data": []}

            def send_order(self, **kw):
                counts["sent"] += 1
                return {"ok": True}

        orig = {"fetch": sl.fetch_new_messages, "log": sl._log_signal,
                "plan": st.load_current_plan, "cal": ec.fetch_economic_calendar}
        sl.fetch_new_messages = lambda: msgs
        sl._log_signal = lambda *a, **k: None
        st.load_current_plan = lambda p: {"bias": "bearish", "quality": {}}
        ec.fetch_economic_calendar = lambda *a, **k: {"events": []}
        import hermes_runtime
        orig_pp = hermes_runtime._performance_and_policy
        # b41: hermes_runtime from-imports load_current_plan /
        # append_execution_log at module level — patch ITS bindings too, not
        # just engines.storage (signal_listener imports lazily inside its
        # functions so the st patch reaches it; a cycle() call inside the
        # patch window would otherwise read the real bindings).
        orig_hr_plan = hermes_runtime.load_current_plan
        orig_hr_exec = hermes_runtime.append_execution_log
        hermes_runtime.load_current_plan = st.load_current_plan
        hermes_runtime.append_execution_log = st.append_execution_log
        # NOTE: the redundant read b211(b) targets is at the CALL SITE in
        # signal_listener (its argument is evaluated before the patched
        # function runs), so patching here does not hide it.
        hermes_runtime._performance_and_policy = lambda b, a, n: {
            'performance_state': {'day': n.date().isoformat(), 'daily_pnl': 0.0,
                                  'trades_today': 0, 'loss_streak': 0,
                                  'recent_closed': []},
            'account_policy': {'trade_allowed': True, 'regime': 'normal',
                               'open_positions': 0, 'balance': 5000.0,
                               'max_positions_allowed': 1}}
        orig_exec_log = st.append_execution_log
        st.append_execution_log = lambda *a, **k: None
        hermes_runtime.append_execution_log = st.append_execution_log
        orig_group = os.environ.get("TELEGRAM_SIGNAL_GROUP")
        os.environ["TELEGRAM_SIGNAL_GROUP"] = "-100test"
        try:
            res = sl.run_signal_check(FakeBridge(), dry_run=False)
        finally:
            sl.fetch_new_messages, sl._log_signal = orig["fetch"], orig["log"]
            st.load_current_plan, ec.fetch_economic_calendar = orig["plan"], orig["cal"]
            hermes_runtime.load_current_plan = orig_hr_plan
            hermes_runtime.append_execution_log = orig_hr_exec
            hermes_runtime._performance_and_policy = orig_pp
            st.append_execution_log = orig_exec_log
            if orig_group is None:
                os.environ.pop("TELEGRAM_SIGNAL_GROUP", None)
            else:
                os.environ["TELEGRAM_SIGNAL_GROUP"] = orig_group
        return res, counts

    def test_b211b_one_account_read_per_signal_batch(self):
        res, counts = self._run()
        # The signal must have reached the execution block (not failed closed
        # before it) or the count check would be vacuous.
        self.assertEqual(res["signals_found"], 1)
        self.assertNotIn("fail_closed", str(res["executions"][0].get("reasons", [])))
        # 1 read in check_signals (per-message policy #1) + 1 in
        # run_signal_check (the single shared snapshot). Pre-fix: 3.
        self.assertEqual(
            counts["account"], 2,
            "run_signal_check must reuse the one account read (b211(b)); "
            "found " + str(counts["account"]))

    def test_b211b_zero_reads_on_empty_batch(self):
        # anti-vacuity for the harness itself: with no signals the function
        # must not read the account at all.
        import engines.signal_listener as sl
        orig = sl.check_signals
        sl.check_signals = lambda bridge=None: []
        try:
            class Counting:
                n = 0
                def get_account(self):
                    Counting.n += 1
                    return {}
            res = sl.run_signal_check(Counting())
        finally:
            sl.check_signals = orig
        self.assertEqual(res["signals_found"], 0)
        self.assertEqual(Counting.n, 0)


if __name__ == "__main__":
    unittest.main()
