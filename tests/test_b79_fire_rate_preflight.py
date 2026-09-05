"""b79 — the GATE FIRE-RATE STABILITY PRE-FLIGHT must be a real gate, not a
report.

Why this exists (todo b79, from b68 round 16): the weekly-runway gate's pass
rate swung 36%-68% across the four independent windows and its median
room-to-weekly-extreme flipped sign (+6.46 ATR on W1 to -0.79 ATR on W4) —
the oracle's fire rate is ITSELF regime-gifted, so no selection built on it
can be regime-independent. Round 16 spent its four-window ladder measurement
to learn what a 5-line probe on the shipped data already knew.

Round 17's calibration is the other half of the rule and this suite pins it
too: the H4 trend gate is the loop's MOST STABLE fire rate (swing 2.9 pts)
and its arm STILL failed the merit bar 1-of-4 windows. b79 is therefore
NECESSARY-not-sufficient — UNSTABLE stops a round, STABLE only permits one;
b74's lift-vs-control test stays the binding check.

Pins, in order of what would rot first:

1. THE SHIPPED PRE-FLIGHT JSON: round 16's runway gate is UNSTABLE (swing
   > 20 pts AND median-age sign flip), round 17's H4 gate is STABLE, and
   round 12's two-window ledger is INSUFFICIENT — the b77 lesson (a 2-point
   line is not a curve) must apply to fire rates too.
2. THE COUNTERFACTUAL: on the data round 16 had already shipped, the rule
   closes the runway gate on the probe alone (would_have_closed_on_probe_alone).
3. THE DISSOCIATION (necessary-not-sufficient): the STABLE round-17 oracle's
   arm still fails b74's all-windows replication in the SAME shipped ledger
   — a test that would pass if someone "fixed" b79 into a promotion rule.
4. The script REPRODUCES the shipped JSON byte-for-byte from the ledgers
   (b48 seam redirects state, never code).
5. pass_rate() handles every probe shape the loop has shipped and returns
   None (never a fake 0.0) on unknown shapes; count rates (signals/week)
   are swung RELATIVE to the mean, probability rates in percentage points.
6. fire_rate_verdict's three verdicts on synthetic series, both directions,
   including the median-age sign flip firing UNSTABLE on a small swing.
7. The three wired confirm scripts (b68o/p/q) + the round-14 draw script
   compute _b79_preflight in main() — AST-pinned, so the wiring cannot be
   quietly dropped from the loop's tooling.
8. READ-ONLY ISOLATION: no live-path module imports lab_fire_rate.
"""
import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engines import lab_fire_rate as lf  # noqa: E402

PREFLIGHT = os.path.join(ROOT, "data", "backtest",
                         "b79_fire_rate_preflight.json")
BT = os.path.join(ROOT, "data", "backtest")
FOUR = ["W1", "W2", "W3", "W4"]


def _load(path):
    with open(path) as f:
        return json.load(f)


