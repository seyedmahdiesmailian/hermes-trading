"""b103 — THE SHARED HYGIENE LAYER FOR PROSE-READING TRIPWIRES.

Why this module exists: b102 shipped the first tripwire that reads ENGLISH
PROSE (comments, docstrings, commit messages) for a policy claim instead of
reading code structure, and while measuring its own predicate it hit three
bugs that a code-structure scan never has. Each was pinned by a test in
tests/test_b102_nonwidening_pins.py, but the fix lived inside that one file —
so the NEXT prose audit (b94's vocabulary, b52's env names, any future
"this decision must be recorded somewhere enforceable" rule) would re-
discover them from scratch. This module is the reusable form: every rule
below is a function here, and b102 is its first consumer.

THE FOUR RULES (each one is a real miss or a real false positive measured
against this repo's own history, not a hypothetical):

  1. MERGE BEFORE SENTENCING. A claim wrapped across two '#' comment lines
     strands the item number in one half and the verb in the other, and the
     claim VANISHES. Consecutive comment lines must join into one block
     before splitting on sentence ends. (b102's first version lost one of its
     four live claims this way.)

  2. NEGATION WINS, AND SHIPPING EVIDENCE MUST NAME THE ITEM. The naive
     "this is history, spare it" check spared any sentence containing
     'widened in' — which silently swallowed 'deliberately not widened in
     this commit' (b99's real commit message), because the negated phrase
     CONTAINS the substring. So: a negated widening verb always beats the
     history spare, and the positive evidence must carry the item number
     ('widened in b100'), not just the verb.

  3. THE MEDIA UNDER AUDIT INCLUDES GIT HISTORY. A decision recorded only in
     a commit message leaves the working tree looking clean. commit_messages()
     replays a bounded window of `git log --format=%H%x01%B` and hands the
     bodies to the SAME sentence/claim predicates as code prose.

  4. A QUOTED CLAIM PHRASE IS A MENTION, NOT A DECISION (found 2026-09-06 by
     this rule's own tripwire going RED on HEAD 50cf480). b102's commit-
     message replay flagged the sentence describing b102 itself — "...
     binding every live 'filed as bNN'/'deliberately NOT flipped' claim to a
     test method..." — because the vocabulary appears there as an EXAMPLE in
     quotes, and the item it bound to ('b94', from 'self-excluded per b94
     convention') was an incidental reference three clauses away. Two fixes,
     both here: quoted_spans()/mentioned() spare a verb that sits INSIDE a
     quoted span (the sentence mentions the phrase, it does not make the
     claim), and claim_item() binds the b-number NEAREST the verb instead of
     the first one in the sentence.

  5. EXTRACT PROSE FROM THE TOKENIZER, NOT FROM A LINE SCAN (found the same
     day, by this layer's first consumer). b102's splitter treated every line
     containing a hash sign as a comment, so the STRING LITERALS inside a
     tripwire's fixtures — which must quote the vocabulary to pin it — read
     as policy prose, and a test file that was not self-excluded became a
     phantom claim. comment_blocks() now asks Python's tokenizer which spans
     are comments; docstring_blocks() asks the AST.

RESIDUAL, DELIBERATE (measured 2026-09-06, so nobody rediscovers it as a
bug): a quoted span is a mention EVEN IF it carries a concrete item number.
The alternative — spare only spans whose number is a placeholder (bNN) — was
tried and flags this module's own vocabulary documentation plus a fixture
inside test_b103_prose_audit (3 + 1 phantom claims). The cost of the chosen
shape is that a decision parked ONLY inside quotes is spared; the teeth stay
in the unquoted-prose and commit-message paths, which is where parking
actually happens.

  6. A QUOTE IS ONE SENTENCE (found 2026-09-06 by the repo-wide phantom check
     in test_b103_prose_audit, one commit before this layer shipped). The
     naive splitter cut on '. ' INSIDE quoted examples — and an example that
     documents rule 4 almost always carries an ellipsis ("'... convention ...
     deliberately NOT flipped ...'"). The tail half then had no opening quote,
     quoted_spans() found nothing, and the mention spare died on exactly the
     sentences written to demonstrate it, binding a phantom claim to whatever
     b-number survived in the tail. split_sentences() now skips boundaries
     inside quoted spans; both prose paths (code and commit messages) go
     through it.

Anti-vacuity discipline is inherited unchanged (b94/b95): offenders are
injected as in-memory (name, src) pairs, never written into tests/ where a
concurrent suite run would race on them (the b96 flake class), and every
consumer asserts a floor on how much it actually scanned.

This module is NOT named test_*.py on purpose: unittest discovery must not
collect it (it has no TestCase), and b97 already taught the sibling tripwires
to resolve helpers that live outside the test_* naming convention.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

# --- the claim vocabulary -------------------------------------------------
# "filed as b101" / "parked as b101" / "pending_b101" — the forward-looking
# form. The item number is captured; it is the pin's name tag.
FILED_CLAIM = re.compile(
    r'\b(?:filed(?:\s+(?:as|into))?|parked(?:\s+as)?|pending[_ ]):?\s*'
    r'(b\d{2,4})\b', re.I)

# "deliberately NOT flipped here" / "did not widen the plain-assert form" —
# the backward-looking form. MEASURED SCOPE (b102): the verb list is the
# WIDENING vocabulary only; 'deliberately NOT edited' is a FILE-scope
# statement (which round may touch which file), not a parked widening, and
# including it made the audit cry wolf on correct prose.
NONWIDENING = re.compile(
    r'\bdeliberately\s+not\s+(?:flipped|widened|shipped|applied)\b'
    r'|\bdid\s+not\s+(?:flip|widen|ship|apply)\b', re.I)

# Rule 2: a negated widening verb can never be shipping evidence.
NEGATED_WIDENING = re.compile(
    r'\b(?:not|never)\s+(?:widened|shipped|flipped|applied)\b', re.I)

ITEM = re.compile(r'(?<![0-9A-Za-z])b\d{2,4}(?![0-9])')

# Rule 4: a quoted span. Inner text may not contain another quote and is
# length-capped, so a lone apostrophe ("it's") that never closes produces NO
# span — the danger is over-sparing, and an unpaired quote must not eat the
# rest of a sentence.
_QUOTE_CHARS = "'\"`"
QUOTED_SPAN = re.compile(
    r"['\"`]([^'\"`]{1,80})['\"`]")


def quoted_spans(sentence: str):
    """[(start, end)] of every quoted span in the sentence (rule 4)."""
    return [(m.start(), m.end()) for m in QUOTED_SPAN.finditer(sentence)]


def mentioned(pos: int, spans) -> bool:
    """Does this offset fall inside a quoted span? Then the phrase there is
    being MENTIONED (given as an example), not USED to record a decision."""
    return any(a <= pos < b for a, b in spans)


def is_history(sentence: str, item: str) -> bool:
    """Rule 2: does this sentence report the parked item as ALREADY shipped?
    A negated widening verb always wins, and the positive evidence must name
    the item ('widened in b100') or use an unambiguous past form."""
    if NEGATED_WIDENING.search(sentence):
        return False
    if re.search(r'\b(?:now|was|already|since)\s+widened\b', sentence, re.I):
        return True
    return bool(re.search(r'\b(?:widened|shipped)\s+in\s+'
                          + re.escape(item) + r'\b', sentence, re.I))


def nearest_item(sentence: str, verb_start: int, verb_end: int):
    """Rule 4b: bind the b-number CLOSEST to the verb, not the first one in
    the sentence. 'self-excluded per b94 convention ... deliberately NOT
    flipped ...' must not become a claim about b94."""
    best, best_d = None, None
    for m in ITEM.finditer(sentence):
        d = min(abs(m.start() - verb_end), abs(verb_start - m.end()))
        if best_d is None or d < best_d:
            best, best_d = m.group(0), d
    return best.lower() if best else None


