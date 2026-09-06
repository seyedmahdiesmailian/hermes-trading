"""b104 — SEMANTIC AUDITS NEED A REALITY-BINDING END-TO-END CHECK.

RULE (backlog, from b103): a tripwire whose predicate reads MEANING (prose,
naming, intent) cannot be validated by fixtures alone — a fixture only proves
the predicate fires on the shapes its author imagined. Every one of b103's
rules 4/5/6 was a shape the author had NOT imagined, found only when the
predicate was pointed at the repo's REAL prose and REAL history. So pair the
audit with a check that the FINDINGS RESOLVE TO REAL ENTITIES, assert the
scan is NOT VACUOUS on the same real data, and when a shared helper layer
DOCUMENTS N rules, cross-check the owner table against the rule count.

MEASURED AUDIT RESULT (2026-09-06, this file's first run over all .py prose
via prose_audit.sentences — 42 distinct cited test names): three PHANTOMS,
each a different failure shape, none visible to any fixture test:

  1. tests/test_b94_location_dependent_tripwire.py cited
     'pinned by test_plain_assert_identity_stays_spared' — the REAL pin is
     test_plain_assert_identity_stays_spared_pending_b101. A TRUNCATED
     citation reads as a satisfied b102 pin (pin_exists does substring
     matching) while the name it prints resolves to nothing. This is why
     resolution here is EXACT, never prefix: a prefix match is reported as
     truncation, not as a hit.
  2. tests/test_b50_suite_is_location_independent.py cited '(Pinned by
     test_tripwire_distinguishes_code_from_string_of_code.)' — no test with
     that name has EVER existed (git log -S finds nothing). The behaviour it
     claims to pin is real and lives in test_allowed_entries_are_still_real;
     the citation pointed at a phantom.
  3. tests/test_integration.py said manage/enter autonomy is 'checked in
     test_cycle.py' — no such file exists; the real assertions
     (will_execute_now True) live in test_broker_clock.py and
     test_runtime_fallback_management.py.

RESOLUTION DOMAINS (a citation is real if it resolves in at least one):
  * a test method DEFINED inside a TestCase-derived class in tests/*.py
    (the collectable shape — unittest needs both the Test* class prefix and
    the base; module-level test_ functions are NOT collectable and do not
    count);
  * an existing module file (stem of any *.py under tests/, scripts/,
    engines/, notifier/ or the repo root) — prose cites modules by bare
    name constantly ('tests/test_b42_tracked_imports' style without .py);
  * a name BOUND as an identifier in the citing file itself ('test_file' is
    a parameter of patch_sites, not a test — b103 rule 4: the name is quoted
    here because an unquoted mention in THIS docstring is exactly what this
    resolver would sentence as a phantom);
  * a name ending in '_' — glob/wrap shapes ('tests/test_b50_*.py'), which
    are patterns, not names.

RESIDUAL, DELIBERATE: an identifier bound anywhere in the same file spares
the citation file-wide, so a phantom that coincides with a local variable
name in the SAME file is spared. Over-sparing was chosen (b103 rule-4
precedent): the danger is a citation rotting silently, and bound-identifier
citations are how tuple-shape docs legitimately read.

ANTI-VACUITY (b94/b95/b102 discipline): a floor on resolved citations, a
floor requiring BOTH domains to be exercised, and the synthetic offender is
injected as an in-memory (name, src) pair — never written into tests/ where
a concurrent suite run would race on it (b96 flake class).

THE THIRD CLAUSE (rule-table cross-check): prose_audit.py documents six
numbered rules; test_b103's docstring carries an owner table. b103 was
harvested with rule 5 documented and unowned; this run found rule 6 was
documented and MISSING from the table — the exact staleness the clause
exists for, caught on the layer's own second commit. The check parses both
and requires: same rule numbers, every owner class exists in the owner file,
inherits TestCase, and defines at least one test method.
"""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO / 'tests'
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS_DIR))  # prose_audit must import without
                                    # discovery's path insertion (b97 shape)

from prose_audit import (mentioned, quoted_spans, sentences)  # noqa: E402
# (b103 shared hygiene layer — rule 4's mention machinery is reused here for
#  citations: a phantom name QUOTED to document it is a mention, not a pin)

SCAN_DIRS = ('tests', 'scripts', 'engines')
CITATION = re.compile(r'\b(test_[a-z0-9_]+)\b')
# A bare item-number abbreviation of a module name ('test_b42's HEAD scan').
ABBREV = re.compile(r'^test_b\d{1,4}$')
LAYER = TESTS_DIR / 'prose_audit.py'
OWNER_FILE = TESTS_DIR / 'test_b103_prose_audit.py'


def module_stems():
    """Every importable module name the repo actually ships."""
    stems = set()
    for pat in ('*.py', 'tests/*.py', 'scripts/*.py', 'engines/*.py',
                'notifier/*.py'):
        stems |= {p.stem for p in REPO.glob(pat)}
    return stems