class TestShippedPreflight(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _load(PREFLIGHT)

    def test_chrono_order_is_oldest_first_not_label_order(self):
        # W1 is the NEWEST window; every series in the artefact must be
        # ordered by timestamp (b77 rule), never by label.
        for tag, row in self.p["ledgers"].items():
            if "b68m" in tag:
                continue   # two-window ledger, asserted separately below
            self.assertEqual(row["_chrono_order_oldest_first"],
                             ["W4", "W3", "W2", "W1"], tag)
        self.assertEqual(
            self.p["ledgers"]["b68m_htf_pdh_confirm:h1"]["_chrono_order_oldest_first"],
            ["W2", "W1"])
        self.assertEqual(
            self.p["ledgers"]["b68m_htf_pdh_confirm:h4"]["_chrono_order_oldest_first"],
            ["W2", "W1"])

    def test_round16_runway_gate_is_unstable_on_both_clauses(self):
        row = self.p["ledgers"]["b68p_runway_confirm"]
        self.assertEqual(row["verdict"], "UNSTABLE")
        self.assertGreater(row["swing_points"], lf.SWING_FAIL_POINTS)
        self.assertTrue(row["median_age_sign_flip"])
        # the shipped numbers round 16's Findings quoted: 36%-68%
        self.assertAlmostEqual(row["min_rate"], 0.362, places=3)
        self.assertAlmostEqual(row["max_rate"], 0.676, places=3)

    def test_round17_h4_gate_is_stable(self):
        row = self.p["ledgers"]["b68q_nr7htf_confirm"]
        self.assertEqual(row["verdict"], "STABLE")
        self.assertLessEqual(row["swing_points"], lf.SWING_FAIL_POINTS)
        self.assertFalse(row["median_age_sign_flip"])

    def test_round12_two_windows_are_insufficient_not_a_curve(self):
        # b68m shipped only W1/W2 — two points cannot show a swing, for
        # either of its nested oracles (h1 and h4 trend gates).
        for oracle in ("h1", "h4"):
            row = self.p["ledgers"][f"b68m_htf_pdh_confirm:{oracle}"]
            self.assertEqual(row["verdict"], "INSUFFICIENT", oracle)

    def test_round15_geometry_rate_is_unstable_on_relative_swing(self):
        # signals/week is a COUNT rate: 4.0→5.17 breaks/week is a 25% swing
        # relative to the mean, and percentage points would be meaningless.
        row = self.p["ledgers"]["b68o_weekly_confirm"]
        self.assertEqual(row["verdict"], "UNSTABLE")
        self.assertIn("relative", row["swing_basis"])
        self.assertGreater(row["swing_points"], lf.SWING_FAIL_POINTS)

    def test_round14_both_h4_oracles_stable_but_funnel_gate_looser(self):
        pdh = self.p["ledgers"]["b68n4_fourth_draw:h4_pdh"]
        fun = self.p["ledgers"]["b68n4_fourth_draw:h4_funnel"]
        self.assertEqual(pdh["verdict"], "STABLE")
        self.assertEqual(fun["verdict"], "STABLE")
        self.assertLess(pdh["swing_points"], fun["swing_points"])

    def test_verdicts_discriminate_not_constant(self):
        # Anti-vacuity: if every ledger got the same stamp the rule is a
        # constant function wearing a name.
        vs = {k: v["verdict"] for k, v in self.p["ledgers"].items()}
        self.assertGreaterEqual(len(set(vs.values())), 3)

    def test_headline_counterfactual_round16_closed_on_probe_alone(self):
        h = self.p["_headline"]
        self.assertIs(h["round16_would_have_closed_on_probe_alone"], True)
        self.assertEqual(h["round16_runway_gate_verdict"], "UNSTABLE")

    def test_headline_dissociation_stable_gate_still_failed_merit_bar(self):
        # THE necessary-not-sufficient proof, computed from the shipped
        # round-17 ledger: b79 says STABLE, b74's all-windows rule says NO.
        h = self.p["_headline"]
        self.assertEqual(h["round17_h4_gate_verdict"], "STABLE")
        q = _load(os.path.join(BT, "b68q_nr7htf_confirm.json"))
        self.assertIs(q["_verdict"]["replicated_in_all"]["nr7_h4t_agree"],
                      False)
        wins = q["_verdict"]
        beats = sum(1 for w in FOUR
                    if wins[w]["nr7_h4t_agree"]["beats_funnel"])
        self.assertLess(beats, len(FOUR))   # the arm lost at least one window


class TestReproducesFromLedgers(unittest.TestCase):
    def test_script_regenerates_the_shipped_json_exactly(self):
        # The ledger is a computed artefact, not a hand-typed one. Run the
        # script against a redirected OUT (b48: the seam redirects STATE,
        # never code) and require byte equality with what is committed.
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "preflight.json")
            env = dict(os.environ, B79_PREFLIGHT_OUT=out)
            r = subprocess.run([sys.executable,
                                os.path.join(ROOT, "scripts",
                                             "b79_fire_rate_preflight.py")],
                               capture_output=True, text=True, env=env,
                               cwd=ROOT, timeout=180)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            self.assertEqual(_load(out), _load(PREFLIGHT))


