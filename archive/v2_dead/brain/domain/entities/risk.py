"""Risk management domain entities.

Domain model for account risk assessment, performance tracking,
and position sizing calculations.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RiskRegime(Enum):
    """Account risk regime levels.
    
    NORMAL: Full operations, standard risk
    DEFENSIVE: Reduced risk after losses
    RECOVERY: Half risk after drawdown
    LOCKED: No new trades (critical state)
    """
    NORMAL = "normal"
    DEFENSIVE = "defensive"
    RECOVERY = "recovery"
    LOCKED = "locked"


@dataclass(frozen=True)
class PerformanceState:
    """Daily trading performance snapshot."""
    day: str  # YYYY-MM-DD
    starting_balance: float
    daily_pnl: float
    daily_gross_pnl: float
    loss_streak: int
    trades_today: int
    last_closed_ticket: Optional[int]
    recent_closed: list[dict]  # Last 10 closed deals for DEFCON
    
    @property
    def is_losing_day(self) -> bool:
        return self.daily_pnl < 0
    
    @property
    def has_trades(self) -> bool:
        return self.trades_today > 0


@dataclass(frozen=True)
class AccountPolicy:
    """Risk policy and trading restrictions."""
    balance: float
    equity: float
    free_margin: float
    margin: float
    open_positions: int
    drawdown_pct: float
    margin_ratio: float
    base_risk_pct: float
    risk_multiplier: float
    trade_allowed: bool
    regime: RiskRegime
    reasons: list[str]
    max_positions_allowed: int
    
    @property
    def is_healthy(self) -> bool:
        return self.regime in {RiskRegime.NORMAL, RiskRegime.DEFENSIVE}
    
    @property
    def is_locked(self) -> bool:
        return self.regime == RiskRegime.LOCKED
    
    @property
    def effective_risk_pct(self) -> float:
        return self.base_risk_pct * self.risk_multiplier
    
    def to_dict(self) -> dict:
        """Legacy dict format for backward compatibility."""
        return {
            "balance": self.balance,
            "equity": self.equity,
            "free_margin": self.free_margin,
            "margin": self.margin,
            "open_positions": self.open_positions,
            "drawdown_pct": self.drawdown_pct,
            "margin_ratio": self.margin_ratio,
            "base_risk_pct": self.base_risk_pct,
            "risk_multiplier": self.risk_multiplier,
            "trade_allowed": self.trade_allowed,
            "regime": self.regime.value,
            "reasons": self.reasons,
            "max_positions_allowed": self.max_positions_allowed,
        }


@dataclass(frozen=True)
class RiskBudget:
    """Calculated risk budget for a trade."""
    trade_allowed: bool
    risk_pct: Optional[float]
    risk_usd: Optional[float]
    reason: Optional[str]
    regime: RiskRegime
    
    @property
    def is_approved(self) -> bool:
        return self.trade_allowed and self.risk_pct and self.risk_pct > 0
    
    def to_dict(self) -> dict:
        """Legacy dict format."""
        return {
            "trade_allowed": self.trade_allowed,
            "risk_pct": self.risk_pct,
            "risk_usd": self.risk_usd,
            "reason": self.reason,
            "regime": self.regime.value,
        }
