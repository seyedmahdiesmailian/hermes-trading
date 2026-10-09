#!/usr/bin/env python3
"""ML Trader with actual training capability.

Features:
- Train on historical data
- Feature extraction
- Simple neural network (logistic regression)
- Probability predictions
- Continuous learning
"""
import json
import math
import statistics
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class MLFeatures:
    # 20 features total
    ema_20_50_diff: float
    ema_50_200_diff: float
    price_vs_ema20: float
    price_vs_ema50: float
    rsi_14: float
    rsi_normalized: float  # (RSI - 50) / 50
    macd: float
    macd_signal_diff: float
    atr_pct: float
    bb_width: float
    bb_position: float
    volume_ratio: float
    candle_body_pct: float
    upper_shadow_pct: float
    lower_shadow_pct: float
    momentum_3: float  # 3-candle momentum
    momentum_10: float
    higher_highs: float
    lower_lows: float
    range_position: float  # Where in 50-candle range


@dataclass
class TrainingSample:
    features: MLFeatures
    label: int  # 1 = win, 0 = loss
    trade_type: str  # 'buy' or 'sell'


class SimpleNeuralNet:
    """Simple logistic regression for binary classification."""
    
    def __init__(self, n_features: int = 20):
        self.n_features = n_features
        # Initialize small random weights
        self.weights = [0.01 * (hash(str(i)) % 100 - 50) / 100 for i in range(n_features)]
        self.bias = 0.0
        self.learning_rate = 0.01
    
    def sigmoid(self, x: float) -> float:
        return 1 / (1 + math.exp(-max(min(x, 20), -20)))  # Clip to avoid overflow
    
    def predict_proba(self, features: List[float]) -> float:
        """Predict probability of win."""
        z = self.bias + sum(w * f for w, f in zip(self.weights, features))
        return self.sigmoid(z)
    
    def train_batch(self, samples: List[Tuple[List[float], int]]):
        """Train on a batch of samples (features, label)."""
        for features, label in samples:
            # Forward pass
            pred = self.predict_proba(features)
            
            # Error
            error = pred - label
            
            # Update weights
            for i in range(len(self.weights)):
                self.weights[i] -= self.learning_rate * error * features[i]
            
            self.bias -= self.learning_rate * error
    
    def save(self, path: str):
        """Save model."""
        with open(path, 'w') as f:
            json.dump({
                'weights': self.weights,
                'bias': self.bias
            }, f)
    
    def load(self, path: str):
        """Load model."""
        try:
            with open(path) as f:
                data = json.load(f)
                self.weights = data['weights']
                self.bias = data['bias']
        except:
            pass


