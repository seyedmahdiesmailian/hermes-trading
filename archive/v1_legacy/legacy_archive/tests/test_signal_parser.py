#!/usr/bin/env python3
"""Test Signal Parser V2."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from brain.domain.services.signal_parser import SignalParser


def test_parser():
    """Test various signal formats."""
    parser = SignalParser()
    
    test_signals = [
        # English
        "XAUUSD BUY 2650.50 SL 2645 TP 2660",
        "🟢 GOLD LONG @ 2650 | SL: 2645 | TP: 2665",
        "Sell XAUUSD 2650.00 Stop 2655 Target 2640",
        
        # Farsi
        "گلد خرید 2650 استاپ 2645 هدف 2660",
        "طلا فروش 2650 حد ضرر 2655 تارگت 2640",
        
        # With emoji
        "🟢 XAUUSD 2650 SL 2645 TP 2660",
        "🔴 GOLD 2650 SL 2655 TP 2640",
    ]
    
    print("="*80)
    print("Signal Parser V2 - Test Results")
    print("="*80)
    
    for i, text in enumerate(test_signals, 1):
        print(f"\n{i}. Test: {text[:60]}..." if len(text) > 60 else f"\n{i}. Test: {text}")
        print("-" * 80)
        
        result = parser.parse(text)
        
        if result.success:
            sig = result.signal
            risk = abs(sig.entry_price - sig.stop_loss)
            reward = abs(sig.take_profit - sig.entry_price)
            rr = reward / risk if risk > 0 else 0
            
            print(f"✅ SUCCESS")
            print(f"   Symbol: {sig.symbol}")
            print(f"   Direction: {sig.direction.upper()}")
            print(f"   Entry: {sig.entry_price:.2f}")
            print(f"   SL: {sig.stop_loss:.2f}")
            print(f"   TP: {sig.take_profit:.2f}")
            print(f"   Risk: {risk:.2f} | Reward: {reward:.2f} | R:R = {rr:.2f}")
            print(f"   Quality: {sig.quality.value}")
            print(f"   Confidence: {sig.confidence_score:.1%}")
        else:
            print(f"❌ FAILED: {result.error}")
    
    print("\n" + "="*80)
    print("Parser test complete!")
    print("="*80)


if __name__ == '__main__':
    test_parser()
