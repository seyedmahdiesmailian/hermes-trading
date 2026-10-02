#!/usr/bin/env python3
"""b61: EXIT-GEOMETRY EXPECTANCY AUDIT.

Live math (broker deals, 22 closed positions): WR 73% but payoff 0.41
(avg win +23.6$ / avg loss -58.0$) -> net +29$ over 13 days. The user's
complaint is arithmetically correct: one stop erases 2-3 wins.

b60 rebuilt the live ladder as [midpoint, final] and b55 closes 100% at
TP1, so every win is capped at ~0.5-0.75R while every loss is a full -1R.
That is a structurally thin edge: breakeven WR = 1/(1+payoff).

This sweep measures expectancy IN R (not dollars) across TP1 placements
and exit policies, on identical data, so the choice is evidence-based.
"""
import json
import os
import sys
import statistics

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from env_loader import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from bridge_client import BridgeClient
from engines.backtest_real import run_backtest as run_bt
from engines.trade_management import _partial_close_fraction

COUNT = 6500
TIMEFRAME = "M5"


def live_ladder(trade):
    return _partial_close_fraction(trade)


def no_partial(trade):
    return 0.0, "hold_to_final"


def half_partial(trade):
    return 0.5, "half_at_tp1"


ARMS = [
    # name, kwargs
    ("b60_tp1_0.50_full", dict(partial_share_fn=live_ladder, trail_after_partial=0.5, tp1_position=0.50)),
    ("tp1_0.75_full",     dict(partial_share_fn=live_ladder, trail_after_partial=0.5, tp1_position=0.75)),
    ("tp1_1.00_full",     dict(partial_share_fn=live_ladder, trail_after_partial=0.5, tp1_position=1.00)),
    ("hold_to_final",     dict(partial_share_fn=no_partial, trail_after_partial=0.0, tp1_position=0.50)),
    ("tp1_0.50_half",     dict(partial_share_fn=half_partial, trail_after_partial=0.5, tp1_position=0.50)),
    ("tp1_0.75_half",     dict(partial_share_fn=half_partial, trail_after_partial=0.5, tp1_position=0.75)),
]


def r_stats(res):
    """Convert the dollar trade_log into R-multiples using each trade's own risk."""
    trades = res.get("trade_log", []) or []
    rs = []
    for t in trades:
        risk = abs(float(t.get("entry", 0)) - float(t.get("orig_sl") or 0))
        if risk <= 0:
            continue
        rs.append(float(t.get("pnl", 0.0)) / risk)  # both are per-lot $ -> R multiple
    if not rs:
        return {}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    avg_w = statistics.mean(wins) if wins else 0.0
    avg_l = abs(statistics.mean(losses)) if losses else 0.001
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return {
        "n": len(rs),
        "wr": round(100 * len(wins) / len(rs), 1),
        "avg_win_R": round(avg_w, 2),
        "avg_loss_R": round(-avg_l, 2),
        "payoff": round(avg_w / avg_l, 2),
        "expectancy_R": round(statistics.mean(rs), 3),
        "total_R": round(sum(rs), 1),
        "maxDD_R": round(-dd, 1),
    }


def main():
    bridge = BridgeClient()
    from engines.backtest_real import fetch_all_ohlc
    # one shared dataset so every arm is byte-identical
    data = {
        TIMEFRAME: fetch_all_ohlc(bridge, "XAUUSD", TIMEFRAME, COUNT),
        "H1": fetch_all_ohlc(bridge, "XAUUSD", "H1", COUNT),
        "H4": fetch_all_ohlc(bridge, "XAUUSD", "H4", COUNT),
    }
    print("data rows:", {k: len(v) for k, v in data.items()}, flush=True)
    out = {}
    print(f"{'arm':22s} {'net$':>9s} {'n':>4s} {'WR%':>6s} {'avgW_R':>7s} {'avgL_R':>7s} "
          f"{'payoff':>7s} {'exp_R':>7s} {'totR':>7s} {'ddR':>6s}")
    for name, kw in ARMS:
        res = run_bt(bridge, count=COUNT, timeframe=TIMEFRAME, data=data, **kw)
        s = r_stats(res)
        s["net_pnl"] = res.get("net_pnl")
        out[name] = s
        print(f"{name:22s} {s.get('net_pnl', 0):9.2f} {s.get('n', 0):4d} {s.get('wr', 0):6.1f} "
              f"{s.get('avg_win_R', 0):7.2f} {s.get('avg_loss_R', 0):7.2f} {s.get('payoff', 0):7.2f} "
              f"{s.get('expectancy_R', 0):7.3f} {s.get('total_R', 0):7.1f} {s.get('maxDD_R', 0):6.1f}", flush=True)
    with open(os.path.join(os.path.dirname(__file__), "..", "data", "backtest",
              "b61_exit_geometry.json"), "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
