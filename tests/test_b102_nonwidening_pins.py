"""b102 — DELIBERATE NON-WIDENINGS MUST BE PINNED AS TESTS, NOT COMMIT MESSAGES.

RULE (backlog, from b100, 2026-09-06): when a widening is measured free but
deliberately NOT shipped — scope discipline, one widening per commit — the
decision lives nowhere unless a test pins the spared shape with the parked
item's number in its name (b100's
test_plain_assert_identity_stays_spared_pending_b101). So:

  (a) every "we chose NOT to widen here" claim in the codebase must have a
      spared-direction test named after the parked item, and
  (b) that item must carry a line saying the pin must be EDITED, not deleted,
      when it ships — so the flip is deliberate and dated and the boundary
      cannot rot into an accident in either direction.

WHY A TEST AND NOT PROSE: b100 recorded its non-widening in the commit
message and in the backlog. Both are write-once. A test that asserts the
spared shape is the only artifact that (i) fails loudly if someone widens
without editing the pin, and (ii) fails loudly if someone DELETES the pin
without shipping the widening. Prose does neither.

SHAPE OF THE CLAIM (measured 2026-09-06 over all 74 test files, 138 scripts,
36 engines and 9 root modules — 4 claims, all in tests/test_b94_*.py, all
already pinned, so the audit ships green on day one):
  * a sentence in a comment or docstring that says a shape was
    "filed as bNN" / "parked as bNN" / "pending_bNN"  — the forward-looking
    form, OR
  * a sentence that says something was "deliberately NOT flipped|widened|
    shipped|applied" and names a bNN item — the backward-looking form.
  * SPARED: a sentence that also says the item was subsequently shipped
    ("widened in bNN", "shipped in bNN", "now/was widened") — that is a
    HISTORY note, not a live boundary, and forcing a spared-test for it would
    demand a test asserting a shape the scan no longer flags. b94's line
    "filed as b100 and widened in b100 below" is exactly this shape.

Anti-vacuity, same discipline as b94/b95/b99/b100: the sweep runs over
in-memory (name, src) pairs — a synthetic offender is INJECTED, never written
into tests/ where a concurrent suite run would race on it (b95 rule) — and a
MIN_FILES floor asserts the scan actually scanned.

b103 (2026-09-06): the three hygiene rules above — plus the fourth one this
file's own tripwire taught by going RED on HEAD 50cf480 (a QUOTED claim phrase
is a mention, not a decision, and the item must bind NEAREST the verb), the
fifth (extract prose from the tokenizer, not a line scan, or a fixture that
quotes the vocabulary reads as a decision) and the sixth (a quote is one
sentence — splitting inside a quoted example kills the mention spare on the
very sentences that document it) — now live in tests/prose_audit.py, the
shared layer for prose-reading tripwires. This file is its first consumer:
the predicates below are re-exported from there, and
tests/test_b103_prose_audit.py pins the layer itself.
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
sys.path.insert(0, str(TESTS_DIR))  # `import prose_audit` must not depend
                                     # on discovery's path insertion (b97 shape)

from prose_audit import (  # noqa: E402  (b103 shared hygiene layer)
    FILED_CLAIM, NONWIDENING, NEGATED_WIDENING, ITEM,
    COMMIT_WINDOW, claim_items, comment_blocks, docstring_blocks,
    is_history, prose_claims, sentences)
from prose_audit import commit_claims as _shared_commit_claims  # noqa: E402

BACKLOG = REPO / 'data' / 'ops' / 'autopilot_backlog.md'

# The source trees a non-widening decision can be recorded in. Production
# code is included on purpose: the rule is about the DECISION, not the file
# type, and a "we chose not to apply this in engines/x.py" note is just as
# unenforceable as one in a test.
SCAN_DIRS = ('tests', 'scripts', 'engines')

# The claim vocabulary, the history-spare, the sentence splitter and the
# commit-message replay all live in tests/prose_audit.py since b103 — this
# file is that layer's first consumer, and the names it used to define
# locally (FILED_CLAIM, NONWIDENING, is_history, sentences, commit_claims,
# ...) are re-exported from the import above so the tests below keep binding
# the REAL predicates, not copies.
#
# The wording b102 requires inside the parked item itself.
EDIT_NOT_DELETE = re.compile(r'\bedited,?\s+not\s+deleted\b', re.I)


def nonwidening_claims(src: str):
    """[(lineno, item, sentence)] — every live 'we chose NOT to widen' claim
    in one module's prose. Thin alias onto the shared layer's prose_claims()."""
    return prose_claims(src)


def scanned_files():
    """[(relpath, src)] over SCAN_DIRS — read once, reused by every check.

    THIS file is excluded, exactly as b94 excludes itself from its own sweep:
    its prose IS the claim vocabulary (it has to quote "filed as bNN" and
    "deliberately NOT flipped" to define the pattern), so scanning it would
    flag the rule's own documentation. The exclusion is pinned by
    test_this_file_is_self_excluded_and_why so it cannot hide a real offender
    by accident — the synthetic-offender test proves the predicate still bites
    on injected prose.

    b103 note: prose_audit.py itself is deliberately IN the scan set. It is
    the layer's documentation, but its prose was written to pass the rules it
    documents (quoted example phrases read as mentions, unquoted claims bind
    to real parked items) — and if it ever stops passing, that is exactly the
    drift the scan should catch.
    """
    out = []
    for d in SCAN_DIRS:
        for p in sorted((REPO / d).glob('*.py')):
            if p.name == Path(__file__).name:
                continue
            try:
                out.append((f'{d}/{p.name}',
                            p.read_text(encoding='utf-8')))
            except (OSError, UnicodeDecodeError):
                continue
    for p in sorted(REPO.glob('*.py')):
        if p.name == Path(__file__).name:
            continue
        out.append((p.name, p.read_text(encoding='utf-8')))
    return out


def test_method_names(files=None):
    """Every test method name defined in the given (name, src) pairs."""
    files = files if files is not None else [
        (f'tests/{p.name}', p.read_text(encoding='utf-8'))
        for p in sorted(TESTS_DIR.glob('*.py'))]
    names = set()
    for _name, src in files:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith(
                    'test_'):
                names.add(node.name)
    return names


def pin_exists(names, item: str) -> bool:
    """Is there a test method whose NAME carries this item number? Word-ish
    boundaries so b101 never matches b1010 or b99 never matches b990."""
    pat = re.compile(r'(?<![0-9A-Za-z])' + re.escape(item) + r'(?![0-9])',
                     re.I)
    return any(pat.search(n) for n in names)


def find_pins(names, item: str):
    pat = re.compile(r'(?<![0-9A-Za-z])' + re.escape(item) + r'(?![0-9])',
                     re.I)
    return sorted(n for n in names if pat.search(n))


def backlog_items(text: str):
    """{item_id: {'status': 'todo'|'done', 'body': str}} parsed out of the
    backlog's Active section. Checkbox lines start an entry; the next
    checkbox or '## ' heading ends it.

    b104 heal (2026-09-06): 0a281bb tagged meta todos with a leading
    '[META] ' and the old regex anchored on '(b\\d+)' right after the
    checkbox — 14 tagged items (b70, b101, b104...) silently vanished from
    the parse, and b103's phantom-claim check went RED on a REAL item.
    Optional bracket tags are now skipped; a pin below counts raw checkbox
    lines so a future prefix can never shrink the parse again."""
    items = {}
    pat = re.compile(r'^- \[([ xX])\] (?:\[[^\]]*\]\s*)?(b\d+)\b', re.M)
    marks = list(pat.finditer(text))
    for i, m in enumerate(marks):
        start = m.end()
        stop = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        nxt = re.search(r'^## ', text[start:stop], re.M)
        if nxt:
            stop = start + nxt.start()
        items[m.group(2).lower()] = {
            'status': 'todo' if m.group(1) == ' ' else 'done',
            'body': text[start:stop],
        }
    return items


def audit(files=None, names=None):
    """The b102 rule as data: [(file, lineno, item, why, sentence)]."""
    files = files if files is not None else scanned_files()
    names = names if names is not None else test_method_names()
    problems = []
    for name, src in files:
        for lineno, item, s in nonwidening_claims(src):
            if not pin_exists(names, item):
                problems.append(
                    (name, lineno, item,
                     f'no test method name carries {item} — the parked '
                     'widening has no spared-direction pin', s))
    return problems


class B102OnCurrentRepo(unittest.TestCase):
    MIN_FILES = 150  # anti-vacuity: the scan must actually scan

    def test_the_scan_actually_scans(self):
        files = scanned_files()
        self.assertGreaterEqual(len(files), self.MIN_FILES,
                                f'only {len(files)} files scanned — the '
                                'audit is broken, not the repo clean')
        self.assertTrue(any(n.startswith('tests/test_b94') for n, _ in files),
                        'the b94 tripwire file is not in the scan set')

    def test_every_nonwidening_claim_has_a_named_pin(self):
        problems = audit()
        self.assertEqual(
            problems, [],
            'b102: a deliberate non-widening is recorded in prose only. '
            'Every "we chose NOT to widen here" needs (a) a spared-direction '
            'test named after the parked item and (b) an "edited, not '
            'deleted" line inside that item — '
            + '; '.join(f'{f}:{ln} {item} ({why})'
                        for f, ln, item, why, _ in problems))

    def test_the_audit_is_not_vacuous_a_synthetic_claim_without_a_pin_fails(self):
        """Inject the offender as an in-memory (name, src) pair (b95 rule:
        never write a temp file into tests/ where a concurrent suite races
        on it)."""
        offender = ('"""Some tripwire.\n\n'
                    '  The sibling shape is deliberately NOT flipped here;\n'
                    '  it is measured free and filed as b999, its own '
                    'decision.\n"""\n')
        files = scanned_files() + [
            ('tests/test_b102_zz_synthetic.py', offender)]
        problems = audit(files=files)
        self.assertTrue(
            any('test_b102_zz_synthetic' in f and item == 'b999'
                for f, _ln, item, _why, _s in problems),
            'the audit is blind to a bare "filed as bNN" with no pin: '
            + str(problems))
        self.assertEqual(audit(), [],
                         'the synthetic proves the rule bites; the real repo '
                         'must stay clean')


