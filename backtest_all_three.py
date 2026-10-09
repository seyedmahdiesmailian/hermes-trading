#!/usr/bin/env python3
"""Backtest all three approaches."""
import json
import sys
from datetime import datetime

sys.path.insert(0, '/home/ai/hermes-trading')

from improved_trader_v2 import ImprovedTrader, Candle as C1
from ml_trader import MLTrader, Candle as C2
from ensemble_trader import EnsembleTrader, Candle as C3

print("🎯 COMPREHENSIVE BACKTEST - 3 Approaches")
print("="*70)
print()

# Load data
with open('data/backtest_data.json') as f:
    data = json.load(f)

print(f"📊 Data: {len(data['candles'])} candles")
print(f"   Symbol: {data['symbol']} {data['timeframe']}")
print()

# Test each approach
approaches = [
    ('Improved Professional', ImprovedTrader(), C1),
    ('Machine Learning', MLTrader(), C2),
    ('Ensemble (Multi-Strategy)', EnsembleTrader(), C3)
]

results = {}

for name, trader, CandleClass in approaches:
    print(f"\n{'='*70}")
    print(f"🔬 Testing: {name}")
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
                trades.append({'pnl': pnl, 'result': 'WIN' if hit_tp else 'LOSS'})
                
                print(f"{'✅' if hit_tp else '❌'} Trade #{len(trades)}: ${pnl:+,.2f} → Balance: ${balance:,.2f}")
                
                open_trade = None
                continue
        
        # Look for new trade
        if not open_trade:
            signal = trader.analyze_and_decide(current_candles, balance) if name != 'Machine Learning' \
                     else trader.analyze_and_predict(current_candles, balance)
            
            if signal and hasattr(signal, 'action') and signal.action in ['buy', 'sell']:
                open_trade = {
                    'action': signal.action,
                    'entry': signal.entry,
                    'sl': signal.stop_loss,
                    'tp': signal.take_profit,
                    'size': signal.size
                }
    
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
        print(f"   P&L: ${total_pnl:+,.2f}")
        print(f"   Final: ${balance:,.2f} ({(balance/10000-1)*100:+.2f}%)")
    else:
        results[name] = None
        print("\n⚠️  No trades")

# Summary
print("\n\n" + "="*70)
print("📊 FINAL COMPARISON")
print("="*70)
print()

for name, result in results.items():
    if result:
        print(f"\n{name}:")
        print(f"  Return: {result['return_pct']:+.2f}%")
        print(f"  Win Rate: {result['win_rate']:.1f}%")
        print(f"  Trades: {result['trades']}")
    else:
        print(f"\n{name}: No trades")

print()
print("="*70)

# Find best
if any(results.values()):
    valid_results = {k: v for k, v in results.items() if v}
    best = max(valid_results.items(), key=lambda x: x[1]['return_pct'])
    print(f"\n🏆 WINNER: {best[0]}")
    print(f"   Return: {best[1]['return_pct']:+.2f}%")
    print(f"   Win Rate: {best[1]['win_rate']:.1f}%")
else:
    print("\n⚠️  No approach generated trades!")

print()