class TestPassRateExtraction(unittest.TestCase):
    def test_gate_share_shape(self):
        rate, kind = lf.pass_rate({"gate_share": 0.451, "cut_share": 0.42})
        self.assertEqual((rate, kind), (0.451, "gate_share"))

    def test_runway_shape_kept_over_fireable(self):
        p = {"pdh_signals": 125, "no_week_level": 14,
             "runway_buy": 35, "runway_sell": 40}
        rate, kind = lf.pass_rate(p)
        self.assertEqual(kind, "runway")
        self.assertAlmostEqual(rate, 75 / 111, places=6)

    def test_geometry_count_shape(self):
        rate, kind = lf.pass_rate({"signals": 52, "weeks_with_level": 12})
        self.assertEqual(kind, "signals_per_week")
        self.assertAlmostEqual(rate, 52 / 12, places=6)

    def test_unknown_shape_returns_none_never_fake_zero(self):
        rate, why = lf.pass_rate({"bars": 6000, "something": 1})
        self.assertIsNone(rate)
        self.assertIn("unrecognised", why)

    def test_zero_denominators_return_none_not_divide_error(self):
        self.assertIsNone(lf.pass_rate({"pdh_signals": 10, "no_week_level": 10,
                                        "runway_buy": 0, "runway_sell": 0})[0])
        self.assertIsNone(lf.pass_rate({"signals": 3,
                                        "weeks_with_level": 0})[0])

    def test_bools_are_not_numbers(self):
        # a probe that stores gate_share=True must not read as rate 1.0
        self.assertIsNone(lf.pass_rate({"gate_share": True})[0])


class TestFireRateVerdictRule(unittest.TestCase):
    def _s(self, rates, kind="gate_share"):
        return {f"W{i}": {"rate": r, "kind": kind}
                for i, r in enumerate(rates, 1)}

    def _v(self, rates, kind="gate_share"):
        order = [f"W{i}" for i in range(1, len(rates) + 1)]
        return lf.fire_rate_verdict(self._s(rates, kind), order)

    def test_small_swing_is_stable(self):
        v = self._v([0.433, 0.451, 0.461, 0.462])
        self.assertEqual(v["verdict"], "STABLE")
        self.assertLessEqual(v["swing_points"], lf.SWING_FAIL_POINTS)

    def test_big_swing_is_unstable(self):
        v = self._v([0.362, 0.628, 0.491, 0.676])
        self.assertEqual(v["verdict"], "UNSTABLE")
        self.assertGreater(v["swing_points"], lf.SWING_FAIL_POINTS)

    def test_median_age_sign_flip_kills_even_a_small_swing(self):
        s = self._s([0.50, 0.51, 0.52])
        for i, age in zip(("W1", "W2", "W3"), (6.46, 0.81, -0.79)):
            s[i]["median_age"] = age
            s[i]["median_age_field"] = "room_median"
        v = lf.fire_rate_verdict(s, ["W1", "W2", "W3"])
        self.assertEqual(v["verdict"], "UNSTABLE")
        self.assertTrue(v["median_age_sign_flip"])
        self.assertLess(v["swing_points"], lf.SWING_FAIL_POINTS)

    def test_missing_age_on_one_leg_disables_the_flip_clause(self):
        # an age field present on only SOME legs must not be guessed into a
        # flip (None is not a datapoint — b77's None-margin lesson).
        s = self._s([0.50, 0.51, 0.52])
        s["W1"]["median_age"], s["W1"]["median_age_field"] = 6.0, "room_median"
        s["W2"]["median_age"], s["W2"]["median_age_field"] = -6.0, "room_median"
        v = lf.fire_rate_verdict(s, ["W1", "W2", "W3"])
        self.assertFalse(v["median_age_sign_flip"])
        self.assertEqual(v["verdict"], "STABLE")

    def test_count_rate_swing_is_relative_not_percentage_points(self):
        v = self._v([4.0, 5.17, 4.33, 4.92], kind="signals_per_week")
        self.assertIn("relative", v["swing_basis"])
        self.assertEqual(v["verdict"], "UNSTABLE")   # 25% of the mean

    def test_two_legs_are_insufficient(self):
        v = self._v([0.36, 0.68])
        self.assertEqual(v["verdict"], "INSUFFICIENT")

    def test_preflight_reads_meta_from_the_ledgers_own_last_stamps(self):
        led = _load(os.path.join(BT, "b68q_nr7htf_confirm.json"))
        v = lf.preflight(led, FOUR)
        self.assertEqual(v["_chrono_order_oldest_first"],
                         ["W4", "W3", "W2", "W1"])
        self.assertEqual(v["verdict"], "STABLE")


