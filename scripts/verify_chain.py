"""a2: end-to-end verification of the LIVE analysis chain on real data.

Run: python3 scripts/verify_chain.py
Checks (read-only, no trading):
  1. bridge OHLC reachable, sane rows
  2. build_plan_context: ATR>0, trend_strength in ATR units (|x|<~10),
     bias vol-relative, zones ordered (value_low < entry < value_high)
  3. smc_analyse + merge: confidence key present and 0..1
  4. build_plan_from_context: quality.smc_confidence wired (NOT None)
  5. evaluate_monitor_cycle: returns an action without exception
"""
import sys
sys.path.insert(0, '/home/ai/hermes-trading')
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing → local fallback
load_dotenv('/home/ai/hermes-trading/.env')

from bridge_client import BridgeClient
from engines.context import build_plan_context
from engines.smc import smc_analyse, merge_smc_with_classic
from engines.orchestrator import build_plan_from_context, evaluate_monitor_cycle

FAILS = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    if not ok:
        FAILS.append(name)


def rows_of(resp):
    """Same unwrap as backtest_real.fetch_all_ohlc."""
    if isinstance(resp, dict) and resp.get("ok"):
        data = resp.get("data", resp.get("rates", []))
        return data if isinstance(data, list) else []
    return resp if isinstance(resp, list) else []


def main():
    b = BridgeClient()
    # entry TF must match live TIMEFRAME='M5' (b27: was M15, a parity drift)
    m5 = rows_of(b.get_rates("XAUUSD", "M5", 200))
    m15 = rows_of(b.get_rates("XAUUSD", "M15", 80))  # analytical vote only (b28)
    h1 = rows_of(b.get_rates("XAUUSD", "H1", 120))
    h4 = rows_of(b.get_rates("XAUUSD", "H4", 60))
    check("bridge OHLC", len(m5) > 100 and len(h1) > 50 and len(h4) > 30,
          f"m5={len(m5)} h1={len(h1)} h4={len(h4)}")

    now = datetime.now(timezone.utc)
    ctx = build_plan_context(m5, h1, h4, "any", m15_rows=m15)
    check("m15 analytical vote present",
          ctx.get("quality", {}).get("bias_votes", {}).get("m15")
          in ("bullish", "bearish", "neutral"),
          f"votes={ctx.get('quality', {}).get('bias_votes')}")
    atr = ctx.get("atr", 0)
    ts = ctx.get("quality", {}).get("trend_strength", 0)
    zones = ctx.get("zones", {})
    check("atr sane", 0.5 < atr < 60, f"atr={atr:.2f}")
    check("trend_strength in ATR units", abs(ts) < 10, f"ts={ts:.2f}")
    check("bias present", ctx.get("bias") in ("bullish", "bearish", "neutral"),
          f"bias={ctx.get('bias')}")
    vl, vh = zones.get("value_low", 0), zones.get("value_high", 0)
    last = m5[-1]["close"]
    check("zones ordered & near price", 0 < vl < vh and abs(vl - last) < 10 * atr and abs(vh - last) < 10 * atr,
          f"vl={vl:.1f} vh={vh:.1f} last={last:.1f}")
    check("invalidation sane side",
          (ctx["bias"] == "bearish" and ctx["invalidation"] > last) or
          (ctx["bias"] == "bullish" and ctx["invalidation"] < last) or
          ctx["bias"] == "neutral",
          f"inv={ctx['invalidation']} last={last:.1f} bias={ctx['bias']}")

    smc = smc_analyse(m5, now, h1)
    conf = smc.get("confidence")
    check("smc confidence 0..1", isinstance(conf, (int, float)) and 0 <= conf <= 1,
          f"conf={conf}")

    merged = merge_smc_with_classic(ctx, smc)
    check("merge keeps confidence", merged.get("confidence") is not None,
          f"merged conf={merged.get('confidence')}")

    ctx.setdefault("quality", {})["smc_confidence"] = merged.get("confidence")
    plan = build_plan_from_context(ctx, now=now)
    qc = plan.get("quality", {}).get("smc_confidence")
    check("plan quality.smc_confidence wired", qc is not None, f"qc={qc}")

    act = evaluate_monitor_cycle(plan, m5[-1]["close"], now)
    check("monitor cycle runs", isinstance(act, dict) and "action" in act,
          f"action={act.get('action')} reason={str(act.get('reason'))[:60]}")

    print("\nRESULT:", "ALL PASS" if not FAILS else f"FAILS: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
