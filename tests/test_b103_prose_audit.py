"""b103 — pins the SHARED PROSE-AUDIT LAYER (tests/prose_audit.py).

Why this file exists: b102 shipped the first tripwire that reads English
prose for a policy claim, hit four bugs while measuring its own predicate,
and pinned each of them inside its own file. b103 lifts the predicates into
one shared module so the next prose audit inherits them instead of
re-discovering them — and a shared module with no test of its own is the
b42/b44 incident class in a new costume: it would only be found broken by
whichever consumer happens to trip over it. So every rule is pinned HERE,
against the repo's REAL prose and REAL history, not only against fixtures.

THE RULES AND THE TEST CLASS THAT OWNS EACH (one class per rule in
prose_audit.py's docstring — a rule documented without an owning test is the
gap this file exists to close, and rule 5 was exactly that gap when b103 was
harvested):
  1 merge wrapped comment lines before sentencing  -> TestMergeBeforeSentencing
  2 negation wins; shipping evidence names the item -> TestNegationWins
  3 git history is a medium under audit             -> TestHistoryIsAMedium
  4 a quoted phrase is a MENTION, and the item binds
    NEAREST the verb                                -> TestMentionIsNotADecision
  5 prose comes from the TOKENIZER/AST, never from a
    line scan that reads string literals            -> TestProseComesFromTokens
  6 a quote is ONE SENTENCE: the splitter must not
    cut inside a quoted span                        -> TestProseComesFromTokens

Rule 4 is not academic: it is the reason HEAD 50cf480 was BROKEN when this
run started. b102's commit-message replay flagged b102's OWN commit message,
because that message quotes the vocabulary it enforces ("'filed as
bNN'/'deliberately NOT flipped' claim") and the old binder grabbed an
incidental 'b94' three clauses away. The exact sentence is replayed as a
fixture below (b41 discipline: real data, not a strawman), and the
anti-vacuity test proves the same words UNQUOTED are still caught — the
spare narrows the predicate, it does not silence it.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO / 'tests'
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS_DIR))  # `import prose_audit` must not depend on
                                    # discovery's path insertion (b97 shape)

import prose_audit  # noqa: E402
from prose_audit import (  # noqa: E402
    claim_items, comment_blocks, commit_claims, commit_messages,
    docstring_blocks, is_history, mentioned, nearest_item, prose_claims,
    quoted_spans, sentences, split_sentences)

# The sentence that broke HEAD 50cf480 — b102's own commit message, replayed
# verbatim (minus the parts irrelevant to the predicate). It describes the
# rule, quoting the rule's vocabulary; it parks nothing.
MENTION_SENTENCE = (
    "AST+prose audit (257 files over tests/scripts/engines/root, "
    "self-excluded per b94 convention, MIN_FILES floor) binding every live "
    "'filed as bNN'/'deliberately NOT flipped' claim to a test method whose "
    "NAME carries the item, + backlog-side 'edited, not deleted' check for "
    "parked widening todos, + commit-message replay (last 100 messages vs "
    "CURRENT test names) that enforces the 'not commit messages' half;")

# b99's real commit-message sentence: the shape rule 2 exists for.
B99_CLAIM = ("new todo b100 (identity-assert family, measured free, "
             "deliberately not widened in this commit)")

# b100's real commit-message sentence: the shape rule 4b exists for — three
# b-numbers in one sentence and the claim belongs to the one next to the verb.
B100_CLAIM = ("plain-assert is/is-not sibling deliberately NOT flipped (b99 "
              "parked it as a spared pin, one widening per commit) — measured "
              "free, filed as b101, boundary pinned by "
              "test_plain_assert_identity_stays_spared_pending_b101")


class TestMergeBeforeSentencing(unittest.TestCase):
    """Rule 1: consecutive '#' lines are ONE block."""

    def test_a_claim_wrapped_across_two_comment_lines_is_still_caught(self):
        src = ('# new todo b100 (measured free,\n'
               '# deliberately not widened in this commit);\n')
        hits = prose_claims(src)
        self.assertEqual([item for _ln, item, _s in hits], ['b100'],
                         'the wrapped form vanished — per-line splitting is '
                         'back in the extractor')

    def test_the_two_halves_alone_are_not_claims(self):
        """ANTI-VACUITY for the merge: if either half alone were a claim, the
        merge test above would prove nothing."""
        for half in ('# new todo b100 (measured free,\n',
                     '# deliberately not widened in this commit);\n'):
            self.assertEqual(prose_claims(half), [],
                             f'a lone half flagged as a claim: {half!r}')

    def test_a_blank_line_breaks_the_block(self):
        """Merging must not glue unrelated comments across a gap, or every
        file becomes one sentence. The gap comment alone carries no item, so
        a merged block would invent the claim 'filed as b111 deliberately NOT
        flipped' — the gap test is really about what does NOT join."""
        src = ('# filed as b111\n'
               'x = 1\n'
               '# deliberately NOT flipped here\n')
        hits = prose_claims(src)
        self.assertEqual([item for _ln, item, _s in hits], ['b111'],
                         'the forward-looking claim vanished')
        self.assertTrue(all('deliberately' not in s for _ln, _i, s in hits),
                        'two unrelated comments were merged into one claim')


