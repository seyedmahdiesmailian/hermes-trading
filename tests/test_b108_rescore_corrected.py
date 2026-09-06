"""b108 — the funnel baseline and the b70 lane decision set, re-measured under
the b105-CORRECTED backtest engine, and the numbers every past round quoted.

Why these numbers must be pinned: b105 fixed a double-count in
engines/backtest.py (the post-TP1 runner leg was booked at FULL size on top of
the realized partial, and a share>=1.0 TP1 fill — what the live b55/b60 ladder
does for the balanced/weak lanes — left a phantom runner alive that also
BLOCKED real entries). Every exp_R the b68 loop ever printed came out of the
inflated engine, including the 0.854R merit bar and the funnel's own
0.52-0.53 on W1..W4. b108 re-runs b81's measurement VERBATIM (b81's
measure_leg/verdict/lane closures imported, not restated) on the same bars.

Measured result (data/backtest/b108_rescore_corrected.json):

  funnel graded exp_R, inflated -> corrected
    cached 0.796 -> 0.285 | W1 0.676 -> 0.202 | W2 0.662 -> 0.206
    W3 0.767 -> 0.227     | W4 0.745 -> 0.222
  net_R collapses 2.5-3.2x; DD gets WORSE everywhere (W3 -5.1 -> -7.6).

Pins, in order of what would rot first:

1. REPRODUCTION: the `old_*` columns of this ledger equal the shipped b81
   ledger EXACTLY. If they don't, this run compared against the wrong baseline
   (e.g. b81's closures drifted) and every delta below is meaningless.
2. THE CORRECTED BAR: the re-derived merit bar matches the JSON, and the
   cached cell matches b105's own independently-measured 0.285 — two different
   scripts, one number.
3. THE CORRECTION IS NOT NEUTRAL: nr7htf's margin over the funnel shifts by
   the SAME SIGN on all four independent windows (+0.045..+0.093R) while the
   pdh-family shifts are mixed-sign and smaller. A neutral bug cannot produce
   a systematic one-sided shift, so arm-vs-arm comparisons made under the old
   engine were contaminated — this is the finding b105 predicted.
4. A DECISION-RELEVANT FLIP: lane_h4pdh's W4 comparison flips from a win
   (+0.019R) to a loss (-0.002R) purely because of the correction.
5. b70'S ANSWER STANDS, AND THE COUNTS MOVED: no lane replicates on all four
   windows under either engine, but three of four lanes lose one window to the
   correction (2->1, 3->2, 2->1). Pinning both counts means a future re-run
   that restores a count is a deliberate re-open, not silent drift.
6. THE BAR IS NOW ~0.2R, not 0.85R: pinned as a ceiling/floor pair so nobody
   quotes the pre-b105 numbers as current, and so a future "0.8 merit bar"
   claim fails loudly.
7. READ-ONLY ISOLATION: no live-path module imports this script.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LEDGER = os.path.join(ROOT, "data", "backtest", "b108_rescore_corrected.json")
B81 = os.path.join(ROOT, "data", "backtest", "b81_lane_rescore.json")
SCRIPT = os.path.join(ROOT, "scripts", "b108_rescore_corrected.py")

WINDOWS = ("W1", "W2", "W3", "W4")
LEGS = ("cached",) + WINDOWS
LANES = ("lane_gated_pdh_dayext", "lane_h4pdh", "lane_runway", "lane_nr7htf")
ARMS = ("funnel_graded", "funnel_ungraded") + LANES


def _load(path):
    with open(path) as f:
        return json.load(f)


def _cell_of(leg, arm):
    """The measured row for one arm on one leg (lanes nest under 'graded')."""
    row = LED[leg][arm]
    return row["graded"] if "graded" in row else row


LED = _load(LEDGER)
OLD = _load(B81)


class TestLedgerShape(unittest.TestCase):
    def test_every_leg_and_arm_present_with_both_conventions(self):
        for leg in LEGS:
            self.assertIn(leg, LED, f"leg {leg} missing")
            for arm in ARMS:
                cell = LED[leg].get(arm)
                self.assertTrue(cell, f"{arm} missing on {leg}")
            for lane in LANES:
                for conv in ("graded", "ungraded"):
                    self.assertIn(conv, LED[leg][lane])
            self.assertIn("_compare", LED[leg], f"{leg}: no compare block")

    def test_compare_block_is_not_vacuous(self):
        # b104 rule: a reality check that reads zero findings passes on a dead
        # predicate. Every arm on every leg must carry a delta.
        for leg in LEGS:
            cmp_ = LED[leg]["_compare"]
            self.assertEqual(set(cmp_.keys()), set(ARMS),
                             f"{leg}: compare block arms differ from the "
                             "measured arms")
            for arm in ARMS:
                self.assertIn(arm, cmp_, f"{leg}/{arm}: no compare cell")
                for k in ("d_exp_R", "d_net_R", "d_trades", "new", "old"):
                    self.assertIn(k, cmp_[arm], f"{leg}/{arm}: missing {k}")
                self.assertEqual(cmp_[arm]["new"]["exp_R"],
                                 _cell_of(leg, arm)["exp_R"],
                                 f"{leg}/{arm}: new cell disagrees with the "
                                 "measured row")

    def test_live_gate_is_the_imported_constant(self):
        from engines.auto_executor import MIN_SETUP_GRADE
        self.assertEqual(LED["_live_min_grade"], MIN_SETUP_GRADE,
                         "the rescore must apply the LIVE grade, not a "
                         "restated literal")


class TestReproductionAgainstShippedBaseline(unittest.TestCase):
    """The old_* columns ARE b81's shipped numbers, byte for byte."""

    def test_funnel_old_cells_equal_b81(self):
        for leg in LEGS:
            for arm in ("funnel_graded", "funnel_ungraded"):
                o = LED[leg]["_compare"][arm]["old"]
                s = OLD[leg][arm]
                for k in ("trades", "exp_R", "net_R", "maxDD_R"):
                    self.assertEqual(o[k], s[k],
                                     f"{leg}/{arm}: old.{k} {o[k]} != b81 "
                                     f"{s[k]} — wrong baseline")

    def test_lane_old_cells_equal_b81_graded(self):
        checked = 0
        for leg in LEGS:
            for lane in LANES:
                o = LED[leg]["_compare"][lane]["old"]
                s = OLD[leg][lane]["graded"]
                self.assertEqual(o["trades"], s["trades"],
                                 f"{leg}/{lane}: lane trade count differs "
                                 "from b81 — the lane closure drifted")
                self.assertAlmostEqual(o["exp_R"], s["exp_R"], places=6)
                checked += 1
        self.assertGreaterEqual(checked, 20,
                                "reproduction check went vacuous")


