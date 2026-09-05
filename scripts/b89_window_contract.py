#!/usr/bin/env python3
"""b89 — DEFCON WINDOW: DEALS vs TRADES. Option (b): make the CODE and the
DOCUMENTATION say the same thing, and pin the window's exit count so the two
can never drift apart again.

The question b88 left to a human (todo b89) was which of two contracts is real:
  (a) change the slice to closing deals only, so `recent_closed` holds 10 CLOSED
      TRADES as the docstring claimed, or
  (b) keep the deal-level slice and document what it actually means.
(a) is a GLOBAL TIGHTENING of the only feedback-loop gate (b88 measured W1
moving from GREEN 90 / YELLOW 72 to GREEN 11 / YELLOW 148), i.e. a gate change,
which the autopilot hard rule puts out of scope. This round therefore executes
(b) — zero behaviour change — and does the part of the item that is NOT a gate
change: "add a test pinning the window's exit count so the two cannot drift".

What this round MEASURED first (numbers in data/backtest/b89_window_contract.json,
all produced by the live engines.risk + engines.defcon code, never restated):

  1. THE WINDOW IS 10 DEALS AND HOLDS 5 EXITS. compute_performance_state slices
     `[-10:]` off the raw MT5 history-deals feed, which carries one opening deal
     (entry=0, profit 0.0, comment 'Hermes') per position as well as the closing
     deals. A one-position-at-a-time book alternates open/close, so a full window
     is 5 opens + 5 closes. Verified on the real producer, not by reading it.

  2. THAT MOVES THE MEANING OF EVERY COUNT IN engines/defcon.py. `total` is the
     number of DEALS, and `sl_ratio = n_sl / total` has the opening deals in its
     DENOMINATOR. So in a full window:
        RED  (total>=5 and sl_ratio>=0.5 and daily_pnl<0)
             == at least 5 of the last 10 deals are stop-loss closes
             == with an alternating book, EVERY exit in the window must be an SL.
        YELLOW's sl-ratio arm (sl_ratio>=0.5 and total>=3) needs >=2 SLs in a
             4-deal window, >=3 in 6, ... >=5 in 10 — always HALF THE DEALS,
             never half the trades.
     The legacy wording ("half the closed trades died at SL") is a factor-of-two
     optimistic description of what actually runs.

  3. THE DILUTION IS ONE-DIRECTIONAL: any non-SL exit in the window makes the SL
     arms HARDER, never easier. Measured: 5 straight SL closes reads RED; insert
     one take-profit into the same 10-deal window and sl_ratio drops to 0.4 and
     the level is GREEN. So the gate's SL arms are an ALL-or-nothing read on a
     full window, not a majority read.

  4. OPENING DEALS ARE NEUTRAL FOR THE STREAK. loss_streak is driven by profit
     sign and an opening deal has profit 0.0 — neither `profit < 0` nor
     `profit > 0` fires — so the deal-level slice does NOT corrupt the streak
     arm; it only dilutes the ratio arm. That is why the corrected slice is a
     tightening and not a mixed change: it would leave the streak arm alone and
     make the ratio arm bite ~2x sooner.

  5. THE LIVE WINDOW, RIGHT NOW (read-only from data/xau_plan/performance_state
     .json): the shape is recorded so the contract is checked against production
     state, not only against fixtures.

Discipline: no behaviour change anywhere (the only live-file edits in this round
are docstrings/comments), the live classifier is IMPORTED for every number, the
reachability table is an exhaustive enumeration over window shapes rather than a
sample, and the anti-drift pin is a test that fails if either side moves.

HARD RULES honoured: no order endpoint, no gate weakened (nothing is weakened by
writing down what already runs), no gate tightened either (that stays the human's
call — option (a) remains open and its price tag is in b88's ledger).
"""
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines.defcon import analyze_exits, classify_exits, compute_insights  # noqa: E402
from engines.risk import compute_performance_state                          # noqa: E402

OUT = "data/backtest/b89_window_contract.json"
LIVE_STATE = "data/xau_plan/performance_state.json"
WINDOW_DEALS = 10          # the literal slice in engines/risk.py
RED_MIN_DEALS = 5          # engines/defcon.py: total >= 5
YELLOW_MIN_DEALS = 3       # engines/defcon.py: total >= 3
SL_RATIO = 0.5             # engines/defcon.py: sl_ratio >= 0.5


