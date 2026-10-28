#!/usr/bin/env python3
"""Improved Professional Trading Brain v2.0 - Multi-Strategy.

Improvements:
1. Better S/R detection (multiple touches)
2. Volume confirmation
3. Dynamic stops based on volatility
4. Multiple strategies with regime detection
5. Adaptive risk management
"""
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import statistics


class MarketRegime(Enum):
    """Current market state."""
    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    BREAKOUT = "breakout"


@dataclass
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    
    @property
    def body(self) -> float:
        return abs(self.close - self.open)
    
    @property
    def range(self) -> float:
        return self.high - self.low
    
    @property
    def is_bullish(self) -> bool:
        return self.close > self.open


@dataclass
class SupportResistance:
    """S/R level with strength."""
    level: float
    touches: int
    strength: float  # 0-1
    is_support: bool


@dataclass
class TradeSignal:
    """Trade signal with all details."""
    action: str
    entry: float
    stop_loss: float
    take_profit: float
    size: float
    confidence: float
    strategy: str
    regime: MarketRegime
    reasoning: List[str]


class ImprovedTrader:
    """Enhanced professional trader with multiple strategies."""
    
    def __init__(self):
        self.max_risk_per_trade = 0.015  # 1.5% (more conservative)
        self.min_confidence = 75  # Higher threshold
        self.min_rr = 2.5  # Better R:R required
        
    def analyze_and_decide(self, candles: List[Candle], balance: float) -> Optional[TradeSignal]:
        """Main analysis engine."""
        if len(candles) < 200:
            return None
        
        # 1. Detect regime
        regime = self._detect_regime(candles)
        
        # 2. Run appropriate strategy
        if regime == MarketRegime.RANGING:
            signal = self._range_strategy_improved(candles, balance)
        elif regime == MarketRegime.TRENDING:
            signal = self._trend_strategy(candles, balance)
        elif regime == MarketRegime.BREAKOUT:
            signal = self._breakout_strategy(candles, balance)
        else:
            return None
        
        if signal and signal.confidence >= self.min_confidence:
            return signal
        
        return None
    
    def _detect_regime(self, candles: List[Candle]) -> MarketRegime:
        """Smart regime detection."""
        recent = candles[-100:]
        
        # Calculate indicators
        ema20 = self._ema([c.close for c in recent], 20)
        ema50 = self._ema([c.close for c in recent], 50)
        atr = self._atr(recent[-20:], 14)
        
        # Volatility
        volatility = atr / recent[-1].close
        
        # Range analysis
        high = max(c.high for c in recent[-50:])
        low = min(c.low for c in recent[-50:])
        range_size = (high - low) / recent[-1].close
        
        # Price vs EMAs
        price = recent[-1].close
        
        # Decision
        if volatility > 0.02:  # 2%
            return MarketRegime.VOLATILE
        elif range_size < 0.015:  # 1.5% range
            # Check for breakout attempt
            recent_5 = recent[-5:]
            if any(c.high > high * 0.999 for c in recent_5) or any(c.low < low * 1.001 for c in recent_5):
                return MarketRegime.BREAKOUT
            return MarketRegime.RANGING
        elif abs(price - ema20) / price < 0.005 and abs(ema20 - ema50) / ema20 > 0.003:
            return MarketRegime.TRENDING
        else:
            return MarketRegime.RANGING
    
    def _range_strategy_improved(self, candles: List[Candle], balance: float) -> Optional[TradeSignal]:
        """IMPROVED range trading with proper S/R."""
        recent = candles[-200:]
        current = recent[-1]
        
        # Find REAL support and resistance (multiple touches)
        sr_levels = self._find_support_resistance(recent)
        
        if not sr_levels:
            return None
        
        # Sort by strength
        sr_levels.sort(key=lambda x: x.strength, reverse=True)
        
        # Current price analysis
        price = current.close
        atr = self._atr(recent[-20:], 14)
        
        # Find nearest S/R
        nearest_support = None
        nearest_resistance = None
        
        for level in sr_levels:
            if level.is_support and level.level < price:
                if nearest_support is None or level.level > nearest_support.level:
                    nearest_support = level
            elif not level.is_support and level.level > price:
                if nearest_resistance is None or level.level < nearest_resistance.level:
                    nearest_resistance = level
        
        if not nearest_support or not nearest_resistance:
            return None
        
        # Calculate distances
        dist_to_support = (price - nearest_support.level) / price
        dist_to_resistance = (nearest_resistance.level - price) / price
        
        reasons = []
        confidence = 50
        
        # BUY at support
        if dist_to_support < 0.003:  # Within 0.3%
            # Volume confirmation
            avg_volume = statistics.mean(c.volume for c in recent[-20:-1])
            if current.volume > avg_volume * 1.2:
                reasons.append(f"High volume bounce ({current.volume / avg_volume:.1f}x avg)")
                confidence += 15
            
            # Bullish candle
            if current.is_bullish and current.body > current.range * 0.6:
                reasons.append("Strong bullish candle")
                confidence += 15
            
            # Strong S/R
            if nearest_support.strength > 0.7:
                reasons.append(f"Strong support ({nearest_support.touches} touches)")
                confidence += 10
            
            # Previous rejection
            bounces_here = sum(1 for c in recent[-20:] if abs(c.low - nearest_support.level) / c.low < 0.005)
            if bounces_here >= 2:
                reasons.append(f"Previous bounces: {bounces_here}")
                confidence += 10
            
            if confidence >= self.min_confidence:
                # Calculate levels
                entry = price
                sl = nearest_support.level - atr * 0.8  # Below support
                tp = nearest_resistance.level - atr * 0.5  # Near resistance
                
                rr = abs(tp - entry) / abs(sl - entry)
                if rr < self.min_rr:
                    return None
                
                size = self._calculate_size(balance, entry, sl)
                
                return TradeSignal(
                    action='buy',
                    entry=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    size=size,
                    confidence=confidence,
                    strategy='range_bounce_improved',
                    regime=MarketRegime.RANGING,
                    reasoning=reasons
                )
        
        # SELL at resistance
        elif dist_to_resistance < 0.003:
            avg_volume = statistics.mean(c.volume for c in recent[-20:-1])
            if current.volume > avg_volume * 1.2:
                reasons.append(f"High volume rejection ({current.volume / avg_volume:.1f}x avg)")
                confidence += 15
            
            if not current.is_bullish and current.body > current.range * 0.6:
                reasons.append("Strong bearish candle")
                confidence += 15
            
            if nearest_resistance.strength > 0.7:
                reasons.append(f"Strong resistance ({nearest_resistance.touches} touches)")
                confidence += 10
            
            rejections_here = sum(1 for c in recent[-20:] if abs(c.high - nearest_resistance.level) / c.high < 0.005)
            if rejections_here >= 2:
                reasons.append(f"Previous rejections: {rejections_here}")
                confidence += 10
            
            if confidence >= self.min_confidence:
                entry = price
                sl = nearest_resistance.level + atr * 0.8
                tp = nearest_support.level + atr * 0.5
                
                rr = abs(tp - entry) / abs(sl - entry)
                if rr < self.min_rr:
                    return None
                
                size = self._calculate_size(balance, entry, sl)
                
                return TradeSignal(
                    action='sell',
                    entry=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    size=size,
                    confidence=confidence,
                    strategy='range_bounce_improved',
                    regime=MarketRegime.RANGING,
                    reasoning=reasons
                )
        
        return None
    
    def _trend_strategy(self, candles: List[Candle], balance: float) -> Optional[TradeSignal]:
        """Trend following with pullback entry."""
        recent = candles[-100:]
        current = recent[-1]
        
        # EMAs
        ema20 = self._ema([c.close for c in recent], 20)
        ema50 = self._ema([c.close for c in recent], 50)
        ema100 = self._ema([c.close for c in recent], 100)
        
        price = current.close
        atr = self._atr(recent[-20:], 14)
        
        reasons = []
        confidence = 50
        
        # Uptrend
        if price > ema20 > ema50 > ema100:
            # Pullback to EMA20
            if abs(price - ema20) / price < 0.005:
                reasons.append("Pullback to EMA20 in uptrend")
                confidence += 20
                
                # Bullish momentum
                if current.is_bullish:
                    reasons.append("Bullish reversal")
                    confidence += 15
                
                # EMA slope
                ema20_5ago = self._ema([c.close for c in candles[-105:-5]], 20)
                if (ema20 - ema20_5ago) / ema20_5ago > 0.002:
                    reasons.append("Strong EMA20 slope")
                    confidence += 15
                
                if confidence >= self.min_confidence:
                    entry = price
                    sl = ema50 - atr * 0.5
                    tp = entry + abs(entry - sl) * 3
                    
                    rr = abs(tp - entry) / abs(sl - entry)
                    if rr < self.min_rr:
                        return None
                    
                    size = self._calculate_size(balance, entry, sl)
                    
                    return TradeSignal(
                        action='buy',
                        entry=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        size=size,
                        confidence=confidence,
                        strategy='trend_pullback',
                        regime=MarketRegime.TRENDING,
                        reasoning=reasons
                    )
        
        # Downtrend
        elif price < ema20 < ema50 < ema100:
            if abs(price - ema20) / price < 0.005:
                reasons.append("Pullback to EMA20 in downtrend")
                confidence += 20
                
                if not current.is_bullish:
                    reasons.append("Bearish reversal")
                    confidence += 15
                
                ema20_5ago = self._ema([c.close for c in candles[-105:-5]], 20)
                if (ema20_5ago - ema20) / ema20_5ago > 0.002:
                    reasons.append("Strong EMA20 slope")
                    confidence += 15
                
                if confidence >= self.min_confidence:
                    entry = price
                    sl = ema50 + atr * 0.5
                    tp = entry - abs(sl - entry) * 3
                    
                    rr = abs(tp - entry) / abs(sl - entry)
                    if rr < self.min_rr:
                        return None
                    
                    size = self._calculate_size(balance, entry, sl)
                    
                    return TradeSignal(
                        action='sell',
                        entry=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        size=size,
                        confidence=confidence,
                        strategy='trend_pullback',
                        regime=MarketRegime.TRENDING,
                        reasoning=reasons
                    )
        
        return None
    
    def _breakout_strategy(self, candles: List[Candle], balance: float) -> Optional[TradeSignal]:
        """Breakout with retest."""
        recent = candles[-100:]
        consolidation = recent[-50:-2]
        current = recent[-1]
        
        # Consolidation range
        cons_high = max(c.high for c in consolidation)
        cons_low = min(c.low for c in consolidation)
        range_size = cons_high - cons_low
        
        price = current.close
        atr = self._atr(recent[-20:], 14)
        
        reasons = []
        confidence = 50
        
        # Bullish breakout + retest
        if price > cons_high * 1.001:  # Above
            reasons.append(f"Breakout above {cons_high:.1f}")
            confidence += 20
            
            # Volume
            avg_volume = statistics.mean(c.volume for c in consolidation)
            if current.volume > avg_volume * 1.5:
                reasons.append("High breakout volume")
                confidence += 20
            
            # Retest
            if abs(price - cons_high) / price < 0.005:
                reasons.append("Retest of breakout level")
                confidence += 15
            
            if confidence >= self.min_confidence:
                entry = price
                sl = cons_high - atr * 0.5
                tp = entry + range_size * 2
                
                rr = abs(tp - entry) / abs(sl - entry)
                if rr < self.min_rr:
                    return None
                
                size = self._calculate_size(balance, entry, sl)
                
                return TradeSignal(
                    action='buy',
                    entry=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    size=size,
                    confidence=confidence,
                    strategy='breakout_retest',
                    regime=MarketRegime.BREAKOUT,
                    reasoning=reasons
                )
        
        # Bearish breakout
        elif price < cons_low * 0.999:
            reasons.append(f"Breakout below {cons_low:.1f}")
            confidence += 20
            
            avg_volume = statistics.mean(c.volume for c in consolidation)
            if current.volume > avg_volume * 1.5:
                reasons.append("High breakout volume")
                confidence += 20
            
            if abs(price - cons_low) / price < 0.005:
                reasons.append("Retest of breakout level")
                confidence += 15
            
            if confidence >= self.min_confidence:
                entry = price
                sl = cons_low + atr * 0.5
                tp = entry - range_size * 2
                
                rr = abs(tp - entry) / abs(sl - entry)
                if rr < self.min_rr:
                    return None
                
                size = self._calculate_size(balance, entry, sl)
                
                return TradeSignal(
                    action='sell',
                    entry=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    size=size,
                    confidence=confidence,
                    strategy='breakout_retest',
                    regime=MarketRegime.BREAKOUT,
                    reasoning=reasons
                )
        
        return None
    
    def _find_support_resistance(self, candles: List[Candle]) -> List[SupportResistance]:
        """Find REAL S/R levels with multiple touches."""
        levels = []
        
        # Find swing highs and lows
        for i in range(5, len(candles) - 5):
            # Swing high
            if all(candles[i].high > candles[j].high for j in range(i-5, i)) and \
               all(candles[i].high > candles[j].high for j in range(i+1, i+6)):
                level = candles[i].high
                
                # Count touches
                touches = sum(1 for c in candles if abs(c.high - level) / level < 0.003)
                
                if touches >= 2:
                    strength = min(touches / 5, 1.0)
                    levels.append(SupportResistance(
                        level=level,
                        touches=touches,
                        strength=strength,
                        is_support=False
                    ))
            
            # Swing low
            if all(candles[i].low < candles[j].low for j in range(i-5, i)) and \
               all(candles[i].low < candles[j].low for j in range(i+1, i+6)):
                level = candles[i].low
                
                touches = sum(1 for c in candles if abs(c.low - level) / level < 0.003)
                
                if touches >= 2:
                    strength = min(touches / 5, 1.0)
                    levels.append(SupportResistance(
                        level=level,
                        touches=touches,
                        strength=strength,
                        is_support=True
                    ))
        
        # Merge close levels
        merged = []
        for level in levels:
            found = False
            for m in merged:
                if abs(level.level - m.level) / m.level < 0.005:
                    # Merge
                    m.touches += level.touches
                    m.strength = min(m.touches / 5, 1.0)
                    found = True
                    break
            if not found:
                merged.append(level)
        
        return merged
    
    def _calculate_size(self, balance: float, entry: float, sl: float) -> float:
        """Calculate position size."""
        risk_amount = balance * self.max_risk_per_trade
        sl_distance = abs(entry - sl)
        size = risk_amount / (sl_distance * 100)  # $100 per lot per point
        return max(0.01, min(size, 0.5))  # Cap at 0.5 lot
    
    # Helper functions
    def _ema(self, values: List[float], period: int) -> float:
        """EMA calculation."""
        if len(values) < period:
            return sum(values) / len(values)
        multiplier = 2 / (period + 1)
        ema = values[0]
        for val in values[1:]:
            ema = (val - ema) * multiplier + ema
        return ema
    
    def _atr(self, candles: List[Candle], period: int) -> float:
        """ATR calculation."""
        trs = []
        for i in range(1, len(candles)):
            tr = max(
                candles[i].high - candles[i].low,
                abs(candles[i].high - candles[i-1].close),
                abs(candles[i].low - candles[i-1].close)
            )
            trs.append(tr)
        return sum(trs[-period:]) / min(period, len(trs))
