#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 16 — FULL five-leg measurement of the weekly-
RUNWAY-gated PDH breakout (cached + W1..W4), with the b77 decay pre-flight
as step (0) of b74's protocol and the b78 direction-mix disclosure on every
arm.

Legs (b76 discipline: every leg records its own span and the overlap with
the cached set; W1..W4 are the four independent windows b74 spent in
rounds 11-14, zero overlap asserted in the windows ledger):
  cached — 3000 M15 bars, IN-SAMPLE, informational only (round-11 wording);
  W1..W4 — 6000 bars each, the funnel re-measured on the SAME bars as the
           arms (continuity: the funnel rows must reproduce the shipped
           b68n4 ledger exactly — same bars, same harness, drift is a bug,
           pinned by tests/test_b68p_runway_lab.py).

Arms per leg: CURRENT_FUNNEL (live replay), pdh_w10_control (round 4, the
ungated ingredient — b72 rule 3), pdh_runway / pdh_no_runway (the gated
arm and what the gate DROPS — b74's selection-ordering check), the r20
sensitivity pair, and lane_funnel_then_runway (b70 capacity: funnel first,
gated arm only on free bars).

Every arm row carries its BUY/SELL trade mix (b78): a single-window exp_R
for a level-breakout arm is really the number for whichever way that regime
broke, so the mix ships in the ledger and the verdict quotes it.

Decision rules shipped with the ledger:
  b74 all-windows: an arm is REPLICATED only if its ladder_ts exp_R beats
      the funnel's on the SAME bars in EVERY independent window (None and
      ties never beat);
  b77 pre-flight: margins sorted by TIME (never by label — labels are
      newest-first); REGIME_GIFTED (monotone increasing, slope >= 0.02R)
      closes the candidate without further draws;
  selection ordering (rounds 9-14 killer check): runway > no_runway on the
      same bars, in every window counted;
  promotion additionally requires the lane/capacity + live-gate-stack +
      kill-switch math (b70/b74) — wiring stays a human decision.

