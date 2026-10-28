"""b262: MIN_STOP_DISTANCE vs REANCHOR_STOP_ATR_CAP contradiction.

Root cause found in production: the plan-level stop reanchor caps the stop at
REANCHOR_STOP_ATR_CAP * atr (2.0 * ATR), while the executor gate demanded an
ABSOLUTE MIN_STOP_DISTANCE of 8.0 pt. On 2026-10-07 the live master loop
logged `skip_reason: stop_too_tight` with sl_dist 5.83/5.91 against a plan
ATR of 2.9: 2*2.9 = 5.8 < 8.0, so EVERY reanchored entry was refused.

Measured on 1500 live M5 bars: 13% of windows had 2*ATR(12) < 8.0 (ATR<4.0).
The gate was dead on arrival for a large minority of the week.

The four −100$ disasters the 8.0 floor was originally derived from were
5.8–7.0 pt moves on 0.15–0.17 LOT — a position-sizing failure, not a
distance failure. Tightening distance does not fix size; it only removes
entries. The floor now scales with volatility:
    required = min(MIN_STOP_ATR_MULT * atr, MIN_STOP_DISTANCE)
so the absolute 8.0 stays as a CEILING on the required stop in volatile
markets, and the floor relaxes proportionally in quiet ones.
"""

import unittest
from engines import auto_executor


class TestB262AtrAwareStopFloor(unittest.TestCase):
    """The scaled floor must be a strict relaxation for every ATR regime."""

    MIN_STOP_DISTANCE = auto_executor.MIN_STOP_DISTANCE
    MIN_STOP_ATR_MULT = auto_executor.MIN_STOP_ATR_MULT

    def test_min_stop_atr_mult_matches_reanchor_cap(self):
        # The reanchor builds stops at exactly REANCHOR_STOP_ATR_CAP * atr.
        # If the gate's multiplier were HIGHER than the cap, the gate would
        # again refuse every reanchored stop — the very contradiction b262 fixes.
        from engines import plan as plan_mod

        self.assertLessEqual(
            self.MIN_STOP_ATR_MULT,
            plan_mod.REANCHOR_STOP_ATR_CAP,
            "gate floor multiplier must not exceed the reanchor stop cap, "
            "otherwise no reanchored stop can ever pass the gate",
        )

    def test_scaled_floor_never_exceeds_absolute(self):
        # required = min(mult*atr, abs) — the absolute value is a CEILING,
        # so the fix never makes the gate TIGHTER than it was.
        for atr in (0.5, 2.9, 4.0, 8.0, 20.0, 100.0):
            with self.subTest(atr=atr):
                required = min(self.MIN_STOP_ATR_MULT * atr, self.MIN_STOP_DISTANCE)
                self.assertLessEqual(required, self.MIN_STOP_DISTANCE)

    def test_quiet_market_relaxes_below_absolute(self):
        # The live failure case: ATR 2.9 → reanchor stop 5.8.
        # Old gate demanded 8.0 and refused; new floor must admit it.
        atr = 2.9
        required = min(self.MIN_STOP_ATR_MULT * atr, self.MIN_STOP_DISTANCE)
        self.assertLess(required, self.MIN_STOP_DISTANCE)
        reanchor_stop = 2.0 * atr  # 5.8
        self.assertGreaterEqual(reanchor_stop, required - 1e-9)

    def test_volatile_market_keeps_absolute_floor(self):
        # When 2*ATR >= 8.0 the absolute floor is binding again.
        atr = 8.0
        required = min(self.MIN_STOP_ATR_MULT * atr, self.MIN_STOP_DISTANCE)
        self.assertAlmostEqual(required, self.MIN_STOP_DISTANCE, places=6)

    # ── end-to-end through evaluate_proposal ──

    @staticmethod
    def _proposal(sl_dist: float):
        return {
            "symbol": "XAUUSD",
            "side": "sell",
            "blueprint": {
                "symbol": "XAUUSD",
                "side": "sell",
                "entry_price": 4100.0,
                "sl": 4100.0 + sl_dist,  # sell: sl above entry
                "tp": 4100.0 - 2.0 * sl_dist,
            },
        }

    @staticmethod
    def _account_policy():
        return {
            "balance": 4977.0,
            "equity": 4977.0,
            "free_margin": 4977.0,
            "margin": 0.0,
            "open_positions": 0,
            "drawdown_pct": 0.0,
            "margin_ratio": 0.0,
            "base_risk_pct": 1.0,
            "risk_multiplier": 1.0,
            "trade_allowed": True,
            "regime": "stable",
            "reasons": [],
        }

    @staticmethod
    def _perf():
        return {
            "day": "2026-10-07",
            "starting_balance": 4977.0,
            "daily_pnl": 0.0,
            "daily_gross_pnl": 0.0,
            "pnl_basis": "deals",
            "loss_streak": 0,
            "trades_today": 0,
            "last_closed_ticket": 0,
            "recent_closed": [],
        }

    def _evaluate(self, sl_dist, atr):
        return auto_executor.evaluate_proposal(
            proposal=self._proposal(sl_dist),
            account_policy=self._account_policy(),
            performance_state=self._perf(),
            plan={"atr": atr, "bias": "bearish"},
            bridge=None,
        )

    def test_gate_admits_reanchored_stop_in_quiet_market(self):
        # ATR 2.9 → reanchor stop 5.8; the OLD gate returned stop_too_tight.
        out = self._evaluate(sl_dist=5.8, atr=2.9)
        self.assertNotEqual(out.get("reason"), "stop_too_tight")

    def test_gate_still_rejects_absurdly_tight_stop(self):
        # A 0.5pt stop must still be refused — the floor is a floor.
        out = self._evaluate(sl_dist=0.5, atr=2.9)
        self.assertEqual(out.get("reason"), "stop_too_tight")

    def test_gate_rejects_tight_stop_in_volatile_market(self):
        # ATR 8.0 → required 8.0; a 5.0pt stop is noise.
        out = self._evaluate(sl_dist=5.0, atr=8.0)
        self.assertEqual(out.get("reason"), "stop_too_tight")

    def test_missing_atr_falls_back_to_absolute_floor(self):
        # plan['atr'] absent → absolute floor, unchanged legacy behaviour.
        out = self._evaluate(sl_dist=5.0, atr=None)
        self.assertEqual(out.get("reason"), "stop_too_tight")


if __name__ == "__main__":
    unittest.main()
