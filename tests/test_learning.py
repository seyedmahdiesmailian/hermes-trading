"""Tests for engines/learning.py - session x regime journal breakdown."""
import csv
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, '/home/ai/hermes-trading')

from engines import learning

JH = ['ticket', 'close_time', 'side', 'volume', 'price', 'profit',
      'comment', 'journaled_at']
EH = ['at', 'plan_id', 'side', 'lot', 'entry', 'sl', 'tp', 'grade',
      'risk_usd', 'dry_run', 'result_ok']


def mk(h, m=0):
    return datetime(2026, 8, 29, h, m, tzinfo=timezone.utc)


def ep(h, m=0):
    return str(int(mk(h, m).timestamp()))


def jrow(ticket, close_time, side='BUY', profit='10'):
    return {'ticket': ticket, 'close_time': close_time, 'side': side,
            'volume': '0.01', 'price': '4400', 'profit': profit,
            'comment': '', 'journaled_at': ''}


def erow(at, plan_id, dry_run='False', result_ok='True'):
    return {'at': at, 'plan_id': plan_id, 'side': 'BUY', 'lot': '0.01',
            'entry': '4400', 'sl': '4390', 'tp': '4420', 'grade': 'A',
            'risk_usd': '10', 'dry_run': dry_run, 'result_ok': result_ok}


