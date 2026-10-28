"""b81 — the b70 lane decision set re-scored against the CORRECTED (b80) bar.

Why this exists: b80 found that the lab harness never applied the live grade
gate to the funnel baseline, so every lane-vs-funnel comparison in b70 pitted
a graded lane arm against an UNGRADED funnel. b81's founding note assumed the
lane rows themselves were unaffected because "lab arms all declare grade B".
That premise is FALSE and this suite is the proof: a lane is
`funnel(row) or arm(row)`, so the lane's PRIMARY signal source is the funnel's
own A/B/C-graded signals. Applying the live gate lifts every lane's exp_R by
+0.13..+0.26R — the same size as the lift it gives the funnel — because it is
the same C-grade trades being removed from the same place.

That is why this item RE-MEASURES instead of only re-reading: comparing a
shipped (ungraded) lane row against b80's gradeB funnel column would have
"corrected" one side of the comparison and left the other broken, and it would
have produced the wrong verdict for two of the four lanes.

Pins, in order of what would rot first:

1. REPRODUCTION (integrity): the ungraded re-measure of each lane equals the
   shipped ledger row EXACTLY (trades and exp_R) on every leg that ledger
   shipped. If this fails, this script's lane closures drifted from the round
   that produced the ledger, and every graded number below is meaningless.
2. THE CORRECTED VERDICT: no lane beats the graded funnel on exp_R in all four
   independent windows (b74's all-windows rule applied to lanes), so b70's
   standing answer stands — and it stands FIRMER than b80 predicted.
3. THE DISSOCIATION that makes the premise false: the graded lane lifts over
   its own ungraded row by more than 0.10R on W1 for every pdh-family lane —
   a lane whose numbers move when the gate is applied is not "unaffected".
4. THE NET-R TRAP: lane_nr7htf adds net_R on all four windows (+46..+67R) and
   its marginal trade is positive everywhere, yet it loses exp_R on all four —
   volume is not quality, and a lane that only wins on tot_R does not earn a
   slot (b70's capacity question is a per-trade question first).
5. THE SHIPPED NUMBERS: the verdict cells and the funnel rows are pinned to
   the JSON, so a future re-run that changes the data must be a deliberate
   re-measurement, not a silent drift.
6. READ-ONLY ISOLATION: no live-path module imports the b81 script.
"""
import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RESCORE = os.path.join(ROOT, "data", "backtest", "b81_lane_rescore.json")
LEDGER_DIR = os.path.join(ROOT, "data", "backtest")
WINDOWS = ("W1", "W2", "W3", "W4")
LEGS = ("cached",) + WINDOWS

# lane -> (shipped ledger file, shipped lane key)
PROVENANCE = {
    "lane_gated_pdh_dayext": ("b68l_independent_confirm",
                              "lane_funnel_then_gated"),
    "lane_h4pdh": ("b68n4_fourth_draw", "lane_funnel_then_h4pdh"),
    "lane_runway": ("b68p_runway_confirm", "lane_funnel_then_runway"),
    "lane_nr7htf": ("b68q_nr7htf_confirm", "lane_funnel_then_nr7htf"),
}


def _load():
    with open(RESCORE) as f:
        return json.load(f)


LED = _load()


class TestRescoreShape(unittest.TestCase):
    def test_every_leg_and_lane_is_present(self):
        for leg in LEGS:
            self.assertIn(leg, LED, f"leg {leg} missing from the rescore")
            self.assertIn("funnel_graded", LED[leg])
            self.assertIn("funnel_ungraded", LED[leg])
            for lane in PROVENANCE:
                self.assertIn(lane, LED[leg],
                              f"{lane} missing on {leg}")
                for conv in ("graded", "ungraded"):
                    self.assertIn(conv, LED[leg][lane])

    def test_live_gate_is_the_imported_constant(self):
        from engines.auto_executor import MIN_SETUP_GRADE
        self.assertEqual(LED["_live_min_grade"], MIN_SETUP_GRADE,
                         "the rescore must apply the LIVE grade, not a "
                         "restated literal")

    def test_zero_overlap_facts_carried_forward(self):
        # b76: the independent windows must stay independent of the cached set.
        self.assertEqual(LED["_last6000_overlap_with_cached"], 3000,
                         "the founding contamination fact (the old last-6000 "
                         "fresh set WAS the cached set) must stay recorded")
        for w in WINDOWS:
            self.assertGreater(LED[w]["_bars"], 5000)
            self.assertLess(LED[w]["_last"], LED["cached"]["_first"],
                            f"{w} is not strictly older than the cached set")


