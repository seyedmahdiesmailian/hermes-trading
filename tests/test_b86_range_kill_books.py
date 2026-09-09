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
                    # b71: every row carries hold stats on the ts row
                    self.assertIsNotNone(row[mode]["mean_hold_bars"])

    def test_time_exit_is_the_live_one(self):
        # b71: 36h on M15 bars = 144 bars, derived not hardcoded
        for leg in LEGS:
            self.assertEqual(self.led[leg]["gate_conf_0.35"]["_time_stop_bars"], 144)

    def test_mix_ships_per_leg(self):
        # b78: BUY/SELL mix of the trades actually taken
        for leg in LEGS:
            mix = self.led[leg]["gate_conf_0.35"]["_mix"]
            self.assertEqual(mix["buy"] + mix["sell"], mix["trades"])
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
        # the knob's ENTIRE observable effect on the trade book is zero:
        # never-kill and always-kill print identical trades/exp_R/net_R.
        for leg in LEGS:
            rows = [self.led[leg][f"gate_conf_{t}"]["ladder_ts"]
                    for t in LADDER]
            base = (rows[0]["trades"], rows[0]["exp_R"], rows[0]["net_R"])
            for r in rows[1:]:
                self.assertEqual(
                    (r["trades"], r["exp_R"], r["net_R"]), base, leg)

    def test_kill_share_zero_everywhere(self):
        for leg in LEGS:
            for t in LADDER:
                self.assertEqual(
                    self.led[leg]["_ladder"][t]["kill_share"], 0.0,
                    f"{leg} t={t}")


class TestShadowedByGradeGate(unittest.TestCase):
    """The decisive finding: even at full power the gate only ever touches
    C-grade signals — a population the live grade gate already rejects."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(LEDGER):
            raise unittest.SkipTest(f"{LEDGER} not built yet")
        cls.led = _load(LEDGER)

    def test_every_killable_signal_is_c_grade(self):
        for leg in LEGS:
            mix = self.led[leg]["_killed_at_099_grade_mix"]
            self.assertTrue(set(mix) <= {"C"}, f"{leg}: {mix}")
            self.assertGreater(sum(mix.values()), 400,
                               f"{leg}: ceiling should kill a large population")

    def test_live_gated_book_of_killed_population_is_empty(self):
        for leg in LEGS:
            self.assertEqual(
                self.led[leg]["dropped_conf_099_livegates"]["ladder_ts"]["trades"],
                0, leg)
        self.assertTrue(self.led["_verdict"]["fully_shadowed_by_grade_gate"])

    def test_ungated_book_trades_and_earns_below_the_funnel(self):
        # direction check: the rule aims at the WORST book in the system
        # (0.34-0.45R), it just never gets to shoot. Below the funnel bar on
        # EVERY leg — cached included, unlike most regime claims.
        for leg in LEGS:
            ung = self.led[leg]["dropped_conf_099_ungated"]["ladder_ts"]
            live = self.led[leg]["gate_conf_0.35"]["ladder_ts"]
            self.assertGreater(ung["trades"], 100, leg)
            self.assertIsNotNone(ung["exp_R"], leg)
            self.assertLess(ung["exp_R"], live["exp_R"],
                            f"{leg}: shadowed book out-earns the funnel")

    def test_verdict_redundancy_block_matches_legs(self):
        v = self.led["_verdict"]["redundancy"]
        for leg in LEGS:
            self.assertEqual(v[leg]["killed_signals"],
                             self.led[leg]["_signals_killed_at_099"])
            self.assertEqual(v[leg]["live_gated_book_trades"], 0)


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
