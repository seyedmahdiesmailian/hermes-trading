#!/usr/bin/env python3
"""
HERMES BRAIN v3
═══════════════════════════════════════
Connect to Windows MT5 via HTTP Bridge.
Falls back to Yahoo Finance for OHLC data.
"""
import requests, urllib.parse, os, warnings
warnings.filterwarnings("ignore")

WIN_IP = os.getenv("HERMES_WIN_IP", "192.168.10.51")
BRIDGE_URL = f"http://{WIN_IP}:5050"

class HermesMT5Bridge:
    def __init__(self, url=BRIDGE_URL):
        self.url = url.rstrip("/")
        self.connected = False

    def _get(self, endpoint, timeout=10):
        try:
            url = f"{self.url}{endpoint}"
            r = requests.get(url, timeout=timeout)
            return r.json() if r.status_code == 200 else {"ok": False, "error": f"HTTP_{r.status_code}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _post(self, endpoint, data, timeout=15):
        try:
            url = f"{self.url}{endpoint}"
            r = requests.post(url, json=data, timeout=timeout)
            return r.json() if r.status_code in (200, 400) else {"ok": False, "error": f"HTTP_{r.status_code}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def connect(self):
        r = self._get("/", timeout=5)
        self.connected = isinstance(r, dict) and "Hermes" in str(r.get("status", ""))
        return self.connected

    def get_account(self):
        return self._get("/api/account")

    def get_tick(self, symbol="XAUUSD"):
        return self._get(f"/api/tick/{symbol}")

    def get_positions(self, symbol="XAUUSD"):
        return self._get(f"/api/positions?symbol={urllib.parse.quote(symbol)}")

    def get_ohlc(self, symbol="XAUUSD", timeframe="M15", count=50):
        return self._get(f"/api/ohlc/{urllib.parse.quote(symbol)}?timeframe={timeframe}&count={count}")

    def send_order(self, direction, lot=0.01, symbol="XAUUSD", sl=None, tp=None):
        return self._post("/api/order", {"type": direction, "volume": lot, "symbol": symbol, "sl": sl, "tp": tp})

    def close_position(self, ticket):
        return self._post("/api/close", {"ticket": ticket})

    def modify_sl(self, ticket, sl):
        # Bridge needs modify endpoint - use order for now
        pass


# Yahoo Finance fallback
import pandas as pd

def fetch_yf_ohlc(symbol="GC=F", m15_count=50, h1_count=20):
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="5d", interval="15m")
        if df.empty:
            return {"ok": False, "error": "no data"}
        m15 = [{"time": int(ts.timestamp()), "open": round(float(row.Open),2),
                "high": round(float(row.High),2), "low": round(float(row.Low),2),
                "close": round(float(row.Close),2), "tick_volume": int(row.Volume)}
               for ts, row in df.iterrows()]
        df_h1 = df.resample("1h").agg({"Open":"first","High":"max","Low":"min","Close":"last"}).dropna()
        h1 = [{"time": int(ts.timestamp()), "open": round(float(row.Open),2),
               "high": round(float(row.High),2), "low": round(float(row.Low),2),
               "close": round(float(row.Close),2)}
              for ts, row in df_h1.iterrows()]
        return {"ok": True, "source": "YAHOO", "m15": m15[-m15_count:], "h1": h1[-h1_count:], "last_price": m15[-1]["close"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}
