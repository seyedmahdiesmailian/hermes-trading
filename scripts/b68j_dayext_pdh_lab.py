#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 9 — COMBINATION: PDH/PDL breakout x day-extension.

Standing loop (b68): each run tests ONE candidate not yet in the lab. Rounds
1-6 screened every classic FAMILY (all rejected as replacements); rounds 7-8
ran the first two COMBINATIONS of the surviving ingredients:

  round 7: nr7 (compression geometry) x dayext (path gate)  — gate LIFTED its
           control (0.598->0.622 cached, 0.519->0.587 fresh), lane still lost;
  round 8: pdh (level geometry) x nr7 squeeze (compression gate) — gate LOWERED
           its control (0.627->0.406), explained by the stretch probe.

This round closes the 2x2 matrix: the third pairing of {nr7, pdh, dayext} is
pdh geometry gated on the dayext direction oracle — exactly the pairing type
the b73 sequencing rule recommends (gate a LEVEL ingredient on a PATH
ingredient, never on a compression state), and the pairing with the highest
prior: the gate that WORKED (dayext is the only gate that ever lifted its
control) applied to the arm that WORKED (pdh is the only arm that ever beat
the funnel on fresh data, 0.640 vs 0.576).

Thesis: a close-confirmed break of the previous trading day's extreme is more
likely to follow through when the day has ALREADY committed to that direction
(price >= EXT * ATR(14) from the trading-day open after 13:00 UTC, the round-6
trigger). The level supplies location, the day path supplies commitment.
Counter-consideration this round must measure (round-8's failure mode): the
gate demands price already ran 1.5 ATR from the day open, so a gated PDH break
may enter MORE stretched from the broken level — the confirm's stretch probe
(b73 rule b: standard on every combination confirm) settles whether the
selection is geometrically harmful here too.

b72 playbook compliance:
  (1) PURE INTERSECTION — geometry (entry/SL/TP) is pdh_break's, unchanged;
      dayext is a direction oracle only (its 'atr' stop variant is used so the
      oracle itself can never silently drop on risk<=0 — the b69 trap class),
      so no new stop geometry can reintroduce the round-6 traps;
  (2) ANTI-VACUITY probe ships in _probe: fire counts of each ingredient and
      the agree/disagree split of the gated subset;
  (3) the UNGATED ingredient (pdh_break_w10) is re-measured as the CONTROL in
      the same run, same harness, same bars, so the gate's delta is honest;
  (4) the confirm ledger's verdict numbers get pinned by a test;
  (5) lane exp_R and dd_R are quoted together.

Arms:
  pdh_w10_control      — round-4 arm, re-measured (control)
  pdh_dayext_agree     — pdh AND day extended >= 1.5 ATR the SAME way
  pdh_dayext_agree_e25 — same with the round-6 probe's stronger 2.5 ATR gate
  pdh_dayext_notyet    — the COMPLEMENT: pdh breaks the gate DROPS (the day
      has not extended 1.5 ATR from its open yet). Measured because the
      agree/disagree split is DEGENERATE by construction here (disagree=0 on
      both sets): a close-confirmed PDH break with the day already extended
      1.5 ATR from its open is directionally automatic — price beyond PDH is
      beyond the day open by more than PDH is. So the honest anti-vacuity
      question is not "does the oracle ever disagree" but "is what it drops
      good or bad": if the complement arm is NEGATIVE, the gate's cut is real
      selection (it removes the early, uncommitted breaks that reverse back
      inside the day); if the complement is also positive, the +0.30R lift is
      a small-sample fluke of a subset, not a property.

No lookahead: the oracle reads only bars <= i-1 (day open, day bar count, ATR
and the signal bar close all come from closed bars); the pdh arm itself reads
only previous completed trading days. Entry is bar i's OPEN.

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
from scripts import b68e_pdh_lab as pl         # noqa: E402  (geometry supplier)
from scripts import b68g_dayext_lab as dl      # noqa: E402  (path oracle)
from scripts import b68i_squeeze_pdh_lab as r8 # noqa: E402  (build_levels reuse)

DATA = json.load(open(os.path.join(_ROOT, "data/backtest/ab_aggressive_data.json")))
M15 = DATA["M15"]
IDX = {r["time"]: n for n, r in enumerate(M15)}
# Both ingredient modules close over their own module-level M15/IDX — repoint
# them at THIS dataset so pdh_break and dayext see identical bars.
pl.M15 = dl.M15 = M15
pl.IDX = dl.IDX = IDX

STOP_ATR = 1.0     # round 4's lesson: 0.5 ATR gets wicked out, 1.0 survives
EXT, EXT25 = 1.5, 2.5   # round-6 thresholds (1.5 = probe P4, 2.5 = strongest drift)


def rebind(rows):
    """Point ALL ingredient modules (and this one's IDX) at a new dataset and
    rebuild the day levels from it (same contract as round 8's rebind)."""
    global M15, IDX
    M15 = rows
    IDX = {r["time"]: n for n, r in enumerate(rows)}
    pl.M15 = dl.M15 = rows
    pl.IDX = dl.IDX = IDX
    pl.LEVELS = r8.build_levels(rows)


rebind(M15)   # also (re)builds LEVELS from the cached bars


def dayext_dir(i, ext):
    """Direction oracle: the round-6 continuation arm's SIDE at bar i, using
    the 'atr' stop variant so the oracle can never silently drop a signal on
    risk<=0 (b69 trap class) — only the side is consumed by combo()."""
    g = dl.dayext(i, "cont", "atr", ext=ext)
    return g["side"] if g else None


def combo(i, ext):
    """pdh_break (wide) AND the day extended the SAME way.
    Pure intersection: the returned dict is pdh_break's, unchanged."""
    s = pl.pdh_break(i, STOP_ATR)
    if not s:
        return None
    if dayext_dir(i, ext) != s["side"]:
        return None
    return s


def complement(i, ext):
    """The arm the gate DROPS: pdh_break fires but the day has NOT extended
    ext*ATR from its open yet (oracle silent). Same geometry, so its ladder
    exp_R is the direct read on whether the gate's cut is real selection."""
    s = pl.pdh_break(i, STOP_ATR)
    if not s:
        return None
    if dayext_dir(i, ext) is not None:
        return None
    return s


def wrap(fn):
    def w(row):
        i = IDX.get(row.get("time"))
        return None if i is None else fn(i)
    return w


ARMS = [("pdh_w10_control", lambda i: pl.pdh_break(i, STOP_ATR)),
        ("pdh_dayext_agree", lambda i: combo(i, EXT)),
        ("pdh_dayext_agree_e25", lambda i: combo(i, EXT25)),
        ("pdh_dayext_notyet", lambda i: complement(i, EXT))]


def gate_probe(ext):
    """Anti-vacuity (b72 rule 2), adapted for a PATH gate whose disagree arm is
    degenerate by construction (see module docstring): the honest split is
    gated (oracle fires, always agrees) vs not_yet (oracle silent — what the
    gate drops). gate_share ~1 would mean the oracle never filters; not_yet ~0
    would mean the gate is the control twice."""
    n = len(M15)
    pdh = gated = agree = disagree = 0
    for i in range(30, n):
        s = pl.pdh_break(i, STOP_ATR)
        if not s:
            continue
        pdh += 1
        d = dayext_dir(i, ext)
        if d is None:
            continue
        gated += 1
        if d == s["side"]:
            agree += 1
        else:
            disagree += 1
    return {"pdh_signals": pdh, "dayext_gated": gated,
            "not_yet_dropped": pdh - gated,
            "agree": agree, "disagree": disagree,
            "gate_share": round(gated / pdh, 3) if pdh else None,
            "agree_share_of_gated": round(agree / gated, 3) if gated else None}


def main():
    probe = {"e15": gate_probe(EXT), "e25": gate_probe(EXT25)}
    print("dayext gate probe:", json.dumps(probe), flush=True)
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
    p = os.path.join(_ROOT, "data", "backtest", "b68j_dayext_pdh_lab.json")
    json.dump(ledger, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
