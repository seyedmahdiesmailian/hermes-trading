#!/usr/bin/env python3
"""b68l — TRULY INDEPENDENT backtest windows (the round-11 methodology fix).

Why this exists (found while designing b68 round 11, 2026-09-04): every
confirm of rounds 1-10 fetched "the last 6000 M15 bars" as the FRESH set and
re-measured the funnel on the SAME bars (b68 round-4 rule). But the cached
3000-bar set (data/backtest/ab_aggressive_data.json, 2026-07-15 10:00 ->
2026-08-28 23:45 UTC) sits at the END of the broker's M15 history — the last
6000 bars contain ALL 3000 cached bars (100% overlap, measured). So the
"cached vs fresh" merit bar was never an out-of-sample test: it compared the
same July-August regime against a superset of itself. Round 9's champion
(pdh x dayext, 0.924 cached / 0.891 "fresh") has therefore NEVER been scored
on data that excludes the regime it was discovered in.

This module builds the windows the loop should have had from the start:

  W1 — the last 6000 M15 bars STRICTLY BEFORE the cached set's first bar;
  W2 — the last 6000 M15 bars strictly before W1 (a second independent
       window, so b74's ">=2 more independent windows" has its second draw);
  W3 — the last 6000 M15 bars strictly before W2 (round 13, b74's THIRD
       draw: the round-12 champion pdh_h4t_agree replicated on W1+W2, and
       b74 requires >=2 MORE independent windows before a wiring proposal —
       W3 is the next uncontaminated slice the broker's 60000-bar history
       can give);
  W4 — the last 6000 M15 bars strictly before W3 (round 14, b74's FOURTH
       draw: funnel_h4t_agree beat the funnel on W1/W2/W3 with margins
       DECAYING +0.093→+0.032→+0.008, and b74's round-13 note says the
       protocol must price the DECAY, not just the mean — W4 is the draw
       that decides whether the candidate survives or dies).

Each window ships with its H1/H4 context streams (strategy_signal needs
80-bar H1/H4 windows up to each bar's time — the full fetched history is
kept, the consumer slices by time). Windows are cached to
data/backtest/b68l_independent_windows.json so a re-run is deterministic and
offline; overlap with the cached set and between windows is ASSERTED empty
and recorded in the file (a number that must never rot silently).

Read-only: the only bridge calls are get_rates (history). Nothing here is
imported by the live trading path.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))      # b65: BridgeClient consumer owns env

from bridge_client import BridgeClient                       # noqa: E402
from engines.backtest_real import fetch_all_ohlc             # noqa: E402

CACHED = os.path.join(_ROOT, "data", "backtest", "ab_aggressive_data.json")
OUT = os.path.join(_ROOT, "data", "backtest",
                   "b68l_independent_windows.json")
WINDOW_BARS = 6000
FETCH_COUNT = 60000          # broker gives 60000 M15 bars back to 2024-02
# Ordered newest->oldest; each is 6000 M15 bars strictly before the previous.
# W4 needs 5*6000=30000 bars before the cached set — the 60000-bar fetch
# reaches 2024-02, so W4 (2025-07 -> 2025-10) still exists.
WINDOW_NAMES = ("W1", "W2", "W3", "W4")


def cached_span() -> tuple[int, int]:
    """(first_bar_time, last_bar_time) of the cached M15 set."""
    rows = json.load(open(CACHED))["M15"]
    return int(rows[0]["time"]), int(rows[-1]["time"])


def build_windows(fetch: bool = True) -> dict:
    """Slice W1..W4 out of the broker's deep M15 history + H1/H4 context.

    Returns the ledger dict (also written to OUT when fetch=True).
    """
    c0, c1 = cached_span()
    bridge = BridgeClient()
    m15 = fetch_all_ohlc(bridge, "XAUUSD", "M15", FETCH_COUNT)
    h1 = fetch_all_ohlc(bridge, "XAUUSD", "H1", FETCH_COUNT)
    h4 = fetch_all_ohlc(bridge, "XAUUSD", "H4", FETCH_COUNT)
    if len(m15) < (len(WINDOW_NAMES) + 1) * WINDOW_BARS:
        raise RuntimeError(f"not enough M15 history: {len(m15)} bars")

    made: dict[str, list[dict]] = {}
    pool = [r for r in m15 if int(r["time"]) < c0]
    for name in WINDOW_NAMES:
        win = pool[-WINDOW_BARS:]
        if len(win) < WINDOW_BARS:
            raise RuntimeError(f"{name} truncated: {len(win)} bars — broker "
                               f"history cannot give window {name}")
        made[name] = win
        lo = int(win[0]["time"])
        pool = [r for r in pool if int(r["time"]) < lo]

    def ctx(rows: list[dict], lo: int, hi: int) -> dict:
        """H1/H4 covering [lo - 200h, hi] so every window bar has >=80 bars
        of context before it (strategy_signal slices by time itself)."""
        pad = 200 * 3600
        return {"H1": [r for r in rows["H1"]
                       if lo - pad <= int(r["time"]) <= hi],
                "H4": [r for r in rows["H4"]
                       if lo - pad <= int(r["time"]) <= hi]}

    src = {"M15": m15, "H1": h1, "H4": h4}
    out: dict = {"_cached_span": [c0, c1],
                 "_cached_bars": 3000,
                 "_window_bars": WINDOW_BARS}
    spans = {}
    for name, rows in made.items():
        lo, hi = int(rows[0]["time"]), int(rows[-1]["time"])
        spans[name] = (lo, hi)
        out[name] = {"M15": rows, **ctx(src, lo, hi)}
        out[f"_{name}_meta"] = {
            "m15_bars": len(rows), "first": lo, "last": hi,
            # contamination fact, MEASURED: bars inside the cached span
            "overlap_with_cached": sum(
                1 for r in rows if c0 <= int(r["time"]) <= c1),
        }
    # cross-window overlap (each window must end before the previous one
    # starts by construction — measured, not assumed, for every pair).
    # _W1_W2_overlap keeps its founding name (pinned by round-11 tests).
    names = list(made)
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            ta = {int(x["time"]) for x in made[names[a]]}
            ov = sum(1 for r in made[names[b]] if int(r["time"]) in ta)
            if (names[a], names[b]) == ("W1", "W2"):
                out["_W1_W2_overlap"] = ov
            else:
                out[f"_{names[a]}_{names[b]}_overlap"] = ov
    # THE contamination fact, measured not asserted-from-memory:
    last6000 = m15[-WINDOW_BARS:]
    out["_last6000_overlap_with_cached"] = sum(
        1 for r in last6000 if c0 <= int(r["time"]) <= c1)
    if fetch:
        json.dump(out, open(OUT, "w"))
    return out


def load_windows() -> dict:
    if not os.path.exists(OUT):
        raise RuntimeError("independent windows not built — run "
                           "python3 scripts/b68l_windows.py first")
    return json.load(open(OUT))


def main() -> None:
    out = build_windows(fetch=True)
    import datetime as _dt

    def ts(t):
        return _dt.datetime.fromtimestamp(int(t), _dt.timezone.utc)
    for name in WINDOW_NAMES:
        m = out[f"_{name}_meta"]
        print(f"{name}: {m['m15_bars']} M15 bars  "
              f"{ts(m['first'])} -> {ts(m['last'])}  "
              f"overlap_with_cached={m['overlap_with_cached']}")
    for k in sorted(out):
        if k.endswith("_overlap") and not k.startswith("_last"):
            print(f"{k}:", out[k])
    print("last-6000 (old 'fresh') ∩ cached:",
          out["_last6000_overlap_with_cached"], "/ 3000 cached bars")
    print("saved:", os.path.abspath(OUT),
          f"({os.path.getsize(OUT)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