class TestNegationWins(unittest.TestCase):
    """Rule 2: 'not widened in this commit' is never shipping evidence."""

    def test_b99_real_message_is_a_claim(self):
        self.assertEqual([item for item, _v in claim_items(B99_CLAIM)],
                         ['b100'])

    def test_genuine_history_note_is_spared(self):
        s = 'was the identity family, filed as b100 and widened in b100 below'
        self.assertTrue(is_history(s, 'b100'))
        self.assertEqual(claim_items(s), [])

    def test_shipping_evidence_must_name_the_item(self):
        """'widened in b101' spares b101 and says NOTHING about b100 — the
        bare verb must not spare a different item's claim."""
        s = ('the plain form was widened in b101 and the sibling is '
             'deliberately NOT flipped for b100')
        self.assertEqual([item for item, _v in claim_items(s)], ['b100'])


class TestMentionIsNotADecision(unittest.TestCase):
    """Rule 4: quoted vocabulary is a mention; the item binds nearest the verb."""

    def test_the_sentence_that_broke_head_50cf480_is_spared(self):
        self.assertEqual(claim_items(MENTION_SENTENCE), [],
                         'b102 is back to flagging its own commit message — '
                         'the mention spare regressed')

    def test_the_same_words_unquoted_are_still_claims(self):
        """THE ANTI-VACUITY THAT MATTERS: without this, 'spare quoted
        phrases' could silently become 'spare everything'. Same vocabulary,
        same item numbers, no quotes -> the claim must fire."""
        unquoted = MENTION_SENTENCE.replace("'filed as bNN'", 'filed as b101')
        items = [item for item, _v in claim_items(unquoted)]
        self.assertIn('b101', items,
                      'the mention spare ate a real forward-looking claim')

    def test_quoted_span_detection_is_the_binding_step(self):
        spans = quoted_spans(MENTION_SENTENCE)
        self.assertTrue(spans, 'no spans found — quoted_spans died')
        verb = MENTION_SENTENCE.index('deliberately NOT flipped')
        self.assertTrue(mentioned(verb, spans),
                        'the quoted verb is not inside a span')
        self.assertFalse(mentioned(0, spans),
                         'offset 0 (unquoted text) reported as quoted')

    def test_item_binds_to_the_verb_not_to_the_first_number_in_sight(self):
        """Rule 4b: 'self-excluded per b94 convention' is an incidental
        reference; the claim belongs to the number beside the verb."""
        s = ('self-excluded per b94 convention, the sibling is deliberately '
             'NOT flipped and filed as b101')
        self.assertEqual([item for item, _v in claim_items(s)], ['b101'])
        # and the bare-verb form resolves by distance, not by order:
        self.assertEqual(nearest_item(
            'b99 parked it, deliberately NOT flipped, pending b123',
            14, 40), 'b123')

    def test_an_unpaired_apostrophe_does_not_swallow_the_sentence(self):
        """The over-sparing danger: "it's" opens a quote that never closes.
        A span needs BOTH ends, so a real claim in the same sentence must
        survive."""
        s = ("it's the plain form, deliberately NOT flipped and filed "
             "as b101")
        self.assertEqual(quoted_spans(s), [],
                         'an unpaired apostrophe produced a span')
        self.assertEqual([item for item, _v in claim_items(s)], ['b101'])

    def test_b100_real_message_binds_the_number_next_to_the_verb(self):
        """The regression check for the distance binder: b100's message names
        b99, b101 and a b101-carrying test method, and the claim is b101's.
        NB: this method deliberately does NOT carry 'b101' in its own name —
        b102's uniqueness assert counts b101-name-carriers and this is not a
        boundary pin."""
        self.assertEqual([item for item, _v in claim_items(B100_CLAIM)],
                         ['b101'])


