#!/usr/bin/env python3
"""b119 — RE-PRICE THE b66 / b66b EXIT-GRID DECISIONS UNDER THE CORRECTED ENGINE.

WHY THIS EXISTS (procedure from b117, generalising b83)
=======================================================
b117 re-priced ONE pre-b105 exit decision (b65's runner trail) and its evidence
shrank ~15x. The reason was not that the trail moved: it is that the engine
b65 measured on contained a PHANTOM POPULATION — pre-b105,
`_partial_close_fraction` was fed a trade dict with none of the four live ladder
fields (b108's finding), so `rr_remaining` defaulted to 0.0, the
`rr_remaining <= 1.2` weak branch tripped on EVERY call, and the function
returned the CONSTANT (1.0, 'weak_full_exit_at_tp1'). At the same time
`engines/backtest.py` booked the post-TP1 runner at FULL size on top of the
realized partial and kept the ticket alive after a share>=1.0 close.

b117's rule: when an engine fix DELETES A POPULATION rather than shifting a
number, every stored decision whose evidence was measured ON that population
must be re-priced, not just re-baselined. The whole b55-b66 exit family ran
there. This round takes the two load-bearing ones.

  b66  (data/backtest/b66_exit_grid.json): 2D grid TP1-step x partial share,
       "TP1=.60 wins M5 (+2.1R) but .45 wins M15 (+7.0R) — contradictory,
       incumbent .50 kept". The tp1_position arms only matter if a runner
       survives TP1 to ride toward the final TP. Pre-b105 a phantom full-size
       runner survived on EVERY trade, so the step size was priced on trades
       that live would have closed flat at TP1.

  b66b (data/backtest/b66b_share.json): the SHARE dimension, and the only
       exit-side finding in this repo that claims REAL EDGE rather than local
       optimality: "live grade-based share 184.3R M5 / 211.5R M15 vs flat
       30/50/70% all far worse (91-168R). Grade-weighted partial sizing
       CONFIRMED as real edge."

       That sentence cannot be true as stated, and the proof is cheap: the arm
       b66b called "live grade-fn share" passed
       `partial_share_fn=lambda t: _partial_close_fraction(t)` into an engine
       whose trade dict could not satisfy that function's contract. It was not
       a grade-weighted arm at all — it was CONSTANT 1.0, i.e. "close the whole
       position at TP1, never keep a runner". So the comparison b66b decided on
       was between (a) no runner anywhere and (b) a phantom full-size runner
       everywhere, inflated by the double-count. Two defects, opposite
       directions, on the two sides of ONE comparison. Post-b105/b109 the grade
       fn discriminates (A-grade keeps 0.3, everything else closes), so the
       incumbent arm is a THIRD thing that has never been measured.

WHAT THIS MEASURES
==================
cached + W1..W4 (the b76/b81 window set), identical bars per leg, ONE harness
(engines.lab_harness.run_arm — plain/ladder/ladder_ts come out of it, no
hand-copied funnel, no hand-copied ladder), the live grade gate and the live
min_rr imported, the runner trail and its $ floor DERIVED from live (b118).

  grid A  tp1_position 0.40/0.45/0.50(incumbent)/0.60/0.70, live grade share fn
  grid B  share: live grade fn (incumbent) / constant 1.0 (what b66b's winner
          actually was) / flat 0.30 / flat 0.50 / flat 0.70
  proof   the arm-identity census: over the real funnel signals, how many
          share values does the pre-b109 trade dict give vs the post-b109 one
          (it must be "constant 1.0" vs "discriminating", measured not argued)
  verdict b110's neutrality test: arm-minus-incumbent delta per leg; one-sided
          across >=3 independent windows = the stored ranking was contaminated.

Read-only research: nothing here is imported by the live trading path, no gate
is touched, and every live value (grade gate, min_rr, trail multiplier, trail
floor, share function) is IMPORTED or PROBED, never restated.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                    # noqa: E402
from engines.backtest import backtest_ohlc                # noqa: E402
from engines.trade_management import (LADDER_FIELDS,      # noqa: E402
                                      _partial_close_fraction)
from scripts import b81_lane_rescore as b81               # noqa: E402
from scripts import b68l_windows as wl                    # noqa: E402

OUT = "data/backtest/b119_exit_grid_reprice.json"
LEGS = b81.LEGS
WINDOWS = b81.WINDOWS

# b66's TP1-step arms, verbatim in VALUE (they are grid parameters, not live
# constants — the live value is the incumbent, read out of the harness below).
TP1_ARMS = (("tp1_0.40", 0.40), ("tp1_0.45", 0.45),
            ("incumbent_tp1_0.50", lh.LADDER["tp1_position"]),
            ("tp1_0.60", 0.60), ("tp1_0.70", 0.70))

# b66b's share arms. `b66b_winner_as_measured` is the arm b66b actually scored
# (constant 1.0), named so the ledger cannot be re-read as "the grade fn won".
SHARE_ARMS = (("incumbent_live_grade_fn", "grade"),
              ("b66b_winner_as_measured_const_1.0", 1.0),
              ("flat_0.30", 0.30), ("flat_0.50", 0.50), ("flat_0.70", 0.70))


def _share_fn(value):
    """A flat share arm, in the same (share, reason) contract live uses."""
    if value == "grade":
        return _partial_close_fraction
    return lambda t: (float(value), "lab_flat_share")


def arm_identity_census(m15, h1, h4) -> dict:
    """The decisive cheap measurement: WHICH arm did b66b score?

    b109's defect, replayed on the real funnel signals instead of asserted: the
    pre-b109 backtest trade dict carried only entry/sl/tp/grade/side, so
    _partial_close_fraction saw rr_remaining=0.0 and returned 1.0 on every
    call. The post-b109 dict carries the four ladder fields, so the same
    function discriminates. Count both over the signals the live gate would
    actually trade.
    """
    funnel = b81.funnel_fn(m15, h1, h4)
    pre = {}
    post = {}
    total = 0
    differ = 0
    a_grade = 0
    for row in m15:
        s = funnel(row)
        if not s:
            continue
        if str(s.get("grade", "")) > lh.LIVE_MIN_GRADE:
            continue                          # the live gate rejects it
        total += 1
        # the pre-b109 trade dict: exactly the keys backtest.py built then
        old_trade = {"entry": s["entry"], "sl": s["sl"], "tp": s["tp"],
                     "side": s["side"], "grade": s.get("grade")}
        # the post-b109 dict: the same plus whatever ladder_fields the signal
        # carries (backtest.py copies them in by name, nothing else)
        new_trade = dict(old_trade)
        for k in LADDER_FIELDS:
            if k in s:
                new_trade[k] = s[k]
        sp, _ = _partial_close_fraction(old_trade)
        sq, _ = _partial_close_fraction(new_trade)
        pre[round(sp, 2)] = pre.get(round(sp, 2), 0) + 1
        post[round(sq, 2)] = post.get(round(sq, 2), 0) + 1
        if abs(sp - sq) > 1e-9:
            differ += 1
        if str(s.get("grade", "")) == "A":
            a_grade += 1
    return {"gate_passed_signals": total,
            "a_grade_signals": a_grade,
            "pre_b109_share_histogram": dict(sorted(pre.items())),
            "post_b109_share_histogram": dict(sorted(post.items())),
            "signals_whose_share_changed": differ,
            "pre_b109_is_constant_1.0": set(pre) == {1.0},
            "post_b109_discriminates": len(post) > 1}


def _grid(leg_rows, funnel, ts, arms, param) -> dict:
    """Score one grid through the ONE harness (extra_modes = its extension point).

    Every arm carries `time_stop_bars` so its headline row is the honest
    ladder_ts shape (b71): an arm scored without the live time exit is a
    different exit rule than the one production runs.
    """
    def _value(v):
        return _share_fn(v) if param == "partial_share_fn" else v
    extras = tuple((name, dict(lh.LADDER, time_stop_bars=ts,
                               **{param: _value(v)}))
                   for name, v in arms)
    out = lh.run_arm(leg_rows, funnel, extra_modes=extras)
    return {name: out[name] for name, _v in arms}


def _incumbent_check(m15, funnel, ts) -> dict:
    """Sanity: the incumbent arm must reproduce the harness's own ladder_ts row
    (the merit bar), otherwise this round is measuring a different funnel."""
    res = backtest_ohlc(m15, funnel, min_rr=lh.MIN_RR, spread=lh.SPREAD,
                        min_grade=lh.LIVE_MIN_GRADE,
                        **dict(lh.LADDER, time_stop_bars=ts))
    return lh.r_stats(res, time_stop_bars=ts)


def frame_probe(m15, h1, h4) -> dict:
    """How much of the gap is the ENGINE and how much is the MEASUREMENT FRAME?

    b66/b66b called `backtest_ohlc` directly with no `min_grade` and no
    `time_stop_bars`, so their arms were scored on (a) every C-grade setup the
    live executor rejects and (b) an exit rule live never gives (no 36h time
    exit) — the b71/b80 defect classes, independent of the phantom runner. This
    decomposes the two: the SAME engine, three frames, one row each. Nothing is
    hand-rolled — `min_grade=None` and the harness's own `ladder` (no-ts) row
    are the harness's extension points.
    """
    funnel = b81.funnel_fn(m15, h1, h4)
    graded = lh.run_arm(m15, funnel)                    # live-parity frame
    ungraded = lh.run_arm(m15, funnel, min_grade=None)  # b66/b66b's grade frame
    return {
        "b66_frame_ungraded_no_ts": ungraded["ladder"],
        "ungraded_with_live_ts": ungraded["ladder_ts"],
        "corrected_frame_graded_with_ts": graded["ladder_ts"],
        "grade_gate_cost_R": (round(graded["ladder_ts"]["exp_R"]
                                    - ungraded["ladder_ts"]["exp_R"], 3)
                              if graded["ladder_ts"]["exp_R"] is not None
                              and ungraded["ladder_ts"]["exp_R"] is not None
                              else None),
        "time_exit_cost_R": (round(ungraded["ladder_ts"]["exp_R"]
                                   - ungraded["ladder"]["exp_R"], 3)
                             if ungraded["ladder_ts"]["exp_R"] is not None
                             and ungraded["ladder"]["exp_R"] is not None
                             else None),
    }


def measure_leg(m15, h1, h4) -> dict:
    funnel = b81.funnel_fn(m15, h1, h4)
    ts = lh.live_time_stop_bars(m15)
    return {"_bars": len(m15), "_first": int(m15[0]["time"]),
            "_last": int(m15[-1]["time"]), "_time_stop_bars": ts,
            "funnel_baseline": _incumbent_check(m15, funnel, ts),
            "tp1_grid": _grid(m15, funnel, ts, TP1_ARMS, "tp1_position"),
            "share_grid": _grid(m15, funnel, ts, SHARE_ARMS, "partial_share_fn"),
            "arm_identity": arm_identity_census(m15, h1, h4),
            "frame_probe": frame_probe(m15, h1, h4)}


def _frame_summary(fp: dict) -> dict:
    """Flatten the frame probe to the numbers a reader (and a test) needs."""
    out = {k: v for k, v in fp.items() if not isinstance(v, dict)}
    for row in ("b66_frame_ungraded_no_ts", "ungraded_with_live_ts",
                "corrected_frame_graded_with_ts"):
        out[f"{row}_exp_R"] = fp[row]["exp_R"]
        out[f"{row}_trades"] = fp[row]["trades"]
        out[f"{row}_net_R"] = fp[row]["net_R"]
    return out


def _neutrality(led, grid_key, arms, incumbent) -> dict:
    """b110's test: arm-minus-incumbent exp_R per leg, then the sign census over
    the FOUR INDEPENDENT windows (cached is not independent evidence).

    b66's stored verdict was on TOTAL R (net_R), b66b's too, so the net_R
    margin is carried alongside exp_R — a re-decision that only looked at
    per-trade expectancy would not be testing the claim that was made.
    """
    per_leg = {}
    per_leg_net = {}
    for leg in LEGS:
        row = led[leg][grid_key]
        base = row[incumbent]["exp_R"]
        base_net = row[incumbent]["net_R"]
        per_leg[leg] = {name: (round(r["exp_R"] - base, 3)
                               if r["exp_R"] is not None and base is not None
                               else None)
                        for name, r in row.items()}
        per_leg_net[leg] = {name: (round(r["net_R"] - base_net, 1)
                                   if r["net_R"] is not None and base_net is not None
                                   else None)
                            for name, r in row.items()}
    signs = {}
    for name, _v in arms:
        if name == incumbent:
            continue
        vals = [per_leg[w][name] for w in WINDOWS if per_leg[w][name] is not None]
        net_vals = [per_leg_net[w][name] for w in WINDOWS
                    if per_leg_net[w][name] is not None]
        signs[name] = {"per_window": {w: per_leg[w][name] for w in WINDOWS},
                       "per_window_net_R": {w: per_leg_net[w][name] for w in WINDOWS},
                       "wins": sum(1 for v in vals if v > 0),
                       "losses": sum(1 for v in vals if v < 0),
                       "net_wins": sum(1 for v in net_vals if v > 0),
                       "one_sided_ge_3": (sum(1 for v in vals if v > 0) >= 3
                                          or sum(1 for v in vals if v < 0) >= 3)}
    return {"per_leg_delta_exp_R": per_leg, "per_leg_delta_net_R": per_leg_net,
            "arm_verdicts": signs}


def main() -> int:
    wins = wl.load_windows()
    c = json.load(open("data/backtest/ab_aggressive_data.json"))
    led = {"_note": "b119: b66's TP1-step grid and b66b's share grid re-priced "
                    "under the b105+b109-corrected engine, per b117's rule "
                    "(an engine fix that deletes a POPULATION invalidates every "
                    "decision measured on it). Arms differ in ONE exit "
                    "parameter; same bars, same harness, live grade gate and "
                    "min_rr imported, runner trail and $ floor derived from "
                    "live (b118).",
           "_incumbent_ladder": {"tp1_position": lh.LADDER["tp1_position"],
                                 "partial_tp1_share": lh.LADDER["partial_tp1_share"],
                                 "trail_after_partial": lh.LADDER["trail_after_partial"],
                                 "trail_floor": lh.LADDER["trail_floor"],
                                 "share_fn": "engines.trade_management._partial_close_fraction"},
           "_live_min_grade": lh.LIVE_MIN_GRADE,
           "_live_min_rr_note": "lab MIN_RR=0.0 (raw expectancy); the live gate "
                                "value is imported by run_arm, never restated",
           "_shipped_claims": {
               "b66": "TP1=.60 wins M5 (+2.1R) but .45 wins M15 (+7.0R) — "
                      "contradictory, incumbent .50 kept, loses <3% on either",
               "b66b": "live grade-based share 184.3R M5 / 211.5R M15 vs flat "
                       "30/50/70% all far worse (91-168R). Grade-weighted "
                       "partial sizing CONFIRMED as real edge."}}
    print("##### cached #####", flush=True)
    led["cached"] = measure_leg(c["M15"], c["H1"], c["H4"])
    for w in WINDOWS:
        print(f"##### {w} #####", flush=True)
        led[w] = measure_leg(wins[w]["M15"], wins[w]["H1"], wins[w]["H4"])

    led["_tp1_neutrality"] = _neutrality(led, "tp1_grid", TP1_ARMS,
                                         "incumbent_tp1_0.50")
    led["_share_neutrality"] = _neutrality(led, "share_grid", SHARE_ARMS,
                                           "incumbent_live_grade_fn")
    led["_arm_identity"] = {leg: led[leg]["arm_identity"] for leg in LEGS}
    led["_frame_probe"] = {leg: _frame_summary(led[leg]["frame_probe"])
                           for leg in LEGS}
    led["_funnel_baseline"] = {leg: {k: led[leg]["funnel_baseline"][k] for k in
                                     ("trades", "exp_R", "net_R", "maxDD_R")}
                               for leg in LEGS}

    for key, arms, inc in (("tp1_grid", TP1_ARMS, "incumbent_tp1_0.50"),
                           ("share_grid", SHARE_ARMS, "incumbent_live_grade_fn")):
        print(f"=== exp_R by arm — {key} (ladder_ts) ===")
        hdr = f"{'leg':8s}" + "".join(f"{n[:17]:>19s}" for n, _ in arms)
        print(hdr)
        for leg in LEGS:
            print(f"{leg:8s}" + "".join(
                f"{led[leg][key][n]['exp_R']!s:>19s}" for n, _ in arms))
        print(f"=== net_R by arm — {key} ===")
        print(hdr)
        for leg in LEGS:
            print(f"{leg:8s}" + "".join(
                f"{led[leg][key][n]['net_R']!s:>19s}" for n, _ in arms))
        print(f"=== trades by arm — {key} ===")
        print(hdr)
        for leg in LEGS:
            print(f"{leg:8s}" + "".join(
                f"{led[leg][key][n]['trades']!s:>19s}" for n, _ in arms))

    print("=== b110 neutrality: arm-minus-incumbent exp_R per window ===")
    for label, block, arms, inc in (
            ("tp1", led["_tp1_neutrality"], TP1_ARMS, "incumbent_tp1_0.50"),
            ("share", led["_share_neutrality"], SHARE_ARMS,
             "incumbent_live_grade_fn")):
        print(f"--- {label} (incumbent={inc})")
        for name, v in block["arm_verdicts"].items():
            print(f"  {name:36s} " + " ".join(
                f"{w}={v['per_window'][w]!s:>7s}" for w in WINDOWS) +
                f"  one_sided_ge_3={v['one_sided_ge_3']}")

    print("=== arm identity: what b66b actually scored ===")
    for leg in LEGS:
        ai = led[leg]["arm_identity"]
        print(f"{leg:8s} n={ai['gate_passed_signals']:4d} A={ai['a_grade_signals']:3d} "
              f"pre={ai['pre_b109_share_histogram']} "
              f"post={ai['post_b109_share_histogram']} "
              f"changed={ai['signals_whose_share_changed']} "
              f"const={ai['pre_b109_is_constant_1.0']} "
              f"discrim={ai['post_b109_discriminates']}")

    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
