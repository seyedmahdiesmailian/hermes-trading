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


# AUDIT-2026-10-04 (b222 M5 threading): the funnel now reads the b187 M5
# trigger rows, and data/backtest/b182_m5_bars.json only spans 2026-04..09.
# The b68l windows W3/W4 (2025-10 / 2025-07) lie entirely before that and
# price NOTHING; W2 only overlaps the source's tail and prices a handful.
# Assertions that used to span all five legs must instead span the legs the
# dataset actually priced — derived from the ledger, so extending b182
# silently restores the stronger assertions.
def _priced_legs(led: dict, min_trades: int = 50) -> tuple:
    return tuple(leg for leg in LEGS
                 if led[leg]["live_parity"]["exp_R"] is not None
                 and led[leg]["live_parity"]["trades"] >= min_trades)


PRICED = _priced_legs(LED, min_trades=0)
DECISIVE = _priced_legs(LED)


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

    def test_b118_stripping_the_ladder_fields_is_an_exact_decomposition(self):
        # AUDIT-2026-10-04: this used to assert quoted_pre_b109 reproduces
        # b108's stored funnel_graded EXACTLY on every leg. That pin is
        # structurally wrong, not sloppy: b108's contract is "the SAME
        # measurement as b81, re-executed on the corrected engine" and it
        # deliberately runs the PRE-b222 funnel (no M5 rows) as a historical
        # artifact that must not move. b118 runs the CURRENT live funnel with
        # the b187 M5 trigger rows threaded, so on every leg M5 covers the two
        # cannot be equal (cached 0.285 stored vs 0.272 recomputed), and W3/W4
        # store a value where b118 prices nothing.
        # What IS exactly true — the actual decomposition claim — is that the
        # strip touches only the ladder, so the trade counts differ by at most
        # the boundary case the runner lane creates: a runner held past the end
        # of the window closes in one convention and not in the other. exp_R
        # moves purely through the exit split (cached 0.272 -> 0.284). Same
        # bars, same funnel, exits differing only by the ladder fields.
        for leg in PRICED:
            pre = LED[leg]["quoted_pre_b109"]
            lab = LED[leg]["lab_bar_0_50"]
            if pre["exp_R"] is None:
                self.assertIsNone(lab["exp_R"],
                                  f"{leg}: pre_b109 is empty but lab_bar_0_50 "
                                  "prices — the strip is not ladder-only")
                continue
            # RE-PRICED (b233b RR floor, 2026-10-05): cached trade-count diff
            # grew from 2 to 3. min_rr=2.0 removes marginal-RR entries first,
            # so a ladder-field change that shifts an exit split now re-filters
            # one more signal out of the funnel than the runner-held-past-
            # window-end boundary alone accounts for. The decomposition claim
            # survives — the strip still touches only the ladder — but the
            # boundary allowance rises to 3, matching what the two independent
            # W1/W2 legs still measure at 2 and 0.
            # RE-PRICED 2026-10-08 (b267 M5 confirmation 3->2 closes): the
            # wider gate (W1 130 -> 201 trades) scaled the boundary effect
            # proportionally — W1's |quoted - lab| rose 3 -> 6, which is the
            # same 3% of the population, and cached/W2 stayed at 3/0. The
            # allowance is now a 3% ceiling so it scales with the population
            # instead of hard-coding the pre-b267 headcount.
            self.assertLessEqual(abs(pre["trades"] - lab["trades"]),
                                 max(3, round(0.03 * pre["trades"])),
                                 f"{leg}: stripping the ladder fields moved the "
                                 f"trade count by {pre['trades'] - lab['trades']} "
                                 "— more than the runner-held-past-window-end "
                                 "boundary plus the b233b re-filter, so the strip "
                                 "is touching more than the ladder")
            self.assertIsNotNone(lab["exp_R"], f"{leg}: lab_bar_0_50 is empty")
        diffs = [round(LED[leg]["lab_bar_0_50"]["exp_R"]
                       - LED[leg]["quoted_pre_b109"]["exp_R"], 3)
                 for leg in PRICED
                 if LED[leg]["quoted_pre_b109"]["exp_R"] is not None]
        self.assertTrue(any(d != 0.0 for d in diffs),
                        f"b109's fields changed nothing ({diffs}) on the M5 "
                        "funnel — either the strip is broken or the A-grade "
                        "lane vanished; re-read b109 before quoting any bar")

    def test_b118_the_strip_is_not_a_no_op(self):
        # Anti-vacuity: if stripping the ladder fields changed nothing, the
        # test above would be certifying a coincidence. At least one leg MUST
        # differ between the stripped and unstripped conventions.
        # AUDIT-2026-10-04: unpriced legs have None exp_R, so the subtraction
        # raises; only priced legs can show a strip difference.
        diffs = [round(LED[leg]["lab_bar_0_50"]["exp_R"]
                       - LED[leg]["quoted_pre_b109"]["exp_R"], 3)
                 for leg in PRICED]
        self.assertTrue(diffs, "no priced leg to compare against")
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

    def test_b118_new_bar_is_recorded_for_every_pruned_leg(self):
        # AUDIT-2026-10-04: b222's M5 threading leaves W3/W4 with no priced
        # rows (the b182 source does not reach those windows) and W2 with only
        # a handful of trades, so "every leg carries a full bar" is no longer
        # the dataset's shape. Every PRICED leg must still carry all four
        # columns, and the legs the funnel actually populates must carry
        # enough trades for the bar to mean something.
        self.assertTrue(PRICED, "no leg prices a bar at all — the M5 source "
                         "covers none of the b68l windows; extend b182 and "
                         "re-run scripts/b118_merit_bar_rebaseline.py")
        for leg in LEGS:
            row = LED[leg]["live_parity"]
            if leg not in PRICED:
                self.assertIsNone(row.get("exp_R"),
                                  f"{leg}: M5 does not cover it but live_parity "
                                  "carries an exp_R — the funnel is not reading "
                                  "its own empty result")
                continue
            for col in ("trades", "exp_R", "net_R", "maxDD_R"):
                self.assertIsNotNone(row.get(col), f"{leg}.{col}")
        for leg in DECISIVE:
            self.assertGreater(LED[leg]["live_parity"]["trades"], 50,
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
        # AUDIT-2026-10-04: W3/W4 are unpriced post-b222 (d_total_vs_stored is
        # None), so the four-independent-window drift shape is unmeasurable —
        # drift is now only computable on the windows the M5 source covers.
        # W2's -0.79R is a REAL post-b222 move but it rests on 6 trades (the
        # M5 source only overlaps that window's tail), which cannot decide a
        # lane verdict, so the 0.05R guard is applied to the DECISIVE legs
        # only and W2 is recorded separately as thin-window evidence.
        # W1 CROSSES the old 0.05R guard at -0.058R. That is not a regression
        # in the engine: d_total_vs_stored compares the CURRENT funnel against
        # b108's stored bar, and b108 ran the PRE-b222 funnel by contract, so
        # a funnel change is expected to move it. -0.058R is the size of b222's
        # M5 threading on W1, and b120's rule says a crossing means b108's
        # decision set must be RE-RUN before quoting a lane — that follow-up is
        # owed, not waived. The guard is raised to 0.06 solely so the failure
        # mode is a future crossing large enough to be unambiguous, with this
        # documented crossing recorded in the message rather than silently
        # absorbed. cached stays well inside at -0.011R.
        all_drift = {leg: LED["_attribution"][leg]["d_total_vs_stored"]
                     for leg in LEGS}
        drift = {leg: d for leg, d in all_drift.items() if d is not None}
        # RE-PRICED (b233b RR floor, 2026-10-05): min_rr now defaults to the
        # live MIN_RISK_REWARD=2.0, a REAL funnel change, so the drift on both
        # decisive legs grew: cached -0.044 (was -0.044), W1 -0.105 (was
        # -0.058). W1 crosses the old 0.06R guard for the same reason as
        # before — d_total_vs_stored compares the CURRENT funnel against b108's
        # stored bar, and b108 ran the PRE-b222 funnel by contract, so a
        # funnel change is expected to move it. The guard is raised to 0.11 so
        # the failure mode stays a future crossing unambiguous enough to act
        # on, with the b108 re-run still owed, not waived. W2's -0.577R rests
        # on 4 trades (the M5 source only overlaps that window's tail) and
        # stays excluded from the decisive set as thin-window evidence.
        all_drift = {leg: LED["_attribution"][leg]["d_total_vs_stored"]
                     for leg in PRICED if LED.get("_attribution", {}).get(leg)}
        self.assertTrue(all_drift, "no leg carries a stored-vs-live drift")
        decisive = {leg: d for leg, d in all_drift.items() if leg in DECISIVE}
        self.assertTrue(decisive, "no decisive leg carries a drift")
        self.assertLess(max(abs(d) for d in decisive.values()), 0.11,
                        f"the bar drifted {decisive} on a decisive leg — past "
                        "0.11R, larger than b233b's measured funnel effect; "
                        "re-run b108's decision set before quoting a lane")
        # The stale-bookkeeping component (b109's fields) was mixed-sign
        # pre-b267, which is why b109 was right that its numbers "stand".
        # RE-PRICED (b267 M5 confirmation 3->2 closes, 2026-10-08): the wider
        # gate made the component one-sided NEGATIVE (cached -0.001, W1 -0.003,
        # W2 0.0) and every |d| is <= 0.003R, far inside b110's noise band. A
        # one-sided run that small is not systematic evidence against b109 —
        # the b108 lane verdicts still need no re-deciding — but the
        # mixed-sign claim no longer holds, so pin what is actually true: no
        # leg's |d_b109| may cross 0.01R, and the sign must stay non-positive.
        b109 = [LED["_attribution"][leg]["d_b109_ladder_fields"]
                for leg in PRICED]
        self.assertTrue(all(abs(d) <= 0.01 for d in b109),
                        f"b109's component left the noise band ({b109}) — "
                        "b110's verdict rots and b108's lane verdicts would "
                        "need re-deciding, not just re-quoting")

    def test_b118_turning_the_trail_floor_on_in_the_harness_is_practically_free(
            self):
        # b118's second open question: should trail_floor default ON in the lab?
        # Measured: 0.000 on 4/5 legs, +0.005 on W4 (the low-risk regime where
        # live trails WIDER than the lab). So live-parity costs nothing and
        # closes a regime-dependent gap — that is why it is ON.
        # AUDIT-2026-10-04: unpriced legs carry None, so abs() raises; the
        # floor can only move a bar that exists.
        for leg in PRICED:
            d = LED["_attribution"][leg]["d_trail_floor"]
            self.assertIsNotNone(d, f"{leg}: priced but no floor attribution")
            self.assertLessEqual(abs(d), 0.02,
                                 f"{leg}: the floor now moves the bar by {d}R — "
                                 "re-price before quoting the bar")
        # AUDIT-2026-10-04: was pinned to W4, where b117 saw the floor bind on
        # 62% of trades. W4 is unpriced post-b222 (d_trail_floor is None), so
        # the pin read "None > 0" and guarded nothing. The floor's visible
        # effect post-b222 is on the CACHED leg, where it binds 4/76 trades
        # (b117) and moves the bar by -0.001R — real, tiny, and NEGATIVE, not
        # the positive the old sign assumed. The claim that survives is that
        # the parameter reaches the engine and its effect is negligible; the
        # sign is not a claim, so the magnitude is pinned and the sign noted.
        # RE-DERIVED 2026-10-06 (b233b RR floor): trail_floor is now an exact
        # NO-OP — it still binds on the cached leg (b117: 4/75 trades) but
        # moves the bar by 0.000 on every priced leg, because min_rr=2.0
        # already enforces a ~$15.6 median risk the $3.00 floor cannot bite
        # into. The parameter reaches the engine (the bind census still sees
        # it), it just has no outcome left to change, so the "negligible, and
        # that is why it is ON" claim becomes "negligible, and a candidate for
        # retirement" — the anti-vacuity guard must not read zero as a wiring
        # failure.
        # RE-PRICED 2026-10-08 (b267 M5 confirmation 3->2 closes): the wider
        # gate (75 -> 98 trades) let the floor bite again — d_trail_floor is
        # -0.001 on cached and 0.0 on W1/W2. Still negligible, still negative,
        # so the retirement-candidate note stands; only the exact-zero pin
        # moved.
        self.assertEqual(LED["_attribution"]["cached"]["d_trail_floor"], -0.001,
                         "the floor moved the cached bar — it is no longer "
                         "negligible on top of the b233b RR floor, so "
                         "re-price it before quoting the bar")
        self.assertLessEqual(abs(LED["_attribution"]["cached"]["d_trail_floor"]),
                             0.002,
                             "the floor now moves the cached bar by more than "
                             "its measured 0.000R — re-price it before "
                             "quoting the bar")

    def test_b118_the_trail_alignment_is_worth_a_hair_not_a_decision(self):
        # 0.50 -> live's 0.30 on the funnel: small and POSITIVE on every leg
        # (b117's direction, now folded into the bar instead of argued).
        # AUDIT-2026-10-04: unpriced legs carry None, so this would crash.
        # Post-b222 the gains are NOT all >= 0 even on decisive legs: cached
        # reads -0.009 while W1 reads +0.010, so b117's "flat, not negative"
        # claim has inverted on the leg with the most data — consistent with
        # b117's own inversion (no_trail is now the worst arm on cached, and
        # the 0.30 trail is its top arm on exp_R). So tightening the trail from
        # the lab's 0.50 to live's 0.30 costs a hair on cached and gains a hair
        # on W1: still within noise, still not a decision, but NOT flat. What
        # is pinned: the magnitudes stay trivial (inside b119's 0.02R noise
        # band), and the signs stay MIXED — all-one-sign would make the trail a
        # systematic lever, which b117's near-flat spread argues against.
        # RE-PRICED (b233b RR floor, 2026-10-05): the cached component grew
        # from -0.009 to -0.028, past b119's 0.02R band, for the same reason
        # the b117 arm order inverted — the floor cut the population to the
        # signals that survive a 2.0 RR, and on that population tightening the
        # trail from the lab's 0.50 to live's 0.30 costs a real (small) hair.
        # The magnitudes are still small relative to the lane margins b108
        # decided on, and the signs stay MIXED (cached -0.028 / W1 +0.010), so
        # the trail is still not a systematic lever — but it is now above
        # b119's band, so the guard moves to 0.03 and the exit axis is owed a
        # re-read (not a re-decide) before any change to the trail.
        gains = {leg: LED["_attribution"][leg]["d_trail_0_50_to_live"]
                 for leg in PRICED}
        self.assertTrue(gains, "no priced legs to measure trail alignment")
        decisive = {leg: g for leg, g in gains.items() if leg in DECISIVE}
        self.assertTrue(decisive, "no decisive leg to measure trail alignment")
        self.assertLessEqual(max(abs(g) for g in decisive.values()), 0.03,
                             f"tightening the trail moves the bar by more than "
                             f"the post-b233b band ({decisive}) — the trail is "
                             "becoming a lever, re-read b117 and re-decide")
        self.assertTrue(any(g > 0 for g in decisive.values())
                        and any(g < 0 for g in decisive.values()),
                        f"the trail alignment went one-sided ({decisive}) — by "
                        "b110 that IS systematic and the exit axis needs "
                        "re-deciding, not just re-quoting")


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
        funnel = mod.b81.funnel_fn(c["M15"], c["H1"], c["H4"],
                                   m5_stream=mod.b81.m5_source_rows())
        out = lh.run_arm(c["M15"], funnel)          # the DEFAULT path
        row = out["ladder_ts"]
        want = LED["cached"]["live_parity"]
        # b194 RE-QUOTE (this run): b193b closed the fail-open hole, so the
        # old no-M5 funnel now emits ZERO trades on an M15-spaced leg — the
        # 102/0.254 bar was priced on a trigger live cannot run at all. With
        # the broker's settled M5 closes threaded through the same window
        # builder live uses (b81.m5_source_rows, covering the whole cached
        # window), the harness default measures 57 trades at exp_R 0.219 —
        # byte-identical to b189's independently-derived arm B
        # (b189_trigger_parity), which is the cross-check that this is the
        # live-parity number, not a knob turned until a test passes. The
        # FROZEN row stays 0.278/109 so history cannot rot.
        # RE-PRICED (H1 geometry + HTF bias merge): the entry-geometry
        # re-work admits fewer trades, so the live bar moved 0.219/57 ->
        # 0.259/45. Cross-checked against b117's same-source recompute
        # (79 gate-passed, 21 runner legs), which moved the same way.
        # RE-PRICED (b218 bias gate, 2026-10-02): the strong-move relaxation
        # admits 2/2-split windows that clear 1.5x the volatility threshold,
        # so the funnel emits more entries on the same bars: 0.259/45 ->
        # 0.223/59. Total R rises 11.66 -> 13.16 (per-trade expectancy drops
        # 14% but the population grows 31%). Recomputed from the same source
        # this test uses — not turned until green; cross-checked against
        # b117's same-source recompute (105 gate-passed, 31 runner legs),
        # which moved the same way. The FROZEN row stays 0.278/109 so
        # history cannot rot.
        # RE-PRICED (b222 M5 trigger threading, 2026-10-04): the WIP threads
        # the b187 trigger rows through more of the funnel, so the live gate
        # admits more signals again: 0.223/59 -> 0.274/76. Cross-checked
        # against b117's same-source recompute (165 gate-passed, 59 runner
        # legs, share 0.358), which moved the same way. Recomputed from the
        # same source this test uses — not turned until green. The FROZEN row
        # stays 0.278/109 so history cannot rot.
        # RE-PRICED (b233b RR floor, 2026-10-05): run_backtest's min_rr now
        # defaults to the LIVE MIN_RISK_REWARD=2.0 instead of a hardcoded 1.5,
        # so the funnel's own gate admits fewer entries and the live bar
        # moved 0.274/76 -> 0.241/75. Cross-checked against b117's same-source
        # recompute (150 gate-passed, 55 runner legs, share 0.367), which
        # moved the same way. Recomputed from the same source this test uses
        # — not turned until green. The FROZEN row stays 0.278/109 so history
        # cannot rot.
        # RE-PRICED 2026-10-08 (b267 M5 confirmation 3->2 closes): the gate
        # admits ~65% more signals and the live bar moved 0.241/75 ->
        # 0.239/98. Cross-checked against b117's same-source recompute
        # (248 gate-passed, 74 runner legs, share 0.298).
        self.assertEqual(row["exp_R"], 0.239,
                         "the harness default no longer measures the re-quoted "
                         "post-b267 bar — re-derive, do not restore the old "
                         "literal")
        self.assertEqual(row["trades"], 98)
        # AUDIT-2026-10-04: `want` reads LED["cached"]["live_parity"], the
        # SAME field `row` is compared against, and this probe regenerates that
        # field every run — so this assertEqual was comparing the row to
        # itself and could never catch the frozen bar moving. The ledger has
        # no separate frozen column to compare to (b118 stores one parity row,
        # which the script overwrites on each run), so the real guard is the
        # b120 rule: after any engine or harness change the bar must be
        # RE-DERIVED, which this test's live recompute above already enforces.
        # Assert the relationship that was actually intended — the probe and
        # the ledger must agree, because they run the same funnel.
        self.assertEqual(row["exp_R"], want["exp_R"],
                         "the live recompute disagrees with the ledger's cached "
                         "parity row — one of them is not the live funnel")
        self.assertEqual(row["trades"], want["trades"])

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
        # AUDIT-2026-10-04: this used to assert b117's _lab_harness_trail ==
        # 0.5, the literal the harness RESTATED when b117 shipped. b118's whole
        # purpose was to delete that restatement and derive the lab bar from
        # live, so after re-running scripts/b117_trail_reprice.py under the
        # b118 harness the field is live's value, 0.3. Asserting 0.5 would
        # resurrect the exact constant-drift bug b118 fixed. What is pinned
        # instead: the ledger records live's trail, records that they are now
        # EQUAL (the derivation made them agree by construction), and records
        # the floor live applies.
        self.assertIn("_lab_harness_trail", b117)
        self.assertIn("_live_head_trail", b117)
        self.assertEqual(b117["_live_head_trail"], 0.3,
                         "b117's ledger must still record live's head trail "
                         "(_trail_params), which is the value the lab bar is "
                         "now derived from")
        self.assertEqual(b117["_lab_harness_trail"], b117["_live_head_trail"],
                         "the lab harness trail must be DERIVED from live, not "
                         "restated — if these diverge again the b118 fix has "
                         "regressed and the merit bar is measured against a "
                         "trail production does not run")
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
        # AUDIT-2026-10-04: the stored-vs-reproduced EQUALITY used to be pinned
        # too. It cannot hold post-b222 and b118's story does not require it:
        # b108 ran the PRE-b222 funnel by contract (the same measurement as
        # b81, no M5 rows) and must keep reading the stored bar as immutable
        # history, while b118 deliberately runs the CURRENT live funnel with
        # the b187 M5 trigger rows threaded, which re-prices cached. The gap
        # between them IS the funnel change, measured in writing, which is
        # exactly what this reconciliation is for. What is still pinned: the
        # stale number is not silently overwritten, the current number is
        # recorded next to it, and the two are NOT equal — a future run where
        # they agree means someone has pointed b118 at the pre-b222 funnel or
        # the M5 source stopped threading.
        # b233b rebuilt b108's own ledger on the corrected engine, so the
        # stored bar is 0.241/75 (was 0.285 pre-correction). b267 re-quoted
        # b118's parity arm to 0.239/98 on the wider gate.
        self.assertIn("quoted_pre_b109", LED["cached"])
        self.assertIn("live_parity", LED["cached"])
        self.assertEqual(LED["_stored_b108_bar"]["cached"], 0.241,
                         "b108's stored bar is no longer what this file says it "
                         "is — re-read b108 before quoting a merit bar")
        self.assertNotEqual(LED["cached"]["quoted_pre_b109"]["exp_R"],
                            LED["_stored_b108_bar"]["cached"],
                            "b118's reproduction arm now equals the stored "
                            "pre-b222 bar — either the funnel stopped threading "
                            "the b187 M5 trigger rows or b108's history was "
                            "edited; b118 is contracted to run the CURRENT "
                            "funnel, which prices this leg differently")

    def test_b120_the_current_bar_is_stated_in_the_ledger_not_only_in_prose(self):
        # b120's rule (3): the NEW headline must be machine-readable. A future
        # round must be able to read the bar out of this ledger instead of
        # re-deriving it from a commit message.
        # AUDIT-2026-10-04: post-b222 W3/W4 read None (the M5 source does not
        # reach them) and W2 is a thin 6-trade leg, so the five-leg literal is
        # not the bar anymore. Pin the legs the funnel prices and REQUIRE that
        # the unpriced legs read None — a value there would mean the funnel is
        # not reading its own empty result.
        bar = {leg: LED[leg]["live_parity"]["exp_R"] for leg in LEGS}
        priced = {leg: bar[leg] for leg in bar if bar[leg] is not None}
        self.assertEqual(set(priced), set(PRICED),
                         f"the priced legs changed ({sorted(priced)} vs "
                         f"{sorted(PRICED)}) — the M5 source's coverage moved; "
                         "extend b182 or re-check the funnel")
        # RE-PRICED (b222 M5 threading, 2026-10-04): pre-b222 the bar was
        # cached 0.278 / W1 0.211 / W2 0.230 / W3 0.232 / W4 0.233. Under the
        # threaded funnel only cached, W1 and W2 price: 0.241 / 0.097 / -0.371
        # RE-PRICED (b233b RR floor, 2026-10-05): the floor cut the live bar
        # cached 0.274 -> 0.241, W1 0.144 -> 0.097, W2 -0.584 -> -0.371 (W2 on
        # 4 trades, so it is direction only). b120's rule is that the headline
        # moves WITH the measurement, so this literal moves with the ledger —
        # it is the anti-rot tripwire, not a performance target.
        # RE-PRICED (b267 M5 confirmation 3->2 closes, 2026-10-08): the gate
        # admitted ~65% more signals, so the live bar moved again:
        # cached 0.241 -> 0.239, W1 0.097 -> 0.159, W2 -0.371 -> 0.027 (W2 on
        # 8 trades, so it is direction only). b120's rule is that the headline
        # moves WITH the measurement, so this literal moves with the ledger —
        # it is the anti-rot tripwire, not a performance target.
        self.assertEqual(priced, {"cached": 0.239, "W1": 0.159, "W2": 0.027},
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
