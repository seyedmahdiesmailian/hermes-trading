#!/usr/bin/env python3
"""b121 step 2 — THE REST OF THE SHARE CURVE: IS partial_tp1_share A LEVER?

WHY (came out of step 1, scripts/b121_flat_share_replication.py)
================================================================
b119 crowned `flat_0.30` as "the candidate". Step 1 replicated it on two
windows never ranked before (W5, W6: +0.028/+0.035R) — but the same table
showed something b119's 5-arm grid could not see. `share` is the fraction
CLOSED at TP1, so a LOWER share means MORE of the position rides the trail, and
on every fresh window the ranking is monotone in that direction:

    flat_0.30 > flat_0.50 > flat_0.70 > incumbent(1.0 except A) > const 1.0

The more you let ride, the better the lab scores it — and the live grade gate,
which keeps the 0.3 runner on A only, sits on the WRONG side of its own rule
for every non-A trade. So "is flat_0.30 better" is the wrong question. The
question is whether the curve keeps rising to 0.0 (no partial at all) or turns
somewhere inside the range live could actually run.

WHAT THIS MEASURES
==================
The points step 1 did not: share in {0.0, 0.1, 0.2, 0.4, 0.9}, on the SAME
seven legs, same harness, same engine, arms differing in ONE parameter. Step
1's ledger supplies {0.3, 0.5, 0.7, 1.0, incumbent} — merged, not re-measured,
and the merge is CHECKED: the incumbent row must be byte-identical between the
two ledgers, so a silent harness change between rounds cannot splice two
different funnels into one curve.

Per arm per leg: exp_R / net_R / maxDD_R / hold stats (harness `r_stats`) plus
the EXIT-PATH census — how many trades ride past TP1 (partial + trail + a
second close) vs close in one call at TP1. That census is the OPERATIONAL cost
R cannot see: b121's founding note guessed the partial path would run "5x more
often"; the engine answers it directly instead of guessing.

Read-only research. Nothing is wired — a live exit-behaviour change is a human
gate (b89 class). Every live value (grade gate, min_rr, trail multiplier, $
floor, share fn, time exit) is imported or probed, never restated.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                     # noqa: E402
from engines.backtest import backtest_ohlc                # noqa: E402
from scripts import b81_lane_rescore as b81               # noqa: E402
from scripts.b121_flat_share_replication import (          # noqa: E402
    SELECTION, FRESH, LEGS, INCUMBENT, _rows_for, _path_census)

OUT = "data/backtest/b121b_share_sweep.json"
STEP1 = "data/backtest/b121_flat_share_replication.json"
NEW_SHARES = (0.0, 0.1, 0.2, 0.4, 0.9)
NEW_ARMS = tuple(f"flat_{s:.1f}" for s in NEW_SHARES)


def measure_leg(m15, h1, h4) -> dict:
    funnel = b81.funnel_fn(m15, h1, h4)
    ts = lh.live_time_stop_bars(m15)
    grid, census = {}, {}
    for name in NEW_ARMS:
        share = float(name.split("_")[1])
        kw = dict(lh.LADDER, time_stop_bars=ts,
                  partial_share_fn=lambda t, s=share: (s, "lab_flat_share"))
        res = backtest_ohlc(m15, funnel, min_rr=lh.MIN_RR, spread=lh.SPREAD,
                            min_grade=lh.LIVE_MIN_GRADE, **kw)
        grid[name] = lh.r_stats(res, time_stop_bars=ts)
        census[name] = _path_census(res)
    return {"_bars": len(m15), "_first": int(m15[0]["time"]),
            "_last": int(m15[-1]["time"]), "_time_stop_bars": ts,
            "share_grid": grid, "path_census": census}


def _merge(step1: dict, led: dict) -> dict:
    """Splice step 1's rows onto this round's, with an integrity check.

    The check is the point: if the incumbent row differs between the two
    ledgers, the two rounds measured different funnels and the merged curve is
    a fiction (b118's stale-bar lesson, applied to a merge)."""
    merged = {}
    for leg in LEGS:
        a = step1[leg]["share_grid"]
        b = led[leg]["share_grid"]
        if INCUMBENT in b and b[INCUMBENT] != a[INCUMBENT]:
            raise AssertionError(
                f"{leg}: incumbent row differs between step 1 and step 2 — "
                f"{a[INCUMBENT]} vs {b[INCUMBENT]}; the harness moved between "
                f"rounds, the merged curve is not one measurement")
        row = dict(a)
        row.update({k: v for k, v in b.items() if k != INCUMBENT})
        merged[leg] = row
    return merged


def _curve(merged: dict) -> dict:
    """Per leg: the exp_R curve ordered by share (descending share = least
    riding), where the max sits, and whether it is monotone.

    Names are parsed, not matched: step 1 wrote `flat_0.30` and this round
    writes `flat_0.3`, and a hand-typed name list silently DROPPED the step-1
    points from the curve on the first draft (n_points=6 instead of 10 — the
    b122 shape: an arm named for a rule the code could not see).
    """
    out = {}
    for leg in LEGS:
        pts = []
        for name, row in merged[leg].items():
            if row["exp_R"] is None:
                continue
            if name == INCUMBENT:
                continue
            s = 1.0 if name.endswith("const_1.0") else float(name.split("_", 1)[1])
            pts.append((s, name, row["exp_R"], row["net_R"], row["maxDD_R"]))
        pts.sort(key=lambda p: -p[0])
        best = max(pts, key=lambda p: p[2])
        worst = min(pts, key=lambda p: p[2])
        out[leg] = {
            "curve_by_share_desc": [{"share": p[0], "arm": p[1], "exp_R": p[2],
                                     "net_R": p[3], "maxDD_R": p[4]} for p in pts],
            "best_share": best[0], "best_arm": best[1], "best_exp_R": best[2],
            "worst_share": worst[0], "worst_exp_R": worst[2],
            "range_R": round(best[2] - worst[2], 3),
            # monotone in the RIDING direction (share descending => exp_R rising)
            "monotone_more_riding_better": all(
                pts[i][2] <= pts[i + 1][2] + 1e-9 for i in range(len(pts) - 1)),
            "incumbent_exp_R": merged[leg][INCUMBENT]["exp_R"],
            "incumbent_rank_in_curve": 1 + sum(
                1 for p in pts if p[2] > merged[leg][INCUMBENT]["exp_R"]),
            "n_points": len(pts),
        }
    return out


def main(argv: list[str]) -> int:
    rederive = "--rederive" in argv      # re-run the DERIVATION on saved rows
    step1 = json.load(open(STEP1))
    if rederive:
        led = json.load(open(OUT))
        merged = _merge(step1, {leg: led[leg] for leg in LEGS})
        led["_merged"] = merged
        led["_curve"] = _curve(merged)
        led["_path_census_merged"] = {leg: {**step1[leg]["path_census"],
                                            **led[leg]["path_census"]}
                                      for leg in LEGS}
        _report(led)
        json.dump(led, open(OUT, "w"), indent=1)
        print("re-derived from saved rows:", os.path.abspath(OUT))
        return 0
    led = {"_note": "b121b: the share points step 1 did not measure (0.0/0.1/"
                    "0.2/0.4/0.9), merged with step 1's rows into one curve per "
                    "leg. Question: does the runner-share dimension keep "
                    "improving to no-partial-at-all, or turn inside the "
                    "runnable range?",
           "_share_semantics": "share = fraction CLOSED at TP1. 1.0 = no runner; "
                               "0.0 = no partial at all (no BE move, no trail).",
           "_incumbent": "engines.trade_management._partial_close_fraction "
                         "(0.3 on the A lane, 1.0 elsewhere)",
           "_live_min_grade": lh.LIVE_MIN_GRADE,
           "_incumbent_ladder": {"tp1_position": lh.LADDER["tp1_position"],
                                 "trail_after_partial": lh.LADDER["trail_after_partial"],
                                 "trail_floor": lh.LADDER["trail_floor"]},
           "_selection_legs": list(SELECTION), "_fresh_legs": list(FRESH),
           "_step1_ledger": STEP1}
    for leg in LEGS:
        print(f"##### {leg} #####", flush=True)
        m15, h1, h4 = _rows_for(leg)
        led[leg] = measure_leg(m15, h1, h4)

    merged = _merge(step1, led)
    led["_merged"] = merged
    led["_curve"] = _curve(merged)
    led["_path_census_merged"] = {leg: {**step1[leg]["path_census"],
                                        **led[leg]["path_census"]} for leg in LEGS}

    _report(led)
    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))
    return 0


