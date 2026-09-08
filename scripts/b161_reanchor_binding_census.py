#!/usr/bin/env python3
"""b161 — how many BUY signals does the nearest-vs-furthest pick actually bind?

For each leg, capture the funnel's signal set under both arms (b160's own
capture helpers) and diff the geometry per signal index: count the entries
where incumbent tp != symmetric tp, and report the rr spread of those bound
picks. This is the mechanism census behind the W1 -0.006R divergence: the
book delta is a slot cascade off ONE bound pick, so the honest number is
"how rare is the binding event", not just the exp_R delta.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from scripts import b160_reanchor_symmetry_ab as b160    # noqa: E402


def _geom(s):
    return (round(float(s["entry"]), 2), round(float(s["sl"]), 2),
            round(float(s["tp"]), 2))


def main(argv) -> int:
    legs = [a for a in argv[1:] if not a.startswith("--")] or ["cached", "W1", "W2", "W3", "W4"]
    out = {}
    for leg in legs:
        m15, h1, h4 = b160.load_leg(leg)
        a = b160._capture(m15, h1, h4, b160._ORIG_REANCHOR)
        b = b160._capture(m15, h1, h4, b160.symmetric_reanchor)
        common = sorted(set(a) & set(b))
        bound = [i for i in common if _geom(a[i]) != _geom(b[i])]
        by_side = {}
        for i in bound:
            by_side.setdefault(a[i].get("side", "?"), []).append(
                {"index": i,
                 "rr_inc": round(b160._rr(a[i]), 3),
                 "rr_sym": round(b160._rr(b[i]), 3)})
        out[leg] = {"n_signals": len(a), "n_common": len(common),
                    "n_bound": len(bound),
                    "bound_share": round(len(bound) / len(common), 5) if common else None,
                    "by_side": by_side}
        print(leg, json.dumps(out[leg]), flush=True)
    with open("data/backtest/b161_reanchor_binding_census.json", "w") as fh:
        json.dump({"item": "b161_binding_census", "legs": out}, fh, indent=1, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
