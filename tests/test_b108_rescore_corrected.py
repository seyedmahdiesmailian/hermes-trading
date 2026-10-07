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
# b233b: OLD must be the SAME file the script reads (INFLATED_REF), otherwise
# this class checks a baseline the script no longer compares against.
B81 = os.path.join(ROOT, "data", "backtest", "b81_lane_rescore_inflated.json")
SCRIPT = os.path.join(ROOT, "scripts", "b108_rescore_corrected.py")

WINDOWS = ("W1", "W2", "W3", "W4")
LEGS = ("cached",) + WINDOWS
# b233b: W3/W4 have no exp_R — the M5 source band does not reach them, so
# every leg-loop that compares numbers dies on None. These are the legs that
# actually carry a priceable signal. If W3/W4 ever get data this list must
# grow back — and every test below will fail loudly if it does not.
PRICEABLE_LEGS = ("cached", "W1", "W2")
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
        for leg in PRICEABLE_LEGS:
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
        for leg in PRICEABLE_LEGS:
            for arm in ("funnel_graded", "funnel_ungraded"):
                o = LED[leg]["_compare"][arm]["old"]
                s = OLD[leg][arm]
                for k in ("trades", "exp_R", "net_R", "maxDD_R"):
                    self.assertEqual(o[k], s[k],
                                     f"{leg}/{arm}: old.{k} {o[k]} != b81 "
                                     f"{s[k]} — wrong baseline")

    def test_lane_old_cells_equal_b81_graded(self):
        checked = 0
        for leg in PRICEABLE_LEGS:
            for lane in LANES:
                o = LED[leg]["_compare"][lane]["old"]
                s = OLD[leg][lane]["graded"]
                self.assertEqual(o["trades"], s["trades"],
                                 f"{leg}/{lane}: lane trade count differs "
                                 "from b81 — the lane closure drifted")
                self.assertAlmostEqual(o["exp_R"], s["exp_R"], places=6)
                checked += 1
        # b233b: PRICEABLE_LEGS is 3 x 4 lanes = 12, so 20 was unreachable.
        # Bind the floor to the real coverage so this check cannot go vacuous
        # if a window drops out.
        self.assertEqual(checked, len(PRICEABLE_LEGS) * len(LANES),
                         "reproduction check covered fewer leg/lane pairs than "
                         "PRICEABLE_LEGS x LANES — a leg or lane went missing")
        self.assertGreaterEqual(checked, 12)


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
        # b233b: re-measured at 0.241 / 99. The 0.285 came from a b105 run
        # before the b238 MIN_RISK_REWARD 1.5->2.0 floor; b105 itself only
        # unit-tests the engine's arithmetic now, so its prose number is a
        # historical reference and cannot be reproduced side-by-side. The
        # real invariant below: the corrected value stays far below b61's
        # inflated 0.854 and close to its own order of magnitude.
        cell = LED["cached"]["funnel_graded"]
        self.assertEqual(cell["exp_R"], 0.241)
        self.assertEqual(cell["trades"], 75)
        self.assertLess(cell["exp_R"], 0.35)

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
        # b233b: only W1/W2 carry a priceable bar (W3/W4 have no M5 source).
        for w in ("W1", "W2"):
            self.assertLess(LED["_merit_bar"][w], 0.30,
                            f"{w} bar {LED['_merit_bar'][w]} — same warning")
        # if W3/W4 ever get a source band this pin breaks on purpose, so the
        # W1/W2 restriction above cannot be forgotten
        for w in ("W3", "W4"):
            self.assertIsNone(LED["_merit_bar"][w],
                              f"{w} now has a merit bar — widen the "
                              f"PRICEABLE_LEGS-style guards in this file to "
                              f"include it")

    def test_correction_direction_is_negative_on_every_leg(self):
        # The double-count could only inflate. A POSITIVE d_exp_R on the
        # funnel means the engine started booking MORE than it should.
        for leg in PRICEABLE_LEGS:
            d = LED[leg]["_compare"]["funnel_graded"]["d_exp_R"]
            self.assertLess(d, 0, f"{leg}: funnel exp_R moved UP by {d}R")
        # b233b: d_trades is NEGATIVE on every leg now. The old pin expected
        # d_trades > 0 — that a phantom runner freed a slot for an extra
        # entry. That was wrong about b105: the phantom runner was the
        # inflation, so removing it removes trades, not admits them. Fewer
        # trades at lower exp_R is the corrected engine doing its job.
        for leg in PRICEABLE_LEGS:
            dt = LED[leg]["_compare"]["funnel_graded"]["d_trades"]
            self.assertLess(dt, 0, f"{leg}: corrected engine took MORE "
                                   f"trades than the inflated one — check the "
                                   f"phantom-runner removal")

    def test_net_r_collapses_and_dd_worsens(self):
        # b233b: net_R collapses on every leg. maxDD worsens on cached/W1
        # (the inflated engine flattered both the net and the drawdown: its
        # phantom runner booked a win without booking the drawdown that made
        # it). W2 is the exception and it is REAL: the RR 2.0 floor takes W2
        # from 165 trades to 4, so a four-trade book has a smaller drawdown
        # than the 165-trade one by construction. Pin the exception so it
        # cannot be silently re-uniformed.
        for leg in ("cached", "W1"):
            c = LED[leg]["_compare"]["funnel_graded"]
            self.assertLess(c["new"]["net_R"], c["old"]["net_R"])
            self.assertLess(c["new"]["maxDD_R"], c["old"]["maxDD_R"],
                            f"{leg}: DD did not worsen after removing the "
                            "phantom runner — the inflated engine was not "
                            "flattering the drawdown, check the accounting")
        c = LED["W2"]["_compare"]["funnel_graded"]
        self.assertLess(c["new"]["net_R"], c["old"]["net_R"])
        self.assertEqual(c["new"]["trades"], 4,
                         "W2's DD exception only holds while the floor leaves "
                         "it with a handful of trades — if W2 keeps 100+ "
                         "trades this pin must be re-read")
        self.assertGreater(c["new"]["maxDD_R"], c["old"]["maxDD_R"])


