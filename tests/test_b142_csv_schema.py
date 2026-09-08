"""b142 — "ADD A COLUMN TO THE CSV LOG" IS A SCHEMA MIGRATION, NOT AN EXTRA KEY.

Filed by the b139 probe (2026-09-08). b139 asks for an `execution_style` column
on execution_log.csv so the only per-trade risk damper (STYLE_RISK_MULT 0.5)
can be audited from history. Before writing anything, this file asks the
cheapest question that decides the shape of that fix: can the shared writer
even carry a new column into an EXISTING ledger?

Answer, measured here against the real engines/storage._append_csv_row: NO.
The header is written only when the file does not exist, so a 13th key on a
12-column ledger writes the VALUE and never the COLUMN NAME, and
csv.DictReader — the reader every consumer uses (engines/learning.py's exec
join, notifier/dashboards, scripts/weekly_report, the bNN censuses) — folds
the extra field under the None restkey. The file LOOKS fixed and the audit
question stays unanswerable.

So this is a tripwire against the no-op fix, not a proof of a good one: it
asserts the CURRENT (bad) shape so that whoever ships b139 must either
(a) migrate the header for real — which flips THIS test and must be edited
with a dated note, never deleted (b102's rule) — or (b) write a sidecar
ledger, which leaves this test green and untouched.

Anti-vacuity: the same probe also seeds an OLD-schema row and reads the file
back the way the consumers do, so the failure mode is demonstrated on a file
that really has two schemas in it, not asserted on the dict handed to the
writer (b122: measure what the reader was given).
"""
from __future__ import annotations

import csv
import io
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engines.storage import _append_csv_row  # noqa: E402

# The 12 columns the LIVE execution_log.csv has carried since git 8fbde21
# (2026-08-29). Read from the real file, never restated from memory (b109).
LIVE_LOG = REPO / "data" / "xau_plan" / "execution_log.csv"


def _live_header() -> list[str]:
    with LIVE_LOG.open(newline="", encoding="utf-8-sig") as f:
        return next(csv.reader(f))


class TestLiveLedgerShape(unittest.TestCase):
    """The premise of the whole item: the ledger exists and is 12-wide."""

    def test_execution_log_exists_with_a_twelve_column_header(self):
        self.assertTrue(LIVE_LOG.exists(),
                        "the premise of b142 is the EXISTING ledger; if this "
                        "file is gone the migration question is moot")
        self.assertEqual(len(_live_header()), 12, _live_header())

    def test_every_live_row_has_exactly_the_header_width(self):
        """No row already carries a 13th field — so the trap below is live,
        not hypothetical: the next appended row is the first to differ."""
        rows = list(csv.reader(io.StringIO(
            LIVE_LOG.read_text(encoding="utf-8-sig"))))
        widths = {len(r) for r in rows[1:]}
        self.assertEqual(widths, {12}, f"row widths {widths}")


class TestAppendCsvRowCannotMigrateTheHeader(unittest.TestCase):
    def _seed_old_schema(self, path: Path) -> dict:
        row = {k: "v" for k in _live_header()}
        _append_csv_row(path, row)
        return row

    def test_b142_a_new_key_on_an_existing_ledger_is_invisible_to_DictReader(
            self,):
        """THE name-carrier. If this test ever goes RED because the writer
        learned to migrate its header, b139's option (a) shipped — EDIT this
        docstring and the assertion with a dated note, do not delete it."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "execution_log.csv"
            old = self._seed_old_schema(p)
            new = dict(old, execution_style="aggressive_discount_entry")
            _append_csv_row(p, new)

            with p.open(newline="", encoding="utf-8") as f:
                header = next(csv.reader(f))
            self.assertNotIn("execution_style", header,
                             "the writer DID migrate the header — b139 option "
                             "(a) shipped; edit this pin deliberately (b102)")
            self.assertEqual(header, _live_header())

            with p.open(newline="", encoding="utf-8") as f:
                read = list(csv.DictReader(f))
            self.assertEqual(len(read), 2)
            # The value survived the write...
            self.assertEqual(read[1].get(None), ["aggressive_discount_entry"])
            # ...and is unreachable by name, which is all any consumer does.
            self.assertIsNone(read[1].get("execution_style"))
            self.assertNotIn("execution_style", read[1])

    def test_the_same_key_on_a_FRESH_ledger_is_visible(self):
        """Boundary in the other direction: the writer is fine when it owns
        the header. So the defect is specifically 'new key, existing file',
        and a sidecar ledger (b139 option b) is a real fix, not a workaround
        for a bug that would follow it there too."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "risk_ledger.csv"
            row = {k: "v" for k in _live_header()}
            _append_csv_row(p, dict(row, execution_style="trend_pullback"))
            with p.open(newline="", encoding="utf-8") as f:
                read = list(csv.DictReader(f))
            self.assertEqual(read[0]["execution_style"], "trend_pullback")
            self.assertIsNone(read[0].get(None))


class TestB139StillNeedsADecision(unittest.TestCase):
    def test_b139_is_still_parked_as_a_todo(self):
        """This round filed the trap; it did NOT ship the fix. If b139 closes
        without this pin being edited, the closure happened on the no-op
        shape and the audit question is still unanswerable."""
        text = (REPO / "data" / "ops" / "autopilot_backlog.md").read_text(
            encoding="utf-8")
        line = next((ln for ln in text.splitlines()
                     if "b139 TRADER OBSERVABILITY" in ln), None)
        self.assertIsNotNone(line, "b139 must stay filed")
        self.assertIn("[ ]", line,
                      "b139 shipped — if it shipped via option (a) the header "
                      "test above must be EDITED with a dated note, not "
                      "deleted (b102)")


if __name__ == "__main__":
    unittest.main()
