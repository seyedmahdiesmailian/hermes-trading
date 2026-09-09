#!/usr/bin/env python3
"""b81 — RE-SCORE THE b70 LANE DECISION SET AGAINST THE CORRECTED (b80) BAR.

Why this item exists (b80, 2026-09-05): the b71 harness `run_arm()` used to
pass only `min_rr` to `backtest_ohlc` and never `min_grade`, while the live
executor rejects anything below MIN_SETUP_GRADE="B". b80 fixed the harness
default, so the funnel baseline moved from 0.521-0.532 to 0.662-0.767 on
W1-W4. b81's founding note predicted the lanes would be "unaffected" because
lab arms all declare grade "B".

THE NOTE'S PREMISE IS WRONG, AND THAT IS THE FINDING. Every shipped lane row
is `funnel(row) or arm(row)` — the funnel's OWN signals are the lane's primary
source, and those signals carry grades A/B/C. So the lane inherited the same
C-grade trades the live executor rejects: the lane was NOT unaffected by b80,
it was inflated by exactly the same bug, and comparing a shipped (ungraded)
lane against b80's gradeB column is apples-to-oranges.

So b81 does not just re-read the ledgers; it re-MEASURES each lane under the
live grade gate, on the same bars, same harness, same exit ladder, and puts
graded lane against graded funnel. Read-only research: nothing here is
imported by the live trading path, and no gate is weakened — the gate is only
applied where it was previously missing.

Lanes re-scored (the four that ever reached b70's decision set):
  lane_gated_pdh_dayext  round 9/11  (b68l)  funnel-first + pdh x day-extension
  lane_h4pdh             round 12-14 (b68n4) funnel-first + pdh x H4-trend
  lane_runway            round 16    (b68p)  funnel-first + pdh x weekly runway
  lane_nr7htf            round 17    (b68q)  funnel-first + nr7 x H4-trend

Each lane is measured TWICE per leg — min_grade=None (reproduce the shipped
row, an integrity check against the ledgers) and min_grade=live (the honest
row) — and compared against the funnel measured the same two ways.
"""
import os
import sys
import json
import bisect

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                    # noqa: E402
from engines.auto_executor import MIN_SETUP_GRADE         # noqa: E402
from engines.backtest_real import (strategy_signal,      # noqa: E402
                                   m5_window_for, M5_BAR_SECONDS)
from scripts import b68l_windows as wl                    # noqa: E402

OUT = "data/backtest/b81_lane_rescore.json"
LEGS = ("cached", "W1", "W2", "W3", "W4")
WINDOWS = ("W1", "W2", "W3", "W4")

# lane name -> (shipped ledger file, shipped lane key, shipped funnel key)
PROVENANCE = {
    "lane_gated_pdh_dayext": ("b68l_independent_confirm",
                              "lane_funnel_then_gated"),
    "lane_h4pdh": ("b68n4_fourth_draw", "lane_funnel_then_h4pdh"),
    "lane_runway": ("b68p_runway_confirm", "lane_funnel_then_runway"),
    "lane_nr7htf": ("b68q_nr7htf_confirm", "lane_funnel_then_nr7htf"),
}


# b194: the M5 confirmation source for M15-spaced legs. b187 made the live
# trigger an M5 3-close confirmation, and b193b made it fail-CLOSED when no
# M5 rows are visible. An M15 leg has no M5 stream of its own, so a funnel
# measured without one prices trades live can never take — b194 measured
# exactly that: the cached M15 leg goes 102 trades -> 0 under the shipped
# gate. `m5_stream` threads the broker's settled M5 bars (b182_m5_bars covers
# the whole cached window) through the SAME window builder live uses, so the
# leg is scored against the rule live actually runs. Default None keeps every
# pre-b194 call site byte-identical on purpose; nothing silently changes under
# a ledger that was certified without it.
M5_SOURCE = "data/backtest/b182_m5_bars.json"


def m5_source_rows(path: str = M5_SOURCE) -> list[dict]:
    """The broker's settled M5 OHLC, as dicts `m5_window_for` can bisect.
    Same normalisation b189's arm-B used (tuple rows -> dict rows)."""
    blob = json.load(open(os.path.join(_ROOT, path)))
    blob = blob["bars"] if isinstance(blob, dict) else blob
    out = []
    for r in blob:
        if isinstance(r, dict):
            out.append(r)
        else:
            out.append({"time": r[0], "high": r[1], "low": r[2], "close": r[3]})
    return out


