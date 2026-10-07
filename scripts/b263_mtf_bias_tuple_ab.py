#!/usr/bin/env python3
"""b263: A/B the MTF bias tuple — (M5,H1,H4) vs (M15,H1,H4).

Diagnosis that motivated this: the live plan_history is 41% neutral, and a
neutral plan is an explicit no-trade state (engines/plan.decide_execution_action
returns immediately). The master loop log confirms it:
    4588 no_trade / 9165 cycles = 50%
The dominant root cause is not the gates — it is that the bias tuple is built
on M5, whose 5-bar classify_bias window flips to 'neutral' on any choppy hour.

This script replays real pulled MTF bars and asks ONE question: does swapping
the entry-timeframe vote from M5 to M15 increase the number of DIRECTIONAL
(aligned) plan-hours without degrading their average edge? Neutral share alone
is not a win if the extra directionality is random noise.

Decision rule: the challenger wins only if it raises aligned-hours AND raises
mean |trend_strength| on those hours (i.e. the extra directionality is backed
by real movement, not by a noisier classifier).
"""

import json
import os
import statistics
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from bridge_client import BridgeClient  # noqa: E402
from engines.context import (  # noqa: E402
    _alignment_label,
    classify_bias,
    estimate_atr,
)


def pull(bridge: BridgeClient, tf: str, count: int):
    r = bridge.get_rates(symbol="XAUUSD", timeframe=tf, count=count) or {}
    return r.get("data") or []


def simulate(rows_by_tf: dict, vote_tf: str, step_bars: int, samples: int):
    """Replay history, sampling every `step_bars` of the vote timeframe."""
    m5 = rows_by_tf["M5"]
    m15 = rows_by_tf["M15"]
    h1 = rows_by_tf["H1"]
    h4 = rows_by_tf["H4"]
    vote = rows_by_tf[vote_tf]

    labels = Counter()
    aligned_strength = []
    aligned_net = []
    for i in range(samples):
        # anchor on the vote tf, aligning the others to the same wall-clock
        end_v = len(vote) - i * step_bars
        if end_v < 20:
            break
        v_seg = vote[max(0, end_v - 20) : end_v]
        # M15 and H1/H4 look further back than the vote tf
        end_15 = len(m15) - i * (step_bars // 3 if vote_tf == "M5" else step_bars)
        end_1 = len(h1) - i * (step_bars // 12)
        end_4 = len(h4) - i * (step_bars // 48)
        if end_15 < 8 or end_1 < 8 or end_4 < 6:
            continue
        v_bias = classify_bias(v_seg)
        h1_bias = classify_bias(h1[max(0, end_1 - 10) : end_1])
        h4_bias = classify_bias(h4[max(0, end_4 - 6) : end_4])
        lab = _alignment_label(v_bias, h1_bias, h4_bias)
        labels[lab] += 1

        if lab == "aligned":
            # vote tf IS m5 in the baseline; for the M15 challenger, index m5
            # by the same wall-clock offset (M15 bar = 3 M5 bars).
            m5_end = end_v if vote_tf == "M5" else end_v * 3
            seg = m5[max(0, m5_end - 12) : m5_end]
            if len(seg) >= 13:
                atr = estimate_atr(seg) or 1.0
                aligned_strength.append(abs(seg[-1]["close"] - seg[-13]["close"]) / atr)
                aligned_net.append(abs(seg[-1]["close"] - seg[0]["close"]))

    total = sum(labels.values())
    return {
        "labels": dict(labels),
        "total": total,
        "aligned_pct": (labels["aligned"] / total * 100) if total else 0.0,
        "neutral_pct": (labels["neutral"] / total * 100) if total else 0.0,
        "aligned_n": labels["aligned"],
        "mean_trend_strength": statistics.mean(aligned_strength) if aligned_strength else 0.0,
        "mean_abs_net": statistics.mean(aligned_net) if aligned_net else 0.0,
    }


def main():
    b = BridgeClient()
    rows = {
        "M5": pull(b, "M5", 8000),
        "M15": pull(b, "M15", 2600),
        "H1": pull(b, "H1", 1300),
        "H4": pull(b, "H4", 400),
    }
    print(f"pulled: " + ", ".join(f"{k}={len(v)}" for k, v in rows.items()))
    for k, v in rows.items():
        if len(v) < 100:
            print(f"ERROR: insufficient {k} bars ({len(v)})")
            return 1

    samples = 250
    base = simulate(rows, "M5", step_bars=12, samples=samples)
    chal = simulate(rows, "M15", step_bars=4, samples=samples)

    print(f"\n=== baseline (M5,H1,H4) — {base['total']} samples ===")
    print(f"  aligned {base['aligned_pct']:.0f}%  neutral {base['neutral_pct']:.0f}%")
    print(f"  aligned trend_strength mean = {base['mean_trend_strength']:.2f}")
    print(f"  aligned |net move|    mean = {base['mean_abs_net']:.2f}")

    print(f"\n=== challenger (M15,H1,H4) — {chal['total']} samples ===")
    print(f"  aligned {chal['aligned_pct']:.0f}%  neutral {chal['neutral_pct']:.0f}%")
    print(f"  aligned trend_strength mean = {chal['mean_trend_strength']:.2f}")
    print(f"  aligned |net move|    mean = {chal['mean_abs_net']:.2f}")

    more_aligned = chal["aligned_pct"] >= base["aligned_pct"]
    stronger = chal["mean_trend_strength"] >= base["mean_trend_strength"]
    enough = chal["aligned_n"] >= 20

    print(f"\n=== decision ===")
    print(f"  challenger aligned >= baseline ? {more_aligned}")
    print(f"  challenger strength >= baseline ? {stronger}")
    print(f"  >= 20 aligned samples for validity? {enough} ({chal['aligned_n']})")

    if more_aligned and stronger and enough:
        verdict = "CHALLENGER_WINS"
    elif not enough:
        verdict = "INCONCLUSIVE_TOO_FEW_ALIGNED"
    else:
        verdict = "BASELINE_KEEP"
    print(f"  verdict: {verdict}")

    out = {
        "experiment": "b263_mtf_bias_tuple_ab",
        "samples_base": base["total"],
        "samples_challenger": chal["total"],
        "baseline": {k: round(v, 4) for k, v in base.items() if k != "labels"},
        "challenger": {k: round(v, 4) for k, v in chal.items() if k != "labels"},
        "verdict": verdict,
    }
    (BASE / "data" / "backtest" / "b263_mtf_bias_tuple_ab.json").write_text(
        json.dumps(out, indent=2)
    )
    print(f"\nwrote data/backtest/b263_mtf_bias_tuple_ab.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
