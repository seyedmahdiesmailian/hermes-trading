"""b140 — the signal lane must see the real account regime, on BOTH legs.

What this test locks (the census findings, as executable assertions):
  1. WIRING: every regime risk.assess_account_policy can emit reaches the
     scorer (evaluate_signal) with its REAL name — the pre-b140 code hardcoded
     "normal", so a locked account scored as if healthy. Measured through the
     real run_signal_check lane by spying on the call sites, never by restating
     the literal (b136/b137 template).
  2. OBSERVABLES: locked regimes send ZERO orders; defensive/recovery shrink
     the lot below the normal-regime lot. Tightening only — no assertion here
     may ever demand a LARGER lot or a green light.
  3. FAIL-CLOSED: if the regime cannot be computed, the scorer is given
     trade_allowed=False (b29 discipline), never a silent "normal".
  4. self_check() catches a frozen ledger whose wiring drifted (mutation).

Tests 1-2 run the real lane (temp HERMES_DATA_ROOT, fake bridge, no order
endpoint reachable). The lane run is ~1s per arm, so it happens ONCE in
setUpClass and every test reads the frozen ledger.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import b140_signal_lane_regime_census as C  # noqa: E402
# Bind hermes_runtime BEFORE any emitter patch: it does
# `from engines.risk import assess_account_policy` at import time, so if the
# first import happened while the patch was live, the SIZER's binding would be
# the bomb too and the fail-closed test would blow up the warm-up instead of
# proving the scorer's isolation.
import hermes_runtime  # noqa: E402,F401


class EmitterDiscovery(unittest.TestCase):
    """The arms must cover the emitter's FULL output range (b109)."""

    def test_arms_cover_every_emittable_regime(self):
        names = set(C.emittable_regimes())
        self.assertIn("normal", names)
        self.assertIn("locked", names)
        self.assertIn("defensive", names)
        self.assertIn("recovery", names)
        covered = {C.real_policy(a)["regime"] for a in C.arms()}
        self.assertEqual(covered, names,
                         f"regimes with no arm: {names - covered}")

    def test_normal_arm_is_actually_normal(self):
        pol = C.real_policy({"equity": C.BALANCE, "margin": 0.0,
                             "margin_free": C.BALANCE, "deals": []})
        self.assertEqual(pol["regime"], "normal")
        self.assertTrue(pol["trade_allowed"])


class LaneSeesRealRegime(unittest.TestCase):
    """Findings 1+2, measured through the real lane (runs once)."""

    @classmethod
    def setUpClass(cls):
        cls.rows = C.main()          # writes the ledger, same as __main__
        cls.d = cls.rows["derived"]

    def _arm(self, label):
        return next(a for a in self.rows["arms"] if a["label"] == label)

    def test_scorer_is_given_the_real_regime_on_every_arm(self):
        self.assertEqual(self.d["scoring_blind_arms"], [],
                         f"blind arms: {self.d['scoring_blind_arms']}")
        for a in self.rows["arms"]:
            self.assertEqual(a["scorer_view_regime"],
                             a["real_policy"]["regime"], a["label"])

    def test_locked_arms_block_the_lane(self):
        for label in ("locked_dd", "locked_margin"):
            s = self.d["sizing"][label]
            self.assertEqual(s["regime"], "locked", label)
            self.assertTrue(s["blocked"], f"{label} sent orders while locked")
            self.assertIsNone(s["lot"], f"{label} produced a lot while locked")
        self.assertTrue(self.d["sizing_blocks_locked"])

    def test_tight_regimes_shrink_the_lot(self):
        self.assertTrue(self.d["sizing_shrinks_tight"])
        for label in ("defensive_streak", "defensive_daily_loss", "recovery_dd"):
            s = self.d["sizing"][label]
            self.assertIsNotNone(s["lot"], label)
            self.assertLess(s["lot"], s["normal_lot"],
                            f"{s['regime']} did not shrink {label}")

    def test_normal_arm_still_trades_full_size(self):
        """Tightening must not have broken the healthy path."""
        s = self.d["sizing"]["normal"]
        self.assertEqual(s["regime"], "normal")
        self.assertEqual(s["lot"], s["normal_lot"])
        self.assertEqual(s["orders_sent"], 1)

    def test_ledger_self_check_is_clean(self):
        self.assertEqual(self.rows["_self_check_problems"], [])

    def test_executor_by_name_cross_check(self):
        by = {r["regime"]: r for r in self.rows["executor_by_name"]}
        for name in C.AE.STOP_TRADING_REGIMES:
            if name in by:
                self.assertFalse(by[name]["execute"], name)
        for name in C.AE.TIGHT_REGIMES:
            if name in by and by[name]["execute"]:
                self.assertTrue(by[name]["tight"], name)


class FailClosedOnRegimeError(unittest.TestCase):
    """Finding 3, end-to-end: an uncomputable regime must reach the scorer as
    a BLOCKING policy_error, never a silent "normal". The b140 block does a
    lazy `from engines.risk import assess_account_policy`, which resolves the
    module attribute at call time — so patching the module attribute steers
    the REAL check_signals path (same discipline as the census spies)."""

    def test_assess_failure_yields_policy_error_through_real_lane(self):
        import engines.risk as R

        orig = R.assess_account_policy
        arm = next(a for a in C.arms() if a["label"] == "normal")
        try:
            R.assess_account_policy = _boom
            lane = C._run_lane(arm)
        finally:
            R.assess_account_policy = orig
        saw = lane["scorer_saw"] or {}
        self.assertEqual(saw.get("regime"), "policy_error", saw)
        self.assertFalse(saw.get("trade_allowed"), saw)
        self.assertEqual(lane["orders_sent"], 0,
                         "lane traded on an uncomputable regime")


def _boom(*a, **k):
    raise RuntimeError("synthetic emitter failure")


class SelfCheckCatchesDrift(unittest.TestCase):
    """Finding 4: the ledger cannot silently rot (mutation tests)."""

    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(C.LEDGER.read_text(encoding="utf-8"))

    def test_clean_ledger_passes(self):
        self.assertEqual(C.self_check(copy.deepcopy(self.ledger)), [])

    def test_blind_again_is_caught(self):
        bad = copy.deepcopy(self.ledger)
        normal_view = {"trade_allowed": True, "regime": "normal",
                       "open_positions": 0, "balance": C.BALANCE}
        for a in bad["arms"]:
            a["scorer_view_regime"] = "normal"
            a["score_on_scorer_view"] = C.score_only(dict(normal_view))
        problems = C.self_check(bad)
        self.assertTrue(any("blind" in p for p in problems), problems)

    def test_locked_no_longer_blocks_is_caught(self):
        bad = copy.deepcopy(self.ledger)
        for a in bad["arms"]:
            if a["real_policy"]["regime"] == "locked":
                a["lane"]["orders_sent"] = 1
                a["lane"]["lot"] = 0.1
        problems = C.self_check(bad)
        self.assertTrue(problems, "drifted ledger passed self_check")

    def test_tight_no_longer_shrinks_is_caught(self):
        bad = copy.deepcopy(self.ledger)
        for a in bad["arms"]:
            if a["real_policy"]["regime"] in C.AE.TIGHT_REGIMES:
                a["lane"]["lot"] = a["lane"]["lot"]  # unchanged
        bad["arms"][1]["lane"]["lot"] = 0.1          # defensive -> full size
        problems = C.self_check(bad)
        self.assertTrue(any("shrink" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
