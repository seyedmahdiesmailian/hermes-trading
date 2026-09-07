"""b119 — b66b's "GRADE-WEIGHTED PARTIAL SIZING IS REAL EDGE" WAS SCORED ON AN
ARM THAT WAS NOT GRADE-WEIGHTED, AND THE RANKING RUNS THE OTHER WAY NOW.

WHAT WAS STORED (data/backtest/b66b_share.json + this file's Findings section)
==============================================================================
  "live grade-based share 184.3R M5 / 211.5R M15 vs flat 30/50/70% all far
   worse (91-168R). Grade-weighted partial sizing CONFIRMED as real edge."
and b66: "TP1=.60 wins M5 (+2.1R) but .45 wins M15 (+7.0R) — contradictory,
incumbent .50 kept".

WHY THAT CANNOT HAVE BEEN MEASURED (arm-identity census, recomputed in
scripts/b119_exit_grid_reprice.py over the real funnel signals, not argued):
b66b passed `partial_share_fn=lambda t: _partial_close_fraction(t)` into an
engine whose trade dict carried NONE of the four ladder fields (b108's finding,
fixed by b109). `rr_remaining` therefore defaulted to 0.0, the
`rr_remaining <= 1.2` weak branch tripped on every call, and the function
returned the CONSTANT 1.0 — measured: 306/306 gate-passed cached signals,
536/536 W1, 523/523 W2, 737/737 W3, 578/578 W4. The incumbent arm was "close
the whole position at TP1, never keep a runner". Post-b109 the same function
returns 0.3 for the A-grade lane and 1.0 for the rest (84/306 cached), so the
arm live runs today is a THIRD thing that had never been measured.

And the flat arms were scored against a PHANTOM population: in the frozen b66b
ledger every arm has an IDENTICAL trade count and IDENTICAL win rate (303/62.7%
M5, 338/63.6% M15) while total_r swings 91.5R -> 184.3R. A share rule cannot
change how much a closed ticket is worth without changing which tickets get
taken — the spread is the b105 double-count (a full-size runner booked on top
of the realized partial), not a sizing edge.

MEASURED UNDER THE CORRECTED ENGINE (cached + W1..W4, one harness, live grade
gate + min_rr imported, runner trail and $ floor derived from live per b118;
ledger data/backtest/b119_exit_grid_reprice.json):

  * b66b's verdict REVERSES on its own metric. The constant-1.0 arm b66b
    actually scored now LOSES to the real grade fn on exp_R in 4/4 independent
    windows (-0.005..-0.024R) — so keeping a runner is worth something, but
    ~0.01R/trade, not the 2x total-R gap that was quoted. And `flat_0.30`
    (keep 70% riding on EVERY trade) BEATS the grade-weighted incumbent on
    exp_R in 4/4 windows (+0.002..+0.046R) and on net_R in 3/4, with maxDD
    better on 3/4. By b110's rule a one-sided shift across >=3 windows means
    the stored ranking was contaminated — here it means it was inverted.
  * b66's DECISION survives on its OWN metric; its stated evidence does not.
    b66 chose on TOTAL R ("must beat the incumbent on BOTH M5 and M15"), and on
    net_R no looser arm replicates (.60 wins 2/4 windows, .70 wins 3/4 with a
    -13.2R hole in W2), so .50 stands. But on per-trade expectancy tp1=0.60 is
    positive in 3/4 windows (+0.045/-0.024/+0.016/+0.113) — the OPPOSITE
    direction from b66's evidence, and it is bought with trade count (a higher
    TP1 step is harder to hit: 109 -> 95 trades cached). ".45 wins M15 (+7.0R)"
    is simply refuted: 0.45 loses exp_R in 3/4 windows and net_R in 3/4.
  * FRAME, not just engine: b66/b66b called backtest_ohlc with no min_grade, so
    they scored every C-grade setup the live executor rejects. Same engine,
    same bars: exp_R 0.081-0.161 ungraded vs 0.211-0.278 graded — the grade gate
    is worth +0.079..+0.152R on the LEVEL. The b71 time-exit defect cost
    exactly 0.000R on this family (max hold 112 bars < the 144-bar exit on every
    leg), so one of the two frame bugs was free and the other was not.

NO LIVE CHANGE SHIPPED. engines/trade_management.py is untouched; flat_0.30 is
a candidate for its own measured round + a human gate decision (b89 class), not
something a research probe wires into the exit path.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LEDGER = os.path.join(ROOT, "data", "backtest", "b119_exit_grid_reprice.json")
PROBE = os.path.join(ROOT, "scripts", "b119_exit_grid_reprice.py")
B66B = os.path.join(ROOT, "data", "backtest", "b66b_share.json")
B66 = os.path.join(ROOT, "data", "backtest", "b66_exit_grid.json")
B118 = os.path.join(ROOT, "data", "backtest", "b118_merit_bar_rebaseline.json")

LEGS = ("cached", "W1", "W2", "W3", "W4")
INDEPENDENT = ("W1", "W2", "W3", "W4")
TP1_ARMS = ("tp1_0.40", "tp1_0.45", "incumbent_tp1_0.50", "tp1_0.60", "tp1_0.70")
SHARE_ARMS = ("incumbent_live_grade_fn", "b66b_winner_as_measured_const_1.0",
              "flat_0.30", "flat_0.50", "flat_0.70")
INCUMBENT_TP1 = "incumbent_tp1_0.50"
INCUMBENT_SHARE = "incumbent_live_grade_fn"


def _load(path):
    with open(path) as fh:
        return json.load(fh)


def _load_probe():
    spec = importlib.util.spec_from_file_location("b119_probe", PROBE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LED = _load(LEDGER)


class TestB119LedgerShape(unittest.TestCase):
    """The ledger must be the real thing on the real window set, or every claim
    below passes on nothing."""

    def test_every_leg_carries_both_grids_with_every_arm(self):
        for leg in LEGS:
            row = LED[leg]
            for grid, arms in (("tp1_grid", TP1_ARMS), ("share_grid", SHARE_ARMS)):
                self.assertIn(grid, row, f"{leg} missing {grid}")
                self.assertEqual(sorted(row[grid]), sorted(arms),
                                 f"{leg}.{grid} arm set changed")
                for name, s in row[grid].items():
                    for key in ("trades", "exp_R", "net_R", "maxDD_R"):
                        self.assertIsNotNone(s.get(key),
                                             f"{leg}.{grid}.{name} missing {key}")

    def test_legs_are_the_b76_independent_window_set(self):
        # b110's neutrality test needs >=3 INDEPENDENT windows with enough
        # trades to price an exit arm.
        for leg in INDEPENDENT:
            self.assertGreaterEqual(LED[leg]["_bars"], 5000,
                                    f"{leg} is not a full 6000-bar window")
            self.assertGreater(LED[leg]["share_grid"][INCUMBENT_SHARE]["trades"],
                               100, f"{leg} has too few trades to price an arm")

    def test_incumbent_arms_reproduce_the_b118_merit_bar(self):
        # CROSS-LEDGER INTEGRITY: both grids' incumbent arm IS the harness
        # ladder, so it must print b118's live-parity bar exactly. If the
        # harness drifts (a new trail, a new floor, a new tp1) this fires and
        # the two ledgers cannot silently disagree about what "the bar" means.
        bar = _load(B118)
        for leg in LEGS:
            want = bar[leg]["live_parity"]["exp_R"]
            for grid, inc in (("tp1_grid", INCUMBENT_TP1),
                              ("share_grid", INCUMBENT_SHARE)):
                got = LED[leg][grid][inc]["exp_R"]
                self.assertEqual(got, want,
                                 f"{leg}.{grid} incumbent exp_R {got} != b118 "
                                 f"live-parity bar {want} — re-baseline or "
                                 f"explain, do not edit this pin blind")
            self.assertEqual(LED[leg]["funnel_baseline"]["exp_R"], want)

    def test_harness_ladder_is_the_incumbent_this_round_defends(self):
        # The round's whole point is that the INCUMBENT is live's own ladder.
        # Read it out of the harness rather than restating it (b109's rule).
        from engines import lab_harness as lh
        self.assertEqual(LED["_incumbent_ladder"]["tp1_position"],
                         lh.LADDER["tp1_position"])
        self.assertEqual(LED["_incumbent_ladder"]["trail_after_partial"],
                         lh.LADDER["trail_after_partial"])
        self.assertEqual(LED["_incumbent_ladder"]["trail_floor"],
                         lh.LADDER["trail_floor"])
        self.assertEqual(LED["_live_min_grade"], lh.LIVE_MIN_GRADE)


class TestB119ArmIdentity(unittest.TestCase):
    """b66b's winner was not the arm it was named for. Measured, not asserted."""

    def test_b122_pre_b109_trade_dict_makes_the_live_share_fn_constant(self):
        # NAME-CARRIER for b122 (b102's discipline: a filed item lives in a
        # test name, not only in a commit message). b122's rule — verify an arm
        # is the rule it is named for — IS this class: the census below replays
        # the live share function over the real signals under the OLD trade-dict
        # shape and shows the histogram collapses to one value.
        for leg in LEGS:
            ai = LED[leg]["arm_identity"]
            self.assertTrue(ai["pre_b109_is_constant_1.0"],
                            f"{leg}: the pre-b109 dict no longer forces share "
                            f"1.0 — b109's fix has been widened or the census "
                            f"frame changed; b66b's premise needs re-reading")
            self.assertEqual(list(ai["pre_b109_share_histogram"]), ["1.0"])

    def test_post_b109_dict_makes_the_same_function_discriminate(self):
        for leg in LEGS:
            ai = LED[leg]["arm_identity"]
            self.assertTrue(ai["post_b109_discriminates"],
                            f"{leg}: the live share fn is STILL a constant — "
                            f"then b66b's arm identity was fine and this "
                            f"item's premise is void")
            self.assertEqual(ai["signals_whose_share_changed"],
                             ai["a_grade_signals"],
                             f"{leg}: the share change is not the A-grade lane "
                             f"— b109's collapse-to-grade-A claim has moved")

    def test_the_runner_lane_is_a_minority_of_gate_passed_signals(self):
        # The population b66b's flat arms were supposed to beat: if it grew to
        # the whole book, "flat 30%" and "grade fn" would be the same rule and
        # the comparison below would be vacuous.
        for leg in LEGS:
            ai = LED[leg]["arm_identity"]
            share = ai["a_grade_signals"] / ai["gate_passed_signals"]
            self.assertGreater(share, 0.05, f"{leg}: runner lane {share}")
            self.assertLess(share, 0.60, f"{leg}: runner lane {share} — the "
                                         "grade fn is no longer a minority rule")

    def test_frozen_b66b_ledger_shows_the_phantom_population_signature(self):
        # THE SMOKING GUN, read from the immutable shipped ledger: four
        # different share rules produced the SAME trade count and the SAME win
        # rate while total_r swung 2x. A sizing rule that changes neither which
        # trades are taken nor their outcome cannot change their number of R —
        # the spread is the b105 double-count.
        old = _load(B66B)
        for tf in ("M5", "M15"):
            rows = {n: v["full"] for n, v in old[tf].items()}
            self.assertEqual(len({r["n"] for r in rows.values()}), 1,
                             f"{tf}: trade counts now differ across share arms")
            self.assertEqual(len({r["wr"] for r in rows.values()}), 1,
                             f"{tf}: win rates now differ across share arms")
            totals = [r["total_r"] for r in rows.values()]
            self.assertGreater(max(totals) - min(totals), 50.0,
                               f"{tf}: the stored spread is gone — this test "
                               f"is certifying a defect that no longer exists")


