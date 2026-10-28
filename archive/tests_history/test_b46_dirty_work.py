"""b46 — abandoned UNCOMMITTED code must be detectable, not invisible.

Background (proven incident, not hypothetical): b36 was found FULLY
IMPLEMENTED — 403 lines (fixtures + drift test + 4 consumer migrations) —
but left staged-and-dirty in the working tree by an interrupted autopilot
run. cron, git_sync and verify_head all see only HEAD, so the finished work
was invisible everywhere and the backlog still said `todo`. One
`git checkout -- .` would have erased it silently.

These tests pin engines/dirty_work (the single canonical detector, b40
pattern):
  * scope: only *.py/*.sh under tests/ engines/ scripts/ notifier/ or repo
    root count — data files, legacy_backup/, backups/ never page;
  * the age rule: untouched for >= DIRTY_ALERT_MINUTES while uncommitted =
    abandoned; fresh edits (an agent mid-run) are NOT flagged;
  * deleted tracked code (no mtime) always counts — the change itself is at
    risk;
  * porcelain -z parsing incl. the R/C two-field shape (the rename SOURCE
    must not leak as a bogus entry);
  * fail-safe: non-repo root / git failure → None, never a raise (a hermetic
    test run under HERMES_DATA_ROOT must self-disable);
  * panel integration: ops home verdict + ops:auto show the line when the
    detector fires and hide it when clean (scan patched on the SOURCE
    module — dashboards imports it LAZILY inside _dirty_line, so the patch
    reaches it; b41 discipline);
  * digest integration: real subprocess run against a THROWAWAY repo via
    HERMES_REPO_ROOT (never the live tree's dirtiness);
  * tripwire: no production module may hand-parse `git status` again —
    dirty_work is the single seam.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'tests'))

import hermetic  # noqa: E402
from engines import dirty_work  # noqa: E402

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _touch_old(path: Path, minutes: float):
    """Backdate mtime so the age rule can be tested without sleeping."""
    ts = (NOW - timedelta(minutes=minutes)).timestamp()
    os.utime(path, (ts, ts))


class FakeGitRepo:
    """A throwaway git repo with one commit, so `git status` output is
    fully controlled by the test."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='b46_repo_')
        self.root = Path(self._tmp.name)
        for d in ('engines', 'scripts', 'tests', 'data/ops'):
            (self.root / d).mkdir(parents=True)
        self.git('init', '-q')
        self.git('config', 'user.email', 't@t')
        self.git('config', 'user.name', 't')
        (self.root / 'engines/committed.py').write_text('x = 1\n')
        (self.root / 'keep.py').write_text('y = 1\n')
        (self.root / 'data/ops/state.json').write_text('{}\n')
        self.git('add', '-A')
        self.git('commit', '-qm', 'base')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root,
                              capture_output=True, text=True, check=True)

    def cleanup(self):
        self._tmp.cleanup()


class ScopeRules(unittest.TestCase):
    def test_code_paths_count(self):
        for p in ('engines/new.py', 'scripts/x.sh', 'tests/test_x.py',
                  'notifier/dashboards.py', 'hermes_master.py',
                  'position_daemon.py', 'run.sh'):
            self.assertTrue(dirty_work.is_code_path(p), p)

    def test_non_code_and_out_of_scope_never_count(self):
        for p in ('data/ops/autopilot_state.json', 'logs/master.log',
                  'legacy_backup/old.py', 'backups/bak/x.py',
                  'data/xau_plan/hack.py', 'README.md', 'assets/i.png',
                  'ops/systemd/hermes-master.service'):
            self.assertFalse(dirty_work.is_code_path(p), p)

    def test_threshold_is_one_hour(self):
        self.assertEqual(dirty_work.DIRTY_ALERT_MINUTES, 60)


