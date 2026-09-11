"""b207 — the kill-switch HALT must block NEW ENTRIES, not protective MANAGEMENT.

The defect (code review 2026-09-10): hermes_runtime.cycle checked the kill
switch and, when halted, RETURNED before the plan block, before "Manage
Existing Positions" and before the entry monitor. So the halt that exists to
protect the account also cancelled every protective action on the exposure
already on the book — news_lock tightening, time_exit, TP1 partial,
breakeven (b205 ratchet), runner trail (b202 ratchet) — for the whole
COOLDOWN_HOURS=4 window.

Why nothing else covers it: the primary manager is the 5s position watchdog,
which never consults the kill switch (correctly). The RUNTIME fallback is by
design the last line of defence and runs only when the watchdog heartbeat is
stale (>60s) — b34's exact double-failure case. Under halt that fallback was
skipped unconditionally, so kill-switch-fired AND watchdog-down left a live
position with its ORIGINAL stop and no guard at all. And the halt's drawdown
leg (equity < balance by >=10%) can only fire WHILE a position is open and
losing: it halts trading precisely when something must be managed.

The fix keeps the single-manager handoff rule intact: the halted branch runs
the SAME extracted manager (_manage_positions_fallback) only when
`positions and old_plan and not watchdog_alive`, returns its payload stamped
with the kill_switch (ops brief still says HALTED + which protective action
ran), and never reaches plan/monitor/entry code.

Test (a) is RED against the pre-fix code: halted state + stale heartbeat + a
position past TP1 recorded ZERO bridge mgmt calls and step 'halted'.
"""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hermetic
from test_integration import MockBridge
import fixtures_bridge as fb
from test_runtime_fallback_management import (ManageBridge, production_plan,
                                              pos_raw, TICK_S)


def halt_now(now: datetime | None = None) -> datetime:
    """A 'now' for arming the test halt. b79: was a FIXED 2026-09-10 10:00,
    which turned this whole file into a time bomb — once wall time passed
    that day's resumes_at, check_kill_switch legitimately AUTO-RESUMED and
    every halted assertion broke. Now: real wall time (so the 3h halt
    always lives ahead of cycle's own _now), shifted PAST the daily market
    close window (b93 gate ~22:00-23:00 UTC) so the tests still never flip
    on wall time. A forward shift is safe: halted_until = shifted+3h is
    still ahead of real now, so the halt stays armed either way.
    """
    if now is not None:
        return now
    now = datetime.now(timezone.utc)
    if 22 <= now.hour:                      # inside/close to the b93 window
        now = now + timedelta(hours=24 - now.hour + 1)   # -> next day 00/01h
    return now


def arm_halt(now: datetime | None = None, reason='autopilot-test-halt'):
    """Write a halted kill_switch_state whose resumes_at is still in the
    future at `now` → check_kill_switch returns halted without re-deriving
    any threshold (state-path injection, same shape as production)."""
    from engines import paths
    now = halt_now(now)
    state = {
        'halted': True,
        'halt_reason': reason,
        'halted_at': (now - timedelta(hours=1)).isoformat(),
        'resumes_at': (now + timedelta(hours=3)).isoformat(),
        'consecutive_losses': 0,
        'last_check': now.isoformat(),
    }
    paths.kill_switch_state().parent.mkdir(parents=True, exist_ok=True)
    paths.kill_switch_state().write_text(json.dumps(state), encoding='utf-8')


