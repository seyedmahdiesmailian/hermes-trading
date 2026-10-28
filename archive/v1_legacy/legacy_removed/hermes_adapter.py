#!/usr/bin/env python3
"""
HERMES DATA ADAPTER
═══════════════════════════════════════════════
مهندسی و دقیق.

این فایل لایه واسط بین:
  - HTTP Bridge (داده خام از MT5)
  - موتورهای تحلیلی قدیمی (mt5_engine, mt5_xau_smc, mt5_xau_context, mt5_xau_defcon)

هدف:
  موتورهای قدیمی بدون تغییر کار کنن. فقط داده‌شون از طریق Adapter تأمین بشه.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/home/ai/hermes-trading/scripts")
sys.path.insert(0, "/home/ai/hermes-trading")

from hermes_brain import HermesMT5Bridge

BASE_DIR = Path("/home/ai/hermes-trading")
LOG_DIR = BASE_DIR / "logs"
SCRIPTS_DIR = BASE_DIR / "scripts"


class HermesDataAdapter:
    """
    Adapter: Bridge HTTP → Old Engine Format
    """
    
    def __init__(self, bridge: HermesMT5Bridge):
        self.bridge = bridge
        
    def get_rates_as_dict(self, symbol="XAUUSD", timeframe="M15", count=80) -> list[dict]:
        """
        دریافت داده از Bridge و تبدیل به فرمت dict list که engine قبلی میفهمه.
        
        Engine قبلی انتظار داره:
        rows = [ {"time":timestamp, "open":float, "high":float, "low":float, "close":float, "tick_volume":int}, ... ]
        """
        resp = self.bridge.get_rates(symbol=symbol, timeframe=timeframe, count=count)
        
        if not resp.get("ok") or not resp.get("data"):
            return []
        
        rows = resp["data"]
        # Bridge already returns as list of dicts with keys: time, open, high, low, close, tick_volume
        # This matches exactly what the old engine expects!
        return rows
    
    def get_ticks(self, symbol="XAUUSD") -> dict:
        """Get tick data in engine format."""
        resp = self.bridge.get_tick(symbol=symbol)
        return resp.get("data", {}) if resp.get("ok") else {}
    
    def get_account(self) -> dict:
        """Get account in engine format."""
        resp = self.bridge.get_account_info()
        return resp.get("data", {}) if resp.get("ok") else {}
    
    def get_positions(self, symbol="XAUUSD"):
        """Get positions in engine format."""
        resp = self.bridge.get_positions(symbol=symbol)
        return resp


def try_import_old_engines():
    """
    تست می‌کنه آیا موتورهای قدیمی قابل import هستن یا نه.
    بعضی‌شون وابستگی به `MetaTrader5` دارن که روی لینوکس نیست — باید فیکس بشن.
    """
    results = {}
    try:
        import mt5_engine as engine
        results["mt5_engine"] = "OK"
    except Exception as e:
        results["mt5_engine"] = f"FAIL: {type(e).__name__}: {str(e)[:80]}"
    
    try:
        import mt5_xau_smc as smc
        results["mt5_xau_smc"] = "OK"
    except Exception as e:
        results["mt5_xau_smc"] = f"FAIL: {type(e).__name__}: {str(e)[:80]}"
    
    try:
        import mt5_xau_context as context
        results["mt5_xau_context"] = "OK"
    except Exception as e:
        results["mt5_xau_context"] = f"FAIL: {type(e).__name__}: {str(e)[:80]}"
    
    try:
        import mt5_xau_defcon as defcon
        results["mt5_xau_defcon"] = "OK"
    except Exception as e:
        results["mt5_xau_defcon"] = f"FAIL: {type(e).__name__}: {str(e)[:80]}"
    
    return results


if __name__ == "__main__":
    print("=== Hermes Data Adapter Test ===")
    bridge = HermesMT5Bridge()
    connected = bridge.connect()
    print(f"Bridge connected: {connected}")
    
    if connected:
        adapter = HermesDataAdapter(bridge)
        
        # Test data fetching
        rates = adapter.get_rates_as_dict("XAUUSD", "M15", 100)
        print(f"Got {len(rates)} M15 candles")
        if rates:
            print(f"Latest: time={rates[-1]['time']},close={rates[-1]['close']}")
        
        # Test imports
        print("\n=== Old Engine Import Test ===")
        imports = try_import_old_engines()
        for name, status in imports.items():
            print(f"  {name}: {status}")
    
