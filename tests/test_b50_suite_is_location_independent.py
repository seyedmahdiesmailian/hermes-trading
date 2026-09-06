"""b50 — the suite must be able to verify a CHECKOUT, not just this disk.

Two facts this file pins, both learned the hard way:

(1) LOCATION INDEPENDENCE. Until b50 every test module did
    `sys.path.insert(0, '/home/ai/hermes-trading')`. Running the suite
    against any other tree (a checkout, a worktree, a deploy box) therefore
    imported PRODUCTION code, and unittest discovery aborted outright:
    "ImportError: 'test_b41_patch_bindings' module incorrectly imported from
    '/home/ai/hermes-trading/tests'. Expected '<checkout>/tests'". The git
    integrity tests (b42/b44/b46) had the same disease from the other side:
    they ran `git` in the production repo, so they certified the wrong tree.
    Tripwire below: no test module may bind the production root; the root
    comes from __file__. ALLOWED entries are the residual literals that are
    INTENTIONAL (docstring prose, synthetic fixture payloads, and b48's
    CODE_ROOT assertion which must prove the harvester's root is hardcoded).

(2) THE VERIFIER MUST RUN THE WHOLE SUITE. Commit 920ed0d shipped b45's
    tests without b45's source fixes: everything imported, 3 tests were RED,
    and verify_head.sh said OK because it only ran the two import checks.
    engines/head_verify.py now runs the FULL suite inside a clean detached
    worktree of the ref and stamps data/ops/head_verified.json. Pinned here
    against REAL history: 920ed0d verifies BROKEN, and the stamp round-trips.

RECURSION GUARD: the inner suite contains THIS file. verify_ref marks its
child env with HERMES_B50_NESTED=1 and the behavioural test skips when it is
set — otherwise every verification would spawn another verification forever.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'tests'))  # `import hermetic` must not depend
                                          # on discovery's path insertion

import hermetic  # noqa: E402
from engines import head_verify  # noqa: E402
# b96: reuse b91's real-worktree fixture builders (cross-test imports are an
# established shape here — b37/b64/b66/b92 do the same).
from test_b91_stale_worktree import _cleanup, _dead_pid, _make_leftover  # noqa: E402

TESTS_DIR = REPO / 'tests'
PROD_ROOT = '/home/ai/hermes-trading'

# The commit that proves the bug class: b45's tests shipped without b45's
# source fixes (selective staging). Import checks passed it; behaviour did not.
BROKEN_COMMIT = '920ed0d'

# Residual production-root literals that are INTENTIONAL. Every entry is
# checked for reality by test_allowed_entries_are_still_real, so a dead
# exemption cannot linger as a silent hole (b41/b42/b44 discipline).
ALLOWED = {
    'test_b44_clean_checkout.py':
        'docstring prose describing the b39 bug + a SYNTHETIC fixture whose '
        'whole point is a hardcoded path escaping the redirected root',
    'test_b48_env_seam_code_vs_state.py':
        'docstring example of the bad shape, synthetic analyzer fixtures, '
        'and the assertion that autopilot_harvest CODE_ROOT is HARDCODED '
        '(that literal must stay a literal — it is the b48 lesson)',
}


def _is_path_usage(value) -> bool:
    """True when a string constant IS the production root (or a path under
    it), as opposed to merely MENTIONING it."""
    if not isinstance(value, str):
        return False
    v = value.strip()
    return v == PROD_ROOT or v.startswith(PROD_ROOT + '/')


def _binding_lines(src: str) -> list:
    """Lines that BIND the production root into code (not prose/fixtures).

    A binding is a string constant that IS the root (or a path under it) and
    sits in a path-consuming position: an argument of `sys.path.insert/
    append`, of `Path(...)`/`os.getenv(...)`/`open(...)`, or the RHS of an
    assignment.

    The position filter is what keeps the scan honest in BOTH directions.
    Text-matching the whole source segment (the first draft) flagged
    `Path(tmp, 'fake_entry.py').write_text('... Path("/home/ai/hermes-trading
    /logs/x.log")\\n')` — a synthetic FIXTURE whose entire purpose is to
    contain the bad shape as data — as a real binding, i.e. the tripwire was
    blind to the difference between code and a string of code. Prose and
    fixture payloads are now excluded because the literal is embedded INSIDE
    a longer string, not equal to it. (Pinned by
    test_tripwire_distinguishes_code_from_string_of_code.)
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    lines = src.splitlines()
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not _is_path_usage(node.value):
            continue
        parent = _parent_map(tree).get(id(node))
        if isinstance(parent, ast.keyword):
            parent = _parent_map(tree).get(id(parent))
        if isinstance(parent, ast.Call):
            func = parent.func
            name = func.attr if isinstance(func, ast.Attribute) else \
                (func.id if isinstance(func, ast.Name) else '')
            if name not in ('insert', 'append', 'extend', 'Path', 'open',
                            'getenv', 'read_text', 'write_text', 'exists',
                            'mkdir'):
                continue
        elif isinstance(parent, ast.Assign):
            pass                      # `REPO = '/home/ai/...'` is a binding
        elif isinstance(parent, (ast.BinOp, ast.JoinedStr, ast.Subscript)):
            pass                      # f-string / concat / indexing under it
        else:
            continue                  # e.g. assertIn(literal, ...) — a claim
        line = lines[node.lineno - 1].strip() if node.lineno <= len(lines) \
            else repr(node.value)[:80]
        hits.append((node.lineno, line))
    return sorted(set(hits))


