#!/usr/bin/env python3
"""b198 — CENSUS: does the reassess loop actually reverse bias, or only flicker?

b188(c) (2026-09-09) claimed: "REASSESS LOOP NEVER REVERSES: 1220 reassessment
events, exactly 1 real bearish->bullish flip. The loop recomputes score but
direction is sticky." and offered two fixes: wire a flip path (re-anchor zones +
invalidate old pending orders) or cut reassess to hourly. b159's rule applies
verbatim: a claimed defect is an OPTION until the disagreement rate and the
consumer count are measured — census BEFORE fixing.

This read-only script freezes data/xau_plan/reassessment_log.csv (append-only,
the only bias-transition record the system keeps) into the ledger and derives,
from those rows alone:

  * event-level transition matrix (old_bias -> new_bias);
  * EPISODE-level reversals: consecutive equal new_bias values collapse into
    one bias episode, and a directional episode pair (bull..bear or bear..bull)
    separated by a neutral episode IS a reversal of the deployed direction —
    the event matrix counts it as two neutral transitions and misses it;
  * run-length statistics per bias (is direction STICKY or FLICKERING?);
  * the two consumer facts that decide the fix options:
      (1) the plan lane never rests a broker order (_build_proposal only acts
          on market_order/market_entry_now, b193b removed the 4 phantom
          resting-order actions), so "invalidate old pending orders on flip"
          has nothing to invalidate — signal-lane pendings come from the
          Telegram channel, not from plan bias;
      (2) the plan (zones/invalidation/targets) is FULLY REBUILT from fresh
          M5/H1/H4 every reassess (build_live_plan -> build_plan_context), so
          zones are already re-anchored at every flip by construction.

Verdict options are computed from the rows, not hardcoded into the flow:
  sticky if directional episodes are long and reversals ~0
  flicker if directional episodes are short (median run small)
  neither -> b188(c) premise false, no wiring change.

b164 rule: the summary is a PURE derive(rows) over the frozen rows embedded in
the ledger; scripts/b127_producer_reproduction.py::check_b198 re-executes it at
test time and demands exact equality, so the backlog number quoted today can
never silently drift with the rolling log.

Writes data/backtest/b198_reassess_flip_census.json (B198_OUT redirects,
b48/b52 pattern).
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

OUT = os.environ.get("B198_OUT", "data/backtest/b198_reassess_flip_census.json")
LOG = os.environ.get("B198_LOG", "data/xau_plan/reassessment_log.csv")

DIRECTIONAL = {"bullish", "bearish"}


def read_rows(path=LOG):
    """Compact frozen rows: (at, plan_id, old_bias, new_bias)."""
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append({
                "at": r.get("at") or "",
                "plan_id": r.get("plan_id") or "",
                "old": r.get("old_bias") or "",
                "new": r.get("new_bias") or "",
            })
    return rows


def episodes(rows):
    """Collapse consecutive equal new_bias values into episodes.

    Returns [(bias, n_events, first_at, last_at)]. The FIRST row's old_bias
    seeds episode 0 only when it differs from the first new_bias (the log
    begins mid-episode); that seed is not an event and is dropped — episodes
    are defined by observed new_bias runs.
    """
    eps = []
    for r in rows:
        b = r["new"]
        if eps and eps[-1][0] == b:
            eps[-1][1] += 1
            eps[-1][3] = r["at"]
        else:
            eps.append([b, 1, r["at"], r["at"]])
    return eps


def derive(rows):
    """Pure summary over frozen rows (b164: re-executed by b127's check)."""
    n = len(rows)
    if n == 0:
        return {"n_events": 0}

    matrix = {}
    for r in rows:
        k = f"{r['old']}->{r['new']}"
        matrix[k] = matrix.get(k, 0) + 1

    # exact opposite-direction pair on ONE event (no neutral in between)
    direct_flips = [r for r in rows
                    if r["old"] in DIRECTIONAL and r["new"] in DIRECTIONAL
                    and r["old"] != r["new"]]

    eps = episodes(rows)
    # episode-level reversals: dir episode -> neutral episode(s) -> opposite dir
    reversals = []
    for i in range(1, len(eps) - 1):
        if eps[i][0] != "neutral":
            continue
        # absorb consecutive neutral episodes (should not occur, but be honest)
        j = i
        while j + 1 < len(eps) and eps[j + 1][0] == "neutral":
            j += 1
        prev, nxt = eps[i - 1], eps[j + 1] if j + 1 < len(eps) else None
        if nxt and prev[0] in DIRECTIONAL and nxt[0] in DIRECTIONAL \
                and prev[0] != nxt[0]:
            reversals.append({"from": prev[0], "to": nxt[0],
                              "at": nxt[2],
                              "neutral_events": sum(e[1] for e in eps[i:j + 1])})

    runs = {b: sorted(e[1] for e in eps if e[0] == b) for b in
            ("bullish", "bearish", "neutral")}

    def med(xs):
        return xs[len(xs) // 2] if xs else None

    dir_runs = runs["bullish"] + runs["bearish"]
    out = {
        "n_events": n,
        "first_at": rows[0]["at"],
        "last_at": rows[-1]["at"],
        "transition_matrix": dict(sorted(matrix.items())),
        "noop_pct": round(100.0 * sum(
            1 for r in rows if r["old"] == r["new"]) / n, 2),
        "direct_flips": len(direct_flips),
        "direct_flip_events": [
            {"at": r["at"], "from": r["old"], "to": r["new"]}
            for r in direct_flips],
        "n_episodes": len(eps),
        "n_directional_episodes": sum(1 for e in eps if e[0] in DIRECTIONAL),
        "episode_reversals_via_neutral": len(reversals),
        "reversal_events": reversals,
        "run_stats": {
            b: {"n": len(runs[b]), "median": med(runs[b]),
                "max": max(runs[b]) if runs[b] else None}
            for b in runs},
        "dir_run_median_events": med(dir_runs),
    }
    # Verdict from the rows: sticky = directional runs long AND reversals rare;
    # flicker = directional runs short. 5-min cadence: run 5 ~= 25 min.
    sticky = (out["run_stats"]["bullish"]["median"] or 0) >= 20 and \
             (out["run_stats"]["bearish"]["median"] or 0) >= 20 and \
             out["episode_reversals_via_neutral"] <= 2
    flicker = (out["dir_run_median_events"] or 0) <= 3
    out["sticky_per_b188c"] = bool(sticky)
    out["flickering"] = bool(flicker)
    return out


def main():
    rows = read_rows()
    led = {"produced_at": datetime.now(timezone.utc).isoformat(),
           "source": LOG, "rows": rows}
    led.update(derive(rows))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(led, fh, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in led.items() if k != "rows"},
                     ensure_ascii=False, indent=1))
    print(f"wrote {OUT} ({len(rows)} frozen rows)")


if __name__ == "__main__":
    main()
