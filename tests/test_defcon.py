"""Unit tests for DEFCON service and entities.

Tests the refactored DEFCON system with 100% coverage.

Run with:
    python3 -m pytest tests/test_defcon.py -v
"""

import unittest
from unittest.mock import Mock, patch
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from brain.domain.entities.defcon import (
    DefconLevel,
    ExitType,
    ClosedDeal,
    ExitStatistics,
    DefconInsights,
)
from brain.application.services.defcon_service import DefconService


class TestDefconEntities(unittest.TestCase):
    """Test DEFCON domain entities."""
    
    def test_defcon_levels(self):
        """Test DefconLevel enum."""
        self.assertEqual(DefconLevel.GREEN.value, "GREEN")
        self.assertEqual(DefconLevel.YELLOW.value, "YELLOW")
        self.assertEqual(DefconLevel.RED.value, "RED")
    
    def test_exit_types(self):
        """Test ExitType enum."""
        self.assertEqual(ExitType.STOP_LOSS.value, "sl")
        self.assertEqual(ExitType.TAKE_PROFIT.value, "tp")
        self.assertEqual(ExitType.MANAGED.value, "managed")
        self.assertEqual(ExitType.UNKNOWN.value, "unknown")
    
    def test_closed_deal_immutable(self):
        """Test ClosedDeal is frozen."""
        deal = ClosedDeal(
            ticket=12345,
            profit=100.0,
            exit_type=ExitType.TAKE_PROFIT,
        )
        
        with self.assertRaises(Exception):  # FrozenInstanceError
            deal.profit = 200.0
    
    def test_exit_statistics_empty(self):
        """Test empty ExitStatistics."""
        stats = ExitStatistics(
            total=0,
            sl_count=0,
            tp_count=0,
            managed_count=0,
            managed_win_ratio=None,
            managed_total_pnl=0.0,
            sl_ratio=0.0,
            sl_dominant=False,
        )
        
        self.assertTrue(stats.is_empty)
    
    def test_defcon_insights_properties(self):
        """Test DefconInsights convenience properties."""
        stats = ExitStatistics(
            total=0, sl_count=0, tp_count=0, managed_count=0,
            managed_win_ratio=None, managed_total_pnl=0.0,
            sl_ratio=0.0, sl_dominant=False,
        )
        
        green = DefconInsights(
            level=DefconLevel.GREEN,
            risk_multiplier=1.0,
            trade_allowed=True,
            runner_allowed=True,
            scale_in_allowed=True,
            exit_stats=stats,
        )
        
        self.assertTrue(green.is_green)
        self.assertFalse(green.is_yellow)
        self.assertFalse(green.is_red)
    
    def test_defcon_insights_to_dict(self):
        """Test DefconInsights legacy dict conversion."""
        stats = ExitStatistics(
            total=5, sl_count=3, tp_count=2, managed_count=0,
            managed_win_ratio=None, managed_total_pnl=0.0,
            sl_ratio=0.6, sl_dominant=True,
        )
        
        insights = DefconInsights(
            level=DefconLevel.YELLOW,
            risk_multiplier=0.5,
            trade_allowed=True,
            runner_allowed=False,
            scale_in_allowed=False,
            exit_stats=stats,
        )
        
        d = insights.to_dict()
        
        self.assertEqual(d["defcon"], "YELLOW")
        self.assertEqual(d["risk_override"], 0.5)
        self.assertFalse(d["runner_allowed"])
        self.assertEqual(d["exit_stats"]["sl_ratio"], 0.6)


