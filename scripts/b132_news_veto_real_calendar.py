#!/usr/bin/env python3
"""b132 — PRICE THE NEWS-VETO ON A REAL EVENT CALENDAR (finishes b107's leg).

WHAT b131 COULD NOT DO
======================
b131 built the machinery (the additive `news_veto_windows` dial, per-trade
entry/exit clock fields, the parity probe through the REAL
evaluate_macro_filter, the neutrality grid) but had to report its own step-3
premise as FALSE: the only calendar on the box (git union of committed
economic_calendar.json) spans Aug 23..Sep 12 2026, so six of seven legs had
COVERAGE ZERO and "inert" there was an absence of data, not a finding. Its
reusable lesson: intersect the gate's DATA window with the measurement windows
BEFORE designing the study.

THIS ROUND
==========
scripts/b132_event_archive_fetch.py recovered a real historical calendar from
the Internet Archive's crawl of the same ForexFactory feed. b132 shipped it
thin (95 daily snapshots, 1941 events, span 2026-05-03..); b133's harvest
re-queried the CDX by PREFIX (the exact-url query was blind to every
`?version=<hash>` capture, see the fetcher's docstring) and the same source
now yields 145 captured days from 2025-01-19, 5043 events, 303 high-impact
USD/XAU — ALL SEVEN legs covered. Step 0 of this script therefore does what
b131 skipped: it MEASURES coverage per leg
(events inside the leg, and the fraction of the leg's span inside the archive)
and only then prices. The veto arms are swept on the REAL calendar at live's
own ±30min and at four wider half-widths, on all seven legs, and the neutrality
verdict is computed over the COVERED legs only — a coverage-zero leg is
excluded from the vote, not silently averaged in as a zero. b133's harvest
adds the second exclusion the design had not anticipated: a leg can be
COVERED and still carry no evidence (W2 has 12 high events in span yet the
±30min veto deleted ZERO funnel entries there), so a sign claim must be read
over legs with n_vetoed_entries > 0, not over _covered_legs blindly.

PARITY (unchanged from b131, by construction)
=============================================
Windows come from probing the real `evaluate_macro_filter` at every bar
timestamp of the leg (its currency filter, its high-impact net, its fail-closed
branch), merged into (start,end) windows at bar granularity; the blackout
half-width is READ from the function's own signature, never restated. The OFF
arm is the b129/b130/b131 incumbent and integrity() demands it BYTE-IDENTICAL
against the frozen b129 ledger on all seven legs, so this grid is the same
funnel and the archive changed no code path.

NOTHING IS WIRED OR RETUNED. The veto stays exactly as live runs it; a live
gate change is a human gate (b89 class). The product is the price on real data
and the coverage census that says where that price is evidence and where it is
still an absence of data.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                      # noqa: E402
from engines.backtest import backtest_ohlc                 # noqa: E402
from scripts import b81_lane_rescore as b81                # noqa: E402
from scripts.b121_flat_share_replication import (          # noqa: E402
    LEGS, _rows_for)
from scripts.b129_timestop_reprice import (                # noqa: E402
    GATE_LIVE, INCUMBENT_STOP, one_sided_strict)
from scripts.b123_protection_share_decomposition import one_sided   # noqa: E402
from scripts.b131_news_veto_pricing import (               # noqa: E402
    LIVE_BLACKOUT_MIN, OFF, _incumbent_kw, veto_windows)

OUT = "data/backtest/b132_news_veto_real_calendar.json"
LEDGER_129 = "data/backtest/b129_timestop_reprice.json"
LEDGER_131 = "data/backtest/b131_news_veto_pricing.json"
ARCHIVE_GLOB = "data/calendar/events_archive_ff_wayback_*.json"

# half-widths swept on the REAL calendar: live's own, then wider.
WIDTHS_MIN = (LIVE_BLACKOUT_MIN, 120, 240, 720, 1440)
ARMS = tuple("real::±%dmin" % m for m in WIDTHS_MIN)
ARM_NAMES = (OFF,) + ARMS

# a leg counts toward the verdict only if at least this much of its span is
# inside the archive AND it holds at least this many high-impact gold events.
MIN_COVERAGE_FRAC = 0.50
MIN_HIGH_EVENTS = 5


def _span_days(cal: dict) -> float:
    """Days covered by an archive's event span (negative = unparseable)."""
    a, b = cal.get("event_first"), cal.get("event_last")
    try:
        return (dt.datetime.fromisoformat(str(b)[:10]) -
                dt.datetime.fromisoformat(str(a)[:10])).days
    except Exception:                                        # noqa: BLE001
        return -1.0


