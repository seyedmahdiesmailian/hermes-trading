"""b49 — fail-safe scripts must not be indistinguishable from no-op scripts.

The observability layer (autopilot_harvest, autopilot_digest,
autopilot_report, engines.dirty_work) swallows every error on purpose so a
broken check never blocks the trading run. The blind side: BROKEN and CLEAN
produce byte-identical output — b48 only caught the harvester's silent
death by luck (a shadow package happened to RAISE). A NameError or a moved
function inside any swallow block would print nothing forever and every
panel would read that silence as "all good".

The seam (engines/selfcheck.py): inside a swallow block call
`fail(section, exc)` before returning the sentinel. Normal mode: no-op,
behaviour byte-identical to `pass`. With --self-check / HERMES_SELFCHECK=1:
re-raises → non-zero exit + traceback naming the broken section. Self-check
mode also suppresses outbound side effects (no Telegram send, no report
STATE write) so probing can neither spam ops nor consume a pending report.

Pinned here:
  * unit: enabled() via env AND argv; fail() silent when off, RuntimeError
    naming the section when on;
  * the DEMONSTRATED ambiguity: harvester with git unfindable (PATH stripped)
    in NORMAL mode = rc 0, empty stdout — byte-identical to a clean tree;
    the SAME breakage under --self-check = rc != 0 (loud);
  * harvester end-to-end on a b36-shaped throwaway repo under --self-check:
    rc 0 AND STEP 0 printed (alive-and-firing is distinguishable from both
    broken and clean); clean repo under --self-check: rc 0, empty;
  * digest --self-check: builds + prints the digest, never sends even with a
    token set; broken git under --self-check exits non-zero;
  * report --self-check: rc arg parsing survives the flag, STATE file is
    NOT written (probe must not consume the pending report);
  * AST tripwire: every swallow block in the wired files must call
    selfcheck.fail — with a minimum-findings count (b41/b48 lesson: a dead
    parse must not pass by finding nothing) and a synthetic BROKEN-source
    replay proving the tripwire bites.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO = Path('/home/ai/hermes-trading')
sys.path.insert(0, str(REPO))

from engines import selfcheck  # noqa: E402

WIRED = ['scripts/autopilot_harvest.py', 'scripts/autopilot_digest.py',
         'scripts/autopilot_report.py', 'engines/dirty_work.py']


def _touch_old(path: Path, minutes: float):
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).timestamp()
    os.utime(path, (ts, ts))


class FakeGitRepo:
    """Throwaway repo with one commit — same harness as b46/b47 tests."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='b49_repo_')
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


class SeamUnit(unittest.TestCase):
    def test_enabled_by_env_truthy_values(self):
        for v in ('1', 'true', 'TRUE', 'yes', 'on'):
            with mock.patch.dict(os.environ, {'HERMES_SELFCHECK': v}):
                self.assertTrue(selfcheck.enabled([]), v)
        for v in ('', '0', 'false', 'off', 'maybe'):
            with mock.patch.dict(os.environ, {'HERMES_SELFCHECK': v}):
                self.assertFalse(selfcheck.enabled([]), repr(v))

    def test_enabled_by_argv_flag(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(selfcheck.enabled(['--self-check']))
            self.assertTrue(selfcheck.enabled(['x', '--self-check']))
            self.assertFalse(selfcheck.enabled([]))

    def test_fail_silent_when_off(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(selfcheck.fail('section', ValueError('boom')))

    def test_fail_raises_named_section_when_on(self):
        with mock.patch.dict(os.environ, {'HERMES_SELFCHECK': '1'}):
            with self.assertRaises(RuntimeError) as cm:
                selfcheck.fail('harvest scan', ValueError('boom'))
        msg = str(cm.exception)
        self.assertIn('harvest scan', msg)
        self.assertIn('boom', msg)
        self.assertIsInstance(cm.exception.__cause__, ValueError)


class _ScriptRunner(unittest.TestCase):
    def _run(self, script, args=(), env_extra=None, cwd=None):
        env = dict(os.environ)
        env['AUTOPILOT_REPORT_BOT_TOKEN'] = ''
        env['TELEGRAM_BOT_TOKEN'] = ''
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, str(REPO / script), *args],
            capture_output=True, text=True, timeout=90,
            env=env, cwd=str(cwd or REPO))


