"""b44 — the COMMITTED tree must boot on a clean checkout, not just import.

Why this file exists: b42 proved (twice: 88cac1e, then the untracked b42
test file itself) that `git commit -am` can ship a HEAD that dies with
ModuleNotFoundError on a fresh checkout. b42's analyzer catches the missing
MODULE, but it is a pure AST scan — it never runs anything. The next shape of
the same incident class is a HEAD that imports fine on THIS disk (where
.env, data/, logs/ and a warm __pycache__ all exist) and crashes or leaks on
a box that has only the commit. Cron runs `python3 hermes_master.py` against
HEAD every 15 min; a boot failure there kills every tick silently.

METHOD: materialize HEAD with `git archive` into a temp dir — a REAL clean
checkout: no .env, no __pycache__, nothing carried over from this disk —
then run a child python with an EMPTY environment (PATH/HOME only, so no
HERMES_* leaks from .env or the test runner) and HERMES_DATA_ROOT pointed at
the checkout. Assertions:
  1. every cron/systemd entrypoint IMPORTS (boot-time imports resolve
     inside the commit alone);
  2. every state accessor RESOLVES UNDER THE CHECKOUT — this is the part
     only a clean tree can prove: a module-level hardcoded
     /home/ai/hermes-trading path (the b39 class) would silently point a
     "clean" run at production state, and on a fresh deploy box it would
     crash on a missing directory;
  3. `python3 -m cli --help` exits 0 (argparse + module-level code run).
     hermes_master has NO argparse — running it would execute a real cycle,
     so it is deliberately NOT invoked, only imported.

The suite runs against HEAD, so it also serves as the POST-COMMIT check:
scripts/verify_head.sh re-runs exactly this file plus test_b42_tracked_imports
after every autopilot commit and logs the verdict (b44 procedure).

Proof it bites: test_synthetic_missing_module_is_flagged builds a fake
checkout whose entrypoint imports a module that is not there — the child
must report it RED.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]

# Modules cron/systemd actually launch (or that those launches import at
# boot). Verified against ops/cron/crontab.backup.txt + ops/systemd/*.
ENTRYPOINT_MODULES = [
    'hermes_master',
    'hermes_runtime',
    'position_daemon',
    'signal_daemon',
    'signal_monitor',
    'bridge_client',
    'cli',
    'env_loader',
]

# module -> [call-time accessor that must resolve INSIDE the redirected root]
# (b39 converted every state path to these; this check proves the conversion
# holds from a tree that contains nothing but the commit).
STATE_ACCESSORS = {
    'hermes_master': ['_log_file', '_report_file'],
    'hermes_runtime': ['_plan_dir'],
    'position_daemon': ['_log_file'],
    'signal_daemon': ['_log_file'],
    'signal_monitor': ['_log_file'],
    'cli': ['_plan_file', '_runtime_file', '_report_file'],
}

_CHILD = (
    'import importlib, json, sys\n'
    'from pathlib import Path\n'
    'sys.path.insert(0, %(root)r)\n'
    'res = {"imports": {}, "accessors": {}, "errors": []}\n'
    'root = Path(%(root)r).resolve()\n'
    'for mod in %(mods)r:\n'
    '    try:\n'
    '        m = importlib.import_module(mod)\n'
    '        res["imports"][mod] = "ok"\n'
    '    except Exception as e:\n'
    '        res["imports"][mod] = f"{type(e).__name__}: {e}"\n'
    '        res["errors"].append(f"{mod}: import failed {type(e).__name__}: {e}")\n'
    '        continue\n'
    '    for fn in %(accessors)r.get(mod, []):\n'
    '        try:\n'
    '            p = Path(str(getattr(m, fn)())).resolve()\n'
    '        except Exception as e:\n'
    '            res["errors"].append(f"{mod}.{fn}() raised {type(e).__name__}: {e}")\n'
    '            continue\n'
    '        under = root in p.parents or p == root\n'
    '        res["accessors"][f"{mod}.{fn}"] = str(p)\n'
    '        if not under:\n'
    '            res["errors"].append(f"{mod}.{fn}() escapes the redirected root: {p}")\n'
    'print(json.dumps(res))\n'
)


def export_ref(dest: str, ref: str = 'HEAD') -> None:
    """Materialize a COMMITTED tree only — git archive carries neither
    untracked files, .env, nor __pycache__: exactly what a fresh deploy
    or a cron checkout sees."""
    r = subprocess.run(['git', 'archive', '--format=tar', ref],
                       cwd=REPO, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f'git archive {ref} failed: {r.stderr.decode()[:200]}')
    p = subprocess.run(['tar', '-x', '-C', dest], input=r.stdout)
    if p.returncode != 0:
        raise RuntimeError('tar extract failed')


def run_child(checkout: str, mods=ENTRYPOINT_MODULES,
              accessors=None) -> dict:
    """Empty env + HERMES_DATA_ROOT=checkout: the boot must depend on the
    commit and the env var ONLY — never on files that exist just on this disk."""
    env = {'PATH': '/usr/bin:/bin', 'HOME': checkout,
           'HERMES_DATA_ROOT': checkout}
    src = _CHILD % {'root': checkout, 'mods': list(mods),
                    'accessors': accessors if accessors is not None
                    else STATE_ACCESSORS}
    r = subprocess.run([sys.executable, '-c', src],
                       capture_output=True, text=True, env=env, timeout=120,
                       cwd=checkout)
    if r.returncode != 0:
        raise AssertionError(
            f'clean-checkout boot child crashed rc={r.returncode}\n'
            f'STDOUT: {r.stdout[-2000:]}\nSTDERR: {r.stderr[-3000:]}')
    return json.loads(r.stdout.strip().splitlines()[-1])


class CleanCheckoutBoot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='hermes_b44_')
        export_ref(cls.tmp, 'HEAD')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_entrypoints_import_from_the_commit_alone(self):
        res = run_child(self.tmp)
        self.assertEqual(res['errors'], [],
                         f'HEAD does not boot on a clean checkout: {res["errors"]}')
        for mod in ENTRYPOINT_MODULES:
            self.assertEqual(res['imports'][mod], 'ok', mod)

    def test_state_accessors_follow_hermes_data_root(self):
        """Every b39 accessor must land inside the redirected root. A single
        hardcoded path here means a fresh deploy writes into a directory it
        does not own — or worse, into production state on this box."""
        res = run_child(self.tmp)
        expected = sum(len(v) for v in STATE_ACCESSORS.values())
        self.assertEqual(
            len(res['accessors']), expected,
            f'anti-vacuity: checked {len(res["accessors"])} accessors, '
            f'expected {expected} — one was silently skipped '
            f'(import died or attr renamed): {sorted(res["accessors"])}')
        for key, p in res['accessors'].items():
            self.assertTrue(
                p.startswith(str(Path(self.tmp).resolve())),
                f'{key}() resolved outside the checkout: {p}')

    def test_cli_help_runs_on_clean_checkout(self):
        env = {'PATH': '/usr/bin:/bin', 'HOME': self.tmp,
               'HERMES_DATA_ROOT': self.tmp}
        r = subprocess.run([sys.executable, '-m', 'cli', '--help'],
                           capture_output=True, text=True, env=env,
                           timeout=60, cwd=self.tmp)
        self.assertEqual(r.returncode, 0,
                         f'cli --help failed:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}')

    def test_no_production_state_written_by_the_boot(self):
        """The child above must not have touched THIS box's live files.
        Snapshot mtimes of the state tree before/after a fresh run. The
        15-min cron can legitimately write these files mid-test, so a
        changed snapshot is retried once — two consecutive 2s windows both
        catching a write is only possible if the boot itself is writing."""
        watch = [REPO / 'data' / 'xau_plan' / 'current_plan.json',
                 REPO / 'data' / 'xau_plan' / 'runtime_state.json',
                 REPO / 'logs' / 'master.log']

        def snap():
            return [(w, w.stat().st_mtime_ns if w.exists() else None)
                    for w in watch]

        for _ in range(2):
            before = snap()
            run_child(self.tmp)
            if snap() == before:
                return
        self.fail('clean-checkout boot wrote into production state')


class TripwireBites(unittest.TestCase):
    def test_verify_head_script_captures_real_rc(self):
        """b44 finding (2026-08-31, live): the first version of
        scripts/verify_head.sh did `if timeout … unittest; then …OK… fi`
        followed by `RC=$?`. In bash, after an `if` whose condition failed
        with NO else branch, `$?` is the status of the IF compound — always
        0 — not the condition's. The real log proves it:
        'HEAD=43c5f52 VERDICT=BROKEN rc=0'. The verdict was right but the
        recorded code was a lie, so any future automation keying on rc would
        read a failure as a success. Pin BOTH halves: the bash semantics
        (old shape yields 0, new shape yields the real code) and the script
        text (must run-then-capture, never if-then-capture)."""
        old = ('if false; then :; fi\nRC=$?\necho "rc=$RC"\n')
        new = ('false\nRC=$?\nif [ "$RC" -ne 0 ]; then echo "rc=$RC"; fi\n')
        r_old = subprocess.run(['bash', '-c', old], capture_output=True,
                               text=True)
        r_new = subprocess.run(['bash', '-c', new], capture_output=True,
                               text=True)
        self.assertEqual(r_old.stdout.strip(), 'rc=0',
                         'bash semantics changed: the old bug shape is no '
                         'longer a lie? then the pin below is stale')
        self.assertEqual(r_new.stdout.strip(), 'rc=1',
                         'run-then-capture must see the real exit code')
        script = (REPO / 'scripts' / 'verify_head.sh').read_text()
        self.assertIn('RC=$?', script, 'verify_head.sh must capture rc')
        # the capture must NOT sit directly after an `fi` (old broken shape)
        lines = [l.strip() for l in script.splitlines() if l.strip()]
        for i, l in enumerate(lines):
            if l.startswith('RC=$?'):
                self.assertNotEqual(lines[i - 1], 'fi',
                                    'RC=$? after `fi` captures the if-'
                                    'compound status (always 0), not the '
                                    'test — the b44 rc bug is back')
        self.assertIn('VERDICT=BROKEN', script,
                      'broken verdict must still be logged')

    def test_synthetic_missing_module_is_flagged(self):
        """An entrypoint importing a module absent from the checkout must
        surface as an error — proof the child really runs the imports."""
        tmp = tempfile.mkdtemp(prefix='hermes_b44_synth_')
        try:
            Path(tmp, 'fake_entry.py').write_text(
                'import engines.definitely_not_there\n')
            res = run_child(tmp, mods=['fake_entry'], accessors={})
            self.assertTrue(any('fake_entry' in e for e in res['errors']),
                            f'broken import not flagged: {res}')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_synthetic_hardcoded_state_path_is_flagged(self):
        """An accessor that ignores HERMES_DATA_ROOT (pre-b39 shape) must be
        caught escaping the redirected root."""
        tmp = tempfile.mkdtemp(prefix='hermes_b44_synth2_')
        try:
            Path(tmp, 'fake_entry.py').write_text(
                'from pathlib import Path\n'
                'def _log_file():\n'
                '    return Path("/home/ai/hermes-trading/logs/x.log")\n')
            res = run_child(tmp, mods=['fake_entry'],
                            accessors={'fake_entry': ['_log_file']})
            self.assertTrue(any('escapes the redirected root' in e
                                for e in res['errors']),
                            f'hardcoded path not flagged: {res}')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
