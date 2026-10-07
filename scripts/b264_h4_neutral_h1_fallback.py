#!/usr/bin/env python3
"""b264: does falling back to H1 bias when H4 is neutral make money?

PROBLEM (measured): the plan bias is h4_bias alone
(engines/context.build_plan_context: `bias = h4_bias if directional else
"neutral"`), and classify_bias(H4) over a 5-bar window is neutral 37% of the
time. A neutral plan is an explicit no-trade state, so the engine sits out
37% of the week. Worse: after an H4-neutral window the forward 24h move
exceeds 3 USD 94% of the time (mean -9.56, sd 64.8, n=180). The engine is
not avoiding dead markets — it is avoiding MOVING markets.

CANDIDATE FIX: when H4 is neutral, inherit H1's directional bias, but mark
the plan as a lower-confidence 'fallback' so downstream gates can tighten
risk rather than accept it at full size.

This script measures the FORWARD edge of the fallback on real bars. It is a
directional-accuracy test, not a dollar backtest: it asks whether H1's
bias, taken during an H4-neutral window, predicts the sign of the next
24h move better than a coin flip, with >= 20 samples for validity.
"""

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from bridge_client import BridgeClient  # noqa: E402
from engines.context import classify_bias  # noqa: E402

FORWARD_H4_BARS = 6  # 24h


def main():
    b = BridgeClient()
    h4 = (b.get_rates(symbol="XAUUSD", timeframe="H4", count=600) or {}).get("data") or []
    h1 = (b.get_rates(symbol="XAUUSD", timeframe="H1", count=2600) or {}).get("data") or []
    print(f"H4={len(h4)} H1={len(h1)}")
    if len(h4) < 60 or len(h1) < 240:
        print("ERROR: not enough bars")
        return 1

    # For every H4 window that classify_bias grades neutral, ask what H1 said
    # at that moment and where price actually went over the next 24h.
    matched = []
    skipped = 0
    for i in range(5, len(h4) - FORWARD_H4_BARS):
        h4b = classify_bias(h4[max(0, i - 5) : i])
        if h4b != "neutral":
            continue
        a = i * 4  # H4 bar i starts at H1 bar i*4
        if a + 20 > len(h1):
            skipped += 1
            continue
        h1b = classify_bias(h1[max(0, a - 20) : a + 20])
        fwd = h4[i : i + FORWARD_H4_BARS]
        move = float(fwd[-1]["close"]) - float(h4[i - 1]["close"])
        matched.append({"h1_bias": h1b, "move": move})

    n = len(matched)
    print(f"\nH4-neutral windows with forward data: {n} (skipped {skipped})")
    if n < 20:
        print("ERROR: fewer than 20 samples — inconclusive by the >=20 rule")
        return 1

    def hit_rate(bias):
        rows = [m for m in matched if m["h1_bias"] == bias]
        if not rows:
            return None, 0
        correct = sum(
            1 for m in rows
            if (bias == "bullish" and m["move"] > 0) or (bias == "bearish" and m["move"] < 0)
        )
        return correct / len(rows) * 100.0, len(rows)

    print("\n=== H1 fallback accuracy during H4-neutral windows ===")
    results = {}
    for bias in ("bullish", "bearish", "neutral"):
        pct, cnt = hit_rate(bias)
        if pct is None:
            print(f"  {bias:8s}: no samples")
            continue
        results[bias] = {"hit_pct": round(pct, 1), "n": cnt}
        flag = " <-- edge" if pct > 55 else ""
        print(f"  {bias:8s}: {pct:5.1f}% correct ({cnt} samples){flag}")

    directional = [m for m in matched if m["h1_bias"] in {"bullish", "bearish"}]
    if directional:
        d_hits = sum(
            1 for m in directional
            if (m["h1_bias"] == "bullish" and m["move"] > 0)
            or (m["h1_bias"] == "bearish" and m["move"] < 0)
        )
        d_pct = d_hits / len(directional) * 100.0
        results["directional_combined"] = {"hit_pct": round(d_pct, 1), "n": len(directional)}
        print(f"\n  directional combined: {d_pct:.1f}% correct ({len(directional)} samples)")
        print(f"  breakeven is 50%. edge = {d_pct - 50:+.1f}pp")

    abs_moves = [abs(m["move"]) for m in matched]
    print(f"\n  forward |move|: mean {statistics.mean(abs_moves):.2f} "
          f"median {statistics.median(abs_moves):.2f}")

    # DECISION: the fallback is worth wiring in only if H1's directional call
    # beats 50% by a real margin AND on enough samples.
    d = results.get("directional_combined")
    if d and d["n"] >= 20 and d["hit_pct"] >= 55.0:
        verdict = "FALLBACK_HAS_EDGE"
    elif d and d["n"] >= 20 and d["hit_pct"] <= 45.0:
        verdict = "FALLBACK_HURTS"
    else:
        verdict = "INCONCLUSIVE"
    print(f"\n=== verdict: {verdict} ===")

    out = {
        "experiment": "b264_h4_neutral_h1_fallback",
        "h4_neutral_windows": n,
        "per_bias": results,
        "mean_abs_forward_move": round(statistics.mean(abs_moves), 2),
        "verdict": verdict,
    }
    (BASE / "data" / "backtest" / "b264_h4_neutral_h1_fallback.json").write_text(
        json.dumps(out, indent=2)
    )
    print("wrote data/backtest/b264_h4_neutral_h1_fallback.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
