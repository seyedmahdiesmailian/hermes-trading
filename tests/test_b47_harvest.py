"""b47 — the autopilot run must HARVEST abandoned work before picking an item.

Background (proven incident): b36 was found fully implemented (403 lines)
but left uncommitted by an interrupted run. b46 made such leftovers VISIBLE
on the dashboards/digest, but the next autopilot run still started blind —
the agent read the backlog and had no idea finished code was sitting in the
tree. The recovery was luck-of-the-audit; this makes it procedure:
scripts/autopilot.sh runs scripts/autopilot_harvest.py before building the
prompt, and when engines/dirty_work fires, a STEP 0 block is prepended
telling the agent to verify + commit the leftover as its own commit FIRST.

Pinned here:
  * harvest_block(): empty for a clean tree; names every file, the count,
    the age, and the verify-then-commit-own-commit procedure;
  * end-to-end subprocess against a THROWAWAY repo via HERMES_REPO_ROOT
    (never the live tree): the exact b36 shape (staged 'AM', 3h old) prints
    STEP 0; a clean repo prints NOTHING (anti-vacuity both directions);
  * fail-safe: non-repo root / missing git → empty stdout, rc=0 — a broken
    harvest check must never block the autopilot run;
  * autopilot.sh wiring tripwire: the script must call the harvester and
    prepend the block to PROMPT before launching the agent, and the bash
    prepend semantics are replayed for real (non-empty → prompt starts with
    STEP 0 and keeps the original task; empty → prompt unchanged).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'scripts'))

import autopilot_harvest  # noqa: E402

# The harvester subprocess reads engines.dirty_work from the REAL repo and
# scans whatever HERMES_REPO_ROOT points at; backdating mtimes must be
# relative to the ACTUAL current time (the subprocess compares against
# datetime.now(), unlike b46's in-process tests which pass now= explicitly).


def _touch_old(path: Path, minutes: float):
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).timestamp()
    os.utime(path, (ts, ts))


class FakeGitRepo:
    """Throwaway repo with one commit — same harness as test_b46_dirty_work."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='b47_repo_')
        self.root = Path(self._tmp.name)
        for d in ('engines', 'scripts', 'tests'):
            (self.root / d).mkdir(parents=True)
        self.git('init', '-q')
        self.git('config', 'user.email', 't@t')
        self.git('config', 'user.name', 't')
        (self.root / 'engines/committed.py').write_text('x = 1\n')
        self.git('add', '-A')
        self.git('commit', '-qm', 'base')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root,
                              capture_output=True, text=True, check=True)

    def cleanup(self):
        self._tmp.cleanup()


class HarvestBlock(unittest.TestCase):
    def test_clean_tree_is_empty_string(self):
        self.assertEqual(autopilot_harvest.harvest_block(None), '')

    def test_block_names_files_count_age_and_procedure(self):
        res = {'files': [{'path': 'tests/fixtures_bridge.py',
                          'status': 'AM', 'age_min': 180.0},
                         {'path': 'engines/leftover.py',
                          'status': '??', 'age_min': 90.0}],
               'count': 2, 'max_age_min': 180.0}
        b = autopilot_harvest.harvest_block(res)
        self.assertIn('STEP 0', b)
        self.assertIn('tests/fixtures_bridge.py', b)
        self.assertIn('engines/leftover.py', b)
        self.assertIn('2 file(s)', b)
        self.assertIn('3.0 hours', b)
        # the procedure itself: verify suite, own commit, verify_head, THEN todo
        self.assertIn('unittest discover -s tests', b)
        self.assertIn('harvest:', b)
        self.assertIn('verify_head.sh', b)
        self.assertIn('TOP', b)

    def test_unknown_age_and_minutes_render(self):
        res = {'files': [{'path': 'keep.py', 'status': 'D', 'age_min': None}],
               'count': 1, 'max_age_min': None}
        self.assertIn('unknown age', autopilot_harvest.harvest_block(res))
        res2 = {'files': [{'path': 'x.py', 'status': '??', 'age_min': 70.0}],
                'count': 1, 'max_age_min': 45.0}
        self.assertIn('45 minutes', autopilot_harvest.harvest_block(res2))


