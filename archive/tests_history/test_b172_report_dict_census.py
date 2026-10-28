"""b172 — census the REPORT-DICT family BOTH ways (filed by b171, 2026-09-09).

b171's rule: for every flag-keyed field, run the writer census and the reader
census in the SAME pass; an empty side is a defect report, not a hygiene note.
A read-only gate is a wiring defect (b170); the mirror — a WRITE-ONLY report
key — is an observability defect: the runtime records something no human ever
sees.

This landing does three things:

1. TOOL FIX (the probe almost mis-filed itself): scripts/b171_flag_gate_census
   .py's census(flags=[...]) narrowed only the REPORTING loop — the AST walker
   kept comparing every literal against the module-level FLAGS list. A census
   over any NEW key returned all-zero writer/reader sets that READ exactly like
   "DEAD-NO-WRITER" findings but were an artifact of the tool. The walker now
   filters against the caller's wanted set. Test 1 is the RED-proof.

2. EXTENSION: FLAGS carries the report-dict family — skip_reason (the singular
   brief carrier), skip_reasons (the plural rejection list), reasons (the
   signal-lane carrier auto_executor writes and signal_listener/dashboards
   read).

3. MEASUREMENT (2026-09-09):
      skip_reason    LIVE        (3W runtime / 2R brief-append in same file)
      skip_reasons   WRITE-ONLY at filing -> FIXED same day by b185
                                  (hermes_runtime._skip_reason_detail is the
                                  reader; the LIVE pins below moved with it)
      reasons        LIVE        (35W / 8R — lane dict wired both ways)
   Pinned so a rename, a new reader, or a deletion must pass through this file.
"""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from b171_flag_gate_census import _Walk, census, verdict  # noqa: E402


class TestFlagsParameterReachesTheWalker(unittest.TestCase):
    """RED-proof of the b172 tool bug: census(flags=[NEW_KEY]) used to see
    nothing for a key outside module FLAGS — zero sets that looked exactly
    like a DEAD-NO-WRITER finding but were the walker's own filter."""

    SRC = (
        "d = {}\n"
        'd["b172_probe_key"] = 1\n'
        'x = d.get("b172_probe_key")\n'
    )

    def _walk(self, **kw):
        w = _Walk("synth.py", **kw)
        w.visit(ast.parse(self.SRC))
        return sorted(k for (_f, k, _l) in w.sites)

    def test_new_key_visible_when_flags_passed(self):
        self.assertEqual(
            self._walk(flags=["b172_probe_key"]), ["R", "W"],
            "the caller's wanted set must drive the walker (pre-b172 it "
            "returned [] — the fake DEAD-NO-WRITER artifact)")

    def test_default_walk_still_ignores_foreign_keys(self):
        self.assertEqual(self._walk(), [],
                         "without flags= the walker keeps using module FLAGS; "
                         "an unrelated literal must not be censused")


class TestReportDictFamilyCensus(unittest.TestCase):
    """The both-ways measurement over production, 2026-09-09."""

    @classmethod
    def setUpClass(cls):
        cls.data = census()

    def test_keys_are_registered_in_module_flags(self):
        from b171_flag_gate_census import FLAGS
        for k in ("skip_reason", "skip_reasons", "reasons"):
            self.assertIn(k, FLAGS,
                          f"{k} must live in the census vocabulary or every "
                          f"later run silently skips the report-dict family")

    def test_skip_reason_carrier_is_live(self):
        v = verdict(self.data["skip_reason"])
        self.assertEqual(v, "LIVE",
                         f"skip_reason: {v} — the singular reason must keep "
                         "its runtime writers AND its brief-append readers")
        self.assertIn("hermes_runtime.py",
                      " ".join(self.data["skip_reason"]["writers"]))
        self.assertIn("hermes_runtime.py",
                      " ".join(self.data["skip_reason"]["readers"]))

    def test_b185_defect_filed_with_named_pin(self):
        # b102 carrier: b185 was filed from this census and LANDED the same
        # day (hermes_runtime._skip_reason_detail is the reader). The pin
        # moved from "- [ ] b185" to "- [x] b185" together with the fix — a
        # future run that un-wires the reader must re-open the todo, not
        # silently drop this assertion.
        with open(os.path.join(ROOT, "data", "ops",
                               "autopilot_backlog.md"), encoding="utf-8") as f:
            self.assertIn("- [x] b185", f.read(),
                          "skip_reasons write-only defect was FIXED by "
                          "b185 (reader wired); it must stay closed-with-"
                          "evidence unless the reader is removed")

    def test_skip_reasons_now_live_after_b185(self):
        # b185 (2026-09-09, THIS pin flipped per b102): the WRITE-ONLY
        # measurement below stood until hermes_runtime._skip_reason_detail
        # became the reader — the plural rejection list now renders as one
        # supplementary line under '⚠️ اجرا نشد' (observability only). The
        # pin moved from WRITE-ONLY to LIVE together with the finding, and
        # tests/test_b185_skip_reasons_reader.py owns the behaviour proof.
        v = verdict(self.data["skip_reasons"])
        self.assertEqual(v, "LIVE",
                         "skip_reasons changed shape — update the backlog "
                         "finding and this pin together")
        self.assertEqual(
            sorted(os.path.basename(s.split(":")[0])
                   for s in self.data["skip_reasons"]["writers"]),
            ["hermes_runtime.py", "hermes_runtime.py"])
        self.assertTrue(self.data["skip_reasons"]["readers"],
                        "b185's reader (hermes_runtime._skip_reason_detail) "
                        "vanished — the list is write-only again; re-file the "
                        "defect, do not just edit this pin")
        self.assertTrue(
            any(s.startswith("hermes_runtime.py")
                for s in self.data["skip_reasons"]["readers"]))

    def test_reasons_lane_carrier_is_live_both_ways(self):
        d = self.data["reasons"]
        self.assertEqual(verdict(d), "LIVE")
        w_files = {os.path.basename(s.split(":")[0]) for s in d["writers"]}
        r_files = {os.path.basename(s.split(":")[0]) for s in d["readers"]}
        self.assertIn("auto_executor.py", w_files,
                      "evaluate_proposal's early returns are the writers "
                      "b170 added — losing them re-deadens the lane alert")
        self.assertTrue({"signal_listener.py", "dashboards.py"} & r_files,
                        f"lane readers vanished: {sorted(r_files)}")

    def test_census_still_covers_the_production_tree(self):
        self.assertGreaterEqual(self.data["_meta"]["files"], 40,
                                "census tree got pruned below production size")


if __name__ == "__main__":
    unittest.main()