class TestLoopToolingWiring(unittest.TestCase):
    """The confirm scripts must compute the b79 pre-flight in main() — an
    AST pin so the wiring cannot be quietly dropped from the loop's tooling
    (the shipped ledgers predate the wiring; re-running a confirm to
    regenerate them would re-burn a four-window draw for zero new facts)."""

    SCRIPTS = ["b68o_confirm_weekly.py", "b68p_confirm_runway.py",
               "b68q_confirm_nr7htf.py", "b68n4_fourth_draw.py"]

    def _main_calls_preflight(self, fname):
        src = open(os.path.join(ROOT, "scripts", fname)).read()
        tree = ast.parse(src)
        main = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        calls = [n for n in ast.walk(main)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and isinstance(n.func.value, ast.Name)
                 and n.func.value.id == "lf" and n.func.attr == "preflight"]
        self.assertTrue(calls, f"{fname}: main() never calls lf.preflight")
        # and its result must be stored under the ledger key, not printed and
        # thrown away
        self.assertIn('"_b79_preflight"', src,
                      f"{fname}: preflight result not stored in the ledger")
        return True

    def test_every_wired_confirm_computes_b79_in_main(self):
        for f in self.SCRIPTS:
            with self.subTest(script=f):
                self._main_calls_preflight(f)

    def test_every_wired_confirm_imports_the_module(self):
        for f in self.SCRIPTS:
            src = open(os.path.join(ROOT, "scripts", f)).read()
            self.assertIn("lab_fire_rate", src, f)


class TestReadOnlyIsolation(unittest.TestCase):
    def test_no_live_module_imports_lab_fire_rate(self):
        # b79 is research tooling: the live trading path (root entrypoints +
        # engines/ + notifier/) must never depend on it. scripts/ MAY.
        targets = ([os.path.join(ROOT, f) for f in sorted(os.listdir(ROOT))
                    if f.endswith(".py")]
                   + [os.path.join(r, fn)
                      for base in ("engines", "notifier")
                      for r, _d, files in os.walk(os.path.join(ROOT, base))
                      for fn in files if fn.endswith(".py")])
        offenders = []
        for p in targets:
            # lab_* modules are the RESEARCH family: they may share code with
            # each other (lab_fire_rate reuses lab_decay's chrono_windows) —
            # the contract this pins is that the LIVE path never touches them.
            if os.path.basename(p).startswith("lab_"):
                continue
            for node in ast.walk(ast.parse(open(p).read(), filename=p)):
                if isinstance(node, ast.Import) and any(
                        "lab_fire_rate" in a.name for a in node.names):
                    offenders.append(p)
                elif isinstance(node, ast.ImportFrom) and (
                        (node.module or "").endswith("lab_fire_rate")):
                    offenders.append(p)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
