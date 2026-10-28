"""Unit tests for Database wrapper.

Run with:
    python3 -m pytest tests/test_database.py -v
    or
    python3 -m unittest tests.test_database
"""

import unittest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone

import sys
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from database import Database


class TestDatabase(unittest.TestCase):
    """Test Database wrapper."""
    
    def setUp(self):
        """Create temporary database for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test.db'
        self.db = Database(str(self.db_path))
    
    def tearDown(self):
        """Clean up temporary database."""
        shutil.rmtree(self.temp_dir)
    
    def test_database_initialization(self):
        """Test database is created with schema."""
        self.assertTrue(self.db_path.exists())
        
        # Check tables exist
        tables = self.db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        table_names = [t['name'] for t in tables]
        
        expected_tables = [
            'plans', 'trades', 'signals', 'position_state',
            'account_snapshots', 'daily_performance',
            'risk_state', 'safety_events',
            'trade_journal', 'learning_adjustments',
            'config', 'system_state'
        ]
        
        for table in expected_tables:
            self.assertIn(table, table_names)
    
    def test_config_operations(self):
        """Test config get/set."""
        # Set string
        self.db.set_config('test_str', 'hello', 'string')
        self.assertEqual(self.db.get_config('test_str'), 'hello')
        
        # Set int
        self.db.set_config('test_int', 42, 'int')
        self.assertEqual(self.db.get_config('test_int'), 42)
        
        # Set float
        self.db.set_config('test_float', 3.14, 'float')
        self.assertAlmostEqual(self.db.get_config('test_float'), 3.14)
        
        # Set bool
        self.db.set_config('test_bool', True, 'bool')
        self.assertTrue(self.db.get_config('test_bool'))
        
        # Default value
        self.assertEqual(self.db.get_config('nonexistent', 'default'), 'default')
    
    def test_plan_operations(self):
        """Test plan save/retrieve."""
        now = int(datetime.now(timezone.utc).timestamp())
        
        plan = {
            'plan_id': 'test-plan-1',
            'symbol': 'XAUUSD',
            'timeframe': 'M15',
            'bias': 'bullish',
            'session': 'london',
            'value_low': 2600.0,
            'value_high': 2610.0,
            'long_entry_low': 2605.0,
            'long_entry_high': 2607.0,
            'atr': 5.0,
            'grade': 'A',
            'setup_score': 0.85,
            'created_at': now,
            'expires_at': now + 3600,
            'status': 'active'
        }
        
        # Save
        plan_id = self.db.save_plan(plan)
        self.assertIsNotNone(plan_id)
        
        # Retrieve
        retrieved = self.db.get_current_plan()
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved['plan_id'], 'test-plan-1')
        self.assertEqual(retrieved['bias'], 'bullish')
        self.assertEqual(retrieved['grade'], 'A')
    
    def test_trade_operations(self):
        """Test trade save/retrieve/update."""
        now = int(datetime.now(timezone.utc).timestamp())
        
        trade = {
            'ticket': 12345,
            'position_id': 67890,
            'symbol': 'XAUUSD',
            'side': 'buy',
            'volume': 0.1,
            'entry_price': 2600.0,
            'stop_loss': 2590.0,
            'take_profit': 2620.0,
            'source': 'plan',
            'source_ref': 'test-plan-1',
            'entry_time': now,
            'status': 'open',
            'comment': 'Test trade'
        }
        
        # Save
        trade_id = self.db.save_trade(trade)
        self.assertIsNotNone(trade_id)
        
        # Retrieve open trades
        open_trades = self.db.get_open_trades()
        self.assertEqual(len(open_trades), 1)
        self.assertEqual(open_trades[0]['ticket'], 12345)
        
        # Update
        self.db.update_trade(12345, {'stop_loss': 2595.0})
        updated = self.db.fetch_one(
            "SELECT stop_loss FROM trades WHERE ticket = ?",
            (12345,)
        )
        self.assertEqual(updated['stop_loss'], 2595.0)
        
        # Close trade
        self.db.close_trade(
            ticket=12345,
            exit_price=2615.0,
            profit=150.0,
            exit_reason='tp',
            commission=-2.0,
            swap=-1.0
        )
        
        closed = self.db.fetch_one(
            "SELECT * FROM trades WHERE ticket = ?",
            (12345,)
        )
        self.assertEqual(closed['status'], 'closed')
        self.assertEqual(closed['exit_price'], 2615.0)
        self.assertEqual(closed['net_pnl'], 147.0)  # 150 - 2 - 1
    
    def test_signal_operations(self):
        """Test signal save/retrieve/update."""
        now = int(datetime.now(timezone.utc).timestamp())
        
        signal = {
            'signal_id': 'sig-test-1',
            'symbol': 'XAUUSD',
            'direction': 'buy',
            'entry_price': 2600.0,
            'stop_loss': 2590.0,
            'take_profit': 2620.0,
            'source': 'telegram',
            'source_id': 'msg-123',
            'raw_message': 'BUY GOLD @ 2600',
            'confidence_score': 0.75,
            'quality': 'good',
            'status': 'pending',
            'received_at': now
        }
        
        # Save
        sig_id = self.db.save_signal(signal)
        self.assertIsNotNone(sig_id)
        
        # Retrieve pending
        pending = self.db.get_pending_signals()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['signal_id'], 'sig-test-1')
        
        # Update status
        self.db.update_signal_status(
            'sig-test-1',
            'accepted',
            'Passed all checks'
        )
        
        updated = self.db.fetch_one(
            "SELECT status, decision_reasoning FROM signals WHERE signal_id = ?",
            ('sig-test-1',)
        )
        self.assertEqual(updated['status'], 'accepted')
        self.assertEqual(updated['decision_reasoning'], 'Passed all checks')
    
    def test_risk_state(self):
        """Test risk state operations."""
        # Initial state
        state = self.db.get_risk_state()
        self.assertEqual(state['defcon_level'], 'GREEN')
        self.assertEqual(state['risk_multiplier'], 1.0)
        
        # Update state
        now = int(datetime.now(timezone.utc).timestamp())
        new_state = {
            'defcon_level': 'YELLOW',
            'loss_streak': 2,
            'daily_loss_pct': 0.03,
            'kill_switch_active': False,
            'risk_multiplier': 0.5,
            'min_grade': 'A'
        }
        self.db.update_risk_state(new_state)
        
        # Retrieve
        updated = self.db.get_risk_state()
        self.assertEqual(updated['defcon_level'], 'YELLOW')
        self.assertEqual(updated['loss_streak'], 2)
        self.assertEqual(updated['risk_multiplier'], 0.5)
    
    def test_safety_events(self):
        """Test safety event logging."""
        self.db.log_safety_event(
            event_type='kill_switch',
            severity='critical',
            message='Kill switch activated',
            data={'reason': 'max_daily_loss', 'loss': -0.05}
        )
        
        events = self.db.fetch_all(
            "SELECT * FROM safety_events ORDER BY created_at DESC LIMIT 1"
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['event_type'], 'kill_switch')
        self.assertEqual(events[0]['severity'], 'critical')
    
    def test_daily_pnl(self):
        """Test daily P&L calculation."""
        # No data yet
        pnl = self.db.get_daily_pnl('2026-10-15')
        self.assertEqual(pnl, 0.0)
        
        # Add performance data
        self.db.execute(
            """INSERT INTO daily_performance (date, net_pnl, total_trades, win_rate)
            VALUES ('2026-10-15', 250.50, 5, 0.6)"""
        )
        
        pnl = self.db.get_daily_pnl('2026-10-15')
        self.assertAlmostEqual(pnl, 250.50)
    
    def test_transaction_rollback(self):
        """Test transaction rollback on error."""
        try:
            with self.db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO config (key, value) VALUES ('test', 'value')"
                )
                # Force error
                conn.execute("INSERT INTO nonexistent_table VALUES (1)")
                conn.commit()
        except:
            pass
        
        # Check that first insert was rolled back
        result = self.db.get_config('test')
        self.assertIsNone(result)
    
    def test_views(self):
        """Test database views."""
        # Test v_active_trades view exists
        result = self.db.fetch_all("SELECT * FROM v_active_trades")
        self.assertIsNotNone(result)
        
        # Test v_current_plan view
        result = self.db.fetch_all("SELECT * FROM v_current_plan")
        self.assertIsNotNone(result)


if __name__ == '__main__':
    unittest.main()
