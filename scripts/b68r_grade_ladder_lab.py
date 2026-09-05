#!/usr/bin/env python3
"""b68 round 18 (b68r) — THE GRADE LADDER ITSELF, MEASURED AS BOOKS.

Why this round exists. b80 found that the lab's funnel baseline had been
measured WITHOUT the live grade gate, and that adding it moved the bar by
+0.15..+0.24R per window — because the funnel emits 58-67% C-grade signals per
leg (cached 542/848, W1 893/1429, W2 1021/1544, W3 1030/1767, W4 1167/1745)
that the LIVE executor rejects at auto_executor Check 6. That made the grade
gate the single largest measured lever in the system, and it made the NEXT
question unavoidable and unmeasured:

    MIN_SETUP_GRADE is a knob with three positions. Live sits on "B".
    What are the A, B and C POPULATIONS worth as separate books, and what
    exactly does tightening B -> A buy and cost?

The only prior answer is the 2026-08-30 grade-gate audit, which is now
superseded on three counts: it measured DOLLARS per trade on M5 windows (not R
under the live exit ladder), it ran with min_grade=None so C setups were
traded, and it predates b80's corrected harness and b71's time exit. Its
headline — B earned MORE dollars/trade than A — has never been tested in R.

This round measures the funnel's own entries as four separate books on the
b71 harness (plain / ladder / ladder_ts, live spread, live time exit) and then
the two counterfactuals on the LIVE gate:

  book_A      only grade-A signals          (what the top rung earns alone)
  book_B      only grade-B signals          (what live keeps and A-tightening drops)
  book_C      only grade-C signals          (what the live gate already drops)
  gateA       the funnel with min_grade="A" (the tightening counterfactual)
  gateB       the funnel with min_grade="B" (= live, the incumbent)
  gateC(None) the funnel ungated            (the no-gate counterfactual)

A book is measured under the SAME one-position-at-a-time model, so its n is
"trades this population would take if it owned the slot", not a slice of the
live trade log — the slot-contention effect is exactly what the gateA/gateB
rows price.

Discipline carried from the loop (each is a rule this file was written under):
  b71  every arm gets plain/ladder/ladder_ts + hold columns; quote ladder_ts.
  b74  a claim must replicate on ALL FOUR independent windows; cached is the
       in-sample regime and is informational only (b76).
  b77  read the margin series CHRONOLOGICALLY (W4 oldest -> W1 newest) before
       spending a draw on it; a monotone ramp is regime, not edge.
  b78  every leg carries the BUY/SELL mix of the trades it actually took — a
       grade book whose mix flips by window is a direction bet, not a rung.
  b83  this round re-MEASURES; it does not re-read b80's rows against a new bar.

HARD RULES honoured: read-only research, nothing imported by the live path, no
gate is weakened anywhere (the tightening direction is measured, never wired),
and the recommendation this file can produce is a PROPOSAL for a human.
"""
import os
import sys
import json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                 # noqa: E402
from engines.auto_executor import MIN_SETUP_GRADE      # noqa: E402
from scripts.b80_gate_parity import funnel_signals     # noqa: E402  (b83: reuse, never re-implement)

OUT = "data/backtest/b68r_grade_ladder.json"
WINDOWS = ("W1", "W2", "W3", "W4")            # b74's independent draws
CHRONO = ("W4", "W3", "W2", "W1")             # b77: oldest -> newest
BOOKS = ("A", "B", "C")


# ── the three books ────────────────────────────────────────────────────────
def book_fn(sigs, idx_of, grade):
    """Funnel signals restricted to ONE grade — a book that owns the slot."""
    def fn(row):
        s = sigs.get(idx_of.get(int(row.get("time", 0)), -1))
        if not s:
            return None
        return s if str(s.get("grade") or "").upper() == grade else None
    return fn


def side_mix(rows, fn, min_grade=None):
    """BUY/SELL split of the trades this fn ACTUALLY takes (b78: raw signal
    counts would lie, because the one-position model changes the mix)."""
    res = lh.backtest_ohlc(rows, fn, spread=lh.SPREAD, **lh.LADDER,
                           time_stop_bars=lh.live_time_stop_bars(rows),
                           min_grade=min_grade)
    sides = [str(t["side"]).upper() for t in res.get("trade_log", [])]
    return {"buy": sides.count("BUY"), "sell": sides.count("SELL"),
            "trades": len(sides)}