class TestB119ShareRankingInverted(unittest.TestCase):
    """The load-bearing finding: b66b's ranking does not survive the fix."""

    def test_constant_full_close_now_loses_to_the_real_grade_fn(self):
        # Direction of b66b's claim survives (a runner is worth keeping) but
        # its magnitude is ~0.01R/trade, not 2x total R.
        v = LED["_share_neutrality"]["arm_verdicts"][
            "b66b_winner_as_measured_const_1.0"]
        losses = sum(1 for w in INDEPENDENT if v["per_window"][w] < 0)
        self.assertGreaterEqual(losses, 3,
                                "the constant-1.0 arm no longer loses to the "
                                "grade fn — b119's re-decision has moved")
        self.assertEqual(v["net_wins"], 0)
        for w in INDEPENDENT:
            self.assertLess(abs(v["per_window"][w]), 0.05,
                            f"{w}: a 2x-scale gap reappeared — that is the "
                            "double-count signature, not an effect")

    def test_flat_30_percent_beats_the_grade_weighted_incumbent_one_sided(self):
        # b110's contamination test, pointed at b66b: one-sided across >=3
        # independent windows. The stored verdict said flat arms were "all far
        # worse"; under the corrected engine the best flat arm is better.
        v = LED["_share_neutrality"]["arm_verdicts"]["flat_0.30"]
        self.assertTrue(v["one_sided_ge_3"],
                        "flat_0.30 is no longer one-sided vs the incumbent — "
                        "the finding has moved, re-read the ledger")
        self.assertEqual(v["wins"], 4, f"per-window deltas {v['per_window']}")
        wins = [w for w in INDEPENDENT if v["per_window_net_R"][w] > 0]
        self.assertGreaterEqual(len(wins), 3,
                                f"net_R wins {wins} — the stored metric was "
                                "total R, so the reversal must hold on it too")
        # and it must stay SMALL: a big number here means a phantom population
        # is back, not that sizing got better.
        for w in INDEPENDENT:
            self.assertLess(v["per_window"][w], 0.10, f"{w}: {v['per_window'][w]}")

    def test_the_reversal_is_not_a_drawdown_tradeoff(self):
        # An arm that buys expectancy with risk is a different decision. Here
        # flat_0.30 improves DD on 3/5 legs and costs at most 0.2R on the one
        # it loses — which is why it is worth a real round, not a dismissal.
        better = 0
        for leg in LEGS:
            inc = LED[leg]["share_grid"][INCUMBENT_SHARE]["maxDD_R"]
            alt = LED[leg]["share_grid"]["flat_0.30"]["maxDD_R"]
            self.assertGreaterEqual(alt, inc - 0.5,
                                    f"{leg}: flat_0.30 DD {alt} vs incumbent "
                                    f"{inc} — the gain is bought with risk")
            if alt >= inc:
                better += 1
        self.assertGreaterEqual(better, 3,
                                "flat_0.30's DD advantage has disappeared — "
                                "re-read the ledger before quoting the finding")

    def test_the_gain_is_not_a_swing_hold_in_disguise(self):
        # b71's defect class: an arm that wins only because it holds like a
        # swing trade on an intraday board. flat_0.30 keeps a runner on every
        # trade, so its hold profile is the thing to check — it must stay
        # inside the live time exit and must not stretch the tail.
        for leg in LEGS:
            ts = LED[leg]["_time_stop_bars"]
            inc = LED[leg]["share_grid"][INCUMBENT_SHARE]
            alt = LED[leg]["share_grid"]["flat_0.30"]
            self.assertEqual(alt["holds_over_time_exit"], 0,
                             f"{leg}: flat_0.30 holds past the live time exit")
            self.assertLess(alt["p95_hold_bars"], ts,
                            f"{leg}: p95 hold {alt['p95_hold_bars']} >= ts {ts}")
            self.assertLess(alt["mean_hold_bars"] - inc["mean_hold_bars"], 2.0,
                            f"{leg}: mean hold {inc['mean_hold_bars']} -> "
                            f"{alt['mean_hold_bars']} — the gain is a longer "
                            "hold, not a better exit")

    def test_share_grid_trades_stay_in_a_narrow_band(self):
        # Anti-vacuity for the one-position gate: if the arms' trade counts
        # diverged wildly the comparison would be about slot occupancy, not
        # about exit sizing.
        for leg in LEGS:
            counts = [LED[leg]["share_grid"][n]["trades"] for n in SHARE_ARMS]
            self.assertLess(max(counts) - min(counts), 15,
                            f"{leg}: trade counts {counts} diverge — the arms "
                            "are no longer measuring the same thing")


