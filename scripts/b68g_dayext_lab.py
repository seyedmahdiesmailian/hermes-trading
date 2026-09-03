#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 6 — TRADING-DAY EXTENSION CONTINUATION.

Standing loop (b68): each round tests ONE candidate method not yet in the lab.
Rounds 1-5: vwap_fade (mean rev), atr_expand (momentum), htf_pullback (the
funnel's own trend+discount class), pdh_break (level breakout), nr7_break
(compression breakout). All REJECTED as replacements; pdh and nr7 escalated to
b70 as additive-lane candidates.

This round tests the family the probe (scripts/b68g_probe.py) picked
empirically — PATH SHAPE OF THE TRADING DAY, not a level and not an indicator.
The probe measured ATR-normalised forward drift on the cached 3000 M15 gold
bars and the result was one-sided:

    P4_day_open_ext_2.5   h8  n=918 mean=+0.400 ATR (t=4.93)
                          h24 n=918 mean=+0.945 ATR (t=7.42)   CONTINUATION
    P3_range_exhaust_3.0  h8  n=2310 mean=-0.201 (t=-4.45)
                          h24 n=2310 mean=-0.794 (t=-9.23)     FADING LOSES
    P2b_extension_fade3.5 h24 n=40   mean=-0.547 (t=-0.85)     FADING LOSES

P3 and P4 are the same phenomenon read from two sides: on this dataset a day
that has already moved KEEPS moving. The fade arms are negative, so the arm
built here is the continuation one. (Caveat recorded up front: P3/P4 samples
overlap heavily — 2310/2940 and 918/2940 bars — so serial correlation inflates
those t-stats. The BACKTEST de-overlaps them by construction: one position at
a time, so the trade-level R stats are the honest number and the probe is only
a screen.)

Arms (round-4/5 convention: signal is bar i-1's CLOSE through the condition,
entry is bar i's OPEN, TP 2R — the convention that moved pdh and nr7 into
contention; the old b62 arms entered at the signal close with a fixed-ATR TP
and are not comparable):

  dayext_cont_w10 — SL 1.0*ATR(14) beyond the TRADING DAY OPEN (level-anchored:
                    the continuation thesis dies when price gives the day back)
  dayext_cont_a10 — SL 1.0*ATR(14) behind the entry (fixed 1-ATR risk, so the
                    stop does not widen with how far the day has already run)
  dayext_fade_w10 — the CONTROL: fade the extension at >= 2.5 ATR from the day
                    open, same geometry. Expected to lose; measured anyway so
                    the loop's "mean reversion is dead on gold M15" finding has
                    a day-shape data point next to the vwap/bb/rsi ones.

Trigger condition (all arms): bar i-1 closes >= EXT_ATR * ATR(14) away from the
trading-day open, at or after hour OPEN_HOUR UTC (the probe's after_hour=13 —
before the London/NY session the day's direction is not yet established), and
the day has >= 8 bars of history. No lookahead: the day open and the day's bar
count come only from bars at index <= i-1; ATR uses bars <= i-1.

Measured with the SAME engine as live (engines.backtest.backtest_ohlc), 0.20$
spread, 3000 cached M15 gold bars, plain 2R geometry AND the live b60 ladder.
Merit bar (b68 round-1 METHOD RULE): funnel +0.854R cached; any confirm
re-measures the funnel on the SAME fresh data.
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

EXT_ATR = 1.5       # probe P4's threshold (2.5 was stronger but rarer)
OPEN_HOUR = 13      # UTC; the trading day here starts at 01:00 UTC
MIN_DAY_BARS = 8    # a day must have some history before we judge its shape
DAY_SHIFT = 3600    # b68e: trading day = 01:00-23:45 UTC in this data


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


def trading_day(ts):
    return datetime.datetime.fromtimestamp(ts - DAY_SHIFT,
                                           datetime.timezone.utc).date()


def hour_utc(i):
    return datetime.datetime.fromtimestamp(M15[i]["time"],
                                           datetime.timezone.utc).hour


def day_open_of(i):
    """The OPEN of the trading day that bar i belongs to, plus how many bars
    of that day exist at index <= i. Built by scanning backwards, so it can
    never see a future bar."""
    d = trading_day(M15[i]["time"])
    j = i
    while j > 0 and trading_day(M15[j - 1]["time"]) == d:
        j -= 1
    if trading_day(M15[j]["time"]) != d:
        return None, 0
    return float(M15[j]["open"]), i - j + 1


def dayext(i, mode="cont", stop="level", ext=EXT_ATR):
    """mode='cont' rides the day's extension, 'fade' fights it.
    stop='level' anchors SL 1.0*ATR beyond the trading-day open;
    stop='atr' puts SL 1.0*ATR behind the entry."""
    if i < 30 or i >= len(M15):
        return None
    sig = M15[i - 1]
    if hour_utc(i - 1) < OPEN_HOUR:
        return None
    a = atr(i - 1)
    if not a:
        return None
    do, nbars = day_open_of(i - 1)
    if do is None or nbars < MIN_DAY_BARS:
        return None
    d = (float(sig["close"]) - do) / a
    if abs(d) < ext:
        return None
    up = d > 0
    want_up = up if mode == "cont" else (not up)
    e = float(M15[i]["open"])
    if want_up:
        sl = (do - 1.0 * a) if stop == "level" else (e - 1.0 * a)
        risk = e - sl
        if risk <= 0:
            return None
        return {"side": "BUY", "entry": e, "sl": sl, "tp": e + 2.0 * risk,
                "style": f"dayext_{mode}", "grade": "B"}
    sl = (do + 1.0 * a) if stop == "level" else (e + 1.0 * a)
    risk = sl - e
    if risk <= 0:
        return None
    return {"side": "SELL", "entry": e, "sl": sl, "tp": e - 2.0 * risk,
            "style": f"dayext_{mode}", "grade": "B"}


# NOTE (b69 lesson applied to my own control arm): the fade arm MUST use the
# 'atr' stop. With 'level' the anchor is the day open, which for a fade sits on
# the SAME side as the move being fought — a SELL of an up-extension would get
# SL = day_open + 1 ATR, i.e. BELOW the entry, so risk <= 0 and every signal is
# silently dropped (measured: 0 trades on both exits). That is exactly the dead
# arm that made b63's compression row read as "compression has no edge" when it
# had never measured anything. The fade is therefore measured with a plain
# 1-ATR stop behind entry, which is also the only geometry that makes its R
# comparable to dayext_cont_a10.
ARMS = [("dayext_cont_w10", lambda i: dayext(i, "cont", "level")),
        ("dayext_cont_a10", lambda i: dayext(i, "cont", "atr")),
        ("dayext_cont_w10_e25", lambda i: dayext(i, "cont", "level", ext=2.5)),
        ("dayext_cont_a10_e25", lambda i: dayext(i, "cont", "atr", ext=2.5)),
        ("dayext_fade_a10", lambda i: dayext(i, "fade", "atr", ext=2.5))]


def r_stats(res):
    rs = []
    for t in res.get("trade_log", []):
        risk = abs(float(t["entry"]) - float(t.get("orig_sl") or t["sl"])) or 1
        rs.append(float(t["pnl"]) / risk)
    if not rs:
        return {"trades": 0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = abs(sum(losses) / len(losses)) if losses else 0.001
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return {"trades": len(rs),
            "exp_R": round(sum(rs) / len(rs), 3),
            "WR%": round(100 * len(wins) / len(rs), 1),
            "avg_win_R": round(avg_w, 2), "avg_loss_R": round(-avg_l, 2),
            "net_R": round(sum(rs), 1), "maxDD_R": round(dd, 1)}


def shape_probe():
    """How often does the trigger actually fire, and what does the day-open
    distance distribution look like? Guards against repeating b69's mistake:
    an arm whose gate never fires measures nothing."""
    n = len(M15)
    hits = {1.0: 0, 1.5: 0, 2.0: 0, 2.5: 0}
    after = 0
    dists = []
    for i in range(30, n):
        if hour_utc(i) < OPEN_HOUR:
            continue
        a = atr(i)
        do, nbars = day_open_of(i)
        if not a or do is None or nbars < MIN_DAY_BARS:
            continue
        after += 1
        d = abs((float(M15[i]["close"]) - do) / a)
        dists.append(d)
        for k in hits:
            if d >= k:
                hits[k] += 1
    dists.sort()
    q = lambda p: round(dists[int(p * (len(dists) - 1))], 2) if dists else None
    return {"bars_after_open_hour": after,
            "dist_median": q(0.5), "dist_p75": q(0.75), "dist_p95": q(0.95),
            "dist_max": round(dists[-1], 2) if dists else None,
            "fire_at_1.0atr": hits[1.0], "fire_at_1.5atr": hits[1.5],
            "fire_at_2.0atr": hits[2.0], "fire_at_2.5atr": hits[2.5]}


def main():
    probe = shape_probe()
    print("day-extension shape probe:", json.dumps(probe), flush=True)
    print(f"{'strategy':18s} {'exit':8s} {'trades':>6s} {'exp_R':>7s} {'WR%':>6s} "
          f"{'net_R':>7s} {'maxDD_R':>8s}")
    out = {"_shape_probe": probe}
    for name, fn in ARMS:
        for mode, kw in (("plain", {}),
                         ("ladder", {"partial_tp1_share": 0.5,
                                     "partial_share_fn": lambda t: _partial_close_fraction(t),
                                     "tp1_position": 0.50, "trail_after_partial": 0.5,
                                     "breakeven_at_r": 0.0})):
            res = backtest_ohlc(M15, indexed(fn), min_rr=0.0, spread=SPREAD, **kw)
            s = r_stats(res)
            out[f"{name}:{mode}"] = s
            print(f"{name:18s} {mode:8s} {s.get('trades',0):6d} {s.get('exp_R',0):7.3f} "
                  f"{s.get('WR%',0):6.1f} {s.get('net_R',0):7.1f} {s.get('maxDD_R',0):8.1f}",
                  flush=True)
    p = os.path.join(_ROOT, "data", "backtest", "b68g_dayext_lab.json")
    json.dump(out, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
