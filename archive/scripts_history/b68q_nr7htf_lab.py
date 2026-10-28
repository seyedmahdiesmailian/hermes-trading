#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 17 — NR7 compression breakout GATED on H4 trend.

Standing loop (b68): each round tests ONE candidate not yet measured. After
16 rounds the surviving ingredients are known: nr7_break_w10 is the only arm
whose ADDITIVE LANE ever beat the funnel's own per-trade R (round 5: 0.620 vs
0.586 fresh), and the H4 trend-state gate is the only oracle that LIFTED its
control on BOTH independent clean windows (round 12: pdh 0.612/0.623 ->
0.657/0.927 vs funnel 0.524/0.521). The two have never been paired: rounds
7-10 gated nr7/pdh on PATH (dayext), COMPRESSION (squeeze) and same-day LEVEL
(PD-break) oracles, round 16 on a weekly STATE — the HTF-regime oracle applied
to the nr7 geometry is the last unmeasured pairing of the two strongest
survivors.

Why this pairing is justified under the loop's own rules, not just novel:
- b73 (sequencing): round 8's failure was compression acting as the ORACLE
  (its information is spent by breakout time). Here compression is the
  GEOMETRY (its squeeze IS the setup) and the oracle is a slow regime STATE —
  the pairing type whose gate lifted its control in rounds 7/9/12.
- b75 (geometry freshness): the geometry supplier is nr7_break_w10 — its
  close-confirmed break bar IS the trigger, so the fresh member carries the
  stop; the H4 EMA state is zero-lag background (fixed by closed HTF bars).
- b78 (direction-mix disclosure): the BUY/SELL mix of every arm's actual
  trades ships in the ledger and the verdict quotes it (round-16 structure).
