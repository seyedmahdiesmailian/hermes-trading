#!/usr/bin/env python3
"""b143 — THE RISK LEDGER GETS A READER: reconcile the recorded shrink stack
against the money the ledger says was risked, and report the REALIZED damper
mix.

Why (b139's own filing): an unwritten ledger is data, an unread one is theatre.
b139 shipped the sidecar (data/xau_plan/risk_ledger.csv) that records, per
entry, the four dampers that multiplied into the lot — learning, style, DEFCON,
regime — plus the product (final_risk_pct) and the money (risk_usd). Nothing
consumed it. This is the consumer, and it asks three questions of every row:

  Q1 ARITHMETIC — does base * learning * style * defcon * regime actually equal
     the final_risk_pct the row recorded? The stack is captured AT THE SOURCE
     inside evaluate_proposal, so a row that fails this is either a torn write
     or a future refactor that changed one leg and not the recorded product.

  Q2 MONEY — does the recorded lot agree with the SHARED sizing model
     (engines.orchestrator.compute_xau_position_size — imported, never
     restated) run on the row's own final_risk_pct and stop distance? This is
     the question b137 could not ask: it is the only per-trade check that the
     dampers did not just FIRE but actually BITE the size.

  Q3 MIX — how often did each damper actually fire, and what did the product
     distribution look like? That is b138's pending human decision (the
     loss_streak>=2 double-charge at 0.25x) turned from an argument into a
     table of realized frequency.

TWO DEFECTS THIS READER FOUND BY HAVING TO WRITE THE JOIN:

  (a) THE LEDGER HAD NO TICKET COLUMN. [FIXED by b144, 2026-09-08: `ticket` is
      now in RISK_LEDGER_FIELDS, both lane writers pass the broker ticket, and
      an existing 18-column file is widened by storage's header migration —
      b142's rule. join_to_tickets below prefers the row's own ticket and falls
      back to the plan_id join only for pre-b144 rows.] Before that there was
      no direct key: RISK_LEDGER_FIELDS (engines/storage.py) carried plan_id,
      not ticket, so the join went risk_ledger -> execution_log (on
      at+plan_id+side+lot) -> ticket -> trade_journal. The plan lane survived
      (plan_id is unique per proposal), but EVERY signal-lane row carried
      plan_id='signal', so the realized-P&L question b138 needs was
      unanswerable for the lane that trades most.

  (b) THE SIGNAL LANE CAPS THE LOT AFTER THE STACK IS COMPUTED, and the cap is
      invisible to the ledger. engines/signal_listener.run_signal_check clamps
      `command['lot'] = min(lot, channel lot)` and rescales risk_usd BEFORE
      _log_signal_risk_stack writes the row — so a capped row's recorded lot
      is legitimately BELOW what its own final_risk_pct sizes to, with no field
      saying so. reconcile() therefore buckets lot-below-model by lane:
      'lot_below_model_signal_capped' (explainable, not evidence of a defect)
      vs 'lot_below_model' on the plan lane (unexplainable — a real defect).
      A lot ABOVE the model is a defect in either lane: it means more risk was
      taken than the shrink stack authorized.

READ-ONLY: no bridge, no order endpoint, no production write except its own
JSON artifact under data/backtest/. The live sidecar may not exist yet (b139
shipped 2026-09-08; the first executed entry creates it) — an absent or empty
ledger reports zero rows honestly; nothing here fabricates a row.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from engines.orchestrator import compute_xau_position_size   # noqa: E402

LEDGER = _ROOT / "data" / "xau_plan" / "risk_ledger.csv"
EXEC_LOG = _ROOT / "data" / "xau_plan" / "execution_log.csv"
JOURNAL = _ROOT / "data" / "xau_plan" / "trade_journal.csv"
OUT = _ROOT / "data" / "backtest" / "b143_risk_ledger_reader.json"

# The sizing call the live entry path makes (engines/auto_executor.py Check 6):
# same point value, same step, same floor. Imported model, pinned constants.
POINT = 0.01
POINT_VALUE_PER_LOT = 1.0
VOLUME_MIN = 0.01
VOLUME_STEP = 0.01
VOLUME_MAX = 1.0
MIN_MEANINGFUL_LOT = 0.01

STATUSES = ("coherent", "product_mismatch", "lot_below_model",
            "lot_above_model", "lot_below_model_signal_capped",
            "unparseable")


def read_ledger(path: Path = LEDGER) -> list[dict]:
    """DictReader over the sidecar. Missing/empty file -> [] (honest zero)."""
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return []
    with p.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        # b142's trap, asserted on READ: a value that landed under the None
        # restkey means the header and the rows disagree — the schema rotted.
        if r.get(None) is not None:
            r["_restkey"] = r.get(None)
    return rows


def _num(v, default=None):
    try:
        s = str(v if v is not None else "").strip()
        return float(s) if s else default
    except (TypeError, ValueError):
        return default


def stack_product(row: dict) -> float | None:
    """base * learning * style * defcon * regime, from the row's OWN legs."""
    base = _num(row.get("base_risk_pct"))
    if base is None:
        return None
    mult = 1.0
    for key in ("learning_risk_mult", "style_mult", "regime_mult"):
        v = _num(row.get(key), 1.0)
        if v is None:
            return None
        mult *= v
    dc = str(row.get("defcon_override") or "").strip()
    if dc not in ("", "None", "none"):
        v = _num(dc)
        if v is None:
            return None
        mult *= v
    return round(base * mult, 12)


