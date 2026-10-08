#!/usr/bin/env python3
"""b63 SMC/RTM STRATEGY LAB — modern smart-money methods, tested honestly.

From the research (ICT/RTM/SMC literature):
  sweep+CHOCH+OB  : liquidity sweep -> structure shift -> order-block retest
  breaker         : failed OB flips role, entry on retest (RTM)
  ote             : displacement leg, entry in 0.62-0.79 fib retracement (ICT)
  turtle_soup     : failed 20-bar breakout reversal (RTM classic)
  compression     : contracting range -> expansion breakout (RTM)
  eqh_sweep       : equal highs swept then reversal (ICT liquidity)
  ob_first_retest : unmitigated OB, first touch after BOS (SMC)

All measured with the SAME engine as live (engines.backtest.backtest_ohlc),
0.20$ spread, on 3000 cached real M15 gold bars. Each arm runs TWICE:
plain 2R geometry AND with the live b60 exit ladder. Merit bar: the live
funnel scores +0.854R/trade (b61). No lookahead: signals use rows[:i+1].
"""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engines.backtest import backtest_ohlc
from engines.trade_management import _partial_close_fraction

DATA = json.load(open(os.path.join(os.path.dirname(__file__), "..",
                                   "data/backtest/ab_aggressive_data.json")))
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


def swing_high(i, k=2, max_age=120):
    """Most recent confirmed swing high at index <= i-k."""
    for j in range(i - k, max(k, i - max_age) - 1, -1):
        h = M15[j]["high"]
        if all(h > M15[j - d]["high"] and h > M15[j + d]["high"] for d in range(1, k + 1)):
            return j, h
    return None, None


def swing_low(i, k=2, max_age=120):
    for j in range(i - k, max(k, i - max_age) - 1, -1):
        lo = M15[j]["low"]
        if all(lo < M15[j - d]["low"] and lo < M15[j + d]["low"] for d in range(1, k + 1)):
            return j, lo
    return None, None


# ---------- 1) sweep + CHOCH + OB retest (short side + long mirror) ----------
def sweep_choch_ob(i):
    if i < 60:
        return None
    a = atr(i)
    if not a:
        return None
    j, sh = swing_high(i - 8)          # older swing high
    if sh is None:
        return None
    # sweep: bar in last 12 that pierced sh but closed back below
    sweep = None
    for s in range(max(j, i - 12), i - 1):
        if M15[s]["high"] > sh + 0.10 * a and M15[s]["close"] < sh:
            sweep = s
            break
    if sweep is None:
        return None
    # CHOCH: after sweep, a close below the lowest low between j and sweep
    ll = min(M15[q]["low"] for q in range(j, sweep + 1))
    choch = None
    for c in range(sweep + 1, i):
        if M15[c]["close"] < ll:
            choch = c
            break
    if choch is None:
        return None
    # OB = last up candle before the down move started
    ob = None
    for q in range(choch, sweep, -1):
        if M15[q]["close"] > M15[q]["open"]:
            ob = q
            break
    if ob is None:
        return None
    top, bot = M15[ob]["high"], M15[ob]["low"]
    c = M15[i]["close"]
    # first retest into OB zone then rejection (close back below top)
    if M15[i]["high"] >= top and bot < c < top and c < M15[i]["open"]:
        sl = top + 0.3 * a
        risk = sl - c
        if risk <= 0:
            return None
        return {"side": "SELL", "entry": c, "sl": sl, "tp": c - 2.0 * risk,
                "style": "sweep_choch_ob", "grade": "B"}
    return None


# ---------- 2) breaker block (failed OB flips) ----------
def breaker(i):
    if i < 80:
        return None
    a = atr(i)
    if not a:
        return None
    jl, sl_ = swing_low(i - 20)        # swing low before the up break
    if sl_ is None:
        return None
    # find BOS up: close above the swing high that followed jl, with displacement
    jh, sh = swing_high(i - 5, max_age=40)
    if sh is None:
        return None
    bos = None
    for q in range(jl, i):
        if M15[q]["close"] > sh + 0.5 * a:
            bos = q
            break
    if bos is None:
        return None
    # breaker candle: last DOWN candle before the BOS move
    br = None
    for q in range(bos, jl, -1):
        if M15[q]["close"] < M15[q]["open"]:
            br = q
            break
    if br is None:
        return None
    top, bot = M15[br]["high"], M15[br]["low"]
    c = M15[i]["close"]
    # price broke back below the breaker, now retests it from below and rejects
    if (M15[i]["low"] <= top and bot < c < top and c > M15[i]["open"]
            and min(M15[q]["close"] for q in range(br + 1, i)) < bot):
        sl = bot - 0.3 * a
        risk = c - sl
        if risk <= 0:
            return None
        return {"side": "BUY", "entry": c, "sl": sl, "tp": c + 2.0 * risk,
                "style": "breaker", "grade": "B"}
    return None


# ---------- 3) OTE: displacement leg + 0.62-0.79 fib retracement ----------
def ote(i):
    if i < 40:
        return None
    a = atr(i)
    if not a:
        return None
    j0, lo0 = swing_low(i - 6, max_age=40)
    j1, hi1 = swing_high(i - 2, max_age=30)
    if lo0 is None or hi1 is None or j1 <= j0:
        return None
    leg = hi1 - lo0
    if leg < 2.5 * a:                       # needs displacement
        return None
    c = M15[i]["close"]
    o62, o79 = hi1 - 0.62 * leg, hi1 - 0.79 * leg
    if M15[i]["low"] <= o62 and o79 <= c <= o62 and c > M15[i]["open"]:
        sl = lo0 - 0.2 * a
        risk = c - sl
        if risk <= 0:
            return None
        return {"side": "BUY", "entry": c, "sl": sl, "tp": c + 2.0 * risk,
                "style": "ote", "grade": "B"}
    return None


