#!/usr/bin/env python3
"""b111 — WHAT DOES THE GRADE-RULE DIVERGENCE ACTUALLY CHANGE?

b109 filed b111 as a HUMAN-GATE decision on the premise that aligning the
watchdog's inline grade rule onto the canonical one "would change the live
breakeven lock on a real account". This probe tests that premise instead of
assuming it. Read-only: no bridge call, no order endpoint, no gate touched.

THREE measurements, in the frame the decision runs in (b113's rule — the
watchdog only ever builds a trade dict WHILE a position is open, so a census
over all 1500+ plan snapshots is the wrong frame):

1. DIFFERING CELLS. Sweep the whole (alignment, trend, regime) input space and
   keep only the cells where the two grade rules disagree. For each, run the
   REAL evaluate_trade_management through the live sequence (TP1 hit -> what the
   caller commits -> the next call) and ask whether ANY observable action
   differs. The weak/balanced lane distinction only matters if the position
   survives TP1, because post-b55 both lanes return share 1.0 and
   auto_executor routes share>=1.0 to bridge.close_position — the ticket is
   gone, so the breakeven branch is never reached.

2. STRUCTURAL REACHABILITY. The only cell that can differ is
   aligned + trend>=3.0 + a NON-continuation regime (strict says B -> close
   full; watchdog says A -> keep 0.3 runner -> BE lock fires). Feed the REAL
   producers (context._alignment_label + context._detect_regime) every
   combination of TF votes and trend/price geometry and ask whether that cell
   can be produced at all.

3. LIVE REPLAY. Join execution_log (the trades that actually executed) to their
   plan snapshot and replay the ladder under BOTH rules.

Writes data/backtest/b111_blast_radius.json.
"""
from __future__ import annotations

import csv
import glob
import itertools
import json
import os
import sys
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from engines.context import _alignment_label, _detect_regime  # noqa: E402
from engines.trade_management import (  # noqa: E402
    evaluate_trade_management, ladder_fields)

OUT = os.path.join(_ROOT, "data", "backtest", "b111_blast_radius.json")
CONT = {"breakout_continuation", "pullback_continuation"}


def strict_grade(alignment: str, trend: float, regime: str) -> str:
    """The canonical rule (auto_executor/hermes_runtime, b45)."""
    if alignment == "aligned" and trend >= 3.0 and regime in CONT:
        return "A"
    if alignment == "aligned" and trend >= 1.2:
        return "B"
    return "C"


def watchdog_grade(alignment: str, trend: float, regime: str) -> str:
    """position_daemon.build_trade's inline PRE-b45 rule (b111's subject)."""
    if alignment == "aligned" and trend >= 3.0:
        return "A"
    if alignment in ("aligned", "mixed") and trend >= 1.2:
        return "B"
    return "C"


def _trade(side: str, entry: float, sl: float, tp: float,
           quality: dict, grade: str) -> dict:
    """A trade dict shaped the way both live producers shape it."""
    return {"symbol": "XAUUSD", "side": side, "entry_price": entry,
            "sl": sl, "tp_levels": [entry + (tp - entry) * 0.5, tp],
            "tp_shares": [0.5, 0.3, 0.2], "scale_in_levels": [],
            "filled_tp_levels": [], "breakeven_active": False,
            "runner_active": True, "scaled_in_levels": [], "volume": 0.10,
            "setup_grade": grade,
            **{k: v for k, v in ladder_fields(quality, grade).items()
               if k != "setup_grade"}}


def _actionable(step: tuple) -> tuple:
    """What the BROKER would see: the action plus its numeric payload. The
    `reason` string is a label, not an instruction —
    'weak_full_exit_at_tp1' and 'balanced_full_exit_at_tp1' both carry
    close_fraction 1.0 and both route to bridge.close_position, so they are
    the SAME outcome. Comparing reason labels would report a difference where
    no order changes — the mistake this probe exists to avoid. For a stop
    move, the payload IS the new SL, which is exactly what distinguishes a
    +0.15R lock from a plain breakeven."""
    action, payload = step[0], step[1]
    return (action, payload)


def acts(seq: list) -> list:
    """The actionable projection of a replay: what would differ at the broker."""
    return [_actionable(s) for s in seq]


