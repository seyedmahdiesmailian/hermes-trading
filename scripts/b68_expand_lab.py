#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 2 — ATR-expansion continuation (one new arm).

Standing loop (b68): each run tests ONE candidate method not yet in the lab.
Round 1 was vwap_fade (mean reversion, rejected). This round: momentum —
the ATR-EXPANSION CONTINUATION. Definition (classic volatility-breakout
literature): a bar whose true range blows past k x ATR(14) AND closes in the
extreme quarter of its own range is a displacement/expansion bar; if the
PRIOR bar was not itself an expansion (a fresh ignition, not the tail of a
run), enter in the direction of the expansion on the NEXT bar's open (the
signal bar's close is not executable — no lookahead, no same-bar fill),
SL just beyond the signal bar's extreme, TP at 2R.

Not yet measured here: b62 tested classic indicators (EMA/RSI/BB/Donchian/
FVG/session ORB), b63 tested SMC/RTM structures (this round's `compression`
arm fired 0 trades — its 0.9*ATR tightness gate never triggered on gold —
so the OPPOSITE shape, expansion, is the untested half), b68r1 tested VWAP
band fade.

Measured with the SAME engine as live (engines.backtest.backtest_ohlc),
0.20$ spread, 3000 cached M15 gold bars, plain 2R geometry AND the live b60
exit ladder. Merit bar: the live funnel's +0.854R/trade (b61) on this set —
and per the b68 round-1 METHOD RULE, any confirm must re-measure the funnel
on the SAME fresh data too. Two variants are measured: all sessions, and
London/NY only (expansion bars in the thin Asia hours are the usual false
ignitions).
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


def tr(i):
    h, l, pc = M15[i]["high"], M15[i]["low"], M15[i - 1]["close"]
    return max(h - l, abs(h - pc), abs(l - pc))


def hour_utc(i):
    return datetime.datetime.fromtimestamp(M15[i]["time"],
                                           tz=datetime.timezone.utc).hour


def _is_expansion(i, k):
    """Fresh expansion bar: TR > k*ATR, close in the extreme quarter, and the
    prior bar was NOT an expansion (ignition, not run continuation tail)."""
    a = atr(i)
    if not a or tr(i) <= k * a:
        return None
    b = M15[i]
    rng = b["high"] - b["low"]
    if rng <= 0:
        return None
    pos = (b["close"] - b["low"]) / rng          # 1 = closed at the high
    if pos >= 0.75:
        return "BUY"
    if pos <= 0.25:
        return "SELL"
    return None


def expansion_continuation(i, k=1.8, sessions=None):
    """Enter NEXT bar open in the direction of a fresh ATR-expansion bar."""
    if i < 30:
        return None
    if sessions is not None:
        h = hour_utc(i - 1)                       # anchor on the signal bar
        if h not in sessions:
            return None
    side = _is_expansion(i - 1, k)
    if side is None:
        return None
    sig = M15[i - 1]
    c = M15[i]["open"]                            # executable next-bar open
    a = atr(i - 1)
    if side == "BUY":
        sl = sig["low"] - 0.25 * a
        risk = c - sl
        if risk <= 0:
            return None
        return {"side": "BUY", "entry": c, "sl": sl, "tp": c + 2.0 * risk,
                "style": "atr_expand", "grade": "B"}
    sl = sig["high"] + 0.25 * a
    risk = sl - c
    if risk <= 0:
        return None
    return {"side": "SELL", "entry": c, "sl": sl, "tp": c - 2.0 * risk,
            "style": "atr_expand", "grade": "B"}


LONDON_NY = set(range(7, 24))                     # live session map parity

ARMS = [("atr_expand_all", lambda i: expansion_continuation(i)),
        ("atr_expand_lny", lambda i: expansion_continuation(i, sessions=LONDON_NY))]


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
    p = os.path.join(_ROOT, "data", "backtest", "b68_expand_lab.json")
    json.dump(out, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
