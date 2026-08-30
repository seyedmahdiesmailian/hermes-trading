#!/usr/bin/env python3
"""b3: funnel attribution — for each bar that produced market_entry_now,
which EXECUTOR gate would kill it? (grade / rr / cooldown / macro)
Uses the real executor on real M5 data. Read-only."""
import sys
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
from engines.auto_executor import evaluate_proposal
from hermes_runtime import _infer_setup_grade

b = BridgeClient()
def rows(tf, n):
    r = b.get_rates("XAUUSD", tf, n)
    return r.get("data", r.get("rates", [])) if r.get("ok") else []

m5, h1, h4 = rows("M5", 2400), rows("H1", 400), rows("H4", 200)
policy = {'balance': 5070.41, 'equity': 5070.41, 'margin_free': 5000, 'margin': 0,
          'regime': 'normal', 'trade_allowed': True, 'open_positions': 0, 'drawdown_pct': 0}
perf = {'daily_pnl': 0.0, 'trades_today': 0, 'loss_streak': 0, 'recent_closed': []}

kill = Counter(); entered = 0; total = 0
for i in range(200, len(m5), 12):
    w = m5[max(0, i-120):i+1]; t = w[-1]["time"]
    now = datetime.fromtimestamp(t, tz=timezone.utc)
    h1w = [r for r in h1 if r["time"] <= t][-30:]; h4w = [r for r in h4 if r["time"] <= t][-15:]
    if len(h1w) < 10: continue
    total += 1
    sess = "asia" if now.hour < 7 else "london" if now.hour < 13 else "newyork"
    ctx = build_plan_context(w, h1w, h4w, sess)
    merged = merge_smc_with_classic(ctx, smc_analyse(w, now=now, h1_rows=h1w))
    if ctx.get("quality", {}).get("regime") == "range" and merged.get("bias") != "neutral" and (merged.get("confidence") or 0) < 0.35:
        ctx["bias"] = "neutral"
    else:
        ctx["bias"] = merged.get("bias", ctx.get("bias"))
    ctx.setdefault("quality", {})["smc_confidence"] = merged.get("confidence")
    plan = build_plan_from_context(ctx, now=now)
    act = evaluate_monitor_cycle(plan, w[-1]["close"], now)
    if act.get("action") != "market_entry_now":
        kill[f"pre:{act.get('action')}:{str(act.get('reason'))[:22]}"] += 1
        continue
    bp = act.get("blueprint") or {}
    proposal = {'blueprint': bp, 'monitor_action': 'market_entry_now', 'zone': act.get('zone'),
                'price': bp.get('entry_price'), 'at': now.isoformat()}
    res = evaluate_proposal(proposal, policy, perf, plan, b)
    if res.get('execute'):
        entered += 1
        kill["EXECUTED"] += 1
    else:
        kill[f"exec:{res.get('reason')}"] += 1

print(f"bars sampled: {total}")
for k, v in kill.most_common(14):
    print(f"{v:4d}  {k}")
print(f"\nSURVIVORS (would trade): {entered} in {total} hourly samples")