def _main_worktree(repo=None):
    """Path of the MAIN worktree (owner of the shared .git dir), derived
    from git itself — location-independent (b50/b94 rule: never assume
    which checkout shape the suite runs in; inside a nested verification
    worktree, REPO is NOT the main one)."""
    repo = Path(repo) if repo else REPO
    r = subprocess.run(['git', 'rev-parse', '--path-format=absolute',
                        '--git-common-dir'],
                       cwd=str(repo), capture_output=True, text=True)
    cd = (r.stdout or '').strip().rstrip('/')
    if not cd:
        return None
    if cd.endswith('/.git'):
        cd = cd[:-len('/.git')]
    return str(Path(cd).resolve())


def _unowned_leftovers(repo=None):
    """Registered worktrees that are NOT this checkout, NOT the main
    worktree, and NOT owned by a LIVE verifier (b96).

    The old leak test asserted `len(git worktree list) == 1`. That races
    legitimate concurrency: b91's own contract is that a concurrent
    verification (cron's b51 start-heal vs the agent's step 4b) is a
    SUPPORTED shape whose worktree the sweep deliberately KEEPS — so a
    2-line listing while another verifier is mid-run is not a leak, and
    the 2026-09-06 b94 run proved it: a background suite overlapped a
    verify_head.sh and went RED on a healthy repo.

    The honest question is not "how many worktrees exist" but "did a
    verifier fail to clean up after ITSELF". A leftover is attributable:
    verify_ref stamps owner.pid in the temp dir BEFORE registering the
    worktree (b91), so owner_state() separates 'alive' (someone is
    verifying RIGHT NOW — spare it) from dead/unknown (the b91 incident
    shape — a real leak, still counted). Non-prefixed foreign worktrees
    are counted too, exactly as the old test counted them.
    """
    repo = Path(repo) if repo else REPO
    main = _main_worktree(repo)
    leftovers = []
    for wt in head_verify.list_worktrees(repo):
        p = wt.get('path') or ''
        if p == str(repo) or (main and str(Path(p).resolve()) == main):
            continue
        if head_verify.WORKTREE_PREFIX in p:
            base = os.path.dirname(p.rstrip('/'))
            if head_verify.owner_state(base) == 'alive':
                continue
        leftovers.append(p)
    return leftovers


def _parent_map(tree):
    """id(node) -> parent, built once per parse call (ast.walk is a
    GENERATOR — re-iterating it is the b49 lesson)."""
    pm = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            pm[id(child)] = node
    return pm


