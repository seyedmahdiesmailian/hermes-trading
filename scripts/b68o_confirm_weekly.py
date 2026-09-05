#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 15 — the FULL five-leg measurement for the
previous-trading-week breakout arms (cached + W1..W4), with the b77
chronological-decay pre-flight folded in as step (0) of b74's protocol.

Round 14 closed the loop's screening era: after 14 rounds NO lab arm has
ever cleared all four independent windows, and the round-14 note says
future rounds must justify themselves against b77's decay rule before
burning a draw. This round's candidate is the one LEVEL family never
measured — the previous TRADING WEEK's high/low (PWH/PWL), the
higher-timeframe analogue of the loop's only twice-replicated arm
(pdh_break_w10, W1+W2) — so the round is justified on novelty, and the
b77 pre-flight runs on the margin series the round itself ships.

Legs (b76 discipline: every leg records its own span and the overlap with
the cached set; W1..W4 are the four independent windows b74 spent in
rounds 11-14, zero overlap asserted in the windows ledger):
  cached — 3000 M15 bars, IN-SAMPLE, informational only (round-11 wording);
  W1..W4 — 6000 bars each, the funnel re-measured on the SAME bars as the
           arms (continuity: the funnel rows must reproduce the shipped
           b68n/b68n4 ledgers exactly — same bars, same harness, drift is
           a bug, pinned by tests/test_b68o_weekly_lab.py).

Decision rules shipped with the ledger:
  b74 all-windows: an arm is REPLICATED only if its ladder_ts exp_R beats
      the funnel's on the SAME bars in EVERY independent window (None and
      ties never beat);
  b77 pre-flight: margins sorted by TIME (never by label — labels are
      newest-first); REGIME_GIFTED (monotone increasing, slope >= 0.02R)
      closes the candidate without further draws;
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

from engines import lab_harness as lh              # noqa: E402
from engines import lab_decay as ld                # noqa: E402  (b77)
from engines import lab_fire_rate as lf            # noqa: E402  (b79)
from engines.backtest_real import strategy_signal  # noqa: E402
from scripts import b68l_windows as wl             # noqa: E402
from scripts import b68o_weekly_lab as wk          # noqa: E402

OUT = os.path.join(_ROOT, "data", "backtest", "b68o_weekly_confirm.json")
WINDOWS = ("W1", "W2", "W3", "W4")
LEGS = ("cached",) + WINDOWS
ARMS = ("CURRENT_FUNNEL", "pwh_break_t50", "pwh_break_w10")

# round-14 shipped ledger: the funnel rows on W1..W4 must match it exactly
CONTINUITY = os.path.join(_ROOT, "data", "backtest", "b68n4_fourth_draw.json")


def funnel_signals(m15, h1, h4):
    """The live funnel replayed bar-by-bar on one dataset — the exact
    convention b68n's measure_window uses (only fully-closed HTF context
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


def measure_leg(name, m15, h1, h4):
    """One leg: funnel + both weekly arms through the b71 harness, plus the
    b72 anti-vacuity probe and the zero-overlap fact (b76)."""
    wk.rebind(m15)
    funnel, _sigs, _idx = funnel_signals(m15, h1, h4)

    def wrap(fn):
        def w(row):
            i = wk.IDX.get(row.get("time"))
            return None if i is None else fn(i)
        return w

    arms = [("CURRENT_FUNNEL", funnel),
            ("pwh_break_t50", wrap(lambda i: wk.pwh_break(i, 0.5))),
            ("pwh_break_w10", wrap(lambda i: wk.pwh_break(i, 1.0)))]
    c0, c1 = wl.cached_span()
    out = {"_time_stop_bars": lh.live_time_stop_bars(m15),
           "_bars": len(m15),
           "_first": int(m15[0]["time"]), "_last": int(m15[-1]["time"]),
           "_overlap_with_cached": sum(
               1 for r in m15 if c0 <= int(r["time"]) <= c1),
           "_probe": wk.level_probe(m15)}
    for arm_name, fn in arms:
        out[arm_name] = lh.run_arm(m15, fn)
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
    never beat. The cached leg is reported but never counts."""
    v = {}
    for w in windows:
        win = led[w]
        f = win["CURRENT_FUNNEL"]["ladder_ts"]
        v[w] = {"funnel_exp_R": f["exp_R"], "funnel_n": f["trades"]}
        for arm in ARMS[1:]:
            row = win[arm]["ladder_ts"]
            v[w][arm] = {"exp_R": row["exp_R"], "n": row["trades"],
                         "dd_R": row.get("maxDD_R"),
                         "beats_funnel": (row["exp_R"] is not None
                                          and row["exp_R"] > f["exp_R"])}
    v["replicated_in_all"] = {
        arm: all(bool(v[w][arm]["beats_funnel"]) for w in windows)
        for arm in ARMS[1:]}
    return v


def main():
    wins = wl.load_windows()
    c = json.load(open(wk.CACHED_PATH))
    led = {"_note": "round 15: PWH/PWL weekly-level breakout measured on "
                    "cached + W1..W4 (b74 all-windows rule + b77 decay "
                    "pre-flight as step 0); funnel re-measured on the SAME "
                    "bars per leg (b76)",
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
        led, [a for a in ARMS if a != "CURRENT_FUNNEL"], list(WINDOWS), meta)
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
