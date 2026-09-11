#!/usr/bin/env python3
"""b74 — THE SIM/LIVE FIRE-RATE GAP: is it a bug or just clock alignment?

Finding (b72, 2026-09-11): the sanctioned funnel fired 9 market_entry_now on
Sep 10-11 in the lab while LIVE fired zero on the same bars, same code. The
user's complaint ("zero trades") traces to this seam.

Hypotheses to separate, by measurement:
  H1 CLOCK — the lab decides on EVERY settled M5 close (600 moments/day);
     live decides on the 15-min cron grid (96 moments/day, at :00/:15/:30/:45
     bar closes). Signals that appear and die between grid points are real
     signals the live clock cannot see.
  H2 PLAN-STALE — live evaluates the plan built up-to-15-min-ago against
     today's price (zone drift, staleness veto); the lab rebuilds context at
     every bar. Same funnel, different input freshness.
  H3 BUG — something else (offset, session, guards).

METHOD: same funnel as b72 (evaluate_monitor_cycle per bar with live plan
paths), but tag every market_entry_now fire by its minute mod 15:
  on-grid   minute in {0,15,30,45}  <- live COULD see it (same bar boundary)
  off-grid  everything else         <- invisible to the 15-min cron
Then re-run the decision at the NEXT grid boundary using the plan as it was
then (live semantics): does the fire survive 5-10min of staleness?
Count how many of the lab's fires would still fire under live clock+stale
plan. That number is the honest live-parity expectation.

Read-only research.
"""
from __future__ import annotations
import json, os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); os.chdir(_ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

from bridge_client import BridgeClient
from engines.context import build_plan_context
from engines.smc import smc_analyse, merge_smc_with_classic
from engines.plan import apply_smc_merge
from engines.orchestrator import build_plan_from_context, evaluate_monitor_cycle
from engines.backtest_real import settled_m5_rows
from datetime import datetime, timezone

M5_BARS = 600


def main():
    b = BridgeClient()
    rows = sorted(b.get_rates("XAUUSD", "M5", M5_BARS).get("data", []), key=lambda r: int(r["time"]))
    h1 = sorted(b.get_rates("XAUUSD", "H1", 900).get("data", []), key=lambda r: int(r["time"]))
    h4 = sorted(b.get_rates("XAUUSD", "H4", 900).get("data", []), key=lambda r: int(r["time"]))

    def decide(i, price, use_fresh_ctx=True):
        row = rows[i]
        t = int(row["time"])
        now = datetime.fromtimestamp(t, tz=timezone.utc)
        h = now.hour
        session = "asia" if h < 7 else ("london" if h < 13 else "newyork")
        w = rows[max(0, i - 120):i + 1]
        ctx = build_plan_context(w[-120:], [r for r in h1 if int(r["time"]) <= t][-80:],
                                 [r for r in h4 if int(r["time"]) <= t][-80:], session)
        s = smc_analyse(w[-120:], now=now, h1_rows=[r for r in h1 if int(r["time"]) <= t][-80:])
        apply_smc_merge(ctx, merge_smc_with_classic(ctx, s), entry_close=float(row["close"]), range_kill_conf=0.35)
        plan = build_plan_from_context(ctx, now=now)
        m5r = settled_m5_rows(w, t + 300) or None
        return evaluate_monitor_cycle(plan, price=price, now=now, m5_rows=m5r), plan

    fires = []
    for i in range(130, len(rows)):
        t = int(rows[i]["time"])
        dec, _plan = decide(i, float(rows[i]["close"]))
        if dec.get("action") == "market_entry_now":
            minute = datetime.fromtimestamp(t, tz=timezone.utc).minute
            # M5 row time is the OPEN; the decision moment is its close
            # (t+300). Live cron fires at :00/:15/:30/:45, i.e. sees closes
            # of the bars opened at :55/:10/:25/:40 -> minute % 15 == 10.
            on_grid_minute = (minute + 5) % 15 == 0
            fires.append({"t": datetime.fromtimestamp(t, tz=timezone.utc).strftime("%m-%d %H:%M"),
                          "price": round(float(rows[i]["close"]), 2), "minute": minute,
                          "grid": on_grid_minute})

    on_grid = [f for f in fires if f["grid"]]
    off_grid = [f for f in fires if not f["grid"]]
    # For each off-grid fire: does it SURVIVE to the next live cycle? Live
    # decides at :00/:15/:30/:45; the fire's signal bar must still produce
    # market_entry_now at the NEXT such moment (fresh live semantics there).
    survive = []
    times = [int(r["time"]) for r in rows]
    for f in off_grid:
        ti = next((j for j, r in enumerate(rows)
                   if datetime.fromtimestamp(int(r["time"]), tz=timezone.utc).strftime("%m-%d %H:%M") == f["t"]), None)
        if ti is None: continue
        for k in range(ti + 1, min(ti + 5, len(rows))):
            if (datetime.fromtimestamp(times[k], tz=timezone.utc).minute + 5) % 15 == 0:
                dec2, _ = decide(k, float(rows[k]["close"]))
                survive.append({"orig": f["t"], "boundary": datetime.fromtimestamp(times[k], tz=timezone.utc).strftime("%H:%M"),
                                "still": dec2.get("action") == "market_entry_now"})
                break

    print("lab fires:", len(fires), "| on-grid:", len(on_grid), "| off-grid:", len(off_grid))
    st_ok = sum(1 for s in survive if s["still"])
    print("off-grid fires tested at boundary:", len(survive), "| survive:", st_ok)
    for f in fires:
        print(" ", f["t"], f["price"], "grid" if f["minute"] % 15 == 0 else "off")
    for s in survive[:12]:
        print("  boundary recheck:", s)


if __name__ == "__main__":
    main()
