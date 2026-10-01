"""SQLite mirror of the three CSV journals (WP4, 2026-09-18).

Why this exists: the CSVs are append-only logs with no index. Every learning
pass re-scans megabytes of text (b133's audit: the full history is re-read on
each cycle), header migrations are hand-rolled per file (b144), and a new
column mid-tuple silently misaligns every reader (b142's rule). SQLite gives
indexed, typed, queryable history.

Design contract (read before touching):
  1. CSV is the SOURCE OF TRUTH. Every mirror call runs AFTER a successful
     CSV write and is FAIL-OPEN: any sqlite error is swallowed and the CSV
     path is unaffected. No reader may consume SQLite yet (readers stay on
     CSV until Faz3 proves parity on live data).
  2. Columns are TEXT, mirroring the CSV string form exactly: ``""`` for None,
     else ``str(value)``. No type coercion — a mirror must byte-match the CSV
     under ``SELECT`` vs ``csv.DictReader`` (see tests/test_store_parity.py).
  3. Unknown keys are preserved in ``extra_json``, never dropped and never
     promoted to columns (b142's rule: adding a column is a schema migration).
  4. Column lists are pinned to the producers by test, not by import: this
     module must NOT import engines.learning or engines.storage (both import
     this module for the dual-write hooks — importing them back would be a
     cycle). tests/test_store_parity.py asserts
     ``STORE_COLS == producer field lists`` so drift fails loudly.
  5. Backfill is a full REBUILD (scripts/backfill_sqlite.py unlinks the db
     first). No UNIQUE constraints: the CSVs are the dedup gate (journal()
     skips known (ticket, close_time); exec/ledger rows are never rewritten),
     so a live mirror can never insert a row the CSV doesn't have.

WAL mode is enabled so a reader never blocks the trading cycle's writes.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from engines import paths  # resolved at CALL time so tests can redirect the tree

DB_FILENAME = "hermes_state.db"

# Pinned by tests/test_store_parity.py against the producers:
#   EXEC_COLS       == the 12-wide execution_log header (b142)
#   RISK_COLS       == storage.RISK_LEDGER_FIELDS (b139/b144)
#   JOURNAL_COLS    == learning.JOURNAL_FIELDS (b152)
EXEC_COLS = ("at", "plan_id", "side", "lot", "entry", "sl", "tp", "grade",
             "risk_usd", "dry_run", "result_ok", "ticket")
RISK_COLS = ("at", "lane", "plan_id", "side", "lot", "entry", "sl", "tp",
             "grade", "base_risk_pct", "learning_risk_mult", "execution_style",
             "style_mult", "defcon_override", "regime", "regime_mult",
             "final_risk_pct", "risk_usd", "ticket")
JOURNAL_COLS = ("ticket", "close_time", "side", "volume", "price", "profit",
                "comment", "journaled_at", "position_id", "commission",
                "swap", "entry_commission")

_TABLE_COLS = {
    "execution_log": EXEC_COLS,
    "risk_ledger": RISK_COLS,
    "trade_journal": JOURNAL_COLS,
}


def db_path(base_dir: str | Path | None = None) -> Path:
    """SQLite file for a plan tree. Same resolution rule as
    storage.ensure_xau_plan_dirs: explicit base_dir wins, else paths.plan_dir().
    """
    root = Path(base_dir) if base_dir else paths.plan_dir()
    return root / DB_FILENAME


def _connect(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    for table, cols in _TABLE_COLS.items():
        col_defs = ", ".join(f'"{c}" TEXT' for c in cols)
        conn.execute(
            f'CREATE TABLE IF NOT EXISTS "{table}" '
            f"(_rowid INTEGER PRIMARY KEY AUTOINCREMENT, {col_defs}, "
            f'"extra_json" TEXT)'
        )
        for idx_col in ("ticket", "at", "close_time", "plan_id"):
            if idx_col in cols:
                conn.execute(
                    f'CREATE INDEX IF NOT EXISTS "idx_{table}_{idx_col}" '
                    f'ON "{table}" ("{idx_col}")'
                )


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _insert_rows(conn: sqlite3.Connection, table: str, rows: list[dict]) -> int:
    """Insert dict rows; known columns → TEXT cols, unknown → extra_json."""
    if not rows:
        return 0
    cols = _TABLE_COLS[table]
    placeholders = ", ".join(["?"] * (len(cols) + 1))
    col_names = ", ".join(f'"{c}"' for c in cols) + ', "extra_json"'
    payload = []
    for row in rows:
        extra = {k: row[k] for k in row.keys() if k not in cols}
        payload.append(
            tuple(_to_text(row.get(c, "")) for c in cols)
            + (json.dumps(extra, default=str) if extra else None,)
        )
    conn.executemany(
        f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders})', payload
    )
    return len(rows)


def _mirror(base_dir: str | Path | None, table: str, rows: list[dict]) -> bool:
    """Fail-open workhorse: False on ANY error, CSV caller must ignore it."""
    try:
        conn = _connect(db_path(base_dir))
        try:
            ensure_schema(conn)
            with conn:
                _insert_rows(conn, table, rows)
        finally:
            conn.close()
        return True
    except Exception:
        return False


def mirror_execution(base_dir: str | Path | None, row: dict) -> bool:
    """Mirror one execution_log row. Call AFTER the CSV write succeeds."""
    return _mirror(base_dir, "execution_log", [row])


def mirror_risk_ledger(base_dir: str | Path | None, row: dict) -> bool:
    """Mirror one risk_ledger row. Call AFTER the CSV write succeeds."""
    return _mirror(base_dir, "risk_ledger", [row])


def mirror_journal(rows: list[dict]) -> bool:
    """Mirror journal() rows. journal() uses the global paths root (no base_dir
    parameter), so this resolves the db from paths.plan_dir() — the same tree
    that holds trade_journal.csv."""
    return _mirror(None, "trade_journal", rows)


def row_counts(base_dir: str | Path | None = None) -> dict[str, int]:
    """Per-table row counts (for backfill verification / monitoring)."""
    db = db_path(base_dir)
    if not db.exists():
        return {t: 0 for t in _TABLE_COLS}
    conn = sqlite3.connect(str(db), timeout=10)
    try:
        ensure_schema(conn)
        return {
            t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            for t in _TABLE_COLS
        }
    finally:
        conn.close()
