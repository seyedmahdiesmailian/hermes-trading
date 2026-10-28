"""Risk management value objects."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskParameters:
    """Immutable risk management parameters.
    
    Defines the risk rules for trading.
    Frozen to ensure consistency across the system.
    """
    # Per-trade risk
    max_risk_per_trade_pct: float = 0.02    # 2% of balance
    min_risk_reward: float = 2.0             # Minimum RR ratio
    
    # Daily limits
    max_daily_loss_pct: float = 0.05         # 5% daily loss limit
    max_daily_trades: int = 5                # Max trades per day
    
    # Position limits
    max_open_positions: int = 1              # Max simultaneous positions
    max_position_size_lots: float = 10.0     # Max lot size
    
    # Stop loss limits
    max_stop_loss_points: float = 100.0      # Max SL distance
    min_stop_loss_points: float = 10.0       # Min SL distance
    
    def __post_init__(self):
        """Validate risk parameters."""
        if not 0.0 < self.max_risk_per_trade_pct <= 0.10:
            raise ValueError(
                f"Risk per trade must be 0-10%: {self.max_risk_per_trade_pct}"
            )
        
        if self.min_risk_reward < 1.0:
            raise ValueError(
                f"Min RR must be >= 1.0: {self.min_risk_reward}"
            )
        
        if not 0.0 < self.max_daily_loss_pct <= 0.20:
            raise ValueError(
                f"Daily loss limit must be 0-20%: {self.max_daily_loss_pct}"
            )
        
        if self.max_daily_trades < 1:
            raise ValueError(
                f"Max daily trades must be >= 1: {self.max_daily_trades}"
            )
        
        if self.max_open_positions < 1:
            raise ValueError(
                f"Max open positions must be >= 1: {self.max_open_positions}"
            )
    
    def is_conservative(self) -> bool:
        """Check if parameters are conservative."""
        return (
            self.max_risk_per_trade_pct <= 0.01 and  # <= 1%
            self.min_risk_reward >= 2.5 and
            self.max_open_positions == 1
        )
    
    def is_aggressive(self) -> bool:
        """Check if parameters are aggressive."""
        return (
            self.max_risk_per_trade_pct >= 0.03 or  # >= 3%
            self.max_open_positions > 2
        )
    
    def __repr__(self) -> str:
        style = "🛡️ Conservative" if self.is_conservative() else (
            "⚡ Aggressive" if self.is_aggressive() else "⚖️ Balanced"
        )
        return (
            f"RiskParameters({style} {self.max_risk_per_trade_pct*100:.1f}% per trade, "
            f"RR≥{self.min_risk_reward:.1f}, max {self.max_open_positions} positions)"
        )


@dataclass(frozen=True)
class RiskReward:
    """Immutable risk/reward calculation result."""
    risk_points: float
    reward_points: float
    ratio: float
    
    def __post_init__(self):
        if self.risk_points < 0:
            raise ValueError(f"Risk cannot be negative: {self.risk_points}")
        if self.reward_points < 0:
            raise ValueError(f"Reward cannot be negative: {self.reward_points}")
    
    def is_acceptable(self, min_ratio: float = 2.0) -> bool:
        """Check if RR ratio meets minimum."""
        return self.ratio >= min_ratio
    
    def __repr__(self) -> str:
        quality = "✅" if self.ratio >= 2.0 else "⚠️" if self.ratio >= 1.5 else "❌"
        return (
            f"RiskReward({quality} {self.ratio:.1f}:1 "
            f"risk:{self.risk_points:.1f} reward:{self.reward_points:.1f})"
        )
