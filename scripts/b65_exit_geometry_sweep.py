#!/usr/bin/env python3
"""b65 EXIT-GEOMETRY SWEEP — same entries (live funnel), different exits.

Why: the live journal shows wins avg +$18 vs losses avg -$50 over 33 closed
trades. The exit ladder (b60/b61) was the single biggest improvement so far,
so the exit SHAPE — not the entry — is where the remaining edge lives.

Method: run the EXACT live funnel signal on 6000 fresh M5 bars, then re-run
those same trades through 11 exit arms. Metric: mean R AND total R harvested
(dollar-weighted: a filter/arm that cuts trades must earn its keep).
Only an arm beating the live ladder on BOTH gets integrated.
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

TF, COUNT, SPREAD = "M5", 6000, 0.20

LIVE = dict(partial_share_fn=lambda t: _partial_close_fraction(t),
            trail_after_partial=0.5, tp1_position=0.50,
            partial_tp1_share=0.5, breakeven_at_r=0.0)

ARMS = [
    ("live ladder TP1=.5R/50%/trail.5", LIVE),
    ("no partial TP=1.0R BE@.5", dict(LIVE, partial_tp1_share=0.0, tp1_position=1.0, breakeven_at_r=0.5)),
    ("no partial TP=1.5R BE@1.0", dict(LIVE, partial_tp1_share=0.0, tp1_position=1.5, breakeven_at_r=1.0)),
    ("no partial TP=2.0R BE@1.0", dict(LIVE, partial_tp1_share=0.0, tp1_position=2.0, breakeven_at_r=1.0)),
    ("TP1=.35R take50 trail.5", dict(LIVE, tp1_position=0.35)),
    ("TP1=.75R take50 trail.5", dict(LIVE, tp1_position=0.75)),
    ("TP1=.5R take70 trail.5", dict(LIVE, partial_tp1_share=0.7)),
    ("TP1=.5R take30 trail.5", dict(LIVE, partial_tp1_share=0.3)),
    ("live + tight trail .3", dict(LIVE, trail_after_partial=0.3)),
    ("live + loose trail .8", dict(LIVE, trail_after_partial=0.8)),
    ("live + BE@.3 earlier", dict(LIVE, breakeven_at_r=0.3)),
    ("live + time stop 12 bars", dict(LIVE, time_stop_bars=12)),
]

def score(res):
    tr = res["trade_log"]
    rs = []
    for t in tr:
        risk = abs(t["entry"] - t["orig_sl"])
        if risk > 0:
            rs.append(t["pnl"] / risk)
    if not rs:
        return dict(n=0, mean_r=0.0, total_r=0.0, wr=0.0, avg_win=0.0, avg_loss=0.0)
    w = [x for x in rs if x > 0]
    l = [x for x in rs if x <= 0]
    return dict(n=len(rs), mean_r=round(statistics.mean(rs), 3),
                total_r=round(sum(rs), 1),
                wr=round(100.0 * len(w) / len(rs), 1),
                avg_win=round(statistics.mean(w), 2) if w else 0.0,
                avg_loss=round(statistics.mean(l), 2) if l else 0.0)

def main():
    bridge = BridgeClient()
    data = {TF: fetch_all_ohlc(bridge, "XAUUSD", TF, COUNT),
            "H1": fetch_all_ohlc(bridge, "XAUUSD", "H1", COUNT),
            "H4": fetch_all_ohlc(bridge, "XAUUSD", "H4", COUNT)}
    rows = data[TF]
    print("bars:", len(rows), flush=True)
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
        res = backtest_ohlc(rows, signal_fn, spread=SPREAD, **lad)
        out[name] = score(res)
        s = out[name]
        print(f"{name:34s} n={s['n']:3d} mean={s['mean_r']:+.3f}R total={s['total_r']:+.1f}R "
              f"wr={s['wr']:.0f}% win={s['avg_win']:+.2f} loss={s['avg_loss']:+.2f}", flush=True)
    os.makedirs("data/backtest", exist_ok=True)
    json.dump(out, open("data/backtest/b65_exit_sweep.json", "w"), indent=1)
    print("saved data/backtest/b65_exit_sweep.json")

if __name__ == "__main__":
    main()
