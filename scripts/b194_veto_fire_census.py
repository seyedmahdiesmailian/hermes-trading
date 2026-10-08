#!/usr/bin/env python3
"""b194 — IS THE b193 VETO SEAM ALIVE IN THE LAB? A FIRE CENSUS, run_backtest only.

WHY THIS EXISTS (filed by b193's landing, 2026-09-09)
=====================================================
b194's re-price of the merit bar under the veto-fixed funnel came back
BYTE-IDENTICAL to b190/b191 (cached 102/0.254 control, 104/0.280 wired; the
M5W band 0.142-0.328 unchanged). An identical ledger has two possible causes:
the veto genuinely changes no trades, or the veto is NOT BEING REACHED in the
lab at all (the b189/b193 parity-drift class, resurrected). This census
separates them the only honest way: instrument the seam and COUNT it firing
while the sanctioned funnel replays the same legs.

METHOD (HARD RULE: engines.backtest_real.run_backtest, never a hand-copied
funnel): wrap `apply_smc_merge` in the `engines.backtest_real` namespace with
a transparent counting proxy (it calls through to the real seam unchanged),
run each leg through run_backtest with lab_harness live geometry, and record:
  calls      - merge invocations that reached the seam
  directional_in  - contexts where ctx['bias'] was bullish/bearish at entry
  vetoes     - calls that returned True (bias forced neutral, stale-at-birth)
  trades     - run_backtest's trade count for that arm
If vetoes > 0 AND trades equals the stored b190/b191 control row, the seam is
PROVEN alive on these legs and the byte-identity is a real measurement, not a
missing wire. If vetoes == 0, b194 becomes a defect report, not a re-quote.

Legs: the cached M15 3000-bar leg and M5W1 (the freshest independent M5-entry
window) — one per entry-TF family, both arms of each (control m5_stream=[] and
wired, so a veto that only bites the wired lane cannot hide).
Read-only research: nothing here is imported by the live trading path; no
gate, threshold, lot or verdict is touched; no bridge call at all (the M5
closes and OHLC come from b190/b191's frozen caches).
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
load_dotenv(os.path.join(_ROOT, ".env"))      # b65: consumer owns env

from engines import lab_harness as lh                          # noqa: E402
import engines.backtest_real as br                             # noqa: E402
from scripts import b190_merit_bar_live_trigger as p190        # noqa: E402
from scripts import b191_m5_window_lab as p191                 # noqa: E402

OUT = "data/backtest/b194_veto_fire_census.json"
B190_LEDGER = p190.OUT
B191_LEDGER = p191.OUT


def run_leg_with_counter(rows: list[dict], timeframe: str, ctx: dict,
                         m5_stream) -> dict:
    """One funnel leg through run_backtest with the seam wrapped by a
    counting proxy. The proxy delegates to the REAL apply_smc_merge —
    it changes nothing, it only watches."""
    real = br.apply_smc_merge
    seen = {"calls": 0, "directional_in": 0, "vetoes": 0,
            "vetoes_by_bias": {}}

    def proxy(ctx_arg, merged, **kw):
        seen["calls"] += 1
        bias_in = ctx_arg.get("bias")
        if bias_in in ("bullish", "bearish"):
            seen["directional_in"] += 1
        fired = real(ctx_arg, merged, **kw)
        if fired:
            seen["vetoes"] += 1
            k = str(bias_in)
            seen["vetoes_by_bias"][k] = seen["vetoes_by_bias"].get(k, 0) + 1
        return fired

    br.apply_smc_merge = proxy
    try:
        kw, ts = p190._harness_kwargs(rows)
        run = br.run_backtest(None, symbol="XAUUSD", timeframe=timeframe,
                              data={timeframe: rows, "H1": ctx["H1"],
                                    "H4": ctx["H4"]},
                              m5_stream=m5_stream, **kw)
    finally:
        br.apply_smc_merge = real
    if not run.get("ok"):
        return {"error": run.get("error")}
    stats = lh.r_stats(run, time_stop_bars=ts)
    return {"calls": seen["calls"],
            "directional_in": seen["directional_in"],
            "vetoes": seen["vetoes"],
            "vetoes_by_bias": seen["vetoes_by_bias"],
            "trades": stats["trades"],
            "exp_R": stats["exp_R"]}


def compare_to_stored(census: dict, led190: dict, led191: dict) -> dict:
    """Pure arithmetic (b127 re-runnable): does each censused arm's trade
    count and exp_R equal the stored b190/b191 row for the same leg+arm, and
    did the seam fire? verdict says which of the two byte-identity causes
    holds: ALIVE_AND_INERT (vetoes>0, rows match), DEAD_WIRE (vetoes==0),
    or DRIFT (rows do not match the re-priced ledger)."""
    stored = {"cached": led190, "M5W1": led191}
    key_by_arm = {"control": ("control_no_trigger",),
                  "wired": ("wired_real_m5", "wired_own_m5_closes")}
    out = {}
    all_match = True
    total_vetoes = 0
    for name, arm in census["_arms"]:
        ledger = stored[name]
        leg = ledger[name]          # the leg ROW inside its ledger, not the file
        row = None
        for k in key_by_arm[arm]:
            if k in leg:
                row = leg[k]
                break
        c = census[arm + "_" + name]
        match = (row is not None and c["trades"] == row["trades"]
                 and c["exp_R"] == row["exp_R"])
        all_match = all_match and match
        total_vetoes += c["vetoes"]
        out[f"{arm}_{name}"] = {"vetoes": c["vetoes"],
                                "row_matches_stored": match}
    verdict = ("ALIVE_AND_INERT" if total_vetoes > 0 and all_match else
               "DEAD_WIRE" if total_vetoes == 0 else "DRIFT")
    out["_verdict"] = verdict
    out["_total_vetoes"] = total_vetoes
    return out


def main() -> int:
    m5_closes = p190.fetch_m5_closes()
    cached = json.load(open(p190.CACHED_LEG))
    m5 = p191.fetch_m5_ohlc()
    wins = p191.build_windows(m5)
    # b191's OWN context fetch (read-only get_rates): the M5W legs are cut
    # from the 60000-bar M5 history, so the H1/H4 streams must come from the
    # same reach the lab used, not b68l's M15 window contexts.
    ctx_full = p191.fetch_context()

    census = {"_note": "b194: fire census on the b193 seam (apply_smc_merge "
                       "wrapped by a pass-through counter) over one M15 and "
                       "one M5-entry leg, both arms, run_backtest only — the "
                       "non-vacuity proof behind the byte-identical re-price.",
              "_arms": []}

    legs = [("cached", cached["M15"], "M15",
             {"H1": cached["H1"], "H4": cached["H4"]}),
            ("M5W1", wins["M5W1"], "M5", None)]
    for name, rows, tf, ctx in legs:
        if ctx is None:
            lo, hi = int(rows[0]["time"]), int(rows[-1]["time"])
            ctx = p191._context_for(ctx_full, lo, hi)
        for arm, stream in (("control", []), ("wired", m5_closes)):
            if tf == "M5" and arm == "wired":
                stream = None       # b191's wired = the stream's own closes
            print(f"##### {name} / {arm} #####", flush=True)
            res = run_leg_with_counter(rows, tf, ctx, stream)
            print("  ", json.dumps(res), flush=True)
            census[arm + "_" + name] = res
            census["_arms"].append([name, arm])

    led190 = json.load(open(B190_LEDGER))
    led191 = json.load(open(B191_LEDGER))
    census["_compare"] = compare_to_stored(census, led190, led191)
    with open(OUT, "w") as fh:
        json.dump(census, fh, indent=1)
    print("\nverdict:", json.dumps(census["_compare"]))
    print("saved:", os.path.abspath(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
