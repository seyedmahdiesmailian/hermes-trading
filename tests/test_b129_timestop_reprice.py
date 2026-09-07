"""b129 — THE b57 TIME-STOP GRID, RE-PRICED ON THE CORRECTED ENGINE.

The founding rule this round executes is b119's (generalising b83): "when an
engine fix deletes a POPULATION rather than shifting a number, every stored
decision whose evidence was measured ON that population must be re-priced".
b117 re-priced b65's trail, b119 re-priced b66/b66b's share/TP1 grids, and
b119's own note named the remaining suspect: "b56/b57/b61's arms". b57 is the
one that decides a LIVE GUARD VALUE — the 36h MAX_POSITION_AGE_HOURS — and its
ledger (data/backtest/ab_b57_timestop.json, 2026-08-31) was scored on 6500 M5
bars through an engine that has since lost the phantom runner (b105), gained the
grade gate (b80), gained the live-parity ladder (b109/b118) and revealed the
time-exit/runner coupling (b123).

WHAT THE SHIPPED LEDGER SAYS (every number below is read out of
data/backtest/b129_timestop_reprice.json by these tests, not restated):

1. THE 36h EXIT IS INERT ON THE FUNNEL'S OWN TRADES. ts_0 (no exit at all)
   differs from the incumbent ts_144 by exactly 0.000R on all seven legs, and
   holds_over_time_exit is 0 everywhere (max hold 49..112 bars vs the 144-bar
   exit). So the guard has never bound in ~33,000 bars of live-parity replay.
   That is NOT an argument to delete it — it is a stuck-position safety net, and
   the lab measures BAR age while live measures WALL-CLK age (the weekend gap
   makes those different rules; filed as b130).
   Anti-vacuity, pinned: the same grid DOES bite at 96 bars on W4 (+0.006R), so
   the zeros are a property of the population, not of the code.
2. TIGHTENING IS ONE-SIDEDLY WORSE. A 2h exit (ts_8) loses to the incumbent on
   5 of 6 real windows (-0.057..-0.024R, mean -0.030R) — the direction of b57's
   original conclusion ("do not time-stop aggressively") survives the engine fix.
3. ts_48 (12h) is the only arm flagged one-sidedly BETTER, and it is worth
   +0.002R/trade mean, max 0.009R — an order of magnitude under b119's 0.10R
   decision ceiling. No lever.
4. THE RUNNER EXEMPTION IS INERT ACROSS THE WHOLE GRID, not just at 144: the
   two gates never disagree about where the optimum sits and the largest
   age_only-minus-no_partial gap anywhere is 0.006R. That extends b123's
   finding #4 from one arm to fourteen.

WHAT THIS ROUND ALSO FOUND ABOUT THE MEASUREMENT TOOLING (b130's carrier):
b123's `one_sided()` — a >=3/4 majority with at most one dissent — is correct
for a grid whose deltas are all non-zero, but on a grid where most arms are
INERT (delta exactly 0.000) it counts only the non-zero legs, so a single
non-zero observation (1 positive, 0 negative) passes the bar. ts_96 is flagged
"one_sided" on exactly that: five zeros and one +0.006. b123's own shipped
flags are untouched (b127 reproduces them; editing the predicate would break
the frozen ledger), so the corrected predicate lives HERE as `unanimous()` and
is pinned in both directions.

NOTHING IS WIRED. engines/legacy_guards.py and engines/backtest.py are
untouched; a live time-stop retune is an exit-behaviour change = human gate
(b89 class).
"""
from __future__ import annotations

import importlib.util
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "data", "backtest", "b129_timestop_reprice.json")
STEP1 = os.path.join(ROOT, "data", "backtest",
                     "b121_flat_share_replication.json")
