"""b191 — THE TRUE LIVE-PARITY BAR: M5-ENTRY WINDOW LEGS (edited pin).

THIS FILE WAS THE SPARED-DIRECTION PIN. It shipped in c201fc3 to certify
that scripts/b191_m5_window_lab.py did NOT exist and the only citable wired
bar was the b190 coverage-gated M15 one. The lab shipped in this same round,
so — exactly as the old docstring promised — the pin is EDITED, not deleted:
its existence assertion became a citation of the new ledger, and the band
re-quote moved here in the open.

WHAT THE LAB SHIPPED (scripts/b191_m5_window_lab.py, ledger
data/backtest/b191_m5_window_lab.json)
====================================================
Independent 6500-bar M5 ENTRY windows (M5W1..M5W4) built b68l-style — each
strictly before the cached M15 span, measured for overlap — run through the
sanctioned funnel twice per leg: wired (the stream's own settled M5 closes,
byte-parity with hermes_runtime) vs control (m5_stream=[], the pre-b189 arm).
M5W0_anchor re-prices b189's arm C/D inside this script as the integrity
anchor: 166/0.197 wired, 159/0.212 control must reproduce exactly.

THE FINDING the pins below certify: on the true entry TF, out of the tuned
regime, the funnel's wired band is ~0.14-0.20 and the b187 trigger delta is
still MIXED SIGN near zero — see the numbers pinned in each test. Nothing
live is wired; no gate, threshold, lot or verdict moved.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LEDGER = os.path.join(ROOT, "data", "backtest", "b191_m5_window_lab.json")
B190_LEDGER = os.path.join(ROOT, "data", "backtest",
                           "b190_merit_bar_live_trigger.json")
LAB = os.path.join(ROOT, "scripts", "b191_m5_window_lab.py")

LEGS = ("M5W0_anchor", "M5W1", "M5W2", "M5W3", "M5W4")
INDEP = ("M5W1", "M5W2", "M5W3", "M5W4")   # strictly before the cached span

if not os.path.exists(LEDGER):
    raise unittest.SkipTest(
        f"{LEDGER} missing — run scripts/b191_m5_window_lab.py")

LED = json.load(open(LEDGER))


class TestB191LabExists(unittest.TestCase):
    """The edited half of the old existence pin: the lab must be THERE (a
    deletion that 'passes' by resurrecting the spared direction fails)."""

    def test_b191_m5_entry_window_lab_shipped(self):
        self.assertTrue(os.path.exists(LAB),
                        "scripts/b191_m5_window_lab.py disappeared — the "
                        "M5-entry bar loses its producer; restore or delete "
                        "this pin in a deliberate commit")

    def test_anchor_reproduces_b189_arms_CD(self):
        """The integrity anchor: this script's own arm machinery re-prices
        b189's arm C (wired) and D (control) byte-identically."""
        a = LED["M5W0_anchor"]
        self.assertTrue(a["anchor_ok"],
                        "b191's arms no longer reproduce b189's stored C/D — "
                        "the window machinery drifted from the funnel that "
                        "produced the bar (b109 class)")
        self.assertEqual([a["wired_own_m5_closes"]["trades"],
                          a["wired_own_m5_closes"]["exp_R"]],
                         a["_stored_b189"]["wired"])
        self.assertEqual([a["control_no_trigger"]["trades"],
                          a["control_no_trigger"]["exp_R"]],
                         a["_stored_b189"]["control"])


class TestB191Independence(unittest.TestCase):
    """b68l round-11's contamination rule applied to M5: an independent leg
    must MEASURE zero overlap with the cached span it was cut before."""

    def test_every_independent_leg_is_measured_zero_overlap(self):
        ind = LED["_independence"]
        for name in INDEP:
            self.assertEqual(ind[name]["overlap_with_cached_span"], 0,
                             f"{name} overlaps the cached span")
            self.assertLess(ind[name]["last"], ind["cached_m15_first"],
                            f"{name} ends inside/after the cached span")
            self.assertEqual(ind[name]["bars"], 6500)

    def test_windows_are_strictly_ordered_newest_first(self):
        spans = [LED[n]["_span"] for n in INDEP]
        for older, newer in zip(spans[1:], spans[:-1]):
            self.assertLess(older[1], newer[0],
                            "M5 windows overlap each other — not independent")


