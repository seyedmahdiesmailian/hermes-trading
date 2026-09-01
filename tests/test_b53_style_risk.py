"""b53 — per-entry-style risk sizing + backtest parity fix (2026-09-01).

Live incident chain: #103649120 (-105$) and #103506741 (-94$) were both
aggressive_discount_entry — the no-trigger lane that chases a move which
already left the plan zone. M5 parity backtest (6500 bars, 2026-09-01,
scripts/ab_m5_sweep.py): discount WR 52% vs premium 65%; the lane is still
net positive (+266$) so REMOVAL loses ~280$ — the fix is HALF RISK.

Also pinned: run_backtest's breakeven_at_r default was 0.5, a rule live
never executes (trade_management only brings SL to entry AFTER a TP fill,
modeled by partial_tp1_share). The phantom default produced 32 scratches
and a fake +943 vs the honest live-parity +1040 / 73.8% WR.
"""
from __future__ import annotations

import inspect
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _pol():
    return {'trade_allowed': True, 'regime': 'normal',
            'open_positions': 0, 'balance': 5000.0}


def _prop(style=None, sl=4460, tp=4435):
    p = {'blueprint': {'side': 'SELL', 'entry_price': 4450,
                       'sl': sl, 'tp': tp, 'symbol': 'XAUUSD'},
         'grade': 'B'}
    if style:
        p['execution_style'] = style
    return p


def _perf():
    from engines.risk import compute_performance_state
    now = datetime.now(timezone.utc)
    return compute_performance_state({}, now.date().isoformat(), 5000.0, [])


class TestStyleRiskMult(unittest.TestCase):
    def _eval(self, prop):
        import engines.auto_executor as ae
        import engines.cooldown as cd
        real, real_cd = ae.is_market_open, cd.check_entry_cooldown
        ae.is_market_open = lambda *a, **k: True
        cd.check_entry_cooldown = lambda now=None: {'allowed': True}
        try:
            return ae.evaluate_proposal(prop, _pol(), _perf(), {}, None)
        finally:
            ae.is_market_open, cd.check_entry_cooldown = real, real_cd

    def test_discount_entry_gets_half_risk(self):
        r = self._eval(_prop(style='aggressive_discount_entry'))
        self.assertTrue(r.get('execute'), r.get('reason'))
        # 2% of 5000 = $100, halved = $50; 10pt SL = $10/lot → 0.05 lots
        self.assertAlmostEqual(r['risk_pct'], 0.01, places=6)
        self.assertAlmostEqual(r['risk_usd'], 50.0, places=0)
        self.assertAlmostEqual(r['command']['lot'], 0.05, places=2)

    def test_premium_entry_keeps_full_risk(self):
        r = self._eval(_prop(style='aggressive_premium_entry'))
        self.assertTrue(r.get('execute'), r.get('reason'))
        self.assertAlmostEqual(r['risk_usd'], 100.0, places=0)
        self.assertAlmostEqual(r['command']['lot'], 0.10, places=2)

    def test_untagged_proposal_keeps_full_risk(self):
        # signal path / legacy callers carry no style tag — must not shrink
        r = self._eval(_prop())
        self.assertTrue(r.get('execute'), r.get('reason'))
        self.assertAlmostEqual(r['risk_usd'], 100.0, places=0)

    def test_style_mult_composes_with_defensive_regime(self):
        pol = _pol()
        pol['regime'] = 'defensive'
        import engines.auto_executor as ae
        import engines.cooldown as cd
        real, real_cd = ae.is_market_open, cd.check_entry_cooldown
        ae.is_market_open = lambda *a, **k: True
        cd.check_entry_cooldown = lambda now=None: {'allowed': True}
        try:
            r = ae.evaluate_proposal(_prop(style='aggressive_discount_entry'),
                                     pol, _perf(), {}, None)
        finally:
            ae.is_market_open, cd.check_entry_cooldown = real, real_cd
        self.assertTrue(r.get('execute'), r.get('reason'))
        # 2% * 0.5 (style) * 0.5 (defensive) = 0.5% → $25 → 0.02 lots
        self.assertAlmostEqual(r['risk_usd'], 25.0, places=0)
        self.assertAlmostEqual(r['command']['lot'], 0.02, places=2)


class TestProposalCarriesStyle(unittest.TestCase):
    def test_build_proposal_tags_execution_style(self):
        from hermes_runtime import _build_proposal
        monitor = {'action': 'market_entry_now',
                   'execution_style': 'aggressive_discount_entry',
                   'blueprint': {'side': 'SELL', 'entry_price': 4450,
                                 'sl': 4460, 'tp': 4435, 'symbol': 'XAUUSD'}}
        p = _build_proposal({}, monitor, {}, 4450.0)
        self.assertEqual(p['execution_style'], 'aggressive_discount_entry')

    def test_signal_path_proposals_untagged_is_legal(self):
        # signal_listener builds its own proposals; the executor must treat a
        # missing tag as FULL risk (documented in STYLE_RISK_MULT comment).
        from engines.auto_executor import STYLE_RISK_MULT
        self.assertNotIn('', STYLE_RISK_MULT)
        self.assertEqual(STYLE_RISK_MULT.get('anything_unlisted', 1.0), 1.0)


class TestBacktestParityDefaults(unittest.TestCase):
    def test_run_backtest_breakeven_default_is_live_parity(self):
        from engines.backtest_real import run_backtest
        sig = inspect.signature(run_backtest)
        self.assertEqual(sig.parameters['breakeven_at_r'].default, 0.0,
                         'live has no standalone BE-at-X rule; a nonzero '
                         'default silently diverges the backtest (b53)')

    def test_min_rr_is_sweepable(self):
        from engines.backtest_real import run_backtest
        sig = inspect.signature(run_backtest)
        self.assertIn('min_rr', sig.parameters)


if __name__ == '__main__':
    unittest.main()
