"""b190 — THE MERIT BAR RE-BASELINED UNDER THE b187-WIRED FUNNEL.

WHAT SHIPPED (scripts/b190_merit_bar_live_trigger.py, ledger
data/backtest/b190_merit_bar_live_trigger.json)
==============================================
b189 wired the live b187 entry trigger (M5 3-close confirmation) into
run_backtest, but every stored funnel ledger runs the funnel through
b81.funnel_fn WITHOUT m5 rows — so re-running b117/b118 today reproduces the
PRE-WIRING bar and cannot price the trigger. This round re-measures the merit
bar per leg (cached + W1..W4) through the sanctioned funnel only, twice:
control (m5_stream=[], the stored 0.254-class bar) vs wired (the broker's own
settled M5 closes at each decision moment).

THE HEADLINE: on the TRUE confirmation windows the trigger delta is MIXED SIGN
— cached +0.026R (102->104), W1 -0.007R (161->167), W2 -0.050R (154->161).
The cached leg's gain is the smallest positive of the five and W2 (the second
independent window with full M5 coverage) is clearly negative. The b187
trigger is NOT a lab win: on three legs with real closes it moves the bar by
-0.050..+0.026R with a mean near zero, exactly the "~neutral" reading b189
filed this re-baseline for. The live NEW bar (wired, coverage-gated):
cached 0.280 | W1 0.197 | W2 0.245 — the quoted band ~0.20-0.28R still holds.

THE COVERAGE FINDING (honesty gate, b116 class): the bridge caps M5 history
at 60000 bars (~2025-11-03 onward). W3 is only 72% covered and W4 has ZERO
M5 closes in its span, so "wired" on those legs degenerates to the control.
`bar()` refuses to quote any leg below 0.9 coverage (returns None) and the
ledger stores the measured coverage per leg — a number that silently means
"no trigger" would be the b116 defect class, and this file pins that it does
not happen.

FOLLOW-UP FILED AS b191: the true live-parity bar is an M5 ENTRY stream over
a window-independent horizon; extending it needs a cached M5 OHLC + H1/H4
context set (like b68l_windows for M15). No live change: no gate, threshold,
lot, or verdict path is touched; the only bridge call in the producer is
get_rates (history), and nothing here is imported by the live trading path.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LEDGER = os.path.join(ROOT, "data", "backtest",
                      "b190_merit_bar_live_trigger.json")
PROBE = os.path.join(ROOT, "scripts", "b190_merit_bar_live_trigger.py")
B189_LEDGER = os.path.join(ROOT, "data", "backtest",
                           "b189_trigger_parity.json")

LEGS = ("cached", "W1", "W2", "W3", "W4")
COVERED = ("cached", "W1", "W2")           # coverage 1.0 (real M5 closes)
UNCOVERED = ("W3", "W4")                   # 0.7185 / 0.0 — cannot be quoted

if not os.path.exists(LEDGER):
    raise unittest.SkipTest(
        f"{LEDGER} missing — run scripts/b190_merit_bar_live_trigger.py")

LED = json.load(open(LEDGER))


def _load_probe():
    import importlib.util
    spec = importlib.util.spec_from_file_location("b190_probe", PROBE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestB190LedgerShape(unittest.TestCase):
    def test_b190_every_leg_has_both_arms_and_coverage(self):
        self.assertEqual(tuple(LED["_legs"]), LEGS)
        for leg in LEGS:
            L = LED[leg]
            for key in ("control_no_trigger", "wired_real_m5"):
                self.assertIn("exp_R", L[key], f"{leg}.{key} has no row")
                self.assertGreater(L[key]["trades"], 0,
                                   f"{leg}.{key} traded nothing")
            self.assertIsInstance(L["_m5_coverage"], float)

    def test_b190_control_reproduces_the_stored_pre_wiring_bar(self):
        # b118's re-quoted harness bar (the pre-b189-parity convention) is
        # 102 trades / exp_R 0.254 on the cached leg. If the control arm
        # drifted, this round is measuring something else than it claims.
        row = LED["cached"]["control_no_trigger"]
        self.assertEqual((row["trades"], row["exp_R"]), (102, 0.254),
                         "the m5_stream=[] control no longer reproduces the "
                         "stored b118/b187-requote bar — re-read before "
                         "quoting any delta")

    def test_b190_wired_cached_leg_reproduces_b189_arm_B(self):
        # b189 measured 104/0.280 on the same leg with real M5 closes. b190
        # re-fetches the closes (the cache is strictly newer), so a match on
        # BOTH numbers proves the two rounds slice the trigger the same way.
        row = LED["cached"]["wired_real_m5"]
        b189 = json.load(open(B189_LEDGER))["B_m15_real_m5_closes"]
        self.assertEqual((row["trades"], row["exp_R"]),
                         (b189["trades"], b189["exp_R"]),
                         "b190's wired arm != b189's arm B — the trigger is "
                         "being priced off different bar sets (b109 class)")


class TestB190CoverageHonesty(unittest.TestCase):
    """THE ANTI-B116 FLOOR: a leg without M5 closes must never be quoted as
    if the trigger fired there."""

    def test_b190_coverage_is_measured_not_assumed(self):
        cov = {leg: LED[leg]["_m5_coverage"] for leg in LEGS}
        for leg in COVERED:
            self.assertGreaterEqual(cov[leg], 0.9, f"{leg} coverage {cov[leg]}")
        self.assertLess(cov["W4"], 0.01,
                        "W4 must be (measured) uncovered — the broker's M5 "
                        "history stops ~2025-11-03, W3-W4 predate it")
        # Anti-vacuity: the coverage column must not be all-1.0 (then the
        # gate would certify nothing) nor all-0 (then the bar would be empty).
        self.assertTrue(0 < sum(1 for v in cov.values() if v >= 0.9) < len(LEGS))

    def test_b190_bar_refuses_uncovered_legs(self):
        bar = LED["_merit_bar_live_wired"]
        for leg in UNCOVERED:
            self.assertIsNone(bar[leg],
                              f"{leg} is quoted despite coverage "
                              f"{LED[leg]['_m5_coverage']} < 0.9")
        for leg in COVERED:
            self.assertIsInstance(bar[leg], float)
        self.assertEqual(bar["_coverage_floor"], 0.9)

    def test_b190_uncovered_wired_row_equals_the_control_exactly(self):
        # Arithmetic consequence of coverage 0: with no closes the trigger can
        # never fire, so wired IS the control. Pin it (W4) — this is what a
        # fake 'wired' number would look like if bar() were silent.
        L = LED["W4"]
        self.assertEqual(L["wired_real_m5"]["trades"],
                         L["control_no_trigger"]["trades"])
        self.assertEqual(L["wired_real_m5"]["exp_R"],
                         L["control_no_trigger"]["exp_R"])
        self.assertEqual(L["d_exp_R"], 0.0)


class TestB190TriggerDeltaIsTheFinding(unittest.TestCase):
    """THE HEADLINE: mixed sign on the covered legs => the b187 trigger is
    lab-neutral, not the +49% win the M15-proxy requote suggested."""

    def test_b190_delta_signs_are_mixed_on_covered_legs(self):
        d = LED["_trigger_delta"]
        deltas = [d[leg]["d_exp_R"] for leg in COVERED]
        self.assertTrue(any(x > 0 for x in deltas) and any(x < 0 for x in deltas),
                        f"delta signs collapsed to one side ({deltas}) — "
                        "the neutrality reading must be re-derived, not kept")
        self.assertEqual(deltas, [0.026, -0.007, -0.05])

    def test_b190_delta_block_is_reproducible_arithmetic(self):
        # b127 discipline: the stored post-processing must equal the
        # producer's own pure function over the same ledger.
        mod = _load_probe()
        self.assertEqual(mod.trigger_delta(LED), LED["_trigger_delta"])
        self.assertEqual(mod.bar(LED), LED["_merit_bar_live_wired"])

    def test_b190_trigger_adds_trades_never_only_removes_them(self):
        # The confirmation both suppresses and (via reward>R on late closes)
        # releases entries: every covered leg has d_trades > 0 on the wired
        # side. If the wired arm ever traded FEWER than the control on all
        # covered legs, someone re-tuned the suppression without deciding.
        d = LED["_trigger_delta"]
        for leg in COVERED:
            self.assertGreaterEqual(d[leg]["d_trades"], 0,
                                    f"{leg}: wired lost trades vs control")
        self.assertEqual({leg: d[leg]["d_trades"] for leg in COVERED},
                         {"cached": 2, "W1": 6, "W2": 7})


class TestB190SanctionedFunnelOnly(unittest.TestCase):
    """HARD RULE: funnel measurements come from run_backtest, never a
    hand-copied funnel — AST-pinned on the producer itself."""

    def test_b190_produces_signals_only_through_run_backtest(self):
        src = open(PROBE).read()
        tree = ast.parse(src)
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                names.update(a.name for a in n.names)
            elif isinstance(n, ast.Import):
                names.update(a.name for a in n.names)
        self.assertIn("run_backtest", names)
        # backtest_ohlc is the ENGINE primitive run_backtest itself calls;
        # importing it here would mean a hand-wired funnel.
        self.assertNotIn("backtest_ohlc", names,
                         "b190 must score through run_backtest, not the raw "
                         "engine (HARD RULE: no hand-copied funnel)")
        self.assertNotIn("strategy_signal", names,
                         "b190 must not call the funnel directly — that is "
                         "the b81.funnel_fn path b189 proved cannot see the "
                         "trigger")

    def test_b190_probe_is_read_only_research(self):
        src = open(PROBE).read()
        for banned in ("open_position", "close_position", "modify_position",
                       "systemctl", "requests.post"):
            self.assertNotIn(banned, src, f"probe mentions {banned}")
        tree = ast.parse(src)
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module.split(".")[0])
            elif isinstance(n, ast.Import):
                for a in n.names:
                    mods.add(a.name.split(".")[0])
        for banned in ("hermes_runtime", "auto_executor", "position_daemon",
                       "signal_daemon", "subprocess"):
            self.assertNotIn(banned, mods, f"probe imports live path {banned}")

    def test_b190_backlog_records_the_item(self):
        text = open(os.path.join(ROOT, "data", "ops",
                                 "autopilot_backlog.md")).read()
        done_line = [ln for ln in text.splitlines()
                     if "b190" in ln and "DONE" in ln]
        self.assertTrue(done_line,
                        "b190 must be marked DONE in the backlog with its "
                        "finding before its ledger's pins run")
        self.assertIn("mixed", " ".join(done_line).lower(),
                      "the DONE line must carry the finding (mixed-sign "
                      "trigger delta), not just a checkmark")


if __name__ == "__main__":
    unittest.main(verbosity=2)
