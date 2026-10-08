#!/usr/bin/env python3
"""b92 (b87 queue, item 3: cooldown) — MEASURE THE COOLDOWN GATE.

b87's rule: for every live FILTER, run the bind test (does it ever reject a
trade the other gates would allow?) and the redundancy/shadow row, plus record
REACHABILITY (can learning.py move the knob?). b84 did min_rr, b86 range-kill,
b88 DEFCON. This file is the cooldown pass, and it produces a verdict of a kind
the earlier rounds never had to write: the gate is in a DIFFERENT DOMAIN than
the book.

What the gate is (engines/cooldown.py, called from auto_executor Check 6.7,
which BOTH entry paths — plan and signal — go through):

  post_open   blocks entries Sun 23:00 -> 23:15 UTC (15 min after the weekly
              XAUUSD open), recomputed from wall clock on every call.
  restart     blocks entries for 5 min after a REAL master restart (gap since
              the last master run >= 30 min; the b30 fix — cron runs master as
              a fresh process every 15 min, so "once per process" used to arm
              the guard on EVERY tick and killed 100% of entries).

Three questions, three measurement domains:

  Q1 BIND (book domain):  how many funnel signals fall inside the post-open
      window on cached + W1..W4? If the answer is zero on every leg, the b84/
      b86/b88 book template CANNOT price this gate — and the reason matters:
      the datasets are weekday-only (the fetch excludes the weekend), so the
      window the gate protects does not exist in the measurement medium at all.
      That is not "the gate is a no-op" (b86's verdict for range-kill); it is
      "the gate is unmeasurable as a book", which is a statement about the
      harness, not the gate.

  Q2 REACH (clock domain): what fraction of live trading time does the window
      cover, and how often does it actually arm? Computed two ways:
        - analytic: 15 min per week over the Sun 23:00 -> Fri 22:00 session;
        - live record: every master cycle in data/xau_plan/plan_history
          (created_at), gaps >= 30 min = a real restart = an armed guard.
      The restart clause is process-lifetime state — no market-time dataset can
      contain it, so the live cycle log is the ONLY honest medium for it.

  Q3 SHADOW (b87's own question): is the cooldown population already rejected
      by another live gate? The candidate is market_hours (Check 7.5): if the
      post-open window were outside trading hours, cooldown would be a shadow.
      is_market_open(Sun 23:05) says OPEN — so no, cooldown is the ONLY gate
      covering its window. The restart clause likewise shadows nothing and is
      shadowed by nothing: it is the sole protection against a cold-start entry
      on stale/unreconciled state.

  Q4 REACHABILITY: engines/learning.adjustments() moves min_rr / min_grade /
      risk_mult only. Neither cooldown constant is reachable — same finding
      class as b86's range-kill (a knob only an operator can move).

Verdict this round can produce, and nothing else:
  * gate is NOT proposed for removal anywhere (hard rule: never weaken a gate);
  * the honest statement is what b87 asked for: whether the gate MATTERS, and
    here the answer is "it is the only lock on a door the books cannot see" —
    so its protection is NOT provided by anything else, and its value can only
    be measured by a clock-domain replay, which this file ships as a probe.

Discipline: read-only, nothing imported by the live path, no gate moved, no
trade touched. The live-parity funnel comes from engines.backtest_real
(strategy_signal) exactly as b86/b88 use it — no hand-written funnel copy.
"""
import os
import sys
import json
import datetime as dt
from collections import Counter

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import cooldown as cd                                        # noqa: E402
from engines.market_hours import is_market_open                           # noqa: E402
from engines.backtest_real import strategy_signal                         # noqa: E402

OUT = "data/backtest/b92_cooldown_gate.json"
PLAN_HIST_DIR = "data/xau_plan/plan_history"
WINDOWS = ("W1", "W2", "W3", "W4")
LEGS = ("cached",) + WINDOWS
# b87's shadow candidate: the only other TIME-domain gate in the executor.
SHADOW_PROBE_TIMES = tuple(dt.datetime(2026, 8, 30, 23, m,
                                       tzinfo=dt.timezone.utc)
                           for m in (0, 5, 10, 14, 15, 20))


def _ts(row):
    """Bar time -> aware UTC datetime (the datasets mix s and ms epochs)."""
    t = float(row["time"])
    if t > 1e12:
        t /= 1000.0
    return dt.datetime.fromtimestamp(t, dt.timezone.utc)


