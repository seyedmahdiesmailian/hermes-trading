"""b94 — LOCATION-DEPENDENT TEST TRIPWIRE.

INCIDENT (b91b, 2026-09-06): the b91 parse test asserted
`self.assertFalse(main['detached'])` about the checkout it runs in. That is
TRUE in the main worktree and FALSE inside b50's nested detached verification
worktree — so the freshly harvested HEAD was stamped BROKEN by verify_head.sh
and only the push gate's age window saved cron. The test inspected git state
but compared git's answer to an assumption imported from the AUTHOR's working
directory.

RULE (the backlog wording): any test that inspects git state must assert
against git's OWN answer for the current checkout (symbolic-ref,
rev-parse --git-common-dir, a list_worktrees entry for this very tree), never
against a property assumed from where the test was written — b50 guarantees
the suite runs in at least TWO different checkout shapes (attached main tree,
detached verifier worktree), so an assumed shape is a coin flip.

This file implements the rule as a structure: an AST scan over every
tests/*.py that flags assertion shapes where a git-CHECKOUT-STATE value
(detached / bare / gitdir / commondir keys of a parsed `git worktree list
--porcelain`, or the result of a subprocess probe that asks git about this
checkout) is compared to a hardcoded literal, or truth-asserted bare. The
scan is pinned against the REAL historical offender (commit 937e82f's copy of
test_b91_stale_worktree.py — b41 discipline: real history, not a strawman)
and against synthetic fixtures for the other shapes, and the two known
git-state test files (b50, b91) are audited by name.

DELIBERATE NON-HITS (pinned by tests so the scan stays honest in BOTH
directions):
  * `assertEqual(main['detached'], _checkout_is_detached())` — state key vs
    git's own live answer: the FIXED shape, exactly what the rule asks for.
  * `assertEqual(len(listing.splitlines()), 1)` — a DERIVED claim about the
    SIZE of a worktree listing, not about the checkout's own state; b50's
    leak test uses this shape legitimately.
  * `assertEqual(main['head'], _sha())` — 'head' is not in the state-key
    vocabulary (it is a content claim, and both sides are live probes).
"""
from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO / 'tests'

# ---------------------------------------------------------------------------
# The vocabulary of "git checkout state" — the properties that DIFFER
# between the two checkout shapes b50 guarantees (main worktree vs detached
# verifier worktree). Deliberately narrow: 'head' is NOT here because a sha
# comparison is a content claim, not a shape claim.
GIT_STATE_KEYS = {'detached', 'bare', 'is_bare', 'isbare', 'gitdir',
                  'git_dir', 'commondir', 'common_dir'}

# Words that mark a subprocess call as asking git about THIS checkout's
# state (as opposed to `git show <sha>`, which is content).
GIT_STATE_WORDS = ('symbolic-ref', '--git-dir', '--git-common-dir',
                   '--is-bare-repository', 'worktree')

# Known live-probe functions (module-level helpers that return checkout
# state). list_worktrees is head_verify's parser; anything that WRAPS a
# state-bearing git call is traced automatically (see scan()).
PROBE_FUNCS = {'list_worktrees'}

# subprocess-ish runners whose args we inspect for GIT_STATE_WORDS.
GIT_RUNNER_NAMES = {'run', 'check_output', 'call', 'Popen', '_git', 'g',
                    'git'}

BOOL_ASSERTS = {'assertTrue', 'assertFalse'}
PAIR_ASSERTS = {'assertEqual', 'assertNotEqual'}

# The real historical offender: HEAD before the b91b fix. Its copy of the
# b91 test contains `assertFalse(main['detached'])` — the exact line that
# made verify_head.sh stamp a good HEAD BROKEN.
BROKEN_COMMIT = '937e82f'
BROKEN_FILE = 'tests/test_b91_stale_worktree.py'


def _fname(func):
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ''


def _call_words(node):
    """All string constants inside a Call, joined — good enough to spot
    ['git', 'symbolic-ref', ...] style argv lists."""
    return ' '.join(c.value for c in ast.walk(node)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str))


def _is_state_call(node):
    """A Call that asks git (or head_verify's parser) about THIS checkout."""
    if not isinstance(node, ast.Call):
        return False
    name = _fname(node.func)
    if name in PROBE_FUNCS:
        return True
    if name in GIT_RUNNER_NAMES and any(
            w in _call_words(node) for w in GIT_STATE_WORDS):
        return True
    return False


