#!/usr/bin/env python3
"""b62 STRATEGY LAB — test classic XAUUSD intraday strategies on real data.

Literature methods implemented as standalone signal_fns and measured with
the SAME engine as live (engines.backtest.backtest_ohlc: one position,
0.20$ spread, conservative intrabar stop-first rule). Expectancy in R,
not dollars, so geometry differences don't lie.

Data: cached ab_aggressive_data.json (3000 M15 bars) — byte-identical
across arms.
"""
import json
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engines.backtest import backtest_ohlc

DATA = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "data/backtest/ab_aggressive_data.json")))
M15 = DATA["M15"]
SPREAD = 0.20
# the engine calls signal_fn(row) with the bar dict; map it back to its index
TIME_INDEX = {r["time"]: n for n, r in enumerate(M15)}


def indexed(fn):
    """Adapt an f(i)->signal|None strategy to the engine's f(row)->... API."""
    def wrapper(row):
        i = TIME_INDEX.get(row.get("time"))
        if i is None:
            return None
        return fn(i)
    return wrapper



def atr(rows, i, n=14):
    if i < n:
        return None
    trs = []
    for j in range(i - n + 1, i + 1):
        h, l, pc = rows[j]["high"], rows[j]["low"], rows[j - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / n


def ema(vals, n):
    k = 2 / (n + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


Closes = [r["close"] for r in M15]
E20 = ema(Closes, 20)
E50 = ema(Closes, 50)


def hour_utc(bar):
    import datetime
    return datetime.datetime.fromtimestamp(bar["time"], tz=datetime.timezone.utc).hour


# ---------- 1) Asia range breakout (London open) ----------
def asia_breakout(i):
    h = hour_utc(M15[i])
    if not (7 <= h < 10):
        return None
    asia = [b for b in M15[max(0, i - 28):i] if hour_utc(b) < 7]
    if len(asia) < 10:
        return None
    hi = max(b["high"] for b in asia)
    lo = min(b["low"] for b in asia)
    a = atr(M15, i)
    if not a:
        return None
    c = M15[i]["close"]
    if c > hi and M15[i - 1]["close"] <= hi:
        return {"side": "BUY", "entry": c, "sl": hi - 1.2 * a, "tp": c + 2.0 * a,
                "style": "asia_break", "grade": "B"}
    if c < lo and M15[i - 1]["close"] >= lo:
        return {"side": "SELL", "entry": c, "sl": lo + 1.2 * a, "tp": c - 2.0 * a,
                "style": "asia_break", "grade": "B"}
    return None


# ---------- 2) NY opening range breakout ----------
def ny_orb(i):
    h = hour_utc(M15[i])
    if not (13 <= h < 16):
        return None
    orb = [b for b in M15[max(0, i - 4):i] if 13 <= hour_utc(b) < 14]
    if len(orb) < 2:
        return None
    hi = max(b["high"] for b in orb)
    lo = min(b["low"] for b in orb)
    a = atr(M15, i)
    if not a:
        return None
    c = M15[i]["close"]
    if c > hi and M15[i - 1]["close"] <= hi:
        return {"side": "BUY", "entry": c, "sl": lo, "tp": c + 2 * (hi - lo),
                "style": "ny_orb", "grade": "B"}
    if c < lo and M15[i - 1]["close"] >= lo:
        return {"side": "SELL", "entry": c, "sl": hi, "tp": c - 2 * (hi - lo),
                "style": "ny_orb", "grade": "B"}
    return None


# ---------- 3) EMA trend pullback ----------
def ema_pullback(i):
    if i < 60:
        return None
    a = atr(M15, i)
    if not a:
        return None
    c, c1 = M15[i]["close"], M15[i - 1]["close"]
    up = E20[i] > E50[i] and Closes[i] > E50[i]
    dn = E20[i] < E50[i] and Closes[i] < E50[i]
    if up and c1 <= E20[i - 1] <= max(M15[i]["high"], c) and c > c1:
        return {"side": "BUY", "entry": c, "sl": E20[i] - 1.5 * a, "tp": c + 2.5 * a,
                "style": "ema_pullback", "grade": "B"}
    if dn and c1 >= E20[i - 1] >= min(M15[i]["low"], c) and c < c1:
        return {"side": "SELL", "entry": c, "sl": E20[i] + 1.5 * a, "tp": c - 2.5 * a,
                "style": "ema_pullback", "grade": "B"}
    return None


# ---------- 4) RSI mean reversion ----------
def rsi(vals, n=14):
    out = [50.0] * len(vals)
    gains = losses = 0.0
    for i in range(1, len(vals)):
        d = vals[i] - vals[i - 1]
        g, l = max(d, 0), max(-d, 0)
        if i <= n:
            gains += g / n
            losses += l / n
            out[i] = 100 - 100 / (1 + (gains / losses if losses else 99))
        else:
            gains = (gains * (n - 1) + g) / n
            losses = (losses * (n - 1) + l) / n
            out[i] = 100 - 100 / (1 + (gains / losses if losses else 99))
    return out


RSI = rsi(Closes)

def rsi_reversion(i):
    if i < 30:
        return None
    a = atr(M15, i)
    if not a:
        return None
    c = M15[i]["close"]
    if RSI[i - 1] < 25 and RSI[i] > 25:
        return {"side": "BUY", "entry": c, "sl": c - 1.5 * a, "tp": c + 2.0 * a,
                "style": "rsi_rev", "grade": "B"}
    if RSI[i - 1] > 75 and RSI[i] < 75:
        return {"side": "SELL", "entry": c, "sl": c + 1.5 * a, "tp": c - 2.0 * a,
                "style": "rsi_rev", "grade": "B"}
    return None


# ---------- 5) Bollinger bounce ----------
def bb(i, n=20, k=2.0):
    if i < n:
        return None, None, None
    w = Closes[i - n + 1:i + 1]
    m = sum(w) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)
    return m, m + k * sd, m - k * sd


def bollinger_bounce(i):
    m, up, lo = bb(i)
    if up is None:
        return None
    a = atr(M15, i)
    if not a:
        return None
    c, c1 = M15[i]["close"], M15[i - 1]["close"]
    if c1 < lo and c > c1 and c < m:
        return {"side": "BUY", "entry": c, "sl": M15[i]["low"] - 0.8 * a, "tp": m,
                "style": "bb_bounce", "grade": "B"}
    if c1 > up and c < c1 and c > m:
        return {"side": "SELL", "entry": c, "sl": M15[i]["high"] + 0.8 * a, "tp": m,
                "style": "bb_bounce", "grade": "B"}
    return None


# ---------- 6) Donchian 20 breakout ----------
def donchian(i, n=20):
    if i < n:
        return None
    a = atr(M15, i)
    if not a:
        return None
    hi = max(b["high"] for b in M15[i - n:i])
    lo = min(b["low"] for b in M15[i - n:i])
    c = M15[i]["close"]
    if c > hi:
        return {"side": "BUY", "entry": c, "sl": c - 2 * a, "tp": c + 3 * a,
                "style": "donchian", "grade": "B"}
    if c < lo:
        return {"side": "SELL", "entry": c, "sl": c + 2 * a, "tp": c - 3 * a,
                "style": "donchian", "grade": "B"}
    return None


# ---------- 7) Liquidity sweep reversal (wick beyond prior extreme, close back) ----------
def sweep_reversal(i, look=10):
    if i < look + 1:
        return None
    a = atr(M15, i)
    if not a:
        return None
    prev_hi = max(b["high"] for b in M15[i - look:i])
    prev_lo = min(b["low"] for b in M15[i - look:i])
    b = M15[i]
    body = abs(b["close"] - b["open"])
    rng = max(b["high"] - b["low"], 1e-9)
    if b["high"] > prev_hi and b["close"] < prev_hi and (b["high"] - max(b["close"], b["open"])) > body:
        return {"side": "SELL", "entry": b["close"], "sl": b["high"] + 0.5 * a,
                "tp": b["close"] - 2.5 * a, "style": "sweep_rev", "grade": "B"}
    if b["low"] < prev_lo and b["close"] > prev_lo and (min(b["close"], b["open"]) - b["low"]) > body:
        return {"side": "BUY", "entry": b["close"], "sl": b["low"] - 0.5 * a,
                "tp": b["close"] + 2.5 * a, "style": "sweep_rev", "grade": "B"}
    return None


# ---------- 8) FVG retest continuation ----------
def fvg_retest(i, look=30):
    if i < look:
        return None
    a = atr(M15, i)
    if not a:
        return None
    for j in range(i - look, i - 1):
        b1, b3 = M15[j], M15[j + 2]
        if b1["high"] < b3["low"]:  # bullish FVG
            gap_lo, gap_hi = b1["high"], b3["low"]
            if M15[i]["low"] <= gap_hi and M15[i]["close"] > gap_hi and Closes[i] > E50[i]:
                return {"side": "BUY", "entry": M15[i]["close"], "sl": gap_lo - 0.8 * a,
                        "tp": M15[i]["close"] + 2.0 * a, "style": "fvg_retest", "grade": "B"}
        if b1["low"] > b3["high"]:  # bearish FVG
            gap_lo, gap_hi = b3["high"], b1["low"]
            if M15[i]["high"] >= gap_lo and M15[i]["close"] < gap_lo and Closes[i] < E50[i]:
                return {"side": "SELL", "entry": M15[i]["close"], "sl": gap_hi + 0.8 * a,
                        "tp": M15[i]["close"] - 2.0 * a, "style": "fvg_retest", "grade": "B"}
    return None


STRATS = [
    ("asia_break", indexed(asia_breakout)),
    ("ny_orb", indexed(ny_orb)),
    ("ema_pullback", indexed(ema_pullback)),
    ("rsi_rev", indexed(rsi_reversion)),
    ("bb_bounce", indexed(bollinger_bounce)),
    ("donchian", indexed(donchian)),
    ("sweep_rev", indexed(sweep_reversal)),
    ("fvg_retest", indexed(fvg_retest)),
]


def r_stats(res):
    rs = []
    for t in res.get("trade_log", []):
        risk = abs(float(t["entry"]) - float(t.get("orig_sl") or t["sl"]))
        if risk <= 0:
            continue
        rs.append(float(t["pnl"]) / risk)  # price-diff pnl / price-diff risk = R
    if not rs:
        return None
    wins = [r for r in rs if r > 0.05]
    losses = [r for r in rs if r < -0.05]
    decided = len(wins) + len(losses)
    return {
        "trades": len(rs),
        "exp_R": round(statistics.mean(rs), 3),
        "WR%": round(100 * len(wins) / decided, 1) if decided else 0,
        "avg_win_R": round(statistics.mean(wins), 2) if wins else 0,
        "avg_loss_R": round(statistics.mean(losses), 2) if losses else 0,
        "net_R": round(sum(rs), 1),
        "maxDD_R": None,
    }


def max_dd(res):
    eq = 0.0
    peak = 0.0
    worst = 0.0
    for t in res.get("trade_log", []):
        risk = abs(float(t["entry"]) - float(t.get("orig_sl") or t["sl"])) or 1
        eq += float(t["pnl"]) / risk
        peak = max(peak, eq)
        worst = min(worst, eq - peak)
    return round(worst, 1)


def main():
    print(f"{'strategy':14s} {'trades':>6s} {'exp_R':>6s} {'WR%':>5s} {'win_R':>6s} {'loss_R':>7s} {'net_R':>6s} {'maxDD_R':>7s}")
    rows = []
    for name, fn in STRATS:
        res = backtest_ohlc(M15, fn, min_rr=0.0, spread=SPREAD,
                            breakeven_at_r=0.0, partial_tp1_share=0.0)
        s = r_stats(res)
        if not s:
            print(f"{name:14s}  (no trades)")
            continue
        s["maxDD_R"] = max_dd(res)
        s["name"] = name
        rows.append(s)
        print(f"{name:14s} {s['trades']:6d} {s['exp_R']:6.3f} {s['WR%']:5.1f} "
              f"{s['avg_win_R']:6.2f} {s['avg_loss_R']:7.2f} {s['net_R']:6.1f} {s['maxDD_R']:7.1f}")
    rows.sort(key=lambda r: -r["exp_R"])
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data/backtest/b62_strategy_lab.json")
    json.dump(rows, open(out, "w"), indent=1)
    print(f"\nBEST: {rows[0]['name']} exp {rows[0]['exp_R']}R/trade -> {out}")


if __name__ == "__main__":
    main()
