#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 3 — HTF trend + pullback into discount (one new arm).

Standing loop (b68): each run tests ONE candidate method not yet in the lab.
Round 1: vwap_fade (mean reversion) — rejected. Round 2: atr_expand
(momentum) — rejected. Both confirmed the pattern: the b60 ladder rescues
losing arms into the 0.34-0.44 fresh band but never into contention; the
funnel's edge is its ENTRY FILTER. So this round tests an entry filter of
the class the funnel itself uses: higher-timeframe trend alignment plus
pullback DEPTH — buy only in an H1 uptrend, and only when price has pulled
back below the midpoint (discount) of the last H1 impulse leg and prints a
bullish rejection; sell mirrors in premium. This is the classic
"HTF bias + premium/discount" ICT entry, measured here for the first time
(b63's `ote` arm used an M15 displacement leg with a fixed fib band; this
arm uses the H1 leg itself and a depth threshold, no fib band).

No lookahead: the H1 context uses only bars CLOSED before the signal bar;
the signal is evaluated on bar i-1 and filled at bar i's open. SL beyond
the leg extreme, TP 2R. Two variants: discount >= 0.50 (shallow) and
>= 0.618 (deep). Measured with the SAME engine as live
(engines.backtest.backtest_ohlc), 0.20$ spread, 3000 cached M15 gold bars,
plain 2R geometry AND the live b60 exit ladder. Merit bar: funnel +0.854R
cached, and per the b68 round-1 METHOD RULE any confirm re-measures the
funnel on the SAME fresh data.
"""
import os, sys, json, datetime
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from engines.backtest import backtest_ohlc
from engines.trade_management import _partial_close_fraction

DATA = json.load(open(os.path.join(_ROOT, "data/backtest/ab_aggressive_data.json")))
M15 = DATA["M15"]
H1 = DATA["H1"]
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


def h1_closed_before(ts):
    """Number of H1 bars fully closed at/before M15 bar start ts."""
    n = 0
    for r in H1:
        if r["time"] + 3600 <= ts:
            n += 1
        else:
            break
    return n


def h1_pivots(count, k=2):
    """Confirmed swing pivots among the first `count` H1 bars.
    Returns (highs, lows) as lists of (idx, price)."""
    highs, lows = [], []
    for j in range(k, count - k):
        h = H1[j]["high"]
        if all(h > H1[j - d]["high"] and h > H1[j + d]["high"] for d in range(1, k + 1)):
            highs.append((j, h))
        lo = H1[j]["low"]
        if all(lo < H1[j - d]["low"] and lo < H1[j + d]["low"] for d in range(1, k + 1)):
            lows.append((j, lo))
    return highs, lows


def leg_state(count):
    """Trend + last impulse leg from H1 pivots closed before the signal bar.
    Returns (bias, leg_lo, leg_hi) with bias in {'up','down','neutral'}:
    up   = last confirmed pivot is a high making a higher high, and the
           pivot low before it defines the impulse leg (lo -> hi).
    down = mirror."""
    highs, lows = h1_pivots(count)
    if not highs or not lows:
        return None
    last_h_i, last_h = highs[-1]
    last_l_i, last_l = lows[-1]
    if last_h_i > last_l_i:                      # leg up: low -> high
        prev_h = highs[-2][1] if len(highs) >= 2 else None
        if prev_h is not None and last_h > prev_h:
            return ("up", last_l, last_h)
        return None
    if last_l_i > last_h_i:                      # leg down: high -> low
        prev_l = lows[-2][1] if len(lows) >= 2 else None
        if prev_l is not None and last_l < prev_l:
            return ("down", last_h, last_l)
        return None
    return None


def htf_pullback(i, min_depth=0.50):
    """Enter next-bar open in the direction of the H1 trend, but ONLY after
    price has retraced at least `min_depth` of the last H1 impulse leg
    (discount in an uptrend / premium in a downtrend) and the signal bar is
    a rejection back with the trend."""
    if i < 30:
        return None
    sig = M15[i - 1]
    nh = h1_closed_before(sig["time"])
    if nh < 10:
        return None
    st = leg_state(nh)
    if st is None:
        return None
    bias, a, b = st
    a = float(a); b = float(b)
    rng = abs(b - a)
    if rng <= 0:
        return None
    c = float(sig["close"])
    lo, hi = (a, b) if bias == "up" else (b, a)
    if bias == "up":
        if c <= lo or c >= hi:                   # outside the leg: no trade
            return None
        depth = (hi - c) / rng
        if depth < min_depth:
            return None
        if c <= float(sig["open"]):              # needs bullish rejection bar
            return None
        e = M15[i]["open"]
        sl = lo - 0.25 * (atr(i - 1) or 0)
        risk = e - sl
        if risk <= 0 or e >= hi:
            return None
        return {"side": "BUY", "entry": e, "sl": sl, "tp": e + 2.0 * risk,
                "style": "htf_pullback", "grade": "B"}
    if c >= hi or c <= lo:
        return None
    depth = (c - lo) / rng
    if depth < min_depth:
        return None
    if c >= float(sig["open"]):                  # needs bearish rejection bar
        return None
    e = M15[i]["open"]
    sl = hi + 0.25 * (atr(i - 1) or 0)
    risk = sl - e
    if risk <= 0 or e <= lo:
        return None
    return {"side": "SELL", "entry": e, "sl": sl, "tp": e - 2.0 * risk,
            "style": "htf_pullback", "grade": "B"}


ARMS = [("htf_pull_50", lambda i: htf_pullback(i, 0.50)),
        ("htf_pull_618", lambda i: htf_pullback(i, 0.618))]


def r_stats(res):
    rs = []
    for t in res.get("trade_log", []):
        risk = abs(float(t["entry"]) - float(t.get("orig_sl") or t["sl"])) or 1
        rs.append(float(t["pnl"]) / risk)
    if not rs:
        return {"trades": 0}
    wins = [r for r in rs if r > 0]
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
    p = os.path.join(_ROOT, "data", "backtest", "b68_htf_lab.json")
    json.dump(out, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
