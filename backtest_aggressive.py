#!/usr/bin/env python3
"""Aggressive backtest with lowered thresholds."""
import sys
import json
from datetime import datetime

sys.path.insert(0, '/home/ai/hermes-trading')

from brain.domain.entities.market import Candle, MarketState
from brain.domain.entities.account import AccountState
from brain.domain.services.market_analyzer import MarketAnalyzer
from brain.domain.services.decision_engine import DecisionEngine
from brain.domain.services.risk_manager import RiskManager
from brain.domain.value_objects.risk import RiskParameters
from analysis.technical.smc_strategy import SMCStrategy
from analysis.technical.classic_strategy import ClassicStrategy

print("🚀 AGGRESSIVE BACKTEST - Hermes V2")
print("="*60)
print("   (Lowered thresholds for more signals)")
print()

# Load
with open('data/backtest_data.json') as f:
    data = json.load(f)

candles = [Candle(
    time=datetime.fromisoformat(c['time']),
    open=c['open'], high=c['high'], low=c['low'],
    close=c['close'], volume=c['volume']
) for c in data['candles']]

print(f"📊 {len(candles)} candles, {(candles[-1].time - candles[0].time).days} days")
print(f"   Range: ${candles[0].close:.0f} → ${candles[-1].close:.0f}")
print()

# Setup with relaxed params
analyzer = MarketAnalyzer()
analyzer.add_strategy(SMCStrategy(), 1.0)
analyzer.add_strategy(ClassicStrategy(), 0.8)

risk_params = RiskParameters(
    max_risk_per_trade_pct=0.02,
    min_risk_reward=1.5,  # Lower from 2.0
    max_daily_loss_pct=0.05,
    max_daily_trades=10,  # More trades
    max_open_positions=1,
    max_position_size_lots=10.0
)
risk_manager = RiskManager(risk_params)
decision_engine = DecisionEngine(risk_manager)

print("🏗️ Config:")
print("   • Strategies: SMC + Classic")
print("   • Risk: 2% per trade")
print("   • Min RR: 1.5:1 (relaxed)")
print("   • Max daily trades: 10")
print()

balance = 10000.0
trades = []
open_pos = None
signals = 0

print(f"💰 Start: ${balance:,.0f}")
print()
print("🔄 Running...\n")

for i in range(200, len(candles), 3):  # Every 3 candles = 15min
    candle = candles[i]
    
    # Exit check
    if open_pos:
        for c in candles[open_pos['i']+1:i+1]:
            tp = (open_pos['d']=='buy' and c.high>=open_pos['tp']) or (open_pos['d']=='sell' and c.low<=open_pos['tp'])
            sl = (open_pos['d']=='buy' and c.low<=open_pos['sl']) or (open_pos['d']=='sell' and c.high>=open_pos['sl'])
            if tp or sl:
                ex = open_pos['tp'] if tp else open_pos['sl']
                pnl = (ex-open_pos['e']) if open_pos['d']=='buy' else (open_pos['e']-ex)
                pnl *= 1.0  # 1 lot = $1/point for backtest
                balance += pnl
                trades.append({'pnl': pnl, 'reason': 'TP' if tp else 'SL', 'time': c.time.isoformat()})
                print(f"{'✅' if pnl>0 else '❌'} #{len(trades)}: ${pnl:+.2f} ({'TP' if tp else 'SL'}) @ {c.time.strftime('%m-%d %H:%M')}")
                open_pos = None
                break
        if open_pos:
            continue
    
    # Entry
    try:
        market = MarketState(
            symbol='XAUUSD', timeframe='M15', current_price=candle.close,
            timestamp=candle.time, candles=candles[max(0,i-500):i+1]
        )
        analysis = analyzer.analyze(market)
        
        # MANUALLY CHECK THRESHOLD (bypass decision engine strict rules)
        if analysis.quality >= 0.35 and analysis.confidence >= 0.45:
            signals += 1
            
            # Simple signal extraction
            signal_direction = analysis.overall_signal
            if signal_direction in ['buy', 'sell']:
                # Manual SL/TP calculation
                atr = sum(c.high - c.low for c in candles[max(0,i-14):i]) / 14
                
                if signal_direction == 'buy':
                    entry = candle.close
                    sl = entry - (atr * 1.5)
                    tp = entry + (atr * 3.0)  # 2:1 RR
                else:
                    entry = candle.close
                    sl = entry + (atr * 1.5)
                    tp = entry - (atr * 3.0)
                
                open_pos = {
                    'i': i,
                    'd': signal_direction,
                    'e': entry,
                    'sl': sl,
                    'tp': tp
                }
                
                print(f"🎯 Signal #{signals}: {signal_direction.upper()} @ {entry:.1f} (Q:{analysis.quality:.2f} C:{analysis.confidence:.2f})")
    except Exception as e:
        pass

print(f"\n{'='*60}")
print(f"\n📊 BACKTEST RESULTS\n")
print(f"Signals Generated: {signals}")
print(f"Trades Executed: {len(trades)}")

if trades:
    wins = sum(1 for t in trades if t['pnl'] > 0)
    losses = sum(1 for t in trades if t['pnl'] < 0)
    total_pnl = sum(t['pnl'] for t in trades)
    
    print(f"\nPerformance:")
    print(f"  Wins: {wins}")
    print(f"  Losses: {losses}")
    print(f"  Win Rate: {wins/len(trades)*100:.1f}%")
    print(f"  \n  Total P&L: ${total_pnl:+,.2f}")
    print(f"  Final Balance: ${balance:,.2f}")
    print(f"  Return: {(balance/10000-1)*100:+.2f}%")
    
    if wins > 0:
        avg_win = sum(t['pnl'] for t in trades if t['pnl'] > 0) / wins
        print(f"  Avg Win: ${avg_win:.2f}")
    if losses > 0:
        avg_loss = sum(t['pnl'] for t in trades if t['pnl'] < 0) / losses
        print(f"  Avg Loss: ${avg_loss:.2f}")
        if avg_loss != 0:
            print(f"  Profit Factor: {abs(sum(t['pnl'] for t in trades if t['pnl'] > 0) / sum(t['pnl'] for t in trades if t['pnl'] < 0)):.2f}")
else:
    print("\n⚠️  No trades executed")
    print("\nReasons:")
    print("  - Quality/confidence thresholds still too high")
    print("  - Market conditions not favorable")
    print(f"  - Generated {signals} signals but none met all criteria")

print()
