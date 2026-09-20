"""Pins for the 2026-09-19 analysis/plan profitability package.

A1 merge reads quality.regime
A2 bias flip rebuilds invalidation when zones exist
A4 ATR fallback is 5 not 20
B1 H1 swing zones
B2 confirmed pullback is NOT reanchored
B3 H4-neutral does not inherit H1/M5 bias
PD veto: no buy premium / no sell discount
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _bar(i, close, high=None, low=None, open_=None):
    return {
        "time": 1_700_000_000 + i * 300,
        "open": close if open_ is None else open_,
        "high": (high if high is not None else close + 1),
        "low": (low if low is not None else close - 1),
        "close": close,
    }


def _trend(n, start, step, bar_range=2.0):
    rows = []
    px = start
    for i in range(n):
        px = round(px + step, 2)
        rows.append(_bar(i, px, high=px + bar_range, low=px - bar_range, open_=px - step / 2))
    return rows


class HtfZonesAndBias(unittest.TestCase):
    def test_h4_neutral_does_not_inherit_lower_tf(self):
        from engines.context import build_plan_context
        # H4 flat, H1/M5 drifting down — old code would have been bearish.
        m5 = _trend(80, 4400, -0.4)
        h1 = _trend(40, 4420, -1.5, bar_range=4)
        h4 = [_bar(i, 4410 + (i % 3) * 0.1, high=4412, low=4408) for i in range(30)]
        ctx = build_plan_context(m5, h1, h4, "london")
        self.assertEqual(ctx["bias"], "neutral")
        self.assertEqual(ctx["quality"]["htf_bias"], "neutral")

    def test_h4_bullish_keeps_bullish_and_uses_h1_zones(self):
        from engines.context import build_plan_context
        m5 = _trend(80, 4300, 0.8, bar_range=3)
        h1 = _trend(30, 4200, 8, bar_range=10)
        h4 = _trend(20, 4000, 25, bar_range=15)
        ctx = build_plan_context(m5, h1, h4, "london")
        self.assertEqual(ctx["bias"], "bullish")
        z = ctx["zones"]
        self.assertEqual(z.get("zone_source"), "h1_swing")
        self.assertLess(z["long_entry_low"], z["long_entry_high"])
        self.assertLess(z["value_low"], z["value_high"])
        self.assertGreater(z["swing_high"] - z["swing_low"], 5)
        # structural stop is beyond the H1 swing, not a 12-bar M5 nick
        self.assertLess(ctx["invalidation"], z["swing_low"])


class MergeAndVeto(unittest.TestCase):
    def test_aligned_continuation_keeps_full_classic_confidence(self):
        from engines.smc import merge_smc_with_classic
        ctx = {"bias": "bearish",
               "quality": {"alignment": "aligned",
                           "regime": "breakout_continuation"}}
        merged = merge_smc_with_classic(
            ctx, {"bias": "bearish", "confidence": 0.8, "signal": "bearish",
                  "smc_weight": 1.0})
        self.assertEqual(merged["classic_source"]["confidence"], 0.7)
        self.assertEqual(merged["classic_source"]["regime"],
                         "breakout_continuation")

    def test_pd_veto_blocks_sell_in_discount(self):
        from engines.plan import apply_smc_merge
        ctx = {"bias": "bearish", "invalidation": 4500.0,
               "quality": {"regime": "breakout_continuation"},
               "context": {}, "zones": {}}
        merged = {"bias": "bearish", "confidence": 0.8, "action": "short",
                  "smc_source": {}}
        apply_smc_merge(
            ctx, merged, entry_close=4400.0,
            smc_result={"premium_discount": {"zone": "discount"}})
        self.assertEqual(ctx["bias"], "neutral")
        self.assertEqual(ctx["quality"].get("pd_veto"), "no_sell_discount")

    def test_flip_rebuilds_stop_when_zones_exist(self):
        from engines.plan import apply_smc_merge
        from engines.context import apply_bias_geometry
        ctx = {
            "bias": "bullish",
            "atr": 5.0,
            "invalidation": 3900.0,  # classic long stop BELOW price
            "quality": {"regime": "pullback_continuation"},
            "context": {},
            "zones": {
                "value_low": 3920, "value_high": 3980,
                "long_entry_low": 3900, "long_entry_high": 3920,
                "short_entry_low": 3980, "short_entry_high": 4000,
                "swing_low": 3900, "swing_high": 4000,
            },
        }
        merged = {"bias": "bearish", "confidence": 0.9, "action": "short",
                  "smc_source": {}}
        fired = apply_smc_merge(ctx, merged, entry_close=3950.0,
                                rebuild=apply_bias_geometry)
        # new bearish stop sits ABOVE the H1 swing, so 3950 is not stale
        self.assertFalse(fired)
        self.assertEqual(ctx["bias"], "bearish")
        self.assertGreater(ctx["invalidation"], 3950.0)


class SweepScoresIntoBias(unittest.TestCase):
    def test_derive_reads_direction_not_the_bool(self):
        from engines.smc import _derive_smc_bias
        eq = {"zone": "equilibrium", "quality": 0}
        # A lone bearish hunt must be enough to pick a side (score 1.5, threshold 1.0).
        bias, _ = _derive_smc_bias([], [], [], [], "bearish", "range", eq, 1.0)
        self.assertEqual(bias, "bearish")
        bias, _ = _derive_smc_bias([], [], [], [], "bullish", "range", eq, 1.0)
        self.assertEqual(bias, "bullish")
        # The pre-fix call site passed the bool `swept`. True/False never
        # equal "bullish"/"bearish", so the hunt was a no-op.
        bias, conf = _derive_smc_bias([], [], [], [], True, "range", eq, 1.0)
        self.assertEqual(bias, "neutral")
        self.assertEqual(conf, 0.0)

    def test_smc_analyse_passes_sweep_side_not_the_bool(self):
        import ast
        import inspect
        import engines.smc as smc
        src = inspect.getsource(smc.smc_analyse)
        tree = ast.parse(src)
        call = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.Call)
                    and getattr(n.func, "id", "") == "_derive_smc_bias")
        fifth = call.args[4]
        names = {n.id for n in ast.walk(fifth) if isinstance(n, ast.Name)}
        self.assertIn("sweep_side", names)
        self.assertNotIn("swept", names)


class PullbackKeepsStructure(unittest.TestCase):
    def test_in_zone_pullback_is_not_reanchored(self):
        from engines.plan import decide_execution_action
        now = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
        plan = {
            "symbol": "XAUUSD",
            "bias": "bullish",
            "atr": 5.0,
            "invalidation": 4300.0,
            "targets": [4380.0, 4400.0, 4420.0],
            "zones": {
                "long_entry_low": 4320.0, "long_entry_high": 4340.0,
                "short_entry_low": 4380.0, "short_entry_high": 4400.0,
                "value_low": 4340.0, "value_high": 4380.0,
            },
            "execution": {
                "tp_levels": [4380.0, 4400.0, 4420.0],
                "tp_shares": [0.5, 0.3, 0.2],
                "breakout_trigger": 4385.0,
                "scale_in_levels": [4340.0],
            },
            "quality": {"smc_confidence": 0.6, "regime": "pullback_continuation",
                        "alignment": "aligned", "trend_strength": 1.5},
        }
        decision = decide_execution_action(plan, price=4330.0, trigger_ok=True,
                                           now=now, m5_ok=True)
        self.assertEqual(decision["action"], "market_entry_now")
        self.assertEqual(decision["execution_style"], "pullback_continuation")
        bp = decision["blueprint"]
        self.assertFalse(bp.get("reanchored"))
        self.assertEqual(bp["sl"], 4300.0)
        self.assertEqual(bp["tp_levels"], [4380.0, 4400.0, 4420.0])

    def test_plan_atr_never_falls_back_to_20(self):
        from engines.plan import _plan_atr
        self.assertEqual(_plan_atr({}), 5.0)
        self.assertEqual(_plan_atr({"atr": 0}), 5.0)
        self.assertEqual(_plan_atr({"atr": 4.2, "quality": {"atr": 20}}), 4.2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
