"""b137 — the shrink-stack census must stay reproducible and self-auditing.

What this test locks (the census findings, as executable assertions):
  1. loss_streak >= 2 charges the SAME fact twice — the regime leg (defensive
     via streak) AND the DEFCON leg (YELLOW risk_override 0.5) — so one bad
     day shrinks entry risk to 0.25x through two independent modules.
  2. The combined floor of all four dampers (learning 0.5 x style 0.5 x
     tight-regime 0.5 x defcon-yellow 0.5 = 0.0625) puts risk_pct at 0.00125,
     which sizes BELOW the broker's min meaningful lot at every stop distance
     the system has actually traded — the lane dies as a SILENT skip, not an
     alarm.
  3. self_check() catches a ledger whose wiring drifted (mutation tests).

These tests call the REAL evaluate_proposal (time gates stubbed open, learning
redirected to a temp root — same discipline as the census itself). No order
endpoint is reachable from here.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import b137_shrink_stack_census as C  # noqa: E402


class DoubleCountLive(unittest.TestCase):
    """Finding 1, reproduced against the real entry path, not the ledger."""

    def _factor(self, probe_label):
        row = next(r for r in C.size_grid() if r["probe"] == probe_label)
        return row

    def test_streak_charges_half_through_regime_and_half_through_defcon(self):
        daily_only = self._factor("tight_defensive_dailyloss")
        yellow_only = self._factor("defcon_yellow_sldom")
        both = self._factor("tight_defensive_streak")
        self.assertAlmostEqual(daily_only["combined_factor"], 0.5, places=6)
        self.assertAlmostEqual(yellow_only["combined_factor"], 0.5, places=6)
        # the same fact (loss_streak>=2) lands on BOTH legs at once:
        self.assertAlmostEqual(both["combined_factor"], 0.25, places=6)
        self.assertAlmostEqual(both["combined_factor"],
                               daily_only["combined_factor"]
                               * yellow_only["combined_factor"], places=6)

    def test_every_damper_leg_moves_the_lot(self):
        base = self._factor("base_normal")["combined_factor"]
        for leg in ("tight_defensive_dailyloss", "defcon_yellow_sldom",
                    "style_half", "learning_floor", "recovery"):
            f = self._factor(leg)["combined_factor"]
            self.assertIsNotNone(f, leg)
            self.assertLess(f, base, f"{leg} did not shrink risk — unwired?")


class FloorIsDeadLane(unittest.TestCase):
    """Finding 2: the floor kills sizing at REAL traded stop distances."""

    @classmethod
    def setUpClass(cls):
        cls.stops = [6.54, 10.16, 16.47, 42.81, 88.02]   # span of traded stops
        cls.learning = C.discover_learning_floor()
        cls.styles = C.style_coverage()
        cls.defcon = C.discover_defcon_overrides()
        cls.regimes = {"defensive": {"regime": "defensive",
                                     "measured_entry_mult": 0.5,
                                     "policy_risk_multiplier": 0.75,
                                     "trade_allowed": True, "probe": {}},
                       "normal": {"regime": "normal",
                                  "measured_entry_mult": 1.0,
                                  "policy_risk_multiplier": 1.0,
                                  "trade_allowed": True, "probe": {}}}
        grid = C.size_grid()
        hist = []
        cls.d = C.derive(grid, hist, cls.stops, cls.learning, cls.styles,
                         cls.defcon, cls.regimes)

    def test_floor_is_product_of_discovered_minimums(self):
        want = (self.learning["floor"] * self.styles["min_style_mult"] * 0.5
                * 0.5)
        self.assertAlmostEqual(self.d["floor"]["combined_factor_analytic"],
                               round(want, 8), places=8)

    def test_lane_dead_at_every_traded_stop_distance(self):
        self.assertFalse(self.d["floor"]["lane_alive_at_median"])
        self.assertEqual(len(self.d["floor"]["stops_where_lane_is_dead"]),
                         len(self.stops))

    def test_probe_and_arithmetic_agree(self):
        self.assertTrue(self.d["floor"]["probe_agrees_with_arithmetic"])

    def test_lot_for_floor_is_zero_via_real_sizing_fn(self):
        lot = C.lot_for(self.d["floor"]["risk_pct_analytic"], C.BALANCE, 10.16)
        self.assertLess(lot, 0.01)


class SelfCheckCatchesDrift(unittest.TestCase):
    """Finding 3: the ledger cannot silently rot."""

    def _ledger(self):
        d = dict(self.d)
        return d

    @classmethod
    def setUpClass(cls):
        stops = [6.54, 10.16, 16.47, 42.81]
        cls.learning = C.discover_learning_floor()
        cls.styles = C.style_coverage()
        cls.defcon = C.discover_defcon_overrides()
        cls.regimes = {"defensive": {"regime": "defensive",
                                     "measured_entry_mult": 0.5,
                                     "policy_risk_multiplier": 0.75,
                                     "trade_allowed": True, "probe": {}},
                       "normal": {"regime": "normal",
                                  "measured_entry_mult": 1.0,
                                  "policy_risk_multiplier": 1.0,
                                  "trade_allowed": True, "probe": {}}}
        cls.d = C.derive(C.size_grid(), [], stops, cls.learning, cls.styles,
                         cls.defcon, cls.regimes)

    def test_clean_ledger_passes(self):
        self.assertEqual(C.self_check(self._ledger()), [])

    def test_unwired_leg_is_caught(self):
        d = self._ledger()
        d["unwired_factors"] = ["style_risk_mult"]
        self.assertTrue(any("unwired" in p for p in C.self_check(d)))

    def test_double_count_fix_is_caught(self):
        d = self._ledger()
        d["double_count"] = dict(d["double_count"], is_double_counted=False)
        self.assertTrue(any("double-count" in p for p in C.self_check(d)))

    def test_loosened_floor_is_caught(self):
        d = self._ledger()
        d["floor"] = dict(d["floor"], lane_alive_at_median=True)
        self.assertTrue(any("ALIVE" in p for p in C.self_check(d)))

    def test_phantom_style_tag_is_caught(self):
        d = self._ledger()
        f = dict(d["factors_in_the_stack"])
        f["style_risk_mult"] = dict(f["style_risk_mult"],
                                    tagged_styles_the_plan_never_emits=["x"])
        d["factors_in_the_stack"] = f
        self.assertTrue(any("never emits" in p for p in C.self_check(d)))


class NoProductionWrites(unittest.TestCase):
    def test_learning_probe_does_not_touch_production_state(self):
        p = ROOT / "data" / "xau_plan" / "learning_state.json"
        before = p.read_bytes() if p.exists() else None
        os.environ.pop("HERMES_DATA_ROOT", None)
        C.discover_learning_floor()
        after = p.read_bytes() if p.exists() else None
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
