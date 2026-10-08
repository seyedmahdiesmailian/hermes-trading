#!/usr/bin/env python3
"""Rebuild hermes_state.db from the three CSV journals (WP4, 2026-09-18).

Full REBUILD, not incremental: the existing db (plus -wal/-shm sidecars) is
unlinked first, then every row of execution_log.csv, risk_ledger.csv and
trade_journal.csv is re-inserted. Safe by construction — the CSVs are only
ever read, never modified; the live trading path never reads the db.

Resolves the plan tree exactly like the producers (HERMES_DATA_ROOT wins,
else the production data/ tree), so:
  HERMES_DATA_ROOT=/tmp/probe python3 scripts/backfill_sqlite.py
rebuilds a scratch tree without touching live state.

Prints one JSON line: {"db": ..., "csv": {table: rows}, "sqlite": {table: rows},
"match": bool}. Exit 0 on full parity, 1 on any mismatch.
"""
import csv
import json
import os
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing -> local fallback
load_dotenv(os.path.join(_ROOT, '.env'))

from engines import paths, store

TABLE_FILES = {
    "execution_log": "execution_log.csv",
    "risk_ledger": "risk_ledger.csv",
    "trade_journal": "trade_journal.csv",
}


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline='', encoding='utf-8') as f:
        return [dict(r) for r in csv.DictReader(f) if r]


def main() -> int:
    plan_dir = paths.plan_dir()
    db = plan_dir / store.DB_FILENAME
    # Full rebuild: drop the old db and its WAL sidecars first.
    for victim in (db, db.with_suffix('.db-wal'), db.with_suffix('.db-shm')):
        try:
            victim.unlink(missing_ok=True)
        except OSError:
            pass
    csv_counts: dict[str, int] = {}
    conn = store._connect(db)
    try:
        store.ensure_schema(conn)
        with conn:
            for table, fname in TABLE_FILES.items():
                rows = _read_csv(plan_dir / fname)
                csv_counts[table] = store._insert_rows(conn, table, rows)
    finally:
        conn.close()
    sqlite_counts = store.row_counts()
    match = all(sqlite_counts[t] == csv_counts[t] for t in TABLE_FILES)
    print(json.dumps({"db": str(db), "csv": csv_counts,
                      "sqlite": sqlite_counts, "match": match}))
    return 0 if match else 1


if __name__ == "__main__":
    sys.exit(main())
