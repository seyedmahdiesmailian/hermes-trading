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

b95 (2026-09-06): the trace is NOT single-module any more. Cross-test imports
are real in this repo (b50 sys.path-inserts tests/, test_b37/b64/b66/b92 all
import helpers from sibling test modules), so a probe can arrive from the
module next door: `from test_b91_stale_worktree import _checkout_is_detached`
followed by `assertFalse(_checkout_is_detached())` used to slip past, because
the imported name is not in the LOCAL probes set. scan() now seeds the set
two ways — (1) any imported name matching the checkout-state vocabulary, and
(2) any imported name that the SIBLING module's own traced set contains
(resolved through an injectable loader, cycle-guarded).

b97 (2026-09-06): the sibling resolution only walked modules named test_*
inside tests/. A checkout-state probe with a NON-vocabulary name living in a
shared helper (tests/hermetic.py, a future tests/_gitutil.py, or a scripts/
or engines/ module) and imported into a test slipped past BOTH seeds. The
loader now resolves ANY dotted module name the way Python would from the
paths the suite actually sys.path-inserts (tests/, repo root, scripts/), and
_imported_probe_names walks every ImportFrom/Import through it — the
vocabulary seed stays as the fallback for unresolvable sources. To keep the
widening from seeding a production module's LOCAL variable names (head_verify
traces 'r', 'add', 'rm' inside its own functions) into a consumer's probes
set, only names the module EXPOSES at its top level are imported
(exported_probes).

b99 (2026-09-06): two siblings of the same disease, both measured FREE
(zero offenders in the whole suite before shipping, per the backlog's own
measurement):
  (1) EMPTY-CONTAINER literals. _scalar() accepted only None/bool/int/float/
      str/bytes, so `assertEqual(list_worktrees(REPO), [])` — hardcoding
      "no worktrees" as the answer a live probe exists to discover — slipped
      past while `assertFalse(probe())` was flagged. b96's OLD leak test
      asserted a COUNT of the shared listing; the empty-container sibling is
      the same disease. _hardcoded_answer() now covers [] () {} set()
      frozenset() alongside the scalars.
  (2) the PLAIN-assert comparison. The bare-assert pass caught
      `assert probe()` but not `assert probe() == []` / `assert x['detached']
      == False`, even though the self.assert* path catches both forms — an
      asymmetry, not a policy. Plain `assert <probe|state-key> == <answer>`
      (Eq/NotEq only) is now flagged with the same predicate.
      Derived claims stay spared on BOTH paths: `assert len(wts) == 1` is a
      SIZE claim (b50/b96 territory), not a shape claim.

b100 (2026-09-06): the IDENTITY family on the self.assert* path — the
  widening b99 measured free and filed rather than shipping silently.
  `assertIs(probe(), False)` hardcodes the answer through `is` exactly as
  `assertEqual(probe(), False)` does through `==`, and
  `assertIsNone(probe())`/`assertIsNotNone(probe())` hardcode it by OMITTING
  it (None lives in the method name) — "the probe found nothing" is b99's
  empty-container claim in a different spelling. IDENTITY_ASSERTS joins the
  pass-2 filter; both operand orders are covered, mirroring assertEqual.
  The plain-assert `is`/`is not` sibling is deliberately NOT flipped here
  (b99 parked it as a spared pin; one widening per commit) — measured free
  and filed as b101, pinned by test_plain_assert_identity_stays_spared_pending_b101.

DELIBERATE NON-HITS (pinned by tests so the scan stays honest in BOTH
directions):
  * `assertEqual(main['detached'], _checkout_is_detached())` — state key vs
    git's own live answer: the FIXED shape, exactly what the rule asks for.
  * `assertEqual(len(listing.splitlines()), 1)` — a DERIVED claim about the
    SIZE of a worktree listing, not about the checkout's own state; b50's
    leak test uses this shape legitimately.
  * `assertEqual(main['head'], _sha())` — 'head' is not in the state-key
    vocabulary (it is a content claim, and both sides are live probes).
  * `assertIsNone(cfg.path)` / `assertIs(obj.attr, None)` (b100) — an
    identity claim about a NON-probe object: the scan binds probes by
    dataflow and imports, so unrelated identity asserts stay untouched.
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

# b95: name vocabulary for probe-shaped helpers. A name imported from
# ANOTHER module cannot be traced by dataflow here (the state call lives in
# that module), so an imported name that READS like a checkout-state probe
# is seeded into the probes set. Deliberately substring-matched: the repo's
# helpers are `_checkout_is_detached`, `_worktree_paths`, `_is_bare_repo`...
PROBE_NAME_WORDS = ('detach', 'bare', 'gitdir', 'git_dir', 'commondir',
                    'common_dir', 'worktree', 'work_tree', 'checkout',
                    'is_bare')

