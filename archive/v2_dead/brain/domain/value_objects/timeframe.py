"""Timeframe value objects."""

from dataclasses import dataclass
from enum import Enum


class TimeFrameUnit(Enum):
    """Timeframe unit."""
    MINUTE = "M"
    HOUR = "H"
    DAY = "D"
    WEEK = "W"
    MONTH = "MN"


@dataclass(frozen=True)
class TimeFrame:
    """Immutable timeframe value.
    
    Represents a chart timeframe (e.g., M5, M15, H1, H4, D1).
    """
    value: int
    unit: TimeFrameUnit
    
    def __post_init__(self):
        if self.value <= 0:
            raise ValueError(f"Timeframe value must be positive: {self.value}")
    
    @classmethod
    def from_string(cls, tf_str: str) -> 'TimeFrame':
        """Create TimeFrame from string (e.g., 'M5', 'H1', 'D1').
        
        Args:
            tf_str: Timeframe string (M5, M15, H1, H4, D1, etc)
            
        Returns:
            TimeFrame object
            
        Examples:
            >>> TimeFrame.from_string('M5')
            TimeFrame(5, MINUTE)
            >>> TimeFrame.from_string('H1')
            TimeFrame(1, HOUR)
        """
        tf_str = tf_str.upper()
        
        # Parse unit
        if tf_str.startswith('M'):
            if tf_str == 'MN' or tf_str.startswith('MN'):
                unit = TimeFrameUnit.MONTH
                value_str = tf_str[2:] or '1'
            else:
                unit = TimeFrameUnit.MINUTE
                value_str = tf_str[1:]
        elif tf_str.startswith('H'):
            unit = TimeFrameUnit.HOUR
            value_str = tf_str[1:]
        elif tf_str.startswith('D'):
            unit = TimeFrameUnit.DAY
            value_str = tf_str[1:] or '1'
        elif tf_str.startswith('W'):
            unit = TimeFrameUnit.WEEK
            value_str = tf_str[1:] or '1'
        else:
            raise ValueError(f"Invalid timeframe format: {tf_str}")
        
        # Parse value
        try:
            value = int(value_str) if value_str else 1
        except ValueError:
            raise ValueError(f"Invalid timeframe value: {value_str}")
        
        return cls(value=value, unit=unit)
    
    def to_string(self) -> str:
        """Convert to standard string format.
        
        Returns:
            String like 'M5', 'H1', 'D1'
        """
        return f"{self.unit.value}{self.value}"
    
    def to_minutes(self) -> int:
        """Convert timeframe to minutes.
        
        Returns:
            Total minutes represented by this timeframe
        """
        if self.unit == TimeFrameUnit.MINUTE:
            return self.value
        elif self.unit == TimeFrameUnit.HOUR:
            return self.value * 60
        elif self.unit == TimeFrameUnit.DAY:
            return self.value * 1440
        elif self.unit == TimeFrameUnit.WEEK:
            return self.value * 10080
        elif self.unit == TimeFrameUnit.MONTH:
            return self.value * 43200  # Approximate
        return 0
    
    def is_higher_than(self, other: 'TimeFrame') -> bool:
        """Check if this timeframe is higher than another."""
        return self.to_minutes() > other.to_minutes()
    
    def is_lower_than(self, other: 'TimeFrame') -> bool:
        """Check if this timeframe is lower than another."""
        return self.to_minutes() < other.to_minutes()
    
    def is_intraday(self) -> bool:
        """Check if timeframe is intraday (< 1 day)."""
        return self.to_minutes() < 1440
    
    def __str__(self) -> str:
        return self.to_string()
    
    def __repr__(self) -> str:
        return f"TimeFrame({self.to_string()})"


# Common timeframes
M1 = TimeFrame(1, TimeFrameUnit.MINUTE)
M5 = TimeFrame(5, TimeFrameUnit.MINUTE)
M15 = TimeFrame(15, TimeFrameUnit.MINUTE)
M30 = TimeFrame(30, TimeFrameUnit.MINUTE)
H1 = TimeFrame(1, TimeFrameUnit.HOUR)
H4 = TimeFrame(4, TimeFrameUnit.HOUR)
D1 = TimeFrame(1, TimeFrameUnit.DAY)
W1 = TimeFrame(1, TimeFrameUnit.WEEK)
MN1 = TimeFrame(1, TimeFrameUnit.MONTH)