def _model_lot(balance: float, risk_pct: float, stop: float) -> dict:
    return compute_xau_position_size(
        balance=balance, risk_pct=risk_pct, stop_distance_price=stop,
        point=POINT, point_value_per_lot=POINT_VALUE_PER_LOT,
        volume_min=VOLUME_MIN, volume_step=VOLUME_STEP, volume_max=VOLUME_MAX,
        min_meaningful_lot=MIN_MEANINGFUL_LOT)


def expected_lot(row: dict) -> dict | None:
    """Re-run the SHARED sizing model on the row's own risk, deriving the
    balance from the row's own money (risk_usd / final_risk_pct) so no live
    account call is needed and the check stays a pure function of the row.

    risk_usd is stored ROUNDED to cents (round(balance*risk_pct, 2)), so the
    derived balance carries up to 0.005/risk_pct of error — enough to flip the
    model's floor() at an exact step boundary. The model is therefore run at
    the low/mid/high of that rounding band and the row is coherent if ANY of
    the three answers equals the recorded lot; the MID answer is what gets
    reported."""
    risk_pct = _num(row.get("final_risk_pct"))
    risk_usd = _num(row.get("risk_usd"))
    entry = _num(row.get("entry"))
    sl = _num(row.get("sl"))
    if not risk_pct or risk_usd is None or entry is None or sl is None:
        return None
    stop = abs(entry - sl)
    if stop <= 0:
        return None
    mid = risk_usd / risk_pct
    band = 0.005 / risk_pct
    answers = {}
    for tag, b in (("lo", mid - band), ("mid", mid), ("hi", mid + band)):
        answers[tag] = float(_model_lot(b, risk_pct, stop).get("lot") or 0.0)
    sizing = _model_lot(mid, risk_pct, stop)
    return {"lot": answers["mid"], "lot_band": answers,
            "balance": round(mid, 2),
            "stop_distance": round(stop, 2),
            "meaningful": sizing.get("meaningful"),
            "reason": sizing.get("reason")}


