"""b118b + b126 — THE b70 LANE ANSWER RE-DERIVED ON NUMBERS THAT REPRODUCE,
AND THE DEAD PRODUCER PATH THAT RE-DERIVATION EXPOSED.

WHAT THIS ROUND FOUND (the bigger half)
======================================
`scripts/b108_rescore_corrected.py` — the script b118b's own method note told
the next run to re-execute — has NEVER RUN END TO END since it shipped
(3003cbb, 2026-09-06). Line 168 called `redeide_b70(led)`; the function the
file defines is `redecide_b70`. A NameError on the LAST statement of `main()`:
after all five legs were measured, before the merit bar, the re-decision, the
printed tables and the `json.dump`. The stored ledger is still HONEST — this
file proves it by EXECUTING the script's own `merit_bar()` and
`redecide_b70()` against the shipped JSON and requiring exact reproduction —
but it was produced by an earlier draft, and no test could see the break because
every b108 test reads the ARTIFACT and none touches the CODE that makes it.
That is the b114/b116 disease (an artifact certifying a number instead of the
code producing it) in a new costume: not a stale process, a stale script.

The general cheap defence ships with it: `scripts/b126_dead_path_scan.py`, a
static scan for calls to names a file never binds. Pinned below in BOTH
directions — clean on the repo today, and loud on a synthetic file that
contains exactly the shipped defect shape (a one-character transposition in a
call name). A scan that cannot catch the bug it was written for is decoration.

WHAT b118b MEASURED (scripts/b118b_lane_redecision.py, ledger
data/backtest/b118b_lane_redecision_live_parity.json)
====================================================
b81's `measure_leg` re-executed verbatim (imported, not restated — hard rule)
on cached+W1..W4 under TODAY'S harness: trail derived from live (0.30) with
live's $3.00 floor (b118), b109's ladder fields in the trade dict. b108's own
ledger is left FROZEN as evidence; this is the reproduction, not an overwrite.

  funnel exp_R, stored b108 -> live-parity:
    cached 0.285 -> 0.278 | W1 0.202 -> 0.211 | W2 0.206 -> 0.230
    W3   0.227 -> 0.232  | W4 0.222 -> 0.233
  (exactly b118's re-quoted bar — cross-ledger integrity is pinned below)

  b70 RE-DECIDED on live-parity margins (b74's all-windows rule, same
  b81.verdict function): windows_beaten 1/4 (gated_pdh_dayext, unchanged),
  2 -> 1 (h4pdh: its W2 margin +0.003 turns to -0.001), 1/4 (runway,
  unchanged), 0/4 (nr7htf, unchanged). NO LANE EARNS A SLOT, and the answer
  got FIRMER, not weaker: three of four lanes now sit at 1/4 or worse and
  every surviving margin is <= 0.051R — inside the noise band b110 defines.
  b118b's founding note guessed "unlikely to flip anything"; the flip it did
  allow (h4pdh W2) moves in the direction of the standing answer.

NO LIVE CHANGE: no gate, no exit constant, no trading-path module touched.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SCAN = os.path.join(ROOT, "scripts", "b126_dead_path_scan.py")
B108 = os.path.join(ROOT, "scripts", "b108_rescore_corrected.py")
B118B = os.path.join(ROOT, "scripts", "b118b_lane_redecision.py")
LEDGER = os.path.join(ROOT, "data", "backtest",
                      "b118b_lane_redecision_live_parity.json")
B108_LEDGER = os.path.join(ROOT, "data", "backtest",
                           "b108_rescore_corrected.json")
B118_LEDGER = os.path.join(ROOT, "data", "backtest",
                           "b118_merit_bar_rebaseline.json")

WINDOWS = ("W1", "W2", "W3", "W4")
LEGS = ("cached",) + WINDOWS
LANES = ("lane_gated_pdh_dayext", "lane_h4pdh", "lane_runway", "lane_nr7htf")


def _load(path):
    with open(path) as f:
        return json.load(f)


LED = _load(LEDGER) if os.path.exists(LEDGER) else None
B108_LED = _load(B108_LEDGER)
B118_LED = _load(B118_LEDGER)


# ── b126: the scan itself ──────────────────────────────────────────────────
def _scan_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("b126_scan", SCAN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestB126DeadPathScan(unittest.TestCase):
    """The scan must be CLEAN today and LOUD on the defect it was written for."""

    def test_b126_the_repo_is_clean_of_unresolved_calls(self):
        mod = _scan_module()
        findings = mod.scan(ROOT)
        self.assertEqual(
            findings, {},
            "dead call path(s) found: " + json.dumps(
                {k: [list(h) for h in v] for k, v in findings.items()}))

    def test_b126_the_scan_catches_the_shipped_defect_shape(self):
        # Anti-vacuity: the exact bug this round found — a one-character
        # transposition turning a call name into a name the file never binds.
        # Without this test the clean scan could mean "the scan is broken".
        mod = _scan_module()
        src = ("def redecide_b70(x):\n    return x\n\n\n"
               "def main():\n    y = redecide_b70(1)\n"
               "    z = redeide_b70(y)\n    return z\n")
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "synthetic_dead.py")
            with open(p, "w") as f:
                f.write(src)
            hits = mod.unresolved_calls(p)
        self.assertEqual(hits, [(7, "redeide_b70")],
                         "the scan missed the b108 defect shape")

    def test_b126_star_imports_do_not_produce_false_positives(self):
        # report_lib's helpers are called bare by the two report builders via
        # `from report_lib import *`. A scan that flags 238 of those buries
        # the real finding and gets deleted (b114's lesson), so resolution of
        # star imports is pinned explicitly.
        mod = _scan_module()
        names = mod.star_imported_names(
            ast.parse("from report_lib import *").body[0],
            os.path.join(ROOT, "scripts", "build_full_report.py"))
        for fn in ("heading", "para", "make_table", "rtl", "R", "callout"):
            self.assertIn(fn, names, f"report_lib.{fn} not resolved")

    def test_b126_the_scan_scans_the_trading_code_not_just_itself(self):
        mod = _scan_module()
        files = [os.path.relpath(p, ROOT) for p in mod.python_files(ROOT)]
        for must in ("engines/backtest.py", "engines/trade_management.py",
                     "hermes_master.py", "scripts/b108_rescore_corrected.py",
                     "scripts/b118b_lane_redecision.py"):
            self.assertIn(must, files, f"{must} outside the scan's view")
        self.assertGreater(len(files), 150)


class TestB108ProducerPathIsAlive(unittest.TestCase):
    """The artifact-vs-code gap that hid the defect for a day.

    Every pre-existing b108 test reads the JSON. These tests EXECUTE the
    script's functions against the shipped ledger and require exact
    reproduction — which is what the missing test would have been, and what
    makes the frozen artifact trustworthy despite the broken main().
    """

    def setUp(self):
        from scripts import b108_rescore_corrected as b108mod
        self.b108 = b108mod
        self.led = B108_LED

    def test_b126_b108_main_no_longer_calls_a_name_that_does_not_exist(self):
        with open(B108) as f:
            src = f.read()
        self.assertNotIn("redeide_b70", src,
                         "the b108 typo is back — main() dies before json.dump")
        tree = ast.parse(src)
        defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        called = {n.func.id for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("redecide_b70", defined)
        self.assertIn("redecide_b70", called,
                      "the fixed function must actually be CALLED by main()")

    def test_b126_b108_merit_bar_reproduces_the_stored_ledger(self):
        self.assertEqual(self.b108.merit_bar(self.led), self.led["_merit_bar"])

    def test_b126_b108_redecide_b70_reproduces_the_stored_counts(self):
        v = self.b108.redecide_b70(self.led)
        stored = self.led["_b70_redecision"]
        self.assertEqual({k: row["windows_beaten"] for k, row in v.items()},
                         {k: row["windows_beaten"] for k, row in stored.items()},
                         "b108's own re-decision no longer reproduces its own "
                         "ledger — the artifact and the code have diverged")


# ── b118b: the re-derived lane answer ──────────────────────────────────────
@unittest.skipIf(LED is None, "b118b ledger not built yet")
class TestB118bLaneRedecision(unittest.TestCase):
    def test_b118b_the_funnel_bar_matches_b118_exactly_on_every_leg(self):
        # Cross-ledger integrity: b118b re-measured the funnel with b81's
        # measure_leg; b118 measured the same funnel's live_parity arm. Two
        # scripts, one number — or one of them is not running the live funnel.
        for leg in LEGS:
            self.assertEqual(
                LED[leg]["funnel_graded"]["exp_R"],
                B118_LED[leg]["live_parity"]["exp_R"], leg)
            self.assertEqual(
                LED[leg]["funnel_graded"]["trades"],
                B118_LED[leg]["live_parity"]["trades"], leg)

    def test_b118b_the_stored_b108_cells_match_the_frozen_ledger(self):
        # The comparison baseline must be the ARTIFACT, not a restatement:
        # every stored_* cell in this ledger must equal the frozen b108 row
        # it claims to carry, and the live_parity_* cell must equal this
        # ledger's own measurement. If they diverge, the drift columns are
        # arithmetic on two different worlds.
        for leg in LEGS:
            self.assertEqual(
                LED["_funnel_bar"][leg]["stored_b108_exp_R"],
                B108_LED[leg]["funnel_graded"]["exp_R"], f"{leg} funnel")
            self.assertEqual(
                LED["_funnel_bar"][leg]["live_parity_exp_R"],
                LED[leg]["funnel_graded"]["exp_R"], f"{leg} funnel row")
            for lane in LANES:
                m = LED[leg]["_margins"][lane]
                self.assertEqual(m["stored_b108"]["exp_R"],
                                 B108_LED[leg][lane]["graded"]["exp_R"],
                                 f"{leg}/{lane} stored cell was restated")
                self.assertEqual(m["live_parity"]["exp_R"],
                                 LED[leg][lane]["graded"]["exp_R"],
                                 f"{leg}/{lane} parity cell is not this run")
                self.assertEqual(m["d_exp_R_live_parity"],
                                 round(m["live_parity"]["exp_R"]
                                       - LED[leg]["funnel_graded"]["exp_R"], 3),
                                 f"{leg}/{lane} margin is not its own rows")

    def test_b118b_no_lane_earns_a_slot_on_live_parity_numbers(self):
        v = LED["_b70_redecision_live_parity"]
        for lane in LANES:
            self.assertLess(v[lane]["windows_beaten"], v[lane]["of"],
                            f"{lane} beats the funnel on ALL windows — b70 "
                            "must be re-opened on this ledger, not re-quoted")
            self.assertFalse(v[lane]["replicated_all_windows"])

    def test_b118b_the_only_count_change_moves_toward_the_standing_answer(self):
        v = LED["_b70_redecision_live_parity"]
        changed = {k: row for k, row in v.items() if row["count_changed"]}
        self.assertEqual(set(changed), {"lane_h4pdh"},
                         "a second lane's windows_beaten moved — re-read the "
                         "ledger before quoting b70's answer")
        row = changed["lane_h4pdh"]
        self.assertEqual((row["windows_beaten_stored_b108"],
                          row["windows_beaten"]), (2, 1),
                         "h4pdh moved the WRONG way (toward a slot) — that is "
                         "a re-open of b70, not a bookkeeping note")

    def test_b118b_no_lane_beats_the_funnel_by_more_than_the_noise_band(self):
        # The noise-band claim is about POSITIVE margins: a lane may lose by
        # any amount (that settles b70), but a lane that WINS by more than
        # ~0.05R is a candidate and b70 must be re-opened. Largest positive
        # margin on live-parity numbers is +0.051 (cached, gated_pdh_dayext).
        worst = max(LED[leg]["_margins"][lane]["d_exp_R_live_parity"]
                    for leg in LEGS for lane in LANES)
        self.assertLessEqual(worst, 0.06,
                             f"a lane beats the funnel by {worst}R — outside "
                             "b110's noise band; b70 is up for re-decision")
        self.assertAlmostEqual(worst, 0.051, places=3)

    def test_b118b_the_margin_drift_is_small_and_mixed_sign(self):
        drifts = [LED[leg]["_margins"][lane]["margin_drift"]
                  for leg in LEGS for lane in LANES]
        self.assertTrue(all(d is not None for d in drifts))
        self.assertLessEqual(max(abs(d) for d in drifts), 0.015,
                             "the convention drift swelled past b109's own "
                             "noise band — b108's stored margins are rotting")
        positives = sum(1 for d in drifts if d > 0)
        negatives = sum(1 for d in drifts if d < 0)
        self.assertTrue(positives and negatives,
                        "drift became one-sided — the convention now moves "
                        "every lane the same way, which is b110's contamination "
                        "signature, not neutrality")

    def test_b118b_the_harness_row_records_a_derived_not_restated_trail(self):
        h = LED["_harness"]
        from engines import lab_harness as lh
        self.assertEqual(h["trail_after_partial"], lh.LADDER["trail_after_partial"])
        self.assertEqual(h["trail_floor"], lh.LADDER["trail_floor"])
        self.assertEqual(h["min_grade"], lh.LIVE_MIN_GRADE)
        self.assertNotEqual(h["trail_after_partial"], 0.50,
                           "the legacy literal is back in the harness")

    def test_b118b_script_imports_b81_and_b108_rather_than_restating_them(self):
        with open(B118B) as f:
            src = f.read()
        self.assertIn("from scripts import b81_lane_rescore", src)
        self.assertIn("from scripts import b108_rescore_corrected", src)
        self.assertIn("b81.measure_leg", src)
        self.assertIn("STORED = b108.OUT", src,
                      "the frozen ledger must be referenced by b108's own path")
        self.assertNotIn("strategy_signal", src,
                         "b118b must not re-derive the funnel itself")

    def test_b118b_wired_nothing_into_the_live_path(self):
        for d in ("engines", "hermes_master.py", "hermes_runtime.py",
                  "position_daemon.py", "signal_daemon.py"):
            p = os.path.join(ROOT, d)
            files = ([p] if os.path.isfile(p) else
                     [os.path.join(p, f) for f in sorted(os.listdir(p))
                      if f.endswith(".py")]) if os.path.exists(p) else []
            for fp in files:
                with open(fp) as f:
                    body = f.read()
                for needle in ("b118b_lane_redecision", "b126_dead_path_scan"):
                    self.assertNotIn(needle, body,
                                     f"{fp} imports the {needle} lab script")


if __name__ == "__main__":
    unittest.main(verbosity=2)
