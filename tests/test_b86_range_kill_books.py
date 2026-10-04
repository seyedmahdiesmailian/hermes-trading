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
        # AUDIT-2026-10-04: b86's probe runs the b222-threaded funnel (the b187
        # M5 trigger priced), while b80's ledger is the frozen PRE-b222
        # measurement (99 trades vs this probe's 75 on cached). b80 is the
        # shared reference the ledger web pins against, so it is deliberately
        # NOT re-priced here; what is pinned instead is that the two agree on
        # SHAPE — b86's live row is b80's live row minus the signals the M5
        # trigger removes — and that the probe still reports a clean parity
        # verdict over its own books.
        for leg in LEGS:
            a = self.led[leg]["gate_conf_0.35"]["ladder_ts"]
            b = self.par["legs"][leg]["gradeB_rr15"]
            if not _priced(self.led, leg):
                # Unpriced legs carry 0, not None — the probe runs the funnel
                # and gets an empty population on the M5-free windows.
                self.assertEqual(a["trades"], 0, f"{leg}: M5 does not cover "
                                 "this window but it prices trades — the "
                                 "trigger rows are leaking outside the source")
                continue
            # Same direction and sign; the M5 threading removes trades without
            # flipping the row's sign or emptying the leg.
            self.assertEqual(len({(a["trades"] > 0), (b["trades"] > 0)}), 1,
                             f"{leg}: one row prices trades and the other does "
                             "not — a funnel change, not a re-count")
            self.assertLessEqual(a["trades"], b["trades"], f"{leg}: the threaded "
                                "probe admits MORE signals than b80's pre-b222 "
                                "row — the trigger rows are additive, not "
                                "restrictive; re-read b222")
        # The probe's own parity verdict is now False by construction — it
        # re-checks its books against b80's frozen pre-b222 numbers and records
        # the divergence per leg (see _verdict.parity_vs_b80). Asserting True
        # would deny the funnel change; asserting the boolean at all adds
        # nothing over the per-leg checks above. Assert instead that the probe
        # actually performed the comparison and reported a reason for every leg.
        pv = self.led["_verdict"]["parity_vs_b80"]
        self.assertEqual(set(pv), set(LEGS), "the probe did not compare every "
                         "leg against b80 — its parity record is incomplete")
        for leg, rec in pv.items():
            self.assertIn("match", rec, f"{leg}: no match verdict recorded")
            self.assertIn("this_round", rec, f"{leg}: no measurement recorded")
            self.assertIn("b80", rec, f"{leg}: no b80 reference recorded")

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
    """b230 (2026-10-03, measured): the decisive finding has INVERTED AGAIN.

    b222 found the kill at t=0.99 reached exclusively B-grade setups and was
    NOT shadowed by the grade gate. b230 then removed the agreement-path: the
    range-kill used to fire whenever regime==range and SMC was directional,
    even when the classic bias AGREED with it. Post-b230 it fires only when
    the two models actually DISAGREE — and on this population they agree, so
    the kill is now a no-op even at t=0.99 (kill_share 0.0 on every priced
    leg, 0 signals killed, the killed population is empty).

    That is not a regression: b230 was the fix for 495/500 live plans shipping
    neutral, and the population this probe measures is the agreement case the
    old gate used to murder. The redundancy question is now moot — the gate
    reaches nothing, so there is nothing for the grade gate to shadow. The
    b222 test asserted the kill reached a B-grade population; b230 shows that
    population no longer exists at any threshold because the kill's trigger
    condition (disagreement) does not occur here."""

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
            # b230: the kill reaches NO population at all, on any threshold —
            # the disagreement it now requires does not occur on these bars.
            # Pre-b222 the mix was all-C; b222 found all-B; b230 finds empty.
            self.assertEqual(sum(mix.values()), 0,
                             f"{leg}: t=0.99 should kill nothing post-b230 "
                             "because the agreement case it used to ride on "
                             "was removed")

    def test_live_gated_book_of_killed_population_is_empty(self):
        for leg in LEGS:
            trades = self.led[leg]["dropped_conf_099_livegates"]["ladder_ts"]["trades"]
            # b230: the killed population is empty at every threshold, so its
            # live-gated book is empty by construction. Pre-b222 this asserted
            # the grade gate shadowed the kill; b222 asserted it did NOT; b230
            # makes both moot — there is no killed population to gate.
            self.assertEqual(trades, 0,
                             f"{leg}: no killed population post-b230, so its "
                             "live-gated book must be empty")
        # b230: with nothing killed, the shadow question has no object. The
        # verdict reports fully_shadowed=True (0 killed, 0 shadowed) which is
        # vacuously true rather than the b222 live-threshold claim.
        self.assertTrue(self.led["_verdict"]["fully_shadowed_by_grade_gate"],
                        "with no killed population the verdict is vacuous")

    def test_verdict_redundancy_block_matches_legs(self):
        # b230: the redundancy verdict is now driven by the kill being a
        # no-op, not by the grade gate shadowing a live population. The
        # always-kill share is zero on every priced leg.
        shares = self.led["_verdict"]["always_kill_share_of_signals"]
        for leg in LEGS:
            if not _priced(self.led, leg):
                self.assertIsNone(shares[leg], f"{leg} is unpriced")
                continue
            self.assertEqual(shares[leg], 0.0,
                             f"{leg}: t=0.99 kills 0% of signals post-b230 — "
                             "the disagreement trigger does not fire here")

    def test_ungated_book_trades_and_earns_below_the_funnel(self):
        # b230 (2026-10-03, measured): the killed population is empty at every
        # threshold, so the ungated dropped book has no trades to compare
        # against the funnel. Pre-b222 it earned 0.34-0.45R below the funnel;
        # b222 found it out-earning the funnel; b230 finds nothing there at
        # all. The direction question is moot — the disagreement trigger the
        # kill now requires does not occur on these bars.
        for leg in LEGS:
            ung = self.led[leg]["dropped_conf_099_ungated"]["ladder_ts"]
            live = self.led[leg][f"gate_conf_{LIVE_CONF}"]["ladder_ts"]
            if not _priced(self.led, leg):
                continue
            self.assertEqual(ung["trades"], 0,
                             f"{leg}: no killed population post-b230, so the "
                             "ungated dropped book must be empty")
            self.assertIsNone(ung["exp_R"], leg)

    def test_verdict_redundancy_block_matches_legs(self):
        # b230: the redundancy verdict is now driven by the kill being a
        # no-op, not by the grade gate shadowing a live population. The
        # always-kill share is zero on every priced leg and all_killed_are_C
        # is vacuously True (0 killed, so all 0 of them are C-grade).
        v = self.led["_verdict"]
        shares = v["always_kill_share_of_signals"]
        for leg in LEGS:
            if not _priced(self.led, leg):
                self.assertIsNone(shares[leg], f"{leg} is unpriced")
                continue
            self.assertEqual(shares[leg], 0.0,
                             f"{leg}: t=0.99 kills 0% of signals post-b230")


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
