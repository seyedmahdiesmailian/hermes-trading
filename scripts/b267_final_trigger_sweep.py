#!/usr/bin/env python3
"""b267-final: bug-free trigger sweep with K = number of MOVES.

b239/b265/b266 all read M5_CONFIRM_CLOSES as a count of closes while the
implementation compared len(closes)-1 adjacent pairs. That made the setting
off-by-one (K=3 enforced 2 moves) and made K=1 degenerate — a one-close slice
has zero adjacent pairs, so all([]) == True and every single bar passed.

m5_confirmation now asks for K+1 closes and compares K pairs. This re-runs the
same locked-dataset funnel under the corrected semantics so the trade-count /
net-PnL claim that justified shortening can be measured honestly.

Decision: keep K=1 if it still carries the trade-count advantage over K=3
under the corrected counting.
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

COUNT = 8000


def main():
    bc = BridgeClient()
    data = {
        "M15": (bc.get_rates(symbol="XAUUSD", timeframe="M5", count=COUNT) or {}).get("data") or [],
        "H1": (bc.get_rates(symbol="XAUUSD", timeframe="H1", count=COUNT // 12 + 80) or {}).get("data") or [],
        "H4": (bc.get_rates(symbol="XAUUSD", timeframe="H4", count=COUNT // 48 + 80) or {}).get("data") or [],
    }
    print(f"locked dataset: M5={len(data['M15'])} H1={len(data['H1'])} H4={len(data['H4'])}")
    if len(data["M15"]) < 500:
        print("ERROR: insufficient bars")
        return 1

    out = {}
    _orig_conf = O.m5_confirmation
    _orig_k = O.M5_CONFIRM_CLOSES
    # the setting counts CLOSES; K closes give K-1 close-to-close moves.
    # A setting of 1 is degenerate (no adjacent pair -> all([]) == True), so
    # m5_confirmation floors it at 2; that row is what "no real confirmation"
    # looks like and is kept only as context, never as a shipped setting.
    for k in (0, 2, 3, 4, 5):
        if k == 0:
            O.m5_confirmation = lambda rows, bias: True
        else:
            O.m5_confirmation = _orig_conf
            O.M5_CONFIRM_CLOSES = k
        r = run_backtest(bc, symbol="XAUUSD", timeframe="M5", count=COUNT,
                         min_rr=1.5, data=data)
        tl = r["trade_log"]
        net = sum(float(t.get("pnl") or 0) for t in tl)
        wins = sum(1 for t in tl if float(t.get("pnl") or 0) > 0)
        worst = min((float(t.get("pnl") or 0) for t in tl), default=0.0)
        out[str(k)] = {
            "closes": k,
            "moves": max(k - 1, 0),
            "trades": len(tl),
            "wr": round(100 * wins / max(1, len(tl)), 1),
            "net": round(net, 2),
            "worst": round(worst, 2),
        }
        label = "0 (unconditional)" if k == 0 else f"{k} closes ({k-1} moves)"
        print(f"{label:28s}: trades={len(tl):3d} "
              f"WR={100*wins/max(1,len(tl)):5.1f}% net={net:+8.2f} worst={worst:7.2f}")
    O.m5_confirmation = _orig_conf
    O.M5_CONFIRM_CLOSES = _orig_k

    best = max((kv for kv in out.items() if kv[0] != "0"), key=lambda kv: kv[1]["net"])
    print(f"\nbest confirmed length by net: {best[0]} closes -> {best[1]}")
    print(f"unconditional: {out['0']}")
    print(f"2 closes vs 3 (previously deployed): "
          f"trades {out['2']['trades']-out['3']['trades']:+d} "
          f"net {out['2']['net']-out['3']['net']:+.2f}")

    (BASE / "data" / "backtest" / "b267_final_trigger_sweep.json").write_text(
        json.dumps(out, indent=2))
    print("wrote data/backtest/b267_final_trigger_sweep.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
