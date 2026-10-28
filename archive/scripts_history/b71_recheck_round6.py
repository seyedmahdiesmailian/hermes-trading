#!/usr/bin/env python3
"""b71 — re-measure the round-6 arms under the LIVE time exit, honestly.

Todo b71 exists because round-6's headline (dayext_cont_w10 ladder exp_R
+1.096 — the best number any lab arm ever produced) was an ARTEFACT: mean stop
5.66 ATR from entry, mean hold 87 M15 bars (max 520 = 5+ days). A swing
position scored on an intraday board. The old lab harness never passed
time_stop_bars, so live's 36h time_exit was simply absent from the measurement.

This script re-runs every round-6 arm through engines.lab_harness.run_arm —
which measures plain / ladder / ladder_ts (the live b60 ladder PLUS the live
36h time exit, derived from MAX_POSITION_AGE_HOURS and the dataset's own bar
spacing) and prints the hold column next to exp_R — and ships the result to
data/backtest/b71_harness_recheck.json. tests/test_b71_lab_harness.py pins
that shipped JSON: every arm row must carry ladder_ts + mean_hold_bars, and
the w10 artefact must be visible as a >0.15R drop under the time exit.

Read-only research code; nothing here touches the live trading path.
"""
import os
import sys
import json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from engines import lab_harness as lh          # noqa: E402
from scripts import b68g_dayext_lab as lab     # noqa: E402

DATA = json.load(open(os.path.join(_ROOT, "data/backtest/ab_aggressive_data.json")))
M15 = DATA["M15"]
IDX = {r["time"]: n for n, r in enumerate(M15)}


def wrap(fn):
    """row -> index arm (the indexed() adapter convention of every b68 round)."""
    def w(row):
        i = IDX.get(row.get("time"))
        return None if i is None else fn(i)
    return w


def main():
    lab.M15 = M15
    lab.IDX = IDX
    ledger = {"_time_stop_bars": lh.live_time_stop_bars(M15)}
    arms = [name for name, _fn in lab.ARMS]
    for name, fn in lab.ARMS:
        ledger[name] = lh.run_arm(M15, wrap(fn))
        lh.print_table(ledger, [name], label=f"{name} (b71 harness)")
    complaints = lh.summarize(ledger, arms)
    ledger["_honesty_complaints"] = complaints
    print("\n=== b71 honesty summary ===")
    if complaints:
        for c in complaints:
            print("!", c)
    else:
        print("no complaints — every arm quoted from its ladder_ts row")
    p = os.path.join(_ROOT, "data", "backtest", "b71_harness_recheck.json")
    json.dump(ledger, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
