#!/usr/bin/env python3
"""b66b — the SHARE dimension, tested correctly this time.

b66 bug found in its own output: TP1=.50 at 30/50/70% gave IDENTICAL totals,
because the arms kept partial_share_fn (grade-based, b54c) which OVERRIDES the
flat partial_tp1_share. So b66 only ever tested TP1. This script varies the
share through the fn itself: flat 0.30 / 0.50 / 0.70 and the live grade fn,
with TP1=.50 and the winning trail=.30 locked.
Metric: TOTAL R, must win on BOTH M5 and M15 full windows.
"""
import sys, os, json, statistics
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from bridge_client import BridgeClient
from engines.backtest import backtest_ohlc
from engines.backtest_real import fetch_all_ohlc, strategy_signal
from engines.trade_management import _partial_close_fraction

SPREAD = 0.20
ARMS = [("live grade-fn share", lambda t: _partial_close_fraction(t)),
        ("flat 30%", lambda t: 0.30), ("flat 50%", lambda t: 0.50),
        ("flat 70%", lambda t: 0.70)]

def score(res):
    rs = [t["pnl"]/abs(t["entry"]-t["orig_sl"]) for t in res["trade_log"]
          if abs(t["entry"]-t["orig_sl"]) > 0]
    if not rs: return dict(n=0, mean_r=0.0, total_r=0.0, wr=0.0)
    w = [x for x in rs if x > 0]
    return dict(n=len(rs), mean_r=round(statistics.mean(rs),3),
                total_r=round(sum(rs),1), wr=round(100.0*len(w)/len(rs),1))

def run(rows, data, lo, hi, fn):
    sub = rows[lo:hi]
    idx = {r["time"]: n for n, r in enumerate(sub)}
    def signal_fn(row):
        i = idx.get(row.get("time"))
        if i is None: return None
        bt = row.get("time", 0)
        hw = [r for r in data["H1"] if r.get("time",0) <= bt][-80:]
        h4w = [r for r in data["H4"] if r.get("time",0) <= bt][-80:]
        return strategy_signal(row, hw, h4w, i, m15_window=sub[max(0,i-120):i+1])
    return score(backtest_ohlc(sub, signal_fn, spread=SPREAD,
                partial_share_fn=fn, trail_after_partial=0.30,
                tp1_position=0.50, partial_tp1_share=0.5, breakeven_at_r=0.0))

def main():
    bridge = BridgeClient(); out = {}
    for tf in ("M5", "M15"):
        rows = fetch_all_ohlc(bridge, "XAUUSD", tf, 6000)
        data = {tf: rows,
                "H1": fetch_all_ohlc(bridge, "XAUUSD", "H1", 6000),
                "H4": fetch_all_ohlc(bridge, "XAUUSD", "H4", 6000)}
        n = len(rows)
        out[tf] = {}
        print(f"\n════ {tf} ({n} bars) ════", flush=True)
        base = None
        for name, fn in ARMS:
            full = run(rows, data, 0, n, fn)
            old = run(rows, data, 0, n//2, fn)
            new = run(rows, data, n//2, n, fn)
            out[tf][name] = dict(full=full, old=old, new=new)
            if base is None: base = full["total_r"]
            print(f"  {name:20s} n={full['n']:3d} tot={full['total_r']:7.1f}R "
                  f"({full['total_r']-base:+6.1f}) mean={full['mean_r']:+.3f} "
                  f"wr={full['wr']:.0f}% | old={old['total_r']:.1f} new={new['total_r']:.1f}",
                  flush=True)
    json.dump(out, open(os.path.join(_ROOT,"data/backtest/b66b_share.json"),"w"), indent=1)
    print("\nwrote data/backtest/b66b_share.json", flush=True)

if __name__ == "__main__":
    main()