def _row(res_row):
    return {"trades": res_row["trades"], "exp_R": res_row["exp_R"],
            "net_R": res_row["net_R"], "WR%": res_row["WR%"],
            "maxDD_R": res_row["maxDD_R"],
            "mean_hold_bars": res_row["mean_hold_bars"]}


def _atr14_mean(rows, n=14):
    """Mean true range over the leg — the dollars-per-R unit, so a total-R
    claim can be read against the leg's own volatility regime."""
    trs = []
    for i in range(1, len(rows)):
        h, l, pc = (float(rows[i]["high"]), float(rows[i]["low"]),
                    float(rows[i - 1]["close"]))
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return (sum(trs) / len(trs)) if trs else 0.0


def measure_leg(name, m15, h1, h4):
    sigs = funnel_signals(m15, h1, h4)
    idx_of = {int(r["time"]): i for i, r in enumerate(m15)}
    graded = {g: sum(1 for s in sigs.values()
                     if str(s.get("grade") or "").upper() == g) for g in BOOKS}
    out = {"_bars": len(m15), "_first": int(m15[0]["time"]),
           "_last": int(m15[-1]["time"]), "_signals": len(sigs),
           "_atr_mean": round(_atr14_mean(m15), 3),
           "_signal_grade_mix": graded}

    # the books: each population measured as if it owned the single slot
    for g in BOOKS:
        fn = book_fn(sigs, idx_of, g)
        arm = lh.run_arm(m15, fn, min_grade=None)
        out["book_" + g] = {m: _row(arm[m]) for m in ("plain", "ladder", "ladder_ts")}
        out["book_" + g]["_time_stop_bars"] = arm["_time_stop_bars"]
        out["book_" + g]["_mix"] = side_mix(m15, fn)
        if arm.get("zero_reason"):
            out["book_" + g]["zero_reason"] = arm["zero_reason"]

    # the gate counterfactuals on the whole funnel
    def all_fn(row):
        return sigs.get(idx_of.get(int(row.get("time", 0)), -1))
    for label, mg in (("gateA", "A"), ("gateB", MIN_SETUP_GRADE),
                      ("gateC_ungated", None)):
        arm = lh.run_arm(m15, all_fn, min_grade=mg)
        out[label] = {m: _row(arm[m]) for m in ("plain", "ladder", "ladder_ts")}
        out[label]["_time_stop_bars"] = arm["_time_stop_bars"]
        out[label]["_mix"] = side_mix(m15, all_fn, min_grade=mg)

    # b78 taken to its end: is the A/B flip a RUNG property or a DIRECTION
    # property? Measure each grade book split by side (same slot model, same
    # exit ladder, one run per cell — the signals are already computed).
    out["_side_split"] = {}
    for g in BOOKS:
        for side in ("BUY", "SELL"):
            def sfn(row, _g=g, _s=side, _sigs=sigs, _idx=idx_of):
                s = _sigs.get(_idx.get(int(row.get("time", 0)), -1))
                if not s:
                    return None
                if str(s.get("grade") or "").upper() != _g:
                    return None
                return s if str(s.get("side", "")).upper() == _s else None
            res = lh.backtest_ohlc(m15, sfn, spread=lh.SPREAD, **lh.LADDER,
                                   time_stop_bars=lh.live_time_stop_bars(m15),
                                   min_grade=None)
            out["_side_split"][f"{g}_{side.lower()}"] = lh.r_stats(
                res, time_stop_bars=lh.live_time_stop_bars(m15))

    # the two questions the live operator actually asks, in R
    a, b, c = (out["book_A"]["ladder_ts"], out["book_B"]["ladder_ts"],
               out["book_C"]["ladder_ts"])
    gA, gB, gC = (out["gateA"]["ladder_ts"], out["gateB"]["ladder_ts"],
                  out["gateC_ungated"]["ladder_ts"])
    out["_ladder"] = {
        "A_minus_B_exp_R": _d(a["exp_R"], b["exp_R"]),
        "B_minus_C_exp_R": _d(b["exp_R"], c["exp_R"]),
        "A_over_B_selection": (a["exp_R"] is not None and b["exp_R"] is not None
                               and a["exp_R"] > b["exp_R"]),
        "B_over_C_selection": (b["exp_R"] is not None and c["exp_R"] is not None
                               and b["exp_R"] > c["exp_R"]),
        # tightening B -> A: what the dropped (B) book paid, per trade it held
        "tighten_d_exp_R": _d(gA["exp_R"], gB["exp_R"]),
        "tighten_d_net_R": _d(gA["net_R"], gB["net_R"]),
        "tighten_d_trades": gA["trades"] - gB["trades"],
        "tighten_d_dd_R": _d(gA["maxDD_R"], gB["maxDD_R"]),
        "tighten_kept_share": (round(gA["trades"] / gB["trades"], 3)
                               if gB["trades"] else None),
        # b81's rule: quote exp_R and net_R TOGETHER, and price the marginal
        # trade. Loosening B -> C adds trades; what did each extra one pay?
        # Negative marginal = the extra volume is worth less than nothing.
        "loosen_d_exp_R": _d(gC["exp_R"], gB["exp_R"]),
        "loosen_d_net_R": _d(gC["net_R"], gB["net_R"]),
        "loosen_d_trades": gC["trades"] - gB["trades"],
        "loosen_d_dd_R": _d(gC["maxDD_R"], gB["maxDD_R"]),
        "loosen_marginal_R_per_extra_trade": (
            round((gC["net_R"] - gB["net_R"]) / (gC["trades"] - gB["trades"]), 3)
            if gC["trades"] != gB["trades"] else None),
        "tighten_marginal_R_per_dropped_trade": (
            round((gB["net_R"] - gA["net_R"]) / (gB["trades"] - gA["trades"]), 3)
            if gB["trades"] != gA["trades"] else None),
    }
    return out