COMMIT_CLAIM_WINDOW = 100  # last N commit messages


def commit_claims(n: int = COMMIT_CLAIM_WINDOW):
    """[(sha, item, sentence)] for every live claim recorded in a COMMIT
    MESSAGE — the medium b102 exists to distrust. b99's own message
    ('new todo b100 ... deliberately not widened in this commit') is the
    shape: the decision was recorded ONLY in prose git history, and no test
    would have caught someone silently widening b100's parked shape without
    the b100-named pin.

    Thin wrapper onto prose_audit.commit_claims (b103) so the repo is always
    the repo THIS test file lives in — the same REPO binding the b42/b44
    integrity scans use, never an author's cwd."""
    return _shared_commit_claims(REPO, n)


class CommitMessagesAreNotTheOnlyRecord(unittest.TestCase):
    """The b41 discipline applied to this rule: replay REAL history, not a
    strawman. Every non-widening claim the last 100 commits made must today
    have a test named after its item — commit prose is allowed to RECORD a
    decision, just never to be the ONLY place it lives."""

    def test_the_window_actually_contains_claims(self):
        claims = commit_claims()
        self.assertGreaterEqual(
            len(claims), 1,
            'zero claims in the last '
            f'{COMMIT_CLAIM_WINDOW} commit messages — either the window is '
            'stale or the predicate died; the audit would pass vacuously')

    def test_every_commit_recorded_nonwidening_has_a_named_pin_today(self):
        names = test_method_names()
        bad = [(sha, item, s) for sha, item, s in commit_claims()
               if not pin_exists(names, item)]
        self.assertEqual(
            bad, [],
            'b102: a commit message parked a widening but no test method '
            'name carries the item — the boundary lives only in prose: '
            + '; '.join(f'{sha}:{item} ({s[:80]})' for sha, item, s in bad))


