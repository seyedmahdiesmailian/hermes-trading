#!/usr/bin/env python3
"""b68i-confirm — PDH x NR7-squeeze combo vs the CURRENT live funnel on FRESH.

b68 merit bar (round-1 METHOD RULE + round-4 update): an arm must beat the
funnel on BOTH the cached set AND one fresh fetch, and the confirm must
re-measure the funnel on the SAME fresh bars. Cached result (b68i_squeeze_lab):
the squeeze gate LOWERS its own control — pdh_w10 0.627 (n=54) ->
pdh_squeeze_agree_k6 0.406 (n=21) / k8 0.364 (n=26) — the opposite sign from
round 7's dayext gate. This confirm settles whether that is a small-sample
artefact of the cached 54-trade control or a real property, and feeds b70:

  (1) fresh exp_R for control + both gated variants (funnel re-measured on
      the SAME bars),
  (2) the ADDITIVE-LANE comparison b70 has been asking for: on identical
      fresh bars, funnel-only vs funnel+raw-pdh lane vs funnel+gated-pdh
      lane — the first lane probe that compares a gated variant against its
      own ungated control in the SAME run (rounds 4/7 measured their lanes in
      different runs), so the contention delta is same-bars same-harness,
  (3) a MECHANISM probe: mean entry-stretch (entry minus the broken level,
      in ATR) for gated vs control signals. The pre-confirm theory: a squeeze
      that has ALREADY resolved has consumed part of the move before the
      day-level break confirms, so the gated entry is stretched away from the
      level-anchored stop -> bigger risk -> TP 2R sits further out and the
      ladder's partial never pays for it. If the stretch is real, the gate's
      damage is geometric, not informational.

The lab module closes over module-level M15/IDX and repoints both ingredient
modules, so rebind() points everything (including rebuilt day LEVELS) at the
fresh bars.
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
from scripts import b68i_squeeze_pdh_lab as lab    # noqa: E402

TF = "M15"
COUNT = 6000


def stretch_probe():
    """Mean |entry - broken level| / ATR at signal time, control vs gated k6.
    Mechanism check for the cached gate regression (see module docstring)."""
    import datetime
    m15 = lab.M15
    rows = {"control": [], "gated_k6": []}
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
        if lab.squeeze_dir(i, lab.K6) == s["side"]:
            rows["gated_k6"].append(abs(e - level) / a)
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

    def funnel(row):
        i = idx_of.get(row.get("time"))
        if i is None:
            return None
        bt = row.get("time", 0)
        hw = [r for r in h1 if r.get("time", 0) <= bt][-80:]
        h4w = [r for r in h4 if r.get("time", 0) <= bt][-80:]
        mw = m15[max(0, i - 120):i + 1]
        return strategy_signal(row, hw, h4w, i, m15_window=mw)

    def make_lane(arm_fn):
        """Additive-lane probe: funnel first, arm only on bars the funnel
        leaves empty, one position at a time (b70's capacity model)."""
        def lane_fn(row):
            return funnel(row) or arm_fn(row)
        return lane_fn

    arms = [("CURRENT_FUNNEL", funnel),
            ("pdh_w10_control", wrap(lambda i: lab.pl.pdh_break(i, lab.STOP_ATR))),
            ("pdh_squeeze_agree_k6", wrap(lambda i: lab.combo(i, lab.K6))),
            ("lane_funnel_then_pdh", make_lane(wrap(lambda i: lab.pl.pdh_break(i, lab.STOP_ATR)))),
            ("lane_funnel_then_gated", make_lane(wrap(lambda i: lab.combo(i, lab.K6))))]
    out = {"_time_stop_bars": lh.live_time_stop_bars(m15),
           "_stretch_probe": stretch_probe(),
           "_gate_probe": {"k6": lab.gate_probe(lab.K6)}}
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
    p = os.path.join(_ROOT, "data", "backtest", "b68i_squeeze_pdh_confirm.json")
    json.dump(out, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
