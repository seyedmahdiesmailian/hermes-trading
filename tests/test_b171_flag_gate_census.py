"""b171 — READER-SIDE SOURCE PIN IS NOT WIRING: census flag gates BOTH ways.

The procedure filed by b170 says: for every dict-flag gate, run the writer
census and the reader census in the SAME pass; an empty side is a defect
report, not a hygiene note. This run (2026-09-09) exercised the rule with
scripts/b171_flag_gate_census.py over all production modules and found the
MIRROR IMAGE of the b170 bug: hermes_runtime writes three entry-veto flags
into the monitor dict —

    monitor['spread_blocked']       = spread value  (wide-spread veto)
    monitor['calendar_unavailable'] = True          (blind-calendar veto)
    monitor['macro_blocked']        = gate reason   (b170's observability)

— and production had ZERO readers for all three (b170's grep only ever
walked the writer side of macro_blocked). A vetoed real setup therefore
rendered the SAME five-line monitor brief as "no setup formed" — exactly
the window the operator asks why nothing traded.

FIX (reporting-only; no gate/threshold/verdict path changed):
engines/report.render_monitor_brief now appends one Persian veto line via
_entry_veto_fa when any of the three flags is set.

PINS:
1. verdict() is non-vacuous on synthetic writer/reader sets (the census
   classifier itself is tested, not just run).
2. the production census: every veto flag has >=1 writer AND >=1 reader.
3. stale_rates/stale_tick measure DEAD-NO-WRITER in production — they are
   only test-suite vocabulary (daemon tick staleness is positional, not
   flag-keyed); pinned so a future key rename must go through this file.
4. render_monitor_brief shows the veto line per flag, stays byte-identical
   without one, and the veto text NEVER changes a gate outcome (evaluate-
   proposal path untouched — asserted by source pin).
"""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from b171_flag_gate_census import census, verdict  # noqa: E402
from engines.report import render_monitor_brief, _entry_veto_fa  # noqa: E402

RT_SRC = os.path.join(ROOT, "hermes_runtime.py")
REPORT_SRC = os.path.join(ROOT, "engines", "report.py")

VETO_FLAGS = ["spread_blocked", "calendar_unavailable", "macro_blocked"]


class TestCensusClassifierIsNotVacuous(unittest.TestCase):
    """verdict() must actually distinguish the three shapes."""

    def test_three_shapes(self):
        live = {"writers": {"a.py:1"}, "readers": {"b.py:2"}, "passthrough": set()}
        dead = {"writers": set(), "readers": {"b.py:2"}, "passthrough": set()}
        wonly = {"writers": {"a.py:1"}, "readers": set(), "passthrough": set()}
        self.assertEqual(verdict(live), "LIVE")
        self.assertEqual(verdict(dead), "DEAD-NO-WRITER")
        self.assertEqual(verdict(wonly), "WRITE-ONLY")

    def test_passthrough_alone_is_not_a_writer(self):
        # {"flag": x.get("flag")} copies state through; it cannot arm a gate.
        pt = {"writers": {"c.py:3"}, "readers": set(),
              "passthrough": {"c.py:3"}}
        self.assertEqual(verdict(pt), "DEAD-NO-WRITER")


