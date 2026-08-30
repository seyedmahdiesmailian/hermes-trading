#!/usr/bin/env python3
"""A/B the aggressive premium/discount entry paths (backlog item, 2026-08-30).

Runs the EXACT live-parity funnel (engines.backtest_real.run_backtest) on one
byte-identical pre-fetched dataset, three times:
  A baseline       — live behaviour as-is (all entry styles)
  B no_aggr_pd     — aggressive_premium_entry / aggressive_discount_entry disabled
  C no_aggr_all    — every aggressive_* style disabled (incl. aggressive_value_entry)

Read-only: fetches rates only, never touches order endpoints.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, '/home/ai/hermes-trading')
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing → local fallback
load_dotenv('/home/ai/hermes-trading/.env')

from bridge_client import BridgeClient
from engines.backtest_real import run_backtest

COUNT = 3000
DATA_CACHE = Path('/home/ai/hermes-trading/data/backtest/ab_aggressive_data.json')
OUT = Path('/home/ai/hermes-trading/data/backtest/ab_aggressive_results.json')
SYMBOL = "XAUUSD"


def main() -> None:
    bridge = BridgeClient()
    health = bridge.health()
    if not health.get("ok"):
        print("Bridge unreachable — aborting (no data fetch possible).")
        sys.exit(1)

    # One dataset, cached: all configs must see identical bars.
    if DATA_CACHE.exists():
        data = json.loads(DATA_CACHE.read_text())
        print(f"cached data: M15={len(data['M15'])} H1={len(data['H1'])} H4={len(data['H4'])}")
    else:
        data = {
            "M15": _fetch(bridge, "M15", COUNT),
            "H1": _fetch(bridge, "H1", max(COUNT // 4, 200)),
            "H4": _fetch(bridge, "H4", max(COUNT // 16, 200)),
        }
        if not (data["M15"] and data["H1"] and data["H4"]):
            print("insufficient data from bridge — aborting")
            sys.exit(1)
        DATA_CACHE.write_text(json.dumps(data))
        print(f"fetched+cached: M15={len(data['M15'])} H1={len(data['H1'])} H4={len(data['H4'])}")

    configs = [
        ("A_baseline_live", []),
        ("B_no_aggressive_pd", ["aggressive_premium", "aggressive_discount"]),
        ("C_no_aggressive_all", ["aggressive"]),
    ]
    results = []
    for label, excl in configs:
        r = run_backtest(bridge, symbol=SYMBOL, timeframe="M15", count=COUNT,
                         exclude_styles=excl, data=data)
        r.pop("trade_log", None)  # keep the JSON small; per-style below comes from baseline
        r["label"] = label
        r["exclude_styles"] = excl
        results.append(r)
        wr = r.get("win_rate", 0) * 100
        print(f"{label:20s} trades={r.get('trades', 0):3d} W={r.get('wins', 0):2d} "
              f"L={r.get('losses', 0):2d} scratch={r.get('scratches', 0):2d} "
              f"WR={wr:5.1f}% pnl={r.get('net_pnl', 0):+9.2f}")

    # Per-style attribution on the LIVE baseline (which styles earn or bleed)
    r_live = run_backtest(bridge, symbol=SYMBOL, timeframe="M15", count=COUNT,
                          exclude_styles=[], data=data)
    style_pnl: dict[str, dict] = {}
    for t in r_live.get("trade_log", []):
        s = style_pnl.setdefault(str(t.get("style") or "unknown"),
                                 {"n": 0, "pnl": 0.0, "wins": 0, "losses": 0})
        s["n"] += 1
        s["pnl"] += t["pnl"]
        if t["pnl"] > 0.01:
            s["wins"] += 1
        elif t["pnl"] < -0.01:
            s["losses"] += 1
    print("\nPer-style attribution (baseline, live behaviour):")
    for k, v in sorted(style_pnl.items(), key=lambda kv: kv[1]["pnl"]):
        print(f"  {k:28s} n={v['n']:3d} win={v['wins']:2d} loss={v['losses']:2d} pnl={v['pnl']:+9.2f}")

    OUT.write_text(json.dumps({"results": results, "style_attribution": style_pnl}, indent=2))
    print(f"\nsaved {OUT}")


def _fetch(bridge, tf: str, count: int) -> list:
    resp = bridge.get_rates(SYMBOL, tf, count)
    if isinstance(resp, dict) and resp.get("ok"):
        d = resp.get("data", resp.get("rates", []))
        if isinstance(d, list):
            return d
    return []


if __name__ == "__main__":
    main()
