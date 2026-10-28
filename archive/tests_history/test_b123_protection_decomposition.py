"""b123 — THE SHARE AXIS IS DECOMPOSED: THE PROTECTION CONFOUND IS REAL AND
MIXED-SIGN, AND THE SHARE EFFECT SURVIVES IT AT ~0.03R — WHICH MAKES THE
b119/b121 CANDIDATE A HUMAN-GATE DECISION, NOT A DEAD END.

WHY THIS ROUND EXISTS (b121b's note, verbatim problem)
======================================================
In engines/backtest.py the SL->entry move and the runner trail were BOTH armed
only inside the branch that takes a TP1 partial. So sweeping
`partial_tp1_share` from 1.0 to 0.0 did not move one dial: at 0.0 the trade
loses its partial, its breakeven protection, its trail AND its exemption from
the b57 time exit (that gate also read `partial_taken == 0`). Four things, one
knob. That is why the coupled curve's left end was the BEST arm on
cached/W1/W4/W5 and the WORST on W2/W3/W6 — a mixed sign b110 reads as no
lever, but the cause was the confound, not noise.

WHAT THE ROUND MEASURES
=======================
scripts/b123_protection_share_decomposition.py scores 18 arms x 2 time-exit
gates on the SAME seven legs b121/b121b used (cached + W1..W6), one parameter
at a time:
  * `partial`   = the coupled engine (every stored number in this repo),
  * `tp1`       = a TP1 TOUCH arms BE+trail whatever the share,
  * `none`      = a TP1 touch never arms them.
The `partial` family must reproduce b121/b121b row for row (integrity()), and
for the LIVE share rule `partial` and `tp1` must be the SAME trade while
`none` must differ — b122's arm-identity check run on this round's own arms,
so a mode that is not what it is named for fails the round instead of
quietly shipping a mislabelled column.

THE FINDINGS (read off the shipped ledger, data/backtest/
b123_protection_share_decomposition.json — every number below is in it)
=======================================================================
1. THE CONFOUND IS CONFIRMED AND THE CONFOUNDED AXIS IS NOT A LEVER. The
   coupled curve's left end (share=0.0) beats the incumbent on 4 of 7 legs and
   loses on 3 (+0.072..+0.094 vs -0.016..-0.029); the PURE protection effect at
   that same point (coupled 0.0 minus protected 0.0) is +0.072/+0.037/-0.030/
   -0.054/+0.013/+0.059/-0.056 — mixed sign, mean -0.006R. b110: no lever. So
   b121b's "monotone in the riding direction" curve really was two dials, and
   neither dial on its own replicates.
2. THE SHARE EFFECT SURVIVES WITH PROTECTION HELD CONSTANT — SMALL, AND
   ONE-SIDED. On the always-protected curve, 0.3 minus 1.0 is
   -0.007/+0.032/+0.026/+0.021/+0.057/+0.033/+0.049: 6 legs positive, 1
   slightly negative, BOTH fresh windows positive, mean +0.030R, max +0.057R.
   net_R agrees (6/7, +6.1R mean) and so does maxDD (5/7 better). That clears
   b110's one-sided bar under the leg-count-corrected definition (see
   TestB123OneSidedRule) and stays under b119's 0.10R magnitude ceiling.
   The honest statement is therefore the OPPOSITE of "no lever": the riding
   direction is a systematic but SMALL effect, and the confound inflated its
   apparent size (the coupled curve's left end looked worth up to +0.094R; the
   pure share effect at the same shape is worth ~+0.03R).
3. THE LIVE RULE IS PROTECTION-MODE INVARIANT (finding, not assumption): for
   `_partial_close_fraction`, `partial` and `tp1` are byte-identical on all
   seven legs, because live's function returns 1.0 for every non-A ticket —
   closed at TP1 before any arming — and 0.3 for the A lane, armed either way.
   So the cheap wiring proposal (decouple protection from the partial, keep the
   grade gate) is a MEASURED NO-OP. The only way to buy finding #2's +0.03R is
   to change the SHARE rule, and the arm that expresses it (`tp1::share_0.3`)
   runs a protection policy live does NOT run today: position_daemon arms BE
   only after a TP FILL, so a zero-share ticket never arms. That is a live
   exit-behaviour change = human gate (b89 class) → filed b125 with the
   decision package.
4. THE TIME-EXIT EXEMPTION IS MEASURED INERT ON THIS POPULATION. Live's
   `engines.legacy_guards.evaluate_time_exit` is purely age-based while the lab
   exempts any trade that took a partial, so the lab has a parity gap in
   principle. In numbers it is 0.000R on 15 of the 18 arms and -0.010..+0.003R
   on the three that reach it (the never-protected 0.3/0.5/0.7 arms, whose
   max_hold is 137-361 bars vs the 144-bar exit) — mixed sign, no leg count.
   The stored funnel bar therefore does NOT need a re-baseline; the gap is
   documented and pinned so it fails loudly if a future arm makes it material
   → filed b124.

WHAT THIS ROUND CHANGED IN THE ENGINE
=====================================
`protection_mode` and `time_stop_gate` parameters, both DEFAULTING to today's
behaviour, plus a `prot_armed` trade flag. The coupled path is untouched: the
incumbent row and every flat row reproduce b121/b121b byte-identically on all
seven legs (integrity() raises otherwise, and TestB123EngineIsAdditive pins
the defaults). engines/trade_management.py is untouched — this round measures,
it does not re-wire exits (standing rule), and finding #3 says there is no
free version of the change anyway.

A NOTE ON THIS FILE'S OWN HISTORY (b103/b118 discipline — the round was
rescued, not restarted): the first draft of this round was left UNCOMMITTED by
a dead run, and its docstring concluded "protection is the big axis, share is
the small one, neither clears b110's bar". Its own shipped ledger says the
reverse of both halves of that sentence (findings #1 and #2 above). The draft
also defined `one_sided_ge_3` as `pos >= 3 or neg >= 3` on SEVEN legs, where
the two sides always sum to seven so one of them is always >= 4: the flag was a
constant True, and the draft's anti-wiring pin asserted `assertFalse` on it —
i.e. the draft was RED because it could not express mixedness at its own leg
count. Fixed by `one_sided()` (a proportion rule that reproduces b110's literal
exactly at n=4), by re-deriving the ledger's `_neutrality` block, and by
rewriting every conclusion in this file against the numbers rather than the
prose. b120's rule applied to this round itself: the headline is re-quoted in
the same round that moved it.
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LED = os.path.join(ROOT, "data", "backtest",
                   "b123_protection_share_decomposition.json")
STEP1 = os.path.join(ROOT, "data", "backtest",
                     "b121_flat_share_replication.json")
STEP2 = os.path.join(ROOT, "data", "backtest", "b121b_share_sweep.json")
BT_PY = os.path.join(ROOT, "engines", "backtest.py")
SCRIPT = os.path.join(ROOT, "scripts",
                      "b123_protection_share_decomposition.py")

LEGS = ("cached", "W1", "W2", "W3", "W4", "W5", "W6")
FRESH = ("W5", "W6")
SHARES = (1.0, 0.7, 0.5, 0.3, 0.0)


def _load(path):
    with open(path) as fh:
        return json.load(fh)


L = _load(LED)
L1 = _load(STEP1)
L2 = _load(STEP2)


def arm(mode, value):
    return (f"{mode}::live_grade_share" if value == "grade"
            else f"{mode}::share_{value:.1f}")


def cell(leg, gate, name, metric="exp_R"):
    return L[leg]["grid"][f"{gate}::{name}"][metric]


def row(leg, gate, name):
    return L[leg]["grid"][f"{gate}::{name}"]


def delta(mode_a, mode_b, value, metric="exp_R", gate="no_partial"):
    """Per-leg difference of two arms that differ in ONE dial."""
    return {leg: round(cell(leg, gate, arm(mode_a, value), metric)
                       - cell(leg, gate, arm(mode_b, value), metric), 3)
            for leg in LEGS}


def signs(vals):
    v = [x for x in vals if x is not None]
    return sum(1 for x in v if x > 0), sum(1 for x in v if x < 0)


def ONE_SIDED(pos, neg):
    """The test file's own copy of the script's rule, deliberately INDEPENDENT:
    b104's discipline says a predicate that feeds a conclusion must be pinned
    against known splits, and if the test imported the script's function the
    cross-check in TestB123OneSidedRule would compare a function with itself.
    The stored ledger's flags are then checked against THIS one, so the two
    implementations cannot drift apart silently (b118's two-ledger rule)."""
    n = pos + neg
    return n > 0 and max(pos, neg) * 4 >= n * 3 and min(pos, neg) <= 1


class TestB123EngineIsAdditive(unittest.TestCase):
    """The new dials must default to the behaviour every stored number has."""

    def test_b123_protection_mode_and_gate_default_to_the_stored_shape(self):
        tree = ast.parse(open(BT_PY).read())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "backtest_ohlc")
        defaults = {a.arg: ast.unparse(d) for a, d in
                    zip(fn.args.args[len(fn.args.args) - len(fn.args.defaults):],
                        fn.args.defaults)}
        self.assertEqual(defaults.get("protection_mode"), "'partial'")
        self.assertEqual(defaults.get("time_stop_gate"), "'no_partial'")

    def test_b123_the_coupled_family_reproduces_b121_and_b121b_exactly(self):
        # The integrity check ran inside the script and raised otherwise; this
        # re-verifies it from the shipped ledger so a hand-edited JSON cannot
        # pass. `partial` IS the old engine — if these rows move, every stored
        # verdict in data/backtest/ silently changed meaning (b118's class).
        # b123's own first draft compared a FLOAT (exp_R) to a whole ROW DICT
        # here and was red on all seven legs; the comparison is dict-to-dict,
        # exactly like the script's, so a changed trade COUNT cannot hide behind
        # an unchanged mean.
        pairs = ((arm("partial", "grade"), L1, "incumbent_live_grade_fn"),
                 (arm("partial", 0.3), L1, "flat_0.30"),
                 (arm("partial", 0.5), L1, "flat_0.50"),
                 (arm("partial", 0.7), L1, "flat_0.70"),
                 (arm("partial", 1.0), L1, "b66b_winner_as_measured_const_1.0"),
                 (arm("partial", 0.0), L2, "flat_0.0"))
        for leg in LEGS:
            self.assertEqual(L["_integrity"][leg],
                             {k: True for k in L["_integrity"][leg]},
                             f"{leg}: integrity flags claim otherwise")
            for name, src, key in pairs:
                self.assertEqual(row(leg, "no_partial", name),
                                 src[leg]["share_grid"][key],
                                 f"{leg}/{name}: the coupled row differs from "
                                 f"the stored {key} row — two funnels spliced")

    def test_b123_the_engine_still_gates_the_trail_on_the_arm_flag(self):
        # NAME-CARRIER for the shape b121's pin watched: the trail now reads
        # `t["prot_armed"]`, which under the default mode is set exactly when a
        # partial was taken. If someone re-couples it to the share directly,
        # the decomposition cells stop being one-parameter arms.
        src = open(BT_PY).read()
        self.assertIn('if (trail_after_partial > 0 and t["prot_armed"]', src)
        self.assertIn('protection_mode: str = "partial"', src)


