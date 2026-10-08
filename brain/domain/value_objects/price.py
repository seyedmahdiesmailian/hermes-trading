"""Price value objects."""

from dataclasses import dataclass
from enum import Enum


class PriceType(Enum):
    """Price level type."""
    SUPPORT = "support"
    RESISTANCE = "resistance"
    ORDER_BLOCK = "order_block"
    FAIR_VALUE_GAP = "fair_value_gap"
    LIQUIDITY = "liquidity"
    PIVOT = "pivot"


@dataclass(frozen=True)
class Price:
    """Immutable price value.
    
    Represents a price point with optional metadata.
    Frozen to ensure immutability and allow hashing.
    """
    value: float
    
    def __post_init__(self):
        if self.value <= 0:
            raise ValueError(f"Invalid price: {self.value}")
    
    def distance_to(self, other: 'Price') -> float:
        """Calculate distance to another price."""
        return abs(self.value - other.value)
    
    def distance_pct_to(self, other: 'Price') -> float:
        """Calculate distance as percentage."""
        return (abs(self.value - other.value) / self.value) * 100
    
    def is_above(self, other: 'Price') -> bool:
        return self.value > other.value
    
    def is_below(self, other: 'Price') -> bool:
        return self.value < other.value
    
    def __float__(self) -> float:
        return self.value
    
    def __repr__(self) -> str:
        return f"Price({self.value:.5f})"


@dataclass(frozen=True)
class PriceLevel:
    """Immutable price level with context.
    
    Represents a significant price level (support, resistance, etc)
    with type and strength information.
    """
    price: float
    type: PriceType
    strength: float = 0.5  # 0.0 to 1.0
    touches: int = 0       # How many times price touched this level
    
    def __post_init__(self):
        if self.price <= 0:
            raise ValueError(f"Invalid price: {self.price}")
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(f"Strength must be 0-1: {self.strength}")
        if self.touches < 0:
            raise ValueError(f"Touches cannot be negative: {self.touches}")
    
    def is_strong(self) -> bool:
        """Check if level is strong (strength > 0.7)."""
        return self.strength > 0.7
    
    def is_support(self) -> bool:
        return self.type == PriceType.SUPPORT
    
    def is_resistance(self) -> bool:
        return self.type == PriceType.RESISTANCE
    
    def distance_to(self, price: float) -> float:
        """Calculate distance from this level to a price."""
        return abs(self.price - price)
    
    def is_near(self, price: float, threshold: float = 10.0) -> bool:
        """Check if a price is near this level.
        
        Args:
            price: Price to check
            threshold: Distance threshold in points
        """
        return self.distance_to(price) <= threshold
    
    def __repr__(self) -> str:
        strength_emoji = "🔥" if self.is_strong() else "⭐"
        type_emoji = "🟢" if self.is_support() else "🔴" if self.is_resistance() else "📍"
        return (
            f"PriceLevel({type_emoji} {self.type.value} @ {self.price:.2f} "
            f"{strength_emoji}{self.strength:.1f} touches:{self.touches})"
        )