# subprocess-ish runners whose args we inspect for GIT_STATE_WORDS.
GIT_RUNNER_NAMES = {'run', 'check_output', 'call', 'Popen', '_git', 'g',
                    'git'}

BOOL_ASSERTS = {'assertTrue', 'assertFalse'}
PAIR_ASSERTS = {'assertEqual', 'assertNotEqual'}

# b100: the IDENTITY family of the same disease. `assertIs(probe(), False)`
# hardcodes the answer through `is` exactly as `assertEqual(probe(), False)`
# does through `==`, and `assertIsNone(probe())` hardcodes it by OMITTING it
# (None is implicit in the method name) — "the probe found nothing" is
# b99's empty-container claim spelled differently.
#
# Scope follows this file's own stated policy, which is STRICT, not
# semantic: the scan flags any assertion that compares a checkout-state
# value to a hardcoded answer, in EITHER direction — PAIR_ASSERTS already
# contains assertNotEqual, so `assertNotEqual(probe(), None)` has been an
# offender since b94. The identity family is the same claim through `is`,
# so all four methods are in: assertIs/assertIsNot (answer in arg 2) and
# assertIsNone/assertIsNotNone (answer implicit). Dropping the negative
# forms would leave the tripwire blind to `assertIsNotNone(probe())` while
# it still catches its `!= None` twin — the exact asymmetry b99 shipped the
# plain-assert comparison to close.
# All four were measured FREE (zero offenders over all 73 test files).
IDENTITY_PAIR_ASSERTS = {'assertIs', 'assertIsNot'}
IDENTITY_UNARY_ASSERTS = {'assertIsNone', 'assertIsNotNone'}
IDENTITY_ASSERTS = IDENTITY_PAIR_ASSERTS | IDENTITY_UNARY_ASSERTS

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


# b99: the empty-container siblings of the scalar answers. `set()`/
# `frozenset()` are CALLS in the AST, not Constants, so they need their own
# shape check; a non-empty container is a DERIVED/structural claim (b96's
# owner-attributed leftovers list compares against a built fixture) and is
# deliberately NOT in here — see _hardcoded_answer.
EMPTY_CONTAINER_CALLS = {'set', 'frozenset'}


def _empty_container(c):
    if isinstance(c, (ast.List, ast.Tuple, ast.Set)) and not c.elts:
        return True
    if isinstance(c, ast.Dict) and not c.keys:
        return True
    return (isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
            and c.func.id in EMPTY_CONTAINER_CALLS
            and not c.args and not c.keywords)


def _hardcoded_answer(c):
    """b99: is this operand a HARDCODED answer to a checkout-state question?
    Scalars (True/False/'/x/.git'/None) plus the empty containers [] () {}
    set() frozenset() — 'no worktrees'/'no output' is just as much an
    assumed answer as 'not detached', and it is the shape a live probe
    exists to discover."""
    return _scalar(c) or _empty_container(c)


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


def _probe_shaped(name: str) -> bool:
    """b95: does an IMPORTED name read like a checkout-state probe? The
    state call lives in the sibling module, so local dataflow cannot see it
    and the name itself is the only evidence. ALL-CAPS names are skipped:
    they are constants (paths, shas), not probes."""
    if name.isupper() or name.startswith('__'):
        return False
    low = name.lower()
    return any(w in low for w in PROBE_NAME_WORDS)


def _trace_local_probes(tree) -> set:
    """Pass 1 of the old single-module scan: variables assigned from state
    calls, and helper functions whose body makes a state call."""
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
    return probes


# b97: the roots the suite actually puts on sys.path (every test module does
# sys.path.insert for REPO, most also for REPO/tests, b47-style ones for
# REPO/scripts). A helper imported by a test can only live on one of these.
# (b97 also retired b95's tests/-only _default_loader: the widened resolver
# below is a superset of it, and dead helpers are exactly what this repo's
# audits remove.)
MODULE_ROOTS = (TESTS_DIR, REPO, REPO / 'scripts')


def resolve_src(mod_name: str):
    """b97: resolve ANY dotted module name the way Python would from
    MODULE_ROOTS (tests/, repo root, scripts/). Returns None when nothing
    there can answer (stdlib, third-party, moved module) — the vocabulary
    seed then covers the name as the unresolvable-source fallback."""
    parts = mod_name.split('.')
    for root in MODULE_ROOTS:
        try:
            cand = root.joinpath(*parts).with_suffix('.py')
            if cand.is_file():
                return cand.read_text(encoding='utf-8')
            pkg = root.joinpath(*parts) / '__init__.py'
            if pkg.is_file():
                return pkg.read_text(encoding='utf-8')
        except OSError:
            continue
    return None


def _top_level_names(tree) -> set:
    """Names an `import *`/`from m import name` can actually bind: module
    level defs, assignments, and imported aliases."""
    out = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                if a.name != '*':
                    out.add(a.asname or a.name)
    return out


