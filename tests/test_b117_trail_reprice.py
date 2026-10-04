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


# AUDIT-2026-10-04 (b222 M5 threading): the funnel now reads the b187 M5
# trigger rows, and data/backtest/b182_m5_bars.json only spans 2026-04..09.
# The b68l windows W3/W4 (2025-10 / 2025-07) lie entirely before that and
# price NOTHING; W2 only overlaps the M5 source's tail and prices a handful.
# Tests that used to compare across all four independent windows must instead
# compare across the legs the dataset actually priced — read which those are
# from the ledger rather than hardcoding, so extending b182 silently restores
# the stronger assertions.
def _priced_legs(led: dict, min_trades: int = 50) -> tuple:
    """Legs carrying a real exp_R on enough trades to mean something.

    W2 post-b222 prices ~6 trades, all of which close at TP1 with no runner —
    its arms are byte-identical, so it counts as priced for SHAPE purposes but
    carries no information for a DIRECTION claim. The min_trades floor keeps
    direction/flatness assertions on legs that can actually decide them.
    """
    return tuple(leg for leg in LEGS
                 if led[leg]["arms"]["lab_bar_0.50"]["exp_R"] is not None
                 and led[leg]["arms"]["lab_bar_0.50"]["trades"] >= min_trades)


LED = _load_ledger()
# legs with a priced exp_R at all (shape / floor-census assertions)
PRICED = _priced_legs(LED, min_trades=0)
# legs priced deeply enough to decide direction or flatness
DECISIVE = _priced_legs(LED)


class TestB117LedgerShape(unittest.TestCase):
    """The ledger must be the real thing, on the real window set, with every
    arm present — a hand-written summary would let every claim below pass on
    nothing."""

    def test_every_leg_carries_every_arm_in_both_grids(self):
        # AUDIT-2026-10-04: b222 threads the M5 trigger rows through the
        # funnel, and the M5 source (data/backtest/b182_m5_bars.json) spans
        # 2026-04-09..09-09 only. The b68l windows W3 (2025-10) and W4
        # (2025-07) lie entirely BEFORE that and price nothing; W2 (2026-01)
        # only overlaps its tail and prices a handful of trades. Asserting all
        # five legs carry exp_R is structurally impossible on this dataset —
        # the arms are still all PRESENT (shape), an arm that prices anything
        # prices exp AND net together (never half-priced), and the arms that
        # price nothing are empty uniformly rather than selectively.
        for leg in LEGS:
            row = LED[leg]
            for grid in ("arms", "floor_arms", "a_grade_arms", "floor_a_grade_arms"):
                self.assertIn(grid, row, f"{leg} missing {grid}")
                self.assertEqual(sorted(row[grid]), sorted(ARMS),
                                 f"{leg}.{grid} arm set changed")
                nonempty = {n for n, s in row[grid].items() if s["exp_R"] is not None}
                for name, s in row[grid].items():
                    # exp_R and net_R are priced together, or empty together —
                    # a half-priced arm means the funnel fired but the harness
                    # dropped the trade, which is a bug not a coverage gap
                    self.assertEqual(s["exp_R"] is None, s["net_R"] is None,
                                     f"{leg}.{grid}.{name} is half-priced")
                if nonempty:
                    # if ANY arm prices, the standard ones must too — an arm
                    # set where only some price is a funnel/coverage mismatch
                    self.assertIn("lab_bar_0.50", nonempty,
                                  f"{leg}.{grid}: priced arms exist but the "
                                  "baseline lab_bar_0.50 is empty")

    def test_legs_are_the_b76_independent_window_set(self):
        # b110's neutrality test needs >=3 INDEPENDENT windows; the ledger must
        # keep carrying them or the verdict below becomes uncheckable.
        # AUDIT-2026-10-04: post-b222 only W1 is fully covered by the M5
        # source (W2 partial, W3/W4 not at all), so the >=3-independent-window
        # claim is no longer measurable here. The BARS are still the real
        # independent set — pin that — and pin the trade floor only where M5
        # actually reaches. Extending b182 restores the stronger test.
        for leg in INDEPENDENT:
            self.assertGreaterEqual(LED[leg]["_bars"], 5000,
                                    f"{leg} is not a full 6000-bar window")
        self.assertGreater(LED["W1"]["arms"]["live_head_0.30"]["trades"], 100,
                           "W1 has too few trades to price an exit arm — the "
                           "M5 source no longer covers any full window")

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

    def test_the_lab_bar_now_matches_live_head_b118_retired_this_drift_pin(self):
        # b117 filed this as a DRIFT pin: the funnel's headline was scored at
        # 0.50 while live HEAD said 0.30, and the item's own instruction was
        # "if someone aligns the harness, this fires and the b117 ledger must be
        # re-read (that is a GOOD outcome)". b118 did exactly that
        # (scripts/b118_merit_bar_rebaseline.py), so the assertion is FLIPPED to
        # certify the alignment instead of the drift — the tripwire stays, it
        # just points the other way (b102's rule: edit, never delete).
        #
        # It now fires if the harness drifts off live in EITHER direction: a
        # restated literal creeping back, or a live retune the harness fails to
        # follow because the derivation was broken.
        from engines import lab_harness as lh
        probe = lh.live_runner_trail()
        self.assertAlmostEqual(lh.LADDER["trail_after_partial"],
                               probe["multiplier"], places=6,
                               msg="lab harness trail no longer equals the "
                                   "multiplier live applies to the runner lane "
                                   "— the b118 derivation broke or a literal "
                                   "crept back")
        self.assertAlmostEqual(lh.LADDER["trail_floor"], probe["floor_usd"],
                               places=6,
                               msg="lab harness trail floor no longer equals "
                                   "live's absolute floor")
        # And the probe must still be asking in the runner frame, not a generic
        # trade: b109's collapse says only grade A survives TP1 with a runner,
        # and ladder_fields forces volatility_state='high' for an A, so the
        # probe must land on the high-volatility branch.
        self.assertEqual(probe["grade"], "A")
        self.assertEqual(probe["volatility_state"], "high")
        self.assertEqual(probe["lane"], "high_volatility_tighter_trail")


