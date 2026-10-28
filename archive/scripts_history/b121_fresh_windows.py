#!/usr/bin/env python3
"""b121 step 1 — TWO FRESH INDEPENDENT WINDOWS (W5, W6) BEYOND THE SELECTION SET.

WHY (b121's own precondition 1)
===============================
b119 found `flat_0.30` (keep a 0.3 runner on EVERY trade) beating the live
grade-weighted incumbent on exp_R in 4/4 windows. Those four windows are
W1..W4 — the SAME bars every exit decision in this repo has been chosen on
since b68l built them. A one-sided delta measured on the selection set is not
replication; b74's protocol says a candidate needs independent draws it was
never ranked on. W5 and W6 are those draws.

WHAT THIS DOES
==============
Slice the last 2 x 6000 M15 bars strictly BEFORE W4 out of the broker's deep
history, with the same H1/H4 context padding b68l uses, and MEASURE (not
assert) that each new window overlaps nothing: not the cached set, not W1..W4.
The anchor is read out of the existing b68l ledger, so the new windows cannot
silently slide into the old ones if that file is ever rebuilt.

Bar-count and fetch constants are IMPORTED from b68l_windows — a restated
6000 is a second source of truth (b109's disease).

Read-only: the only bridge calls are get_rates (history). Nothing here is
imported by the live trading path.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

from bridge_client import BridgeClient                        # noqa: E402
from engines.backtest_real import fetch_all_ohlc              # noqa: E402
from scripts import b68l_windows as wl                        # noqa: E402

OUT = os.path.join(_ROOT, "data", "backtest", "b121_fresh_windows.json")
WINDOW_BARS = wl.WINDOW_BARS          # 6000, imported not restated
FETCH_COUNT = wl.FETCH_COUNT          # 60000, imported not restated
NEW_NAMES = ("W5", "W6")


def _old_spans() -> dict:
    """(first,last) of the cached set and of W1..W4, read from their ledgers."""
    c0, c1 = wl.cached_span()
    old = {"cached": (int(c0), int(c1))}
    wins = json.load(open(wl.OUT))
    for name in wl.WINDOW_NAMES:
        m = wins[f"_{name}_meta"]
        old[name] = (int(m["first"]), int(m["last"]))
    return old


def build(fetch: bool = True) -> dict:
    spans = _old_spans()
    anchor = spans["W4"][0]                 # everything must be strictly older
    bridge = BridgeClient()
    src = {"M15": fetch_all_ohlc(bridge, "XAUUSD", "M15", FETCH_COUNT),
           "H1": fetch_all_ohlc(bridge, "XAUUSD", "H1", FETCH_COUNT),
           "H4": fetch_all_ohlc(bridge, "XAUUSD", "H4", FETCH_COUNT)}
    m15 = src["M15"]
    if not m15:
        raise RuntimeError("bridge gave no M15 history")
    pool = [r for r in m15 if int(r["time"]) < anchor]
    made: dict[str, list[dict]] = {}
    for name in NEW_NAMES:
        win = pool[-WINDOW_BARS:]
        if len(win) < WINDOW_BARS:
            raise RuntimeError(
                f"{name} truncated: {len(win)} bars available before the "
                f"anchor — broker history cannot give this window")
        made[name] = win
        pool = [r for r in pool if int(r["time"]) < int(win[0]["time"])]

    def ctx(rows: list[dict], lo: int, hi: int) -> dict:
        pad = 200 * 3600                     # same padding rule as b68l
        return {"H1": [r for r in rows["H1"] if lo - pad <= int(r["time"]) <= hi],
                "H4": [r for r in rows["H4"] if lo - pad <= int(r["time"]) <= hi]}

    out: dict = {"_anchor_first_bar_W4": anchor,
                 "_old_spans": {k: list(v) for k, v in spans.items()},
                 "_window_bars": WINDOW_BARS}
    for name, rows in made.items():
        lo, hi = int(rows[0]["time"]), int(rows[-1]["time"])
        ov = {}
        for other, (o0, o1) in spans.items():
            ov[other] = sum(1 for r in rows if o0 <= int(r["time"]) <= o1)
        # overlap with the OTHER new window (they must be disjoint too)
        for other_name, other_rows in made.items():
            if other_name == name:
                continue
            ts = {int(r["time"]) for r in other_rows}
            ov[other_name] = sum(1 for r in rows if int(r["time"]) in ts)
        out[name] = {"M15": rows, **ctx(src, lo, hi)}
        out[f"_{name}_meta"] = {"m15_bars": len(rows), "first": lo, "last": hi,
                                "h1_ctx": len(out[name]["H1"]),
                                "h4_ctx": len(out[name]["H4"]),
                                "overlaps": ov}
        assert sum(ov.values()) == 0, f"{name} contaminated: {ov}"
    if fetch:
        json.dump(out, open(OUT, "w"))
    return out


def load() -> dict:
    if not os.path.exists(OUT):
        raise RuntimeError("fresh windows not built — run "
                           "python3 scripts/b121_fresh_windows.py first")
    return json.load(open(OUT))


def main() -> None:
    out = build(fetch=True)
    def ts(t):
        return dt.datetime.fromtimestamp(int(t), dt.timezone.utc)
    for name in NEW_NAMES:
        m = out[f"_{name}_meta"]
        print(f"{name}: {m['m15_bars']} M15 bars {ts(m['first'])} -> {ts(m['last'])} "
              f"h1_ctx={m['h1_ctx']} h4_ctx={m['h4_ctx']} overlaps={m['overlaps']}")
    print("saved:", os.path.abspath(OUT), f"({os.path.getsize(OUT)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
