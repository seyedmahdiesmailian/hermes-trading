"""b34 — the runtime's FALLBACK management path must survive real bridge data.

Why this file exists: hermes_runtime.cycle manages positions only when the
watchdog heartbeat is stale (daemon dead). That fallback is the last line of
defense — and it was DEAD ON ARRIVAL: the bridge (scripts/mt5_http_server_v2
/api/positions) sends type as the STRING 'BUY'/'SELL', while _pos_obj did
int(p.get('type', 0) or 0) → ValueError('invalid literal for int() with base
10: BUY') → the exception propagates out of cycle() (no try/except) and out
of hermes_master (also none) → the ENTIRE master cycle crashes, every 15-min
tick, for as long as a position is open and the watchdog is dead. No plan, no
monitor, no entries, no Telegram — the exact double-failure the fallback
exists to cover.

No existing test caught it because every MockBridge in the suite returns
positions={'data': []} — the loop body never ran.

These tests replay a production-shaped open position through the REAL
cycle() against a fake bridge. The first test goes RED against the old code.
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, '/home/ai/hermes-trading')
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hermetic
from test_integration import MockBridge


TICK_S = {'ok': True, 'ask': 4430.5, 'bid': 4430.0}   # SELL TP1=4435 hit
TICK_B = {'ok': True, 'ask': 4496.0, 'bid': 4495.5}   # BUY  TP1=4490 hit


def production_plan(side='SELL'):
    """current_plan.json in the exact production shape (tp on the correct
    side of entry — see test_daemon_guards.write_plan note)."""
    now = datetime.now(timezone.utc)
    tps = [4435.0, 4420.0, 4405.0] if side == 'SELL' else [4490.0, 4505.0, 4520.0]
    return {
        'plan_id': 'xau-fallback-test', 'symbol': 'XAUUSD', 'bias': side.lower(),
        'session': 'London', 'atr': 5.0,
        'invalidation': 4460.0 if side == 'SELL' else 4440.0,
        'created_at': now.isoformat(),
        'expires_at': (now + timedelta(hours=4)).isoformat(),
        'next_reassessment': (now + timedelta(hours=2)).isoformat(),
        'quality': {'trend_strength': 2.0, 'alignment': 'aligned',
                    'regime': 'trending'},
        'execution': {'tp_levels': tps, 'tp_shares': [0.5, 0.3, 0.2]},
        # zones far from the test price: the monitor must never enter here,
        # so any management action is unambiguously from the fallback path.
        'zones': {'long_entry_low': 4300.0, 'long_entry_high': 4305.0,
                  'short_entry_low': 4600.0, 'short_entry_high': 4605.0,
                  'value_low': 4305.0, 'value_high': 4600.0},
        'context': {'macro': {'allowed': True,
                              'calendar': {'high_impact': [], 'medium_impact': []}}},
    }


def bridge_with(positions, tick):
    return MockBridge(tick=tick, positions={'ok': True, 'data': positions,
                                            'count': len(positions)})


class ManageBridge(MockBridge):
    """MockBridge + the three management endpoints, recording every call."""

    def __init__(self, positions, tick, accept=True):
        super().__init__(tick=tick,
                         positions={'ok': True, 'data': positions,
                                    'count': len(positions)})
        self.accept = accept
        self.mgmt_calls = []

    def _r(self, name, **kw):
        self.mgmt_calls.append((name, kw))
        return {'ok': True, 'retcode': 10009} if self.accept else \
            {'ok': False, 'error': 'retcode_invalid_stops'}

    def modify_position(self, ticket, sl=None, tp=None):
        return self._r('modify_position', ticket=ticket, sl=sl, tp=tp)

    def partial_close(self, ticket, percent):
        return self._r('partial_close', ticket=ticket, percent=percent)

    def close_position(self, ticket):
        return self._r('close_position', ticket=ticket)


def pos_raw(type_val, entry=4450.0):
    """Position exactly as /api/positions returns it (bridge v2: type is a
    STRING, time is broker-clock epoch)."""
    broker_epoch = int(datetime.now(timezone.utc).timestamp()) + 3 * 3600 - 7200
    return {'ticket': 99001, 'symbol': 'XAUUSD', 'type': type_val,
            'volume': 0.02, 'price_open': entry, 'sl': 4460.0, 'tp': 4600.0,
            'price_current': entry, 'profit': 0.0, 'swap': 0.0,
            'comment': '', 'time': broker_epoch}


class RuntimeFallbackTests(unittest.TestCase):
    def setUp(self):
        hermetic.use_temp_data_root()
        from engines.storage import save_current_plan, save_runtime_state
        from engines import paths
        save_current_plan(paths.plan_dir(), production_plan('SELL'))
        save_runtime_state(paths.plan_dir(), {})
        self.hb = paths.plan_dir() / 'watchdog_heartbeat'

    def tearDown(self):
        hermetic.release()

    def _stale_heartbeat(self):
        self.hb.write_text((datetime.now(timezone.utc)
                            - timedelta(minutes=10)).isoformat())

    def _fresh_heartbeat(self):
        self.hb.write_text(datetime.now(timezone.utc).isoformat())

    # ── the crash ──────────────────────────────────────────────────────
    def test_sell_position_string_type_does_not_crash_cycle(self):
        """RED against old code: _pos_obj int('SELL') → ValueError → the
        whole master cycle dies instead of managing the trade."""
        from hermes_runtime import cycle
        self._stale_heartbeat()
        bridge = ManageBridge([pos_raw('SELL')], TICK_S)
        result = cycle(bridge, dry_run=False)   # must not raise
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(result.get('step'), 'manage')

    def test_tp1_hit_triggers_partial_on_fallback(self):
        from hermes_runtime import cycle
        self._stale_heartbeat()
        bridge = ManageBridge([pos_raw('SELL')], TICK_S)
        result = cycle(bridge, dry_run=False)
        self.assertEqual(result.get('step'), 'manage')
        self.assertEqual(result['management']['action'], 'partial_take_profit')
        self.assertEqual([c[0] for c in bridge.mgmt_calls], ['partial_close'])
        self.assertTrue(result['will_execute_now'])

    def test_buy_side_is_not_inverted(self):
        """Old code would have mapped any non-int type to SELL anyway; pin
        that 'BUY' means BUY: TP hit only when price rises past the target."""
        from hermes_runtime import cycle
        self._stale_heartbeat()
        save = production_plan('BUY')
        from engines.storage import save_current_plan
        from engines import paths
        save_current_plan(paths.plan_dir(), save)
        # bid 4495.5 is ABOVE tp1 4490 → BUY hit; and it is NOT a SELL hit
        bridge = ManageBridge([pos_raw('BUY', entry=4450.0)], TICK_B)
        result = cycle(bridge, dry_run=False)
        self.assertEqual(result.get('step'), 'manage')
        self.assertEqual(result['management']['action'], 'partial_take_profit')
        self.assertEqual([c[0] for c in bridge.mgmt_calls], ['partial_close'])

    def test_legacy_int_types_still_work(self):
        from hermes_runtime import cycle
        self._stale_heartbeat()
        bridge = ManageBridge([pos_raw(0)], TICK_S)   # 0=BUY, price below → no hit
        result = cycle(bridge, dry_run=False)
        self.assertTrue(result.get('ok'))
        # BUY at 4450 with bid 4430: no TP hit, thesis valid → no mgmt action,
        # cycle falls through to monitor. The point: no crash on int type.
        self.assertNotEqual(result.get('step'), 'crashed')

    def test_fresh_heartbeat_skips_fallback_entirely(self):
        """Handoff discipline: while the watchdog is alive the runtime must
        NOT manage (double-modify race)."""
        from hermes_runtime import cycle
        self._fresh_heartbeat()
        bridge = ManageBridge([pos_raw('SELL')], TICK_S)
        result = cycle(bridge, dry_run=False)
        self.assertTrue(result.get('ok'))
        self.assertEqual(bridge.mgmt_calls, [],
                         'runtime must not manage while the watchdog is alive')

    def test_rejected_partial_is_not_committed(self):
        """b7b discipline on the fallback path: broker rejection must leave
        runtime_state['management'] untouched."""
        from hermes_runtime import cycle
        from engines.storage import load_runtime_state
        from engines import paths
        self._stale_heartbeat()
        bridge = ManageBridge([pos_raw('SELL')], TICK_S, accept=False)
        result = cycle(bridge, dry_run=False)
        self.assertEqual(result.get('step'), 'manage')
        self.assertFalse(result['will_execute_now'])
        saved = load_runtime_state(paths.plan_dir())
        tstate = (saved.get('management') or {}).get('99001', {})
        self.assertEqual(tstate.get('filled_tp_levels', []), [],
                         'rejected partial must not mark TP1 filled')


if __name__ == '__main__':
    unittest.main()
