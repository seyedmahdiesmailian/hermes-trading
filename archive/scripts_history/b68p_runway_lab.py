#!/usr/bin/env python3
"""b68 STRATEGY LAB ROUND 16 — PDH/PDL breakout GATED on weekly RUNWAY.

Standing loop (b68): after 15 rounds every classic FAMILY is screened; the
round-14 note says a new round must justify itself. This round's candidate
is the fourth combination pairing (rounds 7/8/9/10 covered day-path,
compression and reversed pairings) and the FIRST whose oracle is a WEEK-level
STATE. Justification, rule by rule:

- b73 (sequencing): the gate is a slow level-STATE, not a compression state —
  round 8 died because the squeeze's information was spent by breakout time;
  a weekly extreme cannot be "spent" the same way;
- b75 (geometry freshness): the geometry supplier is pdh_break (round 4's
  arm, the only one ever replicated 2-of-2 on clean windows) — its signal
  bar IS the trigger; the weekly level is pure background state with ZERO
  lag (the level is fixed at the week's first bar), so the fresh member
  carries the stop, as the rule demands;
- b78 (direction-mix disclosure): the round ships the BUY/SELL split of
  every arm's trades on every leg, and the verdict quotes it — this is the
  first round run under that rule from the start;
- novelty: round 15 measured the weekly level as GEOMETRY (break the week);
  nobody has measured it as an ORACLE (is there room left in the week for
  this day-break to run?).

Definition (pure intersection, pdh geometry UNCHANGED): a pdh_break signal
at bar i has RUNWAY when the entry sits >= room*ATR(14) BELOW the previous
trading week's high (BUY) or >= room*ATR ABOVE its low (SELL) — room 1.0
(primary) and 2.0 (sensitivity). The complement arm (no_runway) is what the
gate DROPS: per b74/b76 the agree-vs-cut ordering is the selection check,
and per b78 its direction mix is quoted too.

Measured through the b71 harness (plain/ladder/ladder_ts, derived time
exit, hold columns, zero_reason). scripts/b68p_confirm_runway.py runs the
full cached + W1..W4 grid with the b74 all-windows rule, the b77 decay
pre-flight, the lane arms (b70) and the stretch/lag probes (b72/b73/b75).

Read-only research code: nothing here is imported by the live trading path.
"""
import os
import sys
import json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from engines import lab_harness as lh          # noqa: E402  (b71 harness)
from scripts import b68e_pdh_lab as pl         # noqa: E402  (pdh geometry)
from scripts import b68o_weekly_lab as wk      # noqa: E402  (weekly levels)

CACHED_PATH = os.path.join(_ROOT, "data/backtest/ab_aggressive_data.json")
STOP_ATR = 1.0                    # round 4's survivor width — UNCHANGED
ROOM, ROOM2 = 1.0, 2.0            # primary + sensitivity thresholds


def bind(rows):
    """Point BOTH ingredient modules at one dataset (levels rebuilt, never
    stale — the b76 contamination class lives in stale level tables)."""
    pl.M15 = rows
    pl.IDX = {r["time"]: n for n, r in enumerate(rows)}
    pl.LEVELS = pl.prev_day_levels()
    wk.rebind(rows)
    return pl.LEVELS, wk.LEVELS


def runway_at(rows, i, room=ROOM, stop_atr=STOP_ATR):
    """True/False: does the pdh signal at bar i have >= room*ATR of space to
    the previous trading week's extreme IN TRADE DIRECTION? None when the
    signal or the weekly level does not exist. Pure function of (rows, i) —
    both modules' tables must be bound to `rows` via bind()."""
    s = pl.pdh_break(i, stop_atr)
    if not s:
        return None
    wk_key = wk.trading_week(rows[i - 1]["time"])
    if wk_key not in wk.LEVELS:
        return None
    pwh, pwl = wk.LEVELS[wk_key]
    a = wk.atr_of(rows, i - 1)
    if not a:
        return None
    e = float(s["entry"])
    return ((pwh - e) / a >= room) if s["side"] == "BUY" else ((e - pwl) / a >= room)


def gated(i, want, room=ROOM):
    """The combo arm: pdh geometry, weekly-runway oracle, PURE intersection."""
    s = pl.pdh_break(i, STOP_ATR)
    if not s:
        return None
    return s if runway_at(pl.M15, i, room) == want else None