def in_post_open(t: dt.datetime) -> bool:
    """Exactly the post_open clause of check_entry_cooldown, imported form."""
    opened = cd._market_open_utc(t)
    return t < opened + dt.timedelta(minutes=cd.POST_OPEN_COOLDOWN_MIN)


def _signals(m15, h1, h4):
    """The live-parity funnel population for a leg (b86's _pass, default knob)."""
    import bisect
    h1t = [r.get("time", 0) for r in h1]
    h4t = [r.get("time", 0) for r in h4]
    out = []
    for i, row in enumerate(m15):
        bt = row.get("time", 0)
        j1 = bisect.bisect_right(h1t, bt)
        j4 = bisect.bisect_right(h4t, bt)
        s = strategy_signal(row, h1[max(0, j1 - 80):j1], h4[max(0, j4 - 80):j4], i,
                            m15_window=m15[max(0, i - 120):i + 1])
        if s:
            out.append((bt, s))
    return out


def measure_leg(name, m15, h1, h4):
    unit = 1000.0 if m15[0]["time"] > 1e12 else 1.0
    dts = [_ts(r) for r in m15]
    wd = Counter(t.weekday() for t in dts)               # Mon=0..Sun=6
    sundays = sum(v for k, v in wd.items() if k == 6)
    sigs = _signals(m15, h1, h4)
    in_win = [(bt, s) for bt, s in sigs
              if in_post_open(dt.datetime.fromtimestamp(bt / unit, dt.timezone.utc))]
    return {
        "_bars": len(m15),
        "_first": dts[0].isoformat(), "_last": dts[-1].isoformat(),
        "_weekday_hist": {str(k): v for k, v in sorted(wd.items())},
        "_sunday_bars": sundays,
        "_signals": len(sigs),
        "_signals_in_post_open_window": len(in_win),
        # the b84/b86 book question, answered for the clock domain:
        "bind": {"signals_rejected_by_gate": len(in_win),
                 "book_is_measurable": sundays > 0},
    }


def measure_live_cycles():
    """The restart clause's real fire-rate: master cycle stamps in plan_history.

    A gap >= 30 min between consecutive created_at stamps is exactly the
    condition ensure_startup_cooldown uses to arm the 5-min guard (b30 rule),
    so the count of such gaps IS the count of times the gate armed in the live
    record — no market dataset can carry this fact, only the log can.
    """
    stamps = []
    for fn in sorted(os.listdir(PLAN_HIST_DIR)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(PLAN_HIST_DIR, fn), encoding="utf-8") as f:
                at = json.load(f).get("created_at")
            if at:
                stamps.append(dt.datetime.fromisoformat(at))
        except Exception:
            continue
    stamps.sort()
    gaps = []
    for a, b in zip(stamps, stamps[1:]):
        g = (b - a).total_seconds() / 60.0
        if g >= 30:
            gaps.append({"from": a.isoformat(), "to": b.isoformat(),
                         "gap_min": round(g, 1)})
    span_days = ((stamps[-1] - stamps[0]).total_seconds() / 86400.0
                 if len(stamps) >= 2 else 0.0)
    return {"cycles": len(stamps),
            "first": stamps[0].isoformat() if stamps else None,
            "last": stamps[-1].isoformat() if stamps else None,
            "span_days": round(span_days, 2),
            "restart_guard_armed": len(gaps),
            "gaps": gaps,
            "blocked_cycles_per_arm": 1,
            "note": ("each arm blocks the cycle that armed it for "
                     f"{cd.RESTART_COOLDOWN_MIN} min; the next cron tick is at "
                     "+15 min, outside the guard, so one arm costs at most one "
                     "cycle — the b30 fix made the guard proportional")}


def measure_reach():
    """Analytic clock-domain reach of the post_open window."""
    # weekly session Sun 23:00 -> Fri 22:00 UTC = 117 h
    session_min = 117 * 60
    return {"window_min": cd.POST_OPEN_COOLDOWN_MIN,
            "session_min_per_week": session_min,
            "share_of_trading_time": round(cd.POST_OPEN_COOLDOWN_MIN / session_min, 5),
            "windows_per_week": 1,
            "restart_window_min": cd.RESTART_COOLDOWN_MIN,
            "restart_armed_by_gap_min": 30}


