"""b109 — the backtest's trade dict now DOES satisfy the contract of the LIVE
partial-close function. SHIPPED 2026-09-06.

This file was written by b108 to pin the MISMATCH (the "live-parity ladder" was
a constant). b109's own instruction was to EDIT these tests to expect the real
lane split, not delete them (b102's rule), so the pins below now certify the
fix from both directions: the fields arrive, and the ladder discriminates.

WHAT WAS WRONG (b108's side finding, measured): `engines/lab_harness.LADDER`
passed the REAL live function `_partial_close_fraction(trade)` and
`engines/backtest.py`'s b55 comment claimed passing the whole trade dict let it
"read grade AND momentum/rr/structure from it". It could not:

  live  hermes_runtime built: setup_grade, momentum_strength, rr_remaining,
                               structure_state, ...
  back  engines/backtest built: grade, style, side, entry, sl, tp, ...
                                 (NONE of the four)

With rr_remaining defaulting to 0.0 the `rr_remaining <= 1.2` weak branch
tripped unconditionally, so the function returned (1.0,
'weak_full_exit_at_tp1') on 935/935 calls on the cached funnel — all 84 A-grade
signals included.

WHAT SHIPPED:
1. engines.trade_management.ladder_fields(quality, setup_grade, session=None)
   — ONE definition of how a plan becomes the fields the ladder reads.
   hermes_runtime.cycle, position_daemon.build_trade and
   engines.backtest_real.strategy_signal all call it, so the parity is by
   construction and the three producers cannot drift field by field again.
   engines.trade_management.LADDER_FIELDS names the keys once;
   engines/backtest.py imports it (never restates it) and carries any of them
   present on a signal into the trade dict.
2. THE COLLAPSE (scripts/b109_probe_lane_reachability.py, 1540 real plans): the
   four-way AND is not a four-factor judgement. Both live producers derive all
   four inputs from TWO plan fields (alignment, trend_strength) and hardcode
   rr_remaining = 2.0, so
       grade>=3 AND momentum>=0.8 AND rr>=2.0 AND structure=='healthy'
       ==  setup_grade == 'A'
   exactly — pinned below over every distinct (alignment, trend, regime) in
   plan_history. b55's comment called the runner lane "a thesis the parity
   backtest cannot model"; it is one threshold, and this file now models it.
3. THE RE-MEASUREMENT (scripts/b109_ladder_parity_rescore.py, ledger
   data/backtest/b109_ladder_parity_rescore.json): pre/post legs differ ONLY in
   whether the signal carries the fields, on identical bars. The A-grade runner
   leg is worth ~nothing: d_exp_R = -0.015 (cached), +0.003 (W1), +0.021 (W2),
   -0.004 (W3), -0.001 (W4) — MIXED SIGN, max |delta| 0.021R, DD unchanged on
   all five legs. By b110's rule a mixed-sign shift is noise, not contamination,
   so the b80/b81/b108 numbers stand and the merit bar does not move.
4. THE DRIFT FOUND ON THE WAY (filed as b111, a human decision): the two live
   producers do NOT share a grade rule. position_daemon.build_trade inlines a
   PRE-b45 rule (no regime clause for an A; 'mixed' alignment reaches B) while
   hermes_runtime/auto_executor require a continuation regime and send 'mixed'
   to C. The lane census shows they agree on the strong-runner lane (0
   disagreements over 1540 plans) but differ on the WEAK lane (runtime 86.9% vs
   watchdog 68.1% of plans) — and the weak lane is the one that decides whether
   the stop gets locked in. Aligning them changes live breakeven behaviour, so
   it is filed, NOT taken.
"""
from __future__ import annotations

import ast
import glob
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engines.trade_management import (  # noqa: E402
    LADDER_FIELDS, _partial_close_fraction, ladder_fields)


def _plan_history_combos() -> dict:
    """{(alignment, trend_strength, regime): count} over every real plan the
    live system wrote. Read-only; empty dict if the data is not present."""
    out = {}
    files = sorted(glob.glob(os.path.join(ROOT, "data", "xau_plan",
                                          "plan_history", "*.json")))
    for f in files:
        try:
            q = (json.load(open(f)).get("quality") or {})
        except Exception:
            continue
        key = (str(q.get("alignment")), float(q.get("trend_strength") or 0),
               str(q.get("regime")))
        out[key] = out.get(key, 0) + 1
    return out


