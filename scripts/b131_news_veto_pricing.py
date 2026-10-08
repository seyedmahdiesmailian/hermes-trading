#!/usr/bin/env python3
"""b131 — PRICE THE NEWS-VETO ON THE FUNNEL (b107's last unmeasured leg).

WHY THIS EXISTS
===============
b107's exit-side research mandate is complete except for this leg: the live
entry-side news blackout (engines/macro_filter.evaluate_macro_filter, consulted
by BOTH entry paths and enforced by auto_executor Check 7) has NEVER been
priced against the funnel's own trades. b31/b33 fixed its plumbing; nobody has
asked whether the veto earns its keep in R.

b107's progress note blocked this round on a DATA fact, not a code fact: the
stored funnel ledgers carry per-arm AGGREGATES only, and a time-based gate
cannot be priced by arithmetic on aggregates (the reusable lesson: an
aggregate-only ledger can only re-price LEVEL-based arms). This round ships
the fix the item's own procedure demanded — engines/backtest.py gained the
additive `news_veto_windows` dial AND the trade_log now carries
entry_time/exit_time, so from today a veto question IS ledger arithmetic.

THE CALENDAR PROBLEM (measured, not assumed)
============================================
ForexFactory's public feed only covers the current week; no yearly archive
exists (probed 2026-09-07: ff_calendar_2024/2025/2026.json all 404). The only
historical calendar in this repo is the UNION of the 27 committed versions of
data/calendar/economic_calendar.json — Aug 23..Sep 12 2026, 14 strict-high
USD/XAU events at 6 unique timestamps. The lab legs are cached (Jul 15..Aug 28
2026) and W1..W6 (Jan 2025..Jul 2026), so the REAL calendar intersects exactly
ONE leg (cached, at its tail). That is a coverage fact about the data, and this
ledger reports it as such instead of hiding it behind a synthetic calendar.

THREE QUESTIONS
===============
Q1 REAL RULE: with live's own ±30-min blackout applied through live's own
   predicate over the only calendar that exists, how many funnel entries are
   vetoed per leg and what does it cost in exp_R / net_R / maxDD_R?
Q2 COVERAGE PROXY: a monthly first-Friday 12:30 UTC NFP-cadence calendar
   (clearly labelled synthetic — a cadence, not a historical record) gives
   every leg a calendar. Sweeping the blackout half-width 30min/2h/4h/12h/24h
   measures how WIDE the veto must get before it moves the funnel at all.
Q3 NEUTRALITY (b110 under b123/b129/b130's rules): every arm reports its
   delta AND n_nonzero next to any one-sided flag; an inert grid must read as
   inert, not as unanimous.

PARITY BY CONSTRUCTION (b71/b80/b118's rule)
============================================
The veto windows are NOT hand-derived from event timestamps: `veto_windows()`
probes the REAL evaluate_macro_filter at every bar time of the leg and merges
consecutive blocked bars into windows. The blackout half-width is READ from
the function's own default signature, never restated. The engine applies the
windows at bar granularity, exactly the granularity the probe used, so the
lab's veto ⟺ live's predicate, cell by cell (pinned by test).

The OFF arm is the b129/b130 incumbent (lh.LADDER, protection_mode="partial",
time_stop_bars=144, gate no_partial) and integrity() checks it BYTE-IDENTICAL
against the frozen b129 ledger on all seven legs — so this grid is the same
funnel, not a splice, and the engine edit moved nothing.

NOTHING IS WIRED OR RETUNED. The veto stays exactly as live runs it; changing
a risk gate is a human gate (b89 class) and this round does not propose one.
The product is the price, the coverage census, and the reusable clock fields.
"""
from __future__ import annotations

import datetime as dt
import inspect
import json
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                      # noqa: E402
from engines.backtest import backtest_ohlc                 # noqa: E402
from engines.macro_filter import evaluate_macro_filter     # noqa: E402
from scripts import b81_lane_rescore as b81                # noqa: E402
from scripts.b121_flat_share_replication import (          # noqa: E402
    LEGS, _rows_for)
