"""b154 — the dashboard's money columns must be NET and PER POSITION.

Filed by b152 (2026-09-08): notifier/dashboards.py::_stats summed the raw
`profit` column per journal ROW — neither the fees (b151/b152 net) nor the
position grouping. On the live file that showed +17.89$ while the broker's
all-in on the SAME positions was +5.65$: the operator's phone carried a
rosier book than the auto-trader trades on. Same disease as b151 (a display
layer hand-copying the funnel instead of calling it), relocated.

The fix routes every aggregate through engines.learning.group_positions —
the ONE net formula pinned by b152 — keeps the row list only for the recency
display (now at per-leg net too), and DISCLOSES the basis when the import
degrades to gross (b49: a fail-safe must not look like a correct number).
"""
import os
import sys
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from notifier import dashboards as d  # noqa: E402
from engines import learning  # noqa: E402

DAY = 86400


def _leg(ticket, profit, position_id, commission=0.0, swap=0.0,
         entry_commission=0.0, volume="0.05", side="BUY", close_time=None):
    """One journal ROW (closing deal), full b152 header shape."""
    ct = close_time if close_time is not None else 1788000000
    return {
        'ticket': str(ticket), 'close_time': str(ct), 'side': side,
        'volume': volume, 'price': '4400', 'profit': str(profit),
        'comment': '', 'journaled_at': '2026-08-29T00:00:00+00:00',
        'position_id': str(position_id), 'commission': str(commission),
        'swap': str(swap), 'entry_commission': str(entry_commission),
    }


# One position closed in TWO legs with fees on both halves (b152 shape),
# plus a single-leg loser. Broker all-in:
#   pos 77: +10.0 +5.0 -0.2 -0.1 +0 -0.3 -0.2 = +14.2 net
#   pos 88: -8.0 -0.15 +0 -0.15              = -8.3 net
FIXTURE = [
    _leg(501, 10.0, 77, commission=-0.2, entry_commission=-0.3),
    _leg(502, 5.0, 77, commission=-0.1, entry_commission=-0.2),
    _leg(503, -8.0, 88, commission=-0.15, entry_commission=-0.15,
         side='SELL'),
]
GROSS_ROWS = 7.0          # old dashboard: 10+5-8 per row, fees invisible
NET_POSITIONS = 14.2 - 8.3  # what the broker and the loop agree on


@contextmanager
def journal(rows):
    with patch.object(d, '_journal_rows', lambda: list(rows)):
        yield


class TestStatsAreNetPerPosition(unittest.TestCase):
    def test_b154_stats_net_equals_the_one_formula(self):
        """_stats()['net'] must equal sum(group_positions(...))['net'] on
        the SAME rows — not a hand-copy of the arithmetic (b151's disease)."""
        expected = sum(g['net'] for g in
                       learning.group_positions(FIXTURE).values())
        with journal(FIXTURE):
            st = d._stats()
        self.assertAlmostEqual(st['net'], expected, places=6)
        self.assertAlmostEqual(st['net'], NET_POSITIONS, places=4)

    def test_b154_trade_count_is_positions_not_legs(self):
        with journal(FIXTURE):
            st = d._stats()
        self.assertEqual(st['n'], 2)          # 3 legs, 2 positions
        self.assertEqual(st['wins'], 1)
        self.assertEqual(st['losses'], 1)

    def test_b154_the_fix_is_not_vacuous_gross_differs_from_net(self):
        """If the fixture ever stops separating gross-per-row from
        net-per-position, the other assertions prove nothing."""
        gross = sum(float(r['profit']) for r in FIXTURE)
        self.assertNotAlmostEqual(gross, NET_POSITIONS, places=2)
        with journal(FIXTURE):
            st = d._stats()
        self.assertAlmostEqual(gross, GROSS_ROWS, places=4)  # old reading
        self.assertLess(st['net'], gross)                    # fees bite

    def test_b154_stats_calls_group_positions_at_runtime(self):
        """Behavioural pin: the funnel must ACTUALLY route through
        engines.learning.group_positions (a re-introduced local copy of the
        arithmetic would pass the value tests above but fail this spy)."""
        real = learning.group_positions
        calls = []

        def spy(rows):
            calls.append(len(rows))
            return real(rows)
        with journal(FIXTURE), patch.object(learning, 'group_positions', spy):
            st = d._stats()
        self.assertTrue(calls, 'dashboards bypassed the ONE net formula')
        self.assertEqual(st['basis'], 'position_net')

    def test_b154_best_worst_pf_read_on_net_positions(self):
        with journal(FIXTURE):
            st = d._stats()
        self.assertAlmostEqual(st['best'], 14.2, places=4)
        self.assertAlmostEqual(st['worst'], -8.3, places=4)
        self.assertAlmostEqual(st['pf'], 14.2 / 8.3, places=4)
        self.assertAlmostEqual(st['exp'], NET_POSITIONS / 2, places=4)

    def test_b154_by_side_is_net_per_position_too(self):
        with journal(FIXTURE):
            st = d._stats()
        self.assertEqual(st['buy_n'], 1)
        self.assertAlmostEqual(st['buy_pnl'], 14.2, places=4)
        self.assertEqual(st['sell_n'], 1)
        self.assertAlmostEqual(st['sell_pnl'], -8.3, places=4)


