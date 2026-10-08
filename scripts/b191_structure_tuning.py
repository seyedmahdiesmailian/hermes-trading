#!/usr/bin/env python3
"""b191 STRUCTURE TUNING SWEEP - same honest harness as b190 v2.

Population: b189 legs (stale-cut, directional plans), conservative rules:
stop = touch-based checked first; targets = close-only; fills on settled bars;
$7 commission; SERIAL single-slot (K=1) R/week is the decision metric.

Variants swept (one lever at a time, everything else = DEPLOYED):
  base   : confirm3, M5, 15-min grid, invalidation stop, P2 half-exit
  conf2  : 2 confirmation closes
  conf4  : 4 confirmation closes
  grid5  : 5-min fill grid (i.e. cron every 5 min instead of 15)
  noAsia : trigger only if confirm-close lands 08:00-21:00 UTC
  nyOnly : trigger only 13:00-21:00 UTC
  wide15 / wide20 : stop widened to max(inv, entry - 1.5/2.0 x stop-dist)... [truncated]
"""
import importlib.util, json, sys, statistics as st
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, str(ROOT / rel))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

b189 = load("b189", "scripts/b189_structure_counterfactuals.py")
b182 = b189.b182
COMMISSION_R = 0.07

def hour_of(bar_t):
    return datetime.fromtimestamp(bar_t, tz=timezone.utc).hour

# TP1 = nearest real ladder rung (replicates b190 v2 fix)
def build_cache():
    import glob
    cache = {}
    for p in sorted(glob.glob('data/xau_plan/plan_history/*.json')):
        try:
            d = json.loads(Path(p).read_text())
        except Exception:
            continue
        tt = d.get("targets") or []
        if isinstance(tt, dict):
            tt = list(tt.values())
        tg = [float(x) for x in tt if x]
        if d.get("plan_id") and tg:
            cache[d["plan_id"]] = {"tgs": tg}
    return cache

