"""Regression tests for the 2026-08-30 critical audit fixes.

1. trades_today must be COMPUTED (daily trade cap was dead code: the field
   was read by the gate but never written).
2. The signal path must run through evaluate_proposal — sizing comes from
   our risk model, never from the channel's raw lot.
"""
import unittest
from datetime import datetime, timezone


class TestTradesToday(unittest.TestCase):
    def test_counts_entry_deals_today(self):
        from engines.risk import compute_performance_state
        now = datetime.now(timezone.utc)
        deals = [
            {'ticket': 1, 'entry': 0, 'time': now.timestamp(), 'profit': 5.0},   # open today
            {'ticket': 2, 'entry': 0, 'time': now.timestamp(), 'profit': -5.0},  # open today
            {'ticket': 3, 'entry': 1, 'time': now.timestamp(), 'profit': 2.0},   # CLOSE, not an entry
            {'ticket': 4, 'entry': 0, 'time': now.timestamp() - 86400 * 3, 'profit': 1.0},  # old
        ]
        perf = compute_performance_state({}, now.date().isoformat(), 5000.0, deals)
        self.assertEqual(perf['trades_today'], 2)

    def test_rolls_over_on_new_day(self):
        from engines.risk import compute_performance_state
        old = {'day': '2020-01-01', 'trades_today': 5, 'daily_pnl': -99.0}
        perf = compute_performance_state(old, '2026-08-30', 5000.0, [])
        self.assertEqual(perf['trades_today'], 0)
        self.assertEqual(perf['daily_pnl'], 0.0)

    def test_monotonic_within_day(self):
        from engines.risk import compute_performance_state
        now = datetime.now(timezone.utc)
        deals = [{'ticket': 1, 'entry': 0, 'time': now.timestamp(), 'profit': 1.0}]
        perf = compute_performance_state(
            {'day': now.date().isoformat(), 'trades_today': 3, 'daily_pnl': 0.0},
            now.date().isoformat(), 5000.0, deals)
        self.assertEqual(perf['trades_today'], 3)  # never decreases mid-day


class TestSignalGateParity(unittest.TestCase):
    """evaluate_proposal must enforce the same gates for signal proposals."""

    def _pol(self):
        return {'trade_allowed': True, 'regime': 'normal',
                'open_positions': 0, 'balance': 5000.0}

    def _prop(self, sl=4460, tp=4435):
        return {'blueprint': {'side': 'SELL', 'entry_price': 4450,
                              'sl': sl, 'tp': tp, 'symbol': 'XAUUSD'},
                'grade': 'B'}

    def test_lot_comes_from_risk_model_not_channel(self):
        import engines.auto_executor as ae
        import engines.cooldown as cd
        real = ae.is_market_open
        real_cd = cd.check_entry_cooldown
        ae.is_market_open = lambda *a, **k: True
        cd.check_entry_cooldown = lambda now=None: {'allowed': True}
        try:
            from engines.auto_executor import evaluate_proposal
            from engines.risk import compute_performance_state
            now = datetime.now(timezone.utc)
            perf = compute_performance_state({}, now.date().isoformat(), 5000.0, [])
            r = evaluate_proposal(self._prop(), self._pol(), perf, {}, None)
            if not r.get('execute'):
                self.fail(f'expected execute, got {r.get("reason")}')
            # 2% of 5000 = $100 risk; 10pt SL = $10/lot → exactly 0.10 lots
            self.assertAlmostEqual(r['command']['lot'], 0.1, places=2)
            self.assertAlmostEqual(r['risk_usd'], 100.0, places=0)
        finally:
            ae.is_market_open = real
            cd.check_entry_cooldown = real_cd

    def test_grade_override_from_proposal(self):
        from engines.auto_executor import evaluate_proposal
        prop = self._prop()
        prop['grade'] = 'C'
        perf = {'day': 'x', 'daily_pnl': 0, 'trades_today': 0, 'loss_streak': 0}
        r = evaluate_proposal(prop, self._pol(), perf, {}, None)
        self.assertFalse(r['execute'])
        self.assertIn('grade_C_below_minimum', r['reasons'])

    def test_daily_cap_blocks(self):
        from engines.auto_executor import evaluate_proposal
        perf = {'day': 'x', 'daily_pnl': 0, 'trades_today': 5, 'loss_streak': 0}
        r = evaluate_proposal(self._prop(), self._pol(), perf, {}, None)
        self.assertFalse(r['execute'])
        self.assertEqual(r['reason'], 'daily_trade_limit')

    def test_position_cap_blocks(self):
        from engines.auto_executor import evaluate_proposal
        pol = self._pol()
        pol['open_positions'] = 2
        perf = {'day': 'x', 'daily_pnl': 0, 'trades_today': 0, 'loss_streak': 0}
        r = evaluate_proposal(self._prop(), pol, perf, {}, None)
        self.assertFalse(r['execute'])
        self.assertEqual(r['reason'], 'position_limit')


if __name__ == '__main__':
    unittest.main()
