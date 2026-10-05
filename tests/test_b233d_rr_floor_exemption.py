"""b233d — the RR floor is style-aware, not global.

The finding (5000-bar OOS study, 2026-10-04, 5 disjoint windows): the
MIN_RISK_REWARD floor is actively harmful on aggressive_value_entry. That
style netted +115.00 over 27 trades at 70% wr while 93% of its trades have
realized rr < 2.0 — the floor kills the edge to spare losers in the worse
styles. Exempting it (and pullback_continuation) won 5/5 disjoint windows
at +203.89 over 31 trades, vs 4/5 at +130.12 over 5 for the global floor.

This test pins the causal rule: the exempt set, and that the floor still
binds on every other style.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engines import auto_executor as ae
from engines.auto_executor import (MIN_RISK_REWARD, RR_FLOOR_EXEMPT_STYLES,
                                   STYLE_RISK_MULT)


class TestFloorExemptionSet(unittest.TestCase):
    def test_the_two_strong_styles_are_exempt(self):
        self.assertIn("aggressive_value_entry", RR_FLOOR_EXEMPT_STYLES)
        self.assertIn("pullback_continuation", RR_FLOOR_EXEMPT_STYLES)

    def test_the_chase_styles_are_not_exempt(self):
        # the floor must still bind on the losers it was protecting against
        for chase in ("aggressive_discount_entry", "aggressive_premium_entry"):
            self.assertNotIn(chase, RR_FLOOR_EXEMPT_STYLES,
                             f"{chase} must NOT be exempt — it netted negative")

    def test_exempt_set_is_immutable(self):
        # frozenset so nothing can mutate the exempt set at runtime
        self.assertIsInstance(RR_FLOOR_EXEMPT_STYLES, frozenset)


class TestFloorBehavior(unittest.TestCase):
    """The causal rule: exempt styles skip the floor, all others hit it."""

    def _prop(self, rr: float, style: str):
        # rr is the planned rr: |tp-entry| / |entry-sl|
        return {
            "blueprint": {"side": "BUY", "entry_price": 4450.0,
                          "sl": 4440.0, "tp": 4450.0 + 10.0 * rr,
                          "symbol": "XAUUSD"},
            "grade": "B",
            "execution_style": style,
        }

    def _pol(self):
        return {"trade_allowed": True, "regime": "normal",
                "open_positions": 0, "balance": 5000.0}

    def _run(self, rr, style):
        import engines.cooldown as cd
        real_market = ae.is_market_open
        real_cd = cd.check_entry_cooldown
        ae.is_market_open = lambda *a, **k: True
        cd.check_entry_cooldown = lambda now=None: {"allowed": True}
        try:
            from engines.auto_executor import evaluate_proposal
            from engines.risk import compute_performance_state
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            perf = compute_performance_state({}, now.date().isoformat(),
                                             5000.0, [])
            return evaluate_proposal(self._prop(rr, style), self._pol(), perf,
                                     {}, None)
        finally:
            ae.is_market_open = real_market
            cd.check_entry_cooldown = real_cd

    def test_exempt_style_admitted_below_floor(self):
        r = self._run(1.2, "aggressive_value_entry")
        self.assertTrue(r.get("execute"),
                        f"exempt style must pass below floor, got {r.get('reason')}")

    def test_exempt_style_admitted_at_terrible_rr(self):
        r = self._run(0.5, "pullback_continuation")
        self.assertTrue(r.get("execute"),
                        f"exempt style must pass even at rr 0.5, got {r.get('reason')}")

    def test_chase_style_rejected_below_floor(self):
        r = self._run(1.2, "aggressive_discount_entry")
        self.assertFalse(r.get("execute"))
        self.assertEqual(r.get("reason"), "poor_rr_1.20")

    def test_chase_style_admitted_at_floor(self):
        r = self._run(MIN_RISK_REWARD, "aggressive_discount_entry")
        self.assertTrue(r.get("execute"),
                        f"chase style must pass at floor, got {r.get('reason')}")

    def test_floor_value_unchanged_for_chase_styles(self):
        # the exemption only lowers the floor for the exempt set; the chase
        # styles still see exactly MIN_RISK_REWARD
        r = self._run(MIN_RISK_REWARD - 0.01, "aggressive_premium_entry")
        self.assertFalse(r.get("execute"))


if __name__ == "__main__":
    unittest.main()
