#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 13 — the H4-trend STATE as a GENERAL gate:
W3 replication of the round-12 champion + a candidate never measured before
(gating the FUNNEL's own entries on the H4 state).

Round 12 (b68m) left the loop with its first thrice-qualified arm: pdh_w10
geometry gated on the H4-trend state beat the funnel AND its own control on
BOTH independent windows and kept agree > disagree on both. But b74 is
explicit: replication on two windows earns a THIRD DRAW, not a wiring
proposal. This round spends that draw: W3 (2025-10-08 -> 2026-01-12, zero
overlap with cached/W1/W2, asserted in the windows ledger) re-measures the
exact round-12 arms on fresh bars.

The second question is the one round 12 could not answer: the H4 gate was
only ever applied to PDH breakouts. The funnel itself consumes H1/H4 context
inside build_plan_from_context, but it never checks the EMA50 STATE — a
funnel BUY in a confirmed H4 downtrend is a real, executed possibility. If
the state oracle carries information for pdh entries, does it carry any for
the funnel's? New arms: funnel_h4t_agree (funnel signal AND state agrees)
and funnel_h4t_disagree (what such a gate would cut from the live funnel).
This is measurement only — wiring anything would need its own round and the
full b74 protocol; no live file is touched here.

Discipline carried from rounds 11-12 (b76/b74/b72):
- every arm is compared against the funnel re-measured on the SAME bars
  (round-4 rule), on legs with ASSERTED zero overlap (b76);
- the cached leg is included for continuity and LABELLED in-sample;
- gate_probe (anti-vacuity) and state-age (b75 rule-6 for a STATE oracle)
  ship for the funnel-signal population, not just the pdh one;
- ladder_ts exp_R AND dd_R are quoted together (b72 rule 5);
- replication now means beating the funnel on ALL THREE independent windows.

Read-only research code: nothing here is imported by the live trading path.
"""
import os
import sys
import json
import bisect

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from engines import lab_harness as lh              # noqa: E402
from engines.backtest_real import strategy_signal  # noqa: E402
from scripts import b68l_windows as wl             # noqa: E402
from scripts import b68m_htf_pdh_lab as mm         # noqa: E402

OUT = os.path.join(_ROOT, "data", "backtest", "b68n_funnel_gate_w3.json")
WINDOWS = ("W1", "W2", "W3")
ARMS = ("CURRENT_FUNNEL", "pdh_w10_control", "pdh_h4t_agree",
        "pdh_h4t_disagree", "lane_funnel_then_h4pdh",
        "funnel_h4t_agree", "funnel_h4t_disagree")


def funnel_probe(prep, sigs):
    """Anti-vacuity + state-age for the gate applied to FUNNEL signals
    (b72 rule 2 / b75 rule 6): what share of funnel entries sit in an
    agreeing H4 state, how many the gate would cut, and how old the state
    is where it agrees."""
    n = agree = dis = silent = 0
    ages = []
    for i, s in sigs.items():
        n += 1
        side, age = mm.trend_state(prep, mm.M15[i]["time"])
        if side is None:
            silent += 1
        elif side == s["side"]:
            agree += 1
            ages.append(age)
        else:
            dis += 1
    ages.sort()
    return {"funnel_signals": n, "agree": agree, "disagree": dis,
            "silent": silent,
            "gate_share": round(agree / n, 3) if n else None,
            "cut_share": round(dis / n, 3) if n else None,
            "agree_state_age_median_htf_bars":
                ages[len(ages) // 2] if ages else None,
            "agree_state_age_p25_htf_bars":
                ages[int(0.25 * (len(ages) - 1))] if ages else None}


def measure_window(name, rows):
    m15, h1, h4 = rows["M15"], rows["H1"], rows["H4"]
    mm.rebind(m15, h1, h4)
    idx_of = mm.IDX

    def wrap(fn):
        def w(row):
            i = idx_of.get(row.get("time"))
            return None if i is None else fn(i)
        return w

    h1t = [r.get("time", 0) for r in h1]
    h4t = [r.get("time", 0) for r in h4]
    f_sig = {}
    for i, row in enumerate(m15):
        bt = row.get("time", 0)
        j1 = bisect.bisect_right(h1t, bt)
        j4 = bisect.bisect_right(h4t, bt)
        hw = h1[max(0, j1 - 80):j1]
        h4w = h4[max(0, j4 - 80):j4]
        mw = m15[max(0, i - 120):i + 1]
        s = strategy_signal(row, hw, h4w, i, m15_window=mw)
        if s:
            f_sig[i] = s

    def funnel(row):
        return f_sig.get(idx_of.get(row.get("time"), -1))

    def funnel_gate(row, want):
        s = funnel(row)
        if not s:
            return None
        i = idx_of.get(row.get("time"))
        side, _age = mm.trend_state(mm.H4P, m15[i]["time"])
        if want == "agree":
            return s if side == s["side"] else None
        return s if side is not None and side != s["side"] else None

    def lane_h4(row):
        return funnel(row) or wrap(lambda i: mm.gated(i, mm.H4P))(row)

    arms = [("CURRENT_FUNNEL", funnel),
            ("pdh_w10_control", wrap(lambda i: mm.pl.pdh_break(i, mm.STOP_ATR))),
            ("pdh_h4t_agree", wrap(lambda i: mm.gated(i, mm.H4P))),
            ("pdh_h4t_disagree", wrap(lambda i: mm.cut(i, mm.H4P, "dis"))),
            ("lane_funnel_then_h4pdh", lane_h4),
            ("funnel_h4t_agree", lambda row: funnel_gate(row, "agree")),
            ("funnel_h4t_disagree", lambda row: funnel_gate(row, "dis"))]
    out = {"_time_stop_bars": lh.live_time_stop_bars(m15),
           "_bars": len(m15),
           "_first": int(m15[0]["time"]), "_last": int(m15[-1]["time"]),
           "_overlap_with_cached": sum(
               1 for r in m15 if wl.cached_span()[0] <= int(r["time"])
               <= wl.cached_span()[1])}
    for arm_name, fn in arms:
        out[arm_name] = lh.run_arm(m15, fn)
        lh.print_table(out, [arm_name], label=f"{arm_name} ({name}, b71)")
        print(flush=True)
    out["_probe"] = {"h4_pdh": mm.gate_probe(mm.H4P),
                     "h4_funnel": funnel_probe(mm.H4P, f_sig)}
    out["_honesty_complaints"] = lh.summarize(out, [a for a, _ in arms])
    print(f"=== {name} honesty ===")
    for c in out["_honesty_complaints"] or ["no complaints"]:
        print("!", c)
    return out


def verdict(led, windows=WINDOWS):
    """b74 replication rule, third-draw edition: an arm is replicated only
    if its ladder_ts exp_R beats the funnel's on the SAME bars in EVERY
    window; None (0 trades) and ties never beat."""
    v = {}
    for w in windows:
        win = led[w]
        f = win["CURRENT_FUNNEL"]["ladder_ts"]
        v[w] = {"funnel_exp_R": f["exp_R"], "funnel_n": f["trades"]}
        for arm in ARMS[1:]:
            row = win[arm]["ladder_ts"]
            v[w][arm] = {"exp_R": row["exp_R"], "n": row["trades"],
                         "beats_funnel": (row["exp_R"] is not None
                                          and row["exp_R"] > f["exp_R"])}
    both = {}
    for arm in ARMS[1:]:
        both[arm] = all(bool(v[w][arm]["beats_funnel"]) for w in windows)
    v["replicated_in_all"] = both
    return v


def main():
    wins = wl.load_windows()
    led = {"_note": "round 13: W3 third draw for the round-12 champion + "
                    "H4-state gate applied to the funnel's OWN entries "
                    "(b76: overlap asserted per leg)",
           "_last6000_overlap_with_cached": wins["_last6000_overlap_with_cached"]}
    import json as _j
    cached = _j.load(open(wl.CACHED))
    print("##### cached_3000 #####", flush=True)
    led["cached"] = measure_window("cached_3000", cached)
    for name in WINDOWS:
        print(f"##### {name} #####", flush=True)
        led[name] = measure_window(name, wins[name])
    led["_verdict"] = verdict(led)
    print("=== VERDICT ===")
    print(json.dumps(led["_verdict"], indent=1))
    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
