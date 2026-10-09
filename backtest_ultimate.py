#!/usr/bin/env python3
"""Backtest Ultimate System."""
import json
import sys
from datetime import datetime

sys.path.insert(0, '/home/ai/hermes-trading')

from ultimate_trader import UltimateTrader, Candle

print("🎯 ULTIMATE SYSTEM BACKTEST")
print("="*70)
print("Maximum Profitability Configuration")
print()

with open('data/backtest_data.json') as f:
    data = json.load(f)

candles = [Candle(
    time=datetime.fromisoformat(c['time']),
    open=c['open'],
    high=c['high'],
    low=c['low'],
    close=c['close'],
    volume=c['volume']
) for c in data['candles']]

print(f"📊 Data: {len(candles)} candles")
print(f"   Period: {candles[0].time.strftime('%Y-%m-%d')} → {candles[-1].time.strftime('%Y-%m-%d')}")
print()

trader = UltimateTrader()
balance = 10000.0
trades = []
open_trade = None

print(f"💰 Starting: ${balance:,.2f}")
print(f"⚙️  Base Risk: {trader.base_risk*100:.1f}%")
print(f"🎯 Min Win Prob: {trader.min_win_prob*100:.0f}%")
print(f"📈 Min Confidence: {trader.min_confidence:.0f}%")
print(f"✨ Min Quality: {trader.min_quality:.0f}%")
print()
print("🔄 Running...\n")

for i in range(250, len(candles), 5):
    current_candles = candles[:i+1]
    current_price = current_candles[-1].close
    
    # Check exit
    if open_trade:
        setup = open_trade
        hit_tp = (setup.action == 'buy' and current_price >= setup.take_profit) or \
                 (setup.action == 'sell' and current_price <= setup.take_profit)
        hit_sl = (setup.action == 'buy' and current_price <= setup.stop_loss) or \
                 (setup.action == 'sell' and current_price >= setup.stop_loss)
        
        if hit_tp or hit_sl:
            exit_price = setup.take_profit if hit_tp else setup.stop_loss
            
            if setup.action == 'buy':
                pnl = (exit_price - setup.entry) * setup.size * 100
            else:
                pnl = (setup.entry - exit_price) * setup.size * 100
            
            balance += pnl
            won = hit_tp
            trades.append({'pnl': pnl, 'result': 'WIN' if won else 'LOSS', 'setup': setup})
            
            # Update performance
            trader.update_performance(
                regime=setup.regime.value,
                session=setup.session.value,
                strategy=setup.strategy,
                won=won,
                pnl=pnl
            )
            
            emoji = '✅' if won else '❌'
            print(f"{emoji} #{len(trades)}: {setup.action.upper()} ${pnl:+,.2f} → ${balance:,.2f}")
            print(f"   {setup.regime.value} | {setup.session.value} | Q:{setup.quality_score:.0f}")
            
            if len(trades) % 10 == 0:
                wr = sum(1 for t in trades if t['result'] == 'WIN') / len(trades) * 100
                print(f"\n📊 Stats: {len(trades)} trades | {wr:.1f}% WR | ${balance:,.2f}\n")
            
            open_trade = None
            continue
    
    # Look for new trade
    if not open_trade:
        setup = trader.analyze_and_decide(current_candles, balance)
        
        if setup:
            open_trade = setup
            print(f"\n🎯 SIGNAL: {setup.action.upper()}")
            print(f"   Entry: {setup.entry:.1f} | SL: {setup.stop_loss:.1f} | TP: {setup.take_profit:.1f}")
            print(f"   Win Prob: {setup.win_probability*100:.0f}% | Confidence: {setup.confidence:.0f}%")
            print(f"   Quality: {setup.quality_score:.0f} | EV: {setup.expected_value:.2f}")
            print(f"   Size: {setup.size} lots | Session: {setup.session.value}")
            for reason in setup.reasons:
                print(f"     • {reason}")
            print()

print("\n" + "="*70)
print("📊 FINAL RESULTS\n")

if trades:
    wins = [t for t in trades if t['result'] == 'WIN']
    total_pnl = sum(t['pnl'] for t in trades)
    win_rate = len(wins) / len(trades) * 100
    
    print(f"Trades: {len(trades)}")
    print(f"Wins: {len(wins)} | Losses: {len(trades) - len(wins)}")
    print(f"Win Rate: {win_rate:.1f}%")
    print()
    print(f"Total P&L: ${total_pnl:+,.2f}")
    print(f"Final Balance: ${balance:,.2f}")
    print(f"Return: {(balance/10000-1)*100:+.2f}%")
    print()
    
    if wins:
        avg_win = sum(t['pnl'] for t in wins) / len(wins)
        print(f"Avg Win: ${avg_win:.2f}")
    
    if len(trades) > len(wins):
        losses = [t for t in trades if t['result'] == 'LOSS']
        avg_loss = sum(t['pnl'] for t in losses) / len(losses)
        print(f"Avg Loss: ${avg_loss:.2f}")
        
        if avg_loss != 0:
            pf = abs(sum(t['pnl'] for t in wins) / sum(t['pnl'] for t in losses))
            print(f"Profit Factor: {pf:.2f}")
    
    # Performance breakdown
    print("\n📊 Performance by Regime:")
    for regime, stats in trader.performance.regime_stats.items():
        wr = stats['wins'] / stats['trades'] * 100 if stats['trades'] > 0 else 0
        print(f"  {regime}: {stats['trades']} trades | {wr:.1f}% WR | ${stats['pnl']:+,.2f}")
    
    print("\n📊 Performance by Session:")
    for session, stats in trader.performance.session_stats.items():
        wr = stats['wins'] / stats['trades'] * 100 if stats['trades'] > 0 else 0
        print(f"  {session}: {stats['trades']} trades | {wr:.1f}% WR | ${stats['pnl']:+,.2f}")
    
    print("\n🎯 Auto-tuned Parameters:")
    print(f"  Risk Multiplier: {trader.risk_multiplier:.2f}x")
    print(f"  Min Confidence: {trader.min_confidence:.1f}%")
    print(f"  Min Win Prob: {trader.min_win_prob*100:.1f}%")

else:
    print("⚠️  No trades executed")
    print("Filters too strict for this market")

print()
