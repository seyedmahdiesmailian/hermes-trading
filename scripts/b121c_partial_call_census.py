#!/usr/bin/env python3
"""b121c — THE COST SIDE, MEASURED HONESTLY: HOW MANY PARTIAL CLOSES WOULD LIVE
actually send if the runner share stopped being grade-gated?

WHY (b121's own precondition 2, and a b122 catch inside this round)
===================================================================
b121 asked for the operational price of the candidate: "a 0.7 runner on every
trade means 70% of every position rides past TP1, so the live partial-close
path runs 5x more often (bridge calls, MT5 10026 rejection handling, the
`_tp1_exit_closes_all` branch)". Step 1 tried to answer that with an
`exit_reason` census and got a VOID column: flat_0.1 through flat_0.9 all
reported the same share, and share=0.0 — the arm that never takes a partial at
all — reported the LARGEST. The reason is structural: which exit a runner
REACHES (tp / sl_part / sl) is a function of the price path, not of the share,
so exit_reason cannot see the one parameter the grid varies. Pinned void by
tests/test_b121_flat_share_replication.py::TestB121CensusIsBlind.

engines/backtest.py's trade_log now carries `partial_taken` — the share the TP1
partial ACTUALLY took, read off the trade dict (additive; every pre-b121 row
and every stored number is unchanged). That is the only field that can answer
the question, and this script answers it for the pair that matters: the live
incumbent vs the replicated candidate, on the cached set and the two FRESH
windows (W5/W6) the candidate was never ranked on.

WHAT IS COUNTED (a PROXY, labelled as one)
==========================================
  partial_close_calls   = trades whose TP1 partial actually fired (share > 0)
                          -> live: ONE bridge call each (the partial), and for
                             share < 1.0 a LATER close of the remainder
  runner_closes         = trades that took a partial AND survived TP1
                          (share < 1.0) -> they need the trail modifies and a
                          final close, i.e. the multi-call path
  one_call_closes       = trades closed at TP1 with share >= 1.0 (tp1_full)
                          -> the single-call path live uses today
The lab cannot see MT5 rejections, retries, or the watchdog's 5s loop; it can
count how often each path is taken. That is the honest scope of this number.

Read-only research; nothing is wired and no gate is touched.
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
from engines.trade_management import _partial_close_fraction  # noqa: E402
from scripts import b81_lane_rescore as b81                # noqa: E402
from scripts.b121_flat_share_replication import (           # noqa: E402
    FRESH, SELECTION, INCUMBENT, _rows_for)

OUT = "data/backtest/b121c_partial_call_census.json"
LEGS = ("cached",) + FRESH          # the decision-relevant legs, not all 7
ARMS = (INCUMBENT, "flat_0.30")


def census(res: dict) -> dict:
    log = res.get("trade_log", [])
    n = len(log)
    partial = [t for t in log if float(t.get("partial_taken") or 0.0) > 0]
    full = [t for t in partial if float(t["partial_taken"]) >= 1.0]
    runner = [t for t in partial if float(t["partial_taken"]) < 1.0]
    return {"trades": n,
            "partial_close_calls": len(partial),
            "one_call_closes_at_tp1": len(full),
            "multi_call_runner_trades": len(runner),
            "partial_call_rate": round(len(partial) / n, 4) if n else None,
            "runner_rate": round(len(runner) / n, 4) if n else None,
            "exp_R": None, "net_R": None}


def measure(m15, h1, h4) -> dict:
    funnel = b81.funnel_fn(m15, h1, h4)
    ts = lh.live_time_stop_bars(m15)
    out = {}
    for name in ARMS:
        kw = dict(lh.LADDER, time_stop_bars=ts)
        if name != INCUMBENT:
            kw["partial_share_fn"] = lambda t: (0.30, "lab_flat_share")
        res = backtest_ohlc(m15, funnel, min_rr=lh.MIN_RR, spread=lh.SPREAD,
                            min_grade=lh.LIVE_MIN_GRADE, **kw)
        c = census(res)
        s = lh.r_stats(res, time_stop_bars=ts)
        c["exp_R"], c["net_R"] = s["exp_R"], s["net_R"]
        out[name] = c
    return out


def main() -> int:
    led = {"_note": "b121c: the operational cost side of the share candidate, "
                    "counted off trade_log.partial_taken (the field b121 added "
                    "to engines/backtest.py) because exit_reason is "
                    "structurally blind to the share (step 1's void column).",
           "_scope": "PROXY for bridge-call volume: the lab cannot see MT5 "
                     "rejections, retries, or the watchdog loop — only which "
                     "exit path each trade took.",
           "_arms": {"incumbent_live_grade_fn":
                     "engines.trade_management._partial_close_fraction",
                     "flat_0.30": "lambda: (0.30, 'lab_flat_share')"},
           "_live_min_grade": lh.LIVE_MIN_GRADE}
    for leg in LEGS:
        print(f"##### {leg} #####", flush=True)
        m15, h1, h4 = _rows_for(leg)
        led[leg] = measure(m15, h1, h4)

    led["_ratio"] = {leg: {
        "partial_calls_candidate_over_incumbent":
            round(led[leg]["flat_0.30"]["partial_close_calls"]
                  / max(led[leg][INCUMBENT]["partial_close_calls"], 1), 2),
        "multi_call_runner_trades_candidate_over_incumbent":
            round(led[leg]["flat_0.30"]["multi_call_runner_trades"]
                  / max(led[leg][INCUMBENT]["multi_call_runner_trades"], 1), 2),
    } for leg in LEGS}

    print(f"{'leg':8s}{'arm':28s}{'n':>6s}{'partials':>10s}{'1-call':>8s}"
          f"{'runners':>9s}{'part_rate':>10s}{'exp_R':>8s}")
    for leg in LEGS:
        for arm in ARMS:
            c = led[leg][arm]
            print(f"{leg:8s}{arm:28s}{c['trades']:6d}"
                  f"{c['partial_close_calls']:10d}"
                  f"{c['one_call_closes_at_tp1']:8d}"
                  f"{c['multi_call_runner_trades']:9d}"
                  f"{c['partial_call_rate']!s:>10s}{c['exp_R']!s:>8s}")
    print("=== candidate / incumbent call ratios ===")
    for leg in LEGS:
        print(leg, led["_ratio"][leg])

    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