class HarvesterSubprocess(unittest.TestCase):
    """Run the script the way autopilot.sh does — fresh subprocess,
    HERMES_REPO_ROOT at a throwaway repo (b46 seam)."""

    def _run(self, repo_root):
        env = dict(os.environ)
        env['HERMES_REPO_ROOT'] = str(repo_root)
        r = subprocess.run([sys.executable,
                            str(REPO / 'scripts/autopilot_harvest.py')],
                           capture_output=True, text=True, timeout=60,
                           env=env, cwd=str(REPO))
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        return r.stdout

    def test_b36_shape_prints_step_zero(self):
        r = FakeGitRepo()
        try:
            p = r.root / 'tests/fixtures_bridge.py'
            p.write_text('# finished, staged, never committed\n')
            r.git('add', 'tests/fixtures_bridge.py')
            p.write_text('# plus unstaged edits\n')
            # backdate AFTER the second write — writing resets mtime
            _touch_old(p, 180)
            out = self._run(r.root)
            self.assertIn('STEP 0', out)
            self.assertIn('tests/fixtures_bridge.py', out)
        finally:
            r.cleanup()

    def test_clean_repo_prints_nothing(self):
        r = FakeGitRepo()
        try:
            self.assertEqual(self._run(r.root).strip(), '',
                             'a clean tree must not inject a STEP 0')
        finally:
            r.cleanup()

    def test_fresh_edit_prints_nothing(self):
        # an agent mid-edit (< 60 min) is not abandoned work
        r = FakeGitRepo()
        try:
            p = r.root / 'engines/wip.py'
            p.write_text('# new\n')
            self.assertEqual(self._run(r.root).strip(), '')
        finally:
            r.cleanup()

    def test_non_repo_is_silent_not_crash(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(self._run(td).strip(), '')


class AutopilotShWiring(unittest.TestCase):
    """autopilot.sh must actually USE the harvester — the whole point of
    b47 is procedure, not a module nobody calls."""

    def test_script_calls_harvester_and_prepends_block(self):
        sh = (REPO / 'scripts' / 'autopilot.sh').read_text()
        self.assertIn('autopilot_harvest.py', sh,
                      'autopilot.sh must run the harvester before the prompt')
        self.assertIn('HARVEST="$(', sh)
        self.assertIn('PROMPT="$HARVEST', sh,
                      'the block must be PREPENDED to PROMPT')
        # ordering: harvest runs before the agent launches
        self.assertLess(sh.index('autopilot_harvest.py'),
                        sh.index('"$HERMES_BIN" -z'),
                        'harvest must happen before the agent starts')
        # b49: the blind `|| true` is GONE — the harvester now runs with
        # --self-check and its real rc is captured immediately (never after
        # an `if` compound, b44 lesson); a broken harvester must be LOUD in
        # the log while the run still continues (no exit on the failure path).
        seg = sh[sh.index('autopilot_harvest.py'):sh.index('PROMPT=\'You are')]
        code = '\n'.join(l for l in seg.splitlines()
                         if not l.strip().startswith('#'))
        self.assertIn('--self-check', code,
                      'autopilot.sh must run the harvester in self-check mode')
        self.assertIn('HARVEST_RC=$?', code)
        self.assertNotIn('|| true', code,
                         'blind || true would make BROKEN == CLEAN again')
        self.assertNotIn('exit', code,
                         'a failed self-check must LOG, never kill the run')

    def test_bash_prepend_semantics_replayed(self):
        """Prove the exact shell shape in autopilot.sh behaves: non-empty
        HARVEST → prompt starts with STEP 0 and keeps the task; empty →
        prompt unchanged."""
        snippet = (
            'HARVEST="$1"\n'
            'PROMPT="TASK: pick the top todo."\n'
            'if [ -n "$HARVEST" ]; then\n'
            '  PROMPT="$HARVEST\n\n$PROMPT"\n'
            'fi\n'
            'printf "%s" "$PROMPT"\n')
        r1 = subprocess.run(['bash', '-c', snippet, 'b47', 'STEP 0: harvest'],
                            capture_output=True, text=True)
        self.assertTrue(r1.stdout.startswith('STEP 0: harvest'), r1.stdout)
        self.assertIn('TASK: pick the top todo.', r1.stdout,
                      'the original procedure must survive the prepend')
        r2 = subprocess.run(['bash', '-c', snippet, 'b47', ''],
                            capture_output=True, text=True)
        self.assertEqual(r2.stdout, 'TASK: pick the top todo.')


if __name__ == '__main__':
    unittest.main()
