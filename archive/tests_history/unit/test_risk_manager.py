"""Unit tests for Risk Manager."""
import pytest
from brain.domain.services.risk_manager import RiskManager
from brain.domain.entities.account import AccountState
from brain.domain.value_objects.risk import RiskParameters


class TestRiskManager:
    """Test RiskManager service."""
    
    def setup_method(self):
        """Setup for each test."""
        self.params = RiskParameters(
            max_risk_per_trade_pct=2.0,
            min_risk_reward=2.0,
            max_daily_loss_pct=5.0,
            max_daily_trades=5,
            max_open_positions=1,
            max_position_size=10.0,
            sl_range=(10, 100)
        )
        self.risk_manager = RiskManager(self.params)
    
    def test_check_daily_loss_ok(self):
        """Test daily loss check passes."""
        account = AccountState(
            balance=5000.0,
            equity=4950.0,  # -50 = 1% loss
            margin=0.0,
            free_margin=4950.0,
            margin_level=0.0,
            profit=-50.0,
            open_positions=0,
            open_positions_volume=0.0
        )
        
        result = self.risk_manager.check_risk(account)
        assert result.allowed is True
    
    def test_check_daily_loss_exceeded(self):
        """Test daily loss check fails."""
        account = AccountState(
            balance=5000.0,
            equity=4700.0,  # -300 = 6% loss
            margin=0.0,
            free_margin=4700.0,
            margin_level=0.0,
            profit=-300.0,
            open_positions=0,
            open_positions_volume=0.0
        )
        
        result = self.risk_manager.check_risk(account)
        assert result.allowed is False
        assert 'daily loss' in result.reason.lower()
    
    def test_max_positions_check(self):
        """Test max positions check."""
        account = AccountState(
            balance=5000.0,
            equity=5000.0,
            margin=200.0,
            free_margin=4800.0,
            margin_level=2500.0,
            profit=0.0,
            open_positions=2,  # Exceeds max of 1
            open_positions_volume=0.2
        )
        
        result = self.risk_manager.check_risk(account)
        assert result.allowed is False
        assert 'positions' in result.reason.lower()
    
    def test_calculate_position_size(self):
        """Test position size calculation."""
        balance = 5000.0
        sl_distance = 20.0  # points
        
        size = self.risk_manager.calculate_position_size(
            balance=balance,
            sl_distance_points=sl_distance
        )
        
        # Risk = 2% of 5000 = $100
        # Size = 100 / (20 * 1) = 5.0 lots (if tick_value=1)
        assert size > 0
        assert size <= self.params.max_position_size
