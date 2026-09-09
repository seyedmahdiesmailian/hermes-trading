#!/usr/bin/env python3
"""b189 STRUCTURE COUNTERFACTUALS - the self-interrogation made auditable.

Question this answers: given everything we know (b185: bias is a momentum echo;
b187: zone-touch entries are adverse selection), which ENTRY RULE maximizes net
R on the directional plan population, measured with the exact production clock
(fill only on settled M5 closes, decisions land on the 15-minute cron grid) and
broker commissions, not a chart-perfect fantasy?

Rules compared:
  A_immediate   : fill on the zone touch bar           (pre-b187 production)
  C_confirm3    : 3 consecutive M5 closes toward bias  (DEPLOYED b187)
  G_one_close   : 1 close above/below touch-bar close  (looser)
  H_time_gate   : C_confirm3 but touch must come >=60min after plan birth
                  (tests: is an early touch a falling knife?)
  I_zone_depth  : C_confirm3 but only touches that pierce 30% into the zone
                  (tests: shallow graze vs real retest)

Race = TP2 vs invalidation on M5, outcome stop=-1R target=+rr open=0.
Commission per side per lot $3.5 -> $7/lot round turn, in R via $100 risk.
"""
import importlib.util, json, statistics as st, sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, str(ROOT / rel))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

b187 = load("b187", "scripts/b187_entry_confirmation.py")
b182 = b187.b182
b185 = b187.b185
COMMISSION_R = 7.0 / 100.0  # per round trip at $100 risk

def legs_build(bars, times):
    legs, skip = [], Counter()
    for d in b185.original_plans():
        t0 = b185._ts(d.get("created_at"))
        inv, tg, bias = d.get("invalidation"), d.get("targets"), d.get("bias")
        z = d.get("zones") or {}
        atr = float(d.get("atr") or 0)
        if not t0 or inv is None or not tg or len(tg) < 2 or atr <= 0 \
                or bias not in ("bullish", "bearish"):
            skip["incomplete"] += 1; continue
        i = b182.first_bar_at_or_after(times, int(t0))
        if i >= len(bars) - 24:
            skip["no_room"] += 1; continue
        is_buy = bias == "bullish"
        ref = bars[i][3]; inv = float(inv)
        tp2 = max(float(x) for x in tg) if is_buy else min(float(x) for x in tg)
        k = "long_entry" if is_buy else "short_entry"
        try:
            lo_e, hi_e = float(z[f"{k}_low"]), float(z[f"{k}_high"])
        except (KeyError, TypeError, ValueError):
            skip["no_zone"] += 1; continue
        # b188(a) parity: skip stale-at-birth like live production now does
        if is_buy and not (ref > inv and tp2 > ref and hi_e > ref):
            skip["stale_at_birth"] += 1; continue
        if not is_buy and not (ref < inv and tp2 < ref and lo_e < ref):
            skip["stale_at_birth"] += 1; continue
        texp = b185._ts(d.get("expires_at"))
        wb = int((texp - t0) / 300) if texp else 288
        end = min(i + max(24, min(wb, 288)), len(bars))
        ti = None
        for j in range(i + 1, end):
            _t, hi, lo, _c = bars[j]
            if (is_buy and lo <= hi_e) or ((not is_buy) and hi >= lo_e):
                ti = j; break
        if ti is None or end - ti < 24:
            skip["no_trigger"] += 1; continue
        legs.append({"id": d["plan_id"], "is_buy": is_buy, "inv": inv, "tp2": tp2,
                     "i0": i, "ti": ti, "end": end, "atr": atr,
                     "lo_e": lo_e, "hi_e": hi_e})
    return legs, skip

def next_grid_fill(k):
    # cron decisions land on :00/:15/:30/:45; fill on first settled 15m mark
    day = k - (k % 288)
    return day + 3 * ((k - day) // 3 + 1)

def run_rule(legs, bars, rule):
    out = []
    for t in legs:
        ib, ti, end, atr = t["is_buy"], t["ti"], t["end"], t["atr"]
        if rule == "A_immediate":
            entry_i = ti
        else:
            entry_i = None
            for j2 in range(ti + 1, min(ti + 25, end)):  # confirm within 2h
                if rule in ("C_confirm3", "I_zone_depth", "H_time_gate"):
                    seg = [bars[x][3] for x in range(max(ti, j2 - 3), j2 + 1)]
                    ok = all((c > bars[ti][3]) if ib else (c < bars[ti][3]) for c in seg)
                elif rule == "G_one_close":
                    ok = (bars[j2][3] > bars[ti][3]) if ib else (bars[j2][3] < bars[ti][3])
                if not ok:
                    continue
                if rule == "H_time_gate" and (j2 - t["i0"]) < 12:
                    break  # early touch = knife, skip this leg entirely
                if rule == "I_zone_depth":
                    depth = abs(bars[ti][3] - (t["hi_e"] if ib else t["lo_e"]))
                    zone = abs(t["hi_e"] - t["lo_e"])
                    if zone <= 0 or depth / zone < 0.30:
                        break
                entry_i = j2; break
            if entry_i is None:
                continue
        f = next_grid_fill(entry_i + 1)
        if f >= end:
            continue
        r = b187.race(ib, t["inv"], t["tp2"], bars, f, end)
        rr = abs(t["tp2"] - bars[f][3]) / max(abs(t["inv"] - bars[f][3]), 1e-9)
        net = (rr - COMMISSION_R) if r == "target" else \
              (-1.0 - COMMISSION_R) if r == "stop" else 0.0
        out.append({"net": net, "win": r == "target", "decided": r != "open"})
    dec = [o for o in out if o["decided"]]
    return {
        "fills": len(out), "decided": len(dec),
        "win_rate": round(sum(o["win"] for o in dec) / len(dec), 3) if dec else None,
        "net_R": round(sum(o["net"] for o in out), 2),
        "net_R_per_fill": round(sum(o["net"] for o in out) / len(out), 3) if out else None,
    }

def main():
    bars = b182.load_bars(offline=True)
    times = [b[0] for b in bars]
    legs, skip = legs_build(bars, times)
    res = {rule: run_rule(legs, bars, rule)
           for rule in ("A_immediate", "G_one_close", "C_confirm3",
                        "H_time_gate", "I_zone_depth")}
    out = {"legs": len(legs), "skip": dict(skip), "rules": res}
    Path(ROOT / "data/backtest").mkdir(exist_ok=True)
    (ROOT / "data/backtest/b189_structure_counterfactuals.json").write_text(
        json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
