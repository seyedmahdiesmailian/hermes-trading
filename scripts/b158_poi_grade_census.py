#!/usr/bin/env python3
"""b158 — CENSUS THE POI GRADE UNDER THE TWO WORLDS BEFORE PICKING A FIX.

b157 left the score card: grade_poi is fed ONLY the entry-TF sets
(has_active_ob / has_active_fvg from unmitigated_obs / unfilled_fvgs), while
the bias that actually drives the plan is derived from the MERGED sets
(obs+h1_obs, fvgs+h1_fvgs). So a POI graded "C: weak" can sit on a bias
carried mostly by H1 structure, and vice versa — the label and the decision
see different worlds.

b110's rule: measure first, per outcome.  This census answers the one
question that decides between the two fix shapes in the backlog item:

  (a) merge the H1 sets into grade_poi  — correct IF the merged grade tells
      us more about forward outcomes than the entry-TF-only grade (i.e. the
      H1 half of the world carries real information the label is dropping);
  (b) leave the label entry-TF-only (and document/rename honestly) — correct
      IF the merge buys nothing.

Nothing on the DECISION path consumes `poi` today (grep-verified by b157:
only ctx['quality']['smc_poi'], a plan-record label), so THIS is a display
measurement, not a funnel round; no run_backtest needed to decide it.  If a
future round wants poi in a gate, b158's closing note says that needs its
own funnel evidence.

WHAT IT MEASURES on the cached bars (no bridge call, read-only):
  1. grade distribution arm SQ (status quo, entry-TF only) vs arm MERGED
     (same sets _derive_smc_bias gets), and the per-bar flip rate;
  2. BIAS AGREEMENT: how often the grade's confluence (has_ob/has_fvg
     booleans) contradicts the sign of the bias that IS driving the plan —
     the operator-confusion metric the item was filed for;
  3. FORWARD SEPARATION: mean ATR-normalised drift over the next 12 bars,
     signed ALONG the bias, bucketed by grade, for both arms.  A grade that
     cannot rank forward outcomes in either arm is decoration, and the fix
     shape is then "be honest in the label", not "merge".

Writes data/backtest/b158_poi_grade_census.json.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines.smc import (_derive_smc_bias, grade_poi, detect_fair_value_gaps,
                         detect_order_blocks, detect_liquidity_sweep,
                         market_structure_phase, premium_discount_zone,
                         active_killzone_session)
import datetime as _dt

OUT = "data/backtest/b158_poi_grade_census.json"
CACHED = "data/backtest/ab_aggressive_data.json"
FWD_BARS = 12          # 3h on M15 — matches the intraday horizon the plan lives on
GRADES = ("A+", "A", "B", "C")


def atr14(rows: list[dict], i: int) -> float:
    lo = max(0, i - 14)
    trs = []
    for r in rows[lo:i + 1]:
        trs.append(r["high"] - r["low"])
    return (sum(trs) / len(trs)) if trs else 0.0


def grade_inputs(m5_rows, h1_rows):
    """Rebuild, bar-by-bar, EXACTLY what smc_analyse computes for the bias
    and for grade_poi today, so the two arms differ ONLY in the sets."""
    obs = detect_order_blocks(m5_rows)
    un5 = [o for o in obs if not o["mitigated"]]
    fvgs = detect_fair_value_gaps(m5_rows)
    uf5 = [f for f in fvgs if not f["filled"]]
    if h1_rows and len(h1_rows) >= 10:
        h1_obs = detect_order_blocks(h1_rows, lookback=15)
        h1_un = [o for o in h1_obs if not o["mitigated"]]
        h1_fvgs = detect_fair_value_gaps(h1_rows)
        h1_uf = [f for f in h1_fvgs if not f["filled"]]
    else:
        h1_obs = h1_un = h1_fvgs = h1_uf = []

    swept, _ = detect_liquidity_sweep(m5_rows)
    phase, _conf = market_structure_phase(m5_rows)
    if h1_rows and len(h1_rows) >= 15:
        recent = h1_rows[-15:]
    else:
        recent = m5_rows[-20:] if len(m5_rows) >= 20 else m5_rows
    swing_high = max(r["high"] for r in recent)
    swing_low = min(r["low"] for r in recent)
    pd_zone = premium_discount_zone(m5_rows[-1]["close"], swing_high, swing_low)
    _sess, kw = active_killzone_session(
        _dt.datetime.utcfromtimestamp(m5_rows[-1]["time"]))
    bias, _c = _derive_smc_bias(
        obs + h1_obs, un5 + h1_un, fvgs + h1_fvgs, uf5 + h1_uf,
        swept, phase, pd_zone, kw)

    structure_aligned = (
        (bias == "bullish" and phase in ("bos_bullish", "choch_bullish"))
        or (bias == "bearish" and phase in ("bos_bearish", "choch_bearish")))
    in_good_zone = (
        (bias == "bullish" and pd_zone["zone"] == "discount")
        or (bias == "bearish" and pd_zone["zone"] == "premium"))

    common = dict(liq_sweep=swept, discount=in_good_zone,
                  killzone_weight=kw, structure_aligned=structure_aligned)
    g_sq = grade_poi(has_ob=len(un5) > 0, ob_mitigated=False,
                     has_fvg=len(uf5) > 0, fvg_filled=False, **common)
    g_mg = grade_poi(has_ob=len(un5) + len(h1_un) > 0, ob_mitigated=False,
                     has_fvg=len(uf5) + len(h1_uf) > 0, fvg_filled=False,
                     **common)
    return {"sq": g_sq, "merged": g_mg, "bias": bias,
            "n_un5": len(un5), "n_h1_un": len(h1_un),
            "n_uf5": len(uf5), "n_h1_uf": len(h1_uf)}


def main() -> int:
    if not os.path.exists(CACHED):
        print(json.dumps({"ok": False, "reason": f"missing {CACHED}"}))
        return 1
    c = json.load(open(CACHED))
    m5, h1 = c["M15"], c["H1"]
    import bisect
    h1t = [r["time"] for r in h1]

    dist_sq = {g: 0 for g in GRADES}
    dist_mg = {g: 0 for g in GRADES}
    cross = {}                       # (sq, merged) -> count
    fwd = {arm: {g: [] for g in GRADES} for arm in ("sq", "merged")}
    n = flips = 0
    contrad_sq = contrad_mg = 0      # grade-vs-bias world contradiction
    for i in range(200, len(m5) - FWD_BARS, 3):
        win5 = m5[max(0, i - 119):i + 1]
        if len(win5) < 30:
            continue
        bt = win5[-1]["time"]
        j = bisect.bisect_right(h1t, bt)
        win1 = h1[max(0, j - 80):j]
        if len(win1) < 20:
            continue
        g = grade_inputs(win5, win1)
        a = atr14(m5, i)
        if a <= 0:
            continue
        sign = 1.0 if g["bias"] == "bullish" else (
            -1.0 if g["bias"] == "bearish" else 0.0)
        n += 1
        dist_sq[g["sq"]] += 1
        dist_mg[g["merged"]] += 1
        key = f"{g['sq']}->{g['merged']}"
        cross[key] = cross.get(key, 0) + 1
        if g["sq"] != g["merged"]:
            flips += 1
        # contradiction = entry-TF world says "no POI behind it" while the
        # merged world (the bias driver) has OB/FVG support, or vice versa
        if (g["n_un5"] + g["n_uf5"] == 0) != (
                g["n_un5"] + g["n_h1_un"] + g["n_uf5"] + g["n_h1_uf"] == 0):
            if g["n_h1_un"] + g["n_h1_uf"] > 0 and g["bias"] != "neutral":
                contrad_sq += 1
        if sign != 0.0:
            drift = (m5[i + FWD_BARS]["close"] - m5[i]["close"]) / a * sign
            fwd["sq"][g["sq"]].append(drift)
            fwd["merged"][g["merged"]].append(drift)

    def bucket_stats(arm):
        out = {}
        for g in GRADES:
            vals = fwd[arm][g]
            out[g] = {"n": len(vals),
                      "mean_drift_atr": round(sum(vals) / len(vals), 3)
                      if vals else None}
        return out

    led = {
        "item": "b158",
        "dataset": {"bars_scanned": n, "fwd_bars": FWD_BARS,
                    "cached": CACHED},
        "grade_distribution_sq": dist_sq,
        "grade_distribution_merged": dist_mg,
        "flip_rate": round(flips / n, 4) if n else None,
        "transitions": dict(sorted(cross.items(),
                                   key=lambda kv: -kv[1])),
        "entry_tf_blind_bars": contrad_sq,
        "entry_tf_blind_rate": round(contrad_sq / n, 4) if n else None,
        "forward_drift_by_grade_sq": bucket_stats("sq"),
        "forward_drift_by_grade_merged": bucket_stats("merged"),
    }
    # separation = mean(A+/A) - mean(B/C), aligned drift; the ranking power
    # of the label under each world
    def sep(arm):
        s = bucket_stats(arm)
        good = [v for g in ("A+", "A") for v in
                ([s[g]["mean_drift_atr"]] if s[g]["n"] >= 30 else [])]
        bad = [v for g in ("B", "C") for v in
               ([s[g]["mean_drift_atr"]] if s[g]["n"] >= 30 else [])]
        return (round(sum(good) / len(good) - sum(bad) / len(bad), 3)
                if good and bad else None)
    led["separation_sq"] = sep("sq")
    led["separation_merged"] = sep("merged")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(led, fh, indent=1, sort_keys=True)
    print(json.dumps(led, indent=1, sort_keys=True)[:3500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
