#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 6 — CANDIDATE PROBE (pick by raw drift, then trade it).

Round 4's method: before spending a round on an arm, measure the RAW forward
drift of the candidate condition on the cached 3000 M15 gold bars. A condition
with no drift has no chance against the funnel (0.854 cached / 0.576 fresh);
a condition with a big drift and a usable n is worth a full arm.

Every family the loop has already measured and REJECTED: mean reversion
(vwap_fade, bb_bounce, rsi_rev, sweep_rev), momentum (atr_expand, donchian),
HTF trend+pullback (htf_pullback, ema_pullback), level breakout (asia_break,
ny_orb, pdh_break, nr7_break), SMC/RTM (b63: ob/breaker/ote/turtle_soup/
eqh/sweep_choch), overnight gap (too thin), session-open drift (noise).

The untested family this probe screens is PATH SHAPE rather than LEVEL or
INDICATOR: how far price has already travelled, how fast, and how
consecutively. Specifically:

  P1 streak_fade      k consecutive same-direction closes with cumulative
                      displacement >= 1.5 ATR -> does the run exhaust?
  P2 extension_fade   close >= 2.5 ATR(14) beyond the 20-EMA -> rubber band
  P3 range_exhaust    the TRADING DAY already moved > 3.0 ATR(50) by hour h ->
                      does the rest of the day continue or fade?
  P4 day_open_ext     price >= 1.5 ATR away from the trading-day open late in
                      the day -> drift into the close (continuation or fade)
  P5 slow_break       close-confirmed break of the Asia range in London hours,
                      measured with the round-4/5 CONVENTION (entry next bar
                      open). The lab's asia_break scored 0.18 under the OLD
                      convention (entry at the signal close, fixed-ATR TP,
                      1.2 ATR stop) — the convention change is what moved pdh
                      and nr7 into contention, so the old number is not the
                      same measurement.
  P6 gap_open         |day open - prev day close| >= 0.5 ATR -> fill rate
                      (re-measure the thin overnight-gap finding at the
                      trading-day boundary, not the calendar one)

