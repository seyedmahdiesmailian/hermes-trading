"""b167 TRADER CODE REVIEW — THE RUNTIME FALLBACK LETS A NEWS LOCK STEAL THE
BREAKEVEN FLAG; b32 FIXED THIS ONLY IN THE WATCHDOG.

The defect (cross-module, measured before fixing):
engines/legacy_guards.evaluate_news_lock REUSES the action name
`move_stop_to_breakeven` because that is the SL-modify executor's verb. The
side effect: callers that mark "the real post-TP1 breakeven happened" when they
see that action mark it for a NEWS LOCK too. b32 (position_daemon, 2026-08-30)
explicitly guarded this — `if not reason.startswith('news_lock')` — because
breakeven_active=True suppresses evaluate_trade_management's BE branch
(`if filled and not trade['breakeven_active']`) FOREVER for that position:
a news lock fired BEFORE TP1 means the runner never gets moved to entry even
after TP1 fills, and it rides on its original stop through the give-back.
hermes_runtime.cycle's fallback management path — the ONLY manager while the
watchdog is dead (b34/b35/b37 all hardened exactly this path) — was never
given the guard: it sets management['breakeven_active']=True and persists
tstate['breakeven_active']=True on ANY move_stop_to_breakeven, news lock
included. The fallback loop runs 15-min cycles across a 30-min lock window,
so a pre-TP1 lock on this path is committed to runtime_state.json and the
suppression survives restarts.

Fix shape (b109/b111 lesson — two lookalikes drift, one definition does not):
ONE predicate engines/legacy_guards.is_news_lock(management), consulted by
BOTH callers; the daemon's inline startswith is replaced by it (behaviour
byte-identical), the runtime gains the missing condition. Direction is
TIGHTENING-ONLY: after the fix the real post-TP1 breakeven can fire in MORE
situations (the ones a news lock had poisoned), never fewer.
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hermetic
import fixtures_bridge as fb
from test_runtime_fallback_management import ManageBridge, production_plan
from fixtures_bridge import pos_raw

TICKET = '99001'


def event(minutes_ahead, impact='high', currency='USD', title='FOMC'):
    t = datetime.now(timezone.utc) + timedelta(minutes=minutes_ahead)
    return {'title': title, 'currency': currency, 'impact': impact,
            'date': t.isoformat(), 'time': '', 'forecast': '', 'previous': ''}


def news_plan(calendar_events, side='SELL'):
    """production_plan with a real (non-empty) high-impact calendar bucket."""
    p = production_plan(side)
    p['context']['macro']['calendar'] = {'high_impact': calendar_events,
                                         'medium_impact': []}
    return p


class TestB167FallbackNewsLockBreakeven(unittest.TestCase):
    def setUp(self):
        hermetic.use_temp_data_root()
        from engines.storage import save_current_plan, save_runtime_state
        from engines import paths
        self.paths = paths
        save_runtime_state(paths.plan_dir(), {})
        self.hb = paths.plan_dir() / 'watchdog_heartbeat'

    def tearDown(self):
        hermetic.release()

    def _stale_heartbeat(self):
        self.hb.write_text((datetime.now(timezone.utc)
                            - timedelta(minutes=10)).isoformat())

    def _saved_tstate(self):
        from engines.storage import load_runtime_state
        rs = load_runtime_state(self.paths.plan_dir())
        return (rs.get('management') or {}).get(TICKET, {})

    def test_b167_fallback_news_lock_does_not_claim_breakeven(self):
        """RED against the old code: lock fires (SELL 4450, SL 4460, ATR 5 →
        new SL 4447.5), broker accepts, runtime_state must NOT remember it as
        'real breakeven happened'."""
        from engines.storage import save_current_plan
        from hermes_runtime import cycle
        self._stale_heartbeat()
        save_current_plan(self.paths.plan_dir(),
                          news_plan([event(10)]))
        # price 4445 (bid): below entry → no TP hit → core chain holds;
        # the guard upgrade to news_lock is the ONLY action available.
        tick = fb.tick_payload(ask=4445.5, bid=4445.0)
        bridge = ManageBridge([pos_raw('SELL', entry=4450.0, sl=4460.0)], tick)
        result = cycle(bridge, dry_run=False)
        self.assertEqual(result.get('step'), 'manage', result)
        self.assertEqual(result['management']['action'], 'move_stop_to_breakeven')
        self.assertTrue(str(result['management']['reason']).startswith('news_lock'),
                        'the fired action must actually be the news lock '
                        '(else this test certifies nothing)')
        self.assertTrue(result['will_execute_now'])
        self.assertEqual([c[0] for c in bridge.mgmt_calls], ['modify_position'])
        tstate = self._saved_tstate()
        self.assertFalse(tstate.get('breakeven_active'),
                         'a news lock must NOT set breakeven_active: doing so '
                         'suppresses the REAL post-TP1 breakeven forever '
                         '(b32 fixed exactly this in the watchdog)')

    def test_b167_real_breakeven_still_claims_the_flag(self):
        """Anti-vacuity for the fix: a genuine post-TP1 breakeven (reason
        lock_in_after_tp1/plain_breakeven) must STILL commit
        breakeven_active=True — the guard is news_lock-specific, not a
        blanket suppression."""
        from engines.storage import save_current_plan
        from hermes_runtime import cycle
        self._stale_heartbeat()
        save_current_plan(self.paths.plan_dir(), news_plan([]))
        # SELL 4450, SL 4460, TP1 4435 already filled; bid 4434 is past it.
        # risk 10, momentum 1.0, grade>=2 → lock_in stop at 4448.5 (> price+0.5,
        # so the b52 gap guard passes).
        from engines.storage import save_runtime_state
        save_runtime_state(self.paths.plan_dir(),
                           {'management': {TICKET: {'filled_tp_levels': [4435.0],
                                                    'breakeven_active': False}}})
        tick = fb.tick_payload(ask=4434.5, bid=4434.0)
        bridge = ManageBridge([pos_raw('SELL', entry=4450.0, sl=4460.0)], tick)
        result = cycle(bridge, dry_run=False)
        self.assertEqual(result.get('step'), 'manage', result)
        self.assertEqual(result['management']['action'], 'move_stop_to_breakeven')
        self.assertFalse(str(result['management']['reason']).startswith('news_lock'))
        self.assertTrue(result['will_execute_now'])
        tstate = self._saved_tstate()
        self.assertTrue(tstate.get('breakeven_active'),
                        'the REAL breakeven must still be recorded')
        self.assertEqual(tstate.get('filled_tp_levels'), [4435.0])

    def test_b167_one_predicate_shared_by_both_callers(self):
        """b109/b111 rule: ONE definition, both management callers consult it.
        The daemon's inline startswith('news_lock') is replaced by
        engines.legacy_guards.is_news_lock, and hermes_runtime imports and
        calls it on BOTH commit sites (in-memory + persisted tstate)."""
        import ast
        from engines.legacy_guards import is_news_lock
        self.assertTrue(is_news_lock({'action': 'move_stop_to_breakeven',
                                      'reason': 'news_lock:FOMC_10min'}))
        self.assertFalse(is_news_lock({'action': 'move_stop_to_breakeven',
                                       'reason': 'lock_in_after_tp1'}))
        self.assertFalse(is_news_lock({'action': 'move_stop_to_breakeven',
                                       'reason': 'plain_breakeven'}))
        self.assertFalse(is_news_lock(None))

        repo = Path(__file__).resolve().parents[1]
        for fname in ('hermes_runtime.py', 'position_daemon.py'):
            tree = ast.parse((repo / fname).read_text(encoding='utf-8'))
            imported = any(
                isinstance(n, ast.ImportFrom)
                and n.module == 'engines.legacy_guards'
                and any(a.name == 'is_news_lock' for a in n.names)
                for n in ast.walk(tree))
            self.assertTrue(imported, f'{fname} must import is_news_lock')
            called = any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == 'is_news_lock'
                for n in ast.walk(tree))
            self.assertTrue(called, f'{fname} must CALL is_news_lock')

        # the drift this caused must not come back as a third lookalike:
        daemon = (repo / 'position_daemon.py').read_text(encoding='utf-8')
        self.assertNotIn("startswith('news_lock')", daemon,
                         'b167: the daemon must use the shared predicate, '
                         'not its own string check')

    def test_b167_persist_site_is_gated_not_the_whole_branch(self):
        """AST pin: inside hermes_runtime.cycle the persisted
        tstate['breakeven_active']=True sits under an `elif ...
        move_stop_to_breakeven` arm that also tests is_news_lock — a fix that
        only gated the in-memory dict (which nothing re-reads next cycle)
        would pass the behavioural test above only by accident."""
        import ast
        repo = Path(__file__).resolve().parents[1]
        src = (repo / 'hermes_runtime.py').read_text(encoding='utf-8')
        tree = ast.parse(src)
        # b207: the fallback manage body moved VERBATIM out of cycle() into
        # _manage_positions_fallback (one manager, two callers: normal path +
        # halted path). The pin must scan both, or the extraction 'passes' by
        # shrinking the scan to an empty function.
        scan_fns = [n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef)
                    and n.name in ('cycle', '_manage_positions_fallback')]
        self.assertEqual(len(scan_fns), 2,
                         'b207: cycle() and _manage_positions_fallback() must '
                         'both exist — the manager body lives in one place and '
                         'both callers ride on it')
        cycle_fn = next(n for n in scan_fns if n.name == '_manage_positions_fallback')
        assigns = [n for n in ast.walk(cycle_fn)
                   if isinstance(n, ast.Assign) and any(
                       isinstance(t, ast.Subscript)
                       and isinstance(t.slice, ast.Constant)
                       and t.slice.value == 'breakeven_active'
                       for t in n.targets)]
        self.assertEqual(len(assigns), 2,
                         'expected exactly the two commit sites (in-memory + '
                         'persisted); a third lookalike means the file moved')
        arms = [n for n in ast.walk(cycle_fn)
                if isinstance(n, ast.If)
                and 'move_stop_to_breakeven' in ast.dump(n.test)]
        for a in assigns:
            ok = False
            for arm in arms:
                body = _arm_body_nodes(arm)
                if any(a is n for n in body) and any(
                        isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id == 'is_news_lock' for n in body):
                    ok = True
            self.assertTrue(ok, 'every breakeven_active=True write must sit '
                                'under a move_stop_to_breakeven arm that also '
                                'tests is_news_lock')


def _arm_body_nodes(ifnode):
    """Nodes of an If arm WITHOUT its orelse (the orelse holds the NEXT elif —
    including it would let one gated arm certify a sibling's write)."""
    import ast
    out = []
    for field, value in ast.iter_fields(ifnode):
        if field == 'orelse':
            continue
        values = value if isinstance(value, list) else [value]
        for v in values:
            if isinstance(v, ast.AST):
                out.extend(ast.walk(v))
    return out


if __name__ == '__main__':
    unittest.main()
