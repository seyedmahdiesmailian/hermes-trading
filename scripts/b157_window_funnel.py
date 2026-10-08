#!/usr/bin/env python3
"""b157 LAYER 3 — does honouring the smc.py lookback windows move the FUNNEL?

Layers 1-2 (scripts/b157_smc_window_census.py) measured:
  * live plan xau-... : 4 unfilled FVGs score into bias where a honoured
    20-bar window would keep 2 (stale ones are 7-8h old);
  * 934 historical bars: the bias CLASS flips on 36.8% of bars when the
    window is honoured — mean |weight shift| 14.8 vs OB/FVG weights of 2.0/1.5.
So this is NOT a parameter tidy-up: it is a live behaviour change, and b110's
rule applies — no behavioural change ships without a measured before/after on
the sanctioned live-parity funnel.

THIS ROUND runs engines/backtest_real.run_backtest (never a hand-written copy
of the funnel) twice on the same bars:
  arm "incumbent"  — the code as shipped (FVG scan unbounded);
  arm "windowed"   — same funnel, same data, but detect_fair_value_gaps
                     patched to slice rows[-lookback:] exactly the way the
                     parameter has always CLAIMED to.
The patch is a MONKEY-PATCH of the live function for the lab arm only;
nothing here changes production code.  If the windowed arm is one-sidedly
WORSE (b123's one_sided rule from b121's round), deleting the lying params is
the honest fix; if it is better or neutral, implementing the window is.

Legs: cached + the independent windows, capped by --legs for time.
Writes data/backtest/b157_window_funnel.json (b127 shape: _derived reproducible).

KNOWN LIMITATION (stamped by the b157 landing run, 2026-09-08): production
smc_analyse calls detect_fair_value_gaps WITHOUT a lookback after the params
were deleted, so the monkey-patched windowed_fvg applies its default 20-bar
window to the H1 scan too, while the old signature had claimed 10. A 20-bar
H1 window is LOOSER (closer to incumbent) than the promised 10, so this arm
UNDER-states the effect of the full tightening — which makes the measured
"windowed WORSE" direction (W1 -0.033R / W2 -0.078R / W3 -0.023R) a
conservative estimate. The keep-the-unbounded-scan call cannot flip in the
optimistic direction from this simplification.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                       # noqa: E402
from engines import smc as smc_mod                          # noqa: E402
from engines.backtest import backtest_ohlc                  # noqa: E402
from engines.backtest_real import strategy_signal           # noqa: E402
from scripts.b157_smc_window_census import M5_LOOKBACK, H1_LOOKBACK  # noqa: E402

OUT = os.environ.get("B157_OUT", "data/backtest/b157_window_funnel.json")
_ORIG_FVG = smc_mod.detect_fair_value_gaps


def windowed_fvg(rows, lookback: int = 20):
    """The detector the signature has always promised: scan only the trailing
    `lookback` candles. Fill-check still uses the full tail (a gap that was
    later filled is filled), matching the original semantics exactly."""
    head = rows[:-lookback] if len(rows) > lookback else []
    tail = rows[-lookback:] if len(rows) > lookback else rows
    found_in_window = _ORIG_FVG(tail)
    for f in found_in_window:
        # rebase indices from the tail slice back to full-rows coordinates
        f["c1_index"] += len(rows) - len(tail)
        f["c3_index"] += len(rows) - len(tail)
    return found_in_window


def _bisect_window(h_rows, h_times, bt, n=80):
    import bisect
    j = bisect.bisect_right(h_times, bt)
    return h_rows[max(0, j - n):j]


def funnel_fn(m15, h1, h4):
    """Same construction as b81.funnel_fn (live-parity strategy_signal per
    bar), but the signal is captured ONCE per leg and both arms score the
    SAME signal dict shape — the only difference between arms is the detector
    patch, which is applied OUTSIDE this call."""
    h1t = [r.get("time", 0) for r in h1]
    h4t = [r.get("time", 0) for r in h4]
    idx = {r["time"]: n for n, r in enumerate(m15)}
    sigs = {}
    for i, row in enumerate(m15):
        bt = row.get("time", 0)
        s = strategy_signal(row, _bisect_window(h1, h1t, bt),
                            _bisect_window(h4, h4t, bt), i,
                            m15_window=m15[max(0, i - 120):i + 1])
        if s:
            sigs[i] = s

    def fn(row):
        return sigs.get(idx.get(row.get("time"), -1))
    return fn


def measure_leg(m15, h1, h4) -> dict:
    ts = lh.live_time_stop_bars(m15)
    out = {}
    for arm, patch in (("incumbent", _ORIG_FVG), ("windowed", windowed_fvg)):
        smc_mod.detect_fair_value_gaps = patch
        try:
            fn = funnel_fn(m15, h1, h4)
            res = backtest_ohlc(m15, fn, min_rr=lh.LIVE_MIN_RR,
                                spread=lh.SPREAD, min_grade=lh.LIVE_MIN_GRADE,
                                **lh.LADDER)
        finally:
            smc_mod.detect_fair_value_gaps = _ORIG_FVG
        out[arm] = lh.r_stats(res, time_stop_bars=ts)
    out["_delta_exp_R"] = (round(out["windowed"]["exp_R"] - out["incumbent"]["exp_R"], 3)
                           if out["windowed"]["exp_R"] is not None
                           and out["incumbent"]["exp_R"] is not None else None)
    return out


def load_leg(name):
    from scripts import b121_flat_share_replication as b121
    return b121._rows_for(name)


def main(argv) -> int:
    legs = [a for a in argv[1:] if not a.startswith("--")] or ["cached"]
    led = {"item": "b157", "arms": ("incumbent", "windowed"), "legs": {}}
    deltas = {}
    for leg in legs:
        m15, h1, h4 = load_leg(leg)
        led["legs"][leg] = measure_leg(m15, h1, h4)
        deltas[leg] = led["legs"][leg]["_delta_exp_R"]
        print(leg, json.dumps(led["legs"][leg]), flush=True)
    nonzero = [v for v in deltas.values() if v is not None]
    pos = sum(1 for v in nonzero if v > 0)
    neg = sum(1 for v in nonzero if v < 0)
    led["verdict"] = {
        "per_leg_delta_exp_R": deltas,
        "better_legs": pos, "worse_legs": neg,
        "direction": ("windowed BETTER" if neg == 0 and pos else
                      "windowed WORSE" if pos == 0 and neg else "MIXED"),
        "note": "one-sidedness rule needs >=3 non-zero legs to be a decision "
                "(b129's one_sided_strict floor); below that this is a "
                "direction report, not a verdict.",
    }
    with open(OUT, "w") as fh:
        json.dump(led, fh, indent=1, sort_keys=True)
    print("VERDICT", json.dumps(led["verdict"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