def _testcase_classes(tree):
    """Classes that inherit something TestCase-ish — the shape unittest
    actually collects. NB: the CLASS NAME does not matter (discover's
    pattern filters MODULES, not classes): test_b50's
    SuiteIsLocationIndependent and test_b39's siblings are collected
    exactly like TestFoo is. Requiring a Test* prefix here would invent
    phantoms out of real pins — the same lesson b94 learned about trusting
    your own predicate's shape."""
    out = []
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        bases = set()
        for b in cls.bases:
            if isinstance(b, ast.Name):
                bases.add(b.id)
            elif isinstance(b, ast.Attribute):
                bases.add(b.attr)
        if any('TestCase' in b for b in bases):
            out.append(cls)
    return out


def defined_test_methods():
    """test_* methods defined inside a collectable class in tests/*.py."""
    out = set()
    for p in sorted(TESTS_DIR.glob('test_*.py')):
        try:
            tree = ast.parse(p.read_text(encoding='utf-8'))
        except SyntaxError:
            continue
        for cls in _testcase_classes(tree):
            for n in cls.body:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and n.name.startswith('test_'):
                    out.add(n.name)
    return out


def bound_identifiers(src):
    """Every identifier the file binds or references (params, locals, defs,
    attributes) — a citation that is really a tuple-shape doc about a local
    variable is not a test claim."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            names.add(n.id)
        elif isinstance(n, ast.arg):
            names.add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                            ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, ast.Attribute):
            names.add(n.attr)
    return names


def prose_citations(files):
    """[(file, lineno, cited_name)] over comment+docstring prose only —
    the b103 layer owns what counts as prose (rules 1 and 5). A name inside
    a QUOTED span is skipped: b103 rule 4 reused — a tripwire that documents
    a phantom (this file does exactly that) MENTIONS the name, it does not
    pin behaviour with it."""
    rows = []
    for name, src in files:
        for lineno, s in sentences(src):
            spans = quoted_spans(s)
            for m in CITATION.finditer(s):
                if mentioned(m.start(), spans):
                    continue
                rows.append((name, lineno, m.group(1)))
    return rows


def scanned_py_files():
    out = []
    for d in SCAN_DIRS:
        for p in sorted((REPO / d).glob('*.py')):
            try:
                out.append((f'{d}/{p.name}',
                            p.read_text(encoding='utf-8',
                                        errors='replace')))
            except OSError:
                continue
    for p in sorted(REPO.glob('*.py')):
        out.append((p.name, p.read_text(encoding='utf-8', errors='replace')))
    return out


def resolve(citations, methods, stems, bound_by_file):
    """(resolved, phantoms) — resolved = [(file, lineno, name, domain)],
    phantoms = [(file, lineno, name, why)]. EXACT matching only; a strict
    prefix of a real method is reported AS TRUNCATION, never as a hit.
    Domains: 'method' (defined in a collectable class), 'module' (exact
    module stem), 'abbrev' (a bare item-number short form like 'test_b42'
    that prefixes at least one real module — prose uses these constantly),
    'identifier' (bound in the citing file)."""
    resolved, phantoms = [], []
    for name, lineno, cite in citations:
        if cite.endswith('_'):
            continue                      # glob/wrap shape, not a name
        if cite in methods:
            resolved.append((name, lineno, cite, 'method'))
        elif cite in stems:
            resolved.append((name, lineno, cite, 'module'))
        elif ABBREV.match(cite) and any(s.startswith(cite + '_')
                                        for s in stems):
            resolved.append((name, lineno, cite, 'abbrev'))
        elif cite in bound_by_file.get(name, set()):
            resolved.append((name, lineno, cite, 'identifier'))
        else:
            pref = [m for m in methods if m.startswith(cite + '_')]
            why = ('truncated prefix of ' + pref[0]) if pref \
                else 'no such test method, module, or bound identifier'
            phantoms.append(f'{name}:{lineno}: {cite} ({why})')
    return resolved, phantoms


class TestCitedTestsResolveToRealEntities(unittest.TestCase):
    MIN_RESOLVED = 25  # anti-vacuity: the scan must actually resolve things

    def _run(self, files=None):
        files = files if files is not None else scanned_py_files()
        bound = {name: bound_identifiers(src) for name, src in files}
        cites = prose_citations(files)
        return resolve(cites, defined_test_methods(), module_stems(), bound)

    def test_no_phantom_citations_in_repo_prose(self):
        _resolved, phantoms = self._run()
        self.assertEqual(
            phantoms, [],
            'b104: prose cites a test that resolves to nothing — the pin it '
            'claims is not the pin that runs: ' + '; '.join(phantoms))

    def test_the_scan_resolves_a_floor_of_real_citations(self):
        resolved, _phantoms = self._run()
        self.assertGreaterEqual(
            len(resolved), self.MIN_RESOLVED,
            f'only {len(resolved)} citations resolved — the extractor or '
            'the resolver is broken, not the repo clean')
        domains = {d for *_rest, d in resolved}
        self.assertIn('method', domains,
                      'no method citation resolved — the method domain is '
                      'dead and phantoms would slip past it')
        self.assertIn('module', domains,
                      'no module citation resolved — the module domain is '
                      'dead and phantoms would slip past it')

    def test_the_three_shipped_fixes_resolve_by_exact_name(self):
        """The b104 audit's own victims, pinned so a future rename that
        breaks the citation fails HERE, not in a reader's confusion."""
        methods = defined_test_methods()
        stems = module_stems()
        self.assertIn('test_plain_assert_identity_stays_spared_pending_b101',
                      methods)
        self.assertIn('test_allowed_entries_are_still_real', methods)
        self.assertIn('test_broker_clock', stems)
        self.assertIn('test_runtime_fallback_management', stems)

    def test_a_synthetic_phantom_is_flagged_and_a_real_name_is_not(self):
        """Anti-vacuity on the resolver itself (in-memory pair, b95 rule):
        the predicate must bite on an injected phantom and stay clean on the
        same sentence citing a real collectable method."""
        phantom_src = ('"""Doc. The rule is pinned by '
                       'test_b104zzphantompinshape here."""\n')
        real_src = ('"""Doc. The rule is pinned by '
                    'test_allowed_entries_are_still_real here."""\n')
        files = [('tests/test_b104_zz_synthetic.py', phantom_src),
                 ('tests/test_b104_zz_synthetic_ok.py', real_src)]
        resolved, phantoms = self._run(files=files)
        self.assertTrue(any('zz_synthetic.py:' in p and
                            'test_b104zzphantompinshape' in p
                            for p in phantoms),
                        'the resolver is blind to a bare phantom: '
                        + str(phantoms))
        self.assertTrue(any(d == 'method' for *_r, d in resolved),
                        'a real citation was flagged or the ok-file died')
        self.assertFalse(any('zz_synthetic_ok' in p for p in phantoms))

    def test_truncation_is_reported_as_truncation_not_as_a_hit(self):
        """The b94 victim shape replayed: a strict prefix of a real method
        must NOT resolve (pin_exists-style substring matching is exactly
        what let the truncated citation read as satisfied for a day)."""
        resolved, phantoms = resolve(
            [('tests/x.py', 1, 'test_allowed_entries_are_still')],
            defined_test_methods(), module_stems(), {})
        self.assertEqual(resolved, [])
        self.assertEqual(len(phantoms), 1)
        self.assertIn('truncated prefix', phantoms[0])