def entry_index(t, bars, nconf, grid):
    ib, ti, end = t["is_buy"], t["ti"], t["end"]
    for j2 in range(ti + 1, min(ti + 25, end)):
        seg = [bars[x][3] for x in range(max(ti, j2 - (nconf - 1)), j2 + 1)]
        ok = all((c > bars[ti][3]) if ib else (c < bars[ti][3]) for c in seg)
        if ok:
            g = 1 if grid == 5 else 3
            f = (j2 // g + 1) * g
            return f if f < end else None
    return None

def walk(pol, ib, entry, tp1, tp2, sl, bars, f, end):
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    sign = 1.0 if ib else -1.0
    cur_sl = sl; banked = 0.0; half = False; best = entry
    for i in range(f, end):
        cl = bars[i][3]; hi, lo = bars[i][1], bars[i][2]
        if (ib and lo <= cur_sl) or (not ib and hi >= cur_sl):
            move = sign * (cur_sl - entry) / risk
            return (banked + move * (0.5 if half else 1.0) - COMMISSION_R, i)
        if pol != "P3_ride" and not half:
            if (ib and cl >= tp1) or (not ib and cl <= tp1):
                half = True
                banked += sign * (tp1 - entry) / risk * 0.5
                if pol == "P0_full":
                    banked += sign * (tp1 - entry) / risk * 0.5
                    return (banked - COMMISSION_R, i)
                if pol == "P2_half":
                    cur_sl = entry + sign * 0.15 * risk
        if (ib and cl >= tp2) or (not ib and cl <= tp2):
            banked += sign * (tp2 - entry) / risk * (0.5 if half else 1.0)
            return (banked - COMMISSION_R, i)
        best = max(best, cl) if ib else min(best, cl)
        if pol == "P4_trail" and half:
            tr = best - sign * 0.3 * risk
            if (ib and tr > cur_sl) or (not ib and tr < cur_sl):
                cur_sl = tr
    r = banked + sign * (bars[end - 1][3] - entry) / risk * (0.5 if half else 1.0)
    return (r - COMMISSION_R, end - 1)

def serial_R(trades, days, K=1):
    trades = sorted(trades, key=lambda x: x[0])
    slots = [-1] * K; taken = []
    for (f, e, R) in trades:
        cand = [i for i in range(K) if slots[i] <= f]
        if not cand:
            continue
        i = max(cand, key=lambda i: (slots[i], i))
        slots[i] = e + 1; taken.append(R)
    return (sum(taken) / (days / 7), len(taken),
            sum(1 for x in taken if x > 0) / max(len(taken), 1))

def main():
    bars = b182.load_bars(offline=True)
    times = [b[0] for b in bars]
    legs, skip = b189.legs_build(bars, times)
    cache = build_cache()
    legs = [t for t in legs if t["id"] in cache]
    days = (times[-1] - times[0]) / 86400.0

    def tp1_for(t, entry):
        ib = t["is_buy"]
        cand = [x for x in cache[t["id"]]["tgs"]
                if (ib and entry < x < t["tp2"]) or ((not ib) and t["tp2"] < x < entry)]
        return (min(cand) if ib else max(cand)) if cand else None

    def run(nconf=3, grid=15, hour_ok=None, wide=None, pol="P2_half", tag=""):
        trades = []
        for t in legs:
            f = entry_index(t, bars, nconf, grid)
            if f is None:
                continue
            if hour_ok and not hour_ok(hour_of(bars[f][0])):
                continue
            entry = bars[f][3]; tp1 = tp1_for(t, entry)
            if tp1 is None:
                continue
            sl = t["inv"]
            if wide:
                base_stop = abs(entry - sl)
                sl2 = entry - wide * base_stop if t["is_buy"] else entry + wide * base_stop
                sl = min(sl, sl2) if t["is_buy"] else max(sl, sl2)
            r = walk(pol, t["is_buy"], entry, tp1, t["tp2"], sl, bars, f, t["end"])
            if r:
                trades.append((f, r[1], r[0]))
        rw, n, w = serial_R(trades, days)
        return {"serial_R_wk": round(rw, 2), "taken": n, "win": round(w, 2)}

    out = {}
    out["base_C3_15m"] = run()
    out["conf2"] = run(nconf=2)
    out["conf4"] = run(nconf=4)
    out["grid5"] = run(grid=5)
    out["noAsia_08_21"] = run(hour_ok=lambda h: 8 <= h < 21)
    out["nyOnly_13_21"] = run(hour_ok=lambda h: 13 <= h < 21)
    out["wide15"] = run(wide=1.5)
    out["wide20"] = run(wide=2.0)
    out["P0_fullTP1"] = run(pol="P0_full")
    out["P3_ride"] = run(pol="P3_ride")
    out["P4_trail"] = run(pol="P4_trail")

    # hour-of-trigger diagnostic on base rule
    by_hour = defaultdict(lambda: [0, 0, 0.0])
    for t in legs:
        f = entry_index(t, bars, 3, 15)
        if f is None:
            continue
        entry = bars[f][3]; tp1 = tp1_for(t, entry)
        if tp1 is None:
            continue
        r = walk("P2_half", t["is_buy"], entry, tp1, t["tp2"], t["inv"], bars, f, t["end"])
        if not r:
            continue
        sess = "asia(0-7)" if hour_of(bars[f][0]) < 8 else ("ldn(8-12)" if hour_of(bars[f][0]) < 13 else "ny(13-21)" if hour_of(bars[f][0]) < 21 else "late(21-23)")
        by_hour[sess][0] += r[0] > 0; by_hour[sess][1] += 1; by_hour[sess][2] += r[0]
    out["session_all_fills"] = {k: {"wins": v[0], "n": v[1], "sumR": round(v[2], 1),
                                    "avgR": round(v[2] / v[1], 2)} for k, v in sorted(by_hour.items())}
    base = out["base_C3_15m"]["serial_R_wk"]
    out["decision_rule"] = ("adopt lever ONLY if serial_R_wk >= 1.2x base AND taken>=15 AND win>=0.55; "
                            f"base={base}")
    Path(ROOT / "data/backtest").mkdir(exist_ok=True)
    (ROOT / "data/backtest/b191_structure_tuning.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=1))

if __name__ == "__main__":
    main()
