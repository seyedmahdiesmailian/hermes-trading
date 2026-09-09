"""b193 contract: ONE bias-merge definition, enforced on BOTH the live plan
path and the lab funnel.

b188(a) shipped the stale-at-birth veto inside hermes_runtime.build_live_plan
only. engines/backtest_real.strategy_signal carried its own hand-copy of the
same merge block and never copied the veto, so from 0e44f76 onward the lab priced
exp_R on a funnel live cannot emit: measured on the cached M15 leg, 112 of 1705
directional lab contexts (6.6%) were stale-at-birth and 11 of 523 emitted
signals (2.1%) came from them. Every one would have been forced neutral live.
That is the b189 defect class running in the opposite direction (b189 was the
lab missing the live TRIGGER; this was the lab missing the live REJECT).

Fix: engines.plan.apply_smc_merge holds the merge + veto; build_live_plan and
strategy_signal each call it. These pins fail if anyone re-inlines either copy.
"""
import inspect
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engines import plan as plan_mod            # noqa: E402
from engines.plan import apply_smc_merge, stale_at_birth  # noqa: E402


def _fresh_ctx(bias="bullish", regime="trend", inv=3900.0):
    return {"bias": bias, "invalidation": inv,
            "quality": {"regime": regime}, "context": {}, "zones": {}}


def _merged(bias="bearish", conf=0.9):
    return {"bias": bias, "confidence": conf, "action": "enter",
            "smc_source": {"poi": 3910.0, "signal": "BOS"}}


class TestSharedSeam(unittest.TestCase):
    def test_live_path_calls_the_seam(self):
        import hermes_runtime
        src = inspect.getsource(hermes_runtime.build_live_plan)
        self.assertIn("apply_smc_merge(", src)
        # no re-inlined copy of the range-kill predicate left behind
        self.assertNotIn("classic_regime ==", src)
        self.assertNotIn("smc_confidence <", src)

    def test_lab_funnel_calls_the_seam(self):
        import engines.backtest_real as br
        src = inspect.getsource(br.strategy_signal)
        self.assertIn("apply_smc_merge(", src)
        self.assertNotIn("classic_regime ==", src)
        self.assertNotIn("smc_confidence <", src)

    def test_runtime_predicate_is_the_same_object(self):
        import hermes_runtime
        self.assertIs(hermes_runtime._stale_at_birth, stale_at_birth,
                      "two copies of the veto is exactly the b193 defect")

    def test_range_kill_threshold_is_one_constant(self):
        self.assertEqual(plan_mod.RANGE_KILL_CONF, 0.35)
        sig = inspect.signature(apply_smc_merge)
        self.assertEqual(sig.parameters["range_kill_conf"].default,
                         plan_mod.RANGE_KILL_CONF)
        import engines.backtest_real as br
        self.assertEqual(
            inspect.signature(br.run_backtest).parameters[
                "range_kill_conf"].default, plan_mod.RANGE_KILL_CONF)


class TestMergeBehaviour(unittest.TestCase):
    """The merged block must be byte-equivalent to what build_live_plan always
    did, plus the veto now reaching the lab."""

    def test_stale_bias_flip_is_forced_neutral(self):
        # classic bullish, invalidation 3900 (under price 3950 - a FRESH long).
        # SMC flips the bias to bearish; the stop is now on the wrong side of
        # price (close 3950 >= inv 3900) -> the bearish plan is born dead.
        # This is the flip geometry that made live rejections: any merge-driven
        # flip lands the stale check on the classic swing level.
        ctx = _fresh_ctx(bias="bullish", inv=3900.0)
        fired = apply_smc_merge(ctx, _merged("bearish", 0.9), entry_close=3950.0)
        self.assertTrue(fired)
        self.assertEqual(ctx["bias"], "neutral")
        self.assertTrue(ctx["quality"]["stale_at_birth"])

    def test_fresh_bias_flip_survives(self):
        # flip to bearish with price BELOW the classic bullish invalidation -
        # the level is now on the correct side -> no veto.
        ctx = _fresh_ctx(bias="bullish", inv=3900.0)
        fired = apply_smc_merge(ctx, _merged("bearish", 0.9), entry_close=3890.0)
        self.assertFalse(fired)
        self.assertEqual(ctx["bias"], "bearish")

    def test_same_bias_no_flip_fresh(self):
        ctx = _fresh_ctx(bias="bullish", inv=3900.0)
        fired = apply_smc_merge(ctx, _merged("bullish", 0.9), entry_close=3950.0)
        self.assertFalse(fired)
        self.assertEqual(ctx["bias"], "bullish")

    def test_range_kill_still_wins_over_merge(self):
        ctx = _fresh_ctx(regime="range")
        apply_smc_merge(ctx, _merged("bullish", 0.2), entry_close=3950.0,
                        smc_result={"x": 1})
        self.assertEqual(ctx["bias"], "neutral")
        self.assertEqual(ctx["quality"]["smc_confidence"], 0.2)
        self.assertEqual(ctx["context"]["smc"], {"x": 1})
        self.assertNotIn("stale_at_birth", ctx["quality"])

    def test_live_only_stamps_are_absent_when_smc_result_omitted(self):
        lab = _fresh_ctx(regime="range")
        apply_smc_merge(lab, _merged("bullish", 0.2), entry_close=3950.0)
        self.assertNotIn("smc", lab["context"])
        self.assertNotIn("smc_poi", lab["quality"])
        self.assertNotIn("merged", lab["context"])

    def test_live_stamps_are_written_when_smc_result_given(self):
        live = _fresh_ctx(regime="range")
        apply_smc_merge(live, _merged("bullish", 0.2), entry_close=3950.0,
                        smc_result={"poi": 1})
        self.assertEqual(live["context"]["smc"], {"poi": 1})
        self.assertIn("merged", live["context"])
        self.assertNotIn("smc_result", live["context"]["merged"])

    def test_junk_close_fails_open_on_merged_bias(self):
        ctx = _fresh_ctx(bias="bullish", inv=3900.0)
        apply_smc_merge(ctx, _merged("bullish", 0.9), entry_close=0.0)
        self.assertEqual(ctx["bias"], "bullish")
        self.assertNotIn("stale_at_birth", ctx["quality"])

    def test_entry_close_handles_both_row_shapes(self):
        self.assertEqual(plan_mod._entry_close(
            [{"close": 10.0}, {"close": 260.5}]), 260.5)
        self.assertEqual(plan_mod._entry_close(
            [[0, 1, 2, 261.0]]), 261.0)
        self.assertEqual(plan_mod._entry_close([]), 0.0)
        self.assertEqual(plan_mod._entry_close([{"Close": 7}]), 7.0)


