"""b124 — THE LAB'S TIME-EXIT EXEMPTION HAS A REAL POPULATION ON LIVE'S CLOCK,
AND THAT POPULATION IS 100% WINNERS, YET THE GAP STILL COSTS ~NOTHING.

WHAT THIS ROUND CLOSES
======================
b123 filed the code gap (the lab exempts any trade that took a partial from the
b57 time exit; `legacy_guards.evaluate_time_exit` is age-based and does not).
b129 priced it on the BAR clock and called it inert across all 14 arms. b130
proved the bar clock is the wrong clock — 32 funnel trades are at/over 36 WALL
hours while ZERO reach 144 bars — but its census counted old trades WITHOUT
splitting them by `partial_taken`, so the ledger never said how many of those 32
the lab's default convention lets ride. That cross-tab is the number b124's
decision rests on, and it is the load-bearing claim pinned here.

THE FINDINGS
============
1. THE EXEMPTION IS NOT VACUOUS ON LIVE'S CLOCK: 14 of the 32 wall-old trades
   (44%) took a partial, so the lab's stored convention spares them and live
   would close them. On the bar clock the same census finds 0 old trades — the
   exemption has literally nothing to exempt — which is exactly why b123 and
   b129 could both measure 0.000R honestly and still not answer the question.
2. ALL 14 SPARED TRADES ARE WINNERS (+$235.41 summed, 14/14 pnl > 0), and 10 of
   the 14 are full-close-at-TP1 tickets. So the stored bar's bias from this gap
   is DIRECTIONAL and known: the lab keeps a winner alive past live's limit.
   That is the honest statement of the parity gap — not "0.000R, inert".
3. THE COST IS STILL NOISE: age_only minus no_partial at live's own limit is
   -0.003..0.000R per leg (mean -0.0012R, max |0.003|), one-sided in sign but
   3x UNDER b123's own 0.010R tripwire and 30x under b119's 0.10R ceiling. The
   mechanism is b130's, now confirmed on the gate axis: trade counts are
   IDENTICAL at both gates on all seven legs (0 delta), so the exemption does
   not even free a slot — the cut trade's own pnl is replaced by a comparable
   one, and the R moves by a rounding.
4. THE TRIGGER IS THE TOOLING FINDING: b124's wording is "fires if the
   exemption moves the bar ONE-SIDED **or** past 0.010R". An OR of a sign test
   and a magnitude test means a one-sided 0.003R — a directional nothing —
   satisfies it, and the round would have had to print "RE-BASELINE DECISION"
   for a gap no stored number can see. The corrected shape (pinned below) is a
   CONJUNCTION for the decision and a REPORT of both axes: one_sided AND
   past_tripwire is a re-baseline, one_sided alone is a disclosed bias.
   b129's `one_sided_strict` fixed the DENOMINATOR of the same class of bug;
   this fixes its MAGNITUDE half, which no predicate in this repo checks.
5. DECOMPOSITION, so the next round does not blame the wrong cause: the total
   lab-vs-live time-exit gap splits into clock_part (b130's, mean +0.0018R,
   max 0.007) and gate_part (b124's, mean -0.0012R, max 0.003). The two have
   OPPOSITE signs, and the total is mixed-sign (4 pos / 2 neg) — so the whole
   gap is smaller than either part, which is the arithmetic reason no re-baseline
   is owed.

NOTHING IS WIRED: `engines/backtest.py`'s `time_stop_gate` default is unchanged,
`legacy_guards.MAX_POSITION_AGE_HOURS` is untouched, and a live time-stop retune
stays a human gate (b89 class). The engine gained no dial this round — b130's
`time_stop_hours` and `time_stop_gate` already express every cell measured here.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LEDGER = os.path.join(ROOT, "data", "backtest",
                      "b124_gate_exemption_census.json")
LEDGER_130 = os.path.join(ROOT, "data", "backtest",
                          "b130_wall_clock_parity.json")
B123_TEST = os.path.join(ROOT, "tests",
                         "test_b123_protection_decomposition.py")

if not os.path.exists(LEDGER):
    raise unittest.SkipTest(
        f"{LEDGER} missing — run scripts/b124_gate_exemption_census.py")

L = json.load(open(LEDGER))
L130 = json.load(open(LEDGER_130))
LEGS = L["_legs"]
WINDOWS = tuple(x for x in LEGS if x != "cached")


def _load_producer():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "b124_census", os.path.join(ROOT, "scripts",
                                    "b124_gate_exemption_census.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestB124LedgerShape(unittest.TestCase):
    def test_ledger_carries_both_gates_on_seven_legs(self):
        self.assertEqual(LEGS, L130["_legs"],
                         "b124 must score the SAME seven legs b130 scored, or "
                         "the two clock/gate verdicts are not comparable")
        for leg in LEGS:
            self.assertEqual(set(L[leg]["grid"]), {"no_partial", "age_only"})
            self.assertIn("_census", L[leg])

    def test_the_live_limit_is_imported_not_restated(self):
        # b71/b118's rule: a round that measures live's guard must ASK live.
        from scripts import b124_gate_exemption_census as b124
        from engines.legacy_guards import MAX_POSITION_AGE_HOURS
        self.assertEqual(b124.LIVE_HOURS, float(MAX_POSITION_AGE_HOURS))
        for leg in LEGS:
            self.assertEqual(L[leg]["_live_hours"], b124.LIVE_HOURS,
                             f"{leg}: the run used a different limit than "
                             "live's guard — the census is not live's clock")

    def test_the_gate_names_are_b129s_names_not_new_ones(self):
        # Two ledgers must not mean different things by "the lab convention".
        from scripts import b124_gate_exemption_census as b124
        from scripts import b129_timestop_reprice as b129
        self.assertEqual(b124.LAB_GATE, b129.GATE_LIVE,
                         "b129 calls the stored convention GATE_LIVE; if "
                         "either spelling moved, the two ledgers no longer "
                         "mean the same gate")
        self.assertEqual(b124.LIVE_GATE, "age_only")
        self.assertEqual(b124.INCUMBENT_STOP, b129.INCUMBENT_STOP)


class TestB124ExemptionHasAPopulation(unittest.TestCase):
    """THE POINT OF THE ROUND: the gap is not vacuous on live's clock, and the
    bar-clock ledgers could not see that."""

    def test_b124_the_lab_default_exempts_real_wall_old_trades(self):
        tot_old = sum(L[leg]["_census"]["n_wall_old"] for leg in LEGS)
        tot_ex = sum(L[leg]["_census"]["n_wall_old_exempted"] for leg in LEGS)
        self.assertEqual(tot_old, L["_verdict"]["n_wall_old_trades"])
        self.assertGreater(tot_ex, 0,
                           "the exemption found nothing to exempt on the wall "
                           "clock — either the census broke or the population "
                           "changed; b130 measured 32 old trades")
        self.assertEqual(tot_ex,
                         L["_verdict"]["n_wall_old_exempted_by_lab_default"])
        # and the census must agree with b130's independent count of old trades
        for leg in LEGS:
            self.assertEqual(L[leg]["_census"]["n_wall_old"],
                             L130[leg]["_census"]["n_over_wall"],
                             f"{leg}: two censuses of the same off-run disagree")

    def test_b124_the_bar_clock_exemption_has_nothing_to_exempt(self):
        # The anti-vacuity pair: on the clock b123/b129 measured, the SAME
        # census finds zero. If this ever stops being true, b129's "inert
        # across the grid" needs re-reading, not just b124's number.
        for leg in LEGS:
            self.assertEqual(L[leg]["_census"]["n_bar_old"], 0,
                             f"{leg}: a funnel trade now holds past "
                             "144 bars — b129's inert claim is dead and the "
                             "stored bar needs re-deriving")
            self.assertEqual(L[leg]["_census"]["n_bar_old_exempted"], 0)

    def test_every_exempted_trade_was_still_open_at_live_limit(self):
        # The census is off the NO-EXIT run, so a trade is "old" only if its
        # NATURAL exit came after live's limit — i.e. live really would have cut
        # it. A spared trade that had already closed would be a phantom.
        for leg in LEGS:
            for t in L[leg]["_census"]["exempted_trades"]:
                self.assertGreaterEqual(t["wall_age_h"], L[leg]["_live_hours"])
                self.assertGreater(t["partial_taken"], 0.0)

    def test_the_spared_trades_are_named_not_aggregated(self):
        # b130's rule: a census that feeds a decision lists its rows.
        tot = sum(len(L[leg]["_census"]["exempted_trades"]) for leg in LEGS)
        self.assertEqual(tot, L["_verdict"]["n_wall_old_exempted_by_lab_default"],
                         "the per-leg exempt counts and the listed trades "
                         "disagree — one of them is hand-written")


class TestB124BiasDirection(unittest.TestCase):
    """Finding 2: the gap's SIGN is known even where its size is noise."""

    def test_b124_every_spared_trade_is_a_winner(self):
        v = L["_verdict"]
        self.assertEqual(v["exempt_n_positive"],
                         v["n_wall_old_exempted_by_lab_default"],
                         "the exemption no longer spares only winners — the "
                         "stored bar's bias direction is no longer one way and "
                         "b124's honest statement must be rewritten")
        self.assertGreater(v["exempt_pnl_sum_usd"], 0.0)
        # 10 of 14 are full-close-at-TP1 tickets: the lab lets a share>=1.0
        # ticket reach TP1 past live's limit. That is the b105 parity rule
        # interacting with the exemption, and it is why the count is not 4.
        self.assertEqual(v["n_exempt_full_close_tp1"]
                         + v["n_exempt_runner"],
                         v["n_wall_old_exempted_by_lab_default"])

    def test_b124_the_gate_moves_no_trade_count(self):
        # The mechanism check: if the exemption's cost were a real repricing,
        # the two gates would disagree about how many trades fit the single
        # slot. They do not, on any leg — so the R delta is a substitution, not
        # a harvest, which is exactly why it lands at 0.003R.
        for leg in LEGS:
            g = L[leg]["grid"]
            self.assertEqual(g["no_partial"]["trades"], g["age_only"]["trades"],
                             f"{leg}: the gate now changes the trade count — "
                             "the substitution explanation is wrong, re-read "
                             "this round before quoting its gap")
        self.assertEqual(set(L["_gate_gap_other_metrics"]["trades"].values()),
                         {0})


