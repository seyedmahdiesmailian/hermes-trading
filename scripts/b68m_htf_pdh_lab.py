#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 12 — COMBINATION: PDH breakout x HTF-trend oracle.

Standing loop (b68): each round tests ONE candidate not yet measured. Round 11
(b68l) re-scored the whole decision set on TRULY independent windows and left
one fact standing: the UNGATED pdh_w10 is the only arm that beats the funnel
on both independent windows (0.612 W1 / 0.623 W2 vs funnel 0.524/0.521), while
round 9's dayext gate FLIPPED SIGN between regimes (agree 0.928->0.447,
complement 0.415->0.743) and was downgraded by b75's caveat.

So this round gates the ONLY replicated geometry (pdh, unchanged — b75's
freshness rule holds: the level break IS the trigger event) on an oracle
family that has never acted as a gate: the HIGHER-TIMEFRAME TREND state.
Rounds 7-10 used path (dayext), compression (NR7 squeeze) and same-day level
(PD-break) oracles; the funnel itself consumes H1/H4 context, so an HTF
regime filter is the pairing with the highest prior that has NOT been
measured as a standalone gate.

Oracle definition (no lookahead, deliberately slow so it is a STATE, not an
event): at the entry bar i, take only H1 (or H4) bars fully CLOSED before
bar i opens (r.time + span <= M15[i].time — stricter than the funnel's own
convention, so the gate can never peek). trend_up = last closed HTF close
above EMA50 AND EMA50 rising over the last 5 HTF bars; mirror for down.
Fewer than 56 HTF bars of history -> silent (None), counted as no-info.

