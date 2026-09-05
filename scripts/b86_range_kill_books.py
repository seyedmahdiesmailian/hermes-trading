#!/usr/bin/env python3
"""b86 (b68 round 19) — MEASURE THE GATE, NOT JUST THE ARM: the range-kill
confidence threshold measured as books (todo b84's named next filter).

Why this round exists. b84 established the template and named the queue: every
live FILTER must eventually be measured as BOOKS — the funnel's own KEPT
population and DROPPED population each run as a standalone book through the b71
harness on cached+W1..W4, plus the counterfactual "live, but the knob sits at
value t" row that prices slot contention. b84 finished min_rr (verdict: a
no-op, because _reanchor_blueprint manufactures rr = floor+0.05). The next
filter b84's note queued is the range-kill:

    if classic_regime == 'range' and smc_bias != 'neutral' and smc_confidence < 0.35:
        bias -> neutral  (the entry dies downstream)

Its live home is hermes_runtime.build_live_plan (a hardcoded 0.35); the
backtest twin is engines/backtest_real.strategy_signal(range_kill_conf=...) —
the ONLY funnel parameter that was ever made overridable for A/B (scripts/
ab_range_kill.py, 2026-08) and never measured in R since.

Pre-flight on the cached leg (this run, before shipping anything): at the live
0.35 the kill removes ZERO signals (848 -> 848, byte-identical geometry), while
at 0.99 it removes 462 of 848. So the honest questions are the same three b84
asked, and one b84 could not ask:

  kept/dropped books   does the gate select anything at all, per leg?
  gate_conf_<t>        the counterfactual funnel at t in (0.0 never-kill,
                       0.35 live, 0.50, 0.70, 0.99 always-kill) — slot model
                       intact, so this prices what the executor would do.
  REACHABILITY         unlike min_rr, NO adaptive code can move this knob:
                       engines/learning.py adjusts min_rr/min_grade/risk_mult
                       only, and 0.35 is a literal in build_live_plan. A gate
                       that never binds AND can never be tightened is not a
                       risk control — it is dead code with a risk vocabulary.
                       This round prices the whole band so the operator can
                       see how much of the funnel the rule COULD take if it
                       ever fired (the always-kill book is the upper bound).

Verdicts this file can produce (b84's rules, unchanged):
  * a filter whose dropped book is EMPTY on every leg is a no-op on the
    funnel — it does not select, it only waits;
  * the CLIFF here is the threshold at which the gate starts eating the book
    (kill_share by t, per leg, read chronologically W4 oldest -> W1 newest);
  * tightening/loosening must be judged on exp_R AND net_R AND DD together
    (b81), and no cached-leg or single-cell number justifies moving a gate
    (b74/b76);
  * b83: the live row (gate_conf_0.35) must REPRODUCE b80's gradeB_rr15 column
    exactly on every leg — if it doesn't, this round's harness drifted and the
    numbers are worthless.

Discipline: b71 harness (plain/ladder/ladder_ts + hold columns), b74
all-windows rule, b77 chronological read, b78 BUY/SELL mix of the trades
actually taken, b80 imported live gates, b83 re-MEASURE + reproduce.

HARD RULES honoured: read-only research, nothing imported by the live path, no
gate is weakened or moved anywhere (the 0.0/0.99 rows are COUNTERFACTUALS run
in a lab script, not config changes), and any recommendation is a PROPOSAL for
a human.
"""
import os
import sys
import json
from collections import Counter

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                     # noqa: E402
from engines.auto_executor import (                       # noqa: E402
    MIN_RISK_REWARD, MIN_SETUP_GRADE)
from scripts.b68r_grade_ladder_lab import side_mix        # noqa: E402 (b84: reuse)

OUT = "data/backtest/b86_range_kill_books.json"
PARITY = "data/backtest/b80_gate_parity.json"
WINDOWS = ("W1", "W2", "W3", "W4")
CHRONO = ("W4", "W3", "W2", "W1")                 # b77: oldest -> newest
LEGS = ("cached",) + WINDOWS

