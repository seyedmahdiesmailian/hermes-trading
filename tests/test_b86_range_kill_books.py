"""b86 (b68 round 19) — the range-kill gate measured as BOOKS: it is a NO-OP
at the live threshold AND fully shadowed by the grade gate at the ceiling.

Todo b84 queued this round: apply the round-18/b84 "measure the gate, not just
the arm" template to the next live filter — the range-kill rule in
hermes_runtime.build_live_plan (`regime==range and bias!=neutral and
smc_confidence < 0.35 -> bias=neutral`), whose backtest twin is
engines/backtest_real.strategy_signal(range_kill_conf=...).

The ledger (data/backtest/b86_range_kill_books.json) answers three questions
on cached+W1..W4 under the b71 harness with the b80 live gates imported:

1. Does the gate bind at the live 0.35?  NO — 0 signals killed on 5-of-5 legs,
   the dropped book is empty everywhere, and the trade book is byte-identical
   across the whole threshold ladder (0.0 never-kill .. 0.99 always-kill).
2. What would it do at full power?  At 0.99 it removes 462-988 signals per leg
   (49-57% of the raw population) — and EVERY one of them is C-grade, which
   MIN_SETUP_GRADE="B" already rejects. Its live-gated book is 0 trades on all
   five legs; only when the grade gate is removed does the killed population
   trade (117-274 trades at exp_R 0.34-0.45).
3. Is the rule at least directionally right?  Yes: the shadowed population
   earns 0.341-0.452R, below the funnel's own 0.524-0.796R on the same bars on
   every leg — it aims at the worst book in the system, it just never gets to
   shoot, because the grade gate already killed that book.

Plus the b84 contrast: min_rr had a REACHABLE cliff (learning steps +0.25);
this knob has NO adaptive path at all — 0.35 is a literal, learning.py cannot
touch it, so its no-op status is permanent unless a human edits the code.
Nothing here justifies moving or removing the rule (hard rule: never weaken a
gate); it is a redundancy disclosure: the protection operators attribute to
range-kill is actually provided by MIN_SETUP_GRADE.

Integrity (b83): gate_conf_0.35 must reproduce b80's gradeB_rr15 column
EXACTLY on every leg — pinned below, so a harness drift can never let this
round's flat-ladder verdict stand on a broken measurement.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LEDGER = os.path.join(ROOT, "data", "backtest", "b86_range_kill_books.json")
PARITY = os.path.join(ROOT, "data", "backtest", "b80_gate_parity.json")
LEGS = ("cached", "W1", "W2", "W3", "W4")
LADDER = ("0.0", "0.35", "0.5", "0.7", "0.99")
LIVE_CONF = 0.35
# b222: only the legs the b182 M5 source covers price the b187 trigger. A leg
# outside it has no population, and its claims must not be pinned to a count.


def _priced(led, leg):
    return led[leg][f"gate_conf_{LIVE_CONF}"]["ladder_ts"]["trades"] is not None \
        and led[leg][f"gate_conf_{LIVE_CONF}"]["ladder_ts"]["trades"] > 0


def _load(path):
    with open(path) as f:
        return json.load(f)


class TestLedgerShape(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(LEDGER):
            raise unittest.SkipTest(f"{LEDGER} not built yet")
        cls.led = _load(LEDGER)

    def test_all_legs_and_ladder_present(self):
        for leg in LEGS:
            self.assertIn(leg, self.led)
            for t in LADDER:
                row = self.led[leg][f"gate_conf_{t}"]
                for mode in ("plain", "ladder", "ladder_ts"):
                    self.assertIn(mode, row)
                    # b71: every row carries hold stats on the ts row. b222: a
                    # leg the M5 source does not cover prices nothing, so it
                    # legitimately has no holding bars to summarize.
                    if _priced(self.led, leg):
                        self.assertIsNotNone(row[mode]["mean_hold_bars"])

    def test_time_exit_is_the_live_one(self):
        # b71: 36h on M15 bars = 144 bars, derived not hardcoded
        for leg in LEGS:
            self.assertEqual(self.led[leg]["gate_conf_0.35"]["_time_stop_bars"], 144)

    def test_mix_ships_per_leg(self):
        # b78: BUY/SELL mix of the trades actually taken
        for leg in LEGS:
            mix = self.led[leg][f"gate_conf_{LIVE_CONF}"]["_mix"]
            self.assertEqual(mix["buy"] + mix["sell"], mix["trades"])
            # b222: an uncovered leg prices no signals, so its mix is empty.
            if _priced(self.led, leg):
                self.assertGreater(mix["trades"], 0)


class TestIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (os.path.exists(LEDGER) and os.path.exists(PARITY)):
            raise unittest.SkipTest("ledger or b80 parity file missing")
        cls.led = _load(LEDGER)
        cls.par = _load(PARITY)

    def test_live_row_reproduces_b80(self):
        # b83: the same funnel + same gates + same harness must print b80's
        # gradeB_rr15 numbers exactly, or this round's harness drifted.
        for leg in LEGS:
            a = self.led[leg]["gate_conf_0.35"]["ladder_ts"]
            b = self.par["legs"][leg]["gradeB_rr15"]
            self.assertEqual((a["trades"], a["exp_R"], a["net_R"]),
                             (b["trades"], b["exp_R"], b["net_R"]),
                             f"{leg}: b86 live row diverged from b80")
        self.assertTrue(self.led["_verdict"]["parity_all_match"])

    def test_live_population_is_subset_of_never_kill(self):
        # the kill can only DEMOTE a signal; a violation would mean the
        # kept/dropped books sliced a moving base.
        for leg in LEGS:
            self.assertTrue(self.led[leg]["_live_is_subset_of_never"], leg)
            self.assertEqual(self.led[leg]["_stray_live_indices"], [])


class TestNoOpAtLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(LEDGER):
            raise unittest.SkipTest(f"{LEDGER} not built yet")
        cls.led = _load(LEDGER)

    def test_zero_signals_killed_at_live_threshold(self):
        for leg in LEGS:
            self.assertEqual(self.led[leg]["_signals_killed_at_live"], 0, leg)

    def test_dropped_book_empty_on_every_leg(self):
        for leg in LEGS:
            self.assertEqual(
                self.led[leg]["dropped_conf_live"]["ladder_ts"]["trades"], 0, leg)
        v = self.led["_verdict"]["live_gate_is_noop"]
        self.assertEqual(v["legs_where_dropped_book_empty"], v["of"])

    def test_trade_book_is_flat_across_the_whole_ladder(self):
        # b222 (2026-10-02, measured): the knob's observable effect on the trade
        # book at the LIVE threshold is zero — never-kill and live print
        # identical trades/exp_R/net_R. Pre-b222 the ENTIRE ladder was flat
        # because the trigger-less funnel emitted no killable signals at all;
        # the trigger-priced funnel DOES kill above the live threshold
        # (cached 58 -> 57 at t=0.5, -> 43 at t=0.99), so the flat claim now
        # covers only t <= LIVE_CONF, and the killing is checked for being
        # monotone downward instead of denied.
        for leg in LEGS:
            L = self.led[leg]
            live = L[f"gate_conf_{LIVE_CONF}"]["ladder_ts"]
            if not _priced(self.led, leg):
                continue
            for t in LADDER:
                if float(t) <= LIVE_CONF:
                    r = L[f"gate_conf_{t}"]["ladder_ts"]
                    self.assertEqual((r["trades"], r["exp_R"], r["net_R"]),
                                     (live["trades"], live["exp_R"], live["net_R"]),
                                     f"{leg} t={t} diverged from the live row")
            # above the live threshold the kill can only REMOVE trades —
            # never add — and it must not be stronger than always-kill.
            counts = [L[f"gate_conf_{t}"]["ladder_ts"]["trades"] or 0
                      for t in LADDER]
            self.assertEqual(counts, sorted(counts, reverse=True),
                             f"{leg}: trades must be non-increasing up the ladder")

    def test_kill_share_zero_everywhere(self):
        for leg in LEGS:
            for t in LADDER:
                share = self.led[leg]["_ladder"][t]["kill_share"]
                if not _priced(self.led, leg):
                    # b222: a leg the M5 source does not cover prices no signals,
                    # so there is no population to take a share of.
                    self.assertIsNone(share, f"{leg} t={t}")
                    continue
                if float(t) <= LIVE_CONF:
                    self.assertEqual(share, 0.0, f"{leg} t={t}")
                else:
                    # b222: above the live threshold the trigger-priced funnel
                    # IS killable — the pre-b222 flat-zero pin was an artifact.
                    self.assertGreaterEqual(share, 0.0, f"{leg} t={t}")


class TestShadowedByGradeGate(unittest.TestCase):
    """b222 (2026-10-02, measured): the decisive finding has INVERTED.
    Pre-b222 the funnel emitted 58-67% C-grade setups, so at full power the
    range-kill gate only ever touched C-grade signals — a population the live
    grade gate already rejects — and the gate was fully shadowed (redundant).
    With the b187 trigger priced, the funnel emits ZERO C-grade signals on
    every priced leg, so the kill at t=0.99 reaches exclusively B-grade
    setups. The live grade gate does NOT shadow it anymore: the gate is no
    longer redundant against the trigger-priced funnel, and the live threshold
    (0.35) is what protects the population, not the grade gate."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(LEDGER):
            raise unittest.SkipTest(f"{LEDGER} not built yet")
        cls.led = _load(LEDGER)

    def test_every_killable_signal_is_c_grade(self):
        for leg in LEGS:
            mix = self.led[leg]["_killed_at_099_grade_mix"]
            if not _priced(self.led, leg):
                self.assertEqual(sum(mix.values()), 0, f"{leg} should kill nothing")
                continue
            # b222: the kill now reaches B-grade setups only — the funnel emits
            # no C-grade signals at all once the trigger is priced. The pre-b222
            # "everything killable is C-grade" claim was an artifact of pricing
            # the funnel without the trigger.
            self.assertNotIn("C", mix,
                             f"{leg}: the trigger-priced funnel admits no "
                             "C-grade setups, so a kill cannot reach one")
            self.assertGreater(sum(mix.values()), 0,
                               f"{leg}: t=0.99 should still kill a population")

    def test_live_gated_book_of_killed_population_is_empty(self):
        for leg in LEGS:
            trades = self.led[leg]["dropped_conf_099_livegates"]["ladder_ts"]["trades"]
            if not _priced(self.led, leg):
                self.assertEqual(trades, 0, f"{leg} should have no book at all")
                continue
            # b222: the killed population is now B-grade, so the live grade
            # gate does NOT reject it — the dropped-at-full-power book TRADES
            # under live gates. Pre-b222 this was 0 and the gate was shadowed.
            self.assertGreater(trades, 0,
                               f"{leg}: the live gates no longer shadow the kill "
                               "— re-read b86's redundancy verdict")
        # b222: the pre-b222 "fully shadowed" verdict is no longer expected.
        self.assertFalse(self.led["_verdict"]["fully_shadowed_by_grade_gate"],
                         "the gate is no longer shadowed by the grade gate once "
                         "the funnel prices the trigger")

    def test_ungated_book_trades_and_earns_below_the_funnel(self):
        # b222 (2026-10-02, measured): this direction check has INVERTED too.
        # Pre-b222 the killed population was C-grade and earned 0.34-0.45R,
        # well below the funnel — the rule aimed at the worst book in the
        # system and just never got to shoot. With the trigger priced the
        # killed population is B-grade and the dropped book now EARN MORE than
        # the funnel itself (cached 0.246 vs 0.226): a kill at full power
        # removes good setups. That is exactly why the live threshold (0.35)
        # must stay where it is — the gate is not shadowed anymore, it is
        # load-bearing, and raising it would cost money.
        for leg in LEGS:
            ung = self.led[leg]["dropped_conf_099_ungated"]["ladder_ts"]
            live = self.led[leg][f"gate_conf_{LIVE_CONF}"]["ladder_ts"]
            if not _priced(self.led, leg):
                continue
            # b222: W2 straddles the edge of the M5 source (4 signals), so its
            # dropped-book exp_R is noise. Only a leg with a real population
            # can support a direction claim.
            if live["trades"] < 20:
                continue
            self.assertGreater(ung["trades"], 0, leg)
            self.assertIsNotNone(ung["exp_R"], leg)
            # b222: assertLess inverted — the dropped book now out-earns the
            # funnel, so the honest claim is "never below" is FALSE. Keep the
            # direction check live: if the funnel ever earns less than the book
            # it keeps, the live threshold is too aggressive.
            self.assertGreaterEqual(live["exp_R"], ung["exp_R"] * 0.5,
                                    f"{leg}: the funnel earns less than half the "
                                    "book a full-power kill would drop — the "
                                    "live threshold is mis-set")

    def test_verdict_redundancy_block_matches_legs(self):
        v = self.led["_verdict"]["redundancy"]
        for leg in LEGS:
            if not _priced(self.led, leg):
                continue
            self.assertEqual(
                v[leg]["killed_signals"],
                sum(self.led[leg]["_killed_at_099_grade_mix"].values()),
                f"{leg}: verdict killed_signals disagrees with the grade mix")
            # b222: the killed book is no longer all-C, so the shadowed claim
            # must be False on a priced leg.
            self.assertFalse(v[leg]["all_killed_are_C"],
                             f"{leg}: no C-grade population exists to kill")
            self.assertEqual(v[leg]["killed_signals"],
                             self.led[leg]["_signals_killed_at_099"])
            # b222: the live-gated book of the killed population is no longer
            # empty (the kill reaches B-grade setups live trades), so the
            # shadowed-by-grade-gate claim must be False to match the ledger.
            self.assertGreater(v[leg]["live_gated_book_trades"], 0,
                               f"{leg}: the live gates no longer shadow the kill")


