"""Market Data Repository Interface.

Defines how the domain accesses market data (prices, candles, ticks).
"""

from abc import ABC, abstractmethod
from typing import List
from datetime import datetime

from brain.domain.entities.market import MarketState, Candle
from brain.domain.value_objects.timeframe import TimeFrame


class IMarketDataRepository(ABC):
    """Market data repository interface.
    
    Implementations can fetch from:
    - MT5 (live data)
    - CSV files (backtest)
    - Database (historical)
    - API (external provider)
    """
    
    @abstractmethod
    def get_current_state(
        self, 
        symbol: str, 
        timeframe: TimeFrame,
        bars_count: int = 500
    ) -> MarketState:
        """Get current market state with recent candles.
        
        Args:
            symbol: Symbol (e.g., "XAUUSD")
            timeframe: Timeframe (e.g., M15)
            bars_count: Number of recent bars to include
            
        Returns:
            MarketState with current price and candles
        """
        ...
    
    @abstractmethod
    def get_candles(
        self,
        symbol: str,
        timeframe: TimeFrame,
        start: datetime,
        end: datetime
    ) -> List[Candle]:
        """Get historical candles for a date range.
        
        Args:
            symbol: Symbol
            timeframe: Timeframe
            start: Start datetime
            end: End datetime
            
        Returns:
            List of Candle objects
        """
        ...
    
    @abstractmethod
    def get_current_price(self, symbol: str) -> float:
        """Get current market price.
        
        Args:
            symbol: Symbol
            
        Returns:
            Current price
        """
        ...
    
    @abstractmethod
    def get_tick(self, symbol: str) -> dict:
        """Get current tick with bid/ask.
        
        Args:
            symbol: Symbol
            
        Returns:
            Dict with bid, ask, time
        """
        ...