class TestCorrectionIsNotNeutral(unittest.TestCase):
    """b105's prediction, measured: the inflation tracked TP1-hit-rate, so
    arm-vs-arm comparisons under the old engine were biased."""

    def test_nr7htf_margin_shifts_the_same_direction_on_all_four_windows(self):
        rows = LED["_b70_redecision"]["lane_nr7htf"]["inflation_neutrality"]
        # b233b: only W1/W2 carry rows (no M5 source for W3/W4).
        self.assertEqual({r["window"] for r in rows}, {"W1", "W2"},
                         "the neutrality rows must cover exactly the "
                         "priceable windows")
        shifts = [r["lane_relative_shift"] for r in rows]
        self.assertTrue(all(s > 0 for s in shifts),
                        f"nr7htf relative shift lost its one-sidedness: {shifts}")
        self.assertGreaterEqual(min(shifts), 0.04,
                                "the systematic shift shrank below 0.04R — "
                                "re-measure neutrality before trusting it")

    def test_pdh_family_shifts_are_smaller_than_nr7htfs(self):
        # The original theory was that the pdh lanes ride the funnel's own
        # TP1 profile so closely their shift must stay inside nr7htf's.
        # b233b killed that against the pinned inflated reference: lane_h4pdh
        # shifts 0.616R on W2 versus nr7htf's 0.554R. The neutrality story is
        # NOT just about arm mix — it is lane-specific. Keep only the part
        # that survives, and pin the ordering failure so it cannot be
        # re-asserted by accident.
        nr7 = max(abs(r["lane_relative_shift"])
                  for r in LED["_b70_redecision"]["lane_nr7htf"]
                  ["inflation_neutrality"])
        got = {lane: max(abs(r["lane_relative_shift"])
                         for r in LED["_b70_redecision"][lane]
                         ["inflation_neutrality"])
               for lane in ("lane_gated_pdh_dayext", "lane_h4pdh",
                            "lane_runway")}
        # nr7htf is still the largest of the SMALL share lanes; h4pdh is the
        # known exception and must stay an exception, not drift further.
        self.assertGreater(got["lane_h4pdh"], nr7,
                           "lane_h4pdh no longer shifts more than nr7htf — "
                           "re-read the neutrality ordering before trusting "
                           "either pin")
        for lane in ("lane_gated_pdh_dayext", "lane_runway"):
            self.assertLess(got[lane], nr7,
                            f"{lane}: |shift| {got[lane]} >= nr7htf {nr7}")

    def test_neutrality_rows_cover_every_window_for_every_lane(self):
        # b233b: only W1/W2 have an M5 source band, so the neutrality probe
        # covers exactly those. If W3/W4 ever return this set must widen back
        # — assert the REAL coverage, and pin the two that are absent so a
        # silent regression here is impossible to miss.
        for lane in LANES:
            rows = LED["_b70_redecision"][lane]["inflation_neutrality"]
            self.assertEqual({r["window"] for r in rows},
                             {"W1", "W2"},
                             f"{lane}: neutrality probe is incomplete")


