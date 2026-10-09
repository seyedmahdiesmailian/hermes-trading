#!/usr/bin/env python3
"""Backtest the Professional Trading Brain."""
import json
import sys
from datetime import datetime

sys.path.insert(0, '/home/ai/hermes-trading')

from pro_trader_brain import ProfessionalTrader, Candle

print("🎯 PROFESSIONAL TRADER BACKTEST")
print("="*70)
print()

# Load data
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

print(f"📊 Data: {len(candles)} candles ({data['symbol']} {data['timeframe']})")
print(f"   Period: {candles[0].time.strftime('%Y-%m-%d')} → {candles[-1].time.strftime('%Y-%m-%d')}")
print(f"   Days: {(candles[-1].time - candles[0].time).days}")
print()

# Initialize trader
trader = ProfessionalTrader()
balance = 10000.0
trades = []
open_trade = None

print(f"💰 Starting Balance: ${balance:,.2f}")
print(f"⚙️  Risk per trade: {trader.max_risk_per_trade*100}%")
print(f"🎯 Min confidence: {trader.min_confidence}%")
print(f"📈 Min R:R: {trader.min_risk_reward}:1")
print()
print("🔄 Running backtest...\n")

# Run backtest
for i in range(250, len(candles), 5):  # Every 5 candles = ~1 hour
    current_candles = candles[:i+1]
    current_price = current_candles[-1].close
    
    # Check exit
    if open_trade:
        decision = open_trade
        hit_tp = (decision.action == 'buy' and current_price >= decision.take_profit) or \
                 (decision.action == 'sell' and current_price <= decision.take_profit)
        hit_sl = (decision.action == 'buy' and current_price <= decision.stop_loss) or \
                 (decision.action == 'sell' and current_price >= decision.stop_loss)
        
        if hit_tp or hit_sl:
            exit_price = decision.take_profit if hit_tp else decision.stop_loss
            
            if decision.action == 'buy':
                pnl = (exit_price - decision.entry) * decision.size * 100  # $100 per lot per point
            else:
                pnl = (decision.entry - exit_price) * decision.size * 100
            
            balance += pnl
            trades.append({
                'entry_time': decision.reasoning[0] if decision.reasoning else '',
                'exit_time': current_candles[-1].time.isoformat(),
                'type': decision.action,
                'entry': decision.entry,
                'exit': exit_price,
                'pnl': pnl,
                'result': 'WIN' if hit_tp else 'LOSS',
                'setup': decision.setup_type.value,
                'regime': decision.market_regime.value
            })
            
            result_emoji = '✅' if hit_tp else '❌'
            print(f"{result_emoji} Trade #{len(trades)}: {decision.action.upper()} {decision.setup_type.value}")
            print(f"   Entry: {decision.entry:.1f} → Exit: {exit_price:.1f}")
            print(f"   P&L: ${pnl:+,.2f} | Balance: ${balance:,.2f}")
            print(f"   Regime: {decision.market_regime.value}")
            print()
            
            open_trade = None
            continue
    
    # Look for new trade
    if not open_trade:
        decision = trader.analyze_and_decide(current_candles, balance)
        
        if decision.action in ['buy', 'sell']:
            open_trade = decision
            
            print(f"🎯 NEW TRADE: {decision.action.upper()}")
            print(f"   Time: {current_candles[-1].time.strftime('%Y-%m-%d %H:%M')}")
            print(f"   Setup: {decision.setup_type.value}")
            print(f"   Regime: {decision.market_regime.value}")
            print(f"   Confidence: {decision.confidence:.0f}%")
            print(f"   Win Prob: {decision.win_probability*100:.0f}%")
            print(f"   Entry: {decision.entry:.1f}")
            print(f"   SL: {decision.stop_loss:.1f} | TP: {decision.take_profit:.1f}")
            print(f"   R:R: {decision.risk_reward:.1f}:1")
            print(f"   Size: {decision.size} lots")
            print(f"   Reasoning:")
            for reason in decision.reasoning:
                print(f"     • {reason}")
            print()

print("\n" + "="*70)
print("📊 BACKTEST RESULTS\n")

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
            profit_factor = abs(sum(t['pnl'] for t in wins) / sum(t['pnl'] for t in losses))
            print(f"Profit Factor: {profit_factor:.2f}")
    
    print()
    print("Trades by Setup:")
    setups = {}
    for t in trades:
        setup = t['setup']
        if setup not in setups:
            setups[setup] = {'count': 0, 'wins': 0}
        setups[setup]['count'] += 1
        if t['result'] == 'WIN':
            setups[setup]['wins'] += 1
    
    for setup, stats in setups.items():
        wr = stats['wins'] / stats['count'] * 100
        print(f"  {setup}: {stats['count']} trades, {wr:.0f}% win rate")

else:
    print("⚠️  No trades executed")
    print("\nThis means:")
    print("  • Professional trader found no high-quality setups")
    print("  • This is GOOD risk management")
    print("  • Better to wait than force trades")

print()
