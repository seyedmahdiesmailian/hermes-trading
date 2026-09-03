#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 2 — session-anchored VWAP band fade (one new arm).

Standing loop (b68): each run tests ONE candidate method not yet in the lab.
This round: VWAP. Institutions benchmark execution to the session VWAP; the
classic trade is the BAND FADE — price stretches 2 sd away from the anchored
VWAP, prints a rejection bar, and is faded back to the mean. Not yet measured
here (b62 tested classic indicators, b63 tested SMC/RTM structures).

Anchoring: VWAP resets at each UTC calendar-day open (00:00 UTC), the standard
institutional anchor for XAUUSD intraday. Bands are volume-weighted sd.
No lookahead: session window is rows[:i+1] only.

Measured with the SAME engine as live (engines.backtest.backtest_ohlc),
0.20$ spread, 3000 cached M15 gold bars, plain 2R geometry AND the live b60
exit ladder. Merit bar: the live funnel's +0.854R/trade (b61).
"""
import os, sys, json, datetime
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from engines.backtest import backtest_ohlc
from engines.trade_management import _partial_close_fraction

DATA = json.load(open(os.path.join(_ROOT, "data/backtest/ab_aggressive_data.json")))
M15 = DATA["M15"]
SPREAD = 0.20
IDX = {r["time"]: n for n, r in enumerate(M15)}


def indexed(fn):
    def w(row):
        i = IDX.get(row.get("time"))
        return None if i is None else fn(i)
    return w


def atr(i, n=14):
    if i < n:
        return None
    trs = []
    for j in range(i - n + 1, i + 1):
        h, l, pc = M15[j]["high"], M15[j]["low"], M15[j - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / n


def day_key(t):
    return datetime.datetime.fromtimestamp(t, tz=datetime.timezone.utc).date()


# anchored VWAP + sd per bar (incremental within each UTC day); recompute_vwap()
# repoints the tables at another dataset (the b68b fresh-fetch confirm does this)
VWAP = [None] * len(M15)
VSD = [None] * len(M15)


def recompute_vwap():
    global VWAP, VSD
    VWAP = [None] * len(M15)
    VSD = [None] * len(M15)
    _pv = _vol = _sq = 0.0
    _cur_day = None
    for _i, _b in enumerate(M15):
        dk = day_key(_b["time"])
        if dk != _cur_day:
            _cur_day = dk
            _pv = _vol = _sq = 0.0
        tp = (_b["high"] + _b["low"] + _b["close"]) / 3.0
        v = float(_b.get("tick_volume") or 1)
        _pv += tp * v
        _vol += v
        m = _pv / _vol
        _sq += v * (tp - m) ** 2
        VWAP[_i] = m
        VSD[_i] = (_sq / _vol) ** 0.5


recompute_vwap()


def session_bars(i):
    dk = day_key(M15[i]["time"])
    n = 0
    j = i
    while j >= 0 and day_key(M15[j]["time"]) == dk:
        n += 1
        j -= 1
    return n


def vwap_band_fade(i, k=2.0, min_bars=12):
    """Fade a 2-sd stretch off the anchored VWAP once a rejection bar prints."""
    if i < 30 or session_bars(i) < min_bars:
        return None
    a = atr(i)
    if not a or VSD[i] is None or VSD[i] <= 0:
        return None
    up_band = VWAP[i] + k * VSD[i]
    lo_band = VWAP[i] - k * VSD[i]
    b, p = M15[i], M15[i - 1]
    c, pc = b["close"], p["close"]
    # long: stretched below band, rejection bar (bullish close back above band)
    if p["low"] < lo_band and c > lo_band and c > b["open"] and c > pc:
        sl = min(p["low"], lo_band) - 0.5 * a
        risk = c - sl
        if risk <= 0:
            return None
        return {"side": "BUY", "entry": c, "sl": sl, "tp": c + 2.0 * risk,
                "style": "vwap_fade", "grade": "B"}
    # short mirror
    if p["high"] > up_band and c < up_band and c < b["open"] and c < pc:
        sl = max(p["high"], up_band) + 0.5 * a
        risk = sl - c
        if risk <= 0:
            return None
        return {"side": "SELL", "entry": c, "sl": sl, "tp": c - 2.0 * risk,
                "style": "vwap_fade", "grade": "B"}
    return None


ARMS = [("vwap_fade", vwap_band_fade)]


def r_stats(res):
    rs = []
    for t in res.get("trade_log", []):
        risk = abs(float(t["entry"]) - float(t.get("orig_sl") or t["sl"])) or 1
        rs.append(float(t["pnl"]) / risk)
    if not rs:
        return {"trades": 0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return {"trades": len(rs),
            "exp_R": round(sum(rs) / len(rs), 3),
            "WR%": round(100 * len(wins) / len(rs), 1),
            "net_R": round(sum(rs), 1), "maxDD_R": round(dd, 1)}


def main():
    print(f"{'strategy':16s} {'exit':8s} {'trades':>6s} {'exp_R':>7s} {'WR%':>6s} {'net_R':>7s} {'maxDD_R':>8s}")
    out = {}
    for name, fn in ARMS:
        for mode, kw in (("plain", {}),
                         ("ladder", {"partial_tp1_share": 0.5,
                                     "partial_share_fn": lambda t: _partial_close_fraction(t),
                                     "tp1_position": 0.50, "trail_after_partial": 0.5,
                                     "breakeven_at_r": 0.0})):
            res = backtest_ohlc(M15, indexed(fn), min_rr=0.0, spread=SPREAD, **kw)
            s = r_stats(res)
            out[f"{name}:{mode}"] = s
            print(f"{name:16s} {mode:8s} {s.get('trades',0):6d} {s.get('exp_R',0):7.3f} "
                  f"{s.get('WR%',0):6.1f} {s.get('net_R',0):7.1f} {s.get('maxDD_R',0):8.1f}", flush=True)
    p = os.path.join(_ROOT, "data", "backtest", "b68_vwap_lab.json")
    json.dump(out, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
