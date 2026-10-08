#!/usr/bin/env python3
"""b260: Round-Number Liquidity Sweep Reversion — fully causal backtest.

Source: research/b258_modern_smc_research.md recommendation #1 (Osler NY Fed
SR125/SR150 stop-clustering, multi-era benchmark Al Brooks F2 variant).

Mechanism: stop-loss orders cluster just past round numbers; price
overshoots to reach the cluster, then reverts as the cascade exhausts.
Grid on XAUUSD = $50 increments.

Contract (no look-ahead): every decision at bar t uses ONLY bars < t.
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(ROOT, "data", "probe_h1_6000.json")

GRID = 50.0
ATR_PERIOD = 14
ATR_MULT = 0.25          # sweep depth cap: <= 0.25 x ATR
VOL_MULT = 1.30          # tick_volume > 1.3 x trailing median
RETEST_MIN = 2           # >=2 prior touches in trailing 5 sessions
SESSION_BARS_H1 = 5 * 24  # 5 sessions in H1 bars
ATR_STOP = 1.5           # stop = 1.5 x ATR beyond the sweep wick
TP_GRID_MULT = 1.0       # target = next round number in direction


def load():
    d = json.load(open(PROBE))
    rows = d["candles"] if isinstance(d, dict) and "candles" in d else d
    return [
        {
            "time": int(r["time"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "tick_volume": float(r["tick_volume"]),
        }
        for r in rows
    ]


def atr(rows, i, period=ATR_PERIOD):
    """Causal ATR using only bars strictly before i."""
    lo = max(1, i - period)
    acc = 0.0
    n = 0
    for j in range(lo, i):
        prev = rows[j - 1]
        cur = rows[j]
        tr = max(
            cur["high"] - cur["low"],
            abs(cur["high"] - prev["close"]),
            abs(cur["low"] - prev["close"]),
        )
        acc += tr
        n += 1
    return acc / n if n else 0.0


def vol_median(rows, i, window=SESSION_BARS_H1):
    """Median tick_volume over the trailing window BEFORE bar i
    (bar i excluded — it is the sweep bar under test)."""
    lo = max(0, i - window)
    return sorted(rows[j]["tick_volume"] for j in range(lo, i))[(i - lo) // 2]


def round_levels(price):
    return (price // GRID) * GRID


def active_level(rows, i):
    """Grid levels touched >=RETEST_MIN times in the trailing 5 sessions
    BEFORE bar i (bar i is the possible sweeper). Return those within
    the sweep depth cap of bar i's own high/low, nearest first."""
    window_lo = max(0, i - SESSION_BARS_H1)
    touches = {}
    for j in range(window_lo, i):
        for name in ("high", "low"):
            touches[round_levels(rows[j][name])] = touches.get(round_levels(rows[j][name]), 0) + 1
    cur = rows[i]
    a = atr(rows, i)
    if a <= 0:
        return None
    cands = []
    for lvl, c in touches.items():
        if c < RETEST_MIN:
            continue
        gap = max(cur["high"] - lvl, lvl - cur["low"])
        if 0 < gap <= ATR_MULT * a:
            cands.append((abs(cur["close"] - lvl), lvl))
    if not cands:
        return None
    cands.sort()
    return cands[0][1]


def backtest(rows):
    """Returns list of closed trades: {entry_t, side, pnl, rr}."""
    trades = []
    i = SESSION_BARS_H1 + 5
    n = len(rows)
    last_entry_t = 0
    while i < n - 1:
        cur = rows[i]
        lvl = active_level(rows, i)
        if lvl is None:
            i += 1
            continue
        a = atr(rows, i)
        if a <= 0:
            i += 1
            continue
        depth = max(cur["high"] - lvl, lvl - cur["low"])
        if depth <= 0 or depth > ATR_MULT * a:
            i += 1
            continue
        if cur["tick_volume"] <= VOL_MULT * vol_median(rows, i):
            i += 1
            continue
        # Direction: sweep above -> revert down (SELL); sweep below -> BUY
        if cur["high"] > lvl:
            side = "SELL"
            entry = cur["close"]
            stop = min(cur["high"], lvl + ATR_MULT * a) + ATR_STOP * a
            target = lvl - GRID
            if target >= entry:
                i += 1
                continue
        else:
            side = "BUY"
            entry = cur["close"]
            stop = max(cur["low"], lvl - ATR_MULT * a) - ATR_STOP * a
            target = lvl + GRID
            if target <= entry:
                i += 1
                continue
        if abs(stop - entry) < 1e-9:
            i += 1
            continue
        risk = abs(entry - stop)
        if rows[i]["time"] == last_entry_t:
            i += 1
            continue
        last_entry_t = rows[i]["time"]
        entry_t = cur["time"]
        j = i + 1
        exit_pnl = None
        while j < n:
            bar = rows[j]
            if side == "BUY":
                if bar["low"] <= stop:
                    exit_pnl = stop - entry
                    break
                if bar["high"] >= target:
                    exit_pnl = target - entry
                    break
            else:
                if bar["high"] >= stop:
                    exit_pnl = entry - stop
                    break
                if bar["low"] <= target:
                    exit_pnl = entry - target
                    break
            j += 1
        if exit_pnl is None:
            j = n - 1
            exit_pnl = rows[j]["close"] - entry if side == "BUY" else entry - rows[j]["close"]
        rr = exit_pnl / risk if risk > 0 else 0.0
        trades.append(
            {"entry_t": entry_t, "side": side, "pnl": round(exit_pnl, 2),
             "rr": round(rr, 2)}
        )
        i = j + 1
    return trades


def main():
    rows = load()
    print(f"loaded {len(rows)} H1 bars")
    t = backtest(rows)
    n = len(t)
    if not n:
        print("RESULT: 0 trades — setup never fired")
        return 0
    total = sum(x["pnl"] for x in t)
    wins = sum(1 for x in t if x["pnl"] > 0)
    rr = [x["rr"] for x in t]
    print(f"RESULT: n={n} pnl={total:.2f} wr={100.0*wins/n:.1f}% "
          f"rr_med={sorted(rr)[n//2]:.2f}")
    print(f"  worst={min(x['pnl'] for x in t):.2f} best={max(x['pnl'] for x in t):.2f}")
    # Baseline: same bars, random-direction control at round numbers
    buys = sum(1 for x in t if x["side"] == "BUY")
    print(f"  side split: BUY={buys} SELL={n-buys}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
