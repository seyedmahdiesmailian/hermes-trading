"""C1 (review 2026-09-17, report row 3) — management must survive a missing plan.

position_daemon's live loop gated the ENTIRE management call on
`if not DRY_RUN and plan:` — so a missing/corrupt/empty current_plan.json
silently switched off EVERY protection the watchdog owns (TP ladder,
breakeven, trail, AND the plan-independent news_lock / time_exit guards)
for as long as the file stayed broken. The broker's static SL/TP was the
only thing left, and no ops alert ever fired. The report called it the
third red finding: the management layer fails silent exactly when the
brain that writes plans is the thing that broke.

The fix, pinned here:
  * guards-only management still runs with an empty plan (time_exit and
    news_lock need no plan fields — ATR falls back, calendar re-fetched);
  * the plan-DEPENDENT core (ladder/BE/trail read plan quality/execution)
    is skipped rather than run on guessed data;
  * the live loop no longer requires a plan to call manage_position, and
    the no-plan state is LOUD (source pins: alert on entry, hourly
    reminder, recovery note — b37 dedupe discipline).
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hermetic
import fixtures_bridge as fb

BROKER_OFFSET = fb.BROKER_OFFSET_SEC  # broker clock = UTC+3 (b32/b35)


class RecordingBridge:
    """Just the management endpoints manage_position touches, recorded."""

    def __init__(self, accept=True):
        self.accept = accept
        self.calls = []

    def _r(self, name, **kw):
        self.calls.append((name, kw))
        return {'ok': True, 'retcode': 10009} if self.accept \
            else {'ok': False, 'error': 'retcode_invalid_stops'}

    def modify_position(self, ticket, sl=None, tp=None):
        return self._r('modify_position', ticket=ticket, sl=sl, tp=tp)

    def partial_close(self, ticket, percent):
        return self._r('partial_close', ticket=ticket, percent=percent)

    def close_position(self, ticket):
        return self._r('close_position', ticket=ticket)


def wstate(opened_hours_ago: float = 2.0) -> dict:
    return {
        'side': 'SELL', 'volume': 0.02, 'volume0': 0.02, 'entry': 4450.0,
        'opened_at': (datetime.now(timezone.utc)
                      - timedelta(hours=opened_hours_ago)).isoformat(),
        'mfe': 5.0, 'mae': -1.0, 'sl': 4460.0, 'tp': 4400.0,
        'events': [],
    }


class C1GuardsSurviveMissingPlan(unittest.TestCase):
    def setUp(self):
        # hermetic root and DELIBERATELY no current_plan.json — the C1 state
        self.root = hermetic.use_temp_data_root()
        # the daemon defaults to dry-run; management must actually execute
        # against the fake bridge (same convention as test_daemon_guards)
        import position_daemon as pd
        self._dry = pd.DRY_RUN
        pd.DRY_RUN = False
        # NO NETWORK: without a plan there is no plan-context calendar, so
        # _guard_calendar fetches — patch the fetch with an empty calendar
        # for every test in this class (the news-lock test overrides it
        # with its own patch).
        self._cal = patch('engines.economic_calendar.get_upcoming_events',
                          return_value={'source': 'test', 'high_impact': []})
        self._cal.start()
        self._reset_guard_cache()

    def tearDown(self):
        self._cal.stop()
        import position_daemon as pd
        pd.DRY_RUN = self._dry
        hermetic.release()

    @staticmethod
    def _reset_guard_cache():
        import position_daemon as pd
        pd._guard_cache.update(cal=None, cal_at=0.0, last_eval={}, applied={})

    def _manage(self, bridge, pos, tracked_state, *, age_hours=40.0,
                price=4440.0):
        import position_daemon as pd
        now = datetime.now(timezone.utc)
        pd.manage_position(int(pos['ticket']), pos, {}, tracked_state,
                           bridge, price, now, BROKER_OFFSET)

    def test_time_exit_still_closes_without_any_plan(self):
        """RED against the old loop gate: with no plan the whole manage
        call was skipped, so a 40h-old position sat until the broker's
        static SL/TP decided its fate."""
        import position_daemon as pd
        pos = fb.pos_raw(type='SELL', ticket=99001, entry=4450.0,
                         sl=4460.0, tp=4400.0, age_hours=40.0)
        tracked = {'99001': wstate(opened_hours_ago=40.0)}
        bridge = RecordingBridge()
        self._manage(bridge, pos, tracked, age_hours=40.0)
        closes = [c for c in bridge.calls if c[0] == 'close_position']
        self.assertTrue(closes, f'time_exit never reached the bridge '
                                f'without a plan (calls={bridge.calls})')
        ev = tracked['99001']['events'][-1]
        self.assertIn('close_trade_early', ev)
        self.assertIn('time_exit_4', ev)  # ~40h, not exactly pinned

    def test_news_lock_guard_fires_without_any_plan(self):
        """The priority-1 guard also survives: a FOMC-grade event 10
        minutes away must tighten the stop even with no plan on disk."""
        import position_daemon as pd
        now = datetime.now(timezone.utc)
        pos = fb.pos_raw(type='SELL', ticket=99002, entry=4450.0,
                         sl=4460.0, tp=4400.0, age_hours=2.0)
        tracked = {'99002': wstate(opened_hours_ago=2.0)}
        bridge = RecordingBridge()
        cal = {'source': 'test',
               'high_impact': [{'title': 'FOMC', 'currency': 'USD',
                                'impact': 'high',
                                'date': (now + timedelta(minutes=10)
                                         ).isoformat()}]}
        # _guard_calendar prefers plan context (none here) then fetches
        self._reset_guard_cache()
        # SELL with SL 4460: the lock tightens SL to market+0.5*ATR
        # (4450+2.5=4452.5) — inside the old SL, i.e. protective
        with patch('engines.economic_calendar.get_upcoming_events',
                   return_value=cal):
            self._manage(bridge, pos, tracked, price=4450.0)
        modifies = [c for c in bridge.calls if c[0] == 'modify_position']
        self.assertTrue(modifies, f'news_lock never reached the bridge '
                                  f'without a plan (calls={bridge.calls})')
        self.assertEqual(modifies[0][1]['sl'], 4452.5)

    def test_plan_dependent_core_is_not_run_on_guessed_data(self):
        """No plan -> the ladder/BE/trail core must NOT fire: a young
        position at a TP-clearing price stays untouched (only guards may
        act), because its grade/ladder would be guesses."""
        pos = fb.pos_raw(type='SELL', ticket=99003, entry=4450.0,
                         sl=4460.0, tp=4400.0, age_hours=2.0)
        tracked = {'99003': wstate(opened_hours_ago=2.0)}
        bridge = RecordingBridge()
        # price well past the tracked TP — with a real plan this is a
        # partial_take_profit; without one it must be a no-op
        self._manage(bridge, pos, tracked, price=4380.0)
        self.assertEqual(bridge.calls, [],
                         f'core management ran without a plan: {bridge.calls}')

    def test_young_position_no_news_is_a_quiet_noop(self):
        pos = fb.pos_raw(type='SELL', ticket=99004, entry=4450.0,
                         sl=4460.0, tp=4400.0, age_hours=2.0)
        tracked = {'99004': wstate(opened_hours_ago=2.0)}
        bridge = RecordingBridge()
        self._manage(bridge, pos, tracked, price=4455.0)
        self.assertEqual(bridge.calls, [])


class C1NoPlanStateIsLoud(unittest.TestCase):
    """Source pins for the alerting half (the 5s loop itself is not
    unit-testable; same convention as b132/b171 source pins)."""

    def test_loop_no_longer_gates_management_on_plan(self):
        src = (Path(__file__).resolve().parents[1] / 'position_daemon.py'
               ).read_text(encoding='utf-8')
        self.assertNotIn('if not DRY_RUN and plan:', src,
                         'the C1 gate is back: a missing plan silences ALL '
                         'management again')
        self.assertIn('if not DRY_RUN:', src)

    def test_alert_fires_on_state_entry_with_reminder_and_recovery(self):
        src = (Path(__file__).resolve().parents[1] / 'position_daemon.py'
               ).read_text(encoding='utf-8')
        # entry alert
        self.assertIn("if live and not plan:", src)
        self.assertIn("_no_plan['active'] = True", src)
        # hourly reminder while it lasts (b37 dedupe: not per 5s cycle)
        self.assertIn("_now_ts - _no_plan['at'] >= 3600", src)
        # recovery note when the plan comes back
        self.assertIn("elif plan and _no_plan['active']:", src)

    def test_manage_position_degrades_to_guards_only(self):
        src = (Path(__file__).resolve().parents[1] / 'position_daemon.py'
               ).read_text(encoding='utf-8')
        self.assertIn("if plan:", src)
        self.assertIn("mgmt_core = {'action': 'hold', 'priority': 3}", src,
                      'the no-plan fallback core vanished — guards can no '
                      'longer win the priority merge without a plan')


if __name__ == '__main__':
    unittest.main(verbosity=2)
