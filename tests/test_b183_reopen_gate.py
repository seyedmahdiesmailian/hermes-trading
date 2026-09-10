"""b209 — tests for scripts/b183_reopen_gate.py (the corrected b183 n-gate).

The parked b183 reopening line was measured DEAD two independent ways, and
these tests pin both the death of the old form and the behaviour of the new
predicate. Nothing here touches a live gate or the bridge.
"""
from __future__ import annotations

import csv
import importlib.util
import io
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "b183_reopen_gate", ROOT / "scripts" / "b183_reopen_gate.py")
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)

HDR = ["ticket", "close_time", "side", "volume", "price", "profit", "comment",
       "journaled_at", "position_id", "commission", "swap", "entry_commission"]

SHIP = "2026-09-09"
TS_PRE = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp())
TS_POST = int(datetime(2026, 9, 9, 12, tzinfo=timezone.utc).timestamp())


def _write(rows, tmpdir):
    p = Path(tmpdir) / "trade_journal.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HDR)
        for r in rows:
            w.writerow(r)
    return p


def _row(ticket, close_time, volume, pid, side="BUY", profit="1.0"):
    return [ticket, close_time, side, volume, "4500", profit, "Hermes",
            "2026-09-09T18:45:02+00:00", pid, "-0.3", "0", "0"]


class CloseParsing(unittest.TestCase):
    def test_epoch_digits_parse_as_utc(self):
        dt = G._close_dt("1788989529")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.date().isoformat(), "2026-09-09")

    def test_iso_string_parses_and_naive_is_utc(self):
        self.assertEqual(G._close_dt("2026-09-09T12:00:00").utcoffset().total_seconds(), 0)
        self.assertIsNotNone(G._close_dt("2026-09-09T12:00:00+00:00"))

    def test_garbage_is_excluded_not_guessed(self):
        for bad in ("", None, "not-a-date", "2026-13-99"):
            self.assertIsNone(G._close_dt(bad), bad)

    def test_b183_the_old_string_compare_cannot_work_on_epoch(self):
        # 'close_time' is epoch-as-string: '1788989529' < '2026-09-09' ('1'<'2'),
        # so a lexicographic >= ship-date matches NOTHING. This is the b116
        # misread the parked wording fell into even after the column name fix.
        self.assertLess("1788989529", SHIP)
        self.assertEqual(G._close_dt("1788989529").date().isoformat(), "2026-09-09")


class GateCounting(unittest.TestCase):
    def test_counts_positions_not_rows(self):
        # one position closed by TWO legs (TP1 half + runner) must count ONCE:
        # b183 asks for ~30 TRADES of the new policy, not 30 deals.
        with tempfile.TemporaryDirectory() as d:
            p = _write([_row(11, TS_POST, "0.10", "777"),
                        _row(12, TS_POST + 60, "0.05", "777")], d)
            out = G.positions_since_ship(p, SHIP)
        self.assertEqual(out["rows_total"], 2)
        self.assertEqual(out["positions_post_ship"], 1)
        self.assertEqual(out["post_lot_mix"], {"0.10": 1})

    def test_pre_ship_positions_are_not_counted(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write([_row(1, TS_PRE, "0.05", "1"),
                        _row(2, TS_POST, "0.05", "2")], d)
            out = G.positions_since_ship(p, SHIP)
        self.assertEqual(out["positions_total"], 2)
        self.assertEqual(out["positions_post_ship"], 1)

    def test_legacy_rows_without_position_id_stay_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write([_row(21, TS_POST, "0.05", ""),
                        _row(22, TS_POST, "0.05", "")], d)
            out = G.positions_since_ship(p, SHIP)
        self.assertEqual(out["positions_post_ship"], 2)

    def test_unparseable_close_time_is_counted_and_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write([_row(31, "garbage", "0.05", "3"),
                        _row(32, TS_POST, "0.05", "4")], d)
            out = G.positions_since_ship(p, SHIP)
        self.assertEqual(out["rows_unparseable_close_time"], 1)
        self.assertEqual(out["positions_post_ship"], 1)

    def test_001_lane_is_reported_separately(self):
        # option (c) can only be priced if 0.01-lot positions exist post-ship
        with tempfile.TemporaryDirectory() as d:
            p = _write([_row(41, TS_POST, "0.01", "5"),
                        _row(42, TS_POST, "0.05", "6")], d)
            out = G.positions_since_ship(p, SHIP)
        self.assertEqual(out["post_001_lot_positions"], 1)
        self.assertEqual(out["post_lot_mix"], {"0.01": 1, "0.05": 1})

    def test_b183_reopen_flag_fires_only_at_30(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write([_row(100 + i, TS_POST, "0.05", f"p{i}")
                        for i in range(G.REOPEN_MIN_TRADES)], d)
            out = G.positions_since_ship(p, SHIP)
        self.assertEqual(out["positions_post_ship"], G.REOPEN_MIN_TRADES)
        self.assertTrue(out["reopen_met"])

    def test_dead_predicates_would_match_nothing_on_the_real_journal(self):
        # Pins the FINDING (not just the helper): the parked wording's two
        # candidate forms both return 0 on the LIVE journal, whatever it holds.
        out = G.positions_since_ship(G.journal_path(), SHIP)
        self.assertEqual(out["dead_predicate_rows_matched_at_column"], 0)
        self.assertEqual(out["dead_predicate_rows_matched_close_time_string"], 0)
        # and the honest count is a small n — the item must stay parked.
        self.assertLess(out["positions_post_ship"], G.REOPEN_MIN_TRADES)
        self.assertFalse(out["reopen_met"])


class NoSideEffects(unittest.TestCase):
    def test_module_reads_only_and_ships_no_constants_tweaked(self):
        self.assertEqual(G.POLICY_SHIP_UTC_DATE, "2026-09-09")
        self.assertEqual(G.REOPEN_MIN_TRADES, 30)
        src = (ROOT / "scripts" / "b183_reopen_gate.py").read_text()
        for banned in ("send_order", "open_position", "close_position",
                       "modify_position", "send_pending", "cancel_order",
                       "BridgeClient"):
            self.assertNotIn(banned, src, banned)

    def test_does_not_mutate_the_journal(self):
        p = G.journal_path()
        before = p.read_bytes()
        G.positions_since_ship(p, SHIP)
        self.assertEqual(p.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
