#!/usr/bin/env python3
"""b124 — CLOSE THE PARITY QUESTION: WHOSE TRADES DOES THE LAB'S TIME-EXIT
EXEMPTION ACTUALLY COVER, ON THE CLOCK LIVE RUNS, AND WHAT DOES IT COST?

THE GAP IN CODE (b123's finding #4, filed as b124)
==================================================
`engines/backtest.py` exempts any trade that took a partial from the b57 time
exit (`time_stop_gate="no_partial"`, the DEFAULT, so every stored funnel number
in this repo carries it). `engines/legacy_guards.evaluate_time_exit` is purely
age-based and does not care about partials. So the lab lets a runner ride past
the time exit and live closes it. That is a real parity gap in code, not a
rounding artefact.

WHAT HAD ALREADY BEEN MEASURED, AND WHAT HAD NOT
================================================
b123 priced the gap on the BAR clock at the incumbent stop and found 0.000R on
15/18 arms. b129 re-priced the whole 14-arm bar grid under both gates and found
the RUNNER EXEMPTION INERT ACROSS THE GRID (max gate gap 0.006R). b130 then
showed the bar clock is the wrong clock: live counts WALL hours, XAUUSD bars do
not span the Sunday-night close, and 32 trades across the seven legs are at/over
36 wall hours while NONE reaches 144 bars.

But none of those rounds recorded the ONE number the decision rests on. The
exemption can only cost something if there is an OLD TRADE for it to exempt, and
b130's census counted old trades on the OFF arm WITHOUT splitting them by
`partial_taken` — so the ledger says "32 trades are old on live's clock" and
stays silent on how many of those 32 the lab's default convention lets ride.
This round measures exactly that cross-tab, per leg, trade by trade, plus the
cost of the exemption AT LIVE'S OWN LIMIT (wall::ts_36h), which b130 shipped in
its grid but never reported as a gate gap (its `_gate_gap` block is bar-clock
only, and its `verdict()` lists one-sided arms without the gate axis).

THE DECISION THIS ROUND HAS TO SUPPORT
======================================
b124's own wording: "decide whether the lab should mirror live's age rule by
DEFAULT". Flipping the engine default would silently re-price every stored
ledger (b120's rule), so the bar for doing it is a cost that is one-sided OR
past b123's 0.010R tripwire. The finding below is that the exemption covers
14/32 of the wall-old population — a real, non-empty exposure, the thing b129's
zeros could never see — and still costs at most 0.003R, mixed sign, because the
cut frees the single slot for a comparable trade instead of repricing the cut
one (b130's mechanism, now confirmed on the gate axis too).

READ-ONLY RESEARCH. Nothing here is imported by the live trading path. The
engine's `time_stop_gate` default is UNCHANGED, `MAX_POSITION_AGE_HOURS` is
IMPORTED from engines.legacy_guards (never restated), the 144-bar incumbent is
DERIVED via lh.live_time_stop_bars, and the funnel is b81.funnel_fn on
b121's seven legs — the same bars, the same harness, the same ladder.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                       # noqa: E402
from engines.backtest import backtest_ohlc                  # noqa: E402
from engines.legacy_guards import MAX_POSITION_AGE_HOURS    # noqa: E402
from scripts import b81_lane_rescore as b81                 # noqa: E402
from scripts.b121_flat_share_replication import (           # noqa: E402
    LEGS, _rows_for)
from scripts.b123_protection_share_decomposition import one_sided       # noqa
from scripts.b129_timestop_reprice import (                             # noqa
    INCUMBENT_STOP, one_sided_strict)

OUT = "data/backtest/b124_gate_exemption_census.json"
LEDGER_130 = "data/backtest/b130_wall_clock_parity.json"
LEDGER_129 = "data/backtest/b129_timestop_reprice.json"

# b129 named the lab's stored convention GATE_LIVE, which reads backwards now
# that b130 proved live's RULE is the age-only one. Name them for what they
# are; the test pins both spellings against b129's own constants so the two
# ledgers cannot mean different things by the same arm.
LAB_GATE = "no_partial"        # the engine default = every stored number
LIVE_GATE = "age_only"         # mirrors legacy_guards.evaluate_time_exit

WINDOWS = tuple(w for w in LEGS if w != "cached")
LIVE_HOURS = float(MAX_POSITION_AGE_HOURS)

# b123's own tripwire, imported by value from the test that enforces it: the
# exemption stops being a documentation item past this cost.
TRIPWIRE_R = 0.010


def _run(m15, funnel, gate: str, **stop) -> dict:
    """One funnel replay at live-parity defaults + one gate + one stop."""
    kw = dict(lh.LADDER, time_stop_gate=gate, protection_mode="partial")
    kw.update(stop)
    return backtest_ohlc(m15, funnel, min_rr=lh.MIN_RR, spread=lh.SPREAD,
                         min_grade=lh.LIVE_MIN_GRADE, **kw)


def wall_age_h(t: dict) -> float:
    return (int(t["exit_time"]) - int(t["entry_time"])) / 3600.0


def bar_age(t: dict) -> int:
    return int(t["exit_index"]) - int(t["entry_index"])


def off_rows(trade_log: list[dict]) -> list[dict]:
    """The census's INPUT, in ledger-native form: one row per off-run trade
    with exactly the fields the census reads. b130 stores its census input the
    same way (`_ages_off`), so b127 can re-execute the census from the shipped
    JSON without re-running the funnel (b128's ship-time rule)."""
    return [{"entry": t["entry"], "grade": t.get("grade"),
             "side": t.get("side"), "bar_age": bar_age(t),
             "wall_age_h": round(wall_age_h(t), 4),
             "partial_taken": round(float(t.get("partial_taken") or 0.0), 4),
             "exit_reason": t["exit_reason"], "pnl": round(t["pnl"], 2)}
            for t in trade_log]


def exemption_census(rows: list[dict], hours: float, bars: int) -> dict:
    """THE CROSS-TAB b130 never produced: old trades x exempted-or-not.

    Computed off the NO-EXIT run on purpose — an exit truncates the very tail
    the census is about (b130's convention, kept identical so the two ledgers
    count the same population). `exempted` = the lab's default `no_partial`
    gate would let this trade ride past live's limit; `not_exempted` = both
    gates close it identically, so it contributes nothing to the gap.
    """
    old = [t for t in rows if t["wall_age_h"] >= hours]
    ex = [t for t in old if t["partial_taken"] > 0.0]
    ne = [t for t in old if t["partial_taken"] <= 0.0]
    # Every trade in `old` was STILL OPEN at live's limit by construction: its
    # natural exit came later than the limit, so live's age rule would have cut
    # it first. That is what makes the exemption a real difference rather than
    # a no-op on already-dead tickets. The split that explains the SIGN of the
    # gap is which kind of open ticket it spares: a runner (0 < share < 1) or a
    # full-close-at-TP1 ticket (share >= 1.0, which live's b105 rule closes at
    # TP1 — the lab lets it reach that TP1, live closes it at the bar close at
    # 36h). `exempt_pnl_sum` is the tell: if the spared trades are winners, the
    # lab's default flatters the stored bar (bias UP), and the honest direction
    # of the gap is fixed even when its size is noise.
    runner = [t for t in ex if t["partial_taken"] < 1.0]
    full = [t for t in ex if t["partial_taken"] >= 1.0]
    return {
        "n_trades": len(rows),
        "n_wall_old": len(old),
        "n_wall_old_exempted": len(ex),
        "n_wall_old_not_exempted": len(ne),
        "n_exempt_runner": len(runner),
        "n_exempt_full_close_tp1": len(full),
        "exempt_pnl_sum": round(sum(t["pnl"] for t in ex), 2),
        "exempt_n_positive": sum(1 for t in ex if t["pnl"] > 0),
        "exempt_share": (round(len(ex) / len(old), 3) if old else 0.0),
        # the bar-clock mirror: on the clock b123/b129 measured, the exemption
        # has NOTHING to exempt, which is why those rounds read the gap as 0.
        "n_bar_old": sum(1 for t in rows if t["bar_age"] >= bars),
        "n_bar_old_exempted": sum(1 for t in rows
                                  if t["bar_age"] >= bars
                                  and t["partial_taken"] > 0.0),
        "max_wall_age_h": round(max((t["wall_age_h"] for t in rows),
                                    default=0.0), 2),
        "exempted_trades": sorted(
            ({"entry": t["entry"], "grade": t["grade"], "side": t["side"],
              "bar_age": t["bar_age"], "wall_age_h": round(t["wall_age_h"], 2),
              "partial_taken": t["partial_taken"],
              "exit_reason": t["exit_reason"], "pnl": t["pnl"]}
             for t in ex), key=lambda a: -a["wall_age_h"]),
    }


def gate_gap_row(leg: str, m15, funnel) -> dict:
    """The cost of the exemption AT LIVE'S LIMIT: age_only minus no_partial."""
    ts_bars = lh.live_time_stop_bars(m15)
    cells = {}
    for gate in (LAB_GATE, LIVE_GATE):
        cells[gate] = lh.r_stats(
            _run(m15, funnel, gate, time_stop_hours=LIVE_HOURS),
            time_stop_bars=ts_bars)
    # the OFF cell feeds the census (no exit truncates the tail)
    off = _run(m15, funnel, LAB_GATE, time_stop_bars=0, time_stop_hours=0.0)
    rows = off_rows(off["trade_log"])
    return {"_time_stop_bars": ts_bars, "_live_hours": LIVE_HOURS,
            "grid": cells,
            "_off_rows": rows,
            "_census": exemption_census(rows, LIVE_HOURS, INCUMBENT_STOP)}


def build() -> dict:
    led = {
        "_note": "b124: the lab's time exit exempts any trade that took a "
                 "partial; live's evaluate_time_exit is age-based and does not. "
                 "This round counts WHICH wall-old trades that exemption "
                 "covers (the cross-tab b130's census left out) and prices the "
                 "gap at live's own limit. Nothing wired: the engine default "
                 "time_stop_gate is unchanged.",
        "_live_guard": f"engines.legacy_guards.MAX_POSITION_AGE_HOURS = "
                       f"{MAX_POSITION_AGE_HOURS}h (imported, not restated)",
        "_lab_default_gate": LAB_GATE,
        "_live_mirror_gate": LIVE_GATE,
        "_frame": "M15 legs (b121/b123/b129/b130's seven), live-parity funnel "
                  "from b81.funnel_fn, lh.LADDER (grade share fn, trail+floor "
                  "derived per b118), min_grade=live, spread=0.20, "
                  "protection_mode='partial' (b123's stored coupling).",
        "_arm": f"wall::ts_{int(LIVE_HOURS)}h at both gates",
        "_tripwire_R": TRIPWIRE_R,
        "_legs": list(LEGS),
    }
    for leg in LEGS:
        print(f"##### {leg} #####", flush=True)
        m15, h1, h4 = _rows_for(leg)
        funnel = b81.funnel_fn(m15, h1, h4)
        led[leg] = gate_gap_row(leg, m15, funnel)
    led["_gate_gap_R"] = gate_gap(led)
    led["_gate_gap_other_metrics"] = {
        m: gate_gap(led, m) for m in ("net_R", "maxDD_R", "trades")}
    led["_neutrality"] = neutrality(led)
    led["_parity_decomposition"] = parity_decomposition(led)
    led["_integrity"] = integrity(led)
    led["_verdict"] = verdict(led)
    return led


def _cell(led, leg, gate, metric="exp_R"):
    return led[leg]["grid"][gate][metric]


def gate_gap(led, metric: str = "exp_R") -> dict:
    """age_only minus no_partial per leg — the exemption's price, pure
    arithmetic on the grid (b127: a test re-executes this against the JSON)."""
    return {leg: round(_cell(led, leg, LIVE_GATE, metric)
                       - _cell(led, leg, LAB_GATE, metric), 3)
            for leg in led["_legs"]}


def neutrality(led) -> dict:
    """b110's test on the ONE arm this round measures, with b130's denominator
    rule: n_nonzero sits next to every flag, because a proportion over mostly
    inert legs is not evidence."""
    g = gate_gap(led)
    vals = [g[w] for w in WINDOWS]
    pos = sum(1 for v in vals if v > 0)
    neg = sum(1 for v in vals if v < 0)
    return {
        "time_exit_exemption_cost_R": {
            "per_leg": g, "n_windows": len(vals),
            "positive": pos, "negative": neg, "n_nonzero": pos + neg,
            "one_sided": one_sided(pos, neg),
            "unanimous": one_sided_strict(pos, neg, len(WINDOWS)),
            "mean_R": round(sum(vals) / len(vals), 4),
            "max_abs_R": max(abs(v) for v in vals),
            "all_legs_max_abs_R": max(abs(v) for v in g.values()),
            "past_tripwire": max(abs(v) for v in g.values()) > TRIPWIRE_R,
        }}


def integrity(led) -> dict:
    """This round must be the SAME funnel b130 froze, or its gate gap is a
    splice. The wall-36h cells at both gates are byte-compared against b130's
    shipped grid; the bar incumbent is re-checked against b129 through b130's
    own integrity claim (b130 already proved its bar cell equals b129/b123/b121,
    so chaining to it is the cheap, non-duplicating form)."""
    l130 = json.load(open(LEDGER_130))
    l129 = json.load(open(LEDGER_129))
    # the chain to b129: b130 proved its BAR incumbent equals b129's frozen
    # cell on every leg. If that claim rots, this round's wall cells are still
    # b130's but no longer the same funnel b123/b129 priced, so the gate gap
    # would be a splice of two engines.
    assert all(all(v.values()) for v in l130["_integrity"].values()), \
        "b130's own integrity block is no longer all-true — do not read this " \
        "round's gap until the bar incumbent reproduces again"
    assert all(l129[leg]["grid"][f"{LAB_GATE}::ts_{INCUMBENT_STOP}"]["exp_R"]
               == l130[leg]["grid"][f"{LAB_GATE}::bar::ts_{INCUMBENT_STOP}"]["exp_R"]
               for leg in l130["_legs"]), \
        "b129's bar incumbent no longer equals b130's — the two ledgers are " \
        "different funnels and the gate gap is not comparable to b123's"
    out = {}
    for leg in led["_legs"]:
        out[leg] = {
            "wall36_no_partial_matches_b130":
                led[leg]["grid"][LAB_GATE]
                == l130[leg]["grid"][f"{LAB_GATE}::wall::ts_{int(LIVE_HOURS)}h"],
            "wall36_age_only_matches_b130":
                led[leg]["grid"][LIVE_GATE]
                == l130[leg]["grid"][f"{LIVE_GATE}::wall::ts_{int(LIVE_HOURS)}h"],
            "census_old_count_matches_b130":
                led[leg]["_census"]["n_wall_old"]
                == l130[leg]["_census"]["n_over_wall"],
        }
    return out


def parity_decomposition(led) -> dict:
    """The whole lab-vs-live time-exit gap, split into its two causes.

    The stored funnel bar is `no_partial` on the BAR clock at the derived 144
    incumbent (b123/b129's convention). Live runs `age-based` on the WALL clock
    at MAX_POSITION_AGE_HOURS. Two things changed between them and b124's
    question is only about ONE of them:

        clock_part = wall::no_partial  - bar::no_partial   (b130's finding)
        gate_part  = wall::age_only    - wall::no_partial  (THIS round)
        total      = wall::age_only    - bar::no_partial

    Reading the total as "the exemption" would blame b123's gate for b130's
    clock (and vice versa). Each part gets its own neutrality row, so the
    re-baseline decision attaches to whichever cause actually earns it.
    """
    l130 = json.load(open(LEDGER_130))
    bar_inc = f"{LAB_GATE}::bar::ts_{INCUMBENT_STOP}"
    wall_np = f"{LAB_GATE}::wall::ts_{int(LIVE_HOURS)}h"
    out = {}
    for leg in led["_legs"]:
        b = l130[leg]["grid"][bar_inc]["exp_R"]
        w_np = l130[leg]["grid"][wall_np]["exp_R"]
        w_ao = led[leg]["grid"][LIVE_GATE]["exp_R"]
        out[leg] = {"stored_bar_no_partial_144": b,
                    "live_clock_lab_gate": w_np,
                    "live_clock_live_gate": w_ao,
                    "clock_part_R": round(w_np - b, 3),
                    "gate_part_R": round(w_ao - w_np, 3),
                    "total_R": round(w_ao - b, 3)}
    parts = {}
    for key in ("clock_part_R", "gate_part_R", "total_R"):
        vals = {leg: out[leg][key] for leg in led["_legs"]}
        w = [out[leg][key] for leg in WINDOWS]
        pos = sum(1 for v in w if v > 0)
        neg = sum(1 for v in w if v < 0)
        parts[key] = {"per_leg": vals, "n_windows": len(w),
                      "positive": pos, "negative": neg,
                      "n_nonzero": pos + neg, "one_sided": one_sided(pos, neg),
                      "unanimous": one_sided_strict(pos, neg, len(WINDOWS)),
                      "mean_R": round(sum(w) / len(w), 4),
                      "max_abs_R": max(abs(v) for v in w)}
    return {"per_leg": out, "parts": parts}


def verdict(led) -> dict:
    neu = led["_neutrality"]["time_exit_exemption_cost_R"]
    dec = parity_decomposition(led)
    cen = {leg: led[leg]["_census"] for leg in led["_legs"]}
    n_old = sum(c["n_wall_old"] for c in cen.values())
    n_ex = sum(c["n_wall_old_exempted"] for c in cen.values())
    one_sided = neu["one_sided"]
    past = neu["past_tripwire"]
    # b124's own trigger is "one-sided OR past 0.010R". That OR is the last
    # thing this round has to say: a one-sided 0.003R fires it, so the trigger
    # as written cannot distinguish a real re-baseline case from a directionally
    # consistent rounding of nothing. Report both axes and name the third state.
    if one_sided and past:
        decision = "RE-BASELINE DECISION — one-sided AND past the tripwire"
    elif past:
        decision = ("RE-BASELINE DECISION — the cost is past b123's 0.010R "
                    "tripwire even though the sign is mixed")
    elif one_sided:
        decision = ("TRIGGER FIRES ON NOISE — one-sided in sign but "
                    f"{neu['max_abs_R']}R, under b123's own 0.010R tripwire and "
                    "30x under b119's 0.10R ceiling; no stored number moves, "
                    "the parity gap stays documented, not wired")
    else:
        decision = ("NO LEVER — keep the lab default; the parity gap stays "
                    "documented, not wired")
    return {
        "exemption_has_a_population_on_live_clock": n_ex > 0,
        "n_wall_old_trades": n_old,
        "n_wall_old_exempted_by_lab_default": n_ex,
        "n_bar_old_trades": sum(c["n_bar_old"] for c in cen.values()),
        "n_bar_old_exempted": sum(c["n_bar_old_exempted"]
                                  for c in cen.values()),
        "exempt_share_of_wall_old": (round(n_ex / n_old, 3) if n_old else 0.0),
        "n_exempt_runner": sum(c["n_exempt_runner"] for c in cen.values()),
        "n_exempt_full_close_tp1": sum(c["n_exempt_full_close_tp1"]
                                       for c in cen.values()),
        "exempt_pnl_sum_usd": round(sum(c["exempt_pnl_sum"]
                                        for c in cen.values()), 2),
        "exempt_n_positive": sum(c["exempt_n_positive"] for c in cen.values()),
        "gate_gap_max_abs_R": neu["max_abs_R"],
        "gate_gap_mean_R": neu["mean_R"],
        "gate_gap_one_sided": one_sided,
        "gate_gap_n_nonzero": neu["n_nonzero"],
        "past_b123_tripwire": past,
        "parity_parts": dec["parts"],
        "decision": decision,
    }


def main() -> int:
    led = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(led, fh, indent=1)
    v = led["_verdict"]
    print(f"\nwalls-old trades: {v['n_wall_old_trades']}  "
          f"exempted by lab default: "
          f"{v['n_wall_old_exempted_by_lab_default']} "
          f"({v['exempt_share_of_wall_old']:.0%})   "
          f"bar-old: {v['n_bar_old_trades']}")
    print(f"gate gap @ live limit: max |{v['gate_gap_max_abs_R']}|R  "
          f"mean {v['gate_gap_mean_R']}R  one_sided="
          f"{v['gate_gap_one_sided']} (n_nonzero={v['gate_gap_n_nonzero']})  "
          f"past_tripwire={v['past_b123_tripwire']}")
    print("DECISION:", v["decision"])
    bad = {k: x for k, x in led["_integrity"].items() if not all(x.values())}
    print("integrity failures:", bad or "none")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