Drift is quoted in ATR(14) units, signed WITH the condition's implied
direction, over 8/24 bars ahead, with a t-stat. No trades are placed, no
live state is touched — read-only analysis on a cached JSON.
"""
import os, sys, json, math, datetime, statistics

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

DATA = json.load(open(os.path.join(_ROOT, "data/backtest/ab_aggressive_data.json")))
M15 = DATA["M15"]
DAY_SHIFT = 3600          # b68e: trading day = 01:00-23:45 UTC in this data


def atr(i, n=14):
    if i < n:
        return None
    trs = []
    for j in range(i - n + 1, i + 1):
        h, l, pc = M15[j]["high"], M15[j]["low"], M15[j - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / n


def atr_long(i, n=50):
    return atr(i, n)


def hour_utc(i):
    return datetime.datetime.fromtimestamp(M15[i]["time"],
                                           datetime.timezone.utc).hour


def trading_day(ts):
    return datetime.datetime.fromtimestamp(ts - DAY_SHIFT,
                                           datetime.timezone.utc).date()


def drift(i, sign, horizon):
    """ATR-normalised forward move from bar i's close, signed by `sign`
    (+1 = the condition expects up). None if the window runs off the end."""
    a = atr(i)
    if not a or i + horizon >= len(M15):
        return None
    return sign * (M15[i + horizon]["close"] - M15[i]["close"]) / a


def report(name, samples):
    if not samples:
        print(f"{name:22s} n=0")
        return {"n": 0}
    out = {}
    for h, vals in samples.items():
        if len(vals) < 5:
            out[h] = {"n": len(vals)}
            continue
        m = statistics.fmean(vals)
        sd = statistics.pstdev(vals) or 1e-9
        t = m / (sd / math.sqrt(len(vals)))
        out[h] = {"n": len(vals), "mean_atr": round(m, 3), "t": round(t, 2)}
    print(f"{name:22s} " + "  ".join(
        f"h{h}: n={v.get('n',0)} mean={v.get('mean_atr','-')} t={v.get('t','-')}"
        for h, v in out.items()))
    return {"samples": out, "events": max([len(v) for v in samples.values()] or [0])}


RESULTS = {}


def collect(name, cond_fn, horizons=(8, 24)):
    """cond_fn(i) -> +1/-1/None (direction the condition predicts)."""
    samples = {h: [] for h in horizons}
    for i in range(60, len(M15) - max(horizons) - 1):
        s = cond_fn(i)
        if not s:
            continue
        for h in horizons:
            d = drift(i, s, h)
            if d is not None:
                samples[h].append(d)
    RESULTS[name] = report(name, samples)


# ---------- P1: consecutive-close streak with real displacement ----------
def streak_fade(k=4, min_disp=1.5):
    def f(i):
        a = atr(i)
        if not a or i < k + 1:
            return None
        closes = [M15[j]["close"] for j in range(i - k, i + 1)]
        up = all(closes[j + 1] > closes[j] for j in range(k))
        dn = all(closes[j + 1] < closes[j] for j in range(k))
        if not (up or dn):
            return None
        disp = abs(closes[-1] - closes[0]) / a
        if disp < min_disp:
            return None
        return -1 if up else 1          # fade the run
    return f


def streak_cont(k=4, min_disp=1.5):
    f = streak_fade(k, min_disp)
    def g(i):
        s = f(i)
        return None if s is None else -s  # ride the run
    return g


# ---------- P2: extension beyond the 20-EMA ----------
def ema(vals, n):
    k = 2 / (n + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


Closes = [r["close"] for r in M15]
E20 = ema(Closes, 20)


def extension_fade(mult=2.5):
    def f(i):
        a = atr(i)
        if not a:
            return None
        d = (M15[i]["close"] - E20[i]) / a
        if d >= mult:
            return -1
        if d <= -mult:
            return 1
        return None
    return f


# ---------- P3/P4: trading-day context ----------
DAY_BUCKETS = {}
for _n, _r in enumerate(M15):
    DAY_BUCKETS.setdefault(trading_day(_r["time"]), []).append(_n)
DAY_OF = {n: trading_day(M15[n]["time"]) for n in range(len(M15))}


def day_so_far(i):
    return [M15[j] for j in DAY_BUCKETS[DAY_OF[i]] if j <= i]


def range_exhaust(min_range_atr=3.0, ref_n=50):
    def f(i):
        a = atr_long(i, ref_n)
        if not a:
            return None
        bars = day_so_far(i)
        if len(bars) < 20:
            return None
        rng = (max(b["high"] for b in bars) - min(b["low"] for b in bars)) / a
        if rng < min_range_atr:
            return None
        up = bars[-1]["close"] >= bars[0]["open"]
        return -1 if up else 1          # fade an already-extended day
    return f


def day_open_ext(mult=1.5, after_hour=13):
    def f(i):
        a = atr(i)
        if not a or hour_utc(i) < after_hour:
            return None
        bars = day_so_far(i)
        if len(bars) < 8:
            return None
        d = (M15[i]["close"] - bars[0]["open"]) / a
        if d >= mult:
            return 1                    # continuation into the close
        if d <= -mult:
            return -1
        return None
    return f


# ---------- P5: Asia range break, round-4/5 convention ----------
def asia_break_new(after=7, before=12, min_bars=10):
    def f(i):
        h = hour_utc(i)
        if not (after <= h < before):
            return None
        a = atr(i)
        if not a:
            return None
        asia = [M15[j] for j in range(max(0, i - 40), i) if hour_utc(j) < after]
        if len(asia) < min_bars:
            return None
        hi = max(b["high"] for b in asia)
        lo = min(b["low"] for b in asia)
        c, pc = M15[i]["close"], M15[i - 1]["close"]
        if pc <= hi < c:
            return 1
        if pc >= lo > c:
            return -1
        return None
    return f


# ---------- P6: trading-day opening gap ----------
def gap_open(mult=0.5):
    days = sorted(DAY_BUCKETS)
    prev_close = {}
    for k in range(1, len(days)):
        prev_close[days[k]] = M15[DAY_BUCKETS[days[k - 1]][-1]]["close"]
    def f(i):
        a = atr(i)
        if not a or hour_utc(i) != 1:
            return None
        if DAY_BUCKETS[DAY_OF[i]][0] != i:
            return None
        pc = prev_close.get(DAY_OF[i])
        if pc is None:
            return None
        g = (M15[i]["open"] - pc) / a
        if abs(g) < mult:
            return None
        return -1 if g > 0 else 1       # fade the gap (fill)
    return f


def main():
    print(f"cached M15 bars: {len(M15)}  "
          f"({datetime.datetime.fromtimestamp(M15[0]['time'], datetime.timezone.utc):%Y-%m-%d %H:%M}"
          f" -> {datetime.datetime.fromtimestamp(M15[-1]['time'], datetime.timezone.utc):%Y-%m-%d %H:%M})")
    collect("P1_streak_fade_k4", streak_fade(4, 1.5))
    collect("P1b_streak_cont_k4", streak_cont(4, 1.5))
    collect("P1c_streak_fade_k5", streak_fade(5, 2.0))
    collect("P2_extension_fade2.5", extension_fade(2.5))
    collect("P2b_extension_fade3.5", extension_fade(3.5))
    collect("P3_range_exhaust_3.0", range_exhaust(3.0))
    collect("P4_day_open_ext_1.5", day_open_ext(1.5))
    collect("P4b_day_open_ext_2.5", day_open_ext(2.5))
    collect("P5_asia_break_new", asia_break_new())
    collect("P6_gap_open_0.5", gap_open(0.5))
    p = os.path.join(_ROOT, "data", "backtest", "b68g_probe.json")
    json.dump(RESULTS, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