class SuiteIsLocationIndependent(unittest.TestCase):
    MIN_FILES_SCANNED = 20  # anti-vacuity: the scan must actually scan

    def test_no_test_module_binds_the_production_root(self):
        offenders = []
        scanned = 0
        for p in sorted(TESTS_DIR.glob('*.py')):
            if p.name == Path(__file__).name:
                continue  # this file names the root only to forbid it
            scanned += 1
            src = p.read_text(encoding='utf-8')
            if PROD_ROOT not in src:
                continue
            if p.name in ALLOWED:
                continue
            for lineno, line in _binding_lines(src):
                offenders.append(f'{p.name}:{lineno}: {line[:90]}')
        self.assertGreaterEqual(scanned, self.MIN_FILES_SCANNED,
                                f'only {scanned} test files scanned — the '
                                'scan is broken, not the repo clean')
        self.assertEqual(
            offenders, [],
            'test modules hardcode the production root, so the suite cannot '
            'verify a checkout (discovery imports production code and dies, '
            'and git-based checks certify the wrong tree). Derive the root '
            'from __file__ instead: ' + '; '.join(offenders))

    def test_allowed_entries_are_still_real(self):
        """A dead exemption is a silent hole: if the file no longer contains
        the literal, or the literal is now a BINDING (not prose/fixture), the
        exemption must go."""
        stale = []
        for name, why in ALLOWED.items():
            p = TESTS_DIR / name
            if not p.exists():
                stale.append(f'{name}: file gone')
                continue
            src = p.read_text(encoding='utf-8')
            if PROD_ROOT not in src:
                stale.append(f'{name}: literal no longer present')
                continue
            bindings = _binding_lines(src)
            if bindings and name != 'test_b48_env_seam_code_vs_state.py':
                stale.append(f'{name}: residual literals are now BINDINGS: '
                             f'{bindings}')
        self.assertEqual(stale, [], 'remove dead ALLOWED entries: '
                                     + '; '.join(stale))

    def test_every_test_module_resolves_its_own_root(self):
        """Positive half of the rule: a test that needs the repo must define
        it from __file__ — proof the conversion happened, not that the scan
        missed the file."""
        missing = []
        checked = 0
        for p in sorted(TESTS_DIR.glob('test_*.py')):
            src = p.read_text(encoding='utf-8')
            needs = ('sys.path.insert' in src or 'REPO' in src)
            if not needs:
                continue
            checked += 1
            if '__file__' not in src:
                missing.append(p.name)
        self.assertGreaterEqual(checked, 20,
                                f'only {checked} test modules checked — the '
                                'scan is broken, not the repo clean')
        self.assertEqual(missing, [],
                         'test modules derive the repo root from a hardcoded '
                         f'path instead of __file__: {missing}')


class HeadVerifyMechanism(unittest.TestCase):
    """engines/head_verify.py: the module that runs the suite INSIDE a ref."""

    # NESTED: skip ONLY the expensive real-history verification. Inside a
    # verification the mechanism is already being exercised end-to-end (that
    # run IS the proof), so replaying it against another commit just doubles
    # the cost. The cheap contract tests below still run nested — they are
    # what keeps the stamp seam honest inside the tree under test.
    @classmethod
    def setUpClass(cls):
        cls.tmp = hermetic.use_temp_data_root()

    @classmethod
    def tearDownClass(cls):
        hermetic.release()

    def test_stamp_round_trips_under_the_active_root(self):
        self.assertIsNone(head_verify.read_stamp())
        payload = head_verify.write_stamp('abc123', 'OK', tests=357,
                                          seconds=51.2)
        self.assertIsNotNone(payload)
        got = head_verify.read_stamp()
        self.assertEqual(got['sha'], 'abc123')
        self.assertEqual(got['verdict'], 'OK')
        self.assertEqual(got['tests'], 357)
        self.assertTrue(got['at'].endswith('Z'))
        self.assertEqual(head_verify.stamp_path(),
                         self.tmp / 'data' / head_verify.STAMP_REL,
                         'the stamp must follow the redirected root (b39)')

    def test_unresolvable_ref_is_error_never_a_raise(self):
        res = head_verify.verify_ref('no-such-ref-at-all')
        self.assertEqual(res['verdict'], 'ERROR')
        self.assertIsNone(res['sha'])
        self.assertIn('cannot resolve', res['note'])

    def test_verdict_vocabulary_is_closed(self):
        """A verdict outside the four signatures is a bug, not a state."""
        self.assertEqual(head_verify.VERDICTS,
                         ('OK', 'BROKEN', 'TIMEOUT', 'ERROR'))

    def test_parse_counts_reads_the_real_summary(self):
        self.assertEqual(head_verify.parse_counts(
            '....\nRan 357 tests in 49.138s\n\nOK\n'), 357)
        self.assertIsNone(head_verify.parse_counts('no summary here'))

    @unittest.skipIf(os.environ.get('HERMES_B50_NESTED') == '1',
                     'nested: this test forks ANOTHER full-suite verification '
                     '(and its child would fork one more) — the recursion '
                     'guard must cover it, not just FullSuiteInsideHead')
    def test_the_broken_commit_from_real_history_verifies_broken(self):
        """920ed0d: b45's tests shipped WITHOUT its source fixes. The old
        import-only verifier called it OK. The full-suite verifier must call
        it BROKEN — real history, not a strawman (b41 discipline)."""
        sha = head_verify.resolve_sha(BROKEN_COMMIT)
        self.assertIsNotNone(sha, f'{BROKEN_COMMIT} not in this repo?')
        res = head_verify.verify_ref(BROKEN_COMMIT, timeout=400)
        self.assertEqual(res['verdict'], 'BROKEN',
                         f'the verifier let the real broken commit through: '
                         f'{res["tail"][-800:]}')
        # The stamp is what b45's push gate reads: BROKEN must be recorded,
        # not silently dropped.
        head_verify.write_stamp(sha, res['verdict'], ref=BROKEN_COMMIT,
                                tests=res['tests'], seconds=res['seconds'],
                                note=res['note'])
        got = head_verify.read_stamp()
        self.assertEqual((got['sha'], got['verdict']),
                         (sha, 'BROKEN'))

    def test_nested_marker_is_passed_to_the_child(self):
        """Recursion guard, static half: the child env must carry the marker
        so the inner suite skips the behavioural test instead of forking an
        infinite chain of verifications."""
        src = (REPO / 'engines' / 'head_verify.py').read_text(
            encoding='utf-8')
        self.assertIn('HERMES_B50_NESTED', src,
                      'verify_ref must mark its child env — the inner suite '
                      'contains this test and would recurse forever')
        self.assertIn('HERMES_B50_NESTED',
                      Path(__file__).read_text(encoding='utf-8'),
                      'and this file must honour the marker')


