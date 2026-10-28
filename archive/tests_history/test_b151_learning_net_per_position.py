"""b151 — the learning loop must judge itself on NET P&L per POSITION.

Root cause found 2026-09-08: `analyze().stats()` averaged the raw `profit`
column over journal ROWS. The journal writes one row per closing deal (b75), so
a position closed in three parts contributed three rows, and `profit` excludes
commission/swap. On live data the loop read win_rate 0.737 / avg +0.07$ while
the same rows grouped per-position-net read 0.679 / -0.11$ — the loop believed a
losing system was profitable, and its only defensive trigger
(`wr < 0.40 and avg < 0`) could never fire.

These tests pin the corrected view and, critically, the DIRECTION of the fix:
the change may only ever make the loop see WORSE, never better, because a
tighten-only loop that suddenly sees a higher win rate would be a loosening.
"""
import contextlib
import csv
import importlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines import learning  # noqa: E402


HEADER = learning.JOURNAL_FIELDS


def _row(ticket, profit, commission=0.0, swap=0.0, position_id=None, side="BUY"):
    return {
        "ticket": str(ticket), "close_time": "1788000000", "side": side,
        "volume": "0.05", "price": "4400", "profit": str(profit),
        "comment": "", "journaled_at": "2026-09-08T00:00:00+00:00",
        "position_id": str(position_id if position_id is not None else ticket),
        "commission": str(commission), "swap": str(swap),
    }


@contextlib.contextmanager
def journal_with(rows):
    """Point learning._load_journal at a temp CSV for the duration of a test."""
    tmp = Path(tempfile.mkdtemp()) / "trade_journal.csv"
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)
    real = learning._load_journal

    def _read():
        with tmp.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    learning._load_journal = _read
    try:
        yield
    finally:
        learning._load_journal = real


class NetPerPosition(unittest.TestCase):
    def test_partial_closes_count_as_one_trade(self):
        """Three legs of one position = one trade, not three."""
        rows = [_row(1, 30, position_id=77), _row(2, 20, position_id=77),
                _row(3, 10, position_id=77)]
        with journal_with(rows):
            o = learning.analyze()["overall"]
        self.assertEqual(o["trades"], 1)
        self.assertAlmostEqual(o["net_pnl"], 60.0, places=2)

    def test_commission_and_swap_are_included(self):
        rows = [_row(1, 5.0, commission=-3.0, swap=-1.0, position_id=9)]
        with journal_with(rows):
            o = learning.analyze()["overall"]
        self.assertAlmostEqual(o["net_pnl"], 1.0, places=2)

    def test_gross_winner_that_is_net_loser_counts_as_loss(self):
        """The exact distortion: +0.05 gross, -0.06 commission => a LOSING trade."""
        rows = [_row(1, 0.05, commission=-0.06, position_id=5)]
        with journal_with(rows):
            o = learning.analyze()["overall"]
        self.assertEqual(o["win_rate"], 0.0)
        self.assertLess(o["avg_pnl"], 0)

    def test_legacy_rows_without_position_id_stay_one_row_each(self):
        rows = [_row(11, 10, position_id=""), _row(12, -5, position_id="")]
        with journal_with(rows):
            o = learning.analyze()["overall"]
        self.assertEqual(o["trades"], 2)


class DirectionOfTheFix(unittest.TestCase):
    def test_net_view_is_never_more_favourable_than_leg_view(self):
        """A tighten-only loop must not be handed a rosier picture by a
        reporting change. Commission is always <= 0, so per-position-net
        win_rate <= per-leg-gross win_rate on any book where every leg is a
        separate position."""
        rows = [_row(i, 0.05, commission=-0.06, position_id=i) for i in range(1, 9)]
        with journal_with(rows):
            o = learning.analyze()["overall"]
        self.assertEqual(o["win_rate"], 0.0)          # net: all losers
        self.assertLess(o["win_rate"], 0.737)         # leg/gross would have said 1.0

    def test_tighten_trigger_can_now_fire(self):
        """A book of net losers must actually propose tightening — the whole
        point of the fix. Before b151 the same shape (gross-positive legs)
        returned an empty change set."""
        rows = [_row(i, 0.05, commission=-0.06, position_id=i) for i in range(1, 21)]
        with journal_with(rows):
            d = learning.adjustments()
        self.assertGreaterEqual(d["sample"], learning.MIN_TRADES_SAMPLE)
        self.assertLess(d["win_rate"], 0.40)
        self.assertTrue(d["changes"], "loop stayed mute on a losing book")
        # and every proposed change must be a TIGHTENING
        self.assertGreaterEqual(d["changes"].get("min_rr", 1.5), 1.5)
        self.assertLessEqual(d["changes"].get("risk_mult", 1.0), 1.0)

    def test_profitable_book_still_proposes_nothing(self):
        rows = [_row(i, 20, commission=-1, position_id=i) for i in range(1, 21)]
        with journal_with(rows):
            d = learning.adjustments()
        self.assertEqual(d["changes"], {})


class LiveShape(unittest.TestCase):
    def test_real_journal_is_measured_per_position(self):
        """Sanity on the shipped file: trades must equal distinct positions,
        never the raw row count (the b75 leg/row distinction)."""
        real = learning._load_journal()
        if not real:
            self.skipTest("no journal on this host")
        with journal_with(real):
            o = learning.analyze()["overall"]
        self.assertLessEqual(o["trades"], learning.position_count(real))


if __name__ == "__main__":
    unittest.main()