# The band the knob can sit on. 0.35 is the live literal in build_live_plan;
# 0.0 = never kill, 0.99 = always kill when regime==range & bias!=neutral
# (confidence is capped at 1.0 by merge_smc_with_classic, so 0.99 is the
# practical ceiling). 0.50/0.70 are the intermediate settings ab_range_kill.py
# never got around to measuring.
LADDER_CONF = (0.0, 0.35, 0.50, 0.70, 0.99)
LIVE_CONF = 0.35


def _row(arm_row):
    return {"trades": arm_row["trades"], "exp_R": arm_row.get("exp_R"),
            "net_R": arm_row.get("net_R"), "WR%": arm_row.get("WR%"),
            "maxDD_R": arm_row.get("maxDD_R"),
            "mean_hold_bars": arm_row.get("mean_hold_bars")}


def _d(x, y):
    return round(x - y, 3) if (x is not None and y is not None) else None


def sig_fn(sigs, idx_of):
    def fn(row):
        return sigs.get(idx_of.get(int(row.get("time", 0)), -1))
    return fn


def measure_leg(name, m15, h1, h4):
    # ONE pass per threshold: the funnel re-runs because the kill happens
    # INSIDE strategy_signal (it is not a post-filter on a fixed population —
    # that is exactly what makes this gate different from min_rr).
    pops = {t: _pass(m15, h1, h4, t) for t in LADDER_CONF}
    never = pops[0.0]
    live = pops[LIVE_CONF]

    idx_of = {int(r["time"]): i for i, r in enumerate(m15)}
    # The kill can only DEMOTE a signal (bias -> neutral), so the live
    # population must be a subset of the never-kill population. If it ever
    # isn't, the kept/dropped books below would be slicing a moving base and
    # the ledger would be lying — record the violation instead of hiding it.
    stray = sorted(set(live) - set(never))
    killed_live = {i: never[i] for i in set(never) - set(live)}
    killed_max = {i: never[i] for i in set(never) - set(pops[0.99])}
    out = {"_bars": len(m15), "_first": int(m15[0]["time"]),
           "_last": int(m15[-1]["time"]),
           "_signals_never_kill": len(never),
           "_signals_live": len(live),
           "_live_is_subset_of_never": not stray,
           "_stray_live_indices": stray[:10],
           "_signals_killed_at_live": len(killed_live),
           "_signals_killed_at_099": len(killed_max),
           # THE decisive probe: WHO does the gate actually take? If every
           # signal it can ever kill is already C-grade, the gate is redundant
           # with MIN_SETUP_GRADE, not independent of it.
           "_killed_at_099_grade_mix": dict(Counter(
               str(s.get("grade") or "").upper() for s in killed_max.values())),
           "_killed_at_live_grade_mix": dict(Counter(
               str(s.get("grade") or "").upper() for s in killed_live.values())),
           }

    for t in LADDER_CONF:
        fn = sig_fn(pops[t], idx_of)
        arm = lh.run_arm(m15, fn, min_rr=MIN_RISK_REWARD,
                         min_grade=MIN_SETUP_GRADE)
        out[f"gate_conf_{t}"] = {m: _row(arm[m]) for m in
                                 ("plain", "ladder", "ladder_ts")}
        out[f"gate_conf_{t}"]["_time_stop_bars"] = arm["_time_stop_bars"]
        out[f"gate_conf_{t}"]["_mix"] = side_mix(
            m15, fn, min_grade=MIN_SETUP_GRADE)
        if arm.get("zero_reason"):
            out[f"gate_conf_{t}"]["zero_reason"] = arm["zero_reason"]

    # kept/dropped books at the LIVE threshold (b84's books): kept = the live
    # population; dropped = the signals the live gate removes. Empty dropped
    # book on every leg == the gate never selects.
    dropped_idx = set(never) - set(live)
    keep_fn = sig_fn(never, idx_of)          # superset book: everything the
    drop_map = {i: never[i] for i in dropped_idx}   # gate could ever allow
    out["kept_conf_live"] = _book(m15, keep_fn, idx_of,
                                  lambda i: i not in dropped_idx, never)
    out["dropped_conf_live"] = _book(m15, keep_fn, idx_of,
                                     lambda i: i in dropped_idx, never)

    # THE REDUNDANCY BOOK (b86's own question): the maximum-kill population
    # measured TWICE — once under the live gates (what the executor would
    # actually trade: nothing, if the kill only hits C) and once UNGRADED
    # (what the rule really removes from the world, if the grade gate were not
    # already there). The gap between the two rows IS the redundancy.
    kill_max_fn = sig_fn(killed_max, idx_of)
    out["dropped_conf_099_livegates"] = _book(
        m15, kill_max_fn, idx_of, lambda i: True, killed_max)
    arm = lh.run_arm(m15, kill_max_fn, min_rr=0.0, min_grade=None)
    ung = {m: _row(arm[m]) for m in ("plain", "ladder", "ladder_ts")}
    ung["_mix"] = side_mix(m15, kill_max_fn, min_grade=None)
    out["dropped_conf_099_ungated"] = ung

    # the ladder read (b81: exp_R AND net_R AND DD together)
    live_row = out[f"gate_conf_{LIVE_CONF}"]["ladder_ts"]
    out["_ladder"] = {}
    for t in LADDER_CONF:
        g = out[f"gate_conf_{t}"]["ladder_ts"]
        out["_ladder"][str(t)] = {
            "gate_trades": g["trades"], "gate_exp_R": g["exp_R"],
            "gate_net_R": g["net_R"], "gate_dd_R": g["maxDD_R"],
            "kill_share": (round(1 - g["trades"] / live_row["trades"], 3)
                           if live_row["trades"] else None),
            "d_exp_R_vs_live": _d(g["exp_R"], live_row["exp_R"]),
            "d_net_R_vs_live": _d(g["net_R"], live_row["net_R"]),
            "d_dd_R_vs_live": _d(g["maxDD_R"], live_row["maxDD_R"]),
        }
    return out


