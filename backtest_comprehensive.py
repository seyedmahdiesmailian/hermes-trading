#!/usr/bin/env python3
"""Comprehensive Backtest - All strategies on existing data.

Compares:
1. ML Heuristic
2. V1 SMC
3. Hybrid ML-SMC
4. SMC Strategy (current production)
5. Classic Strategy (current production)
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import List

# Add project root
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class Candle:
    """Simple candle for backtest."""
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Trade:
    """Trade result."""
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    direction: str  # 'LONG' or 'SHORT'
    pnl: float
    pnl_pct: float


class SimpleBacktest:
    """Simple backtest engine."""
    
    def __init__(self, initial_capital: float = 10000):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.trades: List[Trade] = []
    
    def run(self, candles: List[Candle], strategy) -> dict:
        """Run backtest."""
        self.capital = self.initial_capital
        self.trades = []
        
        position = None  # {'direction': 'LONG'/'SHORT', 'entry_price': float, 'entry_time': datetime}
        
        for i in range(50, len(candles)):  # Need history for indicators
            current = candles[i]
            history = candles[max(0, i-200):i+1]
            
            # Get signal
            signal = strategy.analyze(history)
            
            # Close position if signal reverses or stop/target hit
            if position:
                exit_price = None
                
                if position['direction'] == 'LONG':
                    if signal == 'SHORT' or current.close < position['stop_loss']:
                        exit_price = current.close
                    elif current.close >= position['take_profit']:
                        exit_price = position['take_profit']
                
                elif position['direction'] == 'SHORT':
                    if signal == 'LONG' or current.close > position['stop_loss']:
                        exit_price = current.close
                    elif current.close <= position['take_profit']:
                        exit_price = position['take_profit']
                
                if exit_price:
                    # Close trade
                    if position['direction'] == 'LONG':
                        pnl = exit_price - position['entry_price']
                    else:
                        pnl = position['entry_price'] - exit_price
                    
                    pnl_pct = (pnl / position['entry_price']) * 100
                    
                    self.trades.append(Trade(
                        entry_time=position['entry_time'],
                        entry_price=position['entry_price'],
                        exit_time=current.time,
                        exit_price=exit_price,
                        direction=position['direction'],
                        pnl=pnl,
                        pnl_pct=pnl_pct
                    ))
                    
                    self.capital += pnl
                    position = None
            
            # Open new position
            if not position and signal in ['LONG', 'SHORT']:
                # Simple stops: 1% SL, 2% TP
                if signal == 'LONG':
                    sl = current.close * 0.99
                    tp = current.close * 1.02
                else:
                    sl = current.close * 1.01
                    tp = current.close * 0.98
                
                position = {
                    'direction': signal,
                    'entry_price': current.close,
                    'entry_time': current.time,
                    'stop_loss': sl,
                    'take_profit': tp
                }
        
        # Close any open position at end
        if position:
            exit_price = candles[-1].close
            if position['direction'] == 'LONG':
                pnl = exit_price - position['entry_price']
            else:
                pnl = position['entry_price'] - exit_price
            
            pnl_pct = (pnl / position['entry_price']) * 100
            
            self.trades.append(Trade(
                entry_time=position['entry_time'],
                entry_price=position['entry_price'],
                exit_time=candles[-1].time,
                exit_price=exit_price,
                direction=position['direction'],
                pnl=pnl,
                pnl_pct=pnl_pct
            ))
            self.capital += pnl
        
        # Calculate stats
        return self._calculate_stats()
    
    def _calculate_stats(self) -> dict:
        """Calculate performance statistics."""
        if not self.trades:
            return {
                'trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'return_pct': 0,
                'winners': 0,
                'losers': 0
            }
        
        winners = [t for t in self.trades if t.pnl > 0]
        losers = [t for t in self.trades if t.pnl <= 0]
        
        total_pnl = sum(t.pnl for t in self.trades)
        return_pct = ((self.capital - self.initial_capital) / self.initial_capital) * 100
        
        return {
            'trades': len(self.trades),
            'win_rate': (len(winners) / len(self.trades)) * 100,
            'total_pnl': total_pnl,
            'return_pct': return_pct,
            'winners': len(winners),
            'losers': len(losers),
            'avg_win': sum(t.pnl for t in winners) / len(winners) if winners else 0,
            'avg_loss': sum(t.pnl for t in losers) / len(losers) if losers else 0,
        }


class MLHeuristicStrategy:
    """ML Heuristic - simple moving average crossover for now."""
    
    def analyze(self, candles: List[Candle]) -> str:
        if len(candles) < 50:
            return 'HOLD'
        
        # Simple EMA crossover
        closes = [c.close for c in candles]
        ema20 = sum(closes[-20:]) / 20
        ema50 = sum(closes[-50:]) / 50
        
        if ema20 > ema50 and closes[-1] > ema20:
            return 'LONG'
        elif ema20 < ema50 and closes[-1] < ema20:
            return 'SHORT'
        
        return 'HOLD'


class SMCStrategy:
    """Smart Money Concept strategy - simple structure break."""
    
    def analyze(self, candles: List[Candle]) -> str:
        if len(candles) < 20:
            return 'HOLD'
        
        # Find recent highs/lows
        recent = candles[-20:]
        high_20 = max(c.high for c in recent)
        low_20 = min(c.low for c in recent)
        
        current = candles[-1]
        
        # Break of structure
        if current.close > high_20 * 1.001:  # 0.1% buffer
            return 'LONG'
        elif current.close < low_20 * 0.999:
            return 'SHORT'
        
        return 'HOLD'


class ClassicStrategy:
    """Classic RSI + MA strategy."""
    
    def analyze(self, candles: List[Candle]) -> str:
        if len(candles) < 50:
            return 'HOLD'
        
        closes = [c.close for c in candles]
        
        # Simple RSI
        changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [c if c > 0 else 0 for c in changes[-14:]]
        losses = [-c if c < 0 else 0 for c in changes[-14:]]
        
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        
        # MA
        ma50 = sum(closes[-50:]) / 50
        
        if rsi < 30 and closes[-1] > ma50:
            return 'LONG'
        elif rsi > 70 and closes[-1] < ma50:
            return 'SHORT'
        
        return 'HOLD'


def main():
    """Main backtest."""
    print("="*70)
    print("COMPREHENSIVE BACKTEST - All Strategies")
    print("="*70)
    
    # Load data
    data_file = PROJECT_ROOT / 'data' / 'backtest_data.json'
    
    if not data_file.exists():
        print(f"❌ Data file not found: {data_file}")
        return
    
    with open(data_file, 'r') as f:
        data = json.load(f)
    
    candles = [
        Candle(
            time=datetime.fromisoformat(c['time']),
            open=c['open'],
            high=c['high'],
            low=c['low'],
            close=c['close'],
            volume=c['volume']
        )
        for c in data['candles']
    ]
    
    print(f"\n📊 Data: {len(candles)} candles")
    print(f"   From: {candles[0].time.strftime('%Y-%m-%d %H:%M')}")
    print(f"   To: {candles[-1].time.strftime('%Y-%m-%d %H:%M')}")
    print(f"   Period: ~{(candles[-1].time - candles[0].time).days} days")
    
    # Strategies to test
    strategies = [
        ('ML Heuristic (EMA)', MLHeuristicStrategy()),
        ('SMC (Structure Break)', SMCStrategy()),
        ('Classic (RSI+MA)', ClassicStrategy()),
    ]
    
    print(f"\n{'Strategy':<25} {'Trades':<8} {'Win%':<8} {'Return%':<10} {'PnL':<10}")
    print("-" * 70)
    
    results = []
    
    for name, strategy in strategies:
        backtest = SimpleBacktest(initial_capital=10000)
        stats = backtest.run(candles, strategy)
        
        results.append((name, stats))
        
        print(f"{name:<25} {stats['trades']:<8} {stats['win_rate']:<8.1f} "
              f"{stats['return_pct']:<10.2f} ${stats['total_pnl']:<10.2f}")
    
    # Find winner
    print("\n" + "="*70)
    best = max(results, key=lambda x: x[1]['return_pct'])
    print(f"🏆 WINNER: {best[0]}")
    print(f"   Return: {best[1]['return_pct']:.2f}%")
    print(f"   Win Rate: {best[1]['win_rate']:.1f}%")
    print(f"   Trades: {best[1]['trades']}")
    print("="*70)
    
    # Note
    print("\n⚠️  NOTE: This is a simple backtest on 29-day ranging market data.")
    print("   For production deployment, need:")
    print("   - Longer test period (6+ months)")
    print("   - Walk-forward validation")
    print("   - Out-of-sample testing")
    print("   - Different market conditions (trend + range)")


if __name__ == '__main__':
    main()