def funnel_fn(m15, h1, h4, m5_stream=None):
    """The exact live-parity funnel, evaluated once per leg (b76: same bars).

    m5_stream=None -> no confirmation rows (pre-b194 behavior, byte-identical).
    Pass m5_source_rows() to score an M15-spaced leg against b187's trigger.
    """
    h1t = [r.get("time", 0) for r in h1]
    h4t = [r.get("time", 0) for r in h4]
    idx = {r["time"]: n for n, r in enumerate(m15)}
    m5t = [int(r.get("time", 0)) for r in (m5_stream or [])]
    # The decision moment is the entry bar's CLOSE, so the settled-M5 window is
    # cut at time + bar_spacing — exactly what engines.backtest_real.run_backtest
    # does. Inferred from the entry stream's own spacing (b189 rule), never a
    # hardcoded 900 that would silently rot if a leg changed timeframe.
    gaps = sorted(int(m15[i + 1]["time"]) - int(m15[i]["time"])
                  for i in range(len(m15) - 1)
                  if isinstance(m15[i].get("time"), (int, float))
                  and isinstance(m15[i + 1].get("time"), (int, float)))
    gaps = [g for g in gaps if g > 0]
    bar_spacing = gaps[len(gaps) // 2] if gaps else M5_BAR_SECONDS
    sigs = {}
    for i, row in enumerate(m15):
        bt = row.get("time", 0)
        j1 = bisect.bisect_right(h1t, bt)
        j4 = bisect.bisect_right(h4t, bt)
        _m5 = (m5_window_for(m5_stream, m5t, int(bt) + bar_spacing)
               if m5_stream else None)
        s = strategy_signal(row, h1[max(0, j1 - 80):j1],
                            h4[max(0, j4 - 80):j4], i,
                            m15_window=m15[max(0, i - 120):i + 1],
                            m5_rows=_m5, derive_m5=_m5 is None)
        if s:
            sigs[i] = s

    def fn(row):
        return sigs.get(idx.get(row.get("time"), -1))
    return fn


def lane_factories():
    """The four b70 lane arms, geometry and oracle VERBATIM from their round's
    module (b72 rule 1: pure intersection, nothing retuned here).

    Each factory BINDS its own ingredient modules and returns the row->signal
    closure. Binding is done per lane, immediately before that lane is
    measured: b68j/b68m/b68p all mutate the SAME shared `b68e_pdh_lab` tables
    (M15/IDX/LEVELS), so binding them all up front would let the last binder
    silently redefine the others' level tables. One lane, one bind, one
    measurement — no cross-lane state leak.
    """
    from scripts import b68j_dayext_pdh_lab as j9
    from scripts import b68m_htf_pdh_lab as mm
    from scripts import b68p_runway_lab as rp
    from scripts import b68q_nr7htf_lab as q

    def gated_pdh_dayext(m15, h1, h4, funnel):
        j9.rebind(m15)
        return lambda row: funnel(row) or j9.wrap(
            lambda i: j9.combo(i, j9.EXT))(row)

    def h4pdh(m15, h1, h4, funnel):
        mm.rebind(m15, h1, h4)
        return lambda row: funnel(row) or mm.wrap(
            lambda i: mm.gated(i, mm.H4P))(row)

    def runway(m15, h1, h4, funnel):
        rp.bind(m15)
        return lambda row: funnel(row) or rp.indexed(
            lambda i: rp.gated(i, True, rp.ROOM))(row)

    def nr7htf(m15, h1, h4, funnel):
        prep = q.bind(m15, h1, h4)
        return lambda row: funnel(row) or q.indexed(
            lambda i: q.gated(i, prep, "agree"))(row)

    return {"lane_gated_pdh_dayext": gated_pdh_dayext,
            "lane_h4pdh": h4pdh,
            "lane_runway": runway,
            "lane_nr7htf": nr7htf}


LANE_BUILDERS = lane_factories()


def _row(res):
    r = res["ladder_ts"]
    return {"trades": r["trades"], "exp_R": r["exp_R"], "net_R": r["net_R"],
            "WR%": r["WR%"], "maxDD_R": r["maxDD_R"],
            "mean_hold_bars": r["mean_hold_bars"]}


def measure_leg(name, m15, h1, h4):
    funnel = funnel_fn(m15, h1, h4)
    out = {"_bars": len(m15), "_first": int(m15[0]["time"]),
           "_last": int(m15[-1]["time"])}
    # The funnel, both conventions. Measured BEFORE any lane binds a shared
    # module: strategy_signal takes its bars as arguments, so it is immune to
    # the lab modules' globals, but ordering keeps the intent obvious.
    out["funnel_graded"] = _row(lh.run_arm(m15, funnel))
    out["funnel_ungraded"] = _row(lh.run_arm(m15, funnel, min_grade=None))
    for lane_name, build in LANE_BUILDERS.items():
        fn = build(m15, h1, h4, funnel)
        # ungraded first: reproduces the shipped ledger row (integrity check)
        out[lane_name] = {
            "ungraded": _row(lh.run_arm(m15, fn, min_grade=None)),
            "graded": _row(lh.run_arm(m15, fn)),
        }
        out[lane_name]["graded_vs_graded_funnel"] = delta(
            out[lane_name]["graded"], out["funnel_graded"])
        out[lane_name]["ungraded_vs_ungraded_funnel"] = delta(
            out[lane_name]["ungraded"], out["funnel_ungraded"])
    return out


def delta(lane, fun):
    """The b70 capacity question in one dict: does the lane earn its slot?
    exp_R is the quality axis, net_R the volume axis, maxDD_R the risk axis,
    marginal_R_per_extra_trade what the extra trades actually paid."""
    dn = lane["trades"] - fun["trades"]
    return {
        "d_exp_R": _r(lane["exp_R"], fun["exp_R"], "exp_R"),
        "d_net_R": _r(lane["net_R"], fun["net_R"], "net_R"),
        "d_trades": dn,
        "d_dd_R": _r(lane["maxDD_R"], fun["maxDD_R"], "maxDD_R"),
        "marginal_R_per_extra_trade": (
            round((lane["net_R"] - fun["net_R"]) / dn, 3) if dn else None),
        "beats_funnel_exp_R": (lane["exp_R"] is not None
                               and fun["exp_R"] is not None
                               and lane["exp_R"] > fun["exp_R"]),
        "beats_funnel_net_R": lane["net_R"] > fun["net_R"],
    }


def _r(a, b, _axis):
    return round(a - b, 3) if (a is not None and b is not None) else None


def verdict(led):
    """b74's all-windows rule applied to LANES: a lane earns a slot only if it
    beats the graded funnel on exp_R in EVERY independent window. The cached
    leg is informational (b76: it is the in-sample regime)."""
    v = {}
    for lane in PROVENANCE:
        wins = []
        for w in WINDOWS:
            leg = led[w][lane]
            wins.append({"window": w,
                         "lane_exp_R": leg["graded"]["exp_R"],
                         "funnel_exp_R": led[w]["funnel_graded"]["exp_R"],
                         "d_exp_R": leg["graded_vs_graded_funnel"]["d_exp_R"],
                         "d_net_R": leg["graded_vs_graded_funnel"]["d_net_R"],
                         "marginal_R": leg["graded_vs_graded_funnel"]
                         ["marginal_R_per_extra_trade"],
                         "beats": leg["graded_vs_graded_funnel"]
                         ["beats_funnel_exp_R"]})
        v[lane] = {
            "windows_beaten": sum(1 for x in wins if x["beats"]),
            "of": len(wins),
            "replicated_all_windows": all(x["beats"] for x in wins),
            "marginal_R_positive_windows": sum(
                1 for x in wins
                if x["marginal_R"] is not None and x["marginal_R"] > 0),
            "per_window": wins,
            "cached": {"lane_exp_R": led["cached"][lane]["graded"]["exp_R"],
                       "funnel_exp_R": led["cached"]["funnel_graded"]["exp_R"],
                       "d_exp_R": led["cached"][lane][
                           "graded_vs_graded_funnel"]["d_exp_R"]},
        }
    return v


def main():
    wins = wl.load_windows()
    c = json.load(open("data/backtest/ab_aggressive_data.json"))
    led = {"_note": "b81: lanes re-measured UNDER the live grade gate (b80 "
                    "fix) on cached + W1..W4, same bars/harness/ladder as the "
                    "shipped ledgers. Founding premise corrected: the shipped "
                    "lane rows were NOT unaffected by b80 — a lane is "
                    "funnel-first, so it carried the funnel's C-grade trades "
                    "too. Both conventions ship per leg so the delta is "
                    "auditable without re-running.",
           "_live_min_grade": MIN_SETUP_GRADE,
           "_last6000_overlap_with_cached": wins.get(
               "_last6000_overlap_with_cached"),
           "_provenance": {k: v[0] for k, v in PROVENANCE.items()}}
    print("##### cached (in-sample, informational) #####", flush=True)
    led["cached"] = measure_leg("cached", c["M15"], c["H1"], c["H4"])
    for w in WINDOWS:
        print(f"##### {w} #####", flush=True)
        led[w] = measure_leg(w, wins[w]["M15"], wins[w]["H1"], wins[w]["H4"])
    led["_verdict"] = verdict(led)
    print("=== VERDICT ===")
    print(json.dumps(led["_verdict"], indent=1))
    json.dump(led, open(OUT, "w"), indent=1)
    print("saved:", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
