"""Focused net-PnL contracts for the account risk state.

The broker deal feed records opening and closing legs separately. The account
risk state must count every cash component once, while loss streaks must judge
the completed position net of the opening commission.
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines.risk import compute_performance_state, deal_net_pnl  # noqa: E402


class TestDealNetPnl(unittest.TestCase):
    def test_profit_commission_and_swap_are_all_cash_pnl(self):
        self.assertEqual(deal_net_pnl({
            "profit": "5.00", "commission": "-0.30", "swap": "-0.20",
        }), 4.5)

    def test_missing_or_malformed_cost_fields_are_zero(self):
        self.assertEqual(deal_net_pnl({"profit": 2.0}), 2.0)
        self.assertEqual(deal_net_pnl({"profit": "2", "commission": "bad"}), 2.0)


class TestPerformanceStateNetPnl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.today = datetime.now(timezone.utc).date().isoformat()
        cls.ts = datetime.now(timezone.utc).timestamp()

    def _state(self, deals, current=None):
        return compute_performance_state(
            current or {
                "day": self.today,
                "pnl_basis": "net",
                "daily_pnl": 0.0,
                "daily_gross_pnl": 0.0,
                "loss_streak": 0,
                "last_closed_ticket": None,
            },
            self.today,
            5000.0,
            deals,
        )

    def test_daily_pnl_keeps_gross_audit_and_uses_net(self):
        deals = [
            {"ticket": 1, "position_id": 10, "entry": 0,
             "volume": 0.10, "time": self.ts, "profit": 0.0,
             "commission": -0.30, "swap": 0.0},
            {"ticket": 2, "position_id": 10, "entry": 1,
             "volume": 0.10, "time": self.ts + 1, "profit": 5.0,
             "commission": -0.10, "swap": -0.20},
        ]
        state = self._state(deals)
        self.assertEqual(state["daily_pnl"], 4.4)
        self.assertEqual(state["daily_gross_pnl"], 5.0)
        self.assertEqual(state["pnl_basis"], "net")

    def test_entry_commission_can_turn_gross_winner_into_loss_streak(self):
        deals = [
            {"ticket": 1, "position_id": 11, "entry": 0,
             "volume": 0.10, "time": self.ts, "profit": 0.0,
             "commission": -0.30, "swap": 0.0},
            {"ticket": 2, "position_id": 11, "entry": 1,
             "volume": 0.10, "time": self.ts + 1, "profit": 0.20,
             "commission": 0.0, "swap": 0.0},
        ]
        state = self._state(deals)
        self.assertEqual(state["daily_pnl"], -0.1)
        self.assertEqual(state["loss_streak"], 1)

    def test_swap_is_included_in_daily_loss(self):
        deals = [{
            "ticket": 3, "position_id": 12, "entry": 1,
            "volume": 0.10, "time": self.ts, "profit": 3.0,
            "commission": -0.10, "swap": -2.50,
        }]
        state = self._state(deals)
        self.assertEqual(state["daily_pnl"], 0.4)
        self.assertEqual(state["daily_gross_pnl"], 3.0)

    def test_legacy_gross_state_is_rebuilt_as_net_once(self):
        deals = [{
            "ticket": 4, "position_id": 13, "entry": 1,
            "volume": 0.10, "time": self.ts, "profit": 5.0,
            "commission": -0.50, "swap": -0.25,
        }]
        legacy = {
            "day": self.today, "daily_pnl": 5.0, "loss_streak": 0,
            "last_closed_ticket": None,
        }
        state = self._state(deals, current=legacy)
        self.assertEqual(state["daily_pnl"], 4.25)
        self.assertEqual(state["daily_gross_pnl"], 5.0)
        self.assertEqual(state["pnl_basis"], "net")

    def test_net_state_cursor_does_not_double_count_old_deals(self):
        deals = [{
            "ticket": 1, "position_id": 14, "entry": 1,
            "volume": 0.10, "time": self.ts, "profit": 4.0,
            "commission": -0.25, "swap": -0.25,
        }, {
            "ticket": 2, "position_id": 15, "entry": 1,
            "volume": 0.10, "time": self.ts + 1, "profit": 2.0,
            "commission": -0.25, "swap": 0.0,
        }]
        current = {
            "day": self.today, "pnl_basis": "net", "daily_pnl": 3.5,
            "daily_gross_pnl": 4.0, "loss_streak": 0,
            "last_closed_ticket": 1,
        }
        state = self._state(deals, current=current)
        self.assertEqual(state["daily_pnl"], 5.25)
        self.assertEqual(state["daily_gross_pnl"], 6.0)
        self.assertEqual(state["last_closed_ticket"], 2)

    def test_rollover_resets_day_pnl_but_preserves_defcon_window(self):
        deals = [{
            "ticket": 9, "position_id": 16, "entry": 1,
            "time": self.ts, "profit": -10.0, "commission": -0.2,
            "swap": 0.0,
        }]
        state = compute_performance_state(
            {"day": "2020-01-01", "daily_pnl": -10.0,
             "loss_streak": 2, "last_closed_ticket": 8},
            self.today, 5000.0, deals,
        )
        self.assertEqual(state["daily_pnl"], 0.0)
        self.assertEqual(state["loss_streak"], 0)
        self.assertEqual(state["recent_closed"], deals)


if __name__ == "__main__":
    unittest.main()
