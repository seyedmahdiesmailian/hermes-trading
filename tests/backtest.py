#!/usr/bin/env python3
"""Backtest Framework - Validate strategies on historical data.

Usage:
    python -m tests.backtest --symbol XAUUSD --from 2026-01-01 --to 2026-10-01
"""
import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from brain.domain.entities.market import MarketState, Candle
from brain.domain.services.market_analyzer import MarketAnalyzer
from brain.domain.services.decision_engine import DecisionEngine, Decision
from brain.domain.services.risk_manager import RiskManager
from brain.domain.value_objects.risk import RiskParameters
from analysis.technical.smc_strategy import SMCStrategy
from analysis.technical.classic_strategy import ClassicStrategy


@dataclass
class BacktestResult:
    """Backtest results."""
    symbol: str
    start_date: str
    end_date: str
    initial_balance: float
    final_balance: float
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    profit: float
    profit_pct: float
    max_drawdown: float
    sharpe_ratio: float
    trades: list


class Backtester:
    """Backtest engine."""
    
    def __init__(self, initial_balance: float = 10000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.equity = initial_balance
        self.trades = []
        
        # Initialize components
        strategies = [
            (SMCStrategy(), 1.0),
            (ClassicStrategy(), 0.8)
        ]
        self.analyzer = MarketAnalyzer(strategies)
        self.decision_engine = DecisionEngine()
        
        risk_params = RiskParameters(
            max_risk_per_trade_pct=2.0,
            min_risk_reward=2.0,
            max_daily_loss_pct=5.0,
            max_daily_trades=5,
            max_open_positions=1,
            max_position_size=10.0,
            sl_range=(10, 100)
        )
        self.risk_manager = RiskManager(risk_params)
    
    def run(self, symbol: str, candles: list[Candle]) -> BacktestResult:
        """Run backtest on historical data.
        
        Args:
            symbol: Trading symbol
            candles: Historical candle data
        
        Returns:
            BacktestResult with metrics
        """
        print(f"Running backtest on {len(candles)} candles...")
        
        open_position = None
        daily_trades = 0
        last_date = None
        peak_equity = self.initial_balance
        max_dd = 0.0
        
        for i in range(200, len(candles)):  # Need 200 bars for analysis
            candle = candles[i]
            
            # Reset daily counter
            if last_date and candle.time.date() != last_date:
                daily_trades = 0
            last_date = candle.time.date()
            
            # Check existing position
            if open_position:
                # Check exit conditions
                if self._check_exit(open_position, candle):
                    self._close_position(open_position, candle)
                    open_position = None
                continue
            
            # Check if we can open new position
            if daily_trades >= 5:
                continue
            
            # Analyze market
            try:
                market = self._build_market_state(symbol, candles[:i+1])
                analysis = self.analyzer.analyze(market)
                
                # Decision
                decision = self.decision_engine.evaluate_entry(
                    analysis=analysis,
                    account=self._get_account_state(),
                    market=market
                )
                
                # Execute if approved
                if decision.should_execute():
                    params = decision.action_params
                    if params:
                        open_position = self._open_position(
                            symbol=symbol,
                            direction=params.get('direction', 'BUY'),
                            entry=candle.close,
                            sl=params.get('sl', candle.close - 20),
                            tp=params.get('tp', candle.close + 40),
                            time=candle.time
                        )
                        daily_trades += 1
            
            except Exception as e:
                print(f"Error at candle {i}: {e}")
                continue
            
            # Track drawdown
            if self.equity > peak_equity:
                peak_equity = self.equity
            dd = (peak_equity - self.equity) / peak_equity * 100
            if dd > max_dd:
                max_dd = dd
        
        # Calculate metrics
        wins = len([t for t in self.trades if t['profit'] > 0])
        losses = len([t for t in self.trades if t['profit'] < 0])
        win_rate = (wins / len(self.trades) * 100) if self.trades else 0
        profit = self.balance - self.initial_balance
        profit_pct = (profit / self.initial_balance * 100)
        
        # Sharpe ratio (simplified)
        if self.trades:
            returns = [t['profit'] / self.initial_balance for t in self.trades]
            avg_return = sum(returns) / len(returns)
            std_return = (sum((r - avg_return)**2 for r in returns) / len(returns))**0.5
            sharpe = (avg_return / std_return * (252**0.5)) if std_return > 0 else 0
        else:
            sharpe = 0
        
        return BacktestResult(
            symbol=symbol,
            start_date=candles[0].time.isoformat(),
            end_date=candles[-1].time.isoformat(),
            initial_balance=self.initial_balance,
            final_balance=self.balance,
            total_trades=len(self.trades),
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            profit=profit,
            profit_pct=profit_pct,
            max_drawdown=max_dd,
            sharpe_ratio=sharpe,
            trades=self.trades
        )
    
    def _build_market_state(self, symbol: str, candles: list[Candle]) -> MarketState:
        """Build market state from candles."""
        from brain.domain.value_objects.price import Price
        from brain.domain.entities.market import Trend
        
        last = candles[-1]
        
        # Simple ATR calculation
        atr = sum(c.high - c.low for c in candles[-14:]) / 14
        
        return MarketState(
            symbol=symbol,
            timeframe="M15",
            current_price=Price(bid=last.close, ask=last.close),
            trend=Trend.NEUTRAL,
            atr=atr,
            timestamp=last.time,
            candles=candles
        )
    
    def _get_account_state(self):
        """Get current account state."""
        from brain.domain.entities.account import AccountState
        
        return AccountState(
            balance=self.balance,
            equity=self.equity,
            margin=0.0,
            free_margin=self.equity,
            margin_level=0.0,
            profit=0.0,
            open_positions=0,
            open_positions_volume=0.0
        )
    
    def _open_position(self, symbol, direction, entry, sl, tp, time):
        """Open a position."""
        return {
            'symbol': symbol,
            'direction': direction,
            'entry': entry,
            'sl': sl,
            'tp': tp,
            'open_time': time,
            'size': 0.1  # Fixed for now
        }
    
    def _check_exit(self, position, candle):
        """Check if position should be closed."""
        if position['direction'] == 'BUY':
            if candle.low <= position['sl']:
                return True
            if candle.high >= position['tp']:
                return True
        else:
            if candle.high >= position['sl']:
                return True
            if candle.low <= position['tp']:
                return True
        return False
    
    def _close_position(self, position, candle):
        """Close a position."""
        exit_price = position['tp'] if abs(candle.close - position['tp']) < abs(candle.close - position['sl']) else position['sl']
        
        if position['direction'] == 'BUY':
            profit = (exit_price - position['entry']) * position['size'] * 100  # Simplified
        else:
            profit = (position['entry'] - exit_price) * position['size'] * 100
        
        self.balance += profit
        self.equity = self.balance
        
        trade = {
            **position,
            'exit': exit_price,
            'close_time': candle.time.isoformat(),
            'profit': profit
        }
        self.trades.append(trade)
        print(f"Trade closed: {profit:.2f}")


if __name__ == "__main__":
    # Example: Load candles and run backtest
    print("Backtest framework ready!")
    print("Load historical data and call: backtester.run(symbol, candles)")
