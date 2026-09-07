#!/usr/bin/env python3
"""b118 — RE-BASELINE THE LAB BAR ONTO THE TRAIL LIVE ACTUALLY RUNS, AND
DECOMPOSE EVERY DRIFT THAT SEPARATES THE QUOTED MERIT BAR FROM THE HONEST ONE.

WHY THIS EXISTS (decision opened by b117, 2026-09-07)
=====================================================
`engines/lab_harness.LADDER.trail_after_partial` was a RESTATED LITERAL (0.50)
while live HEAD's runner lane trails at 0.30 x risk with a $3.00 absolute floor
(`_trail_params`). b117 measured that the trail grid is FLAT, so the drift was
harmless to the RANKINGS — but it is the b82 class: a harness that re-declares
its own exit constants instead of deriving them from live drifts silently, and
the next retune will move the bar without anyone deciding to.

b118 takes option (a): the harness now DERIVES the multiplier and the floor from
`_trail_params` by probe (the b117 method — no restated literal), so a live
retune moves the lab bar automatically, exactly like b80 did for the grade gate
and b71 did for the time exit.

THE SECOND, BIGGER FINDING: THE QUOTED BAR WAS STALE BY TWO DRIFTS, NOT ONE
===========================================================================
`data/backtest/b108_rescore_corrected.json` — the ledger this repo quotes as the
merit bar (cached 0.285 / W1 0.202 / W2 0.206 / W3 0.227 / W4 0.222) — DOES NOT
REPRODUCE on today's engine. Re-running the identical call (same bars, same
harness, same LADDER at 0.50, no floor) prints cached 0.270 / 107 trades, not
0.285 / 110. The gap is b109: that round shipped `LADDER_FIELDS` into the
backtest trade dict and measured the A-grade runner leg at d_exp_R -0.015
cached, then declared the old numbers "STAND" because the delta was noise-level.
Noise-level is not the same as already-counted: the headline was never
re-quoted, so every document since 2026-09-06 carries a pre-b109 number.

So this script measures the funnel per leg under FOUR conventions and attributes
the whole gap between the quoted bar and the live-parity bar:

  quoted_0_285   — reproduce b108's stored row (LADDER_FIELDS stripped from the
                   signal = the pre-b109 trade dict)
  lab_bar_0_50   — today's engine, the OLD literal bar (0.50, no floor)
  live_trail     — today's engine, live's multiplier (0.30), no floor
  live_parity    — that PLUS live's $ floor  == the NEW harness default

Read-only research: nothing here is imported by the live trading path, no gate
is touched, and the live grade gate + min_rr + trail geometry are IMPORTED from
the live modules (by the harness), never restated.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                    # noqa: E402
from engines.trade_management import LADDER_FIELDS       # noqa: E402
from scripts import b81_lane_rescore as b81              # noqa: E402
from scripts import b68l_windows as wl                   # noqa: E402

OUT = "data/backtest/b118_merit_bar_rebaseline.json"
LEGS = b81.LEGS
WINDOWS = b81.WINDOWS
OLD_BAR_LEDGER = "data/backtest/b108_rescore_corrected.json"

# The pre-b118 literal, kept HERE as a measurement arm only (never in the
# harness): it is what every stored funnel number in this repo was scored with.
LEGACY_TRAIL = 0.50


def _strip_ladder_fields(funnel):
    """The pre-b109 trade dict: the same signals WITHOUT the live ladder keys.

    b109 made `engines/backtest.py` copy LADDER_FIELDS out of the signal into
    the trade dict the share function reads. Before that the dict carried none
    of them, `rr_remaining` defaulted to 0.0, the weak branch tripped on every
    call and the ladder degenerated to a constant 1.0. Stripping the keys is
    therefore the exact way to reproduce a pre-b109 number on today's engine.
    """
    drop = set(LADDER_FIELDS)

    def fn(row):
        s = funnel(row)
        if not s:
            return None
        return {k: v for k, v in s.items() if k not in drop}
    return fn


def _row(m15, funnel, **over) -> dict:
    kw = dict(lh.LADDER)
    kw.update(over)
    kw["time_stop_bars"] = lh.live_time_stop_bars(m15)
    return lh.r_stats(lh.backtest_ohlc(m15, funnel, min_rr=lh.MIN_RR,
                                       spread=lh.SPREAD,
                                       min_grade=lh.LIVE_MIN_GRADE, **kw),
                      time_stop_bars=kw["time_stop_bars"])


def measure_leg(m15, h1, h4) -> dict:
    funnel = b81.funnel_fn(m15, h1, h4)
    mult = lh.LIVE_TRAIL_MULT
    floor = lh.LIVE_TRAIL_FLOOR
    return {
        "_bars": len(m15), "_first": int(m15[0]["time"]),
        "_last": int(m15[-1]["time"]),
        "quoted_pre_b109": _row(m15, _strip_ladder_fields(funnel),
                                trail_after_partial=LEGACY_TRAIL,
                                trail_floor=0.0),
        "lab_bar_0_50": _row(m15, funnel, trail_after_partial=LEGACY_TRAIL,
                             trail_floor=0.0),
        "live_trail_no_floor": _row(m15, funnel, trail_after_partial=mult,
                                    trail_floor=0.0),
        "live_parity": _row(m15, funnel),          # the NEW harness defaults
    }


def attribution(led: dict) -> dict:
    """Each step of the drift, per leg — pure arithmetic on the ledger's rows.

    b127: lifted verbatim out of main() so a test can EXECUTE it against the
    shipped JSON and require exact reproduction. Before this, the only copy of
    this arithmetic lived in a main() that no test could call without re-running
    the 7-minute funnel replay (and overwriting the frozen ledger).
    """
    attr = {}
    for leg in LEGS:
        L = led[leg]
        attr[leg] = {
            "d_b109_ladder_fields": round(L["lab_bar_0_50"]["exp_R"]
                                          - L["quoted_pre_b109"]["exp_R"], 3),
            "d_trail_0_50_to_live": round(L["live_trail_no_floor"]["exp_R"]
                                          - L["lab_bar_0_50"]["exp_R"], 3),
            "d_trail_floor": round(L["live_parity"]["exp_R"]
                                   - L["live_trail_no_floor"]["exp_R"], 3),
            "d_total_vs_stored": round(L["live_parity"]["exp_R"]
                                       - led["_stored_b108_bar"][leg], 3),
            "trades_quoted": L["quoted_pre_b109"]["trades"],
            "trades_live_parity": L["live_parity"]["trades"],
        }
    return attr


def main() -> int:
    wins = wl.load_windows()
    c = json.load(open("data/backtest/ab_aggressive_data.json"))
    old = json.load(open(OLD_BAR_LEDGER))

    led = {"_note": "b118: the lab bar re-baselined onto live's runner trail "
                    "(multiplier AND $ floor derived from _trail_params by the "
                    "harness, not restated), with the full decomposition of the "
                    "gap between the quoted merit bar and the live-parity one.",
           "_legacy_literal_trail": LEGACY_TRAIL,
           "_live_trail_mult_derived": lh.LIVE_TRAIL_MULT,
           "_live_trail_floor_derived": lh.LIVE_TRAIL_FLOOR,
           "_harness_ladder_trail": lh.LADDER["trail_after_partial"],
           "_harness_ladder_floor": lh.LADDER.get("trail_floor", 0.0),
           "_live_min_grade": lh.LIVE_MIN_GRADE,
           "_live_min_rr": lh.LIVE_MIN_RR}

    print("##### cached #####", flush=True)
    led["cached"] = measure_leg(c["M15"], c["H1"], c["H4"])
    for w in WINDOWS:
        print(f"##### {w} #####", flush=True)
        led[w] = measure_leg(wins[w]["M15"], wins[w]["H1"], wins[w]["H4"])

    # The stored bar this repo quotes, read from b108's own ledger.
    led["_stored_b108_bar"] = {leg: old[leg]["funnel_graded"]["exp_R"]
                               for leg in LEGS}
    led["_stored_b108_trades"] = {leg: old[leg]["funnel_graded"]["trades"]
                                  for leg in LEGS}

    # Attribution: each step of the drift, per leg. b127: the arithmetic lives
    # in attribution() so the reproduction test executes THE SAME code that
    # ships in the ledger, not a copy of it.
    led["_attribution"] = attribution(led)

    print(f"{'leg':8s} {'stored':>8s} {'quoted':>8s} {'lab050':>8s} "
          f"{'livetr':>8s} {'parity':>8s}   attribution")
    for leg in LEGS:
        L, a = led[leg], attr[leg]
        print(f"{leg:8s} {led['_stored_b108_bar'][leg]:>8.3f} "
              f"{L['quoted_pre_b109']['exp_R']:>8.3f} "
              f"{L['lab_bar_0_50']['exp_R']:>8.3f} "
              f"{L['live_trail_no_floor']['exp_R']:>8.3f} "
              f"{L['live_parity']['exp_R']:>8.3f}   "
              f"b109={a['d_b109_ladder_fields']:+.3f} "
              f"trail={a['d_trail_0_50_to_live']:+.3f} "
              f"floor={a['d_trail_floor']:+.3f} "
              f"total={a['d_total_vs_stored']:+.3f}")
    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
