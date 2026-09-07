#!/usr/bin/env python3
"""b123 — DECOMPOSE THE SHARE AXIS FROM THE PROTECTION (BE/TRAIL) AXIS.

WHY THIS EXISTS
===============
b121b swept `partial_tp1_share` from 1.0 down to 0.0 and called the result a
curve. It is not one curve — it is two dials turning together. In
engines/backtest.py the SL->entry move and the runner trail were BOTH armed
only inside the branch that takes a TP1 partial, so at share=0.0 the trade
loses its breakeven protection AND its trail as well as its partial. The left
end of the "share curve" is a different TRADE, which is why it was the best arm
on cached/W1/W4/W5 (+0.066..+0.099R over the incumbent) and the worst on
W2/W3/W6 (-0.016..-0.051R): a mixed sign across seven windows that b110 reads
as NO LEVER, but the cause is the confound, not noise.

A THIRD coupling turned up while writing this round and is measured here too:
the b57 time exit is gated on `partial_taken == 0`, so a share=0 trade is also
the only one the 36h time exit can kill. Live's own
`engines.legacy_guards.evaluate_time_exit` is purely age-based — it does not
look at partials at all — so the lab's exemption is a FOURTH thing the share
dial silently moves.

WHAT IS MEASURED
================
Three families, one harness, one parameter at a time (b72's pure-arm rule), on
cached + W1..W6 (the same seven legs b121/b121b used, same bars, same funnel):

  P — PROTECTION AT FIXED SHARE. The live incumbent share rule, measured with
      the protection armed the way live arms it (`partial`), never armed
      (`none`), and armed on a TP1 touch (`tp1`). The `tp1` row must be
      BYTE-IDENTICAL to `partial` for the incumbent: live's rule returns 1.0
      for every non-A trade (closed at TP1 before any arming) and 0.3 for the A
      lane (armed either way). If that identity fails, the two modes are not
      what they are named for — b122's shape, pinned rather than assumed.

  S — SHARE AT FIXED PROTECTION. share in {1.0, 0.7, 0.5, 0.3, 0.0} measured
      TWICE: with protection always armed on a TP1 touch (`tp1`) and never
      armed (`none`). The share=0 point of the `none` curve IS the coupled
      engine's share=0 arm (identity pinned), so the jump between the two
      curves at share=0 is a PURE protection effect and the slope along the
      `tp1` curve is a PURE share effect.

  T — TIME-EXIT GATE. Every arm measured under both `no_partial` (the stored
      convention) and `age_only` (live's actual rule), so the exemption's cost
      is a column instead of a hidden variable.

THE DECISION THIS FEEDS
=======================
b121's candidate (flat_0.30, +0.028/+0.035R on the fresh pair) is small enough
that a protection effect of the same size would fully explain it. If the share
effect survives with protection held constant, the candidate is a candidate.
If it does not, the whole b119/b121/b121b line was measuring the BE/trail arm
wearing a share label, and every stored verdict built on it is void, not
shrunk (b122's rule).

NOTHING IS WIRED. `protection_mode="tp1"` is a runnable POLICY (a desk can move
SL to entry and trail without closing anything), but it is NOT what live does
today: position_daemon arms BE only after a TP FILL (`if filled and not
breakeven_active`), so a zero-share ticket never arms. Changing that is a live
exit-behaviour change = human gate (b89 class). engines/trade_management.py is
untouched by this round.

Every live value (grade gate, min_rr, trail multiplier, $ floor, share fn, time
exit) is imported or probed, never restated (b118's rule).
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                     # noqa: E402
from engines.backtest import backtest_ohlc                # noqa: E402
from engines.trade_management import _partial_close_fraction  # noqa: E402
from scripts import b81_lane_rescore as b81               # noqa: E402
from scripts.b121_flat_share_replication import (          # noqa: E402
    SELECTION, FRESH, LEGS, INCUMBENT, _rows_for)

OUT = "data/backtest/b123_protection_share_decomposition.json"
STEP1 = "data/backtest/b121_flat_share_replication.json"
STEP2 = "data/backtest/b121b_share_sweep.json"

SHARES = (1.0, 0.7, 0.5, 0.3, 0.0)
GATES = ("no_partial", "age_only")
# The three protection families. "partial" is the COUPLED engine — the one
# every stored number in data/backtest/ was measured on — so its share curve
# must reproduce b121/b121b row for row (integrity()). "tp1" arms BE+trail on a
# TP1 TOUCH whatever the share; "none" never arms them. tp1 minus none at a
# fixed share is a PURE protection effect; the slope along tp1 is a PURE share
# effect. That is the decomposition b121b's single curve could not express.
MODES = ("partial", "tp1", "none")


def _share_fn(value):
    if value == "grade":
        return _partial_close_fraction
    return lambda t: (float(value), "lab_flat_share")


def arm_name(mode: str, value) -> str:
    if value == "grade":
        return f"{mode}::live_grade_share"
    return f"{mode}::share_{value:.1f}"


def arms() -> list[tuple[str, str, object]]:
    """(name, protection_mode, share_fn_value) — name carries the family so a
    reader can never mistake the coupled row for the unprotected one."""
    out = []
    for mode in MODES:
        out.append((arm_name(mode, "grade"), mode, "grade"))
    for value in SHARES:
        for mode in MODES:
            out.append((arm_name(mode, value), mode, value))
    return out


ARM_NAMES = tuple(n for n, _, _ in arms())


def measure_leg(m15, h1, h4) -> dict:
    funnel = b81.funnel_fn(m15, h1, h4)
    ts = lh.live_time_stop_bars(m15)
    grid = {}
    for gate in GATES:
        for name, mode, value in arms():
            kw = dict(lh.LADDER, time_stop_bars=ts,
                      protection_mode=mode, time_stop_gate=gate)
            if value != "grade":
                kw["partial_share_fn"] = _share_fn(value)
            res = backtest_ohlc(m15, funnel, min_rr=lh.MIN_RR,
                                spread=lh.SPREAD, min_grade=lh.LIVE_MIN_GRADE,
                                **kw)
            grid[f"{gate}::{name}"] = lh.r_stats(res, time_stop_bars=ts)
    return {"_bars": len(m15), "_first": int(m15[0]["time"]),
            "_last": int(m15[-1]["time"]), "_time_stop_bars": ts,
            "grid": grid}


def _g(led, leg, gate, arm, metric="exp_R"):
    return led[leg]["grid"][f"{gate}::{arm}"][metric]


INC_ARM = arm_name("partial", "grade")


def decomposition(led) -> dict:
    """The numbers the confound hid, per leg, at the stored gate."""
    out = {}
    for leg in LEGS:
        # 1. PURE PROTECTION EFFECT at share=0.0 — the coupled curve's left end
        #    vs the same share with protection held on. This is the size of the
        #    thing b121b's curve was actually measuring at its best point.
        prot0 = _delta(led, leg, arm_name("tp1", 0.0), arm_name("none", 0.0))
        # 2. PURE PROTECTION EFFECT at the live share rule.
        prot_inc = _delta(led, leg, arm_name("tp1", "grade"),
                          arm_name("none", "grade"))
        # 3. PURE SHARE EFFECT with protection HELD: the candidate's shape
        #    (0.3) against no-riding (1.0) on the always-protected curve.
        share_03_vs_10 = _delta(led, leg, arm_name("tp1", 0.3),
                                arm_name("tp1", 1.0))
        # 4. Same on the never-protected curve — if the two disagree in sign
        #    the "share lever" was protection all along.
        share_03_vs_10_unprot = _delta(led, leg, arm_name("none", 0.3),
                                       arm_name("none", 1.0))
        out[leg] = {
            "protection_at_share_0_R": prot0,
            "protection_at_live_share_R": prot_inc,
            "share_0_3_vs_1_0_protected_R": share_03_vs_10,
            "share_0_3_vs_1_0_unprotected_R": share_03_vs_10_unprot,
            # the time-exit exemption's price, on the candidate's shape
            "time_exit_exemption_cost_R": _delta_gate(
                led, leg, arm_name("partial", 0.3)),
            "incumbent_exp_R": _g(led, leg, "no_partial", INC_ARM),
        }
    return out


def _delta(led, leg, a, b, metric="exp_R", nd=3):
    x, y = _g(led, leg, "no_partial", a, metric), _g(led, leg, "no_partial", b, metric)
    return round(x - y, nd) if x is not None and y is not None else None


def _delta_gate(led, leg, arm, metric="exp_R", nd=3):
    """age_only minus no_partial for one arm: what the exemption is worth."""
    x = _g(led, leg, "age_only", arm, metric)
    y = _g(led, leg, "no_partial", arm, metric)
    return round(x - y, nd) if x is not None and y is not None else None


def share_curve(led, mode: str, gate: str = "no_partial") -> dict:
    """exp_R vs share along ONE protection family, per leg, plus where the
    live incumbent (coupled) row sits inside it."""
    out = {}
    for leg in LEGS:
        pts = [(s, _g(led, leg, gate, arm_name(mode, s))) for s in SHARES]
        pts = [(s, v) for s, v in pts if v is not None]
        inc = _g(led, leg, gate, INC_ARM)
        best = max(pts, key=lambda p: p[1])
        out[leg] = {
            "curve": [{"share": s, "exp_R": v} for s, v in pts],
            "best_share": best[0], "best_exp_R": best[1],
            "range_R": round(best[1] - min(v for _, v in pts), 3),
            "monotone_more_riding_better": all(
                pts[i][1] <= pts[i + 1][1] + 1e-9
                for i in range(len(pts) - 1) if pts[i][0] > pts[i + 1][0]),
            "incumbent_exp_R": inc,
            "incumbent_rank": (1 + sum(1 for _, v in pts if v > inc))
            if inc is not None else None,
        }
    return out


def one_sided(pos: int, neg: int) -> bool:
    """b110's contamination test, ADAPTED TO THE LEG COUNT — and the adaptation
    is the whole point, so it is spelled out instead of inherited silently.

    b110 and b119 wrote `pos >= 3 or neg >= 3` on FOUR windows, where 3-of-4
    means a 75% majority with at most one dissent. b121 ran the same literal on
    SIX. This round scores SEVEN legs, and on seven legs `>= 3` is SATISFIED BY
    EVERY POSSIBLE SPLIT (3/4, 4/3, 5/2 ... the two sides always sum to seven,
    so one of them is always >= 4 >= 3): the flag stops being a test and becomes
    a constant True. The abandoned first draft of this round hit exactly that —
    its own anti-wiring pin asserted `not one_sided_ge_3` for a 3-positive /
    4-negative axis, i.e. a genuinely MIXED sign, and went RED because the flag
    could not express mixedness at n=7.

    So the rule is carried over as its INTENT, as a proportion: one-sided means
    a >=3/4 majority AND at most one dissent. On 4 legs that reproduces b110's
    literal exactly (3/4 with 0-1 dissent); on 7 legs it asks for 6 or 7 with at
    most one dissent. A 3/4 split — the shape b110 was written to catch — is
    NOT one-sided on any leg count.
    """
    n = pos + neg
    if n == 0:
        return False
    majority, minority = max(pos, neg), min(pos, neg)
    return majority * 4 >= n * 3 and minority <= 1


def neutrality(led) -> dict:
    """b110's test applied to EACH axis separately: a one-sided sign across the
    independent windows is a systematic effect, a mixed sign is no lever (see
    one_sided() for the leg-count adaptation and why the bare `>=3` literal
    cannot be used at n=7). Reported for the fresh pair separately so a reader
    cannot mistake in-sample one-sidedness for replication."""
    dec = decomposition(led)
    keys = ("protection_at_share_0_R", "protection_at_live_share_R",
            "share_0_3_vs_1_0_protected_R", "share_0_3_vs_1_0_unprotected_R",
            "time_exit_exemption_cost_R")
    out = {}
    for name in keys:
        d = {leg: dec[leg][name] for leg in LEGS}
        vals = [v for v in d.values() if v is not None]
        pos = sum(1 for v in vals if v > 0)
        neg = sum(1 for v in vals if v < 0)
        fresh = [d[w] for w in FRESH if d[w] is not None]
        out[name] = {
            "per_leg": d, "n_legs": len(vals), "positive": pos, "negative": neg,
            "one_sided_ge_3": one_sided(pos, neg),
            "fresh_legs": {w: d[w] for w in FRESH},
            "fresh_all_same_sign": (len(fresh) == len(FRESH)
                                    and (all(v > 0 for v in fresh)
                                         or all(v < 0 for v in fresh))),
            "max_abs_R": max((abs(v) for v in vals), default=None),
            "mean_R": round(sum(vals) / len(vals), 4) if vals else None,
        }
    return out


def integrity(led, step1: dict, step2: dict) -> dict:
    """The stored rows this round must reproduce, or the decomposition is
    splicing two funnels (b121b's merge check, applied backwards). The
    `partial` family IS the coupled engine, so every b121/b121b arm must land
    byte-identical on it."""
    checks = {}
    for leg in LEGS:
        s1 = step1[leg]["share_grid"]
        s2 = step2[leg]["share_grid"]
        g = led[leg]["grid"]
        checks[leg] = {
            "incumbent_matches_step1": g[f"no_partial::{INC_ARM}"] == s1[INCUMBENT],
            "flat_0_3_matches_step1": g[f"no_partial::{arm_name('partial', 0.3)}"]
            == s1["flat_0.30"],
            "flat_0_5_matches_step1": g[f"no_partial::{arm_name('partial', 0.5)}"]
            == s1["flat_0.50"],
            "flat_0_7_matches_step1": g[f"no_partial::{arm_name('partial', 0.7)}"]
            == s1["flat_0.70"],
            "flat_1_0_matches_step1": g[f"no_partial::{arm_name('partial', 1.0)}"]
            == s1["b66b_winner_as_measured_const_1.0"],
            "flat_0_0_matches_step2": g[f"no_partial::{arm_name('partial', 0.0)}"]
            == s2["flat_0.0"],
        }
    return checks


def main(argv: list[str]) -> int:
    rederive = "--rederive" in argv
    step1 = json.load(open(STEP1))
    step2 = json.load(open(STEP2))
    if rederive:
        led = json.load(open(OUT))
    else:
        led = {"_note": "b123: decompose the share axis from the BE/trail "
                        "protection axis and from the time-exit exemption. "
                        "Three families (P protection at fixed share, S share "
                        "at fixed protection, T time-stop gate), one parameter "
                        "at a time, cached+W1..W6, same harness/bars as "
                        "b121/b121b.",
               "_engine_lever": "engines/backtest.py protection_mode "
                                "(partial|tp1|none) and time_stop_gate "
                                "(no_partial|age_only); both default to the "
                                "stored behaviour, so no pre-b123 number moves",
               "_live_coupling_still_in_place": "position_daemon arms BE only "
                                                "after a TP FILL; "
                                                "engines/trade_management.py "
                                                "untouched",
               "_incumbent_ladder": {"tp1_position": lh.LADDER["tp1_position"],
                                     "trail_after_partial": lh.LADDER["trail_after_partial"],
                                     "trail_floor": lh.LADDER["trail_floor"],
                                     "share_fn": "engines.trade_management._partial_close_fraction"},
               "_live_min_grade": lh.LIVE_MIN_GRADE,
               "_selection_legs": list(SELECTION), "_fresh_legs": list(FRESH),
               "_shares": list(SHARES), "_gates": list(GATES)}
        for leg in LEGS:
            print(f"##### {leg} #####", flush=True)
            m15, h1, h4 = _rows_for(leg)
            led[leg] = measure_leg(m15, h1, h4)

    led["_integrity"] = integrity(led, step1, step2)
    bad = {leg: c for leg, c in led["_integrity"].items()
           if not all(v for v in c.values())}
    if bad:
        raise AssertionError(f"stored rows do not reproduce: {bad}")
    led["_curve_coupled_live_engine"] = share_curve(led, "partial")
    led["_curve_protection_always"] = share_curve(led, "tp1")
    led["_curve_protection_never"] = share_curve(led, "none")
    led["_curve_protection_always_age_only"] = share_curve(led, "tp1",
                                                           gate="age_only")
    led["_decomposition"] = decomposition(led)
    led["_neutrality"] = neutrality(led)
    # b122's arm-identity check, run on this round's own arms: for the LIVE
    # share rule the three protection families must be the SAME trade, because
    # live's function returns 1.0 for every non-A ticket (closed at TP1 before
    # any arming) and 0.3 for the A lane (armed under all three modes). If they
    # differ, one of the modes is not what it is named for.
    led["_arm_identity_live_share"] = {
        leg: {"partial_eq_tp1": (led[leg]["grid"][f"no_partial::{INC_ARM}"]
                                 == led[leg]["grid"]
                                 [f"no_partial::{arm_name('tp1', 'grade')}"]),
              "partial_neq_none": (led[leg]["grid"][f"no_partial::{INC_ARM}"]
                                   != led[leg]["grid"]
                                   [f"no_partial::{arm_name('none', 'grade')}"])}
        for leg in LEGS}
    bad = [leg for leg, v in led["_arm_identity_live_share"].items()
           if not (v["partial_eq_tp1"] and v["partial_neq_none"])]
    if bad:
        raise AssertionError(f"arm identity failed on {bad} — the protection "
                             "modes are not the dials they are named for (b122)")

    _report(led)
    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))
    return 0


def _report(led: dict) -> None:
    print("=== exp_R by share, per protection family (gate=no_partial) ===")
    print(f"{'leg':8s}{'arm':10s}" + "".join(f"{s:>9.1f}" for s in SHARES)
          + f"{'INC':>9s}")
    for leg in LEGS:
        for mode in MODES:
            row = [_g(led, leg, "no_partial", arm_name(mode, s)) for s in SHARES]
            print(f"{leg:8s}{mode:10s}" + "".join(f"{v!s:>9}" for v in row)
                  + f"{_g(led, leg, 'no_partial', INC_ARM)!s:>9}")
    print("=== decomposition (R, gate=no_partial) ===")
    print(f"{'leg':8s}{'prot@0.0':>10s}{'prot@live':>11s}{'sh3v10 P':>10s}"
          f"{'sh3v10 N':>10s}{'ts_cost':>9s}")
    for leg in LEGS:
        d = led["_decomposition"][leg]
        print(f"{leg:8s}{d['protection_at_share_0_R']!s:>10}"
              f"{d['protection_at_live_share_R']!s:>11}"
              f"{d['share_0_3_vs_1_0_protected_R']!s:>10}"
              f"{d['share_0_3_vs_1_0_unprotected_R']!s:>10}"
              f"{d['time_exit_exemption_cost_R']!s:>9}")
    print("=== b110 neutrality per axis ===")
    for name, v in led["_neutrality"].items():
        print(f"{name:38s} pos={v['positive']} neg={v['negative']} "
              f"one_sided_ge_3={v['one_sided_ge_3']} fresh={v['fresh_legs']} "
              f"fresh_same_sign={v['fresh_all_same_sign']} mean={v['mean_R']}")
    print("=== incumbent rank inside each curve (1 = best of 5) ===")
    for leg in LEGS:
        p = led["_curve_protection_always"][leg]
        n = led["_curve_protection_never"][leg]
        c = led["_curve_coupled_live_engine"][leg]
        print(f"{leg:8s} coupled best={c['best_share']} mono={c['monotone_more_riding_better']}"
              f" | protected best={p['best_share']} range={p['range_R']}"
              f" mono={p['monotone_more_riding_better']}"
              f" | unprotected best={n['best_share']} range={n['range_R']}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