class HarvesterAmbiguityKilled(_ScriptRunner):
    """THE core b49 claim, demonstrated end-to-end: a harvester whose git
    is unfindable prints NOTHING and exits 0 in normal mode — byte-identical
    to a clean tree — and goes LOUD (non-zero) under --self-check."""

    NO_GIT = {'PATH': '/nonexistent-b49'}

    def _harvest(self, repo_root, selfcheck_on):
        env = {'HERMES_REPO_ROOT': str(repo_root), **self.NO_GIT}
        args = ['--self-check'] if selfcheck_on else []
        return self._run('scripts/autopilot_harvest.py', args, env)

    def test_broken_is_silent_in_normal_mode(self):
        # the ambiguity this item exists to kill, pinned as a FACT:
        r = self._harvest(REPO, selfcheck_on=False)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        self.assertEqual(r.stdout.strip(), '')

    def test_broken_is_loud_under_selfcheck(self):
        r = self._harvest(REPO, selfcheck_on=True)
        self.assertNotEqual(r.returncode, 0,
                            'git unfindable must exit non-zero under --self-check')
        self.assertIn('harvest scan', r.stderr,
                      'traceback must name the swallowed section')

    def test_env_var_form_also_loud(self):
        env = {'HERMES_REPO_ROOT': str(REPO), **self.NO_GIT,
               'HERMES_SELFCHECK': '1'}
        r = self._run('scripts/autopilot_harvest.py', (), env)
        self.assertNotEqual(r.returncode, 0)

    def test_alive_and_firing_is_distinguishable(self):
        # b36-shaped leftover in a throwaway repo, self-check ON, git WORKS:
        # rc 0 AND STEP 0 printed — three states now have three signatures:
        # broken=rc!=0, firing=rc0+text, clean=rc0+empty.
        r = FakeGitRepo()
        try:
            p = r.root / 'tests/leftover_b49.py'
            p.write_text('# finished, staged, never committed\n')
            r.git('add', 'tests/leftover_b49.py')
            p.write_text('# plus unstaged edits\n')
            _touch_old(p, 180)
            res = self._run('scripts/autopilot_harvest.py', ['--self-check'],
                            {'HERMES_REPO_ROOT': str(r.root)})
            self.assertEqual(res.returncode, 0, res.stderr[-400:])
            self.assertIn('STEP 0', res.stdout)
        finally:
            r.cleanup()

    def test_clean_repo_selfcheck_rc0_empty(self):
        r = FakeGitRepo()
        try:
            res = self._run('scripts/autopilot_harvest.py', ['--self-check'],
                            {'HERMES_REPO_ROOT': str(r.root)})
            self.assertEqual(res.returncode, 0, res.stderr[-400:])
            self.assertEqual(res.stdout.strip(), '')
        finally:
            r.cleanup()


class DigestSelfCheck(_ScriptRunner):
    def test_selfcheck_prints_digest_and_never_sends(self):
        # token SET (fake) — normal mode would attempt a send; self-check
        # must fall through to printing the text instead.
        r = self._run('scripts/autopilot_digest.py', ['--self-check'],
                      {'AUTOPILOT_REPORT_BOT_TOKEN': '123:fake-b49-token'})
        self.assertEqual(r.returncode, 0, r.stderr[-600:])
        self.assertIn('گزارش خودکار', r.stdout)
        self.assertNotIn('digest sent', r.stdout)
        self.assertNotIn('send failed', r.stdout)

    def test_selfcheck_loud_on_broken_git(self):
        r = self._run('scripts/autopilot_digest.py', ['--self-check'],
                      {'PATH': '/nonexistent-b49'})
        self.assertNotEqual(r.returncode, 0,
                            'digest swallow blocks must raise under --self-check')
        self.assertIn('git commits section', r.stderr)

    def test_normal_mode_still_survives_broken_git(self):
        r = self._run('scripts/autopilot_digest.py', (),
                      {'PATH': '/nonexistent-b49'})
        self.assertEqual(r.returncode, 0, r.stderr[-600:])
        self.assertIn('گزارش خودکار', r.stdout)


