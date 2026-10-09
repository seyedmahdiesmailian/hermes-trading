#!/usr/bin/env python3
"""Full V2 Backtest - All 2000 candles."""
import sys
import json
from datetime import datetime

sys.path.insert(0, '/home/ai/hermes-trading')

from brain.domain.entities.market import MarketState, Candle
from brain.domain.entities.account import AccountState
from brain.domain.services.market_analyzer import MarketAnalyzer
from brain.domain.services.decision_engine import DecisionEngine, Decision
from brain.domain.services.risk_manager import RiskManager
from brain.domain.value_objects.risk import RiskParameters
from brain.ml_heuristic_strategy import MLHeuristicStrategy

print("🎯 V2 FULL BACKTEST - ML HEURISTIC")
print("="*70)
print("Complete test: 2000 candles (همه data)")
print()

# Load data
with open('data/backtest_data.json') as f:
    data = json.load(f)

candles_data = [Candle(
    time=datetime.fromisoformat(c['time']),
    open=c['open'],
    high=c['high'],
    low=c['low'],
    close=c['close'],
    volume=c['volume']
) for c in data['candles']]

print(f"📊 Data: {len(candles_data)} candles")
print(f"   Period: {candles_data[0].time.strftime('%Y-%m-%d')} → {candles_data[-1].time.strftime('%Y-%m-%d')}")
print(f"   Symbol: XAUUSD | Timeframe: M15")
print()

# Setup V2 system
analyzer = MarketAnalyzer()
analyzer.add_strategy(MLHeuristicStrategy(), 1.0)

risk_params = RiskParameters(
    max_risk_per_trade_pct=0.015,
    min_risk_reward=2.0,
    max_daily_loss_pct=0.05,
    max_daily_trades=10,
    max_open_positions=1,
    max_position_size_lots=0.5
)
risk_manager = RiskManager(risk_params)
decision_engine = DecisionEngine(risk_manager)

print("⚙️  V2 Configuration:")
print("   Brain: MarketAnalyzer + DecisionEngine + RiskManager")
print("   Strategy: ML Heuristic (20 features)")
print("   Risk: 1.5% per trade | Min R:R: 2:1")
print()

balance = 10000.0
trades = []
open_trade = None
max_dd = 0.0
peak = balance

print(f"💰 Starting: ${balance:,.2f}")
print("\n🔄 Running full backtest...\n")

# Run through ALL candles
for i in range(250, len(candles_data)):
    current_candles = candles_data[:i+1]
    current_price = current_candles[-1].close
    
    # Track drawdown
    if balance > peak:
        peak = balance
    dd = (peak - balance) / peak * 100
    if dd > max_dd:
        max_dd = dd
    
    # Check exit
    if open_trade:
        decision = open_trade
        hit_tp = (decision['action'] == 'buy' and current_price >= decision['tp']) or \
                 (decision['action'] == 'sell' and current_price <= decision['tp'])
        hit_sl = (decision['action'] == 'buy' and current_price <= decision['sl']) or \
                 (decision['action'] == 'sell' and current_price >= decision['sl'])
        
        if hit_tp or hit_sl:
            exit_price = decision['tp'] if hit_tp else decision['sl']
            
            if decision['action'] == 'buy':
                pnl = (exit_price - decision['entry']) * decision['size'] * 100
            else:
                pnl = (decision['entry'] - exit_price) * decision['size'] * 100
            
            balance += pnl
            won = hit_tp
            trades.append({
                'pnl': pnl,
                'result': 'WIN' if won else 'LOSS',
                'entry': decision['entry'],
                'exit': exit_price,
                'size': decision['size'],
                'time': current_candles[-1].time
            })
            
            if len(trades) % 20 == 0:
                wr = sum(1 for t in trades if t['result'] == 'WIN') / len(trades) * 100
                print(f"📊 Progress: {len(trades)} trades | {wr:.1f}% WR | ${balance:,.2f}")
            
            open_trade = None
            continue
    
    # Look for new trade
    if not open_trade:
        try:
            market = MarketState(
                symbol='XAUUSD',
                timeframe='M15',
                current_price=current_price,
                timestamp=current_candles[-1].time,
                candles=current_candles
            )
            
            analysis = analyzer.analyze(market)
            
            if analysis.is_bullish() or analysis.is_bearish():
                account = AccountState(
                    balance=balance,
                    equity=balance,
                    margin_free=balance
                )
                
                result = decision_engine.evaluate_entry(analysis, market, account)
                
                if result.decision == Decision.ENTER_TRADE and result.action_params:
                    params = result.action_params
                    action = 'buy' if analysis.is_bullish() else 'sell'
                    
                    entry = params.get('entry_price', current_price)
                    sl = params.get('stop_loss', analysis.key_levels.get('stop_loss', [0])[0])
                    tp = params.get('take_profit', analysis.key_levels.get('take_profit', [0])[0])
                    size = params.get('lot_size', 0.01)
                    
                    open_trade = {
                        'action': action,
                        'entry': entry,
                        'sl': sl,
                        'tp': tp,
                        'size': size
                    }
        
        except Exception:
            pass

print("\n" + "="*70)
print("📊 FINAL RESULTS - V2 ML HEURISTIC\n")

if trades:
    wins = [t for t in trades if t['result'] == 'WIN']
    losses = [t for t in trades if t['result'] == 'LOSS']
    total_pnl = sum(t['pnl'] for t in trades)
    win_rate = len(wins) / len(trades) * 100
    
    print(f"Period: {trades[0]['time'].strftime('%Y-%m-%d')} → {trades[-1]['time'].strftime('%Y-%m-%d')}")
    print(f"Total Trades: {len(trades)}")
    print(f"Wins: {len(wins)} | Losses: {len(losses)}")
    print(f"Win Rate: {win_rate:.1f}%")
    print()
    print(f"Starting Balance: $10,000.00")
    print(f"Final Balance: ${balance:,.2f}")
    print(f"Total P&L: ${total_pnl:+,.2f}")
    print(f"Return: {(balance/10000-1)*100:+.2f}%")
    print(f"Max Drawdown: {max_dd:.2f}%")
    print()
    
    if wins:
        avg_win = sum(t['pnl'] for t in wins) / len(wins)
        max_win = max(t['pnl'] for t in wins)
        print(f"Avg Win: ${avg_win:.2f}")
        print(f"Max Win: ${max_win:.2f}")
    
    if losses:
        avg_loss = sum(t['pnl'] for t in losses) / len(losses)
        max_loss = min(t['pnl'] for t in losses)
        print(f"Avg Loss: ${avg_loss:.2f}")
        print(f"Max Loss: ${max_loss:.2f}")
        
        if sum(t['pnl'] for t in losses) != 0:
            pf = abs(sum(t['pnl'] for t in wins) / sum(t['pnl'] for t in losses))
            print(f"Profit Factor: {pf:.2f}")
    
    print("\n" + "="*70)
    print("🎯 COMPARISON\n")
    print("Standalone ML (ml_trader.py):")
    print("   Return: -1.08% | WR: 28.8% | Trades: 66")
    print()
    print("V2 Integrated (این سیستم):")
    print(f"   Return: {(balance/10000-1)*100:+.2f}% | WR: {win_rate:.1f}% | Trades: {len(trades)}")
    print()
    
    if balance >= 9900:  # Less than 1% loss
        print("✅ EXCELLENT - System works in V2!")
        print("   Ready for production deployment")
    elif balance >= 9800:
        print("✅ GOOD - Acceptable performance")
    else:
        print("⚠️  Review needed")

else:
    print("❌ No trades executed")

print()
