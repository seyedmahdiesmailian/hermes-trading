#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 4 — previous-day high/low BREAKOUT continuation.

Standing loop (b68): each run tests ONE candidate method not yet in the lab.
Rounds 1-3 tested vwap_fade (mean reversion), atr_expand (momentum) and
htf_pullback (the funnel's own trend+discount class); all REJECTED, all
landing in the same 0.19-0.44 fresh band. This round tests the classic
"PDH/PDL break" — the level the ICT/SMC playbook treats as the single most
important intraday liquidity reference: the previous TRADING day's high and
low (a trading day here is 01:00-23:45 UTC, i.e. the broker session boundary
measured in the cached data: the daily break is 23:45 -> 01:00, so grouping
by broker calendar date would splice two sessions together and invent a
level nobody on the desk would draw).

The probe that picked this candidate is itself the finding worth measuring:
splitting the 141 level TOUCHES on 3000 cached M15 bars by what the
breaking bar does, a bar that CLOSES back inside (a sweep) drifts +0.38 ATR
against the break (t=0.8, noise), while a bar that CLOSES THROUGH the level
drifts +1.00 ATR WITH the break over the next 24 bars (n=72, t=+2.1) — the
strongest raw predictive split this loop has produced, and the reason the
arm requires a close confirmation instead of a wick. But raw drift is not
expectancy: the trade has to survive a stop. So the arm is measured with two
stop widths beyond the broken level — 0.5 ATR (tight, textbook) and 1.0 ATR
(wide) — to see whether the drift survives the geometry at all.

No lookahead: the level uses only bars of the PREVIOUS trading day, the
signal is bar i-1's close through the level, entry is bar i's open. TP 2R.
Measured with the SAME engine as live (engines.backtest.backtest_ohlc),
0.20$ spread, 3000 cached M15 gold bars, plain 2R geometry AND the live b60
exit ladder. Merit bar (b68 round-1 METHOD RULE): funnel +0.854R cached,
and any confirm re-measures the funnel on the SAME fresh data.
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

# A trading day runs 01:00-23:45 UTC (the data's own session break), so the
# day key is shifted by one hour: 00:xx bars belong to the PREVIOUS day.
DAY_SHIFT = 3600


def trading_day(ts):
    return datetime.datetime.fromtimestamp(ts - DAY_SHIFT,
                                          datetime.timezone.utc).date()


def prev_day_levels():
    """{day: (prev_high, prev_low)} built ONLY from completed earlier days."""
    buckets = {}
    for r in M15:
        buckets.setdefault(trading_day(r["time"]), []).append(r)
    days = sorted(buckets)
    levels = {}
    for k in range(1, len(days)):
        prev = buckets[days[k - 1]]
        if len(prev) >= 40:                      # a real session, not a stub
            levels[days[k]] = (max(x["high"] for x in prev),
                               min(x["low"] for x in prev))
    return levels


LEVELS = prev_day_levels()


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


def pdh_break(i, stop_atr=0.5):
    """Continuation on a CLOSE-CONFIRMED break of the previous trading day's
    extreme: bar i-1 closes above PDH (prior bar's close was at/below it) ->
    BUY at bar i's open, SL stop_atr*ATR beyond PDH, TP 2R. Mirror for PDL."""
    if i < 30 or i >= len(M15):
        return None
    sig, prior = M15[i - 1], M15[i - 2]
    day = trading_day(sig["time"])
    if day not in LEVELS:
        return None
    ph, pl = LEVELS[day]
    a = atr(i - 1)
    if not a:
        return None
    pc = float(prior["close"])
    sc = float(sig["close"])
    if pc <= ph < sc:                              # broke the day's HIGH
        e = float(M15[i]["open"])
        sl = ph - stop_atr * a
        risk = e - sl
        if risk <= 0:
            return None
        return {"side": "BUY", "entry": e, "sl": sl, "tp": e + 2.0 * risk,
                "style": "pdh_break", "grade": "B"}
    if pc >= pl > sc:                              # broke the day's LOW
        e = float(M15[i]["open"])
        sl = pl + stop_atr * a
        risk = sl - e
        if risk <= 0:
            return None
        return {"side": "SELL", "entry": e, "sl": sl, "tp": e - 2.0 * risk,
                "style": "pdh_break", "grade": "B"}
    return None


ARMS = [("pdh_break_t50", lambda i: pdh_break(i, 0.5)),
        ("pdh_break_w10", lambda i: pdh_break(i, 1.0))]


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


def main():
    print(f"{'strategy':16s} {'exit':8s} {'trades':>6s} {'exp_R':>7s} {'WR%':>6s} "
          f"{'net_R':>7s} {'maxDD_R':>8s}")
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
                  f"{s.get('WR%',0):6.1f} {s.get('net_R',0):7.1f} {s.get('maxDD_R',0):8.1f}",
                  flush=True)
    p = os.path.join(_ROOT, "data", "backtest", "b68e_pdh_lab.json")
    json.dump(out, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
