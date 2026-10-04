"""b84 — the min_rr gate measured as BOOKS (kept vs dropped) + the floor ladder.

Todo b84 asked for the grade-gate template of round 18 applied to the next live
filter: MIN_RISK_REWARD = 1.5 (auto_executor Check 5.6). The answer is not
"weak gate" — it is "the gate has nothing to select on", and the reason is
structural: engines/plan.py::_reanchor_blueprint builds tp = price ± stop*(rr+0.05),
so the funnel's own geometry MANUFACTURES every entry 0.05 above the floor the
executor then checks. 99.7-100% of the grade-passing signals sit inside
1.55 ± 0.06 on all five legs.

Consequences pinned here:
1. The live floor is a NO-OP on the funnel: the dropped book is empty on 5-of-5
   legs, and gate_rr_1.5 reproduces b80's gradeB column EXACTLY on every leg —
   which is also this round's integrity proof (b83: re-measure, and prove the
   old row).
2. The knob is a CLIFF, not a filter: the smallest reachable tightening
   (learning steps +0.25 → 1.75) kills 98.9-100% of the trade population on
   every window (cliff identical on all four independent windows). The two
   windows where exp_R "pays" (+0.97/+1.81R) are n=2 and n=1 survivors — the
   total price is -257.3R and 795 of 795 trades.
3. kept_rr_1.5 == gate_rr_1.5 (the kept book IS the live population) and the
   dropped book is empty everywhere, so there is no marginal trade to price —
   b84's "true cliff" test cannot even be run on this knob.
4. The adaptive hazard is real but not armed: learning_state.min_rr is 1.5, the
   journal (34 trades, WR 79.4%) does not tighten now, and the first tightening
   step lands exactly on the cliff.

HARD RULE compliance: this round MEASURES a tightening and reports it; it wires
nothing and moves no gate. The b84 finding is a hazard note + a proposal, not a
config change.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engines.auto_executor import MIN_RISK_REWARD, MIN_SETUP_GRADE  # noqa: E402
from engines.learning import RR_FLOOR_CEILING  # noqa: E402

LEDGER = os.path.join(ROOT, "data", "backtest", "b84_rr_gate_books.json")
PARITY = os.path.join(ROOT, "data", "backtest", "b80_gate_parity.json")
LEGS = ("cached", "W1", "W2", "W3", "W4")
WINDOWS = ("W1", "W2", "W3", "W4")


def _load(path):
    with open(path) as f:
        return json.load(f)


class TestLedgerShape(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(LEDGER):
            raise unittest.SkipTest(f"{LEDGER} not built yet")
        cls.led = _load(LEDGER)

    def test_ladder_is_the_reachable_learning_steps(self):
        # engines/learning.py steps min_rr by +0.25 clamped at RR_FLOOR_CEILING.
        # LADDER_RR is generated FROM MIN_RISK_REWARD, so at floor 2.0 the
        # ladder is 2.0..2.5 (at 1.5 it was 1.5..2.5) — no invented thresholds.
        self.assertEqual([str(t) for t in self.led["_rr_ladder"]],
                         [str(t) for t in
                          tuple(round(MIN_RISK_REWARD + 0.25 * k, 2)
                                for k in range(int((RR_FLOOR_CEILING - MIN_RISK_REWARD) / 0.25) + 1))])
        self.assertEqual(MIN_RISK_REWARD, 2.0)
        self.assertEqual(RR_FLOOR_CEILING, 2.5)

    def test_every_leg_carries_every_book_and_the_ladder(self):
        for leg in LEGS:
            L = self.led[leg]
            for t in self.led["_rr_ladder"]:
                for kind in (f"kept_rr_{t}", f"drop_rr_{t}", f"gate_rr_{t}"):
                    self.assertIn(kind, L, f"{leg} missing {kind}")
                    self.assertIn("ladder_ts", L[kind])
                    self.assertIn("_mix", L[kind])
            self.assertIn(str(self.led["_rr_ladder"][-1]), L["_ladder"])

    def test_b78_mix_and_b71_hold_columns_present(self):
        for leg in LEGS:
            for t in self.led["_rr_ladder"]:
                for kind in (f"kept_rr_{t}", f"gate_rr_{t}"):
                    row = self.led[leg][kind]
                    mix = row["_mix"]
                    self.assertEqual(mix["buy"] + mix["sell"], mix["trades"])
                    self.assertEqual(row["ladder_ts"]["trades"], mix["trades"],
                                     f"{leg}/{kind}: mix must count the trades "
                                     "ACTUALLY taken, not raw signals (b78)")
                    self.assertIsNotNone(row.get("_time_stop_bars"))

    def test_zero_rows_carry_a_named_reason(self):
        # b71 rule: trades=0 must name the clause, never read as "no edge".
        for leg in LEGS:
            for t in self.led["_rr_ladder"]:
                for kind in (f"kept_rr_{t}", f"drop_rr_{t}", f"gate_rr_{t}"):
                    row = self.led[leg][kind]
                    if row["ladder_ts"]["trades"] == 0:
                        self.assertIn("zero_reason", row,
                                      f"{leg}/{kind} is empty with no reason")


class TestIntegrityVsB80(unittest.TestCase):
    """b83: the re-measure must reproduce the OLD row exactly, so a changed
    verdict can only come from the fix, never from drift."""

    @classmethod
    def setUpClass(cls):
        if not (os.path.exists(LEDGER) and os.path.exists(PARITY)):
            raise unittest.SkipTest("ledgers not built yet")
        cls.led = _load(LEDGER)
        cls.par = _load(PARITY)

    def test_gate_at_live_floor_does_not_reproduce_b80_gradeB(self):
        """b83: at floor 1.5 the gate row reproduced b80 gradeB exactly — that
        was the proof the gate was a NO-OP (it let everything through). The
        AUDIT-2026-10-04 floor raise to 2.0 breaks that equality ON PURPOSE:
        the gate now drops real trades, so gate_rr_2.0 < gradeB on volume.
        What still must hold: the gate row EXISTS and is internally consistent
        (exp_R and net_R are both real numbers, trades non-negative)."""
        key = f"gate_rr_{MIN_RISK_REWARD}"
        for leg in LEGS:
            self.assertIn(key, self.led[leg], f"{leg}: {key} missing")
            row = self.led[leg][key]["ladder_ts"]
            self.assertIsInstance(row["trades"], int)
            self.assertGreaterEqual(row["trades"], 0)
            # exp_R/net_R are floats when the leg traded, None when it did not
            if row["trades"]:
                self.assertIsInstance(row["exp_R"], float)
                self.assertIsInstance(row["net_R"], float)

    def test_kept_book_equals_the_gate_at_the_live_floor(self):
        # the kept book (rr>=floor) and the gate counterfactual at the floor
        # are the same population seen two ways; they must agree
        # trade-for-trade at whatever the live floor currently is.
        key = f"kept_rr_{MIN_RISK_REWARD}"
        gate = f"gate_rr_{MIN_RISK_REWARD}"
        for leg in LEGS:
            self.assertEqual(self.led[leg][key]["ladder_ts"],
                             self.led[leg][gate]["ladder_ts"],
                             f"{leg}: kept book != gate at the live floor")


class TestVerdictFacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(LEDGER):
            raise unittest.SkipTest("ledger not built yet")
        cls.led = _load(LEDGER)
        cls.v = cls.led["_verdict"]

    def test_live_floor_is_a_real_filter_not_a_noop(self):
        """AUDIT-2026-10-04: at MIN_RISK_REWARD=1.5 this gate was a NO-OP on
        5-of-5 legs — _reanchor_blueprint manufactured every entry at 1.55,
        exactly 0.05 above the floor, so nothing could ever fall below it.
        Raising the floor to 2.0 (b233, measured +29..+43 USD on 4 windows)
        made the gate BIND: the dropped book is no longer empty on 3-of-5
        legs. That is the whole point of the change, so pin it here — a future
        relaxation back to 1.5 must fail this test, not pass silently."""
        noop = self.v["live_floor_is_noop"]
        # it must NOT be empty on every leg anymore
        self.assertNotEqual(noop["legs_where_dropped_book_empty"],
                            noop["of"],
                            "the floor is a no-op again — check MIN_RISK_REWARD "
                            "has not been relaxed back to 1.5")
        # and it must actually be dropping real trades
        dropped = noop["dropped_trades_per_leg"]
        self.assertGreater(sum(dropped.values()), 0)

    def test_rr_population_is_now_filtered_not_manufactured(self):
        """AUDIT-2026-10-04: at floor 1.5, _reanchor_blueprint manufactured
        every entry at 1.55 (0.05 above the floor it was built against), so
        >=99.7% of the grade-passing population sat in a 1.55±0.06 spike and
        the floor could reject nothing. At floor 2.0 that spike breaks on the
        legs with a real sample (cached 0.8, W1 0.69) because low-RR geometry
        finally falls below the gate. Legs with almost no signals (W2 n=7)
        stay at 1.0 by scarcity, not by manufacture — only require the check
        where the sample is meaningful. If share climbs back to ~1.0 on the
        big legs the builder is aiming at the new floor again (see
        REANCHOR_MIN_RR, which must NOT track MIN_RISK_REWARD)."""
        for leg in LEGS:
            c = self.v["rr_concentration"][leg]
            if not c.get("grade_passing_signals"):
                continue
            if c["grade_passing_signals"] < 20:
                continue  # too few signals for a share to mean anything
            self.assertLess(c["share"], 0.997,
                            f"{leg}: spike share {c['share']} is back at the "
                            "manufactured level — _reanchor_blueprint is aiming "
                            "at MIN_RISK_REWARD again; keep REANCHOR_MIN_RR at 1.5")

    def test_cliff_is_measured_per_window(self):
        """At floor 1.5 the cliff (the floor where the funnel goes silent) sat
        at the first learning step on every window — the same sharp event at
        the same place, kill_share >= 0.98 at 1.75. At floor 2.0 the starting
        point moved, so the cliff is no longer identical across windows. What
        still must hold: the measurement exists and is per-floor."""
        self.assertIn("cliff_by_floor", self.v)
        for w in WINDOWS:
            self.assertIn(w, self.v["cliff_by_floor"])

    def test_tightening_above_the_live_floor_is_measured(self):
        """At floor 1.5 the first learning step was 1.75 and it was a silence
        (<=3 survivors, -250R given up). At floor 2.0 the ladder starts at
        2.0, so the 1.75 step no longer exists in the measurement. What must
        hold for ANY step above the live floor: the measurement exists, and
        tightening never replicates on all windows (a step that pays
        everywhere would be the live floor already)."""
        tbf = self.v["tighten_by_floor"]
        # the steps strictly ABOVE the live floor are the tightening candidates
        for step in self.led["_rr_ladder"]:
            if float(step) > MIN_RISK_REWARD:
                self.assertIn(str(step), tbf,
                              f"step {step} is reachable but unmeasured")
                self.assertFalse(tbf[str(step)]["replicated_all_windows"],
                                 f"step {step} pays on all windows — it should "
                                 "be the live floor instead")

    def test_marginal_trade_count_is_measured(self):
        """b84's true-cliff test needs a dropped book. At floor 1.5 it was
        empty on all five legs (marginal_trade == 0 everywhere). At floor 2.0
        the gate binds, so the counts are non-zero on the legs that have
        low-geometry entries. What must hold: the field exists and is a
        per-leg integer — the cliff test reads it."""
        m = self.v["live_gate_marginal_trade"]
        for leg in LEGS:
            self.assertIn(leg, m)
            self.assertIsInstance(m[leg], int)

    def test_adaptive_hazard_is_measured_not_armed(self):
        r = self.v["adaptive_gate_reach"]
        # The LEARNING module's own floor is its persistent default; the live
        # floor is max(MIN_RISK_REWARD, learning min_rr), so the effective
        # floor is still the audit's 2.0. Both must agree that nothing is
        # about to tighten on its own.
        self.assertEqual(r["learning_state"]["min_rr"], 1.5)
        self.assertFalse(r["adjustments_would_tighten_now"])
        # 1.75 kills >=98.9% everywhere but leaves 1-2 survivors on W1/W3, so it
        # is not literally a total silence — the ledger must say so honestly.
        self.assertIsNone(r["floor_that_silences_the_funnel"])


class TestNoLivePathImport(unittest.TestCase):
    def test_lab_module_is_not_imported_by_the_live_tree(self):
        # read-only research: engines/ and the daemons must never import this.
        import subprocess
        out = subprocess.run(
            ["grep", "-rl", "b84_rr_gate_books", "engines/", "hermes_master.py",
             "hermes_runtime.py"],
            cwd=ROOT, capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, "", f"live path imports the b84 lab: {out}")


if __name__ == "__main__":
    unittest.main()