Arms (b72 playbook compliance in brackets):
  pdh_w10_control        — round-4/11 arm re-measured, same bars/harness (3)
  pdh_h1t_agree          — pdh AND H1 trend state aligned  (1: pure
                           intersection, geometry is pdh_break's, unchanged)
  pdh_h4t_agree          — pdh AND H4 trend state aligned (slower state)
  pdh_h1t_disagree       — pdh AND H1 trend OPPOSITE (what the gate cuts)
  pdh_h1t_noinfo         — pdh while the oracle is silent (warmup only)
Anti-vacuity gate_probe ships in the ledger (2); lane exp_R AND dd_R are
quoted together (5); the b75 rule-(6) probe for a STATE oracle is the
state-AGE distribution (bars since the trend state flipped) — a gate whose
state is mostly freshly flipped is an event in disguise and inherits the
round-10 chase-tax risk, a gate whose state is old is background regime.

Measured through the b71 harness (engines.lab_harness.run_arm): plain /
ladder / ladder_ts (live b60 ladder + live 36h time exit, derived), hold
columns mandatory, trades:0 must name its clause.

Merit bar (round-11 update, b76): the cached 0.854 funnel bar is
regime-inflated and informational only; REPLACEMENT requires beating the
funnel's ladder_ts on the SAME bars in BOTH independent windows — that is
scripts/b68m_confirm_independent.py's job. This file is the cached leg.

Read-only research code: nothing here is imported by the live trading path.
"""
import os
import sys
import json
import bisect

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from engines import lab_harness as lh          # noqa: E402  (b71 harness)
from scripts import b68e_pdh_lab as pl         # noqa: E402  (geometry supplier)
from scripts import b68i_squeeze_pdh_lab as r8  # noqa: E402  (build_levels)

DATA = json.load(open(os.path.join(_ROOT, "data/backtest/ab_aggressive_data.json")))
M15 = DATA["M15"]
H1 = DATA["H1"]
H4 = DATA["H4"]
IDX = {r["time"]: n for n, r in enumerate(M15)}
STOP_ATR = 1.0                 # round-4 lesson: w10 is the surviving width
EMA_N, EMA_SLOPE_BARS = 50, 5
MIN_HTF_BARS = EMA_N + EMA_SLOPE_BARS + 1

# ingredient modules close over their own M15/IDX — repoint at THIS dataset
pl.M15 = M15
pl.IDX = IDX
pl.LEVELS = r8.build_levels(M15)


def _htf_prep(rows, span):
    """EMA50 series + times for one HTF stream (computed once per rebind)."""
    closes = [float(r["close"]) for r in rows]
    k = 2.0 / (EMA_N + 1)
    ema = [closes[0]]
    for c in closes[1:]:
        ema.append(c * k + ema[-1] * (1 - k))
    return {"t": [int(r["time"]) for r in rows], "c": closes, "e": ema,
            "span": span}


def rebind(m15, h1, h4):
    """Point the geometry + both HTF streams at a new dataset."""
    global M15, H1, H4, IDX, H1P, H4P
    M15, H1, H4 = m15, h1, h4
    IDX = {r["time"]: n for n, r in enumerate(m15)}
    pl.M15, pl.IDX = m15, IDX
    pl.LEVELS = r8.build_levels(m15)
    H1P = _htf_prep(h1, 3600)
    H4P = _htf_prep(h4, 4 * 3600)


rebind(M15, H1, H4)


def trend_state(prep, entry_time):
    """'BUY'/'SELL'/None — HTF regime at the moment bar `entry_time` opens.
    Only bars FULLY CLOSED before entry_time are read (no lookahead)."""
    j = bisect.bisect_right(prep["t"], entry_time - prep["span"])
    # j = count of HTF bars whose open time <= entry_time - span, i.e. whose
    # close happened at or before entry. Strictly closed bars only.
    if j < MIN_HTF_BARS:
        return None, None
    c, e = prep["c"], prep["e"]
    up = c[j - 1] > e[j - 1] and e[j - 1] > e[j - 1 - EMA_SLOPE_BARS]
    dn = c[j - 1] < e[j - 1] and e[j - 1] < e[j - 1 - EMA_SLOPE_BARS]
    side = "BUY" if up else "SELL" if dn else None
    if side is None:
        return None, j
    # state age: how many consecutive closed HTF bars share this side
    age = 0
    for i in range(j - 1, MIN_HTF_BARS - 2, -1):
        u = c[i] > e[i] and e[i] > e[i - EMA_SLOPE_BARS]
        d = c[i] < e[i] and e[i] < e[i - EMA_SLOPE_BARS]
        s = "BUY" if u else "SELL" if d else None
        if s != side:
            break
        age += 1
    return side, age


def gated(i, prep):
    """Pure intersection: pdh_break's dict, unchanged, only when the HTF
    state at the entry bar's open agrees with the break direction."""
    s = pl.pdh_break(i, STOP_ATR)
    if not s:
        return None
    side, _age = trend_state(prep, M15[i]["time"])
    if side != s["side"]:
        return None
    return s


def cut(i, prep, want):
    """The complement arms: what the gate DROPS (want='dis' opposite state,
    want='noinfo' silent state). Same geometry, so the exp_R delta is the
    direct read on whether the gate's cut is real selection."""
    s = pl.pdh_break(i, STOP_ATR)
    if not s:
        return None
    side, _age = trend_state(prep, M15[i]["time"])
    if want == "noinfo":
        return s if side is None else None
    return s if side is not None and side != s["side"] else None


def wrap(fn):
    def w(row):
        i = IDX.get(row.get("time"))
        return None if i is None else fn(i)
    return w


ARMS = [("pdh_w10_control", lambda i: pl.pdh_break(i, STOP_ATR)),
        ("pdh_h1t_agree", lambda i: gated(i, H1P)),
        ("pdh_h4t_agree", lambda i: gated(i, H4P)),
        ("pdh_h1t_disagree", lambda i: cut(i, H1P, "dis")),
        ("pdh_h1t_noinfo", lambda i: cut(i, H1P, "noinfo"))]


def gate_probe(prep):
    """b72 rule 2 — anti-vacuity: fire counts of the geometry, and the
    agree/disagree/silent split of the gated subset."""
    n = pdh = agree = dis = silent = 0
    ages = []
    for i in range(30, len(M15)):
        s = pl.pdh_break(i, STOP_ATR)
        if not s:
            continue
        pdh += 1
        side, age = trend_state(prep, M15[i]["time"])
        if side is None:
            silent += 1
        elif side == s["side"]:
            agree += 1
            ages.append(age)
        else:
            dis += 1
    ages.sort()
    return {"pdh_signals": pdh, "agree": agree, "disagree": dis,
            "silent": silent,
            "gate_share": round(agree / pdh, 3) if pdh else None,
            "cut_share": round(dis / pdh, 3) if pdh else None,
            "agree_state_age_median_htf_bars":
                ages[len(ages) // 2] if ages else None,
            "agree_state_age_p25_htf_bars":
                ages[int(0.25 * (len(ages) - 1))] if ages else None}


def stretch_probe(prep):
    """b73 rule (b) — standard on every combination confirm: mean |entry -
    broken level| / ATR at signal time, control vs gated vs cut. A gate whose
    retained entries sit FURTHER from the level is buying a chase tax
    (rounds 8/10); equal stretch means the lift is informational (round 9)."""
    rows = {"control": [], "gated": [], "cut": []}
    for i in range(30, len(M15)):
        s = pl.pdh_break(i, STOP_ATR)
        if not s:
            continue
        a = pl.atr(i - 1)
        day = pl.trading_day(M15[i - 1]["time"])
        if not a or day not in pl.LEVELS:
            continue
        ph, plow = pl.LEVELS[day]
        level = ph if s["side"] == "BUY" else plow
        st = abs(float(s["entry"]) - level) / a
        rows["control"].append(st)
        side, _age = trend_state(prep, M15[i]["time"])
        rows["gated" if side == s["side"] else "cut"].append(st)
    out = {}
    for k, v in rows.items():
        v.sort()
        out[k] = {"n": len(v),
                  "mean_stretch_atr": round(sum(v) / len(v), 3) if v else None,
                  "median_stretch_atr": round(v[len(v) // 2], 3) if v else None}
    return out


def main():
    probe = {"h1": gate_probe(H1P), "h4": gate_probe(H4P)}
    print("HTF gate probe:", json.dumps(probe), flush=True)
    ledger = {"_probe": probe,
              "_stretch_probe": {"h1": stretch_probe(H1P),
                                 "h4": stretch_probe(H4P)},
              "_time_stop_bars": lh.live_time_stop_bars(M15)}
    arms = [name for name, _fn in ARMS]
    for name, fn in ARMS:
        ledger[name] = lh.run_arm(M15, wrap(fn))
        lh.print_table(ledger, [name], label=f"{name} (b71 harness, cached)")
    complaints = lh.summarize(ledger, arms)
    ledger["_honesty_complaints"] = complaints
    print("\n=== b71 honesty summary ===")
    for c in complaints or ["no complaints"]:
        print("!", c)
    p = os.path.join(_ROOT, "data", "backtest", "b68m_htf_pdh_lab.json")
    json.dump(ledger, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
