"""b215 — the volume_min floor must never hand back MORE risk than asked for.

THE SHAPE: compute_xau_position_size() sized the lot down from the risk
budget, then ran it through

    lot = max(volume_min, min(volume_max, round(stepped, 2)))

`min(volume_max, ...)` is a cap and is safe — capping can only reduce risk.
`max(volume_min, ...)` is a FLOOR, and a floor on a position size is a
floor on RISK: when the budget only buys 0.001 lots, rounding up to the
broker minimum silently multiplies the loss the strategy agreed to take.

Measured on the production call shape (point=0.01, $1/point/lot,
volume_min=0.01) with the floor reachable: a $500 account risking 1% behind
an $80 stop wants $5 of risk and would have been handed 0.01 lots = $80 of
risk. 16x.

WHY IT DID NOT BITE: every caller happens to pass
min_meaningful_lot >= volume_min, so `raw_lot < min_meaningful_lot` already
refused those cases one branch earlier. auto_executor passes exactly 0.01,
equal to volume_min — the two guards coincide by luck, not by design. That
coupling was undocumented and untested, so a single edit to either constant
(or one new caller passing a smaller floor) would have turned a skip into
an oversized live order with no test going red.

THE FIX: the floor refuses instead of inflating. A sizing function may
round DOWN into safety, never UP into risk.

TIGHTENING ONLY: for every caller in the tree today the behaviour is
byte-identical (proven below); the only possible change for a future caller
is a skip where there would have been an oversized lot.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engines.orchestrator import compute_xau_position_size as size  # noqa: E402

# XAUUSD production constants (engines/auto_executor.py)
POINT = 0.01
PV = 1.0          # $ per point per lot
VMIN = 0.01
VSTEP = 0.01
VMAX = 1.0


def realised_risk(lot: float, stop_price_distance: float) -> float:
    """What the position would actually lose if the stop is hit."""
    return lot * (stop_price_distance / POINT) * PV


def call(balance, risk_pct, stop, mml=0.01, vmax=VMAX):
    return size(balance=balance, risk_pct=risk_pct, stop_distance_price=stop,
                point=POINT, point_value_per_lot=PV, volume_min=VMIN,
                volume_step=VSTEP, volume_max=vmax, min_meaningful_lot=mml)


class TheFloorNeverInflatesRisk(unittest.TestCase):
    """The core invariant, stated once."""

    def test_realised_risk_never_exceeds_the_budget(self):
        checked = 0
        for stop in [s / 2 for s in range(1, 400)]:          # $0.5 .. $199.5
            for balance in (200, 500, 1000, 2000, 5000, 10000, 50000):
                for risk_pct in (0.0005, 0.0025, 0.005, 0.01, 0.02, 0.05):
                    for mml in (0.0, 0.001, 0.01, 0.05):
                        r = call(balance, risk_pct, stop, mml=mml)
                        if r["lot"] <= 0:
                            continue
                        checked += 1
                        self.assertLessEqual(
                            realised_risk(r["lot"], stop),
                            r["risk_usd"] + 0.01,
                            f"bal={balance} risk={risk_pct} stop={stop} "
                            f"mml={mml} lot={r['lot']} inflated the budget")
        self.assertGreater(checked, 1000, "anti-vacuity: grid sized nothing")

    def test_the_specific_16x_case_is_refused(self):
        """The worst measured overshoot, kept as a named regression."""
        r = call(balance=500, risk_pct=0.01, stop=80.0, mml=0.0)
        self.assertEqual(r["lot"], 0.0)
        self.assertFalse(r["meaningful"])
        self.assertEqual(r["reason"], "below_min_meaningful_lot")

    def test_a_budget_that_cannot_buy_the_broker_minimum_is_refused(self):
        """Even with every softer guard disabled."""
        for balance, stop in ((500, 80.0), (1000, 60.0), (200, 50.0)):
            r = call(balance, 0.01, stop, mml=0.0)
            self.assertEqual(r["lot"], 0.0, f"bal={balance} stop={stop}")


class ProductionBehaviourIsUnchanged(unittest.TestCase):
    """Tightening only: the live call shape must be byte-identical."""

    def test_executor_shape_still_sizes_the_same_lots(self):
        """auto_executor passes min_meaningful_lot=0.01 == volume_min, so the
        old floor was already unreachable there. Pin that it stays so."""
        expected = {10.0: 0.05, 25.0: 0.02, 50.0: 0.01}
        for stop, lot in expected.items():
            r = call(5000, 0.01, stop, mml=0.01)
            self.assertEqual(r["lot"], lot, f"stop={stop}")
            self.assertTrue(r["meaningful"])
            self.assertAlmostEqual(realised_risk(r["lot"], stop), 50.0, places=2)

    def test_normal_sizing_is_untouched(self):
        r = call(5000, 0.01, 5.0)
        self.assertGreater(r["lot"], 0.05)
        self.assertTrue(r["meaningful"])
        self.assertIsNone(r["reason"])

    def test_the_volume_max_cap_still_caps(self):
        """Capping reduces risk and must survive."""
        r = call(1_000_000, 0.05, 1.0, mml=0.0, vmax=1.0)
        self.assertEqual(r["lot"], 1.0)
        self.assertTrue(r["capped"])

    def test_invalid_inputs_still_refuse(self):
        for kwargs in ({"stop": 0.0}, {"stop": -5.0}):
            r = call(5000, 0.01, **kwargs)
            self.assertEqual(r["lot"], 0.0)
            self.assertEqual(r["reason"], "invalid_sizing_inputs")


class TheGuardsNoLongerDependOnLuck(unittest.TestCase):
    """The reason this bug was invisible: two independent constants happened
    to coincide. Make the dependency explicit so it cannot silently break."""

    def test_executor_floor_is_at_least_the_broker_minimum(self):
        src = (ROOT / "engines" / "auto_executor.py").read_text(encoding="utf-8")
        self.assertIn("min_meaningful_lot=0.01", src)
        self.assertIn("volume_min=0.01", src)

    def test_safety_no_longer_relies_on_that_coincidence(self):
        """Even if a caller drops min_meaningful_lot to zero, risk holds."""
        for stop in (30.0, 60.0, 80.0, 120.0):
            r = call(500, 0.01, stop, mml=0.0)
            if r["lot"] > 0:
                self.assertLessEqual(realised_risk(r["lot"], stop),
                                     r["risk_usd"] + 0.01)

    def test_refusal_reason_is_one_the_callers_already_handle(self):
        """auto_executor branches on 'sizing_' + reason, and b196 pins the
        exact string — a new reason would have been an unhandled path."""
        r = call(500, 0.01, 80.0, mml=0.0)
        self.assertEqual(r["reason"], "below_min_meaningful_lot")


if __name__ == "__main__":
    unittest.main()
