#!/usr/bin/env python3
"""b78 — GRADE-PARITY CENSUS: were my b72/b74 fire counts inflated?

b74 counted 34 market_entry_now fires over 600 M5 bars by replaying
evaluate_monitor_cycle. But evaluate_monitor_cycle is only the MONITOR — the
live path then hands the blueprint to auto_executor.evaluate_proposal, whose
Check 6 kills every setup_grade == C plan (MIN_SETUP_GRADE="B"), and whose
poor_rr / invalid_geometry checks kill more. engines/backtest_real applies
grade parity (b108 note), but b74's census called the monitor directly —
so any fire whose plan has alignment='mixed' (setup_grade can ONLY be C per
b45: mixed never qualifies for B) was counted as a live opportunity in my
gap analysis when live could NEVER take it. That inflates the sim/live gap.

Measured tonight on the Sep-9 morning: 3 of the 4 blocked fires were exactly
this — aggressive_premium_entry on mixed-alignment plans, monitor fires,
executor C-kills. Guaranteed-dead fires.

This script re-classifies b74's fire list with FULL executor parity
(grade + reanchored RR + invalid geometry, no news/spread/cooldown —
those are logged separately when they bind) and reports:
  fires_raw -> fires that survive executor parity -> fires on-grid -> survive-to-grid.
If the parity count is far below 34, the b74 narrative needs correcting
and the real funnel problem is upstream of the clock.

Read-only. No gates touched.
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); os.chdir(_ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

from bridge_client import BridgeClient
from engines.backtest_real import build_plan_context, settled_m5_rows, M5_BAR_SECONDS
from engines.smc import smc_analyse, merge_smc_with_classic
from engines.plan import apply_smc_merge
from engines.orchestrator import evaluate_monitor_cycle, _passes_quality_gate, build_plan_from_context
from engines.auto_executor import evaluate_proposal, MIN_SETUP_GRADE
from hermes_runtime import _infer_setup_grade

M5_BARS = 600; H1_BARS = 1100; H4_BARS = 700
GRID = (0, 15, 30, 45)


def main():
    b = BridgeClient()
    acc = (b.get_account().get("data") or {})
    bal = float(acc.get("balance") or acc.get("equity") or 5000.0)
    from engines.risk import assess_account_policy
    POLICY = assess_account_policy(bal, float(acc.get("equity") or bal),
                                   float(acc.get("margin_free") or bal),
                                   float(acc.get("margin") or 0), 0.0, 0, 0)
    print(f"real balance={bal} base_risk_pct={POLICY.get('base_risk_pct')}")
    m5 = sorted(b.get_rates("XAUUSD", "M5", M5_BARS).get("data", []), key=lambda r: int(r["time"]))[:-1]
    h1 = sorted(b.get_rates("XAUUSD", "H1", H1_BARS).get("data", []), key=lambda r: int(r["time"]))[:-1]
    h4 = sorted(b.get_rates("XAUUSD", "H4", H4_BARS).get("data", []), key=lambda r: int(r["time"]))[:-1]
    fires = []
    for k in range(120, len(m5)):
        row = m5[k]; rt = int(row["time"])
        w_m5 = [r for r in m5[:k + 1] if int(r["time"]) >= rt - 120 * 300]
        w_h1 = [r for r in h1 if rt - 80 * 3600 <= int(r["time"]) < rt + 3600]
        w_h4 = [r for r in h4 if rt - 80 * 14400 <= int(r["time"]) < rt + 14400]
        now = datetime.fromtimestamp(rt + M5_BAR_SECONDS, tz=timezone.utc)
        h = now.hour
        session = "asia" if h < 7 else ("london" if h < 13 else "newyork")
        ctx = build_plan_context(w_m5[-120:], w_h1[-80:], w_h4[-80:], session)
        sm = smc_analyse(w_m5[-120:], now=now, h1_rows=w_h1[-80:])
        merged = merge_smc_with_classic(ctx, sm)
        apply_smc_merge(ctx, merged, entry_close=float(row["close"]))
        plan = build_plan_from_context(ctx, now=now)
        m5_rows = settled_m5_rows(w_m5, rt + M5_BAR_SECONDS) or None
        dec = evaluate_monitor_cycle(plan, price=float(row["close"]), now=now, m5_rows=m5_rows)
        if dec.get("action") != "market_entry_now":
            continue
        bp = dec.get("blueprint") or {}
        # FULL executor parity (this is what b74 skipped). REAL account state
        # via read-only bridge (b78 v1 bug: passing {} made balance=0 and
        # killed 13 sizing-eligible fires with a fake sizing_below error).
        prop = {"blueprint": bp, "monitor_action": dec.get("action"),
                "zone": dec.get("zone"), "price": float(row["close"]),
                "execution_style": dec.get("execution_style")}
        ex = evaluate_proposal(prop, POLICY, {"trades_today": 0, "daily_pnl": 0.0, "loss_streak": 0}, plan, None)
        fires.append({
            "t": rt + M5_BAR_SECONDS, "decision_utc": now.strftime("%m-%d %H:%M"),
            "bias": plan.get("bias"), "style": dec.get("execution_style"),
            "align": (plan.get("quality") or {}).get("alignment"),
            "grade": _infer_setup_grade(plan),
            "qgate": _passes_quality_gate(plan),
            "exec_ok": bool(ex.get("execute")),
            "exec_reason": ex.get("reason"),
            "on_grid": now.minute % 15 == 0,
        })
    raw = len(fires)
    par = [f for f in fires if f["exec_ok"]]
    ong = [f for f in fires if f["on_grid"]]
    ong_par = [f for f in par if f["on_grid"]]
    from collections import Counter
    kill_reasons = Counter(f["exec_reason"] for f in fires if not f["exec_ok"])
    print(f"RAW monitor fires: {raw}")
    print(f"survive FULL executor parity: {len(par)}")
    print(f"  on-grid (raw): {len(ong)} | on-grid (parity): {len(ong_par)}")
    print(f"  kill reasons: {dict(kill_reasons)}")
    print(f"  grades of parity survivors: {Counter(f['grade'] for f in par)}")
    print(f"  styles of parity survivors: {Counter(f['style'] for f in par)}")
    json.dump(fires, open("data/backtest/b78_grade_parity_census.json", "w"), indent=1)
    print("saved -> data/backtest/b78_grade_parity_census.json")


if __name__ == "__main__":
    main()