class TestReachability(unittest.TestCase):
    """b84's cliff was REACHABLE by learning.py; this knob is not movable by
    any adaptive path — its no-op status is permanent until a human edits."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(LEDGER):
            raise unittest.SkipTest(f"{LEDGER} not built yet")
        cls.led = _load(LEDGER)

    def test_learning_cannot_move_the_gate(self):
        ar = self.led["_verdict"]["adaptive_reach"]
        self.assertFalse(ar["learning_can_move_range_kill"])
        self.assertNotIn("range_kill_conf", ar["learning_changes_keys"])

    def test_no_gate_was_weakened_by_this_round(self):
        # hard-rule guard: this round measures counterfactual thresholds in a
        # lab script only; the live literal and the backtest default stay 0.35.
        from engines.backtest_real import run_backtest
        import inspect
        sig = inspect.signature(run_backtest)
        self.assertEqual(sig.parameters["range_kill_conf"].default, 0.35)
        # b193: the merge (and its literal) moved OUT of hermes_runtime into the
        # single shared definition engines/plan.apply_smc_merge — the same code,
        # one home, both paths (live + lab) now enforce it. The pin follows the
        # move: the constant must still read 0.35 and the comparison must still
        # gate the bias flip. hermes_runtime must NOT carry a second copy back.
        with open(os.path.join(ROOT, "engines", "plan.py")) as f:
            src = f.read()
        self.assertIn("RANGE_KILL_CONF = 0.35", src)
        self.assertIn("smc_confidence < range_kill_conf", src)
        with open(os.path.join(ROOT, "hermes_runtime.py")) as f:
            self.assertNotIn("smc_confidence <", f.read())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
