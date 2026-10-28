#!/usr/bin/env python3
"""b191 — THE TRUE LIVE-PARITY BAR: M5 ENTRY WINDOWS, run_backtest only.

WHY THIS EXISTS (filed by b189/b190, 2026-09-09)
================================================
Every cited merit-bar number so far lives on M15 ENTRY legs: b190 re-baselined
cached/W1..W4 (all 6000-bar M15 windows) against the broker's real M5 closes,
and b189 priced the b187 trigger on its own 6500-bar M5 leg — but that leg
(Jul 28 - Aug 28) sits INSIDE the cached M15 span, so it is the same July-August
regime the funnel was tuned on, not an independent draw. The one missing view
(b190's own docstring, "FOLLOW-UP FILED AS b191") is W-style INDEPENDENT
windows run on the LIVE ENTRY TIMEFRAME (M5, what hermes_runtime actually
trades), where the trigger rows are the stream's own settled closes exactly as
live sees them — no M15 proxy anywhere.

WHAT THIS MEASURES (HARD RULE: the sanctioned funnel only)
==========================================================
Windows are built exactly like b68l's: M5 bars STRICTLY BEFORE the cached M15
set's first bar (2026-07-15 10:00 UTC), each 6500 bars (b189's arm-C size, so
its 166/0.197 is the natural fifth row), newest-window-first M5W1..M5W4. The
bridge caps M5 history at 60000 bars (~2025-11-03 onward, measured in b190),
so independent M5 windows can only start ~2025-11 — exactly the limitation the
b191 item states; every window is measured for length and overlap instead of
assumed.

Each leg runs TWICE through `engines.backtest_real.run_backtest` on the same
bars (never a hand-copied funnel), under `lab_harness` live exit geometry:

  wired    m5_stream=None   the entry stream IS M5 == live TIMEFRAME, so the
                            b189 derivation feeds the settled closes at every
                            decision moment — byte-parity with hermes_runtime.
  control  m5_stream=[]     the pre-b189-parity arm: no confirmation rows, the
                            pullback lane can never fire (b189's arm-D shape).

INTEGRITY ANCHORS (measured in-script, fail loud):
  * M5W0 == b189's arm C leg (robustness_data_M5.json, inside the cached span)
    reproduced by THIS script's arm builder must print 166/0.197 wired and
    159/0.212 control — the pin that the window machinery is the same funnel
    that produced the stored numbers.
  * `_m5_coverage` per leg via the shared `m5_window_for` (b190's honesty gate:
    a leg below 0.9 cannot be quoted wired; for M5-entry legs it is ~1.0 by
    construction, and this MEASURES rather than asserts it).

Read-only research: nothing here is imported by the live trading path; no gate,
threshold, lot or verdict is touched; the only bridge call is get_rates
(history), fetched ONCE and cached to data/backtest/b191_m5_ohlc.json.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))      # b65: BridgeClient consumer owns env

from bridge_client import BridgeClient                        # noqa: E402
from engines import lab_harness as lh                          # noqa: E402
from engines.backtest_real import (fetch_all_ohlc,            # noqa: E402
                                   m5_window_for)
from scripts import b190_merit_bar_live_trigger as b190        # noqa: E402
from scripts.b68l_windows import cached_span                   # noqa: E402

OUT = "data/backtest/b191_m5_window_lab.json"
M5_OHLC_CACHE = "data/backtest/b191_m5_ohlc.json"
B189_LEDGER = "data/backtest/b189_trigger_parity.json"
B189_M5_LEG = "data/backtest/robustness_data_M5.json"

M5_FETCH = 60000          # the bridge's own M5 cap (measured in b190)
WIN_BARS = 6500           # b189 arm-C size: every leg comparable to its 166/0.197
WINDOW_NAMES = ("M5W1", "M5W2", "M5W3", "M5W4")
MIN_TRIG_ROWS = 3         # orchestrator.m5_confirmation's minimum (b190's value)
COVERAGE_FLOOR = 0.9      # b190's honesty floor, shared constant by reference


def _harness_kwargs(rows: list[dict]) -> tuple[dict, int]:
    """Live exit geometry + gates DERIVED from lab_harness (b118's rule), the
    exact call shape b189's _arm / b190's _arm used."""
    ts = lh.live_time_stop_bars(rows)
    kw = dict(lh.LADDER)
    kw.update(min_rr=lh.MIN_RR, min_grade=lh.LIVE_MIN_GRADE,
              time_stop_bars=ts, spread_override=lh.SPREAD)
    return kw, ts


def fetch_m5_ohlc(force: bool = False) -> list[dict]:
    """The full broker M5 history as complete row dicts (the entry stream
    needs open/high/low, not just closes — backtest_ohlc touches the bar
    extremes). Read-only get_rates, cached once."""
    if os.path.exists(M5_OHLC_CACHE) and not force:
        return json.load(open(M5_OHLC_CACHE))["rows"]
    rows = fetch_all_ohlc(BridgeClient(), "XAUUSD", "M5", M5_FETCH)
    if not rows:
        raise RuntimeError("bridge returned no M5 history")
    rows = sorted(rows, key=lambda r: int(r["time"]))
    with open(M5_OHLC_CACHE, "w") as fh:
        json.dump({"_span": [int(rows[0]["time"]), int(rows[-1]["time"])],
                   "_bars": len(rows),
                   "_note": "b191: broker M5 OHLC, get_rates only; entry "
                            "stream for the independent M5 window legs",
                   "rows": rows}, fh)
    return rows


def fetch_context() -> dict:
    """H1/H4 streams covering the whole M5 span (+200h pad, b68l's ctx rule).
    60000 H1 bars reach ~6.8 years — strictly deeper than the M5 window."""
    b = BridgeClient()
    return {"H1": fetch_all_ohlc(b, "XAUUSD", "H1", M5_FETCH),
            "H4": fetch_all_ohlc(b, "XAUUSD", "H4", M5_FETCH)}


def build_windows(m5: list[dict]) -> dict:
    """M5W1..M5W4: 6500 M5 bars strictly before the cached M15 set, newest
    first, each independent of the others (b68l's construction, M5 spacing).
    Raises if the broker's M5 reach cannot give all four — measured, never
    assumed (that is the item's stated ~2025-11 limit)."""
    c0, _c1 = cached_span()
    pool = [r for r in m5 if int(r["time"]) < c0]
    if len(pool) < len(WINDOW_NAMES) * WIN_BARS:
        raise RuntimeError(
            f"M5 history before the cached span: {len(pool)} bars — not "
            f"enough for {len(WINDOW_NAMES)} x {WIN_BARS} independent windows")
    out: dict[str, list[dict]] = {}
    for name in WINDOW_NAMES:
        win = pool[-WIN_BARS:]
        out[name] = win
        pool = [r for r in pool if int(r["time"]) < int(win[0]["time"])]
    return out


def _context_for(ctx: dict, lo: int, hi: int) -> dict:
    pad = 200 * 3600
    return {tf: [r for r in rows if lo - pad <= int(r["time"]) <= hi]
            for tf, rows in ctx.items()}


def _arm(rows: list[dict], ctx: dict, m5_stream, ts: int) -> dict:
    from engines.backtest_real import run_backtest
    kw, _ = _harness_kwargs(rows)
    run = run_backtest(None, symbol="XAUUSD", timeframe="M5",
                       data={"M5": rows, "H1": ctx["H1"], "H4": ctx["H4"]},
                       m5_stream=m5_stream, **kw)
    if not run.get("ok"):
        return {"error": run.get("error")}
    stats = lh.r_stats(run, time_stop_bars=ts)
    stats["_bars"] = len(rows)
    stats["_time_stop_bars"] = ts
    return stats


def coverage(rows: list[dict]) -> float:
    """Share of leg bars whose decision moment holds >= MIN_TRIG_ROWS settled
    M5 closes through the SAME m5_window_for the funnel slices with (b190's
    function, imported not restated)."""
    times = [int(r["time"]) for r in rows]
    spacing = lh.bar_seconds(rows)
    hit = sum(1 for r in rows
              if isinstance(r.get("time"), (int, float))
              and len(m5_window_for(rows, times, int(r["time"]) + spacing))
              >= MIN_TRIG_ROWS)
    return round(hit / len(rows), 4) if rows else 0.0


def measure_leg(name: str, rows: list[dict], ctx: dict) -> dict:
    ts = lh.live_time_stop_bars(rows)
    out = {"_entry_bars": len(rows),
           "_span": [int(rows[0]["time"]), int(rows[-1]["time"])],
           "_m5_coverage": coverage(rows),
           "control_no_trigger": _arm(rows, ctx, [], ts),
           "wired_own_m5_closes": _arm(rows, ctx, None, ts)}
    c, w = out["control_no_trigger"], out["wired_own_m5_closes"]
    if "exp_R" in c and "exp_R" in w:
        out["d_exp_R"] = round(w["exp_R"] - c["exp_R"], 3)
        out["d_trades"] = w["trades"] - c["trades"]
    return out


def measure_anchor() -> dict:
    """Reproduce b189's arm C/D (the Jul-Aug M5 leg INSIDE the cached span)
    with this script's own arms — the integrity anchor."""
    c5 = json.load(open(B189_M5_LEG))
    rows = c5["M5"]
    ctx = {"H1": c5["H1"], "H4": c5["H4"]}
    led = json.load(open(B189_LEDGER))
    out = measure_leg("M5W0_anchor", rows, ctx)
    out["_stored_b189"] = {
        "wired": [led["C_m5_live_parity"]["trades"],
                  led["C_m5_live_parity"]["exp_R"]],
        "control": [led["D_m5_no_trigger_rows"]["trades"],
                    led["D_m5_no_trigger_rows"]["exp_R"]]}
    out["anchor_ok"] = (
        [out["wired_own_m5_closes"]["trades"],
         out["wired_own_m5_closes"]["exp_R"]] == out["_stored_b189"]["wired"]
        and [out["control_no_trigger"]["trades"],
             out["control_no_trigger"]["exp_R"]]
        == out["_stored_b189"]["control"])
    return out


def bar(led: dict) -> dict:
    """THE MACHINE-READABLE M5-ENTRY BAR: wired exp_R per leg, coverage-gated
    exactly like b190.bar() (a leg below the floor is None, never a fake
    'wired' number that is really the control — b116's class)."""
    out = {}
    for leg in led["_legs"]:
        L = led[leg]
        if L["_m5_coverage"] < COVERAGE_FLOOR:
            out[leg] = None
        else:
            out[leg] = L["wired_own_m5_closes"]["exp_R"]
    out["_control_bar"] = {leg: led[leg]["control_no_trigger"]["exp_R"]
                           for leg in led["_legs"]}
    out["_coverage_floor"] = COVERAGE_FLOOR
    return out


def trigger_delta(led: dict) -> dict:
    """Per-leg wired-minus-control, pure arithmetic on the ledger (b127: the
    same function the tests re-execute)."""
    return {leg: {"d_exp_R": led[leg].get("d_exp_R"),
                  "d_trades": led[leg].get("d_trades"),
                  "coverage": led[leg]["_m5_coverage"]}
            for leg in led["_legs"]}


def _independence_block(wins: dict) -> dict:
    """Contamination facts, MEASURED per leg (b68l's rule): bars, span, and
    overlap with the cached M15 span, which must be 0 by construction."""
    c0, c1 = cached_span()
    block = {"cached_m15_first": c0, "cached_m15_last": c1}
    for n, w in wins.items():
        block[n] = {"bars": len(w),
                    "first": int(w[0]["time"]), "last": int(w[-1]["time"]),
                    "overlap_with_cached_span": sum(
                        1 for r in w if c0 <= int(r["time"]) <= c1)}
    return block


def main() -> int:
    m5 = fetch_m5_ohlc()
    wins = build_windows(m5)
    ctx = fetch_context()

    led = {"_note": "b191: the merit bar on the LIVE ENTRY TIMEFRAME — "
                    "independent 6500-bar M5 windows strictly before the "
                    "cached M15 span, every arm engines.backtest_real."
                    "run_backtest with lab_harness live exit geometry; "
                    "wired = the stream's own settled M5 closes (byte-parity "
                    "with hermes_runtime), control = m5_stream=[] (pre-b189 "
                    "parity). M5W0 reproduces b189's arm C/D as the integrity "
                    "anchor.",
           "_legs": ["M5W0_anchor"] + list(WINDOW_NAMES),
           "_m5_source": {"file": M5_OHLC_CACHE, "bars": len(m5),
                          "first": int(m5[0]["time"]),
                          "last": int(m5[-1]["time"])},
           "_gates": {"min_rr": lh.MIN_RR, "live_min_rr": lh.LIVE_MIN_RR,
                      "min_grade": lh.LIVE_MIN_GRADE, "spread": lh.SPREAD,
                      "trail_mult": lh.LIVE_TRAIL_MULT,
                      "trail_floor": lh.LIVE_TRAIL_FLOOR},
           "_independence": _independence_block(wins)}

    print("##### M5W0_anchor (b189 leg) #####", flush=True)
    led["M5W0_anchor"] = measure_anchor()
    print("  anchor_ok =", led["M5W0_anchor"]["anchor_ok"], flush=True)
    if not led["M5W0_anchor"]["anchor_ok"]:
        print("  ANCHOR MISMATCH vs b189:",
              json.dumps(led["M5W0_anchor"]["_stored_b189"]), flush=True)
        return 2

    for name in WINDOW_NAMES:
        rows = wins[name]
        lo, hi = int(rows[0]["time"]), int(rows[-1]["time"])
        print(f"##### {name} ({lo} -> {hi}) #####", flush=True)
        led[name] = measure_leg(name, rows, _context_for(ctx, lo, hi))
        c, w = led[name]["control_no_trigger"], led[name]["wired_own_m5_closes"]
        print(f"  cov={led[name]['_m5_coverage']} control={c.get('trades')}"
              f"/{c.get('exp_R')} wired={w.get('trades')}/{w.get('exp_R')}",
              flush=True)

    led["_merit_bar_m5_entry"] = bar(led)
    led["_trigger_delta"] = trigger_delta(led)
    # cross-read the b190 bar this lab sits beside (pure arithmetic on stored
    # ledgers; b127 re-runs both blocks from the frozen file).
    led["_band_vs_b190_m15_bar"] = band_comparison(led)

    with open(OUT, "w") as fh:
        json.dump(led, fh, indent=1)
    print("\nM5-entry bar (wired, coverage>=0.9):",
          json.dumps(led["_merit_bar_m5_entry"]))
    print("trigger delta:", json.dumps(led["_trigger_delta"]))
    print("band vs b190:", json.dumps(led["_band_vs_b190_m15_bar"]))
    print("saved:", os.path.abspath(OUT))
    return 0


def band_comparison(led: dict) -> dict:
    """Where the M5-entry legs sit against the cited b190 ~0.20-0.28 band.
    Pure arithmetic over the two frozen ledgers (b127 re-runnable). The
    M5W0_anchor leg is the b189 INSIDE-cached-span leg — an integrity row,
    never part of the quoted band (that would mix the tuned regime back into
    the out-of-sample view, the exact b68l round-11 contamination)."""
    b190_led = json.load(open(b190.OUT))
    m15_bar = {k: v for k, v in b190_led["_merit_bar_live_wired"].items()
               if k not in ("_control_bar", "_coverage_floor")}
    m5_bar = {k: v for k, v in led["_merit_bar_m5_entry"].items()
              if not k.startswith("_") and k != "M5W0_anchor"}
    vals = [v for v in list(m15_bar.values()) + list(m5_bar.values())
            if isinstance(v, float)]
    m15_vals = [v for v in m15_bar.values() if isinstance(v, float)]
    return {"b190_m15_wired": m15_bar,
            "b191_m5_entry_wired": m5_bar,
            "m15_quoted": [min(m15_vals), max(m15_vals)] if m15_vals else None,
            "all_quoted_span": [min(vals), max(vals)] if vals else None}


if __name__ == "__main__":
    sys.exit(main())
