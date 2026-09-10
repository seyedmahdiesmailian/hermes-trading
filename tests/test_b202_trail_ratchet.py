"""b202 (2026-09-10) — the live runner trail must be a RATCHET.

evaluate_trade_management's trail_stop branch computed
`new_sl = price ∓ trail_distance` and shipped it to the broker with NO
comparison against the SL already on the book. The live-parity funnel
(engines/backtest.py) has always ratcheted: `if cand > t["sl"]` for a BUY
(`<` for a SELL). So on every pullback after the second TP fill, live
proposed a stop BEHIND the current one — giving back the breakeven lock and
the harvested runner profit — while every stored exp_R was priced on a
funnel that never does that.

This is the b123/b189 drift class in mirror: lab stricter than live. The fix
is strictly TIGHTENING (it only refuses to loosen a stop that is already in
force; no gate, share or trigger changed), so no stored ledger needs a
re-derivation — the funnel already models the fixed behaviour.

TestB202* methods pin, in both directions:
  - an improving trail still fires (the exit chain is not weakened),
  - a non-improving trail holds with reason trail_stop_not_improving,
  - the b44 broker-validity hold is untouched and still ordered after it,
  - the breakeven LOCK (entry ± 0.15·risk) survives a bounce that would
    previously have erased it,
  - the funnel's ratchet line is the same rule (source pin, b109 class).
"""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from engines.trade_management import evaluate_trade_management  # noqa: E402


def runner_trade(side, entry, sl, filled, tp3):
    """A trade that has passed the trail-eligibility gates: 2 TPs filled,
    breakeven done, runner alive, no farther target hit."""
    return {
        'symbol': 'XAUUSD', 'side': side, 'entry_price': entry, 'sl': sl,
        'tp_levels': filled + [tp3], 'tp_shares': [0.5, 0.3, 0.2],
        'scale_in_levels': [], 'scaled_in_levels': [],
        'filled_tp_levels': list(filled),
        'breakeven_active': True, 'runner_active': True,
        'thesis_valid': True, 'setup_grade': 'B',
        'momentum_strength': 0.5, 'volatility_state': 'normal',
        'structure_state': 'healthy', 'rr_remaining': 2.0,
        'exposure_fraction': 0.5, 'volume': 0.08,
    }


NOW = datetime.now(timezone.utc)


