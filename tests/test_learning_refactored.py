"""Unit tests for Learning service and entities.

Tests the refactored adaptive learning system.

Run with:
    python3 -m pytest tests/test_learning_refactored.py -v
"""

import unittest
from datetime import datetime, timezone
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from brain.domain.entities.learning import (
    SetupGrade,
    TradingSession,
    RegimeBucket,
    TradeStatistics,
    LearningAdjustments,
    LearningState,
)
from brain.application.services.learning_service import LearningService


class TestLearningEntities(unittest.TestCase):
    """Test learning domain entities."""
    
    def test_setup_grade_comparison(self):
        """Test SetupGrade ordering."""
        self.assertTrue(SetupGrade.C < SetupGrade.B)
        self.assertTrue(SetupGrade.B < SetupGrade.A)
        self.assertTrue(SetupGrade.C < SetupGrade.A)
        
        self.assertTrue(SetupGrade.A > SetupGrade.B)
        self.assertTrue(SetupGrade.B >= SetupGrade.B)
        self.assertTrue(SetupGrade.A >= SetupGrade.C)
    
    def test_trade_statistics_properties(self):
        """Test TradeStatistics convenience properties."""
        # Profitable
        stats = TradeStatistics(
            trades=20,
            win_rate=0.60,
            net_pnl=100.0,
            avg_pnl=5.0,
        )
        self.assertTrue(stats.is_profitable)
        self.assertTrue(stats.has_sufficient_sample)  # Default 15
        
        # Losing
        stats_losing = TradeStatistics(
            trades=10,
            win_rate=0.30,
            net_pnl=-50.0,
            avg_pnl=-5.0,
        )
        self.assertFalse(stats_losing.is_profitable)
        self.assertFalse(stats_losing.has_sufficient_sample)
    
    def test_learning_adjustments(self):
        """Test LearningAdjustments properties."""
        # Has changes
        adj = LearningAdjustments(
            risk_multiplier=0.8,
            min_grade=None,
            min_rr=None,
            reason='test',
        )
        self.assertTrue(adj.has_changes)
        
        # No changes
        no_change = LearningAdjustments(
            risk_multiplier=None,
            min_grade=None,
            min_rr=None,
            reason='no_change',
        )
        self.assertFalse(no_change.has_changes)
    
    def test_learning_state_conversion(self):
        """Test LearningState dict conversion."""
        state = LearningState(
            risk_mult=0.8,
            min_grade=SetupGrade.A,
            min_rr=1.75,
            last_updated='2026-10-15T12:00:00+00:00',
        )
        
        # to_dict
        d = state.to_dict()
        self.assertEqual(d['risk_mult'], 0.8)
        self.assertEqual(d['min_grade'], 'A')
        self.assertEqual(d['min_rr'], 1.75)
        
        # from_dict
        state2 = LearningState.from_dict(d)
        self.assertEqual(state2.risk_mult, 0.8)
        self.assertEqual(state2.min_grade, SetupGrade.A)
        self.assertEqual(state2.min_rr, 1.75)


