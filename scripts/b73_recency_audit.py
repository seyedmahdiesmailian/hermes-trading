#!/usr/bin/env python3
"""b73 — RECENCY AUDIT: is the deployed funnel's edge ALIVE on the newest data?

User's thesis (2026-09-11): "تحلیل قدیمی/بی‌ارزش است" — in lab terms: edge
DECAY. Every cited merit number (57/0.219, b191 anchors 166/0.197) was priced
on Jul-Aug bars; the newest independent window ends 2026-07-14. Nothing has
measured the funnel on Aug-late/Sep since. This does:

  N3 = newest 3000 M5 bars (roughly Sep 1 - Sep 11)   <- THE live regime
  N2 = the 3000 before   (roughly Aug 18 - Sep 1)
  N1 = the 3000 before   (roughly Aug 5 - Aug 18)     (sanity: should match book)

Each leg runs through engines.backtest_real.run_backtest ONLY (b189 hard rule),
deployed arm: lab_harness LADDER + live time stop + MIN_RR 1.5 + grade B +
b187 trigger wired (m5_stream=None on an M5 entry stream = auto parity).

Read b77 doctrine when quoting: the SHAPE across N1->N2->N3 in chronological
order is the verdict, not any single leg.

Read-only research; one bridge get_rates per TF, cached.
"""
from __future__ import annotations
import json, os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); os.chdir(_ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

from bridge_client import BridgeClient
from engines import lab_harness as lh
from engines.backtest_real import fetch_all_ohlc, run_backtest
from datetime import datetime, timezone

SEG = 3000
CACHE = "data/backtest/b73_m5_9000.json"
OUT = "data/backtest/b73_recency_audit.json"


def rows_m5():
    if os.path.exists(CACHE):
        return json.load(open(CACHE))["rows"]
    b = BridgeClient()
    rows = sorted(fetch_all_ohlc(b, "XAUUSD", "M5", 9500), key=lambda r: int(r["time"]))
    json.dump({"rows": rows}, open(CACHE, "w"))
    return rows


def ctx_h():
    b = BridgeClient()
    return {"H1": fetch_all_ohlc(b, "XAUUSD", "H1", 2000),
            "H4": fetch_all_ohlc(b, "XAUUSD", "H4", 2000)}


def main():
    m5 = rows_m5()
    ctx = ctx_h()
    n = len(m5)
    segs = {"N3_newest": m5[n - SEG:], "N2_mid": m5[n - 2 * SEG: n - SEG],
            "N1_older": m5[n - 3 * SEG: n - 2 * SEG]}
    out = {}
    for name, rows in segs.items():
        if not rows:
            continue
        lo, hi = int(rows[0]["time"]), int(rows[-1]["time"])
        ts = lh.live_time_stop_bars(rows)
        kw = dict(lh.LADDER)
        kw.update(min_rr=lh.MIN_RR, min_grade=lh.LIVE_MIN_GRADE,
                  time_stop_bars=ts, spread_override=lh.SPREAD)
        r = run_backtest(None, symbol="XAUUSD", timeframe="M5",
                         data={"M5": rows, "H1": [x for x in ctx["H1"] if lo - 7200 <= int(x["time"]) <= hi],
                               "H4": [x for x in ctx["H4"] if lo - 28800 <= int(x["time"]) <= hi]},
                         m5_stream=None, **kw)
        st = lh.r_stats(r, time_stop_bars=ts)
        st["_span"] = [datetime.fromtimestamp(lo, tz=timezone.utc).strftime("%m-%d"),
                       datetime.fromtimestamp(hi, tz=timezone.utc).strftime("%m-%d")]
        st["_bars"] = len(rows)
        out[name] = st
        print(name, st["_span"], "trades", st.get("trades"), "exp_R", st.get("exp_R"), flush=True)
    out["_book_reference"] = {"parity": "57 trades exp_R 0.219 (Jul-Aug)", "b48h": "b72: 14 trades exp_R -0.046 (Sep 9-11)"}
    json.dump(out, open(OUT, "w"), indent=1, default=str)
    print("saved ->", OUT)


if __name__ == "__main__":
    main()
