"""Regression tests for the 2026-08-30 critical audit fixes.

1. trades_today must be COMPUTED (daily trade cap was dead code: the field
   was read by the gate but never written).
2. The signal path must run through evaluate_proposal — sizing comes from
   our risk model, never from the channel's raw lot.
"""
import unittest
from datetime import datetime, timezone

# IMPORTANT: force the real module bindings BEFORE any monkeypatching.
# hermes_runtime does `from engines.storage import load_current_plan` at import
# time; if its FIRST import happens inside TestSignalSpreadGate's patch window
# (signal_listener lazily imports hermes_runtime there), it permanently binds
# the patched 2-key stub and every later test that runs a real cycle dies with
# KeyError: 'zones'. Importing it up front makes the leak impossible.
import hermes_runtime  # noqa: F401,E402
import engines.storage  # noqa: F401,E402


class TestTradesToday(unittest.TestCase):
    def test_counts_entry_deals_today(self):
        from engines.risk import compute_performance_state
        now = datetime.now(timezone.utc)
        deals = [
            {'ticket': 1, 'entry': 0, 'time': now.timestamp(), 'profit': 5.0},   # open today
            {'ticket': 2, 'entry': 0, 'time': now.timestamp(), 'profit': -5.0},  # open today
            {'ticket': 3, 'entry': 1, 'time': now.timestamp(), 'profit': 2.0},   # CLOSE, not an entry
            {'ticket': 4, 'entry': 0, 'time': now.timestamp() - 86400 * 3, 'profit': 1.0},  # old
        ]
        perf = compute_performance_state({}, now.date().isoformat(), 5000.0, deals)
        self.assertEqual(perf['trades_today'], 2)

    def test_rolls_over_on_new_day(self):
        from engines.risk import compute_performance_state
        old = {'day': '2020-01-01', 'trades_today': 5, 'daily_pnl': -99.0}
        perf = compute_performance_state(old, '2026-08-30', 5000.0, [])
        self.assertEqual(perf['trades_today'], 0)
        self.assertEqual(perf['daily_pnl'], 0.0)

    def test_monotonic_within_day(self):
        from engines.risk import compute_performance_state
        now = datetime.now(timezone.utc)
        deals = [{'ticket': 1, 'entry': 0, 'time': now.timestamp(), 'profit': 1.0}]
        perf = compute_performance_state(
            {'day': now.date().isoformat(), 'trades_today': 3, 'daily_pnl': 0.0},
            now.date().isoformat(), 5000.0, deals)
        self.assertEqual(perf['trades_today'], 3)  # never decreases mid-day


class TestSignalGateParity(unittest.TestCase):
    """evaluate_proposal must enforce the same gates for signal proposals."""

    def _pol(self):
        return {'trade_allowed': True, 'regime': 'normal',
                'open_positions': 0, 'balance': 5000.0}

    @staticmethod
    def _prop(sl=4460, tp=4435):
        return {'blueprint': {'side': 'SELL', 'entry_price': 4450,
                              'sl': sl, 'tp': tp, 'symbol': 'XAUUSD'},
                'grade': 'B'}

    def test_lot_comes_from_risk_model_not_channel(self):
        import engines.auto_executor as ae
        import engines.cooldown as cd
        real = ae.is_market_open
        real_cd = cd.check_entry_cooldown
        ae.is_market_open = lambda *a, **k: True
        cd.check_entry_cooldown = lambda now=None: {'allowed': True}
        try:
            from engines.auto_executor import evaluate_proposal
            from engines.risk import compute_performance_state
            now = datetime.now(timezone.utc)
            perf = compute_performance_state({}, now.date().isoformat(), 5000.0, [])
            r = evaluate_proposal(self._prop(), self._pol(), perf, {}, None)
            if not r.get('execute'):
                self.fail(f'expected execute, got {r.get("reason")}')
            # 2% of 5000 = $100 risk; 10pt SL = $10/lot → exactly 0.10 lots
            self.assertAlmostEqual(r['command']['lot'], 0.1, places=2)
            self.assertAlmostEqual(r['risk_usd'], 100.0, places=0)
        finally:
            ae.is_market_open = real
            cd.check_entry_cooldown = real_cd

    def test_grade_override_from_proposal(self):
        from engines.auto_executor import evaluate_proposal
        prop = self._prop()
        prop['grade'] = 'C'
        perf = {'day': 'x', 'daily_pnl': 0, 'trades_today': 0, 'loss_streak': 0}
        r = evaluate_proposal(prop, self._pol(), perf, {}, None)
        self.assertFalse(r['execute'])
        self.assertIn('grade_C_below_minimum', r['reasons'])

    def test_daily_cap_blocks(self):
        from engines.auto_executor import evaluate_proposal
        perf = {'day': 'x', 'daily_pnl': 0, 'trades_today': 5, 'loss_streak': 0}
        r = evaluate_proposal(self._prop(), self._pol(), perf, {}, None)
        self.assertFalse(r['execute'])
        self.assertEqual(r['reason'], 'daily_trade_limit')

    def test_position_cap_blocks(self):
        from engines.auto_executor import evaluate_proposal
        pol = self._pol()
        pol['open_positions'] = 2
        perf = {'day': 'x', 'daily_pnl': 0, 'trades_today': 0, 'loss_streak': 0}
        r = evaluate_proposal(self._prop(), pol, perf, {}, None)
        self.assertFalse(r['execute'])
        self.assertEqual(r['reason'], 'position_limit')


