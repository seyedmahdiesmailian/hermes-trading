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
        # engines/learning.py steps min_rr by +0.25 clamped at RR_FLOOR_CEILING,
        # so the ladder must be exactly 1.5..2.5 — no invented thresholds.
        self.assertEqual([str(t) for t in self.led["_rr_ladder"]],
                         ["1.5", "1.75", "2.0", "2.25", "2.5"])
        self.assertEqual(MIN_RISK_REWARD, 1.5)
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

    def test_gate_at_live_floor_reproduces_b80_gradeB(self):
        key = f"gate_rr_{MIN_RISK_REWARD}"
        for leg in LEGS:
            mine = self.led[leg][key]["ladder_ts"]
            theirs = self.par["legs"][leg]["gradeB"]
            for col in ("trades", "exp_R", "net_R", "maxDD_R"):
                self.assertEqual(mine[col], theirs[col],
                                 f"{leg}: b84 {key} {col}={mine[col]} != b80 "
                                 f"gradeB {theirs[col]} — harness drift")

    def test_kept_book_equals_the_gate_at_the_live_floor(self):
        # the kept book (rr>=1.5) and the gate counterfactual at 1.5 are the same
        # population seen two ways; they must agree trade-for-trade.
        for leg in LEGS:
            self.assertEqual(self.led[leg]["kept_rr_1.5"]["ladder_ts"],
                             self.led[leg]["gate_rr_1.5"]["ladder_ts"],
                             f"{leg}: kept book != gate at the live floor")


class TestVerdictFacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(LEDGER):
            raise unittest.SkipTest("ledger not built yet")
        cls.led = _load(LEDGER)
        cls.v = cls.led["_verdict"]

    def test_live_floor_is_a_noop_on_every_leg(self):
        self.assertEqual(self.v["live_floor_is_noop"]["legs_where_dropped_book_empty"],
                         self.v["live_floor_is_noop"]["of"])
        self.assertTrue(all(x == 0 for x in
                            self.v["live_floor_is_noop"]["dropped_trades_per_leg"].values()))

    def test_rr_is_a_manufactured_spike_not_a_spread(self):
        # >=99.7% of the grade-passing population sits inside 1.55±0.06 on every
        # leg — the floor is a target the builder aims at, not a filter.
        for leg in LEGS:
            c = self.v["rr_concentration"][leg]
            self.assertGreaterEqual(c["share"], 0.997,
                                    f"{leg}: spike share {c['share']} — if this "
                                    "drops, _reanchor_blueprint's padding changed")
            self.assertLess(c["rr_min"], 1.56)
            self.assertGreaterEqual(c["rr_median"], 1.549)

    def test_cliff_is_at_the_first_learning_step_on_all_windows(self):
        self.assertTrue(self.v["cliff_identical_on_all_windows"])
        for w in WINDOWS:
            self.assertEqual(self.v["cliff_by_floor"][w]["cliff_floor"], 1.75,
                             f"{w}: cliff moved — re-read the tightening hazard")
            self.assertGreaterEqual(
                self.v["cliff_by_floor"][w]["kill_share_by_floor"]["1.75"], 0.98)

    def test_tightening_to_1_75_is_a_silence_not_a_selection(self):
        t = self.v["tighten_by_floor"]["1.75"]
        # the two "paying" windows are n<=2 survivors; the honest read is volume.
        self.assertLessEqual(t["total_trades_left"], 3)
        self.assertLess(t["total_net_R_given_up"], -250.0)
        self.assertFalse(t["replicated_all_windows"])
        for row in t["per_window"]:
            if row["pays"]:
                self.assertLessEqual(row["gate_trades"], 2,
                                     "an exp_R 'win' on n>2 at this floor would "
                                     "mean the population is no longer a spike")

    def test_no_marginal_trade_exists_for_this_gate(self):
        # b84's true-cliff test needs a dropped book; here it is empty on all
        # five legs, so the gate cannot be judged on selection at all.
        self.assertTrue(all(x == 0 for x in
                            self.v["live_gate_marginal_trade"].values()))

    def test_adaptive_hazard_is_measured_not_armed(self):
        r = self.v["adaptive_gate_reach"]
        self.assertEqual(r["learning_state"]["min_rr"], MIN_RISK_REWARD)
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