class TestB123OneSidedRule(unittest.TestCase):
    """b104's discipline on this round's own predicate: the neutrality test is
    a MEASUREMENT, so it is pinned against known splits before any conclusion
    is drawn from it. The draft's `pos >= 3 or neg >= 3` is a tautology at
    n=7 — these are the cells that prove the replacement is not."""

    def test_b123_one_sided_is_a_proportion_not_a_count(self):
        # b110's original shape at n=4: 3-of-4 with <=1 dissent is systematic.
        self.assertTrue(ONE_SIDED(3, 1))
        self.assertTrue(ONE_SIDED(4, 0))
        self.assertFalse(ONE_SIDED(2, 2), "an even split is the definition of mixed")
        # at n=7 the draft's literal was always True; a 4/3 split must not be.
        self.assertFalse(ONE_SIDED(4, 3), "3-of-7 is NOT b110's contamination "
                                          "signal — the draft's >=3 literal "
                                          "made every axis 'one-sided' and its "
                                          "own anti-wiring pin unsatisfiable")
        self.assertTrue(ONE_SIDED(6, 1))
        self.assertTrue(ONE_SIDED(7, 0))
        self.assertFalse(ONE_SIDED(5, 2), "5-of-7 is a majority, not the >=3/4 bar")
        self.assertFalse(ONE_SIDED(0, 0))

    def test_b123_the_shipped_neutrality_block_uses_the_pinned_rule(self):
        # The ledger's flags must agree with the predicate re-run on the
        # ledger's own counts, or the shipped JSON and the code disagree about
        # what "one-sided" means (b118's two-ledgers rule).
        for name, v in L["_neutrality"].items():
            self.assertEqual(v["one_sided_ge_3"],
                             ONE_SIDED(v["positive"], v["negative"]),
                             f"{name}: stored flag != recomputed flag")


