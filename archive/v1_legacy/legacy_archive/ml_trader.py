#!/usr/bin/env python3
"""Machine Learning Trader - Data-driven approach.

Features:
- Technical indicators as features
- Pattern recognition
- Win probability prediction
- Adaptive learning from results
"""
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import statistics
import math


@dataclass
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class Features:
    """ML features for prediction."""
    # Trend
    ema_20_50_diff: float
    ema_50_100_diff: float
    price_to_ema20: float
    
    # Momentum
    rsi: float
    macd: float
    macd_signal: float
    
    # Volatility
    atr_normalized: float
    bb_position: float  # Position in Bollinger Bands
    
    # Volume
    volume_ratio: float
    
    # Pattern
    candle_pattern_score: float
    
    # Market structure
    higher_highs: int
    lower_lows: int
    

@dataclass
class MLSignal:
    action: str
    entry: float
    stop_loss: float
    take_profit: float
    size: float
    win_probability: float
    expected_value: float
    features: Features


class MLTrader:
    """Machine Learning based trader."""
    
    def __init__(self):
        self.min_win_prob = 0.60
        self.min_expected_value = 0.5  # Minimum EV
        self.max_risk = 0.015
        
        # Simple learned weights (normally from training)
        self.feature_weights = {
            'ema_trend': 0.15,
            'rsi_extremes': 0.12,
            'macd_cross': 0.10,
            'volatility': 0.08,
            'volume': 0.10,
            'pattern': 0.15,
            'structure': 0.15,
            'bb_position': 0.15
        }
    
    def analyze_and_predict(self, candles: List[Candle], balance: float) -> Optional[MLSignal]:
        """ML-based prediction."""
        if len(candles) < 200:
            return None
        
        # Extract features
        features = self._extract_features(candles)
        
        # Predict win probability
        win_prob_long, win_prob_short = self._predict_win_probability(features, candles)
        
        # Calculate expected value
        current_price = candles[-1].close
        atr = self._atr(candles[-20:], 14)
        
        # Entry levels
        if win_prob_long > self.min_win_prob:
            entry = current_price
            sl = entry - atr * 1.2
            tp = entry + atr * 3.0
            
            risk = abs(sl - entry)
            reward = abs(tp - entry)
            
            ev = (win_prob_long * reward) - ((1 - win_prob_long) * risk)
            
            if ev > self.min_expected_value:
                size = self._calculate_size(balance, entry, sl)
                
                return MLSignal(
                    action='buy',
                    entry=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    size=size,
                    win_probability=win_prob_long,
                    expected_value=ev,
                    features=features
                )
        
        elif win_prob_short > self.min_win_prob:
            entry = current_price
            sl = entry + atr * 1.2
            tp = entry - atr * 3.0
            
            risk = abs(sl - entry)
            reward = abs(tp - entry)
            
            ev = (win_prob_short * reward) - ((1 - win_prob_short) * risk)
            
            if ev > self.min_expected_value:
                size = self._calculate_size(balance, entry, sl)
                
                return MLSignal(
                    action='sell',
                    entry=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    size=size,
                    win_probability=win_prob_short,
                    expected_value=ev,
                    features=features
                )
        
        return None
    
    def _extract_features(self, candles: List[Candle]) -> Features:
        """Extract ML features from candles."""
        recent = candles[-100:]
        current = recent[-1]
        
        closes = [c.close for c in recent]
        
        # EMAs
        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, 50)
        ema100 = self._ema(closes, 100)
        
        # RSI
        rsi = self._rsi(closes, 14)
        
        # MACD
        macd, signal = self._macd(closes)
        
        # ATR
        atr = self._atr(recent[-20:], 14)
        atr_normalized = atr / current.close
        
        # Bollinger Bands
        bb_upper, bb_lower = self._bollinger_bands(closes, 20, 2)
        bb_position = (current.close - bb_lower) / (bb_upper - bb_lower)
        
        # Volume
        avg_volume = statistics.mean(c.volume for c in recent[-20:-1])
        volume_ratio = current.volume / avg_volume
        
        # Candle pattern
        pattern_score = self._candle_pattern_score(current)
        
        # Market structure
        higher_highs = sum(1 for i in range(len(recent)-10, len(recent)) 
                          if recent[i].high > max(c.high for c in recent[i-10:i]))
        lower_lows = sum(1 for i in range(len(recent)-10, len(recent)) 
                        if recent[i].low < min(c.low for c in recent[i-10:i]))
        
        return Features(
            ema_20_50_diff=(ema20 - ema50) / ema50,
            ema_50_100_diff=(ema50 - ema100) / ema100,
            price_to_ema20=(current.close - ema20) / ema20,
            rsi=rsi,
            macd=macd,
            macd_signal=signal,
            atr_normalized=atr_normalized,
            bb_position=bb_position,
            volume_ratio=volume_ratio,
            candle_pattern_score=pattern_score,
            higher_highs=higher_highs,
            lower_lows=lower_lows
        )
    
    def _predict_win_probability(self, features: Features, candles: List[Candle]) -> Tuple[float, float]:
        """Predict win probability for long and short."""
        # Simple weighted model (in real ML, this would be trained)
        
        long_score = 0.5  # Start neutral
        short_score = 0.5
        
        # Trend following
        if features.ema_20_50_diff > 0.005:
            long_score += 0.15
        elif features.ema_20_50_diff < -0.005:
            short_score += 0.15
        
        # RSI extremes (mean reversion)
        if features.rsi < 30:
            long_score += 0.12
        elif features.rsi > 70:
            short_score += 0.12
        
        # MACD crossover
        if features.macd > features.macd_signal:
            long_score += 0.10
        else:
            short_score += 0.10
        
        # Bollinger Bands
        if features.bb_position < 0.2:
            long_score += 0.15
        elif features.bb_position > 0.8:
            short_score += 0.15
        
        # Volume confirmation
        if features.volume_ratio > 1.3:
            # High volume supports the move
            if features.ema_20_50_diff > 0:
                long_score += 0.10
            else:
                short_score += 0.10
        
        # Candle pattern
        if features.candle_pattern_score > 0.7:
            long_score += 0.10
        elif features.candle_pattern_score < 0.3:
            short_score += 0.10
        
        # Market structure
        if features.higher_highs >= 3:
            long_score += 0.10
        elif features.lower_lows >= 3:
            short_score += 0.10
        
        # Normalize to 0-1
        long_prob = max(0.0, min(1.0, long_score))
        short_prob = max(0.0, min(1.0, short_score))
        
        return long_prob, short_prob
    
    def _calculate_size(self, balance: float, entry: float, sl: float) -> float:
        risk_amount = balance * self.max_risk
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
    
    def _rsi(self, closes: List[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        
        gains = []
        losses = []
        
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _macd(self, closes: List[float]) -> Tuple[float, float]:
        ema12 = self._ema(closes, 12)
        ema26 = self._ema(closes, 26)
        macd = ema12 - ema26
        
        # Signal line (9-period EMA of MACD)
        # Simplified
        signal = macd * 0.9
        
        return macd, signal
    
    def _bollinger_bands(self, closes: List[float], period: int, std_dev: float) -> Tuple[float, float]:
        if len(closes) < period:
            avg = sum(closes) / len(closes)
            return avg, avg
        
        recent = closes[-period:]
        sma = sum(recent) / period
        variance = sum((x - sma) ** 2 for x in recent) / period
        std = math.sqrt(variance)
        
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        
        return upper, lower
    
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
    
    def _candle_pattern_score(self, candle: Candle) -> float:
        """Score candle pattern 0-1."""
        body = abs(candle.close - candle.open)
        range_size = candle.high - candle.low
        
        if range_size == 0:
            return 0.5
        
        body_ratio = body / range_size
        
        # Bullish patterns
        if candle.close > candle.open:
            # Strong bullish candle
            if body_ratio > 0.7:
                return 0.9
            elif body_ratio > 0.5:
                return 0.7
            else:
                return 0.6
        else:
            # Bearish patterns
            if body_ratio > 0.7:
                return 0.1
            elif body_ratio > 0.5:
                return 0.3
            else:
                return 0.4
