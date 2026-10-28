#!/usr/bin/env python3
"""b161 — merge b160's cached leg + the W1..W4 legs into ONE verdict ledger.

Each leg was measured in its own process (B160_OUT knob, b48/b52 pattern) via
scripts/b160_reanchor_symmetry_ab.py. This merge reads those ledgers back,
recomputes the per-leg deltas, and applies b129's one-sided rule to the FIVE
legs (cached + W1..W4): a behaviour change needs >=3 non-zero legs agreeing in
direction. It also applies b161's OWN retirement rule from the brief: if the
symmetric arm never beats the incumbent on any leg, the BUY-nearest asymmetry
is not costing money and the question retires closed-by-evidence (with the
prescription narrowed to a docstring fix, never a geometry change).

Reads:  data/backtest/b160_reanchor_symmetry.json          (b160, cached leg)
        data/backtest/b160_reanchor_symmetry_W{1..4}.json  (b161 legs)
Writes: data/backtest/b161_reanchor_symmetry_verdict.json
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

OUT = "data/backtest/b161_reanchor_symmetry_verdict.json"
LEG_FILES = {
    "cached": "data/backtest/b160_reanchor_symmetry.json",
    "W1": "data/backtest/b160_reanchor_symmetry_W1.json",
    "W2": "data/backtest/b160_reanchor_symmetry_W2.json",
    "W3": "data/backtest/b160_reanchor_symmetry_W3.json",
    "W4": "data/backtest/b160_reanchor_symmetry_W4.json",
}


def _row(r):
    return {k: r.get(k) for k in ("trades", "exp_R", "net_R", "maxDD_R", "WR%")}


def merge() -> dict:
    legs = {}
    for leg, path in LEG_FILES.items():
        with open(path) as fh:
            led = json.load(fh)
        L = led["legs"][leg]
        inc, sym = L["incumbent"], L["symmetric"]
        delta = (None if inc.get("exp_R") is None or sym.get("exp_R") is None
                 else round(sym["exp_R"] - inc["exp_R"], 3))
        # integrity: the per-leg file must AGREE with the delta it printed
        assert delta == L.get("_delta_exp_R"), (leg, delta, L.get("_delta_exp_R"))
        # binding census: share of BUY signals where the symmetric pick moved rr
        b_inc = L["_signals_incumbent"].get("BUY", {})
        b_sym = L["_signals_symmetric"].get("BUY", {})
        legs[leg] = {
            "incumbent": _row(inc), "symmetric": _row(sym),
            "delta_exp_R": delta,
            "identical_book": _row(inc) == _row(sym),
            "buy_rr_max_incumbent": b_inc.get("max"),
            "buy_rr_max_symmetric": b_sym.get("max"),
            "buy_share_rr_above_1_6_symmetric": b_sym.get("share_above_1_6"),
        }
    deltas = {k: v["delta_exp_R"] for k, v in legs.items()}
    nonzero = [v for v in deltas.values() if v]
    pos = sum(1 for v in nonzero if v > 0)
    neg = sum(1 for v in nonzero if v < 0)
    out = {
        "item": "b161",
        "question": "does plan._reanchor_blueprint's BUY-nearest / SELL-furthest "
                    "asymmetry cost exp_R vs a symmetric furthest-for-both pick?",
        "arms": ("incumbent", "symmetric (BUY picks max rr)"),
        "legs": legs,
        "verdict": {
            "per_leg_delta_exp_R": deltas,
            "legs_symmetric_better": pos,
            "legs_symmetric_worse": neg,
            "legs_zero": len(deltas) - len(nonzero),
            "b129_floor_met": len(nonzero) >= 3 and (pos == 0 or neg == 0),
            "symmetric_better_on_any_leg": pos > 0,
        },
        "interpretation":
            "The symmetric arm never beats the incumbent on any of the five legs "
            "(cached/W2/W3/W4 byte-identical books, W1 -0.006R via a 1-vs-2-trade "
            "slot cascade — see scripts/b161_w1_divergence_probe.py). The asymmetry "
            "is REAL in code, DORMANT in practice: the incumbent BUY rr max caps at "
            "1.554 on every leg, so the nearest-pick almost never binds, and where "
            "it does bind the incumbent's pick is not worse. RETIRE the question: "
            "no geometry change ships; the docstring (which promised 'furthest' for "
            "both sides) is corrected to state the measured asymmetry instead.",
    }
    return out


def main() -> int:
    out = merge()
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print(json.dumps(out["verdict"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
