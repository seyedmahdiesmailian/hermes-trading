#!/usr/bin/env python3
"""b68k-confirm — day-extension x same-day PD-break (REVERSED pairing) vs the
CURRENT live funnel on FRESH data.

b68 merit bar (round-1 METHOD RULE + round-4 update): an arm must beat the
funnel on BOTH the cached set AND one fresh fetch, and the confirm must
re-measure the funnel on the SAME fresh bars.

Cached result (b68k_pdh_dayext_lab): the same-day-break gate LIFTS its own
control (dayext_a10 ladder 0.327 -> agree 0.369, n 407 -> 222) and the cut is
informative — the DISAGREE arm (the day extended one way, the last PD break
went the other) is the worst of the family at 0.151, below both the control
and the not-yet-broken arm (0.336). So the oracle separates real commitment
from a day that has run without breaking a level. But the lift is small and
the level stays far below the funnel's 0.854 cached bar.

This confirm settles:
  (1) the fresh numbers for control + agree + disagree + notyet with the
      funnel re-measured on the SAME bars, and
  (2) the ADDITIVE-LANE question for b70: funnel-first, gated dayext only on
      bars the funnel leaves empty. Round 6's ungated dayext lane was the
      weakest measured (0.410, dd 17.6) because the arm fires 2.5x more often
      than the funnel; the gate cuts it to ~55% of that frequency, so the
      question is whether cutting frequency buys enough marginal quality.

b73 rule (b): the stretch probe (entry distance from the broken level, in
ATR) is standard on every combination confirm. Here it asks a new question:
the gate demands the level already broke, so how far has price travelled from
that level by the time the day-extension trigger prints? If the agree entries
are heavily stretched, the +0.04R lift is being paid for in geometry.

The funnel signal is evaluated ONCE into a dict and reused by the funnel arm
and the lane arm (same bars, same context windows — deterministic), so the
two funnel-consuming arms cannot drift apart by construction.
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
from scripts import b68k_pdh_dayext_lab as lab     # noqa: E402

TF = "M15"
COUNT = 6000


def stretch_probe():
    """Mean |entry - broken level| / ATR at signal time for control vs agree
    vs disagree (b73 standard probe). Only signals whose oracle fired carry a
    level, so control's stretch is measured over its gated subset for a like
    - like comparison (documented in the shipped JSON)."""
    m15 = lab.M15
    rows = {"agree": [], "disagree": []}
    for i in range(30, len(m15)):
        s = lab.geo(i)
        if not s:
            continue
        info = lab.pd_break_info(i)
        if info is None:
            continue
        side, level = info
        a = lab.dl.atr(i - 1)
        if not a:
            continue
        d = abs(float(s["entry"]) - float(level)) / a
        if side == s["side"]:
            rows["agree"].append(d)
        else:
            rows["disagree"].append(d)
    out = {}
    for k, v in rows.items():
        v.sort()
        out[k] = {"n": len(v),
                  "mean_stretch_atr": round(sum(v) / len(v), 3) if v else None,
                  "median_stretch_atr": v[len(v) // 2] if v else None,
                  "p95_stretch_atr": v[int(0.95 * (len(v) - 1))] if v else None}
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

    # ONE funnel evaluation pass, reused by the funnel arm and the lane.
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
            ("dayext_a10_control", wrap(lambda i: lab.geo(i))),
            ("dayext_pdbreak_agree", wrap(lab.combo)),
            ("dayext_pdbreak_dis", wrap(lab.opposed)),
            ("dayext_pdbreak_not", wrap(lab.notbroken)),
            ("lane_funnel_then_agree", make_lane(wrap(lab.combo)))]
    out = {"_time_stop_bars": lh.live_time_stop_bars(m15),
           "_stretch_probe": stretch_probe(),
           "_gate_probe": lab.gate_probe()}
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
    p = os.path.join(_ROOT, "data", "backtest", "b68k_pdh_dayext_confirm.json")
    json.dump(out, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
