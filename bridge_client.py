#!/usr/bin/env python3
from __future__ import annotations

import os
import urllib.parse
import requests

WIN_IP = os.getenv("HERMES_WIN_IP", "192.168.10.51")
BRIDGE_URL = os.getenv("HERMES_BRIDGE_URL", f"http://{WIN_IP}:5050")

class BridgeClient:
    def __init__(self, url: str = BRIDGE_URL, token: str | None = None):
        self.url = url.rstrip("/")
        self.token = token or os.getenv("HERMES_BRIDGE_TOKEN")
        self.connected = False

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _get(self, endpoint: str, timeout: int = 8) -> dict:
        try:
            r = requests.get(f"{self.url}{endpoint}", headers=self._headers(), timeout=timeout)
            try:
                data = r.json()
            except Exception:
                data = {"raw": r.text[:500]}
            if r.status_code == 200:
                return data if isinstance(data, dict) else {"ok": True, "data": data}
            return {"ok": False, "error": f"HTTP_{r.status_code}", "data": data}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _post(self, endpoint: str, payload: dict, timeout: int = 12) -> dict:
        try:
            r = requests.post(f"{self.url}{endpoint}", json=payload, headers=self._headers(), timeout=timeout)
            try:
                data = r.json()
            except Exception:
                data = {"raw": r.text[:500]}
            if r.status_code in (200, 400):
                return data if isinstance(data, dict) else {"ok": True, "data": data}
            return {"ok": False, "error": f"HTTP_{r.status_code}", "data": data}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def health(self):
        # prefer real health endpoint; fallback to root for old bridge
        h = self._get("/health", timeout=5)
        if h.get("ok"):
            self.connected = True
            return h
        r = self._get("/", timeout=5)
        self.connected = isinstance(r, dict) and (r.get("ok") is True or "Hermes" in str(r))
        return {"ok": self.connected, "health": h, "root": r}

    def get_account(self): return self._get("/api/account")
    def get_tick(self, symbol="XAUUSD"): return self._get(f"/api/tick/{urllib.parse.quote(symbol)}")
    def get_positions(self, symbol="XAUUSD"): return self._get(f"/api/positions?symbol={urllib.parse.quote(symbol)}")

    def get_rates(self, symbol="XAUUSD", timeframe="M15", count=80):
        # old OHLC endpoint (what the actual server exposes)
        r = self._get(f"/api/ohlc/{urllib.parse.quote(symbol)}?timeframe={timeframe}&count={count}")
        if r.get("ok"):
            return r
        # new standard endpoint fallback
        return self._get(f"/api/rates/{urllib.parse.quote(symbol)}?tf={timeframe}&count={count}")

    def get_history_deals(self, symbol="XAUUSD", days=7):
        return self._get(f"/api/history/deals?symbol={urllib.parse.quote(symbol)}&days={int(days)}")

    # execution endpoints are available but called only by approval_gate after explicit command
    def send_order(self, side, lot, symbol="XAUUSD", sl=None, tp=None):
        return self._post("/api/order", {"type": side.lower(), "volume": float(lot), "symbol": symbol, "sl": sl, "tp": tp})
    def close_position(self, ticket): return self._post("/api/close", {"ticket": int(ticket)})
    def partial_close(self, ticket, percent): return self._post("/api/partial", {"ticket": int(ticket), "percent": float(percent)})
    def modify_position(self, ticket, sl=None, tp=None): return self._post("/api/modify", {"ticket": int(ticket), "sl": sl, "tp": tp})