class TestB109ContractIsNowSatisfied(unittest.TestCase):
    """The edited half of b108's pin: the fields must ARRIVE."""

    def test_b109_the_live_fields_are_now_supplied_by_the_backtest(self):
        # b108 pinned the ABSENCE of these keys; b109 ships them. The list is
        # imported from the reader module, so a new field the ladder starts to
        # read cannot be quietly left out of the producer contract.
        from engines.backtest_real import strategy_signal
        src = __import__("inspect").getsource(strategy_signal)
        self.assertIn("ladder_fields", src,
                      "strategy_signal no longer emits the live ladder fields "
                      "— the parity b109 shipped has regressed")
        self.assertTrue(set(LADDER_FIELDS) >= {"setup_grade",
                                               "momentum_strength",
                                               "rr_remaining",
                                               "structure_state"})

    def test_b109_engine_carries_the_fields_into_the_trade_dict(self):
        # Behaviour, not source: a signal that carries the fields must reach
        # partial_share_fn WITH them, so the function can discriminate.
        from engines.backtest import backtest_ohlc
        seen = []

        def sig(row):
            if row.get("time") == 100:
                return {"side": "BUY", "entry": 100.0, "sl": 98.0, "tp": 104.0,
                        "grade": "A", "style": "x",
                        **ladder_fields({"alignment": "aligned",
                                         "trend_strength": 6.0}, "A")}
            return None

        rows = [{"time": 100 + i, "open": 100.0, "high": 100.0,
                 "low": 99.5, "close": 100.0} for i in range(6)]
        rows[1]["high"] = 103.0     # TP1 (midpoint 102) hit
        backtest_ohlc(rows, sig, partial_tp1_share=0.5, tp1_position=0.5,
                      partial_share_fn=lambda t: (seen.append(dict(t)) or 1.0))
        self.assertTrue(seen, "the ladder fn was never called — dead fixture")
        for field in ("setup_grade", "momentum_strength", "rr_remaining",
                      "structure_state"):
            self.assertIn(field, seen[0],
                          f"{field} did not survive into the trade dict")
        self.assertEqual(seen[0]["setup_grade"], "A")
        self.assertEqual(seen[0]["rr_remaining"], 2.0)

    def test_b109_an_arm_that_supplies_nothing_keeps_the_old_shape(self):
        # Every standalone lab arm declares grade B and NO ladder fields; the
        # engine must not invent them, or the b68 round numbers would silently
        # change meaning.
        from engines.backtest import backtest_ohlc
        seen = []

        def sig(row):
            if row.get("time") == 100:
                return {"side": "BUY", "entry": 100.0, "sl": 98.0,
                        "tp": 104.0, "grade": "B", "style": "lab_arm"}
            return None

        rows = [{"time": 100 + i, "open": 100.0, "high": 100.0,
                 "low": 99.5, "close": 100.0} for i in range(6)]
        rows[1]["high"] = 103.0
        backtest_ohlc(rows, sig, partial_tp1_share=0.5, tp1_position=0.5,
                      partial_share_fn=lambda t: (seen.append(dict(t)) or 1.0))
        self.assertTrue(seen)
        for field in LADDER_FIELDS:
            self.assertNotIn(field, seen[0],
                             f"{field} was fabricated for an arm that never "
                             "emitted it — lab arms must keep their shape")


