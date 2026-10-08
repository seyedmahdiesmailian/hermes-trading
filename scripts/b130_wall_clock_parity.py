#!/usr/bin/env python3
"""b130 — THE LAB'S TIME EXIT AND LIVE'S TIME EXIT ARE NOT THE SAME GUARD.

WHY THIS EXISTS
===============
b129 re-priced the b57 time-stop grid and reported the headline result that the
live 36h exit is INERT: `ts_0` (no time exit at all) differs from the incumbent
`ts_144` by EXACTLY 0.000R on all seven legs, and `holds_over_time_exit` is 0
everywhere (max hold 49..112 bars against a 144-bar exit). Its own note flagged
the reason that number cannot be trusted as a statement about LIVE: the lab
counts BAR age and live counts WALL-CLK age (filed as b130, half (a)).

Those two clocks are not interchangeable on XAUUSD. The market is closed Sunday
night and over holiday gaps, so 144 M15 bars is 36 hours of CONTINUOUS TAPE —
roughly 48 to 72 wall hours whenever a hold crosses a weekend. A trade can be
"young" in bars and long dead in live's eyes. b129's zeros therefore measure a
rule nobody runs, and any future retune of MAX_POSITION_AGE_HOURS decided on
them would rest on the wrong clock.

WHAT IS MEASURED
================
One harness, one funnel, the same seven legs b121/b123/b129 used (cached +
W1..W6, same bars, b81.funnel_fn, lh.LADDER with the live grade share fn,
min_grade imported from live, spread 0.20). The single parameter is the CLOCK:

  BAR CLOCK   time_stop_bars in {0, 8, 16, 24, 48, 96, 144}   (b129's grid)
  WALL CLOCK  time_stop_hours in {0, 2, 4, 6, 12, 24, 36}     (live's rule)

  x the two b123 gates (no_partial = the stored convention, age_only = live's
    actual exemption behaviour), because the exemption question is clock-
    independent and must stay answered on both.

The 36h wall arm IS live's guard: MAX_POSITION_AGE_HOURS is IMPORTED from
engines.legacy_guards, never restated, and the bar arm 144 is DERIVED from it
via lh.live_time_stop_bars (b71's rule). So the two grids meet at the same
nominal 36 hours and any difference between them is the clock, not the number.

THE THREE QUESTIONS
===================
Q1 Does the wall-clock exit bind where the bar-clock exit does not? (count of
   trades whose WALL age exceeds the limit while their BAR age does not — the
   exact population b129's zeros were blind to.)
Q2 Does the incumbent's exp_R MOVE under live's own clock, and by how much?
   (b129's "0.000R, inert" claim, re-read on the clock that decides it.)
Q3 Does the DIRECTION of b57/b129's verdict survive the clock change — is
   tightening still one-sidedly worse, and is any arm one-sidedly better?
   (b110 neutrality under b123's one_sided() AND b129's one_sided_strict()
   floor, half (b) of this item: every flag reports n_nonzero next to it.)

Integrity, before anything is read: the bar-clock ts_144 @ no_partial cell must
be BYTE-IDENTICAL to b129's and b123's and b121's incumbent rows (so this grid
is the same funnel, not a splice), and the wall-clock OFF arm must equal the
bar-clock OFF arm (no exit is no exit on either clock).

NOTHING IS WIRED. engines/legacy_guards.py is untouched; the new engine dial
`time_stop_hours` defaults to 0.0 = off, so every pre-b130 call site and every
stored ledger is byte-identical (pinned). A live time-stop retune is an
exit-behaviour change = human gate (b89 class). This round's product is the
CENSUS and the clock gap, not a new guard value.
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
from engines.legacy_guards import MAX_POSITION_AGE_HOURS   # noqa: E402
from scripts import b81_lane_rescore as b81                # noqa: E402
from scripts.b121_flat_share_replication import (          # noqa: E402
    LEGS, _rows_for)
from scripts.b123_protection_share_decomposition import (   # noqa: E402
    INC_ARM, one_sided)
from scripts.b129_timestop_reprice import (                 # noqa: E402
    STOP_BARS, GATES, GATE_LIVE, INCUMBENT_STOP, one_sided_strict)

OUT = "data/backtest/b130_wall_clock_parity.json"
LEDGER_129 = "data/backtest/b129_timestop_reprice.json"
LEDGER_123 = "data/backtest/b123_protection_share_decomposition.json"
LEDGER_121 = "data/backtest/b121_flat_share_replication.json"

# The wall-clock grid: the same nominal hours the bar grid expresses in M15
# bars, so bar ts_N and wall ts_Hh are the SAME decision read on two clocks.
HOUR_GRID = (0, 2, 4, 6, 12, 24, MAX_POSITION_AGE_HOURS)
LIVE_HOURS = float(MAX_POSITION_AGE_HOURS)

WINDOWS = tuple(w for w in LEGS if w != "cached")


def bar_name(n: int) -> str:
    return f"bar::ts_{n}"


def wall_name(h: float) -> str:
    return f"wall::ts_{int(h)}h"


def arms() -> list[tuple[str, dict]]:
    """(name, engine kwargs) for the full 28-arm grid, both clocks, both gates.

    Every arm rides lh.LADDER (the live-parity exit ladder, b118) and
    protection_mode="partial" (b123's stored coupling) — the ONLY thing that
    varies is the clock and its limit, so a bar/wall difference is a clock
    difference and nothing else.
    """
    out = []
    for gate in GATES:
        for n in STOP_BARS:
            out.append((f"{gate}::{bar_name(n)}",
                        dict(lh.LADDER, time_stop_bars=n, time_stop_gate=gate,
                             protection_mode="partial")))
        for h in HOUR_GRID:
            out.append((f"{gate}::{wall_name(h)}",
                        dict(lh.LADDER, time_stop_hours=float(h),
                             time_stop_gate=gate, protection_mode="partial")))
    return out


ARM_NAMES = tuple(n for n, _ in arms())


def measure_leg(m15, h1, h4) -> dict:
    """One leg: the live-parity funnel, both clocks, 28 arms."""
    funnel = b81.funnel_fn(m15, h1, h4)
    ts_bars = lh.live_time_stop_bars(m15)
    grid = {}
    for name, kw in arms():
        res = backtest_ohlc(m15, funnel, min_rr=lh.MIN_RR, spread=lh.SPREAD,
                            min_grade=lh.LIVE_MIN_GRADE, **kw)
        grid[name] = lh.r_stats(res, time_stop_bars=ts_bars)
    return {"_bars": len(m15), "_first": int(m15[0]["time"]),
            "_last": int(m15[-1]["time"]), "_time_stop_bars": ts_bars,
            "_wall_hours_span": round((int(m15[-1]["time"]) - int(m15[0]["time"]))
                                      / 3600.0, 1),
            "grid": grid, "_funnel": funnel}


def ages_off(m15: list[dict], funnel, gate: str) -> list[dict]:
    """Bar age AND wall age of every trade the OFF arm takes on this leg.

    Read off the no-exit run on purpose: an exit truncates the very tail the
    census is about, so the population must come from a run that never touches
    it. The run still rides lh.LADDER — the census is about the funnel's OWN
    trades as live manages them, not about a different exit shape.
    """
    res = backtest_ohlc(m15, funnel, min_rr=lh.MIN_RR, spread=lh.SPREAD,
                        min_grade=lh.LIVE_MIN_GRADE,
                        **dict(lh.LADDER, time_stop_gate=gate,
                               protection_mode="partial",
                               time_stop_bars=0, time_stop_hours=0.0))
    ts = [int(r["time"]) for r in m15]
    out = []
    for t in res.get("trade_log", []):
        ei, xi = int(t["entry_index"]), int(t["exit_index"])
        out.append({"bar_age": xi - ei,
                    "wall_age_h": round((ts[xi] - ts[ei]) / 3600.0, 2),
                    "exit_reason": t["exit_reason"],
                    "pnl": t["pnl"], "entry": t["entry"]})
    return out


def census(ages: list[dict], bars: int, hours: float) -> dict:
    """Q1: who is old on one clock and young on the other?"""
    over_bar = [a for a in ages if a["bar_age"] >= bars]
    over_wall = [a for a in ages if a["wall_age_h"] >= hours]
    wall_only = [a for a in ages if a["wall_age_h"] >= hours
                 and a["bar_age"] < bars]
    return {"n_trades": len(ages),
            "max_bar_age": max((a["bar_age"] for a in ages), default=None),
            "max_wall_age_h": max((a["wall_age_h"] for a in ages), default=None),
            "n_over_bar": len(over_bar), "n_over_wall": len(over_wall),
            "n_wall_only": len(wall_only),
            "wall_only": sorted(wall_only, key=lambda a: -a["wall_age_h"])[:12]}


def _g(led, leg, name, metric="exp_R"):
    return (led[leg]["grid"].get(name) or {}).get(metric)


def integrity(led, l129: dict, l123: dict, l121: dict) -> dict:
    """The bar-clock incumbent must be the SAME TRADE the frozen ledgers froze,
    and 'no exit' must be the same trade on both clocks."""
    checks = {}
    for leg in LEGS:
        inc_bar = led[leg]["grid"][f"{GATE_LIVE}::{bar_name(INCUMBENT_STOP)}"]
        checks[leg] = {
            "bar_incumbent_matches_b129":
                inc_bar == l129[leg]["grid"][f"{GATE_LIVE}::ts_{INCUMBENT_STOP}"],
            "bar_incumbent_matches_b123":
                inc_bar == l123[leg]["grid"][f"no_partial::{INC_ARM}"],
            "bar_incumbent_matches_b121":
                inc_bar == l121[leg]["share_grid"]["incumbent_live_grade_fn"],
            "off_arms_agree_across_clocks":
                led[leg]["grid"][f"{GATE_LIVE}::{bar_name(0)}"]
                == led[leg]["grid"][f"{GATE_LIVE}::{wall_name(0)}"],
        }
    return checks


def deltas(led, metric="exp_R") -> dict:
    """Every arm minus the BAR-clock incumbent (b129's reference cell), so the
    two clocks' verdicts are directly comparable on one axis."""
    ref = f"{GATE_LIVE}::{bar_name(INCUMBENT_STOP)}"
    out = {}
    for name, _kw in arms():
        row = {}
        for leg in LEGS:
            a, b = _g(led, leg, name, metric), _g(led, leg, ref, metric)
            row[leg] = round(a - b, 3) if a is not None and b is not None else None
        out[name] = row
    return out


def neutrality(led) -> dict:
    """b110's test per arm under b123's one_sided() and b129's strict floor.

    b130 half (b) is the point of this block: every row reports n_nonzero NEXT
    TO the flag, because on a grid with inert arms a proportion alone is
    meaningless (one +0.006 over five exact zeros is a 100% majority).
    """
    d = deltas(led)
    out = {}
    for name, row in d.items():
        vals = [row[w] for w in WINDOWS if row[w] is not None]
        pos = sum(1 for v in vals if v > 0)
        neg = sum(1 for v in vals if v < 0)
        out[name] = {"per_leg": row, "n_windows": len(vals),
                     "positive": pos, "negative": neg, "n_nonzero": pos + neg,
                     "one_sided": one_sided(pos, neg),
                     "unanimous": one_sided_strict(pos, neg, len(WINDOWS)),
                     "mean_R": round(sum(vals) / len(vals), 4) if vals else None,
                     "max_abs_R": max((abs(v) for v in vals), default=None)}
    return out


def clock_gap(led) -> dict:
    """Q2's headline table: bar ts_N vs wall ts_Nh at the same nominal hours."""
    out = {}
    for gate in GATES:
        rows = {}
        for n, h in zip(STOP_BARS, HOUR_GRID):
            b = f"{gate}::{bar_name(n)}"
            w = f"{gate}::{wall_name(h)}"
            rows[f"{n}bars/{h}h"] = {
                leg: {"bar": _g(led, leg, b), "wall": _g(led, leg, w),
                      "wall_minus_bar": (round(_g(led, leg, w) - _g(led, leg, b), 3)
                                         if _g(led, leg, w) is not None
                                         and _g(led, leg, b) is not None else None)}
                for leg in LEGS}
        out[gate] = rows
    return out


def verdict(led) -> dict:
    neu = neutrality(led)
    off_wall = f"{GATE_LIVE}::{wall_name(0)}"
    inc_bar = f"{GATE_LIVE}::{bar_name(INCUMBENT_STOP)}"
    inc_wall = f"{GATE_LIVE}::{wall_name(LIVE_HOURS)}"
    cen = {leg: led[leg]["_census"] for leg in LEGS}
    return {
        "live_incumbent_exp_R_bar_clock": {leg: _g(led, leg, inc_bar) for leg in LEGS},
        "live_incumbent_exp_R_wall_clock": {leg: _g(led, leg, inc_wall) for leg in LEGS},
        "wall_minus_bar_at_live_limit_R": {
            leg: (round(_g(led, leg, inc_wall) - _g(led, leg, inc_bar), 3)
                  if _g(led, leg, inc_wall) is not None
                  and _g(led, leg, inc_bar) is not None else None)
            for leg in LEGS},
        # b129's headline was "ts_0 differs from the incumbent by 0.000R on all
        # seven legs" — i.e. the guard never binds. Same claim, wall clock.
        "b129_inert_claim_holds_on_wall_clock": all(
            _g(led, leg, off_wall) == _g(led, leg, inc_wall) for leg in LEGS),
        "n_trades_over_live_limit_wall_clock": {leg: cen[leg]["n_over_wall"]
                                                for leg in LEGS},
        "n_trades_wall_only": {leg: cen[leg]["n_wall_only"] for leg in LEGS},
        "one_sided_arms_wall_clock": sorted(
            n for n, v in neu.items()
            if n.startswith(GATE_LIVE + "::wall::") and v["one_sided"]),
        "unanimous_arms_wall_clock": sorted(
            n for n, v in neu.items()
            if n.startswith(GATE_LIVE + "::wall::") and v["unanimous"]),
        "one_sided_arms_bar_clock": sorted(
            n for n, v in neu.items()
            if n.startswith(GATE_LIVE + "::bar::") and v["one_sided"]),
    }


def main() -> int:
    l129 = json.load(open(LEDGER_129))
    l123 = json.load(open(LEDGER_123))
    l121 = json.load(open(LEDGER_121))
    led = {"_note": "b130: the lab's time exit counts BAR age, live's counts "
                    "WALL-CLK age. Both grids re-measured on one funnel, seven "
                    "legs, both b123 gates. Nothing wired; legacy_guards "
                    "untouched; the new engine dial defaults to off.",
           "_live_guard": f"engines.legacy_guards.MAX_POSITION_AGE_HOURS = "
                          f"{MAX_POSITION_AGE_HOURS}h (imported, not restated)",
           "_frame": "M15 legs (b121/b123/b129's seven), live-parity funnel from "
                     "b81.funnel_fn, lh.LADDER (grade share fn, trail+floor "
                     "derived per b118), min_grade=live, spread=0.20.",
           "_bar_grid_m15": list(STOP_BARS),
           "_wall_grid_hours": [float(h) for h in HOUR_GRID],
           "_incumbent_bar": f"{GATE_LIVE}::{bar_name(INCUMBENT_STOP)}",
           "_incumbent_wall": f"{GATE_LIVE}::{wall_name(LIVE_HOURS)}",
           "_legs": list(LEGS)}
    for leg in LEGS:
        print(f"##### {leg} #####", flush=True)
        m15, h1, h4 = _rows_for(leg)
        led[leg] = measure_leg(m15, h1, h4)
        # the closure is carried out of measure_leg so the census reuses the
        # SAME funnel the grid was scored on (b76: same bars, one evaluation);
        # it is popped before the dump because a function is not JSON.
        funnel = led[leg].pop("_funnel")
        led[leg]["_ages_off"] = ages_off(m15, funnel, GATE_LIVE)
        led[leg]["_census"] = census(led[leg]["_ages_off"],
                                     INCUMBENT_STOP, LIVE_HOURS)
        print(f"  trades {led[leg]['_census']['n_trades']}  "
              f"over-bar {led[leg]['_census']['n_over_bar']}  "
              f"over-wall {led[leg]['_census']['n_over_wall']}  "
              f"wall-only {led[leg]['_census']['n_wall_only']}  "
              f"max wall {led[leg]['_census']['max_wall_age_h']}h", flush=True)

    led["_integrity"] = integrity(led, l129, l123, l121)
    bad = {leg: c for leg, c in led["_integrity"].items()
           if not all(v for v in c.values())}
    if bad:
        raise AssertionError(f"incumbent/off-arm integrity failed: {bad}")

    led["_grid"] = {leg: {name: {m: led[leg]["grid"][name].get(m)
                                 for m in ("trades", "exp_R", "net_R", "maxDD_R",
                                           "mean_hold_bars", "max_hold_bars")}
                          for name in ARM_NAMES}
                    for leg in LEGS}
    led["_delta_exp_R"] = deltas(led, "exp_R")
    led["_delta_net_R"] = deltas(led, "net_R")
    led["_delta_maxDD_R"] = deltas(led, "maxDD_R")
    led["_neutrality"] = neutrality(led)
    led["_clock_gap"] = clock_gap(led)
    led["_verdict"] = verdict(led)
    _report(led)
    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))
    return 0


