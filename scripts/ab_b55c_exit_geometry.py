#!/usr/bin/env python3
"""b55c: EXIT-GEOMETRY sweep WITH TRAIL PARITY (b55b's lesson).

b55b showed a monotonic "close everything at TP1" win — but the backtest had
NO trailing stop while live trails after TP1, so the residual runner looked
worse in sim than it is in reality. This run re-tests with the live trail
mirrored (SL follows at trail_mult x original risk after the partial).

Arms (all grade-aware ladder fn from live _partial_close_fraction):
  live_07_trail05   ladder + trail 0.5R   <- candidate new default
  live_07_trail10   ladder + trail 1.0R
  live_07_notrail   ladder, no trail      <- current live behaviour in sim
  flat_100_trail05  close 100% at TP1 + trail (kill the runner entirely)
  flat_085_trail05  85% at TP1 + trail
Reported per arm: net, WR, maxDD, TP1-hit rate, runner contribution.
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


def ladder_fn(scale):
    def fn(trade):
        share, _reason = _partial_close_fraction(trade)
        return min(1.0, share * scale)
    return fn


def flat_fn(share):
    return lambda trade: share


ARMS = [
    ("live_07_notrail", dict(partial_share_fn=ladder_fn(1.0), trail_after_partial=0.0)),
    ("live_07_trail05", dict(partial_share_fn=ladder_fn(1.0), trail_after_partial=0.5)),
    ("live_07_trail10", dict(partial_share_fn=ladder_fn(1.0), trail_after_partial=1.0)),
    ("flat_085_trail05", dict(partial_share_fn=flat_fn(0.85), trail_after_partial=0.5)),
    ("flat_100_trail05", dict(partial_share_fn=flat_fn(1.0), trail_after_partial=0.5)),
]


def main():
    bridge = BridgeClient()
    out = {}
    for name, kw in ARMS:
        res = run_real_backtest(bridge, count=COUNT, timeframe=TIMEFRAME, **kw)
        trades = res.get("trade_log", [])
        exits = {}
        for t in trades:
            exits[t.get("exit_reason")] = exits.get(t.get("exit_reason"), 0) + 1
        s = {k: res.get(k) for k in ("net_pnl", "win_rate", "trades")}
        eq = peak = dd = 0.0
        for t in trades:
            eq += t.get("pnl", 0.0)
            peak = max(peak, eq)
            dd = min(dd, eq - peak)
        s["max_dd"] = round(-dd, 2)
        s["exits"] = exits
        out[name] = s
        print(f"{name:18s} net={s['net_pnl']:8.2f}  WR={100*s['win_rate']:5.1f}%  "
              f"trades={s['trades']}  maxDD={s['max_dd']}  exits={exits}",
              flush=True)
    with open(os.path.join(os.path.dirname(__file__), "..",
              "data", "backtest", "ab_b55c_exit_geometry.json"), "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
