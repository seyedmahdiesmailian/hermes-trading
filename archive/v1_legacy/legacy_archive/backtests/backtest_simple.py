#!/usr/bin/env python3
"""Simple backtest for V2 system."""
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
from analysis.technical.scalping_strategy import ScalpingStrategy
from analysis.technical.breakout_strategy import BreakoutStrategy

print("🚀 BACKTEST - Hermes V2 System")
print("="*60)

# Load
with open('data/backtest_data.json') as f:
    data = json.load(f)

candles = [Candle(
    time=datetime.fromisoformat(c['time']),
    open=c['open'], high=c['high'], low=c['low'],
    close=c['close'], volume=c['volume']
) for c in data['candles']]

print(f"\n📊 {len(candles)} candles, {(candles[-1].time - candles[0].time).days} days")

# Setup - AGGRESSIVE MULTI-STRATEGY
analyzer = MarketAnalyzer()
analyzer.add_strategy(ScalpingStrategy(), 1.5)  # HIGHEST weight
analyzer.add_strategy(BreakoutStrategy(), 1.2)
analyzer.add_strategy(SMCStrategy(), 0.8)
analyzer.add_strategy(ClassicStrategy(), 0.6)

risk_params = RiskParameters(
    max_risk_per_trade_pct=0.02,  # 2%
    min_risk_reward=2.0,
    max_daily_loss_pct=0.05,  # 5%
    max_daily_trades=5,
    max_open_positions=1,
    max_position_size_lots=10.0
)
risk_manager = RiskManager(risk_params)
decision_engine = DecisionEngine(risk_manager)

balance = 10000.0
trades = []
open_pos = None

print(f"💰 Start: ${balance:,.0f}\n")
print("Running...\n")

for i in range(200, len(candles), 5):
    candle = candles[i]
    
    if open_pos:
        for c in candles[open_pos['i']+1:i+1]:
            tp = (open_pos['d']=='buy' and c.high>=open_pos['tp']) or (open_pos['d']=='sell' and c.low<=open_pos['tp'])
            sl = (open_pos['d']=='buy' and c.low<=open_pos['sl']) or (open_pos['d']=='sell' and c.high>=open_pos['sl'])
            if tp or sl:
                ex = open_pos['tp'] if tp else open_pos['sl']
                pnl = (ex-open_pos['e']) if open_pos['d']=='buy' else (open_pos['e']-ex)
                pnl *= 1.0
                balance += pnl
                trades.append(pnl)
                print(f"{'✅' if pnl>0 else '❌'} #{len(trades)}: ${pnl:+.2f}")
                open_pos = None
                break
        if open_pos:
            continue
    
    try:
        market = MarketState(
            symbol='XAUUSD', timeframe='M15', current_price=candle.close,
            timestamp=candle.time, candles=candles[max(0,i-500):i+1]
        )
        analysis = analyzer.analyze(market)
        account = AccountState(balance=balance, equity=balance, margin_free=balance)
        decision = decision_engine.evaluate_entry(analysis, account, market)
        
        if decision.should_execute() and decision.action_params:
            p = decision.action_params
            open_pos = {'i': i, 'd': p['direction'], 'e': candle.close, 'sl': p['sl'], 'tp': p['tp']}
            print(f"🎯 {p['direction'].upper()} @ {candle.close:.1f}")
    except:
        pass

print(f"\n{'='*60}")
print(f"\n📊 RESULTS:\n")
print(f"Trades: {len(trades)}")
if trades:
    wins = sum(1 for t in trades if t > 0)
    print(f"Wins: {wins}/{len(trades)} ({wins/len(trades)*100:.1f}%)")
    print(f"P&L: ${sum(trades):+,.2f}")
    print(f"Final: ${balance:,.2f}")
    print(f"Return: {(balance/10000-1)*100:+.2f}%")
else:
    print("No trades")
print()