class TestB119Tp1DecisionStands(unittest.TestCase):
    """b66's DECISION survives the re-price; its stated evidence does not."""

    def test_looser_tp1_is_one_sided_positive_on_exp_R_but_not_on_the_metric(self):
        # THE HONEST VERSION of "b66's decision stands". b66 chose TOTAL R
        # ("arms must beat the incumbent on BOTH M5 and M15"), and on that
        # metric neither .60 nor .70 replicates (.60 wins 2/4 windows, .70 3/4
        # with a -13.2R W2 hole). But on per-trade expectancy .60 is positive
        # in 3/4 windows — so the axis that moved is NOT the axis the decision
        # was made on, and the direction is the OPPOSITE of b66's evidence.
        # Pinned both ways: if .60 ever wins on net_R too, the incumbent choice
        # has to be re-opened in the open, not quietly.
        for name in ("tp1_0.60", "tp1_0.70"):
            v = LED["_tp1_neutrality"]["arm_verdicts"][name]
            wins = [w for w in INDEPENDENT if v["per_window"][w] > 0]
            self.assertGreaterEqual(len(wins), 3,
                                    f"{name} no longer favours a looser TP1 on "
                                    f"exp_R ({v['per_window']})")
            net_wins = [w for w in INDEPENDENT if v["per_window_net_R"][w] > 0]
            self.assertLess(len(net_wins), 4,
                            f"{name} now wins net_R on ALL FOUR windows — "
                            "b66's 'keep .50' must be re-decided, not re-quoted")

    def test_a_looser_tp1_buys_expectancy_with_trade_count(self):
        # Why the two metrics disagree: a higher TP1 step is harder to hit, so
        # fewer tickets complete their partial and the single slot stays
        # occupied longer. Trade count must fall monotonically with the step.
        for leg in LEGS:
            counts = [LED[leg]["tp1_grid"][n]["trades"] for n in TP1_ARMS]
            self.assertEqual(counts, sorted(counts, reverse=True),
                             f"{leg}: trade counts {counts} no longer fall with "
                             "the TP1 step — the count/cost story is wrong")

    def test_b66s_m15_claim_about_tp1_045_is_refuted(self):
        # "TP1=.45 wins M15 (+7.0R)" — under the corrected engine 0.45 is a
        # loser on both metrics on most windows. Pinned so the sentence cannot
        # be re-quoted as support for an earlier TP1.
        v = LED["_tp1_neutrality"]["arm_verdicts"]["tp1_0.45"]
        neg = sum(1 for w in INDEPENDENT if v["per_window"][w] < 0)
        self.assertGreaterEqual(neg, 3, f"per-window {v['per_window']}")
        neg_net = sum(1 for w in INDEPENDENT if v["per_window_net_R"][w] < 0)
        self.assertGreaterEqual(neg_net, 3, f"net_R {v['per_window_net_R']}")

    def test_tighter_tp1_is_one_sided_worse(self):
        v = LED["_tp1_neutrality"]["arm_verdicts"]["tp1_0.40"]
        self.assertTrue(v["one_sided_ge_3"])
        self.assertEqual(v["wins"], 0, f"per-window {v['per_window']}")


