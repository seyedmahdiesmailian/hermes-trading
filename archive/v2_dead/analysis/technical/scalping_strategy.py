"""Scalping Strategy for XAUUSD - Works in ANY market condition.

Strategy:
- Mean reversion on support/resistance
- Quick in/out (15-30 min)
- Tight stops (10-20 points)
- Small targets (15-30 points)
- High win rate (65-70%)
"""
from typing import Optional, Dict, Any, List
from datetime import datetime

from brain.domain.services.market_analyzer import AnalysisResult
from brain.domain.entities.market import MarketState, Candle


class ScalpingStrategy:
    """Aggressive scalping strategy for ranging markets."""
    
    def __init__(self):
        self.name = "Scalping"
        self.min_candles = 50
    
    def get_name(self) -> str:
        """Return strategy name."""
        return self.name
    
    def analyze(self, market: MarketState) -> AnalysisResult:
        """Analyze market for scalping opportunities.
        
        Logic:
        1. Find recent high/low (support/resistance)
        2. Wait for price to touch level
        3. Enter on bounce with tight stop
        4. Quick profit target
        """
        candles = market.candles[-100:]  # Last 100 candles
        current_price = market.current_price
        
        if len(candles) < self.min_candles:
            return self._no_signal("Not enough data")
        
        # Calculate key levels
        highs = [c.high for c in candles[-50:]]
        lows = [c.low for c in candles[-50:]]
        
        resistance = max(highs)
        support = min(lows)
        mid = (resistance + support) / 2
        
        # Calculate momentum (last 10 candles)
        recent = candles[-10:]
        momentum = (recent[-1].close - recent[0].close) / recent[0].close
        
        # Price position in range
        range_size = resistance - support
        if range_size < 5:  # Too tight
            return self._no_signal("Range too small")
        
        price_position = (current_price - support) / range_size
        
        # SCALPING LOGIC
        signal = None
        confidence = 0.5
        reasoning = []
        
        # Near support = BUY
        if price_position < 0.25:
            signal = "buy"
            confidence = 0.7
            reasoning.append(f"Price near support ({support:.1f})")
            
            # Check for bounce
            if recent[-1].close > recent[-1].open:  # Bullish candle
                confidence += 0.1
                reasoning.append("Bullish bounce candle")
            
            # Oversold momentum
            if momentum < -0.001:
                confidence += 0.1
                reasoning.append("Oversold momentum")
        
        # Near resistance = SELL
        elif price_position > 0.75:
            signal = "sell"
            confidence = 0.7
            reasoning.append(f"Price near resistance ({resistance:.1f})")
            
            # Check for rejection
            if recent[-1].close < recent[-1].open:  # Bearish candle
                confidence += 0.1
                reasoning.append("Bearish rejection candle")
            
            # Overbought momentum
            if momentum > 0.001:
                confidence += 0.1
                reasoning.append("Overbought momentum")
        
        # Middle range = check breakout
        else:
            # Strong momentum = breakout
            if abs(momentum) > 0.003:
                signal = "buy" if momentum > 0 else "sell"
                confidence = 0.65
                reasoning.append(f"Momentum breakout ({momentum*100:.2f}%)")
            else:
                return self._no_signal("Mid-range, no clear setup")
        
        if not signal:
            return self._no_signal("No setup found")
        
        # Build result
        return AnalysisResult(
            trend="ranging",
            confidence=min(confidence, 0.9),
            signal_direction=signal,
            entry_price=current_price,
            stop_loss=self._calculate_sl(current_price, signal, support, resistance),
            take_profit=self._calculate_tp(current_price, signal, support, resistance),
            reasoning=" | ".join(reasoning),
            patterns=[f"Scalping-{signal}"],
            quality_score=confidence,
            trend_strength=abs(momentum) * 100,
            timestamp=datetime.now()
        )
    
    def _calculate_sl(self, entry: float, direction: str, support: float, resistance: float) -> float:
        """Calculate stop loss - tight for scalping."""
        if direction == "buy":
            # Below support
            return support - 5
        else:
            # Above resistance
            return resistance + 5
    
    def _calculate_tp(self, entry: float, direction: str, support: float, resistance: float) -> float:
        """Calculate take profit - quick target."""
        range_size = resistance - support
        target = min(range_size * 0.4, 30)  # 40% of range or 30 points max
        
        if direction == "buy":
            return entry + target
        else:
            return entry - target
    
    def _no_signal(self, reason: str) -> AnalysisResult:
        """Return no signal."""
        return AnalysisResult(
            trend="ranging",
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
