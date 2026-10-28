"""b233 — MIN_RISK_REWARD floor (AUDIT-2026-10-04).

Re-tested live on four M5 windows (500/1000/1500/2000 bars) against the
running bridge. min_rr=2.0 beat 1.5 in ALL FOUR (+26/+26/+43/+29 USD). At 1.5
the engine admits low-edge trades that lose in aggregate — the two short
windows were outright negative at 1.5 and positive at 2.0.

The value is a live gate, so this test pins the number and the reason: a later
"just relax it to 1.5, it trades more" change re-introduces exactly the loss
the floor removes.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engines import auto_executor


def _policy():
    return {"balance": 5000.0, "equity": 5000.0, "margin_free": 5000.0,
            "margin": 0.0, "leverage": 100}


class TestMinRiskReward(unittest.TestCase):
    def test_floor_is_two(self):
        """2.0, not 1.5 — see the commit note on MIN_RISK_REWARD."""
        self.assertEqual(auto_executor.MIN_RISK_REWARD, 2.0)

    def test_low_rr_proposal_is_rejected(self):
        """A 0.5R proposal is below the floor and must not pass the gate."""
        prop = {"cmd": {"side": "BUY", "lot": 0.02, "symbol": "XAUUSD",
                        "entry": 4100.0, "sl": 4090.0, "tp": 4105.0},
                "rr": 0.5}
        r = auto_executor.evaluate_proposal(prop, _policy(), {}, {})
        self.assertFalse(bool(r.get("ok")))

    def test_rr_just_below_two_is_rejected(self):
        """The boundary itself — a 1.9R trade is below the 2.0 floor."""
        prop = {"cmd": {"side": "BUY", "lot": 0.02, "symbol": "XAUUSD",
                        "entry": 4100.0, "sl": 4090.0, "tp": 4119.0},
                "rr": 1.9}
        r = auto_executor.evaluate_proposal(prop, _policy(), {}, {})
        self.assertFalse(bool(r.get("ok")))


if __name__ == "__main__":
    unittest.main()