def load_archive() -> dict:
    """The WIDEST-span fetched archive on disk (b132_event_archive_fetch's
    product).

    b133: this used to be `sorted(glob)[-1]`, i.e. newest by filename. The
    filename carries the event span, so a re-fetch that reaches BACK further
    sorts EARLIER and the old rule would have silently priced the veto on the
    thin archive again. Span is the thing the study needs, so span picks it."""
    cal, path = _pick_archive()
    cal["_path"] = path
    return cal


def _pick_archive() -> tuple[dict, str]:
    paths = sorted(glob.glob(ARCHIVE_GLOB))
    if not paths:
        raise SystemExit("no event archive on disk — run "
                         "scripts/b132_event_archive_fetch.py first")
    cals = [(json.load(open(p)), p) for p in paths]
    return max(cals, key=lambda cp: (_span_days(cp[0]),
                                     int(cp[0].get("n_events") or 0)))


def coverage(cal: dict, first: int, last: int) -> dict:
    """b132's step 0: intersect the gate's DATA window with this leg FIRST."""
    ev = [e for e in cal["events"] if str(e.get("impact", "")).lower() == "high"
          and str(e.get("currency", "")).upper() in ("USD", "XAU", "GOLD")]
    ts = []
    for e in ev:
        try:
            d = dt.datetime.fromisoformat(str(e["date"]))
        except Exception:                                    # noqa: BLE001
            continue
        ts.append(d.timestamp())
    inside = [t for t in ts if first <= t <= last]
    a0 = min(ts) if ts else None
    a1 = max(ts) if ts else None
    if a0 is None or last < a0 or first > a1:
        frac = 0.0
    else:
        ov = min(last, a1) - max(first, a0)
        frac = ov / max(last - first, 1)
    return {"n_high_events_in_leg": len(inside),
            "n_high_events_archive": len(ts),
            "span_overlap_frac": round(frac, 3),
            "covered": bool(frac >= MIN_COVERAGE_FRAC
                            and len(inside) >= MIN_HIGH_EVENTS)}


def measure_leg(m15, h1, h4, cal: dict) -> dict:
    funnel = b81.funnel_fn(m15, h1, h4)
    ts = lh.live_time_stop_bars(m15)
    times = [int(r["time"]) for r in m15]
    grid, wins = {}, {}
    for arm in ARM_NAMES:
        if arm == OFF:
            kw, w = _incumbent_kw(), []
        else:
            half = int(arm.split("±")[1].rstrip("min"))
            w = veto_windows(times, cal, half)
            kw = dict(_incumbent_kw(), news_veto_windows=w)
        res = backtest_ohlc(m15, funnel, min_rr=lh.MIN_RR, spread=lh.SPREAD,
                            min_grade=lh.LIVE_MIN_GRADE, **kw)
        grid[arm] = lh.r_stats(res, time_stop_bars=ts)
        wins[arm] = [[a, b] for a, b in w]
        if arm == OFF:
            rows = [{"entry_time": int(t["entry_time"]),
                     "exit_time": int(t["exit_time"]),
                     "pnl": t["pnl"], "exit_reason": t["exit_reason"],
                     "r": round(t["pnl"] / max(abs(t["entry"] - t["orig_sl"]), 1e-9), 4)}
                    for t in res["trade_log"]]
    return {"_bars": len(m15), "_first": times[0], "_last": times[-1],
            "_time_stop_bars": ts, "grid": grid, "windows": wins,
            "off_rows": rows,
            "_coverage": coverage(cal, times[0], times[-1]),
            "_funnel": funnel}


def integrity(led, l129: dict) -> dict:
    checks = {}
    for leg in LEGS:
        off = led[leg]["grid"][OFF]
        inc129 = l129[leg]["grid"][f"{GATE_LIVE}::ts_{INCUMBENT_STOP}"]
        checks[leg] = {"off_matches_b129_incumbent": off == inc129}
    return checks


def vetoed_census(led) -> dict:
    out = {}
    for leg in LEGS:
        rows = {}
        for arm in ARMS:
            ws = [tuple(w) for w in led[leg]["windows"][arm]]
            hit = [r for r in led[leg]["off_rows"]
                   if any(a <= r["entry_time"] <= b for a, b in ws)]
            rows[arm] = {"n_vetoed_entries": len(hit),
                         "n_off_trades": len(led[leg]["off_rows"]),
                         "vetoed_R": round(sum(h["r"] for h in hit), 3),
                         "n_windows": len(ws)}
        out[leg] = rows
    return out


