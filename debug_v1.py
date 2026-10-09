#!/usr/bin/env python3
"""Debug V1 Strategy - See why no trades."""
import sys
import json
from datetime import datetime

sys.path.insert(0, '/home/ai/hermes-trading')

from brain.domain.entities.market import MarketState, Candle
from brain.strategies.v1_smc_strategy import V1SMCStrategy

print("🔍 V1 STRATEGY DEBUG\n")

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

print(f"Testing on {len(candles_data)} candles\n")

strategy = V1SMCStrategy()

# Sample several points
test_points = [300, 500, 700, 1000, 1500, 1900]

for idx in test_points:
    if idx >= len(candles_data):
        continue
    
    current_candles = candles_data[:idx+1]
    current_price = current_candles[-1].close
    
    market = MarketState(
        symbol='XAUUSD',
        timeframe='M15',
        current_price=current_price,
        timestamp=current_candles[-1].time,
        candles=current_candles
    )
    
    print(f"\n{'='*70}")
    print(f"Candle {idx}: {current_candles[-1].time} | Price: {current_price:.1f}")
    print(f"{'='*70}")
    
    try:
        analysis = strategy.analyze(market)
        
        print(f"\nTrend: {analysis.trend}")
        print(f"Confidence: {analysis.confidence:.2f}")
        print(f"Quality: {analysis.quality_score:.2f}")
        
        if isinstance(analysis.reasoning, dict):
            reason = analysis.reasoning
            print(f"\nReasoning:")
            for key, val in reason.items():
                if key != 'summary':
                    print(f"  {key}: {val}")
            
            if 'summary' in reason:
                print(f"\nSummary:")
                for item in reason['summary']:
                    print(f"  • {item}")
        else:
            print(f"\nReason: {analysis.reasoning}")
        
        if analysis.confidence > 0:
            print(f"\n✅ SIGNAL DETECTED")
            sl = analysis.key_levels.get('stop_loss', [0])
            tp = analysis.key_levels.get('take_profit', [0])
            if sl and tp:
                print(f"   Entry: {current_price:.1f}")
                print(f"   SL: {sl[0]:.1f}")
                print(f"   TP: {tp[0]:.1f}")
        else:
            print(f"\n❌ NO SIGNAL")
    
    except Exception as e:
        print(f"\n⚠️  ERROR: {e}")
        import traceback
        traceback.print_exc()

print(f"\n{'='*70}")
print("Debug complete")
