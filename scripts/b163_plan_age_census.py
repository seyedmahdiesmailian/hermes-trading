#!/usr/bin/env python3
"""b163 — CENSUS: HOW OLD WAS THE PLAN THAT SCORED EACH SIGNAL DECISION?

engines/signal_listener.check_signals loads load_current_plan() and feeds
plan['bias'] into evaluate_signal Check 4 (+2.0 alignment / -1.0 conflict /
+0.5 neutral) WITHOUT ever checking the plan's age — while the plan lane
itself expires at expires_at (12h, engines/orchestrator.route_runtime_step)
and rebuilds every cron tick. If hermes_runtime's cadence breaks (b114 drift,
b154 inert daemon), current_plan.json could carry a DAYS-OLD bias and the
signal lane would still pay +2.0/-1.0 for agreeing/disagreeing with it.
This is a SCORING input, not a gate, so the direction of harm was unmeasured.

b110/b140 rule: CENSUS FIRST. This read-only script joins:
  * data/signals/signals_log.json  — every decision record + wall-clock ts;
  * data/xau_plan/plan_history/*.json + current_plan.json — every plan
    version with its created_at / expires_at / bias (built from created_at,
    NOT the archive filename stamp: same-second archives race);
  * data/xau_plan/reassessment_log.csv — cadence evidence for decisions that
    pre-date the plan_history retention window (PLAN_HISTORY_KEEP=1500),
    giving an age BOUND (the live plan was reassessed at least that recently).

Reports per decision: effective plan age (h) at decision time, expired?
(past its own expires_at), which alignment score Check 4 paid, and whether
that score was DECISIVE for the 6.0 execute floor (counterfactual: what the
verdict's score would have been without the bonus/penalty). Also reports the
plan-cadence gap distribution over the whole history (what age a consumer
COULD maximally see) and the max reassessment gap in the pre-history era.

The census embeds its compact per-decision rows so the ledger is
self-contained: tests re-derive the summary from the FROZEN rows instead of
re-reading the rolling live logs (which mutate and rotate at 200 entries).

Writes data/backtest/b163_plan_age_census.json (B163_OUT redirects it,
b48/b52 pattern).
"""
from __future__ import annotations

import csv
import glob
import json
import os
import sys
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

OUT = os.environ.get("B163_OUT", "data/backtest/b163_plan_age_census.json")

EXEC_FLOOR = 6.0        # evaluate_signal: final_score >= 6.0 -> "execute"
CADENCE_SLOTH_H = 2.0   # "older than one reassessment cadence" per the brief
MAX_SCORE = 10.0


def _dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def build_plan_timeline(root=_ROOT):
    plans = []
    files = sorted(glob.glob(os.path.join(
        root, "data/xau_plan/plan_history/*.json")))
    for f in files:
        try:
            d = json.loads(open(f).read())
        except Exception:
            continue
        created = _dt(d.get("created_at"))
        if created is None:
            continue
        plans.append({
            "plan_id": d.get("plan_id"),
            "created": created,
            "expires": _dt(d.get("expires_at")),
            "bias": d.get("bias"),
            "archived": True,
        })
    try:
        d = json.loads(open(os.path.join(
            root, "data/xau_plan/current_plan.json")).read())
        created = _dt(d.get("created_at"))
        if created is not None:
            plans.append({
                "plan_id": d.get("plan_id"),
                "created": created,
                "expires": _dt(d.get("expires_at")),
                "bias": d.get("bias"),
                "archived": False,
            })
    except Exception:
        pass
    plans.sort(key=lambda p: p["created"])
    return plans


