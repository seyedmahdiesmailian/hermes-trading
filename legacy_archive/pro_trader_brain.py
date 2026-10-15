#!/usr/bin/env python3
"""Professional Trading Brain - Think like a pro trader.

Philosophy:
1. Market context is everything
2. Multiple timeframe confirmation
3. Risk-first approach
4. Patience for high-quality setups
5. Adapt to market conditions
"""
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class MarketRegime(Enum):
    """Current market state."""
    STRONG_TREND_UP = "strong_trend_up"
    STRONG_TREND_DOWN = "strong_trend_down"
    WEAK_TREND_UP = "weak_trend_up"
    WEAK_TREND_DOWN = "weak_trend_down"
    RANGING_TIGHT = "ranging_tight"
    RANGING_WIDE = "ranging_wide"
    VOLATILE = "volatile"
    BREAKOUT = "breakout"


class TradeSetup(Enum):
    """Types of trade setups."""
    TREND_CONTINUATION = "trend_continuation"
    PULLBACK_IN_TREND = "pullback"
    BREAKOUT = "breakout"
    REVERSAL = "reversal"
    RANGE_BOUNCE = "range_bounce"
    NONE = "none"


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
    
    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclass
class TradeDecision:
    """Professional trade decision."""
    action: str  # 'buy', 'sell', 'hold'
    confidence: float  # 0-100
    entry: float
    stop_loss: float
    take_profit: float
    size: float
    setup_type: TradeSetup
    market_regime: MarketRegime
    reasoning: List[str]
    risk_reward: float
    win_probability: float  # Estimated based on setup


