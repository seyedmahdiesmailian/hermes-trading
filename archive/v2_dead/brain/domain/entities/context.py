"""Context domain entities.

Domain model for market context analysis - ATR, bias, zones, structure.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MarketBias(Enum):
    """Directional market bias."""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class ZoneSource(Enum):
    """Source of structure zones."""
    H1_SWING = "h1_swing"
    H1_SWING_WIDE = "h1_swing_wide"
    M5_TIGHT = "m5_tight"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class PriceZones:
    """Price zones for entries (discount/premium)."""
    value_low: float  # Discount high (buy zone top)
    value_high: float  # Premium low (sell zone bottom)
    long_entry_low: float  # Swing low
    long_entry_high: float  # Discount high
    short_entry_low: float  # Premium low
    short_entry_high: float  # Swing high
    swing_low: Optional[float] = None
    swing_high: Optional[float] = None
    zone_source: Optional[ZoneSource] = None
    
    @property
    def discount_zone(self) -> tuple[float, float]:
        """Buy zone range."""
        return (self.long_entry_low, self.long_entry_high)
    
    @property
    def premium_zone(self) -> tuple[float, float]:
        """Sell zone range."""
        return (self.short_entry_low, self.short_entry_high)
    
    @property
    def value_zone(self) -> tuple[float, float]:
        """Fair value range."""
        return (self.value_low, self.value_high)
    
    def to_dict(self) -> dict:
        """Convert to legacy dict format."""
        d: dict = {
            'value_low': self.value_low,
            'value_high': self.value_high,
            'long_entry_low': self.long_entry_low,
            'long_entry_high': self.long_entry_high,
            'short_entry_low': self.short_entry_low,
            'short_entry_high': self.short_entry_high,
        }
        if self.swing_low is not None:
            d['swing_low'] = self.swing_low
        if self.swing_high is not None:
            d['swing_high'] = self.swing_high
        if self.zone_source is not None:
            d['zone_source'] = self.zone_source.value
        return d


@dataclass(frozen=True)
class ExecutionPlan:
    """Execution strategy for a trading plan."""
    entry_target: float
    sl_target: float
    tp_levels: list[float]
    entry_method: str  # 'limit', 'market', 'stop'
    
    def to_dict(self) -> dict:
        """Convert to legacy dict format."""
        return {
            'entry_target': self.entry_target,
            'sl_target': self.sl_target,
            'tp_levels': self.tp_levels,
            'entry_method': self.entry_method,
        }


@dataclass(frozen=True)
class MarketContext:
    """Complete market context for plan creation."""
    bias: MarketBias
    atr: float
    zones: PriceZones
    execution: ExecutionPlan
    invalidation: float
    targets: list[float]
    regime: Optional[str] = None  # From quality assessment
    
    @property
    def is_directional(self) -> bool:
        """Check if bias is directional."""
        return self.bias in (MarketBias.BULLISH, MarketBias.BEARISH)
    
    @property
    def is_trend(self) -> bool:
        """Check if regime is trending."""
        return self.regime in ('breakout_continuation', 'pullback_continuation')
    
    def to_dict(self) -> dict:
        """Convert to legacy dict format."""
        return {
            'bias': self.bias.value,
            'atr': self.atr,
            'zones': self.zones.to_dict(),
            'execution': self.execution.to_dict(),
            'invalidation': self.invalidation,
            'targets': self.targets,
            'regime': self.regime,
        }
