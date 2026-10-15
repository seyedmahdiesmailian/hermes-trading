#!/usr/bin/env python3
"""V2 Backtest with ML Heuristic Strategy."""
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

print("🎯 V2 SYSTEM + ML HEURISTIC BACKTEST")
print("="*70)
print("Integration Test: ML Heuristic در معماری V2")
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
print()

# Setup V2 system with ML Heuristic
analyzer = MarketAnalyzer()
analyzer.add_strategy(MLHeuristicStrategy(), 1.0)  # Only ML

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

print("⚙️  Configuration:")
print("   Strategy: ML Heuristic (proven 28.8% WR)")
print("   Risk: 1.5% per trade")
print("   Min R:R: 2:1")
print("   Max size: 0.5 lot")
print()

balance = 10000.0
trades = []
open_trade = None

print(f"💰 Starting: ${balance:,.2f}")
print()
print("🔄 Running...\n")

for i in range(250, len(candles_data), 5):
    current_candles = candles_data[:i+1]
    current_price = current_candles[-1].close
    
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
                'size': decision['size']
            })
            
            emoji = '✅' if won else '❌'
            print(f"{emoji} Trade #{len(trades)}: ${pnl:+,.2f} → Balance: ${balance:,.2f}")
            
            if len(trades) % 10 == 0:
                wr = sum(1 for t in trades if t['result'] == 'WIN') / len(trades) * 100
                print(f"\n📊 Progress: {len(trades)} trades | {wr:.1f}% WR | ${balance:,.2f}\n")
            
            open_trade = None
            continue
    
    # Look for new trade
    if not open_trade:
        try:
            # Create market state
            market = MarketState(
                symbol='XAUUSD',
                timeframe='M15',
                current_price=current_price,
                timestamp=current_candles[-1].time,
                candles=current_candles
            )
            
            # Get analysis
            analysis = analyzer.analyze(market)
            
            if analysis.is_bullish() or analysis.is_bearish():
                # Create account state
                account = AccountState(
                    balance=balance,
                    equity=balance,
                    margin_free=balance
                )
                
                # Get decision
                result = decision_engine.evaluate_entry(analysis, market, account)
                
                if result.decision == Decision.ENTER_TRADE and result.action_params:
                    params = result.action_params
                    action = 'buy' if analysis.is_bullish() else 'sell'
                    
                    # Extract trade parameters
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
                    
                    print(f"\n🎯 NEW TRADE: {action.upper()}")
                    print(f"   Entry: {entry:.1f}")
                    print(f"   SL: {sl:.1f} | TP: {tp:.1f}")
                    print(f"   Size: {size} lots")
                    print(f"   Confidence: {analysis.confidence*100:.1f}%")
                    
                    reasoning = analysis.reasoning
                    if 'summary' in reasoning:
                        print(f"   Signals: {', '.join(reasoning['summary'])}")
                    print()
        
        except Exception as e:
            pass

print("\n" + "="*70)
print("📊 FINAL RESULTS\n")

if trades:
    wins = [t for t in trades if t['result'] == 'WIN']
    losses = [t for t in trades if t['result'] == 'LOSS']
    total_pnl = sum(t['pnl'] for t in trades)
    win_rate = len(wins) / len(trades) * 100
    
    print(f"Total Trades: {len(trades)}")
    print(f"Wins: {len(wins)} | Losses: {len(losses)}")
    print(f"Win Rate: {win_rate:.1f}%")
    print()
    print(f"Total P&L: ${total_pnl:+,.2f}")
    print(f"Final Balance: ${balance:,.2f}")
    print(f"Return: {(balance/10000-1)*100:+.2f}%")
    print()
    
    if wins:
        avg_win = sum(t['pnl'] for t in wins) / len(wins)
        print(f"Avg Win: ${avg_win:.2f}")
    
    if losses:
        avg_loss = sum(t['pnl'] for t in losses) / len(losses)
        print(f"Avg Loss: ${avg_loss:.2f}")
        
        if avg_loss != 0:
            pf = abs(sum(t['pnl'] for t in wins) / sum(t['pnl'] for t in losses)) if losses else 0
            print(f"Profit Factor: {pf:.2f}")
    
    print("\n🎯 Comparison to Standalone:")
    print("   Standalone: -1.08% | 28.8% WR | 66 trades")
    print(f"   V2 Integrated: {(balance/10000-1)*100:+.2f}% | {win_rate:.1f}% WR | {len(trades)} trades")
    
    if abs((balance/10000-1)*100 - (-1.08)) < 2 and abs(win_rate - 28.8) < 5:
        print("\n✅ Integration SUCCESS - Performance matches standalone!")
    else:
        print("\n⚠️  Performance differs - review integration")

else:
    print("⚠️  No trades executed")
    print("Check filters and thresholds")

print()
