#!/usr/bin/env python3
"""How many bars get FORCED to neutral by the range-kill rule (vs naturally neutral)?
If the rule is the dominant killer, an A/B on its threshold is warranted."""
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))

from datetime import datetime, timezone
from collections import Counter
from bridge_client import BridgeClient
from engines.context import build_plan_context
from engines.smc import smc_analyse, merge_smc_with_classic

b = BridgeClient()
def rows(tf, n):
    r = b.get_rates("XAUUSD", tf, n)
    return r.get("data", r.get("rates", [])) if r.get("ok") else []

m5, h1, h4 = rows("M5", 2400), rows("H1", 400), rows("H4", 200)
c = Counter()
for i in range(200, len(m5), 12):
    w = m5[max(0, i-120):i+1]; t = w[-1]["time"]
    now = datetime.fromtimestamp(t, tz=timezone.utc)
    h1w = [r for r in h1 if r["time"] <= t][-30:]; h4w = [r for r in h4 if r["time"] <= t][-15:]
    if len(h1w) < 10: continue
    sess = "asia" if now.hour < 7 else "london" if now.hour < 13 else "newyork"
    ctx = build_plan_context(w, h1w, h4w, sess)
    merged = merge_smc_with_classic(ctx, smc_analyse(w, now=now, h1_rows=h1w))
    regime = ctx.get("quality", {}).get("regime", "")
    conf = float(merged.get("confidence", 0) or 0)
    smc_bias = merged.get("bias", "neutral")
    classic_bias = ctx.get("bias", "neutral")
    forced = (regime == "range" and smc_bias != "neutral" and conf < 0.35)
    final = "neutral" if forced else (smc_bias if smc_bias != "neutral" else classic_bias)
    if final == "neutral":
        if forced:
            c["FORCED by range-kill"] += 1
        elif classic_bias == "neutral" and smc_bias == "neutral":
            c["both neutral (natural)"] += 1
        else:
            c["merge produced neutral"] += 1
    else:
        c[f"tradeable ({final})"] += 1
    c[f"regime:{regime}"] += 1
    if regime == "range":
        c[f"range&conf<0.35:{conf<0.35}"] += 1

for k, v in c.most_common(14):
    print(f"{v:4d}  {k}")