def measure_shadow():
    """b87's redundancy row, in the clock domain: does market_hours already
    cover the post_open window? Probe the exact minutes the gate protects."""
    rows = []
    for t in SHADOW_PROBE_TIMES:
        rows.append({"at": t.isoformat(),
                     "cooldown_blocks": in_post_open(t),
                     "market_hours_allows": is_market_open(t)})
    both = [r for r in rows if r["cooldown_blocks"] and not r["market_hours_allows"]]
    only_cd = [r for r in rows if r["cooldown_blocks"] and r["market_hours_allows"]]
    return {"probe": rows,
            "shadowed_by_market_hours": len(both),
            "covered_only_by_cooldown": len(only_cd),
            "verdict": ("SHADOWED" if only_cd == [] and both else
                        "NOT_SHADOWED — cooldown is the only gate on its window")}


def measure_reachability():
    from engines.learning import adjustments
    adj = adjustments()
    return {"learning_changes_keys": sorted((adj.get("changes") or {}).keys()),
            "learning_can_move_cooldown": False,
            "constants": {"POST_OPEN_COOLDOWN_MIN": cd.POST_OPEN_COOLDOWN_MIN,
                          "RESTART_COOLDOWN_MIN": cd.RESTART_COOLDOWN_MIN},
            "note": ("both knobs are module literals; learning.py adjusts "
                     "min_rr/min_grade/risk_mult only (same class as b86's "
                     "range-kill: operator-only reach)")}


def main():
    led = {"_note": ("b92 (b87 queue item 3): the COOLDOWN gate measured in its "
                     "own domain. Book test on cached+W1..W4 (live-parity "
                     "strategy_signal), clock test on the live master-cycle log, "
                     "shadow test against market_hours, reachability against "
                     "learning.adjustments(). Read-only; nothing wired; no gate "
                     "weakened."),
           "_live_gates": {"POST_OPEN_COOLDOWN_MIN": cd.POST_OPEN_COOLDOWN_MIN,
                           "RESTART_COOLDOWN_MIN": cd.RESTART_COOLDOWN_MIN,
                           "restart_gap_min": 30}}
    c = json.load(open("data/backtest/ab_aggressive_data.json"))
    led["cached"] = measure_leg("cached", c["M15"], c["H1"], c["H4"])
    wins = json.load(open("data/backtest/b68l_independent_windows.json"))
    for w in WINDOWS:
        led[w] = measure_leg(w, wins[w]["M15"], wins[w]["H1"], wins[w]["H4"])
    led["live_cycles"] = measure_live_cycles()
    led["reach"] = measure_reach()
    led["shadow"] = measure_shadow()
    led["reachability"] = measure_reachability()

    legs = [led[k] for k in LEGS]
    led["_verdict"] = {
        "legs": len(legs),
        "sunday_bars_total": sum(l["_sunday_bars"] for l in legs),
        "signals_in_window_total": sum(l["_signals_in_post_open_window"]
                                       for l in legs),
        "book_can_price_this_gate": all(l["bind"]["book_is_measurable"]
                                        for l in legs),
        "restart_arms_in_live_record": led["live_cycles"]["restart_guard_armed"],
        "shadow_verdict": led["shadow"]["verdict"],
        "adaptive_reachable": led["reachability"]["learning_can_move_cooldown"],
    }
    json.dump(led, open(OUT, "w"), indent=1)

    print(f"{'leg':8s} {'bars':>6s} {'sundays':>8s} {'sigs':>6s} {'in-window':>9s}")
    for k in LEGS:
        L = led[k]
        print(f"{k:8s} {L['_bars']:6d} {L['_sunday_bars']:8d} {L['_signals']:6d} "
              f"{L['_signals_in_post_open_window']:9d}")
    print("\nlive cycles:", json.dumps({k: v for k, v in led["live_cycles"].items()
                                        if k != "gaps"}, indent=1))
    print("gaps:", json.dumps(led["live_cycles"]["gaps"], indent=1))
    print("\nreach:", led["reach"])
    print("\nshadow:", json.dumps(led["shadow"], indent=1))
    print("\nVERDICT:", json.dumps(led["_verdict"], indent=1))
    print("\nsaved:", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
