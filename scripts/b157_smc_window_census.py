#!/usr/bin/env python3
"""b157 — CENSUS THE DEAD WINDOW PARAMS IN engines/smc.py BEFORE TOUCHING THEM.

b155's AST pass found that `detect_fair_value_gaps(rows, lookback=20)` never
reads `lookback`: the scan loop runs over EVERY fetched row, so every
still-unfilled 3-candle gap in the whole window contributes ±1.5 to the bias
score in `_derive_smc_bias`, while `smc_analyse` calls it with lookback=20 (M5)
and lookback=10 (H1) as if a window existed. `detect_order_blocks`' `atr_mult`
is dead the same way.

b110/b136's rule: do not change live behaviour on a code-reading argument.
Measure the blast radius first, in three layers, and only then decide per knob
whether the honest change is to IMPLEMENT the window or DELETE the lying param.

LAYER 1 — LIVE: the plan the trader is trading right now
    Reads data/xau_plan/current_plan.json (a plan snapshot the 15-min cycle
    wrote) and counts how many unfilled FVGs / unmitigated OBs actually fed
    the bias, versus how many would under a honoured window.  Indices in the
    stored dicts are positions in the rows list the detector was given, so the
    honour test is `index >= len(rows) - lookback` (M5 = 120 bars, H1 = 80).

LAYER 2 — HISTORICAL: how often does honouring the window FLIP THE BIAS?
    Walks the cached backtest bars (no bridge call), runs the real detectors
    both ways, and recomputes `_derive_smc_bias` on the same structure /
    premium-discount / killzone inputs.  The number that matters is not "how
    many stale gaps are dropped" but "how many bars change bias CLASS" — that
    is what would change live entries.

LAYER 3 — FUNNEL: does the flip move exp_R?
    engines/backtest_real.run_backtest (the sanctioned live-parity funnel,
    never a hand-copied one) on the cached dataset, incumbent vs honoured-
    window arm, delta reported with b123's one-sided rule.

Read-only w.r.t. trading: no bridge order endpoint, nothing imported by the
live path, nothing wired.  Writes data/backtest/b157_smc_window_census.json.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import smc                                          # noqa: E402
from engines.smc import (_derive_smc_bias, detect_fair_value_gaps,       # noqa: E402
                         detect_order_blocks, market_structure_phase,
                         premium_discount_zone, active_killzone_session)

OUT = "data/backtest/b157_smc_window_census.json"
CACHED = "data/backtest/ab_aggressive_data.json"

# The window sizes smc_analyse PASSES today (and silently ignores for FVGs).
M5_LOOKBACK = 20
H1_LOOKBACK = 10


# ── the two rules, side by side ─────────────────────────────────────────────
def _in_window(item: dict, n_rows: int, lookback: int, key: str) -> bool:
    """Would this detector output still exist if `lookback` were honoured?"""
    return item.get(key, -10 ** 9) >= n_rows - lookback


def bias_both_ways(m5_rows, h1_rows):
    """Return (bias_status_quo, bias_window_honoured, census dict).

    Status quo = the live code path (FVG scan unbounded).  The honoured arm
    re-runs the detectors with `rows[-lookback:]` — exactly what the parameter
    name promises — and feeds the SAME structure/zone/killzone values into the
    real `_derive_smc_bias`.
    """
    n5, n1 = len(m5_rows), len(h1_rows)
    obs = detect_order_blocks(m5_rows)
    un5 = [o for o in obs if not o["mitigated"]]
    fvgs = detect_fair_value_gaps(m5_rows)
    uf5 = [f for f in fvgs if not f["filled"]]

    h1_obs, h1_un, h1_fvgs, h1_uf = [], [], [], []
    if h1_rows:
        h1_obs = detect_order_blocks(h1_rows, lookback=15)
        h1_un = [o for o in h1_obs if not o["mitigated"]]
        h1_fvgs = detect_fair_value_gaps(h1_rows) if h1_rows else []
        h1_uf = [f for f in h1_fvgs if not f["filled"]]

    swept, _ = detect_sweep(m5_rows)
    phase, _conf = market_structure_phase(m5_rows)
    if h1_rows:
        recent = h1_rows[-15:] if len(h1_rows) >= 15 else h1_rows
    else:
        recent = m5_rows[-20:] if len(m5_rows) >= 20 else m5_rows
    swing_high = max(r["high"] for r in recent)
    swing_low = min(r["low"] for r in recent)
    pd_zone = premium_discount_zone(m5_rows[-1]["close"], swing_high, swing_low)
    _sess, kw = active_killzone_session(
        smc.datetime.fromtimestamp(m5_rows[-1]["time"]))

    cur_bias, cur_conf = _derive_smc_bias(
        obs + h1_obs, un5 + h1_un, fvgs + h1_fvgs, uf5 + h1_uf,
        swept, phase, pd_zone, kw)

    # honoured-window arm: filter by index inside the trailing window
    u5w = [o for o in un5 if _in_window(o, n5, M5_LOOKBACK, "index")]
    f5w = [f for f in uf5 if _in_window(f, n5, M5_LOOKBACK, "c3_index")]
    h1_uw = [o for o in h1_un if _in_window(o, n1, 15, "index")] if h1_rows else []
    h1_fw = [f for f in h1_uf if _in_window(f, n1, H1_LOOKBACK, "c3_index")] if h1_rows else []
    hon_bias, hon_conf = _derive_smc_bias(
        obs + h1_obs, u5w + h1_uw, fvgs + h1_fvgs, f5w + h1_fw,
        swept, phase, pd_zone, kw)

    return cur_bias, hon_bias, {
        "ob_active": len(un5), "ob_in_window": len(u5w),
        "fvg_active": len(uf5), "fvg_in_window": len(f5w),
        "h1_ob_active": len(h1_un), "h1_ob_in_window": len(h1_uw),
        "h1_fvg_active": len(h1_uf), "h1_fvg_in_window": len(h1_fw),
        "bias_status_quo": cur_bias, "bias_honoured": hon_bias,
        "conf_status_quo": round(cur_conf, 4), "conf_honoured": round(hon_conf, 4),
        "weight_status_quo": round(sum(
            2.0 if o["type"] == "bullish" else -2.0 for o in un5 + h1_un) +
            sum(1.5 if f["type"] == "bullish" else -1.5 for f in uf5 + h1_uf), 3),
        "weight_honoured": round(sum(
            2.0 if o["type"] == "bullish" else -2.0 for o in u5w + h1_uw) +
            sum(1.5 if f["type"] == "bullish" else -1.5 for f in f5w + h1_fw), 3),
    }


def detect_sweep(rows):
    return smc.detect_liquidity_sweep(rows)


# ── LAYER 1 ─────────────────────────────────────────────────────────────────
def live_census() -> dict:
    p = "data/xau_plan/current_plan.json"
    if not os.path.exists(p):
        return {"ok": False, "reason": "no current_plan.json"}
    plan = json.load(open(p))
    s = ((plan.get("context") or {}).get("smc")) or {}
    n5, n1 = 120, 80           # hermes_runtime: m5 = 120 bars, h1 = 80
    u5 = s.get("active_fvgs") or []
    h1u = s.get("h1_active_fvgs") or []
    ob5 = s.get("active_order_blocks") or []
    ob1 = s.get("h1_active_order_blocks") or []
    keep5 = [f for f in u5 if f.get("c3_index", -9) >= n5 - M5_LOOKBACK]
    keeph1 = [f for f in h1u if f.get("c3_index", -9) >= n1 - H1_LOOKBACK]
    keepob = [o for o in ob5 if o.get("index", -9) >= n5 - M5_LOOKBACK]
    ages = sorted((n5 - f["c3_index"]) for f in u5 if "c3_index" in f)
    return {
        "ok": True, "plan_id": plan.get("plan_id"),
        "created_at": plan.get("created_at"),
        "bias": s.get("bias"), "confidence": s.get("confidence"),
        "fvg_unfilled": len(u5), "fvg_would_survive_window": len(keep5),
        "h1_fvg_unfilled": len(h1u), "h1_fvg_would_survive_window": len(keeph1),
        "ob_unmitigated": len(ob5), "ob_would_survive_window": len(keepob),
        "stale_fvg_age_bars": ages,
        "stale_fvg_age_minutes": [a * 5 for a in ages],
        "note": "M5 window is 120 bars; lookback=20 means only gaps whose "
                "3rd candle sits in rows[-20:] (<=100 min old) should score.",
    }


# ── LAYER 2 ─────────────────────────────────────────────────────────────────
def historical_census(m5, h1, sample_from: int = 200, step: int = 1) -> dict:
    h1_by_time = [r["time"] for r in h1]
    import bisect
    flips = 0
    n = 0
    dropped = []
    weight_gaps = []
    transitions: dict[str, int] = {}
    for i in range(sample_from, len(m5), step):
        win5 = m5[max(0, i - 119):i + 1]
        if len(win5) < 30:
            continue
        bt = win5[-1]["time"]
        j = bisect.bisect_right(h1_by_time, bt)
        win1 = h1[max(0, j - 80):j]
        if len(win1) < 20:
            continue
        cur, hon, c = bias_both_ways(win5, win1)
        n += 1
        dropped.append({"sq": c["fvg_active"] + c["h1_fvg_active"],
                        "hon": c["fvg_in_window"] + c["h1_fvg_in_window"]})
        weight_gaps.append(abs(c["weight_status_quo"] - c["weight_honoured"]))
        if cur != hon:
            flips += 1
            transitions[f"{cur}->{hon}"] = transitions.get(f"{cur}->{hon}", 0) + 1
    dist = {}
    for d in dropped:
        k = d["sq"] - d["hon"]
        dist[k] = dist.get(k, 0) + 1
    return {
        "bars": n,
        "bias_flip_bars": flips,
        "bias_flip_rate": round(flips / n, 4) if n else None,
        "transitions": transitions,
        "stale_gap_count_distribution": {str(k): v for k, v in sorted(dist.items())},
        "mean_extra_stale_gaps": round(sum(d["sq"] - d["hon"] for d in dropped) / n, 3) if n else None,
        "mean_abs_bias_weight_shift": round(sum(weight_gaps) / n, 3) if n else None,
        "max_abs_bias_weight_shift": round(max(weight_gaps), 3) if weight_gaps else None,
        "mean_unfilled_gaps_status_quo": round(sum(d["sq"] for d in dropped) / n, 2) if n else None,
        "mean_unfilled_gaps_honoured": round(sum(d["hon"] for d in dropped) / n, 2) if n else None,
    }


def main() -> int:
    led: dict = {"item": "b157", "live": live_census()}
    if not os.path.exists(CACHED):
        led["cached"] = {"ok": False, "reason": f"missing {CACHED}"}
    else:
        c = json.load(open(CACHED))
        m5, h1, h4 = c["M15"], c["H1"], c["H4"]
        led["dataset"] = {"bars": len(m5), "tf": "M15",
                          "first": m5[0]["time"], "last": m5[-1]["time"]}
        # cached set is M15; live entry stream is M5.  The window is counted
        # in BARS (120) either way, so the census measures the same bar-age
        # rule and only the wall-clock span differs (recorded below).
        led["historical"] = historical_census(m5, h1, step=3)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(led, fh, indent=1, sort_keys=True)
    print(json.dumps(led, indent=1, sort_keys=True)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
