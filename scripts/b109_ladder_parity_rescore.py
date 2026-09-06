#!/usr/bin/env python3
"""b109 — RE-MEASURE THE FUNNEL NOW THAT THE LADDER SEES LIVE SEMANTICS.

The defect (filed by b108, pinned by tests/test_b109_share_fn_contract.py):
`engines/lab_harness.LADDER` passes the REAL live function
`_partial_close_fraction(trade)` to the backtest, and `engines/backtest.py`'s
b55 comment claimed it passed the whole trade dict "so it can read grade AND
momentum/rr/structure from it". It could not: the backtest dict supplied
`grade`/`style`/`entry`/`sl`/`tp` and NONE of the four fields the live function
reads, so `rr_remaining` defaulted to 0.0, the `rr_remaining <= 1.2` weak
branch tripped unconditionally, and the "live-parity ladder" returned the
constant (1.0, 'weak_full_exit_at_tp1') on 935/935 calls on the cached funnel —
the 84 A-grade signals included.

WHAT SHIPPED (this item, plan step 1): `strategy_signal` now emits the live
ladder fields through `engines.trade_management.ladder_fields()` — the SAME
helper both live producers (hermes_runtime.cycle, position_daemon.build_trade)
now call — and `backtest_ohlc` carries them into the trade dict. The parity is
by construction again instead of by luck.

THE MEASUREMENT (plan step 2): b109's own warning was that passing the fields
through without re-measuring would hand the A-grade book "a 0.3 runner leg the
funnel has never been scored with". So this script A/Bs the two shapes on
IDENTICAL bars — same dataset, same engine, same harness ladder, same live
grade gate — and the ONLY difference is whether the signal carries the live
ladder fields:

  pre_b109   fields stripped -> the constant (1.0) ladder, i.e. every number
             the backlog has ever quoted (b80/b81/b108)
  post_b109  fields present  -> the real live lane split

and it reports the lane distribution and the A-grade slice separately, because
the A book is the only population the change can touch (see the collapse
finding below).

THE COLLAPSE FINDING (plan step 3's input): the four-way AND in
`_partial_close_fraction` is not a four-factor judgement. Both live producers
derive all four inputs from TWO plan fields (alignment, trend_strength) and
hardcode rr_remaining = 2.0, so

    grade>=3 AND momentum>=0.8 AND rr>=2.0 AND structure=='healthy'
    ==  setup_grade == 'A'

exactly. Measured over data/xau_plan/plan_history (1540 plans,
scripts/b109_probe_lane_reachability.py): the equivalence holds for every
distinct (alignment, trend, regime) triple, and 65 plans (4.2%) satisfy it. So
the runner lane is reachable live — it simply has not been reached yet, because
no A-grade position has hit TP1 since b55 shipped. The lane is therefore NOT
the "thesis the parity backtest cannot model" that b55's comment called it: it
is one threshold, and this script is what it costs.

Read-only research: nothing here is imported by the live trading path, and no
gate is touched — the live grade gate and min_rr are imported from
engines.auto_executor by the harness, never restated.
"""
from __future__ import annotations

import collections
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                      # noqa: E402
from engines.trade_management import LADDER_FIELDS          # noqa: E402
from scripts import b81_lane_rescore as b81                 # noqa: E402
from scripts import b68l_windows as wl                      # noqa: E402

OUT = "data/backtest/b109_ladder_parity_rescore.json"
LEGS = b81.LEGS
WINDOWS = b81.WINDOWS


def _row(res: dict) -> dict:
    r = res["ladder_ts"]
    return {"trades": r["trades"], "exp_R": r["exp_R"], "net_R": r["net_R"],
            "WR%": r["WR%"], "maxDD_R": r["maxDD_R"],
            "mean_hold_bars": r["mean_hold_bars"]}


def lane_census(m15, h1, h4) -> dict:
    """Which lane does the live function pick for each funnel signal?

    Direct call on the emitted signal — the same dict shape the engine hands
    `partial_share_fn` — so this is the lane split the measurement above is
    built from, not a restatement of it.
    """
    from engines.trade_management import _partial_close_fraction
    funnel = b81.funnel_fn(m15, h1, h4)
    counts = collections.Counter()
    grades = collections.Counter()
    for row in m15:
        s = funnel(row)
        if not s:
            continue
        share, reason = _partial_close_fraction(s)
        counts[(s.get("grade"), share, reason)] += 1
        grades[s.get("grade")] += 1
    return {"signals_by_grade": dict(grades),
            "lane_split": {f"{g}|{share}|{r}": n
                           for (g, share, r), n in sorted(counts.items(),
                                                          key=lambda x: str(x[0]))}}


def measure_leg(name: str, m15, h1, h4) -> dict:
    """Both ladder shapes on the SAME bars — the only difference is whether
    the signal carries the live ladder fields."""
    funnel = b81.funnel_fn(m15, h1, h4)

    def pre_b109(row):
        s = funnel(row)
        if s:
            s = {k: v for k, v in s.items() if k not in LADDER_FIELDS}
        return s

    out = {"_bars": len(m15), "_first": int(m15[0]["time"]),
           "_last": int(m15[-1]["time"])}
    out["pre_b109_constant_ladder"] = _row(lh.run_arm(m15, pre_b109))
    out["post_b109_live_ladder"] = _row(lh.run_arm(m15, funnel))
    a, b = out["pre_b109_constant_ladder"], out["post_b109_live_ladder"]
    out["delta"] = {
        "d_exp_R": (round(b["exp_R"] - a["exp_R"], 3)
                    if a["exp_R"] is not None and b["exp_R"] is not None
                    else None),
        "d_net_R": round(b["net_R"] - a["net_R"], 1),
        "d_trades": b["trades"] - a["trades"],
        "d_dd_R": round(b["maxDD_R"] - a["maxDD_R"], 1),
    }
    out["lane_census"] = lane_census(m15, h1, h4)
    return out


def main() -> int:
    wins = wl.load_windows()
    c = json.load(open("data/backtest/ab_aggressive_data.json"))
    led = {"_note": "b109: the funnel re-measured with the live ladder fields "
                    "actually reaching _partial_close_fraction. pre/post legs "
                    "differ ONLY in that (same bars, same engine, same "
                    "harness ladder, same live grade gate).",
           "_live_min_grade": b81.MIN_SETUP_GRADE,
           "_b108_reference": "data/backtest/b108_rescore_corrected.json"}
    print("##### cached (in-sample, informational) #####", flush=True)
    led["cached"] = measure_leg("cached", c["M15"], c["H1"], c["H4"])
    for w in WINDOWS:
        print(f"##### {w} #####", flush=True)
        led[w] = measure_leg(w, wins[w]["M15"], wins[w]["H1"], wins[w]["H4"])

    # The decision-relevant summary: does the honest lane split move the
    # headline on the INDEPENDENT windows, and in which direction?
    summary = {}
    for leg in LEGS:
        summary[leg] = {"pre": led[leg]["pre_b109_constant_ladder"]["exp_R"],
                        "post": led[leg]["post_b109_live_ladder"]["exp_R"],
                        "delta": led[leg]["delta"]["d_exp_R"],
                        "a_signals": led[leg]["lane_census"]
                        ["signals_by_grade"].get("A", 0)}
    led["_summary"] = summary
    print("=== SUMMARY (exp_R pre -> post) ===")
    print(json.dumps(summary, indent=1))
    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
