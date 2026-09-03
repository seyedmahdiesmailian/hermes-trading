#!/usr/bin/env python3
"""b68h-confirm — NR7xdayext combo vs the CURRENT live funnel on FRESH data.

b68 merit bar (round-1 METHOD RULE + round-4 update): an arm must beat the
funnel on BOTH the cached set AND one fresh fetch, and the confirm must
re-measure the funnel on the SAME fresh bars (the funnel's cached 0.854 is
dataset-specific — on fresh 6000 M15 it scores ~0.58).

Cached ladder (b68h_combo_lab): nr7_dayext_agree +0.622R (n=68) vs its own
control nr7_w10 +0.598R (n=218) vs funnel +0.854R — the day-extension gate
lifts per-trade R by +0.024R at n=68 (noise band) while cutting the sample by
69%, and both lose the cached bar, so the arm cannot be a replacement. This
confirm answers the two open questions:

  (1) the fresh number for the combo (does the gate hold up out of sample?),
  (2) the ADDITIVE-LANE question for b70: funnel-first, combo only on bars
      the funnel leaves empty. The lane is what nr7 (0.620) and pdh (0.559)
      are queued on; a GATED nr7 fires ~3x less often, so its slot-contention
      (round-6 sub-question: lane quality anti-correlates with frequency)
      should be much lower — this is the first lane probe that tests the
      contention finding directly.

FIRST confirm round run through the b71 harness (lh.run_arm): every arm gets
plain / ladder / ladder_ts (live b60 ladder + live 36h time exit derived from
MAX_POSITION_AGE_HOURS x bar spacing) with hold columns, so a swing-shaped
fresh-set arm cannot print an intraday headline again.

The lab module closes over module-level M15/IDX (and repoints the two
ingredient modules), so rebind() points everything at the fresh bars.
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
from bridge_client import BridgeClient            # noqa: E402
from engines import lab_harness as lh             # noqa: E402  (b71 harness)
from engines.backtest import backtest_ohlc        # noqa: E402
from engines.backtest_real import fetch_all_ohlc, strategy_signal  # noqa: E402
from scripts import b68h_combo_lab as lab         # noqa: E402

TF = "M15"
COUNT = 6000


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

    def lane(row):
        """Additive-lane probe: funnel first, combo only on bars the funnel
        leaves empty, one position at a time. Feeds b70's capacity question
        with the GATED variant (contention test, round-6 sub-question)."""
        return funnel(row) or wrap(lambda i: lab.combo(i))(row)

    arms = [("CURRENT_FUNNEL", funnel),
            ("nr7_w10_control", wrap(lambda i: lab.nl.nr7_break(i, wide=True))),
            ("nr7_dayext_agree", wrap(lambda i: lab.combo(i))),
            ("lane_funnel_then_combo", lane)]
    out = {"_time_stop_bars": lh.live_time_stop_bars(m15)}
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
    p = os.path.join(_ROOT, "data", "backtest", "b68h_combo_confirm.json")
    json.dump(out, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
