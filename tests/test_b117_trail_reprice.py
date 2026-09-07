"""b117 — THE b65 TRAIL DECISION WAS PRICED ON A POPULATION THAT NO LONGER EXISTS.

Three runner-trail values were in play and none of them had been priced against
the others under the corrected engine:

  live HEAD      0.30  (engines/trade_management._trail_params, b65 2026-09-03)
  live RUNNING   0.45  (b114: position_daemon booted 17s BEFORE 31c64f7, so
                        production never ran 0.30 once — todo b115)
  the LAB BAR    0.50  (engines/lab_harness.LADDER — the value EVERY funnel
                        number in this repo was measured with)

b65 integrated 0.45 -> 0.30 on the strength of +10.6R (M5 6000 bars), +22.1R
(M15 6000 bars) and both M5 halves. That sweep ran on the PRE-b105 engine, where
`_partial_close_fraction` returned a CONSTANT 1.0 (b108's side finding) and
`engines/backtest.py` kept a PHANTOM full-size runner alive after every TP1
fill. Under that engine the trail touched EVERY trade. Post-b105 a share>=1.0
TP1 close closes the ticket (`tp1_full`), so the only population a trail can act
on is the strong-runner lane, which b109 proved collapses to `setup_grade=='A'`
— ~20-27% of gate-passed signals.

MEASURED (scripts/b117_trail_reprice.py, ledger
data/backtest/b117_trail_reprice.json): same bars, same engine, same harness,
same live grade gate — arms differ ONLY in trail_after_partial.

  * DIRECTION SURVIVES: 0.30 beats 0.45 on net_R in 4/4 independent windows
    (+0.6 / +1.3 / +0.8 / +2.4R) and on exp_R in 3/4.
  * MAGNITUDE IS GONE: the b65 evidence was +10.6..+22.1R; the honest number is
    +0.6..+2.4R per 6000 bars — roughly 1/15th. b65's win was ~93% the phantom
    runner b105 deleted.
  * NOT ONE-SIDED: 0.0 (no trail at all) beats 0.30 on cached exp_R (0.284 vs
    0.278) and W1 (0.227 vs 0.211), while 0.80 wins W1's net_R. By b110's rule a
    mixed-sign response is noise, so the exit grid is FLAT in the trail
    dimension: the trail is not a lever worth pulling, and the real cost of
    leaving b115 un-restarted is ~1R per 6000 bars, not 20R.
  * SECOND GAP: live returns max(risk*mult, $3.00) — an ABSOLUTE floor the lab
    never modelled, so the lab trailed TIGHTER than live on small-risk trades
    (binds on 61.8% of W4's trades, 7.3% cached, 0% W2). engines/backtest.py now
    carries `trail_floor` (default 0.0 = every pre-b117 number unchanged) and
    the ledger scores both grids.

WHY THE PINS SPLIT: the historical claims read the FROZEN ledger (they certify
what was measured and must not rot when the next window is added); the machinery
claims re-derive from the live modules each run (so a retuned trail, a new floor,
or a harness drift fires instead of silently invalidating this file).
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LEDGER = os.path.join(ROOT, "data", "backtest", "b117_trail_reprice.json")
PROBE = os.path.join(ROOT, "scripts", "b117_trail_reprice.py")
B65_LEDGER = os.path.join(ROOT, "data", "backtest", "b65_exit_sweep.json")
B65B_LEDGER = os.path.join(ROOT, "data", "backtest", "b65b_exit_m15.json")

LEGS = ("cached", "W1", "W2", "W3", "W4")
INDEPENDENT = ("W1", "W2", "W3", "W4")
ARMS = ("no_trail_0.00", "live_head_0.30", "live_running_0.45",
        "lab_bar_0.50", "loose_0.60", "loose_0.80")


def _load_ledger() -> dict:
    with open(LEDGER) as fh:
        return json.load(fh)


def _load_probe():
    spec = importlib.util.spec_from_file_location("b117_probe", PROBE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LED = _load_ledger()


class TestB117LedgerShape(unittest.TestCase):
    """The ledger must be the real thing, on the real window set, with every
    arm present — a hand-written summary would let every claim below pass on
    nothing."""

    def test_every_leg_carries_every_arm_in_both_grids(self):
        for leg in LEGS:
            row = LED[leg]
            for grid in ("arms", "floor_arms", "a_grade_arms", "floor_a_grade_arms"):
                self.assertIn(grid, row, f"{leg} missing {grid}")
                self.assertEqual(sorted(row[grid]), sorted(ARMS),
                                 f"{leg}.{grid} arm set changed")
                for name, s in row[grid].items():
                    self.assertIsNotNone(s["exp_R"], f"{leg}.{grid}.{name} exp_R None")
                    self.assertIsNotNone(s["net_R"], f"{leg}.{grid}.{name} net_R None")

    def test_legs_are_the_b76_independent_window_set(self):
        # b110's neutrality test needs >=3 INDEPENDENT windows; the ledger must
        # keep carrying them or the verdict below becomes uncheckable.
        for leg in INDEPENDENT:
            self.assertGreaterEqual(LED[leg]["_bars"], 5000,
                                    f"{leg} is not a full 6000-bar window")
            self.assertGreater(LED[leg]["arms"]["live_head_0.30"]["trades"], 100,
                               f"{leg} has too few trades to price an exit arm")

    def test_probe_reads_the_trail_floor_from_live_and_not_from_a_copy(self):
        # b109's lesson: a restated constant drifts. The probe must PROBE
        # engines/trade_management._trail_params, and the value must still be
        # the one live returns today.
        mod = _load_probe()
        src = open(PROBE).read()
        self.assertIn("_trail_params", src)
        self.assertEqual(mod.trail_floor(), 3.0)
        from engines.trade_management import _trail_params
        t = {"side": "BUY", "entry_price": 0.0, "sl": 0.0,
             "volatility_state": "normal", "momentum_strength": 0.5}
        self.assertEqual(float(_trail_params(t)[0]), mod.trail_floor())


class TestB116BootCommitFrame(unittest.TestCase):
    """b116 (reusable procedure from b114): before quoting LIVE behaviour, ask
    which commit the process that owns the code path BOOTED from. Python binds
    at import and Restart=always only fires after a crash, so "live" means "the
    tree that was HEAD at the last restart" — not the tree on disk.

    This is the b113 frame rule on the TIME axis, and it is the frame THIS
    measurement is argued in: the backlog's own note on b115 says the watchdog
    still runs the pre-b65 0.45R trail. If that claim is wrong, the "cost of not
    restarting" number below is wrong too, so it is pinned to the OS, not to
    prose.
    """

    def test_live_running_trail_is_derived_from_the_boot_commit_not_from_prose(self):
        # The ledger must not ASSERT that live runs 0.45; it must record where
        # the claim came from, and the claim must be re-derivable from the
        # frozen b114 artifact + git.
        self.assertEqual(LED["_live_running_trail_b114"], 0.45)
        self.assertIn("_live_running_trail_b114", LED)
        finding = os.path.join(ROOT, "data", "ops",
                               "daemon_code_drift_b114_finding.json")
        self.assertTrue(os.path.exists(finding),
                        "b114's frozen evidence must survive the b115 restart")
        art = json.load(open(finding))
        pd = art["daemons"]["position_daemon.py"]
        boot = pd["boot_commit"]["sha"]
        # The boot tree must carry 0.45 and the b65 commit must carry 0.30 —
        # read from immutable git objects, never from HEAD (a future retune
        # must not rot this pin).
        import subprocess
        def trail_at(rev: str) -> str:
            out = subprocess.run(
                ["git", "-C", ROOT, "show",
                 f"{rev}:engines/trade_management.py"],
                capture_output=True, text=True, check=True).stdout
            for line in out.splitlines():
                if "balanced_trail" in line and "risk_distance *" in line:
                    return line.strip()
            raise AssertionError(f"no balanced_trail line found in {rev}")
        self.assertIn("0.45", trail_at(boot),
                      "b114's boot tree no longer says 0.45 — the drift claim "
                      "this item is argued in has changed; re-measure")
        self.assertIn("0.3", trail_at("31c64f7"))

    def test_the_lab_bar_differs_from_live_head_so_a_drift_pin_is_needed(self):
        # The reason this item exists: the funnel's headline was scored at 0.50
        # while live HEAD says 0.30. If someone aligns the harness, this fires
        # and the b117 ledger must be re-read (that is a GOOD outcome — it means
        # the lab finally matches live).
        from engines import lab_harness as lh
        from engines.trade_management import _trail_params
        t = {"side": "BUY", "entry_price": 100.0, "sl": 90.0,
             "volatility_state": "normal", "momentum_strength": 0.5}
        live_mult = _trail_params(t)[0] / abs(100.0 - 90.0)
        self.assertNotAlmostEqual(live_mult, lh.LADDER["trail_after_partial"],
                                  places=2,
                                  msg="lab harness trail now matches live HEAD — "
                                      "re-baseline the merit bar (b118) and retire "
                                      "this drift pin with a named edit, not a delete")


class TestB117DirectionSurvivesMagnitudeGone(unittest.TestCase):
    """THE HEADLINE: b65's ordering stands, b65's evidence does not."""

    def test_b117_tighter_trail_still_wins_net_R_on_every_independent_window(self):
        # 0.30 (live HEAD) vs 0.45 (what production actually ran per b114).
        wins = [leg for leg in INDEPENDENT
                if LED[leg]["arms"]["live_head_0.30"]["net_R"]
                > LED[leg]["arms"]["live_running_0.45"]["net_R"]]
        self.assertEqual(len(wins), 4,
                         f"b65's direction must hold on all four windows, won on {wins}")

    def test_b117_the_measured_effect_is_an_order_of_magnitude_smaller_than_b65s(self):
        # b65's own ledgers: trail .3 vs the .5 baseline it compared against.
        b65 = json.load(open(B65_LEDGER))
        b65_m5 = (b65["live + tight trail .3"]["total_r"]
                  - b65["live ladder TP1=.5R/50%/trail.5"]["total_r"])
        self.assertGreater(b65_m5, 10.0,
                           "b65's M5 evidence is no longer the +10.6R this item "
                           "was filed against — re-read the founding claim")
        b65b = json.load(open(B65B_LEDGER))
        b65_m15 = b65b["trail .3"]["total_r"] - b65b["live ladder trail.5"]["total_r"]
        self.assertGreater(b65_m15, 20.0)
        # Honest effect: 0.30 vs 0.45 per window, and vs the lab's 0.50.
        deltas = [LED[leg]["arms"]["live_head_0.30"]["net_R"]
                  - LED[leg]["arms"]["live_running_0.45"]["net_R"] for leg in INDEPENDENT]
        self.assertLess(max(deltas), 5.0,
                        f"the honest trail effect must stay small: {deltas}")
        self.assertLess(sum(deltas) / len(deltas), b65_m5 / 4.0,
                        "the honest mean effect must remain far below b65's "
                        "claimed per-window gain")

    def test_b117_the_trail_is_not_a_lever_flat_response_across_the_grid(self):
        # b110's neutrality test: if the trail were a real lever, the response
        # would be one-sided. It is not — the best arm differs by leg and by
        # metric, so no retune earns a live change.
        best_exp = {leg: max(ARMS, key=lambda a: LED[leg]["arms"][a]["exp_R"])
                    for leg in LEGS}
        best_net = {leg: max(ARMS, key=lambda a: LED[leg]["arms"][a]["net_R"])
                    for leg in LEGS}
        self.assertGreater(len(set(best_exp.values())), 1,
                           f"a single arm dominating every leg would mean the "
                           f"trail IS a lever: {best_exp}")
        self.assertGreater(len(set(best_net.values())), 1,
                           f"see above (net_R): {best_net}")
        # And the incumbent is not the best on cached exp_R — the no-trail
        # control wins there, which is the loudest single statement of flatness.
        self.assertEqual(best_exp["cached"], "no_trail_0.00")

    def test_b117_no_live_change_shipped(self):
        # This item is measurement. The live trail and the lab bar must both be
        # exactly where they were, or the run silently wired a retune.
        src = open(os.path.join(ROOT, "engines", "trade_management.py")).read()
        self.assertIn("risk_distance * 0.3", src)
        self.assertNotIn("risk_distance * 0.35", src)
        from engines import lab_harness as lh
        self.assertEqual(lh.LADDER["trail_after_partial"], 0.5)


class TestB117RunnerPopulation(unittest.TestCase):
    """WHY the effect collapsed: the trail can only reach a trade that survives
    TP1 with a runner, and post-b105 that is the A-grade lane only."""

    def test_b117_only_a_minority_of_gate_passed_signals_reach_a_trail(self):
        for leg in LEGS:
            rc = LED[leg]["runner_census"]
            self.assertGreater(rc["gate_passed_signals"], 100,
                               f"{leg}: nothing was censused")
            self.assertLess(rc["runner_share"], 0.35,
                            f"{leg}: the runner population grew past 35% — the "
                            "collapse finding (b109) no longer bounds the trail's "
                            "reach, so this item's magnitude claim must be re-priced")
            self.assertGreater(rc["signals_with_runner_leg"], 0)

    def test_b117_the_runner_census_matches_the_live_share_function_directly(self):
        # Anti-vacuity: the census is a claim about _partial_close_fraction's
        # output, so recompute one leg's share from the function itself.
        from engines.trade_management import _partial_close_fraction
        mod = _load_probe()
        c = json.load(open(os.path.join(ROOT, "data", "backtest",
                                        "ab_aggressive_data.json")))
        rc = mod.runner_census(c["M15"], c["H1"], c["H4"])
        self.assertEqual(rc["gate_passed_signals"],
                         LED["cached"]["runner_census"]["gate_passed_signals"])
        # And the lane really is A-only: a B-grade signal must return share 1.0.
        b = {"setup_grade": "B", "momentum_strength": 0.9, "rr_remaining": 2.0,
             "structure_state": "healthy"}
        self.assertEqual(_partial_close_fraction(b)[0], 1.0)
        a = dict(b, setup_grade="A")
        self.assertLess(_partial_close_fraction(a)[0], 1.0)


class TestB117TrailFloorParityGap(unittest.TestCase):
    """THE SECOND GAP: live's absolute $ floor is not in the lab's default
    geometry, so the lab trails TIGHTER than live on small-risk trades."""

    def test_b117_engine_default_leaves_every_pre_b117_number_unchanged(self):
        # trail_floor must default to 0.0 in BOTH entry points, and the trail
        # branch must be max(mult*risk, floor) — a bare mult would silently
        # re-tighten live-parity arms.
        for path in ("engines/backtest.py", "engines/backtest_real.py"):
            tree = ast.parse(open(os.path.join(ROOT, path)).read())
            fn = next(n for n in ast.walk(tree)
                      if isinstance(n, (ast.FunctionDef,))
                      and n.name in ("backtest_ohlc", "run_backtest"))
            defaults = {a.arg: ast.unparse(d) for a, d in
                        zip(fn.args.args[len(fn.args.args) - len(fn.args.defaults):],
                            fn.args.defaults)}
            self.assertEqual(defaults.get("trail_floor"), "0.0",
                             f"{path}: trail_floor default moved off 0.0 — every "
                             "stored funnel number is now scored on different "
                             "geometry (that is b118's decision, not this run's)")
        bt = open(os.path.join(ROOT, "engines/backtest.py")).read()
        self.assertIn("max(trail_after_partial * risk, trail_floor)", bt)

    def test_b117_floor_binds_on_a_minority_but_on_W4_it_binds_on_the_majority(self):
        # The gap is invisible on most legs and dominant on W4 — that is the
        # shape of a regime-dependent parity bug, so both ends are pinned.
        fc = {leg: LED[leg]["floor_bind_census"] for leg in LEGS}
        self.assertEqual(fc["W2"]["floor_binds"], 0)
        self.assertGreater(fc["W4"]["floor_bind_share"], 0.5,
                           "W4's floor binding is the evidence that the lab's "
                           "trail geometry is regime-dependent; if it shrank, "
                           "re-read this item")
        self.assertLess(fc["cached"]["floor_bind_share"], 0.15)
        for leg in LEGS:
            self.assertGreaterEqual(fc[leg]["floor_usd"], 3.0)

    def test_b117_modelling_the_floor_does_not_change_the_verdict(self):
        # The floor must not smuggle in a new "best arm": with live's real
        # geometry the grid stays flat too.
        for leg in LEGS:
            best = max(ARMS, key=lambda a: LED[leg]["floor_arms"][a]["exp_R"])
            spread = (max(LED[leg]["floor_arms"][a]["exp_R"] for a in ARMS)
                      - min(LED[leg]["floor_arms"][a]["exp_R"] for a in ARMS))
            self.assertLess(spread, 0.06,
                            f"{leg}: the floored grid is no longer flat "
                            f"({spread}R spread) — the trail may be a lever after all")
            self.assertIn(best, ARMS)

    def test_b117_floor_grid_is_a_real_run_not_a_copy_of_the_unfloored_grid(self):
        # Anti-vacuity: on W4, where the floor binds on 62% of trades, the two
        # grids MUST differ. Identical numbers would mean trail_floor is dead
        # code that never reaches the engine.
        self.assertNotEqual(LED["W4"]["arms"]["live_head_0.30"]["net_R"],
                            LED["W4"]["floor_arms"]["live_head_0.30"]["net_R"],
                            "trail_floor had no effect on the leg where it binds "
                            "most — the parameter is not wired")
        self.assertEqual(LED["W2"]["arms"]["live_head_0.30"]["net_R"],
                         LED["W2"]["floor_arms"]["live_head_0.30"]["net_R"],
                         "W2 has ZERO floor-bound trades, so the floored grid "
                         "must be identical there")


class TestB117ProbeIsReadOnly(unittest.TestCase):
    """The b115 discipline: a research probe must never touch the live path."""

    def test_b117_probe_imports_no_bridge_and_shells_out_to_nothing(self):
        tree = ast.parse(open(PROBE).read())
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names.update(a.name.split(".")[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module:
                names.add(n.module.split(".")[0])
        for banned in ("requests", "BridgeClient", "bridge_client", "subprocess",
                       "os.system"):
            self.assertNotIn(banned, names, f"probe imports {banned}")
        src = open(PROBE).read()
        for verb in ("systemctl", "restart", "open_position", "close_position",
                     "modify"):
            self.assertNotIn(verb, src, f"probe mentions {verb}")

    def test_b117_does_not_restart_the_daemons_it_prices(self):
        # The whole point of b115 is that the autopilot does not restart live
        # services. If b117's measurement had been used to justify one, this
        # pin is the tripwire.
        art = json.load(open(os.path.join(
            ROOT, "data", "ops", "daemon_code_drift_b114_finding.json")))
        self.assertTrue(art["daemons"]["position_daemon.py"]["drift"],
                        "b114's frozen evidence must still show the drift it "
                        "recorded; if a restart happened, the artifact is intact "
                        "and this pin must be re-pointed at the FROZEN boot, not "
                        "deleted")


if __name__ == "__main__":
    unittest.main(verbosity=2)
