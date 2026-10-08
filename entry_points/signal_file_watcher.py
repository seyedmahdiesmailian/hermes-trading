#!/usr/bin/env python3
"""Signal File Watcher - Read signals from forwarder and process them.

The forwarder writes signals to signals_log.json.
This daemon reads new signals and processes them through V2 system.
"""
import sys
import time
import json
import signal as sig
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from infrastructure.di_container import DIContainer
from brain.application.use_cases.signal_processing import (
    SignalProcessingUseCase,
    ProcessSignalRequest
)
from brain.domain.entities.signal import Signal, SignalSource

running = True

def signal_handler(signum, frame):
    global running
    print(f"[{datetime.now()}] Shutdown signal received")
    running = False

def load_signals_from_file(filepath: Path) -> list:
    """Load signals from JSON log."""
    if not filepath.exists():
        return []
    
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except Exception as e:
        print(f"Error loading signals: {e}")
        return []

def parse_signal_entry(entry: dict) -> Signal | None:
    """Parse signal from forwarder format.
    
    Expected keys: symbol, direction, entry, sl, tp, channel, timestamp
    """
    try:
        # Required fields
        if not all(k in entry for k in ['symbol', 'direction', 'entry', 'sl', 'tp']):
            return None
        
        symbol = entry['symbol'].upper()
        direction = entry['direction'].lower()
        entry_price = float(entry['entry'])
        sl = float(entry['sl'])
        tp = float(entry['tp'])
        
        # Validate
        if direction not in ['buy', 'sell']:
            return None
        
        if direction == 'buy' and sl >= entry_price:
            return None  # Invalid: SL should be below entry for BUY
        if direction == 'sell' and sl <= entry_price:
            return None  # Invalid: SL should be above entry for SELL
        
        return Signal(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            stop_loss=sl,
            take_profit=tp,
            source=SignalSource.TELEGRAM,
            confidence_score=0.6
        )
    
    except Exception as e:
        print(f"Error parsing signal: {e}")
        return None

def main():
    print(f"[{datetime.now()}] Signal File Watcher V2 starting...")
    
    # Setup signal handlers
    sig.signal(sig.SIGTERM, signal_handler)
    sig.signal(sig.SIGINT, signal_handler)
    
    # Initialize DI container
    container = DIContainer()
    container.load_config(PROJECT_ROOT / '.env')
    container.wire()
    
    signal_processor = container.get(SignalProcessingUseCase)
    
    signals_file = PROJECT_ROOT / 'data' / 'signals' / 'signals_log.json'
    processed_file = PROJECT_ROOT / 'data' / 'signals' / 'processed_ids.json'
    
    # Load already processed signal IDs
    processed_ids = set()
    if processed_file.exists():
        try:
            with open(processed_file, 'r') as f:
                processed_ids = set(json.load(f))
        except:
            pass
    
    print(f"[{datetime.now()}] Monitoring: {signals_file}")
    print(f"[{datetime.now()}] Already processed: {len(processed_ids)} signals")
    print(f"[{datetime.now()}] Checking every 10 seconds...")
    
    cycle = 0
    
    while running:
        try:
            cycle += 1
            
            # Load signals
            signals = load_signals_from_file(signals_file)
            
            new_count = 0
            for entry in signals:
                # Generate ID from signal
                signal_id = f"{entry.get('timestamp', '')}_{entry.get('symbol', '')}_{entry.get('direction', '')}"
                
                if signal_id in processed_ids:
                    continue  # Already processed
                
                # Parse signal
                signal = parse_signal_entry(entry)
                if not signal:
                    processed_ids.add(signal_id)  # Mark as seen (even if invalid)
                    continue
                
                # Process through V2
                print(f"\n[{datetime.now()}] NEW SIGNAL: {signal.symbol} {signal.direction.upper()} @ {signal.entry_price}")
                print(f"  SL: {signal.stop_loss} | TP: {signal.take_profit}")
                print(f"  Source: {signal.source.value}")
                
                request = ProcessSignalRequest(signal=signal)
                response = signal_processor.execute(request)
                
                if response.accepted:
                    print(f"  ✅ ACCEPTED: {response.reasoning}")
                    if response.action_taken:
                        print(f"  Action: {response.action_taken}")
                else:
                    print(f"  ❌ REJECTED: {response.reasoning}")
                
                processed_ids.add(signal_id)
                new_count += 1
            
            # Save processed IDs
            if new_count > 0:
                with open(processed_file, 'w') as f:
                    json.dump(list(processed_ids), f)
                print(f"[{datetime.now()}] Processed {new_count} new signal(s)")
            
            # Status every 10 cycles
            if cycle % 10 == 0:
                print(f"[{datetime.now()}] Status: {len(processed_ids)} total processed, monitoring...")
            
            time.sleep(10)
        
        except Exception as e:
            print(f"[{datetime.now()}] Error in cycle: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(10)
    
    print(f"[{datetime.now()}] Signal watcher stopped")

if __name__ == "__main__":
    main()
