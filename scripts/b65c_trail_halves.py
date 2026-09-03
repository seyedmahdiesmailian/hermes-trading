#!/usr/bin/env python3
"""b65c — stability check: does trail 0.3 beat trail 0.5 in BOTH halves of
the M5 dataset (recent half vs older half)? Guards against a lucky window."""
import sys, os, statistics
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
BASE = dict(partial_share_fn=lambda t: _partial_close_fraction(t),
            tp1_position=0.50, partial_tp1_share=0.5, breakeven_at_r=0.0)

def score(res):
    rs = [t["pnl"] / abs(t["entry"] - t["orig_sl"]) for t in res["trade_log"]
          if abs(t["entry"] - t["orig_sl"]) > 0]
    return (len(rs), round(statistics.mean(rs), 3) if rs else 0, round(sum(rs), 1) if rs else 0)

bridge = BridgeClient()
data = {TF: fetch_all_ohlc(bridge, "XAUUSD", TF, COUNT),
        "H1": fetch_all_ohlc(bridge, "XAUUSD", "H1", COUNT),
        "H4": fetch_all_ohlc(bridge, "XAUUSD", "H4", COUNT)}
rows = data[TF]
half = len(rows) // 2
for label, sub in (("older half", rows[:half]), ("recent half", rows[half:])):
    idx_of = {r["time"]: n for n, r in enumerate(sub)}
    def signal_fn(row, sub=sub, idx_of=idx_of):
        i = idx_of.get(row.get("time"))
        if i is None:
            return None
        bt = row.get("time", 0)
        hw = [r for r in data["H1"] if r.get("time", 0) <= bt][-80:]
        h4w = [r for r in data["H4"] if r.get("time", 0) <= bt][-80:]
        return strategy_signal(row, hw, h4w, i, m15_window=sub[max(0, i - 120):i + 1])
    for name, tr in (("trail.5", 0.5), ("trail.3", 0.3)):
        n, m, tot = score(backtest_ohlc(sub, signal_fn, spread=SPREAD,
                                        trail_after_partial=tr, **BASE))
        print(f"{label:12s} {name}: n={n:3d} mean={m:+.3f}R total={tot:+.1f}R", flush=True)
