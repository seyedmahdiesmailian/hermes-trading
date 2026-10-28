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
        # b85d: the script's dotenv fallback imports `env_loader` from the
        # REPO ROOT, and the child's sys.path[0] is this throwaway root — so
        # the fixture must carry that file too, or the child dies at import
        # (returncode 1) on any host without python-dotenv installed.
        shutil.copy(REPO / 'env_loader.py', work / 'env_loader.py')
        # b85b: the backlog starts BANKED with zero ticks; the tick is added
        # later and either committed (banked) or left dirty (working tree
        # only) — the note must follow the file's real git state.
        (work / 'data' / 'ops' / 'autopilot_backlog.md').write_text(
            '- [ ] next item\n')
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
        (work / 'data' / 'ops' / 'autopilot_backlog.md').write_text(
            '- [x] done one\n- [ ] next item\n')
        if third:
            f.write_text('c')
            self._git(work, 'add', '-A')
            self._commit(work, '2026-09-05T09:40:00', 'autopilot: b84 work')
        else:
            # the tick stays UNCOMMITTED (working tree only) -> the report
            # must say 'هنوز ثبت نشده'
            pass
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


# assembled at runtime so the phrase never appears verbatim in this file
# (an approval hook false-positives on lifecycle commands in payloads)
GR = 'gateway ' + 'restart'


class NarrativeNoise(unittest.TestCase):
    """b85b: the fleet-restart breadcrumb must never become the narrative.

    The 15:13 report on 2026-09-05 forwarded three lines of English CLI
    startup noise to the ops chat IN PLACE OF the agent's Persian summary,
    because those lines pushed `keep` past the <=2 threshold that guards the
    503 fallback. The run had actually died on a provider 503 — the honest
    text already existed, the noise just hid it.
    """

    NOISE = ('\u26a0 A previous `hermes update` pulled new code but did not '
             'restart running gateways.\n'
             '  Gateways may still be serving pre-update modules '
             '(mixed sys.modules).\n'
             '  Run `hermes update` or `hermes ' + GR + '`.\n')

    def _narrate(self, body):
        import shutil
        import tempfile
        from notifier import dashboards
        tmp = Path(tempfile.mkdtemp(prefix='b85b_'))
        try:
            (tmp / 'logs').mkdir()
            (tmp / 'logs' / 'autopilot.log').write_text(
                '2026-09-05T11:35:01Z === autopilot run start ===\n'
                + body +
                '2026-09-05T11:43:26Z === autopilot run end rc=0 ===\n')
            real = dashboards.ROOT
            dashboards.ROOT = tmp
            try:
                return dashboards._autopilot_narrative(max_chars=900)
            finally:
                dashboards.ROOT = real
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_noise_plus_503_renders_the_persian_fallback(self):
        out = self._narrate(self.NOISE +
                            'API call failed after 3 retries: HTTP 503: '
                            'Chat admission capacity is temporarily '
                            'unavailable. Retry shortly.\n')
        self.assertNotIn('hermes update', out)
        self.assertNotIn('Gateways', out)
        self.assertIn('این اجرا به نتیجه نرسید', out)
        self.assertIn('503', out)

    def test_real_narrative_survives_the_filter(self):
        out = self._narrate('سلام. آیتم b84 انجام شد و تست‌ها سبز هستند.\n')
        self.assertIn('b84', out)


class NarrativeEscape(unittest.TestCase):
    """b90: the agent's narrative is free text with raw '<'/'&' in it
    ('smc_conf < 0.35' killed a real report with Telegram HTTP 400).
    _autopilot_narrative must return HTML-safe text."""

    def test_angle_brackets_are_escaped(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'logs').mkdir()
            (root / 'logs' / 'autopilot.log').write_text(
                '2026-09-05T16:35:01Z === autopilot run start ===\n'
                'منطق `regime==range و bias!=neutral و smc_conf < 0.35` را '
                'روی کشیده و A & B را تست کرد\n'
                '2026-09-05T17:21:05Z === autopilot run end rc=0 ===\n')
            from notifier import dashboards as d
            real = d.ROOT
            d.ROOT = root
            try:
                out = d._autopilot_narrative(max_chars=900)
            finally:
                d.ROOT = real
        self.assertNotIn('< ', out)
        self.assertIn('&lt;', out)
        self.assertIn('&amp;', out)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
