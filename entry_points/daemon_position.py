#!/usr/bin/env python3
"""Position Daemon V2 — Position monitoring with V2 architecture.

Monitors open positions, manages SL/TP, trailing stops, and exit conditions.

Runs as systemd service: hermes-position.service
"""

import sys
import time
import signal as sig
from pathlib import Path
from datetime import datetime

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from infrastructure.di_container import DIContainer
from brain.application.use_cases.position_management import (
    PositionManagementUseCase,
    ManagePositionRequest
)

# V2: Trade notifications
try:
    from notifier.trade_notifier import notify_trade_closed
except ImportError:
    def notify_trade_closed(*args, **kwargs):
        pass

# Global flag
running = True

def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global running
    print(f"\n[{datetime.now()}] Received signal {signum}, shutting down...")
    running = False


def monitor_positions(use_case: PositionManagementUseCase, check_interval: int = 2):
    """Monitor positions continuously.
    
    Args:
        use_case: PositionManagementUseCase
        check_interval: Seconds between checks (default: 2s for second-by-second monitoring)
    """
    print(f"[{datetime.now()}] Position daemon started, monitoring every {check_interval}s")
    
    while running:
        try:
            # Manage all positions
            request = ManagePositionRequest(symbol="XAUUSD")
            response = use_case.execute(request)
            
            if response.success:
                if response.positions_managed > 0:
                    print(f"[{datetime.now()}] Managed {response.positions_managed} position(s)")
                    
                    if response.actions_taken:
                        for action in response.actions_taken:
                            print(f"  Action: {action}")
            else:
                if response.error:
                    print(f"[{datetime.now()}] Error: {response.error}")
            
            # Sleep
            time.sleep(check_interval)
        
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[{datetime.now()}] Error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(check_interval)
    
    print(f"[{datetime.now()}] Position daemon stopped")


def main():
    """Main entry point."""
    # Setup signals
    sig.signal(sig.SIGTERM, signal_handler)
    sig.signal(sig.SIGINT, signal_handler)
    
    try:
        # Setup DI
        print(f"[{datetime.now()}] Initializing DI container...")
        container = DIContainer()
        container.load_config(PROJECT_ROOT / '.env')
        container.wire()
        
        # Get use case
        use_case = container.get(PositionManagementUseCase)
        
        # Start monitoring
        monitor_positions(use_case, check_interval=2)
    
    except Exception as e:
        print(f"[{datetime.now()}] Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