def write_csv(path, header, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


class SessionOfTest(unittest.TestCase):
    def test_mirrors_runtime_bounds(self):
        import hermes_runtime
        for h in range(24):
            self.assertEqual(learning.session_of(mk(h)),
                             hermes_runtime._detect_session(mk(h)),
                             'hour %d mismatch' % h)

    def test_buckets(self):
        self.assertEqual(learning.session_of(mk(0)), 'asia')
        self.assertEqual(learning.session_of(mk(6)), 'asia')
        self.assertEqual(learning.session_of(mk(7)), 'london')
        self.assertEqual(learning.session_of(mk(12)), 'london')
        self.assertEqual(learning.session_of(mk(13)), 'newyork')
        self.assertEqual(learning.session_of(mk(23)), 'newyork')


class AnalyzeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='learning_test_')
        self.plan_dir = Path(self.tmp)
        self.journal = self.plan_dir / 'trade_journal.csv'
        self.exec_log = self.plan_dir / 'execution_log.csv'
        plan = {'plan_id': 'xau-test01',
                'quality': {'regime': 'breakout_continuation'}}
        (self.plan_dir / '20260830_010000_xau-test01.json').write_text(
            json.dumps(plan), encoding='utf-8')

    def patched(self):
        return patch.multiple(
            learning, PLAN_DIR=self.plan_dir, JOURNAL_CSV=self.journal,
            LEARNING_JSON=self.plan_dir / 'learning_state.json')

    def test_analyze_empty_journal(self):
        with self.patched():
            out = learning.analyze()
        self.assertEqual(out['sample'], 0)
        self.assertEqual(out['by_session'], {})
        self.assertEqual(out['by_session_regime'], {})

    def test_session_and_regime_buckets(self):
        write_csv(self.journal, JH, [
            jrow('111', ep(9, 30), 'BUY', '10'),
            jrow('222', ep(9, 40), 'BUY', '-4'),
            jrow('333', ep(22, 0), 'SELL', '3'),
            jrow('444', 'not-a-time', 'BUY', '1'),
        ])
        write_csv(self.exec_log, EH, [
            erow('2026-08-29T08:00:00+00:00', 'xau-test01'),
            erow('2026-08-29T21:30:00+00:00', 'xau-gone'),
        ])
        with self.patched():
            out = learning.analyze()
        self.assertEqual(out['sample'], 4)
        self.assertEqual(out['by_session']['london']['trades'], 2)
        self.assertEqual(out['by_session']['newyork']['trades'], 1)
        self.assertEqual(out['by_session']['unknown']['trades'], 1)
        london = out['by_session_regime']['london']
        self.assertEqual(london['trend']['trades'], 2)
        self.assertEqual(london['trend']['net_pnl'], 6.0)
        self.assertNotIn('unknown', london)
        newyork = out['by_session_regime']['newyork']
        self.assertEqual(newyork['unknown']['trades'], 1)
        self.assertEqual(out['by_session_regime']['unknown']['unknown']['trades'], 1)
        self.assertEqual(out['overall']['trades'], 4)
        self.assertEqual(out['by_side']['BUY']['trades'], 3)

    def test_dry_run_and_failed_execs_ignored(self):
        write_csv(self.journal, JH, [jrow('777', ep(9, 30), 'BUY', '5')])
        write_csv(self.exec_log, EH, [
            erow('2026-08-29T08:00:00+00:00', 'xau-test01', dry_run='True'),
            erow('2026-08-29T08:05:00+00:00', 'xau-test01', result_ok='False'),
            erow('2026-08-24T09:00:00+00:00', 'xau-test01'),
        ])
        with self.patched():
            out = learning.analyze()
        self.assertEqual(
            out['by_session_regime']['london']['unknown']['trades'], 1)

    def test_most_recent_exec_wins(self):
        write_csv(self.journal, JH, [jrow('888', ep(9, 30), 'BUY', '5')])
        write_csv(self.exec_log, EH, [
            erow('2026-08-29T08:00:00+00:00', 'xau-gone'),
            erow('2026-08-29T08:05:00+00:00', 'xau-test01'),
        ])
        with self.patched():
            out = learning.analyze()
        self.assertEqual(
            out['by_session_regime']['london']['trend']['trades'], 1)

    def test_corrupt_plan_file_does_not_crash(self):
        (self.plan_dir / '20260830_010000_xau-bad.json').write_text(
            '{not json', encoding='utf-8')
        write_csv(self.journal, JH, [jrow('555', ep(9, 30), 'BUY', '5')])
        write_csv(self.exec_log, EH,
                  [erow('2026-08-29T08:00:00+00:00', 'xau-bad')])
        with self.patched():
            out = learning.analyze()
        london = out['by_session_regime']['london']
        self.assertEqual(london['unknown']['trades'], 1)
        self.assertNotIn('trend', london)

    def test_ambiguous_plan_id_skipped(self):
        for stamp in ('20260829_010000', '20260830_010000'):
            (self.plan_dir / (stamp + '_xau-dup.json')).write_text(
                json.dumps({'quality': {'regime': 'range'}}), encoding='utf-8')
        write_csv(self.journal, JH, [jrow('777', ep(9, 30), 'SELL', '2')])
        write_csv(self.exec_log, EH,
                  [erow('2026-08-29T08:00:00+00:00', 'xau-dup')])
        with self.patched():
            out = learning.analyze()
        london = out['by_session_regime']['london']
        self.assertEqual(london['unknown']['trades'], 1)
        self.assertNotIn('range', london)

    def test_iso_close_time_and_naive(self):
        write_csv(self.journal, JH, [
            jrow('888', '2026-08-29T09:30:00+00:00', 'BUY', '7'),
            jrow('889', '2026-08-29T05:30:00', 'BUY', '-2'),
        ])
        with self.patched():
            out = learning.analyze()
        self.assertEqual(out['by_session']['london']['trades'], 1)
        self.assertEqual(out['by_session']['asia']['trades'], 1)

    def test_missing_exec_log(self):
        write_csv(self.journal, JH, [jrow('111', ep(9, 30), 'BUY', '10')])
        with self.patched():
            out = learning.analyze()
        self.assertEqual(
            out['by_session_regime']['london']['unknown']['trades'], 1)


class AdjustmentsRegressionTest(unittest.TestCase):
    def test_insufficient_sample_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_dir = Path(tmp)
            journal = plan_dir / 'trade_journal.csv'
            rows = [jrow(str(9000 + i), '2026-08-29T09:00:00+00:00',
                         'BUY' if i % 2 else 'SELL', str(-5 - i))
                    for i in range(10)]
            write_csv(journal, JH, rows)
            with patch.multiple(learning, PLAN_DIR=plan_dir,
                                JOURNAL_CSV=journal,
                                LEARNING_JSON=plan_dir / 'learning_state.json'):
                out = learning.adjustments()
            self.assertEqual(out.get('reason'), 'insufficient_sample_10')
            self.assertEqual(out['changes'], {})


if __name__ == '__main__':
    unittest.main()