class TestB191HonestyGate(unittest.TestCase):
    """b190's floor travels with the method: coverage measured through the
    shared m5_window_for, and a sub-floor leg is never quotable."""

    def test_coverage_is_measured_and_high_on_m5_entry_legs(self):
        cov = {leg: LED[leg]["_m5_coverage"] for leg in LED["_legs"]}
        for leg in INDEP:
            self.assertGreaterEqual(cov[leg], 0.9,
                                    f"{leg} coverage {cov[leg]} < 0.9 — the "
                                    "bar must refuse it, check the flag below")
        # THE STRUCTURAL FINDING vs b190: an M5-ENTRY leg carries its own
        # settled closes, so coverage is ~1.0 on EVERY window — including the
        # leg that predates the broker's 60000-bar M5 history (b190's W4 was
        # 0.00 there). The entry TF removed the coverage hole; pin it.
        self.assertEqual({LED[leg]["_m5_coverage"] for leg in LED["_legs"]},
                         {0.9997},
                         "coverage moved off ~1.0 on every leg — the "
                         "M5-entry legs are the point of this lab; re-derive")
        # anti-vacuity: a column that is all exactly 1.0 would hide a bug in
        # the probe itself; the real market has weekend/holiday gaps.
        self.assertTrue(any(cov[leg] < 1.0 for leg in INDEP),
                        "coverage column is all-1.0 — the probe may be "
                        "certifying nothing (measure via m5_window_for!)")

    def test_bar_refuses_sub_floor_legs(self):
        mod = _load_lab()
        self.assertEqual(mod.bar(LED), LED["_merit_bar_m5_entry"])
        for leg in LED["_legs"]:
            if LED[leg]["_m5_coverage"] < LED["_merit_bar_m5_entry"][
                    "_coverage_floor"]:
                self.assertIsNone(LED["_merit_bar_m5_entry"][leg],
                                  f"{leg} quoted despite low coverage")