class TestB119FrameNotOnlyEngine(unittest.TestCase):
    """b66/b66b also measured in the WRONG FRAME — and the two frame defects
    are worth very different amounts."""

    def test_the_grade_gate_moves_the_level_on_every_leg(self):
        # b80's gate, absent from b66/b66b: ungraded exp_R must be lower on
        # every leg. This is why their absolute numbers cannot be compared to
        # anything measured after b80.
        for leg in LEGS:
            fp = LED[leg]["frame_probe"]
            self.assertGreater(fp["corrected_frame_graded_with_ts"]["exp_R"],
                               fp["b66_frame_ungraded_no_ts"]["exp_R"], leg)
            self.assertGreater(fp["grade_gate_cost_R"], 0.05, leg)
            self.assertGreater(
                fp["b66_frame_ungraded_no_ts"]["trades"],
                fp["corrected_frame_graded_with_ts"]["trades"],
                f"{leg}: the grade gate rejected nothing — it is dead code")

    def test_the_time_exit_genuinely_does_not_bind_on_this_family(self):
        # The honest half of the decomposition: b71's defect cost 0.000R here.
        # Pin WHY (no hold exceeds the exit), so a future dataset where it does
        # bind fires instead of leaving a stale "frame bugs were free" note.
        for leg in LEGS:
            fp = LED[leg]["frame_probe"]
            self.assertEqual(fp["time_exit_cost_R"], 0.0, leg)
            ts = LED[leg]["_time_stop_bars"]
            self.assertLess(fp["b66_frame_ungraded_no_ts"]["max_hold_bars"], ts,
                            f"{leg}: a hold exceeds the time exit but the cost "
                            "still printed 0 — the probe is broken")
            self.assertEqual(fp["b66_frame_ungraded_no_ts"]["holds_over_time_exit"], 0)

    def test_the_time_stop_knob_is_not_dead_code(self):
        # Anti-vacuity for the pin above: a SHORT time exit must move the
        # numbers. If it does not, ts_cost==0 proves nothing about the data.
        from engines import lab_harness as lh
        from engines.backtest import backtest_ohlc
        from scripts import b81_lane_rescore as b81
        c = json.load(open(os.path.join(
            ROOT, "data", "backtest", "ab_aggressive_data.json")))
        funnel = b81.funnel_fn(c["M15"], c["H1"], c["H4"])
        ts = lh.live_time_stop_bars(c["M15"])
        kw = dict(lh.LADDER, time_stop_bars=ts)
        base = lh.r_stats(backtest_ohlc(c["M15"], funnel, min_rr=lh.MIN_RR,
                                        spread=lh.SPREAD,
                                        min_grade=lh.LIVE_MIN_GRADE, **kw),
                          time_stop_bars=ts)
        tight = dict(kw, time_stop_bars=24)
        short = lh.r_stats(backtest_ohlc(c["M15"], funnel, min_rr=lh.MIN_RR,
                                         spread=lh.SPREAD,
                                         min_grade=lh.LIVE_MIN_GRADE, **tight),
                           time_stop_bars=24)
        self.assertNotEqual(base["exp_R"], short["exp_R"],
                            "a 24-bar time exit changed nothing — the knob is "
                            "dead and ts_cost==0 is vacuous")
        # A SHORTER time exit frees the single position slot earlier, so it can
        # only trade the same number or more — never fewer.
        self.assertGreaterEqual(short["trades"], base["trades"],
                                f"base {base['trades']} vs short "
                                f"{short['trades']} — the exit is not binding "
                                "the way the probe claims")


