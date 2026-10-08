"""Setup value objects."""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any


class SetupType(Enum):
    """Type of trading setup."""
    # Classic patterns
    BREAKOUT = "breakout"
    PULLBACK = "pullback"
    REVERSAL = "reversal"
    TREND_CONTINUATION = "trend_continuation"
    
    # SMC/ICT patterns
    ORDER_BLOCK = "order_block"
    FAIR_VALUE_GAP = "fair_value_gap"
    LIQUIDITY_SWEEP = "liquidity_sweep"
    BREAK_OF_STRUCTURE = "break_of_structure"
    CHANGE_OF_CHARACTER = "change_of_character"
    
    # Hybrid
    CONFLUENCE = "confluence"  # Multiple factors aligned


@dataclass(frozen=True)
class SetupContext:
    """Immutable setup context.
    
    Captures the complete context and reasoning for a trading setup.
    This is the "why" behind a trade decision.
    """
    setup_type: SetupType
    
    # Technical factors
    trend: str                    # "bullish", "bearish", "ranging"
    trend_strength: float         # 0.0 to 1.0
    
    # Key levels
    support_levels: tuple = ()    # Tuple of prices (immutable)
    resistance_levels: tuple = ()
    
    # Confluence factors (scored 0-1 each)
    technical_score: float = 0.5
    fundamental_score: float = 0.5
    sentiment_score: float = 0.5
    timing_score: float = 0.5
    
    # Additional context
    metadata: Dict[str, Any] | None = None  # Extra info as dict
    
    def __post_init__(self):
        """Validate context."""
        if self.trend not in ["bullish", "bearish", "ranging"]:
            raise ValueError(f"Invalid trend: {self.trend}")
        
        if not 0.0 <= self.trend_strength <= 1.0:
            raise ValueError(f"Trend strength must be 0-1: {self.trend_strength}")
        
        # Validate scores
        for score_name, score in [
            ('technical', self.technical_score),
            ('fundamental', self.fundamental_score),
            ('sentiment', self.sentiment_score),
            ('timing', self.timing_score)
        ]:
            if not 0.0 <= score <= 1.0:
                raise ValueError(f"{score_name}_score must be 0-1: {score}")
    
    def overall_score(self) -> float:
        """Calculate weighted overall score.
        
        Weights:
        - Technical: 40%
        - Fundamental: 20%
        - Sentiment: 20%
        - Timing: 20%
        """
        return (
            self.technical_score * 0.4 +
            self.fundamental_score * 0.2 +
            self.sentiment_score * 0.2 +
            self.timing_score * 0.2
        )
    
    def is_strong_setup(self) -> bool:
        """Check if setup is strong (overall score > 0.7)."""
        return self.overall_score() > 0.7
    
    def is_trend_aligned(self, direction: str) -> bool:
        """Check if setup is aligned with trend.
        
        Args:
            direction: "buy" or "sell"
        """
        if direction.lower() == "buy":
            return self.trend == "bullish"
        elif direction.lower() == "sell":
            return self.trend == "bearish"
        return False
    
    def has_confluence(self, min_factors: int = 3) -> bool:
        """Check if multiple factors are aligned.
        
        A factor is "aligned" if its score > 0.6
        """
        aligned_count = sum([
            1 for score in [
                self.technical_score,
                self.fundamental_score,
                self.sentiment_score,
                self.timing_score
            ]
            if score > 0.6
        ])
        
        return aligned_count >= min_factors
    
    def __repr__(self) -> str:
        score = self.overall_score()
        quality = "🔥" if score > 0.7 else "⭐" if score > 0.5 else "⚠️"
        
        return (
            f"SetupContext({quality} {self.setup_type.value} {self.trend} "
            f"score:{score:.2f} tech:{self.technical_score:.1f} "
            f"fund:{self.fundamental_score:.1f})"
        )
