#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 8 — COMBINATION: PDH/PDL breakout x NR7 squeeze.

Standing loop (b68): each run tests ONE candidate not yet in the lab. Rounds
1-6 screened every classic FAMILY (all rejected as replacements); round 7 ran
the first COMBINATION (nr7 x dayext, b72 playbook) and found the gate lifts
its control but the lane still does not earn a slot. This round is option (a)
again — two rejected families gated on each other — but with the pair the
b70 lane queue cares about most:

  pdh_break_w10 (round 4) — the ONLY arm that ever beat the funnel on fresh
      data (0.640 vs 0.576), lane exp_R 0.559 (diluting);
  nr7 squeeze (round 5) — the strongest standalone arm and the strongest lane
      (0.620 fresh), but fires 4x too often to sit in one slot.

The thesis is the classic "expansion out of compression AT a key level": a
close-confirmed break of the previous trading day's extreme is more likely to
follow through when it emerges from a RECENTLY RESOLVED volatility squeeze —
the most recent NR7 bar (within k bars) whose range already closed through,
in the SAME direction as the day-level break. The squeeze supplies the fuel
(compressed energy releasing), the PD level supplies the location (liquidity
above/below the prior day). Neither ingredient alone survived; the funnel
uses neither (its bias is H1/H4 swing structure + SMC merge — grep shows no
previous-day level and no squeeze state anywhere in engines/).

b72 playbook compliance:
  (1) PURE INTERSECTION — geometry (entry/SL/TP) is pdh_break's, unchanged;
      the squeeze is a direction oracle only, so no new stop geometry can
      reintroduce the b69/round-6 traps;
  (2) ANTI-VACUITY probe ships in _probe: fire counts of each ingredient and
      the agree/disagree split of the gated subset (measured on cached before
      writing this round: k=6 -> 23 agree / 13 disagree, k=8 -> 31 / 15 — a
      real gate, not the same arm twice);
  (3) the UNGATED ingredient (pdh_break_w10) is re-measured as the CONTROL in
      the same run, same harness, same bars, so the gate's delta is honest;
  (4) the confirm ledger's verdict numbers get pinned by a test;
  (5) lane exp_R and dd_R are quoted together.

Arms:
  pdh_w10_control        — round-4 arm, re-measured (control)
  pdh_squeeze_agree_k6   — pdh AND last NR7 (within 6 bars) resolved same way
  pdh_squeeze_agree_k8   — same, window 8

No lookahead: the oracle reads only bars <= i-2 (the NR7 bar j and its
resolution bar t are both strictly before the signal bar i-1); the pdh arm
itself reads only previous completed trading days. Entry is bar i's OPEN.

Measured through the b71 harness (engines/lab_harness.run_arm): plain /
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
from scripts import b68f_nr7_lab as nl         # noqa: E402  (squeeze oracle)

DATA = json.load(open(os.path.join(_ROOT, "data/backtest/ab_aggressive_data.json")))
M15 = DATA["M15"]
IDX = {r["time"]: n for n, r in enumerate(M15)}
# Both ingredient modules close over their own module-level M15/IDX — repoint
# them at THIS dataset so pdh_break and is_nr7 see identical bars.
pl.M15 = nl.M15 = M15
pl.IDX = nl.IDX = IDX

STOP_ATR = 1.0     # round 4's lesson: 0.5 ATR gets wicked out, 1.0 survives
K6, K8 = 6, 8      # squeeze lookback windows (bars) to probe


def build_levels(rows):
    """Previous-trading-day extremes, same rule as b68e (01:00-23:45 UTC day,
    >=40 bars for a real session). Rebuilt on rebind so a fresh fetch never
    trades against stale cached levels."""
    buckets = {}
    for r in rows:
        buckets.setdefault(pl.trading_day(r["time"]), []).append(r)
    days = sorted(buckets)
    levels = {}
    for k in range(1, len(days)):
        prev = buckets[days[k - 1]]
        if len(prev) >= 40:
            levels[days[k]] = (max(x["high"] for x in prev),
                               min(x["low"] for x in prev))
    return levels


def rebind(rows):
    """Point ALL ingredient modules (and this one's IDX) at a new dataset and
    rebuild the day levels from it."""
    global M15, IDX
    M15 = rows
    IDX = {r["time"]: n for n, r in enumerate(rows)}
    pl.M15 = nl.M15 = rows
    pl.IDX = nl.IDX = IDX
    pl.LEVELS = build_levels(rows)


rebind(M15)   # also (re)builds LEVELS from the cached bars


def squeeze_dir(i, k):
    """Direction oracle: the most recent NR7 bar j in [i-1-k, i-2] whose range
    has ALREADY closed through at some bar t in [j+1, i-2] — returns 'BUY' /
    'SELL' / None. Reads only bars <= i-2, so the signal bar (i-1) and the
    entry (i's open) are never consulted. If the newest NR7 never resolved,
    fall through to older ones inside the window (same scan the pre-round
    probe used, so the shipped _probe numbers match the arm exactly)."""
    for j in range(i - 2, max(i - 2 - k, nl.NR - 1) - 1, -1):
        if not nl.is_nr7(j):
            continue
        hi, lo = float(M15[j]["high"]), float(M15[j]["low"])
        for t in range(j + 1, i - 1):
            c = float(M15[t]["close"])
            if c > hi:
                return "BUY"
            if c < lo:
                return "SELL"
    return None


def combo(i, k):
    """pdh_break (wide) AND the recent squeeze resolved the SAME way.
    Pure intersection: the returned dict is pdh_break's, unchanged."""
    s = pl.pdh_break(i, STOP_ATR)
    if not s:
        return None
    if squeeze_dir(i, k) != s["side"]:
        return None
    return s


def wrap(fn):
    def w(row):
        i = IDX.get(row.get("time"))
        return None if i is None else fn(i)
    return w


ARMS = [("pdh_w10_control", lambda i: pl.pdh_break(i, STOP_ATR)),
        ("pdh_squeeze_agree_k6", lambda i: combo(i, K6)),
        ("pdh_squeeze_agree_k8", lambda i: combo(i, K8))]


def gate_probe(k):
    """Anti-vacuity (b72 rule 2): fire counts of each ingredient and the
    agree/disagree split of the gated subset. gate_share ~1 would mean the
    oracle never filters; agree or disagree ~0 would mean the two arms are
    the same arm twice."""
    n = len(M15)
    pdh = resolved = agree = disagree = 0
    for i in range(30, n):
        s = pl.pdh_break(i, STOP_ATR)
        if not s:
            continue
        pdh += 1
        d = squeeze_dir(i, k)
        if d is None:
            continue
        resolved += 1
        if d == s["side"]:
            agree += 1
        else:
            disagree += 1
    return {"pdh_signals": pdh, "squeeze_resolved": resolved,
            "agree": agree, "disagree": disagree,
            "gate_share": round(resolved / pdh, 3) if pdh else None,
            "agree_share_of_gated": round(agree / resolved, 3) if resolved else None}


def main():
    probe = {"k6": gate_probe(K6), "k8": gate_probe(K8)}
    print("squeeze gate probe:", json.dumps(probe), flush=True)
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
    p = os.path.join(_ROOT, "data", "backtest", "b68i_squeeze_pdh_lab.json")
    json.dump(ledger, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
