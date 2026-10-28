"""Unit tests for Domain Entities."""
import pytest
from datetime import datetime, timezone
from brain.domain.entities.market import MarketState, Trend
from brain.domain.entities.account import AccountState
from brain.domain.value_objects.price import Price


class TestMarketState:
    """Test MarketState entity."""
    
    def test_create_market_state(self):
        """Test creating a market state."""
        state = MarketState(
            symbol="XAUUSD",
            timeframe="M15",
            current_price=Price(bid=2650.50, ask=2650.70),
            trend=Trend.BULLISH,
            atr=15.5,
            timestamp=datetime.now(timezone.utc)
        )
        
        assert state.symbol == "XAUUSD"
        assert state.trend == Trend.BULLISH
        assert state.atr == 15.5
    
    def test_market_state_immutable(self):
        """Test that MarketState is immutable."""
        state = MarketState(
            symbol="XAUUSD",
            timeframe="M15",
            current_price=Price(bid=2650.50, ask=2650.70),
            trend=Trend.BULLISH,
            atr=15.5,
            timestamp=datetime.now(timezone.utc)
        )
        
        with pytest.raises(Exception):
            state.symbol = "EURUSD"  # Should fail


class TestAccountState:
    """Test AccountState entity."""
    
    def test_create_account_state(self):
        """Test creating an account state."""
        account = AccountState(
            balance=5000.0,
            equity=5100.0,
            margin=200.0,
            free_margin=4900.0,
            margin_level=2550.0,
            profit=100.0,
            open_positions=1,
            open_positions_volume=0.1
        )
        
        assert account.balance == 5000.0
        assert account.profit == 100.0
        assert account.open_positions == 1
    
    def test_account_margin_level(self):
        """Test margin level calculation."""
        account = AccountState(
            balance=5000.0,
            equity=5000.0,
            margin=100.0,
            free_margin=4900.0,
            margin_level=5000.0,
            profit=0.0,
            open_positions=1,
            open_positions_volume=0.1
        )
        
        assert account.margin_level == 5000.0
        assert account.free_margin == 4900.0