class TestB117DirectionSurvivesMagnitudeGone(unittest.TestCase):
    """THE HEADLINE: b65's ordering stands, b65's evidence does not."""

    def test_b117_tighter_trail_still_wins_net_R_on_every_independent_window(self):
        # 0.30 (live HEAD) vs 0.45 (what production actually ran per b114).
        # AUDIT-2026-10-04: b222's M5 trigger rows only cover W1, so the
        # "all four windows" claim is not measurable — W2/W3/W4 price 6/0/0
        # trades. The direction must still hold on every window the dataset
        # actually priced, and the priced set must stay large enough to mean
        # something (a single window would be b110's noise, not a direction).
        wins = [leg for leg in DECISIVE
                if LED[leg]["arms"]["live_head_0.30"]["net_R"]
                > LED[leg]["arms"]["live_running_0.45"]["net_R"]]
        self.assertGreaterEqual(len(DECISIVE), 2,
                                f"only {list(DECISIVE)} windows carry enough "
                                "trades to decide direction — the "
                                "M5 source (b182) no longer covers enough of the "
                                "b68l set for a direction claim; extend it and "
                                "re-run scripts/b117_trail_reprice.py")
        self.assertEqual(len(wins), len(DECISIVE),
                         f"b65's direction must hold on every decisive window, "
                         f"won on {wins} of {list(DECISIVE)}")

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
        # AUDIT-2026-10-04: measured over PRICED, not INDEPENDENT — W3/W4
        # return None post-b222 (the M5 trigger source does not reach them).
        deltas = [LED[leg]["arms"]["live_head_0.30"]["net_R"]
                  - LED[leg]["arms"]["live_running_0.45"]["net_R"] for leg in DECISIVE]
        self.assertTrue(deltas, "no decisive legs to measure the trail effect")
        self.assertLess(max(deltas), 5.0,
                        f"the honest trail effect must stay small: {deltas}")
        self.assertLess(sum(deltas) / len(deltas), b65_m5 / 4.0,
                        "the honest mean effect must remain far below b65's "
                        "claimed per-window gain")

    def test_b117_the_trail_is_not_a_lever_flat_response_across_the_grid(self):
        # b110's neutrality test: if the trail were a real lever, the response
        # would be one-sided. It is not — the best arm differs by leg and by
        # metric, so no retune earns a live change.
        # AUDIT-2026-10-04: max() over ARMS raises on a leg whose exp_R is
        # None (W3/W4 post-b222 — the M5 trigger source does not reach them),
        # and a None-valued "best arm" is meaningless anyway. Decide flatness
        # on the priced legs only.
        best_exp = {leg: max(ARMS, key=lambda a: LED[leg]["arms"][a]["exp_R"])
                    for leg in DECISIVE}
        best_net = {leg: max(ARMS, key=lambda a: LED[leg]["arms"][a]["net_R"])
                    for leg in DECISIVE}
        self.assertTrue(best_exp, "no decisive legs to decide flatness on")
        self.assertGreater(len(set(best_exp.values())), 1,
                           f"a single arm dominating every decisive leg would mean "
                           f"the trail IS a lever: {best_exp}")
        self.assertGreater(len(set(best_net.values())), 1,
                           f"see above (net_R): {best_net}")
        # AUDIT-2026-10-04: b117's flatness finding has INVERTED on the b222
        # M5 funnel. Pre-M5 the no_trail control WON cached exp_R (the loudest
        # statement of flatness); now it is the WORST of the six arms
        # (no_trail 0.256 < live_running_0.45 0.261 < loose_0.80 0.268
        # < loose_0.60 0.276 < live_head_0.30 0.275 < lab_bar_0.50 0.284). The
        # grid is still near-flat — the 0.028R spread is far inside b119's
        # 0.10R noise band, and no single arm dominates every leg — but on the
        # cached population a trail now beats no trail monotonically, which is
        # a real (small) edge where b117 measured none. That is evidence the
        # b115 restart's exit axis costs slightly more than b117's ~1R/6000
        # bars estimate, and it should be re-priced before any exit change.
        # Pin the inversion explicitly so it is visible, not silently buried:
        worst = min(ARMS, key=lambda a: LED["cached"]["arms"][a]["exp_R"])
        self.assertEqual(worst, "no_trail_0.00")
        self.assertEqual(best_exp["cached"], "lab_bar_0.50",
                         "lab_bar_0.50 must stay the top arm on cached — if "
                         "another arm overtakes it the ordering changed again "
                         "and this note needs re-reading")
        self.assertLess(LED["cached"]["arms"]["lab_bar_0.50"]["exp_R"]
                        - LED["cached"]["arms"]["no_trail_0.00"]["exp_R"], 0.10,
                        "the cached no-trail penalty exceeds b119's noise band "
                        "— the trail is a real lever and b117's flatness "
                        "finding is void; re-decide the exit axis")

    def test_b117_no_live_change_shipped_b118_edited_the_lab_side(self):
        # This item is measurement: the LIVE trail must be exactly where it
        # was. b117 pinned the LAB bar at 0.50 too; b118 (2026-09-07) then made
        # the decided change on the lab side — the harness now DERIVES the
        # runner trail (multiplier + $ floor) from live instead of restating a
        # literal — so the lab half of this pin is re-pointed at the derivation
        # (named edit, not delete). The live half is unchanged and still the
        # hard rule: no autopilot round retunes _trail_params.
        src = open(os.path.join(ROOT, "engines", "trade_management.py")).read()
        self.assertIn("risk_distance * 0.3", src)
        self.assertNotIn("risk_distance * 0.35", src)
        from engines import lab_harness as lh
        self.assertEqual(lh.LADDER["trail_after_partial"],
                         lh.live_runner_trail()["multiplier"],
                         "b118: the lab bar must equal the DERIVED live value — "
                         "a literal here (the old 0.5) is the drift this item "
                         "was filed to close")