class HaltManagementTests(unittest.TestCase):
    def setUp(self):
        hermetic.use_temp_data_root()
        from engines.storage import save_current_plan, save_runtime_state
        from engines import paths
        self.paths = paths
        save_current_plan(paths.plan_dir(), production_plan('SELL'))
        save_runtime_state(paths.plan_dir(), {})
        self.hb = paths.plan_dir() / 'watchdog_heartbeat'

    def tearDown(self):
        hermetic.release()

    def _stale(self):
        self.hb.write_text((datetime.now(timezone.utc)
                            - timedelta(minutes=10)).isoformat())

    def _fresh(self):
        self.hb.write_text(datetime.now(timezone.utc).isoformat())

    # ── (a) RED against pre-fix: a TP1-hitting position under halt MUST be
    #    managed by the fallback while the watchdog is dead ──
    def test_halted_kill_switch_still_manages_tp1_hit(self):
        from hermes_runtime import cycle
        now = halt_now()
        self._stale()
        arm_halt(now)
        bridge = ManageBridge([pos_raw('SELL')], TICK_S)
        result = cycle(bridge, dry_run=False)
        self.assertTrue(result.get('ok'), result)
        self.assertEqual([c[0] for c in bridge.mgmt_calls], ['partial_close'],
                         'b207: the halt froze the ONLY remaining protective '
                         'manager — a TP1-hitting position got zero action')
        self.assertIn(result.get('step'), ('manage', 'halted'), result)
        self.assertEqual(result['management']['action'], 'partial_take_profit')
        # The ops brief must STILL say the account is halted (and which
        # protective action ran) — visibility of the halt is not lost.
        self.assertEqual((result.get('kill_switch') or {}).get('halted'), True)
        self.assertTrue(result.get('halted'),
                        'the manage payload under halt must be stamped halted')
        self.assertIn('توقف سوییچ', str(result.get('brief', '')),
                      'the ops brief must state the halt is active')

    # ── (b) the halt still blocks NEW ENTRIES ──
    def test_halted_kill_switch_never_enters(self):
        """Non-vacuous: FIRST run the same fixtures un-halted and prove the
        monitor actually gets reached (the entry path is live code), THEN arm
        the halt and prove the monitor is never even called and zero orders
        are sent. Flat book so the management pass is not the reason."""
        from hermes_runtime import cycle
        import hermes_runtime as hr
        now = halt_now()
        self._stale()

        calls = []
        real = hr.evaluate_monitor_cycle

        def spy(plan, **kw):
            calls.append(plan.get('plan_id'))
            return real(plan, **kw)

        hr.evaluate_monitor_cycle = spy
        self.addCleanup(lambda: setattr(hr, 'evaluate_monitor_cycle', real))

        entered = []

        class WatchBridge(ManageBridge):
            def send_order(self, *a, **k):
                entered.append((a, k))
                return {'ok': True, 'ticket': 1}

        # control: no halt → the cycle DOES evaluate the monitor
        bridge = WatchBridge([], TICK_S)
        r0 = cycle(bridge, dry_run=False)
        self.assertTrue(r0.get('ok'), r0)
        self.assertTrue(calls,
                        'anti-vacuity: the un-halted cycle must reach the '
                        'entry monitor with these fixtures')
        n_before = len(calls)

        # halt armed → monitor must NEVER be reached again, no orders
        arm_halt(now)
        bridge2 = WatchBridge([], TICK_S)
        result = cycle(bridge2, dry_run=False)
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(len(calls), n_before,
                         'b207: under halt the entry monitor must be '
                         'unreachable (new entries stay blocked)')
        self.assertEqual(entered, [])
        self.assertEqual(result.get('step'), 'halted')
        self.assertFalse(result.get('will_execute_now'))
        self.assertIn('KILL SWITCH ACTIVE', str(result.get('brief', '')))
        self.assertEqual(bridge2.mgmt_calls, [],
                         'flat book under halt → no management either')

    # ── (c) single-manager handoff survives the halt ──
    def test_halted_with_live_watchdog_does_not_double_manage(self):
        from hermes_runtime import cycle
        now = halt_now()
        self._fresh()
        arm_halt(now)
        bridge = ManageBridge([pos_raw('SELL')], TICK_S)
        result = cycle(bridge, dry_run=False)
        self.assertEqual(result.get('step'), 'halted')
        self.assertEqual(bridge.mgmt_calls, [],
                         'watchdog alive → the runtime must not manage even '
                         'under halt (b34 handoff discipline)')

    # ── (d) b37 guard visibility reaches the HALTED brief ──
    def test_guard_error_surfaces_on_halted_brief(self):
        import hermes_runtime as hr
        from hermes_runtime import cycle
        now = halt_now()
        self._stale()
        arm_halt(now)

        # hold the position (price far from any level) so the management pass
        # runs WITHOUT taking an action — the halted brief is returned and
        # must still carry the degraded-guard line.
        from engines.storage import save_current_plan
        plan = production_plan('SELL')
        save_current_plan(self.paths.plan_dir(), plan)
        hold_tick = fb.tick_payload(ask=4440.5, bid=4440.0)  # above TP1 4427.5 → hold

        real = hr.evaluate_news_lock
        self.addCleanup(lambda: setattr(hr, 'evaluate_news_lock', real))

        def boom(*a, **k):
            raise RuntimeError('b207 halt-path guard probe')

        hr.evaluate_news_lock = boom
        bridge = ManageBridge([pos_raw('SELL')], hold_tick)
        result = cycle(bridge, dry_run=False)
        self.assertEqual(result.get('step'), 'halted', result)
        self.assertIn('گاردهای ایمنی', str(result.get('brief', '')),
                      'b37: a skipped safety guard must be visible even on '
                      'the halted brief')
        self.assertEqual((result.get('guards') or {}).get('state'), 'error')

    # ── anti-vacuity: the halted branch must consult THE SAME manager body ──
    def test_halted_path_reuses_the_single_manager_body(self):
        """b109/b111: the halt calls the extracted helper; there must be
        exactly ONE trade-dict-building loop in the file (no copy-paste
        second manager that a ladder fix would miss)."""
        import ast
        src = (Path(__file__).resolve().parents[1] / 'hermes_runtime.py').read_text(encoding='utf-8')
        tree = ast.parse(src)
        fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        self.assertIn('_manage_positions_fallback', fns)
        # the manager loop is identified by its build_tp_ladder call
        def has_ladder_loop(fn):
            return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                       and n.func.id == 'build_tp_ladder' for n in ast.walk(fn))
        managers = [name for name, fn in fns.items() if has_ladder_loop(fn)]
        self.assertEqual(managers, ['_manage_positions_fallback'],
                         'exactly one fallback manager body must exist')
        cycle_fn = fns['cycle']
        calls = [n for n in ast.walk(cycle_fn)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == '_manage_positions_fallback']
        self.assertEqual(len(calls), 2,
                         'cycle() must call the manager from BOTH the halted '
                         'branch and the normal path')


if __name__ == '__main__':
    unittest.main()