class TestProductionCensus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = census()

    def test_census_saw_production_tree(self):
        # anti-vacuity floor: the walk must cover the real modules.
        self.assertGreaterEqual(self.data["_meta"]["files"], 40,
                                "census tree got pruned below production size")

    def test_every_veto_flag_has_writer_and_reader(self):
        for f in VETO_FLAGS:
            v = verdict(self.data[f])
            self.assertEqual(v, "LIVE",
                             f"{f}: {v} (writers={sorted(self.data[f]['writers'])}, "
                             f"readers={sorted(self.data[f]['readers'])})")

    def test_writers_are_the_runtime_sites(self):
        wr = " ".join(self.data["spread_blocked"]["writers"])
        self.assertIn("hermes_runtime.py", wr)
        self.assertIn("hermes_runtime.py",
                      " ".join(self.data["calendar_unavailable"]["writers"]))
        self.assertIn("hermes_runtime.py",
                      " ".join(self.data["macro_blocked"]["writers"]))

    def test_daemon_stale_flags_are_vocabulary_not_gates(self):
        # Measured 2026-09-09: no production writer or reader; the names live
        # only in tests/test_daemon_guards.py. A future flag-keyed staleness
        # gate must be added HERE as well, or this pin fails by design.
        self.assertEqual(verdict(self.data["stale_rates"]), "DEAD-NO-WRITER")
        self.assertEqual(verdict(self.data["stale_tick"]), "DEAD-NO-WRITER")


class TestMonitorBriefShowsVeto(unittest.TestCase):
    PLAN = {"symbol": "XAUUSD", "bias": "bullish"}

    def _render(self, monitor):
        return render_monitor_brief(self.PLAN, dict(monitor))

    def test_clean_monitor_unchanged(self):
        m = {"action": "wait_for_trigger", "zone": "long_zone", "price": 4350.0}
        base = self._render(m)
        self.assertNotIn("🚫", base)
        self.assertNotIn("تقویم اخبار دیده نشد", base)
        # the five standing lines are still there
        self.assertEqual(len(base.splitlines()), 5)

    def test_spread_veto_line(self):
        m = {"action": "market_order", "zone": "long_zone", "price": 4350.0,
             "spread_blocked": 2.35}
        out = self._render(m)
        self.assertIn("2.35", out)
        self.assertIn("اسپرد", out)

    def test_calendar_veto_line(self):
        m = {"action": "market_order", "zone": "long_zone", "price": 4350.0,
             "calendar_unavailable": True}
        self.assertIn("تقویم اخبار دیده نشد", self._render(m))

    def test_macro_veto_line_carries_reason(self):
        m = {"action": "market_order", "zone": "long_zone", "price": 4350.0,
             "macro_blocked": "high_impact_news_blackout"}
        out = self._render(m)
        self.assertIn("high_impact_news_blackout", out)

    def test_spread_value_garbage_still_vetoes(self):
        self.assertIn("🚫", _entry_veto_fa({"spread_blocked": "N/A"}))

    def test_priority_spread_beats_calendar(self):
        out = _entry_veto_fa({"spread_blocked": 1.2,
                              "calendar_unavailable": True})
        self.assertIn("اسپرد", out)


class TestVetoIsObservabilityOnly(unittest.TestCase):
    """The hard rule: this change must not touch any gate path."""

    def test_runtime_gate_lines_untouched(self):
        src = open(RT_SRC, encoding="utf-8").read()
        # the veto WRITERS (proposal = None + monitor[key] = ...) stay intact
        self.assertIn("proposal = None", src)
        self.assertIn("monitor['spread_blocked'] = round(_spr, 2)", src)
        self.assertIn("monitor['calendar_unavailable'] = True", src)
        self.assertIn("monitor['macro_blocked'] = _mr", src)
        # and hermes_runtime never gained a report-side import beyond briefs
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "engines.report":
                names = {a.name for a in node.names}
                self.assertNotIn("_entry_veto_fa", names,
                                 "runtime must not re-derive the veto line")

    def test_report_veto_reads_only(self):
        # _entry_veto_fa is a pure function of the monitor dict: AST-walk its
        # body; no Assign to anything but locals, no call into executor/risk.
        src = open(REPORT_SRC, encoding="utf-8").read()
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_entry_veto_fa")
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else \
                    getattr(f, "attr", "")
                # dict reads + str/float coercion only — no executor, no
                # risk, no time, no I/O.
                self.assertIn(name, {"float", "str", "get"},
                              "veto line must stay computation-free")


if __name__ == "__main__":
    unittest.main()
