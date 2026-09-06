"""b109 — the backtest's trade dict does NOT satisfy the contract of the LIVE
partial-close function, so the "live-parity ladder" is a constant.

Found by b108 while re-reading the ladder call path. `engines/lab_harness.LADDER`
advertises live parity by passing the REAL live function:

    partial_share_fn=lambda t: _partial_close_fraction(t)

and `engines/backtest.py` (b55 "parity fix" comment) says it passes the WHOLE
trade dict precisely so that function can read "grade AND momentum/rr/structure
from it". It cannot. The two contracts do not overlap:

  live  hermes_runtime builds: setup_grade, momentum_strength, rr_remaining,
                               structure_state, entry_price, ...
  back  engines/backtest builds: grade, style, side, entry, sl, tp, ...
                                 (NO setup_grade, NO momentum_strength,
                                  NO rr_remaining, NO structure_state)

`_partial_close_fraction` reads `setup_grade` (defaults "B" -> rank 2),
`momentum_strength` (defaults 0.5), `rr_remaining` (defaults 0.0) and
`structure_state` (defaults "healthy"). With rr_remaining=0.0 the third
condition `rr_remaining <= 1.2` is ALWAYS true, so the function returns
(1.0, "weak_full_exit_at_tp1") on every single call, whatever the trade is.

Measured on the cached 3000 M15 funnel: 935 calls to the live function, share
distribution {1.0: 935}, reason distribution {'weak_full_exit_at_tp1': 935} —
including the 84 A-grade signals, which live would route to the balanced lane
(and, if momentum/structure agreed, to the 0.3 strong-runner lane).

WHY THIS IS NOT FIXED HERE (and is filed as b109 instead):
1. The NUMBERS are unaffected today. Live returns 1.0 for both the weak and
   the balanced lanes; only the strong-runner lane (grade A + momentum>=0.8 +
   rr>=2 + healthy) returns 0.3, and b55 recorded that it has NEVER fired live
   (0 occurrences in execution_log — re-confirmed here: 0 occurrences anywhere
   in data/ or logs/). So the constant-1.0 degeneration currently agrees with
   live behaviour by luck, not by construction.
2. Making it honest means widening the model: `strategy_signal` would have to
   emit setup_grade/momentum_strength/structure_state from the plan, and the
   A-grade population (84 signals cached) would start taking a 0.3 runner leg
   the funnel has never been measured with. That is a re-measurement of every
   b68/b80/b81/b108 number, i.e. its own round — not a side effect of this one.

These tests pin the MISMATCH as a fact, in both directions: the keys the
backtest supplies, the keys the live function reads, and the resulting
constant. When b109 ships, the constant tests must be EDITED to expect the
real lane split (b102's rule: edited, not deleted).
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engines.trade_management import _partial_close_fraction  # noqa: E402


# The keys engines/backtest.py actually puts in the dict it hands to
# partial_share_fn (see open_trade = {...} in that file).
BACKTEST_TRADE_KEYS = {"entry_index", "side", "entry", "sl", "orig_sl", "tp",
                       "be_moved", "partial_taken", "realized", "style",
                       "grade"}


class TestB109ContractMismatch(unittest.TestCase):
    def test_b109_the_live_ladder_reads_keys_the_backtest_never_sets(self):
        for field in ("setup_grade", "momentum_strength", "rr_remaining",
                      "structure_state"):
            self.assertNotIn(
                field, BACKTEST_TRADE_KEYS,
                f"{field} is now supplied by engines/backtest — b109 shipped "
                "or is being shipped: EDIT this test to expect the real lane "
                "split, do not delete it (b102 rule)")

    def test_b109_the_backtest_grade_key_is_invisible_to_the_live_fn(self):
        # The live fn reads setup_grade; the backtest dict carries `grade`.
        # Proof by behaviour: an A-grade trade and a C-grade trade must
        # produce the same share, because the function cannot see the grade.
        a = {"side": "BUY", "entry": 100.0, "sl": 98.0, "tp": 104.0,
             "grade": "A"}
        c = dict(a, grade="C")
        self.assertEqual(_partial_close_fraction(a)[0],
                         _partial_close_fraction(c)[0],
                         "the share function now discriminates on the "
                         "backtest's `grade` key — b109 is partly fixed; "
                         "update this pin")

    def test_b109_the_ladder_degenerates_to_a_constant_share_of_one(self):
        # rr_remaining defaults to 0.0, which trips `<= 1.2` unconditionally.
        shapes = ({"side": "BUY", "entry": 100.0, "sl": 98.0, "tp": 104.0,
                   "grade": "A"},
                  {"side": "SELL", "entry": 100.0, "sl": 102.0, "tp": 96.0,
                   "grade": "B", "style": "aggressive_breakout"},
                  {"side": "BUY", "entry": 100.0, "sl": 99.0, "tp": 106.0,
                   "grade": "A", "momentum_strength": 0.95,
                   "structure_state": "healthy"})
        for t in shapes:
            share, reason = _partial_close_fraction(t)
            self.assertEqual(share, 1.0,
                             f"a backtest-shaped dict now yields a runner "
                             f"lane ({share}, {reason}) — b109 changed the "
                             "model; re-measure the funnel before quoting "
                             "any exp_R")
            self.assertEqual(reason, "weak_full_exit_at_tp1")

    def test_b109_the_live_shape_would_take_a_different_lane(self):
        # The other half of the pin: the SAME function on a dict shaped like
        # hermes_runtime's DOES branch. So the constant above is a contract
        # failure, not a dead function.
        live_strong = {"side": "BUY", "entry_price": 100.0, "sl": 98.0,
                       "setup_grade": "A", "momentum_strength": 0.9,
                       "rr_remaining": 2.0, "structure_state": "healthy"}
        share, reason = _partial_close_fraction(live_strong)
        self.assertEqual(share, 0.3)
        self.assertEqual(reason, "strong_runner_keep_more")

    def test_b109_harness_still_claims_live_parity_by_import(self):
        # lab_harness must keep importing the real function (that part of the
        # parity claim is true and must not regress into a restated literal).
        from engines import lab_harness as lh
        src = inspect.getsource(lh)
        self.assertIn("from engines.trade_management import "
                      "_partial_close_fraction", src)

    def test_b109_the_key_list_matches_the_backtest_source(self):
        # BACKTEST_TRADE_KEYS must not rot into a restated literal: derive it
        # from engines/backtest.py's own open_trade dict via AST.
        path = os.path.join(ROOT, "engines", "backtest.py")
        with open(path) as f:
            tree = ast.parse(f.read())
        found = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                keys = {k.value for k in node.keys
                        if isinstance(k, ast.Constant)}
                if {"entry_index", "orig_sl", "partial_taken"} <= keys:
                    found = keys
                    break
        self.assertIsNotNone(found, "open_trade dict shape not found in "
                                    "engines/backtest.py — the engine was "
                                    "restructured; re-read b109")
        self.assertEqual(found, BACKTEST_TRADE_KEYS,
                         "the backtest trade dict changed keys — if the live "
                         "fields were added, b109 is fixed: EDIT the constant "
                         "tests above, do not delete them")


class TestB109EvidenceFromTheLedger(unittest.TestCase):
    def test_b109_the_funnel_emits_a_grade_the_ladder_cannot_see(self):
        # The A-grade population is what b109 would newly route to a runner
        # lane, so its size is the blast radius. Pinned from the b108 ledger's
        # own funnel row rather than re-running the signal path.
        led = os.path.join(ROOT, "data", "backtest",
                           "b108_rescore_corrected.json")
        with open(led) as f:
            d = json.load(f)
        self.assertIn("cached", d)
        # graded funnel trades exist on every leg, and the ungraded book is
        # bigger — i.e. the funnel really does emit multiple grades.
        for leg in ("cached", "W1", "W2", "W3", "W4"):
            self.assertGreater(d[leg]["funnel_ungraded"]["trades"],
                               d[leg]["funnel_graded"]["trades"],
                               f"{leg}: the C-grade population vanished — "
                               "the grade gate or the funnel changed; re-read "
                               "b80/b108")


if __name__ == "__main__":
    unittest.main()