class TestB124CostIsNoise(unittest.TestCase):
    def test_the_gate_gap_stays_under_b123s_tripwire(self):
        v = L["_neutrality"]["time_exit_exemption_cost_R"]
        self.assertFalse(v["past_tripwire"],
                         "the exemption's cost grew past 0.010R — b124 is no "
                         "longer a documentation item: re-run the stored bar "
                         "and open the re-baseline decision (b120's rule)")
        self.assertLessEqual(v["max_abs_R"], 0.010)
        self.assertLess(v["max_abs_R"], 0.010,
                        "the gap is at the tripwire, not under it")

    def test_the_tripwire_value_is_b123s_not_this_rounds(self):
        # b123's pin (test_b124_the_time_exit_exemption_costs_nothing_on_the_
        # stored_arms) enforces <=0.010R on the BAR clock. This round must use
        # the SAME number on the wall clock, or the two pins certify different
        # thresholds and a future round cannot tell which one moved.
        from scripts import b124_gate_exemption_census as b124
        self.assertEqual(b124.TRIPWIRE_R, 0.010)
        src = open(B123_TEST).read()
        self.assertIn("assertLessEqual(v[\"max_abs_R\"], 0.010", src,
                      "b123's tripwire moved — this round's threshold is now "
                      "an independent invention; re-read both pins together")

    def test_no_stored_metric_moves_more_than_a_rounding(self):
        for metric, rows in L["_gate_gap_other_metrics"].items():
            if metric == "trades":
                continue
            worst = max(abs(v) for v in rows.values())
            self.assertLessEqual(worst, 0.6 if metric == "net_R" else 0.010,
                                 f"{metric}: {rows} — a leg moved more than a "
                                 "rounding, the bar needs re-quoting (b120)")


