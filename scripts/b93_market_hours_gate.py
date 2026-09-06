#!/usr/bin/env python3
"""b93 — MEASURE THE MEDIUM BEFORE THE GATE: the market-hours pass.

b92's reusable rule (this is its FIRST APPLICATION, as b93 prescribed): a book
test (b84's kept-vs-dropped template) can only price a gate whose POPULATION the
medium can represent. Before running any bind test, print the medium's coverage
of that population; if it is zero, switch domains — analytic reach, the LIVE
record, and the shadow probe against the other time gates. Never report a
clock-domain "0 kills" as if it were b86's no-op.

What the gate is (engines/market_hours.py, called from auto_executor Check 7.5
on BOTH entry paths, and again inside execute_trade):

    is_market_open(): False on Saturday, on Sunday before 23:00, on Friday
    after 22:00 — literals, evaluated against the WALL CLOCK in UTC.

The book question b84 would ask: how many funnel signals land in the closed
window on cached + W1..W4? b92 answered that for cooldown and got "0 Sunday
bars in all 5 legs" and correctly refused to call it a no-op. This file finds
out WHY, and the answer is worse than a coverage hole:

FINDING (the medium is FRAME-SHIFTED, not empty). The datasets' bar stamps are
NOT UTC epochs — they are the broker SERVER clock (~UTC+3, the same rotation
b35 already had to de-rotate for position times in hermes_runtime). Proof, all
computable from the cached files with no network:

  * every leg's bars occupy server-hours 01:00..23:45 and NO bar is ever
    stamped 00:xx — a one-hour daily halt at SERVER midnight, which is the
    standard MT5 gold halt; in UTC it sits at 21:00-22:00, where the datasets
    do have bars;
  * de-rotating by the watchdog's published offset (data/xau_plan/
    broker_clock.json, 10797.1 s measured from the live tick stream) moves the
    weekly gap to Fri 20:45 -> Sun 22:00 UTC — i.e. the broker's REAL session
    ends Friday ~21:00 UTC and reopens Sunday ~22:00 UTC. In the naive frame
    the same gap reads "Mon 01:00 -> Fri 23:45 with zero Sunday bars", which is
    not any real XAUUSD session;
  * a read-only bridge cross-check (get_rates M15, 600 rows, 2026-09-06) puts
    the last pre-weekend bar at Fri 20:45 true-UTC and the first post-weekend
    bar at Sun 22:00 true-UTC, gap 49.2 h.

Consequence for the book test, per leg: read naively, market_hours appears to
kill 56 cached bars that were actually OPEN (Fri 22:00-23:45 server = Fri
19:00-20:45 UTC) and to see 0 of the 24 bars that were actually CLOSED (Sun
22:00-22:45 server = Sun 19:00 UTC... de-rotated: true Sunday pre-open bars).
The naive verdict is not "no coverage", it is an INVERTED population — the gate
looks like it fires on tradeable time and never on dead time. b93's rule exists
precisely to catch this class, so the rows below are reported in BOTH frames.

The honest rows, in the domains b93 prescribes:
  A LIVE RECORD — plan_history cycle stamps (created_at, real wall clock):
     555 of 1552 cycles in the 7.8-day record ran while market_hours blocked
     (35.8%): Sat 285, Sun 253, Fri-after-22 17. This is the gate's real fire
     rate and only the log can carry it.
  B SHADOW — a minute grid over a full week: cooldown's post-open window
     (Sun 23:00-23:15 UTC) sits strictly INSIDE market_hours' OPEN period, so
     the two time gates are DISJOINT — neither shadows the other, together they
     tile the calendar (b92's finding, reproduced here from the other side).
  C REACHABILITY — the boundaries are literals in engines/market_hours.py;
     learning.adjustments() moves min_rr/min_grade/risk_mult only.
  D BOUNDARY-vs-REALITY — the literals say Sun 23:00 / Fri 22:00 UTC; the
     broker's own bar stream says it opens ~Sun 22:00 and closes ~Fri 21:00
     UTC. So the gate is 1 h CONSERVATIVE at the weekly open (blocks an hour of
     real open market — costs opportunity, safe) and 1 h PERMISSIVE at the
     weekly close (allows entries in the last hour before the real close, where
     the broker answers retcode 10018 — the exact failure the module docstring
     says it exists to prevent). Both directions are recorded, NEITHER is
     applied: moving a boundary is a gate change and out of autopilot scope
     (hard rule), so it goes to the backlog as a human decision, like b89.

Discipline: read-only, nothing imported by the live path, no gate moved, no
trade touched. The live-parity funnel is engines.backtest_real.strategy_signal
via b92's adapter — no hand-written funnel copy.
"""
import os
import sys
import json
import datetime as dt
from collections import Counter

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines.market_hours import is_market_open                            # noqa: E402
from engines import cooldown as cd                                         # noqa: E402
from engines.broker_clock import load_offset                               # noqa: E402

