#!/usr/bin/env python3
"""b77 — NY-SESSION FRESH BREAKOUT PRICED WITH THE DEPLOYED EXIT LADDER.

b76 killed London ORB under the honest ladder (18 trades, exp_R -0.26).
Root cause is structural, not the idea: ORB SL = opposite range edge ->
risk 1.5-3x the range -> TP at 2x range is only ~1R. The deployed ladder is
built for the funnel's own geometry (SL below a structure level, TP >= 1.5R)
and punishes wide-stop classes; it also time-stops (b119) before a slow ORB
TP (2x range) can arrive.

Gold is famous for trend CONTINUATION through the NY morning (the 45-min
post-open spike literature). Test the class in its NATURAL shape: after a
confirmed move is already running in the NY window, join it with a STRUCTURE
stop (recent pullback swing), target 1.5R — exactly the geometry the ladder
and the time stop were tuned for. If THIS fails too, the conclusion is that
fresh momentum-breakout edges do not survive 2024-2026 costs on this book,
which is itself a reportable finding.

Entry (all settled bars, UTC window 12:00-15:00, max one signal/day):
  - up: close breaks max(high of previous 24 settled bars) AND the 3-bar
    run before the break also net-rises (momentum already proven);
  - short mirrored on min(low...);
  - SL = min(low of last 6 bars) (long) / max(high) (short); require
    0.5 <= risk <= 6.0 and RR >= 1.5 (TP = entry +/- 1.5*risk) — else skip.
Honesty: one slot, ladder params = deployed (P2 half-TP1 share fn, trail
3R floor, live time stop, spread 0.2), MIN_RR parity, no gate loosening.
Bar (pre-registered, same as b76): >= 15 trades in 30 days AND ladder
exp_R >= +0.15 AND positive on >= 2 of 3 ten-day legs.
"""
from __future__ import annotations
import json, os, sys
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

OUT = "data/backtest/b77_ny_breakout_ladder.json"
SPREAD = 0.2
RR_TARGET = 1.5


def umin(ts): return (ts // 60) % 1440
def uday(ts): return ts // 86400


def derive_signals(rows):
    """rows: M5 dicts. Returns list of {t, side, entry, sl, tp} (settled-close semantics)."""
    sigs = []
    fired_day = set()
    for k in range(24, len(rows)):
        r = rows[k]
        t = int(r["time"]); m = umin(t)
        if not (720 <= m < 900): continue
        d = uday(t)
        if d in fired_day: continue
        prev = rows[k - 24:k]
        c = float(r["close"])
        hi = max(float(x["high"]) for x in prev)
        lo = min(float(x["low"]) for x in prev)
        last6 = rows[k - 5:k]
        side = None
        if c > hi:
            if float(rows[k - 3]["close"]) < float(rows[k]["close"]) and float(rows[k - 4]["close"]) < c:
                side = 1
        elif c < lo:
            if float(rows[k - 3]["close"]) > float(rows[k]["close"]) and float(rows[k - 4]["close"]) > c:
                side = -1
        if side is None: continue
        if side > 0:
            sl = min(float(x["low"]) for x in last6)
            tp = c + RR_TARGET * (c - sl)
            if not (0.5 <= c - sl <= 6.0): continue
        else:
            sl = max(float(x["high"]) for x in last6)
            tp = c - RR_TARGET * (sl - c)
            if not (0.5 <= sl - c <= 6.0): continue
        fired_day.add(d)
        sigs.append({"t": t, "side": side, "entry": c, "sl": sl, "tp": tp})
    return sigs


def main():
    b = BridgeClient()
    rows = sorted(b.get_rates("XAUUSD", "M5", 9000).get("data", []), key=lambda r: int(r["time"]))[:-1]
    sigs = derive_signals(rows)
    dates = [datetime.fromtimestamp(s["t"], tz=timezone.utc).strftime("%m-%d %H:%M") for s in sigs]
    print(f"{len(sigs)} signals in {len(set(uday(s['t']) for s in sigs))} days: {dates}")
    ts = lh.live_time_stop_bars(rows)
    kw = dict(lh.LADDER)
    sig_by_t = {s["t"]: s for s in sigs}

    def signal_fn(row):
        s = sig_by_t.get(int(row["time"]))
        if not s: return None
        risk = abs(s["entry"] - s["sl"])
        if risk <= 0: return None
        rr = abs(s["tp"] - s["entry"]) / risk
        if lh.MIN_RR > 0 and rr < lh.MIN_RR: return None
        return {"side": "BUY" if s["side"] > 0 else "SELL",
                "entry": s["entry"], "sl": s["sl"], "tp": s["tp"],
                "grade": "B", "style": "ny_breakout"}

    res = backtest_ohlc(rows, signal_fn, min_rr=0.0, min_grade=None,
                        breakeven_at_r=0.0,
                        partial_tp1_share=kw["partial_tp1_share"],
                        tp1_position=kw["tp1_position"],
                        partial_share_fn=kw["partial_share_fn"],
                        trail_after_partial=kw["trail_after_partial"],
                        time_stop_bars=ts, trail_floor=3.0, spread=SPREAD)
    st = lh.r_stats(res, time_stop_bars=ts)
    t_end = int(rows[-1]["time"])
    legs = {"L1": [], "L2": [], "L3": []}
    for tr in res.get("trade_log", []):
        risk = abs(float(tr["entry"]) - float(tr.get("orig_sl") or tr["sl"])) or 1
        r = float(tr["pnl"]) / risk
        t_in = int(rows[int(tr["entry_index"])]["time"])
        age = (t_end - t_in) / 86400
        legs["L3" if age <= 10 else ("L2" if age <= 20 else "L1")].append(r)
    out = {"signals_raw": len(sigs),
           "book": {k: v for k, v in st.items() if not isinstance(v, (list, dict))},
           "legs": {k: {"n": len(v), "exp_R": round(sum(v) / len(v), 3) if v else None} for k, v in legs.items()}}
    print(json.dumps(out, indent=1, default=str))
    json.dump(out, open(OUT, "w"), indent=1, default=str)
    print("saved ->", OUT)


if __name__ == "__main__":
    main()