def deltas(led, metric="exp_R", nd=3) -> dict:
    out = {}
    for arm in ARMS:
        row = {}
        for leg in LEGS:
            a = led[leg]["grid"].get(arm, {}).get(metric)
            b = led[leg]["grid"][OFF].get(metric)
            row[leg] = (round(a - b, nd) if a is not None and b is not None else None)
        out[arm] = row
    return out


def covered_legs(led) -> list[str]:
    return [leg for leg in LEGS if led[leg]["_coverage"]["covered"]]


def neutrality(led) -> dict:
    """Vote on COVERED legs only — b132's correction of b131's premise."""
    cov = covered_legs(led)
    out = {}
    for arm in ARMS:
        d = deltas(led)[arm]
        vals = [d[leg] for leg in cov if d[leg] is not None]
        pos = sum(1 for v in vals if v > 0)
        neg = sum(1 for v in vals if v < 0)
        out[arm] = {"legs_voted": cov, "pos": pos, "neg": neg,
                    "n_nonzero": pos + neg,
                    "max_abs": round(max((abs(v) for v in vals), default=0.0), 3),
                    "mean": round(sum(vals) / len(vals), 4) if vals else None,
                    "one_sided": one_sided(pos, neg),
                    "one_sided_strict": one_sided_strict(pos, neg, len(vals))
                    if vals else False}
    return out


def verdict(led) -> dict:
    neu, cen = neutrality(led), vetoed_census(led)
    out = {}
    for arm in ARMS:
        n = neu[arm]
        out[arm] = {
            "n_vetoed_covered_legs": sum(cen[leg][arm]["n_vetoed_entries"]
                                         for leg in n["legs_voted"]),
            "n_vetoed_all_legs": sum(cen[leg][arm]["n_vetoed_entries"]
                                     for leg in LEGS),
            "n_nonzero": n["n_nonzero"],
            "max_abs_exp_R": n["max_abs"],
            "mean_exp_R": n["mean"],
            "one_sided": n["one_sided"],
            "one_sided_strict": n["one_sided_strict"],
            "clears_b119_ceiling": n["max_abs"] >= 0.10,
        }
    return out


def lever_test(led) -> dict:
    """b132's own guard: b119's 0.10R ceiling is a test on exp_R ALONE, and
    exp_R can rise purely because trades were REMOVED (a veto deletes entries,
    the survivors average better, total R falls). An arm is a LEVER only if it
    moves exp_R one-sidedly past the ceiling AND net_R does not go negative on
    the same legs AND maxDD_R is not worse. Without this block the ±720min arm
    reads as 'clears the ceiling' and invites exactly the wrong wiring."""
    neu, verdict_ = neutrality(led), verdict(led)
    dn, dd = deltas(led, "net_R", 1), deltas(led, "maxDD_R", 1)
    out = {}
    for arm in ARMS:
        cov = neu[arm]["legs_voted"]
        nets = [dn[arm][leg] for leg in cov if dn[arm][leg] is not None]
        dds = [dd[arm][leg] for leg in cov if dd[arm][leg] is not None]
        net_neg = sum(1 for v in nets if v < 0)
        dd_worse = sum(1 for v in dds if v > 0)
        out[arm] = {
            "exp_R_clears_ceiling": verdict_[arm]["clears_b119_ceiling"],
            "exp_R_one_sided": verdict_[arm]["one_sided_strict"],
            "n_legs_net_R_negative": net_neg,
            "n_legs_maxDD_worse": dd_worse,
            "exp_R_inflation_by_subtraction": bool(
                verdict_[arm]["clears_b119_ceiling"] and net_neg),
            "is_lever": bool(verdict_[arm]["clears_b119_ceiling"]
                             and verdict_[arm]["one_sided_strict"]
                             and not net_neg and not dd_worse),
        }
    return out


def vs_b131(led, l131: dict) -> dict:
    """Did the real archive change the answer b131 had to give on synthetic
    coverage? Compare the live-width arm's per-leg delta."""
    out = {}
    arm_new = "real::±%dmin" % LIVE_BLACKOUT_MIN
    arm_old = "real::±%dmin" % LIVE_BLACKOUT_MIN
    for leg in LEGS:
        new = led["_delta_exp_R"][arm_new][leg]
        old = (l131.get("_delta_exp_R", {}).get(arm_old) or {}).get(leg)
        out[leg] = {"b131_real_cal": old, "b132_real_archive": new,
                    "changed": (new != old)}
    return out


