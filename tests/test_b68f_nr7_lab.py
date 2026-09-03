"""b68 round 5 (NR7 compression-breakout lab) — integrity pins.

The lab arms are throwaway research code, but four invariants of
scripts/b68f_nr7_lab.py are load-bearing for every future round:

1. NR7 definition: bar i is NR7 only if its plain range is the narrowest of
   the last NR bars INCLUDING itself. A definition that compared only the
   previous 6 bars would fire on bars that are not actually the squeeze, and
   the measured numbers would describe a different pattern than the name.
2. No lookahead: is_nr7/find_nr7/nr7_break may only read bars at index < i
   for the SIGNAL (entry is bar i's open — the signal bar i-1 is fully
   closed). A leak here inflates exp_R silently.
3. Close confirmation: a wick through the NR7 extreme that closes back
   inside must NOT fire (round 4's probe: wick-through is noise,
   close-through is continuation). Same-bar re-cross (prior close already
   beyond the level) must not fire either — only a FRESH cross counts.
4. The b69 range probe must report the dead arm's combo as ~0 on the cached
   set — that is the measured proof that b63's compression gate never fires
   and the reason this round exists. If the probe ever reports a big combo
   count on this dataset, either the data or the probe changed and b69's
   premise must be re-read.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts import b68f_nr7_lab as lab  # noqa: E402


class TestNR7Definition(unittest.TestCase):
    def _mk(self, ranges, i):
        """Synthetic bars with given (high-low) ranges; returns saved state."""
        rows = []
        for k, r in enumerate(ranges):
            rows.append({"time": 1000000 + 900 * k, "open": 100.0,
                         "high": 100.0 + r / 2, "low": 100.0 - r / 2,
                         "close": 100.0})
        saved = lab.M15, lab.IDX
        lab.M15 = rows
        return saved

    def test_narrowest_of_window_including_itself(self):
        # window of 7 ending at index 9: ranges [5,4,3,2,1.5,4,4, 0.8]
        ranges = [5, 4, 3, 2, 1.5, 4, 4, 0.8] + [3] * 5
        saved = self._mk(ranges, 8)
        try:
            self.assertTrue(lab.is_nr7(7))          # 0.8 is the min of 1..7
            self.assertFalse(lab.is_nr7(8))         # 3.0 is not (0.8 in window)
            self.assertFalse(lab.is_nr7(6))         # 4.0 loses to 1.5
        finally:
            lab.M15, lab.IDX = saved

    def test_window_left_edge_is_exclusive(self):
        # The window is bars i-NR+1..i. A bar NARROWER at i-NR must NOT
        # disqualify bar i (an off-by-one that widens the window leftwards
        # silently changes the pattern: NR7 becomes NR8).
        ranges = [1.0] + [5, 5, 5, 5, 5, 5, 3.0] + [4] * 5
        saved = self._mk(ranges, 8)
        try:
            self.assertTrue(lab.is_nr7(7))     # window 1..7: 3.0 is the min
            self.assertFalse(lab.is_nr7(8))    # window 2..8: 3.0 still beats 4.0
        finally:
            lab.M15, lab.IDX = saved

    def test_tie_counts_as_nr7(self):
        # equal-minimum bar: <= comparison means a tie still fires (the
        # definition is "no bar in the window is narrower", not "strictly")
        ranges = [9] + [3] * 7 + [3] * 5
        saved = self._mk(ranges, 8)
        try:
            self.assertTrue(lab.is_nr7(7))          # window 1..7 all tie at 3
            self.assertTrue(lab.is_nr7(8))          # window 2..8 still ties
        finally:
            lab.M15, lab.IDX = saved


class TestNoLookahead(unittest.TestCase):
    def test_find_nr7_never_returns_the_signal_or_entry_bar(self):
        # find_nr7(i) scans j <= i-2: the breakout bar (i-1) may not itself
        # be the NR7 bar (its range is by construction > the old range).
        saved = lab.M15, lab.IDX
        try:
            lab.M15 = [{"time": 1000000 + 900 * k, "open": 100.0,
                        "high": 100.0 + (0.1 if k < 20 else 9.0),
                        "low": 100.0 - 0.1, "close": 100.0}
                       for k in range(40)]
            j = lab.find_nr7(30)                    # bars 20..30 are wide
            self.assertIsNotNone(j)
            self.assertLessEqual(j, 28)             # strictly before i-1=29
            self.assertTrue(lab.is_nr7(j))
        finally:
            lab.M15, lab.IDX = saved

    def test_entry_is_next_bar_open_not_signal_close(self):
        # Build: NR7 squeeze at j, then bar i-1 closes THROUGH j's high,
        # bar i has a distinctive open. The signal's entry must be THAT open.
        saved = lab.M15, lab.IDX, lab.LEVELS if hasattr(lab, "LEVELS") else None
        rows = []
        for k in range(30):
            rows.append({"time": 1000000 + 900 * k, "open": 100.0,
                         "high": 100.2, "low": 99.8, "close": 100.0})
        # bars 23..29 = NR7 window; bar 28 is the squeeze (narrowest)
        rows[28] = {"time": 1000000 + 900 * 28, "open": 100.0,
                    "high": 100.05, "low": 99.95, "close": 100.0}
        # bar 29 = breakout bar: closes through the squeeze high (100.05)
        rows[29] = {"time": 1000000 + 900 * 29, "open": 100.0,
                    "high": 100.6, "low": 99.99, "close": 100.5}
        # bar 30 = entry bar with a distinctive open
        rows.append({"time": 1000000 + 900 * 30, "open": 100.45,
                     "high": 100.7, "low": 100.4, "close": 100.6})
        lab.M15 = rows
        try:
            sig = lab.nr7_break(30, wide=True)
            self.assertIsNotNone(sig)
            self.assertEqual(sig["side"], "BUY")
            self.assertAlmostEqual(sig["entry"], 100.45, places=6)  # bar 30 open
        finally:
            lab.M15, lab.IDX = saved[:2]


class TestCloseConfirmation(unittest.TestCase):
    def _setup_rows(self, sig_close, prior_close=100.0):
        rows = []
        for k in range(30):
            rows.append({"time": 1000000 + 900 * k, "open": 100.0,
                         "high": 100.2, "low": 99.8, "close": 100.0})
        rows[28] = {"time": 1000000 + 900 * 28, "open": 100.0,
                    "high": 100.05, "low": 99.95, "close": 100.0}
        rows[29] = {"time": 1000000 + 900 * 29, "open": 100.0,
                    "high": 100.6, "low": 99.99, "close": sig_close}
        rows.append({"time": 1000000 + 900 * 30, "open": 100.2,
                     "high": 100.4, "low": 100.1, "close": 100.3})
        return rows

    def _run(self, sig_close):
        saved = lab.M15, lab.IDX
        lab.M15 = self._setup_rows(sig_close)
        try:
            return lab.nr7_break(30, wide=True)
        finally:
            lab.M15, lab.IDX = saved

    def test_wick_through_close_inside_does_not_fire(self):
        # high 100.6 pierces the squeeze high 100.05 but close 100.0 is back
        # inside -> sweep, not breakout
        self.assertIsNone(self._run(100.0))

    def test_prior_close_already_outside_does_not_refire(self):
        # both signal and prior closes beyond the level -> not a fresh cross
        # (the arm must not chain entries off one break)
        saved = lab.M15, lab.IDX
        rows = self._setup_rows(100.5)
        rows[28]["close"] = 100.4          # prior bar (i-2) already closed above
        lab.M15 = rows
        try:
            self.assertIsNone(lab.nr7_break(30, wide=True))
        finally:
            lab.M15, lab.IDX = saved

    def test_close_through_fires_with_geometry(self):
        sig = self._run(100.5)             # closes above squeeze high
        self.assertIsNotNone(sig)
        self.assertEqual(sig["side"], "BUY")
        self.assertLess(sig["sl"], 100.05)             # wide stop beyond level
        self.assertAlmostEqual(sig["tp"] - sig["entry"],
                               2 * (sig["entry"] - sig["sl"]), places=6)


class TestLedgerAndProbe(unittest.TestCase):
    def test_range_probe_confirms_b63_gate_is_dead(self):
        # b69's premise, measured: the full b63 combo (tight 12-bar range
        # AND contracting halves AND impulse body) fires ~never on gold M15.
        p = os.path.join(ROOT, "data", "backtest", "b68f_nr7_lab.json")
        with open(p) as f:
            res = json.load(f)
        probe = res["_range_probe"]
        self.assertLessEqual(probe["b63_combo_count"], 2)
        self.assertGreater(probe["nr7_count"], 100)    # the healed definition fires
        self.assertGreater(probe["tight_0.9atr_count"], -1)  # key present

    def test_lab_results_are_recorded(self):
        p = os.path.join(ROOT, "data", "backtest", "b68f_nr7_lab.json")
        with open(p) as f:
            res = json.load(f)
        for arm in ("nr7_break_c", "nr7_break_w10"):
            for mode in ("plain", "ladder"):
                row = res[f"{arm}:{mode}"]
                self.assertGreater(row["trades"], 0, f"{arm}:{mode} fired 0")
                self.assertIn("exp_R", row)


if __name__ == "__main__":
    unittest.main()