class MLTraderTrained:
    """ML Trader with training."""
    
    def __init__(self, model_path: str = 'data/ml_model.json'):
        self.model_buy = SimpleNeuralNet()
        self.model_sell = SimpleNeuralNet()
        self.model_path = model_path
        
        # Training data
        self.training_samples: List[TrainingSample] = []
        
        # Load existing model
        try:
            self.model_buy.load(model_path.replace('.json', '_buy.json'))
            self.model_sell.load(model_path.replace('.json', '_sell.json'))
        except:
            pass
    
    def extract_features(self, candles: List[Candle]) -> Optional[MLFeatures]:
        """Extract 20 features from candles."""
        if len(candles) < 200:
            return None
        
        recent = candles[-100:]
        current = recent[-1]
        closes = [c.close for c in recent]
        
        # EMAs
        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, 50)
        ema200 = self._ema([c.close for c in candles], 200)
        
        # RSI
        rsi = self._rsi(closes, 14)
        
        # MACD
        macd, signal = self._macd(closes)
        
        # ATR
        atr = self._atr(recent[-20:], 14)
        
        # Bollinger Bands
        bb_upper, bb_lower = self._bollinger_bands(closes, 20, 2)
        bb_width = (bb_upper - bb_lower) / current.close
        bb_position = (current.close - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5
        
        # Volume
        avg_volume = statistics.mean(c.volume for c in recent[-20:-1]) if len(recent) > 20 else recent[-1].volume
        volume_ratio = current.volume / avg_volume if avg_volume > 0 else 1.0
        
        # Candle structure
        body = abs(current.close - current.open)
        range_size = current.high - current.low
        candle_body_pct = body / range_size if range_size > 0 else 0.0
        
        if current.close > current.open:
            upper_shadow = current.high - current.close
            lower_shadow = current.open - current.low
        else:
            upper_shadow = current.high - current.open
            lower_shadow = current.close - current.low
        
        upper_shadow_pct = upper_shadow / range_size if range_size > 0 else 0.0
        lower_shadow_pct = lower_shadow / range_size if range_size > 0 else 0.0
        
        # Momentum
        momentum_3 = (closes[-1] - closes[-4]) / closes[-4] if len(closes) >= 4 else 0.0
        momentum_10 = (closes[-1] - closes[-11]) / closes[-11] if len(closes) >= 11 else 0.0
        
        # Market structure
        higher_highs = sum(1 for i in range(len(recent)-10, len(recent)) 
                          if recent[i].high > max(c.high for c in recent[max(0,i-10):i]))
        lower_lows = sum(1 for i in range(len(recent)-10, len(recent)) 
                        if recent[i].low < min(c.low for c in recent[max(0,i-10):i]))
        
        # Range position
        high_50 = max(c.high for c in recent[-50:])
        low_50 = min(c.low for c in recent[-50:])
        range_position = (current.close - low_50) / (high_50 - low_50) if high_50 != low_50 else 0.5
        
        return MLFeatures(
            ema_20_50_diff=(ema20 - ema50) / ema50,
            ema_50_200_diff=(ema50 - ema200) / ema200,
            price_vs_ema20=(current.close - ema20) / ema20,
            price_vs_ema50=(current.close - ema50) / ema50,
            rsi_14=rsi,
            rsi_normalized=(rsi - 50) / 50,
            macd=macd / current.close,
            macd_signal_diff=(macd - signal) / current.close,
            atr_pct=atr / current.close,
            bb_width=bb_width,
            bb_position=bb_position,
            volume_ratio=min(volume_ratio, 5.0),  # Cap at 5x
            candle_body_pct=candle_body_pct,
            upper_shadow_pct=upper_shadow_pct,
            lower_shadow_pct=lower_shadow_pct,
            momentum_3=momentum_3,
            momentum_10=momentum_10,
            higher_highs=higher_highs / 10,
            lower_lows=lower_lows / 10,
            range_position=range_position
        )
    
    def predict(self, candles: List[Candle]) -> Optional[Tuple[str, float]]:
        """Predict trade direction and win probability."""
        features = self.extract_features(candles)
        if not features:
            return None
        
        # Convert to list
        feature_list = [
            features.ema_20_50_diff,
            features.ema_50_200_diff,
            features.price_vs_ema20,
            features.price_vs_ema50,
            features.rsi_14 / 100,  # Normalize
            features.rsi_normalized,
            features.macd,
            features.macd_signal_diff,
            features.atr_pct,
            features.bb_width,
            features.bb_position,
            features.volume_ratio / 5,  # Normalize
            features.candle_body_pct,
            features.upper_shadow_pct,
            features.lower_shadow_pct,
            features.momentum_3,
            features.momentum_10,
            features.higher_highs,
            features.lower_lows,
            features.range_position
        ]
        
        # Predict both
        win_prob_buy = self.model_buy.predict_proba(feature_list)
        win_prob_sell = self.model_sell.predict_proba(feature_list)
        
        # Choose best
        if win_prob_buy > win_prob_sell and win_prob_buy > 0.55:
            return ('buy', win_prob_buy)
        elif win_prob_sell > 0.55:
            return ('sell', win_prob_sell)
        
        return None
    
    def add_training_sample(self, candles: List[Candle], trade_type: str, won: bool):
        """Add a training sample from a completed trade."""
        features = self.extract_features(candles)
        if features:
            self.training_samples.append(TrainingSample(
                features=features,
                label=1 if won else 0,
                trade_type=trade_type
            ))
    
    def train(self, epochs: int = 10):
        """Train models on collected samples."""
        if len(self.training_samples) < 20:
            return  # Not enough data
        
        # Separate by trade type
        buy_samples = [(self._features_to_list(s.features), s.label) 
                       for s in self.training_samples if s.trade_type == 'buy']
        sell_samples = [(self._features_to_list(s.features), s.label) 
                        for s in self.training_samples if s.trade_type == 'sell']
        
        # Train
        for _ in range(epochs):
            if buy_samples:
                self.model_buy.train_batch(buy_samples)
            if sell_samples:
                self.model_sell.train_batch(sell_samples)
        
        # Save
        self.model_buy.save(self.model_path.replace('.json', '_buy.json'))
        self.model_sell.save(self.model_path.replace('.json', '_sell.json'))
    
    def _features_to_list(self, features: MLFeatures) -> List[float]:
        return [
            features.ema_20_50_diff,
            features.ema_50_200_diff,
            features.price_vs_ema20,
            features.price_vs_ema50,
            features.rsi_14 / 100,
            features.rsi_normalized,
            features.macd,
            features.macd_signal_diff,
            features.atr_pct,
            features.bb_width,
            features.bb_position,
            features.volume_ratio / 5,
            features.candle_body_pct,
            features.upper_shadow_pct,
            features.lower_shadow_pct,
            features.momentum_3,
            features.momentum_10,
            features.higher_highs,
            features.lower_lows,
            features.range_position
        ]
    
    # Technical indicators (same as before)
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
            gains.append(max(change, 0))
            losses.append(abs(min(change, 0)))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def _macd(self, closes: List[float]) -> Tuple[float, float]:
        ema12 = self._ema(closes, 12)
        ema26 = self._ema(closes, 26)
        macd = ema12 - ema26
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
        return sma + (std * std_dev), sma - (std * std_dev)
    
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
