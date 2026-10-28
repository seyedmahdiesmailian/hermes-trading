#!/usr/bin/env python3
"""b185 - ANALYSIS EDGE v3: does engines/smc.py output predict anything?

Two independent tests over 271 directional plans (500 are neutral - the
planner abstains most of the time; that is by design):

T1 DIRECTION: sign of the drift over the plan's validity window vs bias.
   Benchmarks: 0.50 coin, and persistence (did the PREVIOUS window move
   the same way - does bias merely echo momentum?).

T2 LEVELS RACE, executed as plans actually trade: price must first touch
   the entry zone (short_entry/long_entry bands in plan.zones); only then
   does the race stop(invalidation) vs TP2 start. Same-bar double touch ->
   conservative stop. Benchmark = driftless random walk:
   P(reach +d_target before -d_stop) = d_stop/(d_stop+d_target).

v1/v2 bugs RETRACTED (see git history): wrong bar-field indexing, and a
market-price race that ignored that plans are PULLBACK orders - 149
plans looked "broken at birth" but are merely not-triggered.
"""
import importlib.util
import json
import pathlib
import statistics as st
from datetime import datetime
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("b182x", ROOT / "scripts/b182_exit_policy_backtest.py")
b182 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b182)

PLAN_DIR = ROOT / "data/xau_plan/plan_history"
OUT = ROOT / "data/backtest/b185_analysis_hit_rate.json"
MIN_BARS, MAX_BARS = 144, 576          # 12h..48h on M5
TRIG_CAP_BARS = 576                     # zone must be touched within 48h


def _ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def original_plans():
    best = {}
    for p in sorted(PLAN_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        pid = d.get("plan_id")
        if pid and (pid not in best or d.get("created_at", "") < best[pid].get("created_at", "")):
            best[pid] = d
    return list(best.values())


def race(is_buy, stop, target, bars, i0, end):
    for i in range(i0, end):
        _t, hi, lo, _c = bars[i]
        if is_buy:
            hs, ht = lo <= stop, hi >= target
        else:
            hs, ht = hi >= stop, lo <= target
        if hs:
            return "stop"
        if ht:
            return "target"
    return "open"


_grade_fn = None


def _grade(d):
    global _grade_fn
    try:
        if _grade_fn is None:
            from engines.plan import setup_grade
            _grade_fn = setup_grade
        return str(_grade_fn(d))
    except Exception:
        return (d.get("quality") or {}).get("smc_poi", "?")


def main():
    bars = b182.load_bars(offline=True)
    times = [b[0] for b in bars]
    plans = original_plans()
    rows, skip = [], Counter()
    for d in plans:
        t0 = _ts(d.get("created_at"))
        inv, tg, bias = d.get("invalidation"), d.get("targets") or [], d.get("bias")
        z = d.get("zones") or {}
        if not t0 or inv is None or len(tg) < 2 or bias not in ("bullish", "bearish"):
            skip["not_directional"] += 1
            continue
        i = b182.first_bar_at_or_after(times, int(t0))
        if i >= len(bars) - 24:
            skip["no_walk_room"] += 1
            continue
        is_buy = bias == "bullish"
        lo_e, hi_e = ((z.get("long_entry_low"), z.get("long_entry_high")) if is_buy
                      else (z.get("short_entry_low"), z.get("short_entry_high")))
        if lo_e is None or hi_e is None:
            skip["no_entry_zone"] += 1
            continue
        inv = float(inv)
        tp2 = max(float(x) for x in tg) if bias == "bullish" else min(float(x) for x in tg)
        near = min(float(x) for x in tg) if bias == "bullish" else max(float(x) for x in tg)
        if not ((is_buy and near > inv) or ((not is_buy) and near < inv)):
            skip["bad_geometry"] += 1
            continue
        lo_e, hi_e = float(lo_e), float(hi_e)
        far_ok = (is_buy and tp2 > hi_e) or ((not is_buy) and tp2 < lo_e)
        ok_geo = far_ok and ((is_buy and lo_e < hi_e < inv) or ((not is_buy) and inv > hi_e > lo_e))
        if not ok_geo:
            skip["bad_geometry"] += 1
            continue
        texp = _ts(d.get("expires_at"))
        wb = int((texp - t0) / 300) if texp else MAX_BARS
        end = min(i + max(MIN_BARS, min(wb, MAX_BARS)), len(bars))
        trig_end = min(i + TRIG_CAP_BARS, len(bars))
        # T1 direction: close of validity window vs creation bar close
        ref0 = bars[i][3]
        net = bars[end - 1][3] - ref0
        prev_net = bars[i][3] - bars[max(0, i - 288)][3]
        # T2: wait for zone touch, enter at band edge nearest to trigger bar
        ti, entry = None, None
        for j in range(i + 1, trig_end):
            _t, hi, lo, _c = bars[j]
            if is_buy and lo <= hi_e:
                ti, entry = j, hi_e
                break
            if not is_buy and hi >= lo_e:
                ti, entry = j, lo_e
                break
        t2 = None
        if ti is not None:
            risk = abs(entry - inv)
            rew = abs(tp2 - entry)
            if 0.3 <= risk and rew >= 0.3:
                r = race(is_buy, inv, tp2, bars, ti + 1, max(ti + 6, trig_end))
                t2 = {"r": r, "rr": rew / risk,
                      "p_rw": risk / (risk + rew)}
        rows.append({"plan_id": d.get("plan_id"), "bias": bias,
                     "grade": _grade(d),
                     "session": d.get("session", "?"),
                     "dir_ok": (net > 0) == is_buy, "net": net,
                     "persist_ok": (prev_net > 0) == is_buy,
                     "triggered": ti is not None, "t2": t2})

    n = len(rows)
    dirp = sum(r["dir_ok"] for r in rows) / n
    persist = sum(r["persist_ok"] for r in rows) / n
    se = (dirp * (1 - dirp) / n) ** 0.5
    t2rows = [r for r in rows if r["t2"]]
    dec = [r for r in t2rows if r["t2"]["r"] != "open"]
    p_act = sum(1 for r in dec if r["t2"]["r"] == "target") / len(dec) if dec else None
    p_rw = st.mean(r["t2"]["p_rw"] for r in t2rows) if t2rows else None
    out = {
        "plans_total": len(plans), "directional": n, "skipped": dict(skip),
        "T1_direction": {"n": n, "p_bias_matches_window_drift": round(dirp, 3),
                         "se": round(se, 3), "z_vs_coin": round((dirp - 0.5) / se, 2),
                         "persistence_baseline": round(persist, 3),
                         "bias_beyond_momentum": round(dirp - persist, 3)},
        "T2_levels_race": {"triggered": len(t2rows), "decided": len(dec),
                           "p_actual": round(p_act, 3) if p_act is not None else None,
                           "p_random_walk": round(p_rw, 3) if p_rw is not None else None,
                           "edge": round(p_act - p_rw, 3) if p_act is not None and p_rw is not None else None},
    }
    # grade/session slices on T1
    for key in ("grade", "bias", "session"):
        for v in sorted({str(r[key]) for r in rows}):
            rs = [r for r in rows if str(r[key]) == v]
            if len(rs) >= 5:
                out[f"T1_{key}={v}"] = {"n": len(rs), "dir": round(sum(r["dir_ok"] for r in rs) / len(rs), 3)}
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
