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


def _bar(c: float) -> dict:
    """Bar with a 20-unit body. classify_bias reads only high/low/close, and
    only close participates in the direction count."""
    return {"open": 0, "high": c + 10, "low": c - 10, "close": c, "tick_volume": 1}


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


if __name__ == "__main__":
    unittest.main()
