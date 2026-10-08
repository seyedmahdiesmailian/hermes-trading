"""Prometheus Metrics Export - Production monitoring.

Exposes metrics for Prometheus scraping.
Run as HTTP server on port 8000.
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import time
from datetime import datetime
from typing import Dict, List
import json
from pathlib import Path


class MetricsCollector:
    """Collect trading metrics for Prometheus."""
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.start_time = time.time()
    
    def collect(self) -> Dict[str, any]:
        """Collect all metrics."""
        metrics = {}
        
        # System uptime
        metrics['hermes_uptime_seconds'] = int(time.time() - self.start_time)
        
        # Account metrics
        try:
            account_file = self.data_dir / 'state' / 'account.json'
            if account_file.exists():
                with open(account_file) as f:
                    account = json.load(f)
                    metrics['hermes_balance'] = account.get('balance', 0)
                    metrics['hermes_equity'] = account.get('equity', 0)
                    metrics['hermes_margin'] = account.get('margin', 0)
                    metrics['hermes_free_margin'] = account.get('margin_free', 0)
                    metrics['hermes_open_positions'] = account.get('open_positions', 0)
        except Exception:
            pass
        
        # Performance metrics
        try:
            perf_file = self.data_dir / 'state' / 'performance.json'
            if perf_file.exists():
                with open(perf_file) as f:
                    perf = json.load(f)
                    metrics['hermes_total_trades'] = perf.get('total_trades', 0)
                    metrics['hermes_win_rate'] = perf.get('win_rate', 0)
                    metrics['hermes_profit_factor'] = perf.get('profit_factor', 0)
                    metrics['hermes_sharpe_ratio'] = perf.get('sharpe_ratio', 0)
                    metrics['hermes_max_drawdown'] = perf.get('max_drawdown', 0)
        except Exception:
            pass
        
        # Plans count
        try:
            plans_dir = self.data_dir / 'plans' / 'history'
            if plans_dir.exists():
                metrics['hermes_plans_total'] = len(list(plans_dir.glob('*.json')))
        except Exception:
            pass
        
        return metrics
    
    def format_prometheus(self) -> str:
        """Format metrics in Prometheus format."""
        metrics = self.collect()
        lines = []
        
        for name, value in metrics.items():
            # Add help text
            lines.append(f"# HELP {name} Trading system metric")
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")
            lines.append("")
        
        return "\n".join(lines)


class MetricsHandler(BaseHTTPRequestHandler):
    """HTTP handler for /metrics endpoint."""
    
    collector = None  # Set by server
    
    def do_GET(self):
        if self.path == '/metrics':
            metrics = self.collector.format_prometheus()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(metrics.encode('utf-8'))
        elif self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            health = {"status": "healthy", "timestamp": datetime.now().isoformat()}
            self.wfile.write(json.dumps(health).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Suppress logs
        pass


def run_metrics_server(port: int = 8000, data_dir: str = "data"):
    """Run Prometheus metrics HTTP server.
    
    Args:
        port: Port to listen on (default 8000)
        data_dir: Data directory path
    
    Usage:
        python -m infrastructure.prometheus_metrics
    
    Then configure Prometheus to scrape:
        scrape_configs:
          - job_name: 'hermes'
            static_configs:
              - targets: ['192.168.10.18:8000']
    """
    collector = MetricsCollector(Path(data_dir))
    MetricsHandler.collector = collector
    
    server = HTTPServer(('0.0.0.0', port), MetricsHandler)
    print(f"[{datetime.now()}] Metrics server running on http://0.0.0.0:{port}/metrics")
    print(f"[{datetime.now()}] Health check: http://0.0.0.0:{port}/health")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n[{datetime.now()}] Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    run_metrics_server()