def _d(x, y):
    return round(x - y, 3) if (x is not None and y is not None) else None


# ── verdict: b74's all-windows rule + b77's chronological read ─────────────
def verdict(led):
    v = {}

    # Q1 does the grade ladder RANK the books? (A > B > C on every window)
    for pair in ("A_vs_B", "B_vs_C"):
        wins = []
        for w in CHRONO:
            lad = led[w]["_ladder"]
            val = (lad["A_over_B_selection"] if pair == "A_vs_B"
                   else lad["B_over_C_selection"])
            margin = (lad["A_minus_B_exp_R"] if pair == "A_vs_B"
                      else lad["B_minus_C_exp_R"])
            wins.append({"window": w, "holds": bool(val), "margin_exp_R": margin})
        v[pair] = {"windows_holding": sum(1 for x in wins if x["holds"]),
                   "of": len(wins),
                   "replicated_all_windows": all(x["holds"] for x in wins),
                   "chronological_margins": [x["margin_exp_R"] for x in wins],
                   "per_window": wins}

    # Q2 does tightening B -> A pay? (needs exp_R up on ALL windows, and the
    # volume cost stated in net_R, never hidden)
    wins = []
    for w in CHRONO:
        lad = led[w]["_ladder"]
        wins.append({"window": w,
                     "gateA_exp_R": led[w]["gateA"]["ladder_ts"]["exp_R"],
                     "gateB_exp_R": led[w]["gateB"]["ladder_ts"]["exp_R"],
                     "d_exp_R": lad["tighten_d_exp_R"],
                     "d_net_R": lad["tighten_d_net_R"],
                     "d_trades": lad["tighten_d_trades"],
                     "d_dd_R": lad["tighten_d_dd_R"],
                     "kept_share": lad["tighten_kept_share"],
                     "pays": (lad["tighten_d_exp_R"] is not None
                              and lad["tighten_d_exp_R"] > 0)})
    v["tighten_B_to_A"] = {
        "windows_paying": sum(1 for x in wins if x["pays"]),
        "of": len(wins),
        "replicated_all_windows": all(x["pays"] for x in wins),
        "chronological_d_exp_R": [x["d_exp_R"] for x in wins],
        "total_net_R_given_up": round(sum(x["d_net_R"] for x in wins
                                          if x["d_net_R"] is not None), 1),
        "total_trades_given_up": sum(x["d_trades"] for x in wins),
        "per_window": wins,
    }

    # Q3 is the live gate (B over C) earning its keep, measured as books?
    v["live_gate_C_out"] = {
        "windows_where_C_loses": sum(
            1 for w in CHRONO
            if led[w]["_ladder"]["B_minus_C_exp_R"] is not None
            and led[w]["_ladder"]["B_minus_C_exp_R"] > 0),
        "of": len(CHRONO),
        "chronological_B_minus_C": [led[w]["_ladder"]["B_minus_C_exp_R"]
                                    for w in CHRONO],
    }

    # Q3b the SAME gate read on TOTAL R (b81's rule: never quote one axis alone)
    v["live_gate_C_total_R"] = {
        "windows_where_ungated_earns_more_net_R": sum(
            1 for w in CHRONO
            if led[w]["_ladder"]["loosen_d_net_R"] is not None
            and led[w]["_ladder"]["loosen_d_net_R"] > 0),
        "of": len(CHRONO),
        "chronological_loosen_d_net_R": [led[w]["_ladder"]["loosen_d_net_R"]
                                         for w in CHRONO],
        "chronological_marginal_R_per_extra_trade": [
            led[w]["_ladder"]["loosen_marginal_R_per_extra_trade"]
            for w in CHRONO],
        "chronological_loosen_d_dd_R": [led[w]["_ladder"]["loosen_d_dd_R"]
                                        for w in CHRONO],
    }

    # Q4 is the A/B flip a rung property or a direction property? (b78)
    v["grade_by_side"] = {}
    for g in BOOKS:
        v["grade_by_side"][g] = {
            w: {side: led[w]["_side_split"][f"{g}_{side}"]["exp_R"]
                for side in ("buy", "sell")}
            for w in CHRONO}
        v["grade_by_side"][g]["n_by_window"] = {
            w: {side: led[w]["_side_split"][f"{g}_{side}"]["trades"]
                for side in ("buy", "sell")}
            for w in CHRONO}

    # b78 mix disclosure per book per leg
    v["mix"] = {w: {("book_" + g): led[w]["book_" + g]["_mix"] for g in BOOKS}
                for w in ("cached",) + WINDOWS}
    return v