class TestB124TriggerIsAConjunction(unittest.TestCase):
    """Finding 4 — the TOOLING result. b124's own wording ('one-sided OR past
    0.010R') is satisfied by a one-sided 0.003R, i.e. by a directional nothing.
    The decision must be a CONJUNCTION and both axes must be reported."""

    def test_b124_one_sided_alone_does_not_open_a_rebaseline(self):
        v = L["_verdict"]
        self.assertTrue(v["gate_gap_one_sided"],
                        "the sign is no longer one-sided — the bias-direction "
                        "pin above is stale, re-read the ledger")
        self.assertFalse(v["past_b123_tripwire"])
        self.assertNotIn("RE-BASELINE DECISION", v["decision"],
                         f"a one-sided sub-tripwire gap is being reported as a "
                         f"re-baseline decision ({v['decision']}) — that is the "
                         "OR-trigger bug this pin exists to keep fixed")
        self.assertIn("TRIGGER FIRES ON NOISE", v["decision"])

    def test_b124_the_conjunction_shape_is_pinned_on_synthetic_axes(self):
        # The predicate, not the prose: run the decision function over the four
        # (one_sided, past_tripwire) states and require only the two past-
        # tripwire states to open a decision.
        import ast
        src = open(os.path.join(ROOT, "scripts",
                                "b124_gate_exemption_census.py")).read()
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "verdict")
        self.assertNotIn("or", [ast.unparse(s) for s in
                                ast.walk(fn) if isinstance(s, ast.BoolOp)],
                         "verdict() went back to an OR of the sign and "
                         "magnitude tests")
        ns = {}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "<v>", "exec"),
             {"parity_decomposition": lambda led: {"parts": {}},
              "json": json}, ns)
        decide = ns["verdict"]
        for one_sided, past, want in ((True, True, "RE-BASELINE"),
                                      (False, True, "RE-BASELINE"),
                                      (True, False, "TRIGGER FIRES ON NOISE"),
                                      (False, False, "NO LEVER")):
            led = {
                "_legs": ["cached"], "_live_hours": 36.0,
                "_neutrality": {"time_exit_exemption_cost_R": {
                    "one_sided": one_sided, "past_tripwire": past,
                    "max_abs_R": 0.003, "mean_R": 0.0, "n_nonzero": 3}},
            }
            led["cached"] = {
                "_census": {"n_wall_old": 2, "n_wall_old_exempted": 1,
                            "n_bar_old": 0, "n_bar_old_exempted": 0,
                            "n_exempt_runner": 1,
                            "n_exempt_full_close_tp1": 0,
                            "exempt_pnl_sum": 1.0, "exempt_n_positive": 1}}
            got = decide(led)["decision"]
            self.assertIn(want, got,
                          f"one_sided={one_sided} past={past} -> {got}")


