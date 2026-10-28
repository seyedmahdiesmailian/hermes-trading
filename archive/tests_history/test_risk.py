"""Unit tests for Risk service and entities.

Tests the refactored risk management system.

Run with:
    python3 -m pytest tests/test_risk.py -v
"""

import unittest
from datetime import datetime, timezone
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from brain.domain.entities.risk import (
    RiskRegime,
    PerformanceState,
    AccountPolicy,
    RiskBudget,
)
from brain.application.services.risk_service import RiskService


class TestRiskEntities(unittest.TestCase):
    """Test risk domain entities."""
    
    def test_risk_regimes(self):
        """Test RiskRegime enum."""
        self.assertEqual(RiskRegime.NORMAL.value, "normal")
        self.assertEqual(RiskRegime.DEFENSIVE.value, "defensive")
        self.assertEqual(RiskRegime.RECOVERY.value, "recovery")
        self.assertEqual(RiskRegime.LOCKED.value, "locked")
    
    def test_performance_state_properties(self):
        """Test PerformanceState convenience properties."""
        state = PerformanceState(
            day="2026-10-15",
            starting_balance=1000.0,
            daily_pnl=-50.0,
            daily_gross_pnl=-45.0,
            loss_streak=2,
            trades_today=3,
            last_closed_ticket=12345,
            recent_closed=[],
        )
        
        self.assertTrue(state.is_losing_day)
        self.assertTrue(state.has_trades)
    
    def test_account_policy_properties(self):
        """Test AccountPolicy convenience properties."""
        # Healthy policy
        policy = AccountPolicy(
            balance=1000.0,
            equity=980.0,
            free_margin=500.0,
            margin=50.0,
            open_positions=1,
            drawdown_pct=0.02,
            margin_ratio=10.0,
            base_risk_pct=0.015,
            risk_multiplier=1.0,
            trade_allowed=True,
            regime=RiskRegime.NORMAL,
            reasons=[],
            max_positions_allowed=1,
        )
        
        self.assertTrue(policy.is_healthy)
        self.assertFalse(policy.is_locked)
        self.assertEqual(policy.effective_risk_pct, 0.015)
        
        # Locked policy
        locked = AccountPolicy(
            balance=1000.0,
            equity=900.0,
            free_margin=100.0,
            margin=50.0,
            open_positions=0,
            drawdown_pct=0.10,
            margin_ratio=2.0,
            base_risk_pct=0.015,
            risk_multiplier=0.0,
            trade_allowed=False,
            regime=RiskRegime.LOCKED,
            reasons=["drawdown_limit"],
            max_positions_allowed=1,
        )
        
        self.assertFalse(locked.is_healthy)
        self.assertTrue(locked.is_locked)
    
    def test_risk_budget_approval(self):
        """Test RiskBudget approval logic."""
        # Approved
        approved = RiskBudget(
            trade_allowed=True,
            risk_pct=0.015,
            risk_usd=15.0,
            reason=None,
            regime=RiskRegime.NORMAL,
        )
        self.assertTrue(approved.is_approved)
        
        # Rejected
        rejected = RiskBudget(
            trade_allowed=False,
            risk_pct=None,
            risk_usd=None,
            reason="policy_block",
            regime=RiskRegime.LOCKED,
        )
        self.assertFalse(rejected.is_approved)