def _report(led: dict) -> None:
    print("=== census: trades old on the wall clock but young in bars ===")
    print(f"{'leg':8s}{'n':>5s}{'maxBar':>8s}{'maxWallH':>10s}"
          f"{'>bar':>6s}{'>wall':>7s}{'wallOnly':>10s}")
    for leg in LEGS:
        c = led[leg]["_census"]
        print(f"{leg:8s}{c['n_trades']:>5d}{c['max_bar_age']:>8d}"
              f"{c['max_wall_age_h']:>10.1f}{c['n_over_bar']:>6d}"
              f"{c['n_over_wall']:>7d}{c['n_wall_only']:>10d}")
    print("=== exp_R: bar clock vs wall clock at the same nominal hours ===")
    for gate in GATES:
        print(f"-- gate {gate} --")
        print(f"{'leg':8s}" + "".join(f"{k:>13s}" for k in led["_clock_gap"][gate]))
        for leg in LEGS:
            cells = []
            for k, row in led["_clock_gap"][gate].items():
                cells.append(f"{row[leg]['bar']!s}/{row[leg]['wall']!s}".rjust(13))
            print(f"{leg:8s}" + "".join(cells))
    print("=== verdict ===")
    print(json.dumps(led["_verdict"], indent=1)[:3000])


if __name__ == "__main__":
    raise SystemExit(main())