class TestDefconService(unittest.TestCase):
    """Test DEFCON service logic."""
    
    def setUp(self):
        """Create service with mock database."""
        self.mock_db = Mock()
        self.service = DefconService(db=self.mock_db)
    
    def test_classify_exit_stop_loss(self):
        """Test SL classification."""
        self.assertEqual(
            self.service.classify_exit("[sl 2600.0]", -50.0),
            ExitType.STOP_LOSS
        )
        self.assertEqual(
            self.service.classify_exit("manual [sl hit]", -50.0),
            ExitType.STOP_LOSS
        )
    
    def test_classify_exit_take_profit(self):
        """Test TP classification."""
        self.assertEqual(
            self.service.classify_exit("[tp 2620.0]", 100.0),
            ExitType.TAKE_PROFIT
        )
    
    def test_classify_exit_managed(self):
        """Test managed exit classification."""
        self.assertEqual(
            self.service.classify_exit("Hermes manage trail", 50.0),
            ExitType.MANAGED
        )
        self.assertEqual(
            self.service.classify_exit("partial take profit", 30.0),
            ExitType.MANAGED
        )
    
    def test_classify_exit_unknown(self):
        """Test unknown exit classification."""
        self.assertEqual(
            self.service.classify_exit("some random comment", 10.0),
            ExitType.UNKNOWN
        )
    
    def test_classify_deals(self):
        """Test deal classification."""
        deals = [
            {"ticket": 1, "profit": 100.0, "comment": "[tp 2620]"},
            {"ticket": 2, "profit": -50.0, "comment": "[sl 2590]"},
        ]
        
        classified = self.service.classify_deals(deals)
        
        self.assertEqual(len(classified), 2)
        self.assertEqual(classified[0].exit_type, ExitType.TAKE_PROFIT)
        self.assertEqual(classified[1].exit_type, ExitType.STOP_LOSS)
    
    def test_analyze_exits_empty(self):
        """Test analysis with no deals."""
        stats = self.service.analyze_exits([])
        
        self.assertEqual(stats.total, 0)
        self.assertTrue(stats.is_empty)
    
    def test_analyze_exits_sl_dominated(self):
        """Test SL-dominated statistics."""
        deals = [
            ClosedDeal(1, -50.0, ExitType.STOP_LOSS),
            ClosedDeal(2, -40.0, ExitType.STOP_LOSS),
            ClosedDeal(3, -30.0, ExitType.STOP_LOSS),
            ClosedDeal(4, 100.0, ExitType.TAKE_PROFIT),
            ClosedDeal(5, 80.0, ExitType.TAKE_PROFIT),
        ]
        
        stats = self.service.analyze_exits(deals)
        
        self.assertEqual(stats.total, 5)
        self.assertEqual(stats.sl_count, 3)
        self.assertEqual(stats.tp_count, 2)
        self.assertEqual(stats.sl_ratio, 0.6)  # 3/5
        self.assertTrue(stats.sl_dominant)
    
    def test_analyze_exits_managed(self):
        """Test managed exit statistics."""
        deals = [
            ClosedDeal(1, 50.0, ExitType.MANAGED),   # win
            ClosedDeal(2, -30.0, ExitType.MANAGED),  # loss
            ClosedDeal(3, -20.0, ExitType.MANAGED),  # loss
            ClosedDeal(4, -10.0, ExitType.MANAGED),  # loss
        ]
        
        stats = self.service.analyze_exits(deals)
        
        self.assertEqual(stats.managed_count, 4)
        self.assertEqual(stats.managed_win_ratio, 0.25)  # 1/4
        self.assertEqual(stats.managed_total_pnl, -10.0)  # 50-30-20-10
    
    def test_compute_insights_green(self):
        """Test GREEN level (normal conditions)."""
        deals = [
            ClosedDeal(1, 100.0, ExitType.TAKE_PROFIT),
            ClosedDeal(2, 80.0, ExitType.TAKE_PROFIT),
        ]
        
        insights = self.service.compute_insights(
            loss_streak=0,
            daily_pnl=180.0,
            classified=deals,
        )
        
        self.assertTrue(insights.is_green)
        self.assertEqual(insights.risk_multiplier, 1.0)
        self.assertTrue(insights.trade_allowed)
        self.assertTrue(insights.runner_allowed)
        self.assertTrue(insights.scale_in_allowed)
    
    def test_compute_insights_yellow_loss_streak(self):
        """Test YELLOW from loss streak."""
        insights = self.service.compute_insights(
            loss_streak=2,
            daily_pnl=-100.0,
            classified=[],
        )
        
        self.assertTrue(insights.is_yellow)
        self.assertEqual(insights.risk_multiplier, 0.5)
        self.assertTrue(insights.trade_allowed)
        self.assertFalse(insights.runner_allowed)
        self.assertFalse(insights.scale_in_allowed)
    
    def test_compute_insights_yellow_sl_ratio(self):
        """Test YELLOW from high SL ratio."""
        deals = [
            ClosedDeal(1, -50.0, ExitType.STOP_LOSS),
            ClosedDeal(2, -40.0, ExitType.STOP_LOSS),
            ClosedDeal(3, 100.0, ExitType.TAKE_PROFIT),
        ]
        
        insights = self.service.compute_insights(
            loss_streak=0,
            daily_pnl=10.0,
            classified=deals,
        )
        
        self.assertTrue(insights.is_yellow)  # 2/3 >= 0.5
        self.assertEqual(insights.risk_multiplier, 0.5)
    
    def test_compute_insights_red(self):
        """Test RED level (critical)."""
        deals = [
            ClosedDeal(1, -50.0, ExitType.STOP_LOSS),
            ClosedDeal(2, -40.0, ExitType.STOP_LOSS),
            ClosedDeal(3, -30.0, ExitType.STOP_LOSS),
            ClosedDeal(4, 10.0, ExitType.TAKE_PROFIT),
            ClosedDeal(5, 5.0, ExitType.TAKE_PROFIT),
        ]
        
        insights = self.service.compute_insights(
            loss_streak=3,
            daily_pnl=-105.0,  # Losing day
            classified=deals,
        )
        
        self.assertTrue(insights.is_red)
        self.assertEqual(insights.risk_multiplier, 0.0)
        self.assertFalse(insights.trade_allowed)
        self.assertFalse(insights.runner_allowed)
    
    def test_compute_insights_managed_exits_losing(self):
        """Test runner block from failing managed exits."""
        deals = [
            ClosedDeal(1, 20.0, ExitType.MANAGED),   # win
            ClosedDeal(2, -30.0, ExitType.MANAGED),  # loss
            ClosedDeal(3, -25.0, ExitType.MANAGED),  # loss
            ClosedDeal(4, -20.0, ExitType.MANAGED),  # loss
        ]
        
        insights = self.service.compute_insights(
            loss_streak=0,
            daily_pnl=50.0,  # Winning day
            classified=deals,
        )
        
        # Should be GREEN but runners blocked
        self.assertTrue(insights.is_green)
        self.assertFalse(insights.runner_allowed)
        self.assertEqual(insights.runner_blocked_reason, "managed_exits_losing")
    
    def test_filter_management_hold(self):
        """Test hold action passes through."""
        insights = DefconInsights(
            level=DefconLevel.RED,
            risk_multiplier=0.0,
            trade_allowed=False,
            runner_allowed=False,
            scale_in_allowed=False,
            exit_stats=ExitStatistics(
                total=0, sl_count=0, tp_count=0, managed_count=0,
                managed_win_ratio=None, managed_total_pnl=0.0,
                sl_ratio=0.0, sl_dominant=False,
            ),
        )
        
        action = {"action": "hold"}
        result = self.service.filter_management_action(action, insights)
        
        self.assertEqual(result["action"], "hold")
    
    def test_filter_management_safety_allowed(self):
        """Test safety actions always pass."""
        insights = DefconInsights(
            level=DefconLevel.RED,
            risk_multiplier=0.0,
            trade_allowed=False,
            runner_allowed=False,
            scale_in_allowed=False,
            exit_stats=ExitStatistics(
                total=0, sl_count=0, tp_count=0, managed_count=0,
                managed_win_ratio=None, managed_total_pnl=0.0,
                sl_ratio=0.0, sl_dominant=False,
            ),
        )
        
        for action_name in ["close_trade_early", "partial_take_profit", "move_stop_to_breakeven"]:
            action = {"action": action_name}
            result = self.service.filter_management_action(action, insights)
            self.assertEqual(result["action"], action_name)
    
    def test_filter_management_runner_blocked(self):
        """Test runner escalation when blocked."""
        insights = DefconInsights(
            level=DefconLevel.YELLOW,
            risk_multiplier=0.5,
            trade_allowed=True,
            runner_allowed=False,
            scale_in_allowed=False,
            exit_stats=ExitStatistics(
                total=0, sl_count=0, tp_count=0, managed_count=0,
                managed_win_ratio=None, managed_total_pnl=0.0,
                sl_ratio=0.0, sl_dominant=False,
            ),
        )
        
        action = {"action": "trail_stop", "distance": 10}
        result = self.service.filter_management_action(action, insights)
        
        # Should escalate to close_runner
        self.assertEqual(result["action"], "close_runner")
        self.assertEqual(result["close_fraction"], 1.0)
    
    def test_filter_management_scale_in_blocked(self):
        """Test scale-in block."""
        insights = DefconInsights(
            level=DefconLevel.YELLOW,
            risk_multiplier=0.5,
            trade_allowed=True,
            runner_allowed=True,
            scale_in_allowed=False,
            exit_stats=ExitStatistics(
                total=0, sl_count=0, tp_count=0, managed_count=0,
                managed_win_ratio=None, managed_total_pnl=0.0,
                sl_ratio=0.0, sl_dominant=False,
            ),
        )
        
        action = {"action": "scale_in_buy", "volume": 0.1}
        result = self.service.filter_management_action(action, insights)
        
        self.assertEqual(result["action"], "hold")
        self.assertIn("scale_in_blocked", result["reason"])


if __name__ == '__main__':
    unittest.main()
