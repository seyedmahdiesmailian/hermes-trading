"""Regression pins for the 2026-09-17 two-pass review fix batch.

One class per fixed defect, same discipline as the b1xx family: every fix
cites the report row it closes (reports/PROJECT_REVIEW_FINDINGS_2026-09-17.md)
and pins the BEHAVIOUR that was wrong, not the incidental shape of the fix.

  * A4  notifier/telegram.py wrote a LITERAL backslash-n into
        telegram_messages.log, so the whole message history lived on one
        line and no line-oriented tool (grep/tail/wc) could read it.
  * A5  economic_calendar.get_news_blackout_check had no production caller
        and its OWN blackout semantics (one-sided next-60-min upcoming
        window, no currency filter) that could disagree with the canonical
        macro_filter.evaluate_macro_filter which actually gates entries.
  * SB  smc.evaluate_silver_bullet_setup: the PM "window" spanned two UTC
        hours against a one-hour label, and neither window knew about DST,
        so every winter both windows shifted by an hour.
  * D3  position_daemon labelled every exit by comparing the POLLING-time
        ask to the tracked SL/TP — a price the trade never traded at — so
        modified/gapped exits were reported as the wrong reason.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests import hermetic


class A4TelegramLogNewline(unittest.TestCase):
    """The message log must be line-oriented: one record, one line."""

    def setUp(self):
        self.root = hermetic.use_temp_data_root()
        # no token -> _send returns False right after WRITING the log line,
        # so no network is ever attempted from this test.
        self._tok = os.environ.pop('TELEGRAM_BOT_TOKEN', None)

    def tearDown(self):
        if self._tok is not None:
            os.environ['TELEGRAM_BOT_TOKEN'] = self._tok
        hermetic.release()

    def test_two_messages_two_lines_with_real_newlines(self):
        from notifier.telegram import send_telegram, _log_dir
        send_telegram('FIRST message')
        send_telegram('SECOND message')
        raw = (_log_dir() / 'telegram_messages.log').read_text(encoding='utf-8')
        # the old bug: both records (and every future one) shared ONE line
        # because the separator was the two characters backslash + n
        self.assertNotIn('\\n', raw,
                          'A4 is back: the log writes a literal backslash-n')
        lines = raw.splitlines()
        self.assertEqual(len(lines), 2,
                         f'expected 2 log lines, got {len(lines)}: {lines!r}')
        self.assertTrue(lines[0].endswith('FIRST message'))
        self.assertTrue(lines[1].endswith('SECOND message'))
        self.assertTrue(raw.endswith('\n'), 'log must end on a line boundary')


class A5BlackoutDelegatesToCanonical(unittest.TestCase):
    """Exactly ONE blackout semantics: the macro_filter one."""

    def setUp(self):
        self.root = hermetic.use_temp_data_root()

    def tearDown(self):
        hermetic.release()

    def _cal(self, events):
        return {"source": "test", "events": events}

    def test_no_arg_call_keeps_the_pinned_contract(self):
        # tests/test_signals.py::TestEconomicCalendar pins this shape
        from engines.economic_calendar import get_news_blackout_check
        with patch('engines.economic_calendar.fetch_economic_calendar',
                   return_value=self._cal([])):
            result = get_news_blackout_check()
        self.assertIn("allowed", result)

    def test_delegation_matches_canonical_filter_verdict(self):
        from engines import economic_calendar as ec
        from engines.macro_filter import evaluate_macro_filter
        now = datetime.now(timezone.utc)
        cal = self._cal([
            {"impact": "high", "currency": "USD",
             "date": (now + timedelta(minutes=10)).isoformat()},
            {"impact": "low", "currency": "EUR",
             "date": (now + timedelta(minutes=1)).isoformat()},
        ])
        with patch.object(ec, 'fetch_economic_calendar', return_value=cal):
            got = ec.get_news_blackout_check(now)
        self.assertEqual(got, evaluate_macro_filter(cal, now),
                         'the legacy helper disagrees with the canonical gate')

    def test_past_high_impact_event_inside_window_now_blocks(self):
        # the old one-sided upcoming window was blind to events that JUST
        # fired — exactly the minutes a blackout exists for
        from engines.economic_calendar import get_news_blackout_check
        now = datetime.now(timezone.utc)
        cal = self._cal([{"impact": "high", "currency": "USD",
                          "date": (now - timedelta(minutes=20)).isoformat()}])
        with patch('engines.economic_calendar.fetch_economic_calendar',
                   return_value=cal):
            r = get_news_blackout_check(now)
        self.assertFalse(r["allowed"])
        self.assertEqual(r["reason"], "high_impact_news_blackout")

    def test_unavailable_calendar_fails_closed(self):
        from engines.economic_calendar import get_news_blackout_check
        with patch('engines.economic_calendar.fetch_economic_calendar',
                   return_value={"source": "unavailable", "events": []}):
            r = get_news_blackout_check(datetime.now(timezone.utc))
        self.assertFalse(r["allowed"])
        self.assertEqual(r["reason"], "calendar_unavailable")


class SilverBulletWindow(unittest.TestCase):
    """One-hour windows, anchored to New York local time (DST-proof)."""

    def test_summer_and_winter_both_map_correctly(self):
        from engines.smc import evaluate_silver_bullet_setup as sb
        # EDT (UTC-4): 10:30 NY == 14:30 UTC, 14:30 NY == 18:30 UTC
        self.assertEqual(sb(datetime(2026, 7, 15, 14, 30,
                                     tzinfo=timezone.utc))["window"], "am")
        self.assertEqual(sb(datetime(2026, 7, 15, 18, 30,
                                     tzinfo=timezone.utc))["window"], "pm")
        # EST (UTC-5): 10:30 NY == 15:30 UTC, 14:30 NY == 19:30 UTC
        self.assertEqual(sb(datetime(2026, 1, 15, 15, 30,
                                     tzinfo=timezone.utc))["window"], "am")
        self.assertEqual(sb(datetime(2026, 1, 15, 19, 30,
                                     tzinfo=timezone.utc))["window"], "pm")

    def test_pm_window_is_exactly_one_hour(self):
        # the old code ALSO fired during the 19 UTC hour in summer, i.e.
        # 15:00 NY — an hour the label never claimed
        from engines.smc import evaluate_silver_bullet_setup as sb
        self.assertFalse(sb(datetime(2026, 7, 15, 19, 30,
                                     tzinfo=timezone.utc))["active"])
        # and the old fixed-UTC winter AM hour (14 UTC = 9:00 NY in January)
        # must NOT fire in winter
        self.assertFalse(sb(datetime(2026, 1, 15, 14, 30,
                                     tzinfo=timezone.utc))["active"])

    def test_both_windows_are_one_hour_wide_end_to_end(self):
        from engines.smc import evaluate_silver_bullet_setup as sb
        for month, am_utc, pm_utc in ((7, 14, 18), (1, 15, 19)):  # EDT / EST
            for minute in (0, 59):
                self.assertEqual(
                    sb(datetime(2026, month, 15, am_utc, minute,
                                tzinfo=timezone.utc))["window"], "am")
                self.assertEqual(
                    sb(datetime(2026, month, 15, pm_utc, minute,
                                tzinfo=timezone.utc))["window"], "pm")


class A1ReadsNeverMkdir(unittest.TestCase):
    """A1: the read path must not require a creatable plan root.

    On any box without /home/ai/hermes-trading (DR checkout, CI, a moved
    install) every load_current_plan/load_runtime_state/load_performance_state
    raised PermissionError from ensure_xau_plan_dirs' mkdir BEFORE
    read_json_safe could honestly return its default — the signal lane then
    rejected everything with account_locked:policy_error (reproduced live
    in test_failclosed_news_spread.SignalTickFailClosedTests on a foreign
    checkout: that suite went red for exactly this reason).
    """

    IMPOSSIBLE = "/proc/hermes-a1-no-such-root/xau_plan"  # cannot be created

    def test_reads_on_an_uncreatable_root_return_defaults(self):
        from engines.storage import (load_current_plan, load_performance_state,
                                     load_runtime_state)
        self.assertIsNone(load_current_plan(self.IMPOSSIBLE))
        self.assertEqual(load_runtime_state(self.IMPOSSIBLE), {})
        self.assertEqual(load_performance_state(self.IMPOSSIBLE), {})

    def test_writers_still_create_the_tree(self):
        import tempfile
        from engines.storage import ensure_xau_plan_dirs, save_current_plan
        with tempfile.TemporaryDirectory() as td:
            import os
            root = os.path.join(td, "deep", "xau_plan")
            save_current_plan(root, {"plan_id": "a1", "bias": "bullish"})
            dirs = ensure_xau_plan_dirs(root)
            self.assertTrue(dirs["plan_history_dir"].is_dir())
            self.assertTrue(dirs["current_plan_path"].exists())

    def test_every_load_function_uses_the_pure_path_helper(self):
        # census-style pin: a load*() that goes back to ensure_xau_plan_dirs
        # reinstates the read-path mkdir silently
        import re
        with open(os.path.join(ROOT, "engines", "storage.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        for fn in ("load_current_plan", "load_runtime_state",
                   "load_performance_state"):
            body = re.search(rf"def {fn}\(.*?\n(.*?)(?=\ndef |\Z)", src,
                             re.S).group(1)
            self.assertIn("xau_plan_paths(base_dir)", body,
                          f"{fn} no longer reads via xau_plan_paths")
            self.assertNotIn("ensure_xau_plan_dirs", body,
                             f"{fn} mkdirs again — A1 is back")


class D3ExitLabelFromBrokerFill(unittest.TestCase):
    """The close report's reason must come from the broker's own fill."""

    class Bridge:
        def __init__(self, deals):
            self._deals = deals

        def get_history_deals(self, symbol='XAUUSD', days=7):
            return {'ok': True, 'data': self._deals}

    def _deals(self, out_price):
        # production shape from /api/history/deals: entry 0 = IN, 1 = OUT
        return [
            {'ticket': 1, 'order': 900, 'position_id': 900, 'entry': 0,
             'type': 'BUY', 'price': 4400.0, 'profit': 0.0,
             'commission': -0.30, 'swap': 0.0},
            {'ticket': 2, 'order': 901, 'position_id': 900, 'entry': 1,
             'type': 'SELL', 'price': out_price, 'profit': -12.0,
             'commission': -0.30, 'swap': 0.0},
        ]

    def test_exit_fill_price_reads_the_out_deal(self):
        import position_daemon as pd
        self.assertEqual(pd.exit_fill_price(self.Bridge(self._deals(4388.10)), 900),
                         4388.10)

    def test_fill_absent_or_incomplete_history_returns_none(self):
        import position_daemon as pd
        # no price key on the OUT deal (older bridge shape) -> None
        deals = self._deals(0.0)
        deals[1].pop('price')
        self.assertIsNone(pd.exit_fill_price(self.Bridge(deals), 900))
        # IN-only history (nothing closed yet) -> None
        inonly = {'ok': True, 'data': [self._deals(0.0)[0]]}
        self.assertIsNone(pd.exit_fill_price(self.Bridge(inonly), 900))
        # bridge error -> None, never a crash
        class Boom:
            def get_history_deals(self, *a, **k):
                raise ConnectionError('bridge down')
        self.assertIsNone(pd.exit_fill_price(Boom(), 900))

    def test_partial_close_uses_the_FINAL_out_deal(self):
        import position_daemon as pd
        deals = self._deals(4395.0) + [
            {'ticket': 3, 'order': 902, 'position_id': 900, 'entry': 1,
             'type': 'SELL', 'price': 4381.55, 'profit': 6.0,
             'commission': -0.15, 'swap': 0.0},
        ]
        self.assertEqual(pd.exit_fill_price(self.Bridge(deals), 900), 4381.55)

    def test_close_report_block_prefers_the_fill_over_polling_price(self):
        # source pin (same family as b132/b171): the closed-position report
        # must consult exit_fill_price BEFORE deriving the reason, or the
        # label silently falls back to the polling ask forever
        with open(os.path.join(ROOT, 'position_daemon.py'),
                  encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('fill = exit_fill_price(bridge, int(tkt))', src)
        i_fill = src.index('fill = exit_fill_price(bridge, int(tkt))')
        i_reason = src.index('reason = close_reason(')
        self.assertLess(i_fill, i_reason,
                        'exit_fill_price is no longer consulted before '
                        'close_reason — the D3 label regressed to polling '
                        'prices')

    def test_realized_pnl_usd_behaviour_unchanged_by_the_refactor(self):
        # b44 pins this function; _ticket_deals must not have drifted it
        import position_daemon as pd
        deals = self._deals(4388.10)
        self.assertEqual(pd.realized_pnl_usd(self.Bridge(deals), 900),
                         round(-12.0 - 0.30 - 0.30 + 0.0, 2))
        self.assertIsNone(pd.realized_pnl_usd(
            self.Bridge({'ok': True, 'data': [deals[0]]}), 900))


if __name__ == '__main__':
    unittest.main(verbosity=2)
