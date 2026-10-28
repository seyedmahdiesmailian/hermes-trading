#!/usr/bin/env python3
"""Signal Daemon V2 — Telegram signal listener with V2 architecture.

Listens to Telegram signal channels, parses signals, and processes them
through the intelligent SignalProcessingUseCase.

Runs as systemd service: hermes-signal.service
"""

import sys
import time
import signal as sig
from pathlib import Path
from datetime import datetime, timezone

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from infrastructure.di_container import DIContainer
from brain.application.use_cases.signal_processing import (
    SignalProcessingUseCase,
    ProcessSignalRequest
)
from brain.domain.entities.signal import Signal, SignalSource

# Global flag for graceful shutdown
running = True

def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global running
    print(f"\n[{datetime.now()}] Received signal {signum}, shutting down...")
    running = False


def parse_telegram_message(text: str, channel: str) -> Signal | None:
    """Parse Telegram message into Signal.
    
    Expected format examples:
    - "XAUUSD BUY @ 2650, SL: 2630, TP: 2690"
    - "Gold SELL 2650 / 2630 / 2690"
    - "Buy XAUUSD entry 2650 stop 2630 target 2690"
    
    Args:
        text: Message text
        channel: Channel name
        
    Returns:
        Signal if parsed, None otherwise
    """
    text = text.upper().strip()
    
    # Skip non-signal messages
    if not any(kw in text for kw in ['BUY', 'SELL', 'ENTRY', 'TP', 'SL']):
        return None
    
    # Simple regex-based parsing (can be improved)
    import re
    
    # Direction
    direction = None
    if 'BUY' in text or 'LONG' in text:
        direction = 'buy'
    elif 'SELL' in text or 'SHORT' in text:
        direction = 'sell'
    
    if not direction:
        return None
    
    # Symbol (default XAUUSD if not specified)
    symbol = "XAUUSD"
    if 'GOLD' in text or 'XAU' in text:
        symbol = "XAUUSD"
    
    # Prices: look for numbers
    numbers = re.findall(r'\d+\.?\d*', text)
    prices = [float(n) for n in numbers if float(n) > 100]  # Filter out small numbers
    
    if len(prices) < 3:
        # Not enough price info
        return None
    
    # Assume: entry, sl, tp (in order mentioned)
    entry = prices[0]
    sl = prices[1]
    tp = prices[2]
    
    # Validate: SL should be on opposite side of entry
    if direction == 'buy' and sl >= entry:
        sl, tp = tp, sl  # Swap if wrong order
    elif direction == 'sell' and sl <= entry:
        sl, tp = tp, sl
    
    return Signal(
        symbol=symbol,
        direction=direction,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        source=SignalSource.TELEGRAM
    )


def listen_to_signals(use_case: SignalProcessingUseCase, check_interval: int = 10):
    """Listen to pending signals and process them.
    
    For now, reads from JSON file (written by forwarder).
    In future: direct Telegram polling.
    
    Args:
        use_case: SignalProcessingUseCase
        check_interval: Seconds between checks
    """
    from adapters.gateways.data.json_repository import JSONRepository
    
    signal_repo = JSONRepository(data_dir=str(PROJECT_ROOT / 'data'))
    
    print(f"[{datetime.now()}] Signal daemon started, checking every {check_interval}s")
    
    while running:
        try:
            # Get pending signals
            pending = signal_repo.get_pending_signals()
            
            if pending:
                print(f"[{datetime.now()}] Found {len(pending)} pending signals")
                
                for signal in pending:
                    print(f"  Processing signal: {signal.symbol} {signal.direction} @ {signal.entry_price}")
                    
                    # Process through use case
                    request = ProcessSignalRequest(signal=signal)
                    response = use_case.execute(request)
                    
                    if response.accepted:
                        print(f"    ✅ Accepted: {response.reasoning}")
                        print(f"    Action: {response.action_taken}")
                    else:
                        print(f"    ❌ Rejected: {response.reasoning}")
            
            # Sleep
            time.sleep(check_interval)
        
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[{datetime.now()}] Error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(check_interval)
    
    print(f"[{datetime.now()}] Signal daemon stopped")


def main():
    """Main entry point."""
    # Setup signal handlers
    sig.signal(sig.SIGTERM, signal_handler)
    sig.signal(sig.SIGINT, signal_handler)
    
    try:
        # Setup DI
        print(f"[{datetime.now()}] Initializing DI container...")
        container = DIContainer()
        container.load_config(PROJECT_ROOT / '.env')
        container.wire()
        
        # Get use case
        use_case = container.get(SignalProcessingUseCase)
        
        # Start listening
        listen_to_signals(use_case, check_interval=10)
    
    except Exception as e:
        print(f"[{datetime.now()}] Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
