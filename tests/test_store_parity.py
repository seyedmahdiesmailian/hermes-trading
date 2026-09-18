"""WP4 (2026-09-18): SQLite mirror parity + fail-open contract.

store.py deliberately does NOT import its producers (engines.storage and
engines.learning both import store for the dual-write hooks — importing them
back would be a cycle). The cost of that decoupling is drift risk between the
mirror's column lists and the real CSV schemas, so this file pins them:

  store.EXEC_COLS    == the 12-wide execution_log header (b142's pin)
  store.RISK_COLS    == storage.RISK_LEDGER_FIELDS (b139/b144)
  store.JOURNAL_COLS == learning.JOURNAL_FIELDS (b152)

plus: dual-write writes BOTH stores byte-identical, unknown keys land in
extra_json (b142's rule), a dead SQLite never breaks the CSV path (fail-open),
and scripts/backfill_sqlite.py rebuilds a scratch tree with full parity.

Hermetic: every test redirects the whole tree (hermetic.use_temp_data_root)
or uses an explicit tmp base_dir — nothing here touches live state.
"""
import csv
import json
import os
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hermetic
from engines import learning, paths, storage, store


def _sqlite_rows(db: Path, table: str, cols) -> list[dict]:
    conn = sqlite3.connect(str(db))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)}, '
            f'"extra_json" FROM "{table}" ORDER BY _rowid')
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _csv_rows(path: Path) -> list[dict]:
    with path.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


class TestSchemaPins(unittest.TestCase):
    def test_exec_cols_match_b142_twelve_wide_header(self):
        self.assertEqual(store.EXEC_COLS,
                         ("at", "plan_id", "side", "lot", "entry", "sl", "tp",
                          "grade", "risk_usd", "dry_run", "result_ok",
                          "ticket"))

    def test_risk_cols_match_producer(self):
        self.assertEqual(tuple(store.RISK_COLS),
                         tuple(storage.RISK_LEDGER_FIELDS))

    def test_journal_cols_match_producer(self):
        self.assertEqual(tuple(store.JOURNAL_COLS),
                         tuple(learning.JOURNAL_FIELDS))


class TestDualWrite(unittest.TestCase):
    def setUp(self):
        self.root = hermetic.use_temp_data_root()
        self.plan_dir = self.root / "data" / "xau_plan"

    def tearDown(self):
        hermetic.release()

    def test_execution_log_dual_write_is_byte_identical(self):
        row = {"at": "2026-09-18T00:00:00+00:00", "plan_id": "xau-test",
               "side": "BUY", "lot": 0.15, "entry": 4420.48, "sl": 4414.18,
               "tp": 4430.24, "grade": "B", "risk_usd": 99.88,
               "dry_run": False, "result_ok": True, "ticket": "105702248"}
        storage.append_execution_log(self.plan_dir, row)
        csv_row = _csv_rows(self.plan_dir / "execution_log.csv")[-1]
        lite_row = _sqlite_rows(self.plan_dir / store.DB_FILENAME,
                                "execution_log", store.EXEC_COLS)[-1]
        for col in store.EXEC_COLS:
            self.assertEqual(lite_row[col], csv_row[col], f"col {col}")
        self.assertIsNone(lite_row["extra_json"])

    def test_risk_ledger_dual_write_is_byte_identical(self):
        row = {c: f"v-{c}" for c in storage.RISK_LEDGER_FIELDS}
        row.update({"at": "2026-09-18T00:00:00+00:00", "ticket": "42"})
        storage.append_risk_ledger(self.plan_dir, row)
        csv_row = _csv_rows(self.plan_dir / "risk_ledger.csv")[-1]
        lite_row = _sqlite_rows(self.plan_dir / store.DB_FILENAME,
                                "risk_ledger", store.RISK_COLS)[-1]
        for col in store.RISK_COLS:
            self.assertEqual(lite_row[col], csv_row[col], f"col {col}")

    def test_unknown_keys_land_in_extra_json_not_columns(self):
        row = {"at": "2026-09-18T00:00:00+00:00", "plan_id": "x",
               "future_field": "must-survive"}
        storage.append_execution_log(self.plan_dir, row)
        lite_row = _sqlite_rows(self.plan_dir / store.DB_FILENAME,
                                "execution_log", store.EXEC_COLS)[-1]
        self.assertEqual(json.loads(lite_row["extra_json"]),
                         {"future_field": "must-survive"})
        # ...while the CSV keeps its own behaviour (new header key) untouched.
        csv_row = _csv_rows(self.plan_dir / "execution_log.csv")[-1]
        self.assertEqual(csv_row["future_field"], "must-survive")

    def test_journal_end_to_end_mirrors_closing_deal(self):
        deals = [
            {"ticket": "500", "order": "900", "position_id": "77",
             "entry": "0", "type": "0", "volume": "0.10",
             "commission": "-0.30", "profit": "0.0", "swap": "0.0",
             "time_done": "1788000000"},
            {"ticket": "501", "order": "900", "position_id": "77",
             "entry": "1", "type": "1", "volume": "0.10",
             "commission": "-0.30", "profit": "10.0", "swap": "0.0",
             "time_done": "1788000100"},
        ]

        class Bridge:
            def get_history_deals(self, symbol, days):
                return {"ok": True, "data": deals}

        added = learning.journal(Bridge())
        self.assertEqual(added, 1)
        csv_row = _csv_rows(self.plan_dir / "trade_journal.csv")[-1]
        lite_row = _sqlite_rows(self.plan_dir / store.DB_FILENAME,
                                "trade_journal", store.JOURNAL_COLS)[-1]
        for col in store.JOURNAL_COLS:
            self.assertEqual(lite_row[col], csv_row[col], f"col {col}")


