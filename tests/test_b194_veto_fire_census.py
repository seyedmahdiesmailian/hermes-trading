"""b194 — RE-PRICE UNDER THE b193 VETO-FIXED FUNNEL: ALIVE AND INERT.

WHAT SHIPPED (scripts/b194_veto_fire_census.py + two frozen before/after
ledgers data/backtest/b194_pre_veto_b19{0,1}_ledger.json)
=========================================================
b193 moved the stale-at-birth veto into the seam BOTH paths share and
measured 11 leaked signals on the cached leg, filing b194 to re-price the
cited merit bar. The re-runs of scripts/b190_merit_bar_live_trigger.py and
scripts/b191_m5_window_lab.py came back BYTE-IDENTICAL: cached 0.280 |
W1 0.197 | W2 0.245, M5-entry band 0.142-0.328 — every leg, both arms, to
the last decimal. An identical ledger has two causes: the veto changes no
trades, or the veto is not being reached (the b189/b193 parity-drift class
resurrected). The fire census separates them: apply_smc_merge is wrapped by
a PASS-THROUGH counter and the funnel legs replay through run_backtest,
counting seam calls and vetoes per arm.

THE FINDING these pins certify: ALIVE_AND_INERT. The seam FIRES inside the
lab funnel on every arm (72/71 vetoes on the cached M15 legs, 281 on each
M5W1 leg, 705 total) and the trade rows still match the stored bar exactly.
The vetoes bite at BAR level but the affected bars never convert to trades —
the rest of the gauntlet (grade-B, min_rr, geometry) already rejects them,
which is the same conclusion b193 reached for live (0 stale plans post-b188
reached execution). The quoted band STANDS; no b68 arm delta needs the
>0.02R re-check (nothing moved at all).

Pins: the verdict block is reproducible arithmetic (b127 rule), every arm
has vetoes > 0 (anti-vacuity: a silently unwired seam would read
DEAD_WIRE), rows match stored, and the byte-identity itself is pinned
against the frozen pre-veto ledgers so no future round can quietly move
the bar while claiming "already re-priced".
"""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LEDGER = os.path.join(ROOT, "data", "backtest", "b194_veto_fire_census.json")
PRE_190 = os.path.join(ROOT, "data", "backtest",
                       "b194_pre_veto_b190_ledger.json")
PRE_191 = os.path.join(ROOT, "data", "backtest",
                       "b194_pre_veto_b191_ledger.json")
NEW_190 = os.path.join(ROOT, "data", "backtest",
                       "b190_merit_bar_live_trigger.json")
NEW_191 = os.path.join(ROOT, "data", "backtest", "b191_m5_window_lab.json")
PROBE = os.path.join(ROOT, "scripts", "b194_veto_fire_census.py")

ARMS = [("cached", "control"), ("cached", "wired"),
        ("M5W1", "control"), ("M5W1", "wired")]
CITED_M15_BAR = {"cached": 0.28, "W1": 0.197, "W2": 0.245}
CITED_M5W_BAND = {"M5W1": 0.202, "M5W2": 0.328, "M5W3": 0.142, "M5W4": 0.297}

if not os.path.exists(LEDGER):
    raise unittest.SkipTest(
        f"{LEDGER} missing — run scripts/b194_veto_fire_census.py")

LED = json.load(open(LEDGER))