class ScanAgainstFakeRepo(unittest.TestCase):
    """The b36 shape replayed end-to-end against a REAL git repo."""

    def setUp(self):
        self.r = FakeGitRepo()

    def tearDown(self):
        self.r.cleanup()

    def _write(self, rel, minutes=None, staged=False):
        p = self.r.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('# work\n')
        if minutes is not None:
            _touch_old(p, minutes)
        if staged:
            self.r.git('add', rel)
        return p

    def test_clean_repo_returns_none(self):
        self.assertIsNone(dirty_work.scan(self.r.root, now=NOW))

    def test_abandoned_dirty_code_is_flagged(self):
        # b36 exactly: staged 'A' with unstaged edits, 403 lines, 3h old
        self._write('tests/fixtures_bridge.py', minutes=180, staged=True)
        res = dirty_work.scan(self.r.root, now=NOW)
        self.assertIsNotNone(res)
        self.assertEqual([f['path'] for f in res['files']],
                         ['tests/fixtures_bridge.py'])
        self.assertAlmostEqual(res['max_age_min'], 180, delta=1)
        line = dirty_work.describe(res)
        self.assertIn('tests/fixtures_bridge.py', line)
        self.assertIn('commit', line)

    def test_fresh_edit_is_not_flagged(self):
        self._write('engines/wip.py', minutes=5)
        self.assertIsNone(dirty_work.scan(self.r.root, now=NOW),
                          'an agent mid-edit must never page')

    def test_shell_script_counts_like_python(self):
        # b44 lesson: verify_head.sh was the untracked file a .py-only scan
        # could not see.
        self._write('scripts/deploy.sh', minutes=120)
        res = dirty_work.scan(self.r.root, now=NOW)
        self.assertEqual([f['path'] for f in res['files']],
                         ['scripts/deploy.sh'])

    def test_dirty_data_files_never_trigger(self):
        # production churns data/*.json every 15 min — they must be invisible
        p = self.r.root / 'data/ops/state.json'
        p.write_text('{"changed": true}\n')
        _touch_old(p, 9999)
        self.assertIsNone(dirty_work.scan(self.r.root, now=NOW))

    def test_deleted_tracked_code_always_counts(self):
        (self.r.root / 'keep.py').unlink()
        res = dirty_work.scan(self.r.root, now=NOW)
        self.assertIsNotNone(res)
        f = res['files'][0]
        self.assertEqual(f['path'], 'keep.py')
        self.assertIsNone(f['age_min'])
        self.assertIn('سن نامعلوم', dirty_work.describe(res))

    def test_staged_rename_parses_without_leaking_source(self):
        self.r.git('mv', 'keep.py', 'renamed.py')
        _touch_old(self.r.root / 'renamed.py', 120)
        res = dirty_work.scan(self.r.root, now=NOW)
        self.assertIsNotNone(res)
        self.assertEqual([f['path'] for f in res['files']], ['renamed.py'],
                         'the rename SOURCE field must not leak as an entry')

    def test_non_repo_root_is_none_not_crash(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(dirty_work.scan(td, now=NOW))

    def test_missing_file_after_listing_is_survivable(self):
        # race: file deleted between git status and stat()
        self._write('engines/race.py', minutes=120)
        res = dirty_work.scan(self.r.root, now=NOW)
        (self.r.root / 'engines/race.py').unlink()
        self.assertIsNotNone(res)  # already-computed scan is pure data

    def test_many_files_sorted_and_truncated_in_line(self):
        for i in range(5):
            self._write(f'engines/f{i}.py', minutes=100 + i)
        res = dirty_work.scan(self.r.root, now=NOW)
        self.assertEqual(res['count'], 5)
        self.assertEqual(res['files'][0]['path'], 'engines/f4.py',
                         'oldest first')
        line = dirty_work.describe(res)
        self.assertIn('+2 دیگر', line)
        self.assertIn('کد commit‌نشده', dirty_work.describe(res, short=True))


class WriterReaderDiscipline(unittest.TestCase):
    """scan() must be the ONLY git-status reader in production code — the
    b40 lesson: two modules parsing one fact drift silently."""

    @staticmethod
    def _is_offender_line(s: str) -> bool:
        """The tripwire's line predicate, extracted so BOTH directions can
        be replayed (b52 discipline: a scoped-down rule must still catch
        the shape it was written for)."""
        return ('porcelain' in s and 'git' in s.lower()
                and 'status' in s.lower())

    def test_single_seam_no_hand_parsed_git_status(self):
        offenders = []
        for base in ('engines', 'notifier', 'scripts'):
            for p in sorted((REPO / base).rglob('*.py')):
                if p.name == 'dirty_work.py' or '__pycache__' in str(p):
                    continue
                for ln in p.read_text(encoding='utf-8',
                                      errors='ignore').splitlines():
                    s = ln.strip()
                    if s.startswith('#'):
                        continue
                    # b91: the seam is git-STATUS, not every --porcelain
                    # command. head_verify's `git worktree list --porcelain`
                    # reads a different fact (worktree registration) that
                    # dirty_work does not provide; flagging it would push a
                    # second module to fake a status parse. Scope the match
                    # to lines that actually parse git status.
                    if self._is_offender_line(s):
                        offenders.append(f'{p.relative_to(REPO)}: {s[:80]}')
        self.assertEqual(offenders, [],
                         'engines/dirty_work is the single git-status seam')

    def test_scoping_keeps_the_rule_alive(self):
        """ANTI-VACUITY (b91): narrowing the predicate to git-STATUS lines
        must not neuter it — the original b46 shape (a hand-parsed
        `git status --porcelain` outside dirty_work) still offends, while
        the worktree-registration read (a different fact, dirty_work has no
        API for it) does not."""
        bad = ["r = subprocess.run(['git', 'status', '--porcelain=v1', '-z'])",
               "out = _git('status', '--porcelain')"]
        for line in bad:
            self.assertTrue(self._is_offender_line(line),
                            f'hand-parsed git status no longer caught: {line}')
        good = ["r = _git('worktree', 'list', '--porcelain', cwd=repo)",
                "x = 1  # no git here"]
        for line in good:
            self.assertFalse(self._is_offender_line(line),
                             f'non-status porcelain command wrongly caught: {line}')


class PanelIntegration(unittest.TestCase):
    """ops home verdict + ops:auto must show the line when the detector
    fires. dashboards imports dirty_work LAZILY inside _dirty_line, so
    patching the source module attribute reaches it (b41-safe); hermetic
    temp root keeps scan() itself self-disabling for every OTHER test."""

    def setUp(self):
        hermetic.use_temp_data_root()
        from notifier import dashboards as d
        self.d = d
        self._real = (d._bridge, d._services)
        d._bridge = lambda: (None, {'ok': True, 'balance': 1000.0,
                                    'equity': 1000.0}, {'data': [], 'count': 0})
        d._services = lambda: {'hermes-signal': 'active',
                               'hermes-position': 'active',
                               'hermes-gateway': 'active',
                               'hermes-dashboard': 'active'}
        import engines.dirty_work as dw
        self._real_scan = dw.scan
        self.finding = {'files': [{'path': 'tests/fixtures_bridge.py',
                                   'status': 'AM', 'age_min': 180.0}],
                        'count': 1, 'max_age_min': 180.0}
        dw.scan = lambda *a, **k: self.finding
        self.addCleanup(lambda: setattr(dw, 'scan', self._real_scan))

    def tearDown(self):
        self.d._bridge, self.d._services = self._real
        hermetic.release()

    def test_hermetic_root_disables_real_scan(self):
        # before patching effects leak: with the REAL scan restored, a temp
        # (non-repo) root must yield None so no test depends on live dirt
        dw_scan = self._real_scan
        self.assertIsNone(dw_scan())

    def test_ops_home_verdict_flags_abandoned_code(self):
        ok, problems = self.d._verdict()
        self.assertFalse(ok, 'uncommitted finished work is a needs-attention fact')
        self.assertTrue(any('commit‌نشده' in p for p in problems), problems)
        text, _ = self.d.ops_home()
        self.assertIn('commit‌نشده', text)

    def test_ops_auto_shows_full_line(self):
        text, _ = self.d.ops_render('auto')
        self.assertIn('tests/fixtures_bridge.py', text)
        self.assertIn('commit‌نشده', text)

    def test_clean_tree_shows_nothing(self):
        import engines.dirty_work as dw
        dw.scan = lambda *a, **k: None
        ok, problems = self.d._verdict()
        self.assertTrue(ok, problems)
        self.assertNotIn('commit‌نشده', self.d.ops_render('auto')[0])
        self.assertNotIn('commit‌نشده', self.d.ops_home()[0])


class DigestIntegration(unittest.TestCase):
    """Run the digest the way cron does — fresh subprocess — but point
    HERMES_REPO_ROOT at a throwaway repo so the assertion never depends on
    whether the live tree happens to be mid-edit."""

    def setUp(self):
        self.r = FakeGitRepo()
        p = self.r.root / 'engines/leftover.py'
        p.write_text('# finished but never committed\n')
        _touch_old(p, 240)

    def tearDown(self):
        self.r.cleanup()

    def _run(self, repo_root):
        env = dict(os.environ)
        env['HERMES_REPO_ROOT'] = str(repo_root)
        env['AUTOPILOT_REPORT_BOT_TOKEN'] = ''
        env['TELEGRAM_BOT_TOKEN'] = ''
        r = subprocess.run([sys.executable, 'scripts/autopilot_digest.py'],
                           capture_output=True, text=True, timeout=60,
                           env=env, cwd=str(REPO))
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        return r.stdout

    def test_digest_includes_abandoned_line(self):
        out = self._run(self.r.root)
        self.assertIn('commit‌نشده', out)
        self.assertIn('engines/leftover.py', out)

    def test_digest_clean_repo_has_no_line(self):
        clean = FakeGitRepo()
        try:
            out = self._run(clean.root)
        finally:
            clean.cleanup()
        self.assertNotIn('commit‌نشده', out)
        self.assertIn('گزارش خودکار', out)  # digest itself still built


if __name__ == '__main__':
    unittest.main()