def _pass(m15, h1, h4, conf):
    import bisect
    h1t = [r.get("time", 0) for r in h1]
    h4t = [r.get("time", 0) for r in h4]
    from engines.backtest_real import strategy_signal
    sigs = {}
    for i, row in enumerate(m15):
        bt = row.get("time", 0)
        j1 = bisect.bisect_right(h1t, bt)
        j4 = bisect.bisect_right(h4t, bt)
        s = strategy_signal(row, h1[max(0, j1 - 80):j1],
                            h4[max(0, j4 - 80):j4], i,
                            m15_window=m15[max(0, i - 120):i + 1],
                            range_kill_conf=conf)
        if s:
            sigs[i] = s
    return sigs


def _book(m15, base_fn, idx_of, keep, sigs):
    """Run a predicate-selected slice of the never-kill population as its own
    book under the harness (one position at a time, live gates)."""
    def fn(row):
        s = base_fn(row)
        if not s:
            return None
        i = idx_of.get(int(row.get("time", 0)), -1)
        return s if keep(i) else None
    arm = lh.run_arm(m15, fn, min_rr=MIN_RISK_REWARD,
                     min_grade=MIN_SETUP_GRADE)
    row = {m: _row(arm[m]) for m in ("plain", "ladder", "ladder_ts")}
    row["_mix"] = side_mix(m15, fn, min_grade=MIN_SETUP_GRADE)
    if arm.get("zero_reason"):
        row["zero_reason"] = arm["zero_reason"]
    return row


