#!/usr/bin/env python3
"""b66 — 2D exit grid on the WINNING arm (trail .3): TP1 step x partial share.

b65 proved trail_after_partial 0.45 -> 0.30 (4/4 slices). b65 also showed
TP1=0.75R raised MEAN R but cut trade count and total dollars.
So the open question: with the tight trail locked in, does a different
TP1 step / partial share harvest MORE total R?

Metric = TOTAL R (dollar-weighted), mean R as tiebreak. Arms must beat
the incumbent on BOTH M5 and M15 to be considered.
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

def arm(tp1, share, trail=0.30):
    return dict(partial_share_fn=lambda t: _partial_close_fraction(t),
                trail_after_partial=trail, tp1_position=tp1,
                partial_tp1_share=share, breakeven_at_r=0.0)

GRID = [("incumbent TP1=.50/50%/trail.3", 0.50, 0.50),
        ("TP1=.40 50%", 0.40, 0.50), ("TP1=.45 50%", 0.45, 0.50),
        ("TP1=.60 50%", 0.60, 0.50), ("TP1=.70 50%", 0.70, 0.50),
        ("TP1=.50 30%", 0.50, 0.30), ("TP1=.50 70%", 0.50, 0.70),
        ("TP1=.40 70%", 0.40, 0.70), ("TP1=.45 30%", 0.45, 0.30),
        ("TP1=.60 30%", 0.60, 0.30)]

def score(res):
    rs = []
    for t in res["trade_log"]:
        risk = abs(t["entry"] - t["orig_sl"])
        if risk > 0:
            rs.append(t["pnl"] / risk)
    if not rs:
        return dict(n=0, mean_r=0.0, total_r=0.0, wr=0.0)
    w = [x for x in rs if x > 0]
    return dict(n=len(rs), mean_r=round(statistics.mean(rs), 3),
                total_r=round(sum(rs), 1), wr=round(100.0*len(w)/len(rs), 1))

def run_window(rows, data, lo, hi):
    sub = rows[lo:hi]
    idx_of = {r["time"]: n for n, r in enumerate(sub)}
    def signal_fn(row):
        i = idx_of.get(row.get("time"))
        if i is None:
            return None
        bt = row.get("time", 0)
        hw = [r for r in data["H1"] if r.get("time", 0) <= bt][-80:]
        h4w = [r for r in data["H4"] if r.get("time", 0) <= bt][-80:]
        return strategy_signal(row, hw, h4w, i,
                               m15_window=sub[max(0, i - 120):i + 1])
    out = {}
    for name, tp1, share in GRID:
        res = backtest_ohlc(sub, signal_fn, spread=SPREAD, **arm(tp1, share))
        out[name] = score(res)
    return out

def main():
    bridge = BridgeClient()
    report = {}
    for tf, count in (("M5", 6000), ("M15", 6000)):
        rows = fetch_all_ohlc(bridge, "XAUUSD", tf, count)
        data = {tf: rows,
                "H1": fetch_all_ohlc(bridge, "XAUUSD", "H1", count),
                "H4": fetch_all_ohlc(bridge, "XAUUSD", "H4", count)}
        n = len(rows)
        full = run_window(rows, data, 0, n)
        old = run_window(rows, data, 0, n // 2)
        new = run_window(rows, data, n // 2, n)
        report[tf] = dict(full=full, old_half=old, new_half=new)
        print(f"\n════════ {tf} full ({n} bars) ════════", flush=True)
        base = full["incumbent TP1=.50/50%/trail.3"]["total_r"]
        for name, s in sorted(full.items(), key=lambda kv: -kv[1]["total_r"]):
            d = s["total_r"] - base
            print(f"  {name:34s} n={s['n']:3d} tot={s['total_r']:7.1f}R "
                  f"({d:+6.1f}) mean={s['mean_r']:+.3f} wr={s['wr']:.0f}%")
        print(f"\n──── {tf} half-split (old vs new) ────", flush=True)
        for name, _tp, _sh in GRID:
            o, w = old[name]["total_r"], new[name]["total_r"]
            print(f"  {name:34s} old={o:7.1f}R new={w:7.1f}R")
    with open(os.path.join(_ROOT, "data/backtest/b66_exit_grid.json"), "w") as f:
        json.dump(report, f, indent=1)
    print("\nwrote data/backtest/b66_exit_grid.json", flush=True)

if __name__ == "__main__":
    main()
