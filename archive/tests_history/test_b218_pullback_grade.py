"""b218 — a pullback setup must be able to clear MIN_SETUP_GRADE.

The grade rule had one B path: `alignment == "aligned" and trend >= 1.2`.
But engines.context._detect_regime only emits pullback_continuation when
H1 and H4 AGREE while M5 reacts AGAINST them — a mixed alignment by
construction, and exactly the entry the plan was built to wait for. Every
pullback_continuation plan therefore graded C, MIN_SETUP_GRADE=B killed it,
and the engine could recognise its highest-probability setup while being
forbidden from trading it. This was the second half of the ~2-week trade
drought (88% of 1543 live plans graded neutral at the bias gate; the
directional remainder mostly died here).

The fix adds a B path for pullback_continuation when the HTF pair agrees
and trend is real. It is deliberately tight: trend >= 1.2, regime must be
the continuation regime (not a raw "mixed" alignment), and h1/h4 must
match exactly. A counter-trend chop with no HTF agreement still gets C.
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engines.plan import grade_qualifies, setup_grade

MIN_B = True


def _plan(alignment, trend, regime, h1=None, h4=None, m5=None):
    return {"quality": {
        "alignment": alignment,
        "trend_strength": trend,
        "regime": regime,
        "bias_votes": {"m5": m5 or "neutral", "h1": h1, "h4": h4},
    }}


class TestB218PullbackGrade(unittest.TestCase):
    def test_pullback_with_htf_agreement_grades_B(self):
        """The bug: M5 reacts against a HTF-aligned trend. Alignment is
        'mixed', but the setup is the pullback the plan wants."""
        plan = _plan("mixed", 1.5, "pullback_continuation",
                     h1="bullish", h4="bullish", m5="bearish")
        self.assertEqual(setup_grade(plan), "B")
        self.assertTrue(grade_qualifies(setup_grade(plan)))

    def test_pullback_with_htf_agreement_down_grades_B(self):
        plan = _plan("mixed", 1.5, "pullback_continuation",
                     h1="bearish", h4="bearish", m5="bullish")
        self.assertEqual(setup_grade(plan), "B")

    def test_pullback_without_htf_agreement_stays_C(self):
        """No HTF agreement: a counter-trend chop, not a pullback."""
        plan = _plan("mixed", 1.5, "pullback_continuation",
                     h1="bullish", h4="bearish", m5="bearish")
        self.assertEqual(setup_grade(plan), "C")
        self.assertFalse(grade_qualifies(setup_grade(plan)))

    def test_pullback_with_weak_trend_stays_C(self):
        """trend < 1.2 is not a real continuation."""
        plan = _plan("mixed", 1.1, "pullback_continuation",
                     h1="bullish", h4="bullish", m5="bearish")
        self.assertEqual(setup_grade(plan), "C")

    def test_mixed_without_continuation_regime_stays_C(self):
        """The gate is the REGIME, not the mixed label alone."""
        plan = _plan("mixed", 2.5, "range",
                     h1="bullish", h4="bullish", m5="bearish")
        self.assertEqual(setup_grade(plan), "C")

    def test_aligned_strong_continuation_still_A(self):
        plan = _plan("aligned", 3.5, "pullback_continuation",
                     h1="bullish", h4="bullish", m5="bullish")
        self.assertEqual(setup_grade(plan), "A")

    def test_aligned_with_trend_still_B(self):
        plan = _plan("aligned", 1.5, "range",
                     h1="bullish", h4="bullish", m5="bullish")
        self.assertEqual(setup_grade(plan), "B")

    def test_pullback_missing_votes_stays_C(self):
        """Fail-closed: a plan without bias_votes cannot prove HTF
        agreement, so it must not inherit a B."""
        plan = {"quality": {"alignment": "mixed", "trend_strength": 1.5,
                            "regime": "pullback_continuation"}}
        self.assertEqual(setup_grade(plan), "C")


if __name__ == "__main__":
    unittest.main()