class TestCorrectedFunnelBaseline(unittest.TestCase):
    """The honest funnel, and the agreement with b105's own measurement."""

    def test_b108_rederives_the_merit_bar_under_the_corrected_engine(self):
        # b102's pin: b105's commit message parked this item ("CONSEQUENCE
        # (filed as b108)"), so the boundary — the OLD 0.854R bar is not the
        # bar — must live in a test name, not only in git prose.
        self.assertEqual(LED["_merit_bar"]["_historical_cached_bar_b61"], 0.854)
        self.assertLess(LED["_merit_bar"]["cached"], 0.35)
        self.assertEqual(LED["_merit_bar"]["cached"],
                         LED["cached"]["funnel_graded"]["exp_R"])

    def test_cached_funnel_matches_b105_independently(self):
        # b105 measured the same funnel through the same live-parity signal
        # path in its own script and printed exp_R 0.285 / trades 110. Two
        # independent scripts, one number — if they diverge, one of them is
        # no longer running the live funnel.
        cell = LED["cached"]["funnel_graded"]
        self.assertEqual(cell["exp_R"], 0.285)
        self.assertEqual(cell["trades"], 110)

    def test_merit_bar_cells_match_the_legs(self):
        bar = LED["_merit_bar"]
        self.assertEqual(bar["cached"],
                         LED["cached"]["funnel_graded"]["exp_R"])
        for w in WINDOWS:
            self.assertEqual(bar[w], LED[w]["funnel_graded"]["exp_R"])

    def test_the_corrected_bar_is_an_order_of_magnitude_below_the_old_one(self):
        # The pre-b105 bar was 0.854 (b61, cached). The corrected one is
        # 0.285. Pin the SIZE of the correction so a future run cannot quietly
        # re-quote 0.85 as if it were current.
        self.assertEqual(LED["_merit_bar"]["_historical_cached_bar_b61"], 0.854)
        self.assertLess(LED["_merit_bar"]["cached"], 0.35,
                        "the cached bar moved back above 0.35R — either the "
                        "engine regressed or the funnel genuinely improved; "
                        "re-read b105 before quoting any merit bar")
        for w in WINDOWS:
            self.assertLess(LED["_merit_bar"][w], 0.30,
                            f"{w} bar {LED['_merit_bar'][w]} — same warning")

    def test_correction_direction_is_negative_on_every_leg(self):
        # The double-count could only inflate. A POSITIVE d_exp_R on the
        # funnel means the engine started booking MORE than it should.
        for leg in LEGS:
            d = LED[leg]["_compare"]["funnel_graded"]["d_exp_R"]
            self.assertLess(d, 0, f"{leg}: funnel exp_R moved UP by {d}R")
            self.assertGreater(LED[leg]["_compare"]["funnel_graded"]["d_trades"],
                               0, f"{leg}: the freed slot admitted no extra "
                                  "entries — b105's phantom-blockage half is "
                                  "not being exercised here")

    def test_net_r_collapses_and_dd_worsens(self):
        for leg in LEGS:
            c = LED[leg]["_compare"]["funnel_graded"]
            self.assertLess(c["new"]["net_R"], c["old"]["net_R"])
            self.assertLessEqual(c["new"]["maxDD_R"], c["old"]["maxDD_R"],
                                 f"{leg}: DD improved after removing phantom "
                                 "profit — check the accounting")


