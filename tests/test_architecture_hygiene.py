"""Architecture hygiene after the clean rebase onto origin/master.

- daily_pnl is NET (profit+commission+swap) so kill-switch/daily-loss
  gates are not half-a-commission optimistic.
- load_* does not mkdir as a side effect of a read.
- dashboard lists the 9 live systemd units, not a silent 4.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class DailyPnlIsNet(unittest.TestCase):
    def test_commission_and_swap_count_toward_daily_pnl(self):
        from engines.risk import compute_performance_state
        prev = {"day": "2026-09-19", "daily_pnl": 0.0, "loss_streak": 0,
                "trades_today": 0, "last_closed_ticket": None}
        deals = [
            {"ticket": 1, "entry": "1", "profit": 10.0,
             "commission": -2.0, "swap": -0.5},
        ]
        out = compute_performance_state(prev, "2026-09-19", 5000.0, deals)
        self.assertEqual(out["daily_pnl"], 7.5)

    def test_net_loss_increments_streak_even_if_gross_was_green(self):
        from engines.risk import compute_performance_state
        prev = {"day": "2026-09-19", "daily_pnl": 0.0, "loss_streak": 0,
                "trades_today": 0, "last_closed_ticket": None}
        deals = [
            {"ticket": 2, "entry": "1", "profit": 1.0,
             "commission": -3.0, "swap": 0.0},
        ]
        out = compute_performance_state(prev, "2026-09-19", 5000.0, deals)
        self.assertEqual(out["daily_pnl"], -2.0)
        self.assertEqual(out["loss_streak"], 1)


class LoadDoesNotMkdir(unittest.TestCase):
    def test_load_current_plan_on_missing_tree_creates_nothing(self):
        from engines.storage import load_current_plan
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "never_made"
            self.assertFalse(root.exists())
            self.assertIsNone(load_current_plan(root))
            self.assertFalse(root.exists())


class DashboardSeesAllUnits(unittest.TestCase):
    def test_nine_live_units_are_queried(self):
        from notifier import dashboards as d
        for name in ('hermes-forwarder', 'hermes-trading',
                     'hermes-trading.timer', 'hermes-webui', 'omniroute'):
            self.assertIn(name, d._SVC_NAMES)
            self.assertIn(name, d._SVC_LABEL)
        self.assertEqual(len(d._SVC_NAMES), 9)


if __name__ == '__main__':
    unittest.main()
