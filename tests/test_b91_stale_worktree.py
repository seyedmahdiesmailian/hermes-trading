"""b91 — the verifier must heal its OWN hard-kill leftovers.

INCIDENT (2026-09-05, found at the start of the next run): the 21:13 autopilot
run was hard-killed while its own suite sat inside
tests/test_b50_*.py::FullSuiteInsideHead.setUpClass -> head_verify.verify_ref.
SIGKILL skips Python's `finally`, so the detached worktree stayed REGISTERED
(/tmp/hermes_headverify_*/checkout). The next full suite then went RED on
test_worktree_is_cleaned_up_after_verification — a test that itself runs
verify_ref at class level, so the leak poisoned every subsequent run until a
human removed it by hand: a self-poisoning loop.

Why `git worktree prune` (which verify_ref already called) cannot heal this:
prune only drops registrations whose DIRECTORY is gone. A killed run leaves
the directory in place, so git sees a perfectly valid live worktree.

The fix pinned here: verify_ref sweeps its own orphans before working.
Safety contract (each clause gets a test):
  1. only paths containing this module's temp prefix are ever touched —
     the main checkout is structurally unremovable;
  2. a worktree whose owner.pid is ALIVE is never removed (a concurrent
     verification — cron's b51 start-heal vs the agent's step 4b — is safe);
  3. a worktree whose owner.pid is DEAD is removed immediately (that is the
     incident shape — no age wait);
  4. no pid file (pre-b91 leftover) falls back to the conservative age rule;
  5. the sweep never raises and its report rides on verify_ref's result.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engines import head_verify  # noqa: E402


def _sha(ref='HEAD'):
    return subprocess.run(['git', 'rev-parse', ref], cwd=str(REPO),
                          capture_output=True, text=True).stdout.strip()


def _worktree_paths():
    out = subprocess.run(['git', 'worktree', 'list', '--porcelain'], cwd=str(REPO),
                         capture_output=True, text=True).stdout
    return [l[len('worktree '):] for l in out.splitlines()
            if l.startswith('worktree ')]


def _make_leftover(pid_text=None, mtime_age=None):
    """Register a real detached worktree under the verifier's own temp prefix,
    exactly the shape a hard-killed run leaves behind. Caller must remove it."""
    base = Path(tempfile.mkdtemp(prefix=head_verify.WORKTREE_PREFIX))
    wt = base / 'checkout'
    if pid_text is not None:
        (base / 'owner.pid').write_text(pid_text, encoding='utf-8')
    r = subprocess.run(['git', 'worktree', 'add', '--detach', str(wt), _sha()],
                       cwd=str(REPO), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    if mtime_age is not None:
        t = time.time() - mtime_age
        os.utime(wt, (t, t))
    return base, wt


def _cleanup(base, wt):
    subprocess.run(['git', 'worktree', 'remove', '--force', str(wt)],
                   cwd=str(REPO), capture_output=True)
    subprocess.run(['git', 'worktree', 'prune'], cwd=str(REPO),
                   capture_output=True)
    import shutil
    shutil.rmtree(base, ignore_errors=True)


def _dead_pid():
    """A pid that cannot be alive: spawn and reap a short-lived child."""
    import subprocess as sp
    p = sp.Popen([sys.executable, '-c', 'pass'])
    p.wait()
    return p.pid


class TestParsing(unittest.TestCase):
    def test_list_worktrees_reads_porcelain(self):
        wts = head_verify.list_worktrees(REPO)
        paths = [w['path'] for w in wts]
        self.assertIn(str(REPO), paths)
        main = next(w for w in wts if w['path'] == str(REPO))
        self.assertFalse(main['detached'])
        self.assertEqual(main['head'], _sha())

    def test_owner_state_three_signatures(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(head_verify.owner_state(d), 'unknown')
            (Path(d) / 'owner.pid').write_text(str(os.getpid()))
            self.assertEqual(head_verify.owner_state(d), 'alive')
            (Path(d) / 'owner.pid').write_text(str(_dead_pid()))
            self.assertEqual(head_verify.owner_state(d), 'dead')
            (Path(d) / 'owner.pid').write_text('not-a-pid')
            self.assertEqual(head_verify.owner_state(d), 'unknown')


class TestSweepRealWorktrees(unittest.TestCase):
    """The sweep against REAL registered worktrees in the REAL repo — the
    incident is a repo-state bug; a mocked listing would pin nothing."""

    def test_dead_owner_orphan_is_removed_at_once(self):
        base, wt = _make_leftover(pid_text=str(_dead_pid()), mtime_age=5)
        try:
            self.assertIn(str(wt), _worktree_paths())
            rep = head_verify.sweep_stale_worktrees(repo=REPO)
            self.assertIn(str(wt), [r['path'] for r in rep['removed']])
            self.assertNotIn(str(wt), _worktree_paths())
            self.assertIn(str(REPO), _worktree_paths())  # main untouched
        finally:
            _cleanup(base, wt)

    def test_alive_owner_is_never_touched(self):
        base, wt = _make_leftover(pid_text=str(os.getpid()), mtime_age=5)
        try:
            rep = head_verify.sweep_stale_worktrees(repo=REPO)
            self.assertNotIn(str(wt), [r['path'] for r in rep['removed']])
            kept = [k['path'] for k in rep['kept_fresh']]
            self.assertIn(str(wt), kept)
            self.assertIn(str(wt), _worktree_paths())
        finally:
            _cleanup(base, wt)

    def test_no_pid_file_young_is_kept_old_is_removed(self):
        # pre-b91 leftovers have no owner.pid: the age rule is the fallback
        base, wt = _make_leftover(pid_text=None, mtime_age=5)
        try:
            rep = head_verify.sweep_stale_worktrees(repo=REPO)
            self.assertNotIn(str(wt), [r['path'] for r in rep['removed']])
            self.assertIn(str(wt), _worktree_paths())
        finally:
            _cleanup(base, wt)
        base, wt = _make_leftover(pid_text=None,
                                  mtime_age=head_verify.STALE_WORKTREE_AFTER_SEC + 60)
        try:
            rep = head_verify.sweep_stale_worktrees(repo=REPO)
            self.assertIn(str(wt), [r['path'] for r in rep['removed']])
            self.assertNotIn(str(wt), _worktree_paths())
        finally:
            _cleanup(base, wt)

    def test_main_checkout_survives_any_sweep(self):
        # even with min_age 0 (the most aggressive sweep possible), the main
        # working tree must remain: its path can never contain the prefix.
        rep = head_verify.sweep_stale_worktrees(repo=REPO, min_age_sec=0)
        self.assertEqual(rep['removed'], [])
        self.assertIn(str(REPO), _worktree_paths())
        self.assertTrue(rep['pruned'])


class TestWiredIntoVerifyRef(unittest.TestCase):
    """verify_ref must actually call the sweep before worktree add — the
    incident heals only if the sweep runs on the verification path itself.
    Source-pinned (running verify_ref here would fork the full suite)."""

    def test_verify_ref_sweeps_before_add(self):
        src = (REPO / 'engines' / 'head_verify.py').read_text(encoding='utf-8')
        body = src[src.index('def verify_ref'):]
        self.assertIn('sweep_stale_worktrees()', body,
                      'verify_ref no longer sweeps its own leftovers — the '
                      'b91 self-poisoning loop is back')
        self.assertLess(body.index('sweep_stale_worktrees()'),
                        body.index("'worktree', 'add'"),
                        'the sweep must run BEFORE worktree add, or a stale '
                        'registration can block the verification')

    def test_owner_pid_written_before_registration(self):
        src = (REPO / 'engines' / 'head_verify.py').read_text(encoding='utf-8')
        body = src[src.index('def verify_ref'):]
        self.assertIn('owner.pid', body)
        self.assertLess(body.index('owner.pid'), body.index("'worktree', 'add'"),
                        'the pid stamp must exist before the worktree does, '
                        'or a sweep can never attribute a leftover to a live '
                        'verifier')

    def test_sweep_report_rides_on_the_result(self):
        src = (REPO / 'engines' / 'head_verify.py').read_text(encoding='utf-8')
        body = src[src.index('def verify_ref'):]
        self.assertIn("out['sweep']", body,
                      'a leak healed silently is a leak not measured — the '
                      'report must be visible in the verdict payload')

    def test_prefix_guard_is_the_module_own_prefix(self):
        # the sweep's blast radius is exactly this module's temp namespace
        self.assertEqual(head_verify.WORKTREE_PREFIX, 'hermes_headverify_')
        src = (REPO / 'engines' / 'head_verify.py').read_text(encoding='utf-8')
        body = src[src.index('def sweep_stale_worktrees'):src.index('def verify_ref')]
        self.assertIn('WORKTREE_PREFIX in p', body)


if __name__ == '__main__':
    unittest.main()