def replay(quality: dict, grade: str, side: str = "SELL",
           entry: float = 4300.0, sl: float = 4320.0,
           tp: float = 4260.0) -> list:
    """Run the REAL management chain the way the live callers run it:
    price reaches TP1 -> the caller commits what the broker accepted -> the
    next evaluation. Returns the ordered list of observable actions."""
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    t = _trade(side, entry, sl, tp, quality, grade)
    tp1 = entry + (tp - entry) * 0.5
    actions = []
    a = evaluate_trade_management(t, tp1, now)
    actions.append((a.get("action"), a.get("close_fraction"), a.get("reason")))
    if a.get("action") == "partial_take_profit":
        if float(a.get("close_fraction") or 0) >= 1.0:
            # auto_executor: fraction>=1.0 -> bridge.close_position. The
            # ticket no longer exists, so NO further management is evaluated.
            actions.append(("TICKET_CLOSED_AT_TP1", None, None))
            return actions
        t["filled_tp_levels"] = [a.get("target_hit")]
    # second call: the position survived TP1 -> breakeven branch is live
    b = evaluate_trade_management(t, tp1, now + timedelta(seconds=5))
    actions.append((b.get("action"), b.get("new_sl"), b.get("reason")))
    return actions


def r1_ne_r2_label_only(d: dict) -> bool:
    """True when the two rules produce DIFFERENT reason strings but the same
    broker-visible action+payload — i.e. the divergence is cosmetic."""
    return (d["replay_strict"] != d["replay_watchdog"]
            and acts(d["replay_strict"]) == acts(d["replay_watchdog"]))


def measure_cells() -> dict:
    alignments = ["aligned", "mixed", "neutral", "counter"]
    trends = [0.0, 0.3, 0.5, 0.8, 1.19, 1.2, 1.3, 2.0, 2.9, 3.0, 4.0, 6.0]
    regimes = ["breakout_continuation", "pullback_continuation", "range",
               "reversal", "none"]
    differing = []
    for al, tr, rg in itertools.product(alignments, trends, regimes):
        g1, g2 = strict_grade(al, tr, rg), watchdog_grade(al, tr, rg)
        if g1 == g2:
            continue
        q = {"alignment": al, "trend_strength": tr, "regime": rg}
        r1, r2 = replay(q, g1), replay(q, g2)
        differing.append({"alignment": al, "trend": tr, "regime": rg,
                          "grade_strict": g1, "grade_watchdog": g2,
                          "replay_strict": r1, "replay_watchdog": r2,
                          "outcome_differs": acts(r1) != acts(r2)})
    return {"cells_differing_in_grade": len(differing),
            "cells_differing_in_reason_label_only": sum(
                1 for d in differing if r1_ne_r2_label_only(d)),
            "cells_differing_in_outcome": sum(1 for d in differing
                                              if d["outcome_differs"]),
            "outcome_differing_cells": [d for d in differing
                                        if d["outcome_differs"]]}


def measure_reachability() -> dict:
    """Can the producers EVER emit aligned + trend>=3 + non-continuation?"""
    votes = ["bullish", "bearish", "neutral"]
    swept = 0
    reachable = []
    for m5, h1, h4 in itertools.product(votes, repeat=3):
        al = _alignment_label(m5, h1, h4)
        if al != "aligned":
            continue
        bias = h4 if h4 != "neutral" else h1
        if bias == "neutral":
            bias = m5
        for tr in (3.0, 3.5, 6.0, 12.0):
            for dv in (-2.0, -0.3, 0.0, 0.3, 2.0):
                for atr in (1.0, 5.0):
                    lp = 110.0 + dv * atr
                    rg = _detect_regime(
                        bias=bias, alignment=al, trend_strength=tr,
                        last_price=lp, value_low=100.0, value_high=110.0,
                        atr=atr, m5_bias=m5, h1_bias=h1, h4_bias=h4)
                    swept += 1
                    if rg not in CONT:
                        reachable.append({"m5": m5, "h1": h1, "h4": h4,
                                          "trend": tr, "dv_atr": dv,
                                          "atr": atr, "regime": rg})
    return {"aligned_strong_trend_geometries_swept": swept,
            "producing_a_non_continuation_regime": len(reachable),
            "examples": reachable[:5]}


