#!/usr/bin/env python3
"""b186 - PLAN GEOMETRY FIX, tested before it ships (v2, honest harness).

v1 RETRACTED: it reused b182.simulate with the plan's raw 1h-swing stop and
a fixed lots, where 1R was computed off THAT tiny stop -> risk < the $2
commission floor, so every cell printed the same (fees ate everything) and
wide/tight stops were indistinguishable. That measured fees, not geometry.

v2 = the experiment the question actually needs:
  - Population: plan_history originals with a healthy tradeable geometry
    (price beyond entry zone, stop behind, ladder ahead) and a zone touch
    within the plan window -> entry at the band edge on the trigger bar.
  - Risk is FIXED per trade at the live $100 standard: lots = 100/(risk*$100).
    R is therefore $100 by construction; commission/lot is the real bridge
    fee ($6 per round lot). Variants then trade STOP WIDTH vs TARGET REACH -
    the actual geometry question - not fee scaling.
  - Variants (engines/context.py knobs only):
      V0 as-is               : stop = 1h swing + 0.5 ATR, ladder as planned
      V1 stop>=1.5 ATR       : noise-scale stop
      V2 stop>=2.0 ATR       : wider
      V3 TP_last>=2.5R       : extend runner (ladder TP1/TP2 untouched)
      V4 V2+V3
  - Policies: b182 P2 lane vs P3 hands-off (does wide stop change the
    answer? P0_old kept for the amputation contrast).
"""
import importlib.util
import json
import pathlib
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("b182x", ROOT / "scripts/b182_exit_policy_backtest.py")
b182 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b182)
spec2 = importlib.util.spec_from_file_location("b185x", ROOT / "scripts/b185_analysis_hit_rate.py")
b185 = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(b185)

OUT = ROOT / "data/backtest/b186_plan_geometry.json"
MIN_BARS, MAX_BARS = 144, 576
POLICIES = ("P0_live", "P2_be_lock", "P3_ride")
RISK_USD = 100.0   # commission handled inside b182.simulate


def build_variants(d, is_buy, entry, atr):
    inv0 = float(d["invalidation"])
    tg = [float(x) for x in d["targets"]]
    far = max(tg) if is_buy else min(tg)
    risk0 = abs(entry - inv0)
    sign = 1 if is_buy else -1

    def widen(min_atr):
        return entry - sign * max(risk0, min_atr * atr)

    def extend(rr_min):
        need = entry + sign * risk0 * rr_min
        return sorted(tg + [round(need, 2)], key=lambda x: -x if is_buy else x)

    v2sl = widen(2.0)
    r2 = abs(entry - v2sl)
    return {
        "V0_as_is": (inv0, tg),
        "V1_stop1.5atr": (round(widen(1.5), 2), tg),
        "V2_stop2.0atr": (round(v2sl, 2), tg),
        "V3_far2.5R": (inv0, extend(2.5)),
        "V4_wide+far": (round(v2sl, 2),
                        sorted(tg + [round(entry + sign * r2 * 2.5, 2)],
                               key=lambda x: -x if is_buy else x)),
    }


def main():
    bars = b182.load_bars(offline=True)
    times = [b[0] for b in bars]
    legs, skip = [], Counter()
    for d in b185.original_plans():
        t0 = b185._ts(d.get("created_at"))
        inv, tg, bias = d.get("invalidation"), d.get("targets"), d.get("bias")
        z = d.get("zones") or {}
        atr = float(d.get("atr") or 0)
        if not t0 or inv is None or not tg or len(tg) < 2 or atr <= 0 \
                or bias not in ("bullish", "bearish"):
            skip["incomplete"] += 1
            continue
        i = b182.first_bar_at_or_after(times, int(t0))
        if i >= len(bars) - 24:
            skip["no_room"] += 1
            continue
        is_buy = bias == "bullish"
        ref = bars[i][3]
        inv = float(inv)
        far = max(float(x) for x in tg) if is_buy else min(float(x) for x in tg)
        key = ("long_entry" if is_buy else "short_entry")
        lo_e, hi_e = float(z[f"{key}_low"]), float(z[f"{key}_high"])
        if is_buy and not (ref > inv and far > ref and hi_e > ref):
            skip["stale_or_priced_in"] += 1
            continue
        if not is_buy and not (ref < inv and far < ref and lo_e < ref):
            skip["stale_or_priced_in"] += 1
            continue
        texp = b185._ts(d.get("expires_at"))
        wb = int((texp - t0) / 300) if texp else MAX_BARS
        end = min(i + max(MIN_BARS, min(wb, MAX_BARS)), len(bars))
        ti, entry = None, None
        for j in range(i + 1, end):
            _t, hi, lo, _c = bars[j]
            if is_buy and lo <= hi_e:
                ti, entry = j, hi_e
                break
            if not is_buy and hi >= lo_e:
                ti, entry = j, lo_e
                break
        if ti is None or end - ti < 24:
            skip["no_trigger"] += 1
            continue
        risk0 = abs(entry - inv)
        if risk0 < 0.3:
            skip["degenerate"] += 1
            continue
        rr_tp1 = min(abs(float(x) - entry) for x in tg) / risk0
        legs.append({"id": d["plan_id"], "side": "BUY" if is_buy else "SELL",
                     "entry": entry, "i": ti, "end": end, "atr": atr,
                     "rr_tp1": rr_tp1, "v": build_variants(d, is_buy, entry, atr)})

    def run(pop):
        res = {}
        for name in ("V0_as_is", "V1_stop1.5atr", "V2_stop2.0atr",
                     "V3_far2.5R", "V4_wide+far"):
            for p in POLICIES:
                rs = []
                for t in pop:
                    sl, ladder = t["v"][name]
                    risk = abs(t["entry"] - sl)
                    if risk <= 0:
                        continue
                    lots = round(RISK_USD / (risk * 100.0), 3)
                    lad = sorted(ladder, key=lambda x: -x if t["side"] == "BUY" else x)
                    sim = b182.simulate(p, t["side"], t["entry"], sl, lad,
                                        lots, bars, t["i"])
                    if sim is None:
                        continue
                    rs.append(sim["R"])   # b182.simulate already nets commission
                n = len(rs)
                res[f"{name}|{p}"] = {
                    "n": n, "total_R": round(sum(rs), 1),
                    "avg_R": round(sum(rs) / n, 3) if n else None,
                    "win%": round(100 * sum(1 for x in rs if x > 0) / n, 1) if n else None,
                    "med_stop_atr": None}
        return res

    pops = {"all": legs,
            "gate_proxy_rrtp1>=1": [t for t in legs if t["rr_tp1"] >= 1.0]}
    results = {k: run(v) for k, v in pops.items() if v}
    OUT.write_text(json.dumps({"skipped": dict(skip), "legs": len(legs),
                               "results": results}, indent=1))
    for k, res in results.items():
        print(f"\n== {k} ==")
        print(f"{'variant|policy':22s} {'n':>4s} {'tot_R':>7s} {'avg_R':>7s} {'win%':>5s}")
        for kk, v in res.items():
            print(f"{kk:22s} {v['n']:>4d} {v['total_R']:>7.1f} "
                  f"{str(v['avg_R']):>7s} {str(v['win%']):>5s}")
    print(f"\nlegs={len(legs)} skipped={dict(skip)}\nledger: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
