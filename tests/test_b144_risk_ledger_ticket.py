"""b144 — the risk ledger gets a TICKET column, and the column must be real.

The defect (filed by b143's reader, which found it by having to WRITE the
join): RISK_LEDGER_FIELDS carried plan_id but no ticket, so a sidecar row
could not reach realized P&L on its own key. The plan lane survived via
execution_log (plan_id is unique per proposal); EVERY signal-lane row says
plan_id='signal', so b138's pending question — "did the 0.25x double-charge
trade actually lose less money?" — was unanswerable for the lane that trades
most.

b142's rule says adding a column to an existing CSV ledger is a SCHEMA
MIGRATION, not an extra key, so this change ships three things and this test
locks all three:

  1. SCHEMA — `ticket` is in RISK_LEDGER_FIELDS, and it is LAST. That is not
     cosmetic: the live daemons still run pre-b144 code and append 18-value
     rows. Under a 19-wide header a SHORT row simply leaves the last cell
     empty (csv only folds EXTRA values under the None restkey), so an
     old-code row stays readable. A column inserted anywhere else would
     misalign every subsequent field for as long as the daemons drift.
  2. MIGRATION — storage._migrate_risk_ledger_header widens an existing
     18-column file in place, preserving every row (learning._migrate_journal
     is the precedent), and REFUSES a header that is not a strict prefix of
     the shipped schema rather than guessing with someone's audit data.
  3. READABILITY + WIRING — a DictReader round-trip on a file seeded with an
     OLD-schema row proves ticket comes back as a NAMED column (never the
     restkey), both lane call sites pass a ticket, and the b143 reader joins
     on the row's own ticket so a signal-lane row is finally joinable.

Additive/observability only: no gate, no lot, no verdict may move.
"""
import ast
import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from engines import storage  # noqa: E402
from engines.storage import (RISK_LEDGER_FIELDS, append_risk_ledger,  # noqa: E402
                             _migrate_risk_ledger_header)

import b143_risk_ledger_reader as R  # noqa: E402

# The exact header the ledger shipped with before b144 (b139, 2026-09-08).
OLD_FIELDS = ("at", "lane", "plan_id", "side", "lot", "entry", "sl", "tp",
              "grade", "base_risk_pct", "learning_risk_mult",
              "execution_style", "style_mult", "defcon_override", "regime",
              "regime_mult", "final_risk_pct", "risk_usd")


def _old_row(**over):
    row = {k: "" for k in OLD_FIELDS}
    row.update({"at": "2026-09-08T04:30:00+00:00", "lane": "signal",
                "plan_id": "signal", "side": "SELL", "lot": "0.02",
                "entry": "3600.0", "sl": "3610.0", "tp": "3575.0",
                "grade": "signal", "base_risk_pct": "0.0105",
                "learning_risk_mult": "1.0",
                "execution_style": "aggressive_retest", "style_mult": "0.5",
                "defcon_override": "None", "regime": "normal",
                "regime_mult": "1.0", "final_risk_pct": "0.00525",
                "risk_usd": "26.25"})
    row.update(over)
    return row


def _seed_old_ledger(path: Path, rows) -> None:
    """Write a file exactly as pre-b144 storage would have."""
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(OLD_FIELDS))
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in OLD_FIELDS})


class TestSchemaShape(unittest.TestCase):
    def test_b144_ticket_is_a_named_column_and_is_last(self):
        self.assertIn("ticket", RISK_LEDGER_FIELDS)
        self.assertEqual(RISK_LEDGER_FIELDS[-1], "ticket",
                         "ticket must stay LAST: the live daemons run "
                         "pre-b144 code and append 18-value rows; a short row "
                         "leaves the last cell empty, a column inserted "
                         "mid-tuple would misalign every field after it")

    def test_b144_old_header_is_a_strict_prefix_of_the_new_one(self):
        """The property the migration depends on. If someone reorders the
        tuple, this fails and the migration's prefix guard stops being a
        safety net (it would start refusing real ledgers)."""
        self.assertEqual(RISK_LEDGER_FIELDS[:len(OLD_FIELDS)], OLD_FIELDS)
        self.assertEqual(len(RISK_LEDGER_FIELDS), len(OLD_FIELDS) + 1)


