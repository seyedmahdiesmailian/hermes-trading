#!/usr/bin/env python3
"""b160 — REANCHOR SYMMETRY A/B: does BUY's nearest-TP pick cost exp_R?

Fresh code review of engines/plan.py::_reanchor_blueprint (2026-09-08) found a
side asymmetry that the docstring contradicts:

    "Tighten the stop to ~2 ATR and pick the FURTHEST valid target"

  SELL branch:  tp = max(cands, key=rr)  -> FARTHEST target (max attainable rr)
  BUY  branch:  tp = min(cands, key=rr)  -> NEAREST  target (min attainable rr)

Both branches then fall back to synthesising tp at floor+0.05 when the pick
misses min_rr, and b84 measured that ~99.7% of the funnel population lands in
that manufactured spike. So the asymmetry is only live for the rare signals
where a NATURAL structural level clears the floor — and when it binds, it binds
one way: BUY trades are capped at their nearest level (small rr, high hit-rate)
while SELL trades get their furthest level (big rr). Whether that is a loss or
a (per accident) win on the funnel's own money axis has never been measured.

This round is b110-compliant: it reruns the sanctioned live-parity funnel
(engines.backtest_real.strategy_signal through backtest_ohlc with the b71
harness stats), exactly the b157 pattern — the only difference between arms is
a monkey-patch of _reanchor_blueprint to make BUY pick the furthest candidate
(symmetry). Nothing here changes production code; a behavioural change would
need >=3 non-zero legs per b129's one-sided rule before anything ships.

Legs: pass as argv (cached, W1, W2, W3, W4); default cached. Output honoring
B160_OUT so several legs can run in separate processes like b157 did.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                       # noqa: E402
from engines import plan as plan_mod                        # noqa: E402
from engines.backtest import backtest_ohlc                  # noqa: E402
from engines.backtest_real import strategy_signal           # noqa: E402

OUT = os.environ.get("B160_OUT", "data/backtest/b160_reanchor_symmetry.json")
_ORIG_REANCHOR = plan_mod._reanchor_blueprint


def symmetric_reanchor(bp: dict, price: float, atr: float,
                       min_rr: "float | None" = None) -> dict:
    """Verbatim copy of the live function with ONE change: BUY picks
    max(cands) (furthest) instead of min(cands) (nearest). Everything else —
    stop cap, 0.5*ATR floor, synthesis fallback, parity padding, rounding —
    identical. SELL branch untouched."""
    if min_rr is None:
        min_rr = plan_mod.REANCHOR_MIN_RR
    atr = float(atr or 0) or 5.0
    side = bp["side"]
    sl = float(bp["sl"])
    stop_dist_cap = plan_mod.REANCHOR_STOP_ATR_CAP * atr

    if side == "SELL":
        sl = min(sl, price + stop_dist_cap) if sl > price else price + stop_dist_cap
        sl = max(sl, price + 0.5 * atr)
        stop_dist = sl - price
        cands = [t for t in bp.get("tp_levels") or [] if t < price]
        tp = max(cands, key=lambda t: (price - t) / stop_dist) if cands else None
        if tp is None or (price - tp) / stop_dist < min_rr:
            tp = price - stop_dist * min_rr
    else:
        sl = max(sl, price - stop_dist_cap) if sl < price else price - stop_dist_cap
        sl = min(sl, price - 0.5 * atr)
        stop_dist = price - sl
        cands = [t for t in bp.get("tp_levels") or [] if t > price]
        tp = max(cands, key=lambda t: (t - price) / stop_dist) if cands else None   # <== the patch
        if tp is None or (tp - price) / stop_dist < min_rr:
            tp = price + stop_dist * min_rr

    bp = dict(bp)
    bp["sl"] = round(sl, 2)
    _sd = abs(price - bp["sl"])
    _tp = round(tp, 2)
    if _sd > 0:
        _need = price - _sd * (min_rr + 0.05) if side == "SELL" else price + _sd * (min_rr + 0.05)
        _tp = min(_tp, _need) if side == "SELL" else max(_tp, _need)
    bp["tp"] = round(_tp, 2)
    bp["tp_levels"] = [round(_tp, 2)]
    bp["tp_shares"] = [1.0]
    bp["reanchored"] = True
    return bp


def funnel_fn(m15, h1, h4):
    """Same construction as b157.funnel_fn: signals captured once per leg."""
    import bisect
    h1t = [r.get("time", 0) for r in h1]
    h4t = [r.get("time", 0) for r in h4]
    idx = {r["time"]: n for n, r in enumerate(m15)}
    sigs = {}
    for i, row in enumerate(m15):
        bt = row.get("time", 0)
        j1 = bisect.bisect_right(h1t, bt); j4 = bisect.bisect_right(h4t, bt)
        s = strategy_signal(row, h1[max(0, j1 - 80):j1], h4[max(0, j4 - 80):j4], i,
                            m15_window=m15[max(0, i - 120):i + 1])
        if s:
            sigs[i] = s

    def fn(row):
        return sigs.get(idx.get(row.get("time", 0), -1))
    return fn


def _rr(s):
    e, sl, tp = float(s["entry"]), float(s["sl"]), float(s["tp"])
    return abs(tp - e) / max(abs(e - sl), 1e-9)


def side_rr(sigs):
    """rr distribution per side of a signal dict."""
    out = {}
    for s in sigs.values():
        side = s.get("side", "?")
        out.setdefault(side, []).append(round(_rr(s), 3))
    return {k: {"n": len(v), "mean": round(sum(v) / len(v), 3),
                "max": max(v), "share_above_1_6": round(sum(1 for x in v if x > 1.6) / len(v), 4)}
            for k, v in out.items()}


def measure_leg(m15, h1, h4) -> dict:
    ts = lh.live_time_stop_bars(m15)
    out = {}
    for arm, patch in (("incumbent", _ORIG_REANCHOR), ("symmetric", symmetric_reanchor)):
        plan_mod._reanchor_blueprint = patch
        try:
            fn = funnel_fn(m15, h1, h4)
            res = backtest_ohlc(m15, fn, min_rr=lh.LIVE_MIN_RR,
                                spread=lh.SPREAD, min_grade=lh.LIVE_MIN_GRADE,
                                **lh.LADDER)
        finally:
            plan_mod._reanchor_blueprint = _ORIG_REANCHOR
        row = lh.r_stats(res, time_stop_bars=ts)
        out[arm] = row
    out["_signals_incumbent"] = side_rr(_capture(m15, h1, h4, _ORIG_REANCHOR))
    out["_signals_symmetric"] = side_rr(_capture(m15, h1, h4, symmetric_reanchor))
    a, b = out["incumbent"]["exp_R"], out["symmetric"]["exp_R"]
    out["_delta_exp_R"] = round(b - a, 3) if a is not None and b is not None else None
    return out


def _capture(m15, h1, h4, patch):
    import bisect
    h1t = [r.get("time", 0) for r in h1]
    h4t = [r.get("time", 0) for r in h4]
    sigs = {}
    plan_mod._reanchor_blueprint = patch
    try:
        for i, row in enumerate(m15):
            bt = row.get("time", 0)
            j1 = bisect.bisect_right(h1t, bt); j4 = bisect.bisect_right(h4t, bt)
            s = strategy_signal(row, h1[max(0, j1 - 80):j1], h4[max(0, j4 - 80):j4], i,
                                m15_window=m15[max(0, i - 120):i + 1])
            if s:
                sigs[i] = s
    finally:
        plan_mod._reanchor_blueprint = _ORIG_REANCHOR
    return sigs


def load_leg(name):
    from scripts import b121_flat_share_replication as b121
    return b121._rows_for(name)


def main(argv) -> int:
    legs = [a for a in argv[1:] if not a.startswith("--")] or ["cached"]
    led = {"item": "b160", "arms": ("incumbent", "symmetric"), "legs": {}}
    deltas = {}
    for leg in legs:
        m15, h1, h4 = load_leg(leg)
        led["legs"][leg] = measure_leg(m15, h1, h4)
        deltas[leg] = led["legs"][leg]["_delta_exp_R"]
        print(leg, json.dumps({a: {k: led["legs"][leg][a][k] for k in
                                   ("trades", "exp_R", "net_R", "maxDD_R") if k in led["legs"][leg][a]}
                               for a in ("incumbent", "symmetric")}), flush=True)
    nonzero = [v for v in deltas.values() if v]
    pos = sum(1 for v in nonzero if v > 0)
    neg = sum(1 for v in nonzero if v < 0)
    led["verdict"] = {
        "per_leg_delta_exp_R": deltas,
        "better_legs": pos, "worse_legs": neg,
        "zero_legs": len(deltas) - len(nonzero),
        "direction": ("symmetric BETTER" if neg == 0 and pos else
                      "symmetric WORSE" if pos == 0 and neg else
                      "NO EFFECT" if not nonzero else "MIXED"),
        "note": "b129 floor: >=3 non-zero legs to be a decision; below that this "
                "is a direction report. A no-effect leg means the nearest-TP "
                "pick never bound (the b84 manufactured spike swallows it).",
    }
    with open(OUT, "w") as fh:
        json.dump(led, fh, indent=1, sort_keys=True)
    print("VERDICT", json.dumps(led["verdict"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