def complement(i, room=ROOM):
    """What the gate DROPS (b74's selection-ordering arm)."""
    return gated(i, False, room)


def indexed(fn):
    def w(row):
        i = pl.IDX.get(row.get("time"))
        return None if i is None else fn(i)
    return w


ARMS = [("pdh_w10_control", lambda i: pl.pdh_break(i, STOP_ATR)),
        ("pdh_runway", lambda i: gated(i, True, ROOM)),
        ("pdh_no_runway", lambda i: complement(i, ROOM)),
        ("pdh_runway_r20", lambda i: gated(i, True, ROOM2)),
        ("pdh_no_runway_r20", lambda i: complement(i, ROOM2))]


def runway_probe(rows=None, room=ROOM):
    """b72 anti-vacuity + b78 direction mix for the gate: how many pdh
    signals the leg emits, how many have no weekly level, and the BUY/SELL
    split of runway vs no_runway vs the dropped set. A gate whose split is
    ~100/0 in either arm is the same arm twice, not a combo."""
    rows = pl.M15 if rows is None else rows
    saved = None
    if rows is not pl.M15:
        saved = (pl.M15, pl.IDX, pl.LEVELS, wk.M15, wk.IDX, wk.LEVELS)
        bind(rows)
    counts = {"pdh_signals": 0, "no_week_level": 0,
              "runway": {"BUY": 0, "SELL": 0},
              "no_runway": {"BUY": 0, "SELL": 0},
              "room_atr": []}
    for i in range(30, len(rows)):
        s = pl.pdh_break(i, STOP_ATR)
        if not s:
            continue
        counts["pdh_signals"] += 1
        st = runway_at(rows, i, room)
        if st is None:
            counts["no_week_level"] += 1
            continue
        counts["runway" if st else "no_runway"][s["side"]] += 1
        wk_key = wk.trading_week(rows[i - 1]["time"])
        pwh, pwl = wk.LEVELS[wk_key]
        a = wk.atr_of(rows, i - 1)
        e = float(s["entry"])
        counts["room_atr"].append(round(
            ((pwh - e) / a) if s["side"] == "BUY" else ((e - pwl) / a), 2))
    if saved:
        pl.M15, pl.IDX, pl.LEVELS, wk.M15, wk.IDX, wk.LEVELS = saved
    rs = sorted(counts["room_atr"])
    n = len(rs)
    return {"bars": len(rows), "pdh_signals": counts["pdh_signals"],
            "no_week_level": counts["no_week_level"],
            "runway_buy": counts["runway"]["BUY"],
            "runway_sell": counts["runway"]["SELL"],
            "no_runway_buy": counts["no_runway"]["BUY"],
            "no_runway_sell": counts["no_runway"]["SELL"],
            "room_min": rs[0] if n else None,
            "room_median": rs[n // 2] if n else None,
            "room_max": rs[-1] if n else None}


def main():
    rows = json.load(open(CACHED_PATH))["M15"]
    bind(rows)
    print(f"cached leg: {len(rows)} M15 bars, {len(wk.LEVELS)} weeks with a level")
    print("runway_probe:", json.dumps(runway_probe(rows)))
    ledger = {}
    for name, fn in ARMS:
        ledger[name] = lh.run_arm(rows, indexed(fn))
        lh.print_table(ledger, [name], label=f"{name} (cached, b71)")
        print(flush=True)
    complaints = lh.summarize(ledger, [n for n, _ in ARMS])
    print("=== honesty ===")
    for c in complaints or ["no complaints"]:
        print("!", c)
    out = {"_note": "round 16 cached leg: PDH/PDL breakout gated on weekly "
                    "runway (room to the previous trading week's extreme in "
                    "trade direction), b71 harness, b72 anti-vacuity + b78 "
                    "direction mix probe",
           "_time_stop_bars": lh.live_time_stop_bars(rows),
           "_probe": runway_probe(rows),
           "_honesty_complaints": complaints,
           **ledger}
    p = os.path.join(_ROOT, "data", "backtest", "b68p_runway_lab.json")
    json.dump(out, open(p, "w"), indent=1)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