class TestB109LadderDiscriminates(unittest.TestCase):
    """The other edited half: the ladder is no longer a constant."""

    def test_b109_the_ladder_is_no_longer_a_constant(self):
        # b108 asserted share==1.0 for EVERY backtest-shaped dict. Now the
        # A-grade shape takes the runner lane and the rest still close full.
        a = ladder_fields({"alignment": "aligned", "trend_strength": 6.0}, "A")
        b = ladder_fields({"alignment": "aligned", "trend_strength": 3.0}, "B")
        c = ladder_fields({"alignment": "mixed", "trend_strength": 0.5}, "C")
        base = {"side": "BUY", "entry": 100.0, "sl": 98.0, "tp": 104.0}
        self.assertEqual(_partial_close_fraction(dict(base, **a)),
                         (0.3, "strong_runner_keep_more"))
        self.assertEqual(_partial_close_fraction(dict(base, **b))[0], 1.0)
        self.assertEqual(_partial_close_fraction(dict(base, **c))[0], 1.0)
        self.assertEqual(_partial_close_fraction(dict(base, **b))[1],
                         "balanced_full_exit_at_tp1")
        self.assertEqual(_partial_close_fraction(dict(base, **c))[1],
                         "weak_full_exit_at_tp1")

    def test_b109_grade_now_discriminates_where_it_could_not(self):
        # b108's pin said an A and a C dict MUST agree, because the function
        # could not see the grade. That is exactly what the fix broke — on
        # purpose.
        base = {"side": "BUY", "entry": 100.0, "sl": 98.0, "tp": 104.0}
        a = dict(base, **ladder_fields({"alignment": "aligned",
                                        "trend_strength": 6.0}, "A"))
        c = dict(base, **ladder_fields({"alignment": "aligned",
                                        "trend_strength": 6.0}, "C"))
        self.assertNotEqual(_partial_close_fraction(a)[0],
                            _partial_close_fraction(c)[0])

    def test_b109_the_collapse_the_lane_is_exactly_grade_A(self):
        """The four-way AND reduces to ONE condition under the live producers.

        Both producers derive momentum/structure from (alignment,
        trend_strength) and hardcode rr_remaining=2.0, so for any grade the
        producer would ACTUALLY emit for that quality,
        grade>=3 AND momentum>=0.8 AND rr>=2.0 AND healthy  <=>  grade=='A'.
        Verified over every distinct (alignment, trend, regime) triple in the
        real plan_history, under BOTH live grade rules (the canonical
        _infer_setup_grade and the watchdog's inline pre-b45 rule — see b111),
        not just a hand-picked shape.
        """
        from hermes_runtime import _infer_setup_grade

        def watchdog_grade(plan):
            # position_daemon.build_trade's inline rule, restated for the
            # probe only (build_trade itself is not importable without a live
            # position dict). Same signature as _infer_setup_grade.
            q = plan.get("quality") or {}
            al, tr = q.get("alignment"), float(q.get("trend_strength") or 0)
            return ("A" if al == "aligned" and tr >= 3.0
                    else "B" if al in ("aligned", "mixed") and tr >= 1.2
                    else "C")

        combos = _plan_history_combos()
        if not combos:
            self.skipTest("no plan_history on this checkout")
        self.assertGreater(len(combos), 50,
                           "plan_history looks truncated — the collapse "
                           "sample is too thin to certify")
        hits = 0
        for (al, tr, rg) in combos:
            quality = {"alignment": al, "trend_strength": tr, "regime": rg}
            for grade_fn in (_infer_setup_grade, watchdog_grade):
                grade = grade_fn({"quality": quality})
                f = ladder_fields(quality, grade)
                lane = _partial_close_fraction(
                    {"side": "BUY", "entry": 100.0, "sl": 98.0, **f})
                self.assertEqual(lane[0] == 0.3, grade == "A",
                                 f"({al},{tr},{rg}) grade={grade} -> {lane}: "
                                 "the runner lane is no longer equivalent to "
                                 "grade A — the collapse note is stale")
                hits += 1
        self.assertGreater(hits, 100, "the collapse sweep was vacuous")

    def test_b109_rr_remaining_is_a_constant_so_two_clauses_are_dead(self):
        # `rr_remaining <= 1.2` (weak) and `>= 2.0` (runner) can never fire on
        # their own: both producers pin the value at 2.0. Pinned so nobody
        # reads the function as a live RR judgement.
        for grade in ("A", "B", "C"):
            f = ladder_fields({"alignment": "aligned", "trend_strength": 2.4},
                              grade)
            self.assertEqual(f["rr_remaining"], 2.0)
        weak_only = {"side": "BUY", "entry": 100.0, "sl": 98.0,
                     **ladder_fields({"alignment": "aligned",
                                      "trend_strength": 2.4}, "B")}
        self.assertEqual(_partial_close_fraction(weak_only)[1],
                         "balanced_full_exit_at_tp1")