class TestLabFunnelEndToEnd(unittest.TestCase):
    """The veto must actually bite INSIDE strategy_signal (lab path), not just
    exist as a function. We pin the ctx that reaches build_plan_from_context:
    if the merged bias is stale against the bar close, the lab must hand the
    plan builder a NEUTRAL ctx stamped stale_at_birth — exactly what
    build_live_plan does since b188(a)."""

    def _run_lab(self, ctx_bias, inv, close, merged_bias):
        import engines.backtest_real as br
        seen = {}

        def fake_ctx(*a, **k):
            return {"bias": ctx_bias, "invalidation": inv,
                    "quality": {"regime": "trend"}, "context": {},
                    "zones": {}, "swing_high": inv + 5, "swing_low": inv - 5}

        orig = (br.build_plan_context, br.smc_analyse,
                br.merge_smc_with_classic, br.build_plan_from_context)
        try:
            br.build_plan_context = fake_ctx
            br.smc_analyse = lambda *a, **k: {"bias": merged_bias}
            br.merge_smc_with_classic = lambda c, s: {
                "bias": s["bias"], "confidence": 0.9, "action": "enter",
                "smc_source": {}}
            br.build_plan_from_context = lambda ctx, now=None: (
                seen.update({"bias": ctx["bias"],
                             "stale": (ctx.get("quality") or {})
                             .get("stale_at_birth")}),
                None)[-1]
            row = {"time": 1700003600, "open": close, "high": close,
                   "low": close, "close": close}
            entry = [{"time": 1700000000 + 300 * i, "open": 100.0,
                      "high": 101.0, "low": 99.0, "close": close}
                     for i in range(200)]
            h1 = [{"time": 1700000000 + 3600 * i, "open": 100.0, "high": 101.0,
                   "low": 99.0, "close": close} for i in range(85)]
            h4 = h1[:85]
            br.strategy_signal(row, h1, h4, 150, m15_window=entry[:151],
                               m5_rows=entry[:151])
        finally:
            (br.build_plan_context, br.smc_analyse,
             br.merge_smc_with_classic, br.build_plan_from_context) = orig
        return seen

    def test_lab_veto_fires_on_stale_bearish_flip(self):
        # classic bullish, SMC flips bearish, close ABOVE the long
        # invalidation -> the bearish plan is born dead -> neutral.
        seen = self._run_lab("bullish", 4000.0, 4001.0, "bearish")
        self.assertEqual(seen.get("bias"), "neutral", seen)
        self.assertTrue(seen.get("stale"), seen)

    def test_lab_allows_fresh_flip(self):
        # same flip but close is BELOW the invalidation -> bearish thesis is
        # alive -> bias must pass through untouched (anti-vacuity).
        seen = self._run_lab("bullish", 4000.0, 3990.0, "bearish")
        self.assertEqual(seen.get("bias"), "bearish", seen)
        self.assertIsNone(seen.get("stale"), seen)


if __name__ == "__main__":
    unittest.main()
