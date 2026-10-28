#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 7 — COMBINATION: NR7 squeeze x day-extension agree.

Standing loop (b68): each run tests ONE candidate method not yet in the lab.
Rounds 1-6 screened every classic FAMILY (mean-rev, momentum, trend+pullback,
level breakout, compression breakout, SMC/RTM, day path-shape, gap, session
drift) — all rejected as replacements. The round-6 backlog note says the next
rounds should test a COMBINATION the funnel does not already use: two of the
rejected families gated on each other. This round does exactly that.

The pair: NR7 compression breakout (round 5 — the strongest standalone arm,
0.598 cached / 0.517 fresh, and the ONLY lane whose exp_R beat the funnel's)
gated on TRADING-DAY EXTENSION direction (round 6 — the strongest raw drift
ever measured here, t=7.4, though it failed standalone). The thesis: a squeeze
breakout is more likely to follow through when the day has ALREADY committed
to that direction (price >= 1.5 ATR from the day open after 13:00 UTC, the
b68g trigger), and the extension gate should cut the ~half of nr7 breaks that
fight the day's drift.

The funnel does NOT use either ingredient as a direction gate: its bias comes
from H1/H4 swing structure + SMC merge (engines/backtest_real.strategy_signal
-> build_plan_context/merge_smc_with_classic); nothing in it reads the day
open or a range-squeeze state. So this is a genuinely unused combination.

Arms (round 4/5/6 convention: signal is bar i-1's CLOSE through the condition,
entry is bar i's OPEN, TP 2R, grade B):
  nr7_w10_control  — plain nr7_break wide (round-5 arm, re-measured here as
                     the CONTROL so the gate's effect is same-dataset, same
                     harness)
  nr7_dayext_agree — nr7_break wide AND b68g dayext continuation fires the
                     SAME side on the same bar (intersection of the two arms,
                     no new geometry)

FIRST ROUND RUN THROUGH THE b71 HARNESS (engines/lab_harness.run_arm): every
arm measured plain / ladder / ladder_ts (live b60 ladder + live 36h time exit,
derived), hold columns mandatory, a trades:0 row must name its clause. The
gate's own fire counts ship in _probe so a future reader can tell "filtered
to nothing" from "measured and flat" (b69 lesson).

Merit bar (b68 round-1 METHOD RULE + round-4 update): replacement needs to
beat funnel +0.854R cached AND the funnel's own score on the SAME fresh bars;
the lane probe (funnel-first, arm on free bars) feeds b70's capacity question.
"""
import os
import sys
import json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from engines import lab_harness as lh          # noqa: E402  (b71 harness)
from scripts import b68f_nr7_lab as nl         # noqa: E402
from scripts import b68g_dayext_lab as dl      # noqa: E402

DATA = json.load(open(os.path.join(_ROOT, "data/backtest/ab_aggressive_data.json")))
M15 = DATA["M15"]
IDX = {r["time"]: n for n, r in enumerate(M15)}
# Both ingredient modules close over their own module-level M15/IDX — repoint
# them at THIS dataset so nr7_break and dayext see identical bars.
nl.M15 = dl.M15 = M15
nl.IDX = dl.IDX = IDX

EXT = 1.5          # b68g's trigger threshold (its cont arms ran at 1.5/2.5)


def rebind(rows):
    """Point both ingredient modules (and this one's IDX) at a new dataset."""
    global M15, IDX
    M15 = rows
    IDX = {r["time"]: n for n, r in enumerate(rows)}
    nl.M15 = dl.M15 = rows
    nl.IDX = dl.IDX = IDX


def combo(i, ext=EXT):
    """nr7_break wide AND the day-extension continuation fires the same side.

    Pure intersection: geometry (entry/SL/TP) is the NR7 arm's, unchanged; the
    dayext arm is used ONLY as a direction oracle, so no new stop geometry can
    sneak in the b69/round-6 traps.
    """
    s7 = nl.nr7_break(i, wide=True)
    if not s7:
        return None
    sd = dl.dayext(i, "cont", "atr", ext=ext)
    if not sd:
        return None
    if str(sd["side"]) != str(s7["side"]):
        return None
    return s7


def wrap(fn):
    def w(row):
        i = IDX.get(row.get("time"))
        return None if i is None else fn(i)
    return w


ARMS = [("nr7_w10_control", lambda i: nl.nr7_break(i, wide=True)),
        ("nr7_dayext_agree", lambda i: combo(i, ext=EXT)),
        ("nr7_dayext_agree_e25", lambda i: combo(i, ext=2.5))]


def gate_probe(ext=EXT):
    """Fire counts of the ingredients and the intersection — anti-vacuity:
    if the combo fires 0, the probe says whether nr7, the gate, or the
    disagreement killed it (b69 lesson: trades:0 must never read as 'no edge').
    """
    n = len(M15)
    nr7 = gate = agree = disagree = 0
    for i in range(30, n):
        s7 = nl.nr7_break(i, wide=True)
        if not s7:
            continue
        nr7 += 1
        sd = dl.dayext(i, "cont", "atr", ext=ext)
        if not sd:
            continue
        gate += 1
        if str(sd["side"]) == str(s7["side"]):
            agree += 1
        else:
            disagree += 1
    return {"nr7_signals": nr7, "dayext_gate_fires": gate,
            "agree": agree, "disagree": disagree,
            "gate_share": round(gate / nr7, 3) if nr7 else None,
            "agree_share_of_gated": round(agree / gate, 3) if gate else None}


def main():
    probe = {"ext": EXT, "e25": gate_probe(2.5), "e15": gate_probe(1.5)}
    print("gate probe:", json.dumps(probe), flush=True)
    ledger = {"_probe": probe, "_time_stop_bars": lh.live_time_stop_bars(M15)}
    arms = [name for name, _fn in ARMS]
    for name, fn in ARMS:
        ledger[name] = lh.run_arm(M15, wrap(fn))
        lh.print_table(ledger, [name], label=f"{name} (b71 harness)")
    complaints = lh.summarize(ledger, arms)
    ledger["_honesty_complaints"] = complaints
    print("\n=== b71 honesty summary ===")
    for c in complaints or ["no complaints"]:
        print("!", c)
    p = os.path.join(_ROOT, "data", "backtest", "b68h_combo_lab.json")
    json.dump(ledger, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