class TestB123ArmIdentity(unittest.TestCase):
    """b122's rule applied to this round's own arms before trusting them."""

    def test_b123_the_live_share_rule_is_protection_mode_invariant(self):
        # partial == tp1 on every leg: live's function closes every non-A
        # ticket at TP1 (share 1.0) before any arming, and the A lane arms
        # under both modes. This is the finding that makes the cheap wiring
        # proposal (decouple protection, keep the grade gate) a NO-OP.
        for leg in LEGS:
            v = L["_arm_identity_live_share"][leg]
            self.assertTrue(v["partial_eq_tp1"],
                            f"{leg}: the two modes that should be identical "
                            f"for the live rule differ — one arm is not the "
                            f"rule it is named for (b122)")
            self.assertTrue(v["partial_neq_none"],
                            f"{leg}: `none` did not remove the protection — "
                            f"the dial is dead and every delta built on it is "
                            f"vacuous")

    def test_b123_the_share_zero_unprotected_arm_is_the_stored_coupled_arm(self):
        # share=0.0 under mode "none" must BE the arm b121b measured (no
        # partial, no BE, no trail) — the identity that lets the tp1 row be
        # read as a pure protection delta against a known quantity.
        for leg in LEGS:
            self.assertEqual(row(leg, "no_partial", arm("none", 0.0)),
                             row(leg, "no_partial", arm("partial", 0.0)),
                             f"{leg}: share=0.0 differs between the coupled "
                             f"engine and mode none — the coupled engine was "
                             f"arming something it should not")