class TestFailOpen(unittest.TestCase):
    def setUp(self):
        self.root = hermetic.use_temp_data_root()
        self.plan_dir = self.root / "data" / "xau_plan"

    def tearDown(self):
        hermetic.release()

    def test_dead_sqlite_never_breaks_csv_path(self):
        orig_connect = store._connect

        def _boom(db):
            raise sqlite3.OperationalError("disk is on fire")

        store._connect = _boom
        try:
            row = {"at": "2026-09-18T00:00:00+00:00", "plan_id": "x"}
            storage.append_execution_log(self.plan_dir, row)  # must not raise
            storage.append_risk_ledger(self.plan_dir, row)  # must not raise
            self.assertFalse(store.mirror_journal([row]))
        finally:
            store._connect = orig_connect
        # CSVs hold the rows despite the dead mirror.
        self.assertEqual(len(_csv_rows(self.plan_dir / "execution_log.csv")), 1)
        self.assertEqual(len(_csv_rows(self.plan_dir / "risk_ledger.csv")), 1)

    def test_row_counts_empty_tree(self):
        self.assertEqual(store.row_counts(self.plan_dir),
                         {"execution_log": 0, "risk_ledger": 0,
                          "trade_journal": 0})


class TestWiring(unittest.TestCase):
    """The fail-open contract hides wiring bugs by design (a NameError in the
    hook is swallowed like any mirror failure) — so these tests assert the
    hooks are CALLED, not just that the CSVs survive. Added 2026-09-18 after
    two hook edits silently failed to land and only the byte-parity tests
    caught them."""

    def setUp(self):
        self.root = hermetic.use_temp_data_root()
        self.plan_dir = self.root / "data" / "xau_plan"

    def tearDown(self):
        hermetic.release()

    def test_execution_hook_is_called(self):
        calls = []
        orig = store.mirror_execution
        store.mirror_execution = lambda b, r: calls.append((b, r)) or True
        try:
            storage.append_execution_log(self.plan_dir, {"plan_id": "x"})
        finally:
            store.mirror_execution = orig
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["plan_id"], "x")

    def test_risk_ledger_hook_is_called(self):
        calls = []
        orig = store.mirror_risk_ledger
        store.mirror_risk_ledger = lambda b, r: calls.append((b, r)) or True
        try:
            storage.append_risk_ledger(self.plan_dir, {"plan_id": "x"})
        finally:
            store.mirror_risk_ledger = orig
        self.assertEqual(len(calls), 1)

    def test_journal_hook_is_called(self):
        calls = []
        orig = store.mirror_journal
        store.mirror_journal = lambda rows: calls.append(rows) or True
        try:
            class Bridge:
                def get_history_deals(self, symbol, days):
                    return {"ok": True, "data": [
                        {"ticket": "501", "order": "900", "position_id": "77",
                         "entry": "1", "type": "1", "volume": "0.10",
                         "commission": "-0.30", "profit": "10.0",
                         "swap": "0.0", "time_done": "1788000100"}]}

            self.assertEqual(learning.journal(Bridge()), 1)
        finally:
            store.mirror_journal = orig
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0]["ticket"], "501")


class TestBackfill(unittest.TestCase):
    def test_backfill_rebuilds_scratch_tree_with_parity(self):
        root = hermetic.use_temp_data_root()
        try:
            plan_dir = root / "data" / "xau_plan"
            exec_rows = [
                {"at": f"2026-09-1{i}T00:00:00+00:00", "plan_id": f"p{i}",
                 "side": "BUY", "lot": "0.05", "entry": "4400",
                 "sl": "4390", "tp": "4410", "grade": "A",
                 "risk_usd": "50", "dry_run": "False", "result_ok": "True",
                 "ticket": str(100 + i)} for i in range(3)]
            with (plan_dir / "execution_log.csv").open(
                    "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(store.EXEC_COLS))
                w.writeheader()
                w.writerows(exec_rows)
            with (plan_dir / "risk_ledger.csv").open(
                    "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(store.RISK_COLS))
                w.writeheader()
                w.writerow({c: "r" for c in store.RISK_COLS})
            # trade_journal.csv deliberately ABSENT (fresh tree) — backfill
            # must report 0 rows for it, not crash.
            env = dict(os.environ)
            env["HERMES_DATA_ROOT"] = str(root)
            proc = subprocess.run(
                [sys.executable, str(REPO / "scripts" / "backfill_sqlite.py")],
                capture_output=True, text=True, timeout=120, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(proc.stdout.strip())
            self.assertTrue(report["match"])
            self.assertEqual(report["csv"],
                             {"execution_log": 3, "risk_ledger": 1,
                              "trade_journal": 0})
            self.assertEqual(report["sqlite"], report["csv"])
            # And the rebuilt db actually holds the data.
            lite = _sqlite_rows(plan_dir / store.DB_FILENAME, "execution_log",
                                store.EXEC_COLS)
            self.assertEqual([r["ticket"] for r in lite], ["100", "101", "102"])
        finally:
            hermetic.release()


if __name__ == "__main__":
    unittest.main()
