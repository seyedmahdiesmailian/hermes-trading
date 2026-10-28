#!/usr/bin/env python3
"""b57: TIME-STOP sweep on top of the b55 default (100% at TP1, trail parity).

Under the one-position gate a trade that sits between entry and TP1 for hours
blocks every new setup — pure opportunity cost. Sweep: force-close at bar
close if TP1 was not reached within N bars.
Arms: N in {0 (off), 12 (1h), 24 (2h), 48 (4h)} on 6500 M5 bars.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from env_loader import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from bridge_client import BridgeClient
from engines.backtest_real import run_backtest as run_real_backtest
from engines.trade_management import _partial_close_fraction

COUNT = 6500
TIMEFRAME = "M5"


def main():
    bridge = BridgeClient()
    out = {}
    base_eq = None
    for ts in (0, 12, 24, 48):
        res = run_real_backtest(bridge, count=COUNT, timeframe=TIMEFRAME,
                                partial_share_fn=_partial_close_fraction,
                                trail_after_partial=0.5,
                                time_stop_bars=ts)
        trades = res.get("trade_log", [])
        eq = peak = dd = 0.0
        for t in trades:
            eq += t.get("pnl", 0.0)
            peak = max(peak, eq)
            dd = min(dd, eq - peak)
        exits = {}
        for t in trades:
            exits[t.get("exit_reason")] = exits.get(t.get("exit_reason"), 0) + 1
        s = {k: res.get(k) for k in ("net_pnl", "win_rate", "trades")}
        s["max_dd"] = round(-dd, 2)
        s["exits"] = exits
        out[f"ts_{ts}"] = s
        if ts == 0:
            base_eq = s["net_pnl"]
        delta = "" if ts == 0 else f"  delta={s['net_pnl'] - base_eq:+8.2f}"
        print(f"ts={ts:3d}  net={s['net_pnl']:8.2f}  WR={100*s['win_rate']:5.1f}%  "
              f"trades={s['trades']}  maxDD={s['max_dd']}{delta}  exits={exits}", flush=True)
    with open(os.path.join(os.path.dirname(__file__), "..",
              "data", "backtest", "ab_b57_timestop.json"), "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