class TestMigration(unittest.TestCase):
    def test_existing_ledger_is_widened_without_losing_rows(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _seed_old_ledger(d / "risk_ledger.csv", [_old_row()])
            append_risk_ledger(d, dict(_old_row(at="2026-09-08T05:00:00+00:00"),
                                       ticket=105127383))
            with (d / "risk_ledger.csv").open(newline="",
                                              encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            header = (d / "risk_ledger.csv").read_text(
                encoding="utf-8").splitlines()[0]
        self.assertEqual(header, ",".join(RISK_LEDGER_FIELDS))
        self.assertEqual(len(rows), 2, "the pre-existing row must survive")
        for r in rows:
            self.assertIsNone(r.get(None), "b142's restkey trap")
            self.assertEqual(r["execution_style"], "aggressive_retest")
            self.assertEqual(r["final_risk_pct"], "0.00525")
        self.assertEqual(rows[0]["ticket"], "", "old row: honest empty")
        self.assertEqual(rows[1]["ticket"], "105127383")

    def test_no_temp_file_is_left_behind(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _seed_old_ledger(d / "risk_ledger.csv", [_old_row()])
            append_risk_ledger(d, dict(_old_row(), ticket=1))
            leftovers = [p.name for p in d.iterdir()
                         if p.name.endswith(".tmp")]
            self.assertEqual(leftovers, [])

    def test_a_foreign_header_is_refused_not_overwritten(self):
        """An unknown column means an unknown writer. Guessing would destroy
        someone's audit data, so the migration raises and the file stays
        byte-identical (the lane's try/except then drops the audit row —
        missing data is honest, corrupt data is not)."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "risk_ledger.csv"
            with p.open("w", newline="", encoding="utf-8") as f:
                f.write("at,lane,mystery\n2026-09-08T04:30:00+00:00,plan,x\n")
            before = p.read_bytes()
            with self.assertRaises(RuntimeError):
                _migrate_risk_ledger_header(p)
            self.assertEqual(p.read_bytes(), before)

    def test_append_on_a_foreign_ledger_never_corrupts_it(self):
        """The live shape: storage.append_risk_ledger is wrapped in
        try/except at both call sites, so a refusal must leave the file
        intact rather than half-write a 19-wide row under a 3-wide header."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = d / "risk_ledger.csv"
            with p.open("w", newline="", encoding="utf-8") as f:
                f.write("at,lane,mystery\n2026-09-08T04:30:00+00:00,plan,x\n")
            before = p.read_bytes()
            with self.assertRaises(Exception):
                append_risk_ledger(d, dict(_old_row(), ticket=7))
            self.assertEqual(p.read_bytes(), before)

    def test_a_concurrent_append_aborts_the_migration(self):
        """The live daemons run pre-b144 code and append to this same file.
        If a row lands mid-rewrite, replacing the file would silently DROP it
        — an audit ledger that loses a trade is worse than one that gains
        none — so the migration bails and leaves the original intact."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "risk_ledger.csv"
            _seed_old_ledger(p, [_old_row()])
            real_writer = csv.DictWriter

            class _RacingWriter(real_writer):
                def writerow(self, row):
                    super().writerow(row)
                    if not getattr(self, "_raced", False):
                        self._raced = True
                        with p.open("a", newline="",
                                    encoding="utf-8") as g:
                            g.write(",".join(["9"] * len(OLD_FIELDS)) + "\n")

            storage.csv.DictWriter = _RacingWriter
            try:
                with self.assertRaises(RuntimeError):
                    _migrate_risk_ledger_header(p)
            finally:
                storage.csv.DictWriter = real_writer
            with p.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2, "original rows must survive")
            self.assertEqual([q.name for q in p.parent.iterdir()],
                             ["risk_ledger.csv"], "no .tmp left behind")

    def test_fresh_ledger_gets_the_full_header(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            append_risk_ledger(d, dict(_old_row(), ticket=555))
            text = (d / "risk_ledger.csv").read_text(encoding="utf-8")
        self.assertEqual(text.splitlines()[0], ",".join(RISK_LEDGER_FIELDS))
        self.assertIn("555", text)


class TestWiring(unittest.TestCase):
    """AST scan: both lanes must hand the writer a ticket. A refactor that
    drops one silently re-creates the defect this item fixed."""

    def _kwargs(self, path, func):
        """Keywords of the dict(...) payload inside each append_risk_ledger(
        ...) call — the lanes build the row with dict(stack, field=...), so
        the fields are keywords of the INNER call, not the outer one."""
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        hits = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == func):
                keys = set()
                for arg in node.args:
                    if (isinstance(arg, ast.Call)
                            and getattr(arg.func, "id", None) == "dict"):
                        keys |= {k.arg for k in arg.keywords if k.arg}
                keys |= {k.arg for k in node.keywords if k.arg}
                hits.append(keys)
        return hits

    def test_plan_lane_passes_a_ticket(self):
        calls = self._kwargs(ROOT / "hermes_runtime.py", "append_risk_ledger")
        self.assertEqual(len(calls), 1, calls)
        self.assertIn("ticket", calls[0])

    def test_signal_lane_helper_accepts_and_forwards_a_ticket(self):
        src = (ROOT / "engines" / "signal_listener.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_log_signal_risk_stack")
        self.assertIn("ticket", [a.arg for a in fn.args.args])
        inner = self._kwargs(ROOT / "engines" / "signal_listener.py",
                             "append_risk_ledger")
        self.assertEqual(len(inner), 1)
        self.assertIn("ticket", inner[0])

    def test_both_signal_exec_paths_pass_the_ticket(self):
        """limit_pending path and market path — the b139 pin counted calls;
        this one counts calls that actually carry a ticket argument."""
        tree = ast.parse((ROOT / "engines" / "signal_listener.py").read_text(
            encoding="utf-8"))
        with_ticket = 0
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None)
                    == "_log_signal_risk_stack"):
                self.assertIn("ticket", {k.arg for k in node.keywords},
                              f"line {node.lineno}: a signal exec path logs "
                              "the stack without a ticket")
                with_ticket += 1
        self.assertEqual(with_ticket, 2)

    def test_the_ticket_is_the_same_value_execution_log_records(self):
        """b122's identity rule: the sidecar must carry the SAME key the
        journal joins on, not a lookalike. Text pin on both lanes: the ledger
        ticket expression is the expression execution_log already used."""
        rt = (ROOT / "hermes_runtime.py").read_text(encoding="utf-8")
        seg = rt[rt.index("b139: per-trade risk-stack audit"):]
        seg = seg[:seg.index("except Exception")]
        self.assertIn("'ticket'", seg)
        self.assertIn("execution_result.get('result')", seg)
        sl = (ROOT / "engines" / "signal_listener.py").read_text(
            encoding="utf-8")
        # market path: same source as the execution_log ticket line
        self.assertEqual(
            sl.count('ticket=(result.get("result") or {}).get("ticket")'), 1)
        self.assertIn("ticket=pres.get(\"ticket\")", sl)


class TestReaderUsesTheNewKey(unittest.TestCase):
    """The reader is the reason the column exists. It must actually prefer it."""

    def _journal(self, tmp, position_id="9001", ticket="9001"):
        p = Path(tmp) / "trade_journal.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["ticket", "close_time", "side",
                                              "volume", "price", "profit",
                                              "comment", "journaled_at",
                                              "position_id", "commission",
                                              "swap"])
            w.writeheader()
            w.writerow({"ticket": "5001", "close_time": "1760000000",
                        "side": "SELL", "volume": "0.01", "price": "3590",
                        "profit": "10.00", "comment": "", "journaled_at": "",
                        "position_id": position_id, "commission": "-0.5",
                        "swap": "0.0"})
            w.writerow({"ticket": "5002", "close_time": "1760000500",
                        "side": "SELL", "volume": "0.01", "price": "3585",
                        "profit": "5.00", "comment": "", "journaled_at": "",
                        "position_id": position_id, "commission": "0.0",
                        "swap": "-0.2"})
        return p

    def test_signal_lane_row_is_now_joinable_on_its_own_ticket(self):
        """THE point of b144: the lane that trades most was unauditable."""
        with tempfile.TemporaryDirectory() as tmp:
            journal = R.read_journal_tickets(self._journal(tmp))
            row = _old_row(ticket="9001")
            out = R.join_to_tickets([row], [], journal)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["joinable"], out[0])
        self.assertEqual(out[0]["join_path"], "row_ticket")
        self.assertEqual(out[0]["ticket"], "9001")
        self.assertEqual(out[0]["close_deals"], 2)
        self.assertAlmostEqual(out[0]["realized_net"], 14.3, places=4)

    def test_pre_b144_signal_row_still_reports_unjoinable_not_a_guess(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = R.read_journal_tickets(self._journal(tmp))
            out = R.join_to_tickets([_old_row()], [], journal)
        self.assertFalse(out[0]["joinable"])
        self.assertIn("pre-b144", out[0]["join_error"])

    def test_pre_b144_plan_row_falls_back_to_the_plan_id_join(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = R.read_journal_tickets(self._journal(tmp))
            exec_rows = [{"at": "2026-09-08T04:30:05+00:00",
                          "plan_id": "xau-test01", "result_ok": "True",
                          "ticket": "9001"}]
            row = _old_row(lane="plan", plan_id="xau-test01")
            out = R.join_to_tickets([row], exec_rows, journal)
        self.assertTrue(out[0]["joinable"], out[0])
        self.assertEqual(out[0]["join_path"], "plan_id_fallback")
        self.assertAlmostEqual(out[0]["realized_net"], 14.3, places=4)

    def test_a_ticket_with_no_journal_row_reports_none(self):
        """A limit row's ticket is the PENDING order ticket, not the position
        key — so it legitimately may not resolve. Honest None, no invention."""
        with tempfile.TemporaryDirectory() as tmp:
            journal = R.read_journal_tickets(self._journal(tmp))
            out = R.join_to_tickets([_old_row(ticket=103493774)], [], journal)
        self.assertTrue(out[0]["joinable"])
        self.assertIsNone(out[0]["realized_net"])
        self.assertIn("no journal row", out[0]["join_note"])

    def test_derive_reports_the_ticket_join_for_a_signal_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = R.read_journal_tickets(self._journal(tmp))
            d = R.derive([_old_row(ticket="9001")], [], journal)
        self.assertEqual(d["ticket_join"][0]["realized_net"], 14.3)


class TestNoGateChanged(unittest.TestCase):
    """Hard rule: this is observability. Nothing here may alter a lot, a
    verdict, or a risk number — the ledger is written AFTER execute_trade."""

    def test_storage_change_is_confined_to_the_risk_ledger(self):
        src = Path(ROOT / "engines" / "storage.py").read_text(
            encoding="utf-8")
        # the shared writer that backs execution_log/reassessment_log is
        # untouched — only the sidecar path gained a migration
        self.assertIn("def _append_csv_row", src)
        shared = src[src.index("def _append_csv_row"):
                     src.index("def append_execution_log")]
        self.assertIn("fieldnames = list(row.keys())", shared)
        self.assertNotIn("_migrate", shared)

    def test_the_ledger_is_written_after_execution_not_before(self):
        """If the write moved ahead of execute_trade, a ledger failure could
        touch the trade path. Pin the order in the plan lane's source."""
        src = (ROOT / "hermes_runtime.py").read_text(encoding="utf-8")
        self.assertLess(src.index("execution_result = execute_trade("),
                        src.index("append_risk_ledger("))

    def test_reader_still_imports_no_bridge_surface(self):
        src = (ROOT / "scripts" / "b143_risk_ledger_reader.py").read_text()
        for needle in ("bridge_client", "BridgeClient", "requests", "urllib",
                       "open_position", "close_position", "send_order"):
            self.assertNotIn(needle, src)


if __name__ == "__main__":
    unittest.main()
