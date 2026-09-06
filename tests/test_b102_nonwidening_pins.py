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

BACKLOG = REPO / 'data' / 'ops' / 'autopilot_backlog.md'

# The source trees a non-widening decision can be recorded in. Production
# code is included on purpose: the rule is about the DECISION, not the file
# type, and a "we chose not to apply this in engines/x.py" note is just as
# unenforceable as one in a test.
SCAN_DIRS = ('tests', 'scripts', 'engines')

# --- the claim vocabulary -------------------------------------------------
# "filed as b101" / "parked as b101" / "pending_b101" (b100's own naming for
# its boundary test). The item number is captured; that is the pin's name tag.
FILED_CLAIM = re.compile(
    r'\b(?:filed(?:\s+(?:as|into))?|parked(?:\s+as)?|pending[_ ]):?\s*'
    r'(b\d{2,4})\b', re.I)

# "deliberately NOT flipped here" / "deliberately not widened" / "...not
# shipped inside b99" / "...not applied".
#
# MEASURED SCOPE DECISION (2026-09-06, pinned by
# test_untouchable_file_scope_note_is_not_a_widening_claim): the verb list is
# the WIDENING vocabulary only. `deliberately NOT edited` was tried and
# dropped: its one repo-wide hit (test_b89_window_contract.py:205, "engines/
# risk.py is deliberately NOT edited by b89") is an untouchable-FILE scope
# statement, not a parked widening, and it is already pinned by a byte-identity
# test named after a different item (b88). Flagging it would have made the
# audit cry wolf on the first run — the same "the scan flags correct code"
# failure b94 pins against.
NONWIDENING = re.compile(
    r'\bdeliberately\s+not\s+(?:flipped|widened|shipped|applied)\b'
    r'|\bdid\s+not\s+(?:flip|widen|ship|apply)\b', re.I)

# The same sentence saying the item HAS since shipped -> history, not a live
# boundary. Deliberately narrow, and MEASURED NARROWER BY A REAL MISS: the
# first version of this file spared any sentence containing "widened in", and
# replaying the actual commit history through the predicate showed it silently
# swallowing b99's own message — "new todo b100 (identity-assert family,
# measured free, deliberately not widened in this commit)" — because "not
# widened in this commit" contains the substring "widened in". That is the
# exact false-negative this audit exists to prevent, caught on day one by
# testing against real data instead of fixtures. So: the shipping evidence must
# name the ITEM ("widened in b100", b94's history line) or use an unambiguous
# past/passive form, and a negated widening verb in the sentence always wins.
NEGATED_WIDENING = re.compile(
    r'\b(?:not|never)\s+(?:widened|shipped|flipped|applied)\b', re.I)


def is_history(sentence: str, item: str) -> bool:
    """Does this sentence report the parked item as ALREADY shipped?"""
    if NEGATED_WIDENING.search(sentence):
        return False
    if re.search(r'\b(?:now|was|already|since)\s+widened\b', sentence, re.I):
        return True
    return bool(re.search(r'\b(?:widened|shipped)\s+in\s+'
                          + re.escape(item) + r'\b', sentence, re.I))

ITEM = re.compile(r'(?<![0-9A-Za-z])b\d{2,4}(?![0-9])')

# The wording b102 requires inside the parked item itself.
EDIT_NOT_DELETE = re.compile(r'\bedited,?\s+not\s+deleted\b', re.I)


def _comment_lines(src: str):
    """(lineno, text) for every comment in the module.

    CONSECUTIVE comment lines are merged into one block: a sentence that
    wraps across two '#' lines ('# new todo b100 (measured free,' /
    '# deliberately not widened in this commit)') is ONE claim, and splitting
    per line would strand the item number in one half and the negated verb in
    the other — so the claim would vanish. (Found by the test that pins the
    wrapped form.)"""
    lines = src.splitlines()
    out = []
    buf = []
    buf_start = 0
    for i, line in enumerate(lines, 1):
        if '#' in line:
            if buf and i != buf_start + len(buf):
                out.append((buf_start, ' '.join(buf)))
                buf = []
            if not buf:
                buf_start = i
            buf.append(line.split('#', 1)[1])
    if buf:
        out.append((buf_start, ' '.join(buf)))
    return out


def _docstring_lines(src: str):
    """(lineno, text) for every docstring line (module/class/function)."""
    out = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            if doc:
                base = getattr(node, 'lineno', 1)
                for off, _ in enumerate(doc.splitlines()):
                    out.append((base, _))
    return out


def sentences(src: str):
    """Comment + docstring text, whitespace-normalised, split on sentence
    ends. Assertions and code are NOT scanned: the claim lives in prose, and
    scanning code would flag the synthetic fixtures inside the tripwire's own
    test data (b94's HEAD strings) as if they were decisions."""
    blocks = _comment_lines(src) + _docstring_lines(src)
    out = []
    for lineno, raw in blocks:
        norm = re.sub(r'\s+', ' ', raw).strip()
        for s in re.split(r'(?<=[.;:])\s+', norm):
            s = s.strip()
            if s:
                out.append((lineno, s))
    return out


def nonwidening_claims(src: str):
    """[(lineno, item, sentence)] — every live 'we chose NOT to widen' claim
    in one module's prose."""
    hits = []
    for lineno, s in sentences(src):
        m = FILED_CLAIM.search(s)
        item = m.group(1) if m else None
        if item is None and NONWIDENING.search(s):
            mm = ITEM.search(s)
            item = mm.group(0) if mm else None
        if item is None or is_history(s, item):
            continue
        hits.append((lineno, item.lower(), s))
    return hits


def scanned_files():
    """[(relpath, src)] over SCAN_DIRS — read once, reused by every check.

    THIS file is excluded, exactly as b94 excludes itself from its own sweep:
    its prose IS the claim vocabulary (it has to quote "filed as bNN" and
    "deliberately NOT flipped" to define the pattern), so scanning it would
    flag the rule's own documentation. The exclusion is pinned by
    test_this_file_is_self_excluded_and_why so it cannot hide a real offender
    by accident — the synthetic-offender test proves the predicate still bites
    on injected prose.
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
    checkbox or '## ' heading ends it."""
    items = {}
    pat = re.compile(r'^- \[([ xX])\] (b\d+)\b', re.M)
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
    """[(sha, item, sentence)] for every non-widening claim recorded in a
    COMMIT MESSAGE — the medium b102 exists to distrust. b99's own message
    ('new todo b100 ... deliberately not widened in this commit') is the
    shape: the decision was recorded ONLY in prose git history, and no test
    would have caught someone silently widening b100's parked shape without
    the b100-named pin. Sentences are split the same way as code prose."""
    import subprocess
    r = subprocess.run(['git', 'log', '--format=%H\x01%B\x02', '-n', str(n)],
                       cwd=str(REPO), capture_output=True, text=True)
    out = []
    for rec in r.stdout.split('\x02'):
        if '\x01' not in rec:
            continue
        sha, body = rec.split('\x01', 1)
        norm = re.sub(r'\s+', ' ', body).strip()
        for s in re.split(r'(?<=[.;:])\s+', norm):
            s = s.strip()
            if not s:
                continue
            mm = FILED_CLAIM.search(s)
            item = mm.group(1) if mm else None
            if item is None and NONWIDENING.search(s):
                q = ITEM.search(s)
                item = q.group(0) if q else None
            if item and not is_history(s, item):
                out.append((sha[:7], item.lower(), s))
    return out


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
