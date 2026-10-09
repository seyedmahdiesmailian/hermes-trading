#!/usr/bin/env python3
"""FINAL COMPREHENSIVE BACKTEST - All 4 systems."""
import json
import sys
from datetime import datetime

sys.path.insert(0, '/home/ai/hermes-trading')

from adaptive_trader import AdaptiveTrader, Candle as C1
from improved_trader_v2 import ImprovedTrader, Candle as C2
from ml_trader import MLTrader, Candle as C3
from ml_trader_trained import MLTraderTrained, Candle as C4

print("🎯 FINAL COMPREHENSIVE BACKTEST")
print("="*70)
print("Testing 4 Advanced Systems:")
print("  1. Adaptive Trader (V1 + V2 hybrid)")
print("  2. Improved Professional")
print("  3. ML Trader (heuristic)")
print("  4. ML Trader with Training")
print()

# Load data
with open('data/backtest_data.json') as f:
    data = json.load(f)

print(f"📊 Data: {len(data['candles'])} candles")
print(f"   Period: {data['candles'][0]['time'][:10]} → {data['candles'][-1]['time'][:10]}")
print()

# Test approaches
approaches = [
    ('Adaptive (Best of V1+V2)', AdaptiveTrader(), C1),
    ('Improved Professional V2', ImprovedTrader(), C2),
    ('ML Heuristic', MLTrader(), C3),
    ('ML Trained', MLTraderTrained(), C4)
]

results = {}

for name, trader, CandleClass in approaches:
    print(f"\n{'='*70}")
    print(f"🧪 Testing: {name}")
    print("="*70)
    print()
    
    candles = [CandleClass(
        time=datetime.fromisoformat(c['time']),
        open=c['open'],
        high=c['high'],
        low=c['low'],
        close=c['close'],
        volume=c['volume']
    ) for c in data['candles']]
    
    balance = 10000.0
    trades = []
    open_trade = None
    
    for i in range(250, len(candles), 5):
        current_candles = candles[:i+1]
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
                trades.append({'pnl': pnl, 'result': 'WIN' if won else 'LOSS'})
                
                # Train ML if applicable
                if name == 'ML Trained':
                    entry_candles = candles[:decision['entry_index']]
                    trader.add_training_sample(entry_candles, decision['action'], won)
                    
                    # Train every 10 trades
                    if len(trades) % 10 == 0:
                        trader.train(epochs=5)
                
                # Update adaptive performance
                if name.startswith('Adaptive'):
                    trader.performance.update(decision.get('regime'), won, pnl)
                
                print(f"{'✅' if won else '❌'} #{len(trades)}: ${pnl:+,.2f} → ${balance:,.2f}")
                
                open_trade = None
                continue
        
        # Look for new trade
        if not open_trade:
            signal = None
            
            if name == 'ML Trained':
                prediction = trader.predict(current_candles)
                if prediction:
                    action, win_prob = prediction
                    atr = trader._atr(current_candles[-20:], 14)
                    entry = current_price
                    
                    if action == 'buy':
                        sl = entry - atr * 1.2
                        tp = entry + atr * 3.0
                    else:
                        sl = entry + atr * 1.2
                        tp = entry - atr * 3.0
                    
                    signal = type('obj', (object,), {
                        'action': action,
                        'entry': entry,
                        'stop_loss': sl,
                        'take_profit': tp,
                        'size': 0.1
                    })
            else:
                signal = trader.analyze_and_decide(current_candles, balance) if hasattr(trader, 'analyze_and_decide') \
                         else trader.analyze_and_predict(current_candles, balance)
            
            if signal and hasattr(signal, 'action') and signal.action in ['buy', 'sell']:
                open_trade = {
                    'action': signal.action,
                    'entry': signal.entry if hasattr(signal, 'entry') else current_price,
                    'sl': signal.stop_loss,
                    'tp': signal.take_profit,
                    'size': signal.size,
                    'entry_index': i
                }
                if hasattr(signal, 'regime'):
                    open_trade['regime'] = signal.regime
    
    # Store results
    if trades:
        wins = [t for t in trades if t['result'] == 'WIN']
        total_pnl = sum(t['pnl'] for t in trades)
        win_rate = len(wins) / len(trades) * 100
        
        results[name] = {
            'trades': len(trades),
            'wins': len(wins),
            'losses': len(trades) - len(wins),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'final_balance': balance,
            'return_pct': (balance / 10000 - 1) * 100
        }
        
        print(f"\n📊 Results:")
        print(f"   Trades: {len(trades)} | Win Rate: {win_rate:.1f}%")
        print(f"   Total P&L: ${total_pnl:+,.2f}")
        print(f"   Final Balance: ${balance:,.2f}")
        print(f"   Return: {(balance/10000-1)*100:+.2f}%")
    else:
        results[name] = None
        print("\n⚠️  No trades executed")

# Final comparison
print("\n\n" + "="*70)
print("🏆 FINAL RANKING")
print("="*70)
print()

valid_results = {k: v for k, v in results.items() if v}
if valid_results:
    sorted_results = sorted(valid_results.items(), key=lambda x: x[1]['return_pct'], reverse=True)
    
    for rank, (name, result) in enumerate(sorted_results, 1):
        emoji = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else "📊"
        print(f"{emoji} #{rank}: {name}")
        print(f"     Return: {result['return_pct']:+.2f}% | Win Rate: {result['win_rate']:.1f}% | Trades: {result['trades']}")
        print()
    
    best_name, best_result = sorted_results[0]
    print(f"🎯 WINNER: {best_name}")
    print(f"   📈 Return: {best_result['return_pct']:+.2f}%")
    print(f"   ✅ Win Rate: {best_result['win_rate']:.1f}%")
    print(f"   💼 Trades: {best_result['trades']}")
    print(f"   💰 Final: ${best_result['final_balance']:,.2f}")
else:
    print("⚠️  No system generated trades!")

print()
