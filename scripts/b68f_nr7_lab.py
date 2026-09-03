#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 5 — NR7 volatility-compression breakout.

Standing loop (b68): each run tests ONE candidate method not yet in the lab.
Rounds 1-4: vwap_fade (MEAN REV, rejected), atr_expand (MOMENTUM, rejected),
htf_pullback (the funnel's own TREND+DISCOUNT class, rejected), pdh_break
(PDH/PDL continuation — first arm to win fresh, escalated to b70). The
untested family left in the classic literature is the compression->expansion
breakout: b63's `compression` arm was SUPPOSED to measure it but fired 0
trades on both sets (todo b69: its (hi-lo) > 0.9*ATR(50) tightness gate plus
contracting-halves condition never co-occur on gold M15). This round uses
the definition that actually fires: John Carter's NR7 — bar i-1 has the
NARROWEST plain range (high-low) of the last 7 bars, a genuine volatility
squeeze — and trades a CLOSE-CONFIRMED break of that bar's range within the
following bars (close confirmation is the pattern b68 round 4 established:
wick-through is noise +0.38 ATR, close-through is continuation +1.00 ATR).

Geometry variants (round 4's stop-width lesson: 0.5 ATR gets wicked out,
1.0 ATR survives the ladder):
  nr7_break_c   — SL at the NR7 bar's OPPOSITE extreme (classic textbook)
  nr7_break_w10 — SL 1.0*ATR(14) beyond the broken extreme (wide)

No lookahead: NR7 status uses only bars up to i-1; the breakout bar is i-1
(its CLOSE through the level); entry is bar i's OPEN. TP 2R. Measured with
the SAME engine as live (engines.backtest.backtest_ohlc), 0.20$ spread,
3000 cached M15 gold bars, plain 2R geometry AND the live b60 exit ladder.
Merit bar (b68 round-1 METHOD RULE): funnel +0.854R cached; any confirm
re-measures the funnel on the SAME fresh data.

Side deliverable (feeds b69): range_probe() measures the distribution of
12-bar range / ATR(50) on this dataset — the exact quantity b63's dead
compression gate tested — so a future round can loosen it to something
that fires instead of guessing.
"""
import os, sys, json, datetime
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from engines.backtest import backtest_ohlc
from engines.trade_management import _partial_close_fraction

DATA = json.load(open(os.path.join(_ROOT, "data/backtest/ab_aggressive_data.json")))
M15 = DATA["M15"]
SPREAD = 0.20
IDX = {r["time"]: n for n, r in enumerate(M15)}

NR = 7          # NR7: narrowest range of the last 7 bars
BREAK_WIN = 6   # the close-through must happen within 6 bars of the NR7 bar


def indexed(fn):
    def w(row):
        i = IDX.get(row.get("time"))
        return None if i is None else fn(i)
    return w


def atr(i, n=14):
    if i < n:
        return None
    trs = []
    for j in range(i - n + 1, i + 1):
        h, l, pc = M15[j]["high"], M15[j]["low"], M15[j - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / n


def rng(i):
    return float(M15[i]["high"]) - float(M15[i]["low"])


def is_nr7(i):
    """Bar i has the narrowest plain range of bars i-NR+1..i (all closed)."""
    if i < NR:
        return False
    r = rng(i)
    return all(r <= rng(j) for j in range(i - NR + 1, i))


def find_nr7(i):
    """Most recent NR7 bar j with i-1-j < BREAK_WIN (j < i-1: the breakout
    bar itself may not double as the NR7 bar). None if no live setup."""
    for j in range(i - 2, max(i - 2 - BREAK_WIN, NR - 1) - 1, -1):
        if is_nr7(j):
            return j
    return None


def nr7_break(i, wide=True):
    """CLOSE-CONFIRMED break of an NR7 range: bar i-1 closes beyond the NR7
    bar's extreme while bar i-2 was still inside it (fresh cross), enter at
    bar i's open. wide=True -> SL 1.0*ATR beyond the broken level; else SL
    at the NR7 bar's opposite extreme (classic)."""
    if i < 30 or i >= len(M15):
        return None
    j = find_nr7(i)
    if j is None:
        return None
    hi, lo = float(M15[j]["high"]), float(M15[j]["low"])
    sig, prior = M15[i - 1], M15[i - 2]
    sc, pc = float(sig["close"]), float(prior["close"])
    a = atr(i - 1)
    if not a:
        return None
    if pc <= hi < sc:                       # closed THROUGH the NR7 high
        e = float(M15[i]["open"])
        sl = hi - 1.0 * a if wide else lo
        risk = e - sl
        if risk <= 0:
            return None
        return {"side": "BUY", "entry": e, "sl": sl, "tp": e + 2.0 * risk,
                "style": "nr7_break", "grade": "B"}
    if pc >= lo > sc:                       # closed THROUGH the NR7 low
        e = float(M15[i]["open"])
        sl = lo + 1.0 * a if wide else hi
        risk = sl - e
        if risk <= 0:
            return None
        return {"side": "SELL", "entry": e, "sl": sl, "tp": e - 2.0 * risk,
                "style": "nr7_break", "grade": "B"}
    return None


ARMS = [("nr7_break_c", lambda i: nr7_break(i, wide=False)),
        ("nr7_break_w10", lambda i: nr7_break(i, wide=True))]


def r_stats(res):
    rs = []
    for t in res.get("trade_log", []):
        risk = abs(float(t["entry"]) - float(t.get("orig_sl") or t["sl"])) or 1
        rs.append(float(t["pnl"]) / risk)
    if not rs:
        return {"trades": 0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = abs(sum(losses) / len(losses)) if losses else 0.001
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return {"trades": len(rs),
            "exp_R": round(sum(rs) / len(rs), 3),
            "WR%": round(100 * len(wins) / len(rs), 1),
            "avg_win_R": round(avg_w, 2), "avg_loss_R": round(-avg_l, 2),
            "net_R": round(sum(rs), 1), "maxDD_R": round(dd, 1)}


def range_probe():
    """b69 feed: how tight does a 12-bar window actually get on gold M15?
    b63's dead compression arm required (hi-lo) <= 0.9*ATR(50) AND
    contracting halves AND a 0.6*ATR impulse body — measure each clause's
    firing rate separately so the arm can be healed to something real."""
    n = len(M15)
    tight = contract = impulse = combo = nr7 = 0
    ratios = []
    for i in range(60, n):
        a = atr(i, 50)
        if not a:
            continue
        win = M15[i - 12:i]
        hi = max(b["high"] for b in win)
        lo = min(b["low"] for b in win)
        ratio = (hi - lo) / a
        ratios.append(ratio)
        t = ratio <= 0.9
        h1 = max(b["high"] for b in win[:6]) - min(b["low"] for b in win[:6])
        h2 = max(b["high"] for b in win[6:]) - min(b["low"] for b in win[6:])
        c = h2 < h1
        body = abs(M15[i]["close"] - M15[i]["open"])
        im = body > 0.6 * a
        tight += t
        contract += c
        impulse += im
        combo += (t and c and im)
        nr7 += is_nr7(i)
    ratios.sort()
    q = lambda p: round(ratios[int(p * (len(ratios) - 1))], 3)
    return {"bars": len(ratios),
            "ratio_min": round(ratios[0], 3), "ratio_p05": q(0.05),
            "ratio_p25": q(0.25), "ratio_median": q(0.50),
            "tight_0.9atr_count": tight,
            "contracting_count": contract,
            "impulse_count": impulse,
            "b63_combo_count": combo,          # the dead arm's full gate
            "nr7_count": nr7}


def main():
    probe = range_probe()
    print("range probe (12-bar range / ATR50):", json.dumps(probe), flush=True)
    print(f"{'strategy':16s} {'exit':8s} {'trades':>6s} {'exp_R':>7s} {'WR%':>6s} "
          f"{'net_R':>7s} {'maxDD_R':>8s}")
    out = {"_range_probe": probe}
    for name, fn in ARMS:
        for mode, kw in (("plain", {}),
                         ("ladder", {"partial_tp1_share": 0.5,
                                     "partial_share_fn": lambda t: _partial_close_fraction(t),
                                     "tp1_position": 0.50, "trail_after_partial": 0.5,
                                     "breakeven_at_r": 0.0})):
            res = backtest_ohlc(M15, indexed(fn), min_rr=0.0, spread=SPREAD, **kw)
            s = r_stats(res)
            out[f"{name}:{mode}"] = s
            print(f"{name:16s} {mode:8s} {s.get('trades',0):6d} {s.get('exp_R',0):7.3f} "
                  f"{s.get('WR%',0):6.1f} {s.get('net_R',0):7.1f} {s.get('maxDD_R',0):8.1f}",
                  flush=True)
    p = os.path.join(_ROOT, "data", "backtest", "b68f_nr7_lab.json")
    json.dump(out, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