class TestPositionCapParity(unittest.TestCase):
    """2026-08-30 audit: live allowed 2 simultaneous positions while
    risk.assess_account_policy said max_positions_allowed=1 and the parity
    backtest models ONE trade at a time — every backtest number (incl. the
    grade-B justification) was computed under a constraint live ignored."""

    def test_live_cap_matches_policy_and_backtest(self):
        from engines.auto_executor import MAX_OPEN_POSITIONS
        from engines.risk import assess_account_policy
        pol = assess_account_policy(5000, 5000, 5000, 0, 0, 0, 0)
        self.assertEqual(MAX_OPEN_POSITIONS, pol['max_positions_allowed'])
        self.assertEqual(MAX_OPEN_POSITIONS, 1)

    def test_second_position_blocked(self):
        from engines.auto_executor import evaluate_proposal
        # NOTE: TestPositionCapParity has no _prop of its own — it must reuse
        # the sibling class's builder (was self._prop() → AttributeError).
        pol = {'trade_allowed': True, 'regime': 'normal',
               'open_positions': 1, 'balance': 5000.0}
        perf = {'day': 'x', 'daily_pnl': 0, 'trades_today': 0, 'loss_streak': 0}
        r = evaluate_proposal(TestSignalGateParity._prop(), pol, perf, {}, None)
        self.assertFalse(r['execute'])
        self.assertEqual(r['reason'], 'position_limit')


class TestSignalSpreadGate(unittest.TestCase):
    """The plan path refuses entries when ask-bid > MAX_ENTRY_SPREAD; the
    signal path must too (news/rollover spikes blow past 2.0$)."""

    def setUp(self):
        # check_signals → kill_switch writes state; without a data root the
        # default /home/ai path PermissionError-s into policy_error and the
        # spread gate never runs.
        from tests import hermetic
        self.root = hermetic.use_temp_data_root()

    def tearDown(self):
        from tests import hermetic
        hermetic.release()

    def _run(self, ask, bid):
        import os
        from datetime import datetime, timezone
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
                # real bridge shape is FLAT: {"ok":true,"ask":...,"bid":...}
                return {"ok": True, "ask": ask, "bid": bid}
            def get_account(self):
                return {"data": {"balance": 5000.0, "equity": 5000.0,
                                 "margin": 0.0, "margin_free": 5000.0,
                                 "positions": 0}}
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
        # hermetic: stub the account-policy helper (the real one WRITES
        # performance_state.json in the production plan dir) and the
        # execution-log appender (would pollute the production journal)
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
        os.environ["TELEGRAM_SIGNAL_GROUP"] = "-100test"
        try:
            res = sl.run_signal_check(FakeBridge(), dry_run=False)
        finally:
            sl.fetch_new_messages, sl._log_signal = orig["fetch"], orig["log"]
            st.load_current_plan, ec.fetch_economic_calendar = orig["plan"], orig["cal"]
            hermes_runtime._performance_and_policy = orig_pp
            st.append_execution_log = orig_exec_log
        return res, calls

    def test_wide_spisk_rejected_before_order(self):
        res, calls = self._run(4451.50, 4450.00)   # 1.50$ spread > 0.60
        ex = res["executions"][0]
        self.assertEqual(ex["verdict"], "skip")
        self.assertTrue(any("spread_too_wide" in r for r in ex["reasons"]),
                        f"expected spread_too_wide, got {ex['reasons']}")
        self.assertEqual(calls["sent"], 0, "no order may reach the bridge")

    def test_normal_spread_not_blocked_by_gate(self):
        res, calls = self._run(4450.10, 4450.00)   # 0.10$ — normal
        ex = res["executions"][0]
        self.assertFalse(any("spread_too_wide" in r for r in ex.get("reasons", [])),
                         f"normal spread must not trip the gate: {ex['reasons']}")


if __name__ == '__main__':
    unittest.main()
