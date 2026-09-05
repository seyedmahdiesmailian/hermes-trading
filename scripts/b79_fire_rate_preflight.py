#!/usr/bin/env python3
"""b79 — apply the GATE FIRE-RATE STABILITY PRE-FLIGHT to every shipped
round ledger that carries a probe block, and freeze the result
(data/backtest/b79_fire_rate_preflight.json).

This is the b79 rule running on the exact data that motivated it: rounds
12-17 all shipped per-leg probe blocks, so the pass-rate series can be read
back WITHOUT any new measurement, no bridge call, no draw spent. The point
is threefold:

1. PROVE the pre-flight would have stopped round 16 on the probe alone: the
   weekly-runway gate's pass rate swings 36%-68% across the four independent
   windows AND its median room-to-extreme flips sign (+6.46 ATR W1 →
   -0.79 ATR W4) — verdict UNSTABLE, so the four-window ladder measurement
   was, in hindsight, not owed.
2. PROVE the screen is NECESSARY-not-sufficient (round 17's calibration):
   the H4 trend gate is the loop's MOST stable (swing 2.9 pts) and its arm
   STILL failed the merit bar 1-of-4 — STABLE only permits a draw, it never
   promises a lift. b74's lift-vs-control test stays the binding check.
3. RECORD the swing for every oracle the loop has ever measured, so a
   future round quotes the fire-rate SHAPE before spending anything.

Read-only research code: nothing here is imported by the live trading path.
"""
import os
import sys
import json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from engines import lab_fire_rate as lf             # noqa: E402

# b48 seam: redirect the OUTPUT FILE only (state), never code — lets
# tests/test_b79_fire_rate_preflight.py regenerate the ledger into a temp dir
# and require byte equality with the shipped artefact without touching it.
OUT = os.environ.get("B79_PREFLIGHT_OUT") or os.path.join(
    _ROOT, "data", "backtest", "b79_fire_rate_preflight.json")
BT = os.path.join(_ROOT, "data", "backtest")
WINDOWS = ["W1", "W2", "W3", "W4"]

# every shipped ledger that carries a per-leg _probe block (b76-era rounds).
# b68m has only two windows — it is included precisely to show b79 refuses to
# read a curve out of two points (INSUFFICIENT, the b77 lesson).
LEDGERS = [
    ("b68m_htf_pdh_confirm", ["W1", "W2"], "h1"),
    ("b68m_htf_pdh_confirm", ["W1", "W2"], "h4"),
    ("b68n4_fourth_draw", WINDOWS, "h4_pdh"),
    ("b68n4_fourth_draw", WINDOWS, "h4_funnel"),
    ("b68o_weekly_confirm", WINDOWS, None),
    ("b68p_runway_confirm", WINDOWS, None),
    ("b68q_nr7htf_confirm", WINDOWS, None),
]


def main():
    out = {"_note": "b79 pre-flight on every shipped probe ledger: oracle "
                    "pass-rate series read CHRONOLOGICALLY (oldest window "
                    "first, b77 rule); UNSTABLE = close the round on the "
                    "probe alone; STABLE = necessary-not-sufficient, the "
                    "b74 lift test still decides",
           "ledgers": {}}
    for name, windows, oracle in LEDGERS:
        led = json.load(open(os.path.join(BT, name + ".json")))
        tag = name + ((":" + oracle) if oracle else "")
        out["ledgers"][tag] = lf.preflight(led, windows, oracle)

    # The headline facts, computed not hardcoded:
    p = out["ledgers"]["b68p_runway_confirm"]
    q = out["ledgers"]["b68q_nr7htf_confirm"]
    m = out["ledgers"]["b68m_htf_pdh_confirm:h4"]
    out["_headline"] = {
        "round16_runway_gate_verdict": p["verdict"],
        "round16_swing_points": p.get("swing_points"),
        "round16_median_age_sign_flip": p.get("median_age_sign_flip"),
        "round16_would_have_closed_on_probe_alone":
            p["verdict"] == "UNSTABLE",
        "round17_h4_gate_verdict": q["verdict"],
        "round17_swing_points": q.get("swing_points"),
        "round17_stable_yet_arm_failed_merit_bar":
            q["verdict"] == "STABLE",   # 1-of-4 windows, Findings round 17
        "round12_two_windows_verdict": m["verdict"],
    }
    print(json.dumps(out, indent=1))
    json.dump(out, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT), file=sys.stderr)


if __name__ == "__main__":
    main()
