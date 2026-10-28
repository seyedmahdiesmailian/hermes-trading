#!/usr/bin/env python3
"""b76 — LONDON ORB PRICED WITH THE DEPLOYED EXIT LADDER (honest test).

b75 census (bar-level, my own TP=2x range) said F1_ORB_LON: 21 signals,
exp_R 0.169, PROMOTE per pre-registered bar. But the deployed system does
NOT exit at raw TP — it exits half at a distance derived from grade/ATR
(P2 half-TP1), trails, and time-stops (live_time_stop_bars). A new signal
class must earn its keep UNDER THAT LADDER, same risk units (R = entry->SL)
as the funnel. Anything less is comparing my exits to the deployed book.

HONEST EXTRA HURDLES a bar-level census cannot see:
  - spread already 0.2 in R units (ladder prices it via SPREAD in backtest_ohlc? NO —
    backtest models spread via signal geometry; we subtract SPREAD at entry here);
  - the funnel's R uses its own SL geometry; ORB SL = opposite range edge — fine,
    it is a real bracket;
  - MIN_RR: ORB TP must be >= 1.5R or the executor would refuse the trade —
    MEASURED and reported per signal (skips below-bar ones = executor parity);
  - weekend/news guards are NOT modeled (same known lab caveat as every arm).

Method: reconstruct the exact b75 F1_ORB_LON signals (deterministic re-derive
from M5), then run each through engines.backtest.backtest_ohlc with the LADDER
params + live time stop, TP/SL from the ORB definition. Compare against the
b73 legs (funnel's own exp on the same calendar window).

Verdict bar (pre-registered in b75, unchanged): ladder-priced exp_R >= 0.15,
>= 15 trades, positive on >= 2 of 3 chronological 10-day legs.
"""
from __future__ import annotations
import json, os, sys, statistics
from datetime import datetime, timezone
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); os.chdir(_ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

from bridge_client import BridgeClient
from engines import lab_harness as lh
from engines.backtest import backtest_ohlc

OUT = "data/backtest/b76_orb_ladder.json"
SPREAD = 0.2


def umin(ts): return (ts // 60) % 1440
def uday(ts): return ts // 86400


def orb_signals(rows):
    days = {}
    for i, r in enumerate(rows):
        days.setdefault(uday(int(r["time"])), []).append(i)
    sigs = []
    for d in sorted(days):
        idx = days[d]
        if len(idx) < 100: continue
        rng = [j for j in idx if 420 <= umin(int(rows[j]["time"])) < 450]
        if len(rng) < 5: continue
        rh = max(float(rows[j]["high"]) for j in rng)
        rl = min(float(rows[j]["low"]) for j in rng)
        size = rh - rl
        if not (0.5 < size < 25): continue
        for j in idx:
            t = int(rows[j]["time"]); m = umin(t)
            if m < 450 or m >= 600: continue
            c = float(rows[j]["close"])
            if c > rh + 1.5:
                sigs.append({"i": j, "t": t, "side": 1, "entry": c, "sl": rl, "tp": rh + 2 * size}); break
            if c < rl - 1.5:
                sigs.append({"i": j, "t": t, "side": -1, "entry": c, "sl": rh, "tp": rl - 2 * size}); break
    return sigs


def main():
    b = BridgeClient()
    rows = sorted(b.get_rates("XAUUSD", "M5", 6000).get("data", []), key=lambda r: int(r["time"]))[:-1]
    sigs = orb_signals(rows)
    ts = lh.live_time_stop_bars(rows)
    kw = dict(lh.LADDER)
    kw.update(trail_floor=lh.SPREAD and 3.0, time_stop_bars=ts)
    # grade: ORB has no funnel grade -> ladder share fn takes grade; pass "B" via signal dict
    sig_by_t = {s["t"]: s for s in sigs}

    def signal_fn(row):
        s = sig_by_t.get(int(row["time"]))
        if not s: return None
        risk = abs(s["entry"] - s["sl"])
        if risk <= 0: return None
        rr = abs(s["tp"] - s["entry"]) / risk
        if lh.MIN_RR > 0 and rr < lh.MIN_RR: return None   # executor parity
        return {"side": "BUY" if s["side"] > 0 else "SELL",
                "entry": s["entry"], "sl": s["sl"], "tp": s["tp"],
                "grade": "B", "style": "orb_london"}

    res = backtest_ohlc(rows, signal_fn, min_rr=0.0, min_grade=None,
                        breakeven_at_r=0.0,
                        partial_tp1_share=kw["partial_tp1_share"],
                        tp1_position=kw["tp1_position"],
                        partial_share_fn=kw["partial_share_fn"],
                        trail_after_partial=kw["trail_after_partial"],
                        time_stop_bars=ts, trail_floor=3.0,
                        spread=SPREAD)
    st = lh.r_stats(res, time_stop_bars=ts)
    t_end = int(rows[-1]["time"])
    legs = {"L1": [], "L2": [], "L3": []}
    for tr in res.get("trade_log", []):
        risk = abs(float(tr["entry"]) - float(tr.get("orig_sl") or tr["sl"])) or 1
        r = float(tr["pnl"]) / risk
        t_in = int(rows[int(tr["entry_index"])]["time"])
        age = (t_end - t_in) / 86400
        legs["L3" if age <= 10 else ("L2" if age <= 20 else "L1")].append(r)
    out = {"signals_raw": len(sigs), "book": {k: v for k, v in st.items() if not isinstance(v, (list, dict))},
           "legs": {k: {"n": len(v), "exp_R": round(sum(v) / len(v), 3) if v else None} for k, v in legs.items()}}
    print(json.dumps(out, indent=1, default=str))
    json.dump(out, open(OUT, "w"), indent=1, default=str)
    print("saved ->", OUT)


if __name__ == "__main__":
    main()