class TestB119NoLiveChangeShipped(unittest.TestCase):
    """A research probe that reverses a stored verdict must not silently act
    on it. The flat-0.30 candidate needs its own round + a human gate (b89)."""

    def test_the_live_share_function_is_untouched(self):
        from engines.trade_management import _partial_close_fraction
        a = {"setup_grade": "A", "momentum_strength": 0.8, "rr_remaining": 2.0,
             "structure_state": "healthy"}
        b = {"setup_grade": "B", "momentum_strength": 0.8, "rr_remaining": 2.0,
             "structure_state": "healthy"}
        self.assertEqual(_partial_close_fraction(a)[0], 0.3)
        self.assertEqual(_partial_close_fraction(b)[0], 1.0)

    def test_live_tp1_geometry_is_still_the_midpoint_the_incumbent_used(self):
        from engines import lab_harness as lh
        self.assertEqual(lh.LADDER["tp1_position"], 0.5)
        self.assertEqual(lh.LADDER["partial_tp1_share"], 0.5)

    def test_probe_is_read_only_and_names_no_live_writer(self):
        tree = ast.parse(open(PROBE).read())
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names.update(a.name.split(".")[0] for a in n.names)
            elif n.__class__ is ast.ImportFrom and n.module:
                names.add(n.module.split(".")[0])
        for banned in ("requests", "BridgeClient", "bridge_client", "subprocess",
                       "os.system"):
            self.assertNotIn(banned, names, f"probe imports {banned}")
        src = open(PROBE).read()
        for verb in ("systemctl", "restart", "open_position", "close_position",
                     "modify_position"):
            self.assertNotIn(verb, src, f"probe mentions {verb}")

    def test_the_flat_share_candidate_is_still_an_unwired_todo(self):
        # The reversal is a FINDING, not a change. b119 itself is DONE (its
        # measurement shipped), so the thing that must stay open is the DECISION
        # it produced. This pin has moved three times, each in the open:
        #   draft 1 rode "- [ ] b119" (its own item) and went red at step 3;
        #   draft 2 rode "- [ ] b121", which b121's own run closed (the
        #           replication shipped: flat_0.30 holds on two fresh windows);
        #   draft 3 rode "- [ ] b123", which shipped 2026-09-07 — the
        #           decomposition is in data/backtest/
        #           b123_protection_share_decomposition.json and it came out
        #           FOR the candidate (the share dial survives with protection
        #           held constant: 6/7 legs, both fresh windows, mean +0.030R),
        #           so the open thing is now the DECISION PACKAGE, b125.
        # b121's own test file pins the same state, so the carrier cannot be
        # quietly dropped: deleting either one leaves the other.
        text = open(os.path.join(ROOT, "data", "ops",
                                 "autopilot_backlog.md")).read()
        self.assertIn("- [x] b119", text,
                      "b119's measurement is shipped and its ledger is in the "
                      "repo — the done marker is the record of that")
        self.assertIn("- [x] b123", text,
                      "b123's decomposition ledger is in the repo — the done "
                      "marker is the record of that")
        self.assertIn("- [ ] b125", text,
                      "b125 (the wiring decision b123's decomposition produced) "
                      "is closed but no live exit change was made in this repo "
                      "— if the wiring happened, delete this pin IN THE OPEN "
                      "with the change")


if __name__ == "__main__":
    unittest.main(verbosity=2)