class TestCorrectionIsNotNeutral(unittest.TestCase):
    """b105's prediction, measured: the inflation tracked TP1-hit-rate, so
    arm-vs-arm comparisons under the old engine were biased."""

    def test_nr7htf_margin_shifts_the_same_direction_on_all_four_windows(self):
        rows = LED["_b70_redecision"]["lane_nr7htf"]["inflation_neutrality"]
        self.assertEqual(len(rows), 4)
        shifts = [r["lane_relative_shift"] for r in rows]
        self.assertTrue(all(s > 0 for s in shifts),
                        f"nr7htf relative shift lost its one-sidedness: {shifts}")
        self.assertGreaterEqual(min(shifts), 0.04,
                                "the systematic shift shrank below 0.04R — "
                                "re-measure neutrality before trusting it")

    def test_pdh_family_shifts_are_smaller_than_nr7htfs(self):
        # The pdh lanes ride the funnel's own TP1 profile closely (their arm
        # is a small share of the book), so their relative shift must stay
        # inside nr7htf's. If a pdh lane ever shifts MORE, the neutrality
        # story is about something other than arm mix.
        nr7 = max(abs(r["lane_relative_shift"])
                  for r in LED["_b70_redecision"]["lane_nr7htf"]
                  ["inflation_neutrality"])
        for lane in ("lane_gated_pdh_dayext", "lane_h4pdh", "lane_runway"):
            got = max(abs(r["lane_relative_shift"])
                      for r in LED["_b70_redecision"][lane]
                      ["inflation_neutrality"])
            self.assertLess(got, nr7,
                            f"{lane}: |shift| {got} >= nr7htf {nr7}")

    def test_neutrality_rows_cover_every_window_for_every_lane(self):
        for lane in LANES:
            rows = LED["_b70_redecision"][lane]["inflation_neutrality"]
            self.assertEqual({r["window"] for r in rows}, set(WINDOWS),
                             f"{lane}: neutrality probe is incomplete")


