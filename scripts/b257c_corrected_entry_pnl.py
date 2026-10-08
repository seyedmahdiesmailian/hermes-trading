"""b257-corrected: full production decision path with ROLLING H4 windows.

The first b257 run passed a FIXED h4[-80:] window for every H1 bar, which
made classic ctx bias 100% bearish (a harness artifact, not a code bug) and
inflated the short-skewed numbers. This version walks the H4 series by time
so each H1 bar sees only H4 bars closed before it — the causal contract the
production daemon has. Measures forward PnL of every market_entry_now verdict.
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

HOLD = 24


def load(name):
    with open(f"data/probe_{name}.json") as f:
        return json.load(f)


def run(step=6):
    h1 = load("h1_2500")
    h4 = load("h4_1200")
    m15 = load("m15_3000")
    n = len(h1)
    C = [r["close"] for r in h1]
    t4 = [r["time"] for r in h4]
    ents = []
    smc_b = Counter()
    for i in range(250, n - HOLD, step):
        t = h1[i]["time"]
        idx = max(0, sum(1 for x in t4 if x <= t) - 1)
        if idx < 80:
            continue
        h4w = h4[max(0, idx - 80):idx + 1]
        h1w = h1[max(0, i - 80):i]
        now = datetime.fromtimestamp(t, tz=timezone.utc)
        hour = now.hour
        sess = "asia" if 0 <= hour < 7 else ("london" if 7 <= hour < 13 else "newyork")
        smc = smc_analyse(execw(), now=now, h1_rows=h1w)
        ctx = build_plan_context(execw(), h1w, h4w, sess,
                                 m15_rows=list(m15[-80:]))
        merged = merge_smc_with_classic(ctx, smc)
        apply_smc_merge(ctx, merged, entry_close=C[i], smc_result=smc)
        plan = build_plan_from_context(ctx, now=now)
        d = decide_execution_action(plan, price=C[i], trigger_ok=True, now=now)
        smc_b[smc.get("bias")] += 1
        if d.get("action") != "market_entry_now":
            continue
        side = 1 if plan.get("bias") == "bullish" else -1
        ents.append((i, side))
    return ents, C, n, smc_b


_cache = []


def execw():
    if not _cache:
        m15 = load("m15_3000")
        _cache.append(m15[-120:])
    return _cache[0]


if __name__ == "__main__":
    ents, C, n, smc_b = run()
    tot = sum(s * (C[min(i + HOLD, n - 1)] - C[i]) for i, s in ents)
    wr = 100 * sum(1 for i, s in ents
                   if s * (C[min(i + HOLD, n - 1)] - C[i]) > 0) / max(len(ents), 1)
    print(f"CORRECTED (rolling H4): {len(ents)} entries  PnL {tot:+.2f}  wr {wr:.0f}%")
    print(f"smc bias dist: {dict(smc_b.most_common())}")
    for w in range(5):
        a, b = w * n // 5, (w + 1) * n // 5
        wt = [(i, s) for i, s in ents if a <= i < b]
        if wt:
            t = sum(s * (C[min(i + HOLD, n - 1)] - C[i]) for i, s in wt)
            print(f"  w{w}: {len(wt):3d}  {t:+8.2f}")