class TestRuleTableIsComplete(unittest.TestCase):
    """b104's THIRD clause: a shared layer that documents N rules must have
    its owner table cross-checked against N — b103 shipped with rule 5
    unowned, and rule 6 was missing from the table when this check was
    written."""

    @staticmethod
    def _doc_rules(src):
        doc = ast.get_docstring(ast.parse(src)) or ''
        return sorted(int(n) for n in
                      re.findall(r'^\s{2}(\d)\.\s+[A-Z]', doc, re.M))

    @staticmethod
    def _owner_rows(src):
        doc = ast.get_docstring(ast.parse(src)) or ''
        rows = {}
        current = None
        for line in doc.splitlines():
            m = re.match(r'\s*(\d)\s+\S', line)
            if m:
                current = int(m.group(1))
            m2 = re.search(r'->\s*(Test\w+)', line)
            if m2 and current is not None:
                rows[current] = m2.group(1)
        return rows

    def test_every_documented_rule_has_an_owner_row(self):
        rules = self._doc_rules(LAYER.read_text(encoding='utf-8'))
        rows = self._owner_rows(OWNER_FILE.read_text(encoding='utf-8'))
        self.assertEqual(rules, sorted(rows),
                         f'layer documents rules {rules}, owner table '
                         f'covers {sorted(rows)} — a documented rule '
                         'without an owning test class is the b103 gap')

    def test_every_owner_class_is_real_and_fires(self):
        rows = self._owner_rows(OWNER_FILE.read_text(encoding='utf-8'))
        tree = ast.parse(OWNER_FILE.read_text(encoding='utf-8'))
        classes = {c.name: c for c in _testcase_classes(tree)}
        for num, owner in sorted(rows.items()):
            self.assertIn(owner, classes,
                          f'rule {num} names owner {owner} which is not a '
                          'collectable TestCase in the owner file')
            methods = [n.name for n in classes[owner].body
                       if isinstance(n, ast.FunctionDef)
                       and n.name.startswith('test_')]
            self.assertGreaterEqual(
                len(methods), 1,
                f'owner {owner} of rule {num} collects zero tests — the '
                'rule is documented, tabled, and unowned in effect')

    def test_the_crosscheck_is_not_vacuous(self):
        """The parser must see the real numbers: six rules, six rows, and
        the rule-6 row this run added (the table was 5/6 before b104)."""
        rules = self._doc_rules(LAYER.read_text(encoding='utf-8'))
        rows = self._owner_rows(OWNER_FILE.read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(rules), 6,
                                'the layer-rule parser found too few — the '
                                'docstring shape changed and the check is '
                                'blind, not the table complete')
        self.assertEqual(rows.get(6), 'TestProseComesFromTokens',
                         'rule 6 (a quote is one sentence) must stay tabled '
                         'with its owner — it was the gap this run fixed')


if __name__ == '__main__':
    unittest.main()
