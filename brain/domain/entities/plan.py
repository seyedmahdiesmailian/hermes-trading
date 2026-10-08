"""Trading plan domain entities."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid


class SetupGrade(Enum):
    """Setup quality grade.
    
    Grades are ordered from best to worst.
    """
    A = "A"  # Excellent — all factors aligned
    B = "B"  # Good — most factors aligned
    C = "C"  # Acceptable — some concerns
    D = "D"  # Poor — significant concerns
    F = "F"  # Failed — should not trade
    
    def is_tradable(self) -> bool:
        """Check if grade is good enough to trade."""
        return self in [SetupGrade.A, SetupGrade.B]
    
    def __lt__(self, other):
        """Allow comparison (A < B < C < D < F)."""
        if not isinstance(other, SetupGrade):
            return NotImplemented
        order = {SetupGrade.A: 0, SetupGrade.B: 1, SetupGrade.C: 2, 
                SetupGrade.D: 3, SetupGrade.F: 4}
        return order[self] < order[other]


class PlanStage(Enum):
    """Trading plan lifecycle stage."""
    ANALYSIS = "analysis"      # Being analyzed
    WAITING = "waiting"        # Waiting for entry conditions
    READY = "ready"            # Ready to execute
    EXECUTED = "executed"      # Order placed
    MONITORING = "monitoring"  # Position open, being managed
    CLOSED = "closed"          # Position closed
    EXPIRED = "expired"        # Setup expired without execution
    REJECTED = "rejected"      # Failed validation


@dataclass
class TradingPlan:
    """Complete trading plan entity.
    
    Represents a full trading setup with analysis, reasoning, and execution parameters.
    This is the core output of the analysis → decision process.
    """
    # Core setup
    symbol: str
    direction: str  # "buy" or "sell"
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float
    
    # Quality and reasoning
    setup_grade: SetupGrade
    reasoning: dict  # Detailed analysis and rationale
    
    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now())
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    stage: PlanStage = PlanStage.ANALYSIS
    
    # Lifecycle timestamps
    executed_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    
    # Execution result (populated after execution)
    ticket: Optional[int] = None
    actual_entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    profit: Optional[float] = None
    
    def __post_init__(self):
        """Validate plan parameters."""
        if self.entry_price <= 0:
            raise ValueError(f"Invalid entry: {self.entry_price}")
        if self.stop_loss <= 0:
            raise ValueError(f"Invalid SL: {self.stop_loss}")
        if self.take_profit <= 0:
            raise ValueError(f"Invalid TP: {self.take_profit}")
        if self.position_size <= 0:
            raise ValueError(f"Invalid size: {self.position_size}")
    
    def is_executable(self) -> bool:
        """Check if plan is ready for execution."""
        return (
            self.stage == PlanStage.READY and
            self.setup_grade.is_tradable()
        )
    
    def risk_reward_ratio(self) -> float:
        """Calculate risk:reward ratio."""
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        return reward / risk if risk > 0 else 0.0
    
    def risk_amount(self) -> float:
        """Calculate risk in price points."""
        return abs(self.entry_price - self.stop_loss) * self.position_size
    
    def potential_profit(self) -> float:
        """Calculate potential profit in price points."""
        return abs(self.take_profit - self.entry_price) * self.position_size
    
    def is_buy(self) -> bool:
        return self.direction.lower() == "buy"
    
    def is_sell(self) -> bool:
        return self.direction.lower() == "sell"
    
    def age_seconds(self) -> float:
        """Plan age in seconds."""
        return (datetime.now() - self.created_at).total_seconds()
    
    def mark_executed(self, ticket: int, actual_entry: float):
        """Mark plan as executed."""
        self.stage = PlanStage.EXECUTED
        self.executed_at = datetime.now()
        self.ticket = ticket
        self.actual_entry_price = actual_entry
    
    def mark_closed(self, exit_price: float, profit: float):
        """Mark plan as closed."""
        self.stage = PlanStage.CLOSED
        self.closed_at = datetime.now()
        self.exit_price = exit_price
        self.profit = profit
    
    def __repr__(self) -> str:
        direction_emoji = "📈" if self.is_buy() else "📉"
        grade_emoji = {"A": "⭐", "B": "✅", "C": "⚠️", "D": "❌", "F": "🚫"}
        
        return (
            f"TradingPlan({direction_emoji} {self.symbol} {self.direction.upper()} "
            f"@ {self.entry_price} Grade:{self.setup_grade.value}{grade_emoji.get(self.setup_grade.value, '')} "
            f"RR:{self.risk_reward_ratio():.1f} {self.stage.value})"
        )