class TestLearningService(unittest.TestCase):
    """Test LearningService logic."""
    
    def setUp(self):
        """Create service."""
        self.service = LearningService(db=None)
    
    def test_group_positions(self):
        """Test position aggregation."""
        rows = [
            {
                'ticket': '101',
                'position_id': 'pos1',
                'side': 'BUY',
                'profit': 50.0,
                'commission': -1.0,
                'swap': -0.5,
                'entry_commission': -0.25,
                'volume': 0.1,
                'close_time': '1234567890',
            },
            {
                'ticket': '102',
                'position_id': 'pos1',  # Same position
                'side': 'BUY',
                'profit': 30.0,
                'commission': -0.5,
                'swap': -0.25,
                'entry_commission': -0.15,
                'volume': 0.05,
                'close_time': '1234567900',
            },
        ]
        
        positions = self.service.group_positions(rows)
        
        self.assertEqual(len(positions), 1)
        self.assertIn('pos1', positions)
        
        pos = positions['pos1']
        self.assertEqual(pos.profit, 80.0)
        self.assertAlmostEqual(pos.net_pnl, 77.35, places=2)  # 80 - 1 - 0.5 - 0.25 - 0.5 - 0.25 - 0.15
        self.assertEqual(pos.volume, 0.1)
        self.assertEqual(pos.legs, 2)
    
    def test_compute_statistics(self):
        """Test statistics computation."""
        rows = [
            {'position_id': 'p1', 'profit': 50, 'commission': -1, 'swap': 0, 'entry_commission': 0},
            {'position_id': 'p2', 'profit': -30, 'commission': -1, 'swap': 0, 'entry_commission': 0},
            {'position_id': 'p3', 'profit': 40, 'commission': -1, 'swap': 0, 'entry_commission': 0},
            {'position_id': 'p4', 'profit': -20, 'commission': -1, 'swap': 0, 'entry_commission': 0},
            {'position_id': 'p5', 'profit': 60, 'commission': -1, 'swap': 0, 'entry_commission': 0},
        ]
        
        stats = self.service.compute_statistics(rows)
        
        self.assertIsNotNone(stats)
        self.assertEqual(stats.trades, 5)
        self.assertEqual(stats.win_rate, 0.6)
        self.assertEqual(stats.net_pnl, 95.0)
        self.assertEqual(stats.avg_pnl, 19.0)
    
    def test_detect_session(self):
        """Test trading session detection."""
        ts_asia = datetime(2026, 10, 15, 5, 0, tzinfo=timezone.utc)
        self.assertEqual(self.service.detect_session(ts_asia), TradingSession.ASIA)
        
        ts_london = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(self.service.detect_session(ts_london), TradingSession.LONDON)
        
        ts_newyork = datetime(2026, 10, 15, 18, 0, tzinfo=timezone.utc)
        self.assertEqual(self.service.detect_session(ts_newyork), TradingSession.NEWYORK)
    
    def test_bucket_regime(self):
        """Test regime bucketing."""
        self.assertEqual(
            self.service.bucket_regime('breakout_continuation'),
            RegimeBucket.TREND
        )
        self.assertEqual(
            self.service.bucket_regime('range'),
            RegimeBucket.RANGE
        )
    
    def test_propose_adjustments_insufficient_sample(self):
        """Test adjustments with insufficient data."""
        stats = TradeStatistics(trades=10, win_rate=0.4, net_pnl=-20.0, avg_pnl=-2.0)
        state = LearningState()
        adj = self.service.propose_adjustments(stats, state)
        
        self.assertFalse(adj.has_changes)
        self.assertEqual(adj.reason, 'insufficient_sample_10')
    
    def test_propose_adjustments_severe(self):
        """Test severe underperformance."""
        stats = TradeStatistics(trades=20, win_rate=0.35, net_pnl=-100.0, avg_pnl=-5.0)
        state = LearningState(risk_mult=1.0, min_grade=SetupGrade.B, min_rr=1.5)
        adj = self.service.propose_adjustments(stats, state)
        
        self.assertTrue(adj.has_changes)
        self.assertEqual(adj.risk_multiplier, 0.9)
        self.assertEqual(adj.min_grade, SetupGrade.A)
        self.assertEqual(adj.min_rr, 1.75)
    
    def test_propose_adjustments_mild(self):
        """Test mild underperformance."""
        stats = TradeStatistics(trades=20, win_rate=0.50, net_pnl=-50.0, avg_pnl=-2.5)
        state = LearningState(risk_mult=1.0)
        adj = self.service.propose_adjustments(stats, state)
        
        self.assertTrue(adj.has_changes)
        self.assertEqual(adj.risk_multiplier, 0.9)
        self.assertIsNone(adj.min_grade)
        self.assertIsNone(adj.min_rr)
    
    def test_apply_adjustments_tighten_only(self):
        """Test tighten-only policy."""
        current = LearningState(risk_mult=0.7, min_grade=SetupGrade.B, min_rr=1.75)
        adj = LearningAdjustments(
            risk_multiplier=0.9,  # Try to relax
            min_grade=SetupGrade.C,
            min_rr=1.5,
            reason='test',
        )
        
        new_state = self.service.apply_adjustments(current, adj)
        
        self.assertEqual(new_state.risk_mult, 0.7)  # Can't increase
        self.assertEqual(new_state.min_grade, SetupGrade.B)  # Can't loosen


if __name__ == '__main__':
    unittest.main()
