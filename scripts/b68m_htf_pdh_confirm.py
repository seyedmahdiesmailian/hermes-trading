#!/usr/bin/env python3
"""b68m-confirm — PDH x HTF-trend combo measured on the INDEPENDENT windows.

b76 discipline (round-11 lesson): no confirm may quote a "fresh" number from
a last-N fetch without proving overlap. This script measures ONLY on the
b68l windows (W1/W2: zero overlap with the cached set and with each other,
asserted + recorded in the windows ledger) plus the cached set for the
round-4 continuity number. The funnel is re-measured on the SAME bars as
every arm (round-4 rule) and the verdict comes from
b68l_confirm_independent-style replication logic: an arm is only
"replicated" if its ladder_ts exp_R beats the funnel's on the SAME bars in
BOTH independent windows.

Arms per window: control (pdh_w10), H1-gated, H4-gated, the H4 disagree cut
(the real-selection check — H1's cut is n=2 noise on cached), and the
additive lane (funnel-first, H4-gated pdh on free bars) for b70.

Read-only: consumes the cached windows JSON (built by scripts/b68l_windows.py
from get_rates history only). Nothing here is imported by the live path.
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

OUT = os.path.join(_ROOT, "data", "backtest", "b68m_htf_pdh_confirm.json")


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

    def lane_h4(row):
        return funnel(row) or wrap(lambda i: mm.gated(i, mm.H4P))(row)

    arms = [("CURRENT_FUNNEL", funnel),
            ("pdh_w10_control", wrap(lambda i: mm.pl.pdh_break(i, mm.STOP_ATR))),
            ("pdh_h1t_agree", wrap(lambda i: mm.gated(i, mm.H1P))),
            ("pdh_h4t_agree", wrap(lambda i: mm.gated(i, mm.H4P))),
            ("pdh_h4t_disagree", wrap(lambda i: mm.cut(i, mm.H4P, "dis"))),
            ("lane_funnel_then_h4pdh", lane_h4)]
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
    out["_probe"] = {"h1": mm.gate_probe(mm.H1P), "h4": mm.gate_probe(mm.H4P)}
    out["_stretch_probe_h4"] = mm.stretch_probe(mm.H4P)
    out["_honesty_complaints"] = lh.summarize(out, [a for a, _ in arms])
    print(f"=== {name} honesty ===")
    for c in out["_honesty_complaints"] or ["no complaints"]:
        print("!", c)
    return out


def verdict(led, windows=("W1", "W2")):
    """Replication rule (b74 seed, same as round 11): an arm must beat the
    funnel's ladder_ts exp_R on the SAME bars in EVERY listed window; a None
    exp_R (0 trades) and ties never beat."""
    v = {}
    for w in windows:
        win = led[w]
        f = win["CURRENT_FUNNEL"]["ladder_ts"]
        v[w] = {"funnel_exp_R": f["exp_R"], "funnel_n": f["trades"]}
        for arm in ("pdh_w10_control", "pdh_h1t_agree", "pdh_h4t_agree",
                    "pdh_h4t_disagree", "lane_funnel_then_h4pdh"):
            row = win[arm]["ladder_ts"]
            v[w][arm] = {"exp_R": row["exp_R"], "n": row["trades"],
                         "beats_funnel": (row["exp_R"] is not None
                                          and row["exp_R"] > f["exp_R"])}
    both = {}
    for arm in v[windows[0]]:
        if arm in ("funnel_exp_R", "funnel_n"):
            continue
        both[arm] = all(bool(v[w][arm]["beats_funnel"]) for w in windows)
    v["replicated_in_both"] = both
    return v


def main():
    wins = wl.load_windows()
    led = {"_note": "round 12: pdh x HTF-trend gate, measured ONLY on the "
                    "b68l independent windows (b76: zero overlap asserted + "
                    "recorded per window in _overlap_with_cached)",
           "_last6000_overlap_with_cached": wins["_last6000_overlap_with_cached"]}
    # cached leg (continuity with the round's lab file)
    print("##### cached_3000 #####", flush=True)
    import json as _j
    cached = _j.load(open(wl.CACHED))
    led["cached"] = measure_window("cached_3000", cached)
    for name in ("W1", "W2"):
        print(f"##### {name} #####", flush=True)
        led[name] = measure_window(name, wins[name])
    led["_verdict"] = verdict(led)
    print("=== VERDICT ===")
    print(json.dumps(led["_verdict"], indent=1))
    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