def _report(led: dict) -> None:
    print(f"{'leg':8s}" + "".join(f"{n:>12s}" for n in NEW_ARMS))
    for metric in ("exp_R", "net_R", "maxDD_R"):
        print(f"=== {metric} (new points) ===")
        for leg in LEGS:
            print(f"{leg:8s}" + "".join(
                f"{led[leg]['share_grid'][n][metric]!s:>12s}" for n in NEW_ARMS))
    print("=== FULL merged curve: exp_R by share (1.0 -> 0.0 = least -> most riding) ===")
    for leg in LEGS:
        c = led["_curve"][leg]
        print(f"{leg:8s} " + " ".join(
            f"{p['share']:.1f}={p['exp_R']}" for p in c["curve_by_share_desc"]) +
            f"  | incumbent={c['incumbent_exp_R']} rank={c['incumbent_rank_in_curve']}"
            f"/{c['n_points']} best={c['best_share']} range={c['range_R']}"
            f" monotone={c['monotone_more_riding_better']}")
    print("=== runner-path share (trades riding past TP1 / all trades) ===")
    for leg in LEGS:
        pc = led["_path_census_merged"][leg]
        print(f"{leg:8s} " + " ".join(
            f"{k.replace('incumbent_live_grade_fn','INC').replace('b66b_winner_as_measured_const_1.0','C1.0')}={pc[k]['runner_path_share']}"
            for k in sorted(pc)))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
