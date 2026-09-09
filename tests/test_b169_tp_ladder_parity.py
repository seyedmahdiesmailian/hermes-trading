"""b169 TRADER CODE REVIEW — THE RUNTIME MANAGE-FALLBACK FED A RAW, UNSHAPED
TP LADDER TO evaluate_trade_management; THE b44/b60 FIXES LIVED ONLY IN THE
WATCHDOG.

The defect (cross-module, measured before fixing):
evaluate_trade_management has TWO producers of the trade dict —
position_daemon.build_trade (5s watchdog) and hermes_runtime.cycle's manage
fallback (the ONLY manager whenever the heartbeat is >60s stale — the exact
situation b34/b35/b37/b60/b65/b67/b167 all hardened). b44 (wrong-side filter,
#103326893) and b60 (TP1 = midpoint of entry→final, #103976964) were applied
inline in build_trade ONLY. The fallback passed
`(plan['execution']['tp_levels'] or plan['targets'])` raw. Consequences while
the watchdog was dead:
  * a stale/wrong-side first target made _next_unfilled_target return a level
    the profit_side guard blocks, and the loop `break`s THERE — every farther
    legit target is dead-locked, so no TP/BE/trail branch can fire; the loop
    can only time-exit (a P&L decision silently replaced by a clock).
  * TP1 took the raw first intermediate level instead of the backtest-parity
    midpoint — the exact geometry b60 proved diverged from the +1641$
    backtest ladder (live closed the whole ticket pennies from entry).

Fix shape (b109/b111 lesson — two lookalikes drift, ONE definition does not):
the inline watchdog block was extracted VERBATIM into
engines.trade_management.build_tp_ladder(price_open, side, broker_tp,
raw_levels); build_trade now calls it (byte-identical behaviour, pinned by
test_daemon_guards' b44/b60 incident tests) and the fallback calls the same
helper. Measured drift on the b44 incident replay (SELL entry 4415.82, stale
TP1 4416.78 above entry): watchdog ladder [4361.24, 4306.65] vs fallback
ladder [4416.78, 4382.67, 4361.24, 4306.65] — four levels, first one wrong-
side, no midpoint. Direction of the fix is SAFETY+PARITY-ONLY: the fallback
gains the watchdog's shaping, the watchdog keeps its behaviour.
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

from engines.trade_management import build_tp_ladder


# ── the helper: pure, incident-shaped ──────────────────────────────────

class TestBuildTpLadder(unittest.TestCase):
    def test_b44_wrong_side_first_target_dropped(self):
        """#103326893 replay: SELL 4415.82, stale TP1 4416.78 ABOVE entry."""
        ladder = build_tp_ladder(4415.82, 'SELL', 4306.65,
                                 [4416.78, 4382.67, 4361.24, 4306.65])
        self.assertTrue(all(t < 4415.82 for t in ladder), ladder)
        self.assertEqual(ladder, [4361.235, 4306.65])  # b60 midpoint of 4306.65

    def test_b60_midpoint_from_broker_tp(self):
        """Final target = broker TP (furthest), TP1 = entry→final midpoint."""
        ladder = build_tp_ladder(4450.0, 'SELL', 4400.0, [4440.0, 4420.0])
        self.assertEqual(ladder, [4425.0, 4400.0])

    def test_buy_side_mirror(self):
        ladder = build_tp_ladder(4450.0, 'BUY', 4550.0, [4440.0, 4470.0])
        # 4440 is the wrong side for BUY → dropped; ladder = mid, final
        self.assertEqual(ladder, [4500.0, 4550.0])

    def test_empty_levels_stay_empty(self):
        self.assertEqual(build_tp_ladder(4450.0, 'SELL', None, []), [])
        self.assertEqual(build_tp_ladder(4450.0, 'SELL', None, None), [])

    # ── the wiring: the fallback cycle must ride THE SAME ladder ───────

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

    def test_b44_incident_position_gets_partial_not_deadlock(self):
        from engines.storage import save_current_plan
        """The b44 SELL at 4415.82 with the stale ladder, at market 4360:
        the watchdog would take profit (midpoint 4361.24 hit). The OLD
        fallback dead-locked on the wrong-side first level — no TP branch
        could fire — and (at age 2h) did NOTHING at all: TP1=4416.78 above
        a SELL is not a hit, and time_exit needs 240min. The fixed fallback
        must take profit exactly like the watchdog."""
        from hermes_runtime import cycle
        self._stale_heartbeat()
        p = production_plan('SELL')
        p['invalidation'] = 4426.0
        p['execution']['tp_levels'] = [4416.78, 4382.67, 4361.24, 4306.65]
        p['targets'] = list(p['execution']['tp_levels'])
        save_current_plan(self.paths.plan_dir(), p)
        pos = fb.pos_raw('SELL', ticket=99001, entry=4415.82, sl=4426.0,
                         tp=4306.65, age_hours=2.0)
        tick = fb.tick_payload(ask=4360.6, bid=4360.0)
        bridge = ManageBridge([pos], tick)
        result = cycle(bridge, dry_run=False)
        self.assertEqual(result.get('step'), 'manage', result)
        self.assertEqual(result['management']['action'], 'partial_take_profit')
        # b182: this ladder has farther targets beyond the hit midpoint and
        # the fixture volume is splittable -> 50% partial, not a full close.
        self.assertEqual([c[0] for c in bridge.mgmt_calls], ['partial_close'])
        self.assertEqual(bridge.mgmt_calls[0][1].get('percent'), 50)

    def test_fresh_heartbeat_still_skips_fallback(self):
        from engines.storage import save_current_plan
        """Guard the other direction: parity must not create a
        double-manager race — while the watchdog is alive the runtime must
        still perform zero mgmt calls."""
        from hermes_runtime import cycle
        self.hb.write_text(datetime.now(timezone.utc).isoformat())
        p = production_plan('SELL')
        save_current_plan(self.paths.plan_dir(), p)
        bridge = ManageBridge(
            [fb.pos_raw('SELL', entry=4450.0)],
            fb.tick_payload(ask=4425.5, bid=4425.0))
        result = cycle(bridge, dry_run=False)
        self.assertTrue(result.get('ok'))
        self.assertEqual(bridge.mgmt_calls, [])


if __name__ == '__main__':
    unittest.main()