def verdict(led):
    v = {}

    # Q1 (b84 rule 1): is the LIVE threshold binding at all?
    v["live_gate_is_noop"] = {
        "legs_where_dropped_book_empty": sum(
            1 for w in LEGS
            if led[w]["dropped_conf_live"]["ladder_ts"]["trades"] == 0),
        "of": len(LEGS),
        "signals_killed_at_live_per_leg": {
            w: led[w]["_signals_killed_at_live"] for w in LEGS},
    }

    # Q2 the band: how much of the book COULD the rule take if the threshold
    # were pushed to the practical ceiling? (upper bound on the gate's power)
    v["always_kill_share_of_signals"] = {
        w: (round(led[w]["_signals_killed_at_099"] / led[w]["_signals_never_kill"], 3)
            if led[w]["_signals_never_kill"] else None) for w in LEGS}

    # Q3 the CLIFF in threshold space: the smallest t that kills >10% / >50%
    # of the live trade population, per window, chronologically read.
    cliff = {}
    for w in CHRONO:
        lad = led[w]["_ladder"]
        def first_over(frac):
            return next((t for t in LADDER_CONF
                         if (lad[str(t)]["kill_share"] or 0) > frac), None)
        cliff[w] = {"kill_share_by_conf": {str(t): lad[str(t)]["kill_share"]
                                           for t in LADDER_CONF},
                    "conf_killing_gt10pct": first_over(0.10),
                    "conf_killing_gt50pct": first_over(0.50)}
    v["cliff_by_conf"] = cliff

    # Q4 (b81) does loosening (t<live) or tightening (t>live) pay on exp_R
    # without giving up net_R? Both directions measured; nothing wired.
    pays = {}
    for t in LADDER_CONF:
        if t == LIVE_CONF:
            continue
        rows = []
        for w in CHRONO:
            lad = led[w]["_ladder"][str(t)]
            rows.append({"window": w, "d_exp_R": lad["d_exp_R_vs_live"],
                         "d_net_R": lad["d_net_R_vs_live"],
                         "d_dd_R": lad["d_dd_R_vs_live"],
                         "gate_trades": lad["gate_trades"],
                         "kill_share": lad["kill_share"]})
        pays[str(t)] = {
            "chronological_d_exp_R": [r["d_exp_R"] for r in rows],
            "chronological_d_net_R": [r["d_net_R"] for r in rows],
            "windows_paying_exp_R": sum(1 for r in rows
                                         if (r["d_exp_R"] or 0) > 0),
            "of": len(rows),
            "total_net_R_delta": round(sum(r["d_net_R"] for r in rows
                                           if r["d_net_R"] is not None), 1),
            "per_window": rows}
    v["move_by_conf"] = pays

    # Q5 (b83 integrity): the live row must reproduce b80's gradeB_rr15 —
    # same funnel, same gates, same harness. Any diff = this round drifted.
    par = json.load(open(PARITY))["legs"]
    v["parity_vs_b80"] = {}
    for w in LEGS:
        a = led[w][f"gate_conf_{LIVE_CONF}"]["ladder_ts"]
        b = par[w]["gradeB_rr15"]
        v["parity_vs_b80"][w] = {
            "match": (a["trades"] == b["trades"]
                      and a["exp_R"] == b["exp_R"]
                      and a["net_R"] == b["net_R"]),
            "this_round": {k: a[k] for k in ("trades", "exp_R", "net_R")},
            "b80": {k: b[k] for k in ("trades", "exp_R", "net_R")}}
    v["parity_all_match"] = all(x["match"] for x in v["parity_vs_b80"].values())

    # Q6 reachability: can any adaptive path ever move this knob?
    from engines.learning import adjustments
    adj = adjustments()
    v["adaptive_reach"] = {
        "learning_changes_keys": sorted((adj.get("changes") or {}).keys()),
        "learning_can_move_range_kill": "range_kill_conf" in (adj.get("changes") or {}),
        "live_value_is_literal_in": "hermes_runtime.build_live_plan (0.35)",
        "note": ("min_rr had a reachable cliff (learning steps +0.25); this "
                 "knob has NO adaptive path at all — it can only move by an "
                 "operator edit, so its no-op status is permanent unless a "
                 "human changes the literal."),
    }

    # Q7 (b86's own question) REDUNDANCY: is the gate's kill population
    # already removed by another live gate? If the max-kill set is 100% C-grade
    # and its live-gated book is empty while its UNGATED book trades, the rule
    # is fully shadowed by MIN_SETUP_GRADE — it can never be the reason a trade
    # is skipped, so it is not an independent risk control.
    red = {}
    for w in LEGS:
        L = led[w]
        mix = L["_killed_at_099_grade_mix"]
        ung = L["dropped_conf_099_ungated"]["ladder_ts"]
        lg = L["dropped_conf_099_livegates"]["ladder_ts"]
        red[w] = {"killed_signals": L["_signals_killed_at_099"],
                  "killed_grade_mix": mix,
                  "all_killed_are_C": set(mix) <= {"C"},
                  "ungated_book_trades": ung["trades"],
                  "ungated_book_exp_R": ung["exp_R"],
                  "ungated_book_net_R": ung["net_R"],
                  "live_gated_book_trades": lg["trades"]}
    v["redundancy"] = red
    v["fully_shadowed_by_grade_gate"] = all(
        r["all_killed_are_C"] and r["live_gated_book_trades"] == 0
        for r in red.values())

    # b78 mix of the live book per leg
    v["mix"] = {w: led[w][f"gate_conf_{LIVE_CONF}"]["_mix"] for w in LEGS}
    return v


