#!/usr/bin/env python3
"""b84 — MEASURE THE GATE, NOT JUST THE ARM: the min_rr knob measured as books.

Why this round exists (todo b84, 2026-09-05). Round 18 (b68r) established the
template: a live FILTER must be measured as the funnel's own KEPT population and
DROPPED population, each run as a standalone book through the b71 harness on
cached+W1..W4, and reported on BOTH R axes (exp_R per trade AND total net_R +
DD), because round 18 proved one filter can win 4-of-4 on selection while losing
4-of-4 on volume. The grade gate got that treatment; the next filter named by
b84 is `MIN_RISK_REWARD = 1.5` (auto_executor Check 5.6), which b80 had already
flagged as "nearly never-binding at the funnel's own entries".

The pre-flight number is stranger than "never-binding". On every leg the funnel's
reward/risk distribution is a SPIKE, not a spread: cached 848/848 signals sit at
rr 1.549-1.552, W4 1745/1745 at 1.547-1.554, W1's median is 1.550 with 3 signals
above 1.75 out of 1429. The reason is in engines/plan.py::_reanchor_blueprint:
it sets tp = price +/- stop_dist * (min_rr + 0.05) — i.e. the geometry builder
MANUFACTURES every entry to sit exactly 0.05 above the floor the executor then
checks. So the gate cannot reject what the builder produced, and the "healthy RR"
the floor is supposed to enforce is a tautology, not a measurement.

That makes the knob's real property the opposite of a quality filter: it is a
CLIFF sitting 0.05 under the whole population. engines/learning.py may raise the
effective floor by +0.25 steps (RR_FLOOR_CEILING 2.5) whenever the journal goes
wr<0.40 and avg<0, and auto_executor takes max(MIN_RISK_REWARD, learning min_rr).
If the first such tightening lands at 1.75, every reanchored entry (rr 1.55) is
rejected — the system goes silent with reason poor_rr_1.55 and it reads like
"no setups", not like "the knob moved". This round prices that ladder.

Measured per leg (cached + b74's four independent windows), all under the LIVE
grade gate so the RR knob's effect is isolated from the grade effect round 18
already priced:

  kept_rr_<t>   the funnel's grade-passing signals with rr >= t, as a book
  drop_rr_<t>   the same population with rr <  t, as a book (what tightening kills)
  gate_rr_<t>   the whole funnel through run_arm(min_rr=t) — the counterfactual
                "live, but the floor sits at t" (slot contention priced, not sliced)
  rr_ladder     t in (1.5 live, 1.75, 2.0, 2.25, 2.5) = exactly the values
                engines/learning.py can reach from 1.5 in +0.25 steps

Verdicts this file can produce (b84's rules):
  * a filter whose dropped book is EMPTY everywhere is a no-op on the funnel —
    it does not select, it only waits;
  * the CLIFF is the smallest reachable t that kills >50% of the population;
  * the concentration (share of signals inside [t, t+0.06)) says whether the
    floor is a filter or a target the builder aims at;
  * tightening must be judged on exp_R AND net_R AND DD together (b81), and a
    cached-leg or single-cell number can never justify moving a gate (b74/b76).

Discipline: b71 harness (plain/ladder/ladder_ts + hold columns), b74 all-windows
rule, b77 chronological read (W4 oldest -> W1 newest), b78 BUY/SELL mix of the
trades actually taken, b83 re-MEASURE rather than re-read.

HARD RULES honoured: read-only research, nothing imported by the live path, no
gate is weakened or moved anywhere (the tightening direction is measured, never
wired), and any recommendation is a PROPOSAL for a human.
"""
import os
import sys
import json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                     # noqa: E402
from engines.auto_executor import (                       # noqa: E402
    MIN_RISK_REWARD, MIN_SETUP_GRADE)
from engines.learning import (                            # noqa: E402
    RR_FLOOR_CEILING, adjustments)
from scripts.b80_gate_parity import funnel_signals        # noqa: E402 (b83: reuse)
from scripts.b68r_grade_ladder_lab import side_mix        # noqa: E402 (b84: reuse)

OUT = "data/backtest/b84_rr_gate_books.json"
WINDOWS = ("W1", "W2", "W3", "W4")
CHRONO = ("W4", "W3", "W2", "W1")                 # b77: oldest -> newest
LEGS = ("cached",) + WINDOWS

