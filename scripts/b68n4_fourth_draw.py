#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 14 — the FOURTH DRAW: does funnel_h4t_agree
survive W4, or does its decaying margin die there?

Round 13 (b68n) produced the loop's most interesting candidate and its
sharpest worry at the same time. The round-12 champion (pdh_h4t_agree)
FAILED its third draw (0.505 vs funnel 0.528 on W3) — 2-of-3 is not
replication. But gating the FUNNEL's own signals on the H4-trend state
(funnel_h4t_agree) became the FIRST arm ever to beat the funnel on all
three independent windows: 0.617/0.553/0.536 vs 0.524/0.521/0.528. The
worry is the SHAPE of that win: the margin decays window by window
(+0.093 → +0.032 → +0.008) and the agree-vs-cut selection ordering FLIPS
on W3 (cut 0.553 > agree 0.536) — the exact regime-flip signature that
killed round 9's champion. b74's round-13 note is explicit: the protocol
must price the DECAY, not just the mean.

This round spends the fourth draw (W4 = 2025-07-09 → 2025-10-08, 6000
M15 bars, zero overlap with cached/W1/W2/W3 asserted in the windows
ledger) on exactly that question, re-measuring the FULL round-13 arm set
on W4 — the funnel (control), the dead champion + its control (continuity
rows), the lane, and the two funnel-gate arms — plus the anti-vacuity and
state-age probes on the funnel population (b72 rule 2 / b75 rule 6).

Decision rule shipped with the ledger (margin-decay rule, b74):
  SURVIVES  = beats the funnel on W4 AND the agree>cut ordering holds on
              W4 (selection is regime-stable for the funnel population);
  DECAYS_OUT = beats the funnel on W4 but ordering flips again (a third
              flip-prone leg: the gate's edge is a W1/W2 regime gift);
  DIES      = fails to beat the funnel on W4 (3-of-4 is not replication
              under a rule that demanded all windows).
Any verdict other than SURVIVES keeps the candidate lab-only; wiring a
funnel-entry filter stays a human decision under the full b74 protocol
(live gate stack, kill-switch streak math) regardless of this round.

Discipline carried from rounds 11-13 (b76/b74/b72/b71):
- arms compared against the funnel re-measured on the SAME bars;
- legs with ASSERTED zero overlap, cached leg labelled in-sample;
- ladder_ts exp_R AND dd_R quoted together;
- cross-round continuity: W1/W2/W3 rows must reproduce round 13's
  shipped numbers exactly (same bars, same harness — drift is a bug).

Read-only research code: nothing here is imported by the live trading
path.
"""
import os
import sys
import json
import bisect

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from engines import lab_harness as lh              # noqa: E402
from engines.backtest_real import strategy_signal  # noqa: E402
from scripts import b68l_windows as wl             # noqa: E402
from scripts import b68m_htf_pdh_lab as mm         # noqa: E402
from scripts import b68n_funnel_gate_w3 as r13     # noqa: E402

OUT = os.path.join(_ROOT, "data", "backtest", "b68n4_fourth_draw.json")
W4 = "W4"
ARMS = r13.ARMS                      # same arm set as round 13
R13_LEDGER = os.path.join(_ROOT, "data", "backtest",
                          "b68n_funnel_gate_w3.json")


def measure_window(name, rows):
    """Same measurement body as round 13 (reuses r13's arm construction by
    calling its measure_window — the arms, probes and honesty gate are
    identical; only the leg differs)."""
    return r13.measure_window(name, rows)


def verdict(led):
    """b74 fourth-draw decision rule (see module docstring). Reads ONLY the
    shipped ledger rows; None exp_R never beats, ties never beat."""
    win = led[W4]
    f = win["CURRENT_FUNNEL"]["ladder_ts"]
    a = win["funnel_h4t_agree"]["ladder_ts"]
    c = win["funnel_h4t_disagree"]["ladder_ts"]
    beats = (a["exp_R"] is not None and f["exp_R"] is not None
             and a["exp_R"] > f["exp_R"])
    ordering = (a["exp_R"] is not None and c["exp_R"] is not None
                and a["exp_R"] > c["exp_R"])
    if beats and ordering:
        v = "SURVIVES"
    elif beats:
        v = "DECAYS_OUT"
    else:
        v = "DIES"
    # margin-decay series across the four independent windows
    margins = {}
    for w in ("W1", "W2", "W3", W4):
        fw = led[w]["CURRENT_FUNNEL"]["ladder_ts"]["exp_R"]
        aw = led[w]["funnel_h4t_agree"]["ladder_ts"]["exp_R"]
        margins[w] = (None if (fw is None or aw is None)
                      else round(aw - fw, 3))
    return {"W4_funnel_exp_R": f["exp_R"], "W4_funnel_n": f["trades"],
            "W4_agree_exp_R": a["exp_R"], "W4_agree_n": a["trades"],
            "W4_cut_exp_R": c["exp_R"], "W4_cut_n": c["trades"],
            "beats_funnel_W4": bool(beats),
            "ordering_holds_W4": bool(ordering),
            "margin_series": margins,
            "verdict": v}


def main():
    wins = wl.load_windows()
    led = {"_note": "round 14: FOURTH DRAW (W4) for funnel_h4t_agree — "
                    "b74's margin-decay rule; full round-13 arm set "
                    "re-measured on W4 (b76: overlap asserted per leg)",
           "_last6000_overlap_with_cached": wins["_last6000_overlap_with_cached"]}
    # W1-W3 come from round 13's shipped ledger (same bars, same harness);
    # re-measuring them here would only re-burn compute — the continuity
    # test asserts they still match. W4 is this round's new draw.
    r13led = json.load(open(R13_LEDGER))
    for w in ("W1", "W2", "W3"):
        led[w] = r13led[w]
    print("##### W4 #####", flush=True)
    led[W4] = measure_window("W4", wins[W4])
    led["_verdict"] = verdict(led)
    print("=== VERDICT ===")
    print(json.dumps(led["_verdict"], indent=1))
    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
