#!/usr/bin/env python3
"""Real-time Monitoring Dashboard - System metrics.

Exports metrics for Prometheus/Grafana or logs to file.
"""
import time
import json
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, asdict


@dataclass
class SystemMetrics:
    """System metrics snapshot."""
    timestamp: str
    
    # Trading
    balance: float
    equity: float
    open_positions: int
    daily_pnl: float
    daily_trades: int
    
    # Performance
    total_trades: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    
    # System
    uptime_seconds: int
    cpu_usage: float
    memory_mb: float
    
    # Services
    mt5_connected: bool
    signal_daemon: bool
    position_daemon: bool
    dashboard_bot: bool


class MetricsCollector:
    """Collect and export system metrics."""
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.start_time = time.time()
    
    def collect(self) -> SystemMetrics:
        """Collect current metrics."""
        import subprocess
        
        # Get account data
        try:
            from adapters.gateways.mt5.mt5_gateway import MT5Gateway
            gateway = MT5Gateway()
            account = gateway.get_account_state()
            mt5_ok = True
        except Exception:
            account = None
            mt5_ok = False
        
        # Check services
        services = self._check_services()
        
        # Get performance stats
        perf = self._load_performance()
        
        # System stats
        cpu = self._get_cpu_usage()
        mem = self._get_memory_usage()
        
        return SystemMetrics(
            timestamp=datetime.now(timezone.utc).isoformat(),
            balance=account.balance if account else 0,
            equity=account.equity if account else 0,
            open_positions=account.open_positions if account else 0,
            daily_pnl=perf.get('daily_pnl', 0),
            daily_trades=perf.get('daily_trades', 0),
            total_trades=perf.get('total_trades', 0),
            win_rate=perf.get('win_rate', 0),
            profit_factor=perf.get('profit_factor', 0),
            sharpe_ratio=perf.get('sharpe_ratio', 0),
            max_drawdown=perf.get('max_drawdown', 0),
            uptime_seconds=int(time.time() - self.start_time),
            cpu_usage=cpu,
            memory_mb=mem,
            mt5_connected=mt5_ok,
            signal_daemon=services.get('signal', False),
            position_daemon=services.get('position', False),
            dashboard_bot=services.get('dashboard', False)
        )
    
    def export_json(self):
        """Export metrics to JSON file."""
        metrics = self.collect()
        
        # Write to file
        output = self.output_dir / 'metrics.json'
        with open(output, 'w') as f:
            json.dump(asdict(metrics), f, indent=2)
        
        # Append to time series
        ts_file = self.output_dir / 'metrics_timeseries.jsonl'
        with open(ts_file, 'a') as f:
            f.write(json.dumps(asdict(metrics)) + '\n')
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format.
        
        Returns:
            Prometheus-formatted metrics
        """
        metrics = self.collect()
        
        lines = [
            f"# HELP trading_balance Account balance",
            f"# TYPE trading_balance gauge",
            f"trading_balance {metrics.balance}",
            "",
            f"# HELP trading_equity Account equity",
            f"# TYPE trading_equity gauge",
            f"trading_equity {metrics.equity}",
            "",
            f"# HELP trading_positions_open Open positions count",
            f"# TYPE trading_positions_open gauge",
            f"trading_positions_open {metrics.open_positions}",
            "",
            f"# HELP trading_daily_pnl Daily P&L",
            f"# TYPE trading_daily_pnl gauge",
            f"trading_daily_pnl {metrics.daily_pnl}",
            "",
            f"# HELP trading_win_rate Win rate percentage",
            f"# TYPE trading_win_rate gauge",
            f"trading_win_rate {metrics.win_rate}",
            "",
            f"# HELP system_uptime_seconds Uptime in seconds",
            f"# TYPE system_uptime_seconds counter",
            f"system_uptime_seconds {metrics.uptime_seconds}",
            "",
            f"# HELP mt5_connected MT5 connection status",
            f"# TYPE mt5_connected gauge",
            f"mt5_connected {1 if metrics.mt5_connected else 0}",
        ]
        
        return "\n".join(lines)
    
    def _check_services(self) -> dict:
        """Check systemd services."""
        import subprocess
        
        services = {}
        for name in ['hermes-signal-v2', 'hermes-position-v2', 'hermes-dashboard']:
            try:
                result = subprocess.run(
                    ['systemctl', '--user', 'is-active', name],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                services[name.split('-')[1]] = result.stdout.strip() == 'active'
            except Exception:
                services[name.split('-')[1]] = False
        
        return services
    
    def _load_performance(self) -> dict:
        """Load performance stats."""
        from pathlib import Path
        
        perf_file = Path('data/state/performance.json')
        if perf_file.exists():
            try:
                with open(perf_file) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}
    
    def _get_cpu_usage(self) -> float:
        """Get CPU usage."""
        try:
            import psutil
            return psutil.cpu_percent(interval=1)
        except ImportError:
            return 0.0
    
    def _get_memory_usage(self) -> float:
        """Get memory usage in MB."""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            return 0.0


if __name__ == "__main__":
    # Export metrics every 60s
    collector = MetricsCollector(Path('data/metrics'))
    
    while True:
        try:
            collector.export_json()
            print(f"Metrics exported: {datetime.now()}")
        except Exception as e:
            print(f"Error: {e}")
        
        time.sleep(60)
