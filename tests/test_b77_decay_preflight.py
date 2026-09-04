"""b77 — the CHRONOLOGICAL-DECAY PRE-FLIGHT must be a real gate, not a report.

Why this exists (todo b77, from b68 round 14): the fourth draw killed
funnel_h4t_agree, and the SHAPE of the kill was the lesson. Margins quoted in
WINDOW order (W1→W4 — labels are NEWEST-FIRST) looked like a slow decay toward
the bar (+0.093/+0.032/+0.008/−0.015); read in CHRONOLOGICAL order (W4 oldest →
W1 newest) they are MONOTONIC INCREASING — the edge grows with recency, i.e. it
is a gift of the recent regime, not a property of gold M15. A candidate like
that cannot be expected to survive forward out of the regime that feeds it, and
no further draw can rescue it. The round-14 near-miss was exactly this misread,
so the rule is: read the margin series by TIMESTAMP, never by label, and check
the shape BEFORE spending a draw.

The abandoned deliverable this test pins (left uncommitted by the round-14
follow-up run, b46 shape): engines/lab_decay.py (margins_by_window /
chrono_windows / decay_verdict / preflight) + scripts/b77_decay_preflight.py
+ data/backtest/b77_decay_preflight.json.

Pins, in order of what would rot first:

1. THE SHIPPED PRE-FLIGHT JSON: the headline facts are present and the
   four-window chronological series for funnel_h4t_agree is exactly the
   round-14 margin series (−0.015/+0.008/+0.032/+0.093) read OLDEST-FIRST,
   verdict REGIME_GIFTED.
2. THE COUNTERFACTUAL (the whole point of the item): on the three windows
   round 13 actually had BEFORE spending W4, the same rule already says
   REGIME_GIFTED — so the pre-flight would have stopped the loop one draw
   earlier. Pinned as would_have_stopped_before_W4 == True.
3. The script REPRODUCES the shipped JSON byte-for-byte from the ledgers
   (the ledger is not a hand-typed artefact).
4. chrono_windows sorts by the windows' own timestamps and REFUSES to guess
   when a window has no timestamp (a silent fallback to label order is the
   exact bug class this module exists to kill).
5. decay_verdict's four verdicts on synthetic series, both directions:
   REGIME_GIFTED needs monotone-increasing AND |slope| >= SLOPE_MIN_R (a
   monotone ramp of 0.001R/step is noise, not a regime gift); DECAYING;
   MIXED; and INSUFFICIENT below 3 windows — a 2-point line is monotone by
   CONSTRUCTION and must never be called a curve.
6. None margins never silently become 0.0 (an arm that traded 0 times on a
   window makes the series INSUFFICIENT, not a fake datapoint).
7. margins_by_window computes arm − funnel per window from a ledger and
   never mutates it; preflight skips the funnel's own row.
8. READ-ONLY ISOLATION: no live-path module (root *.py, engines/, notifier/)
   imports lab_decay — same contract engines/lab_harness.py keeps.
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

from engines import lab_decay as ld  # noqa: E402

PREFLIGHT = os.path.join(ROOT, "data", "backtest", "b77_decay_preflight.json")
LEDGER = os.path.join(ROOT, "data", "backtest", "b68n4_fourth_draw.json")
WINDOWS = os.path.join(ROOT, "data", "backtest",
                       "b68l_independent_windows.json")
CHAMPION = "funnel_h4t_agree"
FOUR = ["W1", "W2", "W3", "W4"]


def _load(path):
    with open(path) as f:
        return json.load(f)


class TestShippedPreflight(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _load(PREFLIGHT)

    def test_chrono_order_is_oldest_first_not_label_order(self):
        # W1 is the NEWEST window by convention; a series read W1→W4 is read
        # backwards. The shipped ledger must name the time order explicitly.
        self.assertEqual(self.p["four_window"]["_chrono_order_oldest_first"],
                         ["W4", "W3", "W2", "W1"])
        self.assertEqual(
            self.p["three_window_pre_w4"]["_chrono_order_oldest_first"],
            ["W3", "W2", "W1"])

    def test_champion_four_window_series_matches_round14_margins(self):
        # The pre-flight must agree with the round-14 ledger it reads — the
        # margin_series there is keyed by label, here ordered by time.
        led = _load(LEDGER)
        by_label = led["_verdict"]["margin_series"]
        row = self.p["four_window"][CHAMPION]
        self.assertEqual(row["series"],
                         [by_label[w] for w in row["chrono_order"]])
        self.assertEqual(row["series"], [-0.015, 0.008, 0.032, 0.093])
        self.assertEqual(row["verdict"], "REGIME_GIFTED")
        self.assertTrue(row["monotone_increasing"])
        self.assertGreaterEqual(row["slope_R_per_step"], ld.SLOPE_MIN_R)

    def test_pre_flight_would_have_stopped_before_the_w4_draw(self):
        # THE headline: on the knowledge round 13 had (W1/W2/W3 only) the
        # rule already called it. This is the counterfactual that earns the
        # item — a pre-flight that only fires after the draw is a report.
        h = self.p["_headline"]
        self.assertEqual(h["arm"], CHAMPION)
        self.assertEqual(h["three_window_verdict_before_w4_draw"],
                         "REGIME_GIFTED")
        self.assertIs(h["would_have_stopped_before_W4"], True)
        self.assertEqual(
            self.p["three_window_pre_w4"][CHAMPION]["series"],
            [0.008, 0.032, 0.093])

    def test_only_the_champion_is_regime_gifted_on_four_windows(self):
        # Anti-vacuity: the rule must not stamp every arm REGIME_GIFTED, or
        # it is a constant function wearing a name.
        fw = {k: v["verdict"] for k, v in self.p["four_window"].items()
              if not k.startswith("_")}
        self.assertEqual([a for a, v in fw.items() if v == "REGIME_GIFTED"],
                         [CHAMPION])
        self.assertIn(fw["pdh_w10_control"], ("MIXED", "DECAYING"))

    def test_slope_min_R_is_shipped_in_the_ledger(self):
        # The threshold that decides REGIME_GIFTED must be visible in the
        # artefact, so a future reader can tell a 0.02 ramp from a 0.001 one.
        self.assertEqual(self.p["four_window"]["_slope_min_R"],
                         ld.SLOPE_MIN_R)


class TestReproducesFromLedgers(unittest.TestCase):
    def test_script_regenerates_the_shipped_json_exactly(self):
        # The ledger is a computed artefact, not a hand-typed one. Run the
        # script against a redirected OUT (b48: the seam redirects STATE,
        # never code) and require byte equality with what is committed.
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "preflight.json")
            env = dict(os.environ, B77_PREFLIGHT_OUT=out)
            r = subprocess.run([sys.executable,
                                os.path.join(ROOT, "scripts",
                                             "b77_decay_preflight.py")],
                               capture_output=True, text=True, env=env,
                               cwd=ROOT, timeout=180)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            self.assertEqual(_load(out), _load(PREFLIGHT))


class TestChronoOrdering(unittest.TestCase):
    def test_sorts_by_timestamp_not_label(self):
        meta = {"W1": {"last": 500}, "W2": {"last": 400},
                "W3": {"last": 300}, "W4": {"last": 200}}
        self.assertEqual(ld.chrono_windows(meta, ["W1", "W2", "W3", "W4"]),
                         ["W4", "W3", "W2", "W1"])

    def test_labels_are_newest_first_in_the_real_windows_ledger(self):
        # The convention this module defends against: W1 is the NEWEST
        # window. If someone ever renames windows oldest-first, the
        # chronological sort still works but this pin tells them the
        # convention changed.
        w = _load(WINDOWS)
        self.assertGreater(w["_W1_meta"]["last"], w["_W2_meta"]["last"])
        self.assertGreater(w["_W2_meta"]["last"], w["_W3_meta"]["last"])
        self.assertGreater(w["_W3_meta"]["last"], w["_W4_meta"]["last"])

    def test_missing_timestamp_raises_instead_of_guessing(self):
        # A silent fallback to label order is the exact bug class b77 kills.
        with self.assertRaises(KeyError):
            ld.chrono_windows({"W1": {"last": 10}}, ["W1", "W9"])


class TestDecayVerdictRule(unittest.TestCase):
    def _v(self, series, order=None):
        order = order or [f"W{i}" for i in range(1, len(series) + 1)]
        return ld.decay_verdict(dict(zip(order, series)), order)

    def test_monotone_ramp_clearing_the_slope_bar_is_regime_gifted(self):
        v = self._v([0.008, 0.032, 0.093])
        self.assertEqual(v["verdict"], "REGIME_GIFTED")
        self.assertTrue(v["monotone_increasing"])

    def test_monotone_ramp_below_the_slope_bar_is_not_a_regime_gift(self):
        # A 0.001R/step ramp is noise; stamping it REGIME_GIFTED would let
        # the rule close candidates on immaterial shapes.
        v = self._v([0.000, 0.001, 0.002])
        self.assertEqual(v["verdict"], "MIXED")
        self.assertTrue(v["monotone_increasing"])
        self.assertLess(abs(v["slope_R_per_step"]), ld.SLOPE_MIN_R)

    def test_monotone_down_is_decaying(self):
        v = self._v([0.090, 0.040, -0.010])
        self.assertEqual(v["verdict"], "DECAYING")
        self.assertTrue(v["monotone_decreasing"])
        self.assertFalse(v["monotone_increasing"])

    def test_any_reversal_is_mixed(self):
        self.assertEqual(self._v([-0.015, 0.008, 0.032, 0.005])["verdict"],
                         "MIXED")

    def test_two_windows_are_insufficient_not_a_curve(self):
        # A 2-point line is monotone by CONSTRUCTION — calling it a decay
        # curve is how a candidate gets closed on two datapoints.
        v = self._v([0.01, 0.09])
        self.assertEqual(v["verdict"], "INSUFFICIENT")
        self.assertIsNone(v["slope_R_per_step"])

    def test_none_margin_never_becomes_a_fake_zero(self):
        v = self._v([0.01, None, 0.09])
        self.assertEqual(v["verdict"], "INSUFFICIENT")
        self.assertIn(None, v["series"])

    def test_tie_step_is_not_monotone(self):
        # strict inequality: a plateau is MIXED, not a ramp.
        v = self._v([0.05, 0.05, 0.20])
        self.assertEqual(v["verdict"], "MIXED")


class TestMarginsAndPreflight(unittest.TestCase):
    def _led(self):
        return {
            "W1": {"CURRENT_FUNNEL": {"ladder_ts": {"exp_R": 0.50}},
                   "arm_a": {"ladder_ts": {"exp_R": 0.60}},
                   "arm_b": {"ladder_ts": {"exp_R": 0.40}}},
            "W2": {"CURRENT_FUNNEL": {"ladder_ts": {"exp_R": 0.50}},
                   "arm_a": {"ladder_ts": {"exp_R": 0.55}},
                   "arm_b": {"ladder_ts": {"exp_R": 0.45}}},
            "W3": {"CURRENT_FUNNEL": {"ladder_ts": {"exp_R": 0.50}},
                   "arm_a": {"ladder_ts": {"exp_R": 0.52}},
                   "arm_b": {"ladder_ts": {}}},
        }

    def test_margin_is_arm_minus_funnel_per_window(self):
        led = self._led()
        m = ld.margins_by_window(led, "arm_a", ["W1", "W2", "W3"])
        self.assertEqual(m, {"W1": 0.1, "W2": 0.05, "W3": 0.02})
        self.assertEqual(led, self._led())   # ledger never mutated

    def test_missing_exp_R_yields_none_margin(self):
        m = ld.margins_by_window(self._led(), "arm_b", ["W3"])
        self.assertIsNone(m["W3"])

    def test_preflight_skips_the_funnel_row_and_keeps_chrono_order(self):
        meta = {"W1": {"last": 300}, "W2": {"last": 200}, "W3": {"last": 100}}
        out = ld.preflight(self._led(),
                           ["CURRENT_FUNNEL", "arm_a", "arm_b"],
                           ["W1", "W2", "W3"], meta)
        self.assertNotIn("CURRENT_FUNNEL", out)
        self.assertEqual(out["_chrono_order_oldest_first"],
                         ["W3", "W2", "W1"])
        self.assertEqual(out["arm_a"]["series"], [0.02, 0.05, 0.1])
        self.assertEqual(out["arm_a"]["verdict"], "REGIME_GIFTED")
        # arm_b has a None margin on W3 -> INSUFFICIENT, not a fake datapoint
        self.assertEqual(out["arm_b"]["verdict"], "INSUFFICIENT")

    def test_preflight_on_the_real_ledger_matches_the_shipped_json(self):
        led, wins = _load(LEDGER), _load(WINDOWS)
        meta = {w: wins[f"_{w}_meta"] for w in FOUR}
        arms = [a for a in led["W4"]
                if not a.startswith("_") and a != "CURRENT_FUNNEL"]
        out = ld.preflight(led, arms, FOUR, meta)
        shipped = _load(PREFLIGHT)["four_window"]
        self.assertEqual({k: v for k, v in out.items()
                          if not k.startswith("_")},
                         {k: v for k, v in shipped.items()
                          if not k.startswith("_")})


class TestReadOnlyIsolation(unittest.TestCase):
    def test_no_live_module_imports_lab_decay(self):
        # b77 is research tooling: the live trading path (root entrypoints +
        # engines/ + notifier/) must never depend on it. scripts/ MAY.
        targets = ([os.path.join(ROOT, f) for f in sorted(os.listdir(ROOT))
                    if f.endswith(".py")]
                   + [os.path.join(r, fn)
                      for base in ("engines", "notifier")
                      for r, _d, files in os.walk(os.path.join(ROOT, base))
                      for fn in files if fn.endswith(".py")])
        offenders = []
        for p in targets:
            if os.path.basename(p) == "lab_decay.py":
                continue
            for node in ast.walk(ast.parse(open(p).read(), filename=p)):
                if isinstance(node, ast.Import) and any(
                        "lab_decay" in a.name for a in node.names):
                    offenders.append(p)
                elif isinstance(node, ast.ImportFrom) and (
                        (node.module or "").endswith("lab_decay")):
                    offenders.append(p)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
