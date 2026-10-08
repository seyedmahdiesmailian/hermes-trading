"""b259 MTF scan: run the production decision path on EVERY timeframe and
measure which cadences carry edge, using fully causal rolling windows.

The user wants: scan M5/M15/M30/H1/H4/D1 and enter on whichever TF shows a
good setup. This measures whether the individual TFs are profitable BEFORE
wiring them into a scanner, so we do not add unprofitable TFs to the live loop.
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

FILES = {"M5": "m5_20000", "M15": "m15_20000", "M30": "m30_6000",
         "H1": "h1_6000", "H4": "h4_3000", "D1": "d1_500"}
SPAN = {"M5": 200, "M15": 120, "M30": 100, "H1": 80, "H4": 60, "D1": 40}
STEP = {"M5": 24, "M15": 24, "M30": 12, "H1": 6, "H4": 4, "D1": 2}
HOLD_H = {"M5": 4, "M15": 8, "M30": 12, "H1": 24, "H4": 96, "D1": 336}


def load(name):
    with open(f"data/probe_{name}.json") as f:
        return json.load(f)


def main():
    h1 = load("h1_6000")
    h4 = load("h4_3000")
    t1 = [r["time"] for r in h1]
    t4 = [r["time"] for r in h4]
    h1map = {r["time"]: r["close"] for r in h1}

    def price_at(t):
        ks = [k for k in h1map if k >= t]
        return h1map[min(ks)] if ks else None

    for tf, key in FILES.items():
        rows = load(key)
        span = SPAN[tf]
        step = STEP[tf]
        hold_s = HOLD_H[tf] * 3600
        nR = len(rows)
        ents = []
        tG = [r["time"] for r in rows]
        for j in range(span, nR, step):
            t = rows[j]["time"]
            i4 = max(0, sum(1 for x in t4 if x <= t) - 1)
            i1 = max(0, sum(1 for x in t1 if x <= t) - 1)
            if i4 < 80 or i1 < 80:
                continue
            ew = rows[max(0, j - span):j + 1]
            h1w = h1[max(0, i1 - 80):i1 + 1]
            h4w = h4[max(0, i4 - 80):i4 + 1]
            now = datetime.fromtimestamp(t, tz=timezone.utc)
            hour = now.hour
            sess = "asia" if 0 <= hour < 7 else ("london" if 7 <= hour < 13 else "newyork")
            try:
                smc = smc_analyse(ew, now=now, h1_rows=h1w)
                ctx = build_plan_context(ew, h1w, h4w, sess,
                                         m15_rows=list(rows[max(0, j - 80):j + 1]))
                merged = merge_smc_with_classic(ctx, smc)
                apply_smc_merge(ctx, merged, entry_close=rows[j]["close"],
                                smc_result=smc)
                plan = build_plan_from_context(ctx, now=now)
                d = decide_execution_action(plan, price=rows[j]["close"],
                                            trigger_ok=True, now=now)
            except Exception:
                continue
            if d.get("action") != "market_entry_now":
                continue
            side = 1 if plan.get("bias") == "bullish" else -1
            ents.append((t, side, rows[j]["close"]))
        tot = 0
        cnt = 0
        for t, s, p in ents:
            fwd = price_at(t + hold_s)
            if fwd is None:
                continue
            tot += s * (fwd - p)
            cnt += 1
        days = (rows[-1]["time"] - rows[0]["time"]) / 86400
        per = tot / max(cnt, 1)
        print(f"{tf:4s}: {cnt:4d} entries  {cnt / max(days, 1):5.1f}/day  "
              f"PnL {tot:+9.2f}  per-trade {per:+7.2f}  ({days:.0f}d)")


if __name__ == "__main__":
    main()
