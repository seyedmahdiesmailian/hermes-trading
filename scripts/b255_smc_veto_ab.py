"""A/B the smc.py:715 veto floor on real H1 data (b255).

A = current: bias==neutral OR bias_confidence<0.4 -> ("wait", 0.0)
B = counterfactual: allow through, confidence scaled down.

Measures trade PnL over 5 disjoint index-sliced windows (discipline rule).
"""
import json, os, sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines.context import build_plan_context
from engines.smc import smc_analyse, merge_smc_with_classic
from engines.plan import apply_smc_merge
from engines.orchestrator import build_plan_from_context
from bridge_client import BridgeClient

h1 = json.load(open("data/probe_h1_5000.json"))
n = len(h1)
C = [r["close"] for r in h1]
br = BridgeClient()
h4 = (br.get_rates("XAUUSD", "H4", 400) or {}).get("data", [])
m15 = (br.get_rates("XAUUSD", "M15", 400) or {}).get("data", [])
h4w = list(h4[-80:])
m5w = list(m15[-120:]) if len(m15) >= 120 else list(m15)
m15w = list(m15[-80:])

HOLD = 12
trades = {"A": [], "B": []}

for i in range(200, n - HOLD, 5):
    h1w = h1[max(0, i - 80):i]
    now = datetime.fromtimestamp(h1[i]["time"], tz=timezone.utc)
    hour = now.hour
    sess = "asia" if 0 <= hour < 7 else ("london" if 7 <= hour < 13 else "newyork")
    ctx = build_plan_context(m5w, h1w, h4w, sess, m15_rows=m15w)
    smc = smc_analyse(m5w, now=now, h1_rows=h1w)
    merged = merge_smc_with_classic(ctx, smc)
    apply_smc_merge(ctx, merged, entry_close=C[i], smc_result=smc)
    plan = build_plan_from_context(ctx, now=now)
    b = plan.get("bias")
    move = C[min(i + HOLD, n - 1)] - C[i]
    if b == "bullish":
        trades["A"].append((i, move))
    elif b == "bearish":
        trades["A"].append((i, -move))
    # B: same but treat smc bias directly when plan is neutral
    sb = smc.get("bias")
    if b in ("bullish", "bearish"):
        trades["B"].append((i, move if b == "bullish" else -move))
    elif sb in ("bullish", "bearish"):
        trades["B"].append((i, move if sb == "bullish" else -move))

for k in ("A", "B"):
    t = trades[k]
    tot = sum(x[1] for x in t)
    wins = sum(1 for x in t if x[1] > 0)
    print(f"[{k}] trades {len(t)}  total {tot:+.2f}  wr {100*wins/max(len(t),1):.0f}%")
    for wi in range(5):
        a, bw = wi * n // 5, (wi + 1) * n // 5
        wt = [x for x in t if a <= x[0] < bw]
        print(f"     w{wi}: {len(wt):3d}  {sum(x[1] for x in wt):+8.2f}")
