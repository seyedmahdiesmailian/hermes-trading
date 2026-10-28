#!/usr/bin/env python3
"""b109 probe — is the strong-runner lane REACHABLE at all, and do the two
live producers of the ladder's inputs agree?

Read-only analysis over data/xau_plan/plan_history/*.json (the plans the live
system actually wrote). No bridge call, no trade, no gate touched.

Two questions:

1. COLLAPSE: `_partial_close_fraction` gates the 0.3 strong-runner lane on
   four inputs (setup_grade, momentum_strength, rr_remaining, structure_state).
   Both live producers (hermes_runtime.cycle and position_daemon.build_trade)
   derive ALL FOUR from the same two plan-quality fields (alignment,
   trend_strength) with rr_remaining hardcoded to 2.0. If the four-way AND
   reduces to a single condition, the lane is not a four-factor judgement —
   it is one threshold, and the "thesis the parity backtest cannot model"
   comment in b55 is wrong about its own complexity.

2. DISAGREEMENT: the two producers do NOT use the same grade rule.
   hermes_runtime._infer_setup_grade requires regime in
   {breakout_continuation, pullback_continuation} for an A;
   position_daemon.build_trade inlines its own rule with NO regime clause and
   also lets 'mixed' alignment reach B. In production the watchdog is alive
   (heartbeat < 60s) whenever a position exists, so the ladder decision that
   actually runs is the WATCHDOG's, not the runtime's. Measure how often the
   two disagree on the lane.
"""
from __future__ import annotations

import collections
import glob
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

GRADE_RANK = {"A": 3, "B": 2, "C": 1}
RUNTIME_REGIMES = {"breakout_continuation", "pullback_continuation"}


def runtime_grade(alignment: str, trend: float, regime: str) -> str:
    """hermes_runtime._infer_setup_grade, restated for the probe."""
    if (alignment == "aligned" and trend >= 3.0
            and regime in RUNTIME_REGIMES):
        return "A"
    if alignment == "aligned" and trend >= 1.2:
        return "B"
    return "C"


def watchdog_grade(alignment: str, trend: float, regime: str) -> str:
    """position_daemon.build_trade's inline grade, restated for the probe."""
    if alignment == "aligned" and trend >= 3.0:
        return "A"
    if alignment in ("aligned", "mixed") and trend >= 1.2:
        return "B"
    return "C"


def lane_inputs(grade_fn):
    def fn(alignment, trend, regime):
        grade = grade_fn(alignment, trend, regime)
        return {
            "setup_grade": grade,
            "momentum_strength": min(1.0, max(0.2, trend / 2.0)),
            "rr_remaining": 2.0,                      # hardcoded by BOTH
            "structure_state": "healthy" if alignment == "aligned" else "mixed",
        }
    return fn


def strong_runner(inputs: dict) -> bool:
    g = GRADE_RANK[inputs["setup_grade"]]
    return (g >= 3 and inputs["momentum_strength"] >= 0.8
            and inputs["rr_remaining"] >= 2.0
            and inputs["structure_state"] == "healthy")


def weak(inputs: dict) -> bool:
    g = GRADE_RANK[inputs["setup_grade"]]
    return (g <= 1 or inputs["momentum_strength"] <= 0.4
            or inputs["rr_remaining"] <= 1.2
            or inputs["structure_state"] == "failing")


def main() -> int:
    files = sorted(glob.glob(os.path.join(_ROOT, "data", "xau_plan",
                                          "plan_history", "*.json")))
    combos = collections.Counter()
    for f in files:
        try:
            p = json.load(open(f))
        except Exception:
            continue
        q = p.get("quality") or {}
        al = str(q.get("alignment"))
        tr = float(q.get("trend_strength") or 0)
        rg = str(q.get("regime"))
        combos[(al, tr, rg)] += 1

    total = sum(combos.values())
    if not total:
        print("no plans found")
        return 1

    rt_in = lane_inputs(runtime_grade)
    wd_in = lane_inputs(watchdog_grade)

    collapse_ok = True
    rt_strong = wd_strong = disagree = 0
    rt_weak = wd_weak = 0
    for (al, tr, rg), n in combos.items():
        r, w = rt_in(al, tr, rg), wd_in(al, tr, rg)
        # COLLAPSE: lane == (grade A under that producer's own rule)?
        if strong_runner(r) != (r["setup_grade"] == "A"):
            collapse_ok = False
        if strong_runner(w) != (w["setup_grade"] == "A"):
            collapse_ok = False
        rt_strong += n * strong_runner(r)
        wd_strong += n * strong_runner(w)
        rt_weak += n * weak(r)
        wd_weak += n * weak(w)
        disagree += n * (strong_runner(r) != strong_runner(w))

    print(f"plans={total} distinct(align,trend,regime)={len(combos)}")
    print(f"COLLAPSE lane==grade-A: {collapse_ok}")
    print(f"runtime  strong-runner plans: {rt_strong} ({100*rt_strong/total:.1f}%)")
    print(f"watchdog strong-runner plans: {wd_strong} ({100*wd_strong/total:.1f}%)")
    print(f"lane DISAGREEMENT between producers: {disagree} ({100*disagree/total:.1f}%)")
    print(f"runtime weak-lane plans:  {rt_weak} ({100*rt_weak/total:.1f}%)")
    print(f"watchdog weak-lane plans: {wd_weak} ({100*wd_weak/total:.1f}%)")
    print("alignment:", dict(collections.Counter(a for (a, t, r) in combos)))
    print("regime:", dict(collections.Counter(r for (a, t, r) in combos)))
    print("trend>=3.0 plans:", sum(n for (a, t, r), n in combos.items() if t >= 3.0))
    print("aligned & trend>=3.0:", sum(n for (a, t, r), n in combos.items()
                                       if a == "aligned" and t >= 3.0))
    print("aligned & trend>=3.0 & regime ok:",
          sum(n for (a, t, r), n in combos.items()
              if a == "aligned" and t >= 3.0 and r in RUNTIME_REGIMES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
