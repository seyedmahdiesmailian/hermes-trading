"""b185 TRADER OBSERVABILITY — skip_reasons had a producer and NO reader.

Measured by the b172 census (2026-09-09): hermes_runtime writes the plural
rejection list at :677 (macro veto) and :782 (entry vetoes, copied from
evaluate_proposal's `reasons`), and zero production files read the key — the
brief rendered only the singular skip_reason, so whenever the headline was a
translated label ('daily_loss_limit') or the veto lived on another line, the
gate CONTEXT carried by the list (the actual loss pct, the failing grade, a
fail-closed gate error's text) reached no human. Same defect class as b170's
mute Check-1 exits, one key later.

FIX (this run): hermes_runtime._skip_reason_detail is the reader — one
supplementary Persian line under '⚠️ اجرا نشد', deduped so single-gate paths
stay byte-identical. Observability only: adds strings, never removes a block
and never touches a gate/threshold/verdict/sizing path.

PINS:
1. The census verdict flipped: skip_reasons is LIVE (writers + reader in
   hermes_runtime itself).
2. Positive: a multi-gate rejection whose headline is a translated label
   DOES surface the list entry that carries the number.
3. Non-vacuity: headline-only shapes (market_closed / poor_rr / macro
   veto already printed by the monitor line) return the empty string — the
   line adds information, not noise.
4. Malformed input (None, non-list, empty entries, long junk) never raises
   and never prints an empty header.
5. Wiring pin: the call sits in the brief-build path (cycle), after the
   headline append; the function body reads only the proposal dict (AST).
"""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from hermes_runtime import _skip_reason_detail  # noqa: E402

RT_SRC = os.path.join(ROOT, "hermes_runtime.py")


class TestB185CensusFlipped(unittest.TestCase):
    """The b102 rule: the pin and the finding move together. b172's
    WRITE-ONLY pin for skip_reasons was flipped in THIS commit
    (tests/test_b172_report_dict_census.py::
    test_skip_reasons_now_live_after_b185); the census must now call the key
    LIVE or this landing is a claim."""

    def test_skip_reasons_is_now_live(self):
        from b171_flag_gate_census import census, verdict
        data = census()
        v = verdict(data["skip_reasons"])
        self.assertEqual(
            v, "LIVE",
            f"skip_reasons verdict is {v} — the reader wired by b185 "
            "vanished or the census vocabulary changed")
        readers = " ".join(data["skip_reasons"]["readers"])
        self.assertIn("hermes_runtime.py", readers,
                      "the b185 reader must live on the brief-build path")


class TestB185DetailSurfacesContext(unittest.TestCase):
    def test_daily_loss_pct_reaches_the_brief(self):
        # Headline is the translated label; only the LIST carries the number
        # (auto_executor Check 3 appends f"daily_loss_{pct:.1%}").
        proposal = {"skip_reason": "daily_loss_limit",
                    "skip_reasons": ["daily_loss_5.1%"]}
        brief = "👀 پایش\n⚠️ اجرا نشد: سقف ضرر روزانه پر شده"
        out = _skip_reason_detail(proposal, brief)
        self.assertIn("daily_loss_5.1%", out)
        self.assertTrue(out.startswith("دلایل تکمیلی:"),
                        "must render as ONE supplementary line")
        self.assertEqual(len(out.splitlines()), 1,
                         "one line only — the brief stays a list of lines")

    def test_grade_gate_failing_grade_surfaces(self):
        proposal = {"skip_reason": "setup_grade_C",
                    "skip_reasons": ["grade_C_below_minimum"]}
        brief = "⚠️ اجرا نشد: setup_grade_C"
        self.assertIn("grade_C_below_minimum",
                      _skip_reason_detail(proposal, brief))

    def test_failclosed_gate_error_text_surfaces(self):
        # b29 fail-closed returns carry the exception text in the list —
        # exactly the thing an operator needs and the headline drops.
        proposal = {"skip_reason": "cooldown_gate_error",
                    "skip_reasons": ["cooldown_error:KeyError('until')"]}
        out = _skip_reason_detail(proposal, "⚠️ اجرا نشد: cooldown_gate_error")
        self.assertIn("cooldown_error:", out)

    def test_cap_four_entries(self):
        proposal = {"skip_reason": "defcon_red_entry_blocked",
                    "skip_reasons": [f"r{i}" for i in range(9)]}
        out = _skip_reason_detail(proposal, "⚠️ اجرا نشد: x")
        self.assertEqual(out.count("·"), 3,
                         "at most 4 entries rendered (line stays readable)")