STEP3 = os.path.join(ROOT, "data", "backtest",
                     "b123_protection_share_decomposition.json")


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "b129_timestop_reprice",
        os.path.join(ROOT, "scripts", "b129_timestop_reprice.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _led():
    with open(LEDGER) as fh:
        return json.load(fh)


class TestB129LedgerIsHonest(unittest.TestCase):
    """The round's own preconditions: right bars, right incumbent, right units."""

    def test_b129_ledger_exists_with_all_seven_legs_and_both_gates(self):
        led = _led()
        for leg in ("cached", "W1", "W2", "W3", "W4", "W5", "W6"):
            self.assertIn(leg, led, f"{leg} missing from the b129 ledger")
            self.assertEqual(len(led[leg]["grid"]), 14,
                             "7 stops x 2 gates = 14 arms per leg")

    def test_the_incumbent_is_the_derived_live_stop_not_a_literal(self):
        """144 must equal lh.live_time_stop_bars on every leg, or the incumbent
        column is not live's guard (b71's derive-don't-hardcode rule)."""
        led = _led()
        for leg, row in led["_live_stop_check"].items():
            self.assertTrue(row["equal"], f"{leg}: {row}")
            self.assertEqual(row["pinned_incumbent"], 144)

    def test_b129_incumbent_reproduces_the_frozen_b121_and_b123_rows(self):
        """Cross-ledger integrity: the ts_144 @ no_partial cell must be the
        SAME TRADE b121 and b123 froze, or this round spliced two funnels."""
        led, s1, s3 = _led(), json.load(open(STEP1)), json.load(open(STEP3))
        checks = led["_integrity"]
        for leg in led["_integrity"]:
            self.assertTrue(all(checks[leg].values()),
                            f"{leg} incumbent does not reproduce: {checks[leg]}")
            inc = led[leg]["grid"]["no_partial::ts_144"]
            self.assertEqual(inc, s1[leg]["share_grid"]["incumbent_live_grade_fn"])
            self.assertEqual(inc, s3[leg]["grid"]["no_partial::partial::live_grade_share"])

    def test_the_producer_reproduces_the_shipped_verdict(self):
        """b127's discipline: execute the shipped derivation, do not just read
        its JSON. verdict() is pure arithmetic on the ledger."""
        mod, led = _load_script(), _led()
        self.assertEqual(mod.verdict(led), led["_verdict"])
        self.assertEqual(mod.neutrality(led), led["_neutrality"])
        self.assertEqual(mod.gate_gap(led), led["_gate_gap"])
        self.assertEqual(mod.best_per_gate(led), led["_best_per_gate"])


class TestB129TheLiveExitIsInert(unittest.TestCase):
    """Finding 1: the 36h guard has never bound on the funnel's own trades."""

    def test_no_time_stop_at_all_costs_nothing_vs_the_live_36h_exit(self):
        led = _led()
        for leg in ("cached", "W1", "W2", "W3", "W4", "W5", "W6"):
            d = led["_delta_exp_R"]["no_partial::ts_0"][leg]
            self.assertEqual(d, 0.0, f"{leg}: removing the exit moved exp_R by {d}")
            self.assertEqual(led[leg]["grid"]["no_partial::ts_144"]
                             ["holds_over_time_exit"], 0, leg)

    def test_anti_vacuity_the_same_grid_DOES_bite_when_it_is_short_enough(self):
        """Without this, finding 1 could be read as 'time_stop_bars is dead
        code'. It is not: at 96 bars W4 moves, and at 8 bars everything moves."""
        led = _led()
        self.assertNotEqual(led["_delta_exp_R"]["no_partial::ts_96"]["W4"], 0.0)
        bites = sum(1 for leg in ("W1", "W2", "W3", "W4", "W5", "W6")
                    if led["_delta_exp_R"]["no_partial::ts_8"][leg] != 0.0)
        self.assertGreaterEqual(bites, 5, "ts_8 must be a live constraint")

    def test_b129_tightening_the_exit_is_one_sidedly_worse_and_stays_worse(self):
        """b57's direction survives the engine fix: a 2h stop loses on 5 of 6
        real windows. Pinned as a DIRECTION, so a future funnel whose holds
        lengthen re-runs this instead of re-quoting b57."""
        led = _led()
        neu = led["_neutrality"]["no_partial::ts_8"]
        self.assertGreaterEqual(neu["negative"], 5)
        self.assertLess(neu["mean_R"], -0.02)
        self.assertTrue(neu["one_sided"])
        self.assertTrue(neu["fresh_all_same_sign"],
                        "the fresh pair must agree — b121's replication rule")

    def test_the_only_one_sided_winner_is_noise_level_not_a_lever(self):
        """ts_48 flags one-sided at +0.002R mean / 0.009R max — under b119's
        0.10R magnitude ceiling by ~10x. If a future round moves it above the
        ceiling this pin fires and the 36h becomes a real decision."""
        led = _led()
        neu = led["_neutrality"]["no_partial::ts_48"]
        self.assertTrue(neu["one_sided"])
        self.assertLess(neu["max_abs_R"], 0.010)
        self.assertLess(abs(neu["mean_R"]), 0.010)


class TestB130OneSidedNeedsNonZeroEvidence(unittest.TestCase):
    """The tooling finding: b123's `one_sided()` is vacuous on an INERT grid.

    b123 fixed the n=7 tautology (>=3 of 7 is satisfied by every split) by
    requiring a >=3/4 majority with <=1 dissent. That is right when every leg
    produced a non-zero delta. On a time-stop grid most arms are byte-identical
    to the incumbent, so `neutrality()` filters the Nones and counts only the
    non-zeros — and a single +0.006 with five exact zeros passes as unanimous.
    ts_96 is flagged one_sided on precisely that shape.
    """

    def test_b130_a_single_non_zero_leg_is_not_one_sided_evidence(self):
        mod = _load_script()
        # b123's shipped predicate: 1-vs-0 passes (the vacuity, pinned so the
        # defect cannot be re-discovered as a discovery).
        self.assertTrue(mod.one_sided(1, 0))
        # the corrected predicate: unanimity needs enough non-zero legs to have
        # been able to disagree.
        self.assertFalse(mod.one_sided_strict(1, 0, n_legs=6))
        self.assertFalse(mod.one_sided_strict(2, 0, n_legs=6))  # below the floor
        self.assertTrue(mod.one_sided_strict(3, 0, n_legs=6))   # at the floor
        self.assertTrue(mod.one_sided_strict(6, 0, n_legs=6))
        self.assertFalse(mod.one_sided_strict(4, 2, n_legs=6))

    def test_ts_96_is_flagged_by_the_loose_rule_and_rejected_by_the_strict_one(self):
        led = _led()
        self.assertTrue(led["_neutrality"]["no_partial::ts_96"]["one_sided"])
        self.assertFalse(led["_neutrality"]["no_partial::ts_96"]["unanimous"],
                         "five zeros + one 0.006R is not a replicated effect")
        # and the two arms that DO have real evidence keep their flags:
        self.assertTrue(led["_neutrality"]["no_partial::ts_8"]["unanimous"])
        self.assertTrue(led["_neutrality"]["no_partial::ts_48"]["unanimous"])


class TestB129GateParity(unittest.TestCase):
    """Finding 4: b123's exemption-inertness extends across the whole grid."""

    def test_the_two_time_exit_gates_never_disagree_on_the_optimum(self):
        led = _led()
        self.assertEqual(led["_verdict"]["gates_disagree_on_best_ts"], [])
        np_best = led["_best_per_gate"]["no_partial"]
        ao_best = led["_best_per_gate"]["age_only"]
        for leg in ("cached", "W1", "W2", "W3", "W4", "W5", "W6"):
            self.assertEqual(np_best[leg]["best_ts"], ao_best[leg]["best_ts"], leg)

    def test_the_runner_exemption_costs_nothing_anywhere_on_this_grid(self):
        """b124's parity gap, measured at every stop instead of only at the
        live 144: max |age_only - no_partial| <= 0.010R across 7 legs x 7 Ns."""
        led = _led()
        vals = [v for row in led["_gate_gap"].values() for v in row.values()
                if v is not None]
        self.assertGreater(len(vals), 40)
        self.assertLessEqual(max(abs(v) for v in vals), 0.010)


class TestB129NothingIsWired(unittest.TestCase):
    """The standing rule: this round measures, it does not re-wire exits."""

    def test_the_live_guard_value_and_engine_defaults_are_untouched(self):
        from engines.legacy_guards import MAX_POSITION_AGE_HOURS
        import inspect
        from engines.backtest import backtest_ohlc
        self.assertEqual(MAX_POSITION_AGE_HOURS, 36)
        sig = inspect.signature(backtest_ohlc)
        self.assertEqual(sig.parameters["time_stop_bars"].default, 0)
        self.assertEqual(sig.parameters["time_stop_gate"].default, "no_partial")

    def test_no_live_module_imports_this_round(self):
        """b114/b121's unwired-state carrier: the live path must not reach the
        lab. Rides b129 so the item has a name in the suite (b102)."""
        live_files = ["hermes_master.py", "hermes_runtime.py",
                      "position_daemon.py", "signal_daemon.py"]
        for f in live_files:
            p = os.path.join(ROOT, f)
            if not os.path.exists(p):
                continue
            self.assertNotIn("b129_timestop", open(p).read(),
                             f"{f} imports the b129 lab round")


if __name__ == "__main__":
    unittest.main()