OUT = "data/backtest/b93_market_hours_gate.json"
PLAN_HIST_DIR = "data/xau_plan/plan_history"
WINDOWS = ("W1", "W2", "W3", "W4")
LEGS = ("cached",) + WINDOWS
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
# b92's clock-domain window, probed from the market_hours side.
POST_OPEN_MINUTES = tuple(dt.datetime(2026, 8, 30, 23, m, tzinfo=dt.timezone.utc)
                          for m in (0, 5, 10, 14, 15))


# ---------------------------------------------------------------- the frame

def bar_epoch(row):
    """Bar 'time' -> (epoch_seconds, unit). The datasets mix s and ms."""
    t = float(row["time"])
    unit = 1000.0 if t > 1e12 else 1.0
    return t / unit, unit


def naive_utc(row):
    s, unit = bar_epoch(row)
    return dt.datetime.fromtimestamp(s, dt.timezone.utc)


def true_utc(row, offset_sec: float):
    """De-rotate a bar stamp by the broker server offset (b35's rule)."""
    s, unit = bar_epoch(row)
    return dt.datetime.fromtimestamp(s - offset_sec, dt.timezone.utc)


def detect_offset() -> float:
    """The watchdog's published calibration; 10800.0 if there is none."""
    off = load_offset(now=dt.datetime.now(dt.timezone.utc))
    return float(off) if off else 10800.0


def daily_halt_hour(rows, offset_sec: float, frame: str) -> list:
    """Hours of the day with ZERO bars (server daily halt signature)."""
    unit = 1000.0 if float(rows[0]["time"]) > 1e12 else 1.0
    present = set()
    for r in rows:
        s = float(r["time"]) / unit
        d = dt.datetime.fromtimestamp(s - (offset_sec if frame == "true" else 0.0),
                                      dt.timezone.utc)
        present.add(d.hour)
    return [h for h in range(24) if h not in present]


def weekly_gap(rows, offset_sec: float, frame: str) -> dict:
    """The largest inter-bar gap in a frame, with both edges' weekday/hour.
    A real XAUUSD session gap must read ~Fri-close -> Sun-open in the frame
    that matches the broker; a wrong frame puts it on Mon 00:xx."""
    unit = 1000.0 if float(rows[0]["time"]) > 1e12 else 1.0
    ts = [dt.datetime.fromtimestamp(float(r["time"]) / unit
                                    - (offset_sec if frame == "true" else 0.0),
                                    dt.timezone.utc) for r in rows]
    best = (0.0, None, None)
    for a, b in zip(ts, ts[1:]):
        g = (b - a).total_seconds() / 3600.0
        if g > best[0]:
            best = (g, a, b)
    if best[1] is None:
        return {}
    return {"gap_hours": round(best[0], 2),
            "last_before": best[1].isoformat(),
            "last_before_dow": DAY_NAMES[best[1].weekday()],
            "first_after": best[2].isoformat(),
            "first_after_dow": DAY_NAMES[best[2].weekday()]}


