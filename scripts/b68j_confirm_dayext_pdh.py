#!/usr/bin/env python3
"""b68j-confirm — PDH x day-extension combo vs the CURRENT live funnel on FRESH.

b68 merit bar (round-1 METHOD RULE + round-4 update): an arm must beat the
funnel on BOTH the cached set AND one fresh fetch, and the confirm must
re-measure the funnel on the SAME fresh bars.

Cached result (b68j_dayext_pdh_lab): the day-extension gate LIFTS its control
hard — pdh_w10 0.627 (n=54) -> pdh_dayext_agree 0.924 (n=23) / e25 1.105
(n=19) — the FIRST combination arm ever above the funnel's cached 0.854 bar,
and the complement arm (what the gate drops) is 0.398 (n=34), so the cut is
real selection, not a fluke subset. The agree/disagree split is degenerate by
construction (a PDH break on an extended up-day is directionally automatic),
which is why the lab also ships the complement.

This confirm settles the two questions the cached run cannot answer:

  (1) the fresh numbers for control + both gated variants + the complement
      (funnel re-measured on the SAME bars), and
  (2) the ADDITIVE-LANE question for b70: funnel-first, gated pdh only on
      bars the funnel leaves empty. If the gated arm's fresh exp_R beats the
      funnel's, the lane probe measures whether it can carry extra volume in
      the single slot without diluting per-trade R or DD.

b73 rule (b): the stretch probe (entry distance from the broken level, in
ATR) runs as a STANDARD part of every combination confirm. Here the theory is
inverted vs round 8: the gate DEMANDS stretch from the day open, so if the
gated entries are stretched from the PD level too, the lift came despite the
geometry (bigger risk, wider TP) — a stronger result; if the lift vanishes on
fresh, stretch is the suspect.

The funnel signal is evaluated ONCE into a dict and reused by the funnel arm
and both lane arms (same bars, same context windows — deterministic), so the
three funnel-consuming arms cannot drift apart by construction.
"""
import os
import sys
import json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))   # b65: a BridgeClient consumer owns its env
from bridge_client import BridgeClient             # noqa: E402
from engines import lab_harness as lh              # noqa: E402  (b71 harness)
from engines.backtest_real import fetch_all_ohlc, strategy_signal  # noqa: E402
from scripts import b68j_dayext_pdh_lab as lab     # noqa: E402

TF = "M15"
COUNT = 6000


def stretch_probe(ext):
    """Mean |entry - broken level| / ATR at signal time: control vs gated vs
    the complement (what the gate drops). b73 standard probe."""
    m15 = lab.M15
    rows = {"control": [], "gated": [], "notyet": []}
    for i in range(30, len(m15)):
        s = lab.pl.pdh_break(i, lab.STOP_ATR)
        if not s:
            continue
        a = lab.pl.atr(i - 1)
        day = lab.pl.trading_day(m15[i - 1]["time"])
        if not a or day not in lab.pl.LEVELS:
            continue
        ph, pl_ = lab.pl.LEVELS[day]
        e = float(s["entry"])
        level = ph if s["side"] == "BUY" else pl_
        rows["control"].append(abs(e - level) / a)
        if lab.dayext_dir(i, ext) == s["side"]:
            rows["gated"].append(abs(e - level) / a)
        else:
            rows["notyet"].append(abs(e - level) / a)
    out = {}
    for k, v in rows.items():
        v.sort()
        out[k] = {"n": len(v),
                  "mean_stretch_atr": round(sum(v) / len(v), 3) if v else None,
                  "median_stretch_atr": v[len(v) // 2] if v else None}
    return out


def main():
    bridge = BridgeClient()
    m15 = fetch_all_ohlc(bridge, "XAUUSD", TF, COUNT)
    h1 = fetch_all_ohlc(bridge, "XAUUSD", "H1", COUNT)
    h4 = fetch_all_ohlc(bridge, "XAUUSD", "H4", COUNT)
    print("bars:", len(m15), len(h1), len(h4), flush=True)
    lab.rebind(m15)
    idx_of = lab.IDX

    def wrap(fn):
        def w(row):
            i = idx_of.get(row.get("time"))
            return None if i is None else fn(i)
        return w

    # ONE funnel evaluation pass, reused by the funnel arm and both lanes.
    f_sig = {}
    for i, row in enumerate(m15):
        bt = row.get("time", 0)
        hw = [r for r in h1 if r.get("time", 0) <= bt][-80:]
        h4w = [r for r in h4 if r.get("time", 0) <= bt][-80:]
        mw = m15[max(0, i - 120):i + 1]
        s = strategy_signal(row, hw, h4w, i, m15_window=mw)
        if s:
            f_sig[i] = s

    def funnel(row):
        return f_sig.get(idx_of.get(row.get("time"), -1))

    def make_lane(arm_fn):
        """Additive-lane probe: funnel first, arm only on bars the funnel
        leaves empty, one position at a time (b70's capacity model)."""
        def lane_fn(row):
            return funnel(row) or arm_fn(row)
        return lane_fn

    arms = [("CURRENT_FUNNEL", funnel),
            ("pdh_w10_control", wrap(lambda i: lab.pl.pdh_break(i, lab.STOP_ATR))),
            ("pdh_dayext_agree", wrap(lambda i: lab.combo(i, lab.EXT))),
            ("pdh_dayext_agree_e25", wrap(lambda i: lab.combo(i, lab.EXT25))),
            ("pdh_dayext_notyet", wrap(lambda i: lab.complement(i, lab.EXT))),
            ("lane_funnel_then_gated", make_lane(wrap(lambda i: lab.combo(i, lab.EXT)))),
            ("lane_funnel_then_gated_e25",
             make_lane(wrap(lambda i: lab.combo(i, lab.EXT25))))]
    out = {"_time_stop_bars": lh.live_time_stop_bars(m15),
           "_stretch_probe": stretch_probe(lab.EXT),
           "_gate_probe": {"e15": lab.gate_probe(lab.EXT),
                           "e25": lab.gate_probe(lab.EXT25)}}
    for name, fn in arms:
        row = lh.run_arm(m15, fn)
        out[name] = row
        lh.print_table(out, [name], label=f"{name} (fresh, b71 harness)")
        print(flush=True)
    complaints = lh.summarize(out, [a for a, _ in arms])
    out["_honesty_complaints"] = complaints
    print("=== b71 honesty summary ===")
    for c in complaints or ["no complaints"]:
        print("!", c)
    print("=== stretch probe ===")
    print(json.dumps(out["_stretch_probe"], indent=1))
    print("=== gate probe (fresh) ===")
    print(json.dumps(out["_gate_probe"], indent=1))
    p = os.path.join(_ROOT, "data", "backtest", "b68j_dayext_pdh_confirm.json")
    json.dump(out, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