def live_shaped_feed(n_trips, sl_at_end=0, partials=0):
    """The deal list the bridge actually returns for a one-position book.

    One opening deal (entry=0, profit 0.0, comment 'Hermes') followed by one
    closing deal per round trip; `sl_at_end` of the closes are '[sl ...]' and the
    rest '[tp ...]'; `partials` extra closing deals ('HermesClose') model
    management closes, which add exits WITHOUT adding opens.
    """
    out, k = [], 1
    for i in range(n_trips):
        out.append({"ticket": k, "entry": 0, "profit": 0.0, "comment": "Hermes",
                    "time": k, "side": "BUY"})
        k += 1
        is_sl = i >= n_trips - sl_at_end
        out.append({"ticket": k, "entry": 1,
                    "profit": -10.0 if is_sl else 5.0,
                    "comment": f"[sl 10.0]" if is_sl else "[tp 20.0]",
                    "time": k, "side": "BUY"})
        k += 1
    for _ in range(partials):
        out.append({"ticket": k, "entry": 1, "profit": 1.0,
                    "comment": "HermesClose", "time": k, "side": "BUY"})
        k += 1
    return out


def level_for(deals, daily_pnl=-1.0, loss_streak=0):
    """DEFCON as the live executor computes it from this window."""
    cl = classify_exits(deals)
    stats = analyze_exits(cl)
    ins = compute_insights(loss_streak=loss_streak, daily_pnl=daily_pnl,
                           balance=5000.0, classified=cl)
    return stats, ins["defcon"]


def producer_window(trips):
    """The window shape produced by the REAL producer for a live-shaped feed."""
    state = compute_performance_state({"day": "2026-09-05"}, "2026-09-05",
                                      5000.0, live_shaped_feed(trips))
    w = state["recent_closed"]
    return {"feed_trips": trips, "window_deals": len(w),
            "window_opens": sum(1 for d in w if str(d.get("entry")) == "0"),
            "window_exits": sum(1 for d in w if str(d.get("entry")) != "0")}


def shape_table():
    """Exhaustive: for every (window length, SL count) shape, what level?

    A window is described by (n_deals, n_sl_closes, n_other_closes); opens are
    whatever is left. Enumerating all of them answers "when can RED fire"
    without sampling, and it is the table the docstring now quotes.
    """
    rows = []
    for n_deals in range(1, WINDOW_DEALS + 1):
        for n_closes in range(0, n_deals + 1):
            n_opens = n_deals - n_closes
            for n_sl in range(0, n_closes + 1):
                deals = ([{"ticket": i, "entry": 0, "profit": 0.0,
                           "comment": "Hermes"} for i in range(n_opens)] +
                         [{"ticket": 100 + i, "entry": 1, "profit": -10.0,
                           "comment": "[sl 10.0]"} for i in range(n_sl)] +
                         [{"ticket": 200 + i, "entry": 1, "profit": 5.0,
                           "comment": "[tp 20.0]"}
                          for i in range(n_closes - n_sl)])
                stats, lv = level_for(deals)
                rows.append({"deals": n_deals, "opens": n_opens,
                             "closes": n_closes, "sl": n_sl,
                             "total": stats["total"],
                             "sl_ratio": stats.get("sl_ratio", 0.0),
                             "level": lv})
    return rows


def reachability(rows):
    """Minimum SL count per window length, and the alternating-book reading."""
    by_len = {}
    for n_deals in range(1, WINDOW_DEALS + 1):
        red = [r["sl"] for r in rows if r["deals"] == n_deals and r["level"] == "RED"]
        yel = [r["sl"] for r in rows if r["deals"] == n_deals and r["level"] == "YELLOW"]
        # an alternating one-position book holds ceil(n/2) opens in the window
        alt_exits = n_deals // 2
        by_len[n_deals] = {
            "min_sl_for_RED": min(red) if red else None,
            "min_sl_for_YELLOW": min(yel) if yel else None,
            "exits_in_alternating_book": alt_exits,
            "RED_needs_every_exit_SL_in_alternating_book":
                (min(red) if red else None) == alt_exits,
        }
    return by_len


