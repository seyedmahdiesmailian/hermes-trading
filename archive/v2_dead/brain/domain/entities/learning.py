"""Learning domain entities.

Domain model for adaptive learning system - journal management,
trade analysis, and parameter adjustments.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SetupGrade(Enum):
    """Trading setup quality grade."""
    C = "C"
    B = "B"
    A = "A"
    
    def __lt__(self, other):
        if not isinstance(other, SetupGrade):
            return NotImplemented
        grades = [SetupGrade.C, SetupGrade.B, SetupGrade.A]
        return grades.index(self) < grades.index(other)
    
    def __le__(self, other):
        if not isinstance(other, SetupGrade):
            return NotImplemented
        return self == other or self < other
    
    def __gt__(self, other):
        if not isinstance(other, SetupGrade):
            return NotImplemented
        return not self <= other
    
    def __ge__(self, other):
        if not isinstance(other, SetupGrade):
            return NotImplemented
        return not self < other


class TradingSession(Enum):
    """Trading session (UTC hours)."""
    ASIA = "asia"          # 00:00-07:00
    LONDON = "london"      # 07:00-13:00
    NEWYORK = "newyork"    # 13:00-24:00
    UNKNOWN = "unknown"


class RegimeBucket(Enum):
    """Market regime classification."""
    TREND = "trend"
    RANGE = "range"
    OTHER = "other"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class JournalEntry:
    """Single closed trade (closing deal).
    
    Note: One position may have multiple closing deals (partial TPs).
    """
    ticket: str
    close_time: str
    side: str  # BUY or SELL
    volume: float
    price: float
    profit: float
    commission: float
    swap: float
    entry_commission: float
    position_id: str
    comment: str
    journaled_at: str


@dataclass(frozen=True)
class PositionSummary:
    """Aggregated position result (may have multiple legs)."""
    position_id: str
    side: str
    volume: float
    profit: float
    net_pnl: float  # profit + commission + swap + entry_commission
    close_time: float
    legs: int  # Number of partial closes


@dataclass(frozen=True)
class TradeStatistics:
    """Performance statistics for a set of trades."""
    trades: int
    win_rate: float
    net_pnl: float
    avg_pnl: float
    
    @property
    def is_profitable(self) -> bool:
        return self.avg_pnl > 0
    
    @property
    def has_sufficient_sample(self, min_trades: int = 15) -> bool:
        return self.trades >= min_trades


@dataclass(frozen=True)
class AnalysisResult:
    """Complete journal analysis."""
    sample_size: int
    overall: TradeStatistics
    by_side: dict[str, TradeStatistics]
    by_session: dict[str, TradeStatistics]
    by_session_regime: dict[str, dict[str, TradeStatistics]]


@dataclass(frozen=True)
class LearningAdjustments:
    """Proposed parameter adjustments based on performance."""
    risk_multiplier: Optional[float]
    min_grade: Optional[SetupGrade]
    min_rr: Optional[float]
    reason: str
    
    @property
    def has_changes(self) -> bool:
        return any([
            self.risk_multiplier is not None,
            self.min_grade is not None,
            self.min_rr is not None,
        ])
    
    def to_dict(self) -> dict:
        """Convert to legacy dict format."""
        changes = {}
        if self.risk_multiplier is not None:
            changes['risk_mult'] = self.risk_multiplier
        if self.min_grade is not None:
            changes['min_grade'] = self.min_grade.value
        if self.min_rr is not None:
            changes['min_rr'] = self.min_rr
        
        return {
            'reason': self.reason,
            'changes': changes,
        }


@dataclass(frozen=True)
class LearningState:
    """Current learning state (adaptive parameters)."""
    risk_mult: float = 1.0
    min_grade: SetupGrade = SetupGrade.B
    min_rr: float = 1.5
    last_updated: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to legacy dict format."""
        return {
            'risk_mult': self.risk_mult,
            'min_grade': self.min_grade.value,
            'min_rr': self.min_rr,
            'last_updated': self.last_updated or '',
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> LearningState:
        """Create from legacy dict format."""
        return cls(
            risk_mult=float(data.get('risk_mult', 1.0)),
            min_grade=SetupGrade(data.get('min_grade', 'B')),
            min_rr=float(data.get('min_rr', 1.5)),
            last_updated=data.get('last_updated'),
        )