class ClaimVocabularyIsHonest(unittest.TestCase):
    """Both directions of the predicate itself, so the audit cannot rot into
    flagging history notes or missing the phrasings the repo actually uses."""

    def test_forward_and_backward_forms_are_both_claims(self):
        for src, want in (
            ('# measured free and filed as b101, its own decision\n', 'b101'),
            ('# the sibling is parked as b123 pending review\n', 'b123'),
            ('def f():\n    """deliberately NOT flipped here (b101)."""\n',
             'b101'),
            ('# b100 did NOT widen the plain-assert form\n', 'b100'),
        ):
            hits = nonwidening_claims(src)
            self.assertTrue(hits, f'claim missed: {src!r}')
            self.assertEqual(hits[0][1], want, f'wrong item bound: {src!r}')

    def test_the_audit_finds_the_real_claims_it_was_written_for(self):
        """Anti-vacuity on REAL data (not just the injected synthetic): while
        b101 is still open, the repo must contain at least one live claim —
        b94's three sentences about the parked plain-assert sibling. If this
        ever reads zero while claims exist, the predicate is dead and the
        green sweep means nothing. When b101 ships, its prose becomes a history
        note ('widened in b101'), so the floor moves with the backlog: this
        test is one of the things to EDIT at that moment, not delete."""
        items = backlog_items(BACKLOG.read_text(encoding='utf-8'))
        live = [c for _n, src in scanned_files()
                for c in nonwidening_claims(src)]
        if items.get('b101', {}).get('status') == 'todo':
            self.assertGreaterEqual(
                len(live), 1,
                'b101 is still open but the audit sees zero live claims — '
                'either the prose was rewritten or the predicate died')
            self.assertTrue(any(item == 'b101' for _ln, item, _s in live),
                            'the claims it sees are not the b101 ones')

    def test_a_history_note_is_spared(self):
        """b94's real line: filed AND widened in the same sentence. Demanding
        a spared test for it would ask for a test asserting a shape the scan
        no longer flags."""
        src = ('# was the identity family, filed as b100 and widened in b100 '
               'below.\n')
        self.assertEqual(nonwidening_claims(src), [],
                         'a shipped history note is being treated as a live '
                         'boundary')

    def test_negated_widening_is_a_claim_even_when_it_reads_like_history(self):
        """THE BUG THIS TEST EXISTS FOR (measured 2026-09-06 against b99's
        real commit message): the first is_history() spared any sentence
        containing 'widened in', which silently swallowed 'deliberately not
        widened in this commit' — a substring collision that would have made
        the whole audit blind to exactly the shape it was written to catch.
        A negated widening verb must NEVER read as shipping evidence."""
        src = ('# new todo b100 (identity-assert family, measured free,\n'
               '# deliberately not widened in this commit);\n')
        hits = nonwidening_claims(src)
        self.assertEqual([item for _ln, item, _s in hits], ['b100'],
                         'the negated form slipped past as history again')
        self.assertTrue(is_history(
            'filed as b100 and widened in b100 below', 'b100'),
            'the genuine history form must still be spared')

    def test_prose_without_an_item_number_is_not_a_claim(self):
        """'deliberately NOT in here' (b99's _hardcoded_answer comment) names
        no parked item — there is nothing to pin."""
        for src in ('# deliberately NOT in here — see _hardcoded_answer.\n',
                    '# this file is deliberately NOT invoked, only imported.\n'):
            self.assertEqual(nonwidening_claims(src), [],
                             f'no-item prose flagged: {src!r}')

    def test_untouchable_file_scope_note_is_not_a_widening_claim(self):
        """MEASURED: 'deliberately NOT edited' was in the verb list for about
        ten seconds. Its only repo-wide hit is b89's 'engines/risk.py is
        deliberately NOT edited by b89' — a statement about which FILE a round
        may touch, already pinned by a byte-identity test (b88's), not a parked
        widening awaiting a spared-shape test. Keeping it would fire the audit
        on correct prose on day one."""
        src = ('# engines/risk.py is deliberately NOT edited by b89: its '
               'sha256 is\n# pinned by test_risk_slice_stays_byte_identical'
               '_for_b88\n')
        self.assertEqual(nonwidening_claims(src), [],
                         'the file-scope form was pulled back into the '
                         'widening vocabulary — re-measure before keeping it')

    def test_this_file_is_self_excluded_and_why(self):
        """Self-exclusion is b94's own convention (its prose IS the pattern).
        Pin it so the exclusion cannot silently widen into 'nothing is
        scanned': the floor test above proves the rest of the repo is."""
        names = [n for n, _ in scanned_files()]
        self.assertNotIn('tests/test_b102_nonwidening_pins.py', names)
        self.assertTrue(any(n.startswith('tests/test_b94') for n in names),
                        'the sibling tripwire must stay IN the scan set')
        # and the exclusion is not a cover for a dead predicate: this file's
        # own docstring contains a live claim shape, which the predicate sees
        # when the file is fed to it explicitly.
        self.assertTrue(nonwidening_claims(
            Path(__file__).read_text(encoding='utf-8')),
            'self-exclusion now hides a predicate that matches nothing')

    def test_code_is_not_scanned_as_a_claim(self):
        """The b94 fixtures contain the literal text 'filed as b101' inside
        assertion STRINGS; only prose (comments/docstrings) is a decision."""
        src = ('class T(unittest.TestCase):\n'
               '    def test_x(self):\n'
               '        s = "this shape was filed as b999 in the backlog"\n'
               '        self.assertIn(s, [])\n')
        self.assertEqual(nonwidening_claims(src), [])