def _module_src(mod_name: str, loader):
    """Source of a module through `loader`, memoized ON the loader object.
    The b97 widening walks the whole import graph for every test file, and
    the same production module (hermes_runtime, head_verify...) is reached
    thousands of times; without this the repo-wide sweep costs ~60s of
    re-reads and re-parses. Keying the cache to the loader object (not to a
    global name table) keeps an injected test loader from ever sharing an
    entry with the real resolver."""
    cache = getattr(loader, '_b97_src_cache', None)
    if cache is None:
        cache = {}
        try:
            loader._b97_src_cache = cache
        except (AttributeError, TypeError):
            pass
    if mod_name in cache:
        return cache[mod_name]
    src = loader(mod_name)
    cache[mod_name] = src
    return src


def _module_tree(mod_name: str, loader):
    """(src, parsed tree or None) — parse once per module per loader."""
    src = _module_src(mod_name, loader)
    if src is None:
        return None, None
    cache = getattr(loader, '_b97_tree_cache', None)
    if cache is None:
        cache = {}
        try:
            loader._b97_tree_cache = cache
        except (AttributeError, TypeError):
            pass
    if mod_name not in cache:
        try:
            cache[mod_name] = ast.parse(src)
        except SyntaxError:
            cache[mod_name] = None
    return src, cache[mod_name]


def exported_probes(mod_name: str, loader, seen=frozenset()) -> set:
    """b97: the probes a module EXPOSES — its traced set intersected with
    its top-level names. Without the filter, widening the loader would seed
    a consumer with a production module's LOCAL variables (head_verify's
    functions trace 'r', 'add', 'rm' as state-call results): a test that
    happens to reuse such a common name would light up. Exposure is what an
    import can bind, so it is the honest boundary."""
    tree = _module_tree(mod_name, loader)[1]
    if tree is None:
        return set()
    return sibling_probes(mod_name, loader, seen) & _top_level_names(tree)


def sibling_probes(mod_name: str, loader, seen=frozenset()) -> set:
    """The full traced-probe set of a sibling module, computed with the SAME
    rules (local dataflow + its own imports), cycle-guarded. Memoized on
    (loader, module, seen) — `seen` is part of the key because the cycle
    guard legitimately truncates the walk differently per call site."""
    if mod_name in seen:
        return set()
    cache = getattr(loader, '_b97_sib_cache', None)
    if cache is None:
        cache = {}
        try:
            loader._b97_sib_cache = cache
        except (AttributeError, TypeError):
            pass
    key = (mod_name, seen)
    if key in cache:
        return cache[key]
    tree = _module_tree(mod_name, loader)[1]
    if tree is None:
        probes = set()
    else:
        probes = _trace_local_probes(tree)
        probes |= _imported_probe_names(tree, loader, seen | {mod_name})
    if len(cache) < 100000:
        cache[key] = probes
    return probes


