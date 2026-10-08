#!/usr/bin/env python3
"""b58: which ENTRY cells actually pay? (style x grade breakdown + drop test)

b55 fixed the exit side. b57 killed the time stop. The remaining lever is the
entry: the sim logs style+grade per trade, so break the b55-default equity
curve into cells, find consistent losers, and A/B dropping them (leave-one-out
re-run, because the one-position gate makes trades interdependent).
"""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from env_loader import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from bridge_client import BridgeClient
from engines.backtest_real import run_backtest as run_real_backtest
from engines.trade_management import _partial_close_fraction

COUNT = 6500
TIMEFRAME = "M5"
KW = dict(partial_share_fn=_partial_close_fraction, trail_after_partial=0.5)


def summarize(res):
    trades = res.get("trade_log", [])
    eq = peak = dd = 0.0
    for t in trades:
        eq += t.get("pnl", 0.0)
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return {"net_pnl": res.get("net_pnl"), "win_rate": res.get("win_rate"),
            "trades": res.get("trades"), "max_dd": round(-dd, 2)}


def main():
    bridge = BridgeClient()
    base = run_real_backtest(bridge, count=COUNT, timeframe=TIMEFRAME, **KW)
    trades = base.get("trade_log", [])

    by_style = defaultdict(lambda: [0, 0.0, 0])
    by_grade = defaultdict(lambda: [0, 0.0, 0])
    for t in trades:
        for key, bucket in ((str(t.get("style")), by_style), (str(t.get("grade")), by_grade)):
            bucket[key][0] += 1
            bucket[key][1] += t.get("pnl", 0.0)
            bucket[key][2] += 1 if t.get("pnl", 0) > 0 else 0

    print("── base:", summarize(base), flush=True)
    print("── by style (n, net, wins):", flush=True)
    for k, v in sorted(by_style.items(), key=lambda kv: kv[1][1]):
        print(f"   {k:34s} n={v[0]:4d} net={v[1]:9.2f} wr={100*v[2]/max(v[0],1):5.1f}%", flush=True)
    print("── by grade:", flush=True)
    for k, v in sorted(by_grade.items()):
        print(f"   {k:6s} n={v[0]:4d} net={v[1]:9.2f} wr={100*v[2]/max(v[0],1):5.1f}%", flush=True)

    losers = [k for k, v in by_style.items() if v[0] >= 15 and v[1] < 0]
    print("── candidate losing styles:", losers, flush=True)

    out = {"base": summarize(base),
           "by_style": {k: {"n": v[0], "net": round(v[1], 2), "wins": v[2]}
                        for k, v in by_style.items()},
           "by_grade": {k: {"n": v[0], "net": round(v[1], 2), "wins": v[2]}
                        for k, v in by_grade.items()},
           "drop_tests": {}}
    drop_sets = ([l for l in losers if len(losers) > 1] and [losers] or []) + [[l] for l in losers]
    for lst in drop_sets:
        name = "drop_" + "+".join(lst)
        res = run_real_backtest(bridge, count=COUNT, timeframe=TIMEFRAME,
                                exclude_styles=lst, **KW)
        s = summarize(res)
        s["delta"] = round(s["net_pnl"] - base["net_pnl"], 2)
        out["drop_tests"][name] = s
        print(f"   {name[:50]:50s} net={s['net_pnl']:8.2f} delta={s['delta']:+8.2f} "
              f"trades={s['trades']}", flush=True)

    with open(os.path.join(os.path.dirname(__file__), "..",
              "data", "backtest", "ab_b58_entry_cells.json"), "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