from scripts.b123_protection_share_decomposition import one_sided   # noqa: E402
from scripts.b129_timestop_reprice import one_sided_strict          # noqa: E402

OUT = "data/backtest/b131_news_veto_pricing.json"
LEDGER_129 = "data/backtest/b129_timestop_reprice.json"

# live's own blackout half-width, READ from the gate's signature (b109's rule:
# a restated 30 is a second source of truth).
LIVE_BLACKOUT_MIN = int(
    inspect.signature(evaluate_macro_filter).parameters["blackout_minutes"].default)

# The b129/b130 incumbent arm — imported values, never literals.
from scripts.b129_timestop_reprice import (                 # noqa: E402
    GATE_LIVE, INCUMBENT_STOP)

WINDOWS_MIN = (LIVE_BLACKOUT_MIN, 120, 240, 720, 1440)
OFF = "off"
REAL = "real::±%dmin" % LIVE_BLACKOUT_MIN
ARM_NAMES = (OFF, REAL) + tuple("nfp::±%dmin" % m for m in WINDOWS_MIN)

GOLD_CURS = {"USD", "XAU", "GOLD", ""}


def git_union_calendar() -> dict:
    """Union of every committed version of the economic calendar (the only
    historical calendar that exists on this box). Read-only git plumbing,
    same source b107's blast-radius note used."""
    hs = subprocess.run(
        ["git", "log", "--format=%H", "--all", "--",
         "data/calendar/economic_calendar.json"],
        capture_output=True, text=True, cwd=_ROOT).stdout.split()
    seen: dict[tuple, dict] = {}
    for h in hs:
        raw = subprocess.run(["git", "show", f"{h}:data/calendar/economic_calendar.json"],
                             capture_output=True, text=True, cwd=_ROOT).stdout
        try:
            d = json.loads(raw)
        except Exception:
            continue
        for e in d.get("events", []):
            if (str(e.get("impact", "")).lower() == "high"
                    and str(e.get("currency", "")).upper() in GOLD_CURS):
                seen[(e.get("date"), e.get("title"))] = e
    return {"source": "git_union_forexfactory",
            "events": sorted(seen.values(), key=lambda e: str(e.get("date")))}


def nfp_calendar(first_ts: int, last_ts: int) -> dict:
    """SYNTHETIC coverage proxy: first Friday of each month, 12:30 UTC, in the
    real feed's shape. This is a CADENCE, not a historical record — it exists
    only because no yearly archive of real events is reachable (see module
    docstring); every number built on it is labelled `nfp::` in the ledger."""
    events = []
    y, m = dt.datetime.fromtimestamp(first_ts, dt.timezone.utc).year, 1
    last_y, last_m = (dt.datetime.fromtimestamp(last_ts, dt.timezone.utc).year,
                      dt.datetime.fromtimestamp(last_ts, dt.timezone.utc).month)
    while (y, m) <= (last_y, last_m):
        for d in range(1, 8):
            day = dt.date(y, m, d)
            if day.weekday() == 4:                      # Friday
                t = dt.datetime(y, m, d, 12, 30, tzinfo=dt.timezone.utc)
                if first_ts - 86400 <= t.timestamp() <= last_ts + 86400:
                    events.append({"title": "Non-Farm Employment Change",
                                   "currency": "USD", "impact": "high",
                                   "date": t.isoformat(), "time": ""})
                break
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return {"source": "synthetic_nfp_cadence", "events": events}


def veto_windows(bar_times: list[int], calendar: dict,
                 half_minutes: int) -> list[tuple[int, int]]:
    """Bars the REAL live predicate blocks, merged into (start,end) windows.

    Parity by construction: we do not reimplement the ±half filter, the
    currency filter or the fail-closed branch — we ask evaluate_macro_filter
    itself, once per bar timestamp, and keep the blocked bars. Consecutive
    blocked bars merge; a gap of one open bar splits the window, which is
    exactly what the engine's per-bar `start <= t <= end` test reproduces.
    """
    blocked = [t for t in bar_times
               if not evaluate_macro_filter(calendar,
                                            dt.datetime.fromtimestamp(
                                                t, dt.timezone.utc),
                                            blackout_minutes=half_minutes)
               .get("allowed", True)]
    out: list[list[int]] = []
    for t in blocked:
        if out and t - out[-1][1] <= 900:               # consecutive M15 bars
            out[-1][1] = t
        else:
            out.append([t, t])
    return [(a, b) for a, b in out]