def reconcile(row: dict) -> dict:
    """One row -> its arithmetic + money verdict. Pure function of the row."""
    out = {"at": row.get("at"), "lane": row.get("lane"),
           "plan_id": row.get("plan_id"),
           "execution_style": row.get("execution_style"),
           "regime": row.get("regime")}
    if row.get("_restkey") is not None:
        out["status"] = "unparseable"
        out["detail"] = "b142 restkey — header/row width mismatch"
        return out
    prod = stack_product(row)
    final = _num(row.get("final_risk_pct"))
    if prod is None or final is None:
        out["status"] = "unparseable"
        out["detail"] = "missing/non-numeric stack field"
        return out
    out["stack_product"] = prod
    out["final_risk_pct"] = final
    if abs(prod - final) > 1e-9:
        out["status"] = "product_mismatch"
        out["detail"] = f"legs say {prod}, row recorded {final}"
        return out
    exp = expected_lot(row)
    lot = _num(row.get("lot"))
    if exp is None or lot is None:
        out["status"] = "unparseable"
        out["detail"] = "cannot re-size (missing entry/sl/risk_usd/lot)"
        return out
    out["expected_lot"] = exp["lot"]
    out["implied_balance"] = exp["balance"]
    out["stop_distance"] = exp["stop_distance"]
    band = exp["lot_band"]
    lo, hi = min(band.values()), max(band.values())
    if abs(lot - exp["lot"]) < 1e-9 or lo - 1e-9 <= lot <= hi + 1e-9:
        out["status"] = "coherent"
    elif lot < lo:
        # the signal lane clamps the lot to the channel's own size AFTER the
        # stack (run_signal_check), so a smaller lot there is expected and is
        # NOT evidence of a defect; on the plan lane nothing can shrink it.
        out["status"] = ("lot_below_model_signal_capped"
                         if str(row.get("lane")) == "signal"
                         else "lot_below_model")
    else:
        out["status"] = "lot_above_model"
    return out


def sizing_epoch(row: dict) -> str:
    """Which sizing regime produced this row's BASE — b197 (2026-09-09).

    b196 wired the account's tiered base_risk_pct (engines/risk.
    _base_risk_pct: <800 -> 1.0%, <1500 -> 1.5%, <5000 -> 2.0%, >=5000 ->
    1.5%) into evaluate_proposal, clamped under MAX_RISK_PER_TRADE_PCT.
    Every tier is <= MAX, so the ONLY row shapes that can appear are:

      'tiered'  — base < MAX: the policy base sized this lot (post-b196; at
                  >=5000 that is a 25% SMALLER lot than any pre-fix trade).
      'max_flat'— base == MAX: either a pre-b196 row (base was always MAX)
                  or a post-b196 row below 5000, where the tier EQUALS MAX —
                  the two are indistinguishable from the row alone, and this
                  is why a >=5000 'max_flat' row after the fix would be a
                  DEFECT, not noise (b196 clamp cannot produce it).
      'unknown' — no parsable base: never guess, say so.

    The tiers are IMPORTED (risk._base_risk_pct), never restated — b143's
    own imported-not-restated rule, extended to the classifier.
    """
    from engines.auto_executor import MAX_RISK_PER_TRADE_PCT
    from engines.risk import _base_risk_pct

    base = _num(row.get("base_risk_pct"))
    if base is None or base <= 0:
        return "unknown"
    # b139's sidecar records final_risk_pct rounded to 4dp and risk_usd to
    # cents, so a derived balance carries error and can sit a hair across a
    # tier edge — b143's own lo/mid/high band rule (expected_lot) applies
    # here too: the row is a tier-MATCH if ANY band point sizes to its base.
    if abs(base - MAX_RISK_PER_TRADE_PCT) < 1e-4:
        return "max_flat"
    risk_usd = _num(row.get("risk_usd"))
    pct = _num(row.get("final_risk_pct"))
    implied = _num(row.get("balance"))
    if implied is None and risk_usd and pct:
        implied = risk_usd / pct
    if implied is not None:
        # two rounding errors move the implied balance: cents on risk_usd
        # (absolute 0.005/pct) and 4dp on final_risk_pct (relative 5e-5/pct —
        # for small final pcts this dominates; b139 rounds risk_pct with
        # round(x, 4), so a 0.0038 final carries ~1.3% of balance).
        band = (0.005 / pct) if (risk_usd and pct) else 0.0
        rel = (5e-5 / pct) if pct else 0.0
        rel = min(max(rel, 0.0), 0.05)  # never treat a >5% drift as rounding
        points = (implied - band, implied, implied + band,
                  implied * (1 - rel), implied * (1 + rel))
        for b in points:
            if abs(_base_risk_pct(b) - base) < 1e-4:
                return "tiered"
        # a tiered base that matches NO balance tier (even across the
        # rounding band): the tier table moved under an old ledger, or the
        # row is torn. Loud, not smoothed into 'tiered'.
        return "tier_mismatch"
    # base < MAX but no money fields to derive a balance from: the value is
    # still unambiguously a tier (only _base_risk_pct emits sub-MAX bases
    # post-b196) — keep it 'tiered', band check just unavailable.
    return "tiered"


