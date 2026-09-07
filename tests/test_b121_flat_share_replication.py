"""b121 — flat_0.30 REPLICATES ON TWO WINDOWS IT WAS NEVER RANKED ON, AND THE
LIVE GRADE-GATED SHARE RULE FINISHES LAST OR SECOND-LAST ON BOTH OF THEM.

WHAT WAS STORED (b119, 2026-09-07)
==================================
b119 re-priced b66b's exit-share decision and found `flat_0.30` (keep a 0.3
runner on EVERY trade instead of only on the A lane) beat the live
grade-weighted incumbent one-sided on exp_R in 4/4 windows (+0.002..+0.046R).
It filed that as a CANDIDATE requiring replication, because those four windows
are W1..W4 — the same bars every exit decision in this repo has been chosen on
since b68l built them. b74's protocol: a one-sided delta on the selection set
is not replication.

WHAT THIS ROUND DID
===================
1. scripts/b121_fresh_windows.py cut W5 and W6 out of the broker's deep M15
   history — 6000 bars each, strictly before W4, overlap with cached/W1..W4/
   each other MEASURED to zero (W5 2025-04-07..2025-07-09, W6 2025-01-06..
   2025-04-07). Bar count and fetch depth are IMPORTED from b68l, not restated.
2. scripts/b121_flat_share_replication.py scored the same arms on all seven
   legs with the same harness (live grade gate + min_rr imported, runner trail
   and $ floor derived per b118). RESULT: flat_0.30 replicates — +0.028R on W5,
   +0.035R on W6, 2/2 fresh windows, and it stays one-sided 4/4 on the
   selection set. The constant-1.0 arm b66b actually crowned loses on both
   fresh windows too (-0.005/-0.014), so b119's reversal holds out of sample.
3. scripts/b121b_share_sweep.py added the five share points step 1 did not run
   (0.0/0.1/0.2/0.4/0.9) and merged them into one curve per leg. The merge is
   CHECKED, not assumed: the incumbent row must be byte-identical between the
   two ledgers, or the "curve" would be two different funnels spliced together
   (b118's stale-bar lesson applied to a merge).

THE FINDING THAT MATTERS MORE THAN THE CANDIDATE
================================================
The curve is monotone in the RIDING direction almost everywhere, and the live
rule — which keeps the runner on A only — sits at the WRONG END of it: on W1,
W4 and W5 the incumbent is beaten by ALL NINE flat alternatives (rank 9/9), and
on W6 by eight of nine. On the two windows nobody had ever ranked on, live's
partial-close policy is the worst-but-one arm in the room. b66b's "grade-
weighted sizing CONFIRMED as real edge" is now not merely unsupported (b119) —
its opposite replicates out of sample.

WHAT THIS ROUND REFUSES TO CLAIM
================================
The left end of the curve is NOT the same trade as the rest of it. In
engines/backtest.py the breakeven move and the runner trail are both gated on
`partial_taken > 0`, so share=0.0 means no partial, no BE, no trail — a plain
TP/SL ticket (and one that the time exit can actually fire on). That arm is
best on cached/W1/W4/W5 (+0.072/+0.071/+0.066/+0.094R over the incumbent) and
WORST on W2/W3/W6 (-0.016/-0.029/-0.020R). Mixed sign across seven windows =
b110's contamination test says NO LEVER, and the confound (share vs BE/trail)
is why. So this round ships a REPLICATION of a small, monotone, gate-shaped
delta and a DECOMPOSITION question (filed b123), not a wiring proposal.

THE CENSUS THAT WAS WRONG IN THIS ROUND'S OWN FIRST DRAFT (b122's shape, caught
by reading the numbers instead of the names): step 1 counted "trades riding past
TP1" off `exit_reason` and reported 0.0952 for flat_0.1 through flat_0.9 —
identical for every share — while claiming 0.54 for share=0.0, an arm that
never takes a partial at all. Which exit a runner reaches is a function of the
price path, not of the share, so that census was STRUCTURALLY BLIND to the one
parameter the grid varies. engines/backtest.py's trade_log now carries
`partial_taken` (additive; every pre-b121 row and number is unchanged), and the
honest operational-cost census is filed as b121c. TestB121CensusIsBlind pins
the defect so the void column can never be re-quoted as a measurement.

NO LIVE CHANGE. engines/trade_management.py is untouched; a live exit-behaviour
change is a human gate (b89 class) and the autopilot does not re-wire the path.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

STEP1 = os.path.join(ROOT, "data", "backtest",
                     "b121_flat_share_replication.json")
STEP2 = os.path.join(ROOT, "data", "backtest", "b121b_share_sweep.json")
FRESH_LEDGER = os.path.join(ROOT, "data", "backtest", "b121_fresh_windows.json")
B119 = os.path.join(ROOT, "data", "backtest", "b119_exit_grid_reprice.json")
B118 = os.path.join(ROOT, "data", "backtest", "b118_merit_bar_rebaseline.json")
WIN_LEDGER = os.path.join(ROOT, "data", "backtest", "b68l_independent_windows.json")
S1_PY = os.path.join(ROOT, "scripts", "b121_flat_share_replication.py")
S2_PY = os.path.join(ROOT, "scripts", "b121b_share_sweep.py")
FW_PY = os.path.join(ROOT, "scripts", "b121_fresh_windows.py")
BT_PY = os.path.join(ROOT, "engines", "backtest.py")

SELECTION = ("cached", "W1", "W2", "W3", "W4")
FRESH = ("W5", "W6")
LEGS = SELECTION + FRESH
INCUMBENT = "incumbent_live_grade_fn"
FLAT30 = "flat_0.30"
CONST10 = "b66b_winner_as_measured_const_1.0"

# b119's stored rows — the selection-set numbers this round must reproduce.
B119_INCUMBENT = {"cached": 0.278, "W1": 0.211, "W2": 0.230, "W3": 0.232,
                  "W4": 0.233}
B119_FLAT30 = {"cached": 0.278, "W1": 0.234, "W2": 0.232, "W3": 0.248,
               "W4": 0.279}


def _load(path):
    with open(path) as fh:
        return json.load(fh)


LED1 = _load(STEP1)
LED2 = _load(STEP2)
FRESH_LED = _load(FRESH_LEDGER)
LED119 = _load(B119)
# b123's decomposition ledger, read by the name-carrier pin below so the
# "share=0.0 is a different trade" claim stays a NUMBER, not a memory.
LED3 = _load(os.path.join(ROOT, "data", "backtest",
                          "b123_protection_share_decomposition.json"))


class TestB121FreshWindowsAreFresh(unittest.TestCase):
    """If W5/W6 touch the selection bars, the whole round is in-sample noise."""

    def test_both_windows_are_full_length(self):
        for name in FRESH:
            m = FRESH_LED[f"_{name}_meta"]
            self.assertEqual(m["m15_bars"], 6000, f"{name} truncated")
            self.assertGreater(m["h1_ctx"], 80, f"{name} has no H1 context")
            self.assertGreater(m["h4_ctx"], 80, f"{name} has no H4 context")

    def test_overlap_with_every_older_window_is_measured_zero(self):
        for name in FRESH:
            ov = FRESH_LED[f"_{name}_meta"]["overlaps"]
            self.assertEqual(set(ov), {"cached", "W1", "W2", "W3", "W4",
                                       "W5", "W6"} - {name},
                             f"{name} overlap census incomplete: {sorted(ov)}")
            for other, n in ov.items():
                self.assertEqual(n, 0, f"{name} overlaps {other} by {n} bars")

    def test_windows_are_chronologically_disjoint_and_before_W4(self):
        w4_first = _load(WIN_LEDGER)["_W4_meta"]["first"]
        w5, w6 = FRESH_LED["_W5_meta"], FRESH_LED["_W6_meta"]
        self.assertLess(w5["last"], w4_first, "W5 reaches into W4")
        self.assertLess(w6["last"], w5["first"], "W6 reaches into W5")
        self.assertEqual(FRESH_LED["_anchor_first_bar_W4"], w4_first,
                         "the anchor was restated, not read from b68l")

    def test_bar_count_is_imported_not_restated(self):
        src = open(FW_PY).read()
        self.assertIn("WINDOW_BARS = wl.WINDOW_BARS", src,
                      "b121 restates the window length instead of importing "
                      "it from b68l (b109's disease)")
        self.assertIn("FETCH_COUNT = wl.FETCH_COUNT", src)

    def test_window_builder_is_history_only(self):
        tree = ast.parse(open(FW_PY).read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr,
                                 ("open_position", "close_position",
                                  "modify_position", "place_order"),
                                 f"builder calls {node.func.attr} — this round "
                                 f"must be read-only")


class TestB121Replication(unittest.TestCase):
    """The candidate must hold on the fresh pair, and must stay SMALL."""

    def test_selection_set_reproduces_b119_exactly(self):
        # Cross-ledger integrity: if these move, this round measured a
        # different funnel than the one whose candidate it is testing.
        for leg in SELECTION:
            self.assertEqual(
                LED1[leg]["share_grid"][INCUMBENT]["exp_R"],
                B119_INCUMBENT[leg], f"{leg} incumbent moved vs b119")
            self.assertEqual(
                LED1[leg]["share_grid"][FLAT30]["exp_R"],
                B119_FLAT30[leg], f"{leg} flat_0.30 moved vs b119")
            self.assertEqual(
                LED1[leg]["share_grid"][INCUMBENT]["exp_R"],
                LED119[leg]["share_grid"][INCUMBENT]["exp_R"],
                f"{leg} disagrees with b119's own ledger")

    def test_the_fresh_legs_are_not_in_b119(self):
        # Anti-vacuity: the replication claim is only worth anything if the
        # windows are new to the round that made the claim.
        for leg in FRESH:
            self.assertNotIn(leg, LED119, f"b119 already scored {leg}")
            self.assertIn(leg, LED1)

    def test_b121_flat_0_30_replicates_on_both_fresh_windows(self):
        # NAME-CARRIER for b121 (b102: a filed item lives in a test name, not
        # only in this file or a commit message).
        v = LED1["_verdict"][FLAT30]
        self.assertTrue(v["replicated_on_fresh"],
                        f"fresh deltas {v['delta_exp_R']} — the candidate did "
                        f"NOT replicate; b121's premise is dead")
        self.assertEqual(v["fresh_windows_won"], 2)
        self.assertEqual(v["fresh_windows_lost"], 0)
        for leg in FRESH:
            self.assertGreater(LED1[leg]["share_grid"][FLAT30]["exp_R"],
                               LED1[leg]["share_grid"][INCUMBENT]["exp_R"], leg)

    def test_the_delta_stays_noise_sized(self):
        # b119's ceiling, re-applied: a gap the size of b66b's phantom 2x
        # would mean the double-count is back, not that sizing got better.
        v = LED1["_verdict"][FLAT30]
        self.assertLess(v["max_abs_delta_exp_R"], 0.10,
                        f"delta grew to {v['max_abs_delta_exp_R']}R — re-read "
                        f"the engine before quoting this candidate")

    def test_b66b_winner_still_loses_out_of_sample(self):
        v = LED1["_verdict"][CONST10]
        self.assertEqual(v["fresh_windows_won"], 0)
        self.assertEqual(v["fresh_windows_lost"], 2)
        self.assertFalse(v["replicated_on_fresh"])

    def test_the_incumbent_is_last_or_second_last_on_every_fresh_window(self):
        # The load-bearing number of the round: live's grade-gated share rule
        # is not mid-pack, it is at the bottom of the curve on data it was
        # never ranked on.
        for leg in FRESH:
            c = LED2["_curve"][leg]
            self.assertGreaterEqual(c["incumbent_rank_in_curve"], c["n_points"] - 1,
                                    f"{leg}: incumbent rank "
                                    f"{c['incumbent_rank_in_curve']}/{c['n_points']}")
        for leg in ("W1", "W4", "W5"):
            c = LED2["_curve"][leg]
            self.assertEqual(c["incumbent_rank_in_curve"], c["n_points"],
                             f"{leg}: incumbent no longer dead last")


class TestB121bCurveIsNotALever(unittest.TestCase):
    """The round must NOT sell the left end of the curve as free money."""

    def test_the_curve_carries_every_share_point_once(self):
        for leg in LEGS:
            c = LED2["_curve"][leg]
            shares = sorted(p["share"] for p in c["curve_by_share_desc"])
            self.assertEqual(shares, sorted([1.0, 0.9, 0.7, 0.5, 0.4, 0.3,
                                             0.2, 0.1, 0.0]),
                             f"{leg} curve is missing points: {shares}")
            self.assertEqual(c["n_points"], 9)

    def test_the_merge_did_not_splice_two_funnels(self):
        # _merge raises on a moved incumbent row; this pins that the check
        # passed on the shipped ledger, leg by leg.
        for leg in LEGS:
            self.assertEqual(LED2["_merged"][leg][INCUMBENT],
                             LED1[leg]["share_grid"][INCUMBENT],
                             f"{leg}: step 2's incumbent differs from step 1")

    def test_share_zero_is_not_one_sided_so_no_lever_is_claimed(self):
        best_is_zero = [leg for leg in LEGS
                        if LED2["_curve"][leg]["best_share"] == 0.0]
        worst_is_zero = [leg for leg in LEGS
                         if LED2["_curve"][leg]["worst_share"] == 0.0]
        self.assertTrue(best_is_zero, "no leg prefers no-partial — re-read")
        self.assertTrue(worst_is_zero,
                        "share=0.0 is no longer a loser anywhere — the "
                        "confound may have been removed, re-decide")
        self.assertLessEqual(len(best_is_zero), 5,
                             "if 0.0 wins everywhere the BE/trail confound "
                             "note in this file is stale")

    def test_b123_the_breakeven_and_trail_are_gated_on_the_partial(self):
        # NAME-CARRIER for b123 (b102's discipline: a filed item lives in a
        # test name, not only in this file). EDITED, not deleted, when b123
        # shipped its decomposition (2026-09-07).
        # WHAT CHANGED: b123 added `protection_mode`, so the trail line now
        # reads `t["prot_armed"]` instead of `t["partial_taken"] > 0`. That is
        # NOT a decoupling — under the DEFAULT mode ("partial") prot_armed is
        # set exactly when a partial was taken, so the live path still moves SL
        # to entry and starts the trail only inside the partial branch, and the
        # share=0.0 confound b121b found still holds for everything live runs.
        # The pin therefore keeps its job in a stronger form: it now asserts
        # BOTH the code shape and the equivalence that makes the shape matter.
        # If someone wires a non-default mode into the live funnel, the
        # equivalence assert is what fires.
        src = open(BT_PY).read()
        self.assertIn('if (trail_after_partial > 0 and t["prot_armed"]', src,
                      "the trail is no longer gated on the arm flag — b123's "
                          "decomposition cells stop being one-parameter arms")
        self.assertIn('protection_mode: str = "partial"', src,
                      "the engine's default protection mode moved off the "
                          "coupled shape every stored number was measured on")
        self.assertIn("t[\"be_moved\"] = True", src)
        # the equivalence, read off b123's own ledger: for the coupled family
        # the protected and unprotected share=0.0 arms are the SAME trade,
        # because at share=0.0 no partial is taken and so nothing arms.
        for leg in ("cached", "W1", "W2", "W3", "W4", "W5", "W6"):
            self.assertEqual(
                LED3[leg]["grid"]["no_partial::partial::share_0.0"],
                LED3[leg]["grid"]["no_partial::none::share_0.0"],
                f"{leg}: the coupled engine arms protection without a partial "
                f"— b121b's confound note is stale, rewrite it")


class TestB121CensusIsBlind(unittest.TestCase):
    """b122's rule applied to this round's own first draft."""

    def test_the_exit_reason_census_cannot_see_the_share(self):
        # flat_0.30/0.50/0.70 all report the SAME runner-path share, and
        # share=0.0 — the arm that never takes a partial at all — reports the
        # LARGEST. The column is void; b121c re-measures it off partial_taken.
        census = LED1["cached"]["path_census"]
        flat = [v["runner_path_share"] for k, v in census.items()
                if k.startswith("flat_")]
        self.assertEqual(len(set(flat)), 1,
                         "the void census stopped being degenerate — b121c may "
                         "already be measured, re-read the ledger")
        merged = LED2["_path_census_merged"]["cached"]
        self.assertGreater(merged["flat_0.0"]["runner_path_share"],
                           merged["flat_0.30"]["runner_path_share"],
                           "the no-partial arm no longer out-reports the "
                           "partial arms — the blindness is gone, delete this "
                           "pin IN THE OPEN with b121c")

    def test_the_engine_now_records_the_share_that_was_taken(self):
        tree = ast.parse(open(BT_PY).read())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "backtest_ohlc")
        src = ast.unparse(fn)
        self.assertIn("partial_taken", src,
                      "trade_log lost the field the honest census needs")
        self.assertIn("float(t.get('partial_taken') or 0.0)", src,
                      "the field is no longer read off the trade dict")

    def test_the_field_is_additive_not_a_restatement(self):
        # partial_taken must be read off the trade dict, never recomputed.
        src = open(BT_PY).read()
        self.assertIn('float(t.get("partial_taken") or 0.0)', src)


class TestB121cHonestCallCensus(unittest.TestCase):
    """The census b121 asked for, measured off the field that CAN see it."""

    CEN = _load(os.path.join(ROOT, "data", "backtest",
                             "b121c_partial_call_census.json"))

    def test_the_candidate_multiplies_runner_trades_not_partial_calls(self):
        # The founding note guessed "the partial-close path runs 5x more
        # often". Measured: the number of PARTIAL CALLS barely moves (the same
        # trades reach TP1 either way), but the trades that stay open AFTER
        # TP1 — the ones needing trail modifies plus a final close — roughly
        # TRIPLE. The cost is in the multi-call tail, not the call count.
        for leg in ("cached", "W5", "W6"):
            ratio = self.CEN["_ratio"][leg]
            self.assertLess(ratio["partial_calls_candidate_over_incumbent"], 1.05,
                            f"{leg}: partial-call volume moved — re-read the "
                            f"engine before quoting this census")
            self.assertGreater(ratio["multi_call_runner_trades_candidate_over_incumbent"],
                               2.0, f"{leg}: the runner tail no longer multiplies")
            self.assertLess(ratio["multi_call_runner_trades_candidate_over_incumbent"],
                            5.0, f"{leg}: the 5x guess is now an understatement — "
                                 f"re-price the operational risk")

    def test_the_incumbent_closes_most_winners_in_one_call(self):
        for leg in ("cached", "W5", "W6"):
            c = self.CEN[leg]["incumbent_live_grade_fn"]
            self.assertGreater(c["one_call_closes_at_tp1"], 0)
            f = self.CEN[leg]["flat_0.30"]
            self.assertEqual(f["one_call_closes_at_tp1"], 0,
                             "flat_0.30 must never close the ticket at TP1")

    def test_the_exp_R_rows_reproduce_step_1(self):
        for leg in ("cached", "W5", "W6"):
            self.assertEqual(self.CEN[leg]["incumbent_live_grade_fn"]["exp_R"],
                             LED1[leg]["share_grid"][INCUMBENT]["exp_R"],
                             f"{leg} incumbent moved between b121 and b121c")
            self.assertEqual(self.CEN[leg]["flat_0.30"]["exp_R"],
                             LED1[leg]["share_grid"][FLAT30]["exp_R"],
                             f"{leg} flat_0.30 moved between b121 and b121c")


class TestB121NothingIsWired(unittest.TestCase):
    """The decision stays human (b89 class)."""

    def test_no_lab_arm_leaks_into_the_live_share_function(self):
        src = open(os.path.join(ROOT, "engines", "trade_management.py")).read()
        self.assertNotIn("lab_flat_share", src)
        self.assertNotIn("b121", src)

    def test_the_research_scripts_are_not_imported_by_the_live_path(self):
        live = [p for p in ("hermes_master.py", "hermes_runtime.py",
                            "position_daemon.py", "signal_daemon.py",
                            "engines/auto_executor.py")
                if os.path.exists(os.path.join(ROOT, p))]
        self.assertGreaterEqual(len(live), 4)
        for p in live:
            tree = ast.parse(open(os.path.join(ROOT, p)).read())
            for node in ast.walk(tree):
                mods = set()
                if isinstance(node, ast.ImportFrom) and node.module:
                    mods.add(node.module)
                elif isinstance(node, ast.Import):
                    mods.update(a.name for a in node.names)
                for m in mods:
                    self.assertNotIn("b121", m, f"{p} imports {m}")

    def test_the_candidate_round_is_still_open(self):
        # b119's pin rode "- [ ] b121"; closing b121 moves the unwired-state
        # carrier to the rounds this one files (b121c census, b123
        # decomposition). EDITED in the open with a named note, never deleted
        # (b102/b114's rule: a suite that punishes the required edit trains
        # people to delete the test).
        # b123 SHIPPED 2026-09-07 (the decomposition: the protection axis is
        # mixed-sign, the share axis survives at ~+0.03R with fresh
        # replication), so the carrier moves to b125 — the wiring DECISION that
        # decomposition produced. The state this pins has not changed: nothing
        # is wired, and the decision is still human.
        text = open(os.path.join(ROOT, "data", "ops",
                                 "autopilot_backlog.md")).read()
        self.assertIn("- [x] b121", text,
                      "b121's measurement is shipped — the done marker is the "
                      "record of that")
        # b121c (the honest call census) shipped IN THE SAME RUN, so the
        # unwired-state carrier is b125, the decision package b123 filed.
        self.assertIn("- [x] b121c", text,
                      "b121c's census ledger is in the repo — the done marker "
                      "is the record of that")
        self.assertIn("- [x] b123", text,
                      "b123's decomposition ledger is in the repo — the done "
                      "marker is the record of that")
        self.assertIn("- [ ] b125", text,
                      "b125 closed but no live exit change was made in this "
                      "repo — if the wiring happened, delete this pin IN THE "
                      "OPEN with the change")


if __name__ == "__main__":
    unittest.main(verbosity=2)
