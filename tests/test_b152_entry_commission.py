"""b152 — the journal must carry the broker's IN-deal commission.

Filed by the b150 audit (2026-09-08): the broker charges commission on the IN
deal as well as the OUT deal (-6.12$ of -12.24$ over the live 30d window lived
ONLY on IN deals), but engines.learning.journal() writes one row per CLOSING
deal and records only that deal's commission — so every net-P&L consumer
(the b151 learning loop, weekly_report, the b143 reader) was blind to exactly
half the commission cost. Measured before the fix: journal per-position net
+11.77$ vs broker all-in net +5.65$ on the identical 29 positions.

The fix adds `entry_commission` as a 12th column (APPENDED LAST — b144's
rule: mid-tuple insertion would misalign every field after it while drifted
writers append short rows), prorates each position's IN-deal fee across its
closing legs by volume, and folds it into the ONE net formula
(group_positions), which analyze() now calls instead of holding a hand-copy
of the arithmetic (b151's duplication was itself a defect).

Direction of the fix: commission is always <= 0, so folding the entry fee in
can only make the loop see WORSE — tightening-neutral, never a loosening.
"""
import contextlib
import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines import learning  # noqa: E402

HEADER = learning.JOURNAL_FIELDS


def _row(ticket, profit, commission=0.0, swap=0.0, position_id=None,
         volume="0.05", entry_commission=None):
    return {
        "ticket": str(ticket), "close_time": "1788000000",
        "side": "BUY", "volume": volume, "price": "4400",
        "profit": str(profit), "comment": "",
        "journaled_at": "2026-09-08T00:00:00+00:00",
        "position_id": str(position_id if position_id is not None else ticket),
        "commission": str(commission), "swap": str(swap),
        **({"entry_commission": str(entry_commission)}
           if entry_commission is not None else {}),
    }


@contextlib.contextmanager
def journal_with(rows):
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


class TestSchemaShape(unittest.TestCase):
    def test_b152_entry_commission_is_the_last_field(self):
        """b144's rule: appended LAST so pre-b152 short rows stay readable."""
        self.assertEqual(HEADER[-1], "entry_commission")
        self.assertEqual(HEADER[:-1],
                         ['ticket', 'close_time', 'side', 'volume', 'price',
                          'profit', 'comment', 'journaled_at', 'position_id',
                          'commission', 'swap'])

    def test_b152_a_pre_fix_row_without_the_column_reads_as_zero(self):
        rows = [_row(1, 10.0, commission=-0.5, position_id=7)]  # no entry fee
        with journal_with(rows):
            o = learning.analyze()["overall"]
        self.assertAlmostEqual(o["net_pnl"], 9.5, places=4)


class TestFeeProration(unittest.TestCase):
    def _deals(self):
        # one position, IN once at 0.10 lot (-0.30 fee), closed in two legs
        return [
            {"ticket": "500", "order": "900", "position_id": "77",
             "entry": "0", "type": "0", "volume": "0.10",
             "commission": "-0.30", "profit": "0.0", "swap": "0.0"},
            {"ticket": "501", "order": "900", "position_id": "77",
             "entry": "1", "type": "1", "volume": "0.06",
             "commission": "-0.18", "profit": "5.0", "swap": "0.0"},
            {"ticket": "502", "order": "900", "position_id": "77",
             "entry": "1", "type": "1", "volume": "0.04",
             "commission": "-0.12", "profit": "-2.0", "swap": "0.0"},
        ]

    def test_b152_totals_come_from_IN_deals_only(self):
        fees = learning._entry_fee_totals(self._deals())
        self.assertAlmostEqual(fees["77"]["fee"], -0.30, places=4)
        self.assertAlmostEqual(fees["77"]["vol"], 0.10, places=4)

    def test_b152_shares_prorate_by_volume_and_sum_to_the_fee(self):
        fees = learning._entry_fee_totals(self._deals())
        deals = self._deals()
        shares = [float(learning._entry_fee_share(fees, d))
                  for d in deals if d["entry"] == "1"]
        self.assertAlmostEqual(shares[0], -0.18, places=4)
        self.assertAlmostEqual(shares[1], -0.12, places=4)
        self.assertAlmostEqual(sum(shares), fees["77"]["fee"], places=4)

    def test_b152_unresolvable_position_reports_empty_not_a_guess(self):
        fees = learning._entry_fee_totals(self._deals())
        self.assertEqual(learning._entry_fee_share(fees, {"position_id": ""}), "")
        self.assertEqual(learning._entry_fee_share({}, {"position_id": "77"}), "")