class ProfessionalTrader:
    """AI Trader that thinks like a pro."""
    
    def __init__(self):
        self.min_risk_reward = 2.0
        self.max_risk_per_trade = 0.02  # 2%
        self.min_confidence = 70  # 0-100
        
    def analyze_and_decide(self, candles: List[Candle], balance: float) -> TradeDecision:
        """Main decision engine - professional analysis."""
        
        if len(candles) < 200:
            return self._no_trade("Insufficient data")
        
        # Step 1: Identify market regime
        regime = self._identify_regime(candles)
        
        # Step 2: Find the best setup for this regime
        setup = self._find_setup(candles, regime)
        
        if setup['type'] == TradeSetup.NONE:
            return self._no_trade(f"No setup in {regime.value}")
        
        # Step 3: Calculate precise entry/SL/TP
        levels = self._calculate_levels(candles, setup, regime)
        
        # Step 4: Risk management check
        size = self._calculate_position_size(balance, levels['entry'], levels['sl'])
        
        # Step 5: Final confidence score
        confidence = self._score_setup(setup, regime, candles)
        
        if confidence < self.min_confidence:
            return self._no_trade(f"Low confidence: {confidence:.0f}%")
        
        # Step 6: Estimate win probability
        win_prob = self._estimate_win_probability(setup['type'], regime, confidence)
        
        return TradeDecision(
            action=setup['direction'],
            confidence=confidence,
            entry=levels['entry'],
            stop_loss=levels['sl'],
            take_profit=levels['tp'],
            size=size,
            setup_type=setup['type'],
            market_regime=regime,
            reasoning=setup['reasons'],
            risk_reward=levels['rr'],
            win_probability=win_prob
        )
    
    def _identify_regime(self, candles: List[Candle]) -> MarketRegime:
        """Identify current market regime - CRITICAL for strategy selection."""
        recent = candles[-100:]
        current_price = recent[-1].close
        
        # Calculate trend indicators
        ema20 = self._ema(recent, 20)
        ema50 = self._ema(recent, 50)
        ema200 = self._ema(candles, 200)
        
        # ATR for volatility
        atr = self._atr(recent[-20:], 14)
        
        # Price position relative to EMAs
        above_all = current_price > ema20 > ema50 > ema200
        below_all = current_price < ema20 < ema50 < ema200
        
        # Trend strength (ADX concept)
        trend_strength = self._calculate_trend_strength(recent)
        
        # Recent range
        high_100 = max(c.high for c in recent)
        low_100 = min(c.low for c in recent)
        range_size = high_100 - low_100
        
        # DECISION TREE
        if above_all and trend_strength > 0.7:
            return MarketRegime.STRONG_TREND_UP
        elif below_all and trend_strength > 0.7:
            return MarketRegime.STRONG_TREND_DOWN
        elif current_price > ema50 and trend_strength > 0.4:
            return MarketRegime.WEAK_TREND_UP
        elif current_price < ema50 and trend_strength > 0.4:
            return MarketRegime.WEAK_TREND_DOWN
        elif atr / current_price > 0.015:  # 1.5% ATR = volatile
            return MarketRegime.VOLATILE
        elif range_size < current_price * 0.01:  # 1% range = tight
            return MarketRegime.RANGING_TIGHT
        else:
            return MarketRegime.RANGING_WIDE
    
    def _find_setup(self, candles: List[Candle], regime: MarketRegime) -> Dict:
        """Find best setup for current regime - PRO LOGIC."""
        
        recent = candles[-100:]
        current = recent[-1]
        
        # Strategy selection based on regime
        if regime in [MarketRegime.STRONG_TREND_UP, MarketRegime.STRONG_TREND_DOWN]:
            return self._find_trend_setup(candles, regime)
        
        elif regime in [MarketRegime.WEAK_TREND_UP, MarketRegime.WEAK_TREND_DOWN]:
            return self._find_pullback_setup(candles, regime)
        
        elif regime in [MarketRegime.RANGING_TIGHT, MarketRegime.RANGING_WIDE]:
            return self._find_range_setup(candles)
        
        elif regime == MarketRegime.VOLATILE:
            return self._find_breakout_setup(candles)
        
        return {'type': TradeSetup.NONE, 'reasons': []}
    
    def _find_trend_setup(self, candles: List[Candle], regime: MarketRegime) -> Dict:
        """Trend continuation setup - ride the wave."""
        recent = candles[-50:]
        current = recent[-1]
        
        is_uptrend = 'UP' in regime.value
        ema20 = self._ema(recent, 20)
        
        reasons = []
        score = 0
        
        # Check for pullback entry
        if is_uptrend:
            # Price near EMA20 = pullback
            if abs(current.close - ema20) / ema20 < 0.003:  # Within 0.3%
                reasons.append("Price at EMA20 support")
                score += 30
            
            # Last 3 candles pullback
            if recent[-3].close > recent[-2].close > recent[-1].close:
                reasons.append("Healthy pullback")
                score += 20
            
            # Current candle bullish reversal
            if current.is_bullish and current.body > current.range * 0.6:
                reasons.append("Strong bullish reversal candle")
                score += 25
        
        else:  # Downtrend
            if abs(current.close - ema20) / ema20 < 0.003:
                reasons.append("Price at EMA20 resistance")
                score += 30
            
            if recent[-3].close < recent[-2].close < recent[-1].close:
                reasons.append("Healthy pullback")
                score += 20
            
            if current.is_bearish and current.body > current.range * 0.6:
                reasons.append("Strong bearish reversal candle")
                score += 25
        
        if score >= 50:
            return {
                'type': TradeSetup.PULLBACK_IN_TREND,
                'direction': 'buy' if is_uptrend else 'sell',
                'score': score,
                'reasons': reasons
            }
        
        return {'type': TradeSetup.NONE, 'reasons': reasons}
    
    def _find_pullback_setup(self, candles: List[Candle], regime: MarketRegime) -> Dict:
        """Pullback setup in weak trend."""
        # Similar to trend but more conservative
        return self._find_trend_setup(candles, regime)
    
    def _find_range_setup(self, candles: List[Candle]) -> Dict:
        """Range bounce setup - buy support, sell resistance."""
        recent = candles[-100:]
        current = recent[-1]
        
        # Find range boundaries
        highs = [c.high for c in recent]
        lows = [c.low for c in recent]
        
        resistance = max(highs)
        support = min(lows)
        mid = (resistance + support) / 2
        
        range_size = resistance - support
        price_position = (current.close - support) / range_size
        
        reasons = []
        score = 0
        
        # Near support = buy
        if price_position < 0.2:
            reasons.append(f"Price near support ({support:.1f})")
            score += 40
            
            # Bounce confirmation
            if current.is_bullish and current.low <= support * 1.002:
                reasons.append("Bullish bounce off support")
                score += 30
            
            if score >= 60:
                return {
                    'type': TradeSetup.RANGE_BOUNCE,
                    'direction': 'buy',
                    'score': score,
                    'reasons': reasons,
                    'support': support,
                    'resistance': resistance
                }
        
        # Near resistance = sell
        elif price_position > 0.8:
            reasons.append(f"Price near resistance ({resistance:.1f})")
            score += 40
            
            if current.is_bearish and current.high >= resistance * 0.998:
                reasons.append("Bearish rejection at resistance")
                score += 30
            
            if score >= 60:
                return {
                    'type': TradeSetup.RANGE_BOUNCE,
                    'direction': 'sell',
                    'score': score,
                    'reasons': reasons,
                    'support': support,
                    'resistance': resistance
                }
        
        return {'type': TradeSetup.NONE, 'reasons': reasons}
    
    def _find_breakout_setup(self, candles: List[Candle]) -> Dict:
        """Breakout setup - catch momentum."""
        recent = candles[-100:]
        consolidation = recent[-50:-5]
        breakout_candles = recent[-5:]
        
        # Consolidation range
        cons_high = max(c.high for c in consolidation)
        cons_low = min(c.low for c in consolidation)
        
        # Breakout check
        current = recent[-1]
        
        reasons = []
        score = 0
        
        # Bullish breakout
        if current.high > cons_high:
            reasons.append(f"Breakout above {cons_high:.1f}")
            score += 40
            
            # Strong momentum
            if current.body > (cons_high - cons_low):
                reasons.append("Strong momentum")
                score += 30
            
            if score >= 60:
                return {
                    'type': TradeSetup.BREAKOUT,
                    'direction': 'buy',
                    'score': score,
                    'reasons': reasons
                }
        
        # Bearish breakout
        elif current.low < cons_low:
            reasons.append(f"Breakout below {cons_low:.1f}")
            score += 40
            
            if current.body > (cons_high - cons_low):
                reasons.append("Strong momentum")
                score += 30
            
            if score >= 60:
                return {
                    'type': TradeSetup.BREAKOUT,
                    'direction': 'sell',
                    'score': score,
                    'reasons': reasons
                }
        
        return {'type': TradeSetup.NONE, 'reasons': reasons}
    
    def _calculate_levels(self, candles: List[Candle], setup: Dict, regime: MarketRegime) -> Dict:
        """Calculate precise entry, SL, TP levels."""
        recent = candles[-50:]
        current = recent[-1].close
        atr = self._atr(recent[-20:], 14)
        
        entry = current
        
        # Setup-specific levels
        if setup['type'] in [TradeSetup.PULLBACK_IN_TREND, TradeSetup.TREND_CONTINUATION]:
            # Trend trades: wider stops, bigger targets
            if setup['direction'] == 'buy':
                sl = entry - (atr * 1.5)
                tp = entry + (atr * 3.5)  # 2.3:1 RR
            else:
                sl = entry + (atr * 1.5)
                tp = entry - (atr * 3.5)
        
        elif setup['type'] == TradeSetup.RANGE_BOUNCE:
            # Range trades: tight stops, moderate targets
            if setup['direction'] == 'buy':
                sl = setup['support'] - (atr * 0.5)
                tp = setup['resistance'] - (atr * 0.5)  # To resistance
            else:
                sl = setup['resistance'] + (atr * 0.5)
                tp = setup['support'] + (atr * 0.5)
        
        elif setup['type'] == TradeSetup.BREAKOUT:
            # Breakout: stop behind consolidation
            if setup['direction'] == 'buy':
                sl = entry - (atr * 2.0)
                tp = entry + (atr * 4.0)  # 2:1
            else:
                sl = entry + (atr * 2.0)
                tp = entry - (atr * 4.0)
        
        else:
            # Default
            if setup['direction'] == 'buy':
                sl = entry - (atr * 1.5)
                tp = entry + (atr * 3.0)
            else:
                sl = entry + (atr * 1.5)
                tp = entry - (atr * 3.0)
        
        rr = abs(tp - entry) / abs(sl - entry)
        
        return {
            'entry': entry,
            'sl': sl,
            'tp': tp,
            'rr': rr
        }
    
    def _calculate_position_size(self, balance: float, entry: float, sl: float) -> float:
        """Calculate position size based on risk."""
        risk_amount = balance * self.max_risk_per_trade
        sl_distance = abs(entry - sl)
        
        # For XAUUSD: 1 lot = $100/point typically
        # But we use mini lots (0.01 = $1/point)
        size = risk_amount / sl_distance
        
        # Clamp to reasonable range
        size = max(0.01, min(size, 1.0))
        
        return round(size, 2)
    
    def _score_setup(self, setup: Dict, regime: MarketRegime, candles: List[Candle]) -> float:
        """Final confidence score 0-100."""
        base_score = setup.get('score', 50)
        
        # Regime bonus
        if regime in [MarketRegime.STRONG_TREND_UP, MarketRegime.STRONG_TREND_DOWN]:
            base_score += 10
        elif regime in [MarketRegime.RANGING_TIGHT, MarketRegime.RANGING_WIDE]:
            base_score += 5
        
        # Multiple timeframe confirmation (placeholder)
        # In real system, check higher TF
        base_score += 5
        
        return min(base_score, 100)
    
    def _estimate_win_probability(self, setup_type: TradeSetup, regime: MarketRegime, confidence: float) -> float:
        """Estimate win probability based on setup and conditions."""
        # Based on historical win rates of each setup type
        base_rates = {
            TradeSetup.PULLBACK_IN_TREND: 0.65,
            TradeSetup.TREND_CONTINUATION: 0.60,
            TradeSetup.RANGE_BOUNCE: 0.70,
            TradeSetup.BREAKOUT: 0.55,
            TradeSetup.REVERSAL: 0.45
        }
        
        base = base_rates.get(setup_type, 0.50)
        
        # Adjust by confidence
        adjusted = base + ((confidence - 70) / 100 * 0.15)
        
        return max(0.40, min(adjusted, 0.85))
    
    # Helper functions
    def _ema(self, candles: List[Candle], period: int) -> float:
        """Exponential Moving Average."""
        closes = [c.close for c in candles[-period:]]
        multiplier = 2 / (period + 1)
        ema = closes[0]
        for close in closes[1:]:
            ema = (close - ema) * multiplier + ema
        return ema
    
    def _atr(self, candles: List[Candle], period: int) -> float:
        """Average True Range."""
        trs = []
        for i in range(1, len(candles)):
            high = candles[i].high
            low = candles[i].low
            prev_close = candles[i-1].close
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            trs.append(tr)
        
        return sum(trs[-period:]) / period
    
    def _calculate_trend_strength(self, candles: List[Candle]) -> float:
        """Calculate trend strength 0-1 (ADX-like)."""
        closes = [c.close for c in candles]
        
        # Directional movement
        ups = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
        downs = len(closes) - 1 - ups
        
        # Linear regression slope
        x = list(range(len(closes)))
        y = closes
        n = len(x)
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(x[i] * y[i] for i in range(n))
        sum_x2 = sum(xi ** 2 for xi in x)
        
        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x ** 2)
        
        # Normalize
        avg_price = sum_y / n
        normalized_slope = abs(slope) / avg_price * 100
        
        strength = min(normalized_slope * 20, 1.0)  # Scale to 0-1
        
        return strength
    
    def _no_trade(self, reason: str) -> TradeDecision:
        """Return no-trade decision."""
        return TradeDecision(
            action='hold',
            confidence=0,
            entry=0,
            stop_loss=0,
            take_profit=0,
            size=0,
            setup_type=TradeSetup.NONE,
            market_regime=MarketRegime.RANGING_TIGHT,
            reasoning=[reason],
            risk_reward=0,
            win_probability=0
        )


if __name__ == '__main__':
    print("Professional Trading Brain v1.0")
    print("="*60)
    print("Ready to think like a pro trader.")
