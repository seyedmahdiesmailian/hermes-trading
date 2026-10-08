"""b193: AUDIT THE AGGRESSIVE LANE - the only entry path b187 never gated.

Live evidence (2026-09-08/09): the single confirmed in-zone entry won
(+19.26$); three `trigger_ok=True` aggressive entries (premium/breakout
style, price OUTSIDE zone) lost (-95.10, -44.85, -24.45). b189/b190/b191
replayed only the in-zone gate -> this lane was never measured.

Harness: replay every historical leg across 15-min grid bars, route each
bar through branch logic replicated from engines/plan.py, classify the
first fill per (policy, style), walk outcomes with b190.walk (P2 exit,
close-only targets, touch stops, commission). Aggressive geometry = live
_reanchor_blueprint convention: SL 2*ATR from entry, TP1 0.75R, TP2 1.5R
(what production actually did at 18:15 today: risk 6.3 = 2*ATR 3.15).

Policies compared (serial one-slot):
  ungated  : pullback needs C3 (b187), aggressive fires on contact  [production]
  gated    : both need C3
  pullback : aggressive dropped
  aggr_only: only aggressive (size that book alone)
Pre-registered gate (b191 rule): change production only if a policy beats
the deployed one by >=1.2x serial R/week.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import b182_exit_policy_backtest as b182  # noqa: E402
import b189_structure_counterfactuals as b189  # noqa: E402
import b190_exit_entry_matrix as b190  # noqa: E402

GRID = 15 * 60
SMC_FLOOR = 0.4


def plan_cache():
    c = {}
    for p in sorted(Path("data/xau_plan/plan_history").glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        if d.get("plan_id"):
            c[d["plan_id"]] = d
    return c


def c3_ok(bars, i, is_buy, n=3):
    cl = [bars[j][3] for j in range(max(0, i - n), i + 1)]
    if len(cl) < n + 1:
        return False
    return (all(cl[k] < cl[k + 1] for k in range(len(cl) - 1)) if is_buy
            else all(cl[k] > cl[k + 1] for k in range(len(cl) - 1)))


def classify(plan, price, is_buy):
    """Return 'pullback' | 'aggressive' | None replicating engines/plan.py routing."""
    z = plan.get("zones") or {}
    conf = plan.get("quality", {}).get("smc_confidence") or 0
    try:
        lo, hi = float(z["long_entry_low"]), float(z["long_entry_high"])
        vlo, vhi = float(z["value_low"]), float(z["value_high"])
        slo, shi = float(z["short_entry_low"]), float(z["short_entry_high"])
    except (KeyError, TypeError, ValueError):
        return None
    if is_buy:
        if lo <= price <= hi:
            return "pullback"
        if price >= vhi and conf >= SMC_FLOOR:
            return "aggressive"
        return None
    if slo <= price <= shi:
        return "pullback"
    if price <= vlo and conf >= SMC_FLOOR:
        return "aggressive"
    return None


def main():
    bars = b182.load_bars(offline=True)
    times = [b[0] for b in bars]
    legs, _skip = b189.legs_build(bars, times)
    pc = plan_cache()
    legs = [t for t in legs if t["id"] in pc]
    days = (times[-1] - times[0]) / 86400.0

    fills = {p: [] for p in ("ungated", "gated", "pullback", "aggr_only")}
    for leg in legs:
        plan = pc[leg["id"]]
        is_buy, atr = leg["is_buy"], leg["atr"]
        end = leg["end"]
        seen = {p: None for p in fills}  # pol -> (bar_idx, style)
        for i in range(max(leg["i0"], leg["ti"]), end):
            if (times[i] - times[leg["i0"]]) % GRID:
                continue
            style = classify(plan, bars[i][3], is_buy)
            if not style:
                continue
            conf = c3_ok(bars, i, is_buy)
            for pol in fills:
                ok = ((pol == "ungated" and ((style == "pullback" and conf) or style == "aggressive"))
                      or (pol == "gated" and conf)
                      or (pol == "pullback" and style == "pullback" and conf)
                      or (pol == "aggr_only" and style == "aggressive"))
                if ok and seen[pol] is None:
                    seen[pol] = (i, style)
        for pol, hit in seen.items():
            if hit is None:
                continue
            i, style = hit
            if style == "pullback":
                entry, sl = leg["lo_e"] if is_buy else leg["hi_e"], leg["inv"]
                tg = [float(x) for x in (plan.get("targets") or [])]
                cand = [x for x in tg if (is_buy and sl < x < leg["tp2"]) or ((not is_buy) and leg["tp2"] < x < sl)]
                tp1 = (max(cand) if is_buy else min(cand)) if cand else entry + (1 if is_buy else -1) * abs(entry - sl)
                tp2 = leg["tp2"]
            else:
                entry = bars[i][3]
                risk = 2 * atr
                sl = entry - risk if is_buy else entry + risk
                tp1 = entry + 0.75 * risk * (1 if is_buy else -1)
                tp2 = entry + 1.5 * risk * (1 if is_buy else -1)
            R, e = b190.walk("P2_half", is_buy, entry, tp1, tp2, sl, bars, i, end - 1)
            fills[pol].append((i, e, R, style))

    out = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "days": round(days, 1), "legs": len(legs), "grid": "15m", "exit": "P2",
           "hypothesis": "aggressive lane bypasses b187 and is untested", "policies": {}}
    for pol, trades in fills.items():
        if not trades:
            out["policies"][pol] = {"n": 0}
            continue
        par = sorted(trades, key=lambda x: x[0])
        serial, cur_end = [], -1
        for tr in par:
            if tr[0] > cur_end:
                serial.append(tr)
                cur_end = tr[1]
        n = len(par)
        wins = sum(1 for t in par if t[2] > 0)
        tot = sum(t[2] for t in par)
        stot = sum(t[2] for t in serial)
        styles = {}
        for t in par:
            s = styles.setdefault(t[3], {"n": 0, "wins": 0, "R": 0.0})
            s["n"] += 1
            s["wins"] += t[2] > 0
            s["R"] += t[2]
        out["policies"][pol] = {
            "n": n, "win_rate": round(wins / n, 3),
            "parallel_R": round(tot, 2), "R_per_trade": round(tot / n, 2),
            "serial_trades": len(serial), "serial_R_per_week": round(stot / (days / 7.0), 2),
            "by_style": {k: {"n": v["n"], "win": round(v["wins"] / v["n"], 3),
                             "mean_R": round(v["R"] / v["n"], 2)} for k, v in styles.items()},
        }
    dep = out["policies"]["ungated"]["serial_R_per_week"]
    for pol in ("gated", "pullback", "aggr_only"):
        v = out["policies"][pol].get("serial_R_per_week")
        out["policies"][pol]["x_vs_deployed"] = round(v / dep, 2) if v is not None and dep else None
    Path("data/backtest").mkdir(exist_ok=True)
    Path("data/backtest/b193_aggressive_lane.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out["policies"], indent=1))
    print("deployed(ungated) serial R/wk:", dep)


if __name__ == "__main__":
    main()
