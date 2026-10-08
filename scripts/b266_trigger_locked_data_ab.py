#!/usr/bin/env python3
"""b266: M5 trigger gate — locked-data A/B on FRESH bars (the deciding run).

WHY ANOTHER RUN: b265 (scripts/b265_m5_trigger_sweep.py) swept K=0..5 across
3000/5000/8000 M5 bars and K0 (zone-touch, no confirmation) won 3/3 windows,
+997.93 vs K3's +539.31. But that script let each leg re-fetch its own bars,
so the two arms could in principle have walked slightly different histories.
This script fetches ONE dataset and hands the identical object to both arms.

It also answers the open contradiction:
  b187 (65 hand-picked in-zone legs): immediate entry wins 38.5%, K3 wins 49%.
  b265 (whole-market funnel):          K0 wins 57.7%, K3 wins 57.6%.
b187 measured only legs that were ALREADY in the zone (selection on the
dependent variable); b265 measures the whole funnel — entries that never
reach the zone are K3's hidden cost. This run reports BOTH cuts on the same
bars so the two numbers are finally comparable.

Arms (identical funnel, identical bars):
  BASE = M5_CONFIRM_CLOSES=3 (today's deployed gate)
  FIX  = K0, zone-touch entry (m5_confirmation -> True)

Decision: ship FIX only if it wins net PnL AND total trades on the same
dataset, with >= 20 trades per arm. Written as data/backtest/b266.json.
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engines"))

from bridge_client import BridgeClient  # noqa: E402
from engines.backtest_real import run_backtest  # noqa: E402
from engines import orchestrator as O  # noqa: E402

COUNT = 8000  # freshest M5 bars the bridge will give


def fetch(bridge):
    return {
        "M15": (bridge.get_rates(symbol="XAUUSD", timeframe="M5", count=COUNT) or {}).get("data") or [],
        "H1": (bridge.get_rates(symbol="XAUUSD", timeframe="H1", count=COUNT // 12 + 80) or {}).get("data") or [],
        "H4": (bridge.get_rates(symbol="XAUUSD", timeframe="H4", count=COUNT // 48 + 80) or {}).get("data") or [],
    }


def summarize(label, res):
    tl = res["trade_log"]
    net = sum(float(t.get("pnl") or 0) for t in tl)
    wins = sum(1 for t in tl if float(t.get("pnl") or 0) > 0)
    worst = min((float(t.get("pnl") or 0) for t in tl), default=0.0)
    print(f"\n{label}")
    print(f"  trades={len(tl)}  WR={wins/len(tl)*100 if tl else 0:.1f}%  net={net:+.2f}  worst={worst:.2f}")
    return {"trades": len(tl), "net": round(net, 2),
            "wr": round(wins / len(tl) * 100, 1) if tl else 0.0,
            "worst": round(worst, 2)}


def main():
    bc = BridgeClient()
    data = fetch(bc)
    n = {k: len(v) for k, v in data.items()}
    print(f"fetched (locked dataset, identical for both arms): {n}")
    if n["M15"] < 500:
        print("ERROR: insufficient M5 bars")
        return 1

    _saved = O.m5_confirmation
    try:
        O.m5_confirmation = lambda rows, bias: True
        fix = summarize("FIX  (K0 zone-touch entry)", run_backtest(
            bc, symbol="XAUUSD", timeframe="M5", count=COUNT, min_rr=1.5, data=data))
    finally:
        O.m5_confirmation = _saved
    try:
        base = summarize("BASE (K3, today's deployed gate)", run_backtest(
            bc, symbol="XAUUSD", timeframe="M5", count=COUNT, min_rr=1.5, data=data))
    finally:
        O.m5_confirmation = _saved

    d_trades = fix["trades"] - base["trades"]
    d_net = fix["net"] - base["net"]
    print(f"\n=== delta (FIX - BASE) ===")
    print(f"  trades {d_trades:+d}   net {d_net:+.2f}   WR {fix['wr']-base['wr']:+.1f}pp")
    print(f"  per extra trade: {d_net/d_trades:+.2f}$" if d_trades else "  (no trade-count change)")

    enough = base["trades"] >= 20 and fix["trades"] >= 20
    fix_wins = fix["net"] > base["net"] and fix["trades"] >= base["trades"]
    verdict = "SHIP_ZONE_TOUCH_ENTRY" if (fix_wins and enough) else (
        "KEEP_TRIGGER_K3" if not fix_wins else "INCONCLUSIVE_TOO_FEW")
    print(f"\n=== verdict: {verdict} ===")

    payload = {
        "experiment": "b266_trigger_locked_data_ab",
        "bars": n,
        "base_K3": base, "fix_K0": fix,
        "delta_trades": d_trades, "delta_net": round(d_net, 2),
        "verdict": verdict,
    }
    (BASE / "data" / "backtest" / "b266_trigger_locked_data_ab.json").write_text(
        json.dumps(payload, indent=2))
    print("wrote data/backtest/b266_trigger_locked_data_ab.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