def _imported_probe_names(tree, loader, seen) -> set:
    """b95: probes that ARRIVE from another module. Two seeds:
    (1) any imported name matching the probe-shape vocabulary, and
    (2) any name imported from a module whose OWN traced set contains it
        (resolved recursively through `loader`).
    b97: seed (2) no longer requires a test_* name or the tests/ folder —
    ANY module resolvable on the suite's sys.path roots is walked, so a
    non-vocabulary probe in a shared helper (tests/hermetic.py, a future
    tests/_gitutil.py, engines/, scripts/) is caught at the import site."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            # b95: `import test_X as m` then `m._checkout_is_detached()` —
            # _fname() returns the attribute name, so seeding the sibling's
            # traced set is enough to catch the module-object shape too.
            for a in node.names:
                out |= exported_probes(a.name, loader, seen)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        mod = (node.module or '').lstrip('.')
        if not mod:
            continue  # `from . import x` — no resolvable module name
        for a in node.names:
            local = a.asname or a.name
            if local != '*' and _probe_shaped(local):
                out.add(local)
        sib = exported_probes(mod, loader, seen)
        for a in node.names:
            if a.name == '*':
                out |= sib
            elif a.name in sib:
                out.add(a.asname or a.name)
    return out


def scan(src: str, loader=None):
    """Return [(lineno, why, line)] for location-dependent git-state
    assertions in the given test-module source. `loader` resolves module
    names to source (b95/b97); defaults to the widened sys.path resolver."""
    if loader is None:
        loader = resolve_src
    tree = ast.parse(src)
    lines = src.splitlines()

    # Pass 1: trace probe names — local dataflow plus b95's cross-module
    # seeds (imported probe-shaped names and the siblings' own traced sets).
    probes = _trace_local_probes(tree) | _imported_probe_names(
        tree, loader, frozenset())

    # Pass 2: assertion shapes that hardcode the answer about the checkout.
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _fname(node.func)
        if name not in BOOL_ASSERTS | PAIR_ASSERTS | IDENTITY_ASSERTS:
            continue
        args = node.args[:2]
        bad = why = ''
        # b100: the identity family. assertIs/assertIsNot carry the answer in
        # their second arg exactly like assertEqual; assertIsNone/
        # assertIsNotNone carry it by OMITTING it (None is in the method
        # name), so they are UNARY probes of the same disease.
        if (name in IDENTITY_UNARY_ASSERTS and args
                and (_state_subscript(args[0])
                     or _direct_probe(args[0], probes))):
            bad, why = True, ('identity assert with an implicit None answer '
                              'on git state: assertIsNone(probe()) hardcodes '
                              'what the probe exists to discover')
        elif (len(args) == 2 and name in IDENTITY_PAIR_ASSERTS
              and (((_state_subscript(args[0]) or _direct_probe(args[0], probes))
                    and _hardcoded_answer(args[1]))
                   or (((_state_subscript(args[1])
                         or _direct_probe(args[1], probes))
                        and _hardcoded_answer(args[0]))))):
            bad, why = True, ('git-state probe compared by identity to a '
                              'literal')
        elif name in BOOL_ASSERTS and args and _state_subscript(args[0]):
            bad, why = True, ('bare truth assert on a git-state key: the '
                              'expected answer depends on WHICH checkout '
                              'the suite runs in')
        elif name in BOOL_ASSERTS and args and _direct_probe(args[0], probes):
            bad, why = True, ('bare truth assert on a live probe: assertTrue'
                              '(probe()) hardcodes the answer the probe '
                              'exists to discover')
        elif len(args) == 2:
            a, b = args
            if _state_subscript(a) and _hardcoded_answer(b):
                bad, why = True, 'git-state key compared to a literal'
            elif _state_subscript(b) and _hardcoded_answer(a):
                bad, why = True, 'literal compared to a git-state key'
            elif _direct_probe(a, probes) and _hardcoded_answer(b):
                bad, why = True, 'live probe result compared to a literal'
            elif _direct_probe(b, probes) and _hardcoded_answer(a):
                bad, why = True, 'literal compared to a live probe result'
        if bad:
            ln = node.lineno
            hits.append((ln, why, lines[ln - 1].strip()[:110]))

    # Plain `assert x['detached']` / `assert probe()` statements carry the
    # same disease as self.assert* and must not slip through.
    # b99: the COMPARISON form of the plain assert (`assert probe() == []`,
    # `assert main['detached'] == False`) is the same disease too — the old
    # pass caught only the bare-truthiness form, an asymmetry with the
    # self.assert* path which flags both. Eq/NotEq only there: `is`/`is not`
    # was the identity family, filed as b100 and widened in b100 below.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) and node.test is not None:
            t = node.test
            if _state_subscript(t) or _direct_probe(t, probes):
                ln = node.lineno
                hits.append((ln, 'bare assert on git state',
                             lines[ln - 1].strip()[:110]))
            elif (isinstance(t, ast.Compare) and len(t.ops) == 1
                    and isinstance(t.ops[0], (ast.Eq, ast.NotEq))):
                a, b = t.left, t.comparators[0]
                if ((_state_subscript(a) and _hardcoded_answer(b))
                        or (_state_subscript(b) and _hardcoded_answer(a))
                        or (_direct_probe(a, probes) and _hardcoded_answer(b))
                        or (_direct_probe(b, probes) and _hardcoded_answer(a))):
                    hits.append((node.lineno,
                                 'assert comparison hardcodes the probe '
                                 'answer',
                                 lines[node.lineno - 1].strip()[:110]))
            # b100 deliberately stops here on the plain-assert path. The
            # `is`/`is not` sibling (`assert main['detached'] is False`) is
            # the same disease and b99 parked it as a SPARED pin on purpose;
            # b100's scope is the self.assert* identity family named in the
            # backlog item. Flipping b99's pin in the same breath as shipping
            # a new family is the multi-widening-in-one-commit shape this
            # repo's audit history warns about -> filed as b101, measured
            # free, its own decision.
    return sorted(set(hits))


def disk_files():
    """Every tests/*.py except THIS file (it names the bad shapes as
    fixtures). Returns [(name, src)] — read once, reused by the sweep."""
    out = []
    for p in sorted(TESTS_DIR.glob('*.py')):
        if p.name == Path(__file__).name:
            continue
        out.append((p.name, p.read_text(encoding='utf-8')))
    return out


def sweep_offenders(files, loader=None):
    """Run scan() over [(name, src)] and flatten to offender strings.
    Shared by the repo-wide test and b95's in-memory anti-vacuity probe —
    a synthetic offender is injected as a (name, src) PAIR, never written
    to tests/: two suite runs sharing one checkout would otherwise race on
    the temp file (the b96 flake class)."""
    offenders = []
    for name, src in files:
        try:
            hits = scan(src, loader=loader)
        except SyntaxError as e:
            offenders.append(f'{name}: SyntaxError: {e}')
            continue
        for ln, why, line in hits:
            offenders.append(f'{name}:{ln}: {why} :: {line}')
    return offenders


class TripwireOnCurrentSuite(unittest.TestCase):
    MIN_FILES_SCANNED = 60  # anti-vacuity: the scan must actually scan

    def test_no_test_module_assumes_the_checkout_shape(self):
        offenders = sweep_offenders(disk_files())
        scanned = len(disk_files())
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


class TestCrossModuleProbes(unittest.TestCase):
    """b95: the single-module trace was blind to a probe imported from a
    sibling test module — the exact shape this repo uses (b50 sys.path-
    inserts tests/; b37/b64/b66/b92 import sibling helpers). The scan must
    resolve `from test_X import probe` against X's OWN traced set, and must
    still spare legitimate cross-imports."""

    # sibling module: defines a real probe (state call in its body)
    SIB = ("def _checkout_is_detached():\n"
           "    r = subprocess.run(['git', 'symbolic-ref', '-q', 'HEAD'],\n"
           "                       cwd=str(REPO))\n"
           "    return r.returncode != 0\n"
           "def _sha(ref='HEAD'):\n"
           "    return subprocess.run(['git', 'rev-parse', ref]).stdout\n")
    # consumer module: imports the probe and hardcodes its answer
    OFFENDER = ("from test_sibling_fixture import _checkout_is_detached\n"
                'class T(unittest.TestCase):\n'
                '    def test_x(self):\n'
                '        self.assertFalse(_checkout_is_detached())\n')

    @staticmethod
    def _loader(mapping):
        return lambda name: mapping.get(name)

    def test_imported_sibling_probe_is_caught(self):
        loader = self._loader({'test_sibling_fixture': self.SIB})
        hits = scan(self.OFFENDER, loader=loader)
        self.assertTrue(any('probe' in why for _, why, _ in hits),
                        'cross-module probe slipped past the scan: ' + str(hits))

    def test_star_import_of_sibling_probe_is_caught(self):
        src = ("from test_sibling_fixture import *\n"
               'class T(unittest.TestCase):\n'
               '    def test_x(self):\n'
               '        self.assertTrue(_checkout_is_detached())\n')
        loader = self._loader({'test_sibling_fixture': self.SIB})
        hits = scan(src, loader=loader)
        self.assertTrue(hits, 'star-imported sibling probe not caught')

    def test_aliased_sibling_probe_is_caught(self):
        src = ("from test_sibling_fixture import _checkout_is_detached as det\n"
               'class T(unittest.TestCase):\n'
               '    def test_x(self):\n'
               "        self.assertEqual(det(), False)\n")
        loader = self._loader({'test_sibling_fixture': self.SIB})
        hits = scan(src, loader=loader)
        self.assertTrue(hits, 'aliased sibling probe not caught: ' + str(hits))

    def test_probe_shaped_import_name_is_caught_without_the_sibling(self):
        """Seed (1): the source of the sibling may be unresolvable (moved,
        renamed, outside tests/) — a name that READS like a checkout-state
        probe is still enough to flag hardcoding its answer."""
        src = ("from somewhere_else import is_detached\n"
               'class T(unittest.TestCase):\n'
               '    def test_x(self):\n'
               '        self.assertTrue(is_detached())\n')
        hits = scan(src, loader=self._loader({}))
        self.assertTrue(hits, 'probe-shaped import not caught: ' + str(hits))

    def test_legitimate_cross_import_is_spared(self):
        """The repo's real shapes: importing a Mock or a parser helper from
        a sibling must NOT turn every use into a hit."""
        src = ("from test_runtime_fallback_management import MockBridge\n"
               "from test_b52_env_names import _env_doc_values\n"
               'class T(unittest.TestCase):\n'
               '    def test_x(self):\n'
               '        self.assertTrue(MockBridge.ok)\n'
               '        self.assertEqual(len(_env_doc_values()), 3)\n')
        self.assertEqual(scan(src, loader=self._loader({})), [])

    def test_imported_state_key_dict_is_spared_when_derived(self):
        """ALL-CAPS imports are constants, not probes: `from x import
        GITDIR` used in a path join must not seed the probes set."""
        src = ("from test_sibling_fixture import MAIN_WORKTREE_PATH\n"
               'class T(unittest.TestCase):\n'
               '    def test_x(self):\n'
               '        self.assertTrue(MAIN_WORKTREE_PATH.exists())\n')
        self.assertEqual(scan(src, loader=self._loader({})), [])

    def test_module_object_probe_call_is_caught(self):
        """`import test_X as sib` then `sib._checkout_is_detached()` —
        _fname() sees the attribute, so the sibling's traced set catches it."""
        src = ("import test_sibling_fixture as sib\n"
               'class T(unittest.TestCase):\n'
               '    def test_x(self):\n'
               '        self.assertFalse(sib._checkout_is_detached())\n')
        loader = self._loader({'test_sibling_fixture': self.SIB})
        hits = scan(src, loader=loader)
        self.assertTrue(hits, 'module-object sibling probe not caught: '
                              + str(hits))

    def test_import_cycle_between_siblings_terminates(self):
        a = ("from test_b_fixture import probe_b\n"
             "def probe_a():\n"
             "    return probe_b()\n")
        b = ("from test_a_fixture import probe_a\n"
             "def probe_b():\n"
             "    return probe_a()\n")
        loader = self._loader({'test_a_fixture': a, 'test_b_fixture': b})
        # must not recurse forever and must not raise
        hits = scan(a, loader=loader)
        self.assertIsInstance(hits, list)

    def test_real_b91_sibling_resolves_under_the_default_loader(self):
        """The fixture above mirrors the REAL repo: b91's own traced set
        must contain _checkout_is_detached, so any future test that imports
        it and hardcodes the answer is caught by the repo-wide sweep.
        b97: the default loader is now the widened sys.path resolver — the
        sibling lives in tests/, which it must still find."""
        probes = sibling_probes('test_b91_stale_worktree', resolve_src)
        self.assertIn('_checkout_is_detached', probes)

    def test_repo_wide_sweep_uses_cross_module_resolution(self):
        """Anti-vacuity for b95 itself: the sweep that guards the repo must
        catch the offender shape end-to-end if it lands in tests/ — proven
        IN MEMORY (inject the (name, src) pair), never by writing a temp
        file into tests/ where a concurrent suite run would race on it."""
        files = disk_files() + [
            ('test_b95_zz_synthetic_offender.py', self.OFFENDER)]
        offenders = sweep_offenders(files)
        self.assertTrue(any('test_b95_zz_synthetic_offender' in o
                            for o in offenders),
                        'repo-wide sweep blind to the b95 shape: '
                        + '; '.join(offenders))
        # and the REAL repo is still clean under the exact same sweep
        self.assertEqual(sweep_offenders(disk_files()), [])


class TestNonTestHelperModules(unittest.TestCase):
    """b97: the residual blind spot of b95. Seed (2) used to walk only
    modules named test_* inside tests/. A checkout-state probe with a
    NON-vocabulary name that lives in a shared helper — tests/hermetic.py,
    a future tests/_gitutil.py, an engines/ or scripts/ module — and is
    imported into a test slipped past BOTH seeds: the name misses
    PROBE_NAME_WORDS and the module misses the test_* filter. The loader now
    resolves ANY module reachable from the suite's sys.path roots."""

    # a helper whose probe name carries NO vocabulary word at all
    GITUTIL = ("def _shape():\n"
               "    r = subprocess.run(['git', 'symbolic-ref', '-q', 'HEAD'],\n"
               "                       cwd=str(REPO))\n"
               "    return r.returncode != 0\n")

    @staticmethod
    def _loader(mapping):
        return lambda name: mapping.get(name)

    def test_non_vocabulary_probe_in_helper_module_is_caught(self):
        src = ("from _gitutil import _shape\n"
               'class T(unittest.TestCase):\n'
               '    def test_x(self):\n'
               '        self.assertFalse(_shape())\n')
        loader = self._loader({'_gitutil': self.GITUTIL})
        hits = scan(src, loader=loader)
        self.assertTrue(hits,
                        'b97 shape: helper probe with a non-vocabulary name '
                        'imported into a test still slips past: ' + str(hits))

    def test_helper_probe_survives_a_rename_via_as(self):
        src = ("from _gitutil import _shape as sh\n"
               'class T(unittest.TestCase):\n'
               '    def test_x(self):\n'
               '        self.assertTrue(sh())\n')
        loader = self._loader({'_gitutil': self.GITUTIL})
        self.assertTrue(scan(src, loader=loader),
                        'aliased helper probe not caught')

    def test_production_module_probe_is_caught_via_the_default_loader(self):
        """No injected loader: the DEFAULT resolution must reach engines/
        (the way the suite's own sys.path does) and flag hardcoding
        head_verify's parser's answer."""
        src = ("from engines.head_verify import list_worktrees\n"
               'class T(unittest.TestCase):\n'
               '    def test_x(self):\n'
               '        self.assertTrue(list_worktrees(REPO))\n')
        hits = scan(src)
        self.assertTrue(hits,
                        'default loader cannot see engines/ — the b97 '
                        'widening is decorative: ' + str(hits))

    def test_helper_locals_are_not_seeded_into_consumers(self):
        """Anti-false-positive for the widening: head_verify's functions
        trace 'r', 'add', 'rm' as state-call results LOCALLY. Those are not
        importable names, so they must never seed a consumer's probes set —
        otherwise every test that happens to use `r` for a subprocess
        result would light up."""
        exposed = exported_probes('engines.head_verify', resolve_src)
        self.assertIn('list_worktrees', exposed)
        for local in ('r', 'add', 'rm', 'pr'):
            self.assertNotIn(local, exposed,
                             f'{local} is a LOCAL of head_verify, not an '
                             'exported probe — seeding it would flag '
                             'unrelated tests')
        src = ("from engines import head_verify\n"
               'class T(unittest.TestCase):\n'
               '    def test_x(self):\n'
               "        r = subprocess.run(['ls'])\n"
               '        self.assertEqual(r.returncode, 0)\n')
        self.assertEqual(scan(src), [],
                         'a plain subprocess result named r flagged — the '
                         'export filter is broken')

    def test_unresolvable_helper_falls_back_to_the_vocabulary_seed(self):
        """A helper OUTSIDE the sys.path roots (moved, third-party) cannot
        be read — the name vocabulary stays as the fallback, exactly as
        b95 shipped it."""
        src = ("from third_party_git_thing import is_detached\n"
               'class T(unittest.TestCase):\n'
               '    def test_x(self):\n'
               '        self.assertTrue(is_detached())\n')
        self.assertTrue(scan(src),
                        'vocabulary fallback lost in the b97 widening')

    def test_repo_wide_sweep_stays_clean_under_the_widened_default(self):
        """The widened default loader must not flag ANYTHING in the current
        suite — if it does, the widening is too aggressive and this test is
        the tripwire on itself."""
        offenders = sweep_offenders(disk_files())  # default loader = resolve_src
        self.assertEqual(offenders, [],
                         'b97 widening flags existing correct code: '
                         + '; '.join(offenders))


class TestEmptyContainerAndPlainAssert(unittest.TestCase):
    """b99: the two siblings of the b94 disease, both measured FREE before
    shipping (zero offenders in the whole suite):
      (1) an EMPTY container literal as the hardcoded answer — `[] () {}
          set() frozenset()` say "no worktrees"/"no output" just as loudly
          as False says "not detached";
      (2) the plain-assert COMPARISON — `assert probe() == []` was caught on
          the self.assert* path but not on the bare-assert path."""

    HEAD = ('class T(unittest.TestCase):\n'
            '    def _checkout_is_detached():\n'
            "        r = subprocess.run(['git', 'symbolic-ref', '-q', "
            "'HEAD'], cwd=str(REPO))\n"
            '        return r.returncode != 0\n'
            '    def test_x(self):\n'
            '        wts = list_worktrees(REPO)\n'
            '        main = wts[0]\n')

    def _hits(self, stmt):
        return scan(self.HEAD + f'        {stmt}\n')

    def test_empty_container_answers_are_caught(self):
        for stmt in ("self.assertEqual(wts, [])",
                     "self.assertEqual(wts, ())",
                     "self.assertEqual(wts, set())",
                     "self.assertEqual(wts, frozenset())",
                     "self.assertEqual(wts, {})",
                     "self.assertEqual([], wts)",
                     "self.assertEqual(main['detached'], [])",
                     "self.assertEqual(_checkout_is_detached(), ())"):
            self.assertTrue(self._hits(stmt),
                            f'b99 shape still slips past the scan: {stmt}')

    def test_non_empty_containers_are_spared(self):
        """A populated literal is a STRUCTURAL/derived claim (b96 compares
        an owner-attributed leftovers LIST against a fixture it built), not
        an assumed answer about this checkout's shape."""
        for stmt in ("self.assertEqual(wts, [1])",
                     "self.assertEqual(wts, {'detached': True})",
                     "self.assertEqual(len(wts), 0)",
                     "self.assertEqual(sorted(wts), ['a'])"):
            self.assertEqual(self._hits(stmt), [],
                             f'the widening flags a non-answer: {stmt}')

    def test_plain_assert_comparison_is_caught(self):
        for stmt in ("assert wts == []",
                     "assert main['detached'] == False",
                     "assert _checkout_is_detached() == True",
                     "assert wts != []",
                     "assert main['gitdir'] == ()"):
            hits = self._hits(stmt)
            self.assertTrue(any('hardcodes' in why for _, why, _ in hits),
                            f'plain-assert comparison slipped past: {stmt} '
                            f'-> {hits}')

    def test_plain_assert_fixed_and_derived_shapes_are_spared(self):
        for stmt in ("assert main['detached'] == _checkout_is_detached()",
                     "assert len(wts) == 1",
                     "assert wts[0]['detached'] == _checkout_is_detached()",
                     "assert wts is not None",
                     "assert main['detached'] is False"):
            self.assertEqual(self._hits(stmt), [],
                             f'plain-assert widening hits a legal shape: '
                             f'{stmt}')

    def test_bare_assert_truthiness_still_caught(self):
        """The b94 original must not regress behind the b99 elif branch."""
        self.assertTrue(self._hits("assert main['detached']"))
        self.assertTrue(self._hits("assert _checkout_is_detached()"))

    def test_repo_wide_sweep_catches_the_b99_shape_end_to_end(self):
        """Anti-vacuity, in memory (b95 rule: never write a temp file into
        tests/ where a concurrent suite would race on it)."""
        offender = (self.HEAD + '        self.assertEqual(wts, [])\n')
        files = disk_files() + [
            ('test_b99_zz_synthetic_offender.py', offender)]
        offenders = sweep_offenders(files)
        self.assertTrue(any('test_b99_zz_synthetic_offender' in o
                            for o in offenders),
                        'repo-wide sweep blind to the b99 empty-container '
                        'shape: ' + '; '.join(offenders))
        self.assertEqual(sweep_offenders(disk_files()), [],
                         'the b99 widening flags existing correct code')


class TestIdentityAsserts(unittest.TestCase):
    """b100 — the IDENTITY sibling of the b94 disease, the widening b99
    measured free and deliberately filed instead of shipping silently.
    `self.assertIs(probe(), False)` hardcodes the answer through `is`
    exactly as `assertEqual(probe(), False)` does through `==`, and
    `self.assertIsNone(probe())` hardcodes it by OMITTING it — "the probe
    found nothing" is b99's empty-container claim in a different spelling.
    Both directions (probe first / literal first) are covered, mirroring
    the assertEqual path."""

    HEAD = TestEmptyContainerAndPlainAssert.HEAD

    def _hits(self, stmt):
        return scan(self.HEAD + f'        {stmt}\n')

    def test_identity_pair_asserts_are_caught(self):
        for stmt in ("self.assertIs(main['detached'], False)",
                     "self.assertIs(_checkout_is_detached(), True)",
                     "self.assertIsNot(main['bare'], True)",
                     "self.assertIs(wts, [])",
                     "self.assertIs(main['gitdir'], '/x')",
                     # literal-first direction, same as assertEqual's path
                     "self.assertIs(False, main['detached'])",
                     "self.assertIs(None, _checkout_is_detached())"):
            self.assertTrue(self._hits(stmt),
                            f'b100 identity shape still slips past: {stmt}')

    def test_implicit_none_identity_asserts_are_caught(self):
        """assertIsNone/assertIsNotNone carry the answer in the METHOD NAME,
        so they are unary probes of the same disease."""
        for stmt in ("self.assertIsNone(list_worktrees(REPO))",
                     "self.assertIsNone(wts)",
                     "self.assertIsNotNone(_checkout_is_detached())",
                     "self.assertIsNone(main['commondir'])"):
            self.assertTrue(self._hits(stmt),
                            f'implicit-None identity shape slipped: {stmt}')

    def test_identity_asserts_on_foreign_objects_are_spared(self):
        """The scan binds probes by dataflow/import — an identity assert on
        an attribute, a plain object, or two live probes is not a checkout
        state claim. `assertIsNone(cfg.path)` is the backlog's own spared
        shape."""
        for stmt in ("self.assertIs(obj.attr, None)",
                     "self.assertIsNone(cfg.path)",
                     "self.assertIs(wts[0], wts[1])",
                     "self.assertIsNotNone(m)",
                     "self.assertIs(main['detached'], "
                     "_checkout_is_detached())",
                     "self.assertIsNone(len(wts))"):
            self.assertEqual(self._hits(stmt), [],
                             f'identity widening hits a legal shape: {stmt}')

    def test_plain_assert_identity_stays_spared_pending_b101(self):
        """b99 parked `assert main['detached'] is False` in its SPARED list
        on purpose, and b100's scope is the self.assert* family the backlog
        names. Flipping the previous commit's pin inside this commit would
        be the multi-widening shape this repo warns about — the plain-assert
        identity sibling is measured free and filed as b101, its own
        decision. This test pins the boundary so b101 cannot be "forgotten"
        in either direction."""
        for stmt in ("assert main['detached'] is False",
                     "assert _checkout_is_detached() is True",
                     "assert wts is not None"):
            self.assertEqual(self._hits(stmt), [],
                             f'b100 crossed into the b101 scope: {stmt}')

    def test_repo_wide_sweep_catches_the_b100_shape_end_to_end(self):
        """Anti-vacuity, in memory (b95 rule)."""
        offender = (self.HEAD
                    + "        self.assertIs(main['detached'], False)\n")
        files = disk_files() + [
            ('test_b100_zz_synthetic_offender.py', offender)]
        offenders = sweep_offenders(files)
        self.assertTrue(any('test_b100_zz_synthetic_offender' in o
                            for o in offenders),
                        'repo-wide sweep blind to the b100 identity shape: '
                        + '; '.join(offenders))
        self.assertEqual(sweep_offenders(disk_files()), [],
                         'the b100 widening flags existing correct code')


if __name__ == '__main__':
    unittest.main()
