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
from scripts.b81_lane_rescore import m5_window_for, m5_source_rows

OUT = "data/backtest/b80_gate_parity.json"
LEGS = ("cached", "W1", "W2", "W3", "W4")
# b222: the broker M5 stream only covers the newest ~45 days, so only the legs
# inside that span price the b187 entry trigger. The rest stay pre-b222.
M5_SOURCE = "data/backtest/b182_m5_bars.json"


def funnel_signals(rows, h1rows, h4rows, m5_stream=None):
    """b222: `m5_stream` prices the b187 M5 3-close trigger. Without it an
    M15-spaced entry stream cannot confirm (m5_confirmation sees no rows), so
    ~67% of bars land in wait_for_trigger and the population collapses. Sourced
    from the ONE definition in scripts/b81_lane_rescore (m5_window_for, never
    restated); None keeps the pre-b222 population byte-identical."""
    h1t = [r.get("time", 0) for r in h1rows]
    h4t = [r.get("time", 0) for r in h4rows]
    m5t = [int(r.get("time", 0)) for r in (m5_stream or [])]
    from engines.backtest_real import M5_BAR_SECONDS
    gaps = sorted(int(rows[i + 1]["time"]) - int(rows[i]["time"])
                  for i in range(len(rows) - 1)
                  if isinstance(rows[i].get("time"), (int, float))
                  and isinstance(rows[i + 1].get("time"), (int, float)))
    gaps = [g for g in gaps if g > 0]
    bar_spacing = gaps[len(gaps) // 2] if gaps else M5_BAR_SECONDS
    sigs = {}
    for i, row in enumerate(rows):
        bt = row.get("time", 0)
        j1 = bisect.bisect_right(h1t, bt)
        j4 = bisect.bisect_right(h4t, bt)
        m5_rows = (m5_window_for(m5_stream, m5t, int(bt) + bar_spacing)
                   if m5_stream else None)
        s = strategy_signal(row, h1rows[max(0, j1 - 80):j1],
                            h4rows[max(0, j4 - 80):j4], i,
                            m15_window=rows[max(0, i - 120):i + 1],
                            m5_rows=m5_rows)
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
    # b222: price the b187 trigger on the legs the M5 source covers.
    m5_all = m5_source_rows(M5_SOURCE)
    m5_span = (int(m5_all[0]["time"]), int(m5_all[-1]["time"])) if m5_all else None

    def m5_for(rows):
        if not m5_span:
            return None
        span = (int(rows[0]["time"]), int(rows[-1]["time"]))
        if span[1] < m5_span[0] or span[0] > m5_span[1]:
            return None
        return m5_all

    for name in LEGS:
        rows = legs[name]
        if name == "cached":
            d = json.load(open("data/backtest/ab_aggressive_data.json"))
            h1rows, h4rows = d["H1"], d["H4"]
        else:
            h1rows, h4rows = wins[name]["H1"], wins[name]["H4"]
        sigs = funnel_signals(rows, h1rows, h4rows,
                              m5_stream=m5_for(rows))
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
            # b222: a leg outside the M5 source prices zero signals, so the
            # RR stats have no population to summarize. None (not a crash) is
            # the honest answer for a leg the funnel cannot fire on.
            "rr_min": round(min(rr), 3) if rr else None,
            "rr_max": round(max(rr), 3) if rr else None,
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