def sizing_epoch_summary(rows: list[dict]) -> dict:
    """The one-line 'sizing epoch' note b197 asked for: how many rows were
    sized by the tiered policy base vs the flat MAX ceiling, per lane, plus
    the human sentence. Pure function of the rows; NO_ROWS_YET never means
    'the fix is dead' — an empty ledger is an empty window (b184's rule)."""
    counts = {"tiered": 0, "max_flat": 0, "tier_mismatch": 0, "unknown": 0}
    per_lane: dict = {}
    first_tiered_at = None
    for r in rows:
        e = sizing_epoch(r)
        counts[e] = counts.get(e, 0) + 1
        lane = str(r.get("lane") or "?")
        per_lane.setdefault(lane, {}).setdefault(e, 0)
        per_lane[lane][e] += 1
        if e in ("tiered", "tier_mismatch") and first_tiered_at is None:
            first_tiered_at = str(r.get("at") or "")
    from engines.auto_executor import MAX_RISK_PER_TRADE_PCT
    from engines.risk import _base_risk_pct
    note = (
        f"sizing epoch (b196+): base_risk_pct < {MAX_RISK_PER_TRADE_PCT} marks "
        f"tiered-policy sizing — a lot that looks 25% small vs history at "
        f"balance>=5000 is CORRECT, not a defect "
        f"(tier at 5000+: {_base_risk_pct(5000)} vs ceiling "
        f"{MAX_RISK_PER_TRADE_PCT}); rows: "
        f"tiered={counts['tiered']} max_flat={counts['max_flat']} "
        f"unknown={counts['unknown']}")
    if counts["tier_mismatch"]:
        note += (f" WARNING: {counts['tier_mismatch']} row(s) carry a base "
                 "that matches NO balance tier — forensic pass needed")
    if not counts["tiered"] and rows:
        note += (" | no tiered row yet — expected until the account crosses "
                 "5000 (pre-b196 rows and sub-5000 rows share base=MAX)")
    return {"counts": counts, "per_lane": per_lane,
            "first_tiered_at": first_tiered_at,
            "tiered_rows_present": counts["tiered"] + counts["tier_mismatch"] > 0,
            "note": note}


def persian_sizing_line(summary: dict) -> str:
    """One Persian ops-brief line (b197): self-explains a lot that looks
    'wrong' vs history. Empty string when there is nothing to say (no rows —
    honest zero, no fabricated line)."""
    c = summary.get("counts", {})
    if sum(c.values()) == 0:
        return ""
    line = (f"پایه ریسک حجم‌ها: {c.get('max_flat', 0)} ردیف با سقف ثابت، "
            f"{c.get('tiered', 0)} ردیف با سیاست پله‌ای (b196)")
    if c.get("tier_mismatch", 0):
        line += f" — ⚠️ {c['tier_mismatch']} ردیف پایه‌اش با هیچ پله‌ای نمی‌خواند"
    if not summary.get("tiered_rows_present"):
        line += (" — پس از عبور موجودی از 5000 حجم‌ها 25٪ کوچک‌تر می‌شوند؛ "
                 "طبیعی است")
    return line


def damper_mix(rows: list[dict]) -> dict:
    """How often each leg actually fired, and the realized product shape."""
    n = len(rows)
    fired = {}
    for key, label in (("learning_risk_mult", "learning"),
                       ("style_mult", "style"),
                       ("defcon_override", "defcon"),
                       ("regime_mult", "regime")):
        c = Counter()
        for r in rows:
            v = str(r.get(key) or "").strip()
            # defcon records the string "None" when no override is active —
            # that is NEUTRAL (1.0), not missing data.
            if key == "defcon_override" and v in ("", "None", "none"):
                c["neutral"] += 1
                continue
            num = _num(v)
            c["missing" if num is None else ("fires" if num < 1.0 else "neutral"
                                             if num == 1.0 else "loosens")] += 1
        fired[label] = dict(c)
    prods = Counter()
    for r in rows:
        p = _num(r.get("final_risk_pct"))
        base = _num(r.get("base_risk_pct"))
        if p is None or not base:
            prods["unparseable"] += 1
            continue
        prods[f"{round(p / base, 4)}x"] += 1
    # b138's table: the double-charge is regime==defensive AND defcon firing on
    # the same row (loss_streak>=2 feeds both modules — b137's finding).
    double = sum(1 for r in rows
                 if str(r.get("regime")) == "defensive"
                 and (_num(r.get("defcon_override")) or 1.0) < 1.0)
    return {"rows": n, "damper_fire_counts": fired,
            "combined_factor_distribution": dict(prods),
            "double_charge_rows_b138": double,
            "regimes_seen": dict(Counter(str(r.get("regime")) for r in rows)),
            "styles_seen": dict(Counter(str(r.get("execution_style")) for r in rows))}


