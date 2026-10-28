#!/usr/bin/env python3
"""b121 — DOES flat_0.30 REPLICATE ON WINDOWS IT WAS NEVER RANKED ON?

WHY THIS EXISTS
===============
b119 re-priced the b66b exit-share decision under the corrected engine and
found the incumbent's own evidence was a phantom (the "grade-weighted" arm was
a constant 1.0), and that `flat_0.30` — keep a 0.3 runner on EVERY trade
instead of only on the A lane — beat the live grade-weighted incumbent
one-sided on exp_R in 4/4 windows (+0.002..+0.046R).

Those four windows are W1..W4: the same bars every exit decision in this repo
has been chosen on since b68l built them. b74's protocol is explicit that a
one-sided delta on the selection set is NOT replication. So b121's precondition
1 was: re-measure on a FRESH draw. scripts/b121_fresh_windows.py cut W5 and W6
out of the broker's deep history — 6000 M15 bars each, strictly before W4,
overlap with cached/W1..W4/the other new window MEASURED to zero — and this
round scores the same arms on them.

WHAT IS MEASURED (three things, one harness)
============================================
1. REPLICATION. incumbent (live `_partial_close_fraction`) vs flat 0.30 / 0.50
   / 0.70 vs the constant-1.0 arm b66b actually crowned, on cached + W1..W4
   (selection set, must reproduce b119's ledger exactly — an integrity pin) and
   on W5 + W6 (fresh, never ranked). The verdict is read off the FRESH pair
   only; the selection set is the control.
2. THE COST SIDE the lab cannot see in R. A 0.3 runner on every trade means
   every TP1 winner takes the partial-close path instead of the close-at-TP1
   path: 1 partial + 1 later close + trail modifies, versus 1 close. That is
   bridge-call volume and MT5 rejection surface (`_tp1_exit_closes_all`,
   retcode 10026 handling in position_daemon), an OPERATIONAL change, not an R
   change. Measured here as the exit-path census per arm per leg — a PROXY for
   call volume, honestly labelled as such (the lab cannot measure rejections).
3. b110's neutrality test across SIX windows (>=3 one-sided = contaminated
   ranking), with the fresh pair reported separately so a reader cannot
   mistake "6/6 one-sided" for "replicated on 6 independent draws".

Nothing here is wired. This is a live EXIT-BEHAVIOUR question = human gate
(b89 class); the autopilot measures and reports, it does not re-wire the path.
Every live value (grade gate, min_rr, trail multiplier, trail floor, share
function, time exit) is IMPORTED or PROBED, never restated.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                    # noqa: E402
from engines.backtest import backtest_ohlc               # noqa: E402
from engines.trade_management import _partial_close_fraction  # noqa: E402
from scripts import b81_lane_rescore as b81              # noqa: E402
from scripts import b68l_windows as wl                    # noqa: E402
from scripts import b121_fresh_windows as fw              # noqa: E402

OUT = "data/backtest/b121_flat_share_replication.json"

SELECTION = ("cached", "W1", "W2", "W3", "W4")     # the bars b119 ranked on
FRESH = ("W5", "W6")                                # never ranked (b121's draw)
LEGS = SELECTION + FRESH

INCUMBENT = "incumbent_live_grade_fn"
ARMS = ((INCUMBENT, "grade"),
        ("b66b_winner_as_measured_const_1.0", 1.0),
        ("flat_0.30", 0.30), ("flat_0.50", 0.50), ("flat_0.70", 0.70))
ARM_NAMES = tuple(n for n, _ in ARMS)

# exit_reason -> which live path produced it (see engines/backtest.py _close)
RUNNER_EXITS = ("tp", "sl_part")     # a runner survived TP1: partial + close
FULL_AT_TP1_EXITS = ("tp1_full",)    # share>=1.0: one close_position at TP1


def _share_fn(value):
    if value == "grade":
        return _partial_close_fraction
    return lambda t: (float(value), "lab_flat_share")


def _rows_for(leg: str) -> tuple[list, list, list]:
    if leg == "cached":
        c = json.load(open("data/backtest/ab_aggressive_data.json"))
        return c["M15"], c["H1"], c["H4"]
    if leg in wl.WINDOW_NAMES:
        w = wl.load_windows()[leg]
        return w["M15"], w["H1"], w["H4"]
    return fw.load()[leg]["M15"], fw.load()[leg]["H1"], fw.load()[leg]["H4"]


def _path_census(res: dict) -> dict:
    """How many trades took the partial-close path vs the close-at-TP1 path."""
    log = res.get("trade_log", [])
    n = len(log)
    runner = sum(1 for t in log if t.get("exit_reason") in RUNNER_EXITS)
    full = sum(1 for t in log if t.get("exit_reason") in FULL_AT_TP1_EXITS)
    return {"trades": n,
            "runner_path_trades": runner,
            "close_at_tp1_trades": full,
            "other_exit_trades": n - runner - full,
            "runner_path_share": round(runner / n, 4) if n else None}


def measure_leg(m15, h1, h4) -> dict:
    funnel = b81.funnel_fn(m15, h1, h4)
    ts = lh.live_time_stop_bars(m15)
    grid, census = {}, {}
    for name, value in ARMS:
        kw = dict(lh.LADDER, time_stop_bars=ts)
        if name != INCUMBENT:
            kw["partial_share_fn"] = _share_fn(value)
        res = backtest_ohlc(m15, funnel, min_rr=lh.MIN_RR, spread=lh.SPREAD,
                            min_grade=lh.LIVE_MIN_GRADE, **kw)
        grid[name] = lh.r_stats(res, time_stop_bars=ts)
        census[name] = _path_census(res)
    return {"_bars": len(m15), "_first": int(m15[0]["time"]),
            "_last": int(m15[-1]["time"]), "_time_stop_bars": ts,
            "share_grid": grid, "path_census": census}


def _delta(led, arm, metric="exp_R", nd=3):
    out = {}
    for leg in LEGS:
        a = led[leg]["share_grid"][arm][metric]
        b = led[leg]["share_grid"][INCUMBENT][metric]
        out[leg] = (round(a - b, nd) if a is not None and b is not None else None)
    return out


def verdict(led) -> dict:
    v = {}
    for name, _ in ARMS:
        if name == INCUMBENT:
            continue
        d_exp = _delta(led, name, "exp_R")
        d_net = _delta(led, name, "net_R", 1)
        d_dd = _delta(led, name, "maxDD_R", 1)
        fresh = [d_exp[w] for w in FRESH if d_exp[w] is not None]
        sel = [d_exp[w] for w in SELECTION if d_exp[w] is not None]
        v[name] = {
            "delta_exp_R": d_exp, "delta_net_R": d_net, "delta_maxDD_R": d_dd,
            "fresh_windows_won": sum(1 for x in fresh if x > 0),
            "fresh_windows_lost": sum(1 for x in fresh if x < 0),
            "selection_windows_won": sum(1 for x in sel if x > 0),
            "selection_windows_lost": sum(1 for x in sel if x < 0),
            "replicated_on_fresh": (len(fresh) == len(FRESH)
                                    and all(x > 0 for x in fresh)),
            "one_sided_ge_3_all6": (sum(1 for x in d_exp.values() if x and x > 0) >= 3
                                    or sum(1 for x in d_exp.values() if x and x < 0) >= 3),
            "max_abs_delta_exp_R": max((abs(x) for x in d_exp.values() if x is not None),
                                       default=None),
        }
    return v


def main() -> int:
    led = {"_note": "b121: does b119's flat_0.30 candidate REPLICATE on two "
                    "windows it was never ranked on (W5,W6)? Same bars-per-leg "
                    "rule, same harness, arms differ in ONE parameter "
                    "(partial_share_fn); live grade gate/min_rr/trail/floor "
                    "imported or derived (b118). cached+W1..W4 must reproduce "
                    "b119's ledger — that is the integrity pin.",
           "_incumbent_ladder": {"tp1_position": lh.LADDER["tp1_position"],
                                 "trail_after_partial": lh.LADDER["trail_after_partial"],
                                 "trail_floor": lh.LADDER["trail_floor"],
                                 "share_fn": "engines.trade_management._partial_close_fraction"},
           "_live_min_grade": lh.LIVE_MIN_GRADE,
           "_selection_legs": list(SELECTION), "_fresh_legs": list(FRESH)}
    fresh_meta = fw.load()
    led["_fresh_windows"] = {n: fresh_meta[f"_{n}_meta"] for n in FRESH}

    for leg in LEGS:
        print(f"##### {leg} #####", flush=True)
        m15, h1, h4 = _rows_for(leg)
        led[leg] = measure_leg(m15, h1, h4)

    led["_verdict"] = verdict(led)

    print(f"{'leg':8s}" + "".join(f"{n[:16]:>18s}" for n in ARM_NAMES))
    for leg in LEGS:
        print(f"{leg:8s}" + "".join(
            f"{led[leg]['share_grid'][n]['exp_R']!s:>18s}" for n in ARM_NAMES))
    print("=== net_R ===")
    for leg in LEGS:
        print(f"{leg:8s}" + "".join(
            f"{led[leg]['share_grid'][n]['net_R']!s:>18s}" for n in ARM_NAMES))
    print("=== runner-path share (partial-close calls / trades) ===")
    for leg in LEGS:
        print(f"{leg:8s}" + "".join(
            f"{led[leg]['path_census'][n]['runner_path_share']!s:>18s}"
            for n in ARM_NAMES))
    print("=== verdict ===")
    for name, v in led["_verdict"].items():
        print(f"{name:36s} fresh {v['fresh_windows_won']}W/{v['fresh_windows_lost']}L "
              f"selection {v['selection_windows_won']}W/{v['selection_windows_lost']}L "
              f"replicated_on_fresh={v['replicated_on_fresh']} "
              f"max|d|={v['max_abs_delta_exp_R']}")
        print(f"{'':36s} d_exp_R={v['delta_exp_R']}")

    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
