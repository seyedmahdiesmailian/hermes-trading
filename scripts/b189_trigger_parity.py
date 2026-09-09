#!/usr/bin/env python3
"""b189 — PRICE THE b187 ENTRY TRIGGER IN THE LAB (live-parity funnel only).

THE GAP (filed by the b187 requote, 2026-09-09)
==============================================
b187 replaced the zone-touch trigger with an M5 3-close confirmation, and
wired it into the LIVE path only: hermes_runtime.cycle fetches the last 12 M5
rows, filters to settled bars (`time + 300 <= now`) and passes them as
`m5_rows=` into evaluate_monitor_cycle. engines/backtest_real called the SAME
function WITHOUT them — so in the lab the confirmation can never pass, the
pullback lane is structurally dead, and the only signals the funnel still
emits come from plan.py's aggressive paths, which hardcode trigger_ok=True.
That is why the 2026-09-09 requote moved the bar to 0.254/102 and could not say
whether the move was a win or a loss: the lab was pricing a rule live never
runs, AND suppressing the lane live actually trades.

WHAT THIS MEASURES
==================
Everything goes through the SANCTIONED live-parity funnel
(`engines.backtest_real.run_backtest`, HARD RULE — no hand-copied funnel):

  arm A  M15 cached leg, m5_stream=[]        -> the pre-b189-parity control.
            Must reproduce the stored bar 0.254/102 byte-identically, which is
            the proof this change did not touch anything already measured.
  arm B  M15 cached leg, m5_stream=REAL M5   -> the same leg with the trigger
            priced off the broker's own M5 closes.
  arm C  M5 leg (6500 bars, entry TF = live TIMEFRAME), m5_stream=None
            -> THE honest live-parity funnel: every M5 close is a live monitor
            decision, trigger included.
  arm D  same M5 bars, m5_stream=[]          -> control: the same leg with the
            confirmation switched off (zone-touch-free: the pullback lane can
            never fire). C vs D is the price of b187 on identical bars.

Read-only research: nothing here is imported by the live trading path, no gate,
threshold, lot or verdict is touched, and no bridge call is made (all data is
already cached in data/backtest/).
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                    # noqa: E402
from engines.backtest_real import run_backtest           # noqa: E402

OUT = "data/backtest/b189_trigger_parity.json"
M15_LEG = "data/backtest/ab_aggressive_data.json"
M5_LEG = "data/backtest/robustness_data_M5.json"
M5_SOURCE = "data/backtest/b182_m5_bars.json"   # (time, high, low, close) rows


def _rows_from_tuples(blob) -> list[dict]:
    """The b182 cache stores (time, high, low, close) tuples; the funnel wants
    dicts. orchestrator._closes reads either, but the WINDOW slice here keys on
    `time`, so normalise once."""
    out = []
    for r in blob:
        if isinstance(r, dict):
            out.append(r)
        else:
            out.append({"time": r[0], "high": r[1], "low": r[2], "close": r[3]})
    return out


def _harness_kwargs(rows: list[dict]) -> dict:
    """The exit geometry AND gates the merit bar is scored under, DERIVED from
    lab_harness (b118's rule: never restate a live constant here). run_backtest
    is the entry point that owns the funnel, so the arms stay live-parity by
    construction instead of by a hand-copied call."""
    ts = lh.live_time_stop_bars(rows)
    kw = dict(lh.LADDER)                      # trail mult/floor/share, share_fn
    kw.update(min_rr=lh.MIN_RR, min_grade=lh.LIVE_MIN_GRADE,
              time_stop_bars=ts,
              spread_override=lh.SPREAD)
    return kw, ts


def _arm(entry_key: str, leg: dict, *, timeframe: str, m5_stream,
         rows_label: str) -> dict:
    """Run the sanctioned funnel once and report the ladder+time-exit row."""
    rows = leg[entry_key]
    kw, ts = _harness_kwargs(rows)
    res = run_backtest(None, symbol="XAUUSD", timeframe=timeframe,
                       data={timeframe: rows, "H1": leg["H1"],
                             "H4": leg["H4"]},
                       m5_stream=m5_stream, **kw)
    if not res.get("ok"):
        return {"error": res.get("error")}
    stats = lh.r_stats(res, time_stop_bars=ts)
    stats["_leg"] = rows_label
    stats["_bars"] = len(rows)
    stats["_time_stop_bars"] = ts
    return stats


def main() -> int:
    c15 = json.load(open(M15_LEG))
    c5 = json.load(open(M5_LEG))
    m5_src = _rows_from_tuples(json.load(open(M5_SOURCE))["bars"])

    led = {"_note": "b189: the b187 M5 3-close confirmation priced inside the "
                    "live-parity funnel (engines.backtest_real.run_backtest). "
                    "arm A = pre-b189-parity control on the cached M15 leg; "
                    "arm B = same leg priced on real M5 closes; arm C = the "
                    "live-parity M5 leg (entry TF == live TIMEFRAME) with the "
                    "trigger; arm D = the same M5 bars without confirmation "
                    "rows (the pullback lane cannot fire).",
           "_source": {"m15_leg": M15_LEG, "m5_leg": M5_LEG,
                       "m5_closes": M5_SOURCE,
                       "m5_closes_span": [m5_src[0]["time"], m5_src[-1]["time"]],
                       "m5_closes_bars": len(m5_src)},
           "_gates": {"min_rr": lh.MIN_RR, "live_min_rr": lh.LIVE_MIN_RR,
                      "min_grade": lh.LIVE_MIN_GRADE, "spread": lh.SPREAD,
                      "trail_mult": lh.LIVE_TRAIL_MULT,
                      "trail_floor": lh.LIVE_TRAIL_FLOOR}}

    # run_backtest's DEFAULTS are the live gates (min_rr=1.5, min_grade='B'),
    # so every arm is a live-parity book; the only thing the arms vary is the
    # confirmation window they were priced against.
    led["A_m15_no_trigger_rows"] = _arm("M15", c15, timeframe="M15",
                                        m5_stream=[], rows_label="cached M15")
    print("A", {k: led["A_m15_no_trigger_rows"].get(k)
                for k in ("trades", "exp_R", "net_R", "maxDD_R")}, flush=True)

    led["B_m15_real_m5_closes"] = _arm("M15", c15, timeframe="M15",
                                       m5_stream=m5_src, rows_label="cached M15")
    print("B", {k: led["B_m15_real_m5_closes"].get(k)
                for k in ("trades", "exp_R", "net_R", "maxDD_R")}, flush=True)

    led["C_m5_live_parity"] = _arm("M5", c5, timeframe="M5",
                                   m5_stream=None, rows_label="M5 live-parity")
    print("C", {k: led["C_m5_live_parity"].get(k)
                for k in ("trades", "exp_R", "net_R", "maxDD_R")}, flush=True)

    led["D_m5_no_trigger_rows"] = _arm("M5", c5, timeframe="M5",
                                       m5_stream=[], rows_label="M5 live-parity")
    print("D", {k: led["D_m5_no_trigger_rows"].get(k)
                for k in ("trades", "exp_R", "net_R", "maxDD_R")}, flush=True)

    def _pick(row):
        return {k: row.get(k) for k in
                ("trades", "exp_R", "net_R", "WR%", "maxDD_R", "mean_hold_bars")}

    led["_comparison"] = {
        "m15_leg": {"pre_b189_parity": _pick(led["A_m15_no_trigger_rows"]),
                    "with_trigger": _pick(led["B_m15_real_m5_closes"])},
        "m5_leg": {"with_trigger": _pick(led["C_m5_live_parity"]),
                   "no_trigger_control": _pick(led["D_m5_no_trigger_rows"])},
    }
    A, B = led["A_m15_no_trigger_rows"], led["B_m15_real_m5_closes"]
    C, D = led["C_m5_live_parity"], led["D_m5_no_trigger_rows"]
    if "exp_R" in A and "exp_R" in B:
        led["_comparison"]["m15_d_exp_R_trigger_vs_none"] = round(
            B["exp_R"] - A["exp_R"], 3)
        led["_comparison"]["m15_d_trades"] = B["trades"] - A["trades"]
    if "exp_R" in C and "exp_R" in D:
        led["_comparison"]["m5_d_exp_R_trigger_vs_none"] = round(
            C["exp_R"] - D["exp_R"], 3)
        led["_comparison"]["m5_d_trades"] = C["trades"] - D["trades"]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(led, open(OUT, "w"), ensure_ascii=False, indent=1)
    print("\nwrote", OUT)
    for leg in ("m15_leg", "m5_leg"):
        print(leg, json.dumps(led["_comparison"][leg]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
