#!/usr/bin/env python3
"""b77 — apply the CHRONOLOGICAL-DECAY PRE-FLIGHT to the shipped round-14
ledger and freeze the result (data/backtest/b77_decay_preflight.json).

This is the b77 rule running on the exact data that motivated it: the four
independent windows (W1 newest → W4 oldest) already measured for the whole
round-13/14 arm set. No new draw is spent, no bridge call is made — the
script only reads shipped JSONs. The point is twofold:

1. PROVE the pre-flight would have stopped the loop BEFORE the W4 draw:
   on W1/W2/W3 alone (the state of knowledge at round 13's end) the
   funnel_h4t_agree margins +0.093/+0.032/+0.008 chronological are already
   monotone increasing with slope >= 0.02R — verdict REGIME_GIFTED, so the
   fourth draw was, in hindsight, not owed.
2. RECORD the four-window verdict for every arm of the round so future
   rounds quote the SHAPE, not just the mean.

Read-only research code: nothing here is imported by the live trading path.
"""
import os
import sys
import json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from engines import lab_decay as ld                 # noqa: E402

# b48 seam: redirect the OUTPUT FILE only (state), never code — lets
# tests/test_b77_decay_preflight.py regenerate the ledger into a temp dir and
# require byte equality with the shipped artefact without touching it.
OUT = os.environ.get("B77_PREFLIGHT_OUT") or os.path.join(
    _ROOT, "data", "backtest", "b77_decay_preflight.json")
LEDGER = os.path.join(_ROOT, "data", "backtest", "b68n4_fourth_draw.json")
WINDOWS_LEDGER = os.path.join(_ROOT, "data", "backtest",
                              "b68l_independent_windows.json")
WINDOWS = ["W1", "W2", "W3", "W4"]


def main():
    led = json.load(open(LEDGER))
    wins = json.load(open(WINDOWS_LEDGER))
    meta = {w: wins[f"_{w}_meta"] for w in WINDOWS}
    arms = [a for a in led["W4"] if not a.startswith("_")
            and a != "CURRENT_FUNNEL"]

    out = {"_note": "b77 pre-flight on the shipped round-14 ledger: margin "
                    "shape read CHRONOLOGICALLY (oldest window first) for "
                    "every arm; the 3-window column is what round 13 knew "
                    "BEFORE spending the W4 draw",
           "four_window": ld.preflight(led, arms, WINDOWS, meta),
           "three_window_pre_w4": ld.preflight(led, arms, ["W1", "W2", "W3"],
                                               meta)}
    # The headline facts, computed not hardcoded:
    fw = out["four_window"]["funnel_h4t_agree"]
    tw = out["three_window_pre_w4"]["funnel_h4t_agree"]
    out["_headline"] = {
        "arm": "funnel_h4t_agree",
        "four_window_verdict": fw["verdict"],
        "four_window_series_chrono": fw["series"],
        "three_window_verdict_before_w4_draw": tw["verdict"],
        "would_have_stopped_before_W4": tw["verdict"] == "REGIME_GIFTED",
    }
    print(json.dumps(out, indent=1))
    json.dump(out, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT), file=sys.stderr)


if __name__ == "__main__":
    main()
