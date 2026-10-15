"""DEFCON domain entities — safety levels and exit analysis.

Domain model for the closed-trade feedback loop that determines trading
restrictions based on recent performance.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DefconLevel(Enum):
    """Trading safety levels.
    
    GREEN: Normal operations, full risk
    YELLOW: Caution (2+ losses or high SL ratio), half risk, no runners/scale-ins
    RED: Critical (5+ deals, SL-dominated, losing day), manage existing only
    """
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class ExitType(Enum):
    """Trade exit classification."""
    STOP_LOSS = "sl"
    TAKE_PROFIT = "tp"
    MANAGED = "managed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ClosedDeal:
    """A closed MT5 deal with classified exit."""
    ticket: int
    profit: float
    exit_type: ExitType
    side: Optional[str] = None
    comment: Optional[str] = None


@dataclass(frozen=True)
class ExitStatistics:
    """Aggregated exit analysis."""
    total: int
    sl_count: int
    tp_count: int
    managed_count: int
    managed_win_ratio: Optional[float]
    managed_total_pnl: float
    sl_ratio: float
    sl_dominant: bool
    
    @property
    def is_empty(self) -> bool:
        return self.total == 0


@dataclass(frozen=True)
class DefconInsights:
    """DEFCON level with trading restrictions."""
    level: DefconLevel
    risk_multiplier: float
    trade_allowed: bool
    runner_allowed: bool
    scale_in_allowed: bool
    exit_stats: ExitStatistics
    runner_blocked_reason: Optional[str] = None
    
    @property
    def is_green(self) -> bool:
        return self.level == DefconLevel.GREEN
    
    @property
    def is_yellow(self) -> bool:
        return self.level == DefconLevel.YELLOW
    
    @property
    def is_red(self) -> bool:
        return self.level == DefconLevel.RED
    
    def to_dict(self) -> dict:
        """Legacy dict format for backward compatibility."""
        return {
            "defcon": self.level.value,
            "risk_override": self.risk_multiplier if self.risk_multiplier != 1.0 else None,
            "trade_allowed": self.trade_allowed,
            "runner_allowed": self.runner_allowed,
            "scale_in_allowed": self.scale_in_allowed,
            "exit_stats": {
                "total": self.exit_stats.total,
                "sl_count": self.exit_stats.sl_count,
                "tp_count": self.exit_stats.tp_count,
                "managed_count": self.exit_stats.managed_count,
                "managed_win_ratio": self.exit_stats.managed_win_ratio,
                "managed_total_pnl": self.exit_stats.managed_total_pnl,
                "sl_ratio": self.exit_stats.sl_ratio,
                "sl_dominant": self.exit_stats.sl_dominant,
            },
            "runner_blocked_reason": self.runner_blocked_reason,
        }