class TestB109ProducerParity(unittest.TestCase):
    """The three producers must not drift apart again."""

    def test_b109_no_producer_restates_the_derivation(self):
        # Each of the three must CALL ladder_fields and must NOT restate the
        # derived keys as its own dict literals — an inline
        # momentum_strength/volatility_state expression in a producer is the
        # b109 disease coming back (three lookalikes that drift).
        derived_keys = {"momentum_strength", "volatility_state",
                        "structure_state", "thesis_valid", "exposure_fraction",
                        "rr_remaining"}
        for rel in ("hermes_runtime.py", "position_daemon.py",
                    "engines/backtest_real.py"):
            path = os.path.join(ROOT, rel)
            with open(path) as fh:
                src = fh.read()
            self.assertIn("ladder_fields", src,
                          f"{rel} no longer derives its ladder fields from "
                          "the shared helper")
            restated = []
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, ast.Dict):
                    for k in node.keys:
                        if (isinstance(k, ast.Constant)
                                and k.value in derived_keys):
                            restated.append(k.value)
            self.assertEqual(restated, [],
                             f"{rel} hardcodes {restated} again — derive them "
                             "through ladder_fields or the producers drift (b109)")

    def test_b111_watchdog_grade_rule_is_now_the_canonical_one(self):
        # EDITED 2026-09-07 (b111 shipped). This pin used to certify the OPPOSITE:
        # that position_daemon's inline pre-b45 rule (no regime clause for an A,
        # 'mixed' reaching B) was still its own on purpose, because b109 filed
        # the drift as a human decision on the premise that aligning it "would
        # change the live breakeven lock on a real account".
        # The premise was measured, not assumed, and it was FALSE: the only
        # broker-visible difference is the cell aligned + trend>=3.0 + a
        # NON-continuation regime, which engines.context._detect_regime cannot
        # emit (0/320 swept cells, 0/65 real plans), and the remaining 35
        # differing cells differ only in a reason LABEL. See
        # scripts/b111_blast_radius_probe.py + tests/test_b111_grade_rule_aligned.py
        # for the pins that replaced this one.
        with open(os.path.join(ROOT, "position_daemon.py")) as fh:
            src = fh.read()
        self.assertIn("from engines.plan import setup_grade", src,
                      "the watchdog no longer shares the canonical grade rule "
                      "— the b111 alignment has regressed")
        self.assertIn("b111", src, "the watchdog's grade line needs its b111 note")
        # The looser inline rule must be GONE, not merely unused: a second
        # definition of the grade is the b109 three-lookalikes disease.
        self.assertNotIn("'B' if alignment in ('aligned', 'mixed')", src,
                         "the pre-b45 inline grade rule is back in the watchdog")

    def test_b111_the_live_producers_now_agree_on_every_lane(self):
        # EDITED 2026-09-07 (b111 shipped). This pin used to measure the drift
        # between TWO LIVE grade rules — the canonical one and the watchdog's
        # inline pre-b45 copy — and asserted the weak-lane share differed by
        # 5%-40% (measured 18.8%) while the runner lane agreed exactly. That
        # band was the blast radius of a decision not yet taken.
        #
        # The decision is taken: position_daemon now calls the same
        # engines.plan.setup_grade as hermes_runtime/auto_executor, so
        # live-vs-live drift is 0 BY CONSTRUCTION and cannot rot. What is still
        # worth pinning is the HISTORY: the canonical rule must remain STRICTER
        # than (never looser than) the rule it replaced, and it must still
        # differ from it on the weak lane — otherwise the alignment was a
        # no-op and the 18.8% number quoted in the backlog is fiction.
        from hermes_runtime import _infer_setup_grade
        import position_daemon as pd_mod

        def pre_b45_watchdog_grade(plan):
            """The rule b111 REMOVED, restated here as the historical control."""
            q = plan.get("quality") or {}
            al, tr = q.get("alignment"), float(q.get("trend_strength") or 0)
            return ("A" if al == "aligned" and tr >= 3.0
                    else "B" if al in ("aligned", "mixed") and tr >= 1.2
                    else "C")

        combos = _plan_history_combos()
        if not combos:
            self.skipTest("no plan_history on this checkout")
        rank = {"A": 3, "B": 2, "C": 1}

        def lane(quality, grade):
            base = {"side": "BUY", "entry": 100.0, "sl": 98.0}
            return _partial_close_fraction(
                dict(base, **ladder_fields(quality, grade)))[1]

        total = runner_diff = weak_diff = looser = 0
        for (al, tr, rg), n in combos.items():
            quality = {"alignment": al, "trend_strength": tr, "regime": rg}
            plan = {"quality": quality}
            g_new, g_old = _infer_setup_grade(plan), pre_b45_watchdog_grade(plan)
            # (1) LIVE-vs-LIVE: the watchdog's real code must equal the
            # canonical rule on every observed plan, not just agree with it.
            raw = {"ticket": 1, "type": "SELL", "volume": 0.05,
                   "price_open": 4300.0, "sl": 4320.0, "tp": 0.0,
                   "profit": 0.0, "time": 1}
            wd_live = pd_mod.build_trade(
                raw, {"quality": quality,
                      "execution": {"tp_levels": [4280.0, 4260.0],
                                    "tp_shares": [0.5, 0.3, 0.2]}}, {})
            self.assertEqual(wd_live["setup_grade"], g_new,
                             f"({al},{tr},{rg}): the watchdog's grade is no "
                             "longer the canonical one — b111 has regressed")
            # (2) HISTORY: never looser, and still a real change on weak.
            if rank[g_new] > rank[g_old]:
                looser += n
            l_new, l_old = lane(quality, g_new), lane(quality, g_old)
            total += n
            runner_diff += n * ((l_new == "strong_runner_keep_more")
                                != (l_old == "strong_runner_keep_more"))
            weak_diff += n * ((l_new == "weak_full_exit_at_tp1")
                              != (l_old == "weak_full_exit_at_tp1"))
        self.assertEqual(looser, 0,
                         f"the canonical grade is LOOSER than the removed rule "
                         f"on {looser}/{total} plans — that would widen a risk "
                         "gate, which b111 must never do")
        self.assertEqual(runner_diff, 0,
                         f"the runner lane differs on {runner_diff}/{total} "
                         "plans — the removed rule's A was reachable after all, "
                         "contradicting the b111 measurement")
        self.assertGreater(weak_diff / total, 0.05,
                           "the alignment changed nothing on the weak lane — "
                           "the 18.8% drift quoted in the backlog is stale")
        self.assertLess(weak_diff / total, 0.40,
                        f"the historical weak-lane drift is {weak_diff}/{total}, "
                        "outside the 5%-40% band b109 measured")


