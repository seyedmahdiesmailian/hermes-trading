#!/usr/bin/env python3
"""SMC/ICT Analysis Engine - V1 Proven Logic in V2 Architecture.

Institutional-grade technical analysis:
- Order Block detection (65% WR in premium zones)
- Fair Value Gap (FVG) detection
- Premium/Discount zones (Fibonacci)
- Liquidity sweep detection
- Market structure (BOS, CHoCH, range)
- POI quality grading

Based on V1 engines/smc.py that achieved 65-73% WR live.
"""
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from brain.domain.entities.market import Candle


@dataclass
class OrderBlock:
    """Order Block structure."""
    type: str  # "bullish" or "bearish"
    price_high: float
    price_low: float
    timestamp: datetime
    mitigated: bool = False
    strength: float = 0.0  # 0-1


@dataclass
class FairValueGap:
    """Fair Value Gap structure."""
    type: str  # "bullish" or "bearish"
    gap_high: float
    gap_low: float
    timestamp: datetime
    filled: bool = False


@dataclass
class SMCAnalysis:
    """Complete SMC analysis result."""
    bias: str  # "bullish", "bearish", "neutral"
    confidence: float  # 0-1
    premium_discount: str  # "premium", "discount", "equilibrium"
    fib_level: float  # 0-1 (0=low, 1=high)
    
    order_blocks: List[OrderBlock]
    fvgs: List[FairValueGap]
    
    liquidity_sweep: Optional[str]  # "bullish", "bearish", None
    market_structure: str  # "bos_bullish", "bos_bearish", "choch", "range"
    
    poi_quality: str  # "A", "B", "C"
    entry_zone: Optional[Tuple[float, float]]  # (low, high)
    invalidation: Optional[float]