class TestB185SingleGateByteIdentical(unittest.TestCase):
    """Dedupe contract: where the headline (or the monitor veto line)
    already carries the reason, NO extra line is produced — the fix adds
    information, not noise, and cannot change any existing brief text."""

    def test_headline_equals_only_reason(self):
        p = {"skip_reason": "market_closed", "skip_reasons": ["market_closed"]}
        self.assertEqual(_skip_reason_detail(p, "⚠️ اجرا نشد: بازار تعطیل"), "")

    def test_poor_rr_already_in_headline(self):
        p = {"skip_reason": "poor_rr_1.20", "skip_reasons": ["poor_rr_1.20"]}
        self.assertEqual(_skip_reason_detail(p, "⚠️ اجرا نشد: poor_rr_1.20"), "")

    def test_macro_veto_already_on_monitor_line(self):
        # :677 writes skip_reasons=['high_impact_news_blackout'] and the
        # b171 monitor veto line already prints that exact string.
        p = {"skip_reason": "macro_blackout",
             "skip_reasons": ["high_impact_news_blackout"]}
        brief = ("⚠️ پشت‌بند اخبار: high_impact_news_blackout\n"
                 "⚠️ اجرا نشد: پشت‌بند اخبار مهم — ورود ممنوع")
        self.assertEqual(_skip_reason_detail(p, brief), "")

    def test_no_list_no_line(self):
        self.assertEqual(_skip_reason_detail({"skip_reason": "x"}, "b"), "")


class TestB185MalformedInputCannotCrash(unittest.TestCase):
    """The brief is built on EVERY skipped cycle; a render helper that
    raises would take the whole monitor step down. Feed it garbage."""

    def test_garbage_never_raises(self):
        brief = "⚠️ اجرا نشد: y"
        for bad in (None, "string", 42, {}, [None], [""], ["   "],
                    ["a" * 500], [1, 2.5], [None, "real_reason"]):
            out = _skip_reason_detail({"skip_reason": "y",
                                       "skip_reasons": bad}, brief)
            self.assertIsInstance(out, str)
        # garbage-only inputs produce NO line (no empty header)
        for bad in (None, "string", 42, {}, [None], [""], ["   "]):
            self.assertEqual(
                _skip_reason_detail({"skip_reason": "y",
                                     "skip_reasons": bad}, brief), "")


class TestB185WiringPins(unittest.TestCase):
    def test_reader_called_on_brief_build_path(self):
        src = open(RT_SRC, encoding="utf-8").read()
        self.assertIn("_skip_reason_detail(proposal, brief)", src,
                      "the reader must be called with the RENDERED brief so "
                      "the dedupe sees what the human already saw")
        # and the call must sit inside cycle()'s skip branch, after the
        # headline append — not in the helper's own definition.
        tree = ast.parse(src)
        cycle_fn = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef) and n.name == "cycle")
        called = any(isinstance(n, ast.Call)
                     and getattr(n.func, "id", "") == "_skip_reason_detail"
                     for n in ast.walk(cycle_fn))
        self.assertTrue(called, "cycle() must call the reader")

    def test_helper_reads_only_the_proposal_dict(self):
        # b171's purity pin, same shape as _entry_veto_fa: the reader must
        # stay computation-free (no gate calls, no I/O, no time).
        src = open(RT_SRC, encoding="utf-8").read()
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_skip_reason_detail")
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) \
                    else getattr(node.func, "attr", "")
                self.assertIn(name, {"str", "get", "join", "split",
                                     "append", "lower", "len", "isinstance"},
                              "detail line must stay computation-free")
        # forbid IMPORTS/globals — the reader must not reach outside its
        # arguments (local accumulator assignments are fine and expected).
        for node in ast.walk(fn):
            self.assertNotIsInstance(
                node, (ast.Import, ast.ImportFrom, ast.Global),
                msg="reader must not reach outside its arguments")

    def test_runtime_writers_untouched(self):
        # b171 pin shape: the fix is reader-side only; the two writers stay.
        src = open(RT_SRC, encoding="utf-8").read()
        self.assertIn("proposal['skip_reasons'] = [_mr]", src)
        self.assertIn("proposal['skip_reasons'] = eval_result.get('reasons', [])",
                      src)


if __name__ == "__main__":
    unittest.main()
