"""b106 — signal_parser's output vs signal_decision's input: the field census.

The item asked for two lists: fields the parser produces that nobody consumes,
and fields a consumer reads that the parser never sets. Both were measured over
the real code and the real signal journal (data/signals/signals_log.json), and
the answers are pinned here so the boundary cannot drift back.

FINDING 1 — ONE used-but-never-set key (fixed).
engines/signal_decision.py reads the signal dict through
`signal.get("rr_ratio", 0) or signal.get("computed_rr", 0)`, but
Signal.to_dict() folded computed_rr INTO rr_ratio (`"rr_ratio": self.rr_ratio
or self.computed_rr`) and never emitted the key itself. So the second operand
of that `or` was reading a field that does not exist at this boundary — it
always yielded the default 0. to_dict() now emits computed_rr as well, which
closes the hole without moving a single verdict (see FINDING 2 for why it is
inert today, and the generic tripwire below for why it must still be emitted).

FINDING 2 — the decision layer's own RR fallback is dead by construction.
Check 5 has a second branch: when rr <= 0 but sl and entry are present, it
recomputes RR from entry/sl/tp. Measured over all 28 journal signals: that
branch is reached ZERO times, because the parser already folded computed_rr
into rr_ratio — whenever rr_ratio is falsy, computed_rr is falsy too, so the
branch can only fire on a signal with no SL, which is exactly the case its own
`sl > 0` guard excludes. It is not a bug (it cannot produce a wrong number), it
is a second, unreachable copy of a rule the parser already owns — the same
disease as b109's three lookalike producers, one step earlier in the pipeline.
Left in place: deleting it would change nothing and the pin below is what makes
it safe to leave.

FINDING 3 — the parser's warnings are 3-valued, the gate reads 1 (filed b112).
Check 8 penalises only warnings containing "sl_". The parser emits three
families; over the journal the census is symbol_defaulted_xauusd 4/28,
no_symbol_found 11/28, sl_* 0/28 — i.e. the ONE family the gate looks at has
never fired, and the two that do fire cost nothing. That matters because
`symbol_defaulted_xauusd` means the message never named an instrument and the
symbol was inferred from a price in 1500..6000 (b74g's note: a 5-digit FX price
gets mangled into something that looks like a valid gold signal), yet Check 1
still awards the full +1.0 for "symbol is XAUUSD". Adding the penalty TIGHTENS
a live gate and changes signal-path verdicts, so it is a human decision (b89
class) — filed as b112, not taken here.

FINDING 4 — parsed-but-never-consumed, measured not guessed.
entries, tp2, tps, ladder_rr and order_type are emitted by to_dict() and read
by NO downstream module (grep over every non-test, non-legacy consumer of the
parsed dict). They are deliberately KEPT: b72's docstring says ladder_rr exists
so "the evidence accumulates before the gate itself is ever retuned", and
radin_replay.py feeds the same to_dict() to the same evaluate_signal, so the
journal rows are the accumulation. Deleting them would destroy the evidence
b112 needs to be decided. The pin below records the census so a future round
decides with the list in hand instead of rediscovering it.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engines.signal_parser import Signal, parse_signal  # noqa: E402

# The keys Signal.to_dict() emits, as data (derived from the source below, not
# hand-typed, so this list cannot rot into a lie).
def _to_dict_keys() -> set:
    path = os.path.join(ROOT, "engines", "signal_parser.py")
    with open(path) as fh:
        tree = ast.parse(fh.read())
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        if cls.name != "Signal":
            continue
        for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
            if fn.name != "to_dict":
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Dict) and node.keys:
                    keys = {k.value for k in node.keys
                            if isinstance(k, ast.Constant)}
                    if "symbol" in keys:
                        return keys
    raise AssertionError("Signal.to_dict() return dict not found — re-read b106")


TO_DICT_KEYS = _to_dict_keys()


def _decision_reads() -> set:
    """Every key signal_decision.py reads out of the `signal` argument."""
    path = os.path.join(ROOT, "engines", "signal_decision.py")
    with open(path) as fh:
        src = fh.read()
    reads = set(re.findall(r'signal\.get\(\s*[\'"]([a-z_0-9]+)[\'"]', src))
    reads |= set(re.findall(r'signal\[\s*[\'"]([a-z_0-9]+)[\'"]\s*\]', src))
    return reads


class TestB106ContractCompleteness(unittest.TestCase):
    def test_b106_every_key_the_decision_layer_reads_is_emitted_by_the_parser(
            self):
        # THE GENERIC TRIPWIRE (the reusable part of b106): a read of a key the
        # producer does not emit is silent — `.get()` returns the default and
        # the gate just computes something else. signal_decision reads exactly
        # one such key today (computed_rr, before b106 shipped); this test
        # makes any future one a failure instead of a quiet behaviour change.
        missing = sorted(_decision_reads() - TO_DICT_KEYS)
        self.assertEqual(
            missing, [],
            f"signal_decision reads {missing} which Signal.to_dict() does not "
            "emit — that read silently yields the default. Either emit the "
            "field or stop reading it (b106's contract rule).")

    def test_b106_computed_rr_is_now_emitted_and_matches_the_property(self):
        sig = parse_signal("خرید\n4560\nحد ضرر\n4550\nحد سود\n4590")
        d = sig.to_dict()
        self.assertIn("computed_rr", d)
        self.assertEqual(d["computed_rr"], sig.computed_rr)
        self.assertEqual(d["computed_rr"], 3.0)

    def test_b106_the_emitted_key_is_inert_rr_ratio_already_carries_it(self):
        # The fix must not have changed what the gate sees: rr_ratio is
        # `rr_ratio or computed_rr`, so the new key can only ever duplicate a
        # value already in the first operand. If this ever fails, b106 was NOT
        # inert and every stored signal-path number needs re-checking.
        for text in ("خرید\n4560\nحد ضرر\n4550\nحد سود\n4590",
                     "BUY XAUUSD entry 4560 sl 4550 tp 4590 rr 2.5",
                     "sell gold at market",
                     "BUY XAUUSD 4560 sl 4550"):
            sig = parse_signal(text)
            d = sig.to_dict()
            self.assertEqual(d["rr_ratio"], sig.rr_ratio or sig.computed_rr,
                             f"{text!r}: rr_ratio stopped being the fold")
            if not sig.rr_ratio:
                self.assertEqual(d["rr_ratio"], d["computed_rr"],
                                 f"{text!r}: the two RR fields disagree")


class TestB106DeadFallback(unittest.TestCase):
    def test_b106_decision_rr_fallback_branch_is_unreachable_via_the_parser(
            self):
        # Check 5's second branch (recompute RR from entry/sl/tp when rr <= 0)
        # can never fire for a signal that came through to_dict(): rr_ratio is
        # falsy only when computed_rr is falsy, and computed_rr is falsy only
        # when risk or reward distance is 0 — which the branch's own `sl > 0
        # and entry > 0` plus `tp > 0` guards then exclude. Verified over the
        # real journal, not by reading the code.
        journal = os.path.join(ROOT, "data", "signals", "signals_log.json")
        if not os.path.exists(journal):
            self.skipTest("no signals journal on this checkout")
        with open(journal) as fh:
            rows = json.load(fh)
        self.assertGreater(len(rows), 20,
                           "journal looks truncated — the census is too thin")
        reached = 0
        for e in rows:
            sig = parse_signal(e.get("raw_text") or "")
            d = sig.to_dict()
            rr = d["rr_ratio"] or d.get("computed_rr", 0)
            if rr <= 0 and d["sl"] > 0 and d["entry"] > 0:
                reached += 1
        self.assertEqual(
            reached, 0,
            f"the decision layer's inline RR fallback now fires for "
            f"{reached}/{len(rows)} signals — it is no longer dead code, so it "
            "is a SECOND copy of the RR rule that can drift from the parser's "
            "(b109's disease). Reconcile the two before trusting any score.")


class TestB106WarningCoverage(unittest.TestCase):
    def test_b106_only_sl_warnings_are_penalised_and_none_have_fired(self):
        # b112's number, pinned so the decision is taken with it in hand: the
        # gate looks at one warning family and the journal contains another
        # two. If a sl_* warning ever appears, b112's premise changed.
        with open(os.path.join(ROOT, "engines", "signal_decision.py")) as fh:
            src = fh.read()
        self.assertIn('"sl_" in w', src,
                      "the warning penalty changed shape — re-read b112")
        census = {}
        for e in self._journal():
            for w in parse_signal(e.get("raw_text") or "").warnings:
                census[w] = census.get(w, 0) + 1
        self.assertEqual(census.get("sl_above_entry_for_buy", 0), 0)
        self.assertEqual(census.get("sl_below_entry_for_sell", 0), 0)
        self.assertGreater(census.get("symbol_defaulted_xauusd", 0), 0,
                           "no defaulted-symbol signal in the journal — b112's "
                           "sample is gone, re-measure before quoting it")

    def test_b112_the_sl_only_warning_penalty_is_spared_on_purpose(self):
        # THE SPARED-DIRECTION PIN for b112 (b102's rule: a deliberate
        # non-widening must be pinned by a test whose NAME carries the item, so
        # the parked decision cannot be quietly "refactored" away). b106 found
        # that the gate penalises only sl_* warnings while the two families
        # that actually fire (symbol_defaulted_xauusd, no_symbol_found) cost
        # nothing, and deliberately did NOT add the penalty: doing so TIGHTENS a
        # live gate and changes signal-path verdicts (b89 class, human gate).
        # If someone widens the penalty, this test fires and forces the human
        # decision to be taken on purpose rather than as a side effect.
        with open(os.path.join(ROOT, "engines", "signal_decision.py")) as fh:
            src = fh.read()
        # The penalty clause must still be sl_-scoped, not broadened to catch
        # the defaulted/no-symbol families.
        self.assertIn('"sl_" in w', src)
        self.assertNotIn('"symbol_defaulted" in w', src,
                         "b112's penalty was added — that is a live gate "
                         "tightening; it needed the human decision, so update "
                         "this pin to certify the shipped choice, do not delete")
        self.assertNotIn('"no_symbol_found" in w', src,
                         "b112's penalty was added — see the note above")

    def test_b106_a_defaulted_symbol_still_earns_the_full_symbol_credit(self):
        # The b112 defect, shown as behaviour rather than asserted: a message
        # that never named an instrument gets +1.0 for symbol and no penalty,
        # because the inference happened BEFORE the gate looked.
        text = "خرید \n4560\nحد ضرر\n4550\nحد سود\n4590"
        sig = parse_signal(text)
        self.assertIn("symbol_defaulted_xauusd", sig.warnings)
        d = sig.to_dict()
        self.assertEqual(d["symbol"], "XAUUSD")
        from engines.signal_decision import evaluate_signal
        dec = evaluate_signal(
            d, {"bias": "bullish"},
            {"trade_allowed": True, "regime": "normal", "open_positions": 0},
            macro_filter={"allowed": True})
        self.assertIn("high_confidence", dec["reasons"])
        self.assertNotIn("parser:symbol_defaulted_xauusd", dec["reasons"],
                         "b112 shipped the penalty — update this pin to expect "
                         "it, do not delete it (b102 rule)")

    @staticmethod
    def _journal():
        # WP1: the live signals journal is no longer tracked in git (live
        # state restores from the offsite backup, not the repo). Same guard
        # as the sibling census test above — a checkout without a journal
        # skips instead of erroring.
        _p = os.path.join(ROOT, "data", "signals", "signals_log.json")
        if not os.path.exists(_p):
            raise unittest.SkipTest("no signals journal on this checkout")
        with open(_p) as fh:
            return json.load(fh)


class TestB106UnusedFieldCensus(unittest.TestCase):
    def test_b106_the_five_uncosumed_fields_are_still_emitted_on_purpose(self):
        # b106's other half: these are parsed, emitted, and read by nobody
        # downstream. They stay (b72 wants the evidence to accumulate, and
        # radin_replay feeds the same dict to the same gate), but the census is
        # pinned so a future round can decide with the list instead of
        # rediscovering it. If one gains a consumer, this test fires and the
        # census gets updated deliberately.
        uncosumed = {"entries", "tp2", "tps", "ladder_rr", "order_type"}
        self.assertTrue(uncosumed <= TO_DICT_KEYS)
        prod = []
        for dp, dn, fn in os.walk(ROOT):
            if any(x in dp for x in ("/.git", "__pycache__", "/logs", "/data",
                                     "legacy_", "/tests", "/scripts")):
                continue
            for f in fn:
                if f.endswith(".py"):
                    prod.append(os.path.join(dp, f))
        for key in sorted(uncosumed):
            readers = []
            for p in prod:
                if p.endswith("signal_parser.py"):
                    continue
                with open(p) as fh:
                    src = fh.read()
                if re.search(r'(?:parsed|signal|sig|s)\.(?:get\(\s*|[\[\s]*[\'"])'
                             + key + r'[\'"]', src):
                    readers.append(os.path.relpath(p, ROOT))
            self.assertEqual(readers, [],
                             f"{key} gained a consumer ({readers}) — update "
                             "b106's census note in the backlog with who reads "
                             "it and why")


if __name__ == "__main__":
    unittest.main(verbosity=2)