class TestRiskService(unittest.TestCase):
    """Test RiskService logic."""
    
    def setUp(self):
        """Create service."""
        self.service = RiskService(db=None)  # No DB for unit tests
    
    def test_base_risk_pct(self):
        """Test base risk percentage calculation."""
        self.assertEqual(self.service.base_risk_pct(500), 0.01)    # < 800
        self.assertEqual(self.service.base_risk_pct(1000), 0.015)  # < 1500
        self.assertEqual(self.service.base_risk_pct(2000), 0.02)   # < 5000
        self.assertEqual(self.service.base_risk_pct(10000), 0.015) # >= 5000
    
    def test_is_entry_deal(self):
        """Test entry deal detection."""
        self.assertTrue(self.service.is_entry_deal({"entry": "0"}))
        self.assertTrue(self.service.is_entry_deal({"entry": "IN"}))
        self.assertTrue(self.service.is_entry_deal({"entry": "in"}))
        self.assertFalse(self.service.is_entry_deal({"entry": "1"}))
        self.assertFalse(self.service.is_entry_deal({"entry": "OUT"}))
    
    def test_deal_net_pnl(self):
        """Test net P&L calculation."""
        deal = {
            "profit": 100.0,
            "commission": -2.0,
            "swap": -1.0,
        }
        self.assertEqual(self.service.deal_net_pnl(deal), 97.0)
        
        # Missing fields
        self.assertEqual(self.service.deal_net_pnl({}), 0.0)
    
    def test_count_entries_today(self):
        """Test entry counting."""
        now = datetime.now(timezone.utc)
        today = now.date().isoformat()
        
        deals = [
            {"entry": "0", "time": now.timestamp()},  # Entry today
            {"entry": "1", "time": now.timestamp()},  # Exit today
            {"entry": "0", "time": now.timestamp()},  # Entry today
        ]
        
        self.assertEqual(self.service.count_entries_today(deals, today), 2)
    
    def test_assess_account_policy_normal(self):
        """Test NORMAL regime."""
        policy = self.service.assess_account_policy(
            balance=1000.0,
            equity=990.0,
            free_margin=1000.0,  # margin_ratio = 1000/50 = 20
            margin=50.0,
            daily_pnl=10.0,
            loss_streak=0,
            open_positions=0,
        )
        
        self.assertEqual(policy.regime, RiskRegime.NORMAL)
        self.assertTrue(policy.trade_allowed)
        self.assertEqual(policy.risk_multiplier, 1.0)
        self.assertEqual(len(policy.reasons), 0)
    
    def test_assess_account_policy_defensive(self):
        """Test DEFENSIVE regime from loss streak."""
        policy = self.service.assess_account_policy(
            balance=1000.0,
            equity=990.0,
            free_margin=1000.0,
            margin=50.0,
            daily_pnl=-5.0,
            loss_streak=2,
            open_positions=0,
        )
        
        self.assertEqual(policy.regime, RiskRegime.DEFENSIVE)
        self.assertTrue(policy.trade_allowed)
        self.assertEqual(policy.risk_multiplier, 0.75)
        self.assertIn("recent_losses", policy.reasons)
    
    def test_assess_account_policy_defensive_daily_loss(self):
        """Test DEFENSIVE from -1% daily loss."""
        policy = self.service.assess_account_policy(
            balance=1000.0,
            equity=990.0,
            free_margin=1000.0,
            margin=50.0,
            daily_pnl=-12.0,  # > 1%
            loss_streak=0,
            open_positions=0,
        )
        
        self.assertEqual(policy.regime, RiskRegime.DEFENSIVE)
        self.assertEqual(policy.risk_multiplier, 0.75)
    
    def test_assess_account_policy_recovery(self):
        """Test RECOVERY regime from drawdown."""
        policy = self.service.assess_account_policy(
            balance=1000.0,
            equity=970.0,  # 3% drawdown
            free_margin=1000.0,
            margin=50.0,
            daily_pnl=0.0,
            loss_streak=0,
            open_positions=0,
        )
        
        self.assertEqual(policy.regime, RiskRegime.RECOVERY)
        self.assertTrue(policy.trade_allowed)
        self.assertEqual(policy.risk_multiplier, 0.5)
        self.assertIn("equity_drawdown", policy.reasons)
    
    def test_assess_account_policy_locked_drawdown(self):
        """Test LOCKED regime from 5% drawdown."""
        policy = self.service.assess_account_policy(
            balance=1000.0,
            equity=940.0,  # 6% drawdown
            free_margin=500.0,
            margin=50.0,
            daily_pnl=0.0,
            loss_streak=0,
            open_positions=0,
        )
        
        self.assertEqual(policy.regime, RiskRegime.LOCKED)
        self.assertFalse(policy.trade_allowed)
        self.assertEqual(policy.risk_multiplier, 0.0)
        self.assertIn("drawdown_limit", policy.reasons)
    
    def test_assess_account_policy_locked_daily_loss(self):
        """Test LOCKED regime from -3% daily loss."""
        policy = self.service.assess_account_policy(
            balance=1000.0,
            equity=990.0,
            free_margin=500.0,
            margin=50.0,
            daily_pnl=-35.0,  # > 3%
            loss_streak=0,
            open_positions=0,
        )
        
        self.assertEqual(policy.regime, RiskRegime.LOCKED)
        self.assertFalse(policy.trade_allowed)
    
    def test_assess_account_policy_locked_margin(self):
        """Test LOCKED regime from low margin."""
        policy = self.service.assess_account_policy(
            balance=1000.0,
            equity=990.0,
            free_margin=50.0,
            margin=10.0,  # Ratio = 5 < 20
            daily_pnl=0.0,
            loss_streak=0,
            open_positions=0,
        )
        
        self.assertEqual(policy.regime, RiskRegime.LOCKED)
        self.assertFalse(policy.trade_allowed)
        self.assertIn("margin_health", policy.reasons)
    
    def test_recommend_risk_budget_grade_a(self):
        """Test risk budget for A-grade setup."""
        policy = AccountPolicy(
            balance=1000.0,
            equity=990.0,
            free_margin=500.0,
            margin=50.0,
            open_positions=0,
            drawdown_pct=0.01,
            margin_ratio=10.0,
            base_risk_pct=0.02,
            risk_multiplier=1.0,
            trade_allowed=True,
            regime=RiskRegime.NORMAL,
            reasons=[],
            max_positions_allowed=1,
        )
        
        budget = self.service.recommend_risk_budget(policy, "A")
        
        self.assertTrue(budget.trade_allowed)
        self.assertEqual(budget.risk_pct, 0.02)  # 0.02 * 1.0 * 1.0
        self.assertEqual(budget.risk_usd, 20.0)  # 1000 * 0.02
    
    def test_recommend_risk_budget_grade_b(self):
        """Test risk budget for B-grade setup."""
        policy = AccountPolicy(
            balance=1000.0,
            equity=990.0,
            free_margin=500.0,
            margin=50.0,
            open_positions=0,
            drawdown_pct=0.01,
            margin_ratio=10.0,
            base_risk_pct=0.02,
            risk_multiplier=1.0,
            trade_allowed=True,
            regime=RiskRegime.NORMAL,
            reasons=[],
            max_positions_allowed=1,
        )
        
        budget = self.service.recommend_risk_budget(policy, "B")
        
        self.assertTrue(budget.trade_allowed)
        self.assertEqual(budget.risk_pct, 0.012)  # 0.02 * 1.0 * 0.6
        self.assertEqual(budget.risk_usd, 12.0)
    
    def test_recommend_risk_budget_blocked_policy(self):
        """Test risk budget when policy blocks."""
        policy = AccountPolicy(
            balance=1000.0,
            equity=940.0,
            free_margin=100.0,
            margin=50.0,
            open_positions=0,
            drawdown_pct=0.06,
            margin_ratio=2.0,
            base_risk_pct=0.02,
            risk_multiplier=0.0,
            trade_allowed=False,
            regime=RiskRegime.LOCKED,
            reasons=["drawdown_limit"],
            max_positions_allowed=1,
        )
        
        budget = self.service.recommend_risk_budget(policy, "A")
        
        self.assertFalse(budget.trade_allowed)
        self.assertIsNone(budget.risk_pct)
        self.assertEqual(budget.reason, "drawdown_limit")
    
    def test_recommend_risk_budget_position_limit(self):
        """Test risk budget when position limit hit."""
        policy = AccountPolicy(
            balance=1000.0,
            equity=990.0,
            free_margin=500.0,
            margin=50.0,
            open_positions=1,  # At limit
            drawdown_pct=0.01,
            margin_ratio=10.0,
            base_risk_pct=0.02,
            risk_multiplier=1.0,
            trade_allowed=True,
            regime=RiskRegime.NORMAL,
            reasons=[],
            max_positions_allowed=1,
        )
        
        budget = self.service.recommend_risk_budget(policy, "A")
        
        self.assertFalse(budget.trade_allowed)
        self.assertEqual(budget.reason, "position_limit")
    
    def test_compute_performance_state_new_day(self):
        """Test performance state on new day."""
        state = self.service.compute_performance_state(
            current={"day": "2026-10-14"},
            today="2026-10-15",
            balance=1000.0,
            closed_trades=[],
        )
        
        self.assertEqual(state.day, "2026-10-15")
        self.assertEqual(state.starting_balance, 1000.0)
        self.assertEqual(state.daily_pnl, 0.0)
        self.assertEqual(state.loss_streak, 0)
        self.assertEqual(state.trades_today, 0)
    
    def test_compute_performance_state_same_day(self):
        """Test performance state continuation."""
        # Setup: existing state + new closed deal
        current = {
            "day": "2026-10-15",
            "starting_balance": 1000.0,
            "daily_pnl": 50.0,
            "daily_gross_pnl": 52.0,
            "pnl_basis": "net",
            "loss_streak": 0,
            "trades_today": 2,
            "last_closed_ticket": 100,
        }
        
        new_deal = {
            "ticket": 101,
            "entry": "1",  # Exit
            "profit": 30.0,
            "commission": -1.0,
            "swap": -0.5,
            "volume": 0.1,
        }
        
        state = self.service.compute_performance_state(
            current=current,
            today="2026-10-15",
            balance=1000.0,
            closed_trades=[new_deal],
        )
        
        self.assertEqual(state.day, "2026-10-15")
        self.assertEqual(state.daily_pnl, 78.5)  # 50 + 30 - 1 - 0.5
        self.assertEqual(state.loss_streak, 0)  # Win doesn't break streak
        self.assertEqual(state.last_closed_ticket, 101)


if __name__ == '__main__':
    unittest.main()
