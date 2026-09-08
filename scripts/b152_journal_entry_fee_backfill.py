"""b152 one-time repair: backfill entry_commission into the live journal.

Why this script exists: engines/learning.journal() only migrates the journal
while the header is NARROWER than JOURNAL_FIELDS. The 12th column
(entry_commission) landed while a live cycle had already widened the header —
so _ensure_journal_schema would now skip forever and existing rows would
silently carry 0.0 of IN-deal fee: the exact "looks fixed, still blind" trap
b142 warns about. This script runs the backfill once, directly, against the
real 30-day deal feed.

Mechanics (all lossless, read-only bridge):
  - fetch deals, aggregate each position's IN-deal commission by position_id;
  - prorate the fee across that position's closing legs by volume (the same
    _entry_fee_share the writer uses — imported, not restated);
  - rewrite the file through learning._migrate_journal (the tested writer);
  - print journal net before/after vs the broker's all-in per position, so
    the parity claim is measured, not asserted.

A row whose position has no IN deal in the window keeps '' (honest zero).
Usage: python3 scripts/b152_journal_entry_fee_backfill.py [--dry-run]
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env_loader import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")
from bridge_client import BridgeClient  # noqa: E402
from engines import learning  # noqa: E402

JOURNAL = ROOT / "data" / "xau_plan" / "trade_journal.csv"
OUT = ROOT / "data" / "backtest" / "b152_entry_fee_backfill.json"


def num(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def journal_net_by_pos(rows):
    agg = defaultdict(float)
    for r in rows:
        key = str(r.get("position_id") or "").strip() or f"t:{r.get('ticket')}"
        agg[key] += num(r.get("profit")) + num(r.get("commission")) \
            + num(r.get("swap")) + num(r.get("entry_commission"))
    return agg


def main(dry_run: bool):
    r = BridgeClient().get_history_deals("XAUUSD", 45)
    if not (isinstance(r, dict) and r.get("ok")):
        print("bridge deals feed unavailable — refusing to touch the journal")
        return 1
    deals = r.get("data") or []
    by_ticket = {str(d.get("ticket")): d for d in deals}
    fees = learning._entry_fee_totals(deals)

    rows = list(csv.DictReader(JOURNAL.open(newline="", encoding="utf-8")))
    before = journal_net_by_pos(rows)

    if dry_run:
        n_fill = 0
        for row in rows:
            pid = str(row.get("position_id") or "").strip()
            if not (row.get("entry_commission") or "").strip() \
                    and learning._entry_fee_share(fees, {
                        "position_id": pid, "volume": row.get("volume")}):
                n_fill += 1
        print(f"[dry-run] rows that would gain an entry fee: {n_fill}/{len(rows)}")
        return 0

    learning._migrate_journal(JOURNAL, by_ticket, fees)

    after_rows = list(csv.DictReader(JOURNAL.open(newline="", encoding="utf-8")))
    after = journal_net_by_pos(after_rows)

    broker = defaultdict(float)
    for d in deals:
        pid = str(d.get("position_id") or d.get("order") or "")
        if pid:
            broker[pid] += num(d.get("profit")) + num(d.get("commission")) \
                + num(d.get("swap"))
    overlap = [p for p in broker if p in after]
    gap = {p: round(after[p] - broker[p], 2) for p in overlap}
    still_off = {p: g for p, g in gap.items() if abs(g) > 0.01}

    # row-count / column integrity
    header = next(csv.reader(JOURNAL.open(newline="", encoding="utf-8")))
    assert header == learning.JOURNAL_FIELDS, header
    assert len(after_rows) == len(rows), "migration lost or duplicated rows"

    tb, ta = sum(before.values()), sum(after.values())
    tbk = sum(broker[p] for p in overlap)
    print(f"positions: {len(after)} | total net {tb:+.2f} -> {ta:+.2f}")
    print(f"broker all-in on the same {len(overlap)} positions: {tbk:+.2f}")
    print(f"positions still disagreeing (>0.01): {len(still_off)} {still_off}")
    OUT.write_text(json.dumps({
        "before_total_net": round(tb, 2),
        "after_total_net": round(ta, 2),
        "broker_net_overlap": round(tbk, 2),
        "positions": len(overlap),
        "positions_disagreeing": len(still_off),
    }, indent=1), encoding="utf-8")
    print(f"ledger -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main("--dry-run" in sys.argv))