class TestB124Decomposition(unittest.TestCase):
    """Finding 5: the total gap is smaller than either part, because the clock
    (b130) and the gate (b124) pull in OPPOSITE directions."""

    def test_the_two_causes_have_opposite_signs(self):
        parts = L["_parity_decomposition"]["parts"]
        self.assertGreater(parts["clock_part_R"]["mean_R"], 0.0)
        self.assertLess(parts["gate_part_R"]["mean_R"], 0.0)
        tot = parts["total_R"]
        self.assertLess(abs(tot["mean_R"]),
                        max(abs(parts["clock_part_R"]["mean_R"]),
                            abs(parts["gate_part_R"]["mean_R"])),
                        "the parts no longer cancel — if the total exceeds both "
                        "parts, one of the two attributions has moved and the "
                        "stored bar needs re-reading")
        self.assertFalse(tot["one_sided"],
                         "the total gap went one-sided: the cancellation that "
                         "keeps this a documentation item is gone")

    def test_the_decomposition_is_pure_arithmetic_on_two_ledgers(self):
        b124 = _load_producer()
        got = b124.parity_decomposition(L)
        self.assertEqual(got, L["_parity_decomposition"],
                         "the producer's decomposition no longer reproduces "
                         "the shipped ledger (b127: derived blocks must be "
                         "re-executable, not hand-written)")
        for leg in LEGS:
            row = got["per_leg"][leg]
            self.assertAlmostEqual(row["clock_part_R"] + row["gate_part_R"],
                                   row["total_R"], places=3)


