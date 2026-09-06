#!/usr/bin/env python3
"""b108 — RE-MEASURE THE FUNNEL BASELINE AND THE b70 DECISION SET UNDER THE
b105-CORRECTED BACKTEST ENGINE.

Why this exists (b105, 2026-09-06): engines/backtest.py booked the post-TP1
RUNNER leg at FULL position size on top of the realized partial, and a
share>=1.0 TP1 fill — which is what the LIVE b55/b60 ladder does for the
balanced and weak lanes (`_partial_close_fraction` returns 1.0, and
auto_executor routes fraction>=1.0 to close_position because MT5 rejects a
100% partial with retcode 10026) — left a PHANTOM runner alive that (a) rode
on to the final TP / BE / trail and (b) BLOCKED entries the live single-slot
model would have taken. b105 fixed both and pinned them in
tests/test_b105_partial_parity.py.

The consequence is what this script measures. Every number the b68 loop ever
quoted — the 0.854R merit bar, the funnel's 0.52-0.53 on W1..W4, all four b70
lane rows — came out of the inflated engine. And the inflation is NOT neutral
across arms: it scales with how often an arm's trades hit TP1 and then ride
the runner, so an arm with a low TP1-hit rate was penalised relative to one
with a high rate. Re-running the arms is therefore not a formality; the
ranking itself is suspect.

WHAT THIS SCRIPT IS NOT: a new measurement. It is the SAME measurement as b81
(same legs, same bars, same harness, same exit ladder, same grade gate, same
lane closures) re-executed against the corrected engine. It imports b81's
`measure_leg` / `verdict` / `PROVENANCE` verbatim rather than restating the
funnel, because a hand-copied funnel is exactly the parity failure the backlog
hard rule forbids.

Outputs, per leg:
  new_*   — the corrected numbers (this run)
  old_*   — the shipped b81 ledger numbers (the inflated engine)
  delta   — new minus old, per arm, on exp_R / net_R / trades / dd_R
and a verdict block that RE-DERIVES the merit bar from the corrected cached
funnel and RE-DECIDES b70 under b74's all-windows rule.

Read-only research: nothing here is imported by the live trading path, and no
gate is touched — the live grade gate and min_rr are still IMPORTED from
engines.auto_executor by the harness, never restated.
"""
import os
import sys
import json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

# b81 machinery, imported not copied. Importing this module also binds the
# four lane labs (b81.LANE_BUILDERS), so the closures are byte-identical to
# the round that produced the shipped ledger.
from scripts import b81_lane_rescore as b81          # noqa: E402
from scripts import b68l_windows as wl               # noqa: E402

OUT = "data/backtest/b108_rescore_corrected.json"
OLD_LEDGER = "data/backtest/b81_lane_rescore.json"
LEGS = b81.LEGS if hasattr(b81, "LEGS") else ("cached", "W1", "W2", "W3", "W4")
WINDOWS = b81.WINDOWS if hasattr(b81, "WINDOWS") else ("W1", "W2", "W3", "W4")
ARMS = ["funnel_graded", "funnel_ungraded"] + list(b81.PROVENANCE)


def _cell(leg, arm):
    """One arm's headline row from a leg dict (lanes nest one level deeper)."""
    row = leg.get(arm)
    if isinstance(row, dict) and "graded" in row:
        return row["graded"]
    return row


def compare(new_leg, old_leg):
    """new minus old for every arm on the four axes b70 cares about."""
    out = {}
    for arm in ARMS:
        n, o = _cell(new_leg, arm), _cell(old_leg, arm)
        if not n or not o:
            continue
        out[arm] = {
            "new": {k: n.get(k) for k in
                    ("trades", "exp_R", "net_R", "maxDD_R", "WR%",
                     "mean_hold_bars")},
            "old": {k: o.get(k) for k in
                    ("trades", "exp_R", "net_R", "maxDD_R", "WR%",
                     "mean_hold_bars")},
            "d_exp_R": _sub(n.get("exp_R"), o.get("exp_R")),
            "d_net_R": _sub(n.get("net_R"), o.get("net_R")),
            "d_trades": _sub(n.get("trades"), o.get("trades")),
            "d_dd_R": _sub(n.get("maxDD_R"), o.get("maxDD_R")),
        }
    return out


def _sub(a, b):
    return round(a - b, 3) if (a is not None and b is not None) else None