class TestJournalWritePath(unittest.TestCase):
    class _Bridge:
        def __init__(self, deals):
            self._deals = deals

        def get_history_deals(self, symbol, days):
            return {"ok": True, "data": self._deals}

    def _deals(self):
        return [
            {"ticket": "500", "order": "900", "position_id": "77",
             "entry": "0", "type": "0", "volume": "0.10",
             "commission": "-0.30", "profit": "0.0", "swap": "0.0",
             "time_done": "1788000000"},
            {"ticket": "501", "order": "900", "position_id": "77",
             "entry": "1", "type": "1", "volume": "0.10",
             "commission": "-0.30", "profit": "10.0", "swap": "0.0",
             "time_done": "1788000100"},
        ]

    def test_b152_journal_writes_entry_commission_on_closing_rows(self):
        tmp = tempfile.mkdtemp()
        old = os.environ.get("HERMES_DATA_ROOT")
        os.environ["HERMES_DATA_ROOT"] = tmp
        try:
            added = learning.journal(self._Bridge(self._deals()))
            self.assertEqual(added, 1)
            rows = list(csv.DictReader(
                (Path(tmp) / "data" / "xau_plan" / "trade_journal.csv")
                .open(newline="", encoding="utf-8")))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["entry_commission"], "-0.3")
            # net = 10.0 profit + (-0.30 out comm) + 0 swap + (-0.30 in fee)
            g = learning.group_positions(rows)
            self.assertAlmostEqual(g["77"]["net"], 9.4, places=4)
        finally:
            if old is None:
                os.environ.pop("HERMES_DATA_ROOT", None)
            else:
                os.environ["HERMES_DATA_ROOT"] = old


class TestMigration(unittest.TestCase):
    def test_b152_migration_backfills_entry_fee_losslessly(self):
        tmp = Path(tempfile.mkdtemp())
        j = tmp / "trade_journal.csv"
        old_header = HEADER[:-1]  # the pre-b152 11-column file
        with j.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=old_header)
            w.writeheader()
            w.writerow({k: r for k, r in zip(
                old_header,
                ["501", "1788000100", "BUY", "0.06", "4400", "5.0", "",
                 "", "77", "-0.18", "0.0"])})
            w.writerow({k: r for k, r in zip(
                old_header,
                ["502", "1788000200", "BUY", "0.04", "4400", "-2.0", "",
                 "", "77", "-0.12", "0.0"])})
        deals = [
            {"ticket": "500", "position_id": "77", "entry": "0",
             "volume": "0.10", "commission": "-0.30"},
            {"ticket": "501", "position_id": "77", "entry": "1",
             "volume": "0.06", "commission": "-0.18"},
            {"ticket": "502", "position_id": "77", "entry": "1",
             "volume": "0.04", "commission": "-0.12"},
        ]
        by_ticket = {str(d["ticket"]): d for d in deals}
        learning._migrate_journal(j, by_ticket,
                                  learning._entry_fee_totals(deals))
        rows = list(csv.DictReader(j.open(newline="", encoding="utf-8")))
        self.assertEqual(list(rows[0].keys()), HEADER)  # header widened
        self.assertEqual(len(rows), 2)                  # rows preserved
        g = learning.group_positions(rows)
        # broker all-in for position 77: 5.0 - 2.0 + (-0.18 -0.12) + (-0.30)
        self.assertAlmostEqual(g["77"]["net"], 2.4, places=4)


class TestDirectionStaysTightening(unittest.TestCase):
    def test_b152_folding_entry_fees_never_raises_net(self):
        rows_no_fee = [_row(i, 5.0, commission=-1.0, position_id=100 + i)
                       for i in range(1, 21)]
        rows_fee = [_row(i, 5.0, commission=-1.0, position_id=100 + i,
                         entry_commission=-1.0) for i in range(1, 21)]
        with journal_with(rows_no_fee):
            a = learning.analyze()["overall"]
        with journal_with(rows_fee):
            b = learning.analyze()["overall"]
        self.assertLess(b["net_pnl"], a["net_pnl"])
        self.assertLessEqual(b["win_rate"], a["win_rate"])

    def test_b152_a_gross_winner_eaten_by_entry_fee_becomes_a_loss(self):
        rows = [_row(1, 0.40, commission=-0.06, entry_commission=-0.36,
                     position_id=9)]
        with journal_with(rows):
            o = learning.analyze()["overall"]
        self.assertEqual(o["win_rate"], 0.0)


class TestOneNetFormula(unittest.TestCase):
    def test_b152_analyze_stats_delegate_to_group_positions(self):
        """Anti-duplication pin (b151's own root-cause class): the per-position
        net arithmetic must not be re-hand-copied inside analyze()."""
        src = Path(learning.__file__).read_text(encoding="utf-8")
        stats_body = src.split("def stats(sub", 1)[1].split(
            "out['overall'] = stats(rows)", 1)[0]
        self.assertIn("group_positions", stats_body)
        self.assertNotIn("_num('commission')", stats_body)


if __name__ == "__main__":
    unittest.main()