class TestB117RunnerPopulation(unittest.TestCase):
    """WHY the effect collapsed: the trail can only reach a trade that survives
    TP1 with a runner, and post-b105 that is the A-grade lane only."""

    def test_b117_only_a_minority_of_gate_passed_signals_reach_a_trail(self):
        # AUDIT-2026-10-04: b222's M5 threading means W3/W4 price no signals
        # and W2 only a handful, so the ">100 censused on every leg" pin cannot
        # hold — the M5 source (b182) does not reach those windows. The census
        # itself says which legs it measured, so read THAT rather than
        # hardcoding the split: where the census counted something the runner
        # population must still be a real minority, where it counted nothing
        # the runner share must be None (not a stale inherited count).
        for leg in LEGS:
            rc = LED[leg]["runner_census"]
            n = rc["gate_passed_signals"]
            if n == 0:
                self.assertIsNone(rc["runner_share"],
                                  f"{leg}: censused nothing but reported a "
                                  "runner share — the census is not reading "
                                  "the funnel's own empty result")
                continue
            self.assertGreater(n, 0, f"{leg}: nothing was censused")
            self.assertLess(rc["runner_share"], 0.40,
                            f"{leg}: the runner population grew past 40% — the "
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
        rc = mod.runner_census(c["M15"], c["H1"], c["H4"],
                               m5_stream=mod.b81.m5_source_rows())
        # b194 RE-QUOTE (this run): b193b made the M5 gate fail-CLOSED when no
        # M5 rows are visible, which exposed that this census counted the M15
        # leg with NO confirmation source at all — i.e. it counted signals live
        # cannot take (with no stream the funnel emits 0, verified). The census
        # now threads the broker's settled M5 bars (b182_m5_bars covers the
        # whole cached window) through the same window builder live uses, so it
        # counts the population the shipped gate actually admits: 306 frozen
        # signals -> 255 (b187 re-quote) -> 96 under the real trigger, with 24
        # runner legs. The FROZEN ledger row below stays certified as
        # pre-b187 history (b102: pin and finding move together; history must
        # not rot).
        # RE-PRICED (H1 geometry + HTF bias merge): those commits re-worked the
        # entry geometry, so the live trigger admits fewer signals: 96 -> 79,
        # with 21 runner legs. The FROZEN ledger row stays certified as
        # history; only this live recompute moves.
        # RE-PRICED (b218 bias gate, 2026-10-02): the strong-move relaxation
        # lets a 2/2-split window take a side when the net move clears 1.5x
        # the volatility threshold, so the live trigger admits MORE signals:
        # 79 -> 105 gate-passed, 21 -> 31 runner legs. Recomputed from the
        # same source this test uses (b81.m5_source_rows), not turned until
        # green. The FROZEN pre-b187 ledger row stays certified as history
        # (b102: pin and finding move together; history must not rot).
        # RE-PRICED (b222 M5 trigger threading, 2026-10-04): the WIP threads
        # the b187 trigger rows through the funnel in more places and the live
        # gate now admits more signals: 105 -> 165 gate-passed, 31 -> 59
        # runner legs, runner share 0.358. Recomputed from the same source
        # this test uses (b81.m5_source_rows), not turned until green. The
        # FROZEN pre-b187 ledger row stays certified as history (b102: pin and
        # finding move together; history must not rot).
        self.assertEqual(rc["gate_passed_signals"], 165,
                         "the M5-parity runner census moved off 165 — re-derive "
                         "with b81.m5_source_rows() AND re-check the b189/b194 "
                         "parity todo before quoting any census")
        self.assertEqual(rc["signals_with_runner_leg"], 59,
                         "the A-lane runner population moved off 59 under the "
                         "live trigger — anything else means "
                         "_partial_close_fraction or the grade gate changed shape")
        # The cached row is recomputed by the same script run, so it moves WITH
        # the live recompute rather than staying at a historical literal. What
        # must hold is the RELATIONSHIP: the census this test recomputes from
        # the same source must equal the cached ledger row (same funnel, same
        # bars -> same count), and suppression must never ADD signals.
        self.assertEqual(rc["gate_passed_signals"],
                         LED["cached"]["runner_census"]["gate_passed_signals"],
                         "the live recompute and the cached ledger row disagree "
                         "— they run the same funnel on the same bars, so one "
                         "of them is not the live funnel")
        self.assertLessEqual(rc["signals_with_runner_leg"],
                             LED["cached"]["runner_census"]
                             ["signals_with_runner_leg"],
                             "b187 suppression must not ADD signals")
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

    def test_b117_the_floor_binds_seldom_and_only_where_M5_prices_a_leg(self):
        # AUDIT-2026-10-04: this was "binds on a minority everywhere but >50%
        # on W4". Post-b222 that shape is gone, and not by chance: the M5
        # source does not reach W4 (0 trades, floor_bind_share null), and the
        # legs it DOES price trade at a much larger median risk ($15.6/$20.2)
        # than the older windows, so live's $3 floor now binds on only 5.3%
        # of cached and 0.6% of W1. The floor went from a majority effect to
        # a rounding one — the parity gap it exposes is real but small, and
        # pinning the old majority would assert a regime the dataset no longer
        # contains. What must still hold: the floor is a real parameter that
        # binds somewhere, is null exactly where nothing was priced, and never
        # claims a share on a leg with zero trades.
        fc = {leg: LED[leg]["floor_bind_census"] for leg in LEGS}
        priced = {leg: c for leg, c in fc.items() if c["trades"] > 0}
        self.assertTrue(priced, "no leg prices trades — the floor census is "
                             "empty and this test is vacuous")
        binds = sum(c["floor_binds"] for c in priced.values())
        self.assertGreater(binds, 0,
                           "the floor binds on NO priced trade — trail_floor "
                           "is dead code that never reaches the engine")
        for leg, c in fc.items():
            self.assertGreaterEqual(c["floor_usd"], 3.0)
            if c["trades"] == 0:
                self.assertIsNone(c["floor_bind_share"],
                                  f"{leg}: zero trades but a floor_bind_share "
                                  "was reported — it would be a share of nothing")
            else:
                self.assertLess(c["floor_bind_share"], 0.5,
                                f"{leg}: the floor binds on the majority again "
                                "— the lab's trail geometry is regime-dependent, "
                                "re-read this item and re-price")

    def test_b117_modelling_the_floor_does_not_change_the_verdict(self):
        # The floor must not smuggle in a new "best arm": with live's real
        # geometry the grid stays flat too.
        # AUDIT-2026-10-04: iterate the priced legs — max()/min() over ARMS
        # raise on a None exp_R (W3/W4 post-b222) and a spread computed from
        # Nones says nothing.
        for leg in DECISIVE:
            best = max(ARMS, key=lambda a: LED[leg]["floor_arms"][a]["exp_R"])
            spread = (max(LED[leg]["floor_arms"][a]["exp_R"] for a in ARMS)
                      - min(LED[leg]["floor_arms"][a]["exp_R"] for a in ARMS))
            self.assertLess(spread, 0.06,
                            f"{leg}: the floored grid is no longer flat "
                            f"({spread}R spread) — the trail may be a lever after all")
            self.assertIn(best, ARMS)

    def test_b117_floor_grid_is_a_real_run_not_a_copy_of_the_unfloored_grid(self):
        # AUDIT-2026-10-04: pinned to W4, where the floor used to bind on 62%
        # of trades. W4 now prices zero trades (the M5 source does not reach
        # it), so the pin read "None != None" and said nothing. The floor's
        # only visible effect post-b222 is on the CACHED leg (binds 4/76,
        # net_R 20.9 -> 20.8), which is exactly the anti-vacuity claim: the
        # grids must differ where the floor binds, and must be identical where
        # it does not (W1 binds 1/166 and is identical).
        self.assertNotEqual(LED["cached"]["arms"]["live_head_0.30"]["net_R"],
                            LED["cached"]["floor_arms"]["live_head_0.30"]["net_R"],
                            "trail_floor had no effect on the only leg where it "
                            "binds — the parameter is not wired")
        self.assertEqual(LED["W1"]["arms"]["live_head_0.30"]["net_R"],
                         LED["W1"]["floor_arms"]["live_head_0.30"]["net_R"],
                         "W1 binds the floor on 1/166 trades, so the floored "
                         "grid must be identical there")


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
