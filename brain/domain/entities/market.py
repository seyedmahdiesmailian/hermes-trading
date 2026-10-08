"""Market domain entities."""

from dataclasses import dataclass
from datetime import datetime
from typing import List


@dataclass(frozen=True)
class Candle:
    """Immutable candle/bar entity.
    
    Represents a single OHLCV candle for any timeframe.
    Frozen (immutable) to ensure data integrity.
    """
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    
    @property
    def body(self) -> float:
        """Candle body size (absolute)."""
        return abs(self.close - self.open)
    
    @property
    def is_bullish(self) -> bool:
        """True if candle closed higher than open."""
        return self.close > self.open
    
    @property
    def is_bearish(self) -> bool:
        """True if candle closed lower than open."""
        return self.close < self.open
    
    @property
    def upper_wick(self) -> float:
        """Upper wick/shadow size."""
        return self.high - max(self.open, self.close)
    
    @property
    def lower_wick(self) -> float:
        """Lower wick/shadow size."""
        return min(self.open, self.close) - self.low
    
    @property
    def range(self) -> float:
        """Total candle range (high - low)."""
        return self.high - self.low
    
    def __repr__(self) -> str:
        direction = "🟢" if self.is_bullish else "🔴"
        return f"Candle({direction} O:{self.open} H:{self.high} L:{self.low} C:{self.close})"


@dataclass
class MarketState:
    """Current market state snapshot.
    
    Represents the complete state of a market at a given time,
    including historical candles and current price.
    """
    symbol: str
    timeframe: str
    candles: List[Candle]
    current_price: float
    timestamp: datetime
    bid: float | None = None  # Optional bid/ask spread
    ask: float | None = None
    
    def latest_candle(self) -> Candle:
        """Get the most recent closed candle."""
        if not self.candles:
            raise ValueError("No candles available")
        return self.candles[-1]
    
    def previous_candle(self, offset: int = 1) -> Candle:
        """Get a previous candle by offset (1 = previous, 2 = before previous, etc)."""
        if len(self.candles) < offset + 1:
            raise ValueError(f"Not enough candles for offset {offset}")
        return self.candles[-(offset + 1)]
    
    def recent_candles(self, count: int) -> List[Candle]:
        """Get the N most recent candles."""
        return self.candles[-count:] if len(self.candles) >= count else self.candles
    
    def __repr__(self) -> str:
        return (
            f"MarketState({self.symbol} {self.timeframe} "
            f"@ {self.current_price:.2f}, {len(self.candles)} candles)"
        )