def measure_live_replay() -> dict:
    """execution_log (real executions) joined to the plan snapshot IN FORCE at
    execution time. b113's frame rule: a plan_id is reassessed every 15 min and
    each reassessment writes a new snapshot under the SAME id, so taking the
    first match joins the trade to a plan that was not the live one when the
    order went out (it happened for the 14:15/14:30 mixed sells)."""
    hist = {}
    for f in sorted(glob.glob(os.path.join(
            _ROOT, "data", "xau_plan", "plan_history", "*.json"))):
        try:
            d = json.load(open(f))
            created = datetime.fromisoformat(d["created_at"])
        except Exception:
            continue
        hist.setdefault(d.get("plan_id"), []).append((created, d))
    for k in hist:
        hist[k].sort(key=lambda x: x[0])
    rows = list(csv.DictReader(open(os.path.join(
        _ROOT, "data", "xau_plan", "execution_log.csv"))))
    executed = [r for r in rows if r.get("result_ok") == "True" and r.get("ticket")]
    checked = skipped = differs = 0
    detail = []
    for r in executed:
        ent = datetime.fromisoformat(r["at"])
        cand = [(c, d) for c, d in hist.get(r["plan_id"], []) if c <= ent]
        if not cand:
            skipped += 1
            continue
        plan = cand[-1][1]
        q = plan.get("quality") or {}
        al, tr = str(q.get("alignment")), float(q.get("trend_strength") or 0)
        rg = str(q.get("regime"))
        side = r["side"]
        entry, sl, tp = (float(r["entry"]), float(r["sl"]), float(r["tp"]))
        r1 = replay(q, strict_grade(al, tr, rg), side, entry, sl, tp)
        r2 = replay(q, watchdog_grade(al, tr, rg), side, entry, sl, tp)
        checked += 1
        if acts(r1) != acts(r2):
            differs += 1
            detail.append({"ticket": r["ticket"], "alignment": al,
                           "trend": tr, "regime": rg,
                           "strict": r1, "watchdog": r2})
    return {"executed_trades": len(executed), "replayed": checked,
            "plan_snapshot_missing": skipped, "differing": differs,
            "detail": detail}


def measure_watchdog_frame() -> dict:
    """The census in the frame the watchdog runs in: plan snapshots taken
    WHILE a position was open (b113's rule)."""
    def _ts(s):
        return datetime.fromisoformat(s)
    rows = list(csv.DictReader(open(os.path.join(
        _ROOT, "data", "xau_plan", "execution_log.csv"))))
    executed = [r for r in rows if r.get("result_ok") == "True" and r.get("ticket")]
    st = json.load(open(os.path.join(
        _ROOT, "data", "xau_plan", "watchdog_state.json")))
    closed = {c["ticket"]: _ts(c["at"]) for c in st.get("closed", [])}
    jr = {}
    for r in csv.DictReader(open(os.path.join(
            _ROOT, "data", "xau_plan", "trade_journal.csv"))):
        try:
            jr[r["position_id"]] = datetime.fromtimestamp(
                int(r["close_time"]), tz=timezone.utc)
        except Exception:
            continue
    windows = []
    for r in executed:
        t = r["ticket"]
        ent = _ts(r["at"])
        cl = closed.get(t) or jr.get(t) or ent + timedelta(hours=4)
        windows.append((ent, cl))
    total = in_frame = differ = 0
    for f in sorted(glob.glob(os.path.join(
            _ROOT, "data", "xau_plan", "plan_history", "*.json"))):
        try:
            d = json.load(open(f))
            created = _ts(d["created_at"])
        except Exception:
            continue
        total += 1
        if not any(a <= created <= b for a, b in windows):
            continue
        in_frame += 1
        q = d.get("quality") or {}
        al, tr = str(q.get("alignment")), float(q.get("trend_strength") or 0)
        rg = str(q.get("regime"))
        if acts(replay(q, strict_grade(al, tr, rg))) != acts(
                replay(q, watchdog_grade(al, tr, rg))):
            differ += 1
    return {"plan_snapshots_total": total,
            "snapshots_while_position_open": in_frame,
            "outcome_differing_in_frame": differ}


def main() -> int:
    led = {
        "_note": "b111: does the watchdog's inline grade rule change any live "
                 "outcome? Three independent measurements (cells, producer "
                 "reachability, live replay) + the watchdog-frame census.",
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "cells": measure_cells(),
        "reachability": measure_reachability(),
        "live_replay": measure_live_replay(),
        "watchdog_frame": measure_watchdog_frame(),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(led, fh, indent=2, ensure_ascii=False, default=str)
    print(json.dumps({k: v for k, v in led.items()
                      if k not in ("_note", "cells")}, indent=2,
                     default=str)[:1600])
    print("cells:", led["cells"]["cells_differing_in_grade"], "grade-differing,",
          led["cells"]["cells_differing_in_outcome"], "outcome-differing")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