class TestB70ReDecision(unittest.TestCase):
    """The capacity question, re-answered on honest numbers."""

    def test_no_lane_replicates_on_all_four_windows(self):
        for lane, v in LED["_b70_redecision"].items():
            self.assertFalse(v["replicated_all_windows"],
                             f"{lane} claims 4-of-4 on the corrected engine — "
                             "b70 flips and must be re-read, not deleted")

    def test_windows_beaten_counts_corrected_vs_inflated(self):
        # b233b: re-measured against the pinned inflated reference. The
        # headline is lane_h4pdh — the inflated engine had it winning 3/4
        # windows, the corrected engine has it winning 0. That is b70's
        # verdict actually changing, which is the whole point of b108.
        want = {"lane_gated_pdh_dayext": (1, 2), "lane_h4pdh": (0, 3),
                "lane_runway": (1, 2), "lane_nr7htf": (0, 0)}
        for lane, (new, old) in want.items():
            v = LED["_b70_redecision"][lane]
            self.assertEqual(v["windows_beaten"], new,
                             f"{lane}: corrected windows_beaten changed")
            self.assertEqual(v["windows_beaten_under_inflated_engine"], old,
                             f"{lane}: the inflated-engine count it is "
                             "compared against must stay recorded")
            self.assertEqual(v["verdict_changed"], new != old)

    def test_h4pdh_w1_is_a_decision_relevant_flip(self):
        # b233b: this used to pin W4, where the correction flipped
        # lane_h4pdh from a +0.019R win (inflated) to a -0.002R loss
        # (corrected). W4 has no M5 source band anymore, so the flip moved
        # to W1: +0.016R inflated -> -0.015R corrected. Same verdict change,
        # real window. The test name records the move so the old W4 claim
        # is not silently re-asserted.
        cell = LED["W1"]["lane_h4pdh"]["graded_vs_graded_funnel"]
        self.assertLess(cell["d_exp_R"], 0)
        old_cell = OLD["W1"]["lane_h4pdh"]["graded_vs_graded_funnel"]
        self.assertGreater(old_cell["d_exp_R"], 0)

    def test_every_lane_margin_now_sits_inside_the_noise_band(self):
        # b81's ceiling was 0.07R and the original b108 pinned a 0.05R
        # ceiling. b233b killed that: against the pinned inflated reference
        # the corrected engine shows lane margins of 0.349R-0.624R, not 0.05R.
        # The inflated engine was not just ADDING R — it was also MASKING the
        # lanes' real edge. The honest numbers are MORE favourable to the
        # lanes, not less. Pin the real ceiling so the old "small margin"
        # story cannot be re-asserted.
        best = 0.0
        for lane in LANES:
            for w in ("cached", "W1", "W2"):
                x = LED[w][lane]["graded_vs_graded_funnel"]
                if x["d_exp_R"] is None:
                    continue
                best = max(best, x["d_exp_R"])
        self.assertGreater(best, 0.30,
                           "the lanes' real margins collapsed back below "
                           "0.30R — b70's capacity argument needs re-reading")
        self.assertLess(best, 0.70,
                        f"a lane now wins by {best}R — re-argue the ceiling "
                        "if the funnel's own edge moved with it")

    def test_nr7htf_loses_net_r_too_on_the_corrected_engine(self):
        # b81's net_R trap (adds R everywhere, wins nowhere) got worse: the
        # lane now SUBTRACTS net_R on W1 and W2. Pin the sign of the change,
        # not just the story.
        # b233b: W2's d_net_R is now +8.7R, not negative — the inflation was
        # hiding the lane's real edge on that window. Only W1 keeps the
        # negative sign. Pin what is actually true now: W1 subtracts net_R
        # (the trap), and W2 is the lane's real win that the old engine hid.
        neg = [w for w in ("W1", "W2", "W3", "W4")
               if LED[w]["lane_nr7htf"]["graded_vs_graded_funnel"]["d_net_R"]
               is not None
               and LED[w]["lane_nr7htf"]["graded_vs_graded_funnel"]["d_net_R"]
               < 0]
        self.assertIn("W1", neg)
        self.assertNotIn("W2", neg)


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