- Counter-consideration to measure: nr7 fires ~4x more often than pdh (455 vs
  ~110 fresh trades), so even a lifting gate may leave the lane crowded
  (round 6/10's slot-crowding failure). The confirm measures the lane on
  every window, not just the standalone arm.

Oracle definition (VERBATIM round 12, imported from b68m_htf_pdh_lab so the
two rounds cannot drift): trend_state(H4P, entry_time) = last FULLY CLOSED H4
close above/below EMA50 with EMA50 rising/falling over 5 H4 bars; 'BUY' /
'SELL' / None (silent). Only bars closed before the M15 entry bar opens are
read — stricter than the funnel's own convention, so the gate cannot peek.

Arms (b72 playbook):
  nr7_w10_control   — round-5 arm re-measured, same bars/harness (rule 3)
  nr7_h4t_agree     — nr7 AND H4 state aligned (rule 1: PURE intersection,
                      geometry is nr7_break's, unchanged)
  nr7_h4t_disagree  — what the gate DROPS (rule: the selection-ordering arm)
Anti-vacuity gate_probe ships in the ledger (rule 2); lane exp_R AND dd_R are
quoted together (rule 5); the shipped verdict numbers get pinned by a test
(rule 4).

Measured through the b71 harness (engines.lab_harness.run_arm): plain /
ladder / ladder_ts (live b60 ladder + live 36h time exit, derived), hold
columns mandatory, trades:0 must name its clause.

Merit bar (round-11/b76 wording): the cached 0.854 funnel bar is
regime-inflated and informational only. REPLACEMENT requires beating the
funnel's ladder_ts on the SAME bars in EVERY independent window (b74's
all-windows rule) — scripts/b68q_confirm_nr7htf.py does that on cached +
W1..W4 with the b77 decay pre-flight as step 0.

Read-only research code: nothing here is imported by the live trading path.
"""
import os
import sys
import json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from engines import lab_harness as lh          # noqa: E402  (b71 harness)
from scripts import b68f_nr7_lab as nf         # noqa: E402  (geometry supplier)
from scripts import b68m_htf_pdh_lab as mm     # noqa: E402  (H4 oracle, verbatim)

CACHED_PATH = os.path.join(_ROOT, "data/backtest/ab_aggressive_data.json")
STOP_ATR = 1.0        # nr7_break wide is round 5's survivor — UNCHANGED


def bind(m15, h1, h4):
    """Point the geometry module AND the oracle's H4 stream at one dataset.

    nr7_break closes over nf.M15/nf.IDX; the H4 prep is rebuilt from the
    leg's own h4 rows (never a stale table — the b76 contamination class).
    """
    nf.M15 = m15
    nf.IDX = {r["time"]: n for n, r in enumerate(m15)}
    prep = mm._htf_prep(h4, 4 * 3600)
    return prep


def state_at(prep, i):
    """H4 trend state at the OPEN of bar i (entry bar) — closed bars only."""
    return mm.trend_state(prep, nf.M15[i]["time"])


def gated(i, prep, want="agree"):
    """The combo arms: nr7_break_w10's dict UNCHANGED, kept only when the H4
    state agrees (want='agree') or disagrees (want='dis') with the break
    direction. Silent state drops from both arms (counted in the probe)."""
    s = nf.nr7_break(i, wide=True)
    if not s:
        return None
    side, _age = state_at(prep, i)
    if want == "agree":
        return s if side == s["side"] else None
    return s if (side is not None and side != s["side"]) else None


def indexed(fn):
    def w(row):
        i = nf.IDX.get(row.get("time"))
        return None if i is None else fn(i)
    return w


def gate_probe(prep):
    """b72 rule 2 — anti-vacuity + b75 rule 6 (state age): fire counts of the
    geometry, the agree/disagree/silent split, and the state-age distribution
    of the agree subset (a mostly-fresh state is an event in disguise)."""
    n = nr7 = agree = dis = silent = 0
    ages = []
    for i in range(30, len(nf.M15)):
        s = nf.nr7_break(i, wide=True)
        if not s:
            continue
        nr7 += 1
        side, age = state_at(prep, i)
        if side is None:
            silent += 1
        elif side == s["side"]:
            agree += 1
            ages.append(age)
        else:
            dis += 1
    ages.sort()
    return {"nr7_signals": nr7, "agree": agree, "disagree": dis,
            "silent": silent,
            "gate_share": round(agree / nr7, 3) if nr7 else None,
            "cut_share": round(dis / nr7, 3) if nr7 else None,
            "agree_state_age_median_htf_bars":
                ages[len(ages) // 2] if ages else None,
            "agree_state_age_p25_htf_bars":
                ages[int(0.25 * (len(ages) - 1))] if ages else None}


def stretch_probe(prep):
    """b73 rule (b): mean |entry - broken NR7 level| / ATR, control vs gated.
    The gate cannot move the entry (pure intersection), so a stretch delta
    far from 0 would mean a binding bug, not geometry."""
    vals = {"control": [], "gated": []}
    for i in range(30, len(nf.M15)):
        s = nf.nr7_break(i, wide=True)
        if not s:
            continue
        j = nf.find_nr7(i)
        if j is None:
            continue
        a = nf.atr(i - 1)
        if not a:
            continue
        hi, lo = float(nf.M15[j]["high"]), float(nf.M15[j]["low"])
        lvl = hi if s["side"] == "BUY" else lo
        d = abs(float(s["entry"]) - lvl) / a
        vals["control"].append(d)
        side, _age = state_at(prep, i)
        if side == s["side"]:
            vals["gated"].append(d)
    out = {}
    for k, v in vals.items():
        v = sorted(v)
        n = len(v)
        out[k] = {"n": n,
                  "mean_stretch_atr": round(sum(v) / n, 3) if n else None,
                  "median_stretch_atr": v[n // 2] if n else None}
    return out


ARMS = [("nr7_w10_control", lambda i, p: nf.nr7_break(i, wide=True)),
        ("nr7_h4t_agree", lambda i, p: gated(i, p, "agree")),
        ("nr7_h4t_disagree", lambda i, p: gated(i, p, "dis"))]


def main():
    data = json.load(open(CACHED_PATH))
    prep = bind(data["M15"], data["H1"], data["H4"])
    rows = data["M15"]
    print(f"cached leg: {len(rows)} M15 bars")
    print("gate_probe:", json.dumps(gate_probe(prep)))
    ledger = {}
    for name, fn in ARMS:
        ledger[name] = lh.run_arm(rows, indexed(lambda i: fn(i, prep)))
        lh.print_table(ledger, [name], label=f"{name} (cached, b71)")
        print(flush=True)
    complaints = lh.summarize(ledger, [n for n, _ in ARMS])
    print("=== honesty ===")
    for c in complaints or ["no complaints"]:
        print("!", c)
    out = {"_note": "round 17 cached leg: NR7 compression breakout gated on "
                    "the H4 EMA trend state (round-12's only clean-window "
                    "replicating oracle), b71 harness, b72 anti-vacuity, "
                    "b75 state-age, b78 mix probe",
           "_time_stop_bars": lh.live_time_stop_bars(rows),
           "_probe": gate_probe(prep),
           "_stretch_probe": stretch_probe(prep),
           "_honesty_complaints": complaints,
           **ledger}
    p = os.path.join(_ROOT, "data", "backtest", "b68q_nr7htf_lab.json")
    json.dump(out, open(p, "w"), indent=1)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