class TestB123TheConfoundIsRealButMixed(unittest.TestCase):
    """Finding #1: the coupled curve's left end was two dials, and neither
    replicates. These pins are the SPARED direction — each one fires if the
    axis it calls mixed ever turns one-sided, which is when the question has
    to be re-decided in the open."""

    def test_b123_the_coupled_share_zero_advantage_is_mixed_sign(self):
        d = {leg: round(cell(leg, "no_partial", arm("partial", 0.0))
                        - cell(leg, "no_partial", arm("partial", "grade")), 3)
             for leg in LEGS}
        pos, neg = signs(d.values())
        self.assertGreaterEqual(pos, 1)
        self.assertGreaterEqual(neg, 1,
                                "share=0.0 no longer loses anywhere against "
                                "the incumbent — b121b's confound note is stale")
        self.assertFalse(ONE_SIDED(pos, neg),
                         "the coupled left end is one-sided on >=3/4 of seven "
                         "windows — re-open it as a candidate (human gate, b89)")

    def test_b123_the_pure_protection_effect_is_mixed_sign_and_small(self):
        v = L["_neutrality"]["protection_at_share_0_R"]
        self.assertGreaterEqual(v["positive"], 1)
        self.assertGreaterEqual(v["negative"], 1,
                                "the protection effect went one-sided — a real "
                                "lever may exist, re-decide in the open")
        self.assertFalse(v["one_sided_ge_3"],
                         "b110's contamination bar is met by the protection "
                         "axis — this is no longer a measurement, it is a "
                         "wiring proposal (human gate, b89)")
        self.assertLess(v["max_abs_R"], 0.10,
                        "the protection effect grew past b119's magnitude "
                        "ceiling — re-read before calling it noise")
        self.assertFalse(v["fresh_all_same_sign"],
                         "the protection effect replicates on the fresh pair — "
                         "re-open the candidate question")

    def test_b123_the_two_share_curves_disagree_so_the_coupled_one_was_the_confound(
            self):
        # The point of the round in one assertion: the coupled curve's shape is
        # NOT reproduced by the protected curve, so its slope was never a pure
        # share effect. If the two curves ever agree, the confound is gone and
        # b121b's stored ranking can be re-quoted.
        diff = [leg for leg in LEGS
                if L["_curve_coupled_live_engine"][leg]["best_share"]
                != L["_curve_protection_always"][leg]["best_share"]]
        self.assertGreater(len(diff), 0,
                           "the coupled and protected curves now agree "
                           "everywhere — the confound note in this file is "
                           "stale, rewrite it with the round that removed it")


