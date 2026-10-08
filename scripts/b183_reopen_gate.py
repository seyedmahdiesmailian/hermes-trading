#!/usr/bin/env python3
"""b183 REOPEN GATE — the corrected, tested predicate for re-opening b183.

WHY THIS EXISTS (2026-09-10, b209)
==================================
b183 (0.01-lot trades cannot halve, so they under-earn on the half+runner
lane) is parked with an explicit reopening condition:

    "re-open when trade_journal shows >=30 closes with at() >= 2026-09-09"

That predicate is DOUBLE-DEAD and was never testable:

  1. `trade_journal.csv` has NO `at` column. Its header is
     ticket,close_time,side,volume,price,profit,comment,journaled_at,
     position_id,commission,swap,entry_commission. `str(r.get('at') or '')`
     is therefore '' for EVERY row, and '' >= '2026-09-09' is False →
     the count is 0 forever, whatever the system does.
  2. Even swapping in the real column fails as a STRING compare:
     `close_time` is a UNIX-EPOCH string ('1788989529'), and
     '1788989529' < '2026-09-09' lexicographically ('1' < '2') → 0 again.

Both mistakes are the b116 class ("before quoting live behaviour, ask which
population you are actually reading") and the b135 class (a decision trigger
must not be a sign test on a string). b183's whole closure path depended on
this line, so it needs a real, dated, unit-tested predicate — which is what
this module is.

WHAT IT MEASURES (all read-only, no gate touched)
-------------------------------------------------
* Closes are parsed the way engines/learning.py parses them: epoch digits →
  UTC datetime, ISO → UTC datetime, anything else → EXCLUDED (never guessed).
* Rows are GROUPED BY POSITION first (engines.learning.group_positions).
  A b182-lane trade emits several OUT deals (TP1 half + runner), so counting
  JOURNAL ROWS would inflate n — b183 asks for ~30 TRADES of the new policy.
* `lot` for a position is its max leg volume (same rule as group_positions).
* It reports the 0.01-lot population separately, because that is the lane
  b183's option (c) needs data for; if it is still empty at n>=30, the item
  closes as option (a) ACCEPT rather than being re-opened.

HARD RULES respected: nothing here is imported by the live trading path, no
bridge call at all, no order endpoint, no gate/threshold changed.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# b182 (half + runner exit policy) shipped 2026-09-09 05:00Z (52827ad).
# Only closes AT OR AFTER this date are priced by the new policy.
POLICY_SHIP_UTC_DATE = "2026-09-09"
# b183's own wording: "needs ~30 trades of the new policy".
REOPEN_MIN_TRADES = 30

JOURNAL_FIELDS = ("close_time", "position_id", "ticket", "volume")


def _close_dt(raw) -> datetime | None:
    """Journal close_time → aware UTC datetime, or None if unusable.

    Mirrors engines/learning.py::_trade_time (the live reader of this exact
    column): all-digit → UNIX SECONDS, otherwise ISO; naive ISO is assumed
    UTC. Anything else returns None so the row is EXCLUDED, not guessed.
    """
    s = str(raw or "").strip()
    if not s:
        return None
    if s.isdigit():
        try:
            return datetime.fromtimestamp(int(s), tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    try:
        ts = datetime.fromisoformat(s)
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def positions_since_ship(journal_path: Path | str,
                         ship_date: str = POLICY_SHIP_UTC_DATE) -> dict:
    """Group the journal into positions and split them around the ship date.

    Returns a dict with: rows_total, rows_unparseable, positions_total,
    positions_post (the n b183 needs), post_volumes (volume → count),
    post_001_count, reopen_met, reopen_needs.
    """
    from engines.learning import group_positions

    path = Path(journal_path)
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)

    # a row whose close_time cannot be dated is EXCLUDED and counted loudly —
    # silently dropping it would make n look smaller with no trace (b37 class).
    dated: list[tuple[dict, datetime]] = []
    unparseable = 0
    for r in rows:
        dt = _close_dt(r.get("close_time"))
        if dt is None:
            unparseable += 1
        else:
            dated.append((r, dt))

    def pos_key(r: dict) -> str:
        # same key rule as engines.learning.group_positions
        return str(r.get("position_id") or "").strip() or f"t:{r.get('ticket')}"

    # one pass: position key -> latest close datetime
    latest: dict[str, datetime] = {}
    for r, dt in dated:
        k = pos_key(r)
        if k not in latest or dt > latest[k]:
            latest[k] = dt

    groups = group_positions([r for r, _ in dated])   # live aggregation rules
    post = {k: g for k, g in groups.items()
            if k in latest and latest[k].date().isoformat() >= ship_date}

    volumes: dict[str, int] = {}
    n_001 = 0
    for g in post.values():
        vol = round(float(g.get("volume") or 0), 2)
        key = f"{vol:.2f}"
        volumes[key] = volumes.get(key, 0) + 1
        if abs(vol - 0.01) < 1e-9:
            n_001 += 1

    n = len(post)
    return {
        "journal": str(path),
        "ship_date_utc": ship_date,
        "rows_total": len(rows),
        "rows_unparseable_close_time": unparseable,
        "positions_total": len(groups),
        "positions_post_ship": n,
        "post_lot_mix": dict(sorted(volumes.items())),
        "post_001_lot_positions": n_001,
        "reopen_needs": REOPEN_MIN_TRADES,
        "reopen_met": n >= REOPEN_MIN_TRADES,
        # what the parked wording would have computed — kept so a future run
        # can SEE the dead predicate rather than re-derive it.
        "dead_predicate_rows_matched_at_column": sum(
            1 for r in rows if str(r.get("at") or "")[:10] >= ship_date),
        "dead_predicate_rows_matched_close_time_string": sum(
            1 for r in rows if str(r.get("close_time") or "") >= ship_date),
    }


def journal_path() -> Path:
    """Resolve through engines.paths so HERMES_DATA_ROOT can redirect it."""
    from engines import paths
    return paths.plan_dir() / "trade_journal.csv"


def main() -> int:
    out = positions_since_ship(journal_path())
    print(json.dumps(out, ensure_ascii=False, indent=2))
    verdict = ("REOPEN b183 (n=%d >= %d)" if out["reopen_met"] else
               "STAY PARKED (n=%d < %d)") % (
        out["positions_post_ship"], out["reopen_needs"])
    print(f"\nb183 gate: {verdict}")
    if out["reopen_met"] and out["post_001_lot_positions"] == 0:
        print("NOTE: sample is large enough but the 0.01-lot lane produced "
              "ZERO positions — b183 closes as option (a) ACCEPT, no code.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
