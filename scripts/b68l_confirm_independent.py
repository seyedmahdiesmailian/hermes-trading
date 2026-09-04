#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 11 — RE-MEASURE THE DECISION SET ON TRULY
INDEPENDENT WINDOWS (the methodology round).

Every confirm in rounds 1-10 fetched "the last 6000 M15 bars" as the FRESH
set. Measured today (scripts/b68l_windows.py): the cached 3000-bar set sits
at the END of the broker's M15 history, so the last 6000 bars contain ALL
3000 cached bars — the "fresh" number was the cached regime plus 3000 extra
bars, never an out-of-sample test. The merit bar ("beat the funnel on BOTH
sets") has therefore been comparing a set against its own superset for ten
rounds. Round 9's champion (pdh x dayext, 0.924 cached / 0.891 "fresh") and
the nr7 lane (0.620 "fresh") have never been scored on data that EXCLUDES
the July-August regime they were selected on.

This round fixes the measurement, not the strategy. It re-runs the CURRENT
b70 decision set — funnel, round-4 control (pdh_w10), round-9 champion
(pdh_dayext_agree + e25 + complement), round-5 nr7 — on two windows that are
independent of the cached set AND of each other (b74's replication
requirement, satisfied in one pass):

  W1  6000 M15 bars 2026-04-14 -> 2026-07-15 (ends where cached begins)
  W2  6000 M15 bars 2026-01-12 -> 2026-04-14

Funnel is re-measured on the SAME bars as every arm (round-4 rule), the b71
harness scores plain/ladder/ladder_ts with derived time exit, and the
additive lane (funnel-first, gated pdh on free bars) ships per window so
b70's capacity question gets honest per-regime numbers instead of one
contaminated aggregate.

Verdict logic (recorded in the ledger, not hardcoded): an arm is only
"replicated" if it beats the funnel's ladder_ts exp_R on the SAME bars in
BOTH independent windows. Anything less and the cached/"fresh" win is
regime luck, exactly what b74 was written to catch.

Read-only: bridge get_rates only (via b68l_windows, cached to disk). Nothing
here is imported by the live trading path.
"""
import os
import sys
import json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from engines import lab_harness as lh              # noqa: E402  (b71 harness)
from engines.backtest_real import strategy_signal  # noqa: E402
from scripts import b68l_windows as wl             # noqa: E402  (W1/W2 builder)
from scripts import b68j_dayext_pdh_lab as j9      # noqa: E402  (round-9 module)
from scripts import b68e_pdh_lab as pl             # noqa: E402  (pdh geometry)
from scripts import b68f_nr7_lab as nl             # noqa: E402  (nr7 geometry)

OUT = os.path.join(_ROOT, "data", "backtest", "b68l_independent_confirm.json")


def measure_window(name: str, rows: dict) -> dict:
    """One window: rebind the ingredient modules, evaluate the funnel ONCE,
    run the decision-set arms through the b71 harness."""
    m15 = rows["M15"]
    h1, h4 = rows["H1"], rows["H4"]
    j9.rebind(m15)                      # round-9 module + pl/dl + LEVELS
    idx_of = j9.IDX

    # nr7 lives in its own module — repoint it at the same bars (same
    # contract as the round-7/8 rebinds, which never needed nr7).
    nl.M15 = m15
    nl.IDX = idx_of

    def wrap(fn):
        def w(row):
            i = idx_of.get(row.get("time"))
            return None if i is None else fn(i)
        return w

    f_sig = {}
    for i, row in enumerate(m15):
        bt = row.get("time", 0)
        hw = [r for r in h1 if r.get("time", 0) <= bt][-80:]
        h4w = [r for r in h4 if r.get("time", 0) <= bt][-80:]
        mw = m15[max(0, i - 120):i + 1]
        s = strategy_signal(row, hw, h4w, i, m15_window=mw)
        if s:
            f_sig[i] = s

    def funnel(row):
        return f_sig.get(idx_of.get(row.get("time"), -1))

    def make_lane(arm_fn):
        def lane_fn(row):
            return funnel(row) or arm_fn(row)
        return lane_fn

    arms = [("CURRENT_FUNNEL", funnel),
            ("pdh_w10_control", wrap(lambda i: pl.pdh_break(i, j9.STOP_ATR))),
            ("pdh_dayext_agree", wrap(lambda i: j9.combo(i, j9.EXT))),
            ("pdh_dayext_agree_e25", wrap(lambda i: j9.combo(i, j9.EXT25))),
            ("pdh_dayext_notyet", wrap(lambda i: j9.complement(i, j9.EXT))),
            ("nr7_break_w10", wrap(lambda i: nl.nr7_break(i, wide=True))),
            ("lane_funnel_then_gated",
             make_lane(wrap(lambda i: j9.combo(i, j9.EXT))))]
    out = {"_time_stop_bars": lh.live_time_stop_bars(m15),
           "_bars": len(m15),
           "_first": int(m15[0]["time"]), "_last": int(m15[-1]["time"])}
    for arm_name, fn in arms:
        out[arm_name] = lh.run_arm(m15, fn)
        lh.print_table(out, [arm_name], label=f"{arm_name} ({name}, b71)")
        print(flush=True)
    out["_honesty_complaints"] = lh.summarize(out, [a for a, _ in arms])
    print(f"=== {name} honesty ===")
    for c in out["_honesty_complaints"] or ["no complaints"]:
        print("!", c)
    return out


def verdict(led: dict) -> dict:
    """Per window: does each arm beat the funnel's ladder_ts on the SAME
    bars? Replication = beats it in BOTH windows."""
    v = {}
    for w in ("W1", "W2"):
        win = led[w]
        f = win["CURRENT_FUNNEL"]["ladder_ts"]
        v[w] = {"funnel_exp_R": f["exp_R"], "funnel_n": f["trades"]}
        for arm in ("pdh_w10_control", "pdh_dayext_agree",
                    "pdh_dayext_agree_e25", "pdh_dayext_notyet",
                    "nr7_break_w10", "lane_funnel_then_gated"):
            row = win[arm]["ladder_ts"]
            v[w][arm] = {"exp_R": row["exp_R"], "n": row["trades"],
                         "beats_funnel": (row["exp_R"] is not None
                                          and row["exp_R"] > f["exp_R"])}
    both = {}
    for arm in v["W1"]:
        if arm in ("funnel_exp_R", "funnel_n"):
            continue
        both[arm] = bool(v["W1"][arm]["beats_funnel"]) and \
            bool(v["W2"][arm]["beats_funnel"])
    v["replicated_in_both"] = both
    return v


def main():
    led = {"_note": "round 11: decision set re-measured on windows that "
                    "exclude the cached set entirely (the last-6000 'fresh' "
                    "of rounds 1-10 contained 100% of the cached bars)",
           "_last6000_overlap_with_cached": None}
    wins = wl.load_windows()
    led["_last6000_overlap_with_cached"] = wins["_last6000_overlap_with_cached"]
    led["_window_meta"] = {k: v for k, v in wins.items()
                           if k.startswith("_")}
    for name in ("W1", "W2"):
        print(f"##### {name} #####", flush=True)
        led[name] = measure_window(name, wins[name])
    led["_verdict"] = verdict(led)
    print("=== VERDICT ===")
    print(json.dumps(led["_verdict"], indent=1))
    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