class TestB123ShareEffectSurvivesHeldProtection(unittest.TestCase):
    """Finding #2 — the correction this round exists for. The draft read its
    own ledger as 'no lever on either axis'; the ledger says the PROTECTION
    axis is the mixed one and the SHARE axis, measured with protection held
    constant, is one-sided with fresh replication. b120's rule: re-quote the
    headline in the round that moved it, in both directions."""

    def test_b123_pure_share_effect_is_one_sided_with_fresh_replication(self):
        v = L["_neutrality"]["share_0_3_vs_1_0_protected_R"]
        self.assertEqual((v["positive"], v["negative"]), (6, 1),
                         "the pure share effect's per-leg sign pattern moved — "
                         "re-read the finding before quoting it")
        self.assertTrue(v["one_sided_ge_3"],
                        "the share effect is no longer one-sided across the "
                        "seven windows — b121's candidate is dead, say so and "
                        "close b125")
        self.assertTrue(v["fresh_all_same_sign"],
                        "the share effect lost its out-of-sample pair — the "
                        "candidate reverts to selection-set-only evidence")

    def test_b123_the_surviving_share_effect_is_small_not_big(self):
        # One-sided is not the same as large: the confounded curve's left end
        # looked worth up to +0.094R, the pure effect is ~1/3 of that. Pin the
        # ceiling so nobody re-inflates it by re-quoting the coupled number.
        v = L["_neutrality"]["share_0_3_vs_1_0_protected_R"]
        self.assertLess(v["max_abs_R"], 0.10, "past b119's magnitude ceiling")
        self.assertLess(v["mean_R"], 0.05)
        coupled = max(abs(x) for x in
                      (L["_decomposition"][leg]["protection_at_share_0_R"]
                       for leg in LEGS))
        self.assertGreater(coupled, v["max_abs_R"],
                           "the confound no longer overstates the share effect "
                           "— this round's central claim needs re-deriving")

    def test_b123_the_supporting_metrics_agree_with_the_share_effect(self):
        # exp_R alone is one number; net_R and maxDD_R are the two an operator
        # actually buys. Both must point the same way or the finding is a
        # per-trade artefact of a thinner trade count.
        def across(value, metric):
            return {leg: round(cell(leg, "no_partial", arm("tp1", value), metric)
                               - cell(leg, "no_partial", arm("tp1", 1.0), metric), 3)
                    for leg in LEGS}
        net, dd = across(0.3, "net_R"), across(0.3, "maxDD_R")
        self.assertGreaterEqual(signs(net.values())[0], 5,
                                f"net_R no longer agrees: {net}")
        self.assertGreaterEqual(signs(dd.values())[0], 4,
                                f"DD no longer agrees: {dd}")
        # And the trade COUNT. The first draft of this pin asserted EXACT
        # equality ("barely moves, so this is not a sample-size ghost") and was
        # RED on its own shipped ledger: cached 105 vs 110, W4 170 vs 179. That
        # was not a broken measurement, it was a wrong expectation — riding a
        # runner past TP1 HOLDS THE SINGLE SLOT LONGER (mean_hold 9.6 vs 8.8
        # bars on cached), so the share=0.3 arm must admit FEWER entries than
        # the share=1.0 arm that closes the ticket at TP1. The count moving is
        # the mechanism, not a confound. So the honest claim is a BOUND plus a
        # DIRECTION: the deficit stays small (else exp_R would be comparing
        # different populations) and it is always negative (else the engine
        # stopped modelling the slot). b121c measured the same asymmetry from
        # the operational side: the candidate multiplies the multi-call tail
        # ~3x while the call COUNT barely moves.
        for leg in LEGS:
            n_r = row(leg, "no_partial", arm("tp1", 0.3))["trades"]
            n_f = row(leg, "no_partial", arm("tp1", 1.0))["trades"]
            self.assertLess(n_r, n_f,
                            f"{leg}: riding the runner no longer costs slot "
                            f"time — check the engine's one-position gate "
                            f"before re-reading this round's exp_R delta")
            self.assertGreater(n_r, n_f * 0.92,
                               f"{leg}: the trade population behind the share "
                               f"delta moved >8% ({n_f} -> {n_r}) — exp_R is "
                               f"now comparing different samples, the finding "
                               f"needs re-deriving")