class ReportSelfCheck(_ScriptRunner):
    def test_flag_does_not_break_rc_arg(self):
        # argv[1] is the run rc; a bare --self-check must parse as rc=0,
        # not crash on int('--self-check').
        r = self._run('scripts/autopilot_report.py', ['--self-check'])
        self.assertNotIn('ValueError', r.stderr)
        self.assertEqual(r.returncode, 0, r.stderr[-600:])

    def test_selfcheck_does_not_write_state(self):
        # probing must not consume the pending report (STATE records the
        # last reported head — writing it from a probe would swallow a real
        # run's report).
        state = REPO / 'data/ops/autopilot_report_state.json'
        before = state.read_bytes() if state.exists() else None
        r = self._run('scripts/autopilot_report.py', ['--self-check'],
                      {'AUTOPILOT_REPORT_BOT_TOKEN': '123:fake-b49-token'})
        self.assertEqual(r.returncode, 0, r.stderr[-600:])
        after = state.read_bytes() if state.exists() else None
        self.assertEqual(before, after,
                         '--self-check must not write report STATE')


# ── static tripwire ──────────────────────────────────────────────────────

def _swallow_blocks(src: str):
    """Yield (lineno, body_src) for every `except Exception` block that
    SWALLOWS — no raise, no selfcheck.fail seam, and no loud output (print/
    logging call). Those are the blocks where BROKEN == CLEAN; every one of
    them in a wired fail-safe file must carry the seam."""
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        t = node.type
        is_exc = ((isinstance(t, ast.Name) and t.id == 'Exception')
                  or (isinstance(t, ast.Attribute) and t.attr == 'Exception'))
        if not is_exc:
            continue
        body_src = ast.unparse(ast.Module(body=node.body, type_ignores=[]))
        if 'selfcheck.fail' in body_src:
            continue  # seam present — loud under self-check
        # NOTE: ast.walk returns a GENERATOR — materialize it, iterating it
        # twice (once per check below) silently makes the second check vacuous.
        nodes = list(ast.walk(ast.Module(body=node.body, type_ignores=[])))
        if any(isinstance(s, (ast.Raise, ast.Try)) for s in nodes):
            continue
        if any(isinstance(s, ast.Call) and
               (getattr(s.func, 'id', '') in ('print', 'log', 'warn')
                or getattr(s.func, 'attr', '') in ('warning', 'error',
                                                   'exception', 'info'))
               for s in nodes):
            continue  # already loud (logs / prints the failure)
        out.append((node.lineno, body_src))
    return out


class SwallowTripwire(unittest.TestCase):
    """Every future `except Exception: pass` in the wired fail-safe files
    must carry the selfcheck seam — or the ambiguity comes back silently."""

    MIN_SWALLOW_BLOCKS = 8  # wired files have 9 today; a dead parse can't pass

    def test_wired_files_have_no_unseamed_swallow(self):
        total = 0
        for rel in WIRED:
            src = (REPO / rel).read_text()
            handlers = [n for n in ast.walk(ast.parse(src))
                        if isinstance(n, ast.ExceptHandler)
                        and ((isinstance(n.type, ast.Name)
                              and n.type.id == 'Exception')
                             or (isinstance(n.type, ast.Attribute)
                                 and n.type.attr == 'Exception'))]
            total += len(handlers)
            for lineno, body in _swallow_blocks(src):
                self.fail(f'{rel}:{lineno} swallows Exception without '
                          f'selfcheck.fail — broken would masquerade as clean: '
                          f'{body[:80]!r}')
        self.assertGreaterEqual(total, self.MIN_SWALLOW_BLOCKS,
                                f'only {total} except-Exception blocks found — '
                                'the parse is dead, not the code clean')

    def test_tripwire_bites_on_synthetic_source(self):
        # PROVEN to catch the exact regression shape: a swallow added later.
        bad = ("try:\n    x = f()\nexcept Exception:\n    pass\n")
        self.assertEqual(len(_swallow_blocks(bad)), 1)
        good = ("try:\n    x = f()\nexcept Exception as e:\n"
                "    selfcheck.fail('s', e)\n")
        self.assertEqual(len(_swallow_blocks(good)), 0)

    def test_harvester_still_imports_dirty_work_lazily(self):
        # the seam must not turn the harvester's import into a hard
        # dependency ordering change: dirty_work stays inside main()'s try
        # (b48 posture), only selfcheck (leaf) moved to module level.
        src = (REPO / 'scripts/autopilot_harvest.py').read_text()
        tree = ast.parse(src)
        top_imports = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                top_imports.add(node.module)
            if isinstance(node, ast.Import):
                top_imports.update(a.name for a in node.names)
        self.assertIn('engines', top_imports)  # engines.selfcheck
        main_src = next(ast.unparse(n) for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef) and n.name == 'main')
        self.assertIn('from engines import dirty_work', main_src,
                      'dirty_work import must stay inside the swallow block')


if __name__ == '__main__':
    unittest.main()