# ── the join the brief asked for: sidecar -> execution_log -> ticket -> journal

def read_execution_log(path: Path = EXEC_LOG) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_journal_rows(path: Path = JOURNAL) -> list[dict]:
    """RAW journal rows, embedded in the artifact so the aggregation in
    read_journal_tickets is re-derivable from this file alone (b127's
    producer-reproduction contract)."""
    p = Path(path)
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def aggregate_journal(rows: list[dict]) -> dict:
    """PURE half of read_journal_tickets (b128's contract: the derived blocks
    must be re-executable from the artifact's embedded rows alone): raw
    journal rows in, position aggregation out. All arithmetic lives HERE —
    the file reader below only feeds it (b152's anti-duplication rule)."""
    by_pos: dict[str, dict] = {}
    index: dict[str, str] = {}
    for r in rows:
        key = str(r.get("position_id") or "").strip() or \
              str(r.get("ticket") or "").strip()
        if not key:
            continue
        agg = by_pos.setdefault(key, {"position_id": key, "close_deals": 0,
                                      "profit": 0.0, "commission": 0.0,
                                      "swap": 0.0, "entry_commission": 0.0,
                                      "closed_at": None})
        agg["close_deals"] += 1
        for col in ("profit", "commission", "swap", "entry_commission"):
            v = _num(r.get(col), 0.0) or 0.0
            agg[col] = round(agg[col] + v, 4)
        ct = _num(r.get("close_time"))
        if ct and (agg["closed_at"] is None or ct > agg["closed_at"]):
            agg["closed_at"] = ct
        for alt in (str(r.get("position_id") or "").strip(),
                    str(r.get("ticket") or "").strip()):
            if alt:
                index.setdefault(alt, key)
    for k, v in by_pos.items():
        # b152: entry_commission (broker IN-deal fee, prorated per leg) joins
        # the net too, so the reader's realized matches learning.group_positions.
        v["realized_net"] = round(v["profit"] + v["commission"] + v["swap"]
                                  + v["entry_commission"], 4)
    by_pos["_index"] = index
    return by_pos


def read_journal_tickets(path: Path = JOURNAL) -> dict:
    """File-reading shell over aggregate_journal (b128): keep all arithmetic
    in the pure function so a reproduction can re-run it from the artifact's
    embedded journal_rows without touching the ledger."""
    return aggregate_journal(read_journal_rows(path))


