"""tests/test_unit_suite.py — Unittest suite for core trading entities, gates, and net PnL."""
from __future__ import annotations

import unittest
from decimal import Decimal
from core.entities import (
    Side,
    SetupGrade,
    BrokerPosition,
    AccountState,
    Plan,
    Signal,
)
from core.gates import GatesEngine
from core.params import Gates


class TestTradingCore(unittest.TestCase):
    def setUp(self):
        self.gates_cfg = Gates(
            max_open_positions=1,
            max_daily_trades=5,
            risk_per_trade_pct=2.0,
            max_daily_loss_pct=5.0,
            min_rr=1.0,
            min_grade=SetupGrade.B,
            min_atr_stop_mult=2.0,
            max_spread_points=2.5,
        )
        self.engine = GatesEngine(self.gates_cfg)
        self.account = AccountState(
            balance=5000.0,
            equity=5000.0,
            margin=0.0,
            margin_free=5000.0,
            currency="USD",
        )
        self.plan = Plan(
            plan_id="p-test-1",
            symbol="XAUUSD",
            side=Side.BUY,
            entry_price=2600.0,
            stop_loss=2590.0,
            take_profit=2620.0,
            volume=0.0,
            grade=SetupGrade.A,
            source="analysis",
            rr=2.0,
        )

    def test_b210_net_profit_includes_swap_and_commission(self):
        """b210: Deal profit must be net of swap and commission."""
        pos = BrokerPosition(
            ticket=999,
            symbol="XAUUSD",
            side=Side.BUY,
            volume=0.1,
            open_price=2600.0,
            current_price=2610.0,
            sl=2590.0,
            tp=2620.0,
            profit=100.0,
            swap=-4.5,
            commission=-7.0,
            open_time=1700000000,
        )
        self.assertEqual(pos.net_profit, 88.5)

    def test_b210_daily_loss_gate_blocks_on_net_loss(self):
        """b210: GatesEngine evaluates daily_loss against true net pnl."""
        # Max allowed loss is 5% of 5000 = $250.
        # If gross was -245 but commission/swap brought it to -255:
        outcome = self.engine.evaluate(
            plan=self.plan,
            account=self.account,
            positions=[],
            trades_today=1,
            daily_pnl=-255.0,
            atr=5.0,
            spread=0.5,
        )
        self.assertFalse(outcome.allowed)
        self.assertTrue(any("daily_loss" in r for r in outcome.reasons))

    def test_gate_allows_valid_setup(self):
        """Clean setup within risk parameters is allowed."""
        outcome = self.engine.evaluate(
            plan=self.plan,
            account=self.account,
            positions=[],
            trades_today=1,
            daily_pnl=50.0,
            atr=4.0,
            spread=0.3,
        )
        self.assertTrue(outcome.allowed)
        self.assertGreater(outcome.volume, 0.0)

    def test_gate_blocks_invalid_balance_or_equity(self):
        """Negative or zero balance/equity must fail closed."""
        dead_acc = AccountState(
            balance=5000.0,
            equity=0.0,
            margin=0.0,
            margin_free=0.0,
            currency="USD",
        )
        outcome = self.engine.evaluate(
            plan=self.plan,
            account=dead_acc,
            positions=[],
            trades_today=0,
            daily_pnl=0.0,
            atr=4.0,
            spread=0.3,
        )
        self.assertFalse(outcome.allowed)
        self.assertIn("equity_invalid", outcome.reasons)


if __name__ == "__main__":
    unittest.main()