# The ladder the ADAPTIVE gate can actually reach from the live floor:
# engines/learning.py steps min_rr by +0.25 and clamps at RR_FLOOR_CEILING.
LADDER_RR = tuple(round(MIN_RISK_REWARD + 0.25 * k, 2)
                  for k in range(0, int((RR_FLOOR_CEILING - MIN_RISK_REWARD) / 0.25) + 1))
BAND = 0.06          # the manufactured-spike band: [t, t+BAND)


def signal_rr(s):
    """Reward:risk exactly as auto_executor Check 5.6 recomputes it."""
    entry, sl, tp = float(s["entry"]), float(s["sl"]), float(s["tp"])
    return abs(tp - entry) / max(abs(entry - sl), 1e-9)


def rr_book(sigs, idx_of, keep):
    """Funnel signals filtered by a predicate on rr — a book that owns the slot."""
    def fn(row):
        s = sigs.get(idx_of.get(int(row.get("time", 0)), -1))
        if not s:
            return None
        return s if keep(signal_rr(s)) else None
    return fn


def _row(arm_row):
    # .get() everywhere: a zero-trade row from lh.r_stats carries only
    # trades/exp_R/net_R/maxDD_R/hold columns — no WR% (b69-class row shape).
    return {"trades": arm_row["trades"], "exp_R": arm_row.get("exp_R"),
            "net_R": arm_row.get("net_R"), "WR%": arm_row.get("WR%"),
            "maxDD_R": arm_row.get("maxDD_R"),
            "mean_hold_bars": arm_row.get("mean_hold_bars")}


def _d(x, y):
    return round(x - y, 3) if (x is not None and y is not None) else None


