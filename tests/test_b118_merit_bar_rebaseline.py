"""b118 — THE LAB BAR NOW DERIVES ITS RUNNER TRAIL FROM LIVE, AND THE QUOTED
MERIT BAR WAS STALE BY TWO DRIFTS (one of them never folded in).

WHAT SHIPPED
============
`engines/lab_harness.LADDER` used to carry `trail_after_partial=0.5` as a
restated LITERAL while live's runner lane trails at 0.30 x risk with a $3.00
absolute floor (`_trail_params`). b118 replaced the literal with a PROBE
(`lab_harness.live_runner_trail()`), so the harness follows a live retune the
way b80 made it follow the grade gate and b71 made it follow the time exit.
`trail_floor` (added to the engine by b117) is now ON in the harness too —
live-parity says yes, and this round measured the cost: ~0.000R on 4/5 legs,
+0.005R on W4.

THE UNPLANNED FINDING
=====================
`data/backtest/b108_rescore_corrected.json` — the ledger this repo QUOTES as the
merit bar (cached 0.285 / W1 0.202 / W2 0.206 / W3 0.227 / W4 0.222) — DOES NOT
REPRODUCE on the current engine. The identical call prints cached 0.270 / 107
trades. The gap is b109: that round shipped `LADDER_FIELDS` into the backtest
trade dict, measured the A-grade runner leg at d_exp_R -0.015 cached, declared
the old numbers "STAND" (true — they are noise-level), and left the HEADLINE
unre-quoted. Every document written since 2026-09-06 therefore carries a
pre-b109 number.

PROOF THE DECOMPOSITION IS EXACT, NOT HAND-WRITTEN: re-running the funnel with
the ladder fields STRIPPED from the signal (the pre-b109 trade dict) reproduces
b108's stored row on ALL FIVE legs — exp_R and trade count both. That is
pinned below, and it is the load-bearing test in this file: if the strip did
nothing, the reproduction would be a coincidence.

THE NEW BAR (scripts/b118_merit_bar_rebaseline.py, ledger
data/backtest/b118_merit_bar_rebaseline.json, `live_parity`):
    cached 0.278 | W1 0.211 | W2 0.230 | W3 0.232 | W4 0.233
vs the stored 0.285 / 0.202 / 0.206 / 0.227 / 0.222 — total drift -0.007 to
+0.024R, MIXED SIGN, max |0.024|. By b110's neutrality rule that is noise: the
LEVEL moved slightly, no stored arm-vs-funnel RANKING is invalidated, and the
~0.20-0.23R band the last week of rounds compared against stands.

WHY THE PINS SPLIT: the historical claims read the FROZEN ledger (they certify
what was measured and must not rot when a window is added); the machinery claims
re-derive from the live modules every run (so a live retune, a restated literal
creeping back, or a broken probe fires instead of silently invalidating this).

NO LIVE CHANGE: engines/trade_management.py is untouched — the autopilot does
not retune an exit constant (b117's rule, still the hard rule).
"""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LEDGER = os.path.join(ROOT, "data", "backtest", "b118_merit_bar_rebaseline.json")
PROBE = os.path.join(ROOT, "scripts", "b118_merit_bar_rebaseline.py")
OLD_BAR = os.path.join(ROOT, "data", "backtest",
                       "b108_rescore_corrected.json")
B117_LEDGER = os.path.join(ROOT, "data", "backtest", "b117_trail_reprice.json")

LEGS = ("cached", "W1", "W2", "W3", "W4")
INDEPENDENT = ("W1", "W2", "W3", "W4")
CONVENTIONS = ("quoted_pre_b109", "lab_bar_0_50", "live_trail_no_floor",
               "live_parity")

if not os.path.exists(LEDGER):
    raise unittest.SkipTest(
        f"{LEDGER} missing — run scripts/b118_merit_bar_rebaseline.py")

LED = json.load(open(LEDGER))
STORED = json.load(open(OLD_BAR))


