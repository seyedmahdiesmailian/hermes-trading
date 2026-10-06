"""b257: does decide_execution_action's entries actually make money?

Replays the FULL production decision path (build_plan_context -> smc_analyse ->
merge_smc_with_classic -> apply_smc_merge -> build_plan_from_context ->
decide_execution_action) on fresh multi-TF data, and measures forward PnL
from every market_entry_now verdict.

CRUCIAL: this replays the same M15 execution window every tick, which is what
the production daemon does. The H1 sample index is the true entry index.
"""
import json, os, sys
from datetime import datetime, timezone
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines.context import build_plan_context
from engines.smc import smc_analyse, merge_smc_with_classic
from engines.plan import apply_smc_merge, decide_execution_action
from engines.orchestrator import build_plan_from_context

HOLD = 12


def load(name):
    with open(f"data/probe_{name}.json") as f:
        return json.load(f)


def run(h1_path, m_exec, label, step=6):
    h1 = load(h1_path)
    h4 = load("h4_1200")
    m15 = load("m15_3000")
    execw = m15[-120:]
    n = len(h1)
    C = [r["close"] for r in h1]
    trades = []
    for i in range(250, n - HOLD, step):
        h1w = h1[max(0, i - 80):i]
        now = datetime.fromtimestamp(h1[i]["time"], tz=timezone.utc)
        hour = now.hour
        sess = "asia" if 0 <= hour < 7 else ("london" if 7 <= hour < 13 else "newyork")
        smc = smc_analyse(execw, now=now, h1_rows=h1w)
        ctx = build_plan_context(execw, h1w, list(h4[-80:]), sess,
                                 m15_rows=list(m15[-80:]))
        merged = merge_smc_with_classic(ctx, smc)
        apply_smc_merge(ctx, merged, entry_close=C[i], smc_result=smc)
        plan = build_plan_from_context(ctx, now=now)
        d = decide_execution_action(plan, price=C[i], trigger_ok=True, now=now)
        if d.get("action") != "market_entry_now":
            continue
        move = C[min(i + HOLD, n - 1)] - C[i]
        side = 1 if plan.get("bias") == "bullish" else -1
        trades.append((i, side * move))
    tot = sum(x[1] for x in trades)
    wins = sum(1 for x in trades if x[1] > 0)
    print(f"=== {label} ({len(trades)} trades) ===")
    if not trades:
        print("  no entries")
        return
    print(f"  total {tot:+.2f}  wr {100*wins/len(trades):.0f}%  per-trade {tot/len(trades):+.2f}")
    # 5 disjoint index windows
    for w in range(5):
        a, b = w * n // 5, (w + 1) * n // 5
        wt = [x for x in trades if a <= x[0] < b]
        if wt:
            print(f"    w{w}: {len(wt):3d}  {sum(x[1] for x in wt):+8.2f}")
        else:
            print(f"    w{w}: 0 trades")


if __name__ == "__main__":
    run("h1_2500", "m15_3000", "H1 entries, M15 execution TF")
