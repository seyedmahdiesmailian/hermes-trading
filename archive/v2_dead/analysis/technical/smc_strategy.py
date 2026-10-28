"""SMC Analysis Strategy.

Smart Money Concepts / ICT analysis implementation.
"""

from typing import List, Dict, Any
from brain.domain.entities.market import MarketState, Candle
from brain.domain.services.market_analyzer import IAnalysisStrategy, AnalysisResult


class SMCStrategy(IAnalysisStrategy):
    """SMC/ICT analysis strategy.
    
    Analyzes:
    - Order Blocks (OB)
    - Fair Value Gaps (FVG)
    - Market Structure (BOS, CHoCH)
    - Liquidity zones
    - Premium/Discount
    
    Ported from V1 engines/smc.py with improvements.
    """
    
    def __init__(self, lookback: int = 50):
        self.lookback = lookback
    
    def analyze(self, market_state: MarketState) -> AnalysisResult:
        """Analyze market using SMC.
        
        Args:
            market_state: Current market snapshot
            
        Returns:
            AnalysisResult
        """
        candles = market_state.recent_candles(self.lookback)
        
        if len(candles) < 20:
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
        
        # 1. Detect trend
        trend, trend_strength = self._detect_trend(candles)
        
        # 2. Find order blocks
        order_blocks = self._detect_order_blocks(candles)
        
        # 3. Find FVGs
        fvgs = self._detect_fvgs(candles)
        
        # 4. Detect market structure
        structure = self._detect_structure(candles)
        
        # 5. Build key levels
        key_levels = self._build_key_levels(order_blocks, fvgs, market_state.current_price)
        
        # 6. Detect patterns
        patterns = []
        if order_blocks:
            patterns.append(f"{len(order_blocks)} order blocks")
        if fvgs:
            patterns.append(f"{len(fvgs)} FVGs")
        if structure:
            patterns.append(structure)
        
        # 7. Calculate quality
        quality_score = self._calculate_quality(
            trend_strength,
            len(order_blocks),
            len(fvgs),
            structure
        )
        
        # 8. Build reasoning
        reasoning = {
            "strategy": "SMC/ICT",
            "trend": trend,
            "trend_strength": trend_strength,
            "order_blocks": len(order_blocks),
            "fvgs": len(fvgs),
            "structure": structure,
            "quality_factors": {
                "trend_clarity": trend_strength,
                "ob_quality": min(len(order_blocks) / 3, 1.0),
                "structure_clarity": 1.0 if structure else 0.5
            }
        }
        
        return AnalysisResult(
            trend=trend,
            trend_strength=trend_strength,
            key_levels=key_levels,
            patterns=patterns,
            quality_score=quality_score,
            confidence=quality_score,  # Same for SMC
            reasoning=reasoning
        )
    
    def get_name(self) -> str:
        return "SMC"
    
    def _detect_trend(self, candles: List[Candle]) -> tuple[str, float]:
        """Detect trend using swing highs/lows.
        
        Returns:
            (trend, strength) where trend is "bullish"/"bearish"/"ranging"
        """
        if len(candles) < 10:
            return "ranging", 0.0
        
        # Simple: compare recent highs/lows
        recent = candles[-20:]
        highs = [c.high for c in recent]
        lows = [c.low for c in recent]
        
        # Higher highs and higher lows = bullish
        hh = highs[-1] > max(highs[-10:-1])
        hl = lows[-1] > max(lows[-10:-1])
        
        # Lower lows and lower highs = bearish
        ll = lows[-1] < min(lows[-10:-1])
        lh = highs[-1] < min(highs[-10:-1])
        
        if hh and hl:
            # Bullish
            strength = min((highs[-1] - min(lows)) / highs[-1], 0.9)
            return "bullish", strength
        elif ll and lh:
            # Bearish
            strength = min((max(highs) - lows[-1]) / max(highs), 0.9)
            return "bearish", strength
        else:
            # Ranging
            return "ranging", 0.3
    
    def _detect_order_blocks(self, candles: List[Candle]) -> List[Dict]:
        """Detect order blocks.
        
        OB = last opposite candle before strong move.
        """
        if len(candles) < 5:
            return []
        
        obs = []
        
        # Calculate average body
        bodies = [c.body for c in candles[-20:]]
        avg_body = sum(bodies) / len(bodies) if bodies else 0
        strong_threshold = avg_body * 1.5
        
        for i in range(len(candles) - 2, 2, -1):
            prev = candles[i - 1]
            curr = candles[i]
            
            # Bullish OB: prev bearish, curr breaks up strong
            if prev.is_bearish and curr.is_bullish and curr.body > strong_threshold:
                obs.append({
                    'type': 'bullish',
                    'price': prev.low,
                    'index': i - 1
                })
            
            # Bearish OB: prev bullish, curr breaks down strong
            elif prev.is_bullish and curr.is_bearish and curr.body > strong_threshold:
                obs.append({
                    'type': 'bearish',
                    'price': prev.high,
                    'index': i - 1
                })
            
            if len(obs) >= 5:  # Limit
                break
        
        return obs
    
    def _detect_fvgs(self, candles: List[Candle]) -> List[Dict]:
        """Detect Fair Value Gaps.
        
        FVG = gap between candle[i-1].low and candle[i+1].high (bullish)
        or candle[i-1].high and candle[i+1].low (bearish).
        """
        if len(candles) < 3:
            return []
        
        fvgs = []
        
        for i in range(1, len(candles) - 1):
            prev = candles[i - 1]
            curr = candles[i]
            next_c = candles[i + 1]
            
            # Bullish FVG
            if prev.high < next_c.low:
                gap = next_c.low - prev.high
                if gap > 0:
                    fvgs.append({
                        'type': 'bullish',
                        'top': next_c.low,
                        'bottom': prev.high,
                        'size': gap
                    })
            
            # Bearish FVG
            elif prev.low > next_c.high:
                gap = prev.low - next_c.high
                if gap > 0:
                    fvgs.append({
                        'type': 'bearish',
                        'top': prev.low,
                        'bottom': next_c.high,
                        'size': gap
                    })
            
            if len(fvgs) >= 5:  # Limit
                break
        
        return fvgs
    
    def _detect_structure(self, candles: List[Candle]) -> str:
        """Detect market structure.
        
        Returns:
            "BOS" (break of structure) or "CHoCH" (change of character) or ""
        """
        if len(candles) < 20:
            return ""
        
        # Simplified: check if recent break is significant
        recent_high = max(c.high for c in candles[-10:])
        prev_high = max(c.high for c in candles[-20:-10])
        
        recent_low = min(c.low for c in candles[-10:])
        prev_low = min(c.low for c in candles[-20:-10])
        
        if recent_high > prev_high * 1.01:  # 1% break
            return "BOS_bullish"
        elif recent_low < prev_low * 0.99:  # 1% break
            return "BOS_bearish"
        
        return ""
    
    def _build_key_levels(self, obs: List[Dict], fvgs: List[Dict], current_price: float) -> Dict:
        """Build key support/resistance levels."""
        supports = []
        resistances = []
        
        # OBs as levels
        for ob in obs:
            if ob['type'] == 'bullish':
                supports.append(ob['price'])
            else:
                resistances.append(ob['price'])
        
        # FVGs as levels
        for fvg in fvgs:
            if fvg['type'] == 'bullish':
                supports.append(fvg['bottom'])
            else:
                resistances.append(fvg['top'])
        
        # Filter by proximity to current price
        supports = [s for s in supports if s < current_price]
        resistances = [r for r in resistances if r > current_price]
        
        return {
            'support': sorted(set(supports), reverse=True)[:3],  # Top 3
            'resistance': sorted(set(resistances))[:3]  # Top 3
        }
    
    def _calculate_quality(self, trend_strength: float, ob_count: int, fvg_count: int, structure: str) -> float:
        """Calculate analysis quality score."""
        # Weighted factors
        score = 0.0
        
        # Trend clarity (40%)
        score += trend_strength * 0.4
        
        # Order blocks present (30%)
        score += min(ob_count / 3, 1.0) * 0.3
        
        # Structure clarity (20%)
        score += (1.0 if structure else 0.5) * 0.2
        
        # FVGs present (10%)
        score += min(fvg_count / 2, 1.0) * 0.1
        
        return min(score, 1.0)
