"""b198 — tests for the reassess flip census (b188(c) resolution).

Pins three things:
1. The ledger's headline blocks are EXACTLY re-derivable from the frozen rows
   embedded in the artifact (b164 rule — the same check b127 runs).
2. The b188(c) verdict: the loop is NOT sticky; the "never reverses" claim was
   an event-matrix artifact — reversals go through neutral.
3. The two consumer facts the fix options hinged on, verified against the
   shipped code (AST), not the docstring: the plan lane places no resting
   orders, and the plan lane rebuilds zones every cycle.
"""
from __future__ import annotations

import ast
import json
import os
import unittest
from pathlib import Path

import sys
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from scripts import b198_reassess_flip_census as b198  # noqa: E402

LEDGER = os.path.join(_ROOT, "data", "backtest",
                      "b198_reassess_flip_census.json")


def _load():
    with open(LEDGER, encoding="utf-8") as fh:
        return json.load(fh)


class TestB198Derive(unittest.TestCase):
    def test_b198_derive_reproduces_frozen_ledger(self):
        led = _load()
        got = b198.derive(led["rows"])
        for key in ("n_events", "transition_matrix", "noop_pct",
                    "direct_flips", "n_episodes",
                    "n_directional_episodes",
                    "episode_reversals_via_neutral", "reversal_events",
                    "run_stats", "dir_run_median_events",
                    "sticky_per_b188c", "flickering"):
            self.assertEqual(got[key], led[key],
                             f"b198 producer no longer reproduces {key}")

    def test_b198_row_arithmetic_self_consistent(self):
        led = _load()
        rows = led["rows"]
        self.assertEqual(led["n_events"], len(rows))
        self.assertEqual(sum(led["transition_matrix"].values()), len(rows))
        # episodes counted from rows == episode count in the ledger
        self.assertEqual(len(b198.episodes(rows)), led["n_episodes"])

    def test_b198_verdict_not_sticky_reversals_exist(self):
        led = _load()
        self.assertFalse(led["sticky_per_b188c"],
                         "census says loop is NOT sticky — b188(c) premise")
        self.assertGreaterEqual(led["episode_reversals_via_neutral"], 10)
        self.assertEqual(led["direct_flips"], 1,
                         "the ONE direct flip b188(c) quoted is real")
        self.assertTrue(led["flickering"],
                        "median directional run is 2 events — flicker, not "
                        "stickiness; 82% of log rows are no-ops")

    def test_b198_noop_rows_dominant(self):
        led = _load()
        # b188(c)'s option "cut reassess to hourly" was pitched as log-noise
        # relief; the noise IS the 82% no-op rows — recorded, not judged here.
        self.assertGreater(led["noop_pct"], 70.0)


class TestB198ConsumerFacts(unittest.TestCase):
    """The fix options assumed two consumers of bias flips. Neither exists in
    the plan lane — verified against the shipped source, not the prose."""

    def _calls_in(self, path):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name):
                    names.add(f.id)
                elif isinstance(f, ast.Attribute):
                    names.add(f.attr)
        return names

    def test_b198_plan_lane_places_no_resting_orders(self):
        # place_signal_limit is called ONLY from the signal lane
        # (engines/signal_listener.py) — never from hermes_runtime, so a
        # plan-lane bias flip has no pending order to invalidate.
        rt = self._calls_in(os.path.join(_ROOT, "hermes_runtime.py"))
        self.assertNotIn("place_signal_limit", rt)
        self.assertNotIn("cancel_order", rt)
        sl = self._calls_in(os.path.join(
            _ROOT, "engines", "signal_listener.py"))
        self.assertIn("place_signal_limit", sl)

    def test_b198_reassess_rebuilds_zones(self):
        # cycle(): the reassess branch calls build_live_plan, which rebuilds
        # zones from fresh M5/H1/H4 — flips re-anchor zones by construction.
        src = Path(os.path.join(_ROOT, "hermes_runtime.py")).read_text(
            encoding="utf-8")
        i = src.index("if step in {'plan', 'reassess'}:")
        j = src.index("else:\n        plan_brief", i)
        block = src[i:j]
        self.assertIn("build_live_plan(bridge, now)", block)

    def test_b198_census_is_read_only(self):
        # no bridge import, no order endpoint names in the census script
        src = open(os.path.join(_ROOT, "scripts",
                                "b198_reassess_flip_census.py"),
                   encoding="utf-8").read()
        self.assertNotIn("bridge", src.split('"""')[2])  # after docstring
        for w in ("open_position", "close_position", "modify", "requests"):
            self.assertNotIn(w, src.split('"""')[2])


if __name__ == "__main__":
    unittest.main()
