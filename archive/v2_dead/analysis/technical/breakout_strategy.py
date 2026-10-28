"""Breakout Strategy - Catch strong moves.

Strategy:
- Identify consolidation
- Wait for breakout with volume
- Enter on retest
- Ride the move
"""
from typing import Optional
from datetime import datetime

from brain.domain.services.market_analyzer import AnalysisResult
from brain.domain.entities.market import MarketState


class BreakoutStrategy:
    """Breakout trading strategy."""
    
    def __init__(self):
        self.name = "Breakout"
        self.min_candles = 100
    
    def get_name(self) -> str:
        """Return strategy name."""
        return self.name
    
    def analyze(self, market: MarketState) -> AnalysisResult:
        """Detect breakouts."""
        candles = market.candles[-150:]
        current = market.current_price
        
        if len(candles) < self.min_candles:
            return self._no_signal("Insufficient data")
        
        # Find consolidation range (last 50 candles)
        consolidation = candles[-50:-5]  # Exclude last 5
        recent = candles[-5:]  # Last 5 for breakout
        
        # Range boundaries
        high = max(c.high for c in consolidation)
        low = min(c.low for c in consolidation)
        range_size = high - low
        
        # Too wide = not consolidation
        if range_size > current * 0.02:  # 2% of price
            return self._no_signal("No consolidation")
        
        # Check for breakout
        breakout_high = max(c.high for c in recent)
        breakout_low = min(c.low for c in recent)
        
        signal = None
        confidence = 0.6
        reasoning = []
        
        # Bullish breakout
        if breakout_high > high:
            signal = "buy"
            confidence = 0.75
            reasoning.append(f"Breakout above {high:.1f}")
            
            # Volume confirmation (approximation using range)
            if recent[-1].high - recent[-1].low > range_size:
                confidence += 0.1
                reasoning.append("Strong momentum")
        
        # Bearish breakout
        elif breakout_low < low:
            signal = "sell"
            confidence = 0.75
            reasoning.append(f"Breakout below {low:.1f}")
            
            if recent[-1].high - recent[-1].low > range_size:
                confidence += 0.1
                reasoning.append("Strong momentum")
        
        else:
            return self._no_signal("No breakout yet")
        
        # Calculate targets
        if signal == "buy":
            sl = low - 5
            tp = current + (range_size * 2)  # 2x range
        else:
            sl = high + 5
            tp = current - (range_size * 2)
        
        return AnalysisResult(
            trend="breakout",
            confidence=confidence,
            signal_direction=signal,
            entry_price=current,
            stop_loss=sl,
            take_profit=tp,
            reasoning=" | ".join(reasoning),
            patterns=[f"Breakout-{signal}"],
            quality_score=confidence,
            trend_strength=range_size / current * 1000,
            timestamp=datetime.now()
        )
    
    def _no_signal(self, reason: str) -> AnalysisResult:
        return AnalysisResult(
            trend="none",
            confidence=0.0,
            signal_direction="hold",
            entry_price=0,
            stop_loss=0,
            take_profit=0,
            reasoning=reason,
            patterns=[],
            quality_score=0.0,
            trend_strength=0.0,
            timestamp=datetime.now()
        )