def _scalar(c):
    return (isinstance(c, ast.Constant)
            and (c.value is None or isinstance(c.value, (bool, int, float,
                                                         str, bytes))))


def _state_subscript(node):
    """x['detached'] / x['bare'] ... — a read of a git-state key."""
    return (isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value in GIT_STATE_KEYS)


def _direct_probe(node, names):
    """The expression IS a probe result: a bare traced Name or a direct
    call of a traced function. A probe buried inside len()/split() is a
    DERIVED claim, a different (legitimate) shape — not matched here."""
    if isinstance(node, ast.Name) and node.id in names:
        return True
    if isinstance(node, ast.Call) and _fname(node.func) in names:
        return True
    return False


def scan(src: str):
    """Return [(lineno, why, line)] for location-dependent git-state
    assertions in the given test-module source."""
    tree = ast.parse(src)
    lines = src.splitlines()

    # Pass 1: trace probe names — variables assigned from state calls, and
    # helper functions whose body makes a state call.
    probes = set(PROBE_FUNCS)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_state_call(node.value):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    probes.add(t.id)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if _is_state_call(sub):
                    probes.add(node.name)
                    break

    # Pass 2: assertion shapes that hardcode the answer about the checkout.
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _fname(node.func)
        if name not in BOOL_ASSERTS | PAIR_ASSERTS:
            continue
        args = node.args[:2]
        bad = why = ''
        if name in BOOL_ASSERTS and args and _state_subscript(args[0]):
            bad, why = True, ('bare truth assert on a git-state key: the '
                              'expected answer depends on WHICH checkout '
                              'the suite runs in')
        elif name in BOOL_ASSERTS and args and _direct_probe(args[0], probes):
            bad, why = True, ('bare truth assert on a live probe: assertTrue'
                              '(probe()) hardcodes the answer the probe '
                              'exists to discover')
        elif len(args) == 2:
            a, b = args
            if _state_subscript(a) and _scalar(b):
                bad, why = True, 'git-state key compared to a literal'
            elif _state_subscript(b) and _scalar(a):
                bad, why = True, 'literal compared to a git-state key'
            elif _direct_probe(a, probes) and _scalar(b):
                bad, why = True, 'live probe result compared to a literal'
            elif _direct_probe(b, probes) and _scalar(a):
                bad, why = True, 'literal compared to a live probe result'
        if bad:
            ln = node.lineno
            hits.append((ln, why, lines[ln - 1].strip()[:110]))

    # Plain `assert x['detached']` / `assert probe()` statements carry the
    # same disease as self.assert* and must not slip through.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) and node.test is not None:
            t = node.test
            if _state_subscript(t) or _direct_probe(t, probes):
                ln = node.lineno
                hits.append((ln, 'bare assert on git state',
                             lines[ln - 1].strip()[:110]))
    return sorted(set(hits))


class TripwireOnCurrentSuite(unittest.TestCase):
    MIN_FILES_SCANNED = 60  # anti-vacuity: the scan must actually scan

    def test_no_test_module_assumes_the_checkout_shape(self):
        offenders = []
        scanned = 0
        for p in sorted(TESTS_DIR.glob('*.py')):
            if p.name == Path(__file__).name:
                continue  # this file names the bad shapes as fixtures
            scanned += 1
            src = p.read_text(encoding='utf-8')
            try:
                hits = scan(src)
            except SyntaxError as e:
                self.fail(f'{p.name} does not parse: {e}')
            for ln, why, line in hits:
                offenders.append(f'{p.name}:{ln}: {why} :: {line}')
        self.assertGreaterEqual(scanned, self.MIN_FILES_SCANNED,
                                f'only {scanned} test files scanned — the '
                                'scan is broken, not the repo clean')
        self.assertEqual(
            offenders, [],
            'location-dependent git-state assertions (b94): assert against '
            "git's OWN answer for the current checkout (symbolic-ref, "
            'rev-parse --git-common-dir, this tree\'s list_worktrees entry), '
            'never a literal assumed from the author\'s working directory — '
            'b50 runs the suite in at least TWO checkout shapes. '
            + '; '.join(offenders))

    def test_the_two_known_git_state_files_are_audited_by_name(self):
        """The backlog asked for an explicit audit of the existing
        worktree tests (b50, b91), not just a repo-wide sweep: if someone
        refactors either back into the bad shape, the failure must name
        the file AND the rule."""
        for name in ('test_b50_suite_is_location_independent.py',
                     'test_b91_stale_worktree.py'):
            p = TESTS_DIR / name
            self.assertTrue(p.exists(), f'{name} vanished — update this '
                                        'audit (b41 dead-exemption rule)')
            hits = scan(p.read_text(encoding='utf-8'))
            self.assertEqual(hits, [], f'{name} regressed into '
                                       'location-dependent assertions: '
                                       + '; '.join(f'{ln}:{w}' for ln, w, _
                                                   in hits))