def main():
    led = {"_note": "b68 round 18: the funnel's own grade ladder measured as "
                    "separate books (A/B/C) plus the gate counterfactuals "
                    "(gateA/gateB=live/gateC=ungated) on cached+W1..W4 under "
                    "the b71 harness with the b80 live gate imported. Read-only; "
                    "no gate changed; a tightening here is a PROPOSAL only.",
           "_live_min_grade": MIN_SETUP_GRADE,
           "_harness": "b71 (plain/ladder/ladder_ts, live spread 0.20, live "
                       "36h time exit) + b80 grade gate + b78 mix + b77 chrono "
                       "read + b74 all-windows rule"}
    c = json.load(open("data/backtest/ab_aggressive_data.json"))
    print("##### cached (in-sample, informational) #####", flush=True)
    led["cached"] = measure_leg("cached", c["M15"], c["H1"], c["H4"])
    wins = json.load(open("data/backtest/b68l_independent_windows.json"))
    for w in WINDOWS:
        print(f"##### {w} #####", flush=True)
        led[w] = measure_leg(w, wins[w]["M15"], wins[w]["H1"], wins[w]["H4"])
    led["_verdict"] = verdict(led)

    print("\n=== books (ladder_ts exp_R / n) ===")
    print(f"{'leg':8s} {'A':>16s} {'B':>16s} {'C':>16s} "
          f"{'gateA':>16s} {'gateB(live)':>16s} {'ungated':>16s}")
    for leg in ("cached",) + WINDOWS:
        L = led[leg]
        cells = [L["book_" + g]["ladder_ts"] for g in BOOKS]
        cells += [L["gateA"]["ladder_ts"], L["gateB"]["ladder_ts"],
                  L["gateC_ungated"]["ladder_ts"]]
        print(f"{leg:8s} " + " ".join(
            f"{(c['exp_R'] if c['exp_R'] is not None else float('nan')):>8.3f}"
            f"/{c['trades']:<5d}" for c in cells))
    print("\n=== VERDICT ===")
    print(json.dumps(led["_verdict"], indent=1))
    json.dump(led, open(OUT, "w"), indent=1)
    print("\nsaved:", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