class TestB70ReDecision(unittest.TestCase):
    """The capacity question, re-answered on honest numbers."""

    def test_no_lane_replicates_on_all_four_windows(self):
        for lane, v in LED["_b70_redecision"].items():
            self.assertFalse(v["replicated_all_windows"],
                             f"{lane} claims 4-of-4 on the corrected engine — "
                             "b70 flips and must be re-read, not deleted")

    def test_windows_beaten_counts_corrected_vs_inflated(self):
        want = {"lane_gated_pdh_dayext": (1, 2), "lane_h4pdh": (2, 3),
                "lane_runway": (1, 2), "lane_nr7htf": (0, 0)}
        for lane, (new, old) in want.items():
            v = LED["_b70_redecision"][lane]
            self.assertEqual(v["windows_beaten"], new,
                             f"{lane}: corrected windows_beaten changed")
            self.assertEqual(v["windows_beaten_under_inflated_engine"], old,
                             f"{lane}: the inflated-engine count it is "
                             "compared against must stay recorded")
            self.assertEqual(v["verdict_changed"], new != old)

    def test_h4pdh_w4_is_a_decision_relevant_flip(self):
        # The one cell where the correction changed a per-window verdict:
        # +0.019R win under the inflated engine, -0.002R loss under the
        # corrected one. Pinned so nobody re-derives the old win.
        cell = LED["W4"]["lane_h4pdh"]["graded_vs_graded_funnel"]
        self.assertLess(cell["d_exp_R"], 0)
        old_cell = OLD["W4"]["lane_h4pdh"]["graded_vs_graded_funnel"]
        self.assertGreater(old_cell["d_exp_R"], 0)

    def test_every_lane_margin_now_sits_inside_the_noise_band(self):
        # b81's ceiling was 0.07R. On the corrected engine the largest lane
        # margin over the funnel is 0.050R (cached) / 0.029R (W1) — every
        # remaining "win" is smaller than the pre-correction ceiling, i.e.
        # the honest numbers are LESS favourable to the lanes, not more.
        best = 0.0
        for lane in LANES:
            for w in WINDOWS:
                x = LED[w][lane]["graded_vs_graded_funnel"]
                best = max(best, x["d_exp_R"])
        self.assertLessEqual(best, 0.05,
                             f"a lane now wins by {best}R on the corrected "
                             "engine — b70's marginal answer needs re-arguing")

    def test_nr7htf_loses_net_r_too_on_the_corrected_engine(self):
        # b81's net_R trap (adds R everywhere, wins nowhere) got worse: the
        # lane now SUBTRACTS net_R on W1 and W2. Pin the sign of the change,
        # not just the story.
        neg = [w for w in WINDOWS
               if LED[w]["lane_nr7htf"]["graded_vs_graded_funnel"]["d_net_R"]
               < 0]
        self.assertIn("W1", neg)
        self.assertIn("W2", neg)


class TestScriptContract(unittest.TestCase):
    def test_script_imports_b81_rather_than_restating_the_funnel(self):
        # Hard rule: backtests must use the live-parity funnel, not a
        # hand-written copy. b108 gets its funnel from b81.funnel_fn, which is
        # engines.backtest_real.strategy_signal — so the import must be there
        # and no local strategy_signal call may appear.
        with open(SCRIPT) as f:
            src = f.read()
        self.assertIn("from scripts import b81_lane_rescore", src)
        self.assertIn("b81.measure_leg", src)
        self.assertNotIn("strategy_signal", src,
                         "b108 must not re-derive the funnel itself")

    def test_defines_the_comparison_and_redecision_functions(self):
        with open(SCRIPT) as f:
            tree = ast.parse(f.read())
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)}
        for fn in ("compare", "merit_bar", "redecide_b70", "main"):
            self.assertIn(fn, names, f"b108 lost {fn}()")

    def test_no_live_path_module_imports_this_script(self):
        for d in ("engines", "hermes_master.py", "hermes_runtime.py"):
            p = os.path.join(ROOT, d)
            files = ([p] if os.path.isfile(p) else
                     [os.path.join(p, f) for f in os.listdir(p)
                      if f.endswith(".py")]) if os.path.exists(p) else []
            for fp in files:
                with open(fp) as f:
                    body = f.read()
                self.assertNotIn("b108_rescore_corrected", body,
                                 f"{fp} imports the b108 lab script")


if __name__ == "__main__":
    unittest.main()