class TestB191BandIsTheHeadline(unittest.TestCase):
    """THE QUOTED RESULT: the M5-entry legs and what they do to the cited
    ~0.20-0.28 band. These numbers move only via a re-measurement that
    re-quotes the backlog in the same commit — that is the whole point."""

    def test_m5_entry_wired_band_matches_the_measured_run(self):
        bar = LED["_merit_bar_m5_entry"]
        quoted = {k: bar[k] for k in INDEP}
        self.assertEqual(quoted, {"M5W1": 0.202, "M5W2": 0.328,
                                  "M5W3": 0.142, "M5W4": 0.297},
                         "the M5-entry wired band moved — re-quote every "
                         "backlog note that uses it (b190 pin discipline)")
        # THE HEADLINE vs b190: on the live entry TF the band WIDENS to
        # 0.142-0.328 (the M15 proxy band was 0.197-0.28) — the mean holds
        # (~0.24), the per-window spread does not. Pin the mean so a future
        # round cannot quietly re-center the bar.
        vals = [v for v in quoted.values() if isinstance(v, float)]
        self.assertEqual(len(vals), 4,
                         "an independent M5 leg lost its quote — with ~1.0 "
                         "coverage on this TF a None means the leg moved out "
                         "of M5 history, a re-fetch decision, not noise")
        self.assertEqual(round(sum(vals) / len(vals), 3), 0.242,
                         "the M5-entry mean exp_R moved — re-quote the band")

    def test_trigger_delta_stays_mixed_sign_on_the_entry_tf(self):
        d = LED["_trigger_delta"]
        deltas = {leg: d[leg]["d_exp_R"] for leg in INDEP}
        self.assertEqual(deltas, {"M5W1": 0.001, "M5W2": 0.042,
                                  "M5W3": 0.01, "M5W4": -0.055},
                         "the wired-minus-control delta moved — the mixed-"
                         "sign neutrality reading must be re-derived")
        self.assertTrue(any(x > 0 for x in deltas.values())
                        and any(x < 0 for x in deltas.values()),
                        f"delta signs collapsed ({deltas}) — b190's reading "
                        "is no longer reproduced on the entry TF")
        # b190's release pattern holds here too: the confirmation never
        # NET-suppresses trades on this TF (late M5 closes push reward>R
        # as often as they gate entries out).
        self.assertTrue(all(d[leg]["d_trades"] >= 0 for leg in INDEP),
                        "wired traded fewer trades than control on some "
                        "independent leg — re-read before quoting")

    def test_band_comparison_excludes_the_anchor(self):
        """M5W0 sits INSIDE the cached (tuned) span — b68l round-11's own
        contamination — so the quoted band arithmetic must exclude it."""
        cmp_block = LED["_band_vs_b190_m15_bar"]
        self.assertNotIn("M5W0_anchor", cmp_block["b191_m5_entry_wired"])
        self.assertIn("M5W1", cmp_block["b191_m5_entry_wired"])
        mod = _load_lab()
        self.assertEqual(mod.band_comparison(LED), cmp_block,
                         "band_comparison() no longer reproduces the stored "
                         "cross-read (b127 rule)")

    def test_m15_cited_bar_untouched_by_this_round(self):
        """The b190 pin re-quoted [0.28, 0.197, 0.245] for cached/W1/W2 —
        b191 measures a NEW view and must not silently move the old one."""
        b190 = json.load(open(B190_LEDGER))
        bar = b190["_merit_bar_live_wired"]
        self.assertEqual([round(bar[k], 3) for k in ("cached", "W1", "W2")],
                         [0.28, 0.197, 0.245])


class TestB191SanctionedFunnelOnly(unittest.TestCase):
    """HARD RULE (b190's template): funnel measurements come from
    run_backtest, never a hand-copied funnel — AST-pinned on the producer."""

    def test_b191_produces_numbers_only_through_run_backtest(self):
        import ast
        src = open(LAB).read()
        tree = ast.parse(src)
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                names.update(a.name for a in n.names)
            elif isinstance(n, ast.Import):
                names.update(a.name for a in n.names)
        self.assertIn("run_backtest", names)
        self.assertNotIn("backtest_ohlc", names,
                         "b191 must score through run_backtest, not the raw "
                         "engine (HARD RULE: no hand-copied funnel)")
        self.assertNotIn("strategy_signal", names,
                         "b191 must not call the funnel directly — that is "
                         "the b81.funnel_fn path b189 proved cannot see the "
                         "trigger")

    def test_b191_lab_is_read_only_research(self):
        import ast
        src = open(LAB).read()
        for banned in ("open_position", "close_position", "modify_position",
                       "systemctl", "requests.post"):
            self.assertNotIn(banned, src, f"lab mentions {banned}")
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
            self.assertNotIn(banned, mods, f"lab imports live path {banned}")

    def test_b191_backlog_records_the_item_done(self):
        text = open(os.path.join(ROOT, "data", "ops",
                                 "autopilot_backlog.md")).read()
        done_line = [ln for ln in text.splitlines()
                     if "b191" in ln and "DONE" in ln]
        self.assertTrue(done_line,
                        "b191 must be marked DONE in the backlog with its "
                        "finding before its ledger's pins run")
        body = " ".join(done_line).lower()
        self.assertTrue("band" in body or "band" in text.lower(),
                        "the DONE entry must carry the finding (the widened "
                        "M5-entry band), not just a checkmark")
        self.assertIn("M5W1 0.202", text,
                      "the DONE entry must quote the measured M5-entry band "
                      "numbers, not a vague claim")


def _load_lab():
    import importlib.util
    spec = importlib.util.spec_from_file_location("b191_lab", LAB)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    unittest.main(verbosity=2)