def build_reassess_events(root=_ROOT):
    """(at, plan_id) reassessment events, sorted — cadence proxy for the
    era that plan_history pruning has forgotten."""
    out = []
    p = os.path.join(root, "data/xau_plan/reassessment_log.csv")
    if not os.path.exists(p):
        return out
    with open(p, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            at = _dt(row.get("at"))
            if at:
                out.append((at, row.get("plan_id")))
    out.sort(key=lambda t: t[0])
    return out


def effective_plan(timeline, ts):
    best = None
    for p in timeline:
        if p["created"] <= ts:
            best = p
        else:
            break
    return best


def age_bound(reassess, ts):
    """Upper bound on plan age from the reassessment cadence: the live plan
    was (re)written no earlier than the most recent reassess <= ts."""
    best = None
    for at, _pid in reassess:
        if at <= ts:
            best = at
        else:
            break
    return ((ts - best).total_seconds() / 3600.0) if best else None


def align_of(reasons):
    if "direction_aligned" in reasons:
        return ("aligned", 2.0)
    if "direction_conflict" in reasons:
        return ("conflict", -1.0)
    if "hermes_neutral" in reasons:
        return ("neutral", 0.5)
    return ("none", 0.0)


def decisive(score, delta):
    """True if removing Check 4's delta moves the decision across the 6.0
    execute floor. score is the CLAMPED final score, so the raw value lies
    in [score, score - min(0, delta_extra...)] — we test the clamped edge
    honestly: if score == MAX_SCORE the raw could have been higher and the
    bonus cannot have been decisive; else raw == score."""
    if delta == 0.0:
        return False
    if score >= MAX_SCORE:
        return False          # clamped: unmeasurable, never claim decisive
    without = score - delta
    return (score >= EXEC_FLOOR) != (without >= EXEC_FLOOR)


def summarize(rows):
    if not rows:
        return {}
    ages = [r["age_h"] for r in rows if r.get("age_h") is not None]
    buckets = {"<1h": 0, "1-2h": 0, "2-12h": 0, ">=12h (past expires_at)": 0}
    for r in rows:
        a = r.get("age_h")
        if a is None:
            continue
        if a < 1:
            buckets["<1h"] += 1
        elif a < CADENCE_SLOTH_H:
            buckets["1-2h"] += 1
        elif a < 12:
            buckets["2-12h"] += 1
        else:
            buckets[">=12h (past expires_at)"] += 1
    return {
        "n_decisions": len(rows),
        "max_age_h": max(ages) if ages else None,
        "age_buckets": buckets,
        "n_past_expires_at": sum(1 for r in rows if r["expired"]),
        "n_age_gt_cadence": sum(1 for r in rows
                                if (r.get("age_h") or 0) > CADENCE_SLOTH_H),
        "n_aligned_decisive_for_floor": sum(
            1 for r in rows if r["align"] == "aligned" and r["decisive"]),
        "n_conflict_decisive_for_floor": sum(
            1 for r in rows if r["align"] == "conflict" and r["decisive"]),
    }


def derive(rows):
    """PURE post-processing over the census rows — b127 re-executes this on
    the shipped ledger's frozen rows and requires EXACT reproduction of the
    six returned keys. The cadence block is NOT derived here: it comes from
    the plan timeline files, which keep growing, so it is pinned as recorded
    (b163 test), not re-derived."""
    covered = [r for r in rows if r["source"] == "timeline"]
    bounded = [r for r in rows if r["source"] == "reassess_bound"]
    summary_cov = summarize(covered)
    summary_bnd = summarize(bounded)
    # "stale" per the brief = a Check 4 +/- that a MEASURED plan age puts past
    # the 2h cadence or past expires_at. reassess_bound rows carry an age
    # UPPER BOUND (pre-retention era, plan rebuilds unlogged), so a bound
    # breach is reported separately and cannot certify the pathology.
    stale_measured = (summary_cov.get("n_past_expires_at", 0)
                      + summary_cov.get("n_age_gt_cadence", 0))
    bound_over_cadence = summary_bnd.get("n_age_gt_cadence", 0)
    # decisive harm: an old-plan +/- that flipped a verdict across the floor
    stale_decisive = (summary_cov.get("n_aligned_decisive_for_floor", 0)
                      + summary_cov.get("n_conflict_decisive_for_floor", 0)
                      ) - (sum(1 for r in covered
                               if r["align"] in ("aligned", "conflict")
                               and r["decisive"]
                               and (r["age_h"] or 0) <= CADENCE_SLOTH_H))
    verdict = ("FRESH_ALWAYS_KEEP_PIN_TRIPWIRE" if stale_measured == 0
               else f"STALE_OCCURRENCES:{stale_measured}")
    return {
        "decisions_on_timeline": summary_cov,
        "decisions_on_reassess_bound": summary_bnd,
        "stale_alignment_scores": stale_measured,
        "bound_over_cadence_pre_history": bound_over_cadence,
        "stale_decisive_for_verdict": max(0, stale_decisive),
        "verdict": verdict,
    }


def run(root=_ROOT):
    timeline = build_plan_timeline(root)
    reassess = build_reassess_events(root)
    if not timeline:
        raise RuntimeError("plan_history timeline empty — nothing to census")
    log_path = os.path.join(root, "data/signals/signals_log.json")
    log = json.loads(open(log_path).read())
    if not isinstance(log, list):
        raise RuntimeError("signals_log is not a list")

    rows = []
    for entry in log:
        ts = _dt(entry.get("timestamp"))
        dec = entry.get("decision") or {}
        reasons = dec.get("reasons") or []
        align, delta = align_of(reasons)
        row = {
            "ts": entry.get("timestamp"),
            "verdict": dec.get("verdict"),
            "score": dec.get("score"),
            "align": align,
            "decisive": decisive(dec.get("score") or 0.0, delta),
        }
        p = effective_plan(timeline, ts) if ts else None
        if p is not None:
            row["plan_id"] = p["plan_id"]
            row["plan_bias"] = p["bias"]
            row["age_h"] = round((ts - p["created"]).total_seconds() / 3600.0, 4)
            row["expired"] = bool(p["expires"] and ts >= p["expires"])
            row["source"] = "timeline"
        else:
            # pre-history: no retained plan file → give the reassessment-bound
            b = age_bound(reassess, ts) if ts else None
            row["plan_id"] = None
            row["plan_bias"] = None
            row["age_h"] = round(b, 4) if b is not None else None
            row["expired"] = False  # cannot establish; bound below covers it
            row["source"] = "reassess_bound" if b is not None else "no_evidence"
        rows.append(row)

    # plan-cadence gaps over the retained timeline: the maximum age any
    # consumer can see between two rebuilds.
    gaps = []
    for a, b in zip(timeline, timeline[1:]):
        gaps.append((b["created"] - a["created"]).total_seconds() / 3600.0)
    rgaps = []
    for a, b in zip(reassess, reassess[1:]):
        rgaps.append((b[0] - a[0]).total_seconds() / 3600.0)

    led = derive(rows)
    led.update({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "plan_versions_retained": len(timeline),
            "timeline_created_range": [timeline[0]["created"].isoformat(),
                                       timeline[-1]["created"].isoformat()],
            "reassess_events": len(reassess),
            "decisions_total": len(rows),
        },
        "cadence": {
            "max_plan_rebuild_gap_h": round(max(gaps), 4) if gaps else None,
            "plan_gaps_gt_cadence": sum(1 for g in gaps if g > CADENCE_SLOTH_H),
            "plan_gaps_gt_expiry": sum(1 for g in gaps if g >= 12),
            "max_reassess_gap_h": round(max(rgaps), 4) if rgaps else None,
            "reassess_gaps_gt_expiry": sum(1 for g in rgaps if g >= 12),
        },
        "rows": rows,
    })
    return led


def main():
    led = run()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(led, fh, indent=2, ensure_ascii=False)
    print(json.dumps({k: led[k] for k in
                      ("verdict", "cadence", "decisions_on_timeline",
                       "decisions_on_reassess_bound",
                       "stale_alignment_scores",
                       "bound_over_cadence_pre_history",
                       "stale_decisive_for_verdict")},
                     indent=2, ensure_ascii=False))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
