#!/usr/bin/env python3
"""b2: measure the funnel on LIVE timeframe (M5) — why entries die.

Distribution of trend_strength / alignment / smc_confidence / setup grade
over ~2000 real M5 bars, plus how often each entry path fires.
Read-only.
"""
import sys, json
sys.path.insert(0, '/home/ai/hermes-trading')
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv('/home/ai/hermes-trading/.env')

from datetime import datetime, timezone
from collections import Counter
from bridge_client import BridgeClient
from engines.context import build_plan_context
from engines.smc import smc_analyse, merge_smc_with_classic
from engines.orchestrator import build_plan_from_context, evaluate_monitor_cycle

b = BridgeClient()

def rows(tf, n):
    r = b.get_rates("XAUUSD", tf, n)
    return r.get("data", r.get("rates", [])) if r.get("ok") else []

m5 = rows("M5", 2400)      # ~8 trading days
h1 = rows("H1", 400)
h4 = rows("H4", 200)
print(f"bars: m5={len(m5)} h1={len(h1)} h4={len(h4)}")

ts_vals, grades, actions, aligns, confs = [], Counter(), Counter(), Counter(), []
STEP = 12  # sample every hour
for i in range(200, len(m5), STEP):
    w_m5 = m5[max(0, i-120):i+1]
    t = w_m5[-1]["time"]
    now = datetime.fromtimestamp(t, tz=timezone.utc)
    h1w = [r for r in h1 if r["time"] <= t][-30:]
    h4w = [r for r in h4 if r["time"] <= t][-15:]
    if len(h1w) < 10:
        continue
    sess = "asia" if now.hour < 7 else "london" if now.hour < 13 else "newyork"
    ctx = build_plan_context(w_m5, h1w, h4w, sess)
    smc = smc_analyse(w_m5, now=now, h1_rows=h1w)
    merged = merge_smc_with_classic(ctx, smc)
    if ctx.get("quality", {}).get("regime") == "range" and merged.get("bias") != "neutral" and (merged.get("confidence") or 0) < 0.35:
        ctx["bias"] = "neutral"
    else:
        ctx["bias"] = merged.get("bias", ctx.get("bias"))
    ctx.setdefault("quality", {})["smc_confidence"] = merged.get("confidence")
    q = ctx.get("quality", {})
    ts = float(q.get("trend_strength", 0) or 0)
    ts_vals.append(ts)
    aligns[q.get("alignment", "?")] += 1
    confs.append(float(q.get("smc_confidence", 0) or 0))
    # grade exactly as runtime computes it
    from hermes_runtime import _infer_setup_grade
    plan = build_plan_from_context(ctx, now=now)
    grades[_infer_setup_grade(plan)] += 1
    act = evaluate_monitor_cycle(plan, w_m5[-1]["close"], now)
    actions[act.get("action")] += 1

import statistics as s
n = len(ts_vals)
print(f"\nsamples: {n}")
print(f"trend_strength (M5): median={s.median(ts_vals):.2f} p25={sorted(ts_vals)[n//4]:.2f} p75={sorted(ts_vals)[3*n//4]:.2f} max={max(ts_vals):.2f}")
print(f"smc_confidence: median={s.median(confs):.2f} p75={sorted(confs)[3*n//4]:.2f} max={max(confs):.2f}")
print(f"alignment: {dict(aligns)}")
print(f"grade: {dict(grades)}  (gate needs >= B)")
print(f"actions: {dict(actions)}")
