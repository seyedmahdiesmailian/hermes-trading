"""b32 — the watchdog (position_daemon) must actually EXECUTE the legacy
guards, and it must do so against a FAKE bridge in tests.

Why this file exists: hermes_runtime.cycle has merged news_lock (priority 1)
and time_exit (priority 2) ahead of the core management chain since the legacy
merge, but in production the runtime's management block is SKIPPED whenever
this watchdog is alive (heartbeat < 60s). The watchdog called
evaluate_trade_management directly and never imported legacy_guards at all —
so the two safety exits had no live executor anywhere. b31 made news_lock
readable, b33 makes the calendar producer deliver events, b32 wires them into
the 5s loop.

These tests replay a blackout window and a stale position against a fake
bridge. They never touch a real order endpoint: the bridge object passed to
manage_position() is always the fake, and FakeBridge raises if anything other
than the read/management endpoints it implements is called.
"""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, '/home/ai/hermes-trading')
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hermetic
import position_daemon as pd


BROKER_OFFSET = 3 * 3600  # CapitalXtend server clock = UTC+3 (measured b32)


class FakeBridge:
    """Records management calls. Implements ONLY what the watchdog uses.

    Deliberately has no open_position/close_position_all — if the code under
    test ever reaches for an entry endpoint, AttributeError fails the test.
    """

    def __init__(self, accept=True, error='retcode_invalid_stops'):
        self.accept = accept
        self.error = error
        self.calls = []

    def _result(self, name, **kw):
        self.calls.append((name, kw))
        if self.accept:
            return {'ok': True, 'retcode': 10009}
        return {'ok': False, 'error': self.error}

    def modify_position(self, ticket, sl=None, tp=None):
        return self._result('modify_position', ticket=ticket, sl=sl, tp=tp)

    def partial_close(self, ticket, percent):
        return self._result('partial_close', ticket=ticket, percent=percent)

    def close_position(self, ticket):
        return self._result('close_position', ticket=ticket)

    @property
    def modifies(self):
        return [c for c in self.calls if c[0] == 'modify_position']

    @property
    def closes(self):
        return [c for c in self.calls if c[0] == 'close_position']


def event(minutes_ahead, impact='high', currency='USD', title='FOMC'):
    t = datetime.now(timezone.utc) + timedelta(minutes=minutes_ahead)
    return {'title': title, 'currency': currency, 'impact': impact,
            'date': t.isoformat(), 'time': '', 'forecast': '', 'previous': ''}


def write_plan(calendar=None, atr=5.0, side='SELL'):
    """current_plan.json in the temp root — the exact production shape.

    TP levels are on the correct side of entry for the side under test:
    evaluate_trade_management treats any price beyond the next unfilled
    target as a hit, so a SELL with targets ABOVE entry would partial-close
    instantly (see the b32 backlog note on plan-shape validation).
    """
    macro = {'allowed': True, 'calendar': calendar or {'high_impact': [],
                                                       'medium_impact': []}}
    tps = [4435.0, 4420.0, 4405.0] if side == 'SELL' else [4465.0, 4480.0, 4495.0]
    plan = {'symbol': 'XAUUSD', 'atr': atr,
            'invalidation': 4460.0 if side == 'SELL' else 4440.0,
            'session': 'London', 'quality': {'trend_strength': 2.0,
                                             'alignment': 'aligned',
                                             'regime': 'trending'},
            'execution': {'tp_levels': tps,
                          'tp_shares': [0.5, 0.3, 0.2]},
            'context': {'macro': macro}}
    from engines import paths
    paths.write_json_atomic(paths.current_plan(), plan, default=str)
    return plan


def position(ticket=98000001, side='SELL', hours_ago=2.0, sl=4460.0,
             offset=BROKER_OFFSET):
    """A live position as the bridge returns it: 'time' is epoch seconds on
    the BROKER clock, so hours_ago is de-rotated before stamping."""
    now = datetime.now(timezone.utc)
    broker_epoch = int((now - timedelta(hours=hours_ago)).timestamp()) + offset
    return {'ticket': ticket, 'type': side, 'volume': 0.02,
            'price_open': 4450.0, 'sl': sl, 'tp': 4600.0, 'profit': 0.0,
            'time': broker_epoch}