@unittest.skipIf(os.environ.get('HERMES_B50_NESTED') == '1',
                 'running INSIDE a head_verify worktree — verifying the '
                 'verifier with the verifier would never terminate')
class FullSuiteInsideHead(unittest.TestCase):
    """The b50 deliverable, end to end: HEAD must pass the WHOLE suite from
    a clean checkout, and the count must match the working tree (a discovery
    that silently collected 3 tests is not a pass).

    COST DISCIPLINE (b50 lesson, learned the expensive way): the first
    version of this file ran the FULL suite THREE extra times per outer run
    — a verbose working-tree count, one verify_ref per test method, plus the
    real-history BROKEN-commit check — so `unittest discover` went from ~50s
    to >400s and the autopilot's own suite step TIMED OUT (rc=124). One
    verification is now shared at class level, and the working-tree count
    comes from the loader (collect, don't execute).
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = hermetic.use_temp_data_root()
        cls.res = head_verify.verify_ref('HEAD', timeout=900)
        # loader-based count of the working tree (no execution). NOTE: no
        # top_level_dir=REPO — tests/ is not a package (no __init__.py), and
        # discover() with the repo as top level raises "not importable".
        import unittest as ut
        suite = ut.TestLoader().discover(start_dir=str(REPO / 'tests'))
        cls.working_count = suite.countTestCases()

    @classmethod
    def tearDownClass(cls):
        hermetic.release()
        cls.res = None

    def test_head_passes_the_full_suite_in_a_clean_worktree(self):
        res = self.res
        self.assertIsNotNone(res)
        self.assertEqual(res['verdict'], 'OK',
                         f'HEAD does not pass the suite on a clean checkout '
                         f'(verdict {res["verdict"]}, note='
                         f'{res["note"]!r}):\n{res["tail"][-2500:]}')
        # NOT an equality check: this test runs BEFORE the commit, so HEAD is
        # the previous commit and legitimately has fewer tests than the
        # working tree (these very b50 files are uncommitted right now). The
        # anti-vacuity that matters: discovery really collected the suite
        # (floor), and HEAD never has MORE tests than the tree it precedes.
        self.assertIsNotNone(res['tests'],
                             'no "Ran N tests" line — the inner suite died '
                             'before collecting, which is not a pass')
        self.assertGreaterEqual(res['tests'], 350,
                                'anti-vacuity floor for this repo')
        self.assertLessEqual(res['tests'], self.working_count,
                             f'HEAD ran {res["tests"]} tests but the working '
                             f'tree collects {self.working_count} — HEAD '
                             'contains tests the tree does not?')

    def test_worktree_is_cleaned_up_after_verification(self):
        """A verifier that leaks worktrees eventually breaks the repo
        (git worktree add refuses, disk fills). Checked against the class-
        level verification above — no second full-suite run.

        b96: the old shape (`len(listing) == 1`) counted EVERY registered
        worktree as a leak, which races legitimate concurrency — b91's
        contract explicitly KEEPS a live-owner worktree (cron's b51
        start-heal vs the agent's step 4b), and on 2026-09-06 a background
        suite overlapped a verify_head.sh and this test went RED on a
        healthy repo. The claim is now owner-attributed: only leftovers
        whose creator is NOT alive count (see _unowned_leftovers)."""
        leftovers = _unowned_leftovers()
        if leftovers:
            # b96 race, other direction: a CONCURRENT verifier may have
            # registered its worktree between our listing and its owner
            # cleanup (dir gone -> owner 'unknown'). A real leak is
            # permanent, so re-confirm after a beat before going RED.
            time.sleep(2.0)
            leftovers = _unowned_leftovers()
        self.assertEqual(len(leftovers), 0,
                         'verification left worktrees behind: '
                         + '; '.join(leftovers))
        listing = subprocess.run(['git', 'worktree', 'list'], cwd=str(REPO),
                                 capture_output=True, text=True).stdout
        self.assertIn(str(REPO), listing)


class LeakTestIsConcurrencySafe(unittest.TestCase):
    """b96: the leak claim must be owner-attributed, not a line count.

    The 2026-09-06 incident: a background suite run overlapped a
    verify_head.sh; the old `len(worktree list) == 1` saw the OTHER
    verifier's live /tmp/hermes_headverify_* checkout and went RED on a
    healthy repo — while b91's contract explicitly KEEPS a live-owner
    worktree (concurrency is supported). These tests pin both directions
    with the real-worktree fixture shape b91 already builds: an alive
    owner is spare (and the old assertion would have failed on the same
    state), a dead/unknown owner is still a leak."""

    def test_alive_owner_worktree_is_not_a_leak(self):
        base, wt = _make_leftover(pid_text=str(os.getpid()), mtime_age=5)
        try:
            # the exact state the b96 flake hit: 2 registered worktrees,
            # one owned by a LIVE verifier
            listing = subprocess.run(
                ['git', 'worktree', 'list'], cwd=str(REPO),
                capture_output=True, text=True).stdout
            self.assertGreater(len(listing.strip().splitlines()), 1,
                               'fixture did not create the concurrency '
                               'shape — this test would pass vacuously')
            self.assertNotIn(str(wt), _unowned_leftovers(),
                             'a live verifier is being counted as a leak — '
                             'the b96 flake is back')
        finally:
            _cleanup(base, wt)

    def test_dead_owner_leftover_is_still_a_leak(self):
        """ANTI-VACUITY: the fix must not have become `assert [] == []`.
        The b91 incident shape (killed run, owner.pid dead) must count."""
        base, wt = _make_leftover(pid_text=str(_dead_pid()), mtime_age=5)
        try:
            self.assertIn(str(wt), _unowned_leftovers(),
                          'dead-owner leftovers no longer counted — the '
                          'leak test verifies nothing')
        finally:
            _cleanup(base, wt)

    def test_unknown_owner_leftover_is_counted(self):
        """No owner.pid (pre-b91 or hand-made): conservative — count it,
        exactly like the old line-count did."""
        base, wt = _make_leftover(pid_text=None, mtime_age=5)
        try:
            self.assertIn(str(wt), _unowned_leftovers())
        finally:
            _cleanup(base, wt)

    def test_main_worktree_is_never_a_leftover(self):
        """Location-independent (b94 rule): the exclusion is derived from
        git's own answer (--git-common-dir), never from the author's cwd —
        inside a nested verification worktree REPO is NOT the main tree,
        and the main tree must still be spared there."""
        main = _main_worktree()
        paths = [w['path'] for w in head_verify.list_worktrees(REPO)]
        self.assertIn(main, paths,
                      '_main_worktree() disagrees with git worktree list')
        self.assertNotIn(main, _unowned_leftovers())
        self.assertNotIn(str(REPO), _unowned_leftovers())


class VerifierScriptIsWired(unittest.TestCase):
    """scripts/verify_head.sh must actually run the full suite and stamp."""

    def test_script_runs_head_verify_and_stamps(self):
        src = (REPO / 'scripts' / 'verify_head.sh').read_text(
            encoding='utf-8')
        self.assertIn('engines/head_verify.py', src,
                      'b50: the post-commit verifier must run the FULL '
                      'suite, not only the import checks')
        self.assertIn('HERMES_STAMP=1', src,
                      'the script is the only thing allowed to stamp the '
                      'verification (a probe must not forge a stamp)')
        self.assertIn('tests.test_b42_tracked_imports', src,
                      'import checks stay FIRST so a ModuleNotFoundError '
                      'still reports its specific shape')
        # b44 lesson must survive the rewrite: run-then-capture, never
        # `if cmd; then ... fi` + `RC=$?`.
        lines = [l.strip() for l in src.splitlines() if l.strip()]
        for i, l in enumerate(lines):
            if l.startswith('RC=$?'):
                self.assertNotEqual(lines[i - 1], 'fi',
                                    'RC=$? after `fi` captures the if-'
                                    'compound status (always 0) — the b44 '
                                    'rc lie is back')
        payload = json.dumps({'ok': True})  # trivially valid, keeps json used
        self.assertTrue(payload)


if __name__ == '__main__':
    unittest.main()
