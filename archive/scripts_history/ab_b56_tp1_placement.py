#!/usr/bin/env python3
"""b56: TP1 placement + time-stop sweep on TOP of the new b55 default.

b55 made TP1 a full exit (100% close at first target, live-parity trail kept
for the runner lane). The remaining free knob on the exit side is WHERE that
first target sits: the sim uses tp1_position (fraction of entry->TP distance)
while live uses the plan's own tp_levels[0]. Sweep it, and test a time-stop
(trades that never hit TP1 within N bars are dead weight — opportunity cost
under the one-position gate).

Arms: tp1_position in {0.35, 0.5 (current), 0.65} x trail 0.5R parity.
Reported: net, WR, trades, maxDD, avg bars-in-trade.
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


def live_ladder(trade):
    return _partial_close_fraction(trade)


ARMS = [
    ("tp1_0.35", dict(partial_share_fn=live_ladder, trail_after_partial=0.5, tp1_position=0.35)),
    ("tp1_0.50", dict(partial_share_fn=live_ladder, trail_after_partial=0.5, tp1_position=0.50)),
    ("tp1_0.65", dict(partial_share_fn=live_ladder, trail_after_partial=0.5, tp1_position=0.65)),
]


def main():
    bridge = BridgeClient()
    out = {}
    for name, kw in ARMS:
        res = run_real_backtest(bridge, count=COUNT, timeframe=TIMEFRAME, **kw)
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
        out[name] = s
        print(f"{name:10s} net={s['net_pnl']:8.2f}  WR={100*s['win_rate']:5.1f}%  "
              f"trades={s['trades']}  maxDD={s['max_dd']}  exits={exits}", flush=True)
    with open(os.path.join(os.path.dirname(__file__), "..",
              "data", "backtest", "ab_b56_tp1_placement.json"), "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
