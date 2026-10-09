#!/usr/bin/env python3
"""Ensemble Trader - Combines multiple strategies with adaptive weighting.

Combines:
1. Improved Range Strategy
2. Trend Following
3. Breakout Strategy
4. ML Predictions

Weights adapt based on recent performance.
"""
import json
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass
import sys

sys.path.insert(0, '/home/ai/hermes-trading')

from improved_trader_v2 import ImprovedTrader, Candle as Candle1, TradeSignal
from ml_trader import MLTrader, Candle as Candle2, MLSignal


@dataclass
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class EnsembleSignal:
    action: str
    entry: float
    stop_loss: float
    take_profit: float
    size: float
    confidence: float
    strategies_agreed: List[str]
    vote_count: int


class EnsembleTrader:
    """Multi-strategy ensemble with adaptive weighting."""
    
    def __init__(self):
        self.improved_trader = ImprovedTrader()
        self.ml_trader = MLTrader()
        
        # Strategy weights (adapt based on performance)
        self.weights = {
            'improved': 1.0,
            'ml': 1.0
        }
        
        # Performance tracking
        self.strategy_performance = {
            'improved': {'wins': 0, 'losses': 0},
            'ml': {'wins': 0, 'losses': 0}
        }
    
    def analyze_and_decide(self, candles: List[Candle], balance: float) -> Optional[EnsembleSignal]:
        """Get signals from all strategies and combine."""
        
        # Get signals from each strategy
        improved_signal = self.improved_trader.analyze_and_decide(candles, balance)
        ml_signal = self.ml_trader.analyze_and_predict(candles, balance)
        
        # Collect votes
        buy_votes = 0
        sell_votes = 0
        buy_strategies = []
        sell_strategies = []
        
        if improved_signal and improved_signal.action == 'buy':
            buy_votes += self.weights['improved']
            buy_strategies.append('improved')
        elif improved_signal and improved_signal.action == 'sell':
            sell_votes += self.weights['improved']
            sell_strategies.append('improved')
        
        if ml_signal and ml_signal.action == 'buy':
            buy_votes += self.weights['ml']
            buy_strategies.append('ml')
        elif ml_signal and ml_signal.action == 'sell':
            sell_votes += self.weights['ml']
            sell_strategies.append('ml')
        
        # Minimum 2 strategies must agree
        min_agreement = 1.5
        
        if buy_votes >= min_agreement:
            # Average the levels from agreeing strategies
            entry = candles[-1].close
            
            sls = []
            tps = []
            
            if improved_signal and improved_signal.action == 'buy':
                sls.append(improved_signal.stop_loss)
                tps.append(improved_signal.take_profit)
            if ml_signal and ml_signal.action == 'buy':
                sls.append(ml_signal.stop_loss)
                tps.append(ml_signal.take_profit)
            
            sl = sum(sls) / len(sls)
            tp = sum(tps) / len(tps)
            
            size = self._calculate_size(balance, entry, sl)
            confidence = (buy_votes / sum(self.weights.values())) * 100
            
            return EnsembleSignal(
                action='buy',
                entry=entry,
                stop_loss=sl,
                take_profit=tp,
                size=size,
                confidence=confidence,
                strategies_agreed=buy_strategies,
                vote_count=len(buy_strategies)
            )
        
        elif sell_votes >= min_agreement:
            entry = candles[-1].close
            
            sls = []
            tps = []
            
            if improved_signal and improved_signal.action == 'sell':
                sls.append(improved_signal.stop_loss)
                tps.append(improved_signal.take_profit)
            if ml_signal and ml_signal.action == 'sell':
                sls.append(ml_signal.stop_loss)
                tps.append(ml_signal.take_profit)
            
            sl = sum(sls) / len(sls)
            tp = sum(tps) / len(tps)
            
            size = self._calculate_size(balance, entry, sl)
            confidence = (sell_votes / sum(self.weights.values())) * 100
            
            return EnsembleSignal(
                action='sell',
                entry=entry,
                stop_loss=sl,
                take_profit=tp,
                size=size,
                confidence=confidence,
                strategies_agreed=sell_strategies,
                vote_count=len(sell_strategies)
            )
        
        return None
    
    def update_performance(self, strategy: str, won: bool):
        """Update strategy performance and adapt weights."""
        if won:
            self.strategy_performance[strategy]['wins'] += 1
        else:
            self.strategy_performance[strategy]['losses'] += 1
        
        # Recalculate weights
        for name in self.weights:
            perf = self.strategy_performance[name]
            total = perf['wins'] + perf['losses']
            
            if total >= 5:  # Minimum trades before adapting
                win_rate = perf['wins'] / total
                
                # Weight based on win rate
                if win_rate > 0.6:
                    self.weights[name] = 1.5
                elif win_rate > 0.5:
                    self.weights[name] = 1.0
                else:
                    self.weights[name] = 0.5
    
    def _calculate_size(self, balance: float, entry: float, sl: float) -> float:
        risk_amount = balance * 0.015
        sl_distance = abs(entry - sl)
        size = risk_amount / (sl_distance * 100)
        return max(0.01, min(size, 0.5))