class TestB123TimeExitExemptionIsInertHere(unittest.TestCase):
    """Finding #4 + NAME-CARRIER for b124 (b102's discipline: a filed item
    lives in a test name, not only in the backlog). The lab exempts any trade
    that took a partial from the b57 time exit; live's
    legacy_guards.evaluate_time_exit is age-based and does not. The gap is
    real in code and measured INERT in numbers — this pin is the spared
    direction: it fires if the exemption ever starts to cost, which is when
    b124's parity decision becomes a re-baseline decision (b120's rule)."""

    def test_b124_the_time_exit_exemption_costs_nothing_on_the_stored_arms(self):
        v = L["_neutrality"]["time_exit_exemption_cost_R"]
        self.assertFalse(v["one_sided_ge_3"],
                         "the exemption moved the bar one-sided on >=3/4 of "
                         "seven windows — the stored funnel numbers need a "
                         "re-baseline decision (b124), not a shrug")
        self.assertLessEqual(v["max_abs_R"], 0.010,
                             "the exemption's cost grew past 0.010R — b124 is "
                             "no longer a documentation item, re-run the bar")
        # and the reason it is inert must stay the reason: no arm that the
        # exemption can see holds past the time exit under either gate.
        ts = L["cached"]["_time_stop_bars"]
        for leg in LEGS:
            self.assertEqual(ts, L[leg]["_time_stop_bars"])
            for name in (arm("partial", "grade"), arm("partial", 0.3),
                         arm("tp1", 0.3), arm("tp1", "grade")):
                self.assertLessEqual(row(leg, "no_partial", name)["max_hold_bars"],
                                     ts, f"{leg}/{name}: a protected arm now "
                                         f"outrides the time exit the lab "
                                         f"exempts it from — the exemption is "
                                         f"no longer inert")


class TestB125WiringDecision(unittest.TestCase):
    """NAME-CARRIER for b125 (b102's discipline: a filed item lives in a test
    name, not only in the backlog). b123 measured that the ONLY way to buy the
    surviving +0.030R share effect is a live exit-behaviour change (arm BE at
    TP1 TOUCH instead of after a partial fill), which is a human gate (b89
    class). This is the spared-direction pin: it fires the day someone wires
    the share rule without editing the decision in the open."""

    def test_b125_live_share_rule_is_still_grade_gated(self):
        # live's share function must still return the FULL close for every
        # non-strong-runner ticket — the flat-0.3 candidate stays lab-only
        # until b125 is decided.
        from engines.trade_management import _partial_close_fraction
        plain = {"grade": "A", "momentum_strength": 0.5,
                 "rr_remaining": 1.5, "structure_state": "healthy"}
        share, _why = _partial_close_fraction(plain)
        self.assertEqual(share, 1.0,
                         "live's share rule moved off the grade-gated 1.0 — "
                         "b125 was wired; edit this pin IN THE OPEN with the "
                         "change, never delete it")
        src = inspect.getsource(_partial_close_fraction)
        self.assertNotIn("protection_mode", src,
                         "the lab's protection dial leaked into live's share "
                         "rule — b123 finding #3 (the cheap wiring is a "
                         "no-op) is no longer the shape live runs")


class TestB123NoLiveChange(unittest.TestCase):
    """Standing rule: the autopilot measures, it does not re-wire exits."""

    def test_b123_wired_nothing_into_the_live_path(self):
        tm = open(os.path.join(ROOT, "engines", "trade_management.py")).read()
        self.assertNotIn("protection_mode", tm)
        self.assertNotIn("prot_armed", tm)
        rt = open(os.path.join(ROOT, "hermes_runtime.py")).read()
        self.assertNotIn("protection_mode", rt)
        pd = open(os.path.join(ROOT, "position_daemon.py")).read()
        self.assertNotIn("protection_mode", pd)

    def test_b123_the_backlog_item_is_closed(self):
        # b114's rule: a pin must not punish the required edit, so this rides
        # the DONE marker the round is supposed to write, not the todo one.
        text = open(os.path.join(ROOT, "data", "ops",
                                 "autopilot_backlog.md")).read()
        self.assertIn("- [x] b123", text)
        self.assertNotIn("- [ ] b123", text,
                         "b123 is still open while its ledger ships — either "
                         "the round did not finish or the note was not moved")

    def test_b123_script_exists_and_is_the_only_producer_of_the_ledger(self):
        self.assertTrue(os.path.exists(SCRIPT))
        src = open(SCRIPT).read()
        self.assertIn("b123_protection_share_decomposition.json", src)
        # every live value imported, never restated (b118's rule)
        self.assertIn("from engines.trade_management import _partial_close_fraction", src)
        self.assertIn("lh.LIVE_MIN_GRADE", src)


if __name__ == "__main__":
    unittest.main()
