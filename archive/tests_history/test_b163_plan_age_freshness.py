#!/usr/bin/env python3
"""b163 — the signal lane's Check 4 bias was census-audited for PLAN AGE and
the verdict is FRESH-ALWAYS → KEEP the scoring as-is and PIN the freshness.

engines/signal_listener.check_signals feeds plan['bias'] into
signal_decision.evaluate_signal Check 4 (+2.0 aligned / -1.0 conflict /
+0.5 neutral) without an age check. b163 joined every logged signal decision
(data/signals/signals_log.json) to the plan timeline (plan_history/*.json +
current_plan.json, built on created_at, not the racing archive filenames):

    46/52 decisions joinable to a retained plan version
    max plan age at decision time: 0.2787 h   (bucket: 46/46 under 1h)
    decisions scored past the plan's own 12h expires_at: 0
    decisions scored older than the 2h cadence:            0
    old-plan +/- that were DECISIVE for the 6.0 execute floor: 0
    plan rebuild gaps over 1513 retained versions: max 0.4998h, none > 2h
    (the 6 pre-retention decisions are bounded by reassessment_log.csv:
     max bound 2.72h, and that era's max reassess gap was 2.94h — still 4x
     under expires_at)
    → verdict FRESH_ALWAYS_KEEP_PIN_TRIPWIRE

Per the brief's outcome (a) + b158's KEEP+PIN shape: NO behaviour change to
Check 4 (no bonus/penalty rewiring; expiry semantics untouched; no gate
touched). What ships instead:
  * OBSERVABILITY — every decision now records the age of the plan whose
    bias it just paid for (signal_listener.plan_age_hours → the decision's
    bias_plan_age_h / bias_plan_id), so a future cadence break (b114 drift,
    b154 inert daemon) is LOUD in the log instead of census archaeology;
  * these pins — so a future change that silently drops the recording, or
    rewrites the scoring to trust an expired plan, fails loudly.

Pins:
 1. the census ledger re-derives from its frozen rows via the producer's own
    derive() (b127 producer is wired in check_b163_derived_blocks; here the
    headline numbers quoted in the backlog note are asserted against it);
 2. plan_age_hours behaves: fresh plan → small, 3-day-old plan → >72h,
    missing/garbage created_at → None (never a silent 0);
 3. the recording is WIRED: after evaluate_signal, check_signals stamps
    bias_plan_age_h on the decision (AST pin, and a live call-through on a
    synthetic fresh plan proving the value is real, not a stub);
 4. Check 4's scoring itself is UNCHANGED by b163 (anti-vacuity: aligned vs
    conflict still differ by exactly 3.0 in score) — the KEEP means a future
    "make it neutral when stale" edit must bring new evidence, and the
    docstring at the site points to this ledger.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from engines import signal_listener, signal_decision  # noqa: E402

LEDGER = os.path.join(_ROOT, "data", "backtest",
                      "b163_plan_age_census.json")


def _load():
    with open(LEDGER) as fh:
        return json.load(fh)


class TestB163CensusLedger(unittest.TestCase):
    def test_ledger_headline_numbers(self):
        led = _load()
        self.assertEqual(led["verdict"], "FRESH_ALWAYS_KEEP_PIN_TRIPWIRE")
        self.assertEqual(led["stale_alignment_scores"], 0)
        self.assertEqual(led["stale_decisive_for_verdict"], 0)
        cov = led["decisions_on_timeline"]
        self.assertEqual(cov["n_decisions"], 46)
        self.assertLessEqual(cov["max_age_h"], 1.0)
        self.assertEqual(cov["n_past_expires_at"], 0)
        self.assertEqual(cov["n_age_gt_cadence"], 0)
        # every timeline-joined decision sits in the <1h bucket
        self.assertEqual(cov["age_buckets"]["<1h"], 46)
        # cadence evidence: no retained plan rebuild gap crossed the 2h
        # cadence or the 12h expiry
        cad = led["cadence"]
        self.assertLess(cad["max_plan_rebuild_gap_h"], 1.0)
        self.assertEqual(cad["plan_gaps_gt_cadence"], 0)
        self.assertEqual(cad["plan_gaps_gt_expiry"], 0)
        self.assertLess(led["cadence"]["max_reassess_gap_h"], 12.0)

    def test_b164_ledger_still_derives_from_its_frozen_rows(self):
        # b164 (the procedure b163 filed): the summary blocks must be
        # re-derivable from the rows the ledger SHIPPED, never re-joined
        # from the rotating live inputs. Named for b164 per b102's rule:
        # the commit that parked the procedure needs a test-name pin.
        # b127's producer check runs the same re-derivation; doing it here
        # too keeps this file self-certifying if b127's list is edited.
        from scripts import b163_plan_age_census as b163
        led = _load()
        got = b163.derive(led["rows"])
        for key in got:
            self.assertEqual(got[key], led[key], f"derive diverged: {key}")


class TestPlanAgeHelper(unittest.TestCase):
    NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)

    def test_fresh_plan_small_age(self):
        p = {"created_at": (self.NOW - timedelta(minutes=10)).isoformat()}
        self.assertAlmostEqual(signal_listener.plan_age_hours(p, self.NOW),
                               1 / 6.0, places=2)

    def test_three_day_old_plan_is_loud(self):
        p = {"created_at": (self.NOW - timedelta(hours=75)).isoformat()}
        self.assertGreater(signal_listener.plan_age_hours(p, self.NOW), 72.0)

    def test_missing_or_garbage_created_at_is_none_not_zero(self):
        self.assertIsNone(signal_listener.plan_age_hours({}, self.NOW))
        self.assertIsNone(signal_listener.plan_age_hours(
            {"created_at": "not-a-date"}, self.NOW))
        self.assertIsNone(signal_listener.plan_age_hours(None, self.NOW))

    def test_naive_created_at_treated_as_utc(self):
        naive = (self.NOW - timedelta(hours=3)).replace(tzinfo=None)
        got = signal_listener.plan_age_hours({"created_at": naive.isoformat()},
                                             self.NOW)
        self.assertAlmostEqual(got, 3.0, places=1)


class TestRecordingWired(unittest.TestCase):
    """The KEEP+PIN verdict only holds if the age is actually RECORDED."""

    def test_check_signals_stamps_the_age_on_the_decision(self):
        # AST pin: between evaluate_signal's call and _log_signal, the
        # decision dict must gain bias_plan_age_h + bias_plan_id.
        with open(os.path.join(_ROOT, "engines",
                               "signal_listener.py")) as fh:
            tree = ast.parse(fh.read())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "check_signals")
        stores = set()
        for t in ast.walk(fn):
            if (isinstance(t, ast.Assign) and len(t.targets) == 1
                    and isinstance(t.targets[0], ast.Subscript)
                    and isinstance(t.targets[0].value, ast.Name)
                    and t.targets[0].value.id == "decision"
                    and isinstance(t.targets[0].slice, ast.Constant)):
                stores.add(t.targets[0].slice.value)
        self.assertIn("bias_plan_age_h", stores)
        self.assertIn("bias_plan_id", stores)

    def test_plan_age_hours_is_used_at_the_call_site(self):
        # anti-vacuity: the helper must be CALLED inside check_signals, not
        # just defined next to it.
        with open(os.path.join(_ROOT, "engines",
                               "signal_listener.py")) as fh:
            tree = ast.parse(fh.read())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "check_signals")
        called = {c.func.id for c in ast.walk(fn)
                  if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        self.assertIn("plan_age_hours", called)

    def test_recorded_decision_carries_a_real_age(self):
        # live call-through on the production seam: plan_age_hours against
        # the REAL current_plan.json returns a sane small age (the same
        # value the lane would stamp on its next decision).
        from engines import paths
        from engines.storage import load_current_plan
        plan = load_current_plan(paths.plan_dir())
        self.assertTrue(plan, "current_plan.json must exist for the lane")
        age = signal_listener.plan_age_hours(plan)
        self.assertIsNotNone(age)
        self.assertGreaterEqual(age, 0.0)
        self.assertLess(age, 12.0,
                        f"live plan is {age}h old — past expires_at: the "
                        "cadence has broken, which is exactly what this "
                        "recording exists to catch. Re-run the census "
                        "(scripts/b163_plan_age_census.py) before relaxing.")


class TestCheck4ScoringUnchanged(unittest.TestCase):
    """KEEP means the +/- stays. A future edit that rewires Check 4 must
    re-open the measurement, not silently pass here."""

    SIG = {"symbol": "XAUUSD", "confidence": 0.8, "rr_ratio": 2.5,
           "entry": 4000.0, "sl": 3990.0, "tp": 4025.0}
    POL = {"trade_allowed": True, "regime": "normal", "open_positions": 0}

    def _score(self, bias, side):
        sig = dict(self.SIG, side=side)
        d = signal_decision.evaluate_signal(
            sig, {"bias": bias, "quality": {}}, self.POL,
            macro_filter={"allowed": True})
        return d["score"], d["verdict"]

    def test_aligned_vs_conflict_gap_is_exactly_three(self):
        aligned, _ = self._score("bullish", "BUY")
        conflict, _ = self._score("bearish", "BUY")
        self.assertAlmostEqual(aligned - conflict, 3.0, places=6)

    def test_check4_ignores_plan_age_by_design(self):
        # the scorer signature takes NO age argument (b163 deliberately kept
        # it that way; the OBSERVABILITY lives on the decision record).
        import inspect
        params = inspect.signature(
            signal_decision.evaluate_signal).parameters
        self.assertNotIn("plan_age_h", params)
        self.assertNotIn("plan", params)


if __name__ == "__main__":
    unittest.main()
