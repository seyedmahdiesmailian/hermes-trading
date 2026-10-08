#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 10 — COMBINATION (REVERSED PAIRING): day-extension
geometry gated on a same-day PD-extreme break.

Standing loop (b68): each run tests ONE candidate not yet in the lab. Rounds
7-9 ran three combinations, all with the PDH/PDL level as the GEOMETRY and
some other family as the oracle:

  round 7:  nr7 geometry  x dayext oracle   — gate LIFTED control (0.598->0.622)
  round 8:  pdh geometry  x squeeze oracle  — gate LOWERED control (0.627->0.406)
  round 9:  pdh geometry  x dayext oracle   — FIRST arm to pass the merit bar
            (0.924 cached / 0.891 fresh), lane positive on all three axes.

This round flips the roles of the round-9 pairing: the DAY-PATH arm supplies
the geometry (dayext_cont_a10 — the 1.0*ATR-behind-entry stop, the variant
whose hold is intraday and whose R is comparable to the funnel's ~1 ATR risk;
the level-anchored w10 variant is the b71 artefact arm and stays out of any
headline), and the LEVEL break is the oracle: has price already closed
through the previous trading day's extreme IN THE SAME DIRECTION today
(bars <= i-1 only)?

Why this pairing is worth measuring (and why it is NOT the round-9 arm
twice): round 9 asked "is a level break more likely to follow through when
the day has committed?" — the answer was yes, hard (the gate fires on ~37%
of pdh signals and lifts them above the funnel). The mirror question is "is
a day-commitment continuation more likely to work when the level has ALREADY
broken today?" — i.e. is the level break a LEADING confirmation of the path,
rather than its consequence? The two arms select different trades: round 9's
gated arm fires at the moment of the level break (bar i-1 closes through the
level) on an extended day; this arm fires at the moment the day-extension
trigger prints (bar i-1 closes >= 1.5 ATR from the day open), which is often
HOURS after the level break. The pre-round probe on the cached 3000 M15 bars
confirms the split is real, not degenerate: of 1130 dayext signals the
same-day-break oracle fires BUY/SELL agreement on 699 (62%), DISAGREES on
178 (16% — the day extended but the last PD break went the other way), and
is silent (no break yet today) on 253 (22%). That disagree arm is the
b73-recommended "path-on-path" cut and the round's key control question.

Arms:
  dayext_a10_control   — round-6 arm re-measured (control, same harness)
  dayext_pdbreak_agree — extension AND last same-day PD break agrees
  dayext_pdbreak_dis   — extension AND last same-day PD break OPPOSES
                         (the b73 path-on-path cut, measured standalone)
  dayext_pdbreak_not   — extension but NO same-day PD break yet (what the
                         agree gate drops for lack of information)

b72 playbook compliance: (1) PURE INTERSECTION — geometry is dayext_cont_a10's
unchanged, the level break is a direction oracle only; (2) ANTI-VACUITY probe
(fire counts + agree/disagree/notyet split) ships in _probe; (3) the UNGATED
ingredient is re-measured as CONTROL in the same run; (4) the confirm ledger's
verdict numbers get pinned by a test; (5) lane exp_R and dd_R quoted together.

No lookahead: the oracle scans breaking bars t <= i-1 (the signal bar), the
day levels come only from PREVIOUS completed trading days, ATR and the day
open use bars <= i-1. Entry is bar i's OPEN.

Measured through the b71 harness (engines.lab_harness.run_arm): plain /
ladder / ladder_ts (live b60 ladder + live 36h time exit, derived), hold
columns mandatory, trades:0 must name its clause.