def _incumbent_kw() -> dict:
    return dict(lh.LADDER, protection_mode="partial",
                time_stop_gate=GATE_LIVE, time_stop_bars=INCUMBENT_STOP)


def measure_leg(m15, h1, h4) -> dict:
    """One leg, all arms: OFF + real-calendar veto + the NFP-cadence grid."""
    funnel = b81.funnel_fn(m15, h1, h4)
    ts = lh.live_time_stop_bars(m15)
    times = [int(r["time"]) for r in m15]
    real_cal = git_union_calendar()
    nfp_cal = nfp_calendar(times[0], times[-1])
    grid, wins = {}, {}
    for arm in ARM_NAMES:
        if arm == OFF:
            kw, w = _incumbent_kw(), []
        elif arm == REAL:
            w = veto_windows(times, real_cal, LIVE_BLACKOUT_MIN)
            kw = dict(_incumbent_kw(), news_veto_windows=w)
        else:
            half = int(arm.split("±")[1].rstrip("min"))
            w = veto_windows(times, nfp_cal, half)
            kw = dict(_incumbent_kw(), news_veto_windows=w)
        res = backtest_ohlc(m15, funnel, min_rr=lh.MIN_RR, spread=lh.SPREAD,
                            min_grade=lh.LIVE_MIN_GRADE, **kw)
        grid[arm] = lh.r_stats(res, time_stop_bars=ts)
        wins[arm] = [[a, b] for a, b in w]
        if arm == OFF:
            # the reusable part of this round: the per-trade CLOCK census that
            # makes every future time-gate question ledger arithmetic.
            rows = [{"entry_time": int(t["entry_time"]),
                     "exit_time": int(t["exit_time"]),
                     "pnl": t["pnl"], "exit_reason": t["exit_reason"],
                     "r": round(t["pnl"] / max(abs(t["entry"] - t["orig_sl"]), 1e-9), 4)}
                    for t in res["trade_log"]]
    return {"_bars": len(m15), "_first": times[0], "_last": times[-1],
            "_time_stop_bars": ts, "grid": grid, "windows": wins,
            "off_rows": rows, "_funnel": funnel}


def _g(led, leg, arm, metric="exp_R"):
    return (led[leg]["grid"].get(arm) or {}).get(metric)


def integrity(led, l129: dict) -> dict:
    """The OFF arm must BE b129's incumbent cell on every leg — same funnel,
    same bars, engine edit moved nothing."""
    checks = {}
    for leg in LEGS:
        off = led[leg]["grid"][OFF]
        inc129 = l129[leg]["grid"][f"{GATE_LIVE}::ts_{INCUMBENT_STOP}"]
        checks[leg] = {"off_matches_b129_incumbent": off == inc129}
    return checks


def vetoed_census(led) -> dict:
    """How many of the OFF arm's own entries fall inside each arm's windows —
    the blast radius, computed as LEDGER ARITHMETIC (b131 step 2's payoff)."""
    out = {}
    for leg in LEGS:
        rows = {}
        for arm in ARM_NAMES:
            if arm == OFF:
                continue
            ws = [tuple(w) for w in led[leg]["windows"][arm]]
            hit = [r for r in led[leg]["off_rows"]
                   if any(a <= r["entry_time"] <= b for a, b in ws)]
            rows[arm] = {"n_vetoed_entries": len(hit),
                         "n_off_trades": len(led[leg]["off_rows"]),
                         "vetoed_R": round(sum(h["r"] for h in hit), 3),
                         "n_windows": len(ws)}
        out[leg] = rows
    return out