class TestTodayAndDaysSlices(unittest.TestCase):
    def test_b154_today_slice_uses_close_time_and_net(self):
        """A position closed TODAY (UTC) counts once, at its NET; the same
        position's second leg does not double the count."""
        now = datetime.now(timezone.utc)
        noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
        secs = noon.timestamp()          # same UTC date whatever the clock
        rows = [_leg(601, 10.0, 99, commission=-1.0, close_time=secs),
                _leg(602, 5.0, 99, commission=-1.0, close_time=secs + 60),
                _leg(603, 7.0, 98, commission=-1.0, close_time=secs - 3 * DAY)]
        with journal(rows):
            st = d._stats()
        self.assertEqual(st['today']['n'], 1)          # ONE position
        self.assertAlmostEqual(st['today']['pnl'], 13.0, places=4)
        days = dict(st['days'])
        self.assertAlmostEqual(days[now.strftime('%Y-%m-%d')], 13.0, places=4)

    def test_b154_a_leg_journaled_today_but_closed_yesterday_is_not_today(
            self):
        """The old slice keyed on journaled_at; the ledger's event is the
        close. A late journaling of yesterday's close must not inflate today."""
        now = datetime.now(timezone.utc)
        late = dict(_leg(701, 20.0, 97, close_time=now.timestamp() - 2 * DAY))
        late['journaled_at'] = now.isoformat()
        with journal([late]):
            st = d._stats()
        self.assertEqual(st['today']['n'], 0)
        self.assertAlmostEqual(st['today']['pnl'], 0.0, places=6)


class TestRecencyDisplay(unittest.TestCase):
    def test_b154_recent_list_shows_leg_net_not_gross(self):
        rows = [_leg(801, 10.0, 77, commission=-0.2, entry_commission=-0.3,
                     close_time=1788000000)]
        with journal(rows):
            st = d._stats()
        self.assertEqual(len(st['recent']), 1)
        self.assertAlmostEqual(st['recent'][0][3], 9.5, places=4)

    def test_b154_a_legacy_row_without_fee_columns_stays_readable(self):
        """b142 shape: a pre-migration row lacks commission/swap/
        entry_commission keys entirely — it must read as its gross, not
        crash the panel."""
        row = {k: v for k, v in FIXTURE[0].items()
               if k not in ('commission', 'swap', 'entry_commission')}
        with journal([row]):
            st = d._stats()
        self.assertAlmostEqual(st['net'], 10.0, places=4)


class TestDegradedBasisIsDisclosed(unittest.TestCase):
    def _rows(self):
        return FIXTURE

    def test_b154_import_failure_falls_back_to_gross_and_says_so(self):
        with journal(self._rows()), \
                patch.object(d, '_group_positions_fn', lambda: None):
            st = d._stats()
        self.assertEqual(st['basis'], 'gross_fallback')
        # honest per-leg net (fees still folded), rows not merged
        self.assertAlmostEqual(st['net'], 7.0 - 1.1, places=4)
        self.assertEqual(st['n'], 3)
        lines = '\n'.join(d._stats_panel_lines(st))
        self.assertIn('⚠️', lines)

    def test_b154_the_good_path_carries_no_warning(self):
        with journal(self._rows()):
            st = d._stats()
        lines = '\n'.join(d._stats_panel_lines(st))
        self.assertNotIn('⚠️', lines)
        # the panel shows the NET book (+5.90$), not the old gross (+7.00$)
        self.assertIn('+5.90', lines)
        self.assertNotIn('+7.00', lines)


class TestPanelRenderersStayAlive(unittest.TestCase):
    """Every _stats() consumer must render on the new shape — an operator
    panel that crashes because the dict gained 'basis' is worse than the
    gross lie it replaced."""

    def test_b154_trade_panels_render_on_a_temp_journal(self):
        tmp = Path(os.environ.get('TMPDIR', '/tmp'))
        with journal(FIXTURE):
            for fn in (d._stats_panel_lines,):
                fn(d._stats())
            st = d._stats()
        self.assertTrue(st['curve'])
        self.assertEqual(st['streak'][1], 'loss')  # last position lost


if __name__ == '__main__':
    unittest.main()