class TestB124Integrity(unittest.TestCase):
    def test_every_integrity_claim_holds(self):
        for leg, checks in L["_integrity"].items():
            self.assertTrue(all(checks.values()), f"{leg}: {checks}")

    def test_the_wall_cells_reproduce_b130_exactly(self):
        # b124 must be scoring b130's funnel, not a re-spliced one.
        for leg in LEGS:
            for gate in ("no_partial", "age_only"):
                self.assertEqual(
                    L[leg]["grid"][gate],
                    L130[leg]["grid"][f"{gate}::wall::ts_36h"],
                    f"{leg}/{gate}: b130's wall cell moved — the engine or the "
                    "harness changed under this ledger")

    def test_the_producer_blocks_reproduce_from_the_shipped_ledger(self):
        b124 = _load_producer()
        for fn, key in ((b124.gate_gap, "_gate_gap_R"),
                        (b124.neutrality, "_neutrality"),
                        (b124.verdict, "_verdict")):
            self.assertEqual(fn(L), L[key],
                             f"producer {key} no longer reproduces")


class TestB124NothingIsWired(unittest.TestCase):
    """Standing rule: the autopilot measures, it does not re-wire exits."""

    def test_the_engine_gate_default_is_unchanged(self):
        import ast
        tree = ast.parse(open(os.path.join(ROOT, "engines",
                                           "backtest.py")).read())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "backtest_ohlc")
        defaults = {a.arg: ast.unparse(d) for a, d in
                    zip(fn.args.args[len(fn.args.args)
                                      - len(fn.args.defaults):],
                        fn.args.defaults)}
        self.assertEqual(defaults.get("time_stop_gate"), "'no_partial'",
                         "b124 flipped the lab's default gate — that silently "
                         "re-prices every stored ledger (b120's rule) and is a "
                         "human decision, not an autopilot edit")

    def test_live_guard_and_callers_are_untouched(self):
        lg = open(os.path.join(ROOT, "engines", "legacy_guards.py")).read()
        self.assertIn("MAX_POSITION_AGE_HOURS = 36", lg)
        self.assertNotIn("partial_taken", lg,
                         "live's age guard grew a partial exemption — that is "
                         "the lab's rule leaking into production")

    def test_no_live_module_imports_this_round(self):
        for name in ("hermes_master.py", "hermes_runtime.py",
                     "position_daemon.py", "signal_daemon.py",
                     "engines/backtest.py", "engines/backtest_real.py",
                     "engines/lab_harness.py"):
            src = open(os.path.join(ROOT, name)).read()
            self.assertNotIn("b124_gate_exemption_census", src,
                             f"{name} imports the research round")


class TestB124BacklogContract(unittest.TestCase):
    def test_b124_is_closed_in_the_backlog(self):
        # b114's rule: the pin rides the DONE marker the round must write, so a
        # run that measures and forgets to land the decision goes RED.
        text = open(os.path.join(ROOT, "data", "ops",
                                 "autopilot_backlog.md")).read()
        self.assertIn("- [x] b124", text)
        self.assertNotIn("- [ ] b124", text,
                         "b124 is still open while its ledger ships — either "
                         "close it with the finding or delete the ledger")

    def test_b124s_name_carrier_still_exists_in_b123s_file(self):
        # b123's pin is the BAR-clock half of the same question and must not be
        # deleted now that the wall-clock half exists.
        src = open(B123_TEST).read()
        self.assertIn("test_b124_the_time_exit_exemption_costs_nothing_on_the_"
                      "stored_arms", src.replace("\n", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
