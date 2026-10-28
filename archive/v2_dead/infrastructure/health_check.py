"""Health Check System - Monitor system health.

Checks:
- MT5 connection
- Services status
- Disk space
- Memory usage
- Recent errors
"""
import subprocess
import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List


class HealthChecker:
    """System health checker."""
    
    def __init__(self, data_dir: Path = Path('data')):
        self.data_dir = data_dir
    
    def check_all(self) -> Dict[str, any]:
        """Run all health checks."""
        return {
            'timestamp': datetime.now().isoformat(),
            'overall_status': 'healthy',  # Will be updated
            'checks': {
                'mt5_connection': self.check_mt5(),
                'services': self.check_services(),
                'disk_space': self.check_disk(),
                'memory': self.check_memory(),
                'recent_trades': self.check_recent_activity(),
                'data_files': self.check_data_files()
            }
        }
    
    def check_mt5(self) -> Dict:
        """Check MT5 bridge connection."""
        try:
            import requests
            import os
            
            url = os.getenv('HERMES_BRIDGE_URL', 'http://192.168.10.51:5050')
            token = os.getenv('HERMES_BRIDGE_TOKEN', '')
            
            response = requests.get(
                f"{url}/api/account",
                headers={'Authorization': f'Bearer {token}'},
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'status': 'healthy',
                    'balance': data.get('data', {}).get('balance'),
                    'connected': True
                }
            else:
                return {'status': 'unhealthy', 'error': f'HTTP {response.status_code}'}
        
        except Exception as e:
            return {'status': 'unhealthy', 'error': str(e)}
    
    def check_services(self) -> Dict:
        """Check systemd services."""
        services = [
            'hermes-signal-v2',
            'hermes-position-v2',
            'hermes-dashboard',
            'hermes-command-bot'
        ]
        
        statuses = {}
        all_ok = True
        
        for service in services:
            try:
                result = subprocess.run(
                    ['systemctl', '--user', 'is-active', service],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                is_active = result.stdout.strip() == 'active'
                statuses[service] = 'active' if is_active else 'inactive'
                
                if not is_active:
                    all_ok = False
            
            except Exception as e:
                statuses[service] = f'error: {e}'
                all_ok = False
        
        return {
            'status': 'healthy' if all_ok else 'degraded',
            'services': statuses
        }
    
    def check_disk(self) -> Dict:
        """Check disk space."""
        try:
            stat = os.statvfs('/')
            free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
            total_gb = (stat.f_blocks * stat.f_frsize) / (1024**3)
            used_pct = ((total_gb - free_gb) / total_gb) * 100
            
            status = 'healthy'
            if used_pct > 90:
                status = 'critical'
            elif used_pct > 80:
                status = 'warning'
            
            return {
                'status': status,
                'free_gb': round(free_gb, 2),
                'total_gb': round(total_gb, 2),
                'used_pct': round(used_pct, 2)
            }
        
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
    
    def check_memory(self) -> Dict:
        """Check memory usage."""
        try:
            with open('/proc/meminfo') as f:
                lines = f.readlines()
            
            mem_info = {}
            for line in lines[:3]:
                key, value = line.split(':')
                mem_info[key.strip()] = int(value.strip().split()[0])
            
            total = mem_info['MemTotal']
            free = mem_info['MemFree'] + mem_info.get('Buffers', 0) + mem_info.get('Cached', 0)
            used_pct = ((total - free) / total) * 100
            
            status = 'healthy'
            if used_pct > 90:
                status = 'critical'
            elif used_pct > 80:
                status = 'warning'
            
            return {
                'status': status,
                'used_pct': round(used_pct, 2),
                'free_mb': round(free / 1024, 2)
            }
        
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
    
    def check_recent_activity(self) -> Dict:
        """Check recent trading activity."""
        try:
            plans_dir = self.data_dir / 'plans' / 'history'
            if not plans_dir.exists():
                return {'status': 'unknown', 'reason': 'no plans directory'}
            
            # Check for plans in last 24h
            recent = []
            cutoff = datetime.now() - timedelta(hours=24)
            
            for plan_file in plans_dir.glob('*.json'):
                mtime = datetime.fromtimestamp(plan_file.stat().st_mtime)
                if mtime > cutoff:
                    recent.append(plan_file)
            
            return {
                'status': 'healthy',
                'plans_24h': len(recent)
            }
        
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
    
    def check_data_files(self) -> Dict:
        """Check data files integrity."""
        files_to_check = [
            'state/account.json',
            'plans/current_plan.json'
        ]
        
        status = {}
        all_ok = True
        
        for file_path in files_to_check:
            full_path = self.data_dir / file_path
            
            if full_path.exists():
                try:
                    with open(full_path) as f:
                        json.load(f)  # Validate JSON
                    status[file_path] = 'ok'
                except Exception as e:
                    status[file_path] = f'corrupt: {e}'
                    all_ok = False
            else:
                status[file_path] = 'missing'
                # Missing is ok for some files
        
        return {
            'status': 'healthy' if all_ok else 'degraded',
            'files': status
        }


if __name__ == "__main__":
    checker = HealthChecker()
    result = checker.check_all()
    print(json.dumps(result, indent=2))
