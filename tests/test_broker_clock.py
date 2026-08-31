"""b35 — the runtime's fallback time_exit must not read the BROKER clock as UTC.

Why this file exists: the bridge stamps position `time` as epoch seconds on
the broker SERVER clock (CapitalXtend = UTC+3, measured in b32), but
hermes_runtime._epoch_to_iso fed that value to evaluate_time_exit untouched.
Every position therefore looked ~3h YOUNGER on the fallback path (the only
manager when the watchdog heartbeat is stale) → the 36h time_exit fired ~3h
LATE. position_daemon fixed this properly for its own 5s loop by estimating
the offset from a live tick stream — a 15-min cycle cannot do that (no
consecutive polls to prove liveness), so the daemon now PUBLISHES its
calibration (engines/broker_clock) and the runtime READS it.

Every degradation path here is checked for DIRECTION: no calibration → the
runtime uses the watchdog's detection time, which is later than the true
open → the position looks older → time_exit fires EARLY, never late.
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, '/home/ai/hermes-trading')
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hermetic
import position_daemon as pd
import fixtures_bridge as fb  # b36: production-shaped payloads
from engines import paths
from engines import broker_clock as bc

BROKER_OFFSET = 3 * 3600  # CapitalXtend server clock = UTC+3 (measured b32)


class CalibrationStoreTests(unittest.TestCase):
    def setUp(self):
        hermetic.use_temp_data_root()

    def tearDown(self):
        hermetic.release()

    def test_roundtrip(self):
        now = datetime.now(timezone.utc)
        self.assertTrue(bc.save_offset(BROKER_OFFSET, now=now))
        self.assertEqual(bc.load_offset(now=now), float(BROKER_OFFSET))

    def test_missing_file_is_none_not_zero(self):
        """0.0 is a legitimate measurement (a UTC broker). 'Unmeasured' must
        stay distinguishable, or the runtime would trust a phantom."""
        self.assertIsNone(bc.load_offset())

    def test_corrupt_file_is_none(self):
        paths.broker_clock_state().write_text('{not json', encoding='utf-8')
        self.assertIsNone(bc.load_offset())

    def test_stale_calibration_is_none(self):
        now = datetime.now(timezone.utc)
        bc.save_offset(BROKER_OFFSET, now=now - timedelta(hours=30))
        self.assertIsNone(bc.load_offset(max_age_sec=24 * 3600, now=now))
        # ...and is still readable with a wider TTL
        self.assertEqual(bc.load_offset(max_age_sec=48 * 3600, now=now),
                         float(BROKER_OFFSET))

    def test_implausible_offset_rejected_on_both_ends(self):
        now = datetime.now(timezone.utc)
        self.assertFalse(bc.save_offset(20 * 3600, now=now))
        self.assertIsNone(bc.load_offset(now=now))
        paths.write_json_atomic(paths.broker_clock_state(),
                                {'offset_sec': 99999, 'measured_at': now.isoformat()})
        self.assertIsNone(bc.load_offset(now=now))

    def test_garbage_inputs_rejected(self):
        for bad in (None, 'x', float('nan'), float('inf')):
            self.assertFalse(bc.save_offset(bad))

    def test_stable_value_is_not_rewritten_every_poll(self):
        """The daemon calls this every 5s; measured_at is the reader's
        liveness stamp, so rewrites are throttled, not per-poll."""
        now = datetime.now(timezone.utc)
        self.assertTrue(bc.save_offset(BROKER_OFFSET, now=now))
        self.assertFalse(bc.save_offset(BROKER_OFFSET, now=now + timedelta(seconds=30)))
        self.assertTrue(bc.save_offset(BROKER_OFFSET, now=now + timedelta(minutes=10)))
        # a genuinely different estimate is written immediately
        self.assertTrue(bc.save_offset(BROKER_OFFSET + 120,
                                       now=now + timedelta(minutes=10, seconds=1)))
        self.assertAlmostEqual(bc.load_offset(
            now=now + timedelta(minutes=10, seconds=1)), BROKER_OFFSET + 120, delta=1)


class DaemonPublishTests(unittest.TestCase):
    """The producer side: only a REAL measurement may reach the file."""

    def setUp(self):
        hermetic.use_temp_data_root()
        pd._guard_cache.update({'cal': None, 'cal_at': 0.0, 'last_eval': {},
                                'applied': {}, 'offsets': [],
                                'prev_tick': (0.0, 0.0)})

    def tearDown(self):
        hermetic.release()

    def test_no_samples_publishes_nothing(self):
        """0.0 from _min_offset() means 'unmeasured'. Writing it would tell
        the runtime the broker clock IS UTC — the bug this whole chain kills."""
        self.assertFalse(pd.publish_calibration())
        self.assertFalse(paths.broker_clock_state().exists())

    def test_live_stream_publishes_min_estimate(self):
        now = datetime.now(timezone.utc)
        est = 0.0
        for i in range(4):
            t = now - timedelta(seconds=(4 - i) * 5)
            est = pd.broker_utc_offset_sec({'time': int(t.timestamp()) + BROKER_OFFSET}, t)
        self.assertGreater(est, 0)
        self.assertTrue(pd.publish_calibration(now=now))
        self.assertAlmostEqual(bc.load_offset(now=now), est, delta=1.0)

    def test_stale_stream_publishes_nothing(self):
        stale = {'time': int((datetime.now(timezone.utc)
                              - timedelta(hours=6)).timestamp()) + BROKER_OFFSET}
        pd.broker_utc_offset_sec(stale, datetime.now(timezone.utc))
        self.assertFalse(pd.publish_calibration())


class FallbackOpenedAtTests(unittest.TestCase):
    """The consumer's decision table (pure helper)."""

    def setUp(self):
        hermetic.use_temp_data_root()

    def tearDown(self):
        hermetic.release()

    def test_uses_calibrated_broker_time(self):
        now = datetime.now(timezone.utc)
        broker_epoch = int((now - timedelta(hours=37)).timestamp()) + BROKER_OFFSET
        from hermes_runtime import _fallback_opened_at
        iso = _fallback_opened_at(broker_epoch, {'opened_at': 'IGNORED'},
                                  float(BROKER_OFFSET))
        self.assertAlmostEqual(
            (now - datetime.fromisoformat(iso)).total_seconds() / 3600,
            37.0, delta=0.05)

    def test_no_calibration_uses_detection_time(self):
        now = datetime.now(timezone.utc)
        detected = (now - timedelta(hours=37)).isoformat()
        from hermes_runtime import _fallback_opened_at
        self.assertEqual(
            _fallback_opened_at(int(now.timestamp()) + BROKER_OFFSET,
                                {'opened_at': detected}, None), detected)

    def test_nothing_available_falls_back_to_raw_epoch(self):
        """Last resort = the old (late-erring) reading, but only when there
        is genuinely no better evidence. Never invent an age."""
        from hermes_runtime import _fallback_opened_at
        epoch = int(datetime.now(timezone.utc).timestamp())
        self.assertEqual(_fallback_opened_at(epoch, None, None),
                         datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat())
        self.assertIsNone(_fallback_opened_at(None, {}, None))