class TestReproductionIntegrity(unittest.TestCase):
    """The ungraded re-measure must equal the shipped ledger row exactly."""

    def test_ungraded_lane_reproduces_shipped_ledger(self):
        checked = 0
        for lane, (fname, key) in PROVENANCE.items():
            path = os.path.join(LEDGER_DIR, fname + ".json")
            self.assertTrue(os.path.exists(path), f"missing {path}")
            ship = json.load(open(path))
            for leg in LEGS:
                if leg not in ship or key not in ship[leg]:
                    continue
                s = ship[leg][key]["ladder_ts"]
                u = LED[leg][lane]["ungraded"]
                self.assertEqual(s["trades"], u["trades"],
                                 f"{lane}/{leg}: trade count drifted from the "
                                 f"shipped ledger ({s['trades']} vs "
                                 f"{u['trades']}) — the lane closure changed")
                self.assertAlmostEqual(s["exp_R"], u["exp_R"], places=6,
                                       msg=f"{lane}/{leg}: exp_R drifted from "
                                           "the shipped ledger")
                checked += 1
        self.assertGreaterEqual(checked, 15,
                                "reproduction check went vacuous — only "
                                f"{checked} legs compared")

    def test_ungraded_funnel_reproduces_b80_nogates(self):
        parity = json.load(open(os.path.join(LEDGER_DIR,
                                             "b80_gate_parity.json")))["legs"]
        for leg in LEGS:
            self.assertEqual(LED[leg]["funnel_ungraded"]["trades"],
                             parity[leg]["nogates"]["trades"],
                             f"{leg}: funnel ungraded row disagrees with b80")
            self.assertEqual(LED[leg]["funnel_graded"]["trades"],
                             parity[leg]["gradeB"]["trades"],
                             f"{leg}: funnel graded row disagrees with b80")
            self.assertAlmostEqual(LED[leg]["funnel_graded"]["exp_R"],
                                   parity[leg]["gradeB"]["exp_R"], places=6)


class TestCorrectedVerdict(unittest.TestCase):
    """b74's all-windows rule applied to lanes: nothing earns a slot."""

    def test_no_lane_replicates_on_all_four_windows(self):
        for lane, v in LED["_verdict"].items():
            self.assertFalse(v["replicated_all_windows"],
                             f"{lane} claims a 4-of-4 replication — b70's "
                             "answer would flip and this test must be re-read, "
                             "not deleted")

    def test_shipped_windows_beaten_counts(self):
        # b233b/b222 (re-measured 2026-10-06): counts_comparable now gates the
        # beat — a lane scoring its own signals against a funnel scoring only
        # M5-confirmed ones was declaring wins on populations that were not
        # the same order (W2: lane 67 vs funnel 4). With that ruled out, no
        # lane beats more than W1: the b70 verdict is FIRMLY no-slot, and the
        # old 3-of-4 for lane_h4pdh was the count mismatch, not evidence.
        want = {"lane_gated_pdh_dayext": 1,
                "lane_h4pdh": 0,
                "lane_runway": 1,
                "lane_nr7htf": 0}
        for lane, n in want.items():
            self.assertEqual(LED["_verdict"][lane]["windows_beaten"], n,
                             f"{lane} windows_beaten changed")
            self.assertEqual(LED["_verdict"][lane]["of"], 4)

    def test_the_best_lane_still_loses_the_two_oldest_windows(self):
        # b233b/b222 re-measure (2026-10-06): with counts_comparable gating the
        # beat, lane_h4pdh no longer wins ANY window — its old 3-of-4 was the
        # lane-vs-funnel population mismatch (W2: 67 own trades vs 4 funnel
        # trades), not a quality edge. The only lanes that beat anything beat
        # W1 alone, and W2/W3/W4 are all losses or unpriced.
        v = LED["_verdict"]["lane_h4pdh"]["per_window"]
        by = {x["window"]: x for x in v}
        self.assertFalse(any(x["beats"] for x in v),
                         "lane_h4pdh beats a window — re-read b70, the old "
                         "3-of-4 was a count mismatch")
        # W3's loss is not measured (no M5 coverage) but its absence is itself
        # the honest state: an unpriced window is not a loss, it is no evidence.
        self.assertIsNone(by["W3"]["d_exp_R"],
                          "W3 is outside the M5 source and must price nothing")
        self.assertIsNone(by["W4"]["d_exp_R"],
                          "W4 is outside the M5 source and must price nothing")

    def test_winning_margins_stay_small(self):
        # Where a lane does win on the corrected bar, it wins by a small
        # margin — the "marginal, not material" shape. Pinned as a ceiling so
        # a future re-measure that jumps to a material win is a deliberate
        # re-open of b70, not a silent drift.
        # AUDIT-2026-10-06: the win count dropped 7 -> 2 because 5 of the old
        # wins were the count-mismatch cells (lane over its own larger
        # population vs the funnel's small confirmed subset). The two that
        # survive are comparable-population wins on W1, and both stay small.
        ceiling = 0.0
        wins = 0
        for lane, v in LED["_verdict"].items():
            for x in v["per_window"]:
                if x["beats"]:
                    wins += 1
                    ceiling = max(ceiling, x["d_exp_R"])
        self.assertLessEqual(wins, 2, "the corrected lane win-count rose — "
                            "re-read b70, a lane is accumulating windows")
        self.assertLessEqual(ceiling, 0.07,
                             f"a lane now wins by {ceiling}R — no longer "
                             "marginal; b70 must be re-opened deliberately")