# ---------- 4) turtle soup: failed 20-bar breakout ----------
def turtle_soup(i):
    if i < 25:
        return None
    a = atr(i)
    if not a:
        return None
    hi20 = max(M15[q]["high"] for q in range(i - 21, i - 1))
    lo20 = min(M15[q]["low"] for q in range(i - 21, i - 1))
    c, pc = M15[i]["close"], M15[i - 1]["close"]
    if M15[i - 1]["high"] > hi20 and c < pc and c < hi20:
        sl = M15[i - 1]["high"] + 0.2 * a
        risk = sl - c
        if risk <= 0:
            return None
        return {"side": "SELL", "entry": c, "sl": sl, "tp": c - 2.0 * risk,
                "style": "turtle_soup", "grade": "B"}
    if M15[i - 1]["low"] < lo20 and c > pc and c > lo20:
        sl = M15[i - 1]["low"] - 0.2 * a
        risk = c - sl
        if risk <= 0:
            return None
        return {"side": "BUY", "entry": c, "sl": sl, "tp": c + 2.0 * risk,
                "style": "turtle_soup", "grade": "B"}
    return None


# ---------- 5) compression -> expansion ----------
# b69 DEAD ARM (measured 2026-09-03, scripts/b68f_nr7_lab.py range_probe):
# on 2940 cached M15 gold bars the 12-bar range / ATR(50) ratio has MINIMUM
# 0.671 and 5th percentile 1.83 — the "<= 0.9*ATR" tightness gate below
# fires 1 time in 2940, and the full combo (tight AND contracting AND
# impulse) 0 times. This arm has NEVER measured anything; do not read
# trades:0 in b63_smc_rtm_lab.json as "compression has no edge". The
# loosened definition that actually fires (NR7 squeeze, 506 occurrences) is
# tested in scripts/b68f_nr7_lab.py — kept here unchanged for history.
def compression(i):
    if i < 60:
        return None
    a = atr(i, 50)
    if not a:
        return None
    win = M15[i - 12:i]
    hi = max(b["high"] for b in win)
    lo = min(b["low"] for b in win)
    if (hi - lo) > 0.9 * a:               # must be tight
        return None
    # contracting: first half range > second half range
    h1 = max(b["high"] for b in win[:6]) - min(b["low"] for b in win[:6])
    h2 = max(b["high"] for b in win[6:]) - min(b["low"] for b in win[6:])
    if h2 >= h1:
        return None
    c = M15[i]["close"]
    body = abs(M15[i]["close"] - M15[i]["open"])
    if body < 0.6 * a:
        return None                        # needs an impulse bar
    if c > hi:
        sl = lo
        risk = c - sl
        if risk <= 0:
            return None
        return {"side": "BUY", "entry": c, "sl": sl, "tp": c + 2.0 * risk,
                "style": "compression", "grade": "B"}
    if c < lo:
        sl = hi
        risk = sl - c
        if risk <= 0:
            return None
        return {"side": "SELL", "entry": c, "sl": sl, "tp": c - 2.0 * risk,
                "style": "compression", "grade": "B"}
    return None


# ---------- 6) equal-highs sweep reversal ----------
def eqh_sweep(i):
    if i < 60:
        return None
    a = atr(i)
    if not a:
        return None
    j1, h1 = swing_high(i - 10)
    if h1 is None:
        return None
    j2, h2 = swing_high(j1 - 1, max_age=100)
    if h2 is None or abs(h1 - h2) > 0.15 * a:
        return None
    hi = max(h1, h2)
    c = M15[i]["close"]
    if M15[i]["high"] > hi + 0.05 * a and c < hi - 0.10 * a and c < M15[i]["open"]:
        sl = M15[i]["high"] + 0.2 * a
        risk = sl - c
        if risk <= 0:
            return None
        return {"side": "SELL", "entry": c, "sl": sl, "tp": c - 2.0 * risk,
                "style": "eqh_sweep", "grade": "B"}
    return None


# ---------- 7) unmitigated OB first retest after BOS ----------
def ob_first_retest(i):
    if i < 50:
        return None
    a = atr(i)
    if not a:
        return None
    jh, sh = swing_high(i - 10)
    if sh is None:
        return None
    bos = None
    for q in range(max(0, i - 30), i):
        if M15[q]["close"] > sh + 0.8 * a and (M15[q]["close"] - M15[q]["open"]) > 0.5 * a:
            bos = q
            break
    if bos is None:
        return None
    ob = None
    for q in range(bos, max(0, bos - 10), -1):
        if M15[q]["close"] < M15[q]["open"]:
            ob = q
            break
    if ob is None:
        return None
    top, bot = M15[ob]["high"], M15[ob]["low"]
    # unmitigated: no bar after BOS traded down into the OB until NOW
    if any(M15[q]["low"] <= top for q in range(bos + 1, i)):
        return None
    c = M15[i]["close"]
    if M15[i]["low"] <= top and c > top and c > M15[i]["open"]:
        sl = bot - 0.2 * a
        risk = c - sl
        if risk <= 0:
            return None
        return {"side": "BUY", "entry": c, "sl": sl, "tp": c + 2.0 * risk,
                "style": "ob_first_retest", "grade": "B"}
    return None


ARMS = [("sweep_choch_ob", sweep_choch_ob), ("breaker", breaker), ("ote", ote),
        ("turtle_soup", turtle_soup), ("compression", compression),
        ("eqh_sweep", eqh_sweep), ("ob_first_retest", ob_first_retest)]


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
    p = os.path.join(os.path.dirname(__file__), "..", "data", "backtest", "b63_smc_rtm_lab.json")
    json.dump(out, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
