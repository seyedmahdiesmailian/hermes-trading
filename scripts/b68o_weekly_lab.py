#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 15 — PREVIOUS-TRADING-WEEK high/low breakout.

Standing loop (b68): each round tests ONE candidate not yet measured. After
14 rounds every classic FAMILY has been screened (round-14 note): mean-rev,
momentum, trend+pullback, level breakout, compression breakout, SMC/RTM, day
path-shape, gap, session drift, plus three combination pairings. But the one
LEVEL family never measured is the HIGHER-TIMEFRAME analogue of the loop's
only replicated arm: round 4/11's pdh_break_w10 trades the previous
TRADING DAY's extreme and is the only arm that beat the funnel on both
independent windows W1/W2. The previous TRADING WEEK's high/low (PWH/PWL) is
the level every ICT/SMC desk draws right next to PDH/PDL, and it has never
been scored here.

Not a re-hash of round 4: the weekly level aggregates five trading days of
range, so a close-confirmed break is rarer and sits further from intraday
noise. The question the loop has never answered is whether a WEEK-level
break carries MORE continuation per signal than a DAY-level one, or just
fewer, later trades.

Geometry is lifted VERBATIM from round 4 (b75's freshness rule: the level
break IS the trigger event, so the geometry supplier is the fresh member of
the pair): bar i-1 CLOSES through the previous trading week's extreme with
bar i-2 still on the other side (close confirmation — round 4's wick-vs-close
split: wick-through is noise +0.38 ATR, close-through is +1.00 ATR), entry
at bar i's OPEN, SL stop_atr*ATR(14) beyond the broken level, TP 2R, grade B.
Two widths, same as round 4: t50 (textbook tight) and w10 (the survivor).

Trading-week definition follows the data's own session boundary: the trading
DAY is 01:00-23:45 UTC (round 4's DAY_SHIFT discovery — 00:xx bars belong to
the previous day) and the trading WEEK is the ISO (year, week) of that
shifted day, so a week runs Mon 01:00 -> Fri 23:45 UTC. The first week of any
dataset has no prior week and is never traded against a stale level carried
over from another leg (rebind() rebuilds the table per dataset).

Measured through the b71 harness (engines.lab_harness.run_arm): plain /
ladder / ladder_ts (live b60 ladder + live 36h time exit, derived), hold
columns mandatory, trades:0 must name its clause.

Merit bar (round-11/b76 wording): the cached 0.854 funnel bar is
regime-inflated and informational only. REPLACEMENT requires beating the
funnel's ladder_ts on the SAME bars in EVERY independent window (b74's
all-windows rule) — scripts/b68o_confirm_weekly.py does that on cached +
W1..W4 and runs the b77 chronological-decay pre-flight on the margin series
before any promotion language is allowed.