Merit bar (b68 round-1 METHOD RULE + round-4 update): replacement needs to
beat funnel +0.854R cached AND the funnel's own score on the SAME fresh bars;
the lane probe feeds b70's capacity question.
"""
import os
import sys
import json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from engines import lab_harness as lh          # noqa: E402  (b71 harness)
from scripts import b68e_pdh_lab as pl         # noqa: E402  (day levels + trading_day)
from scripts import b68g_dayext_lab as dl      # noqa: E402  (geometry supplier)
from scripts import b68i_squeeze_pdh_lab as r8 # noqa: E402  (build_levels reuse)

DATA = json.load(open(os.path.join(_ROOT, "data/backtest/ab_aggressive_data.json")))
M15 = DATA["M15"]
IDX = {r["time"]: n for n, r in enumerate(M15)}
# Both ingredient modules close over their own module-level M15/IDX — repoint
# them at THIS dataset so dayext and the level oracle see identical bars.
pl.M15 = dl.M15 = M15
pl.IDX = dl.IDX = IDX

EXT = 1.5      # round-6/9 threshold (probe P4)


def rebind(rows):
    """Point ALL ingredient modules (and this one's IDX) at a new dataset and
    rebuild the day levels from it (same contract as rounds 8/9)."""
    global M15, IDX
    M15 = rows
    IDX = {r["time"]: n for n, r in enumerate(rows)}
    pl.M15 = dl.M15 = rows
    pl.IDX = dl.IDX = IDX
    pl.LEVELS = r8.build_levels(rows)


rebind(M15)   # also (re)builds LEVELS from the cached bars


def pd_break_info(i):
    """Direction oracle: the LAST close-confirmed break of the previous
    trading day's extreme that happened WITHIN the trading day the signal bar
    belongs to, scanning breaking bars t <= i-1 only. Returns
    (side, level_price) / None (None = no same-day break yet, or no level).
    Reads only closed bars up to the signal bar — no lookahead. The level is
    carried so the confirm's stretch probe (b73 rule b) can measure entry
    distance from the broken level."""
    if i < 30 or i >= len(M15):
        return None
    m = M15
    day = pl.trading_day(m[i - 1]["time"])
    if day not in pl.LEVELS:
        return None
    ph, plo = pl.LEVELS[day]
    j = i - 1
    while j > 0 and pl.trading_day(m[j - 1]["time"]) == day:
        j -= 1
    side = level = None
    for t in range(max(j, 1), i):          # t = breaking bar, up to i-1
        pc = float(m[t - 1]["close"])
        c = float(m[t]["close"])
        if pc <= ph < c:
            side, level = "BUY", ph
        elif pc >= plo > c:
            side, level = "SELL", plo
    return None if side is None else (side, level)


def pd_break_side(i):
    """The oracle's direction only (see pd_break_info)."""
    info = pd_break_info(i)
    return None if info is None else info[0]


def geo(i):
    """The geometry supplier: round-6's dayext continuation with the 'atr'
    stop (1.0*ATR behind entry) — the intraday-hold variant."""
    return dl.dayext(i, "cont", "atr", ext=EXT)


def combo(i):
    """dayext_cont_a10 AND the last same-day PD break agrees.
    Pure intersection: the returned dict is dayext's, unchanged."""
    s = geo(i)
    if not s:
        return None
    if pd_break_side(i) != s["side"]:
        return None
    return s


def opposed(i):
    """The b73 path-on-path cut: extension fires but the last same-day break
    went the OTHER way. Same geometry, so its exp_R is the direct read on
    whether agreement is what the gate buys."""
    s = geo(i)
    if not s:
        return None
    d = pd_break_side(i)
    if d is None or d == s["side"]:
        return None
    return s


def notbroken(i):
    """What the agree gate drops for lack of information: extension fires but
    no same-day PD break has confirmed yet."""
    s = geo(i)
    if not s:
        return None
    if pd_break_side(i) is not None:
        return None
    return s


def wrap(fn):
    def w(row):
        i = IDX.get(row.get("time"))
        return None if i is None else fn(i)
    return w


ARMS = [("dayext_a10_control", lambda i: geo(i)),
        ("dayext_pdbreak_agree", combo),
        ("dayext_pdbreak_dis", opposed),
        ("dayext_pdbreak_not", notbroken)]


def gate_probe():
    """Anti-vacuity (b72 rule 2): fire counts of each ingredient and the
    agree/disagree/notyet split of the dayext signal set. A gate that fires
    on ~100% or whose split is ~0/100 is the same arm twice, not a combo."""
    n = len(M15)
    dayext = agree = dis = not_ = 0
    for i in range(30, n):
        s = geo(i)
        if not s:
            continue
        dayext += 1
        d = pd_break_side(i)
        if d is None:
            not_ += 1
        elif d == s["side"]:
            agree += 1
        else:
            dis += 1
    return {"dayext_signals": dayext, "agree": agree, "disagree": dis,
            "no_break_yet": not_,
            "gate_share": round(agree / dayext, 3) if dayext else None,
            "disagree_share": round(dis / dayext, 3) if dayext else None}


def main():
    probe = gate_probe()
    print("pdbreak gate probe:", json.dumps(probe), flush=True)
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
    p = os.path.join(_ROOT, "data", "backtest", "b68k_pdh_dayext_lab.json")
    json.dump(ledger, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
