#!/usr/bin/env python3
"""b161 — WHY does W1 diverge (-0.006R) when the other legs are exactly 0.000?

b160 measured the cached leg only (delta 0.000). b161 ran the same two arms on
W1..W4: W2/W3/W4 are byte-identical books (delta 0.000, trade counts equal),
W1 shows incumbent 181 trades / +0.211R vs symmetric 182 / +0.205R — the pick
BOUND at least once there. This probe walks the W1 books side by side and
prints exactly which positions differ (geometry, exit reason, pnl), so the
verdict ledger can state the mechanism instead of guessing "slot cascade".

Read-only lab: monkey-patches plan._reanchor_blueprint for the duration of the
call and restores it, exactly like b160; no production change, no bridge order
call, no trade.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                     # noqa: E402
from engines import plan as plan_mod                      # noqa: E402
from engines.backtest import backtest_ohlc                # noqa: E402
from scripts import b160_reanchor_symmetry_ab as b160     # noqa: E402


def _book(patch):
    m15, h1, h4 = b160.load_leg("W1")
    plan_mod._reanchor_blueprint = patch
    try:
        fn = b160.funnel_fn(m15, h1, h4)
        res = backtest_ohlc(m15, fn, min_rr=lh.LIVE_MIN_RR, spread=lh.SPREAD,
                            min_grade=lh.LIVE_MIN_GRADE, **lh.LADDER)
    finally:
        plan_mod._reanchor_blueprint = b160._ORIG_REANCHOR
    return res["trade_log"]


def _key(t):
    return (t.get("entry_index"), t.get("entry"))


def main() -> int:
    a = _book(b160._ORIG_REANCHOR)
    b = _book(b160.symmetric_reanchor)
    ka = {_key(t): t for t in a}
    kb = {_key(t): t for t in b}
    only_a = sorted(set(ka) - set(kb))
    only_b = sorted(set(kb) - set(ka))
    common = set(ka) & set(kb)
    differing = [k for k in sorted(common)
                 if abs(float(ka[k]["pnl"]) - float(kb[k]["pnl"])) > 1e-9
                 or ka[k].get("tp") != kb[k].get("tp")]
    out = {
        "item": "b161_w1_divergence",
        "leg": "W1",
        "n_incumbent": len(a), "n_symmetric": len(b),
        "only_in_incumbent": [
            {"entry_index": k[0], "side": ka[k].get("side"), "tp": ka[k].get("tp"),
             "pnl_R": round(float(ka[k]["pnl"]) /
                            max(abs(float(ka[k]["entry"]) - float(ka[k].get("orig_sl") or ka[k]["sl"])), 1e-9), 3),
             "exit_reason": ka[k].get("exit_reason")} for k in only_a],
        "only_in_symmetric": [
            {"entry_index": k[0], "side": kb[k].get("side"), "tp": kb[k].get("tp"),
             "pnl_R": round(float(kb[k]["pnl"]) /
                            max(abs(float(kb[k]["entry"]) - float(kb[k].get("orig_sl") or kb[k]["sl"])), 1e-9), 3),
             "exit_reason": kb[k].get("exit_reason")} for k in only_b],
        "differing_common": [
            {"entry_index": k[0], "side": ka[k].get("side"),
             "tp_inc": ka[k].get("tp"), "tp_sym": kb[k].get("tp"),
             "pnl_inc": round(float(ka[k]["pnl"]), 2),
             "pnl_sym": round(float(kb[k]["pnl"]), 2),
             "exit_inc": ka[k].get("exit_reason"), "exit_sym": kb[k].get("exit_reason")}
            for k in differing],
    }
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