def claim_items(sentence: str):
    """[(item, verb_text)] for every LIVE claim in one sentence.

    A verb occurrence inside a quoted span is skipped (rule 4), and a
    sentence that reports the item as already shipped is skipped (rule 2).
    """
    spans = quoted_spans(sentence)
    out = []
    for m in FILED_CLAIM.finditer(sentence):
        if mentioned(m.start(), spans):
            continue
        item = m.group(1).lower()
        if not is_history(sentence, item):
            out.append((item, m.group(0)))
    if out:
        return out
    for m in NONWIDENING.finditer(sentence):
        if mentioned(m.start(), spans):
            continue
        item = nearest_item(sentence, m.start(), m.end())
        if item and not is_history(sentence, item):
            out.append((item, m.group(0)))
    return out


# --- prose extraction (rules 1 and 5) ------------------------------------
#
# Rule 5 (found 2026-09-06, by this layer's own first consumer): the
# extraction must be TOKEN-BASED, not "any line containing a hash sign".
# b102's original line-based splitter read the STRING LITERALS inside a
# tripwire's fixtures as comments — so a test that quotes the vocabulary to
# pin it became a phantom policy claim in a file that was not self-excluded.
# The fix is to ask Python's own tokenizer which spans are comments, and the
# AST which spans are docstrings. A prose audit that reads code as prose will
# eventually sentence a fixture.

