#!/usr/bin/env python3
"""b129 (b107 research round, exit side) — RE-PRICE THE TIME-STOP GRID.

WHY THIS EXISTS
===============
b107's mandate is an EXIT-side improvement, and the one exit lever that has
never been measured on the corrected engine is the time stop itself.
scripts/ab_b57_timestop.py (2026-08-31) swept N in {0, 12, 24, 48} on 6500 M5
bars and its ledger (data/backtest/ab_b57_timestop.json) is the evidence behind
the live 36h `MAX_POSITION_AGE_HOURS`. That sweep ran on an engine that has
since changed under it four times:

  * b105 deleted the phantom full-size runner (every TP1 winner used to be
    booked twice) — the population b57 scored no longer exists;
  * b80 found the funnel baseline was scored with NO grade gate, so it traded
    every C setup live rejects (b57 ran through run_backtest, whose default is
    min_grade="B", but with min_rr=1.5 AND no ladder share fn — see FRAME below);
  * b109+b118 made the ladder live-parity (real share fn fed real ladder fields,
    trail multiplier AND $ floor derived from `_trail_params`);
  * b123 showed the time exit is itself coupled to the share dial through the
    `no_partial` exemption, so "the time stop" is TWO rules, not one.

b119's founding RULE (generalising b83) is explicit about this family: "when an
engine fix deletes a POPULATION rather than shifting a number, every stored
decision whose evidence was measured ON that population must be re-priced, not
just re-baselined ... Specifically suspect: b66's TP1-step grid, b66b's
grade-weighted sizing, and b56/b57/b61's arms." b117 re-priced b65's trail,
b119 re-priced b66/b66b. b57 is the remaining one, and it is the only one that
decides a LIVE GUARD VALUE (36h), so it is the one whose re-pricing can change
production behaviour (through b124's parity question and any future retune).

WHAT IS MEASURED
================
One harness, one funnel, one parameter at a time (b72's pure-arm rule), on the
SAME seven legs b121/b123 used (cached + W1..W6, same bars, same
live-parity funnel from b81.funnel_fn):

  TIME STOP N in {0 (off), 8, 16, 24, 48, 96, 144} M15 bars
      144 = the live 36h exit expressed in this dataset's bar length (DERIVED by
      lh.live_time_stop_bars, never hardcoded — b71's rule), so the incumbent
      column IS live. 8/16/24/48/96 = 2h/4h/6h/12h/24h.
  x the TWO time-exit gates b123 named:
      "no_partial" = the stored convention (a trade that took a TP1 partial is
                     EXEMPT — the time exit only ever kills non-runners),
      "age_only"   = live's actual rule (evaluate_time_exit is purely age-based
                     and does not care about partials).
  x the live incumbent share rule (grade fn) — the share dial is HELD, not swept
    (b123's lesson: sweeping it moves four things at once).

So 14 arms per leg, and the incumbent (144 @ no_partial) must reproduce b123's
incumbent row BYTE-IDENTICALLY or the round is splicing two funnels (integrity).

THE THREE QUESTIONS THIS ANSWERS
================================
Q1 Does the live 36h exit earn its place at all, or is a tighter/looser exit
   one-sidedly better on the corrected engine? (b57's answer was "no time stop
   is best" — measured on the phantom-runner engine, on M5, un-laddered.)
Q2 Does the answer depend on the GATE, i.e. on whether runners are exempt?
   b123 measured the exemption's cost at the CANDIDATE's shape (share 0.3) and
   found it inert. At a SHORT time stop the exemption is the whole mechanism:
   a 2h exit that cannot touch a runner is a different guard than a 2h exit
   that can. If the two gates disagree on the best N, the stored 36h is
   defending a rule nobody has measured as live runs it.
Q3 Is the funnel's hold distribution even compatible with 36h? (mean/p95/max
   hold per arm, plus holds_over_time_exit — b71's mandatory hold columns.)

VERDICT RULE: b110's neutrality test under b123's leg-count-corrected
definition (one_sided() imported from b123, never restated), applied to
arm-minus-incumbent exp_R per leg, with the fresh pair (W5/W6) reported
separately so in-sample one-sidedness cannot be read as replication.

NOTHING IS WIRED. A live time-stop retune changes exit behaviour = human gate
(b89 class), and engines/legacy_guards.py is untouched by this round.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                      # noqa: E402
from engines.backtest import backtest_ohlc                 # noqa: E402
from scripts import b81_lane_rescore as b81                 # noqa: E402
from scripts.b121_flat_share_replication import (           # noqa: E402
    SELECTION, FRESH, LEGS, _rows_for)
from scripts.b123_protection_share_decomposition import (    # noqa: E402
    INC_ARM, one_sided)

OUT = "data/backtest/b129_timestop_reprice.json"
STEP1 = "data/backtest/b121_flat_share_replication.json"
STEP3 = "data/backtest/b123_protection_share_decomposition.json"

# The grid, in M15 bars. 144 is NOT a literal choice: it is what
# lh.live_time_stop_bars returns for this dataset (36h / 900s), so the
# incumbent arm is live's own guard. The rest are the round-number hours a
# retune would actually consider.
STOP_BARS = (0, 8, 16, 24, 48, 96, 144)
GATES = ("no_partial", "age_only")
GATE_LIVE = "no_partial"          # the stored convention every number uses
INCUMBENT_STOP = 144              # == lh.live_time_stop_bars on M15 (pinned)


def arm_name(gate: str, n: int) -> str:
    return f"{gate}::ts_{n}"


def arms() -> list[tuple[str, str, int]]:
    return [(arm_name(g, n), g, n) for g in GATES for n in STOP_BARS]


ARM_NAMES = tuple(n for n, _, _ in arms())


def measure_leg(m15, h1, h4) -> dict:
    """One leg: the live-parity funnel, the live ladder, 14 time-stop arms."""
    funnel = b81.funnel_fn(m15, h1, h4)
    ts = lh.live_time_stop_bars(m15)
    grid = {}
    for name, gate, n in arms():
        kw = dict(lh.LADDER, protection_mode="partial", time_stop_gate=gate,
                  time_stop_bars=(n if n else 0))
        res = backtest_ohlc(m15, funnel, min_rr=lh.MIN_RR, spread=lh.SPREAD,
                            min_grade=lh.LIVE_MIN_GRADE, **kw)
        grid[name] = lh.r_stats(res, time_stop_bars=ts)
    return {"_bars": len(m15), "_first": int(m15[0]["time"]),
            "_last": int(m15[-1]["time"]), "_time_stop_bars": ts,
            "grid": grid}


def _g(led, leg, gate, n, metric="exp_R"):
    row = led[leg]["grid"].get(arm_name(gate, n)) or {}
    return row.get(metric)


def integrity(led, step1: dict, step3: dict) -> dict:
    """The incumbent cell must be the SAME TRADE b121/b123 already froze.

    b123's incumbent row is `no_partial::partial::live_grade_share` at the
    derived live time stop; b121's is `incumbent_live_grade_fn`. If either
    differs from this round's ts_144 @ no_partial, the funnel, the ladder or
    the bars moved and every delta below is a splice (b121b's merge check).
    """
    checks = {}
    for leg in LEGS:
        inc = led[leg]["grid"][arm_name(GATE_LIVE, INCUMBENT_STOP)]
        checks[leg] = {
            "incumbent_matches_b123": inc == step3[leg]["grid"][f"no_partial::{INC_ARM}"],
            "incumbent_matches_b121": inc == step1[leg]["share_grid"]["incumbent_live_grade_fn"],
        }
    return checks


def grid_table(led) -> dict:
    """Per leg: exp_R / net_R / maxDD_R / trades for all 14 arms."""
    out = {}
    for leg in LEGS:
        out[leg] = {name: {m: led[leg]["grid"][name].get(m)
                           for m in ("trades", "exp_R", "net_R", "maxDD_R",
                                     "mean_hold_bars", "p95_hold_bars",
                                     "max_hold_bars", "holds_over_time_exit")}
                    for name in ARM_NAMES}
    return out


def deltas(led, metric="exp_R") -> dict:
    """arm minus incumbent (144 @ the stored gate), per leg."""
    out = {}
    for name, gate, n in arms():
        row = {}
        for leg in LEGS:
            a = _g(led, leg, gate, n, metric)
            b = _g(led, leg, GATE_LIVE, INCUMBENT_STOP, metric)
            row[leg] = (round(a - b, 3)
                        if a is not None and b is not None else None)
        out[name] = row
    return out


def one_sided_strict(pos: int, neg: int, n_legs: int) -> bool:
    """b123's proportion rule PLUS a minimum-evidence floor — the tooling
    finding this round exists to record (filed as b130).

    b123 replaced b110's `pos >= 3 or neg >= 3` (a tautology at n=7) with
    ">=3/4 majority and <=1 dissent". That fixes the MAJORITY half but says
    nothing about the DENOMINATOR: neutrality() can only count legs whose delta
    is non-zero, and on a time-stop grid most arms are byte-identical to the
    incumbent because the exit never binds. So a single +0.006R observation on
    one window out of six arrives as (pos=1, neg=0), which is a 100% majority
    with zero dissent and passes. ts_96 is flagged one_sided on exactly that
    shape — one leg, five inert zeros.

    The floor is therefore: at least half the independent windows (never fewer
    than 3) must have produced a non-zero delta. It cannot weaken b123's own
    shipped flags (b127 reproduces those from b123's code, untouched); it only
    makes this round's flags mean what their name says.
    """
    n = pos + neg
    return one_sided(pos, neg) and n >= max(3, (n_legs + 1) // 2)


def neutrality(led) -> dict:
    """b110's test per arm, under b123's leg-count-corrected one_sided() and
    under this round's minimum-evidence floor (one_sided_strict).

    cached is NOT independent evidence (b68's rule), so the flags are computed
    on the SIX real windows only and the fresh pair is reported separately — a
    one-sided result that only holds on the selection set is contamination, not
    replication.
    """
    WINDOWS = tuple(w for w in LEGS if w != "cached")
    d = deltas(led)
    out = {}
    for name, row in d.items():
        vals = [row[w] for w in WINDOWS if row[w] is not None]
        fresh = [row[w] for w in FRESH if row[w] is not None]
        pos = sum(1 for v in vals if v > 0)
        neg = sum(1 for v in vals if v < 0)
        out[name] = {
            "per_leg": row, "n_windows": len(vals),
            "positive": pos, "negative": neg,
            "n_nonzero": pos + neg,
            "one_sided": one_sided(pos, neg),
            "unanimous": one_sided_strict(pos, neg, len(WINDOWS)),
            "fresh_legs": {w: row[w] for w in FRESH},
            "fresh_all_same_sign": (len(fresh) == len(FRESH)
                                    and (all(v > 0 for v in fresh)
                                         or all(v < 0 for v in fresh))),
            "mean_R": round(sum(vals) / len(vals), 4) if vals else None,
            "max_abs_R": max((abs(v) for v in vals), default=None),
        }
    return out


def best_per_gate(led) -> dict:
    """Where the optimum sits under each gate, per leg — Q2's table."""
    out = {}
    for gate in GATES:
        rows = {}
        for leg in LEGS:
            pts = [(n, _g(led, leg, gate, n)) for n in STOP_BARS]
            pts = [(n, v) for n, v in pts if v is not None]
            best = max(pts, key=lambda p: p[1])
            worst = min(pts, key=lambda p: p[1])
            rows[leg] = {"best_ts": best[0], "best_exp_R": best[1],
                         "worst_ts": worst[0], "worst_exp_R": worst[1],
                         "range_R": round(best[1] - worst[1], 3),
                         "incumbent_exp_R": _g(led, leg, gate, INCUMBENT_STOP),
                         "incumbent_is_best": best[0] == INCUMBENT_STOP}
        out[gate] = rows
    return out


def gate_gap(led) -> dict:
    """age_only minus no_partial at each N: what the runner exemption is worth
    once the stop is short enough to bite (b123 measured it only at the
    candidate's shape and at the live 144, where it was inert)."""
    out = {}
    for n in STOP_BARS:
        row = {}
        for leg in LEGS:
            a = _g(led, leg, "age_only", n)
            b = _g(led, leg, GATE_LIVE, n)
            row[leg] = round(a - b, 3) if a is not None and b is not None else None
        out[f"ts_{n}"] = row
    return out


def verdict(led) -> dict:
    """The three questions, answered off the ledger by pure arithmetic."""
    neu = neutrality(led)
    bt = best_per_gate(led)
    gap = gate_gap(led)
    WINDOWS = tuple(w for w in LEGS if w != "cached")

    # Q1: any arm one-sidedly better than live's 144 on the stored gate?
    q1 = {name: v for name, v in neu.items()
          if name.startswith(GATE_LIVE + "::") and v["one_sided"]}
    # Q2: do the two gates disagree about where the optimum is?
    disagree = [leg for leg in LEGS
                if bt["age_only"][leg]["best_ts"] != bt[GATE_LIVE][leg]["best_ts"]]
    # Q3: is the incumbent's own hold tail even near the exit?
    holds = {leg: {"mean": led[leg]["grid"][arm_name(GATE_LIVE, INCUMBENT_STOP)]["mean_hold_bars"],
                   "p95": led[leg]["grid"][arm_name(GATE_LIVE, INCUMBENT_STOP)]["p95_hold_bars"],
                   "max": led[leg]["grid"][arm_name(GATE_LIVE, INCUMBENT_STOP)]["max_hold_bars"],
                   "over": led[leg]["grid"][arm_name(GATE_LIVE, INCUMBENT_STOP)]["holds_over_time_exit"]}
             for leg in LEGS}
    incumbent_still_best = all(
        bt[GATE_LIVE][leg]["incumbent_is_best"] for leg in WINDOWS)
    return {
        "one_sided_arms_vs_incumbent_exp_R": sorted(q1),
        "incumbent_144_is_best_on_every_window": incumbent_still_best,
        "best_ts_by_gate": {g: {leg: bt[g][leg]["best_ts"] for leg in LEGS}
                            for g in GATES},
        "gates_disagree_on_best_ts": disagree,
        "max_gate_gap_R": max((abs(v) for row in gap.values() for v in row.values()
                               if v is not None), default=None),
        "incumbent_hold_stats": holds,
        "n_windows": len(WINDOWS),
    }


def main() -> int:
    step1 = json.load(open(STEP1))
    step3 = json.load(open(STEP3))
    led = {"_note": "b129 (b107 exit-side round): the b57 time-stop grid "
                    "re-priced on the corrected live-parity engine, cached + "
                    "W1..W6, one parameter (time_stop_bars) at a time, under "
                    "both b123 gates. Nothing wired; legacy_guards untouched.",
           "_live_guard": "engines.legacy_guards.MAX_POSITION_AGE_HOURS = 36h; "
                          "the lab's exemption of partial-taken trades is the "
                          "stored convention (no_partial), live's rule is age_only",
           "_frame": "M15 legs (b121/b123's seven), live-parity funnel from "
                     "b81.funnel_fn, lh.LADDER (grade share fn, trail+floor "
                     "derived), min_grade=live, spread=0.20. b57's original "
                     "sweep ran on 6500 M5 bars through run_backtest with "
                     "trail_after_partial=0.5 and NO share fn — a different "
                     "engine AND a different frame.",
           "_original_b57_ledger": "data/backtest/ab_b57_timestop.json",
           "_stop_bars_m15": list(STOP_BARS),
           "_gates": list(GATES),
           "_incumbent": arm_name(GATE_LIVE, INCUMBENT_STOP),
           "_live_min_grade": lh.LIVE_MIN_GRADE,
           "_selection_legs": list(SELECTION), "_fresh_legs": list(FRESH)}
    for leg in LEGS:
        print(f"##### {leg} #####", flush=True)
        m15, h1, h4 = _rows_for(leg)
        led[leg] = measure_leg(m15, h1, h4)

    # the derived live stop must equal the incumbent literal on every leg, or
    # "144" is not live's guard and the incumbent column is a fiction.
    led["_live_stop_check"] = {leg: {"derived": led[leg]["_time_stop_bars"],
                                     "pinned_incumbent": INCUMBENT_STOP,
                                     "equal": led[leg]["_time_stop_bars"] == INCUMBENT_STOP}
                               for leg in LEGS}
    bad = [leg for leg, v in led["_live_stop_check"].items() if not v["equal"]]
    if bad:
        raise AssertionError(f"live time stop is not {INCUMBENT_STOP} bars on {bad}")

    led["_integrity"] = integrity(led, step1, step3)
    bad = {leg: c for leg, c in led["_integrity"].items()
           if not all(v for v in c.values())}
    if bad:
        raise AssertionError(f"stored incumbent rows do not reproduce: {bad}")

    led["_grid"] = grid_table(led)
    led["_delta_exp_R"] = deltas(led, "exp_R")
    led["_delta_net_R"] = deltas(led, "net_R")
    led["_delta_maxDD_R"] = deltas(led, "maxDD_R")
    led["_neutrality"] = neutrality(led)
    led["_best_per_gate"] = best_per_gate(led)
    led["_gate_gap"] = gate_gap(led)
    led["_verdict"] = verdict(led)
    _report(led)
    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))
    return 0


def _report(led: dict) -> None:
    print("=== exp_R by time stop (M15 bars), per gate ===")
    print(f"{'leg':8s}{'gate':12s}" + "".join(f"{n:>9d}" for n in STOP_BARS))
    for leg in LEGS:
        for gate in GATES:
            row = [_g(led, leg, gate, n) for n in STOP_BARS]
            print(f"{leg:8s}{gate:12s}" + "".join(f"{v!s:>9}" for v in row))
    print("=== delta vs incumbent (144 @ no_partial), exp_R ===")
    d = led["_delta_exp_R"]
    print(f"{'arm':22s}" + "".join(f"{leg:>9s}" for leg in LEGS))
    for name in ARM_NAMES:
        print(f"{name:22s}" + "".join(f"{d[name][leg]!s:>9}" for leg in LEGS))
    print("=== verdict ===")
    print(json.dumps(led["_verdict"], indent=1)[:2500])


if __name__ == "__main__":
    raise SystemExit(main())