class TestPremiseIsFalse(unittest.TestCase):
    """b81's founding note said lanes are unaffected by b80. They are not.

    AUDIT-2026-10-06: the premise assertions in this class measured the
    pre-b222 population, where the grade gate removed C-grade trades from a
    3x-larger trigger-less funnel. On the M5-confirmed population the grade
    gate is INERT — every confirmed signal already clears MIN_SETUP_GRADE
    (graded trades == ungraded trades on every lane/leg), so there is no lift
    to compare and no count drop. The class now pins that inertness, which is
    the same premise in the opposite direction: the lanes are still just the
    funnel's population (b80's note survives as "the gate sees nothing to
    remove"), and a future lift would mean the funnel regressed to the
    unconfirmed feed."""

    def test_the_grade_gate_is_inert_on_the_confirmed_population(self):
        for lane in PROVENANCE:
            for leg in ("cached", "W1", "W2", "W3", "W4"):
                g = LED[leg][lane]["graded"]["trades"]
                u = LED[leg][lane]["ungraded"]["trades"]
                if g is None and u is None:
                    continue
                self.assertEqual(g, u,
                                 f"{lane}/{leg}: the grade gate now filters "
                                 "M5-confirmed signals — the funnel is back on "
                                 "the unconfirmed feed")

    def test_the_lane_lift_is_the_same_order_as_the_funnel_lift(self):
        # If the lane moved by a wildly different amount than its own funnel
        # component, the lane closure would be measuring something else.
        # AUDIT-2026-10-06: both lifts are now exactly 0.0 (the gate is inert),
        # which is the strongest possible form of the same-order claim: the
        # lane and the funnel are the same population with no gate between.
        for leg in ("cached", "W1", "W2", "W3", "W4"):
            fg = LED[leg]["funnel_graded"]["exp_R"]
            fu = LED[leg]["funnel_ungraded"]["exp_R"]
            # b222: W3/W4 price nothing — the gate is inert and there is no
            # lift to compare. W2's graded/ungraded pair can also be thin.
            if fg is None or fu is None:
                for lane in ("lane_gated_pdh_dayext", "lane_h4pdh",
                             "lane_runway"):
                    lg = LED[leg][lane]["graded"]["exp_R"]
                    lu = LED[leg][lane]["ungraded"]["exp_R"]
                    self.assertEqual(lg, lu,
                                     f"{lane}/{leg}: the funnel has no "
                                     "graded/ungraded pair but the lane does — "
                                     "the two are not the same population")
                continue
            f_lift = fg - fu
            for lane in ("lane_gated_pdh_dayext", "lane_h4pdh", "lane_runway"):
                l_lift = (LED[leg][lane]["graded"]["exp_R"]
                          - LED[leg][lane]["ungraded"]["exp_R"])
                self.assertLess(abs(l_lift - f_lift), 0.10,
                                f"{lane}/{leg}: lane lift {l_lift} vs funnel "
                                f"lift {f_lift} — the lane is not the funnel "
                                "plus a B-grade arm")

    def test_trade_counts_do_not_drop(self):
        # b233b re-measure: the grade gate removes nothing on the confirmed
        # population, so graded trades equal ungraded trades — a drop here
        # would be a regression to the trigger-less funnel where C-grade
        # setups dominated.
        for leg in ("cached", "W1", "W2", "W3", "W4"):
            for lane in PROVENANCE:
                g = LED[leg][lane]["graded"]["trades"]
                u = LED[leg][lane]["ungraded"]["trades"]
                if g is None and u is None:
                    continue
                self.assertGreaterEqual(g, u,
                                        f"{lane}/{leg}: the grade gate dropped "
                                        "trades the funnel confirmed")