Read-only research code: nothing here is imported by the live trading path.
"""
import os
import sys
import json
import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from engines import lab_harness as lh          # noqa: E402  (b71 harness)

CACHED_PATH = os.path.join(_ROOT, "data/backtest/ab_aggressive_data.json")
DATA = json.load(open(CACHED_PATH))
M15 = DATA["M15"]
SPREAD = 0.20
IDX = {r["time"]: n for n, r in enumerate(M15)}

# A trading day runs 01:00-23:45 UTC (the data's own session break — round 4
# discovery), so the day key is shifted by one hour: 00:xx bars belong to the
# PREVIOUS day. The trading week is the ISO week of that shifted day.
DAY_SHIFT = 3600
BARS_PER_DAY = 95             # 01:00-23:45 in M15 steps
MIN_WEEK_BARS = 4 * BARS_PER_DAY     # a real week, not a holiday stub


def trading_day(ts):
    return datetime.datetime.fromtimestamp(ts - DAY_SHIFT,
                                           datetime.timezone.utc).date()


def trading_week(ts):
    y, w, _ = trading_day(ts).isocalendar()
    return (y, w)


def week_buckets(rows):
    buckets = {}
    for r in rows:
        buckets.setdefault(trading_week(r["time"]), []).append(r)
    return buckets


def build_week_levels(rows):
    """{week: (prev_high, prev_low)} built ONLY from completed earlier weeks.

    Same shape as round 4's prev_day_levels, one timeframe up: a week's level
    is the extreme of the PREVIOUS week's bars, and a stub week (fewer than
    MIN_WEEK_BARS bars — holiday-shortened, or the dataset's own first week)
    never becomes a level.
    """
    buckets = week_buckets(rows)
    weeks = sorted(buckets)
    levels = {}
    for k in range(1, len(weeks)):
        prev = buckets[weeks[k - 1]]
        if len(prev) >= MIN_WEEK_BARS:
            levels[weeks[k]] = (max(x["high"] for x in prev),
                                min(x["low"] for x in prev))
    return levels


LEVELS = build_week_levels(M15)


def rebind(rows):
    """Point the module at a new M15 dataset (levels rebuilt, never stale)."""
    global M15, IDX, LEVELS
    M15 = rows
    IDX = {r["time"]: n for n, r in enumerate(rows)}
    LEVELS = build_week_levels(rows)
    return LEVELS


def atr_of(rows, i, n=14):
    if i < n:
        return None
    trs = []
    for j in range(i - n + 1, i + 1):
        h, l, pc = rows[j]["high"], rows[j]["low"], rows[j - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / n


def atr(i, n=14):
    return atr_of(M15, i, n)


def pwh_break_at(rows, idx_unused, levels, i, stop_atr=1.0):
    """The arm, as a PURE function of (rows, levels, i) — no module state, so
    a test can feed it a synthetic dataset and level_probe can count signals
    without rebinding globals."""
    if i < 30 or i >= len(rows):
        return None
    sig, prior = rows[i - 1], rows[i - 2]
    wk = trading_week(sig["time"])
    if wk not in levels:
        return None
    ph, pl = levels[wk]
    a = atr_of(rows, i - 1)
    if not a:
        return None
    pc = float(prior["close"])
    sc = float(sig["close"])
    if pc <= ph < sc:                              # broke the week's HIGH
        e = float(rows[i]["open"])
        sl = ph - stop_atr * a
        risk = e - sl
        if risk <= 0:
            return None
        return {"side": "BUY", "entry": e, "sl": sl, "tp": e + 2.0 * risk,
                "style": "pwh_break", "grade": "B"}
    if pc >= pl > sc:                              # broke the week's LOW
        e = float(rows[i]["open"])
        sl = pl + stop_atr * a
        risk = sl - e
        if risk <= 0:
            return None
        return {"side": "SELL", "entry": e, "sl": sl, "tp": e - 2.0 * risk,
                "style": "pwh_break", "grade": "B"}
    return None


def pwh_break(i, stop_atr=1.0):
    """The module-bound form the harness feeds to backtest_ohlc (rebind()
    decides which dataset LEVELS/M15 point at)."""
    return pwh_break_at(M15, IDX, LEVELS, i, stop_atr)


def indexed(fn):
    def w(row):
        i = IDX.get(row.get("time"))
        return None if i is None else fn(i)
    return w


ARMS = [("pwh_break_t50", lambda i: pwh_break(i, 0.5)),
        ("pwh_break_w10", lambda i: pwh_break(i, 1.0))]


def level_probe(rows=None, stop_atr=1.0):
    """b72 rule 2 (anti-vacuity) for a STANDALONE level arm: how many weeks
    the dataset spans, how many carry a usable level, and the BUY/SELL split
    of the signals — so a thin n reads as a property of the dataset (weekly
    breaks are RARE by construction) and not as a silent dead arm (b69)."""
    rows = M15 if rows is None else rows
    buckets = week_buckets(rows)
    weeks = sorted(buckets)
    levels = build_week_levels(rows)
    idx = {r["time"]: n for n, r in enumerate(rows)}
    buy = sell = 0
    for i in range(30, len(rows)):
        s = pwh_break_at(rows, idx, levels, i, stop_atr)
        if s:
            buy += s["side"] == "BUY"
            sell += s["side"] == "SELL"
    return {"bars": len(rows), "weeks_in_dataset": len(weeks),
            "weeks_with_level": len(levels),
            "first_week": f"{weeks[0][0]}-W{weeks[0][1]:02d}" if weeks else None,
            "last_week": f"{weeks[-1][0]}-W{weeks[-1][1]:02d}" if weeks else None,
            "signals": buy + sell, "buy": buy, "sell": sell}


def main():
    print(f"cached leg: {len(M15)} M15 bars, "
          f"{len(LEVELS)} weeks with a level")
    print("level_probe:", json.dumps(level_probe()))
    ledger = {}
    for name, fn in ARMS:
        ledger[name] = lh.run_arm(M15, indexed(fn))
        lh.print_table(ledger, [name], label=f"{name} (cached, b71)")
        print(flush=True)
    complaints = lh.summarize(ledger, [n for n, _ in ARMS])
    print("=== honesty ===")
    for c in complaints or ["no complaints"]:
        print("!", c)
    out = {"_note": "round 15 cached leg: previous-TRADING-WEEK high/low "
                    "close-confirmed breakout, b71 harness, b72 anti-vacuity "
                    "probe",
           "_time_stop_bars": lh.live_time_stop_bars(M15),
           "_probe": level_probe(),
           "_honesty_complaints": complaints,
           **ledger}
    p = os.path.join(_ROOT, "data", "backtest", "b68o_weekly_lab.json")
    json.dump(out, open(p, "w"), indent=1)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