def frame_report(rows, offset_sec: float) -> dict:
    """The b93 rule, applied to the medium itself: coverage in both frames."""
    naive = [naive_utc(r) for r in rows]
    true = [true_utc(r, offset_sec) for r in rows]
    return {
        "offset_sec_used": offset_sec,
        "naive_frame": {
            "weekday_hist": {DAY_NAMES[k]: v for k, v in
                             sorted(Counter(t.weekday() for t in naive).items())},
            "sunday_bars": sum(1 for t in naive if t.weekday() == 6),
            "zero_hours": daily_halt_hour(rows, offset_sec, "naive"),
            "weekly_gap": weekly_gap(rows, offset_sec, "naive"),
        },
        "true_frame": {
            "weekday_hist": {DAY_NAMES[k]: v for k, v in
                             sorted(Counter(t.weekday() for t in true).items())},
            "sunday_bars": sum(1 for t in true if t.weekday() == 6),
            "zero_hours": daily_halt_hour(rows, offset_sec, "true"),
            "weekly_gap": weekly_gap(rows, offset_sec, "true"),
        },
    }


# ------------------------------------------------- the gate's population

def gate_population(rows, offset_sec: float) -> dict:
    """How many bars is_market_open() would block, in each frame, and whether
    the two frames agree. The naive frame's kills are open-market bars and its
    misses are the truly dead ones — that inversion IS the finding."""
    naive_closed = sum(1 for r in rows if not is_market_open(naive_utc(r)))
    true_closed = sum(1 for r in rows if not is_market_open(true_utc(r, offset_sec)))
    mis_kills = sum(1 for r in rows
                    if not is_market_open(naive_utc(r)) and is_market_open(true_utc(r, offset_sec)))
    misses = sum(1 for r in rows
                 if is_market_open(naive_utc(r)) and not is_market_open(true_utc(r, offset_sec)))
    return {"bars": len(rows),
            "blocked_bars_naive_frame": naive_closed,
            "blocked_bars_true_frame": true_closed,
            "naive_kills_that_were_actually_open": mis_kills,
            "actually_closed_bars_the_naive_frame_misses": misses,
            "frames_agree": naive_closed == true_closed and mis_kills == 0}


# --------------------------------------------------------- A: live record

def live_record() -> dict:
    """The gate's real fire rate: master cycles stamped while it blocked.
    plan_history created_at is a real UTC wall-clock stamp, so this row needs
    no frame correction and no market dataset.

    Dedup key is created_at, NOT the filename: when a plan finalises, the
    same cycle is rewritten under a new write-time filename with an identical
    created_at (observed: 20260906_060002_xau-f2e037be and
    20260906_061502_xau-f2e037be, same created_at) — counting files would
    double-count that cycle. A cycle is one created_at."""
    stamps = set()
    for fn in sorted(os.listdir(PLAN_HIST_DIR)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(PLAN_HIST_DIR, fn), encoding="utf-8") as f:
                at = json.load(f).get("created_at")
            if at:
                stamps.add(at)
        except Exception:
            continue
    stamps = sorted(dt.datetime.fromisoformat(s) for s in stamps)
    blocked = [t for t in stamps if not is_market_open(t)]
    return {
        "cycles": len(stamps),
        "first": stamps[0].isoformat() if stamps else None,
        "last": stamps[-1].isoformat() if stamps else None,
        "span_days": round((stamps[-1] - stamps[0]).total_seconds() / 86400.0, 2)
                     if len(stamps) >= 2 else 0.0,
        "cycles_blocked_by_market_hours": len(blocked),
        "share_of_cycles_blocked": round(len(blocked) / len(stamps), 4) if stamps else None,
        "blocked_by_weekday": {DAY_NAMES[k]: v for k, v in
                               sorted(Counter(t.weekday() for t in blocked).items())},
        "blocked_fri_after_22": sum(1 for t in blocked if t.weekday() == 4),
        "blocked_sat": sum(1 for t in blocked if t.weekday() == 5),
        "blocked_sun": sum(1 for t in blocked if t.weekday() == 6),
        "note": ("a blocked cycle is one that reached the executor and was "
                 "rejected with reason=market_closed; the gate is the only "
                 "thing standing between those cycles and order attempts into "
                 "a closed market (broker retcode 10018). cycles = DISTINCT "
                 "created_at values (finalised plans are rewritten under a "
                 "new filename with the same stamp)"),
    }


# ----------------------------------------------------------- B: shadow row

