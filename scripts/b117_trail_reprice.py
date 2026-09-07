#!/usr/bin/env python3
"""b117 — RE-PRICE THE b65 TRAIL DECISION UNDER THE CORRECTED ENGINE.

WHY THIS EXISTS (found by b114's drift audit + b110's procedure)
================================================================
Three different runner-trail values are in play and nobody had priced the
difference:

  * live HEAD        0.30  — engines/trade_management._trail_params, changed by
                     b65 (2026-09-03) from 0.45 on the evidence of a sweep.
  * live RUNNING     0.45  — b114 measured that position_daemon booted 17
                     SECONDS before 31c64f7 (the b65 commit), so production has
                     managed every position with the OLD 0.45 (todo b115).
  * the LAB BAR      0.50  — engines/lab_harness.LADDER.trail_after_partial,
                     which is what EVERY funnel number in this repo was
                     measured with (b80/b81/b108's merit bar, b109's deltas).

So the number the whole merit bar rests on (0.285 cached / 0.20-0.23R on the
independent windows) is scored under a trail that neither live-HEAD nor
live-RUNNING uses. That is the b82 parity-drift class on the exit axis.

BUT THE REAL FINDING IS WHY THE DRIFT BARELY MATTERS, and it is a b105
consequence. b65's sweep ran on the PRE-b105 engine, where
`_partial_close_fraction` returned a CONSTANT 1.0 (b108's side finding) and
`engines/backtest.py` kept a PHANTOM full-size runner alive after every TP1
fill. Under that engine the trail applied to EVERY trade, which is exactly why
b65 measured +10.6R (M5) / +22.1R (M15) for 0.45 -> 0.30. Post-b105 a
share>=1.0 TP1 close closes the TICKET (`tp1_full`) — so the only population a
trail can touch is the strong-runner lane, which b109 proved collapses to
`setup_grade == 'A'`. The trail decision was priced on a population that no
longer exists.

b110's rule says a fix must be priced by its NEUTRALITY across arms, not just
its level, and that a one-sided shift across >=3 independent windows proves the
old rankings were contaminated. This script does exactly that for the exit
family: same bars, same engine, same harness, same live grade gate — the ONLY
difference between arms is `trail_after_partial`.

MEASURED PER LEG (cached + W1..W4, the b76/b81 window set):
  arms 0.0 (no trail) / 0.30 (live HEAD) / 0.45 (live RUNNING) / 0.50 (lab bar)
  / 0.60 / 0.80, plus the A-grade slice and the runner-population census, plus
  the SECOND parity gap this read-through found (below).

SECOND FINDING — THE $3.0 TRAIL FLOOR IS NOT MODELLED IN THE LAB AT ALL
=======================================================================
Live `_trail_params` returns `max(risk_distance * mult, 3.0)` (and 4.0 for the
strong-runner lane): a $3.00 ABSOLUTE FLOOR on the trail distance. The backtest
computes `cand = high - trail_after_partial * risk` with NO floor. On a leg
whose median risk is $15 the floor never binds and the gap is invisible; on
W4 (median risk $8.80) it binds on the MAJORITY of trades, where live trails
WIDER than the lab does. `floor_bind_census()` measures how many trades per leg
sit under the floor, so the size of the gap is a number, not an argument.
Nothing is wired here — this is measurement, and the floor is a live RISK
behaviour that must not be weakened (modelling it in the lab would only make
the lab MORE conservative-looking, never less).

Read-only research: nothing here is imported by the live trading path, no gate
is touched, and the live grade gate + min_rr are IMPORTED by the harness, never
restated.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                    # noqa: E402
from engines.trade_management import _trail_params        # noqa: E402
from scripts import b81_lane_rescore as b81               # noqa: E402
from scripts import b68l_windows as wl                    # noqa: E402

OUT = "data/backtest/b117_trail_reprice.json"
LEGS = b81.LEGS
WINDOWS = b81.WINDOWS

# The three values actually in play (live HEAD, live RUNNING per b114, lab bar)
# plus the no-trail control and two looser arms so the response curve is not
# read off a single step.
ARMS = (("no_trail_0.00", 0.0),
        ("live_head_0.30", 0.30),
        ("live_running_0.45", 0.45),
        ("lab_bar_0.50", 0.50),
        ("loose_0.60", 0.60),
        ("loose_0.80", 0.80))

# The absolute floor live puts under the trail distance, read OUT OF the live
# function rather than restated (b109's lesson: a restated constant drifts).
# _trail_params({'entry_price':0,'sl':0,...}) with risk=0 returns max(0, floor)
# = the floor itself, so this is a probe, not a copy.
def trail_floor(mult: float = 0.30) -> float:
    t = {"side": "BUY", "entry_price": 0.0, "sl": 0.0,
         "volatility_state": "normal", "momentum_strength": 0.5}
    return float(_trail_params(t)[0])


def runner_census(m15, h1, h4) -> dict:
    """How many funnel signals even SURVIVE to a state where a trail can act?

    Post-b105 the trail only exists for a trade whose TP1 partial left a
    runner, i.e. share < 1.0, which b109 proved == grade A. Count it directly
    through the real live function instead of asserting it.
    """
    from engines.trade_management import _partial_close_fraction
    funnel = b81.funnel_fn(m15, h1, h4)
    total = 0
    runner = 0
    for row in m15:
        s = funnel(row)
        if not s:
            continue
        if str(s.get("grade", "")) > lh.LIVE_MIN_GRADE:
            continue                      # the live gate rejects it: never traded
        total += 1
        share, _reason = _partial_close_fraction(s)
        if share < 1.0:
            runner += 1
    return {"gate_passed_signals": total, "signals_with_runner_leg": runner,
            "runner_share": round(runner / total, 4) if total else None}


def floor_bind_census(m15, h1, h4, mult: float = 0.30) -> dict:
    """How many ACTUAL trades have risk small enough that live's $ floor, not
    the multiplier, sets the trail distance? The lab models only the
    multiplier, so every one of these trades is scored on trail geometry live
    does not use."""
    funnel = b81.funnel_fn(m15, h1, h4)
    ts = lh.live_time_stop_bars(m15)
    kw = dict(lh.LADDER)
    kw["trail_floor"] = 0.0            # b118: this census measures the UNFLOORED
                                       # grid's risk distribution (see the note in
                                       # measure_leg); the floor is what is being
                                       # counted, so it must not be in the geometry.
    kw["trail_after_partial"] = mult
    kw["time_stop_bars"] = ts
    from engines.backtest import backtest_ohlc
    res = backtest_ohlc(m15, funnel, min_rr=lh.MIN_RR, spread=lh.SPREAD,
                        min_grade=lh.LIVE_MIN_GRADE, **kw)
    floor = trail_floor(mult)
    risks = [abs(t["entry"] - t["orig_sl"]) for t in res["trade_log"]]
    binds = [r for r in risks if r * mult < floor]
    return {"floor_usd": floor, "trades": len(risks),
            "floor_binds": len(binds),
            "floor_bind_share": round(len(binds) / len(risks), 4) if risks else None,
            "median_risk_usd": round(sorted(risks)[len(risks) // 2], 2) if risks else None}


def _a_slice(m15, funnel, kw) -> dict:
    """The A-grade trades only — the population a trail can reach post-b105."""
    from engines.backtest import backtest_ohlc
    res = backtest_ohlc(m15, funnel, min_rr=lh.MIN_RR, spread=lh.SPREAD,
                        min_grade=lh.LIVE_MIN_GRADE, **kw)
    rs = [float(t["pnl"]) / (abs(float(t["entry"]) - float(t["orig_sl"])) or 1)
          for t in res["trade_log"] if t.get("grade") == "A"]
    return {"n": len(rs),
            "exp_R": round(sum(rs) / len(rs), 3) if rs else None,
            "net_R": round(sum(rs), 1) if rs else None}


def measure_leg(m15, h1, h4) -> dict:
    """All trail arms on IDENTICAL bars through the ONE harness.

    `extra_modes` is the harness's own extension point, so plain/ladder/
    ladder_ts still come out of run_arm() — no hand-copied funnel, no
    hand-copied ladder (hard rule).

    TWO grids: `arms` is the historical lab shape (multiplier only, floor off —
    what b65/b80/b81/b108 all measured), `floor_arms` adds live's absolute $
    floor so the ledger carries the number for the geometry live ACTUALLY runs.
    """
    from engines.backtest import backtest_ohlc
    funnel = b81.funnel_fn(m15, h1, h4)
    # b118 PARITY NOTE (edit, not a change to the frozen ledger): the harness
    # LADDER used to carry NO `trail_floor`, so `arms` below was by construction
    # the floor-OFF grid ("the historical lab shape", see measure_leg's
    # docstring). b118 aligned the harness onto live's derived trail INCLUDING
    # the $3.00 floor, so the unfloored grid must now say so explicitly —
    # otherwise re-running this probe would print floored numbers into the
    # `arms` column and contradict the ledger that is this item's evidence.
    BASE = dict(lh.LADDER, trail_floor=0.0)
    extras = tuple((name, dict(BASE, trail_after_partial=mult))
                   for name, mult in ARMS)
    out = lh.run_arm(m15, funnel, extra_modes=extras)
    rows = {name: out[name] for name, _mult in ARMS}
    ts = out["_time_stop_bars"]
    a_only = {}
    floor_rows = {}
    floor_a = {}
    floor = trail_floor()
    for name, mult in ARMS:
        kw = dict(BASE)
        kw["trail_after_partial"] = mult
        kw["time_stop_bars"] = ts
        a_only[name] = _a_slice(m15, funnel, kw)
        kwf = dict(kw)
        kwf["trail_floor"] = floor
        floor_rows[name] = lh.r_stats(backtest_ohlc(m15, funnel, min_rr=lh.MIN_RR,
                                                    spread=lh.SPREAD,
                                                    min_grade=lh.LIVE_MIN_GRADE,
                                                    **kwf), time_stop_bars=ts)
        floor_a[name] = _a_slice(m15, funnel, kwf)
    return {"_bars": len(m15), "_first": int(m15[0]["time"]),
            "_last": int(m15[-1]["time"]),
            "_time_stop_bars": ts,
            "arms": rows, "a_grade_arms": a_only,
            "floor_arms": floor_rows, "floor_a_grade_arms": floor_a,
            "runner_census": runner_census(m15, h1, h4),
            "floor_bind_census": floor_bind_census(m15, h1, h4)}


def main() -> int:
    wins = wl.load_windows()
    c = json.load(open("data/backtest/ab_aggressive_data.json"))
    led = {"_note": "b117: the b65 runner-trail decision re-priced under the "
                    "b105-corrected engine, per b110's neutrality rule. Arms "
                    "differ ONLY in trail_after_partial (same bars, same "
                    "engine, same harness, same live grade gate).",
           "_live_head_trail": 0.30,
           "_live_running_trail_b114": 0.45,
           "_lab_harness_trail": lh.LADDER["trail_after_partial"],
           "_trail_floor_usd": trail_floor(),
           "_arms": {n: m for n, m in ARMS},
           "_live_min_grade": b81.MIN_SETUP_GRADE}
    print("##### cached #####", flush=True)
    led["cached"] = measure_leg(c["M15"], c["H1"], c["H4"])
    for w in WINDOWS:
        print(f"##### {w} #####", flush=True)
        led[w] = measure_leg(wins[w]["M15"], wins[w]["H1"], wins[w]["H4"])

    # b110's neutrality test: the trail-vs-bar margin per arm, per leg.
    # One-sided across >=3 independent windows = the old ranking was contaminated.
    summary = {}
    for leg in LEGS:
        arms = led[leg]["arms"]
        base = arms["lab_bar_0.50"]["exp_R"]
        summary[leg] = {name: {"exp_R": row["exp_R"],
                               "net_R": row["net_R"],
                               "d_vs_lab_bar": (round(row["exp_R"] - base, 3)
                                                if row["exp_R"] is not None
                                                and base is not None else None)}
                        for name, row in arms.items()}
    led["_summary"] = summary
    led["_a_grade_summary"] = {leg: led[leg]["a_grade_arms"] for leg in LEGS}
    led["_floor_summary"] = {leg: {name: {"exp_R": row["exp_R"],
                                          "net_R": row["net_R"]}
                                   for name, row in led[leg]["floor_arms"].items()}
                             for leg in LEGS}
    led["_runner_census"] = {leg: led[leg]["runner_census"] for leg in LEGS}
    led["_floor_bind_census"] = {leg: led[leg]["floor_bind_census"] for leg in LEGS}

    print("=== exp_R by arm (ladder_ts) ===")
    hdr = f"{'leg':8s}" + "".join(f"{n[:14]:>15s}" for n, _ in ARMS)
    print(hdr)
    for leg in LEGS:
        print(f"{leg:8s}" + "".join(
            f"{led[leg]['arms'][n]['exp_R']!s:>15s}" for n, _ in ARMS))
    print("=== net_R by arm ===")
    print(hdr)
    for leg in LEGS:
        print(f"{leg:8s}" + "".join(
            f"{led[leg]['arms'][n]['net_R']!s:>15s}" for n, _ in ARMS))
    print("=== exp_R by arm WITH live's $ floor modelled ===")
    print(hdr)
    for leg in LEGS:
        print(f"{leg:8s}" + "".join(
            f"{led[leg]['floor_arms'][n]['exp_R']!s:>15s}" for n, _ in ARMS))
    print("=== net_R by arm WITH live's $ floor modelled ===")
    print(hdr)
    for leg in LEGS:
        print(f"{leg:8s}" + "".join(
            f"{led[leg]['floor_arms'][n]['net_R']!s:>15s}" for n, _ in ARMS))
    print("=== runner population (signals that even reach a trail) ===")
    for leg in LEGS:
        rc = led[leg]["runner_census"]
        print(f"{leg:8s} gate-passed={rc['gate_passed_signals']:5d} "
              f"with-runner={rc['signals_with_runner_leg']:4d} "
              f"({rc['runner_share']})")
    print("=== $-floor bind census (live trails wider than the lab here) ===")
    for leg in LEGS:
        fc = led[leg]["floor_bind_census"]
        print(f"{leg:8s} floor=${fc['floor_usd']:.2f} trades={fc['trades']:4d} "
              f"binds={fc['floor_binds']:4d} ({fc['floor_bind_share']}) "
              f"median_risk=${fc['median_risk_usd']}")
    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
