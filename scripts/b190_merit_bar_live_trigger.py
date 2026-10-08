#!/usr/bin/env python3
"""b190 — RE-BASELINE THE MERIT BAR UNDER THE b187-WIRED FUNNEL (run_backtest only).

WHY THIS EXISTS (filed by b189, 2026-09-09)
===========================================
b189 wired the live b187 entry trigger (M5 3-close confirmation) into
`engines.backtest_real`: `run_backtest` now feeds `m5_window_for(...)` — the
settled M5 closes live holds at each decision moment — into `strategy_signal`.
But EVERY stored funnel ledger (b117's trail grid, b118's merit bar, b109,
b119, b121...) was produced through `scripts.b81_lane_rescore.funnel_fn`,
which calls `strategy_signal` WITHOUT `m5_rows` (and derives nothing, because
an M15 window is not an M5 stream). Re-running those scripts today therefore
reproduces the PRE-WIRING bar 0.254/102 byte-identically — it cannot see the
trigger b189 connected. The b189 done-note says it plainly: the lab merit of
the shipped trigger is ~neutral on the true TF (-0.015R, +7 trades on 6500
M5 bars) but "pending re-baseline". This is that re-baseline.

WHAT THIS MEASURES (HARD RULE: the sanctioned funnel only)
=========================================================
Every arm runs through `engines.backtest_real.run_backtest` — never a
hand-copied funnel — on the SAME legs the bar has always been quoted on
(cached M15 + W1..W4 from `b68l_windows`), twice per leg:

  control  m5_stream=[]          the pre-b189-parity arm. On `cached` it MUST
                                 reproduce the stored 102/0.254 (b118's
                                 re-quoted harness bar) and the wired arm MUST
                                 reproduce b189's 104/0.280 — those two
                                 cross-pins are the integrity proof that this
                                 round moved nothing but the M5 source.
  wired    m5_stream=REAL M5     the same leg priced against the broker's own
                                 settled M5 closes (the b189 arm-B method,
                                 extended to every window leg for the first
                                 time), fetched ONCE (read-only get_rates) and
                                 cached to data/backtest/b190_m5_closes.json.

HONESTY COVERAGE: the bridge caps M5 history at 60000 bars (~2025-11-03
onward). W3 starts 2025-10-08 and W4 ends 2025-10-08, so for those legs the
"wired" arm has no closes at decision time and degenerates to the control —
this script MEASURES that per leg (`_m5_coverage` = share of leg bars with at
least 3 settled M5 closes at their decision moment, the trigger's minimum) and
`bar()` REFUSES to quote a leg below 0.9 coverage. A number that silently
means "no trigger" is exactly the b116 defect class.

FOLLOW-UP FILED (b191): the TRUE live-parity bar is an M5 ENTRY stream over a
window-independent horizon (b189 priced only its own 6500-bar July-Aug leg,
166 trades / 0.197); extending it needs a cached M5 OHLC + H1/H4 context set.
Nothing here is imported by the live trading path; no gate, threshold, lot or
verdict is touched; the only bridge call is get_rates (history).
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
from scripts import b81_lane_rescore as b81                    # noqa: E402
from scripts import b68l_windows as wl                         # noqa: E402

OUT = "data/backtest/b190_merit_bar_live_trigger.json"
M5_CACHES = "data/backtest/b190_m5_closes.json"
LEGS = b81.LEGS                       # cached, W1..W4 — the legs the bar lives on
CACHED_LEG = "data/backtest/ab_aggressive_data.json"
B189_LEDGER = "data/backtest/b189_trigger_parity.json"
M5_FETCH = 60000                      # the bridge's own M5 cap (measured)
MIN_TRIG_ROWS = 3                     # orchestrator.m5_confirmation's minimum
COVERAGE_FLOOR = 0.9                  # below this a leg cannot be quoted "wired"


def _harness_kwargs(rows: list[dict]) -> tuple[dict, int]:
    """Live exit geometry + gates DERIVED from lab_harness (b118's rule), the
    same call shape b189's _arm used, so the two rounds cannot diverge by
    construction."""
    ts = lh.live_time_stop_bars(rows)
    kw = dict(lh.LADDER)
    kw.update(min_rr=lh.MIN_RR, min_grade=lh.LIVE_MIN_GRADE,
              time_stop_bars=ts, spread_override=lh.SPREAD)
    return kw, ts


def fetch_m5_closes(force: bool = False) -> list[dict]:
    """Settled broker M5 closes for the whole reachable history, cached as
    [time, close] pairs (the trigger reads nothing else). Read-only get_rates."""
    if os.path.exists(M5_CACHES) and not force:
        blob = json.load(open(M5_CACHES))["closes"]
        return [{"time": t, "close": c} for t, c in blob]
    rows = fetch_all_ohlc(BridgeClient(), "XAUUSD", "M5", M5_FETCH)
    if not rows:
        raise RuntimeError("bridge returned no M5 history")
    closes = [[int(r["time"]), float(r["close"])] for r in rows]
    with open(M5_CACHES, "w") as fh:
        json.dump({"_span": [closes[0][0], closes[-1][0]],
                   "_bars": len(closes),
                   "_note": "b190: broker M5 (time, close) pairs, get_rates "
                            "only; the b187 trigger reads closes, nothing else",
                   "closes": closes}, fh)
    return [{"time": t, "close": c} for t, c in closes]


def coverage(m5_stream: list[dict], m5_times: list[int],
             leg_rows: list[dict], spacing: int) -> float:
    """Share of leg bars whose decision moment holds >= MIN_TRIG_ROWS settled
    M5 closes — computed through the SAME m5_window_for the funnel slices with,
    so coverage cannot disagree with what the arm actually saw."""
    hit = 0
    for r in leg_rows:
        t = r.get("time")
        if not isinstance(t, (int, float)):
            continue
        if len(m5_window_for(m5_stream, m5_times, int(t) + spacing)) >= MIN_TRIG_ROWS:
            hit += 1
    return round(hit / len(leg_rows), 4) if leg_rows else 0.0


def _arm(leg: dict, entry_key: str, timeframe: str, m5_stream,
         rows_label: str) -> dict:
    rows = leg[entry_key]
    kw, ts = _harness_kwargs(rows)
    from engines.backtest_real import run_backtest
    run = run_backtest(None, symbol="XAUUSD", timeframe=timeframe,
                       data={timeframe: rows, "H1": leg["H1"], "H4": leg["H4"]},
                       m5_stream=m5_stream, **kw)
    if not run.get("ok"):
        return {"error": run.get("error")}
    stats = lh.r_stats(run, time_stop_bars=ts)
    stats["_bars"] = len(rows)
    stats["_time_stop_bars"] = ts
    return stats


def measure_leg(name: str, leg: dict, entry_key: str, timeframe: str,
                m5_stream: list[dict]) -> dict:
    m5_times = [int(r["time"]) for r in m5_stream]
    rows = leg[entry_key]
    spacing = lh.bar_seconds(rows)
    out = {"_entry_bars": len(rows),
           "_m5_source_bars": len(m5_stream),
           "_m5_coverage": coverage(m5_stream, m5_times, rows, spacing),
           "control_no_trigger": _arm(leg, entry_key, timeframe, [],
                                      "control"),
           "wired_real_m5": _arm(leg, entry_key, timeframe, m5_stream,
                                 "wired")}
    c, w = out["control_no_trigger"], out["wired_real_m5"]
    if "exp_R" in c and "exp_R" in w:
        out["d_exp_R"] = round(w["exp_R"] - c["exp_R"], 3)
        out["d_trades"] = w["trades"] - c["trades"]
    return out


def bar(led: dict) -> dict:
    """THE MACHINE-READABLE NEW BAR: wired exp_R per leg, but ONLY for legs
    whose M5 coverage proves the trigger could actually fire (>=0.9). A leg
    below the floor is quoted None with a reason — never a fake 'wired'
    number that is really the control (b116's class)."""
    out = {}
    for leg in led["_legs"]:
        L = led[leg]
        if L["_m5_coverage"] < COVERAGE_FLOOR:
            out[leg] = None
        else:
            out[leg] = L["wired_real_m5"]["exp_R"]
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


def main() -> int:
    m5_stream = fetch_m5_closes()
    wins = wl.load_windows()
    cached = json.load(open(CACHED_LEG))
    legs = {"cached": {"M15": cached["M15"], "H1": cached["H1"],
                       "H4": cached["H4"]}}
    for w in ("W1", "W2", "W3", "W4"):
        legs[w] = wins[w]

    led = {"_note": "b190: the merit bar re-baselined under the b189-wired "
                    "funnel — every arm is engines.backtest_real.run_backtest "
                    "with the live exit geometry derived from lab_harness; "
                    "control = m5_stream=[] (the pre-wiring bar), wired = "
                    "broker M5 closes at each decision moment.",
           "_legs": list(LEGS),
           "_m5_source": {"file": M5_CACHES, "bars": len(m5_stream),
                          "first": m5_stream[0]["time"],
                          "last": m5_stream[-1]["time"]},
           "_gates": {"min_rr": lh.MIN_RR, "live_min_rr": lh.LIVE_MIN_RR,
                      "min_grade": lh.LIVE_MIN_GRADE, "spread": lh.SPREAD,
                      "trail_mult": lh.LIVE_TRAIL_MULT,
                      "trail_floor": lh.LIVE_TRAIL_FLOOR}}
    for name in LEGS:
        print(f"##### {name} #####", flush=True)
        led[name] = measure_leg(name, legs[name], "M15", "M15", m5_stream)
        c, w = led[name]["control_no_trigger"], led[name]["wired_real_m5"]
        print(f"  cov={led[name]['_m5_coverage']} control={c.get('trades')}"
              f"/{c.get('exp_R')} wired={w.get('trades')}/{w.get('exp_R')}",
              flush=True)

    led["_merit_bar_live_wired"] = bar(led)
    led["_trigger_delta"] = trigger_delta(led)

    # Cross-integrity: the cached leg must reproduce BOTH stored anchors —
    # b118's re-quoted control 102/0.254 and b189's wired 104/0.280.
    b189 = json.load(open(B189_LEDGER))
    led["_cross_check_b189"] = {
        "b189_arm_A": {k: b189["A_m15_no_trigger_rows"][k]
                       for k in ("trades", "exp_R")},
        "b189_arm_B": {k: b189["B_m15_real_m5_closes"][k]
                       for k in ("trades", "exp_R")},
        "b190_control": {k: led["cached"]["control_no_trigger"][k]
                         for k in ("trades", "exp_R")},
        "b190_wired": {k: led["cached"]["wired_real_m5"][k]
                       for k in ("trades", "exp_R")},
    }
    # b182's older cache ends 2026-09-09 07:05; b190's own fetch is strictly
    # newer, so wired may differ from b189's arm B on late bars — the check
    # reports the numbers, it does not force equality (documented in ledger).

    with open(OUT, "w") as fh:
        json.dump(led, fh, indent=1)
    print("\nmerit bar (wired, coverage>=0.9 only):",
          json.dumps(led["_merit_bar_live_wired"]))
    print("trigger delta:", json.dumps(led["_trigger_delta"]))
    print("cross-check vs b189:", json.dumps(led["_cross_check_b189"]))
    print("saved:", os.path.abspath(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