class TestProseComesFromTokens(unittest.TestCase):
    """Rule 5: extraction asks the tokenizer/AST, never 'any line with a #'.

    This rule was found by the layer's own first consumer: b102's line-based
    splitter read the STRING LITERALS inside a tripwire's fixtures as comments,
    and a test file that quotes the vocabulary to pin it (which every tripwire
    must do) became a phantom policy claim the moment it was not self-excluded.
    """

    # The phantom shape: a fixture whose CONTENT is a wrapped claim, held in a
    # string literal whose continuation lines begin with '#'.
    FIXTURE_SRC = ("CLAIM_FIXTURE = ('# new todo b100 (measured free,\\n'\n"
                   "                   '# deliberately not widened in this '\n"
                   "                   commit);\\n')\n")

    def test_a_string_literal_is_not_prose(self):
        self.assertEqual(comment_blocks(self.FIXTURE_SRC), [],
                         'the extractor read a string literal as comments — '
                         'the phantom-claim shape is back')
        self.assertEqual(prose_claims(self.FIXTURE_SRC), [],
                         'a fixture quoting the vocabulary became a policy '
                         'claim')

    def test_the_same_text_as_a_real_comment_is_still_a_claim(self):
        """ANTI-VACUITY: without this, 'ignore string literals' could be
        'ignore everything'. Identical words, real '#' comment lines."""
        real = ('# new todo b100 (measured free,\n'
                '# deliberately not widened in this commit);\n')
        hits = prose_claims(real)
        self.assertEqual([item for _ln, item, _s in hits], ['b100'],
                         'the token-based extractor lost the real comment')

    def test_a_trailing_comment_after_code_is_still_prose(self):
        """The tokenizer must not over-spare: '#' at the END of a code line is
        a comment and carries a claim."""
        src = "x = '#'  # the sibling is filed as b101\n"
        self.assertEqual([item for _ln, item, _s in prose_claims(src)],
                         ['b101'], 'a trailing comment was skipped')

    def test_docstring_delimiters_cannot_masquerade_as_quoted_spans(self):
        """Rule 4 and rule 5 meet here: docstring_blocks() uses the AST VALUE,
        so the ''' fences never enter the text. With raw lines, an odd number
        of apostrophes inside a docstring would open a span that swallows the
        verb and the claim would vanish."""
        src = ('def f():\n'
               '    """it\'s the plain form, deliberately NOT flipped and\n'
               '    filed as b101."""\n')
        self.assertEqual([item for _ln, item, _s in prose_claims(src)],
                         ['b101'],
                         'docstring fences produced a quoted span and ate the '
                         'claim')

    def test_unparseable_source_yields_no_prose_instead_of_crashing(self):
        """A scan set built by glob() will meet a half-written file. The
        audit must sentence nothing rather than raise and take the suite down.
        """
        broken = "def f(:\n    '''unterminated\n"
        self.assertEqual(comment_blocks(broken), [])
        self.assertEqual(docstring_blocks(broken), [])
        self.assertEqual(prose_claims(broken), [])

    def test_a_quote_containing_an_ellipsis_is_not_split_in_half(self):
        """THE RESIDUAL THIS RUN FOUND (2026-09-06, by the test below it):
        prose_audit's own nearest_item docstring quotes an example containing
        '...' — and the naive sentence splitter cut INSIDE the quote, so the
        second half had no opening quote, quoted_spans() found nothing, and the
        mention spare died on the very sentence that documents it. The phantom
        bound to the b-number left in that half ('b94'), which exists nowhere
        as a parked item — that is how the repo-wide check below caught it."""
        src = ("def nearest_item():\n"
               '    """Rule 4b: bind the number to the verb. \'self-excluded\n'
               "    per b94 convention ... deliberately NOT flipped ...' must\n"
               '    not become a claim about b94."""\n')
        self.assertEqual(prose_claims(src), [],
                         'a quoted example containing an ellipsis was split '
                         'and the tail read as an unquoted claim')
        # anti-vacuity: the SAME words unquoted must still be a claim
        unquoted = src.replace("'self-excluded", "self-excluded").replace(
            "flipped ...'", "flipped")
        self.assertEqual([item for _ln, item, _s in prose_claims(unquoted)],
                         ['b94'],
                         'the quote-aware splitter silenced the predicate')

    def test_split_sentences_keeps_quoted_punctuation_inside_the_sentence(self):
        parts = split_sentences("the rule says 'a; b' and stops here. Next.")
        self.assertEqual(parts, ["the rule says 'a; b' and stops here.",
                                 "Next."],
                         'the splitter no longer splits on real boundaries')

    def test_the_real_tripwire_fixtures_produce_no_phantom_claims(self):
        """End-to-end on REAL files: b94/b102/b103 quote the vocabulary inside
        fixtures and docstrings. Every claim the layer finds across the repo
        must bind to an item that actually exists in the backlog — a phantom
        would bind to a number nobody ever filed."""
        sys.path.insert(0, str(TESTS_DIR))
        import test_b102_nonwidening_pins as b102
        items = b102.backlog_items(
            (REPO / 'data' / 'ops' / 'autopilot_backlog.md').read_text(
                encoding='utf-8'))
        found = {item for _name, src in b102.scanned_files()
                 for _ln, item, _s in prose_claims(src)}
        self.assertTrue(found,
                        'zero claims repo-wide — the extractor is dead, not '
                        'the repo clean')
        self.assertEqual(sorted(found - set(items)), [],
                         f'claims bound to items that exist nowhere: '
                         f'{sorted(found - set(items))}')


