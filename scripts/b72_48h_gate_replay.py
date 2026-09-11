#!/usr/bin/env python3
"""b72 — 48h live-funnel replay: DEPLOYED gate vs a ~20% looser quality gate.

Answers the user's exact question (2026-09-11): "were there no good entries in
these two days, or did your gates just strangle everything?"

Method (HARD RULE from b189/b191: sanctioned funnel only, never hand-copied):
  * entry stream = the freshest ~1 day of M5 bars the bridge has (covers
    Sep 10-11; MT5 prints no weekend bars, so the 48h window is 24 trading h)
  * both arms call engines.backtest_real.run_backtest identically; the ONLY
    difference is the quality-gate thresholds (deployed: trend>=1.0 or
    smc>=0.4  vs  looser: trend>=0.8 or smc>=0.32  ~20%).
  * exit geometry from lab_harness (LADDER + live time stop + MIN_RR + grade
    gate) — the deployed b187/b193/b204 stack.
  * a counter wraps evaluate_monitor_cycle to record, per decision moment,
    whether market_entry_now was vetoed by quality_filter (the looser arm's
    extra candidates) — so the delta is NAMED, not inferred from book diffs.

Read-only research. No live gate, lot, or file is touched.
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
from engines import lab_harness as lh
from engines.backtest_real import fetch_all_ohlc, run_backtest
import engines.orchestrator as orch
from datetime import datetime, timezone

M5_BARS = 600          # 600 * 5min = 50 trading h (~2 days, no weekend bars)
H1_BARS = 1100         # covers M5 span + 80-bar warm-up with pad
LOOSE_TREND, LOOSE_SMC = 0.8, 0.32
OUT = "data/backtest/b72_48h_gate_replay.json"


def _harness_kwargs(rows):
    ts = lh.live_time_stop_bars(rows)
    kw = dict(lh.LADDER)
    kw.update(min_rr=lh.MIN_RR, min_grade=lh.LIVE_MIN_GRADE,
              time_stop_bars=ts, spread_override=lh.SPREAD)
    return kw, ts


def gate_census(rows, ctx, ts):
    """Replay decisions directly through evaluate_monitor_cycle to log every
    quality_filter veto with its plan metrics (deployed thresholds)."""
    from engines.context import build_plan_context
    from engines.smc import smc_analyse, merge_smc_with_classic
    from engines.plan import apply_smc_merge
    from engines.orchestrator import build_plan_from_context
    vetoed, fired = [], []
    idx = {id(r): i for i, r in enumerate(rows)}
    for row in rows[130:]:
        i = idx[id(row)]
        t = int(row["time"])
        m5_window = rows[max(0, i - 120):i + 1]
        h1w = [r for r in ctx["H1"] if int(r["time"]) <= t][-80:]
        h4w = [r for r in ctx["H4"] if int(r["time"]) <= t][-80:]
        if len(h1w) < 10 or len(m5_window) < 30:
            continue
        now = datetime.fromtimestamp(t, tz=timezone.utc)
        try:
            c = build_plan_context(m5_window[-120:], h1w, h4w, "newyork" if now.hour >= 13 else ("london" if now.hour >= 7 else "asia"))
            s = smc_analyse(m5_window[-120:], now=now, h1_rows=h1w)
            m = merge_smc_with_classic(c, s)
            apply_smc_merge(c, m, entry_close=float(row["close"]), range_kill_conf=0.35)
            plan = build_plan_from_context(c, now=now)
            from engines.backtest_real import settled_m5_rows
            m5r = settled_m5_rows(m5_window, t + 300) or None
            dec = orch.evaluate_monitor_cycle(plan, price=float(row["close"]), now=now, m5_rows=m5r)
            q = plan.get("quality", {})
            rec = {"t": datetime.fromtimestamp(t, tz=timezone.utc).strftime("%m-%d %H:%M"),
                   "price": round(float(row["close"]), 2), "bias": plan.get("bias"),
                   "trend": round(float(q.get("trend_strength") or 0), 2),
                   "smc": round(float(q.get("smc_confidence") or 0), 2),
                   "align": q.get("alignment"), "action": dec.get("action"),
                   "reason": dec.get("reason")}
            if dec.get("action") == "wait_for_trigger" and rec["reason"] == "quality_filter":
                vetoed.append(rec)
            elif dec.get("action") == "market_entry_now":
                fired.append(rec)
        except Exception:
            continue
    return {"market_entry_now": fired, "quality_vetoes": vetoed}


def main():
    b = BridgeClient()
    m5 = sorted(fetch_all_ohlc(b, "XAUUSD", "M5", M5_BARS), key=lambda r: int(r["time"]))
    ctx = {"H1": fetch_all_ohlc(b, "XAUUSD", "H1", H1_BARS),
           "H4": fetch_all_ohlc(b, "XAUUSD", "H4", H1_BARS)}
    span = [datetime.fromtimestamp(int(m5[0]["time"]), tz=timezone.utc).isoformat(),
            datetime.fromtimestamp(int(m5[-1]["time"]), tz=timezone.utc).isoformat()]
    kw, ts = _harness_kwargs(m5)
    print("window:", span, "bars:", len(m5), "ts:", ts, flush=True)

    # census with deployed thresholds BEFORE any monkeypatch
    census = gate_census(m5, ctx, ts)
    print("funnel fired:", len(census["market_entry_now"]),
          "| quality vetoes:", len(census["quality_vetoes"]), flush=True)

    def run_arm(label):
        r = run_backtest(None, symbol="XAUUSD", timeframe="M5",
                         data={"M5": m5, "H1": ctx["H1"], "H4": ctx["H4"]},
                         m5_stream=None, **kw)
        return r

    real_gate = orch._passes_quality_gate
    deployed = run_arm("deployed")

    def loose_gate(plan):
        q = plan.get("quality", {})
        if q.get("alignment") == "aligned" and float(q.get("trend_strength") or 0) >= LOOSE_TREND:
            return True
        if float(q.get("smc_confidence") or 0) >= LOOSE_SMC:
            return True
        return False
    orch._passes_quality_gate = loose_gate
    # strategy_signal resolves evaluate_monitor_cycle from engines.orchestrator at
    # call time; it imports the FUNCTION object — rebind in backtest_real too
    import engines.backtest_real as br
    br.evaluate_monitor_cycle = orch.evaluate_monitor_cycle
    looser = run_arm("looser")
    orch._passes_quality_gate = real_gate

    def brief(r):
        st = lh.r_stats(r, time_stop_bars=ts)
        return {k: v for k, v in st.items() if not isinstance(v, (list, dict))}

    out = {"window": span, "bars": len(m5),
           "deployed_book": brief(deployed), "looser_book": brief(looser),
           "census": census,
           "loose_thresholds": {"trend": LOOSE_TREND, "smc": LOOSE_SMC}}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False)
    print("deployed:", json.dumps(brief(deployed)))
    print("looser:  ", json.dumps(brief(looser)))
    print("saved ->", OUT)


if __name__ == "__main__":
    main()
