"""Professional-trader risk: Asia half-size + hard lot ceiling.

Live book (data/xau_plan, 34 positions, net -102$):
  * 16/29 filled entries opened 00-07 UTC (the runtime's 'asia' bucket).
  * 5 of 8 fat losses (net < -40$) opened in that window.
  * The four worst (-106/-104/-100/-95) sized 0.15-0.17 lots on ~6$ stops.

Half Asia, cap lot at 0.10. Tightening only: London/NY and missing session
stay 1.0; a 10$ stop at 2%/5k still prints 0.10.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines import auto_executor as AE
from engines import cooldown as CD


def _pol(balance=5000.0):
    return {"trade_allowed": True, "regime": "normal",
            "open_positions": 0, "balance": balance}


def _prop(sl=4460.0, tp=4435.0):
    return {"blueprint": {"side": "SELL", "entry_price": 4450.0,
                          "sl": sl, "tp": tp, "symbol": "XAUUSD"},
            "grade": "B"}


def _perf():
    return {"day": datetime.now(timezone.utc).date().isoformat(),
            "daily_pnl": 0.0, "trades_today": 0, "loss_streak": 0,
            "recent_closed": []}


def _eval(plan=None, sl=4460.0, tp=4435.0, balance=5000.0):
    real_open, real_cd = AE.is_market_open, CD.check_entry_cooldown
    AE.is_market_open = lambda *a, **k: True
    CD.check_entry_cooldown = lambda now=None: {"allowed": True}
    try:
        return AE.evaluate_proposal(_prop(sl=sl, tp=tp), _pol(balance),
                                    _perf(), plan or {}, None)
    finally:
        AE.is_market_open, CD.check_entry_cooldown = real_open, real_cd


class SessionPrior(unittest.TestCase):
    def test_asia_is_half_of_london(self):
        london = _eval(plan={"session": "london"})
        asia = _eval(plan={"session": "asia"})
        self.assertTrue(london.get("execute") and asia.get("execute"),
                        (london.get("reason"), asia.get("reason")))
        self.assertAlmostEqual(asia["risk_pct"], london["risk_pct"] * 0.5, places=6)
        self.assertLess(asia["command"]["lot"], london["command"]["lot"])
        self.assertEqual(asia["risk_stack"]["session_mult"], 0.5)
        self.assertEqual(london["risk_stack"]["session_mult"], 1.0)

    def test_missing_session_is_full_risk(self):
        r = _eval(plan={})
        self.assertTrue(r.get("execute"), r.get("reason"))
        self.assertEqual(r["risk_stack"]["session_mult"], 1.0)

    def test_newyork_is_full_risk(self):
        r = _eval(plan={"session": "newyork"})
        self.assertEqual(r["risk_stack"]["session_mult"], 1.0)


class LotCeiling(unittest.TestCase):
    def test_tight_stop_is_skipped_on_the_5k_book(self):
        # 6$ stop at 2% of 5k used to be 0.16 lots and the four -100$ hits.
        # Noise floor now skips rather than sizing the scalp.
        r = _eval(sl=4456.0, tp=4435.0)  # 6$ stop, RR = 15/6 = 2.5
        self.assertFalse(r.get("execute"), r)
        self.assertEqual(r.get("reason"), "stop_too_tight")
        self.assertEqual(AE.MAX_LOT, 0.10)
        self.assertEqual(AE.MIN_STOP_DISTANCE, 8.0)

    def test_eight_dollar_stop_still_prints(self):
        r = _eval(sl=4458.0, tp=4435.0)  # 8$ stop, RR = 15/8 = 1.875
        self.assertTrue(r.get("execute"), r.get("reason"))
        self.assertLessEqual(r["command"]["lot"], AE.MAX_LOT)

    def test_ten_dollar_stop_still_prints_zero_one(self):
        r = _eval()  # 10$ stop, 2% of 5k → 0.10
        self.assertTrue(r.get("execute"), r.get("reason"))
        self.assertAlmostEqual(r["command"]["lot"], 0.10, places=2)

    def test_small_account_5pt_stop_is_not_the_noise_gate(self):
        # b196 contract: $799 / 1% / 5pt still has to execute 0.01.
        r = _eval(sl=4455.0, tp=4435.0, balance=799.0)
        self.assertNotEqual(r.get("reason"), "stop_too_tight")


if __name__ == "__main__":
    unittest.main()