def main():
    led = {"_note": "b86 (b68 round 19): the range-kill confidence gate measured "
                    "as BOOKS (kept vs dropped at the live 0.35) plus the "
                    "counterfactual threshold ladder (0.0 never-kill .. 0.99 "
                    "always-kill), on cached+W1..W4, under the b71 harness with "
                    "the b80 live gates imported. Read-only; no gate moved; a "
                    "recommendation here is a PROPOSAL for a human.",
           "_live_gates": {"MIN_RISK_REWARD": MIN_RISK_REWARD,
                           "MIN_SETUP_GRADE": MIN_SETUP_GRADE,
                           "RANGE_KILL_CONF": LIVE_CONF},
           "_conf_ladder": list(LADDER_CONF),
           "_harness": "b71 (plain/ladder/ladder_ts, live spread 0.20, live 36h "
                       "time exit) + b80 gates + b78 mix + b77 chrono read + "
                       "b74 all-windows rule + b83 reproduce-b80 check"}
    c = json.load(open("data/backtest/ab_aggressive_data.json"))
    print("##### cached (in-sample, informational) #####", flush=True)
    led["cached"] = measure_leg("cached", c["M15"], c["H1"], c["H4"])
    wins = json.load(open("data/backtest/b68l_independent_windows.json"))
    for w in WINDOWS:
        print(f"##### {w} #####", flush=True)
        led[w] = measure_leg(w, wins[w]["M15"], wins[w]["H1"], wins[w]["H4"])
    led["_verdict"] = verdict(led)

    print("\n=== the threshold ladder (gate_conf_<t> ladder_ts: exp_R / n) ===")
    print(f"{'leg':8s} " + " ".join(f"{('t=' + str(t)):>16s}" for t in LADDER_CONF))
    for leg in LEGS:
        cells = [led[leg][f"gate_conf_{t}"]["ladder_ts"] for t in LADDER_CONF]
        print(f"{leg:8s} " + " ".join(
            f"{(c['exp_R'] if c['exp_R'] is not None else float('nan')):>10.3f}"
            f"/{c['trades']:<5d}" for c in cells))
    print("\n=== signals KILLED by the gate at each threshold (raw signal count) ===")
    for leg in LEGS:
        L = led[leg]
        print(f"{leg:8s} never={L['_signals_never_kill']:5d} live={L['_signals_live']:5d} "
              f"killed@live={L['_signals_killed_at_live']:4d} killed@0.99={L['_signals_killed_at_099']:4d}"
              f" killed_grade_mix={L['_killed_at_099_grade_mix']}")
    print("\n=== VERDICT ===")
    print(json.dumps(led["_verdict"], indent=1))
    json.dump(led, open(OUT, "w"), indent=1)
    print("\nsaved:", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