def dilution_probe():
    """One non-SL exit inside an otherwise all-SL window: what does it cost?"""
    out = []
    for partials in range(0, 4):
        deals = live_shaped_feed(5, sl_at_end=5, partials=partials)[-WINDOW_DEALS:]
        stats, lv = level_for(deals)
        out.append({"extra_non_sl_exits_in_window": partials,
                    "total": stats["total"], "sl_count": stats["sl_count"],
                    "sl_ratio": stats.get("sl_ratio"), "level": lv})
    return out


def streak_neutrality():
    """Do opening deals pollute loss_streak? (profit 0.0 -> neither arm fires)"""
    deals = live_shaped_feed(4, sl_at_end=4)
    state = compute_performance_state({"day": "2026-09-05"}, "2026-09-05",
                                      5000.0, deals)
    return {"feed": "4 round trips, all closed at SL (8 deals: 4 opens + 4 closes)",
            "loss_streak": state["loss_streak"],
            "daily_pnl": state["daily_pnl"],
            "expected_streak": 4,
            "opening_deals_neutral": state["loss_streak"] == 4}


def live_window_snapshot():
    """The production window, read-only, so the contract is checked on real state."""
    if not os.path.exists(LIVE_STATE):
        return {"present": False}
    st = json.load(open(LIVE_STATE))
    w = st.get("recent_closed") or []
    opens = sum(1 for d in w if str(d.get("entry")) == "0")
    stats, lv = level_for(w, daily_pnl=float(st.get("daily_pnl", 0) or 0),
                          loss_streak=int(st.get("loss_streak", 0) or 0))
    return {"present": True, "day": st.get("day"),
            "window_deals": len(w), "window_opens": opens,
            "window_exits": len(w) - opens,
            "exit_type_mix": dict(Counter(c["exit_type"] for c in
                                          classify_exits(w))),
            "total_as_defcon_sees_it": stats["total"],
            "sl_ratio": stats.get("sl_ratio", 0.0),
            "defcon_level_now": lv,
            # RED needs total>=5 AND sl_count >= total/2 (sl_ratio>=0.5)
            "sl_still_needed_for_RED": (
                max(0, -(-stats["total"] // 2) - stats.get("sl_count", 0))
                if stats["total"] >= RED_MIN_DEALS else None)}


def main():
    # Provenance: the contract spans TWO files (the slice in engines/risk.py,
    # the thresholds + denominator in engines/defcon.py). Stamp both so a ledger
    # built against either side drifting cannot pass as current (pinned in
    # tests/test_b89_window_contract.py).
    def _sha(rel):
        with open(os.path.join(_ROOT, *rel.split("/")), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:12]

    rows = shape_table()
    led = {
        "_risk_code_sha": _sha("engines/risk.py"),
        "_defcon_code_sha": _sha("engines/defcon.py"),
        "_built_at": datetime.now(timezone.utc).isoformat(),
        "_note": "b89 option (b): DEFCON's window is 10 DEALS (opening deals "
                 "included), so every count in engines/defcon.py is a DEAL count "
                 "and sl_ratio's denominator includes opens. This ledger is the "
                 "reachability table that statement rests on, produced by the "
                 "live classifier. Zero behaviour change; option (a) — slicing "
                 "closing deals only — stays a human decision, priced in b88.",
        "_contract": {
            "window_deals_literal": WINDOW_DEALS,
            "source": "engines/risk.compute_performance_state -> [-10:] of the "
                      "bridge history-deals feed",
            "red_precondition_deals": RED_MIN_DEALS,
            "yellow_sl_arm_precondition_deals": YELLOW_MIN_DEALS,
            "sl_ratio_threshold": SL_RATIO,
            "ratio_denominator": "all deals in the window (opens included)",
        },
        "_harness": "live engines.risk + engines.defcon, imported not restated; "
                    "exhaustive enumeration over (window length, opens, closes, "
                    "SL count) shapes, not a sample",
        "producer_window_shape": [producer_window(n) for n in (1, 2, 3, 5, 8, 20)],
        "reachability_by_window_length": reachability(rows),
        "dilution_probe": dilution_probe(),
        "streak_neutrality": streak_neutrality(),
        "live_window": live_window_snapshot(),
        "shape_rows": len(rows),
        "level_tally": dict(Counter(r["level"] for r in rows)),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(led, f, indent=1, sort_keys=False)
    print(json.dumps({k: led[k] for k in
                      ("producer_window_shape", "reachability_by_window_length",
                       "dilution_probe", "streak_neutrality", "live_window",
                       "level_tally")}, indent=1))
    print("saved:", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
