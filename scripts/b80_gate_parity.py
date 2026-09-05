#!/usr/bin/env python3
"""b80 — GATE PARITY: measure the funnel baseline with and without the live
grade gate, on cached + W1..W4, and prove the RR gate is redundant.

Why (2026-09-05): the b71 harness `run_arm()` passed only `min_rr` to
`backtest_ohlc` and never `min_grade`, while the canonical live-parity runner
`engines.backtest_real.run_backtest` defaults to `min_grade="B", min_rr=1.5`.
So every round's CURRENT_FUNNEL baseline traded 58-67% C-grade setups the live
executor rejects — the merit bar the lab has been clearing was softer (and
worse) than live. Lab arms all declare grade "B", so the fix is a no-op for
them and only moves the bar.

Read-only research: nothing here touches the live path.
"""
import os, sys, json, bisect
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.backtest_real import strategy_signal
from engines.auto_executor import MIN_RISK_REWARD, MIN_SETUP_GRADE
from engines import lab_harness as lh
from scripts import b68l_windows as wl

OUT = "data/backtest/b80_gate_parity.json"
LEGS = ("cached", "W1", "W2", "W3", "W4")


def funnel_signals(rows, h1rows, h4rows):
    h1t = [r.get("time", 0) for r in h1rows]
    h4t = [r.get("time", 0) for r in h4rows]
    sigs = {}
    for i, row in enumerate(rows):
        bt = row.get("time", 0)
        j1 = bisect.bisect_right(h1t, bt)
        j4 = bisect.bisect_right(h4t, bt)
        s = strategy_signal(row, h1rows[max(0, j1 - 80):j1],
                            h4rows[max(0, j4 - 80):j4], i,
                            m15_window=rows[max(0, i - 120):i + 1])
        if s:
            sigs[i] = s
    return sigs


def main():
    legs = {"cached": json.load(
        open("data/backtest/ab_aggressive_data.json"))["M15"]}
    wins = wl.load_windows()
    for w in ("W1", "W2", "W3", "W4"):
        legs[w] = wins[w]["M15"]

    out = {"live_gates": {"MIN_RISK_REWARD": MIN_RISK_REWARD,
                          "MIN_SETUP_GRADE": MIN_SETUP_GRADE},
           "legs": {}}
    for name in LEGS:
        rows = legs[name]
        if name == "cached":
            d = json.load(open("data/backtest/ab_aggressive_data.json"))
            h1rows, h4rows = d["H1"], d["H4"]
        else:
            h1rows, h4rows = wins[name]["H1"], wins[name]["H4"]
        sigs = funnel_signals(rows, h1rows, h4rows)
        idx_of = {int(r["time"]): i for i, r in enumerate(rows)}

        def funnel(row):
            return sigs.get(idx_of.get(int(row.get("time", 0)), -1))

        rr = [abs(float(s["tp"]) - float(s["entry"])) /
              max(abs(float(s["entry"]) - float(s["sl"])), 1e-9)
              for s in sigs.values()]
        gr = [str(s.get("grade") or "").upper() for s in sigs.values()]
        row = {
            "_bars": len(rows), "_signals": len(sigs),
            "grade_mix": {g: gr.count(g) for g in sorted(set(gr))},
            "rr_min": round(min(rr), 3), "rr_max": round(max(rr), 3),
            "signals_below_live_rr": sum(1 for v in rr if v < MIN_RISK_REWARD),
            "signals_above_live_grade": sum(
                1 for g in gr if g > MIN_SETUP_GRADE),
        }
        for label, kw in (("nogates", dict(min_rr=0.0, min_grade=None)),
                          ("gradeB", dict(min_rr=0.0, min_grade=MIN_SETUP_GRADE)),
                          ("gradeB_rr15", dict(min_rr=MIN_RISK_REWARD,
                                              min_grade=MIN_SETUP_GRADE))):
            res = lh.backtest_ohlc(rows, funnel, spread=lh.SPREAD, **lh.LADDER,
                                   time_stop_bars=lh.live_time_stop_bars(rows), **kw)
            row[label] = lh.r_stats(res, time_stop_bars=lh.live_time_stop_bars(rows))
        out["legs"][name] = row
        print(name, json.dumps({k: row[k] for k in
                                ("_signals", "nogates", "gradeB", "gradeB_rr15")}),
              flush=True)

    json.dump(out, open(OUT, "w"), indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
