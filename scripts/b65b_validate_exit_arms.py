#!/usr/bin/env python3
"""b65b — out-of-sample validation of arms that beat live ladder in b65.

Candidates (b65, 6000 M5 bars): trail 0.3 (+189.1R vs +178.5R baseline) and
TP1=0.75R (mean +0.739R but fewer trades). Validate on a DIFFERENT dataset:
6000 M15 bars (~45 more days back, minimal overlap). An arm must win on
BOTH datasets to integrate.
"""
import sys, os, json, statistics
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing -> local fallback
load_dotenv(os.path.join(_ROOT, '.env'))
from bridge_client import BridgeClient
from engines.backtest import backtest_ohlc
from engines.backtest_real import fetch_all_ohlc, strategy_signal
from engines.trade_management import _partial_close_fraction

TF, COUNT, SPREAD = "M15", 6000, 0.20

LIVE = dict(partial_share_fn=lambda t: _partial_close_fraction(t),
            trail_after_partial=0.5, tp1_position=0.50,
            partial_tp1_share=0.5, breakeven_at_r=0.0)
ARMS = [
    ("live ladder trail.5", LIVE),
    ("trail .3", dict(LIVE, trail_after_partial=0.3)),
    ("TP1=.75R", dict(LIVE, tp1_position=0.75)),
    ("TP1=.75R + trail.3", dict(LIVE, tp1_position=0.75, trail_after_partial=0.3)),
]

def score(res):
    rs = [t["pnl"] / abs(t["entry"] - t["orig_sl"]) for t in res["trade_log"]
          if abs(t["entry"] - t["orig_sl"]) > 0]
    if not rs:
        return dict(n=0, mean_r=0.0, total_r=0.0)
    return dict(n=len(rs), mean_r=round(statistics.mean(rs), 3),
                total_r=round(sum(rs), 1))

def main():
    bridge = BridgeClient()
    data = {TF: fetch_all_ohlc(bridge, "XAUUSD", TF, COUNT),
            "H1": fetch_all_ohlc(bridge, "XAUUSD", "H1", COUNT),
            "H4": fetch_all_ohlc(bridge, "XAUUSD", "H4", COUNT)}
    rows = data[TF]
    print("bars:", len(rows), TF, flush=True)
    idx_of = {r["time"]: n for n, r in enumerate(rows)}

    def signal_fn(row):
        i = idx_of.get(row.get("time"))
        if i is None:
            return None
        bt = row.get("time", 0)
        hw = [r for r in data["H1"] if r.get("time", 0) <= bt][-80:]
        h4w = [r for r in data["H4"] if r.get("time", 0) <= bt][-80:]
        return strategy_signal(row, hw, h4w, i,
                               m15_window=rows[max(0, i - 120):i + 1])

    out = {}
    for name, lad in ARMS:
        s = score(backtest_ohlc(rows, signal_fn, spread=SPREAD, **lad))
        out[name] = s
        print(f"{name:22s} n={s['n']:3d} mean={s['mean_r']:+.3f}R total={s['total_r']:+.1f}R", flush=True)
    json.dump(out, open("data/backtest/b65b_exit_m15.json", "w"), indent=1)

if __name__ == "__main__":
    main()