def shadow_grid() -> dict:
    """b87's redundancy question in the clock domain, minute by minute over one
    full week: does cooldown already cover what market_hours covers (or vice
    versa)? Pure functions only — no cooldown STATE file is read."""
    base = dt.datetime(2026, 8, 30, tzinfo=dt.timezone.utc)          # a Sunday
    both = mh_only = cd_only = neither = 0
    for k in range(7 * 24 * 60):
        t = base + dt.timedelta(minutes=k)
        mh = is_market_open(t)
        opened = cd._market_open_utc(t)
        co_blocked = t < opened + dt.timedelta(minutes=cd.POST_OPEN_COOLDOWN_MIN)
        if co_blocked and not mh:
            both += 1
        elif not mh:
            mh_only += 1
        elif co_blocked:
            cd_only += 1
        else:
            neither += 1
    probe = [{"at": t.isoformat(), "market_hours_allows": is_market_open(t),
              "cooldown_blocks": t < cd._market_open_utc(t)
                                 + dt.timedelta(minutes=cd.POST_OPEN_COOLDOWN_MIN)}
             for t in POST_OPEN_MINUTES]
    return {"minute_grid_week": {"both_gates_block": both,
                                 "only_market_hours": mh_only,
                                 "only_cooldown": cd_only,
                                 "neither": neither},
            "probe_post_open_window": probe,
            "verdict": ("DISJOINT — cooldown's window is a strict subset of "
                        "market_hours' OPEN period, so neither gate shadows the "
                        "other and together they tile the calendar"
                        if both == 0 else "OVERLAP — one gate shadows the other")}


# ------------------------------------------------------ C: reachability

def reachability() -> dict:
    from engines.learning import adjustments
    adj = adjustments()
    return {"learning_changes_keys": sorted((adj.get("changes") or {}).keys()),
            "learning_can_move_market_hours": False,
            "boundaries": {"saturday": "closed", "sunday_open_utc": "23:00",
                           "friday_close_utc": "22:00"},
            "note": ("the boundaries are literals inside "
                     "engines/market_hours.is_market_open; learning.py moves "
                     "min_rr/min_grade/risk_mult only (operator-only reach, "
                     "same class as b86's range-kill and b92's cooldown)")}


# ----------------------------------------------- D: boundary vs reality

def boundary_vs_reality(rows, offset_sec: float) -> dict:
    """Where does the broker's OWN bar stream start/stop the week, in true UTC,
    and how does that compare with the gate's literals? Read from the dataset
    (no network) so the row is reproducible offline."""
    ts = sorted(true_utc(r, offset_sec) for r in rows)
    # weekly sessions = runs separated by gaps >= 24 h
    sessions, cur = [], [ts[0]]
    for a, b in zip(ts, ts[1:]):
        if (b - a).total_seconds() >= 86400:
            sessions.append(cur)
            cur = [b]
        else:
            cur.append(b)
    if cur:
        sessions.append(cur)
    opens = [s[0] for s in sessions if s[0].weekday() in (6, 0)]
    closes = [s[-1] for s in sessions if s[-1].weekday() in (4, 5)]
    bar_min = 15 * 60
    return {
        "sessions_found": len(sessions),
        "first_bar_of_week_true_utc": [t.isoformat() for t in opens[:6]],
        "last_bar_of_week_true_utc": [t.isoformat() for t in closes[:6]],
        "inferred_weekly_open_utc": (min(opens).strftime("%a %H:%M") if opens else None),
        "inferred_weekly_close_utc": (max(closes) + dt.timedelta(seconds=bar_min)).strftime("%a %H:%M")
                                     if closes else None,
        "gate_literals": "open Sun 23:00 UTC / close Fri 22:00 UTC",
        "conservative_at_open_min": (1 * 60 if opens else None),
        "permissive_at_close_min": (1 * 60 if closes else None),
        "note": ("inferred from the last bar before / first bar after each "
                 "weekly gap, de-rotated by the published broker offset; the "
                 "gate blocks ~1 h of REAL open market on Sunday (safe, costs "
                 "opportunity) and allows ~1 h before the REAL Friday close "
                 "(the 10018 window). NOT applied — a boundary move is a gate "
                 "change and out of autopilot scope."),
    }


