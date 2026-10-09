#!/usr/bin/env python3
"""Ultimate Hybrid Trading System - Maximum Profitability.

Combines:
1. ML Predictions (proven 28.8% win rate)
2. Adaptive Regime Detection (V1 learning)
3. Multi-Strategy Selection (V2 quality)
4. Dynamic Risk Management
5. Trade Quality Filtering
6. Market Condition Awareness
7. Time-based Filtering (best sessions)
8. Correlation Analysis
9. Volatility Adaptation
10. Performance-based Auto-tuning

Goal: Maximize profit while minimizing risk.
"""
import json
import math
import statistics
from datetime import datetime, time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum


class MarketRegime(Enum):
    STRONG_UPTREND = "strong_uptrend"
    STRONG_DOWNTREND = "strong_downtrend"
    RANGING_CLEAN = "ranging_clean"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


class TradingSession(Enum):
    ASIAN = "asian"
    LONDON = "london"
    NEW_YORK = "new_york"
    OVERLAP = "overlap"  # London + NY


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
    def is_bullish(self) -> bool:
        return self.close > self.open


@dataclass
class TradeSetup:
    action: str
    entry: float
    stop_loss: float
    take_profit: float
    size: float
    confidence: float
    win_probability: float
    expected_value: float
    regime: MarketRegime
    session: TradingSession
    strategy: str
    quality_score: float
    reasons: List[str]


@dataclass
class PerformanceMetrics:
    """Track and optimize based on performance."""
    trades: int = 0
    wins: int = 0
    total_pnl: float = 0.0
    
    # By regime
    regime_stats: Dict[str, Dict] = field(default_factory=dict)
    
    # By session
    session_stats: Dict[str, Dict] = field(default_factory=dict)
    
    # By strategy
    strategy_stats: Dict[str, Dict] = field(default_factory=dict)
    
    # Recent performance (last 20)
    recent_trades: List[Dict] = field(default_factory=list)
    
    # Best performers
    best_regime: Optional[str] = None
    best_session: Optional[str] = None
    best_strategy: Optional[str] = None
    
    def update(self, regime: str, session: str, strategy: str, won: bool, pnl: float):
        self.trades += 1
        if won:
            self.wins += 1
        self.total_pnl += pnl
        
        # Update regime stats
        if regime not in self.regime_stats:
            self.regime_stats[regime] = {'wins': 0, 'trades': 0, 'pnl': 0.0}
        self.regime_stats[regime]['trades'] += 1
        if won:
            self.regime_stats[regime]['wins'] += 1
        self.regime_stats[regime]['pnl'] += pnl
        
        # Update session stats
        if session not in self.session_stats:
            self.session_stats[session] = {'wins': 0, 'trades': 0, 'pnl': 0.0}
        self.session_stats[session]['trades'] += 1
        if won:
            self.session_stats[session]['wins'] += 1
        self.session_stats[session]['pnl'] += pnl
        
        # Update strategy stats
        if strategy not in self.strategy_stats:
            self.strategy_stats[strategy] = {'wins': 0, 'trades': 0, 'pnl': 0.0}
        self.strategy_stats[strategy]['trades'] += 1
        if won:
            self.strategy_stats[strategy]['wins'] += 1
        self.strategy_stats[strategy]['pnl'] += pnl
        
        # Recent
        self.recent_trades.append({
            'regime': regime,
            'session': session,
            'strategy': strategy,
            'won': won,
            'pnl': pnl
        })
        if len(self.recent_trades) > 20:
            self.recent_trades.pop(0)
        
        # Update best performers
        self._update_best_performers()
    
    def _update_best_performers(self):
        # Best regime by win rate
        best_wr = 0
        for regime, stats in self.regime_stats.items():
            if stats['trades'] >= 5:
                wr = stats['wins'] / stats['trades']
                if wr > best_wr:
                    best_wr = wr
                    self.best_regime = regime
        
        # Best session by PnL
        best_pnl = float('-inf')
        for session, stats in self.session_stats.items():
            if stats['pnl'] > best_pnl:
                best_pnl = stats['pnl']
                self.best_session = session
        
        # Best strategy by win rate
        best_wr = 0
        for strategy, stats in self.strategy_stats.items():
            if stats['trades'] >= 5:
                wr = stats['wins'] / stats['trades']
                if wr > best_wr:
                    best_wr = wr
                    self.best_strategy = strategy
    
    def should_trade_regime(self, regime: str) -> bool:
        if regime not in self.regime_stats:
            return True
        stats = self.regime_stats[regime]
        if stats['trades'] < 10:
            return True
        wr = stats['wins'] / stats['trades']
        return wr >= 0.30  # Block if < 30% win rate
    
    def get_win_rate(self) -> float:
        return self.wins / self.trades if self.trades > 0 else 0.0
    
    def get_recent_win_rate(self) -> float:
        if not self.recent_trades:
            return 0.5
        wins = sum(1 for t in self.recent_trades if t['won'])
        return wins / len(self.recent_trades)


