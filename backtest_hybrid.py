#!/usr/bin/env python3
"""Test Hybrid ML-SMC Strategy."""
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
from brain.strategies.hybrid_ml_smc import HybridMLSMCStrategy

print("🎯 HYBRID ML-SMC STRATEGY BACKTEST")
print("="*70)
print("Best of Both: ML signals + SMC filters = Maximum Profitability")
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

# Setup
analyzer = MarketAnalyzer()
hybrid = HybridMLSMCStrategy()
analyzer.add_strategy(hybrid, 1.0)

risk_params = RiskParameters(
    max_risk_per_trade_pct=0.015,
    min_risk_reward=1.5,  # Lower than V1's 2.0
    max_daily_loss_pct=0.05,
    max_daily_trades=10,
    max_open_positions=1,
    max_position_size_lots=0.5
)
risk_manager = RiskManager(risk_params)
decision_engine = DecisionEngine(risk_manager)

print("⚙️  Hybrid Configuration:")
print("   ML: 20 features, 0.55 threshold")
print("   SMC: Premium/Discount filtering")
print("   Combined: 0.60 minimum")
print("   R:R: Dynamic 1.5-3.0")
print()

balance = 10000.0
trades = []
open_trade = None
max_dd = 0.0
peak = balance
style_stats = {}

print(f"💰 Starting: ${balance:,.2f}\n")

for i in range(250, len(candles_data)):
    current_candles = candles_data[:i+1]
    current_price = current_candles[-1].close
    
    if balance > peak:
        peak = balance
    dd = (peak - balance) / peak * 100
    if dd > max_dd:
        max_dd = dd
    
    # Exit check
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
            
            style = decision.get('style', 'unknown')
            if style not in style_stats:
                style_stats[style] = {'trades': 0, 'wins': 0, 'pnl': 0.0}
            style_stats[style]['trades'] += 1
            if won:
                style_stats[style]['wins'] += 1
            style_stats[style]['pnl'] += pnl
            
            trades.append({
                'pnl': pnl,
                'result': 'WIN' if won else 'LOSS',
                'entry': decision['entry'],
                'exit': exit_price,
                'size': decision['size'],
                'time': current_candles[-1].time,
                'style': style,
                'session': decision.get('session', 'unknown'),
                'zone': decision.get('zone', 'unknown')
            })
            
            if len(trades) % 10 == 0:
                wr = sum(1 for t in trades if t['result'] == 'WIN') / len(trades) * 100
                print(f"📊 {len(trades)} trades | {wr:.1f}% WR | ${balance:,.2f}")
            
            open_trade = None
            continue
    
    # Entry check
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
                    
                    reasoning = analysis.reasoning
                    style = reasoning.get('entry_style', 'unknown') if isinstance(reasoning, dict) else 'unknown'
                    session = reasoning.get('session', 'unknown') if isinstance(reasoning, dict) else 'unknown'
                    zone = reasoning.get('premium_discount', 'unknown') if isinstance(reasoning, dict) else 'unknown'
                    
                    open_trade = {
                        'action': action,
                        'entry': entry,
                        'sl': sl,
                        'tp': tp,
                        'size': size,
                        'style': style,
                        'session': session,
                        'zone': zone
                    }
        except Exception:
            pass

print("\n" + "="*70)
print("📊 FINAL RESULTS - HYBRID ML-SMC\n")

if trades:
    wins = [t for t in trades if t['result'] == 'WIN']
    losses = [t for t in trades if t['result'] == 'LOSS']
    total_pnl = sum(t['pnl'] for t in trades)
    win_rate = len(wins) / len(trades) * 100
    
    print(f"Total Trades: {len(trades)}")
    print(f"Wins: {len(wins)} | Losses: {len(losses)}")
    print(f"Win Rate: {win_rate:.1f}%")
    print()
    print(f"Final Balance: ${balance:,.2f}")
    print(f"Total P&L: ${total_pnl:+,.2f}")
    print(f"Return: {(balance/10000-1)*100:+.2f}%")
    print(f"Max Drawdown: {max_dd:.2f}%")
    print()
    
    if wins:
        avg_win = sum(t['pnl'] for t in wins) / len(wins)
        print(f"Avg Win: ${avg_win:.2f}")
    if losses:
        avg_loss = sum(t['pnl'] for t in losses) / len(losses)
        print(f"Avg Loss: ${avg_loss:.2f}")
        pf = abs(sum(t['pnl'] for t in wins) / sum(t['pnl'] for t in losses)) if losses else 0
        print(f"Profit Factor: {pf:.2f}")
    
    print("\n📈 By Entry Style:\n")
    for style, stats in sorted(style_stats.items(), key=lambda x: x[1]['trades'], reverse=True):
        if stats['trades'] > 0:
            wr = stats['wins'] / stats['trades'] * 100
            print(f"{style:20s}: {stats['trades']:3d} | {wr:5.1f}% WR | ${stats['pnl']:+8.2f}")
    
    print("\n🏆 COMPARISON:\n")
    print("ML Heuristic:  -1.30% | 25.4% WR | 122 trades")
    print("V1 SMC:        -2.30% | 15.4% WR |  13 trades")
    print(f"Hybrid:        {(balance/10000-1)*100:+.2f}% | {win_rate:.1f}% WR | {len(trades)} trades")
    
    if balance > 9870:  # Better than both
        print("\n🎉 WINNER - Best system!")
    elif balance > 9700:
        print("\n✅ GOOD - Competitive performance")
    else:
        print("\n⚠️  Needs optimization")
else:
    print("No trades")

print()
