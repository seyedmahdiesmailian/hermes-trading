#!/usr/bin/env python3
"""Adaptive Trading System - Best of V1 + V2 + ML.

Philosophy:
- Don't fight the market
- Trade ONLY when conditions are perfect
- Adapt strategy to market regime
- Learn from mistakes
- Survive first, profit second
"""
import json
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import math


class MarketRegime(Enum):
    """Market states."""
    STRONG_UPTREND = "strong_uptrend"
    WEAK_UPTREND = "weak_uptrend"
    STRONG_DOWNTREND = "strong_downtrend"
    WEAK_DOWNTREND = "weak_downtrend"
    RANGING_CLEAN = "ranging_clean"  # Clear S/R
    RANGING_CHOPPY = "ranging_choppy"  # Messy
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


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
class PerformanceTracker:
    """Track strategy performance."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    by_regime: Dict[str, Dict] = field(default_factory=dict)
    recent_trades: List[Dict] = field(default_factory=list)  # Last 20
    
    def update(self, regime: MarketRegime, won: bool, pnl: float):
        self.total_trades += 1
        if won:
            self.wins += 1
        else:
            self.losses += 1
        self.total_pnl += pnl
        
        # By regime
        regime_key = regime.value
        if regime_key not in self.by_regime:
            self.by_regime[regime_key] = {'wins': 0, 'losses': 0, 'pnl': 0.0}
        
        if won:
            self.by_regime[regime_key]['wins'] += 1
        else:
            self.by_regime[regime_key]['losses'] += 1
        self.by_regime[regime_key]['pnl'] += pnl
        
        # Recent
        self.recent_trades.append({'regime': regime_key, 'won': won, 'pnl': pnl})
        if len(self.recent_trades) > 20:
            self.recent_trades.pop(0)
    
    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades > 0 else 0.0
    
    def should_trade_regime(self, regime: MarketRegime) -> bool:
        """Should we trade in this regime based on past performance?"""
        regime_key = regime.value
        
        if regime_key not in self.by_regime:
            return True  # Unknown regime, try it
        
        stats = self.by_regime[regime_key]
        total = stats['wins'] + stats['losses']
        
        if total < 5:
            return True  # Not enough data
        
        win_rate = stats['wins'] / total
        
        # Block if consistently losing
        if total >= 10 and win_rate < 0.35:
            return False
        
        return True


@dataclass
class TradeSignal:
    action: str
    entry: float
    stop_loss: float
    take_profit: float
    size: float
    confidence: float
    regime: MarketRegime
    strategy: str
    reasoning: List[str]
    quality_score: float  # 0-100


class AdaptiveTrader:
    """Adaptive trading system."""
    
    def __init__(self):
        self.performance = PerformanceTracker()
        self.max_risk_base = 0.015  # 1.5% base
        self.min_confidence = 75
        self.min_quality = 70
        
        # Adaptive parameters
        self.current_risk_mult = 1.0  # Adjust based on performance
        self.blocked_regimes = set()
    
    def analyze_and_decide(self, candles: List[Candle], balance: float) -> Optional[TradeSignal]:
        """Main decision engine - adaptive."""
        if len(candles) < 200:
            return None
        
        # 1. Detect market regime with HIGH ACCURACY
        regime = self._detect_regime_advanced(candles)
        
        # 2. Check if we should trade this regime
        if not self.performance.should_trade_regime(regime):
            return None
        
        # 3. Adjust risk based on recent performance
        self._adjust_risk_multiplier()
        
        # 4. Run strategy for this regime
        signal = None
        
        if regime == MarketRegime.STRONG_UPTREND:
            signal = self._trend_continuation_long(candles, balance, regime)
        elif regime == MarketRegime.STRONG_DOWNTREND:
            signal = self._trend_continuation_short(candles, balance, regime)
        elif regime in [MarketRegime.WEAK_UPTREND, MarketRegime.WEAK_DOWNTREND]:
            signal = self._pullback_strategy(candles, balance, regime)
        elif regime == MarketRegime.RANGING_CLEAN:
            signal = self._range_strategy_v1_style(candles, balance, regime)
        else:
            # CHOPPY or UNKNOWN = DON'T TRADE
            return None
        
        # 5. Final quality check
        if signal and signal.quality_score >= self.min_quality and signal.confidence >= self.min_confidence:
            return signal
        
        return None
    
    def _detect_regime_advanced(self, candles: List[Candle]) -> MarketRegime:
        """Advanced regime detection - inspired by V1."""
        recent = candles[-100:]
        current = recent[-1]
        
        # Multiple timeframe EMAs
        ema10 = self._ema([c.close for c in recent], 10)
        ema20 = self._ema([c.close for c in recent], 20)
        ema50 = self._ema([c.close for c in recent], 50)
        ema100 = self._ema([c.close for c in recent], 100)
        ema200 = self._ema([c.close for c in candles], 200)
        
        price = current.close
        
        # ATR for volatility
        atr = self._atr(recent[-20:], 14)
        volatility = atr / price
        
        # Trend strength
        ema_alignment_up = price > ema10 > ema20 > ema50 > ema100
        ema_alignment_down = price < ema10 < ema20 < ema50 < ema100
        
        # EMA slopes
        ema20_slope = self._calculate_slope([c.close for c in candles[-25:-5]], 20)
        ema50_slope = self._calculate_slope([c.close for c in candles[-55:-5]], 50)
        
        # Range analysis
        high_50 = max(c.high for c in recent[-50:])
        low_50 = min(c.low for c in recent[-50:])
        range_50 = (high_50 - low_50) / price
        
        # ADX-like trend strength
        adx = self._calculate_adx(recent[-30:], 14)
        
        # Decision tree
        if volatility > 0.025:  # 2.5%
            return MarketRegime.VOLATILE
        
        # Strong trends
        if ema_alignment_up and adx > 25 and ema20_slope > 0.0015:
            return MarketRegime.STRONG_UPTREND
        
        if ema_alignment_down and adx > 25 and ema20_slope < -0.0015:
            return MarketRegime.STRONG_DOWNTREND
        
        # Weak trends
        if price > ema20 > ema50 and adx > 15:
            return MarketRegime.WEAK_UPTREND
        
        if price < ema20 < ema50 and adx > 15:
            return MarketRegime.WEAK_DOWNTREND
        
        # Ranging
        if range_50 < 0.02 and adx < 15:  # 2% range, low ADX
            # Check if clean or choppy
            sr_levels = self._find_key_levels(recent)
            if len(sr_levels) >= 2:  # Clear S/R
                return MarketRegime.RANGING_CLEAN
            else:
                return MarketRegime.RANGING_CHOPPY
        
        return MarketRegime.UNKNOWN
    
    def _trend_continuation_long(self, candles: List[Candle], balance: float, regime: MarketRegime) -> Optional[TradeSignal]:
        """Ride strong uptrend."""
        recent = candles[-50:]
        current = recent[-1]
        
        ema20 = self._ema([c.close for c in recent], 20)
        ema50 = self._ema([c.close for c in recent], 50)
        atr = self._atr(recent[-20:], 14)
        
        reasons = []
        quality = 50
        confidence = 50
        
        # Entry: pullback to EMA20 or breakout continuation
        price = current.close
        
        # Pullback to EMA20
        dist_to_ema20 = abs(price - ema20) / price
        if dist_to_ema20 < 0.004:  # Within 0.4%
            reasons.append(f"Pullback to EMA20 ({ema20:.1f})")
            quality += 20
            confidence += 15
            
            # Bullish reversal candle
            if current.is_bullish and current.body > current.range * 0.5:
                reasons.append("Bullish reversal candle")
                quality += 15
                confidence += 10
            
            # Volume
            avg_vol = statistics.mean(c.volume for c in recent[-20:-1])
            if current.volume > avg_vol * 1.1:
                reasons.append("Volume confirmation")
                quality += 10
                confidence += 10
            
            # EMA20 > EMA50 with good distance
            if (ema20 - ema50) / ema50 > 0.003:
                reasons.append("Strong EMA separation")
                quality += 10
                confidence += 10
            
            if quality >= 70:
                entry = price
                sl = ema50 - atr * 0.5
                tp = entry + abs(entry - sl) * 3.0  # 3:1 R:R
                
                size = self._calculate_adaptive_size(balance, entry, sl)
                
                return TradeSignal(
                    action='buy',
                    entry=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    size=size,
                    confidence=confidence,
                    regime=regime,
                    strategy='trend_continuation_long',
                    reasoning=reasons,
                    quality_score=quality
                )
        
        return None
    
    def _trend_continuation_short(self, candles: List[Candle], balance: float, regime: MarketRegime) -> Optional[TradeSignal]:
        """Ride strong downtrend."""
        recent = candles[-50:]
        current = recent[-1]
        
        ema20 = self._ema([c.close for c in recent], 20)
        ema50 = self._ema([c.close for c in recent], 50)
        atr = self._atr(recent[-20:], 14)
        
        reasons = []
        quality = 50
        confidence = 50
        
        price = current.close
        dist_to_ema20 = abs(price - ema20) / price
        
        if dist_to_ema20 < 0.004:
            reasons.append(f"Pullback to EMA20 ({ema20:.1f})")
            quality += 20
            confidence += 15
            
            if not current.is_bullish and current.body > current.range * 0.5:
                reasons.append("Bearish reversal candle")
                quality += 15
                confidence += 10
            
            avg_vol = statistics.mean(c.volume for c in recent[-20:-1])
            if current.volume > avg_vol * 1.1:
                reasons.append("Volume confirmation")
                quality += 10
                confidence += 10
            
            if (ema50 - ema20) / ema50 > 0.003:
                reasons.append("Strong EMA separation")
                quality += 10
                confidence += 10
            
            if quality >= 70:
                entry = price
                sl = ema50 + atr * 0.5
                tp = entry - abs(sl - entry) * 3.0
                
                size = self._calculate_adaptive_size(balance, entry, sl)
                
                return TradeSignal(
                    action='sell',
                    entry=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    size=size,
                    confidence=confidence,
                    regime=regime,
                    strategy='trend_continuation_short',
                    reasoning=reasons,
                    quality_score=quality
                )
        
        return None
    
    def _pullback_strategy(self, candles: List[Candle], balance: float, regime: MarketRegime) -> Optional[TradeSignal]:
        """Trade pullbacks in weak trends - MORE CONSERVATIVE."""
        # Similar to trend continuation but stricter requirements
        if 'UP' in regime.value:
            signal = self._trend_continuation_long(candles, balance, regime)
            if signal:
                signal.quality_score -= 10  # Lower quality in weak trend
                signal.confidence -= 5
            return signal
        else:
            signal = self._trend_continuation_short(candles, balance, regime)
            if signal:
                signal.quality_score -= 10
                signal.confidence -= 5
            return signal
    
    def _range_strategy_v1_style(self, candles: List[Candle], balance: float, regime: MarketRegime) -> Optional[TradeSignal]:
        """Range trading - V1 inspired with V2 improvements."""
        recent = candles[-200:]
        current = recent[-1]
        
        # Find REAL S/R with multiple touches
        sr_levels = self._find_key_levels(recent)
        
        if len(sr_levels) < 2:
            return None
        
        # Sort by strength
        sr_levels.sort(key=lambda x: x['touches'], reverse=True)
        
        price = current.close
        atr = self._atr(recent[-20:], 14)
        
        # Find nearest support/resistance
        support = None
        resistance = None
        
        for level in sr_levels:
            if level['type'] == 'support' and level['price'] < price:
                if support is None or level['price'] > support['price']:
                    support = level
            elif level['type'] == 'resistance' and level['price'] > price:
                if resistance is None or level['price'] < resistance['price']:
                    resistance = level
        
        if not support or not resistance:
            return None
        
        reasons = []
        quality = 50
        confidence = 50
        
        # BUY at support
        dist_to_support = (price - support['price']) / price
        if dist_to_support < 0.003 and support['touches'] >= 3:
            reasons.append(f"At strong support ({support['price']:.1f}, {support['touches']} touches)")
            quality += 25
            confidence += 20
            
            # Bullish bounce
            if current.is_bullish and current.low <= support['price'] * 1.002:
                reasons.append("Bullish bounce confirmed")
                quality += 20
                confidence += 15
            
            # Volume spike
            avg_vol = statistics.mean(c.volume for c in recent[-20:-1])
            if current.volume > avg_vol * 1.3:
                reasons.append(f"High volume ({current.volume / avg_vol:.1f}x)")
                quality += 15
                confidence += 10
            
            if quality >= 70:
                entry = price
                sl = support['price'] - atr * 0.8
                tp = resistance['price'] - atr * 0.5
                
                # Check R:R
                rr = abs(tp - entry) / abs(sl - entry)
                if rr < 2.0:
                    return None
                
                size = self._calculate_adaptive_size(balance, entry, sl)
                
                return TradeSignal(
                    action='buy',
                    entry=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    size=size,
                    confidence=confidence,
                    regime=regime,
                    strategy='range_bounce',
                    reasoning=reasons,
                    quality_score=quality
                )
        
        # SELL at resistance
        dist_to_resistance = (resistance['price'] - price) / price
        if dist_to_resistance < 0.003 and resistance['touches'] >= 3:
            reasons.append(f"At strong resistance ({resistance['price']:.1f}, {resistance['touches']} touches)")
            quality += 25
            confidence += 20
            
            if not current.is_bullish and current.high >= resistance['price'] * 0.998:
                reasons.append("Bearish rejection confirmed")
                quality += 20
                confidence += 15
            
            avg_vol = statistics.mean(c.volume for c in recent[-20:-1])
            if current.volume > avg_vol * 1.3:
                reasons.append(f"High volume ({current.volume / avg_vol:.1f}x)")
                quality += 15
                confidence += 10
            
            if quality >= 70:
                entry = price
                sl = resistance['price'] + atr * 0.8
                tp = support['price'] + atr * 0.5
                
                rr = abs(tp - entry) / abs(sl - entry)
                if rr < 2.0:
                    return None
                
                size = self._calculate_adaptive_size(balance, entry, sl)
                
                return TradeSignal(
                    action='sell',
                    entry=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    size=size,
                    confidence=confidence,
                    regime=regime,
                    strategy='range_bounce',
                    reasoning=reasons,
                    quality_score=quality
                )
        
        return None
    
    def _find_key_levels(self, candles: List[Candle]) -> List[Dict]:
        """Find key S/R levels with multiple touches."""
        levels = []
        
        # Scan for swing points
        for i in range(10, len(candles) - 10):
            # Swing high
            if all(candles[i].high >= c.high for c in candles[i-10:i]) and \
               all(candles[i].high >= c.high for c in candles[i+1:i+11]):
                level_price = candles[i].high
                
                # Count touches
                touches = sum(1 for c in candles 
                            if abs(c.high - level_price) / level_price < 0.003)
                
                if touches >= 2:
                    levels.append({
                        'type': 'resistance',
                        'price': level_price,
                        'touches': touches
                    })
            
            # Swing low
            if all(candles[i].low <= c.low for c in candles[i-10:i]) and \
               all(candles[i].low <= c.low for c in candles[i+1:i+11]):
                level_price = candles[i].low
                
                touches = sum(1 for c in candles 
                            if abs(c.low - level_price) / level_price < 0.003)
                
                if touches >= 2:
                    levels.append({
                        'type': 'support',
                        'price': level_price,
                        'touches': touches
                    })
        
        # Merge close levels
        merged = []
        for level in levels:
            found = False
            for m in merged:
                if abs(level['price'] - m['price']) / m['price'] < 0.005:
                    m['touches'] = max(m['touches'], level['touches'])
                    found = True
                    break
            if not found:
                merged.append(level)
        
        return merged
    
    def _adjust_risk_multiplier(self):
        """Adjust risk based on recent performance."""
        if len(self.performance.recent_trades) < 10:
            self.current_risk_mult = 1.0
            return
        
        recent_10 = self.performance.recent_trades[-10:]
        wins = sum(1 for t in recent_10 if t['won'])
        win_rate = wins / 10
        
        # Reduce risk if losing
        if win_rate < 0.3:
            self.current_risk_mult = 0.5
        elif win_rate < 0.4:
            self.current_risk_mult = 0.75
        elif win_rate > 0.6:
            self.current_risk_mult = 1.25
        else:
            self.current_risk_mult = 1.0
    
    def _calculate_adaptive_size(self, balance: float, entry: float, sl: float) -> float:
        """Position sizing with adaptive risk."""
        risk_pct = self.max_risk_base * self.current_risk_mult
        risk_amount = balance * risk_pct
        sl_distance = abs(entry - sl)
        size = risk_amount / (sl_distance * 100)
        return max(0.01, min(size, 0.5))
    
    # Technical indicators
    def _ema(self, values: List[float], period: int) -> float:
        if len(values) < period:
            return sum(values) / len(values)
        multiplier = 2 / (period + 1)
        ema = values[0]
        for val in values[1:]:
            ema = (val - ema) * multiplier + ema
        return ema
    
    def _atr(self, candles: List[Candle], period: int) -> float:
        trs = []
        for i in range(1, len(candles)):
            tr = max(
                candles[i].high - candles[i].low,
                abs(candles[i].high - candles[i-1].close),
                abs(candles[i].low - candles[i-1].close)
            )
            trs.append(tr)
        return sum(trs[-period:]) / min(period, len(trs))
    
    def _calculate_slope(self, values: List[float], period: int) -> float:
        """Linear regression slope."""
        if len(values) < period:
            return 0.0
        
        recent = values[-period:]
        x = list(range(len(recent)))
        y = recent
        n = len(x)
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(x[i] * y[i] for i in range(n))
        sum_x2 = sum(xi ** 2 for xi in x)
        
        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x ** 2)
        return slope / (sum_y / n)  # Normalized
    
    def _calculate_adx(self, candles: List[Candle], period: int) -> float:
        """ADX calculation (simplified)."""
        if len(candles) < period + 1:
            return 0.0
        
        plus_dm = []
        minus_dm = []
        tr_list = []
        
        for i in range(1, len(candles)):
            high_diff = candles[i].high - candles[i-1].high
            low_diff = candles[i-1].low - candles[i].low
            
            plus_dm.append(high_diff if high_diff > low_diff and high_diff > 0 else 0)
            minus_dm.append(low_diff if low_diff > high_diff and low_diff > 0 else 0)
            
            tr = max(
                candles[i].high - candles[i].low,
                abs(candles[i].high - candles[i-1].close),
                abs(candles[i].low - candles[i-1].close)
            )
            tr_list.append(tr)
        
        # Smooth
        plus_di = sum(plus_dm[-period:]) / sum(tr_list[-period:]) * 100
        minus_di = sum(minus_dm[-period:]) / sum(tr_list[-period:]) * 100
        
        dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
        
        return dx  # Simplified ADX
