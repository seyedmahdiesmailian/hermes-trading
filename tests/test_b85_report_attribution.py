"""b85 — the autopilot report must attribute commits by TIME, not by author.

The 13:00 report on 2026-09-05 was a small masterpiece of lying. A run hit
the 55-minute ceiling (rc=124) having committed nothing. The report diffed
``prev_head..HEAD``, found ONE commit — a manual fix made at 11:53, between
two runs — and printed:

    ⏱️ این اجرا به سقف زمانی خورد ... اما کارش کامیت شده بود
    🛠 تغییرات این اجرا:  · autopilot: rc=143 ...
    📌 1 تغییر کد کامیت و روی گیت‌هاب ثبت شد

All three lines were false. The operator was told a lost step was safe.

Pinned here:
  * a commit made BEFORE the run started is never "this run's" work;
  * a commit made AFTER the run started is;
  * with no run-start marker (log missing/rotated) we fall back to the old
    behaviour rather than silently dropping the operator's visibility;
  * the marker parser reads the LAST start, in UTC, and ignores 'run end';
  * end-to-end: the exact 13:00 shape (rc=124, one pre-run commit) must
    render the honest line — no "کامیت شده بود", no 🛠/📌, and the commit
    shown under the "بیرون از این اجرا" label.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engines.autopilot_report_lib import (  # noqa: E402
    classify_commits, run_start_from_log)


def epoch(iso: str) -> int:
    return int(datetime.strptime(iso, '%Y-%m-%dT%H:%M:%S')
               .replace(tzinfo=timezone.utc).timestamp())


MARK = '2026-09-05T09:35:01Z === autopilot run start ==='
STARTED = epoch('2026-09-05T09:35:01')


class RunStartMarker(unittest.TestCase):
    def test_reads_last_start_in_utc(self):
        text = ('2026-09-05T08:35:01Z === autopilot run start ===\n'
                'noise\n' + MARK + '\n'
                '2026-09-05T10:22:35Z === autopilot run end rc=0 ===\n')
        self.assertEqual(run_start_from_log(text), STARTED)

    def test_no_marker_returns_none(self):
        self.assertIsNone(run_start_from_log('nothing here at all'))
        self.assertIsNone(run_start_from_log(''))
        self.assertIsNone(run_start_from_log(None))

    def test_end_marker_alone_is_not_a_start(self):
        self.assertIsNone(run_start_from_log(
            '2026-09-05T10:22:35Z === autopilot run end rc=0 ==='))

    def test_malformed_timestamp_is_reported_not_swallowed(self):
        seen = []
        text = '2026-99-99T99:99:99Z === autopilot run start ==='
        # regex needs a well-shaped date, so force the parse failure
        self.assertIsNone(run_start_from_log(text, on_error=seen.append))


class Attribution(unittest.TestCase):
    def line(self, iso, subj):
        return f'{epoch(iso)}\x1f{subj}'

    def test_commit_before_run_start_is_not_the_runs(self):
        raw = self.line('2026-09-05T11:53:52', 'manual fix')  # local TEH-ish
        raw = self.line('2026-09-05T09:20:00', 'manual fix')
        own, other = classify_commits(raw, STARTED)
        self.assertEqual(own, [])
        self.assertEqual(other, ['manual fix'])

    def test_commit_after_run_start_belongs_to_the_run(self):
        own, other = classify_commits(
            self.line('2026-09-05T10:10:00', 'autopilot: b84'), STARTED)
        self.assertEqual(own, ['autopilot: b84'])
        self.assertEqual(other, [])

    def test_mixed_window_splits(self):
        raw = '\n'.join([self.line('2026-09-05T09:30:00', 'mine by hand'),
                         self.line('2026-09-05T09:40:00', 'run work')])
        own, other = classify_commits(raw, STARTED)
        self.assertEqual(own, ['run work'])
        self.assertEqual(other, ['mine by hand'])

    def test_exact_boundary_counts_as_the_run(self):
        own, other = classify_commits(
            self.line('2026-09-05T09:35:01', 'first act'), STARTED)
        self.assertEqual(own, ['first act'])
        self.assertEqual(other, [])

    def test_no_start_marker_falls_back_to_old_behaviour(self):
        own, other = classify_commits(
            self.line('2020-01-01T00:00:00', 'anything'), None)
        self.assertEqual(own, ['anything'])
        self.assertEqual(other, [])

    def test_unparsable_time_stays_visible(self):
        seen = []
        own, other = classify_commits('notanumber\x1fweird', STARTED,
                                      on_error=seen.append)
        self.assertEqual(own, ['weird'])
        self.assertEqual(len(seen), 1)

    def test_blank_lines_dropped(self):
        self.assertEqual(classify_commits('\n  \n', STARTED), ([], []))

    def test_the_13_00_shape_is_not_credited_to_the_run(self):
        """Regression for the demonstrated lie: rc=124 + one pre-run commit."""
        raw = '\n'.join([
            self.line('2026-09-05T06:20:46', 'rc=143 is a cutoff, not a crash'),
            self.line('2026-09-05T09:48:00', 'autopilot: b80 harness'),
        ])
        own, other = classify_commits(raw, epoch('2026-09-05T09:35:01'))
        self.assertEqual(own, ['autopilot: b80 harness'])
        self.assertEqual(other, ['rc=143 is a cutoff, not a crash'])


class ReportRendering(unittest.TestCase):
    """End-to-end on a throwaway git repo with CONTROLLED commit times.

    The repo has: commit A (prev state, 09:00) -> commit B (09:20, made
    BEFORE the run started at 09:35) -> optionally commit C (09:40, made
    DURING the run). `notifier` is deliberately absent so the narrative
    import fails and is swallowed (non-self-check mode), leaving the
    commit-attribution lines as the only variable.
    """

    LOG = ('2026-09-05T08:35:01Z === autopilot run start ===\n'
           '2026-09-05T09:30:02Z === autopilot run end rc=124 ===\n'
           '2026-09-05T09:35:01Z === autopilot run start ===\n')

    def _repo(self, tmp: Path, third: bool):
        work = tmp / 'repo'
        (work / 'scripts').mkdir(parents=True)
        (work / 'data' / 'ops').mkdir(parents=True)
        (work / 'logs').mkdir(parents=True)
        (work / 'engines').symlink_to(REPO / 'engines')
        import shutil
        shutil.copy(REPO / 'scripts' / 'autopilot_report.py',
                    work / 'scripts' / 'autopilot_report.py')
        (work / 'data' / 'ops' / 'autopilot_backlog.md').write_text(
            '- [x] done one\n- [ ] next item\n')
        self._git(work, 'init', '-q')
        self._git(work, 'config', 'user.email', 't@l')
        self._git(work, 'config', 'user.name', 'T')
        f = work / 'f.txt'
        f.write_text('a')
        self._git(work, 'add', '-A')
        self._commit(work, '2026-09-05T09:00:00', 'base')
        prev = self._git(work, 'rev-parse', 'HEAD')
        f.write_text('b')
        self._git(work, 'add', '-A')
        self._commit(work, '2026-09-05T09:20:00', 'manual fix between runs')
        if third:
            f.write_text('c')
            self._git(work, 'add', '-A')
            self._commit(work, '2026-09-05T09:40:00', 'autopilot: b84 work')
        # done=0 so the working-tree backlog (1 tick) always reads as progress
        (work / 'data' / 'ops' / 'autopilot_report_state.json').write_text(
            '{"head": "%s", "done": 0}' % prev)
        (work / 'logs' / 'autopilot.log').write_text(self.LOG)
        return work

    @staticmethod
    def _git(work, *args):
        return subprocess.run(['git', '-C', str(work)] + list(args),
                              capture_output=True, text=True,
                              check=True).stdout.strip()

    def _commit(self, work, when, msg):
        env = dict(os.environ, GIT_AUTHOR_DATE=when + '+0000',
                   GIT_COMMITTER_DATE=when + '+0000')
        subprocess.run(['git', '-C', str(work), 'commit', '-q', '-m', msg],
                       capture_output=True, text=True, check=True, env=env)

    def _render(self, rc, third):
        import shutil
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix='b85_'))
        try:
            work = self._repo(tmp, third)
            env = {k: v for k, v in os.environ.items()
                   if k not in ('AUTOPILOT_REPORT_BOT_TOKEN',
                                'TELEGRAM_BOT_TOKEN', 'HERMES_SELFCHECK')}
            r = subprocess.run(
                [sys.executable, str(work / 'scripts' / 'autopilot_report.py'),
                 str(rc)], capture_output=True, text=True, env=env,
                timeout=120, cwd=str(work))
            return r
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cutoff_with_only_pre_run_commit_is_honest(self):
        r = self._render(124, third=False)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        out = r.stdout
        self.assertIn('به سقف زمانی خورد', out)
        self.assertNotIn('کارش کامیت شده بود', out)
        self.assertIn('بیرون از این اجرا', out)
        self.assertIn('manual fix between runs', out)
        self.assertNotIn('تغییرات این اجرا', out)
        self.assertNotIn('روی گیت‌هاب ثبت شد', out)
        # backlog tick came from the working tree only -> must not read as banked
        self.assertIn('هنوز ثبت نشده', out)

    def test_cutoff_with_real_run_commit_still_credits_the_run(self):
        r = self._render(124, third=True)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        out = r.stdout
        self.assertIn('کارش کامیت شده بود', out)
        self.assertIn('تغییرات این اجرا', out)
        self.assertIn('autopilot: b84 work', out)
        # the pre-run manual commit is still VISIBLE, but never as this
        # run's achievement: it lands under the separate 'other' label
        self.assertIn('بیرون از این اجرا', out)
        self.assertNotIn('هنوز ثبت نشده', out)  # work IS banked here
        own_block = out.split('🧹')[0]
        self.assertNotIn('manual fix between runs', own_block)
        self.assertIn('1 تغییر کد', out)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
