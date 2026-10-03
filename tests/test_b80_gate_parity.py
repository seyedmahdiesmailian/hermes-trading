"""b80 — the lab harness must apply the LIVE grade gate to the funnel baseline.

Root cause (found 2026-09-05, round 17 review): `run_arm()` passed only
`min_rr` to `backtest_ohlc` and never `min_grade`, while the canonical
live-parity runner `engines.backtest_real.run_backtest` defaults to
`min_grade="B", min_rr=1.5`. Every round's CURRENT_FUNNEL baseline therefore
traded the 58-67% C-grade setups the live executor rejects: the bar was
measured ~0.15-0.24R too LOW on all four independent windows. Lab arms all
declare grade "B", so the fix is a no-op for them and only raises the bar —
which is why it is safe and why it had gone unnoticed.

Pins:
1. run_arm's default min_grade IS the live constant (imported, not restated),
   and passing min_grade=None reproduces the old ungated shape.
2. The shipped b80 JSON carries all three gate conventions per leg, so the
   delta is auditable without re-running anything.
3. The RR gate is REDUNDANT for the funnel: no funnel signal is below
   MIN_RISK_REWARD on any leg (rr floor is 1.55), so gradeB == gradeB_rr15.
   If that ever stops being true the funnel changed and this test must be
   re-read, not deleted.
4. The grade gate is NOT redundant: it rejects a majority of funnel signals
   on every leg (>40%), and it lifts exp_R on every leg — the baseline was
   strictly worse than live, never better (no gate was weakened).
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engines import lab_harness as lh  # noqa: E402
from engines.auto_executor import MIN_RISK_REWARD, MIN_SETUP_GRADE  # noqa: E402

PARITY = os.path.join(ROOT, "data", "backtest", "b80_gate_parity.json")
LEGS = ("cached", "W1", "W2", "W3", "W4")


def _load():
    with open(PARITY) as f:
        return json.load(f)


class TestHarnessDefaultsToLiveGates(unittest.TestCase):
    def test_run_arm_default_grade_is_the_live_constant(self):
        import inspect
        sig = inspect.signature(lh.run_arm)
        self.assertIs(sig.parameters["min_grade"].default,
                      MIN_SETUP_GRADE,
                      "run_arm must default to the LIVE MIN_SETUP_GRADE object, "
                      "not a restated literal (b80 parity)")
        self.assertIs(lh.LIVE_MIN_GRADE, MIN_SETUP_GRADE)
        self.assertEqual(lh.LIVE_MIN_RR, MIN_RISK_REWARD)

    def test_grade_gate_changes_a_c_grade_arm(self):
        # Anti-vacuity: an arm that emits a C-grade signal must be measured
        # under the live gate by default and NOT under min_grade=None.
        rows = [{"time": 1784109600 + 900 * i, "open": 100.0, "high": 101.0,
                 "low": 99.0, "close": 100.0} for i in range(400)]

        def sig_c(row):
            return {"side": "BUY", "entry": 100.0, "sl": 99.0, "tp": 102.0,
                    "style": "test_arm", "grade": "C"}

        gated = lh.run_arm(rows, sig_c)
        ungated = lh.run_arm(rows, sig_c, min_grade=None)
        self.assertEqual(gated["ladder"]["trades"], 0,
                         "a C-grade arm must be rejected by the live gate")
        self.assertIn("grade", gated.get("zero_reason", ""),
                      "the zero_reason must name the grade clause (b69 class)")
        self.assertGreater(ungated["ladder"]["trades"], 0,
                           "min_grade=None must still measure (old behaviour)")


class TestShippedParityJson(unittest.TestCase):
    def _priced(self, d, leg):
        """b222: only legs the b182 M5 source covers price the b187 trigger.
        An uncovered leg has no signals, and its claims must not be pinned."""
        return d[leg]["_signals"] > 0

    def test_all_three_conventions_present_per_leg(self):
        d = _load()["legs"]
        self.assertEqual(sorted(d), sorted(LEGS))
        for leg, row in d.items():
            for mode in ("nogates", "gradeB", "gradeB_rr15"):
                self.assertIn(mode, row, f"{leg} missing {mode}")
                # b222: an uncovered leg prices zero signals, so every mode
                # legitimately measures nothing. Only a priced leg must trade.
                if self._priced(d, leg):
                    self.assertGreater(row[mode]["trades"], 0,
                                       f"{leg}/{mode} measured nothing")

    def test_rr_gate_is_redundant_for_the_funnel(self):
        d = _load()["legs"]
        for leg, row in d.items():
            if not self._priced(d, leg):
                continue
            # b222 (2026-10-02, measured): the RR gate is redundant in EXP_R on
            # W1/W2 but not on cached, where it costs one net-negative trade
            # (59 -> 58) and lifts exp_R 0.223 -> 0.226. So the gate is mildly
            # USEFUL against the trigger-priced funnel, not redundant: it must
            # never LOWER exp_R (that would mean the funnel was trading below
            # the live bar and the gate was hurting it). The pre-b222 pin
            # asserted signals_below_live_rr == 0; the trigger-priced funnel
            # admits one sub-floor signal, so the count is bounded, not zeroed.
            self.assertGreaterEqual(row["gradeB_rr15"]["exp_R"],
                                    row["gradeB"]["exp_R"],
                                    f"{leg}: the RR gate LOWERS funnel exp_R — the "
                                    "baseline was not near the live bar")
            below = row["signals_below_live_rr"]
            self.assertLessEqual(below, max(1, row["_signals"] // 100),
                                 f"{leg}: {below} signals below the live RR floor — "
                                 "the funnel is not near the gate's own bar")

    def test_grade_gate_is_not_redundant_and_only_raises_the_bar(self):
        d = _load()["legs"]
        for leg, row in d.items():
            if not self._priced(d, leg):
                continue
            # b222 (2026-10-02, measured): the grade gate is REDUNDANT against
            # the trigger-priced funnel. Pre-b222 the funnel traded 58-67%
            # C-grade setups the live gate rejects, so nogates > gradeB in trades
            # and gradeB exp_R > nogates exp_R. With the trigger priced the
            # cached funnel emits 0 C-grade signals (mix {A: 31, B: 74}), so
            # nogates == gradeB on trades AND exp_R on every priced leg. The
            # C-grade admission was an artifact of the funnel never confirming,
            # not a property of the setup universe.
            self.assertNotIn("C", row["grade_mix"],
                             f"{leg}: the trigger-priced funnel still admits "
                             "C-grade setups the live gate rejects — re-read "
                             "b80's premise against the triggered funnel")
            self.assertEqual(row["gradeB"]["trades"], row["nogates"]["trades"],
                             f"{leg}: the grade gate must be a no-op against a "
                             "funnel that already emits only A/B setups")
            self.assertEqual(row["gradeB"]["exp_R"], row["nogates"]["exp_R"],
                             f"{leg}: the grade gate moved exp_R on a C-free funnel")

    def test_corrected_bar_is_the_shipped_funnel_reference(self):
        # The numbers this run re-scored every lab arm against.
        # b222 (2026-10-02): the bar re-anchored once the b187 M5 trigger was
        # priced. Pre-b222 the funnel could never confirm on an M15-spaced feed,
        # so the population was ~3x larger and exp_R was measured over trades
        # the live system would never have taken. These are the first numbers
        # measured on a funnel the live path agrees with. W3/W4 are outside the
        # M5 source and price nothing (checked for shape elsewhere, not here).
        d = _load()["legs"]
        expected = {"cached": 0.223, "W1": 0.280, "W2": -0.372,
                    "W3": None, "W4": None}
        for leg, exp in expected.items():
            got = d[leg]["gradeB"]["exp_R"]
            if exp is None:
                self.assertIsNone(got, f"{leg} outside the M5 source must be empty")
            else:
                self.assertAlmostEqual(got, exp, places=3,
                                       msg=f"{leg} corrected bar moved")


if __name__ == "__main__":
    unittest.main()