class TestB109Ledger(unittest.TestCase):
    """The re-measurement, pinned from the shipped ledger."""

    LEDGER = os.path.join(ROOT, "data", "backtest",
                          "b109_ladder_parity_rescore.json")

    def _led(self):
        if not os.path.exists(self.LEDGER):
            self.skipTest("b109 ledger not present")
        with open(self.LEDGER) as fh:
            return json.load(fh)

    def test_b109_the_pre_leg_reproduces_the_b108_funnel_numbers(self):
        # Integrity: stripping the fields must land exactly on the numbers the
        # backlog quotes, or the A/B is not measuring what it claims.
        led = self._led()
        ref = json.load(open(os.path.join(
            ROOT, "data", "backtest", "b108_rescore_corrected.json")))
        for leg in ("cached", "W1", "W2", "W3", "W4"):
            self.assertEqual(
                led[leg]["pre_b109_constant_ladder"]["exp_R"],
                ref[leg]["funnel_graded"]["exp_R"],
                f"{leg}: the pre leg no longer reproduces b108's graded funnel")

    def test_b109_the_runner_leg_is_worth_noise_not_a_new_bar(self):
        # b110's neutrality test: a shift that is MIXED SIGN across independent
        # windows is noise, so the merit bar does not move. If the deltas ever
        # go one-sided, the b80/b81/b108 arm rankings are contaminated again
        # and this pin must be re-decided, not edited away.
        led = self._led()
        deltas = [led[leg]["delta"]["d_exp_R"]
                  for leg in ("cached", "W1", "W2", "W3", "W4")]
        self.assertTrue(all(d is not None for d in deltas))
        self.assertTrue(any(d > 0 for d in deltas) and any(d < 0 for d in deltas),
                        f"the A-grade runner leg shifted one-sided on every "
                        f"leg ({deltas}) — by b110 that is systematic, so the "
                        "stored funnel numbers need re-deciding")
        self.assertLessEqual(max(abs(d) for d in deltas), 0.025,
                             "the runner leg moved the headline more than "
                             "expected — re-read the b109 finding")

    def test_b109_dd_is_unchanged_by_the_lane_split(self):
        led = self._led()
        for leg in ("cached", "W1", "W2", "W3", "W4"):
            self.assertEqual(led[leg]["delta"]["d_dd_R"], 0.0,
                             f"{leg}: the lane split moved maxDD_R — the "
                             "runner leg is no longer risk-neutral")

    def test_b109_the_lane_census_shows_a_real_split(self):
        # Anti-vacuity: the fix must actually route A signals to the runner
        # lane and nobody else.
        led = self._led()
        for leg in ("cached", "W1", "W2", "W3", "W4"):
            split = led[leg]["lane_census"]["lane_split"]
            self.assertIn("A|0.3|strong_runner_keep_more", split, leg)
            self.assertIn("B|1.0|balanced_full_exit_at_tp1", split, leg)
            self.assertIn("C|1.0|weak_full_exit_at_tp1", split, leg)
            self.assertEqual(sum(1 for k in split if k.startswith("A|0.3")), 1)


if __name__ == "__main__":
    unittest.main()