def tracked_for(raw, hours_ago=2.0):
    """The watchdog's own view: opened_at = when IT noticed the position."""
    return {str(raw['ticket']): {
        'side': raw['type'], 'volume': raw['volume'], 'entry': raw['price_open'],
        'opened_at': (datetime.now(timezone.utc) - timedelta(hours=hours_ago)
                      ).isoformat(),
        'mfe': 0.0, 'mae': 0.0, 'sl': raw['sl'], 'tp': raw['tp'],
        'last_profit': 0.0, 'events': [], 'filled_tp_levels': [],
        'breakeven_active': False, 'runner_active': True}}


class DaemonGuardTests(unittest.TestCase):
    def setUp(self):
        hermetic.use_temp_data_root()
        pd._guard_cache.update({'cal': None, 'cal_at': 0.0, 'last_eval': {},
                                'applied': {}, 'offsets': [],
                                'prev_tick': (0.0, 0.0)})
        # The daemon runs with HERMES_DRY_RUN=false in production; tests must
        # exercise the SAME path, against the fake bridge.
        self._dry = pd.DRY_RUN
        pd.DRY_RUN = False
        self._tg = pd.send_telegram
        pd.send_telegram = lambda text: None

    def tearDown(self):
        pd.DRY_RUN = self._dry
        pd.send_telegram = self._tg
        hermetic.release()

    def run_mgmt(self, raw, bridge, tracked=None, price=4450.0, now=None):
        tracked = tracked if tracked is not None else tracked_for(raw)
        pd.manage_position(int(raw['ticket']), raw, pd.load_plan(), tracked,
                           bridge, price, now or datetime.now(timezone.utc),
                           BROKER_OFFSET)
        return tracked

    # ── news_lock ──────────────────────────────────────────────────────
    def test_news_lock_fires_in_the_watchdog(self):
        """A blackout window must tighten the live SL through the daemon."""
        write_plan({'high_impact': [event(10)], 'medium_impact': []})
        raw = position()  # SELL @4450, SL 4460
        br = FakeBridge()
        self.run_mgmt(raw, br)
        self.assertEqual(len(br.modifies), 1,
                         'news_lock must reach the broker from the watchdog')
        # SELL, ATR 5 → new SL = 4450 + 2.5 = 4452.5 (tighter, never looser)
        self.assertAlmostEqual(br.modifies[0][1]['sl'], 4452.5)

    def test_news_lock_does_not_claim_breakeven(self):
        """news_lock reuses the move_stop_to_breakeven action name. Marking
        breakeven_active for it would suppress the REAL BE move later."""
        write_plan({'high_impact': [event(10)], 'medium_impact': []})
        raw = position()
        tracked = tracked_for(raw)
        self.run_mgmt(raw, FakeBridge(), tracked)
        self.assertFalse(tracked[str(raw['ticket'])].get('breakeven_active'),
                         'news_lock must not set breakeven_active')

    def test_guard_applies_once_not_every_5s(self):
        write_plan({'high_impact': [event(10)], 'medium_impact': []})
        raw = position()
        br = FakeBridge()
        now = datetime.now(timezone.utc)
        self.run_mgmt(raw, br, now=now)
        self.run_mgmt(raw, br, now=now + timedelta(seconds=5))
        self.run_mgmt(raw, br, now=now + timedelta(seconds=10))
        self.assertEqual(len(br.modifies), 1,
                         'accepted guard must not re-hammer the broker')

    def test_no_news_no_guard_call(self):
        write_plan({'high_impact': [], 'medium_impact': []})
        br = FakeBridge()
        self.run_mgmt(position(), br)
        self.assertEqual(br.calls, [], 'quiet calendar must change nothing')

    # ── time_exit ──────────────────────────────────────────────────────
    def test_time_exit_uses_broker_position_time(self):
        """The watchdog used to know only when IT noticed the position, so a
        restart reset the 36h clock. Broker 'time' must win."""
        write_plan()
        raw = position(hours_ago=38.0)          # true UTC age 38h > 36h
        tracked = tracked_for(raw, hours_ago=0.1)  # daemon just saw it
        br = FakeBridge()
        self.run_mgmt(raw, br, tracked)
        self.assertEqual(len(br.closes), 1,
                         '38h-old position must be closed on time_exit')

    def test_time_exit_de_rotates_the_broker_clock(self):
        """Broker stamps are UTC+3, so reading them as UTC makes a position
        look 3h YOUNGER — time_exit fires 3h LATE. Correction must recover
        the true age."""
        write_plan()
        raw = position(hours_ago=38.0)  # true UTC age 38h
        naive = pd._position_opened_at({'time': raw['time']}, {},
                                       datetime.now(timezone.utc), 0.0)
        corrected = pd._position_opened_at({'time': raw['time']}, {},
                                           datetime.now(timezone.utc),
                                           BROKER_OFFSET)
        now = datetime.now(timezone.utc)
        age_naive = (now - datetime.fromisoformat(naive)).total_seconds() / 3600
        age_corr = (now - datetime.fromisoformat(corrected)).total_seconds() / 3600
        self.assertAlmostEqual(age_corr, 38.0, places=1)
        self.assertAlmostEqual(age_naive, 35.0, places=1)
        self.assertLess(age_naive, age_corr,
                        'uncorrected broker time must make positions look '
                        'younger (late exit), never older')
        # and the corrected path is the one the daemon uses
        br = FakeBridge()
        self.run_mgmt(raw, br, tracked_for(raw, hours_ago=0.1))
        self.assertEqual(len(br.closes), 1)

    def test_uncorrected_clock_would_have_missed_the_exit(self):
        """Regression pin: at 37h true age, the naive UTC reading (34h) is
        under the 36h threshold — the position would have been kept open."""
        from engines.legacy_guards import evaluate_time_exit
        raw = position(hours_ago=37.0)
        now = datetime.now(timezone.utc)
        naive = pd._position_opened_at({'time': raw['time']}, {}, now, 0.0)
        corrected = pd._position_opened_at({'time': raw['time']}, {}, now,
                                           BROKER_OFFSET)
        self.assertNotEqual((evaluate_time_exit({'opened_at': naive}, now) or {})
                            .get('action'), 'close_trade_early',
                            'naive reading should (wrongly) keep it open')
        self.assertEqual(evaluate_time_exit({'opened_at': corrected}, now)
                         ['action'], 'close_trade_early')

    def test_time_exit_falls_back_to_detection_time(self):
        """No broker 'time' (old bridge) → use when we noticed it. That is
        LATER than the real open, so it can only exit early, never late."""
        write_plan()
        raw = position(hours_ago=38.0)
        raw.pop('time')
        tracked = tracked_for(raw, hours_ago=40.0)
        br = FakeBridge()
        self.run_mgmt(raw, br, tracked)
        self.assertEqual(len(br.closes), 1)

    # ── broker clock calibration ───────────────────────────────────────
    def _stream(self, now, offset=BROKER_OFFSET, gap=5.0, n=3):
        """Feed n polls whose tick time advances with the wall clock — the
        only evidence that lets an offset sample be trusted."""
        est = 0.0
        for i in range(n):
            t = now - timedelta(seconds=(n - i) * gap)
            est = pd.broker_utc_offset_sec({'time': int(t.timestamp()) + offset},
                                           t)
        return est

    def test_offset_needs_a_live_stream(self):
        """First poll alone: offset and tick age are indistinguishable, so
        nothing may be estimated yet."""
        now = datetime.now(timezone.utc)
        self.assertEqual(pd.broker_utc_offset_sec(
            {'time': int(now.timestamp()) + BROKER_OFFSET}, now), 0.0)
        # tick stamps are integer seconds → up to 1s of truncation
        self.assertAlmostEqual(self._stream(now), BROKER_OFFSET, delta=1.5)

    def test_offset_from_nested_tick_payload(self):
        now = datetime.now(timezone.utc)
        self._stream(now)
        nested = {'ok': True, 'data': {'time': int(now.timestamp()) + BROKER_OFFSET}}
        self.assertAlmostEqual(pd.broker_utc_offset_sec(nested, now),
                               BROKER_OFFSET, delta=1.5)

    def test_stale_tick_cannot_calibrate(self):
        """A weekend gap / bridge stall / restart onto an old tick must not
        inject hours of offset — that would fire time_exit EARLY."""
        now = datetime.now(timezone.utc)
        stale = {'time': int((now - timedelta(hours=6)).timestamp()) + BROKER_OFFSET}
        self.assertEqual(pd.broker_utc_offset_sec(stale, now), 0.0)
        for tick in ({}, {'time': 0}, {'time': 'garbage'}, {'time': -5}):
            self.assertEqual(pd.broker_utc_offset_sec(tick, now), 0.0,
                             f'invalid tick must yield no estimate: {tick}')

    def test_implausible_offset_rejected(self):
        """A tick implying a >14h offset is a broken stamp, not a timezone."""
        now = datetime.now(timezone.utc)
        self.assertEqual(self._stream(now, offset=20 * 3600), 0.0)

    def test_offset_estimate_is_conservative(self):
        """Residual error must only ever make positions look YOUNGER (late
        exit), never older — the safe direction for an auto-closing guard."""
        now = datetime.now(timezone.utc)
        est = self._stream(now, offset=BROKER_OFFSET)
        self.assertLessEqual(est, BROKER_OFFSET + 1)
        self.assertGreaterEqual(est, 0)

    # ── broker rejection discipline (b7b/b10b) ─────────────────────────
    def test_rejected_guard_is_not_committed_and_retries(self):
        write_plan({'high_impact': [event(10)], 'medium_impact': []})
        raw = position()
        tracked = tracked_for(raw)
        br = FakeBridge(accept=False)
        now = datetime.now(timezone.utc)
        self.run_mgmt(raw, br, tracked, now=now)
        self.assertEqual(len(br.modifies), 1)
        self.assertIn('reject:move_stop_to_breakeven',
                      tracked[str(raw['ticket'])]['_rejected'])
        self.assertFalse(pd._guard_cache['applied'].get(str(raw['ticket'])),
                         'a rejected move must NOT be remembered as applied')
        # after the eval window it retries — the trade is still on its SL
        self.run_mgmt(raw, br, tracked, now=now + timedelta(seconds=61))
        self.assertEqual(len(br.modifies), 2)

    def test_accepted_guard_is_remembered(self):
        write_plan({'high_impact': [event(10)], 'medium_impact': []})
        raw = position()
        br = FakeBridge(accept=True)
        self.run_mgmt(raw, br)
        self.assertTrue(pd._guard_cache['applied'].get(str(raw['ticket'])))

    # ── calendar sourcing ──────────────────────────────────────────────
    def test_plan_calendar_is_used_without_network(self):
        """_guard_calendar prefers plan.context.macro.calendar; economic
        calendar must not be fetched from the 5s loop."""
        write_plan({'high_impact': [event(10)], 'medium_impact': []})
        import engines.economic_calendar as ec
        orig = ec.get_upcoming_events
        ec.get_upcoming_events = lambda **kw: self.fail(
            'watchdog must not fetch the calendar every 5s')
        try:
            br = FakeBridge()
            self.run_mgmt(position(), br)
            self.assertEqual(len(br.modifies), 1)
        finally:
            ec.get_upcoming_events = orig

    def test_guard_cache_pruned_for_dead_tickets(self):
        pd._guard_cache['last_eval'][98000001] = 1.0
        pd._guard_cache['applied']['98000002'] = [('x', 1, 'y')]
        pd.prune_guard_state({98000001})
        self.assertIn(98000001, pd._guard_cache['last_eval'])
        self.assertNotIn('98000002', pd._guard_cache['applied'])

    def test_guard_error_degrades_to_core_management(self):
        """A broken calendar payload must not crash the loop or block the
        core chain — news_lock only tightens, entry gates block separately."""
        write_plan({'high_impact': 'not-a-list'})
        br = FakeBridge()
        self.run_mgmt(position(), br)  # must not raise
        self.assertEqual(br.closes, [])