class ScanIsHonest(unittest.TestCase):
    """Both directions: catches the real shapes, spares the legitimate ones."""

    def test_catches_the_real_historical_offender(self):
        """937e82f's b91 test — the line that stamped a good HEAD BROKEN.
        Read from git history (b41 discipline: real history, not a
        strawman). Works in ANY checkout shape: worktrees share the object
        store, so `git show` answers identically in main and detached."""
        r = subprocess.run(['git', 'show', f'{BROKEN_COMMIT}:{BROKEN_FILE}'],
                           cwd=str(REPO), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0,
                         f'{BROKEN_COMMIT} not reachable from this checkout: '
                         f'{r.stderr[:200]}')
        hits = scan(r.stdout)
        self.assertTrue(any("assertFalse(main['detached'])" in line
                            for _, _, line in hits),
                        'the tripwire is blind to the exact shape that '
                        'caused the b91b incident: ' + str(hits))

    def test_catches_synthetic_bad_shapes(self):
        cases = {
            "self.assertFalse(main['detached'])": 'bare truth assert',
            "self.assertTrue(info['bare'])": 'bare truth assert',
            "self.assertEqual(main['detached'], False)": 'compared to a literal',
            "self.assertEqual(wt['gitdir'], '/x/.git')": 'compared to a literal',
            "self.assertEqual(_checkout_is_detached(), True)": 'probe result compared',
            "self.assertTrue(_checkout_is_detached())": 'bare truth assert on a live probe',
            "assert main['detached']": 'bare assert on git state',
            "assert _checkout_is_detached()": 'bare assert on git state',
        }
        for stmt, expect in cases.items():
            src = ('class T(unittest.TestCase):\n'
                   '    def _checkout_is_detached():\n'
                   "        r = subprocess.run(['git', 'symbolic-ref', '-q', "
                   "'HEAD'], cwd=str(REPO))\n"
                   '        return r.returncode != 0\n'
                   '    def test_x(self):\n'
                   '        wts = list_worktrees(REPO)\n'
                   '        main = wts[0]\n'
                   '        info = wts[0]\n'
                   '        wt = wts[0]\n'
                   f'        {stmt}\n')
            hits = scan(src)
            self.assertTrue(any(expect in why for _, why, _ in hits),
                            f'scan missed {stmt!r} ({expect}): {hits}')

    def test_spares_the_fixed_and_derived_shapes(self):
        good = ('class T(unittest.TestCase):\n'
                '    def _checkout_is_detached():\n'
                "        r = subprocess.run(['git', 'symbolic-ref', '-q', "
                "'HEAD'], cwd=str(REPO))\n"
                '        return r.returncode != 0\n'
                '    def test_x(self):\n'
                '        wts = list_worktrees(REPO)\n'
                '        main = wts[0]\n'
                "        self.assertEqual(main['detached'], "
                '_checkout_is_detached())\n'
                "        listing = subprocess.run(['git', 'worktree', "
                "'list'], capture_output=True).stdout\n"
                '        self.assertEqual(len(listing.splitlines()), 1)\n'
                "        self.assertEqual(main['head'], _sha())\n")
        self.assertEqual(scan(good), [],
                         'the scan flags the shapes the rule EXPLICITLY '
                         'allows — it will fire on correct code')

    def test_current_b91_file_is_the_fixed_shape(self):
        """Positive control for the historical test above: the SAME file at
        HEAD must now be clean (the b91b fix asserted against git itself)."""
        src = (TESTS_DIR / 'test_b91_stale_worktree.py').read_text(
            encoding='utf-8')
        self.assertIn('symbolic-ref', src,
                      'the b91b live-probe fix is gone from the file')
        self.assertEqual(scan(src), [])


if __name__ == '__main__':
    unittest.main()
