#!/usr/bin/env python3
"""Cron Master — Main autonomous trading cycle entry point.

Runs every 5 minutes via cron.

Flow:
1. Load config
2. Wire dependencies
3. Execute autonomous trading cycle
4. Report results
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from infrastructure.di_container import DIContainer
from brain.application.use_cases.autonomous_trading import (
    AutonomousTradingUseCase,
    AutonomousTradingRequest
)


def main():
    """Main entry point."""
    try:
        # 1. Setup DI container
        container = DIContainer()
        container.load_config(PROJECT_ROOT / '.env')
        container.wire()
        
        # 2. Get use case
        use_case = container.get(AutonomousTradingUseCase)
        
        # 3. Execute cycle
        request = AutonomousTradingRequest(
            symbol="XAUUSD",
            timeframe="M15"
        )
        
        response = use_case.execute(request)
        
        # 4. Report
        if response.success:
            print(f"✅ Cycle complete: {response.action_taken}")
            if response.action_taken != "no_action":
                print(f"Details: {response.details}")
            sys.exit(0)
        else:
            print(f"❌ Cycle failed: {response.error}")
            sys.exit(1)
    
    except Exception as e:
        print(f"💥 Fatal error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
