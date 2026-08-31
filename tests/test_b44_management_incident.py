"""b44 — regression pins for the 2026-08-31 management incident (#103326893).

What happened (live demo, watchdog log 04:30-04:34 UTC):
  * A SELL opened at 4415.82 while the plan file still carried TP1 4416.78
    (levels are re-drawn every reassessment; the stale one sat ABOVE entry).
    evaluate_trade_management treats any price beyond the next unfilled
    target as a hit → "TP1" fired ONE SECOND after entry → 0.06 lots
    partial-closed at a LOSS.
  * After the (real) TP1, the breakeven move computed SL 4414.67 for a SELL
    while price was ABOVE it → broker retcode 10016. Then the trail clamped
    SL to entry 4415.82 while price ran back above it → retcode 10025, and
    the 5s loop hammered the same invalid modify ~40 times until the
    position died on that stop.
  * The close report said pnl=+1.83$ — that was `last_profit`, the FLOATING
    pnl of the volume slice left at the final poll. The broker's own deals
    for that ticket sum to -1.05$ realized (verified live via
    /api/history/deals after the bridge gained position_id).

Root cause shape (same class as b34/b39): the plan file and the live
position are two producers of one fact (valid TP levels / valid SL side),
and the consumer trusted the stale one. Fixes under test:
  1. position_daemon.build_trade drops tp_levels on the wrong side of entry;
  2. evaluate_trade_management never realizes a "profit" target that sits
     on the loss side of entry (defense in depth — runtime path too);
  3. breakeven/trail stops on the wrong side of the MARKET are not sent
     (hold instead of hammering a rejected modify);
  4. realized_pnl_usd groups broker deals by position_id (falls back to
     None → caller keeps the floating number when history is unavailable);
  5. drift pin: the bridge server source must keep emitting position_id.

All against FakeBridge-style fakes — no real order endpoint exists here.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/home/ai/hermes-trading')
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hermetic  # noqa: E402
import position_daemon as pd  # noqa: E402
from engines.trade_management import evaluate_trade_management  # noqa: E402

REPO = Path('/home/ai/hermes-trading')


def plan_with_tps(tps, side='SELL'):
    return {'symbol': 'XAUUSD', 'atr': 5.0,
            'invalidation': 4460.0 if side == 'SELL' else 4440.0,
            'quality': {'trend_strength': 2.0, 'alignment': 'aligned',
                        'regime': 'trending'},
            'execution': {'tp_levels': tps, 'tp_shares': [0.5, 0.3, 0.2]},
            'context': {'macro': {'allowed': True,
                                  'calendar': {'high_impact': [],
                                               'medium_impact': []}}}}


class BuildTradeTpFilter(unittest.TestCase):
    """Fix 1: stale plan levels on the wrong side of THIS position's entry
    must never become partial-close targets."""

    def test_sell_drops_targets_above_entry(self):
        raw = {'ticket': 103326893, 'type': 'SELL', 'volume': 0.08,
               'price_open': 4415.82, 'sl': 4460.0, 'tp': 0.0,
               'profit': 0.0, 'time': 1788161402}
        plan = plan_with_tps([4416.78, 4404.44, 4390.0])  # TP1 stale ABOVE
        trade = pd.build_trade(raw, plan, {})
        self.assertEqual(trade['tp_levels'], [4404.44, 4390.0],
                         'a SELL target above entry is not a take-profit')

    def test_buy_drops_targets_below_entry(self):
        raw = {'ticket': 1, 'type': 'BUY', 'volume': 0.05,
               'price_open': 4450.0, 'sl': 4440.0, 'tp': 0.0,
               'profit': 0.0, 'time': 1}
        plan = plan_with_tps([4445.0, 4465.0, 4480.0], side='BUY')
        trade = pd.build_trade(raw, plan, {})
        self.assertEqual(trade['tp_levels'], [4465.0, 4480.0])

    def test_int_wire_shape_still_works(self):
        """b34 class: bridge may send type as 0/1 int — the side decision
        for the TP filter must use the NORMALIZED side, not the raw value."""
        raw = {'ticket': 2, 'type': 1, 'volume': 0.05,   # 1 = SELL
               'price_open': 4415.82, 'sl': 4460.0, 'tp': 0.0,
               'profit': 0.0, 'time': 1}
        plan = plan_with_tps([4416.78, 4404.44])
        trade = pd.build_trade(raw, plan, {})
        self.assertEqual(trade['side'], 'SELL')
        self.assertEqual(trade['tp_levels'], [4404.44])

    def test_all_levels_wrong_side_yields_empty(self):
        raw = {'ticket': 3, 'type': 'SELL', 'volume': 0.05,
               'price_open': 4415.82, 'sl': 4460.0, 'tp': 0.0,
               'profit': 0.0, 'time': 1}
        plan = plan_with_tps([4416.78, 4420.0])
        trade = pd.build_trade(raw, plan, {})
        self.assertEqual(trade['tp_levels'], [],
                         'no valid target must mean NO partial-close, ever')


class WrongSideTargetNeverRealizes(unittest.TestCase):
    """Fix 2 (defense in depth): even a hand-built trade dict with a stale
    target cannot fire a loss-making partial_take_profit."""

    def _trade(self, side, entry, tps, filled=None):
        return {'side': side, 'entry_price': entry, 'sl': entry + 40,
                'tp_levels': tps, 'tp_shares': [0.5, 0.3, 0.2],
                'filled_tp_levels': filled or [],
                'breakeven_active': False, 'runner_active': True,
                'scale_in_levels': [], 'scaled_in_levels': [],
                'thesis_valid': True, 'setup_grade': 'B',
                'momentum_strength': 0.5, 'volatility_state': 'normal',
                'structure_state': 'healthy', 'rr_remaining': 2.0,
                'exposure_fraction': 0.5, 'volume': 0.08}

    def test_sell_target_above_entry_no_partial(self):
        now = datetime.now(timezone.utc)
        t = self._trade('SELL', 4415.82, [4416.78])
        m = evaluate_trade_management(t, 4410.0, now)  # price below target
        self.assertNotEqual(m['action'], 'partial_take_profit',
                            f'stale target realized: {m}')

    def test_buy_target_below_entry_no_partial(self):
        now = datetime.now(timezone.utc)
        t = self._trade('BUY', 4450.0, [4445.0])
        m = evaluate_trade_management(t, 4460.0, now)
        self.assertNotEqual(m['action'], 'partial_take_profit')

    def test_valid_target_still_fires(self):
        """The guard must not disable real take-profits (that would weaken
        the exit chain — hard rule)."""
        now = datetime.now(timezone.utc)
        t = self._trade('SELL', 4415.82, [4404.44])
        m = evaluate_trade_management(t, 4404.00, now)
        self.assertEqual(m['action'], 'partial_take_profit')
        self.assertEqual(m['target_hit'], 4404.44)


class StopMustFaceTheMarket(unittest.TestCase):
    """Fix 3: a stop on the wrong side of the market is rejected by the
    broker (10016/10025). The evaluator must not propose one — hold instead,
    keeping the existing SL in force."""

    def _trade(self, **kw):
        base = {'side': 'SELL', 'entry_price': 4415.82, 'sl': 4460.0,
                'tp_levels': [4404.44], 'tp_shares': [0.5, 0.3, 0.2],
                'filled_tp_levels': [4404.44],
                'breakeven_active': False, 'runner_active': True,
                'scale_in_levels': [], 'scaled_in_levels': [],
                'thesis_valid': True, 'setup_grade': 'B',
                'momentum_strength': 0.5, 'volatility_state': 'normal',
                'structure_state': 'healthy', 'rr_remaining': 2.0,
                'exposure_fraction': 0.5, 'volume': 0.08}
        base.update(kw)
        return base

    def test_breakeven_not_proposed_when_price_past_stop(self):
        now = datetime.now(timezone.utc)
        # SELL BE stop = entry - lock ≈ 4415.06; market ran ABOVE entry
        m = evaluate_trade_management(self._trade(), 4420.0, now)
        self.assertNotEqual(m['action'], 'move_stop_to_breakeven',
                            f'invalid BE proposed: {m}')

    def test_breakeven_fires_when_price_is_valid_side(self):
        now = datetime.now(timezone.utc)
        m = evaluate_trade_management(self._trade(), 4405.0, now)
        self.assertEqual(m['action'], 'move_stop_to_breakeven')

    def test_trail_holds_instead_of_hammering_invalid_stop(self):
        now = datetime.now(timezone.utc)
        t = self._trade(breakeven_active=True,
                        filled_tp_levels=[4404.44, 4390.0],
                        tp_levels=[4404.44, 4390.0, 4380.0])
        # price back above entry: clamped SL would sit at entry < price
        m = evaluate_trade_management(t, 4418.0, now)
        self.assertEqual(m['action'], 'hold')
        self.assertEqual(m['reason'], 'trail_stop_invalid_vs_market')

    def test_valid_trail_still_moves(self):
        now = datetime.now(timezone.utc)
        t = self._trade(breakeven_active=True,
                        filled_tp_levels=[4404.44, 4390.0],
                        tp_levels=[4404.44, 4390.0, 4380.0])
        m = evaluate_trade_management(t, 4385.0, now)
        self.assertEqual(m['action'], 'trail_stop')
        self.assertGreater(m['new_sl'], 4385.0,
                           'SELL trail stop must sit ABOVE the market')


class RealizedPnl(unittest.TestCase):
    """Fix 4: the close report must show the broker-confirmed sum of ALL
    deals of the position (incl. the IN deal's commission), not the floating
    pnl of the last volume slice."""

    def _deals(self):
        # production shape from /api/history/deals (verified live 2026-08-31)
        return {'ok': True, 'data': [
            {'ticket': 98203171, 'order': 103326893, 'position_id': 103326893,
             'entry': 0, 'type': 'SELL', 'profit': 0.0,
             'commission': -0.39, 'swap': 0.0},
            {'ticket': 98203175, 'order': 103326897, 'position_id': 103326893,
             'entry': 1, 'type': 'BUY', 'profit': -1.56,
             'commission': -0.18, 'swap': 0.0},
            {'ticket': 98203263, 'order': 103326985, 'position_id': 103326893,
             'entry': 1, 'type': 'BUY', 'profit': 2.88,
             'commission': -0.12, 'swap': 0.0},
            {'ticket': 98203591, 'order': 103327300, 'position_id': 103326893,
             'entry': 1, 'type': 'BUY', 'profit': -1.59,
             'commission': -0.09, 'swap': 0.0},
            # another position's deal must not leak in
            {'ticket': 98200436, 'order': 103324106, 'position_id': 103324106,
             'entry': 0, 'type': 'SELL', 'profit': 0.0,
             'commission': -0.36, 'swap': 0.0},
        ]}

    class Bridge:
        def __init__(self, payload, raise_it=False):
            self.payload = payload
            self.raise_it = raise_it

        def get_history_deals(self, symbol='XAUUSD', days=7):
            if self.raise_it:
                raise ConnectionError('bridge down')
            return self.payload

    def test_real_incident_ticket_sums_to_negative(self):
        got = pd.realized_pnl_usd(self.Bridge(self._deals()), 103326893)
        self.assertEqual(got, -1.05,
                         'the trade the report called +1.83$ was -1.05$ '
                         'realized (broker deals, verified live)')

    def test_other_position_not_polluted(self):
        # 103324106's only deal in the fixture is the IN one → history for
        # it is incomplete → None (caller falls back), and crucially the
        # 103326893 deals never leak into its number.
        deals = {'ok': True, 'data': [
            {'ticket': 98200436, 'order': 103324106,
             'position_id': 103324106, 'entry': 0, 'type': 'SELL',
             'profit': 0.0, 'commission': -0.36, 'swap': 0.0}]}
        self.assertIsNone(pd.realized_pnl_usd(self.Bridge(deals), 103324106))

    def test_incomplete_history_returns_none(self):
        # position with only an IN deal: realized result is unknown, the
        # caller must fall back rather than report commission-only.
        deals = {'ok': True, 'data': [d for d in self._deals()['data']
                                      if d['position_id'] == 103324106]}
        self.assertIsNone(pd.realized_pnl_usd(self.Bridge(deals), 103324106))

    def test_bridge_error_returns_none_not_crash(self):
        self.assertIsNone(pd.realized_pnl_usd(
            self.Bridge(None, raise_it=True), 1))

    def test_legacy_shape_without_position_id(self):
        """Old bridge payloads lack position_id. The `order` fallback only
        matches the IN deal (OUT deals carry their own order id — the exact
        reason the bridge gained position_id on 2026-08-31). So a partially
        closed legacy-shape trade must return None → caller falls back to
        the floating number. Honest degradation, never a wrong sum."""
        deals = {'ok': True, 'data': [
            {k: v for k, v in d.items() if k != 'position_id'}
            for d in self._deals()['data'] if d['position_id'] == 103326893]}
        self.assertIsNone(pd.realized_pnl_usd(self.Bridge(deals), 103326893))
        # a FULL close (single OUT deal whose order == ticket) still sums:
        full = {'ok': True, 'data': [
            {'ticket': 5, 'order': 103326893, 'entry': 0, 'type': 'SELL',
             'profit': 0.0, 'commission': -0.39, 'swap': 0.0},
            {'ticket': 6, 'order': 103326893, 'entry': 1, 'type': 'BUY',
             'profit': 3.0, 'commission': -0.18, 'swap': 0.0}]}
        self.assertEqual(pd.realized_pnl_usd(self.Bridge(full), 103326893),
                         2.43)


class BridgeProducerDrift(unittest.TestCase):
    """Fix 5: realized_pnl groups by position_id, which the bridge only
    started sending on 2026-08-31. If the server source ever drops the key,
    the fallback (order) silently mis-groups partial closes again — fail
    loudly here instead (b36 drift-test pattern)."""

    def test_server_emits_position_id_in_deals(self):
        src = (REPO / 'scripts' / 'mt5_http_server_v2.py').read_text()
        self.assertIn('"position_id"', src,
                      'bridge server no longer emits position_id in '
                      '/api/history/deals — realized_pnl grouping breaks')


if __name__ == '__main__':
    unittest.main()