def measure_leg(name, m15, h1, h4):
    sigs = funnel_signals(m15, h1, h4)
    idx_of = {int(r["time"]): i for i, r in enumerate(m15)}
    # the population the LIVE executor is allowed to see at all: grade gate first
    passing = {i: s for i, s in sigs.items()
               if str(s.get("grade") or "").upper() <= MIN_SETUP_GRADE}
    rrs = sorted(signal_rr(s) for s in passing.values())
    all_rrs = sorted(signal_rr(s) for s in sigs.values())

    out = {"_bars": len(m15), "_first": int(m15[0]["time"]),
           "_last": int(m15[-1]["time"]), "_signals": len(sigs),
           "_grade_passing": len(passing),
           "_rr_min": round(all_rrs[0], 4) if all_rrs else None,
           "_rr_max": round(all_rrs[-1], 4) if all_rrs else None,
           "_rr_median": round(rrs[len(rrs) // 2], 4) if rrs else None,
           "_rr_in_spike_band": (sum(1 for v in rrs if BAND * -1 < v - 1.55 < BAND)
                                 if rrs else 0)}

    def all_fn(row):
        return sigs.get(idx_of.get(int(row.get("time", 0)), -1))

    for t in LADDER_RR:
        kept = rr_book(sigs, idx_of, lambda v, _t=t: v >= _t)
        drop = rr_book(sigs, idx_of, lambda v, _t=t: v < _t)
        for label, fn in ((f"kept_rr_{t}", kept), (f"drop_rr_{t}", drop)):
            arm = lh.run_arm(m15, fn, min_rr=0.0, min_grade=MIN_SETUP_GRADE)
            out[label] = {m: _row(arm[m]) for m in
                          ("plain", "ladder", "ladder_ts")}
            out[label]["_time_stop_bars"] = arm["_time_stop_bars"]
            out[label]["_mix"] = side_mix(m15, fn, min_grade=MIN_SETUP_GRADE)
            if arm.get("zero_reason"):
                out[label]["zero_reason"] = arm["zero_reason"]
        # the counterfactual: live funnel with the FLOOR moved to t (slot model
        # intact, so this prices what the executor would actually do). Its mix is
        # taken from the KEPT book because gate_rr_t and kept_rr_t are the same
        # population seen two ways (fn filter vs engine min_rr filter) — passing
        # all_fn here would report the UNGATED mix and lie about the trade count.
        arm = lh.run_arm(m15, all_fn, min_rr=t, min_grade=MIN_SETUP_GRADE)
        out[f"gate_rr_{t}"] = {m: _row(arm[m]) for m in
                               ("plain", "ladder", "ladder_ts")}
        out[f"gate_rr_{t}"]["_time_stop_bars"] = arm["_time_stop_bars"]
        out[f"gate_rr_{t}"]["_mix"] = side_mix(m15, kept,
                                               min_grade=MIN_SETUP_GRADE)
        if arm.get("zero_reason"):
            out[f"gate_rr_{t}"]["zero_reason"] = arm["zero_reason"]

    # the two questions the operator asks, in R, on the live-parity row
    live = out[f"gate_rr_{MIN_RISK_REWARD}"]["ladder_ts"]
    out["_ladder"] = {}
    for t in LADDER_RR:
        g = out[f"gate_rr_{t}"]["ladder_ts"]
        k = out[f"kept_rr_{t}"]["ladder_ts"]
        d = out[f"drop_rr_{t}"]["ladder_ts"]
        out["_ladder"][str(t)] = {
            "gate_trades": g["trades"], "gate_exp_R": g["exp_R"],
            "gate_net_R": g["net_R"], "gate_dd_R": g["maxDD_R"],
            "kept_trades": k["trades"], "kept_exp_R": k["exp_R"],
            "kept_net_R": k["net_R"],
            "dropped_trades": d["trades"], "dropped_exp_R": d["exp_R"],
            "dropped_net_R": d["net_R"],
            "kill_share": (round(1 - g["trades"] / live["trades"], 3)
                           if live["trades"] else None),
            "d_exp_R_vs_live": _d(g["exp_R"], live["exp_R"]),
            "d_net_R_vs_live": _d(g["net_R"], live["net_R"]),
            "d_dd_R_vs_live": _d(g["maxDD_R"], live["maxDD_R"]),
        }
    return out


def verdict(led):
    v = {}

    # Q1 (b84 rule 1) is the live floor binding AT ALL? The dropped book of the
    # live threshold must be empty on every leg for the knob to be a no-op.
    v["live_floor_is_noop"] = {
        "legs_where_dropped_book_empty": sum(
            1 for w in LEGS
            if led[w][f"drop_rr_{MIN_RISK_REWARD}"]["ladder_ts"]["trades"] == 0),
        "of": len(LEGS),
        "dropped_trades_per_leg": {
            w: led[w][f"drop_rr_{MIN_RISK_REWARD}"]["ladder_ts"]["trades"]
            for w in LEGS},
    }

    # Q2 the CONCENTRATION: what share of the grade-passing population sits
    # inside the spike band the builder aims at (1.55 +/- BAND)?
    v["rr_concentration"] = {}
    for w in LEGS:
        L = led[w]
        n = L["_grade_passing"]
        v["rr_concentration"][w] = {
            "grade_passing_signals": n,
            "inside_1_55_band": L["_rr_in_spike_band"],
            "share": round(L["_rr_in_spike_band"] / n, 4) if n else None,
            "rr_min": L["_rr_min"], "rr_median": L["_rr_median"],
            "rr_max": L["_rr_max"]}

    # Q3 (b84 rule 2) where is the CLIFF — the smallest reachable floor that
    # kills >50% of the live trade population, per leg, chronologically read.
    cliff = {}
    for w in CHRONO:
        lad = led[w]["_ladder"]
        hit = next((float(t) for t in LADDER_RR
                    if (lad[str(t)]["kill_share"] or 0) > 0.5), None)
        cliff[w] = {"cliff_floor": hit,
                    "kill_share_by_floor": {str(t): lad[str(t)]["kill_share"]
                                            for t in LADDER_RR}}
    v["cliff_by_floor"] = cliff
    v["cliff_identical_on_all_windows"] = (
        len({c["cliff_floor"] for c in cliff.values()}) == 1)

    # Q4 (b81's rule) does ANY reachable tightening pay on exp_R without giving
    # up volume? Quote both axes; a floor that kills the book pays in silence.
    pays = {}
    for t in LADDER_RR[1:]:
        rows = []
        for w in CHRONO:
            lad = led[w]["_ladder"][str(t)]
            rows.append({"window": w, "d_exp_R": lad["d_exp_R_vs_live"],
                         "d_net_R": lad["d_net_R_vs_live"],
                         "gate_trades": lad["gate_trades"],
                         "kill_share": lad["kill_share"],
                         "pays": (lad["d_exp_R_vs_live"] is not None
                                  and lad["d_exp_R_vs_live"] > 0)})
        pays[str(t)] = {
            "windows_paying": sum(1 for r in rows if r["pays"]), "of": len(rows),
            "replicated_all_windows": all(r["pays"] for r in rows),
            "chronological_d_exp_R": [r["d_exp_R"] for r in rows],
            "total_net_R_given_up": round(sum(r["d_net_R"] for r in rows
                                              if r["d_net_R"] is not None), 1),
            "total_trades_left": sum(r["gate_trades"] for r in rows),
            "per_window": rows}
    v["tighten_by_floor"] = pays

    # Q5 the marginal trade of the live gate (b84: negative everywhere = true
    # cliff, single-cell flip = direction artifact). Here the dropped book is
    # empty, so the marginal trade does not exist — say so in numbers.
    v["live_gate_marginal_trade"] = {
        w: led[w]["_ladder"][str(MIN_RISK_REWARD)]["dropped_trades"] for w in LEGS}

    # b78 mix per kept book per leg
    v["mix"] = {w: {f"kept_rr_{t}": led[w][f"kept_rr_{t}"]["_mix"]
                    for t in LADDER_RR} for w in LEGS}

    # the adaptive-gate hazard: can learning actually reach a killing floor, and
    # what does the live state say right now?
    from engines.learning import load_learning_state
    v["adaptive_gate_reach"] = {
        "learning_state": load_learning_state(),
        "reachable_floors": list(LADDER_RR),
        "floor_that_silences_the_funnel": min(
            (float(t) for t in LADDER_RR
             if all(led[w]["_ladder"][str(t)]["gate_trades"] == 0 for w in LEGS)),
            default=None),
        "adjustments_would_tighten_now": bool(
            (adjustments().get("changes") or {}).get("min_rr")),
    }
    return v


def main():
    led = {"_note": "b84: the min_rr gate measured as BOOKS (kept vs dropped) "
                    "plus the counterfactual floor ladder the adaptive gate can "
                    "reach, on cached+W1..W4, under the b71 harness with the "
                    "b80 live grade gate imported. Read-only; no gate moved; a "
                    "recommendation here is a PROPOSAL for a human.",
           "_live_gates": {"MIN_RISK_REWARD": MIN_RISK_REWARD,
                           "MIN_SETUP_GRADE": MIN_SETUP_GRADE},
           "_rr_ladder": list(LADDER_RR),
           "_harness": "b71 (plain/ladder/ladder_ts, live spread 0.20, live 36h "
                       "time exit) + b80 grade gate + b78 mix + b77 chrono read "
                       "+ b74 all-windows rule"}
    c = json.load(open("data/backtest/ab_aggressive_data.json"))
    print("##### cached (in-sample, informational) #####", flush=True)
    led["cached"] = measure_leg("cached", c["M15"], c["H1"], c["H4"])
    wins = json.load(open("data/backtest/b68l_independent_windows.json"))
    for w in WINDOWS:
        print(f"##### {w} #####", flush=True)
        led[w] = measure_leg(w, wins[w]["M15"], wins[w]["H1"], wins[w]["H4"])
    led["_verdict"] = verdict(led)

    print("\n=== the RR floor ladder (gate_rr_<t> ladder_ts: exp_R / n) ===")
    print(f"{'leg':8s} " + " ".join(f"{('t=' + str(t)):>16s}" for t in LADDER_RR))
    for leg in LEGS:
        cells = [led[leg][f"gate_rr_{t}"]["ladder_ts"] for t in LADDER_RR]
        print(f"{leg:8s} " + " ".join(
            f"{(c['exp_R'] if c['exp_R'] is not None else float('nan')):>10.3f}"
            f"/{c['trades']:<5d}" for c in cells))
    print("\n=== dropped book of each floor (trades the tightening kills) ===")
    print(f"{'leg':8s} " + " ".join(f"{('t=' + str(t)):>10s}" for t in LADDER_RR))
    for leg in LEGS:
        print(f"{leg:8s} " + " ".join(
            f"{led[leg][f'drop_rr_{t}']['ladder_ts']['trades']:>10d}"
            for t in LADDER_RR))
    print("\n=== VERDICT ===")
    print(json.dumps(led["_verdict"], indent=1))
    json.dump(led, open(OUT, "w"), indent=1)
    print("\nsaved:", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
