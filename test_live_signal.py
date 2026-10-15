#!/usr/bin/env python3
"""Test signal processing with a sample signal."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from brain.domain.services.signal_parser import SignalParser

# Sample signals from different formats
test_signals = [
    # English
    "🟢 XAUUSD BUY @ 2650.50\nSL: 2645.00\nTP: 2665.00\nR:R = 2.9:1",
    
    # Farsi
    "گلد خرید 2650\nاستاپ: 2645\nهدف: 2665\n✅ سیگنال قوی",
    
    # Emoji-based
    "🔴 GOLD SELL\nEntry: 2650\nSL: 2655\nTP: 2635",
    
    # Poor R:R (should be rejected)
    "XAUUSD BUY 2650\nSL: 2648\nTP: 2653\n(R:R = 1.5)",
]

parser = SignalParser()

print("🧪 Testing Signal Parser\n" + "="*80)

for i, signal_text in enumerate(test_signals, 1):
    print(f"\n📨 Test #{i}:")
    print(f"   Text: {signal_text[:60]}...")
    
    result = parser.parse(signal_text)
    
    if result.success:
        signal = result.signal
        print(f"   ✅ SUCCESS")
        print(f"   Symbol: {signal.symbol}")
        print(f"   Direction: {signal.direction}")
        print(f"   Entry: {signal.entry_price:.2f}")
        print(f"   SL: {signal.stop_loss:.2f} | TP: {signal.take_profit:.2f}")
        print(f"   R:R: {signal.risk_reward_ratio():.2f}")
        print(f"   Quality: {signal.quality.value}")
    else:
        print(f"   ❌ FAILED: {result.error}")

print("\n" + "="*80)
print("✅ Parser test complete")