class BacklogSideOfTheRule(unittest.TestCase):
    """(b) of the rule: the parked item itself must say the pin is EDITED,
    not deleted, when it ships."""

    def test_the_backlog_actually_parses(self):
        items = backlog_items(BACKLOG.read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(items), 20,
                                f'only {len(items)} backlog items parsed — '
                                'the parser is broken')
        self.assertEqual(items.get('b101', {}).get('status'), 'todo',
                         'b101 is the live example this rule was written '
                         'from; if it moved, update this test deliberately')
        self.assertEqual(items.get('b100', {}).get('status'), 'done')

    def test_every_parked_widening_todo_carries_the_edit_not_delete_line(self):
        items = backlog_items(BACKLOG.read_text(encoding='utf-8'))
        bad = []
        for item, rec in sorted(items.items()):
            if rec['status'] != 'todo':
                continue
            body = rec['body']
            if not re.search(r'one widening per commit|deliberately NOT|'
                             r'did NOT flip|boundary pin', body, re.I):
                continue
            if not EDIT_NOT_DELETE.search(body):
                bad.append(item)
        self.assertEqual(
            bad, [],
            'b102: a parked widening must say its pin is "edited, not '
            'deleted" so the flip is deliberate and dated: '
            + ', '.join(bad))

    def test_the_live_reference_shape_of_the_rule(self):
        """The live example, pinned by name: the claim, the named pin, and
        the edit-not-delete line must all still line up. If b101 ships, this
        test is one of the things that must be EDITED (not deleted silently).
        NB: this method deliberately does NOT carry 'b101' in its own name —
        the uniqueness assert below counts name-carriers, and a second one
        would be indistinguishable from a duplicated boundary pin."""
        items = backlog_items(BACKLOG.read_text(encoding='utf-8'))
        self.assertIn('b101', items)
        self.assertTrue(EDIT_NOT_DELETE.search(items['b101']['body']))
        names = test_method_names()
        self.assertIn('test_plain_assert_identity_stays_spared_pending_b101',
                      names)
        self.assertEqual(
            find_pins(names, 'b101'),
            ['test_plain_assert_identity_stays_spared_pending_b101'],
            'a second b101-named test appeared — check it is not a duplicate '
            'boundary pin')


if __name__ == '__main__':
    unittest.main()
