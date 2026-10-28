#!/usr/bin/env python3
"""b187 - ADVERSE SELECTION KILLER: does a reversal trigger fix the fill?

b185/b186 condensed finding: plans are pullback LIMITS at zone edges.
Conditional on the fill happening, price is mid-move AGAINST the bias -
classic maker adverse selection: 24% race win vs 55% random walk (z=-5,
n=129). The analyzer's bias adds ~0 (T1 is confounded by the down-month);
the FILL MECHANISM is the measured poison.

Test: same legs, two entry rules, race TP2 vs invalidation afterwards:
  A immediate  : touch zone -> fill at band edge (status quo)
  B confirm2   : touch zone at bar j -> wait up to 12 bars (1h) for a close
                 back toward bias (buy: close[j'] >= close[j]+0.1*ATR with
                 j'>j; sell mirrored). Fill at that bar's close. No
                 confirm inside 1h -> NO TRADE.
  C confirm_m5 : touch AND m5-bias of the last 3 bars agrees with plan bias
                 -> fill at close. (cheap proxy of the live m5 vote)
Stop/targets identical (invalidation, TP2). Same-bar double-touch -> stop.
Also counts HOW MANY legs each rule trades (B/C skip the toxic fills by
design - if survivors' win-rate exceeds random, the filter is real).
"""
import importlib.util
import json
import pathlib
import statistics as st
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("b182x", ROOT / "scripts/b182_exit_policy_backtest.py")
b182 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b182)
spec2 = importlib.util.spec_from_file_location("b185x", ROOT / "scripts/b185_analysis_hit_rate.py")
b185 = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(b185)

OUT = ROOT / "data/backtest/b187_entry_confirmation.json"
MIN_BARS, MAX_BARS = 144, 576
CONFIRM_WINDOW = 12


def race(is_buy, stop, target, bars, i0, end):
    for i in range(i0, end):
        _t, hi, lo, _c = bars[i]
        hs = (lo <= stop) if is_buy else (hi >= stop)
        ht = (hi >= target) if is_buy else (lo <= target)
        if hs:
            return "stop"
        if ht:
            return "target"
    return "open"


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
        tp2 = max(float(x) for x in tg) if is_buy else min(float(x) for x in tg)
        k = "long_entry" if is_buy else "short_entry"
        lo_e, hi_e = float(z[f"{k}_low"]), float(z[f"{k}_high"])
        if is_buy and not (ref > inv and tp2 > ref and hi_e > ref):
            skip["stale_at_birth"] += 1
            continue
        if not is_buy and not (ref < inv and tp2 < ref and lo_e < ref):
            skip["stale_at_birth"] += 1
            continue
        texp = b185._ts(d.get("expires_at"))
        wb = int((texp - t0) / 300) if texp else MAX_BARS
        end = min(i + max(MIN_BARS, min(wb, MAX_BARS)), len(bars))
        ti = None
        for j in range(i + 1, end):
            _t, hi, lo, _c = bars[j]
            if (is_buy and lo <= hi_e) or ((not is_buy) and hi >= lo_e):
                ti = j
                break
        if ti is None or end - ti < 24:
            skip["no_trigger"] += 1
            continue
        legs.append({"id": d["plan_id"], "is_buy": is_buy, "inv": inv, "tp2": tp2,
                     "ti": ti, "end": end, "atr": atr, "hi_e": hi_e, "lo_e": lo_e,
                     "align": (d.get("quality") or {}).get("alignment"),
                     "votes": (d.get("quality") or {}).get("bias_votes") or {}})

    res = {}
    for rule in ("A_immediate", "B_confirm2", "C_confirm_m5"):
        wins = losses = opens = traded = 0
        for t in legs:
            ib, j, end, atr = t["is_buy"], t["ti"], t["end"], t["atr"]
            if rule == "A_immediate":
                entry_i = j
            else:
                entry_i = None
                for j2 in range(j + 1, min(j + 1 + CONFIRM_WINDOW, end)):
                    if rule == "B_confirm2":
                        ok = (bars[j2][3] >= bars[j][3] + 0.1 * atr) if ib \
                            else (bars[j2][3] <= bars[j][3] - 0.1 * atr)
                    else:  # C: last 3 closes all on bias side of bar j close
                        seg = [bars[x][3] for x in range(max(j, j2 - 3), j2 + 1)]
                        ok = all((c > bars[j][3]) if ib else (c < bars[j][3]) for c in seg)
                    if ok:
                        entry_i = j2
                        break
                if entry_i is None:
                    continue
            r = race(ib, t["inv"], t["tp2"], bars, entry_i + 1, end)
            traded += 1
            wins += r == "target"
            losses += r == "stop"
            opens += r == "open"
        dec = wins + losses
        rw = st.mean(abs(t["tp2"] - (t["hi_e"] if t["is_buy"] else t["lo_e"])) and
                     (abs(t["inv"] - (t["hi_e"] if t["is_buy"] else t["lo_e"])) /
                      (abs(t["inv"] - (t["hi_e"] if t["is_buy"] else t["lo_e"])) +
                       abs(t["tp2"] - (t["hi_e"] if t["is_buy"] else t["lo_e"]))))
                     for t in legs)
        res[rule] = {"traded": traded, "decided": dec, "wins": wins,
                     "win_rate": round(wins / dec, 3) if dec else None,
                     "vs_random_walk": round(wins / dec - rw, 3) if dec else None}
    n = len(legs)
    rw = res["A_immediate"]["vs_random_walk"]
    OUT.write_text(json.dumps({"legs": n, "skipped": dict(skip), "results": res}, indent=1))
    print(f"legs={n} skipped={dict(skip)}")
    for k, v in res.items():
        print(f"{k:14s} traded={v['traded']:>3d}/{n} win={v['win_rate']} "
              f"edge_vs_random={v['vs_random_walk']:+.3f}")
    print(f"ledger: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