def join_to_tickets(rows: list[dict], exec_rows: list[dict],
                    journal: dict) -> list[dict]:
    """Attach a ticket + realized P&L to each sidecar row.

    b144 changed the primary path: the row carries its OWN `ticket` now, so a
    row joins directly — no key ambiguity, and the SIGNAL lane (plan_id
    repeats as 'signal') is finally auditable, which was the whole point.
    Rows written BEFORE b144 have an empty ticket cell; those fall back to
    the old plan-lane plan_id join (exact there, since plan_id is unique per
    proposal) and are reported joinable=False on the signal lane rather than
    matched by timestamp, which would be a fabricated join.

    A limit-order row's ticket is the PENDING order ticket, not the position
    ticket the journal keys on, so it may resolve to nothing — that reports
    realized=None honestly instead of guessing at a fill."""
    by_plan: dict[str, list[dict]] = {}
    for e in exec_rows:
        by_plan.setdefault(str(e.get("plan_id")), []).append(e)
    index = journal.get("_index") or {}
    out = []
    for r in rows:
        pid = str(r.get("plan_id"))
        info = {"at": r.get("at"), "lane": r.get("lane"), "plan_id": pid,
                "joinable": False, "ticket": None, "realized_net": None,
                "join_path": None}
        own = str(r.get("ticket") or "").strip()
        if own:
            info.update(joinable=True, ticket=own, join_path="row_ticket")
            pos = journal.get(index.get(own, own))
            if pos is not None:
                info["position_id"] = pos.get("position_id")
                info["close_deals"] = pos.get("close_deals")
                info["realized_net"] = pos.get("realized_net")
            else:
                info["join_note"] = ("ticket resolves to no journal row "
                                     "(open position, or a pending-order "
                                     "ticket that is not the position key)")
        elif r.get("lane") == "plan":
            cands = [e for e in by_plan.get(pid, [])
                     if str(e.get("result_ok")).lower() == "true"
                     and str(e.get("ticket") or "").strip()]
            if len(cands) == 1:
                t = str(cands[0]["ticket"]).strip()
                info.update(joinable=True, ticket=t,
                            join_path="plan_id_fallback")
                pos = journal.get(index.get(t, t))
                if pos is not None:
                    info["position_id"] = pos.get("position_id")
                    info["close_deals"] = pos.get("close_deals")
                    info["realized_net"] = pos.get("realized_net")
            elif len(cands) > 1:
                info["join_error"] = f"{len(cands)} executed rows share plan_id"
            else:
                info["join_error"] = "no executed execution_log row for plan_id"
        else:
            info["join_error"] = ("no ticket column value (pre-b144 row) and "
                                  "signal-lane plan_id is not unique")
        out.append(info)
    return out


def derive(rows: list[dict], exec_rows: list[dict], journal: dict) -> dict:
    """PURE post-processing of the collected rows — the b127/b128 contract: a
    frozen ledger can be re-derived from its own inputs."""
    recs = [reconcile(r) for r in rows]
    status_counts = dict(Counter(r["status"] for r in recs))
    defects = [r for r in recs if r["status"] in
               ("product_mismatch", "lot_below_model", "lot_above_model",
                "unparseable")]
    return {
        "rows": len(rows),
        "status_counts": status_counts,
        "defect_rows": defects,
        "damper_mix": damper_mix(rows),
        # b197: which sizing BASE produced these rows (pre/post-b196 tiering).
        "sizing_epoch": sizing_epoch_summary(rows),
        "ticket_join": join_to_tickets(rows, exec_rows, journal),
        "verdict": ("NO_ROWS_YET" if not rows else
                    ("LEDGER_RECONCILES" if not defects
                     else f"RECONCILIATION_DEFECTS:{len(defects)}")),
    }


def main() -> dict:
    rows = read_ledger()
    exec_rows = read_execution_log()
    journal = read_journal_tickets()
    led = {
        "_note": "b143 reader: reconciles the b139 risk_stack sidecar against "
                 "the shared sizing model and reports the realized damper mix "
                 "(b138's double-charge frequency as a table). Read-only. The "
                 "JOIN INPUTS are embedded so _derived is reproducible from "
                 "this artifact alone (b127's producer-reproduction contract) "
                 "even though the live CSVs keep growing.",
        "_sources": {"risk_ledger": str(LEDGER), "risk_ledger_exists":
                     LEDGER.exists(), "execution_log": str(EXEC_LOG),
                     "trade_journal": str(JOURNAL)},
        "rows": rows,
        "execution_log": exec_rows,
        "journal_rows": read_journal_rows(),
        "journal_positions": [v for k, v in journal.items() if k != "_index"],
        "_derived": derive(rows, exec_rows, journal),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(led, indent=1), encoding="utf-8")
    d = led["_derived"]
    print("rows:", d["rows"], "| verdict:", d["verdict"])
    print("statuses:", d["status_counts"])
    if d["rows"]:
        print("damper fire counts:", d["damper_mix"]["damper_fire_counts"])
        print("combined factor:",
              d["damper_mix"]["combined_factor_distribution"])
        print("b138 double-charge rows:",
              d["damper_mix"]["double_charge_rows_b138"])
        # b197: the sizing epoch line — makes a 'small-looking' lot
        # self-explaining instead of triggering a manual forensic pass.
        print(d["sizing_epoch"]["note"])
    print("ledger:", OUT)
    return led


if __name__ == "__main__":
    main()