def merit_bar(led):
    """RE-DERIVE the b68 merit bar from the corrected engine.

    The bar has always been 'the funnel's own exp_R on the leg being quoted',
    so the honest re-derivation is just the corrected funnel_graded row per
    leg. The historical 0.854R literal (b61, cached, inflated engine) is
    carried alongside so a reader can see the size of the correction.
    """
    return {
        "_historical_cached_bar_b61": 0.854,
        "_b81_cached_bar_inflated_engine": _cell(
            json.load(open(OLD_LEDGER))["cached"], "funnel_graded")["exp_R"],
        "cached": _cell(led["cached"], "funnel_graded")["exp_R"],
        **{w: _cell(led[w], "funnel_graded")["exp_R"] for w in WINDOWS},
    }


def redecide_b70(led):
    """b70's capacity question, re-answered on corrected numbers.

    Rule unchanged (b74, applied to lanes by b81): a lane earns a slot only if
    it beats the GRADED funnel on exp_R in EVERY independent window. The cached
    leg stays informational (b76: in-sample regime). What is NEW is that both
    sides of the comparison now come from the same corrected engine, so the
    delta is no longer contaminated by a TP1-hit-rate-dependent inflation.
    """
    v = b81.verdict(led)
    old_v = json.load(open(OLD_LEDGER))["_verdict"]
    for lane, row in v.items():
        row["windows_beaten_under_inflated_engine"] = \
            old_v.get(lane, {}).get("windows_beaten")
        row["verdict_changed"] = (row["windows_beaten"] !=
                                  row["windows_beaten_under_inflated_engine"])
        # the inflation-neutrality question, answered per lane: did the lane's
        # margin move MORE than the funnel's on the same bars?
        deltas = []
        for w in WINDOWS:
            c = led[w]["_compare"]
            d_fun = c["funnel_graded"]["d_exp_R"]
            d_lane = c[lane]["d_exp_R"]
            if d_fun is not None and d_lane is not None:
                deltas.append({"window": w, "d_funnel_exp_R": d_fun,
                               "d_lane_exp_R": d_lane,
                               "lane_relative_shift": round(d_lane - d_fun, 3)})
        row["inflation_neutrality"] = deltas
    return v


def main():
    old = json.load(open(OLD_LEDGER))
    wins = wl.load_windows()
    c = json.load(open("data/backtest/ab_aggressive_data.json"))

    led = {"_note": "b108: b81's measurement re-executed on the b105-corrected "
                    "engine (runner leg scaled by 1-partial_taken; share>=1.0 "
                    "closes at TP1 and frees the slot). Same legs, same bars, "
                    "same harness, same ladder, same live grade gate — b81's "
                    "measure_leg/verdict imported, not restated. old_* columns "
                    "are the shipped b81 ledger (inflated engine).",
           "_engine_fix": "b105 (engines/backtest.py _close + tp1_full)",
           "_live_min_grade": b81.MIN_SETUP_GRADE,
           "_provenance": {k: v[0] for k, v in b81.PROVENANCE.items()}}

    print("##### cached (in-sample, informational) #####", flush=True)
    led["cached"] = b81.measure_leg("cached", c["M15"], c["H1"], c["H4"])
    for w in WINDOWS:
        print(f"##### {w} #####", flush=True)
        led[w] = b81.measure_leg(w, wins[w]["M15"], wins[w]["H1"], wins[w]["H4"])
    for leg in LEGS:
        led[leg]["_compare"] = compare(led[leg], old[leg])

    led["_merit_bar"] = merit_bar(led)
    led["_b70_redecision"] = redeide_b70(led)
    print("=== MERIT BAR (corrected) ===")
    print(json.dumps(led["_merit_bar"], indent=1))
    print("=== b70 RE-DECISION ===")
    print(json.dumps({k: {kk: vv for kk, vv in v.items()
                          if kk not in ("inflation_neutrality", "per_window")}
                      for k, v in led["_b70_redecision"].items()}, indent=1))
    print("=== FUNNEL new vs old ===")
    for leg in LEGS:
        cmp_ = led[leg]["_compare"]["funnel_graded"]
        print(f"{leg:7s} exp_R {cmp_['old']['exp_R']} -> {cmp_['new']['exp_R']} "
              f"({cmp_['d_exp_R']:+}) | net_R {cmp_['old']['net_R']} -> "
              f"{cmp_['new']['net_R']} | trades {cmp_['old']['trades']} -> "
              f"{cmp_['new']['trades']} | dd {cmp_['old']['maxDD_R']} -> "
              f"{cmp_['new']['maxDD_R']}")
    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
