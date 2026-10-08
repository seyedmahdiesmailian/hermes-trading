"""MT5 Gateway — MetaTrader 5 integration.

Implements market data and execution ports for MT5.
"""

from infrastructure.cache import Cache, cached, cache_market_data, get_cached_market_data
from infrastructure.connection_pool import ConnectionPool
import requests
from typing import List
from datetime import datetime, timezone

from brain.domain.entities.market import MarketState, Candle
from brain.domain.entities.account import AccountState
from brain.domain.value_objects.timeframe import TimeFrame
from brain.domain.repositories.market_data_repo import IMarketDataRepository


class MT5Gateway(IMarketDataRepository):
    """MT5 Gateway — connects to Windows MT5 bridge.
    
    Communicates with MT5 via HTTP bridge on Windows machine.
    
    Bridge URL: http://192.168.10.51:5050
    
    Endpoints:
    - GET /api/account → account info
    - GET /api/positions → open positions
    - GET /api/tick/{symbol} → current tick
    - GET /api/ohlc/{symbol}/{timeframe} → candles
    - POST /api/order → place order
    
    Usage:
        gateway = MT5Gateway(
            bridge_url="http://192.168.10.51:5050",
            token="your-bearer-token"
        )
        
        market_state = gateway.get_current_state("XAUUSD", M15)
    """
    
    def __init__(self, bridge_url: str, token: str, timeout: int = 10):
        self.bridge_url = bridge_url.rstrip('/')
        self.token = token
        self.timeout = timeout
        
        # Use connection pool for better performance
        self.pool = ConnectionPool(
            base_url=bridge_url,
            token=token,
            pool_size=10,
            max_retries=3,
            timeout=timeout,
            rate_limit=120  # 120 req/min
        )
        
        # Keep old headers for compatibility
        self._headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
    
    def get_current_state(
        self, 
        symbol: str, 
        timeframe: TimeFrame,
        bars_count: int = 500
    ) -> MarketState:
        """Get current market state from MT5.
        
        Args:
            symbol: Symbol (e.g., "XAUUSD")
            timeframe: Timeframe
            bars_count: Number of bars to fetch
            
        Returns:
            MarketState object
        """
        # Get current tick
        tick = self.get_tick(symbol)
        current_price = tick['bid']  # Use bid for current price
        
        # Get candles
        tf_string = timeframe.to_string()
        candles = self._fetch_candles(symbol, tf_string, bars_count)
        
        return MarketState(
            symbol=symbol,
            timeframe=tf_string,
            candles=candles,
            current_price=current_price,
            timestamp=datetime.now(timezone.utc),
            bid=tick['bid'],
            ask=tick['ask']
        )
    
    def get_candles(
        self,
        symbol: str,
        timeframe: TimeFrame,
        start: datetime,
        end: datetime
    ) -> List[Candle]:
        """Get historical candles.
        
        Args:
            symbol: Symbol
            timeframe: Timeframe
            start: Start datetime
            end: End datetime
            
        Returns:
            List of Candle objects
        """
        # MT5 bridge doesn't support date range yet
        # Fall back to recent bars
        tf_string = timeframe.to_string()
        return self._fetch_candles(symbol, tf_string, 500)
    
    def get_current_price(self, symbol: str) -> float:
        """Get current market price.
        
        Args:
            symbol: Symbol
            
        Returns:
            Current bid price
        """
        tick = self.get_tick(symbol)
        return tick['bid']
    
    def get_tick(self, symbol: str) -> dict:
        """Get current tick with bid/ask.
        
        Args:
            symbol: Symbol
            
        Returns:
            Dict with bid, ask, time
        """
        url = f"{self.bridge_url}/api/tick/{symbol}"
        
        try:
            response = requests.get(
                url,
                headers=self._headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            if not data.get('ok'):
                raise Exception(f"MT5 error: {data.get('error', 'unknown')}")
            
            return {
                'bid': float(data['bid']),
                'ask': float(data['ask']),
                'time': data.get('time', datetime.now(timezone.utc).isoformat())
            }
        
        except requests.RequestException as e:
            raise Exception(f"MT5 connection failed: {e}")
    
    def get_account_state(self) -> AccountState:
        """Get account state from MT5.
        
        Returns:
            AccountState object
        """
        url = f"{self.bridge_url}/api/account"
        
        try:
            response = requests.get(
                url,
                headers=self._headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            if not data.get('ok'):
                raise Exception(f"MT5 error: {data.get('error', 'unknown')}")
            
            return AccountState(
                balance=float(data['balance']),
                equity=float(data['equity']),
                margin_free=float(data['margin_free']),
                timestamp=datetime.now(timezone.utc)
            )
        
        except requests.RequestException as e:
            raise Exception(f"MT5 connection failed: {e}")
    
    def _fetch_candles(self, symbol: str, timeframe: str, count: int = 500) -> List[Candle]:
        """Fetch candles from MT5 with caching.
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe string
            count: Number of candles
            
        Returns:
            List of Candle objects
        """
        # Check cache first (30 second TTL)
        cache_key = f"candles:{symbol}:{timeframe}:{count}"
        cached_data = Cache.instance().get(cache_key)
        
        if cached_data:
            return [Candle(**c) for c in cached_data]
        
        # Cache miss - fetch from MT5
        """Fetch candles from MT5.
        
        Args:
            symbol: Symbol
            timeframe: Timeframe string (M5, M15, etc)
            count: Number of bars
            
        Returns:
            List of Candle objects
        """
        url = f"{self.bridge_url}/api/ohlc/{symbol}"
        params = {'timeframe': timeframe, 'count': count}
        
        try:
            response = requests.get(
                url,
                headers=self._headers,
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            if not data.get('ok'):
                raise Exception(f"MT5 error: {data.get('error', 'unknown')}")
            
            candles = []
            for bar in data.get('data', []):
                candle = Candle(
                    time=datetime.fromtimestamp(bar['time'], tz=timezone.utc),
                    open=float(bar['open']),
                    high=float(bar['high']),
                    low=float(bar['low']),
                    close=float(bar['close']),
                    volume=int(bar.get('tick_volume', bar.get('volume', 0)))
                )
                candles.append(candle)
            
            return candles
        
        except requests.RequestException as e:
            raise Exception(f"MT5 connection failed: {e}")
    
    def health_check(self) -> bool:
        """Check if MT5 bridge is accessible.
        
        Returns:
            True if healthy, False otherwise
        """
        url = f"{self.bridge_url}/api/health"
        
        try:
            response = requests.get(url, timeout=5)
            return response.ok
        except:
            return False
    
    def __repr__(self) -> str:
        return f"MT5Gateway({self.bridge_url})"
    
    def place_order(self, symbol: str, order_type: str, volume: float,
                   price: float, sl: float, tp: float, comment: str = "") -> dict:
        """Place a new order.
        
        Args:
            symbol: Trading symbol (e.g., "XAUUSD")
            order_type: "BUY" or "SELL"
            volume: Lot size
            price: Entry price (0 for market)
            sl: Stop loss
            tp: Take profit
            comment: Order comment
        
        Returns:
            dict with order result: {"ok": bool, "ticket": int, "error": str}
        """
        url = f"{self.bridge_url}/api/order"
        
        payload = {
            "symbol": symbol,
            "type": order_type.upper(),
            "volume": volume,
            "price": price,
            "sl": sl,
            "tp": tp,
            "comment": comment or "Hermes V2"
        }
        
        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def close_position(self, ticket: int) -> dict:
        """Close an open position.
        
        Args:
            ticket: Position ticket number
        
        Returns:
            dict with result: {"ok": bool, "ticket": int, "error": str}
        """
        url = f"{self.bridge_url}/api/close"
        
        try:
            response = requests.post(
                url,
                json={"ticket": ticket},
                headers=self._headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def modify_position(self, ticket: int, sl: float = None, tp: float = None) -> dict:
        """Modify SL/TP of an open position.
        
        Args:
            ticket: Position ticket number
            sl: New stop loss (None = no change)
            tp: New take profit (None = no change)
        
        Returns:
            dict with result: {"ok": bool, "error": str}
        """
        url = f"{self.bridge_url}/api/modify"
        
        payload = {"ticket": ticket}
        if sl is not None:
            payload["sl"] = sl
        if tp is not None:
            payload["tp"] = tp
        
        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}
