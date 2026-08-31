"""b37 — the fallback path's guard merge must never fail SILENTLY.

Why this file exists: hermes_runtime.cycle() merged news_lock(1) and
time_exit(2) over the core management chain inside

    try:
        ...
    except Exception:
        pass

so ANY error in that block dropped both safety guards with no log, no
metric, and no trace in the report — while position_daemon at least logged
'guard eval error'. b30 closed this exact hole class on the ENTRY side;
this is the management side.

And the hole was not theoretical. The calendar lookup was

    plan.get('context', {}).get('macro', {}).get('calendar')

and the monitor path writes that key literally as None whenever
analyze_macro() degrades (`plan['context']['macro'] = macro_snap` with
macro_snap=None). None.get → AttributeError → swallowed → the 36h time_exit
and the pre-news SL tighten BOTH vanish for that position, every cycle,
forever. Reproduced end-to-end in
test_broken_macro_snapshot_still_time_exits (RED against the old code).

Also pinned here:
  * the guard outcome is LOUD — logs/runtime.log + payload['guards'] + the
    Telegram brief (the runtime had no logger at all before b37);
  * news_lock gets a calendar even when the plan carries none (the
    plan/reassess path never writes context.macro at all);
  * b35's opened_at priority chain survives the refactor;
  * hermes_master.alert_degraded_guards fires when degraded, stays silent
    when healthy;
  * a source-level tripwire so the merge can never be re-wrapped in a bare
    `except Exception: pass`.

Every test patches the calendar feed — no test in this file touches network.
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hermetic
from test_runtime_fallback_management import (ManageBridge, TICK_S,
                                              production_plan, pos_raw)

# b41: this file patches notifier.telegram.send_ops, and hermes_master does
# `from notifier.telegram import send_ops` at MODULE level. If hermes_master's
# FIRST import happened inside a patch window it would permanently bind the
# fake. Importing it up front captures the real binding before any patch.
import hermes_master  # noqa: E402,F401

TICKET = 99001
DEAD_CAL = {'source': 'unavailable', 'events': []}


def patch_calendar(result):
    """Replace engines.economic_calendar.get_upcoming_events for the test.
    hermes_runtime imports it lazily INSIDE the helper, so patching the
    module attribute is enough. Returns the list of calls made."""
    import engines.economic_calendar as ec
    real = ec.get_upcoming_events
    calls = []

    def fake(**kw):
        calls.append(kw)
        if isinstance(result, Exception):
            raise result
        return result

    ec.get_upcoming_events = fake

    def restore():
        ec.get_upcoming_events = real
    return restore, calls


def aged_position(hours: float = 40):
    """A SELL opened `hours` ago on the BROKER clock (UTC+3), priced so the
    core management chain says 'hold' — only a guard can act."""
    broker_epoch = int(datetime.now(timezone.utc).timestamp()) + 3 * 3600 - hours * 3600
    return {'ticket': TICKET, 'symbol': 'XAUUSD', 'type': 'SELL',
            'volume': 0.02, 'price_open': 4450.0, 'sl': 4460.0, 'tp': 4600.0,
            'price_current': 4430.0, 'profit': 0.0, 'swap': 0.0,
            'comment': '', 'time': broker_epoch}


def hold_plan(**overrides):
    """Production-shaped plan whose TP/scale levels are unreachable, so
    evaluate_trade_management returns hold and any action is unambiguously
    from the legacy guard merge."""
    plan = production_plan('SELL')
    plan['execution']['tp_levels'] = [4300.0]     # SELL hit needs bid<=4300
    plan['invalidation'] = 4460.0
    plan.update(overrides)
    return plan


def broken_macro_plan():
    """EXACTLY what the monitor path persists when analyze_macro() degrades:
    context.macro = None (hermes_runtime: plan['context']['macro']=macro_snap).
    """
    plan = hold_plan()
    plan['context'] = {'macro': None, 'smc': {}}
    return plan


def imminent_news_calendar(minutes: int = 10):
    when = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
    return {'source': 'forexfactory',
            'high_impact': [{'title': 'FOMC Rate Decision', 'impact': 'high',
                             'currency': 'USD', 'timestamp': when}],
            'medium_impact': [], 'total_events': 110, 'window_hours': 24}


class _CalendarIsolated(unittest.TestCase):
    """Shared: temp state tree + a fake calendar feed (never network)."""

    cal_result = DEAD_CAL

    def setUp(self):
        hermetic.use_temp_data_root()
        restore, calls = patch_calendar(self.cal_result)
        self.addCleanup(restore)
        self.cal_calls = calls
        import hermes_runtime as hr
        self.hr = hr
        from engines import paths
        self.paths = paths


class GuardMergeUnitTests(_CalendarIsolated):
    """evaluate_legacy_guards in isolation — shapes, status, no raises."""

    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc)
        self.p = self.hr._pos_obj(pos_raw('SELL'))
        self.trade = {'side': 'SELL', 'entry_price': 4450.0, 'sl': 4460.0,
                      'tp_levels': [4300.0], 'thesis_valid': True}
        self.hold = {'action': 'hold', 'priority': 3,
                     'reason': 'no_management_trigger'}

    def _guards(self, plan, broker_offset=None, wd_entry=None, p=None):
        return self.hr.evaluate_legacy_guards(
            dict(self.hold), plan, self.trade, p or self.p, 4430.0, self.now,
            broker_offset, wd_entry=wd_entry)

    # ── the swallowed-exception battery ────────────────────────────────
    def test_never_raises_on_any_plan_shape(self):
        """Whatever a corrupted/legacy plan looks like, the merge returns
        (management, status) — never propagates, never silently drops."""
        for plan in [broken_macro_plan(),
                     {'context': {'macro': 'unavailable'}, 'quality': {}},
                     {'context': None, 'quality': {}},
                     {'context': {}, 'quality': None},
                     {'context': {'macro': {'calendar': 42}}, 'quality': {}},
                     {'context': {'macro': {'calendar': [{'impact': 'high'}]}}},
                     {}]:
            m, st = self._guards(plan)
            self.assertIsInstance(m, dict)
            self.assertIn(st.get('state'),
                          {'none', 'applied', 'error', 'calendar_unavailable'},
                          f"no status for shape {plan}: {st}")

    def test_broken_macro_shape_still_runs_the_guards(self):
        """macro=None made the OLD inline lookup raise AttributeError. The new
        lookup is shape-safe, so time_exit still fires instead of being
        dropped along with news_lock."""
        p = self.hr._pos_obj(aged_position(40))
        m, st = self._guards(broken_macro_plan(), p=p)
        self.assertEqual(m['action'], 'close_trade_early',
                         f"time_exit must survive macro=None: {m} {st}")
        self.assertEqual(st['state'], 'applied')

    def test_error_state_is_named_and_detailed(self):
        """If a guard itself explodes, the status says so with the reason."""
        real = self.hr.evaluate_news_lock
        self.addCleanup(lambda: setattr(self.hr, 'evaluate_news_lock', real))

        def boom(*a, **k):
            raise RuntimeError('calendar payload is garbage')

        self.hr.evaluate_news_lock = boom
        m, st = self._guards(hold_plan())
        self.assertEqual(m['action'], 'hold', 'must fall back to core chain')
        self.assertEqual(st['state'], 'error')
        self.assertIn('calendar payload is garbage', st['detail'])

    def test_error_is_written_to_the_runtime_log(self):
        """b37 minimum fix: log it. The runtime had NO logger before."""
        real = self.hr.evaluate_news_lock
        self.addCleanup(lambda: setattr(self.hr, 'evaluate_news_lock', real))

        def boom(*a, **k):
            raise RuntimeError('kaboom')

        self.hr.evaluate_news_lock = boom
        self._guards(hold_plan())
        logf = self.paths.logs_dir() / 'runtime.log'
        self.assertTrue(logf.exists(), 'runtime.log must be written')
        text = logf.read_text(encoding='utf-8')
        self.assertIn('guard eval error', text)
        self.assertIn('kaboom', text)
        self.assertIn(str(TICKET), text)

    # ── calendar sourcing ──────────────────────────────────────────────
    def test_calendar_comes_from_the_plan_when_present(self):
        plan = hold_plan()
        plan['context'] = {'macro': {'calendar': imminent_news_calendar()}}
        cal, src = self.hr._guard_calendar(plan, self.now)
        self.assertEqual(src, 'plan')
        self.assertTrue(cal['high_impact'])
        self.assertEqual(self.cal_calls, [], 'must not refetch a good plan cal')

    def test_stale_plan_calendar_is_flagged(self):
        plan = hold_plan()
        plan['context'] = {'macro': {'calendar': {'high_impact': [],
                                                 'stale': True,
                                                 'total_events': 5}}}
        cal, src = self.hr._guard_calendar(plan, self.now)
        self.assertEqual(src, 'plan_stale')

    def test_unavailable_plan_calendar_falls_through_to_fetch(self):
        """b30 discipline: source='unavailable' is NOT 'no news'."""
        restore, calls = patch_calendar({'source': 'forexfactory',
                                         'high_impact': [], 'total_events': 110})
        self.addCleanup(restore)
        plan = hold_plan()
        plan['context'] = {'macro': {'calendar': {'source': 'unavailable',
                                                 'events': []}}}
        cal, src = self.hr._guard_calendar(plan, self.now)
        self.assertEqual(src, 'fetched')
        self.assertEqual(len(calls), 1)

    def test_dead_calendar_is_reported_as_unavailable(self):
        cal, src = self.hr._guard_calendar({'context': {}}, self.now)
        self.assertIsNone(cal)
        self.assertEqual(src, 'unavailable')

    def test_calendar_module_crash_is_caught_not_propagated(self):
        restore, _ = patch_calendar(RuntimeError('feed socket reset'))
        self.addCleanup(restore)
        cal, src = self.hr._guard_calendar({'context': {}}, self.now)
        self.assertIsNone(cal)
        self.assertEqual(src, 'unavailable')
        text = (self.paths.logs_dir() / 'runtime.log').read_text(encoding='utf-8')
        self.assertIn('guard calendar failed', text)

    def test_empty_but_real_bucket_is_not_called_unavailable(self):
        """'No high-impact news today' (total_events>0) is a HEALTHY calendar;
        crying wolf every quiet day would make the alert worthless."""
        restore, _ = patch_calendar({'source': 'forexfactory',
                                     'high_impact': [], 'total_events': 110})
        self.addCleanup(restore)
        cal, src = self.hr._guard_calendar({'context': {}}, self.now)
        self.assertEqual(src, 'fetched')

    # ── b35 chain preserved through the refactor ───────────────────────
    def test_opened_at_priority_calibrated_epoch_wins(self):
        now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
        epoch = int((now - timedelta(hours=40)).timestamp()) + 3 * 3600
        p = self.hr._pos_obj({**aged_position(), 'time': epoch})
        wd = {'opened_at': (now - timedelta(hours=1)).isoformat()}  # says 1h
        m, st = self.hr.evaluate_legacy_guards(
            dict(self.hold), hold_plan(), self.trade, p, 4430.0, now,
            3 * 3600, wd_entry=wd)
        self.assertEqual(m['action'], 'close_trade_early')
        self.assertIn('time_exit_40h', m['reason'])

    def test_opened_at_falls_back_to_watchdog_detection_time(self):
        now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
        p = self.hr._pos_obj({**aged_position(), 'time': None})
        wd = {'opened_at': (now - timedelta(hours=38)).isoformat()}
        m, st = self.hr.evaluate_legacy_guards(
            dict(self.hold), hold_plan(), self.trade, p, 4430.0, now, None,
            wd_entry=wd)
        self.assertEqual(m['action'], 'close_trade_early')
        self.assertIn('time_exit_38h', m['reason'])

    def test_fresh_position_is_left_alone(self):
        now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
        p = self.hr._pos_obj({**aged_position(), 'time': int(now.timestamp())})
        m, st = self.hr.evaluate_legacy_guards(
            dict(self.hold), hold_plan(), self.trade, p, 4430.0, now, 0.0)
        self.assertEqual(m['action'], 'hold')
        self.assertNotEqual(st['state'], 'error')


class FallbackCycleIntegrationTests(_CalendarIsolated):
    """The REAL cycle() with a stale watchdog heartbeat — production shape."""

    def setUp(self):
        super().setUp()
        from engines.storage import save_current_plan, save_runtime_state
        self.save_current_plan = save_current_plan
        save_runtime_state(self.paths.plan_dir(), {})
        self.hb = self.paths.plan_dir() / 'watchdog_heartbeat'
        self.hb.write_text((datetime.now(timezone.utc)
                            - timedelta(minutes=10)).isoformat())

    def _run(self, plan, positions, accept=True):
        self.save_current_plan(self.paths.plan_dir(), plan)
        bridge = ManageBridge(positions, TICK_S, accept=accept)
        from hermes_runtime import cycle
        return bridge, cycle(bridge, dry_run=False)

    def test_broken_macro_snapshot_still_time_exits(self):
        """RED against the old code: context.macro=None (written by the
        monitor path itself) made the calendar lookup raise, the bare
        `except Exception: pass` ate it, and a 40h-old position — past the
        36h limit — was never closed, while the cycle reported a clean
        'monitor' step with both guards silently off."""
        bridge, result = self._run(broken_macro_plan(), [aged_position(40)])
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(result.get('step'), 'manage',
                         f"time_exit must fire despite macro=None: {result}")
        self.assertEqual(result['management']['action'], 'close_trade_early')
        self.assertIn('time_exit', result['management']['reason'])
        self.assertEqual([c[0] for c in bridge.mgmt_calls], ['close_position'])

    def test_guard_status_is_in_the_manage_payload(self):
        _, result = self._run(broken_macro_plan(), [aged_position(40)])
        guards = result.get('guards') or {}
        self.assertEqual(guards.get('state'), 'applied')
        self.assertEqual(guards.get('calendar'), 'unavailable')

    def test_news_lock_fires_on_the_fallback_path(self):
        """build_live_plan never writes context.macro, so the guard merge used
        to be handed None and news_lock could not fire at all. With the
        calendar fallback it tightens the SL before FOMC.

        The plan is deliberately stripped of its calendar (the shared
        production_plan fixture carries an EMPTY one, which is a legitimate
        'no news' answer and would short-circuit the fetch) — this test is
        about the FETCH path, i.e. exactly the live plan shape."""
        restore, _ = patch_calendar(imminent_news_calendar())
        self.addCleanup(restore)
        plan = hold_plan()
        plan['context'] = {}          # what build_live_plan actually produces
        bridge, result = self._run(plan, [pos_raw('SELL')])
        self.assertEqual(result.get('step'), 'manage', result)
        self.assertEqual(result['management']['action'], 'move_stop_to_breakeven')
        self.assertIn('news_lock', result['management']['reason'])
        self.assertEqual([c[0] for c in bridge.mgmt_calls], ['modify_position'])
        self.assertEqual(result['guards']['calendar'], 'fetched')

    def test_guard_error_reaches_the_brief_and_the_log(self):
        import hermes_runtime as hr
        real = hr.evaluate_news_lock
        self.addCleanup(lambda: setattr(hr, 'evaluate_news_lock', real))

        def boom(*a, **k):
            raise RuntimeError('plan shape exploded')

        hr.evaluate_news_lock = boom
        _, result = self._run(hold_plan(), [pos_raw('SELL')])
        self.assertTrue(result.get('ok'), result)
        self.assertEqual((result.get('guards') or {}).get('state'), 'error')
        self.assertIn('plan shape exploded', result['guards']['detail'])
        self.assertIn('گاردهای ایمنی', str(result.get('brief', '')),
                      'the operator must see that the guards were skipped')
        text = (self.paths.logs_dir() / 'runtime.log').read_text(encoding='utf-8')
        self.assertIn('guard eval error', text)

    def test_healthy_cycle_brief_stays_clean(self):
        """Visibility must not become noise: no guard problem → no warning."""
        plan = hold_plan()
        plan['context'] = {'macro': {'calendar': {'high_impact': [],
                                                  'total_events': 100}}}
        _, result = self._run(plan, [pos_raw('SELL')])
        brief = str(result.get('brief', ''))
        self.assertNotIn('گاردهای ایمنی', brief)
        self.assertNotIn('تقویم اخبار', brief)

    def test_dead_watchdog_with_no_position_is_unaffected(self):
        """No positions → the guard block never runs → no guards key, no
        spurious warning, monitor path behaves exactly as before."""
        _, result = self._run(hold_plan(), [])
        self.assertTrue(result.get('ok'), result)
        self.assertNotIn('guards', result)

    def test_rejected_close_is_still_not_committed(self):
        """b7b discipline survives the refactor: a broker-rejected close must
        not be reported as executed."""
        _, result = self._run(broken_macro_plan(), [aged_position(40)],
                              accept=False)
        self.assertEqual(result.get('step'), 'manage')
        self.assertFalse(result['will_execute_now'],
                         'rejected close must never claim execution')
        self.assertIn('رد کرد', str(result.get('brief', '')))

    def test_fresh_heartbeat_still_skips_the_fallback(self):
        """b34 handoff discipline: while the watchdog is alive the runtime
        must not manage (double-modify race)."""
        self.hb.write_text(datetime.now(timezone.utc).isoformat())
        bridge, result = self._run(broken_macro_plan(), [aged_position(40)])
        self.assertEqual(bridge.mgmt_calls, [],
                         'runtime must not manage while the watchdog is alive')


class MasterAlertTests(unittest.TestCase):
    """hermes_master must turn payload['guards'] into an ops alert."""

    def setUp(self):
        hermetic.use_temp_data_root()

    def tearDown(self):
        hermetic.release()

    def _capture_ops(self, raises=False):
        import notifier.telegram as tg
        real = tg.send_ops
        self.addCleanup(lambda: setattr(tg, 'send_ops', real))
        sent = []

        def fake(msg):
            sent.append(msg)
            if raises:
                raise RuntimeError('telegram 429')
            return True
        tg.send_ops = fake
        return sent

    def test_error_state_alerts(self):
        from hermes_master import alert_degraded_guards
        sent = self._capture_ops()
        self.assertTrue(alert_degraded_guards(
            {'guards': {'state': 'error', 'detail': 'AttributeError: x'}},
            'monitor'))
        self.assertEqual(len(sent), 1)
        self.assertIn('error', sent[0])

    def test_calendar_unavailable_alerts(self):
        from hermes_master import alert_degraded_guards
        sent = self._capture_ops()
        self.assertTrue(alert_degraded_guards(
            {'guards': {'state': 'calendar_unavailable'}}, 'manage'))
        self.assertEqual(len(sent), 1)

    def test_healthy_states_are_silent(self):
        from hermes_master import alert_degraded_guards
        sent = self._capture_ops()
        for st in ('none', 'applied', None, 'unknown_future_state'):
            payload = {'guards': {'state': st}} if st else {}
            self.assertFalse(alert_degraded_guards(payload, 'monitor'), st)
        self.assertEqual(sent, [], 'healthy cycles must not page anyone')

    def test_a_dead_telegram_never_breaks_the_report(self):
        from hermes_master import alert_degraded_guards
        self._capture_ops(raises=True)
        self.assertTrue(alert_degraded_guards(
            {'guards': {'state': 'error', 'detail': 'x'}}, 'manage'))

    # ── b37: alert fatigue — the master runs every 15 min ──────────────
    def test_same_degradation_is_paged_once_per_cooldown(self):
        """Without dedupe a calendar outage pages 4x/hour until it heals —
        the page that gets ignored is the one that matters."""
        from hermes_master import alert_degraded_guards
        sent = self._capture_ops()
        now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
        payload = {'guards': {'state': 'calendar_unavailable'}}
        self.assertTrue(alert_degraded_guards(payload, 'monitor', now=now))
        for m in (15, 30, 45):  # the next three cycles: suppressed
            self.assertFalse(alert_degraded_guards(
                payload, 'monitor', now=now + timedelta(minutes=m)),
                f'cycle +{m}min must not re-page the same fact')
        self.assertEqual(len(sent), 1)
        # ... but the LOG still records every occurrence
        from hermes_master import _log_file
        text = _log_file().read_text(encoding='utf-8')
        self.assertEqual(text.count('GUARDS DEGRADED'), 4,
                         'suppressed pages must still be logged')

    def test_re_pages_after_the_cooldown_expires(self):
        from hermes_master import (GUARD_ALERT_COOLDOWN_SEC,
                                   alert_degraded_guards)
        sent = self._capture_ops()
        now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
        payload = {'guards': {'state': 'error', 'detail': 'boom'}}
        self.assertTrue(alert_degraded_guards(payload, 'manage', now=now))
        later = now + timedelta(seconds=GUARD_ALERT_COOLDOWN_SEC + 60)
        self.assertTrue(alert_degraded_guards(payload, 'manage', now=later),
                        'a still-broken guard must eventually re-page')
        self.assertEqual(len(sent), 2)

    def test_a_CHANGED_failure_pages_immediately(self):
        from hermes_master import alert_degraded_guards
        sent = self._capture_ops()
        now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(alert_degraded_guards(
            {'guards': {'state': 'error', 'detail': 'AttributeError: a'}},
            'manage', now=now))
        self.assertTrue(alert_degraded_guards(
            {'guards': {'state': 'error', 'detail': 'KeyError: b'}},
            'manage', now=now + timedelta(minutes=15)),
            'a new failure is new information')
        self.assertEqual(len(sent), 2)

    def test_healing_clears_the_state_so_the_next_failure_pages(self):
        from hermes_master import alert_degraded_guards
        sent = self._capture_ops()
        now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
        bad = {'guards': {'state': 'error', 'detail': 'boom'}}
        self.assertTrue(alert_degraded_guards(bad, 'manage', now=now))
        self.assertFalse(alert_degraded_guards(
            {'guards': {'state': 'applied'}}, 'manage', now=now))
        self.assertTrue(alert_degraded_guards(bad, 'manage',
                                              now=now + timedelta(minutes=15)),
                        'recovery then relapse must not be silenced')
        self.assertEqual(len(sent), 2)

    def test_absent_guards_key_does_not_clear_the_state(self):
        """step=plan/monitor with a LIVE watchdog has no guards key — that is
        'runtime did not manage', not 'guards are healthy'."""
        from hermes_master import alert_degraded_guards
        sent = self._capture_ops()
        now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(alert_degraded_guards(
            {'guards': {'state': 'error', 'detail': 'boom'}}, 'manage',
            now=now))
        alert_degraded_guards({'step': 'reassess'}, 'reassess', now=now)
        self.assertFalse(alert_degraded_guards(
            {'guards': {'state': 'error', 'detail': 'boom'}}, 'manage',
            now=now + timedelta(minutes=15)),
            'a watchdog-managed cycle must not reset the dedupe window')
        self.assertEqual(len(sent), 1)

    def test_corrupt_alert_state_degrades_to_alerting(self):
        """Fail-LOUD: an unreadable dedupe file must never silence the page."""
        from hermes_master import _guard_alert_state, alert_degraded_guards
        sent = self._capture_ops()
        p = _guard_alert_state()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{not json', encoding='utf-8')
        self.assertTrue(alert_degraded_guards(
            {'guards': {'state': 'error', 'detail': 'x'}}, 'manage'))
        self.assertEqual(len(sent), 1)


class NoSilentPassRegression(unittest.TestCase):
    """Source-level tripwire on the guard merge itself.

    A future 'cleanup' that re-wraps the merge in `except Exception: pass`
    would re-open b37 while every behavioural test still passed (the helper
    catches internally). This one reads the AST of the three guard helpers —
    scoped deliberately: the file still has pre-existing bare passes on
    non-safety paths (heartbeat parse, spread gate) that are out of scope."""

    GUARD_FUNCS = ('evaluate_legacy_guards', '_guard_calendar',
                   '_plan_calendar', '_guard_brief_line')

    def test_guard_helpers_have_no_bare_except_pass(self):
        import ast
        import inspect
        import hermes_runtime as hr
        offenders = []
        for fname in self.GUARD_FUNCS:
            fn = getattr(hr, fname)
            tree = ast.parse(inspect.getsource(fn).strip())
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and \
                        all(isinstance(s, ast.Pass) for s in node.body):
                    offenders.append(f'{fname}:line {node.lineno}')
        self.assertEqual(offenders, [],
                         f'b37: guard helpers must never swallow silently '
                         f'— {offenders}')

    def test_cycle_delegates_the_merge_to_the_named_helper(self):
        src = (REPO / 'hermes_runtime.py').read_text(
            encoding='utf-8')
        self.assertIn('evaluate_legacy_guards(', src)
        self.assertNotIn("plan.get('context', {}).get('macro', {})", src,
                         'the shape-unsafe inline calendar lookup is back')


if __name__ == '__main__':
    unittest.main()