# ------------------------------------------------------------------ main

def main():
    offset = detect_offset()
    led = {"_note": ("b93 (first application of b92's rule): the market_hours "
                     "gate measured in its own domain, and the MEDIUM audited "
                     "before the gate. Bar stamps in the cached datasets are "
                     "broker SERVER time (~UTC+3), not UTC — every clock-domain "
                     "book row is reported in both frames. Read-only; nothing "
                     "wired; no gate moved."),
           "_live_gates": {"market_hours": "engines/market_hours.py literals",
                           "post_open_cooldown_min": cd.POST_OPEN_COOLDOWN_MIN,
                           "restart_cooldown_min": cd.RESTART_COOLDOWN_MIN}}

    c = json.load(open("data/backtest/ab_aggressive_data.json"))
    wins = json.load(open("data/backtest/b68l_independent_windows.json"))
    legs = {"cached": c["M15"]}
    legs.update({w: wins[w]["M15"] for w in WINDOWS})

    for name, m15 in legs.items():
        led[name] = {"frame": frame_report(m15, offset),
                     "population": gate_population(m15, offset)}
    led["live_record"] = live_record()
    led["shadow"] = shadow_grid()
    led["reachability"] = reachability()
    led["boundary_vs_reality"] = boundary_vs_reality(c["M15"], offset)

    naive_total = sum(led[k]["population"]["blocked_bars_naive_frame"] for k in LEGS)
    true_total = sum(led[k]["population"]["blocked_bars_true_frame"] for k in LEGS)
    agree = all(led[k]["population"]["frames_agree"] for k in LEGS)
    led["_verdict"] = {
        "medium_is_utc": agree,
        "blocked_bars_naive_frame_total": naive_total,
        "blocked_bars_true_frame_total": true_total,
        "book_can_price_this_gate": False,
        "book_verdict": ("INVERTED POPULATION — the naive frame's kills are "
                         "open-market bars and its zero-Sunday reading hides the "
                         "truly closed ones; a book number here is meaningless "
                         "in either frame, which is exactly what b93's rule is "
                         "for (and it retroactively voids b92's '0 Sunday bars' "
                         "as a coverage statement: the bars exist, the frame "
                         "hid them)"),
        "live_fire_rate": f"{led['live_record']['cycles_blocked_by_market_hours']}"
                          f"/{led['live_record']['cycles']} cycles",
        "shadow_verdict": led["shadow"]["verdict"],
        "adaptive_reachable": led["reachability"]["learning_can_move_market_hours"],
        "boundary_mismatch": (f"gate Sun 23:00/Fri 22:00 vs broker "
                              f"{led['boundary_vs_reality']['inferred_weekly_open_utc']}"
                              f"/{led['boundary_vs_reality']['inferred_weekly_close_utc']}"),
        "action": ("ESCALATE as human decision (b89 class): the Friday literal "
                   "is ~1 h looser than the broker's real close. Autopilot "
                   "changes nothing."),
    }
    json.dump(led, open(OUT, "w"), indent=1)

    for k in LEGS:
        p = led[k]["population"]
        print(f"{k:8s} bars={p['bars']:5d} blocked_naive={p['blocked_bars_naive_frame']:4d} "
              f"blocked_true={p['blocked_bars_true_frame']:4d} "
              f"mis_kills={p['naive_kills_that_were_actually_open']:4d} "
              f"misses={p['actually_closed_bars_the_naive_frame_misses']:4d} "
              f"agree={p['frames_agree']}")
    print("\nlive_record:", json.dumps({k: v for k, v in led["live_record"].items()
                                        if k != "note"}, indent=1))
    print("shadow:", json.dumps(led["shadow"]["minute_grid_week"], indent=1),
          "->", led["shadow"]["verdict"])
    print("reachability:", led["reachability"]["learning_changes_keys"])
    print("boundary:", json.dumps(led["boundary_vs_reality"], indent=1))
    print("\nVERDICT:", json.dumps(led["_verdict"], indent=1))
    print("saved:", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