def build() -> dict:
    cal = load_archive()
    led: dict = {
        "_live_blackout_min": LIVE_BLACKOUT_MIN,
        "_arms": list(ARM_NAMES),
        "_archive": {"path": _pick_archive()[1],
                     "source": cal.get("source"),
                     "n_events": cal.get("n_events"),
                     "n_high_gold": cal.get("n_high_gold"),
                     "event_first": cal.get("event_first"),
                     "event_last": cal.get("event_last"),
                     "n_snapshots": cal.get("n_snapshots"),
                     "n_snapshots_failed": cal.get("n_snapshots_failed")},
        "_coverage_rule": {"min_span_overlap_frac": MIN_COVERAGE_FRAC,
                           "min_high_events_in_leg": MIN_HIGH_EVENTS},
        "_note": ("veto windows probed through the REAL evaluate_macro_filter "
                  "over a REAL historical archive (ForexFactory feed captured "
                  "week-by-week by the Internet Archive); neutrality votes are "
                  "cast on COVERED legs only"),
    }
    for leg in LEGS:
        m15, h1, h4 = _rows_for(leg)
        led[leg] = measure_leg(m15, h1, h4, cal)
        led[leg].pop("_funnel")
    led["_coverage"] = {leg: led[leg]["_coverage"] for leg in LEGS}
    led["_covered_legs"] = covered_legs(led)
    led["_integrity"] = integrity(led, json.load(open(LEDGER_129)))
    led["_census"] = vetoed_census(led)
    led["_delta_exp_R"] = deltas(led)
    led["_delta_net_R"] = deltas(led, "net_R", 1)
    led["_delta_maxDD_R"] = deltas(led, "maxDD_R", 1)
    led["_neutrality"] = neutrality(led)
    led["_verdict"] = verdict(led)
    led["_lever"] = lever_test(led)
    n_cov = len(led["_covered_legs"])
    uncovered = [leg for leg in LEGS if leg not in led["_covered_legs"]]
    floor = ("the floor is unreachable and NO arm can be strictly one-sided "
             "here by construction" if n_cov < 3
             else "a strict verdict is reachable")
    led["_caveat"] = (
        f"{n_cov} of {len(LEGS)} legs are covered by the archive "
        f"(archive span {led['_archive']['event_first'][:10]}.."
        f"{led['_archive']['event_last'][:10]}); b129's one_sided_strict floor "
        f"is max(3, half the legs) non-zero legs, so at n={n_cov} {floor}. "
        f"Legs with no archive coverage are an absence of data, not a finding "
        f"of no-effect: {uncovered or 'none'}.")
    led["_vs_b131"] = vs_b131(led, json.load(open(LEDGER_131)))
    return led


def main() -> None:
    led = build()
    bad = [leg for leg in LEGS
           if not led["_integrity"][leg]["off_matches_b129_incumbent"]]
    if bad:
        raise SystemExit(f"INTEGRITY FAIL: OFF arm != b129 incumbent on {bad}")
    print("integrity: OFF == b129 incumbent on all", len(LEGS), "legs")
    print("archive:", led["_archive"]["n_events"], "events, high USD/XAU",
          led["_archive"]["n_high_gold"], "span",
          led["_archive"]["event_first"], "..", led["_archive"]["event_last"])
    for leg in LEGS:
        c = led["_coverage"][leg]
        print(f"  {leg:>6}: high events in leg={c['n_high_events_in_leg']:>3} "
              f"overlap={c['span_overlap_frac']:.2f} covered={c['covered']}")
    print("covered legs:", led["_covered_legs"])
    for arm, v in led["_verdict"].items():
        print(f"{arm:>16}: vetoed(covered)={v['n_vetoed_covered_legs']:>3} "
              f"vetoed(all)={v['n_vetoed_all_legs']:>3} "
              f"n_nonzero={v['n_nonzero']} max|Δexp_R|={v['max_abs_exp_R']} "
              f"mean={v['mean_exp_R']} one_sided={v['one_sided']}/"
              f"strict={v['one_sided_strict']} ceiling={v['clears_b119_ceiling']}")
    moved = [leg for leg, r in led["_vs_b131"].items() if r["changed"]]
    print("legs whose delta changed vs b131:", moved or "none")
    print("lever test (exp_R ceiling AND net_R AND maxDD must agree):")
    for arm, v in led["_lever"].items():
        print(f"{arm:>16}: ceiling={v['exp_R_clears_ceiling']} "
              f"one_sided={v['exp_R_one_sided']} "
              f"net_R_neg_legs={v['n_legs_net_R_negative']} "
              f"maxDD_worse={v['n_legs_maxDD_worse']} "
              f"inflation_by_subtraction={v['exp_R_inflation_by_subtraction']} "
              f"IS_LEVER={v['is_lever']}")
    print("caveat:", led["_caveat"])
    with open(OUT, "w") as f:
        json.dump(led, f, indent=1)
    print("saved:", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
