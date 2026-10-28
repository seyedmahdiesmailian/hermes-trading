"""SMC/ICT domain entities.

Domain model for Smart Money Concepts analysis - order blocks,
fair value gaps, liquidity, structure, and confluences.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class OrderBlockType(Enum):
    """Order block direction."""
    BULLISH = "bullish"
    BEARISH = "bearish"


class FVGType(Enum):
    """Fair value gap direction."""
    BULLISH = "bullish"
    BEARISH = "bearish"


class StructurePhase(Enum):
    """Market structure phase."""
    BOS_BULLISH = "bos_bullish"  # Break of structure bullish
    BOS_BEARISH = "bos_bearish"  # Break of structure bearish
    CHOCH_BULLISH = "choch_bullish"  # Change of character bullish
    CHOCH_BEARISH = "choch_bearish"  # Change of character bearish
    RANGE = "range"
    UNKNOWN = "unknown"


class PremiumDiscountZone(Enum):
    """Price position in swing range."""
    PREMIUM = "premium"  # 75-100% (sell zone)
    EQUILIBRIUM = "equilibrium"  # 25-75%
    DISCOUNT = "discount"  # 0-25% (buy zone)


class POIGrade(Enum):
    """Point of Interest grade (confluence quality)."""
    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"


@dataclass(frozen=True)
class OrderBlock:
    """Institutional entry zone (last opposite candle before breakout)."""
    ob_type: OrderBlockType
    high: float
    low: float
    open_price: float
    close: float
    index: int  # Bar index in data
    mitigated: bool
    
    @property
    def zone_range(self) -> tuple[float, float]:
        """(low, high) tuple."""
        return (self.low, self.high)
    
    def to_dict(self) -> dict:
        """Convert to legacy dict format."""
        return {
            'type': self.ob_type.value,
            'high': self.high,
            'low': self.low,
            'open': self.open_price,
            'close': self.close,
            'index': self.index,
            'mitigated': self.mitigated,
        }


@dataclass(frozen=True)
class FairValueGap:
    """Imbalance zone (3-candle gap pattern)."""
    fvg_type: FVGType
    low: float
    high: float
    c1_index: int  # First candle index
    c3_index: int  # Third candle index
    filled: bool
    
    @property
    def gap_range(self) -> tuple[float, float]:
        """(low, high) tuple."""
        return (self.low, self.high)
    
    @property
    def gap_size(self) -> float:
        """Gap width."""
        return self.high - self.low
    
    def to_dict(self) -> dict:
        """Convert to legacy dict format."""
        return {
            'type': self.fvg_type.value,
            'low': self.low,
            'high': self.high,
            'c1_index': self.c1_index,
            'c3_index': self.c3_index,
            'filled': self.filled,
        }


@dataclass(frozen=True)
class LiquiditySweep:
    """Stop hunt detection."""
    swept: bool
    swept_level: Optional[float]
    sweep_side: Optional[str]  # 'bullish' or 'bearish'
    
    @property
    def is_bullish_sweep(self) -> bool:
        """Low swept (buy-side liquidity taken)."""
        return self.sweep_side == 'bullish'
    
    @property
    def is_bearish_sweep(self) -> bool:
        """High swept (sell-side liquidity taken)."""
        return self.sweep_side == 'bearish'


@dataclass(frozen=True)
class MarketStructure:
    """Market structure state."""
    phase: StructurePhase
    confidence: float  # 0.0-1.0
    
    @property
    def is_bullish(self) -> bool:
        return self.phase in (StructurePhase.BOS_BULLISH, StructurePhase.CHOCH_BULLISH)
    
    @property
    def is_bearish(self) -> bool:
        return self.phase in (StructurePhase.BOS_BEARISH, StructurePhase.CHOCH_BEARISH)
    
    @property
    def is_trending(self) -> bool:
        return self.phase in (
            StructurePhase.BOS_BULLISH,
            StructurePhase.BOS_BEARISH,
            StructurePhase.CHOCH_BULLISH,
            StructurePhase.CHOCH_BEARISH,
        )


@dataclass(frozen=True)
class PremiumDiscount:
    """Price position in swing range."""
    zone: PremiumDiscountZone
    fib_level: float  # 0.0-1.0
    quality: int  # 0-100
    swing_high: float
    swing_low: float
    
    @property
    def in_discount(self) -> bool:
        return self.zone == PremiumDiscountZone.DISCOUNT
    
    @property
    def in_premium(self) -> bool:
        return self.zone == PremiumDiscountZone.PREMIUM
    
    def to_dict(self) -> dict:
        """Convert to legacy dict format."""
        return {
            'zone': self.zone.value,
            'fib_level': self.fib_level,
            'quality': self.quality,
            'swing_high': self.swing_high,
            'swing_low': self.swing_low,
        }


@dataclass(frozen=True)
class KillzoneSession:
    """Trading session killzone."""
    name: str  # london, newyork, asia, london_close, dead
    weight: float  # 0.0-1.0
    
    @property
    def is_active(self) -> bool:
        return self.weight > 0.0
    
    @property
    def is_prime(self) -> bool:
        """High-quality trading time."""
        return self.weight >= 0.8


@dataclass(frozen=True)
class SMCAnalysis:
    """Complete SMC/ICT analysis result."""
    # Order blocks
    order_blocks: list[OrderBlock]
    unmitigated_obs: list[OrderBlock]
    
    # Fair value gaps
    fvgs: list[FairValueGap]
    unfilled_fvgs: list[FairValueGap]
    
    # Liquidity
    liquidity_sweep: LiquiditySweep
    
    # Structure
    structure: MarketStructure
    h1_structure: Optional[MarketStructure]
    
    # Premium/Discount
    pd_zone: PremiumDiscount
    
    # Killzone
    killzone: KillzoneSession
    
    # POI grade
    poi_grade: POIGrade
    
    # Derived bias
    smc_bias: str  # 'bullish', 'bearish', 'neutral'
    bias_score: float
    confidence: float
    
    def to_dict(self) -> dict:
        """Convert to legacy dict format."""
        return {
            'order_blocks': [ob.to_dict() for ob in self.order_blocks],
            'unmitigated_obs': [ob.to_dict() for ob in self.unmitigated_obs],
            'fvgs': [fvg.to_dict() for fvg in self.fvgs],
            'unfilled_fvgs': [fvg.to_dict() for fvg in self.unfilled_fvgs],
            'liquidity_sweep': {
                'swept': self.liquidity_sweep.swept,
                'swept_level': self.liquidity_sweep.swept_level,
                'sweep_side': self.liquidity_sweep.sweep_side,
            },
            'structure_phase': self.structure.phase.value,
            'structure_confidence': self.structure.confidence,
            'h1_structure_phase': self.h1_structure.phase.value if self.h1_structure else 'unknown',
            'h1_structure_confidence': self.h1_structure.confidence if self.h1_structure else 0.0,
            'pd_zone': self.pd_zone.to_dict(),
            'killzone': {
                'session': self.killzone.name,
                'weight': self.killzone.weight,
            },
            'poi_grade': self.poi_grade.value,
            'smc_bias': self.smc_bias,
            'bias_score': self.bias_score,
            'confidence': self.confidence,
        }