def deltas(led, metric="exp_R", nd=3) -> dict:
    out = {}
    for arm in ARM_NAMES:
        if arm == OFF:
            continue
        row = {}
        for leg in LEGS:
            a, b = _g(led, leg, arm, metric), _g(led, leg, OFF, metric)
            row[leg] = (round(a - b, nd) if a is not None and b is not None else None)
        out[arm] = row
    return out


def neutrality(led) -> dict:
    """b110's rule under b123's one_sided(), b129's strict floor and b130's
    denominator: every flag carries n_nonzero next to it."""
    out = {}
    for arm in ARM_NAMES:
        if arm == OFF:
            continue
        d = deltas(led)[arm]
        vals = [d[leg] for leg in LEGS if d[leg] is not None]
        pos = sum(1 for v in vals if v > 0)
        neg = sum(1 for v in vals if v < 0)
        nz = pos + neg
        out[arm] = {"pos": pos, "neg": neg, "n_nonzero": nz,
                    "max_abs": round(max((abs(v) for v in vals), default=0.0), 3),
                    "mean": round(sum(vals) / len(vals), 4) if vals else None,
                    "one_sided": one_sided(pos, neg),
                    "one_sided_strict": one_sided_strict(pos, neg, len(vals))}
    return out


def verdict(led) -> dict:
    """The decision-relevant summary: does any veto arm move the funnel by
    more than b119's 0.10R ceiling, one-sidedly?"""
    neu = neutrality(led)
    cen = vetoed_census(led)
    out = {}
    for arm in ARM_NAMES:
        if arm == OFF:
            continue
        n = neu[arm]
        out[arm] = {
            "n_vetoed_total": sum(cen[leg][arm]["n_vetoed_entries"] for leg in LEGS),
            "n_nonzero": n["n_nonzero"],
            "max_abs_exp_R": n["max_abs"],
            "mean_exp_R": n["mean"],
            "one_sided": n["one_sided"],
            "one_sided_strict": n["one_sided_strict"],
            "clears_b119_ceiling": n["max_abs"] >= 0.10,
        }
    return out


def build() -> dict:
    led: dict = {"_live_blackout_min": LIVE_BLACKOUT_MIN,
                 "_arms": list(ARM_NAMES),
                 "_note": ("real:: calendar = git union of committed "
                           "economic_calendar.json (Aug23..Sep12 2026 only); "
                           "nfp:: = synthetic first-Friday cadence proxy, NOT "
                           "a historical record")}
    for leg in LEGS:
        m15, h1, h4 = _rows_for(leg)
        led[leg] = measure_leg(m15, h1, h4)
        led[leg].pop("_funnel")
    led["_integrity"] = integrity(led, json.load(open(LEDGER_129)))
    led["_census"] = vetoed_census(led)
    led["_delta_exp_R"] = deltas(led)
    led["_delta_net_R"] = deltas(led, "net_R", 1)
    led["_delta_maxDD_R"] = deltas(led, "maxDD_R", 1)
    led["_neutrality"] = neutrality(led)
    led["_verdict"] = verdict(led)
    return led


def main() -> None:
    led = build()
    bad = [leg for leg in LEGS if not led["_integrity"][leg]["off_matches_b129_incumbent"]]
    if bad:
        raise SystemExit(f"INTEGRITY FAIL: OFF arm != b129 incumbent on {bad}")
    with open(OUT, "w") as f:
        json.dump(led, f, indent=1)
    print("integrity: OFF == b129 incumbent on all", len(LEGS), "legs")
    for arm, v in led["_verdict"].items():
        print(f"{arm:>16}: vetoed={v['n_vetoed_total']:>3}  "
              f"n_nonzero={v['n_nonzero']}  max|Δexp_R|={v['max_abs_exp_R']}  "
              f"mean={v['mean_exp_R']}  one_sided={v['one_sided']}/strict={v['one_sided_strict']}  "
              f"ceiling={v['clears_b119_ceiling']}")
    print("saved:", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