class TestB202TrailIsARatchet(unittest.TestCase):

    # BUY geometry: entry 4450, SL already trailed to 4470 (locked +20).
    # risk=|4450-4470|=20 → trail distance = max(20*0.3, 3.0) = 6.0.
    BUY_ENTRY, BUY_SL = 4450.0, 4470.0

    def _buy(self):
        return runner_trade('BUY', self.BUY_ENTRY, self.BUY_SL,
                            [4475.0, 4490.0], 4520.0)

    def test_b202_buy_trail_holds_when_price_pulls_back(self):
        # price 4472 → cand = 4472 - 6 = 4466 BEHIND the current 4470.
        # Pre-b202 this was proposed (and is broker-valid: 4466 < 4471.5),
        # i.e. live donated $4/oz of locked runner profit per bounce.
        m = evaluate_trade_management(self._buy(), 4472.0, NOW)
        self.assertEqual(m['action'], 'hold')
        self.assertEqual(m['reason'], 'trail_stop_not_improving')

    def test_b202_buy_trail_still_fires_when_price_runs(self):
        # price 4490 → cand = 4484 > 4470: a real improvement must pass —
        # the ratchet may never weaken the protective chain (hard rule).
        m = evaluate_trade_management(self._buy(), 4490.0, NOW)
        self.assertEqual(m['action'], 'trail_stop')
        self.assertAlmostEqual(m['new_sl'], 4484.0, places=2)
        self.assertGreater(m['new_sl'], self.BUY_SL)

    def test_b202_sell_trail_holds_when_price_bounces_up(self):
        # SELL mirror: entry 4450, SL trailed DOWN to 4430 (locked +20).
        # risk=20 → dist 6.0; price 4428 → cand = 4434 > 4430 = loosening.
        t = runner_trade('SELL', 4450.0, 4430.0, [4425.0, 4410.0], 4380.0)
        m = evaluate_trade_management(t, 4428.0, NOW)
        self.assertEqual(m['action'], 'hold')
        self.assertEqual(m['reason'], 'trail_stop_not_improving')

    def test_b202_sell_trail_still_fires_when_price_falls(self):
        t = runner_trade('SELL', 4450.0, 4430.0, [4425.0, 4410.0], 4380.0)
        m = evaluate_trade_management(t, 4408.0, NOW)
        self.assertEqual(m['action'], 'trail_stop')
        self.assertAlmostEqual(m['new_sl'], 4414.0, places=2)
        self.assertLess(m['new_sl'], 4430.0)

    def test_b202_equal_stop_holds_not_hammers(self):
        # cand == sl exactly (flat market at dist from the trailed stop):
        # no modify must be sent — the b44 anti-hammer intent, extended to
        # the no-op case (the broker accepts a same-SL modify; wasteful).
        t = runner_trade('SELL', 4450.0, 4430.0, [4425.0, 4410.0], 4380.0)
        m = evaluate_trade_management(t, 4424.0, NOW)  # 4424 + 6 = 4430
        self.assertEqual(m['action'], 'hold')
        self.assertEqual(m['reason'], 'trail_stop_not_improving')

    def test_b202_breakeven_lock_survives_a_bounce(self):
        # A locked-in stop (entry+3 for a BUY) on the book must survive a
        # bounce: risk=3 → dist max(0.9, 3.0)=3.0; price 4455 → cand 4452
        # < sl 4453 → the ratchet holds. Pre-b202 this shipped 4452,
        # donating back $1/oz of the lock per bounce. (The b202 run's first
        # fixture used price 4458 — cand 4455 > 4453, a REAL improvement —
        # which is why it failed green-code: arithmetic, not a defect.)
        entry, sl = 4450.0, 4453.0      # locked +3 above entry
        t = runner_trade('BUY', entry, sl, [4475.0, 4490.0], 4520.0)
        m = evaluate_trade_management(t, 4455.0, NOW)
        self.assertEqual(m['action'], 'hold')
        self.assertEqual(m['reason'], 'trail_stop_not_improving')
        # and the same trade at price 4462 → cand 4459 > 4453 must still
        # trail: the ratchet may not freeze legitimate progress either.
        m2 = evaluate_trade_management(t, 4462.0, NOW)
        self.assertEqual(m2['action'], 'trail_stop')
        self.assertGreater(m2['new_sl'], sl)

    def test_b202_broker_validity_hold_still_ordered_after_ratchet(self):
        # b44's invalid-vs-market hold must remain reachable for an
        # IMPROVING cand that sits too close to price: entry 4000, sl 3998
        # (never trailed, below entry), risk 2 → dist max(0.6, 3.0)=3.0;
        # price 4000.3 → cand 3997.3, the entry-clamp pins it to 4000 →
        # improving (4000 > 3998) but 4000 > 4000.3-0.5 → gap fails →
        # the b44 hold still fires after the ratchet lets it through.
        t = runner_trade('BUY', 4000.0, 3998.0, [4010.0, 4020.0], 4030.0)
        m = evaluate_trade_management(t, 4000.3, NOW)
        self.assertEqual(m['action'], 'hold')
        self.assertEqual(m['reason'], 'trail_stop_invalid_vs_market')
        # ORDERING proof: a LOOSENING cand that would also fail the b44 gap
        # must be held by the RATCHET reason, not b44's — entry 4000, sl
        # 4002, price 4000.2 → cand 3997.2 clamped to 4000 < 4002: the
        # ratchet answers first, so the reason names the ratchet.
        t2 = runner_trade('BUY', 4000.0, 4002.0, [4010.0, 4020.0], 4030.0)
        m2 = evaluate_trade_management(t2, 4000.2, NOW)
        self.assertEqual(m2['action'], 'hold')
        self.assertEqual(m2['reason'], 'trail_stop_not_improving')


class TestB202FunnelParityPin(unittest.TestCase):
    """The funnel line this fix copies — pinned at the source, not restated
    as a behaviour guess (b109: a re-quoted constant drifts; b122: verify the
    arm is the rule it is named for)."""

    def test_b202_funnel_trail_only_ratchets(self):
        src = open(os.path.join(ROOT, 'engines', 'backtest.py')).read()
        self.assertIn('if cand > t["sl"]:', src,
                      'the funnel no longer ratchets BUYs — the parity claim '
                      'behind b202 is void; re-read both paths before '
                      'trusting trail ledgers')
        self.assertIn('if cand < t["sl"]:', src,
                      'the funnel no longer ratchets SELLs (mirror line)')

    def test_b202_live_evaluator_carries_the_ratchet(self):
        src = open(os.path.join(ROOT, 'engines',
                                'trade_management.py')).read()
        self.assertIn('trail_stop_not_improving', src)
        self.assertIn('improves = new_sl > sl if side_buy else new_sl < sl',
                      src, 'b202: live trail must compare against the SL on '
                          'the book, like the funnel compares cand vs t["sl"]')


if __name__ == '__main__':
    unittest.main()