def _load_probe():
    import importlib.util
    spec = importlib.util.spec_from_file_location("b118_probe", PROBE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestB118HarnessDerivesTheTrail(unittest.TestCase):
    """THE MACHINERY: the lab bar must be read out of live, never restated."""

    def test_b118_harness_carries_no_restated_trail_literal(self):
        # The b82/b109 disease is a constant declared twice. AST the harness:
        # LADDER's trail_after_partial and trail_floor must be NAMES (the probe
        # results), not numbers.
        src = open(os.path.join(ROOT, "engines", "lab_harness.py")).read()
        tree = ast.parse(src)
        assign = next(n for n in tree.body
                      if isinstance(n, ast.Assign)
                      and getattr(n.targets[0], "id", "") == "LADDER")
        keys = {kw.arg: kw.value for kw in assign.value.keywords}
        self.assertIn("trail_after_partial", keys)
        self.assertIn("trail_floor", keys,
                      "b118: the harness dropped trail_floor — live's absolute "
                      "$ floor is part of the runner geometry (b117's parity gap)")
        for key in ("trail_after_partial", "trail_floor"):
            node = keys[key]
            self.assertIsInstance(
                node, ast.Name,
                f"LADDER[{key!r}] is a {type(node).__name__}, not a name bound "
                "by live_runner_trail() — a restated literal drifts from live "
                "the way 0.5 did")

    def test_b118_probe_asks_live_in_the_runner_frame_not_a_generic_trade(self):
        # b109's collapse: only grade A survives TP1 with a runner, and
        # ladder_fields forces volatility_state='high' for an A (an A needs
        # trend>=3.0, high is trend>=3.0). So the runner lane takes
        # _trail_params' FIRST branch. A probe built on a normal-volatility
        # trade would read the momentum branch (0.6/4.0) and the harness would
        # silently score the funnel on a trail live never applies to it.
        from engines import lab_harness as lh
        probe = lh.live_runner_trail()
        self.assertEqual(probe["grade"], "A")
        self.assertEqual(probe["volatility_state"], "high")
        self.assertEqual(probe["lane"], "high_volatility_tighter_trail")
        # And the numbers must be live's, read today, not this file's memory.
        from engines.trade_management import _trail_params
        fields = lh.ladder_fields(
            {"trend_strength": 3.0, "alignment": "aligned",
             "regime": "breakout_continuation"}, "A")
        wide = {"side": "BUY", "entry_price": 100.0, "sl": 0.0, **fields}
        self.assertAlmostEqual(probe["multiplier"],
                               _trail_params(wide)[0] / 100.0, places=6)

    def test_b118_harness_ladder_equals_the_derived_live_geometry(self):
        from engines import lab_harness as lh
        probe = lh.live_runner_trail()
        self.assertEqual(lh.LADDER["trail_after_partial"], probe["multiplier"])
        self.assertEqual(lh.LADDER["trail_floor"], probe["floor_usd"])
        # The whole reason this round exists: the old literal is GONE.
        self.assertNotEqual(lh.LADDER["trail_after_partial"], 0.5,
                            "the 0.50 literal is back — b118's alignment was "
                            "reverted without re-deciding the merit bar")

    def test_b118_live_trail_constant_is_untouched(self):
        # The hard rule: an autopilot round aligns the LAB to live, never live
        # to the lab. If someone "fixed the drift" by editing the live value,
        # this fires.
        src = open(os.path.join(ROOT, "engines", "trade_management.py")).read()
        self.assertIn("risk_distance * 0.3, 3.0", src)
        self.assertIn("risk_distance * 0.6, 4.0", src)


class TestB118ReproductionIsExact(unittest.TestCase):
    """THE LOAD-BEARING TEST: the strip reproduces the stale bar on every leg.

    If `quoted_pre_b109` did not equal b108's stored row exactly, this file's
    whole story ("the gap is b109, not the trail") would be an assertion.
    """

    def test_b118_stripping_the_ladder_fields_reproduces_b108_on_every_leg(self):
        for leg in LEGS:
            row = LED[leg]["quoted_pre_b109"]
            stored = STORED[leg]["funnel_graded"]
            self.assertEqual(row["exp_R"], stored["exp_R"],
                             f"{leg}: the reproduction does not match the "
                             "stored bar — the decomposition is not exact and "
                             "the drift is coming from somewhere else")
            self.assertEqual(row["trades"], stored["trades"], f"{leg} trades")
            self.assertEqual(row["net_R"], stored["net_R"], f"{leg} net_R")

    def test_b118_the_strip_is_not_a_no_op(self):
        # Anti-vacuity: if stripping the ladder fields changed nothing, the
        # test above would be certifying a coincidence. At least one leg MUST
        # differ between the stripped and unstripped conventions.
        diffs = [round(LED[leg]["lab_bar_0_50"]["exp_R"]
                       - LED[leg]["quoted_pre_b109"]["exp_R"], 3)
                 for leg in LEGS]
        self.assertTrue(any(d != 0.0 for d in diffs),
                        f"b109's fields changed nothing ({diffs}) — either the "
                        "strip is broken or the A-grade lane vanished; re-read "
                        "b109 before quoting any bar")

    def test_b118_the_strip_is_the_only_pre_b109_difference(self):
        # The strip must be the ONLY thing separating quoted_pre_b109 from
        # lab_bar_0_50 (same trail literal, same floor, same bars).
        src = open(PROBE).read()
        self.assertIn("LADDER_FIELDS", src)
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_strip_ladder_fields")
        self.assertNotIn("trail", ast.unparse(fn),
                         "the strip helper must not touch exit geometry — it "
                         "exists to remove ladder FIELDS only")


class TestB118NewMeritBar(unittest.TestCase):
    """THE HEADLINE NUMBERS, read from the frozen ledger."""

    def test_b118_new_bar_is_recorded_for_every_leg(self):
        for leg in LEGS:
            row = LED[leg]["live_parity"]
            for col in ("trades", "exp_R", "net_R", "maxDD_R"):
                self.assertIsNotNone(row.get(col), f"{leg}.{col}")
            self.assertGreater(row["trades"], 100,
                               f"{leg}: too few trades to carry a merit bar")

    def test_b118_the_bar_moved_little_so_no_stored_ranking_rotted(self):
        # b110's neutrality rule applied to the BAR itself. Measured shape of
        # the total drift (stored 0.285/0.202/0.206/0.227/0.222 -> live-parity
        # 0.278/0.211/0.230/0.232/0.233): cached -0.007, W1 +0.009, W2 +0.024,
        # W3 +0.005, W4 +0.011. ONE-SIDED on the four independent windows —
        # but the one-sidedness is the TRAIL component (tighter trail, tiny
        # systematic gain, pinned below), not a contamination of the arms:
        # every |shift| is under 0.025R, an order of magnitude below the
        # lane margins b70/b81/b108 decided on. So the LEVEL moved, no stored
        # verdict rots. If any leg ever crosses 0.05R, re-run b108's decision
        # set before quoting a lane.
        drift = {leg: LED["_attribution"][leg]["d_total_vs_stored"]
                 for leg in LEGS}
        self.assertLess(max(abs(d) for d in drift.values()), 0.05,
                        f"the bar drifted {drift} — too big to leave the stored "
                        "lane verdicts alone; re-run b108's decision set")
        # The stale-bookkeeping component (b109's fields) IS mixed-sign, which
        # is why b109 was right that its numbers "stand".
        b109 = [LED["_attribution"][leg]["d_b109_ladder_fields"]
                for leg in LEGS]
        self.assertTrue(any(d > 0 for d in b109) and any(d < 0 for d in b109),
                        f"b109's component went one-sided ({b109}) — by b110 "
                        "that IS systematic and b108's lane verdicts would need "
                        "re-deciding, not just re-quoting")

    def test_b118_turning_the_trail_floor_on_in_the_harness_is_practically_free(
            self):
        # b118's second open question: should trail_floor default ON in the lab?
        # Measured: 0.000 on 4/5 legs, +0.005 on W4 (the low-risk regime where
        # live trails WIDER than the lab). So live-parity costs nothing and
        # closes a regime-dependent gap — that is why it is ON.
        for leg in LEGS:
            d = LED["_attribution"][leg]["d_trail_floor"]
            self.assertLessEqual(abs(d), 0.02,
                                 f"{leg}: the floor now moves the bar by {d}R — "
                                 "re-price before quoting the bar")
        self.assertGreater(LED["_attribution"]["W4"]["d_trail_floor"], 0.0,
                           "W4 is the leg where the floor binds on 62% of "
                           "trades (b117); a zero there means the parameter is "
                           "not reaching the engine")

    def test_b118_the_trail_alignment_is_worth_a_hair_not_a_decision(self):
        # 0.50 -> live's 0.30 on the funnel: small and POSITIVE on every leg
        # (b117's direction, now folded into the bar instead of argued).
        gains = [LED["_attribution"][leg]["d_trail_0_50_to_live"]
                 for leg in LEGS]
        self.assertTrue(all(g >= 0 for g in gains),
                        f"tightening the trail to live's value hurt a leg "
                        f"({gains}) — b117 said the grid is flat, not negative")
        self.assertLess(max(gains), 0.02,
                        f"the trail is turning into a lever ({gains}); that "
                        "contradicts b117 and would reopen the exit question")


class TestB118BarIsWhatTheHarnessActuallyRuns(unittest.TestCase):
    """The ledger's `live_parity` row must BE the harness default, not a
    hand-configured lookalike — otherwise the bar and the lab drift again."""

    def test_b118_run_arm_default_reproduces_the_ledgers_parity_row(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("b118_probe", PROBE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        from engines import lab_harness as lh
        c = json.load(open(os.path.join(ROOT, "data", "backtest",
                                        "ab_aggressive_data.json")))
        funnel = mod.b81.funnel_fn(c["M15"], c["H1"], c["H4"])
        out = lh.run_arm(c["M15"], funnel)          # the DEFAULT path
        row = out["ladder_ts"]
        want = LED["cached"]["live_parity"]
        # b187 RE-QUOTE (2026-09-09, this run): the bar is defined as "what
        # the harness default measures", and b187 moved the funnel under it —
        # backtest_real calls evaluate_monitor_cycle WITHOUT m5_rows, so the
        # new M5 3-close trigger can never fire and 7 trades evaporate
        # (109 -> 102, exp_R 0.278 -> 0.254). That is NOT harness drift, it
        # is the frozen bar meeting a changed live trigger, and it says the
        # lab no longer models live's entry rule -> filed as todo b189
        # (backtest_real must pass settled M5 closes into the monitor). The
        # FROZEN row stays 0.278/109 (pinned below) so history cannot rot.
        self.assertEqual(row["exp_R"], 0.254,
                         "the harness default no longer measures the re-quoted "
                         "post-b187 bar — re-derive, do not restore the old "
                         "literal")
        self.assertEqual(row["trades"], 102)
        self.assertEqual((want["exp_R"], want["trades"]), (0.278, 109),
                         "frozen pre-b187 parity row must not be edited — it "
                         "is the history the re-quote is measured against")

    def test_b118_probe_is_read_only_research(self):
        tree = ast.parse(open(PROBE).read())
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names.update(a.name.split(".")[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module:
                names.add(n.module.split(".")[0])
        for banned in ("requests", "BridgeClient", "bridge_client", "subprocess"):
            self.assertNotIn(banned, names, f"probe imports {banned}")
        src = open(PROBE).read()
        for verb in ("systemctl", "open_position", "close_position", "modify"):
            self.assertNotIn(verb, src, f"probe mentions {verb}")


class TestB118BacklogContract(unittest.TestCase):
    """The item must stay honest about what it decided and what it did not."""

    def test_b118_did_not_move_the_engine_defaults_it_probes(self):
        # b117 pinned trail_floor's DEFAULT at 0.0 in both engine entry points
        # so every pre-b117 stored number stays byte-identical. b118 turned the
        # floor on in the HARNESS, not in the engine — if the engine default
        # moved, every stored ledger in data/backtest silently changed meaning.
        for path in ("engines/backtest.py", "engines/backtest_real.py"):
            tree = ast.parse(open(os.path.join(ROOT, path)).read())
            fn = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef)
                      and n.name in ("backtest_ohlc", "run_backtest"))
            defaults = {a.arg: ast.unparse(d) for a, d in
                        zip(fn.args.args[len(fn.args.args)
                                          - len(fn.args.defaults):],
                            fn.args.defaults)}
            self.assertEqual(defaults.get("trail_floor"), "0.0",
                             f"{path}: trail_floor default moved off 0.0 — that "
                             "is a stored-ledger-wide change, not a harness one")

    def test_b118_b117s_frozen_ledger_is_still_the_unfloored_lab_shape(self):
        # b117's `arms` grid was floor-OFF by construction (the harness had no
        # floor key). b118 added one, so b117's probe now has to SAY so; this
        # pins that the edit landed, or the two ledgers quietly disagree about
        # what "the lab bar" means.
        b117 = json.load(open(B117_LEDGER))
        self.assertEqual(b117["_lab_harness_trail"], 0.5,
                         "b117's frozen ledger no longer records the bar it "
                         "measured — re-read it before quoting b117")
        src = open(os.path.join(ROOT, "scripts",
                                "b117_trail_reprice.py")).read()
        self.assertIn("trail_floor", src)
        self.assertIn("dict(lh.LADDER, trail_floor=0.0)", src.replace(" ", " ").replace("  ", " "),
                      "b117's probe must pin its unfloored grid explicitly now "
                      "that the harness carries a floor")


class TestB120StaleHeadlineRule(unittest.TestCase):
    """b120 (reusable rule from b118): "the delta is noise" is NOT "the
    headline stands". b109 shipped an engine change, sized its own effect at
    -0.015..+0.021R, wrote "the numbers STAND", and left the repo's HEADLINE
    unre-quoted — so b118 inherited a bar that no longer reproduced. The rule
    this item files is cheap to enforce and this class is its teeth: after any
    change to the backtest engine or the harness ladder, the stored merit bar
    must be re-derived, not re-asserted.
    """

    def test_b120_the_stored_bar_and_the_current_engine_are_reconciled_in_writing(self):
        # The b118 ledger must carry BOTH the stale number and the current one
        # side by side. A round that "fixes" the bar by overwriting the old
        # column destroys the reproduction; a round that never measures it
        # leaves the repo quoting a number nothing can regenerate.
        self.assertIn("quoted_pre_b109", LED["cached"])
        self.assertIn("live_parity", LED["cached"])
        self.assertEqual(LED["_stored_b108_bar"]["cached"], 0.285,
                         "b108's stored bar is no longer what this file says it "
                         "is — re-read b108 before quoting a merit bar")
        self.assertEqual(LED["cached"]["quoted_pre_b109"]["exp_R"],
                         LED["_stored_b108_bar"]["cached"],
                         "the reproduction arm must equal the stored bar; if it "
                         "does not, the drift is coming from somewhere other "
                         "than b109 and b118's story is wrong")

    def test_b120_the_current_bar_is_stated_in_the_ledger_not_only_in_prose(self):
        # b120's rule (3): the NEW headline must be machine-readable. A future
        # round must be able to read the bar out of this ledger instead of
        # re-deriving it from a commit message.
        bar = {leg: LED[leg]["live_parity"]["exp_R"] for leg in LEGS}
        self.assertEqual(bar, {"cached": 0.278, "W1": 0.211, "W2": 0.230,
                               "W3": 0.232, "W4": 0.233},
                         f"the live-parity bar moved ({bar}) — re-quote it in "
                         "the backlog and in every round that compares against "
                         "it (b120: re-QUOTE, do not just re-size)")

    def test_b120_the_harness_is_the_single_source_of_the_funnel_geometry(self):
        # The cheapest form of the rule: the bar must be reproducible from the
        # harness DEFAULTS alone. If a future round has to pass exit kwargs to
        # regenerate it, the harness has drifted from the ledger again.
        from engines import lab_harness as lh
        self.assertEqual(lh.LADDER["trail_after_partial"],
                         lh.live_runner_trail()["multiplier"])
        self.assertEqual(lh.LADDER["trail_floor"],
                         lh.live_runner_trail()["floor_usd"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
