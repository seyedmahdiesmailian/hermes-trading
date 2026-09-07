#!/usr/bin/env python3
"""b118b — RE-DERIVE THE b70 LANE ANSWER FROM NUMBERS THAT REPRODUCE.

WHY THIS EXISTS (todo b118b, filed by b118, 2026-09-07)
=======================================================
b118 re-derived the funnel BAR (live-parity cached 0.278 / W1 0.211 / W2 0.230
/ W3 0.232 / W4 0.233) but left the stored lane-vs-funnel DELTAS in
`data/backtest/b108_rescore_corrected.json` computed against the pre-b109 row,
so every `d_exp_R` in that file carries b109's mixed-sign component
(-0.015..+0.021). b118b's own note calls the re-decision "unlikely to flip
anything" and rates it LOW — but it also says b70's standing answer should be
re-derived from numbers that reproduce rather than argued from. This is that
re-derivation.

THE OBSTACLE THIS ROUND FOUND FIRST (and the real finding)
==========================================================
The item's method was "re-run scripts/b108_rescore_corrected.py". That script
has NEVER RUN END TO END since it shipped (3003cbb, 2026-09-06): line 168
called `redeide_b70(led)` while the function it defines is `redecide_b70`. A
NameError on the last statement of `main()` — after the five legs had been
measured, before the merit bar, the re-decision, the printed tables and the
`json.dump`. The stored ledger therefore came from an earlier draft of the
file, and the shipped test suite could not see it because every b108 test
reads the JSON ARTIFACT and none executes the SCRIPT. That is the b114/b116
disease in a new costume (an artifact that certifies a number, not the code
that makes it), and it is why this round also ships `scripts/
b126_dead_path_scan.py`: a static scan for calls to names the file does not
bind, pinned by tests/test_b118b_lane_redecision_and_b126_dead_scan.py.

WHAT THIS SCRIPT DOES
=====================
It does NOT overwrite b108's ledger — that file is frozen evidence, pinned by
tests/test_b108_rescore_corrected.py (b114's rule: a re-measurement must not
delete the artifact that justified the previous round). It re-executes the
SAME measurement b108 executed — `b81.measure_leg` imported verbatim, same
legs, same bars, same harness — on today's engine, where the harness derives
the runner trail and the $ floor from live (b118) instead of restating 0.50.
Then it diffs, per lane and per window:

  stored_b108_margin  — b108's d_exp_R (pre-b109 bar, trail 0.50, no floor)
  live_parity_margin  — this run's d_exp_R (live-parity bar)
  margin_drift        — the difference, i.e. how much of b108's margin was
                        convention rather than content
and re-applies b74's all-windows rule to the live-parity margins, so the
question "does any lane earn a slot?" is answered on numbers that reproduce.

Read-only research: nothing here is imported by the live trading path, and the
live grade gate + min_rr + trail geometry are IMPORTED from the live modules
(by the harness), never restated.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                    # noqa: E402
from scripts import b81_lane_rescore as b81              # noqa: E402
from scripts import b108_rescore_corrected as b108       # noqa: E402
from scripts import b68l_windows as wl                   # noqa: E402

OUT = "data/backtest/b118b_lane_redecision_live_parity.json"
# The frozen b108 ledger, by its OWN path constant (b118's rule: a re-run
# references the artifact it re-derives, it does not restate the filename).
STORED = b108.OUT
LEGS = b81.LEGS
WINDOWS = b81.WINDOWS
LANES = tuple(b81.PROVENANCE)


def funnel_row(leg: dict) -> dict:
    return leg["funnel_graded"]


def margin_table(new_leg: dict, stored_leg: dict) -> dict:
    """Per lane: this run's margin vs the funnel, and b108's stored margin."""
    out = {}
    for lane in LANES:
        n_lane = new_leg[lane]["graded"]
        s_lane = stored_leg[lane]["graded"]
        out[lane] = {
            "live_parity": {k: n_lane.get(k) for k in
                            ("trades", "exp_R", "net_R", "maxDD_R", "WR%")},
            "stored_b108": {k: s_lane.get(k) for k in
                            ("trades", "exp_R", "net_R", "maxDD_R", "WR%")},
            "d_exp_R_live_parity": _sub(n_lane["exp_R"],
                                        new_leg["funnel_graded"]["exp_R"]),
            "d_exp_R_stored_b108": _sub(s_lane["exp_R"],
                                        stored_leg["funnel_graded"]["exp_R"]),
        }
        if (out[lane]["d_exp_R_live_parity"] is not None
                and out[lane]["d_exp_R_stored_b108"] is not None):
            out[lane]["margin_drift"] = round(
                out[lane]["d_exp_R_live_parity"]
                - out[lane]["d_exp_R_stored_b108"], 3)
        else:
            out[lane]["margin_drift"] = None
        # did the convention change flip the beats/loses verdict on this leg?
        out[lane]["verdict_flipped"] = (
            out[lane]["d_exp_R_live_parity"] is not None
            and out[lane]["d_exp_R_stored_b108"] is not None
            and (out[lane]["d_exp_R_live_parity"] > 0)
            != (out[lane]["d_exp_R_stored_b108"] > 0))
    return out


def _sub(a, b):
    return round(a - b, 3) if (a is not None and b is not None) else None


def redecide(led: dict) -> dict:
    """b74's all-windows rule on the live-parity margins, vs b108's stored
    counts. Same rule, same function (b81.verdict imported by b108 too),
    different numbers."""
    now = b81.verdict(led)
    stored = json.load(open(STORED))["_b70_redecision"]
    for lane, row in now.items():
        row["windows_beaten_stored_b108"] = stored.get(lane, {}).get(
            "windows_beaten")
        row["count_changed"] = (row["windows_beaten"]
                                != row["windows_beaten_stored_b108"])
        row["per_window_drift"] = [
            {"window": p["window"],
             "d_exp_R_live_parity": p["d_exp_R"],
             "d_exp_R_stored_b108": next(
                 (q["d_exp_R"] for q in stored.get(lane, {}).get(
                     "per_window", []) if q["window"] == p["window"]), None),
             "beats_live_parity": p["beats"]}
            for p in row["per_window"]]
    return now


def main():
    stored = json.load(open(STORED))
    wins = wl.load_windows()
    c = json.load(open("data/backtest/ab_aggressive_data.json"))

    led = {"_note":
           "b118b: b108's measurement re-executed on TODAY'S engine — the "
           "harness derives the runner trail and the $ floor from live (b118) "
           "instead of restating 0.50, and the trade dict carries b109's "
           "ladder fields. Same legs, same bars, same b81.measure_leg "
           "(imported, not restated). b108's own ledger is left FROZEN as "
           "evidence; this file is the reproduction.",
           "_harness": {"trail_after_partial": lh.LADDER["trail_after_partial"],
                        "trail_floor": lh.LADDER["trail_floor"],
                        "tp1_position": lh.LADDER["tp1_position"],
                        "partial_tp1_share": lh.LADDER["partial_tp1_share"],
                        "trail_lane": lh.live_runner_trail()["lane"],
                        "min_grade": b81.MIN_SETUP_GRADE},
           "_provenance": {k: v[0] for k, v in b81.PROVENANCE.items()}}

    print("##### cached #####", flush=True)
    led["cached"] = b81.measure_leg("cached", c["M15"], c["H1"], c["H4"])
    for w in WINDOWS:
        print(f"##### {w} #####", flush=True)
        led[w] = b81.measure_leg(w, wins[w]["M15"], wins[w]["H1"], wins[w]["H4"])
    for leg in LEGS:
        led[leg]["_margins"] = margin_table(led[leg], stored[leg])

    led["_funnel_bar"] = {leg: {
        "live_parity_exp_R": led[leg]["funnel_graded"]["exp_R"],
        "live_parity_trades": led[leg]["funnel_graded"]["trades"],
        "stored_b108_exp_R": stored[leg]["funnel_graded"]["exp_R"],
        "stored_b108_trades": stored[leg]["funnel_graded"]["trades"],
        "drift": _sub(led[leg]["funnel_graded"]["exp_R"],
                      stored[leg]["funnel_graded"]["exp_R"])} for leg in LEGS}
    led["_b70_redecision_live_parity"] = redecide(led)

    print("=== FUNNEL BAR: stored b108 vs this run ===")
    print(json.dumps(led["_funnel_bar"], indent=1))
    print("=== b70 RE-DECISION (live-parity margins) ===")
    print(json.dumps({k: {kk: vv for kk, vv in v.items()
                          if kk not in ("per_window", "inflation_neutrality")}
                      for k, v in
                      led["_b70_redecision_live_parity"].items()}, indent=1))
    print("=== PER-LANE MARGIN DRIFT (live_parity minus stored_b108) ===")
    for leg in LEGS:
        for lane, row in led[leg]["_margins"].items():
            print(f"{leg:7s} {lane:24s} exp_R {row['stored_b108']['exp_R']}"
                  f" -> {row['live_parity']['exp_R']}"
                  f" | margin {row['d_exp_R_stored_b108']:+} ->"
                  f" {row['d_exp_R_live_parity']:+}"
                  f" (drift {row['margin_drift']:+})"
                  f"{' FLIPPED' if row['verdict_flipped'] else ''}")
    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