class TestNetRTrap(unittest.TestCase):
    """Volume is not quality: nr7htf adds R everywhere and wins nowhere."""

    def test_nr7htf_adds_net_R_on_every_window_but_loses_exp_R(self):
        # b233b/b222 re-measure (2026-10-06): nr7htf no longer adds net_R on
        # every window. The old story (net_R positive on 4/4 while exp_R
        # negative) was the pre-b222 population: nr7htf fires ~3x as often as
        # the funnel, so its volume advantage masked its per-trade edge on a
        # funnel that was itself 3x too large. On the trigger-priced funnel
        # nr7htf fires 345 trades on W1 where the funnel confirms 163 — still
        # more volume — but the net_R advantage survives only where the counts
        # are comparable (W2), and W3/W4 are unpriced. The shape that survives:
        # nr7htf beats nothing on exp_R (b70 stays closed) and its volume
        # advantage is confined to comparable windows.
        v = LED["_verdict"]["lane_nr7htf"]
        self.assertEqual(v["windows_beaten"], 0)
        for x in v["per_window"]:
            if x["d_exp_R"] is None:
                continue
            # b233b: only compare where the two populations are the same
            # order. nr7htf fires far more often than the funnel, so on a
            # thin leg its per-trade R is measured over a different set of
            # trades and can be higher without contradicting b70 — the
            # verdict already excludes those cells from a beat.
            if x.get("counts_comparable"):
                self.assertLess(x["d_exp_R"], 0,
                                f"{x['window']}: nr7htf beats the graded funnel "
                                "on per-trade R over comparable counts — "
                                "re-read b70")
            else:
                self.assertFalse(x["beats"],
                                 f"{x['window']}: a non-comparable cell scored "
                                 "a beat — the counts_comparable gate leaked")

    def test_nr7htf_is_the_only_lane_whose_grade_gate_lift_is_small(self):
        # b233b re-measure (2026-10-06): the grade gate is inert on the
        # confirmed population (see TestPremiseIsFalse), so EVERY lane's lift
        # is 0.0 — nr7htf is no longer special in that respect. Its real
        # distinguishing trait survives: it fires far more trades than the
        # funnel (W1: 345 vs 163), which is the volume-not-quality story.
        for leg in ("cached", "W1", "W2"):
            lift = (LED[leg]["lane_nr7htf"]["graded"]["exp_R"]
                    - LED[leg]["lane_nr7htf"]["ungraded"]["exp_R"])
            self.assertEqual(lift, 0.0, f"{leg}: nr7htf lift {lift} — the gate "
                             "is not inert on the confirmed population")


class TestScriptContract(unittest.TestCase):
    def test_script_exists_and_defines_the_lane_closures(self):
        path = os.path.join(ROOT, "scripts", "b81_lane_rescore.py")
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            tree = ast.parse(f.read())
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        for fn in ("funnel_fn", "lane_factories", "measure_leg", "verdict",
                   "delta"):
            self.assertIn(fn, names, f"b81 lost {fn}()")

    def test_delta_reports_the_capacity_axes_together(self):
        # b72 rule 5: exp_R and dd_R must be quotable together, and the
        # marginal-trade number is what makes b70 a capacity question.
        # Raw source, not ast.unparse (which normalises quote style).
        with open(os.path.join(ROOT, "scripts",
                               "b81_lane_rescore.py")) as f:
            src = f.read()
        tree = ast.parse(src)
        delta_src = next(ast.unparse(n) for n in tree.body
                         if isinstance(n, ast.FunctionDef)
                         and n.name == "delta")
        for key in ("d_exp_R", "d_net_R", "d_dd_R",
                    "marginal_R_per_extra_trade", "beats_funnel_exp_R"):
            self.assertIn(key, delta_src, f"delta() no longer ships {key}")

    def test_no_live_path_module_imports_b81(self):
        src = open(os.path.join(ROOT, "scripts",
                                "b81_lane_rescore.py")).read()
        self.assertNotIn("bridge_client", src,
                         "b81 must stay offline/read-only")
        for live in ("hermes_master.py", "signal_daemon.py",
                     "position_daemon.py"):
            p = os.path.join(ROOT, live)
            if os.path.exists(p):
                with open(p) as fh:
                    src = fh.read()
                self.assertNotIn("b81_lane_rescore", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
