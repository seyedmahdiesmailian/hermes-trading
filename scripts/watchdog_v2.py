#!/usr/bin/env python3
"""Trading Lane Watchdog V2.

Monitors V2 services and alerts on issues.

Checks:
- hermes-signal-v2.service
- hermes-position-v2.service  
- MT5 bridge health
- Recent logs
"""
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))


def check_service(name: str) -> tuple[bool, str]:
    """Check if systemd service is running.
    
    Returns:
        (is_running, status)
    """
    try:
        result = subprocess.run(
            ['systemctl', '--user', 'is-active', name],
            capture_output=True,
            text=True,
            timeout=5
        )
        status = result.stdout.strip()
        return status == 'active', status
    except Exception as e:
        return False, f"error: {e}"


def check_bridge() -> tuple[bool, str]:
    """Check MT5 bridge via bridge_health_monitor state.
    
    Returns:
        (is_healthy, message)
    """
    state_file = BASE / 'data' / 'bridge_health_state.json'
    
    if not state_file.exists():
        return False, "no health state"
    
    try:
        import json
        with open(state_file) as f:
            state = json.load(f)
        
        if state.get('consecutive_failures', 0) == 0:
            return True, "OK"
        else:
            return False, f"{state['consecutive_failures']} failures"
    except Exception as e:
        return False, f"exception: {e}"


def check_recent_log(log_file: Path, max_age_min: int = 60) -> tuple[bool, str]:
    """Check if log was written recently.
    
    Returns:
        (is_fresh, message)
    """
    if not log_file.exists():
        return False, "not found"
    
    try:
        mtime = datetime.fromtimestamp(log_file.stat().st_mtime, tz=timezone.utc)
        age = datetime.now(timezone.utc) - mtime
        
        if age < timedelta(minutes=max_age_min):
            return True, f"{int(age.total_seconds() / 60)} min ago"
        else:
            return False, f"stale {int(age.total_seconds() / 60)} min"
    except Exception as e:
        return False, f"error: {e}"


def main():
    """Main watchdog check."""
    issues = []
    
    # Check V2 services
    signal_ok, signal_status = check_service('hermes-signal-v2.service')
    if not signal_ok:
        issues.append(f"SERVICE hermes-signal-v2: {signal_status}")
    
    position_ok, position_status = check_service('hermes-position-v2.service')
    if not position_ok:
        issues.append(f"SERVICE hermes-position-v2: {position_status}")
    
    # Check bridge
    bridge_ok, bridge_msg = check_bridge()
    if not bridge_ok:
        issues.append(f"BRIDGE {bridge_msg}")
    
    # Check master log
    master_log = BASE / 'logs' / 'master_cron.log'
    log_ok, log_msg = check_recent_log(master_log, max_age_min=30)
    if not log_ok:
        issues.append(f"MASTER log {log_msg}")
    
    # Report
    if issues:
        print("🛑 واچ‌داگ ترید V2 — مشکل پیدا شد!")
        for issue in issues:
            print(f"• {issue}")
        print(f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        sys.exit(1)
    else:
        print("✅ واچ‌داگ ترید V2 — همه چیز سالم است")
        print(f"• Signal service: {signal_status}")
        print(f"• Position service: {position_status}")
        print(f"• Bridge: {bridge_msg}")
        print(f"• Master log: {log_msg}")
        sys.exit(0)


if __name__ == '__main__':
    main()