def _load_probe():
    import importlib.util
    spec = importlib.util.spec_from_file_location("b194_probe", PROBE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestB194CensusShape(unittest.TestCase):
    def test_every_arm_reached_the_seam(self):
        self.assertEqual([list(a) for a in LED["_arms"]],
                         [list(a) for a in ARMS])
        for name, arm in ARMS:
            c = LED[arm + "_" + name]
            self.assertGreater(c["calls"], 0,
                               f"{arm}/{name}: funnel ran without touching "
                               "the merge seam at all")
            self.assertGreater(c["trades"], 0,
                               f"{arm}/{name}: leg traded nothing")


class TestB194VerdictIsTheFinding(unittest.TestCase):
    """THE HEADLINE: the b193 seam is ALIVE in the lab funnel (vetoes fire)
    and INERT at trade level (rows byte-match the stored bar). If a future
    refactor unwires the seam the verdict flips to DEAD_WIRE; if the rows
    move it flips to DRIFT — both go RED here, in the same commit that
    moves the bar."""

    def test_verdict_is_alive_and_inert(self):
        cmp_block = LED["_compare"]
        self.assertEqual(cmp_block["_verdict"], "ALIVE_AND_INERT")
        self.assertGreater(cmp_block["_total_vetoes"], 0,
                           "zero total vetoes cannot certify a live seam")

    def test_vetoes_fire_on_every_arm_anti_vacuity(self):
        for name, arm in ARMS:
            self.assertGreater(LED[arm + "_" + name]["vetoes"], 0,
                               f"{arm}/{name}: the seam never fired — the "
                               "byte-identity of this leg is UNPROVEN "
                               "(b189/b193 class)")

    def test_rows_match_the_stored_bar_on_every_arm(self):
        for key, cell in LED["_compare"].items():
            if key.startswith("_"):
                continue
            self.assertTrue(cell["row_matches_stored"],
                            f"{key}: censused trades/exp_R != the stored "
                            "b190/b191 row — the re-price silently moved")

    def test_compare_block_is_reproducible_arithmetic(self):
        # b127 discipline: the stored verdict must re-derive from the
        # census rows plus the two frozen ledgers, no funnel replay.
        mod = _load_probe()
        led190 = json.load(open(NEW_190))
        led191 = json.load(open(NEW_191))
        self.assertEqual(mod.compare_to_stored(LED, led190, led191),
                         LED["_compare"],
                         "compare_to_stored() no longer reproduces the "
                         "stored verdict block")


class TestB194ByteIdentityIsTheReprice(unittest.TestCase):
    """The re-price result itself: b190/b191 ledgers AFTER the b193 seam
    equal the frozen pre-veto copies on every quoted number. This is the
    bar that was re-quoted under the fixed funnel — pinning equality here
    means any future move of these numbers is a decision, not drift."""

    def _strip_meta(self, led):
        return {k: v for k, v in led.items() if not k.startswith("_")}

    def test_b190_bar_unchanged_by_the_veto_fix(self):
        old = json.load(open(PRE_190))
        new = json.load(open(NEW_190))
        self.assertEqual(new["_merit_bar_live_wired"],
                         old["_merit_bar_live_wired"],
                         "the b190 coverage-gated bar moved — b194's "
                         "'byte-identical' finding no longer holds; "
                         "re-quote the backlog")
        for leg in old["_legs"]:
            self.assertEqual(self._strip_meta(new[leg]),
                             self._strip_meta(old[leg]),
                             f"b190 leg {leg} moved")

    def test_b191_m5_entry_ledger_unchanged_by_the_veto_fix(self):
        old = json.load(open(PRE_191))
        new = json.load(open(NEW_191))
        self.assertEqual(new["_merit_bar_m5_entry"], old["_merit_bar_m5_entry"])
        self.assertEqual(new["_band_vs_b190_m15_bar"],
                         old["_band_vs_b190_m15_bar"])
        self.assertTrue(new["M5W0_anchor"]["anchor_ok"],
                        "the b189 integrity anchor broke in the re-run — "
                        "the funnel drifted, not just the veto")

    def test_cited_band_numbers_are_the_repriced_ones(self):
        b190 = json.load(open(NEW_190))["_merit_bar_live_wired"]
        b191 = json.load(open(NEW_191))["_merit_bar_m5_entry"]
        self.assertEqual({k: b190[k] for k in CITED_M15_BAR}, CITED_M15_BAR)
        self.assertEqual({k: b191[k] for k in CITED_M5W_BAND}, CITED_M5W_BAND)


class TestB194SanctionedFunnelOnly(unittest.TestCase):
    """HARD RULE (b190/b191 template): numbers come from run_backtest only,
    and the probe is read-only research."""

    def test_b194_scores_only_through_run_backtest(self):
        src = open(PROBE).read()
        tree = ast.parse(src)
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                names.update(a.name for a in n.names)
            elif isinstance(n, ast.Import):
                names.update(a.name for a in n.names)
        # b194 reaches the funnel as `br.run_backtest(...)` (module-qualified,
        # because it must patch the module attr for the counter) — so the pin
        # is on the CALL SITE, not on a bare import name.
        self.assertIn("br.run_backtest(", src,
                      "b194 must score through run_backtest (the sanctioned "
                      "funnel), qualified or imported")
        self.assertNotIn("backtest_ohlc", names,
                         "b194 must not import the raw engine primitive "
                         "(HARD RULE: no hand-copied funnel)")
        self.assertNotIn("strategy_signal", names,
                         "b194 must not call the funnel directly — that is "
                         "the b81.funnel_fn path b189 proved cannot see the "
                         "trigger")
        self.assertNotIn("strategy_signal(", src)

    def test_b194_probe_is_read_only_research(self):
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

    def test_proxy_delegates_to_the_real_seam(self):
        # The census must MEASURE the shipped seam, not a copy: the proxy
        # body calls the bound original it captured (one-definition rule).
        src = open(PROBE).read()
        self.assertIn("br.apply_smc_merge = proxy", src)
        self.assertIn("fired = real(ctx_arg, merged, **kw)", src)
        self.assertIn("br.apply_smc_merge = real", src,
                      "the proxy must be restored in a finally — a test "
                      "lane that leaks the wrapper changes global state")

    def test_b194_backlog_records_the_item(self):
        text = open(os.path.join(ROOT, "data", "ops",
                                 "autopilot_backlog.md")).read()
        done_line = [ln for ln in text.splitlines()
                     if "b194" in ln and "DONE" in ln]
        self.assertTrue(done_line,
                        "b194 must be marked DONE in the backlog with its "
                        "finding before its ledger's pins run")
        body = " ".join(done_line)
        self.assertIn("ALIVE_AND_INERT", body,
                      "the DONE line must carry the verdict, not just a "
                      "checkmark")


if __name__ == "__main__":
    unittest.main(verbosity=2)
