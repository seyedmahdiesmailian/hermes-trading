#!/usr/bin/env python3
"""Backtest robustness — parity funnel on separate 500-bar windows (backlog item).

Fetches one large cached dataset (~6500 M15 bars ≈ 3 months, read-only rates),
then slices NON-OVERLAPPING 500-bar M15 windows (≈1 trading week each) and runs
the EXACT live-parity funnel (engines.backtest_real.run_backtest, data= so all
windows see byte-identical source bars) on each. Reports variance of WR/PnL
across windows: mean, stdev, min, max.

H1/H4 context rows are padded BEFORE each window start (time <= window_end),
which matches live behaviour where the funnel always has full prior history.

Read-only: fetches rates only, never touches order endpoints.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _ROOT)
# Shared loader: .env parsed READ-ONLY (token never printed, file never modified)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing → local fallback
load_dotenv(os.path.join(_ROOT, '.env'))

from bridge_client import BridgeClient
from engines.backtest_real import run_backtest

SYMBOL = "XAUUSD"
# Entry timeframe must match live TIMEFRAME (M5). Override with argv[1]
# (e.g. "M15") for legacy comparisons; cache/state/out files are per-TF.
TF = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("M") else "M5"
M15_COUNT = 6500          # ~3 months of M15 / ~22 days of M5
WINDOW = 500              # bars per window (non-overlapping)
H1_PAD_BEFORE = 48        # H1 context rows before window start (live has full history)
H4_PAD_BEFORE = 20
DATA_CACHE = Path(_ROOT) / f'data/backtest/robustness_data_{TF}.json'
OUT = Path(_ROOT) / f'data/backtest/robustness_results_{TF}.json'
STATE = Path(_ROOT) / f'data/backtest/robustness_state_{TF}.json'


def fetch(bridge, tf: str, count: int) -> list:
    resp = bridge.get_rates(SYMBOL, tf, count)
    if isinstance(resp, dict) and resp.get("ok"):
        d = resp.get("data", resp.get("rates", []))
        if isinstance(d, list):
            return d
    return []


def ts(b) -> str:
    return datetime.fromtimestamp(b.get("time", 0), tz=timezone.utc).strftime("%m-%d %H:%M")


def main() -> None:
    bridge = BridgeClient()
    if not bridge.health().get("ok"):
        print("Bridge unreachable — aborting (no data fetch possible).")
        sys.exit(1)

    state = json.loads(STATE.read_text()) if STATE.exists() else {"done": []}
    # Only keep stored results for windows the state still marks as done —
    # otherwise a cleared state (fresh rerun after a parity fix) silently
    # mixes stale pre-fix numbers with new ones (measured: 26 rows for 13 windows).
    results = []
    if OUT.exists():
        try:
            done = set(state["done"])
            results = [r for r in json.loads(OUT.read_text())["results"] if r.get("window") in done]
        except Exception:
            results = []

    # One dataset, cached: every window slices the same byte-identical bars.
    if DATA_CACHE.exists():
        data = json.loads(DATA_CACHE.read_text())
        print(f"cached: {TF}={len(data[TF])} H1={len(data['H1'])} H4={len(data['H4'])}")
    else:
        data = {TF: fetch(bridge, TF, M15_COUNT),
                "H1": fetch(bridge, "H1", 2000),
                "H4": fetch(bridge, "H4", 700)}
        if len(data[TF]) < WINDOW * 3 or not data["H1"] or not data["H4"]:
            print("insufficient data — aborting")
            sys.exit(1)
        DATA_CACHE.write_text(json.dumps(data))
        print(f"fetched+cached: {TF}={len(data[TF])} H1={len(data['H1'])} H4={len(data['H4'])}")

    m15, h1, h4 = data[TF], data["H1"], data["H4"]
    n_windows = len(m15) // WINDOW
    print(f"{n_windows} non-overlapping {WINDOW}-bar windows (each ~1 trading week)\n")

    for w in range(n_windows):
        key = f"win{w:02d}"
        if key in state["done"]:
            continue
        lo, hi = w * WINDOW, (w + 1) * WINDOW
        w_m15 = m15[lo:hi]
        t_end = w_m15[-1]["time"]
        t_start_pad = w_m15[0]["time"] - H1_PAD_BEFORE * 3600
        slice_data = {
            TF: w_m15,
            "H1": [r for r in h1 if t_start_pad <= r.get("time", 0) <= t_end],
            "H4": [r for r in h4 if w_m15[0]["time"] - H4_PAD_BEFORE * 4 * 3600
                   <= r.get("time", 0) <= t_end],
        }
        r = run_backtest(bridge, symbol=SYMBOL, timeframe=TF, count=WINDOW, data=slice_data)
        if not r.get("ok"):
            print(f"{key}: engine error {r.get('error')} — skipping")
            continue
        r.pop("trade_log", None)
        r["window"] = key
        r["bars"] = [w_m15[0]["time"], t_end]
        results.append(r)
        state["done"].append(key)
        STATE.write_text(json.dumps(state))
        OUT.write_text(json.dumps({"n_windows": n_windows, "window_bars": WINDOW,
                                   "results": results}, indent=2))
        wr = r.get("win_rate", 0) * 100
        print(f"{key} {ts(w_m15[0])}→{ts(w_m15[-1])} trades={r.get('trades', 0):3d} "
              f"W={r.get('wins', 0):2d} L={r.get('losses', 0):2d} scr={r.get('scratches', 0):2d} "
              f"WR={wr:5.1f}% pnl={r.get('net_pnl', 0):+9.2f}")

    # ── variance summary over completed windows ──
    if len(results) < 2:
        print("\nneed ≥2 windows for variance — rerun to continue")
        return
    pnls = [r["net_pnl"] for r in results]
    wrs = [r.get("win_rate", 0) * 100 for r in results]
    trs = [r.get("trades", 0) for r in results]
    tot = sum(pnls)

    def stats(xs):
        n = len(xs)
        mean = sum(xs) / n
        sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
        return mean, sd, min(xs), max(xs)

    print(f"\n=== VARIANCE over {len(results)}/{n_windows} windows ({WINDOW} bars each) ===")
    for name, xs, fmt in (("PnL ($)", pnls, "{:+8.2f}"), ("WR (%)", wrs, "{:6.1f}"),
                          ("trades", [float(t) for t in trs], "{:6.1f}")):
        mean, sd, lo, hi = stats(xs)
        print(f"{name:9s} mean={fmt.format(mean)} sd={sd:7.2f} min={fmt.format(lo)} max={fmt.format(hi)}")
    print(f"total PnL across all windows: {tot:+.2f} over {sum(trs)} trades")
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