class RuntimeCycleTimeExitTests(unittest.TestCase):
    """End-to-end through the REAL cycle() with a stale heartbeat, against a
    fake bridge. The first test goes RED against the pre-b35 code."""

    def setUp(self):
        hermetic.use_temp_data_root()
        from test_runtime_fallback_management import production_plan
        from engines.storage import save_current_plan, save_runtime_state
        save_current_plan(paths.plan_dir(), production_plan('SELL'))
        save_runtime_state(paths.plan_dir(), {})
        self.hb = paths.plan_dir() / 'watchdog_heartbeat'
        self.hb.write_text((datetime.now(timezone.utc)
                            - timedelta(minutes=10)).isoformat())

    def tearDown(self):
        hermetic.release()

    @staticmethod
    def _pos(hours_ago, offset=BROKER_OFFSET, ticket=99002):
        """SELL position at 4450, opened `hours_ago` REAL hours ago, stamped
        on the broker clock — and priced so nothing else manages it
        (TP1=4435 is below the 4445.5 bid, no TP filled → core = hold).
        b36: built by the shared production-shaped fixture."""
        return fb.pos_raw('SELL', ticket=ticket, age_hours=hours_ago,
                          broker_offset=offset)

    def _run(self, raw, accept=True):
        from test_runtime_fallback_management import ManageBridge
        from hermes_runtime import cycle
        tick = {'ok': True, 'ask': 4446.0, 'bid': 4445.5}
        bridge = ManageBridge([raw], tick, accept=accept)
        return cycle(bridge, dry_run=False), bridge

    def test_37h_position_closes_only_when_clock_is_calibrated(self):
        """RED against old code: raw broker epoch read as UTC made the trade
        look 34h old → no exit → an unmanaged stale position stays in the
        market past the 36h limit."""
        now = datetime.now(timezone.utc)
        bc.save_offset(BROKER_OFFSET, now=now)
        result, bridge = self._run(self._pos(37.0))
        self.assertEqual(result.get('step'), 'manage', result)
        self.assertEqual(result['management']['action'], 'close_trade_early')
        self.assertTrue(result['management']['reason'].startswith('time_exit_37h'),
                        result['management'])
        self.assertEqual([c[0] for c in bridge.mgmt_calls], ['close_position'])
        self.assertTrue(result['will_execute_now'])

    def test_without_calibration_it_still_exits_via_detection_time(self):
        """No published calibration → watchdog_state's opened_at (detection
        time, seconds after the real open) → exits EARLY, never late."""
        raw = self._pos(37.0)
        paths.write_json_atomic(paths.watchdog_state(), {
            'positions': {str(raw['ticket']): {
                'opened_at': (datetime.now(timezone.utc)
                              - timedelta(hours=37)).isoformat()}},
            'closed': []})
        result, bridge = self._run(raw)
        self.assertEqual(result.get('step'), 'manage', result)
        self.assertEqual(result['management']['action'], 'close_trade_early')
        self.assertEqual([c[0] for c in bridge.mgmt_calls], ['close_position'])

    def test_fresh_position_is_not_closed_early_by_calibration(self):
        """Symmetry check: a 2h-old trade must stay untouched — the fix may
        only shift the 36h boundary, never manufacture exits."""
        bc.save_offset(BROKER_OFFSET, now=datetime.now(timezone.utc))
        result, bridge = self._run(self._pos(2.0))
        self.assertNotEqual(result.get('step'), 'manage', result)
        self.assertEqual(bridge.mgmt_calls, [])

    def test_rejected_close_is_not_committed(self):
        """b7b discipline holds on this new action too: runner_active must
        not flip when the broker said no."""
        from engines.storage import load_runtime_state
        bc.save_offset(BROKER_OFFSET, now=datetime.now(timezone.utc))
        result, bridge = self._run(self._pos(37.0), accept=False)
        self.assertEqual(result.get('step'), 'manage')
        self.assertFalse(result['will_execute_now'])
        tstate = (load_runtime_state(paths.plan_dir())
                  .get('management') or {}).get(str(99002), {})
        self.assertNotEqual(tstate.get('runner_active'), False)


if __name__ == '__main__':
    unittest.main()
