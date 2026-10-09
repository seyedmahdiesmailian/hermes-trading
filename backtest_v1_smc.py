#!/usr/bin/env python3
"""Backtest V1 SMC Strategy - Test 65% WR Claim.

Test the recreated V1 logic against same data:
- Should see 60-70% WR in premium zones
- Should see 50-55% WR in discount zones
- aggressive_value entries should perform best
- Asia session should show issues
"""
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
from brain.strategies.v1_smc_strategy import V1SMCStrategy

print("🎯 V1 SMC STRATEGY BACKTEST")
print("="*70)
print("Testing recreated V1 logic: Expected 65-73% WR")
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

# Setup V2 with V1 strategy
analyzer = MarketAnalyzer()
v1_strategy = V1SMCStrategy()
analyzer.add_strategy(v1_strategy, 1.0)

risk_params = RiskParameters(
    max_risk_per_trade_pct=0.02,  # V1's 2%
    min_risk_reward=2.0,           # V1 proven
    max_daily_loss_pct=0.05,
    max_daily_trades=10,
    max_open_positions=1,
    max_position_size_lots=0.5
)
risk_manager = RiskManager(risk_params)
decision_engine = DecisionEngine(risk_manager)

print("⚙️  V1 Configuration:")
print("   Strategy: V1 SMC (65-73% WR target)")
print("   Risk: 2% per trade")
print("   Min R:R: 2.0 (V1 proven)")
print("   Min Stop: $8 (noise filter)")
print("   Sessions: Asia 0.5x, London/NY 1.0x")
print()

balance = 10000.0
trades = []
open_trade = None
max_dd = 0.0
peak = balance

# Track by entry style
style_stats = {}

print(f"💰 Starting: ${balance:,.2f}")
print("\n🔄 Running V1 backtest...\n")

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
            
            # Track style stats
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
                    
                    # Extract V1 metadata
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
print("📊 FINAL RESULTS - V1 SMC STRATEGY\n")

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
    
    # V1 Analysis: By Entry Style
    print("\n" + "="*70)
    print("📈 V1 ANALYSIS: By Entry Style\n")
    
    for style, stats in sorted(style_stats.items(), key=lambda x: x[1]['trades'], reverse=True):
        if stats['trades'] > 0:
            wr = stats['wins'] / stats['trades'] * 100
            print(f"{style:20s}: {stats['trades']:3d} trades | {wr:5.1f}% WR | ${stats['pnl']:+8.2f}")
    
    # By Zone
    print("\n📍 By Premium/Discount Zone:\n")
    zone_stats = {}
    for t in trades:
        zone = t['zone']
        if zone not in zone_stats:
            zone_stats[zone] = {'trades': 0, 'wins': 0, 'pnl': 0.0}
        zone_stats[zone]['trades'] += 1
        if t['result'] == 'WIN':
            zone_stats[zone]['wins'] += 1
        zone_stats[zone]['pnl'] += t['pnl']
    
    for zone, stats in sorted(zone_stats.items()):
        if stats['trades'] > 0:
            wr = stats['wins'] / stats['trades'] * 100
            print(f"{zone:15s}: {stats['trades']:3d} trades | {wr:5.1f}% WR | ${stats['pnl']:+8.2f}")
    
    # By Session
    print("\n⏰ By Session:\n")
    session_stats = {}
    for t in trades:
        sess = t['session']
        if sess not in session_stats:
            session_stats[sess] = {'trades': 0, 'wins': 0, 'pnl': 0.0}
        session_stats[sess]['trades'] += 1
        if t['result'] == 'WIN':
            session_stats[sess]['wins'] += 1
        session_stats[sess]['pnl'] += t['pnl']
    
    for sess, stats in sorted(session_stats.items()):
        if stats['trades'] > 0:
            wr = stats['wins'] / stats['trades'] * 100
            print(f"{sess:10s}: {stats['trades']:3d} trades | {wr:5.1f}% WR | ${stats['pnl']:+8.2f}")
    
    print("\n" + "="*70)
    print("🎯 V1 TARGET COMPARISON\n")
    print("V1 Historical (Live):")
    print("   Overall WR: 65-73%")
    print("   Premium zones: 65% WR")
    print("   Discount zones: 52% WR")
    print("   aggressive_value: 70% WR, +$115/27 trades")
    print()
    print("This Backtest:")
    print(f"   Overall WR: {win_rate:.1f}%")
    
    # Check if we hit targets
    if win_rate >= 60:
        print("\n✅ EXCELLENT - V1 performance matched!")
    elif win_rate >= 50:
        print("\n✅ GOOD - Acceptable performance")
    elif win_rate >= 40:
        print("\n⚠️  FAIR - Below V1 target but viable")
    else:
        print("\n❌ POOR - Needs tuning")

else:
    print("❌ No trades executed")
    print("Check V1 filters - may be too strict")

print()