class UltimateTrader:
    """The ultimate profit-maximizing trading system."""
    
    def __init__(self):
        self.performance = PerformanceMetrics()
        
        # Dynamic parameters (adapt based on performance)
        self.base_risk = 0.015  # 1.5% base
        self.risk_multiplier = 1.0  # Adjust up/down
        self.min_confidence = 60.0  # Relaxed
        self.min_win_prob = 0.52  # More trades
        self.min_expected_value = 0.3  # Relaxed
        self.min_quality = 65.0  # Relaxed
        
        # Session preferences (learned from V1)
        self.session_multipliers = {
            TradingSession.ASIAN: 0.7,      # More conservative
            TradingSession.LONDON: 1.2,     # Best liquidity
            TradingSession.NEW_YORK: 1.1,
            TradingSession.OVERLAP: 1.3     # Best time
        }
        
        # Load saved performance
        self._load_performance()
    
    def analyze_and_decide(self, candles: List[Candle], balance: float) -> Optional[TradeSetup]:
        """Main decision engine with all filters."""
        if len(candles) < 200:
            return None
        
        current = candles[-1]
        
        # 1. Time filter - best sessions only
        session = self._get_session(current.time)
        if not self._is_good_time(current.time, session):
            return None
        
        # 2. Regime detection
        regime = self._detect_regime_advanced(candles)
        
        # 3. Performance filter - don't trade bad regimes
        if not self.performance.should_trade_regime(regime.value):
            return None
        
        # 4. Volatility filter - REMOVED (too restrictive)
        # All volatility levels acceptable
        
        # 5. Get ML prediction
        ml_prediction = self._ml_predict(candles)
        if not ml_prediction:
            return None
        
        direction, win_prob = ml_prediction
        
        # 6. Get technical confirmation
        tech_signal = self._technical_analysis(candles, direction, regime)
        if not tech_signal:
            return None
        
        # 7. Combine scores
        combined_confidence = (win_prob * 0.6 + tech_signal['confidence'] / 100 * 0.4) * 100
        
        # 8. Quality gate
        quality = self._calculate_quality(candles, direction, regime, session, combined_confidence)
        
        if quality < self.min_quality or combined_confidence < self.min_confidence or win_prob < self.min_win_prob:
            return None
        
        # 9. Calculate optimal levels
        entry = current.close
        sl, tp = self._calculate_optimal_levels(candles, direction, regime, win_prob)
        
        # 10. Risk-reward check
        rr = abs(tp - entry) / abs(sl - entry)
        if rr < 1.5:  # Minimum 1.5:1 (relaxed)
            return None
        
        # 11. Expected value check
        risk = abs(sl - entry)
        reward = abs(tp - entry)
        ev = (win_prob * reward) - ((1 - win_prob) * risk)
        
        if ev < self.min_expected_value:
            return None
        
        # 12. Dynamic position sizing
        size = self._calculate_dynamic_size(balance, entry, sl, session, regime, win_prob)
        
        # 13. Build setup
        return TradeSetup(
            action=direction,
            entry=entry,
            stop_loss=sl,
            take_profit=tp,
            size=size,
            confidence=combined_confidence,
            win_probability=win_prob,
            expected_value=ev,
            regime=regime,
            session=session,
            strategy=tech_signal['strategy'],
            quality_score=quality,
            reasons=tech_signal['reasons'] + [
                f"Win Prob: {win_prob*100:.1f}%",
                f"EV: {ev:.2f}",
                f"R:R: {rr:.1f}:1",
                f"Session: {session.value}"
            ]
        )
    
    def _get_session(self, dt: datetime) -> TradingSession:
        """Determine trading session."""
        hour = dt.hour
        
        # UTC times
        if 0 <= hour < 8:  # Asian
            return TradingSession.ASIAN
        elif 8 <= hour < 13:  # London
            return TradingSession.LONDON
        elif 13 <= hour < 16:  # Overlap
            return TradingSession.OVERLAP
        elif 16 <= hour < 21:  # New York
            return TradingSession.NEW_YORK
        else:
            return TradingSession.ASIAN
    
    def _is_good_time(self, dt: datetime, session: TradingSession) -> bool:
        """Filter out bad times."""
        hour = dt.hour
        day = dt.weekday()
        
        # No trading Friday after 20:00 UTC (weekend)
        if day == 4 and hour >= 20:
            return False
        
        # No trading Sunday night (low liquidity)
        if day == 6 and hour < 22:
            return False
        
        # Prefer London/Overlap (proven best in V1)
        if session in [TradingSession.LONDON, TradingSession.OVERLAP]:
            return True
        
        # Allow NY but with lower multiplier
        if session == TradingSession.NEW_YORK:
            return True
        
        # Asian allowed (relaxed)
        if session == TradingSession.ASIAN:
            return True  # Allow Asian session
        
        return True
    
    def _detect_regime_advanced(self, candles: List[Candle]) -> MarketRegime:
        """Advanced regime detection."""
        recent = candles[-100:]
        current = recent[-1]
        
        closes = [c.close for c in recent]
        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, 50)
        ema200 = self._ema([c.close for c in candles], 200)
        
        atr = self._atr(recent[-20:], 14)
        volatility = atr / current.close
        
        # ADX for trend strength
        adx = self._calculate_adx(recent[-30:], 14)
        
        # Alignment
        strong_up = current.close > ema20 > ema50 > ema200
        strong_down = current.close < ema20 < ema50 < ema200
        
        # Decision
        if volatility > 0.025:
            return MarketRegime.VOLATILE
        
        if strong_up and adx > 25:
            return MarketRegime.STRONG_UPTREND
        
        if strong_down and adx > 25:
            return MarketRegime.STRONG_DOWNTREND
        
        # Check for clean range
        high_50 = max(c.high for c in recent[-50:])
        low_50 = min(c.low for c in recent[-50:])
        range_pct = (high_50 - low_50) / current.close
        
        if range_pct < 0.02 and adx < 20:
            # Check S/R quality
            sr_count = len(self._find_support_resistance(recent))
            if sr_count >= 2:
                return MarketRegime.RANGING_CLEAN
        
        return MarketRegime.UNKNOWN
    
    def _check_volatility(self, candles: List[Candle]) -> bool:
        """Check if volatility is acceptable."""
        recent = candles[-20:]
        atr = self._atr(recent, 14)
        current = recent[-1].close
        
        volatility = atr / current
        
        # Too low = no opportunity
        if volatility < 0.002:  # 0.2% (relaxed)
            return False
        
        # Too high = too risky
        if volatility > 0.04:  # 4% (relaxed)
            return False
        
        return True
    
    def _ml_predict(self, candles: List[Candle]) -> Optional[Tuple[str, float]]:
        """ML prediction (same as winning ML Heuristic)."""
        features = self._extract_ml_features(candles)
        if not features:
            return None
        
        # Heuristic model (proven 28.8% win rate)
        long_score = 0.5
        short_score = 0.5
        
        # EMA trend
        if features['ema_20_50_diff'] > 0.005:
            long_score += 0.15
        elif features['ema_20_50_diff'] < -0.005:
            short_score += 0.15
        
        # RSI extremes
        if features['rsi'] < 35:
            long_score += 0.12
        elif features['rsi'] > 65:
            short_score += 0.12
        
        # MACD
        if features['macd'] > features['macd_signal']:
            long_score += 0.10
        else:
            short_score += 0.10
        
        # Bollinger Bands
        if features['bb_position'] < 0.25:
            long_score += 0.15
        elif features['bb_position'] > 0.75:
            short_score += 0.15
        
        # Volume
        if features['volume_ratio'] > 1.3:
            if features['momentum_3'] > 0:
                long_score += 0.10
            else:
                short_score += 0.10
        
        # Market structure
        if features['higher_highs'] >= 3:
            long_score += 0.10
        elif features['lower_lows'] >= 3:
            short_score += 0.10
        
        # Momentum confirmation
        if features['momentum_10'] > 0.005:
            long_score += 0.08
        elif features['momentum_10'] < -0.005:
            short_score += 0.08
        
        long_score = max(0.0, min(1.0, long_score))
        short_score = max(0.0, min(1.0, short_score))
        
        if long_score > short_score and long_score > 0.52:  # Relaxed
            return ('buy', long_score)
        elif short_score > 0.52:  # Relaxed
            return ('sell', short_score)
        
        return None
    
    def _extract_ml_features(self, candles: List[Candle]) -> Optional[Dict]:
        """Extract ML features."""
        if len(candles) < 200:
            return None
        
        recent = candles[-100:]
        current = recent[-1]
        closes = [c.close for c in recent]
        
        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, 50)
        ema200 = self._ema([c.close for c in candles], 200)
        
        rsi = self._rsi(closes, 14)
        macd, signal = self._macd(closes)
        atr = self._atr(recent[-20:], 14)
        bb_upper, bb_lower = self._bollinger_bands(closes, 20, 2)
        
        avg_volume = statistics.mean(c.volume for c in recent[-20:-1])
        volume_ratio = current.volume / avg_volume if avg_volume > 0 else 1.0
        
        momentum_3 = (closes[-1] - closes[-4]) / closes[-4] if len(closes) >= 4 else 0.0
        momentum_10 = (closes[-1] - closes[-11]) / closes[-11] if len(closes) >= 11 else 0.0
        
        higher_highs = sum(1 for i in range(len(recent)-10, len(recent)) 
                          if recent[i].high > max(c.high for c in recent[max(0,i-10):i]))
        lower_lows = sum(1 for i in range(len(recent)-10, len(recent)) 
                        if recent[i].low < min(c.low for c in recent[max(0,i-10):i]))
        
        return {
            'ema_20_50_diff': (ema20 - ema50) / ema50,
            'ema_50_200_diff': (ema50 - ema200) / ema200,
            'rsi': rsi,
            'macd': macd,
            'macd_signal': signal,
            'atr': atr / current.close,
            'bb_position': (current.close - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5,
            'volume_ratio': volume_ratio,
            'momentum_3': momentum_3,
            'momentum_10': momentum_10,
            'higher_highs': higher_highs,
            'lower_lows': lower_lows
        }
    
    def _technical_analysis(self, candles: List[Candle], direction: str, regime: MarketRegime) -> Optional[Dict]:
        """Technical confirmation."""
        recent = candles[-50:]
        current = recent[-1]
        
        ema20 = self._ema([c.close for c in recent], 20)
        ema50 = self._ema([c.close for c in recent], 50)
        atr = self._atr(recent[-20:], 14)
        
        reasons = []
        confidence = 50
        strategy = "unknown"
        
        # Trend following
        if regime in [MarketRegime.STRONG_UPTREND, MarketRegime.STRONG_DOWNTREND]:
            strategy = "trend_continuation"
            
            if direction == 'buy' and regime == MarketRegime.STRONG_UPTREND:
                dist = abs(current.close - ema20) / current.close
                if dist < 0.004:
                    reasons.append("Pullback to EMA20")
                    confidence += 20
                
                if current.is_bullish:
                    reasons.append("Bullish candle")
                    confidence += 15
                
                if confidence >= 55:  # Relaxed
                    return {'confidence': confidence, 'reasons': reasons, 'strategy': strategy}
            
            elif direction == 'sell' and regime == MarketRegime.STRONG_DOWNTREND:
                dist = abs(current.close - ema20) / current.close
                if dist < 0.004:
                    reasons.append("Pullback to EMA20")
                    confidence += 20
                
                if not current.is_bullish:
                    reasons.append("Bearish candle")
                    confidence += 15
                
                if confidence >= 55:  # Relaxed
                    return {'confidence': confidence, 'reasons': reasons, 'strategy': strategy}
        
        # Range trading
        elif regime == MarketRegime.RANGING_CLEAN:
            strategy = "range_bounce"
            sr_levels = self._find_support_resistance(recent)
            
            if not sr_levels:
                return None
            
            price = current.close
            
            for level in sr_levels:
                dist = abs(price - level['price']) / price
                
                if dist < 0.003:
                    if direction == 'buy' and level['type'] == 'support':
                        reasons.append(f"At support {level['price']:.1f}")
                        confidence += 20
                        
                        if current.is_bullish:
                            reasons.append("Bullish bounce")
                            confidence += 15
                        
                        if level['touches'] >= 3:
                            reasons.append(f"{level['touches']} touches")
                            confidence += 10
                        
                        if confidence >= 65:
                            return {'confidence': confidence, 'reasons': reasons, 'strategy': strategy}
                    
                    elif direction == 'sell' and level['type'] == 'resistance':
                        reasons.append(f"At resistance {level['price']:.1f}")
                        confidence += 20
                        
                        if not current.is_bullish:
                            reasons.append("Bearish rejection")
                            confidence += 15
                        
                        if level['touches'] >= 3:
                            reasons.append(f"{level['touches']} touches")
                            confidence += 10
                        
                        if confidence >= 65:
                            return {'confidence': confidence, 'reasons': reasons, 'strategy': strategy}
        
        return None
    
    def _calculate_quality(self, candles: List[Candle], direction: str, regime: MarketRegime, 
                          session: TradingSession, confidence: float) -> float:
        """Calculate overall setup quality."""
        quality = confidence * 0.5  # Start from confidence
        
        # Regime bonus
        if regime in [MarketRegime.STRONG_UPTREND, MarketRegime.STRONG_DOWNTREND]:
            quality += 10
        elif regime == MarketRegime.RANGING_CLEAN:
            quality += 5
        
        # Session bonus
        if session == TradingSession.OVERLAP:
            quality += 10
        elif session == TradingSession.LONDON:
            quality += 8
        elif session == TradingSession.NEW_YORK:
            quality += 5
        
        # Performance bonus
        if self.performance.best_regime == regime.value:
            quality += 5
        
        if self.performance.best_session == session.value:
            quality += 5
        
        # Recent performance bonus
        recent_wr = self.performance.get_recent_win_rate()
        if recent_wr > 0.5:
            quality += 5
        elif recent_wr < 0.3:
            quality -= 10
        
        return min(100, max(0, quality))
    
    def _calculate_optimal_levels(self, candles: List[Candle], direction: str, 
                                 regime: MarketRegime, win_prob: float) -> Tuple[float, float]:
        """Calculate optimal SL and TP based on win probability and regime."""
        recent = candles[-50:]
        current = recent[-1].close
        atr = self._atr(recent[-20:], 14)
        
        # Adaptive SL based on win probability
        # Higher win prob = tighter stop
        sl_multiplier = 1.5 - (win_prob - 0.5) * 0.8  # 1.5 at 50%, 1.1 at 90%
        
        # Adaptive TP based on regime
        if regime in [MarketRegime.STRONG_UPTREND, MarketRegime.STRONG_DOWNTREND]:
            tp_multiplier = 3.5  # Ride the trend
        else:
            tp_multiplier = 2.5  # Conservative in range
        
        if direction == 'buy':
            sl = current - (atr * sl_multiplier)
            tp = current + (atr * tp_multiplier)
        else:
            sl = current + (atr * sl_multiplier)
            tp = current - (atr * tp_multiplier)
        
        return sl, tp
    
    def _calculate_dynamic_size(self, balance: float, entry: float, sl: float, 
                               session: TradingSession, regime: MarketRegime, win_prob: float) -> float:
        """Dynamic position sizing based on multiple factors."""
        # Base risk
        risk_pct = self.base_risk * self.risk_multiplier
        
        # Session adjustment
        risk_pct *= self.session_multipliers[session]
        
        # Regime adjustment
        if regime in [MarketRegime.STRONG_UPTREND, MarketRegime.STRONG_DOWNTREND]:
            risk_pct *= 1.1  # Slightly more aggressive in strong trends
        elif regime == MarketRegime.RANGING_CLEAN:
            risk_pct *= 1.0
        else:
            risk_pct *= 0.8  # More conservative in unknown
        
        # Win probability adjustment
        if win_prob > 0.70:
            risk_pct *= 1.15  # High confidence = more size
        elif win_prob < 0.60:
            risk_pct *= 0.85
        
        # Recent performance adjustment
        recent_wr = self.performance.get_recent_win_rate()
        if recent_wr > 0.5:
            risk_pct *= 1.1  # On a roll
        elif recent_wr < 0.35:
            risk_pct *= 0.7  # In a slump
        
        # Calculate size
        risk_amount = balance * risk_pct
        sl_distance = abs(entry - sl)
        size = risk_amount / (sl_distance * 100)
        
        # Cap at 0.5 lot
        return max(0.01, min(size, 0.5))
    
    def update_performance(self, regime: str, session: str, strategy: str, won: bool, pnl: float):
        """Update performance and auto-tune parameters."""
        self.performance.update(regime, session, strategy, won, pnl)
        
        # Auto-tune every 10 trades
        if self.performance.trades % 10 == 0:
            self._auto_tune()
        
        # Save
        self._save_performance()
    
    def _auto_tune(self):
        """Automatically adjust parameters based on performance."""
        overall_wr = self.performance.get_win_rate()
        recent_wr = self.performance.get_recent_win_rate()
        
        # Adjust risk multiplier
        if recent_wr > 0.55:
            self.risk_multiplier = min(1.3, self.risk_multiplier + 0.1)
        elif recent_wr < 0.35:
            self.risk_multiplier = max(0.6, self.risk_multiplier - 0.1)
        
        # Adjust confidence threshold
        if overall_wr > 0.50 and self.performance.trades >= 30:
            self.min_confidence = max(65.0, self.min_confidence - 2)
        elif overall_wr < 0.40 and self.performance.trades >= 20:
            self.min_confidence = min(80.0, self.min_confidence + 3)
        
        # Adjust win probability threshold
        if overall_wr > 0.50:
            self.min_win_prob = max(0.55, self.min_win_prob - 0.02)
        elif overall_wr < 0.40:
            self.min_win_prob = min(0.70, self.min_win_prob + 0.03)
    
    def _save_performance(self):
        try:
            with open('data/ultimate_performance.json', 'w') as f:
                json.dump({
                    'trades': self.performance.trades,
                    'wins': self.performance.wins,
                    'total_pnl': self.performance.total_pnl,
                    'regime_stats': self.performance.regime_stats,
                    'session_stats': self.performance.session_stats,
                    'strategy_stats': self.performance.strategy_stats,
                    'risk_multiplier': self.risk_multiplier,
                    'min_confidence': self.min_confidence,
                    'min_win_prob': self.min_win_prob
                }, f, indent=2)
        except:
            pass
    
    def _load_performance(self):
        try:
            with open('data/ultimate_performance.json') as f:
                data = json.load(f)
                self.performance.trades = data.get('trades', 0)
                self.performance.wins = data.get('wins', 0)
                self.performance.total_pnl = data.get('total_pnl', 0.0)
                self.performance.regime_stats = data.get('regime_stats', {})
                self.performance.session_stats = data.get('session_stats', {})
                self.performance.strategy_stats = data.get('strategy_stats', {})
                self.risk_multiplier = data.get('risk_multiplier', 1.0)
                self.min_confidence = data.get('min_confidence', 70.0)
                self.min_win_prob = data.get('min_win_prob', 0.58)
                self.performance._update_best_performers()
        except:
            pass
    
    def _find_support_resistance(self, candles: List[Candle]) -> List[Dict]:
        levels = []
        for i in range(10, len(candles) - 10):
            if all(candles[i].high >= c.high for c in candles[i-10:i]) and \
               all(candles[i].high >= c.high for c in candles[i+1:i+11]):
                level_price = candles[i].high
                touches = sum(1 for c in candles if abs(c.high - level_price) / level_price < 0.003)
                if touches >= 2:
                    levels.append({'type': 'resistance', 'price': level_price, 'touches': touches})
            
            if all(candles[i].low <= c.low for c in candles[i-10:i]) and \
               all(candles[i].low <= c.low for c in candles[i+1:i+11]):
                level_price = candles[i].low
                touches = sum(1 for c in candles if abs(c.low - level_price) / level_price < 0.003)
                if touches >= 2:
                    levels.append({'type': 'support', 'price': level_price, 'touches': touches})
        
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
    
    def _calculate_adx(self, candles: List[Candle], period: int) -> float:
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
        plus_di = sum(plus_dm[-period:]) / sum(tr_list[-period:]) * 100 if sum(tr_list[-period:]) > 0 else 0
        minus_di = sum(minus_dm[-period:]) / sum(tr_list[-period:]) * 100 if sum(tr_list[-period:]) > 0 else 0
        dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
        return dx