Read-only research code: nothing here is imported by the live trading path.
"""
import os
import sys
import json
import bisect

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from engines import lab_harness as lh              # noqa: E402  (b71 harness)
from engines import lab_decay as ld                # noqa: E402  (b77)
from engines import lab_fire_rate as lf            # noqa: E402  (b79)
from engines.backtest import backtest_ohlc         # noqa: E402  (mix probe)
from engines.backtest_real import strategy_signal  # noqa: E402
from scripts import b68l_windows as wl             # noqa: E402
from scripts import b68p_runway_lab as rp          # noqa: E402
from scripts import b68e_pdh_lab as pl             # noqa: E402
from scripts import b68o_weekly_lab as wk          # noqa: E402

OUT = os.path.join(_ROOT, "data", "backtest", "b68p_runway_confirm.json")
WINDOWS = ("W1", "W2", "W3", "W4")
LEGS = ("cached",) + WINDOWS
GATED_ARMS = ("pdh_runway", "pdh_no_runway", "pdh_runway_r20",
              "pdh_no_runway_r20")
ARMS = ("CURRENT_FUNNEL", "pdh_w10_control") + GATED_ARMS + \
       ("lane_funnel_then_runway",)

# round-14 shipped ledger: the funnel rows on W1..W4 must match it exactly
CONTINUITY = os.path.join(_ROOT, "data", "backtest", "b68n4_fourth_draw.json")


def funnel_signals(m15, h1, h4):
    """The live funnel replayed bar-by-bar on one dataset — the exact
    convention b68n/b68o's measure_leg uses (only fully-closed HTF context
    bars, 80-bar H1/H4 windows, 120-bar M15 window)."""
    h1t = [r.get("time", 0) for r in h1]
    h4t = [r.get("time", 0) for r in h4]
    idx_of = {r["time"]: n for n, r in enumerate(m15)}
    sigs = {}
    for i, row in enumerate(m15):
        bt = row.get("time", 0)
        j1 = bisect.bisect_right(h1t, bt)
        j4 = bisect.bisect_right(h4t, bt)
        hw = h1[max(0, j1 - 80):j1]
        h4w = h4[max(0, j4 - 80):j4]
        mw = m15[max(0, i - 120):i + 1]
        s = strategy_signal(row, hw, h4w, i, m15_window=mw)
        if s:
            sigs[i] = s

    def funnel(row):
        return sigs.get(idx_of.get(row.get("time"), -1))
    return funnel, sigs, idx_of


def side_mix(rows, fn):
    """b78: BUY/SELL split of the TRADES an arm actually takes under the
    live exit ladder + time exit (not of raw signals — slot occupancy can
    change the mix)."""
    ts = lh.live_time_stop_bars(rows)
    res = backtest_ohlc(rows, fn, min_rr=lh.MIN_RR, spread=lh.SPREAD,
                        **dict(lh.LADDER, time_stop_bars=ts))
    buy = sum(1 for t in res.get("trade_log", []) if t["side"] == "BUY")
    sell = sum(1 for t in res.get("trade_log", []) if t["side"] == "SELL")
    return {"trades": buy + sell, "buy": buy, "sell": sell}


def stretch_probe(rows):
    """b73 standard probe: mean |entry - broken PD level| / ATR, control vs
    gated — distinguishes an INFORMATIONAL lift from a geometric one (and
    round 8's chase tax)."""
    out = {}
    for label, want in (("control", None), ("gated", True)):
        vals = []
        for i in range(30, len(rows)):
            s = pl.pdh_break(i, rp.STOP_ATR)
            if not s:
                continue
            if want is not None and rp.runway_at(rows, i, rp.ROOM) is not True:
                continue
            a = pl.atr(i - 1)
            day = pl.trading_day(rows[i - 1]["time"])
            if not a or day not in pl.LEVELS:
                continue
            ph, pwl = pl.LEVELS[day]
            e = float(s["entry"])
            vals.append(abs(e - (ph if s["side"] == "BUY" else pwl)) / a)
        vals.sort()
        n = len(vals)
        out[label] = {"n": n,
                      "mean_stretch_atr": round(sum(vals) / n, 3) if n else None,
                      "median_stretch_atr": vals[n // 2] if n else None}
    return out


def measure_leg(name, m15, h1, h4):
    """One leg: funnel + the whole round-16 arm set through the b71 harness,
    plus the b72 anti-vacuity probe, the b78 mix per arm, the stretch probe
    and the zero-overlap fact (b76)."""
    rp.bind(m15)
    funnel, _sigs, _idx = funnel_signals(m15, h1, h4)
    wrap = rp.indexed

    def lane(row):
        return funnel(row) or wrap(lambda i: rp.gated(i, True, rp.ROOM))(row)

    arms = [("CURRENT_FUNNEL", funnel),
            ("pdh_w10_control", wrap(lambda i: pl.pdh_break(i, rp.STOP_ATR))),
            ("pdh_runway", wrap(lambda i: rp.gated(i, True, rp.ROOM))),
            ("pdh_no_runway", wrap(lambda i: rp.complement(i, rp.ROOM))),
            ("pdh_runway_r20", wrap(lambda i: rp.gated(i, True, rp.ROOM2))),
            ("pdh_no_runway_r20", wrap(lambda i: rp.complement(i, rp.ROOM2))),
            ("lane_funnel_then_runway", lane)]
    c0, c1 = wl.cached_span()
    out = {"_time_stop_bars": lh.live_time_stop_bars(m15),
           "_bars": len(m15),
           "_first": int(m15[0]["time"]), "_last": int(m15[-1]["time"]),
           "_overlap_with_cached": sum(
               1 for r in m15 if c0 <= int(r["time"]) <= c1),
           "_probe": rp.runway_probe(m15),
           "_stretch_probe": stretch_probe(m15)}
    for arm_name, fn in arms:
        out[arm_name] = lh.run_arm(m15, fn)
        out[arm_name]["_mix"] = side_mix(m15, fn)
        lh.print_table(out, [arm_name], label=f"{arm_name} ({name}, b71)")
        print(flush=True)
    out["_honesty_complaints"] = lh.summarize(out, [a for a, _ in arms])
    print(f"=== {name} honesty ===")
    for c in out["_honesty_complaints"] or ["no complaints"]:
        print("!", c)
    return out


def verdict(led, windows=WINDOWS):
    """b74 replication rule, all-windows edition: beats the funnel's
    ladder_ts on the SAME bars in EVERY independent window; None and ties
    never beat. The cached leg is reported but never counts. b78: every
    cell carries the arm's BUY/SELL mix. Selection ordering (runway vs the
    dropped no_runway) is counted per window."""
    v = {}
    for w in windows + ("cached",):
        win = led[w]
        f = win["CURRENT_FUNNEL"]["ladder_ts"]
        v[w] = {"funnel_exp_R": f["exp_R"], "funnel_n": f["trades"]}
        for arm in ARMS[1:]:
            row = win[arm]["ladder_ts"]
            mix = win[arm]["_mix"]
            v[w][arm] = {"exp_R": row["exp_R"], "n": row["trades"],
                         "dd_R": row.get("maxDD_R"),
                         "buy": mix["buy"], "sell": mix["sell"],
                         "beats_funnel": (row["exp_R"] is not None
                                          and row["exp_R"] > f["exp_R"])}
    v["replicated_in_all"] = {
        arm: all(bool(v[w][arm]["beats_funnel"]) for w in windows)
        for arm in ("pdh_runway", "pdh_runway_r20")}
    v["selection_ordering"] = {}
    for room, agree, cut in (("r10", "pdh_runway", "pdh_no_runway"),
                             ("r20", "pdh_runway_r20", "pdh_no_runway_r20")):
        wins_ok = sum(1 for w in windows
                      if v[w][agree]["exp_R"] is not None
                      and v[w][cut]["exp_R"] is not None
                      and v[w][agree]["exp_R"] > v[w][cut]["exp_R"])
        v["selection_ordering"][room] = {
            "agree_gt_cut_windows": wins_ok, "of": len(windows)}
    return v


def main():
    wins = wl.load_windows()
    c = json.load(open(wk.CACHED_PATH))
    led = {"_note": "round 16: PDH breakout x weekly-runway gate measured on "
                    "cached + W1..W4 (b74 all-windows rule + b77 decay "
                    "pre-flight as step 0 + b78 direction mix per arm); "
                    "funnel re-measured on the SAME bars per leg (b76)",
           "_last6000_overlap_with_cached": wins.get(
               "_last6000_overlap_with_cached")}
    print("##### cached (in-sample, informational) #####", flush=True)
    led["cached"] = measure_leg("cached", c["M15"], c["H1"], c["H4"])
    for w in WINDOWS:
        print(f"##### {w} #####", flush=True)
        led[w] = measure_leg(w, wins[w]["M15"], wins[w]["H1"], wins[w]["H4"])
    led["_verdict"] = verdict(led)
    meta = {w: {"last": led[w]["_last"]} for w in WINDOWS}
    led["_b77_preflight"] = ld.preflight(
        led, ["pdh_runway", "pdh_runway_r20", "pdh_no_runway"],
        list(WINDOWS), meta)
    led["_b79_preflight"] = lf.preflight(led, list(WINDOWS))
    print("=== VERDICT ===")
    print(json.dumps(led["_verdict"], indent=1))
    print("=== b77 PRE-FLIGHT ===")
    print(json.dumps(led["_b77_preflight"], indent=1))
    print("=== b79 FIRE-RATE PRE-FLIGHT ===")
    print(json.dumps(led["_b79_preflight"], indent=1))
    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
