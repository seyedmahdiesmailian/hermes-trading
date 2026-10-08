#!/usr/bin/env python3
"""b265: M5 trigger gate — sweep the confirmation length across eras.

CONTEXT: scripts/ab_b239_no_trigger.py compared BASE (m5_confirmation enforced:
3 consecutive same-direction closes) against FIX (short-circuited to True, i.e.
zone-touch entry) on 3000 M5 bars and found FIX better on every axis:

    BASE  trades=43  WR=55.8%  net=+113.97  meanR=1.26
    FIX   trades=52  WR=57.7%  net=+170.09  meanR=1.30

That contradicts the justification recorded for b187/b193, which gated the
aggressive entry lanes behind the trigger citing "-95/-45/-24$ unconfirmed vs
+19$ confirmed" (3 live days) and an "untested path: 25% win, -0.67R/trade".
b265 widens the evidence before changing anything.

This script sweeps the confirmation length K = 1,2,3,4,5 over MULTIPLE M5
windows so the decision is not a single-window artefact. Score = net PnL over
identical bars, live-parity funnel (min_rr=1.5). K=0 is zone-touch entry.
Decision rule: the fix is shipped only if K=0 (or the lowest K) wins on the
MAJORITY of windows AND on aggregate net, with >= 20 trades per leg.
"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engines"))

from env_loader import load_dotenv  # noqa: E402

load_dotenv(BASE / ".env")

from bridge_client import BridgeClient  # noqa: E402
from engines.backtest_real import run_backtest  # noqa: E402
from engines import orchestrator as O  # noqa: E402

WINDOWS = [
    ("recent_3000", 3000),
    ("recent_5000", 5000),
    ("recent_8000", 8000),
]
KS = [0, 1, 2, 3, 4, 5]


def make_confirmer(k: int):
    if k == 0:
        return lambda rows, bias: True
    _orig = O.m5_confirmation

    def _c(rows, bias: str) -> bool:
        # require k consecutive closes all moving with the bias
        closes = O._closes(rows, k + 1)
        if len(closes) < k + 1:
            return False
        if bias == "bullish":
            return all(closes[i] < closes[i + 1] for i in range(len(closes) - 1))
        if bias == "bearish":
            return all(closes[i] > closes[i + 1] for i in range(len(closes) - 1))
        return False

    return _c


def leg(bridge, k: int, count: int):
    _saved = O.m5_confirmation
    O.m5_confirmation = make_confirmer(k)
    try:
        res = run_backtest(bridge, symbol="XAUUSD", timeframe="M5", count=count, min_rr=1.5)
    finally:
        O.m5_confirmation = _saved
    tl = res["trade_log"]
    net = sum(float(t.get("pnl") or 0) for t in tl)
    wins = sum(1 for t in tl if float(t.get("pnl") or 0) > 0)
    return {
        "trades": len(tl),
        "net": round(net, 2),
        "wr": round(wins / len(tl) * 100, 1) if tl else 0.0,
        "meanR": round(sum(float(t.get("R") or 0) for t in tl) / len(tl), 2) if tl else 0.0,
    }


def main():
    bc = BridgeClient()
    out = {}
    agg = {k: {"trades": 0, "net": 0.0} for k in KS}
    wins_count = 0

    for name, count in WINDOWS:
        print(f"\n=== {name} ({count} M5 bars) ===")
        out[name] = {}
        row = []
        for k in KS:
            r = leg(bc, k, count)
            out[name][f"K{k}"] = r
            agg[k]["trades"] += r["trades"]
            agg[k]["net"] += r["net"]
            print(f"  K{k}: trades={r['trades']:3d}  WR={r['wr']:5.1f}%  "
                  f"net={r['net']:+9.2f}  meanR={r['meanR']:.2f}")
            row.append(r)
        best_net = max(row, key=lambda r: r["net"])
        baseline_k3 = out[name]["K3"]
        print(f"  → best net: K{row.index(best_net)}  (baseline K3 net={baseline_k3['net']})")
        if best_net["net"] > baseline_k3["net"]:
            wins_count += 1

    print(f"\n=== aggregate across {len(WINDOWS)} windows ===")
    for k in KS:
        print(f"  K{k}: trades={agg[k]['trades']:4d}  net={agg[k]['net']:+10.2f}")

    k3_net = agg[3]["net"]
    k0_net = agg[0]["net"]
    enough = agg[0]["trades"] >= 20 and agg[3]["trades"] >= 20
    k0_wins_windows = wins_count

    print(f"\n=== decision ===")
    print(f"  K0 (zone-touch) beats K3 on aggregate net? {k0_net > k3_net} "
          f"({k0_net:+.2f} vs {k3_net:+.2f})")
    print(f"  K0 wins the majority of windows? {k0_wins_windows}/{len(WINDOWS)}")
    print(f"  >= 20 trades per leg? {enough}")

    if k0_net > k3_net and k0_wins_windows >= (len(WINDOWS) + 1) // 2 and enough:
        verdict = "SHIP_ZONE_TOUCH_ENTRY"
    elif k0_net < k3_net * 0.8:
        verdict = "KEEP_TRIGGER_K3"
    else:
        verdict = "INCONCLUSIVE"
    print(f"  verdict: {verdict}")

    payload = {
        "experiment": "b265_m5_trigger_sweep",
        "windows": out,
        "aggregate": {f"K{k}": v for k, v in agg.items()},
        "k0_wins_windows": k0_wins_windows,
        "verdict": verdict,
    }
    (BASE / "data" / "backtest" / "b265_m5_trigger_sweep.json").write_text(
        json.dumps(payload, indent=2)
    )
    print("wrote data/backtest/b265_m5_trigger_sweep.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