def _comment_token_lines(src: str):
    """{lineno: comment text} from the tokenizer — the ONLY lines that are
    comments. Returns None if the source cannot be tokenized (then it is not
    Python and has no prose to audit)."""
    import io
    import tokenize
    out = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                out[tok.start[0]] = tok.string.lstrip('#').strip()
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    return out


def _blocks_from_lines(lines, wanted, start_of=None):
    """Merge ADJACENT wanted line numbers into (first_lineno, joined_text)
    blocks (rule 1). `wanted` is {lineno: text}."""
    out = []
    buf, buf_start = [], 0
    for i, line in enumerate(lines, 1):
        if i in wanted:
            if buf and i != buf_start + len(buf):
                out.append((buf_start, ' '.join(buf)))
                buf = []
            if not buf:
                buf_start = i
            buf.append(wanted[i])
    if buf:
        out.append((buf_start, ' '.join(buf)))
    return out


def comment_blocks(src: str):
    """(lineno, text) per comment BLOCK: consecutive comment lines are merged
    so a sentence wrapped across them stays one sentence (rule 1)."""
    lines = src.splitlines()
    wanted = _comment_token_lines(src)
    if wanted is None:
        return []
    return _blocks_from_lines(lines, wanted)


def docstring_blocks(src: str):
    """(lineno, text) per docstring BLOCK — one block per docstring, joined,
    for the same reason as comments: a claim wrapped across two docstring
    lines is one claim. Using the docstring VALUE (not raw lines) also keeps
    the ''' delimiters out of the text, so they cannot masquerade as the
    quoted spans of rule 4."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            if doc:
                text = ' '.join(l.strip() for l in doc.splitlines()).strip()
                out.append((getattr(node, 'lineno', 1), text))
    return out


def split_sentences(norm: str):
    """Cut normalized prose into sentences — but NEVER inside a quoted span.

    b103 residual, found by this layer's own rule-5 test: an example quoted to
    illustrate the vocabulary usually contains an ellipsis ("'self-excluded per
    b94 convention ... deliberately NOT flipped ...'"), and the naive
    lookbehind split on '. ' cut the span in half. The second half then has no
    opening quote, so quoted_spans() finds nothing, the verb reads as UNQUOTED
    prose, and the mention spare (rule 4) dies on exactly the sentences that
    exist to document it — a phantom claim bound to whatever b-number survives
    in that half. A quote is one unit of meaning; a period inside it is not a
    sentence boundary.
    """
    spans = quoted_spans(norm)
    parts, start = [], 0
    for m in re.finditer(r'(?<=[.;:])\s+', norm):
        if not mentioned(m.start(), spans):
            parts.append(norm[start:m.start()])
            start = m.end()
    parts.append(norm[start:])
    return [p.strip() for p in parts if p.strip()]


def sentences(src: str):
    """Comment + docstring text, whitespace-normalised, split on sentence
    ends. CODE IS NOT SCANNED — and since b103, neither are the string
    literals inside it (rule 5): the claim lives in prose, and a tripwire's
    own fixtures quote the vocabulary to pin it."""
    out = []
    for lineno, raw in comment_blocks(src) + docstring_blocks(src):
        norm = re.sub(r'\s+', ' ', raw).strip()
        for s in split_sentences(norm):
            out.append((lineno, s))
    return out


def prose_claims(src: str):
    """[(lineno, item, sentence)] — every live non-widening claim in one
    module's prose."""
    hits = []
    for lineno, s in sentences(src):
        for item, _verb in claim_items(s):
            hits.append((lineno, item, s))
    return hits


# --- the git-history medium (rule 3) -------------------------------------

COMMIT_WINDOW = 100


def commit_messages(repo, n: int = COMMIT_WINDOW):
    """[(sha, body)] over the last n commits. NUL-delimited so a multi-line
    body survives intact."""
    r = subprocess.run(['git', 'log', '--format=%H\x01%B\x02', '-n', str(n)],
                       cwd=str(Path(repo)), capture_output=True, text=True)
    out = []
    for rec in r.stdout.split('\x02'):
        if '\x01' not in rec:
            continue
        sha, body = rec.split('\x01', 1)
        out.append((sha[:7], body))
    return out


def commit_claims(repo, n: int = COMMIT_WINDOW):
    """[(sha, item, sentence)] for every live claim recorded in a COMMIT
    MESSAGE — the medium this rule exists to distrust. Same predicates as
    code prose, so a claim that reads as a mention in a docstring reads as a
    mention in a commit message too."""
    out = []
    for sha, body in commit_messages(repo, n):
        norm = re.sub(r'\s+', ' ', body).strip()
        for s in split_sentences(norm):
            for item, _verb in claim_items(s):
                out.append((sha, item, s))
    return out
