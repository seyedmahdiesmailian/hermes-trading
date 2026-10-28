"""Trade domain entities."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid


class OrderType(Enum):
    """Order direction."""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """Order lifecycle status."""
    PENDING = "pending"      # Created but not sent
    SUBMITTED = "submitted"  # Sent to broker
    OPEN = "open"            # Active position
    CLOSED = "closed"        # Position closed
    CANCELLED = "cancelled"  # Order cancelled
    REJECTED = "rejected"    # Order rejected by broker


@dataclass
class Order:
    """Trading order entity.
    
    Represents an order intent with all parameters needed for execution.
    Immutable once created (use replace() for modifications).
    """
    symbol: str
    type: OrderType
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    comment: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now())
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: OrderStatus = OrderStatus.PENDING
    
    def __post_init__(self):
        """Validate order parameters."""
        if self.volume <= 0:
            raise ValueError(f"Invalid volume: {self.volume}")
        if self.entry_price <= 0:
            raise ValueError(f"Invalid entry price: {self.entry_price}")
        if self.stop_loss <= 0:
            raise ValueError(f"Invalid stop loss: {self.stop_loss}")
        if self.take_profit <= 0:
            raise ValueError(f"Invalid take profit: {self.take_profit}")
    
    def risk_reward_ratio(self) -> float:
        """Calculate risk:reward ratio.
        
        Returns reward/risk (e.g., 2.0 means 2:1 RR).
        """
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        return reward / risk if risk > 0 else 0.0
    
    def risk_amount(self) -> float:
        """Calculate risk in price points."""
        return abs(self.entry_price - self.stop_loss) * self.volume
    
    def reward_amount(self) -> float:
        """Calculate potential reward in price points."""
        return abs(self.take_profit - self.entry_price) * self.volume
    
    def is_buy(self) -> bool:
        return self.type == OrderType.BUY
    
    def is_sell(self) -> bool:
        return self.type == OrderType.SELL
    
    def __repr__(self) -> str:
        direction = "📈" if self.is_buy() else "📉"
        return (
            f"Order({direction} {self.symbol} {self.volume} lots "
            f"@ {self.entry_price}, SL:{self.stop_loss}, TP:{self.take_profit}, "
            f"RR:{self.risk_reward_ratio():.1f})"
        )


@dataclass
class Position:
    """Open trading position entity.
    
    Represents an active position in the market with real-time tracking.
    Mutable because price/profit updates frequently.
    """
    ticket: int              # Broker ticket ID
    order: Order             # Original order
    open_time: datetime
    open_price: float
    current_price: float
    profit: float = 0.0
    
    # Performance tracking
    max_profit: float = 0.0  # MFE (Max Favorable Excursion)
    max_loss: float = 0.0    # MAE (Max Adverse Excursion)
    
    def update_price(self, new_price: float, new_profit: float):
        """Update current price and recalculate metrics.
        
        Args:
            new_price: Current market price
            new_profit: Current P&L from broker
        """
        self.current_price = new_price
        self.profit = new_profit
        
        # Track max favorable/adverse excursion
        if self.profit > self.max_profit:
            self.max_profit = self.profit
        if self.profit < self.max_loss:
            self.max_loss = self.profit
    
    def profit_pct(self) -> float:
        """Profit as percentage of entry."""
        return (self.profit / abs(self.open_price * self.order.volume)) * 100
    
    def duration_seconds(self) -> float:
        """Position duration in seconds."""
        return (datetime.now() - self.open_time).total_seconds()
    
    def is_profitable(self) -> bool:
        return self.profit > 0
    
    def distance_to_sl(self) -> float:
        """Distance from current price to stop loss (in points)."""
        return abs(self.current_price - self.order.stop_loss)
    
    def distance_to_tp(self) -> float:
        """Distance from current price to take profit (in points)."""
        return abs(self.order.take_profit - self.current_price)
    
    def __repr__(self) -> str:
        pnl_emoji = "💰" if self.profit > 0 else "📉"
        return (
            f"Position({pnl_emoji} #{self.ticket} {self.order.symbol} "
            f"{self.order.type.value.upper()} P&L:{self.profit:.2f} "
            f"MFE:{self.max_profit:.2f} MAE:{self.max_loss:.2f})"
        )