class CalendarProducerShapeTests(unittest.TestCase):
    """b33 — the guard is only as good as the events feeding it.

    get_upcoming_events() used to bucket by `now + hours_ahead` MINUTES, so
    every event in the window collapsed into one 60-minute bucket and the
    [:10] cap kept 10 arbitrary events: a USD FOMC 20 minutes out could be
    (and was) evicted by AUD/NZD events hours away. The watchdog guard reads
    this bucket, so the eviction silently disabled the news lock.
    """

    def setUp(self):
        hermetic.use_temp_data_root()
        import engines.economic_calendar as ec
        self._orig_fetch = ec.fetch_economic_calendar

    def tearDown(self):
        # b31: these tests monkeypatch fetch_economic_calendar with a lambda;
        # without restoring it, every later test class sees the fake (3 reds
        # in test_failclosed_news_spread under discover ordering).
        import engines.economic_calendar as ec
        ec.fetch_economic_calendar = self._orig_fetch
        hermetic.release()

    def test_window_is_hours_not_minutes(self):
        import engines.economic_calendar as ec
        now = datetime.now(timezone.utc)

        def at(hours):
            return {'title': f'event {hours}', 'currency': 'USD',
                    'impact': 'High', 'forecast': '', 'previous': '',
                    'date': (now + timedelta(hours=hours)).isoformat()}

        events = [at(h) for h in range(0, 25)]
        ec.fetch_economic_calendar = lambda: {'source': 'test',
                                              'events': events,
                                              'fetched_at': now.isoformat()}
        out = ec.get_upcoming_events(hours_ahead=24)
        self.assertGreaterEqual(out['total_events'], 20,
                                'a 24h window must not collapse to ~1h')
        self.assertLessEqual(max(0.0, min(
            (datetime.fromisoformat(e['date']) - now).total_seconds() / 3600
            for e in out['high_impact'])), 24.0)

    def test_usd_events_survive_the_cap(self):
        """The 10-slot cap must never evict a gold-relevant event behind
        AUD/NZD/CAD noise."""
        import engines.economic_calendar as ec
        now = datetime.now(timezone.utc)

        def ev(cur, hours, title):
            return {'title': title, 'currency': cur, 'impact': 'High',
                    'forecast': '', 'previous': '',
                    'date': (now + timedelta(hours=hours)).isoformat()}

        events = ([ev(c, h, f'{c} CPI') for c in ('AUD', 'NZD', 'CAD')
                   for h in range(1, 9)]
                  + [ev('USD', 20, 'FOMC Statement')])
        ec.fetch_economic_calendar = lambda: {'source': 'test',
                                              'events': events,
                                              'fetched_at': now.isoformat()}
        out = ec.get_upcoming_events(hours_ahead=24)
        titles = [e['title'] for e in out['high_impact']]
        self.assertIn('FOMC Statement', titles,
                      'USD high-impact event was evicted by non-USD noise')

    def test_guard_sees_a_realistic_far_event(self):
        """End-to-end: an event 20h out must NOT lock (outside 30min), one
        10min out must. Both must be present in the bucket."""
        write_plan()  # ensures temp root exists
        import engines.economic_calendar as ec
        now = datetime.now(timezone.utc)

        def ev(hours, cur='USD'):
            return {'title': f'CPI {hours}h', 'currency': cur, 'impact': 'High',
                    'forecast': '', 'previous': '',
                    'date': (now + timedelta(hours=hours)).isoformat()}

        ec.fetch_economic_calendar = lambda: {'source': 'test',
                                              'events': [ev(0.17), ev(20)],
                                              'fetched_at': now.isoformat()}
        cal = ec.get_upcoming_events(hours_ahead=24)
        self.assertEqual(len(cal['high_impact']), 2)
        near = {'high_impact': [ev(0.17)], 'medium_impact': []}
        far = {'high_impact': [ev(20)], 'medium_impact': []}
        trade = {'side': 'SELL', 'entry_price': 4450.0, 'sl': 4460.0, 'atr': 5.0}
        from engines.legacy_guards import evaluate_news_lock
        self.assertIsNotNone(evaluate_news_lock(trade, 4450.0, near, now))
        self.assertIsNone(evaluate_news_lock(trade, 4450.0, far, now))


if __name__ == '__main__':
    unittest.main()
