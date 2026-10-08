"""Classic Technical Analysis Strategy.

Traditional indicators and patterns.
"""

from typing import List, Dict
from brain.domain.entities.market import MarketState, Candle
from brain.domain.services.market_analyzer import IAnalysisStrategy, AnalysisResult


class ClassicStrategy(IAnalysisStrategy):
    """Classic technical analysis strategy.
    
    Analyzes:
    - Moving averages (trend)
    - Support/Resistance
    - RSI (momentum)
    - Volume
    - Chart patterns
    """
    
    def __init__(self, ma_fast: int = 20, ma_slow: int = 50):
        self.ma_fast = ma_fast
        self.ma_slow = ma_slow
    
    def analyze(self, market_state: MarketState) -> AnalysisResult:
        """Analyze market using classic TA.
        
        Args:
            market_state: Current market snapshot
            
        Returns:
            AnalysisResult
        """
        candles = market_state.candles
        
        if len(candles) < self.ma_slow:
            # Not enough data
            return AnalysisResult(
                trend="ranging",
                trend_strength=0.0,
                key_levels={"support": [], "resistance": []},
                patterns=[],
                quality_score=0.3,
                confidence=0.3,
                reasoning={"error": "insufficient_data"}
            )
        
        # 1. Moving averages
        ma_fast = self._sma(candles, self.ma_fast)
        ma_slow = self._sma(candles, self.ma_slow)
        
        # 2. Trend from MAs
        trend, trend_strength = self._detect_trend_ma(ma_fast, ma_slow, market_state.current_price)
        
        # 3. Support/Resistance
        sr_levels = self._detect_support_resistance(candles, market_state.current_price)
        
        # 4. RSI (simplified)
        rsi = self._calculate_rsi(candles, period=14)
        
        # 5. Patterns
        patterns = self._detect_patterns(candles, ma_fast, ma_slow, rsi)
        
        # 6. Quality score
        quality_score = self._calculate_quality(trend_strength, rsi, len(sr_levels['support']) + len(sr_levels['resistance']))
        
        # 7. Reasoning
        reasoning = {
            "strategy": "Classic TA",
            "ma_fast": ma_fast,
            "ma_slow": ma_slow,
            "rsi": rsi,
            "price_vs_ma_fast": "above" if market_state.current_price > ma_fast else "below",
            "price_vs_ma_slow": "above" if market_state.current_price > ma_slow else "below",
            "ma_alignment": "bullish" if ma_fast > ma_slow else "bearish"
        }
        
        return AnalysisResult(
            trend=trend,
            trend_strength=trend_strength,
            key_levels=sr_levels,
            patterns=patterns,
            quality_score=quality_score,
            confidence=quality_score * 0.9,  # Slightly lower confidence
            reasoning=reasoning
        )
    
    def get_name(self) -> str:
        return "Classic"
    
    def _sma(self, candles: List[Candle], period: int) -> float:
        """Simple Moving Average."""
        if len(candles) < period:
            return candles[-1].close
        
        closes = [c.close for c in candles[-period:]]
        return sum(closes) / period
    
    def _detect_trend_ma(self, ma_fast: float, ma_slow: float, current_price: float) -> tuple[str, float]:
        """Detect trend from moving averages."""
        # MA alignment
        if ma_fast > ma_slow and current_price > ma_fast:
            # Strong bullish
            strength = min((ma_fast - ma_slow) / ma_slow, 0.9)
            return "bullish", strength
        elif ma_fast < ma_slow and current_price < ma_fast:
            # Strong bearish
            strength = min((ma_slow - ma_fast) / ma_slow, 0.9)
            return "bearish", strength
        elif ma_fast > ma_slow:
            # Weak bullish
            return "bullish", 0.5
        elif ma_fast < ma_slow:
            # Weak bearish
            return "bearish", 0.5
        else:
            # Ranging
            return "ranging", 0.3
    
    def _detect_support_resistance(self, candles: List[Candle], current_price: float) -> Dict:
        """Detect support and resistance levels.
        
        Simplified: recent swing highs/lows.
        """
        if len(candles) < 20:
            return {"support": [], "resistance": []}
        
        recent = candles[-50:]
        
        # Find swing highs (resistance)
        resistances = []
        for i in range(2, len(recent) - 2):
            if (recent[i].high > recent[i-1].high and 
                recent[i].high > recent[i-2].high and
                recent[i].high > recent[i+1].high and
                recent[i].high > recent[i+2].high):
                if recent[i].high > current_price:
                    resistances.append(recent[i].high)
        
        # Find swing lows (support)
        supports = []
        for i in range(2, len(recent) - 2):
            if (recent[i].low < recent[i-1].low and 
                recent[i].low < recent[i-2].low and
                recent[i].low < recent[i+1].low and
                recent[i].low < recent[i+2].low):
                if recent[i].low < current_price:
                    supports.append(recent[i].low)
        
        return {
            'support': sorted(set(supports), reverse=True)[:3],
            'resistance': sorted(set(resistances))[:3]
        }
    
    def _calculate_rsi(self, candles: List[Candle], period: int = 14) -> float:
        """Calculate RSI."""
        if len(candles) < period + 1:
            return 50.0  # Neutral
        
        # Calculate price changes
        changes = []
        for i in range(len(candles) - period, len(candles)):
            change = candles[i].close - candles[i-1].close
            changes.append(change)
        
        # Separate gains and losses
        gains = [c if c > 0 else 0 for c in changes]
        losses = [-c if c < 0 else 0 for c in changes]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _detect_patterns(self, candles: List[Candle], ma_fast: float, ma_slow: float, rsi: float) -> List[str]:
        """Detect classic patterns."""
        patterns = []
        
        current = candles[-1]
        
        # MA crossover
        if ma_fast > ma_slow:
            patterns.append("MA bullish alignment")
        elif ma_fast < ma_slow:
            patterns.append("MA bearish alignment")
        
        # RSI conditions
        if rsi > 70:
            patterns.append("RSI overbought")
        elif rsi < 30:
            patterns.append("RSI oversold")
        
        # Price vs MA
        if current.close > ma_fast > ma_slow:
            patterns.append("Strong uptrend")
        elif current.close < ma_fast < ma_slow:
            patterns.append("Strong downtrend")
        
        return patterns
    
    def _calculate_quality(self, trend_strength: float, rsi: float, level_count: int) -> float:
        """Calculate analysis quality."""
        score = 0.0
        
        # Trend strength (50%)
        score += trend_strength * 0.5
        
        # RSI clarity (30%) - extreme values = higher quality
        rsi_score = 0.0
        if rsi > 70 or rsi < 30:
            rsi_score = 1.0
        elif rsi > 60 or rsi < 40:
            rsi_score = 0.7
        else:
            rsi_score = 0.4
        score += rsi_score * 0.3
        
        # S/R levels (20%)
        score += min(level_count / 4, 1.0) * 0.2
        
        return min(score, 1.0)
