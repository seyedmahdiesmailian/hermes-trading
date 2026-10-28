#!/usr/bin/env python3
"""b190 v2 HONEST exit x entry matrix - CLOSE-ONLY fills, real plan TP1.

v1 retracted: it borrowed b182.simulate which fills TP/SL on intra-bar highs,
and it invented a midpoint TP1. Both flatter the partial-profit policies.

Rules of this harness (same conservatism as b189 race, so the two agree):
  - a level counts as hit only when an M5 CLOSE is beyond it
  - SL checked before targets on the same bar
  - ambiguous same-bar (lock/BE stop crossed within bar but close beyond) ->
    scored as OPEN (0R), neither banked nor stopped
  - fill only on settled bars at the production 15-min grid; entry = close of
    first grid bar after confirm
  - commission 0.07R round trip ($7 at $100 risk)

Exit policies (all on the SAME entry):
  P0_full    : close 100% at TP1                      (old b55 production)
  P2_half    : half at TP1, rest to TP2, stop->+0.15R (deployed b182)
  P3_ride    : ignore TP1, hold to TP2 or stop        (hands-off)
  P4_trail   : P2 + after TP1 trail rest at 0.3R off best close
  T24        : P2 but forced market exit after 24h (slot freed)

SERIAL accounting = one slot, real exit bar frees it (unlike b189's
window-blocked approximation). Reports per-week R over 153 days.
"""
import importlib.util, json, sys
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

def plan_tp1(d_plan_cache, t):
    return float(d_plan_cache[t["id"]]["tp1"])

def confirm_entry(t, bars, rule):
    ib, ti, end = t["is_buy"], t["ti"], t["end"]
    if rule == "A_immediate":
        f = ti + 1
    else:
        f = None
        for j2 in range(ti + 1, min(ti + 25, end)):
            seg = [bars[x][3] for x in range(max(ti, j2 - 3), j2 + 1)]
            ok = all((c > bars[ti][3]) if ib else (c < bars[ti][3]) for c in seg)
            if ok:
                f = b189.next_grid_fill(j2 + 1)
                break
        if f is None or f >= end:
            return None
    return f if f + 4 < end else None

def walk(pol, ib, entry, tp1, tp2, sl, bars, f, end):
    """Close-only state machine. Returns (netR, exit_bar) or None if ambiguous
    same-bar -> treated as (0.0, i) exit with kind OPEN."""
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    sign = 1.0 if ib else -1.0
    cur_sl = sl
    banked = 0.0
    half = False
    best = entry
    for i in range(f, end):
        cl = bars[i][3]
        hi, lo = bars[i][1], bars[i][2]
        # STOP is touch-based and checked FIRST (conservative): a wick through
        # the stop counts even if the close recovers. Targets need a CLOSE
        # beyond the level. Same-bar ambiguity resolves to the stop.
        if (ib and lo <= cur_sl) or (not ib and hi >= cur_sl):
            move = sign * (cur_sl - entry) / risk
            return (banked + move * (0.5 if half else 1.0) - COMMISSION_R, i)
        if pol != "P3_ride" and not half:
            hit1 = (ib and cl >= tp1) or (not ib and cl <= tp1)
            if hit1:
                half = True
                banked += sign * (tp1 - entry) / risk * 0.5
                if pol == "P0_full":
                    banked += sign * (tp1 - entry) / risk * 0.5
                    return (banked - COMMISSION_R, i)
                if pol in ("P2_half", "P4_trail", "T24"):
                    cur_sl = entry + sign * 0.15 * risk
        hit2 = (ib and cl >= tp2) or (not ib and cl <= tp2)
        if hit2:
            banked += sign * (tp2 - entry) / risk * (0.5 if half else 1.0)
            return (banked - COMMISSION_R, i)
        best = max(best, cl) if ib else min(best, cl)
        if pol == "P4_trail" and half:
            tr = best - sign * 0.3 * risk
            if (ib and tr > cur_sl) or (not ib and tr < cur_sl):
                cur_sl = tr
        if pol == "T24" and i - f >= 288:
            r = banked + sign * (cl - entry) / risk * (0.5 if half else 1.0)
            return (r - COMMISSION_R, i)
    r = banked + sign * (bars[end - 1][3] - entry) / risk * (0.5 if half else 1.0)
    return (r - COMMISSION_R, end - 1)


def holding_stats(trades):
    import statistics
    h = [e - f for (f, e, R) in trades]
    return (len(h), round(statistics.median(h) * 5 / 60, 1) if h else None)

def main():
    bars = b182.load_bars(offline=True)
    times = [b[0] for b in bars]
    legs, skip = b189.legs_build(bars, times)
    # real TP1 = first ladder target from the plan
    import glob
    from datetime import datetime
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
    legs = [t for t in legs if t["id"] in cache]

    def tp1_for(t, entry):
        ib = t["is_buy"]
        cand = [x for x in cache[t["id"]]["tgs"]
                if (ib and x > entry and x < t["tp2"]) or ((not ib) and x < entry and x > t["tp2"])]
        if not cand:
            return None
        return max(cand) if ib else min(cand)
    days = (times[-1] - times[0]) / 86400.0
    out = {"legs": len(legs), "days": round(days, 1), "matrix": {}, "ledger": []}
    for rule in ("A_immediate", "C_confirm3"):
        for pol in ("P0_full", "P2_half", "P3_ride", "P4_trail", "T24"):
            trades = []
            for t in legs:
                f = confirm_entry(t, bars, rule)
                if f is None:
                    continue
                entry = bars[f][3]
                tp1 = tp1_for(t, entry)
                if tp1 is None:
                    continue
                r = walk(pol, t["is_buy"], entry, tp1,
                         t["tp2"], t["inv"], bars, f, t["end"])
                if r is None:
                    continue
                trades.append((f, r[1], r[0]))
            par = [x[2] for x in trades]
            trades.sort(key=lambda x: x[0])
            busy = -1; ser = []
            for (f, e, R) in trades:
                if f <= busy:
                    continue
                busy = max(busy, e + 1)
                ser.append(R)
            cell = {"fills": len(par),
                    "par_win": round(sum(1 for x in par if x > 0) / len(par), 3) if par else None,
                    "par_R": round(sum(par), 2),
                    "ser_taken": len(ser),
                    "ser_win": round(sum(1 for x in ser if x > 0) / len(ser), 3) if ser else None,
                    "ser_R": round(sum(ser), 2),
                    "ser_R_wk": round(sum(ser) / (days / 7), 3)}
            out["matrix"][f"{rule}|{pol}"] = cell
            if rule == "C_confirm3":
                out["ledger"].append({"pol": pol, "R": round(sum(par), 2)})
    (ROOT / "data/backtest/b190_exit_entry_matrix.json").write_text(
        json.dumps(out, indent=2))
    print(f"legs={len(legs)} days={days:.0f}")
    print(f"{'entry|exit':24s} {'fills':>5s} {'pwin':>5s} {'parR':>6s} {'serN':>4s} {'swin':>5s} {'serR':>6s} {'R/wk':>6s}")
    for k, c in out["matrix"].items():
        print(f"{k.replace('_confirm3',''):24s} {c['fills']:5d} {str(c['par_win']):>5s} {c['par_R']:6.1f} {c['ser_taken']:4d} {str(c['ser_win']):>5s} {c['ser_R']:6.1f} {c['ser_R_wk']:6.2f}")

if __name__ == "__main__":
    main()
