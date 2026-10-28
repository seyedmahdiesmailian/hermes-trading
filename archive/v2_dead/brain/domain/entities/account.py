"""Account domain entities."""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class Account:
    """Trading account entity.
    
    Represents a trading account with its identifying information.
    """
    account_number: int
    broker: str
    currency: str = "USD"
    account_type: str = "demo"  # "demo" or "live"
    
    def is_live(self) -> bool:
        return self.account_type.lower() == "live"
    
    def is_demo(self) -> bool:
        return self.account_type.lower() == "demo"
    
    def __repr__(self) -> str:
        type_emoji = "🔴" if self.is_live() else "🟡"
        return f"Account({type_emoji} #{self.account_number} {self.broker})"


@dataclass
class AccountState:
    """Current account state snapshot.
    
    Represents the real-time state of a trading account.
    Used by risk management and decision making.
    """
    # Core financials
    balance: float
    equity: float
    margin_free: float
    margin_used: float = 0.0
    
    # Position tracking
    open_positions: int = 0
    open_positions_volume: float = 0.0
    
    # Daily tracking
    daily_pnl: float = 0.0
    daily_trades: int = 0
    daily_wins: int = 0
    daily_losses: int = 0
    
    # Timestamps
    timestamp: Optional[datetime] = None
    
    def profit_today(self) -> float:
        """Today's profit/loss."""
        return self.daily_pnl
    
    def profit_today_pct(self) -> float:
        """Today's profit/loss as percentage of balance."""
        return (self.daily_pnl / self.balance * 100) if self.balance > 0 else 0.0
    
    def win_rate_today(self) -> float:
        """Today's win rate (0.0 to 1.0)."""
        total = self.daily_wins + self.daily_losses
        return self.daily_wins / total if total > 0 else 0.0
    
    def margin_level(self) -> float:
        """Margin level percentage."""
        return (self.equity / self.margin_used * 100) if self.margin_used > 0 else 0.0
    
    def is_profitable_today(self) -> bool:
        return self.daily_pnl > 0
    
    def has_open_positions(self) -> bool:
        return self.open_positions > 0
    
    def __repr__(self) -> str:
        pnl_emoji = "💰" if self.daily_pnl > 0 else "📉" if self.daily_pnl < 0 else "➖"
        return (
            f"AccountState(Balance:{self.balance:.2f} Equity:{self.equity:.2f} "
            f"Open:{self.open_positions} {pnl_emoji}Today:{self.daily_pnl:.2f})"
        )