class SMCAnalyzer:
    """SMC/ICT Technical Analysis Engine.
    
    V1-proven logic: 65% WR in premium zones, 52% in discount.
    """
    
    def __init__(self):
        self.lookback_ob = 20
        self.lookback_structure = 50
    
    def analyze(self, candles: List[Candle], timeframe: str = "M15") -> SMCAnalysis:
        """Perform complete SMC analysis.
        
        Args:
            candles: Price data
            timeframe: Current timeframe
            
        Returns:
            Complete SMC analysis
        """
        if len(candles) < self.lookback_structure:
            return self._neutral_analysis()
        
        # 1. Detect Order Blocks
        order_blocks = self._detect_order_blocks(candles)
        
        # 2. Detect Fair Value Gaps
        fvgs = self._detect_fvgs(candles)
        
        # 3. Calculate Premium/Discount zones
        premium_discount, fib_level = self._calculate_premium_discount(candles)
        
        # 4. Detect Market Structure
        market_structure = self._detect_market_structure(candles)
        
        # 5. Check for Liquidity Sweep
        liquidity_sweep = self._detect_liquidity_sweep(candles)
        
        # 6. Determine Bias
        bias, confidence = self._determine_bias(
            order_blocks, fvgs, market_structure, premium_discount, liquidity_sweep
        )
        
        # 7. Grade POI Quality
        poi_quality = self._grade_poi(bias, premium_discount, market_structure, confidence)
        
        # 8. Calculate Entry Zone
        entry_zone, invalidation = self._calculate_entry_zone(
            bias, order_blocks, fvgs, candles[-1].close
        )
        
        return SMCAnalysis(
            bias=bias,
            confidence=confidence,
            premium_discount=premium_discount,
            fib_level=fib_level,
            order_blocks=order_blocks,
            fvgs=fvgs,
            liquidity_sweep=liquidity_sweep,
            market_structure=market_structure,
            poi_quality=poi_quality,
            entry_zone=entry_zone,
            invalidation=invalidation
        )
    
    def _detect_order_blocks(self, candles: List[Candle]) -> List[OrderBlock]:
        """Detect unmitigated order blocks.
        
        Bullish OB = last bearish candle before strong bullish move
        Bearish OB = last bullish candle before strong bearish move
        """
        if len(candles) < 3:
            return []
        
        # Calculate average body for strength threshold
        recent = candles[-self.lookback_ob:]
        bodies = [abs(c.close - c.open) for c in recent]
        avg_body = sum(bodies) / len(bodies) if bodies else 0.0
        strong_threshold = avg_body * 1.5
        
        obs = []
        current_price = candles[-1].close
        
        for i in range(len(candles) - 2, max(0, len(candles) - self.lookback_ob), -1):
            prev = candles[i - 1]
            curr = candles[i]
            
            # Bullish OB: prev bearish, curr breaks above strongly
            if prev.close < prev.open:
                body_curr = abs(curr.close - curr.open)
                if curr.close > curr.open and body_curr > strong_threshold:
                    # Check if not yet mitigated (price hasn't come back down)
                    mitigated = current_price < prev.low
                    
                    obs.append(OrderBlock(
                        type="bullish",
                        price_high=prev.high,
                        price_low=prev.low,
                        timestamp=prev.time,
                        mitigated=mitigated,
                        strength=min(1.0, body_curr / strong_threshold)
                    ))
            
            # Bearish OB: prev bullish, curr breaks below strongly
            elif prev.close > prev.open:
                body_curr = abs(curr.close - curr.open)
                if curr.close < curr.open and body_curr > strong_threshold:
                    mitigated = current_price > prev.high
                    
                    obs.append(OrderBlock(
                        type="bearish",
                        price_high=prev.high,
                        price_low=prev.low,
                        timestamp=prev.time,
                        mitigated=mitigated,
                        strength=min(1.0, body_curr / strong_threshold)
                    ))
        
        # Return only unmitigated OBs, strongest first
        unmitigated = [ob for ob in obs if not ob.mitigated]
        return sorted(unmitigated, key=lambda x: x.strength, reverse=True)[:3]
    
    def _detect_fvgs(self, candles: List[Candle]) -> List[FairValueGap]:
        """Detect Fair Value Gaps.
        
        Bullish FVG: gap between candle[i-1].high and candle[i+1].low
        Bearish FVG: gap between candle[i-1].low and candle[i+1].high
        """
        if len(candles) < 3:
            return []
        
        fvgs = []
        current_price = candles[-1].close
        
        for i in range(2, min(len(candles), self.lookback_ob + 2)):
            prev = candles[-i-1]
            curr = candles[-i]
            next_c = candles[-i+1]
            
            # Bullish FVG
            if prev.high < next_c.low:
                gap_size = next_c.low - prev.high
                if gap_size > 0:
                    filled = current_price < next_c.low
                    
                    fvgs.append(FairValueGap(
                        type="bullish",
                        gap_high=next_c.low,
                        gap_low=prev.high,
                        timestamp=curr.time,
                        filled=filled
                    ))
            
            # Bearish FVG
            elif prev.low > next_c.high:
                gap_size = prev.low - next_c.high
                if gap_size > 0:
                    filled = current_price > next_c.high
                    
                    fvgs.append(FairValueGap(
                        type="bearish",
                        gap_high=prev.low,
                        gap_low=next_c.high,
                        timestamp=curr.time,
                        filled=filled
                    ))
        
        # Return unfilled FVGs
        return [fvg for fvg in fvgs if not fvg.filled]
    
    def _calculate_premium_discount(self, candles: List[Candle]) -> Tuple[str, float]:
        """Calculate Premium/Discount zones using Fibonacci.
        
        V1 proven: Premium zones have 65% WR vs 52% in Discount!
        
        Returns:
            (zone_name, fib_level)
        """
        recent = candles[-self.lookback_structure:]
        
        swing_high = max(c.high for c in recent)
        swing_low = min(c.low for c in recent)
        current_price = candles[-1].close
        
        if swing_high == swing_low:
            return "equilibrium", 0.5
        
        # Fibonacci level (0 = low, 1 = high)
        fib_level = (current_price - swing_low) / (swing_high - swing_low)
        
        # Premium: 0.618 - 1.0
        # Equilibrium: 0.382 - 0.618
        # Discount: 0.0 - 0.382
        if fib_level >= 0.618:
            zone = "premium"
        elif fib_level >= 0.382:
            zone = "equilibrium"
        else:
            zone = "discount"
        
        return zone, fib_level
    
    def _detect_market_structure(self, candles: List[Candle]) -> str:
        """Detect market structure phase.
        
        Returns:
            "bos_bullish", "bos_bearish", "choch", "range"
        """
        if len(candles) < 10:
            return "range"
        
        recent = candles[-30:]
        
        # Find swing highs and lows
        highs = [c.high for c in recent]
        lows = [c.low for c in recent]
        
        # Simple structure detection
        recent_high = max(highs[-10:])
        recent_low = min(lows[-10:])
        prev_high = max(highs[-20:-10])
        prev_low = min(lows[-20:-10])
        
        current_price = candles[-1].close
        
        # Break of Structure (BOS)
        if recent_high > prev_high and recent_low > prev_low:
            return "bos_bullish"
        elif recent_high < prev_high and recent_low < prev_low:
            return "bos_bearish"
        
        # Change of Character (CHoCH)
        range_size = recent_high - recent_low
        if range_size < (prev_high - prev_low) * 0.5:
            return "choch"
        
        return "range"
    
    def _detect_liquidity_sweep(self, candles: List[Candle]) -> Optional[str]:
        """Detect liquidity sweep (stop hunt).
        
        Returns:
            "bullish" = swept lows then reversed up
            "bearish" = swept highs then reversed down
            None = no sweep
        """
        if len(candles) < 5:
            return None
        
        recent = candles[-10:]
        current = candles[-1]
        
        # Look for recent swing low that was broken then reclaimed
        swing_low = min(c.low for c in recent[:-1])
        if current.low < swing_low and current.close > swing_low:
            return "bullish"
        
        # Look for recent swing high that was broken then reclaimed
        swing_high = max(c.high for c in recent[:-1])
        if current.high > swing_high and current.close < swing_high:
            return "bearish"
        
        return None
    
    def _determine_bias(self,
                       order_blocks: List[OrderBlock],
                       fvgs: List[FairValueGap],
                       market_structure: str,
                       premium_discount: str,
                       liquidity_sweep: Optional[str]) -> Tuple[str, float]:
        """Determine overall bias and confidence.
        
        Returns:
            (bias, confidence)
        """
        bullish_score = 0.0
        bearish_score = 0.0
        
        # Order Blocks (strongest signal)
        for ob in order_blocks[:2]:  # Top 2
            if ob.type == "bullish":
                bullish_score += 0.3 * ob.strength
            else:
                bearish_score += 0.3 * ob.strength
        
        # Market Structure
        if market_structure == "bos_bullish":
            bullish_score += 0.25
        elif market_structure == "bos_bearish":
            bearish_score += 0.25
        
        # FVGs
        bullish_fvgs = [f for f in fvgs if f.type == "bullish"]
        bearish_fvgs = [f for f in fvgs if f.type == "bearish"]
        
        if len(bullish_fvgs) > len(bearish_fvgs):
            bullish_score += 0.15
        elif len(bearish_fvgs) > len(bullish_fvgs):
            bearish_score += 0.15
        
        # Liquidity Sweep (high probability reversal)
        if liquidity_sweep == "bullish":
            bullish_score += 0.2
        elif liquidity_sweep == "bearish":
            bearish_score += 0.2
        
        # Premium/Discount bias (V1 proven!)
        # Premium zones favor shorts, Discount favors longs
        if premium_discount == "premium":
            bearish_score += 0.1
        elif premium_discount == "discount":
            bullish_score += 0.1
        
        # Determine bias
        if bullish_score > bearish_score and bullish_score > 0.4:
            return "bullish", min(1.0, bullish_score)
        elif bearish_score > 0.4:
            return "bearish", min(1.0, bearish_score)
        else:
            return "neutral", max(bullish_score, bearish_score)
    
    def _grade_poi(self, bias: str, premium_discount: str,
                   market_structure: str, confidence: float) -> str:
        """Grade Point of Interest quality (A/B/C).
        
        V1 system: Grade affects risk multiplier.
        """
        score = 0
        
        # Confidence
        if confidence >= 0.7:
            score += 2
        elif confidence >= 0.5:
            score += 1
        
        # Premium/Discount alignment
        if (bias == "bullish" and premium_discount == "discount") or \
           (bias == "bearish" and premium_discount == "premium"):
            score += 2
        
        # Clear structure
        if market_structure in ["bos_bullish", "bos_bearish"]:
            score += 1
        
        # Grade
        if score >= 4:
            return "A"
        elif score >= 2:
            return "B"
        else:
            return "C"
    
    def _calculate_entry_zone(self, bias: str, order_blocks: List[OrderBlock],
                            fvgs: List[FairValueGap], current_price: float) -> Tuple[Optional[Tuple[float, float]], Optional[float]]:
        """Calculate entry zone and invalidation level.
        
        Returns:
            (entry_zone, invalidation)
        """
        if bias == "neutral":
            return None, None
        
        # Use nearest relevant OB as entry zone
        relevant_obs = [ob for ob in order_blocks 
                       if ob.type == bias and not ob.mitigated]
        
        if relevant_obs:
            ob = relevant_obs[0]
            entry_zone = (ob.price_low, ob.price_high)
            
            # Invalidation: opposite side of OB
            if bias == "bullish":
                invalidation = ob.price_low * 0.998  # Slightly below
            else:
                invalidation = ob.price_high * 1.002  # Slightly above
            
            return entry_zone, invalidation
        
        # Fallback: use FVG
        relevant_fvgs = [f for f in fvgs if f.type == bias]
        if relevant_fvgs:
            fvg = relevant_fvgs[0]
            entry_zone = (fvg.gap_low, fvg.gap_high)
            invalidation = fvg.gap_low * 0.998 if bias == "bullish" else fvg.gap_high * 1.002
            return entry_zone, invalidation
        
        return None, None
    
    def _neutral_analysis(self) -> SMCAnalysis:
        """Return neutral analysis when insufficient data."""
        return SMCAnalysis(
            bias="neutral",
            confidence=0.0,
            premium_discount="equilibrium",
            fib_level=0.5,
            order_blocks=[],
            fvgs=[],
            liquidity_sweep=None,
            market_structure="range",
            poi_quality="C",
            entry_zone=None,
            invalidation=None
        )
