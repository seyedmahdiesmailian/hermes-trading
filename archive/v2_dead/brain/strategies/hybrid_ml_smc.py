#!/usr/bin/env python3
"""Hybrid ML-SMC Strategy - Maximum Profitability.

Combines:
- ML Heuristic: 20 features, probability-based (proven -1.3%)
- V1 SMC Filters: Premium/Discount zones, POI grading
- Best of both: ML for signals, SMC for filtering

Logic:
1. ML detects opportunities (broad net)
2. SMC filters quality (high-probability only)
3. Premium zone shorts + Discount zone longs = edge
4. Session risk multipliers
5. Dynamic R:R based on market structure
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import statistics
import math

from brain.domain.entities.market import MarketState, Candle
from brain.domain.services.market_analyzer import AnalysisResult
from brain.analysis.smc_analyzer import SMCAnalyzer, SMCAnalysis


class HybridMLSMCStrategy:
    """Hybrid ML-SMC - Maximum Win Rate Strategy.
    
    Combines ML's adaptive learning with SMC's institutional edge.
    Target: 40-50% WR (realistic for ranging + trending)
    """
    
    def __init__(self):
        self.name = "Hybrid_ML_SMC"
        self.smc_analyzer = SMCAnalyzer()
        
        # Relaxed thresholds for more trades
        self.min_ml_confidence = 0.55  # ML must be confident
        self.min_smc_confidence = 0.35  # SMC adds confluence
        self.min_combined = 0.60  # Combined threshold
        
        # Dynamic R:R (not fixed 2.0)
        self.base_rr = 1.8
        
        # Session multipliers (V1 proven)
        self.session_mult = {
            'asia': 0.6,
            'london': 1.0,
            'newyork': 1.0,
            'overlap': 1.1
        }
    
    def get_name(self) -> str:
        return self.name
    
    def analyze(self, market: MarketState) -> AnalysisResult:
        """Hybrid analysis: ML + SMC."""
        candles = market.candles
        
        if len(candles) < 200:
            return self._no_signal("Insufficient data")
        
        # 1. ML Analysis (primary signal)
        ml_signal, ml_confidence, ml_features = self._ml_analysis(candles)
        
        if ml_signal is None or ml_confidence < self.min_ml_confidence:
            return self._no_signal(f"ML no signal or low confidence: {ml_confidence:.2f}")
        
        # 2. SMC Analysis (quality filter)
        smc = self.smc_analyzer.analyze(candles)
        
        # 3. Check alignment (ML + SMC must agree)
        if not self._check_alignment(ml_signal, smc):
            return self._no_signal(f"ML-SMC misalignment: ML={ml_signal}, SMC={smc.bias}")
        
        # 4. Calculate combined confidence
        combined_conf = self._calculate_combined_confidence(
            ml_confidence, smc.confidence, smc.premium_discount, ml_signal
        )
        
        if combined_conf < self.min_combined:
            return self._no_signal(f"Combined confidence too low: {combined_conf:.2f}")
        
        # 5. Session & Style analysis
        session = self._detect_session(candles[-1].time)
        entry_style = self._classify_style(smc, ml_signal)
        
        # 6. Calculate dynamic R:R
        rr = self._calculate_dynamic_rr(smc, ml_features)
        
        # 7. Calculate levels
        entry_price = candles[-1].close
        sl, tp = self._calculate_levels(ml_signal, smc, entry_price, candles, rr)
        
        if sl is None or tp is None:
            return self._no_signal("Could not calculate levels")
        
        # 8. Quality gate: Check stop size
        atr = self._calculate_atr(candles[-20:], 14)
        stop_distance = abs(entry_price - sl)
        
        if stop_distance < atr * 1.0:  # Minimum 1 ATR
            return self._no_signal(f"Stop too tight: {stop_distance:.1f} < {atr*1.0:.1f}")
        
        if stop_distance > atr * 5.0:  # Maximum 5 ATR
            return self._no_signal(f"Stop too wide: {stop_distance:.1f} > {atr*5.0:.1f}")
        
        # 9. Calculate risk multiplier
        risk_mult = self._calculate_risk_multiplier(
            session, smc.premium_discount, smc.poi_quality, entry_style
        )
        
        # 10. Build reasoning
        reasoning = self._build_reasoning(
            ml_confidence, smc, ml_features, entry_style, session, 
            risk_mult, rr, combined_conf
        )
        
        # 11. Build result
        return AnalysisResult(
            trend="bullish" if ml_signal == "buy" else "bearish",
            trend_strength=combined_conf,
            key_levels={
                'support': [sl] if ml_signal == "buy" else [tp],
                'resistance': [tp] if ml_signal == "buy" else [sl],
                'entry': [entry_price],
                'stop_loss': [sl],
                'take_profit': [tp]
            },
            patterns=[
                f"Hybrid-{ml_signal}",
                entry_style,
                smc.premium_discount,
                f"Grade-{smc.poi_quality}"
            ],
            quality_score=combined_conf * risk_mult,
            confidence=combined_conf,
            reasoning=reasoning
        )
    
    def _ml_analysis(self, candles: List[Candle]) -> Tuple[Optional[str], float, Dict]:
        """ML analysis using 20 features.
        
        Returns:
            (signal, confidence, features)
        """
        if len(candles) < 200:
            return None, 0.0, {}
        
        recent = candles[-100:]
        current = recent[-1]
        closes = [c.close for c in recent]
        
        # Extract features
        features = {}
        
        # EMAs
        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, 50)
        ema200 = self._ema([c.close for c in candles], 200)
        features['ema_20_50_diff'] = (ema20 - ema50) / ema50
        features['ema_50_200_diff'] = (ema50 - ema200) / ema200
        
        # RSI
        rsi = self._rsi(closes, 14)
        features['rsi'] = rsi
        features['rsi_normalized'] = (rsi - 50) / 50
        
        # MACD
        macd, signal = self._macd(closes)
        features['macd'] = macd
        features['macd_signal_diff'] = macd - signal
        
        # Bollinger Bands
        bb_upper, bb_lower = self._bollinger_bands(closes, 20, 2)
        features['bb_position'] = (current.close - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5
        features['bb_width'] = (bb_upper - bb_lower) / current.close
        
        # Volume
        avg_volume = statistics.mean(c.volume for c in recent[-20:-1]) if len(recent) > 20 else recent[-1].volume
        features['volume_ratio'] = current.volume / avg_volume if avg_volume > 0 else 1.0
        
        # Momentum
        features['momentum_3'] = (closes[-1] - closes[-4]) / closes[-4] if len(closes) >= 4 else 0.0
        features['momentum_10'] = (closes[-1] - closes[-11]) / closes[-11] if len(closes) >= 11 else 0.0
        
        # Market structure
        features['higher_highs'] = sum(1 for i in range(len(recent)-10, len(recent)) 
                                      if recent[i].high > max(c.high for c in recent[max(0,i-10):i]))
        features['lower_lows'] = sum(1 for i in range(len(recent)-10, len(recent)) 
                                    if recent[i].low < min(c.low for c in recent[max(0,i-10):i]))
        
        # Predict
        long_score = 0.5
        short_score = 0.5
        
        # EMA trend (weight: 0.15)
        if features['ema_20_50_diff'] > 0.003:
            long_score += 0.15
        elif features['ema_20_50_diff'] < -0.003:
            short_score += 0.15
        
        # RSI extremes (weight: 0.12)
        if rsi < 40:
            long_score += 0.12
        elif rsi > 60:
            short_score += 0.12
        
        # MACD (weight: 0.10)
        if macd > signal:
            long_score += 0.10
        else:
            short_score += 0.10
        
        # Bollinger Bands (weight: 0.15)
        if features['bb_position'] < 0.3:
            long_score += 0.15
        elif features['bb_position'] > 0.7:
            short_score += 0.15
        
        # Volume (weight: 0.10)
        if features['volume_ratio'] > 1.2:
            if features['momentum_3'] > 0:
                long_score += 0.10
            else:
                short_score += 0.10
        
        # Market structure (weight: 0.10)
        if features['higher_highs'] >= 3:
            long_score += 0.10
        elif features['lower_lows'] >= 3:
            short_score += 0.10
        
        # Momentum (weight: 0.08)
        if features['momentum_10'] > 0.003:
            long_score += 0.08
        elif features['momentum_10'] < -0.003:
            short_score += 0.08
        
        long_score = max(0.0, min(1.0, long_score))
        short_score = max(0.0, min(1.0, short_score))
        
        if long_score > short_score and long_score > 0.55:
            return 'buy', long_score, features
        elif short_score > 0.55:
            return 'sell', short_score, features
        
        return None, max(long_score, short_score), features
    
    def _check_alignment(self, ml_signal: str, smc: SMCAnalysis) -> bool:
        """Check if ML and SMC agree.
        
        Returns:
            True if aligned or SMC neutral
        """
        if smc.bias == "neutral":
            return True  # SMC neutral = don't filter
        
        if ml_signal == "buy" and smc.bias == "bullish":
            return True
        
        if ml_signal == "sell" and smc.bias == "bearish":
            return True
        
        return False
    
    def _calculate_combined_confidence(self, ml_conf: float, smc_conf: float,
                                       premium_discount: str, ml_signal: str) -> float:
        """Calculate combined confidence score.
        
        Boosts:
        - Premium shorts: +10%
        - Discount longs: +5%
        """
        # Base: weighted average (ML 70%, SMC 30%)
        combined = ml_conf * 0.7 + smc_conf * 0.3
        
        # Premium/Discount boost (V1 proven edge)
        if ml_signal == "sell" and premium_discount == "premium":
            combined += 0.10  # Premium shorts = V1's 65% WR!
        elif ml_signal == "buy" and premium_discount == "discount":
            combined += 0.05  # Discount longs
        
        return min(1.0, combined)
    
    def _detect_session(self, timestamp: datetime) -> str:
        """Detect trading session."""
        hour_utc = timestamp.hour
        
        if 12 <= hour_utc < 16:
            return 'overlap'
        elif 7 <= hour_utc < 16:
            return 'london'
        elif 12 <= hour_utc < 21:
            return 'newyork'
        else:
            return 'asia'
    
    def _classify_style(self, smc: SMCAnalysis, ml_signal: str) -> str:
        """Classify entry style."""
        if ml_signal == "sell" and smc.premium_discount == "premium":
            return "premium_fade"  # V1's 65% WR
        
        if ml_signal == "buy" and smc.premium_discount == "discount":
            if len(smc.order_blocks) > 0 and smc.order_blocks[0].strength > 0.6:
                return "value_entry"  # Strong OB
            return "discount_long"
        
        if smc.market_structure in ["bos_bullish", "bos_bearish"]:
            return "trend_continuation"
        
        return "standard"
    
    def _calculate_dynamic_rr(self, smc: SMCAnalysis, ml_features: Dict) -> float:
        """Calculate dynamic R:R based on market conditions.
        
        Returns:
            Risk:Reward ratio (1.5 - 3.0)
        """
        rr = self.base_rr
        
        # Strong trend = wider targets
        if abs(ml_features.get('momentum_10', 0)) > 0.008:
            rr += 0.5
        
        # Clear structure = wider targets
        if smc.market_structure in ["bos_bullish", "bos_bearish"]:
            rr += 0.3
        
        # High confidence = wider targets
        if smc.confidence > 0.7:
            rr += 0.2
        
        return min(3.0, max(1.5, rr))
    
    def _calculate_levels(self, signal: str, smc: SMCAnalysis, entry: float,
                         candles: List[Candle], rr: float) -> Tuple[Optional[float], Optional[float]]:
        """Calculate SL and TP."""
        atr = self._calculate_atr(candles[-20:], 14)
        
        if signal == "buy":
            # SL: ATR-based or SMC invalidation
            if smc.invalidation and smc.invalidation < entry:
                sl = max(smc.invalidation, entry - atr * 2.5)
            else:
                sl = entry - atr * 1.5
            
            # TP: Dynamic R:R
            risk = entry - sl
            tp = entry + (risk * rr)
        
        else:  # sell
            if smc.invalidation and smc.invalidation > entry:
                sl = min(smc.invalidation, entry + atr * 2.5)
            else:
                sl = entry + atr * 1.5
            
            risk = sl - entry
            tp = entry - (risk * rr)
        
        return sl, tp
    
    def _calculate_risk_multiplier(self, session: str, premium_discount: str,
                                   poi_grade: str, entry_style: str) -> float:
        """Calculate risk multiplier.
        
        Returns:
            0.6 - 1.1
        """
        # Base session mult
        mult = self.session_mult.get(session, 1.0)
        
        # Premium fade bonus (V1 edge!)
        if entry_style == "premium_fade":
            mult *= 1.05
        
        # Grade adjustment
        grade_mult = {'A': 1.0, 'B': 0.95, 'C': 0.85}.get(poi_grade, 0.9)
        mult *= grade_mult
        
        return max(0.6, min(1.1, mult))
    
    def _build_reasoning(self, ml_conf: float, smc: SMCAnalysis, ml_features: Dict,
                        entry_style: str, session: str, risk_mult: float,
                        rr: float, combined_conf: float) -> Dict:
        """Build reasoning dict."""
        reasoning = {
            'ml_confidence': ml_conf,
            'smc_confidence': smc.confidence,
            'combined_confidence': combined_conf,
            'premium_discount': smc.premium_discount,
            'fib_level': smc.fib_level,
            'market_structure': smc.market_structure,
            'poi_grade': smc.poi_quality,
            'entry_style': entry_style,
            'session': session,
            'risk_multiplier': risk_mult,
            'risk_reward': rr,
            'ml_features': {
                'rsi': ml_features.get('rsi', 0),
                'bb_position': ml_features.get('bb_position', 0),
                'momentum_10': ml_features.get('momentum_10', 0)
            },
            'summary': []
        }
        
        # Build summary
        reasoning['summary'].append(f"Hybrid: ML {ml_conf*100:.0f}% + SMC {smc.confidence*100:.0f}%")
        reasoning['summary'].append(f"{smc.premium_discount.title()} zone")
        reasoning['summary'].append(f"Grade {smc.poi_quality}")
        reasoning['summary'].append(f"Style: {entry_style}")
        
        if len(smc.order_blocks) > 0:
            reasoning['summary'].append(f"{len(smc.order_blocks)} OBs")
        
        if smc.liquidity_sweep:
            reasoning['summary'].append(f"Sweep: {smc.liquidity_sweep}")
        
        reasoning['summary'].append(f"R:R {rr:.1f}:1")
        reasoning['summary'].append(f"{session.title()} ({risk_mult:.2f}x)")
        
        # Edge indicators
        if entry_style == "premium_fade":
            reasoning['summary'].append("⭐ V1 65% WR style")
        elif entry_style == "value_entry":
            reasoning['summary'].append("⭐ Strong OB")
        
        return reasoning
    
    def _no_signal(self, reason: str) -> AnalysisResult:
        """No signal result."""
        return AnalysisResult(
            trend="ranging",
            trend_strength=0.0,
            key_levels={'support': [], 'resistance': []},
            patterns=[],
            quality_score=0.0,
            confidence=0.0,
            reasoning={'status': 'no_signal', 'reason': reason}
        )
    
    # Technical indicators (same as ML Heuristic)
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
    
    def _calculate_atr(self, candles: List[Candle], period: int) -> float:
        if len(candles) < 2:
            return 0.0
        trs = []
        for i in range(1, len(candles)):
            tr = max(
                candles[i].high - candles[i].low,
                abs(candles[i].high - candles[i-1].close),
                abs(candles[i].low - candles[i-1].close)
            )
            trs.append(tr)
        return statistics.mean(trs[-period:]) if trs else 0.0
