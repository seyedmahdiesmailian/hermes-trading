#!/usr/bin/env python3
"""b75 — STRATEGY-FAMILY CENSUS v2: new signal classes the funnel is blind to.

v1 bug (caught same day): broker-offset detection invented offset=21 and put
London at UTC 10:00. v2 uses REAL UTC windows:
  Asian range      00:00-07:00 UTC (quiet block per hourly-range profile)
  London opening   07:00-07:30 UTC (range) -> entries to 10:00
  NY opening       12:30-13:00 UTC (range) -> entries to 15:00
  Sweep window     07:00-09:30 UTC vs Asian H/L

Families (from 2024-2026 gold research: ORB-Master XAUUSD M5, Quantum-Algo
London-vs-Asia +8pp, rule-based London-break plans):
  F1 ORB_LON / F1b ORB_NY — opening-range breakout, M5 close beyond range
     (+$1.5 acceptance), skip too-wide/tight ranges, SL=opposite edge,
     TP=2x range.
  F2 SWEEP — Asian-extreme liquidity sweep + reclaim inside London 07-09:30
     -> fade back across the extreme, SL beyond wick, TP 2R.
  F3 NRC  — narrow Asian range (<0.6 x 20-day median) -> London break
     continuation.

Pre-registered bar (unchanged): positive exp_R on >=2 of 3 chronological
10-day legs, >=15 signals, exp_R >= 0.15 net of SPREAD. Bar-level outcomes,
first-touch conservative (both touched in a bar -> LOSS). No funnel, no live.
"""
from __future__ import annotations
import json, os, sys, statistics
from datetime import datetime, timezone
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); os.chdir(_ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

from bridge_client import BridgeClient

SPREAD = 0.2
OUT = "data/backtest/b75_strategy_census.json"


def fetch():
    b = BridgeClient()
    rows = sorted(b.get_rates("XAUUSD", "M5", 6000).get("data", []), key=lambda r: int(r["time"]))
    return rows[:-1]  # settled only


def umin(ts):
    return (ts // 60) % 1440  # minutes since 00:00 UTC


def uday(ts):
    return ts // 86400


def bucket(idx, lo, hi):
    out = []
    for j in idx:
        m = umin(int(j_ts[j]))
        if m >= lo and m < hi:
            out.append(j)
    return out


j_ts = []  # filled in main; helper closure


def first_fire_breakout(rows, idx, rng_lo, rng_hi, win_lo, win_hi, name, fams, size_min=0.5, size_max=25.0):
    rng = [j for j in idx if rng_lo <= umin(int(rows[j]["time"])) < rng_hi]
    if len(rng) < 5:
        return
    rh = max(float(rows[j]["high"]) for j in rng)
    rl = min(float(rows[j]["low"]) for j in rng)
    size = rh - rl
    if not (size_min < size < size_max):
        return
    for j in idx:
        t = int(rows[j]["time"]); m = umin(t)
        if m < win_lo: continue
        if m >= win_hi: break
        c = float(rows[j]["close"])
        if c > rh + 1.5:
            fams[name].append({"t": t, "side": 1, "entry": c, "sl": rl, "tp": rh + 2 * size}); return
        if c < rl - 1.5:
            fams[name].append({"t": t, "side": -1, "entry": c, "sl": rh, "tp": rl - 2 * size}); return


def main():
    rows = fetch()
    global j_ts
    j_ts = [int(r["time"]) for r in rows]
    span = (datetime.fromtimestamp(j_ts[0], tz=timezone.utc).strftime("%m-%d"),
            datetime.fromtimestamp(j_ts[-1], tz=timezone.utc).strftime("%m-%d"))
    print("bars", len(rows), "span", span, flush=True)

    days = {}
    for i in range(len(rows)):
        days.setdefault(uday(j_ts[i]), []).append(i)
    sorted_days = sorted(days)

    fams = {"F1_ORB_LON": [], "F1b_ORB_NY": [], "F2_SWEEP": [], "F3_NRC": []}
    asian_sizes = []  # trailing for NRC median
    for di, d in enumerate(sorted_days):
        idx = days[d]
        if len(idx) < 100:
            continue
        asia = [j for j in idx if umin(j_ts[j]) < 420]           # 00-07 UTC
        ah = max(float(rows[j]["high"]) for j in asia) if asia else None
        al = min(float(rows[j]["low"]) for j in asia) if asia else None

        # F1/F1b breakouts
        first_fire_breakout(rows, idx, 420, 450, 450, 600, "F1_ORB_LON", fams)   # LON 07:00-07:30 range, entry to 10:00
        first_fire_breakout(rows, idx, 750, 780, 780, 900, "F1b_ORB_NY", fams)   # NY 12:30-13:00 range (UTC), entry to 15:00

        # F2 sweep+reclaim of Asian extremes during London
        if asia:
            sh = sl_ = False
            for j in idx:
                m = umin(j_ts[j])
                if m < 420: continue
                if m >= 570: break
                h, l, c = float(rows[j]["high"]), float(rows[j]["low"]), float(rows[j]["close"])
                if not sh and h > ah and c < ah - 0.5:
                    sh = True
                    fams["F2_SWEEP"].append({"t": j_ts[j], "side": -1, "entry": c,
                                             "sl": h + 1.0, "tp": c - 2 * max(h - c, 1.0)})
                if not sl_ and l < al and c > al + 0.5:
                    sl_ = True
                    fams["F2_SWEEP"].append({"t": j_ts[j], "side": 1, "entry": c,
                                             "sl": l - 1.0, "tp": c + 2 * max(c - l, 1.0)})

        # F3 narrow-asian-range continuation on London break
        if asia:
            asize = ah - al
            if len(asian_sizes) >= 8 and asize < 0.6 * statistics.median(asian_sizes[-20:]):
                for j in idx:
                    m = umin(j_ts[j])
                    if m < 420 or m >= 600: continue
                    c = float(rows[j]["close"])
                    if c > ah:
                        fams["F3_NRC"].append({"t": j_ts[j], "side": 1, "entry": c, "sl": c - asize, "tp": c + 2 * asize}); break
                    if c < al:
                        fams["F3_NRC"].append({"t": j_ts[j], "side": -1, "entry": c, "sl": c + asize, "tp": c - 2 * asize}); break
            asian_sizes.append(asize)

    # price out + legs
    t_end = j_ts[-1]
    out = {"_span": span, "_windows_utc": "asia 00-07, LON open 07-07:30 (entry->10), NY open 12:30-13 (entry->15)"}
    for name, sigs in fams.items():
        res = []
        for s in sigs:
            o = price_outcome(rows, s)
            if o is None: continue
            age = (t_end - s["t"]) / 86400
            leg = "L3" if age <= 10 else ("L2" if age <= 20 else "L1")
            res.append((o, leg))
        if not res:
            out[name] = {"signals": 0}
            continue
        all_r = [x[0] for x in res]
        per_leg = {}
        for leg in ("L1", "L2", "L3"):
            v = [x[0] for x in res if x[1] == leg]
            per_leg[leg] = {"n": len(v), "exp_R": round(sum(v) / len(v), 3) if v else None}
        exp = sum(all_r) / len(all_r)
        out[name] = {"signals": len(res), "exp_R": round(exp, 3),
                     "wr": round(100 * sum(1 for x in all_r if x > 0) / len(all_r), 1),
                     "net_R": round(sum(all_r), 2), "legs": per_leg,
                     "PROMOTE": exp >= 0.15 and sum(1 for v in per_leg.values() if (v["exp_R"] or 0) > 0) >= 2 and len(res) >= 15}
        print(name, out[name], flush=True)
    json.dump(out, open(OUT, "w"), indent=1)
    print("saved ->", OUT)


def price_outcome(rows, sig, horizon_bars=72):
    t0 = sig["t"]; side = sig["side"]
    last = None
    for r in rows:
        ts = int(r["time"])
        if ts <= t0: continue
        if ts - t0 > horizon_bars * 300: break
        h, l = float(r["high"]), float(r["low"])
        hit_sl = (l <= sig["sl"]) if side > 0 else (h >= sig["sl"])
        hit_tp = (h >= sig["tp"]) if side > 0 else (l <= sig["tp"])
        if hit_sl: return -1.0
        if hit_tp: return 2.0
        last = float(r["close"])
    if last is not None:
        risk = abs(sig["entry"] - sig["sl"]) or 1e-9
        return round(((last - sig["entry"]) * side - SPREAD) / risk, 3)
    return None


if __name__ == "__main__":
    main()
