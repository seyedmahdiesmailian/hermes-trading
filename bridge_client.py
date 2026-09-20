#!/usr/bin/env python3
from __future__ import annotations

import os
import urllib.parse
import requests

DEFAULT_WIN_IP = "192.168.10.51"


def bridge_url() -> str:
    """Resolve the Bridge URL at call time, not when this module is imported.

    Import-time configuration made a long-lived daemon retain an old endpoint
    when its environment was loaded or changed after another module imported
    bridge_client. Explicit URL wins; otherwise derive from the documented
    Windows host knob.
    """
    explicit = os.getenv("HERMES_BRIDGE_URL")
    if explicit:
        return explicit.rstrip("/")
    return f"http://{os.getenv('HERMES_WIN_IP', DEFAULT_WIN_IP)}:5050"


def bridge_token() -> str | None:
    """Resolve the Bridge token at client construction time."""
    return os.getenv("HERMES_BRIDGE_TOKEN") or None


# Backward-compatible snapshots for scripts that display/import these names.
# New network clients must use BridgeClient() or bridge_url(), both of which
# resolve at call time.
WIN_IP = os.getenv("HERMES_WIN_IP", DEFAULT_WIN_IP)
BRIDGE_URL = bridge_url()


class BridgeClient:
    def __init__(self, url: str | None = None, token: str | None = None):
        self.url = (url if url is not None else bridge_url()).rstrip("/")
        self.token = bridge_token() if token is None else token
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

    def get_price_band(self, symbol="XAUUSD", hours=24):
        """(low, high) traded over the last `hours` H1 candles.

        b72: used to disambiguate abbreviated signal prices ('24' → 4424 vs
        4524). Returns None when the bridge is unreachable — callers must
        treat that as 'no band', never as a reason to drop the signal.
        """
        try:
            r = self.get_rates(symbol, "H1", max(6, int(hours)))
            rows = r.get("rates") or r.get("candles") or r.get("data") or []
            lows, highs = [], []
            for row in rows:
                if isinstance(row, dict):
                    lo, hi = row.get("low"), row.get("high")
                else:
                    lo, hi = row[3], row[4]
                if lo:
                    lows.append(float(lo))
                if hi:
                    highs.append(float(hi))
            if lows and highs:
                return (min(lows), max(highs))
        except Exception:
            pass
        return None

    # execution endpoints — used by the autonomous executor and signal listener
    def send_order(self, side, lot, symbol="XAUUSD", sl=None, tp=None):
        return self._post("/api/order", {"type": side.lower(), "volume": float(lot), "symbol": symbol, "sl": sl, "tp": tp})
    def close_position(self, ticket): return self._post("/api/close", {"ticket": int(ticket)})
    def partial_close(self, ticket, percent): return self._post("/api/partial", {"ticket": int(ticket), "percent": float(percent)})
    def modify_position(self, ticket, sl=None, tp=None): return self._post("/api/modify", {"ticket": int(ticket), "sl": sl, "tp": tp})

    # b70 — pending (limit) orders for signals whose entry price hasn't been reached
    def send_pending(self, side, lot, symbol="XAUUSD", price=None, sl=None, tp=None):
        r = self._post("/api/pending", {"type": 2 if str(side).upper() == "BUY" else 3,
                                        "volume": float(lot), "symbol": symbol,
                                        "price": float(price), "sl": sl, "tp": tp})
        if r.get("ok") and r.get("order") and not r.get("ticket"):
            r["ticket"] = int(r["order"])   # bridge returns 'order', engine reads 'ticket'
        return r

    def get_orders(self):
        r = self._get("/api/pending")       # live bridge lists active orders here
        if isinstance(r, dict) and "orders" in r and "data" not in r:
            r["data"] = r["orders"]
        return r

    def cancel_order(self, ticket): return self._post("/api/cancel", {"ticket": int(ticket)})
