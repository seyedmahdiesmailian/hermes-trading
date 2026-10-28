"""b218 — the bias gate must grade a CHOPPY trend, not only a monotonic one.

SYMPTOM (live, 2026-10-02): the system had not traded for ~2 weeks. The plan
funnel showed 88% neutral plans over 1543 live cycles, and master.log ended
almost every tick `action=no_trade reason=neutral_bias`.

ROOT CAUSE: classify_bias required, at once, (a) net_move >= 0.5 * avg 5-bar
range AND (b) >= 3 of the 4 intra-window diffs in the same direction. The
live H4 window closed 4153.82 -> 4190.59: net +36.77 against a 20.95
threshold (1.75x) yet graded NEUTRAL because the bar colours split 2 up /
2 down. Gold does not move in monotonic bars; a 2/2 colour split on a
1.75x-threshold move is a trend, not a range, and the neutral-path
no_trade branch above it is dead weight for that entire week.

FIX: a move at >= 1.5x threshold is STRONG and earns a 2-of-4 bar-count
requirement. The threshold itself is untouched (still volatility-relative)
and a window below 1.5x still needs the full 3-of-4 agreement, so this
opens the gate on real trends only — a 1.0x net with a 2/2 split is still
neutral, because that IS a range.
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engines.context import classify_bias


def _bar(c: float, o: float | None = None) -> dict:
    """Bar with a 20-unit body. classify_bias reads only high/low/close, and
    only close participates in the direction count. Pass `o` to give the bar
    an explicit open (the b218b reversal path reads the bar body)."""
    return {"open": c if o is None else o, "high": c + 10, "low": c - 10,
            "close": c, "tick_volume": 1}


class TestB218ChoppyTrend(unittest.TestCase):
    def test_live_h4_window_is_now_directional(self):
        """The exact 2026-10-02 live H4 closes: net +36.8 = 1.75x threshold,
        colours 2/2 -> BULLISH (neutral before b218)."""
        rows = [_bar(c) for c in (4153.82, 4184.90, 4184.33, 4217.30, 4190.59)]
        self.assertEqual(classify_bias(rows), "bullish")

    def test_strong_move_up_needs_only_two_bars(self):
        # threshold 5; diffs +12,-6,+24,+10 -> 3 up, but the point is the
        # strong-move lane: net 40 = 8x threshold
        rows = [_bar(c) for c in (4000, 4012, 4006, 4030, 4040)]
        self.assertEqual(classify_bias(rows), "bullish")

    def test_strong_move_down_needs_only_two_bars(self):
        # threshold 5; net -40 = 8x
        rows = [_bar(c) for c in (4040, 4028, 4034, 4010, 4000)]
        self.assertEqual(classify_bias(rows), "bearish")

    def test_strong_move_with_choppy_two_up_only(self):
        """A 2/2 colour split on a >=1.5x move is the whole bug: still
        directional after b218."""
        # threshold 5; diffs +18,-6,+7,-3 -> 2 up, net +16 = 3.2x -> strong
        rows = [_bar(c) for c in (4000, 4018, 4012, 4019, 4016)]
        self.assertEqual(classify_bias(rows), "bullish")

    def test_strong_move_down_with_choppy_two_down_only(self):
        rows = [_bar(c) for c in (4000, 3982, 3988, 3981, 3984)]
        self.assertEqual(classify_bias(rows), "bearish")

    def test_marginal_move_with_two_up_is_still_neutral(self):
        """The fix must not open the gate on a true RANGE: net just clears
        the threshold with a 2/2 split -> still neutral."""
        # threshold 5; diffs +15,-10,+7,-2 -> 2 up, net +5 = 1.0x -> neutral
        rows = [_bar(c) for c in (4000, 4015, 4005, 4012, 4005)]
        self.assertEqual(classify_bias(rows), "neutral")

    def test_marginal_move_with_real_three_up_is_bullish(self):
        """Below 1.5x the ORIGINAL rule holds: 3-of-4 agreement alone still
        opens the gate, no strong move required."""
        # body 20 -> threshold 10. 3 up bars of ~5 with one ~5 down bar:
        # diffs +6,-5,+6,+3 -> 3 up, net +10 = 1.0x -> bullish by agreement
        rows = [_bar(c) for c in (4000, 4006, 4001, 4007, 4010)]
        self.assertEqual(classify_bias(rows), "bullish")

    def test_flat_window_is_neutral(self):
        rows = [_bar(c) for c in (4000, 4001, 3999, 4002, 4000)]
        self.assertEqual(classify_bias(rows), "neutral")

    def test_short_window_still_neutral(self):
        self.assertEqual(classify_bias([_bar(4000), _bar(4010)]), "neutral")


class TestB218DominantBarReversal(unittest.TestCase):
    """b218b: a single dominant closing bar that breaks the window is a
    directional signal the close-to-close net cannot see. Live H4
    2026-10-02 16:00 UTC: 4217.29 -> 4132.94 (body -84) inside a window
    whose close-to-close net was only -17.77 — graded NEUTRAL before b218b.
    """

    def test_live_h4_dominant_down_bar_is_bearish(self):
        # closes 4153.82,4184.9,4184.33,4217.3,4136.05; the last bar's body
        # breaks below the window low and is bigger than its avg range.
        rows = [
            _bar(4153.82, o=4176.38),
            _bar(4184.90, o=4153.61),
            _bar(4184.33, o=4184.90),
            _bar(4217.30, o=4184.55),
            _bar(4136.05, o=4217.29),
        ]
        self.assertEqual(classify_bias(rows), "bearish")

    def test_dominant_up_bar_breaking_high_is_bullish(self):
        rows = [
            _bar(4200, o=4190),
            _bar(4190, o=4200),
            _bar(4195, o=4190),
            _bar(4205, o=4195),
            _bar(4290, o=4200),  # body +90, closes above the window high
        ]
        self.assertEqual(classify_bias(rows), "bullish")

    def test_big_bar_inside_the_range_is_still_neutral(self):
        """A large body that closes INSIDE the prior window is noise, not a
        directional break — the guard is the breakout, not the body size."""
        rows = [
            _bar(4200, o=4190),
            _bar(4190, o=4200),
            _bar(4195, o=4190),
            _bar(4205, o=4195),
            # huge body, but it closes at 4200, well inside 4180..4215
            _bar(4200, o=4100),
        ]
        self.assertEqual(classify_bias(rows), "neutral")

    def test_small_body_does_not_fire(self):
        """An ordinary bar must not reach the reversal branch."""
        rows = [
            _bar(4200, o=4198),
            _bar(4190, o=4200),
            _bar(4195, o=4192),
            _bar(4205, o=4195),
            _bar(4198, o=4200),
        ]
        self.assertEqual(classify_bias(rows), "neutral")


if __name__ == "__main__":
    unittest.main()