class TestHistoryIsAMedium(unittest.TestCase):
    """Rule 3: git log is scanned with the SAME predicates as code prose."""

    MIN_CLAIMS = 1  # anti-vacuity: the window must actually contain claims

    def test_commit_messages_survive_a_multiline_body(self):
        msgs = commit_messages(REPO, 20)
        self.assertGreaterEqual(len(msgs), 5,
                                'git log replay returned almost nothing — '
                                'the NUL-delimited parse died')
        self.assertTrue(any('\n' in body for _sha, body in msgs),
                        'no multi-line body in the window: the parse cannot '
                        'be trusted to preserve one')
        for sha, body in msgs:
            self.assertGreaterEqual(len(sha), 7)
            self.assertTrue(body.strip())

    def test_the_real_parked_claims_are_still_found_in_history(self):
        """The point of rule 4's existence: the mention spare must NOT have
        blinded the replay to the two claims it was written to catch.

        b207-run FIX 2026-09-10: this replay used to read the DEFAULT rolling
        window (prose_audit.COMMIT_WINDOW=100). History moves: by 2026-09-10
        there were 287 commits and the b100/b101 pair had aged to #100-101, so
        the assertion failed on an untouched repo — verify_head stamped HEAD
        BROKEN for a rule about GIT ANCHORING that had nothing to do with the
        code under review. A test that names specific historical commits must
        scan deep enough to still see them; the window stays rolling for the
        live-claim audits (they SHOULD expire with the window)."""
        found = {item for _sha, item, _s in commit_claims(REPO, n=1000)}
        self.assertIn('b101', found, 'b100 parked b101 in prose and the '
                                     'replay no longer sees it')
        self.assertIn('b100', found, 'b99 parked b100 in prose and the '
                                      'replay no longer sees it')

    def test_the_broken_head_sentence_is_not_among_them(self):
        bad = [(sha, item) for sha, item, s in commit_claims(REPO)
               if item == 'b94']
        self.assertEqual(bad, [],
                         f'the mention spare regressed in the real replay: {bad}')


class TestLayerIsNotATestModule(unittest.TestCase):
    """prose_audit.py is a helper: discovery must not collect it, and the
    sibling tripwires must still be able to resolve probes through it."""

    def test_the_module_defines_no_testcase_and_is_not_named_test(self):
        self.assertFalse(Path(prose_audit.__file__).name.startswith('test_'),
                         'named test_*, so unittest discovery would collect '
                         'a module with no tests in it')
        tree = ast.parse(Path(prose_audit.__file__).read_text(encoding='utf-8'))
        classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        self.assertEqual(classes, [],
                         f'helper grew test classes ({classes}) — it belongs '
                         'in a test file then')

    def test_the_layer_is_inside_b102s_scan_set(self):
        """Self-scan honesty: the layer documents the vocabulary, so it is
        the file most likely to trip its own rule. It must be scanned, not
        exempted."""
        sys.path.insert(0, str(TESTS_DIR))
        import test_b102_nonwidening_pins as b102
        names = [n for n, _ in b102.scanned_files()]
        self.assertIn('tests/prose_audit.py', names,
                      'the shared layer exempted itself from its own audit')
        self.assertEqual(b102.audit(), [],
                         'the layer is scanned but does not pass the rule')

    def test_b94_can_resolve_a_probe_imported_from_a_helper_module(self):
        """b97's loader must reach this module too: it is a non-test_ helper
        in tests/, exactly the shape b97 widened for."""
        sys.path.insert(0, str(TESTS_DIR))
        import test_b94_location_dependent_tripwire as b94
        loader = b94.make_loader() if hasattr(b94, 'make_loader') else None
        src = ("from prose_audit import sentences\n"
               "self.assertEqual(len(sentences('x')), 0)\n")
        hits = b94.scan(src, loader=loader)
        self.assertEqual(hits, [],
                         'a derived len() claim started being flagged: '
                         f'{hits}')


if __name__ == '__main__':
    unittest.main()
