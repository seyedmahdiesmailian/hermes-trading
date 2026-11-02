"""Async MT5 Gateway - High-performance async version.

Uses asyncio and aiohttp for non-blocking I/O.
Significantly faster for parallel operations.
"""
import asyncio
import aiohttp
from typing import List, Optional
from datetime import datetime, timezone

from brain.domain.entities.market import Candle
from infrastructure.cache import Cache


class AsyncMT5Gateway:
    """Async version of MT5Gateway for high-performance scenarios."""
    
    def __init__(self, bridge_url: str, token: str, timeout: int = 10):
        self.bridge_url = bridge_url.rstrip('/')
        self.token = token
        self.timeout = timeout
        self._headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        """Context manager entry."""
        self._session = aiohttp.ClientSession(
            headers=self._headers,
            timeout=aiohttp.ClientTimeout(total=self.timeout),
            connector=aiohttp.TCPConnector(limit=10)
        )
        return self
    
    async def __aexit__(self, *args):
        """Context manager exit."""
        if self._session:
            await self._session.close()
    
    async def fetch_multiple_candles(
        self,
        requests: List[tuple[str, str, int]]
    ) -> List[List[Candle]]:
        """Fetch multiple candle sets in parallel.
        
        Args:
            requests: List of (symbol, timeframe, count) tuples
        
        Returns:
            List of candle lists (same order as requests)
        
        Example:
            async with AsyncMT5Gateway(...) as gateway:
                results = await gateway.fetch_multiple_candles([
                    ('XAUUSD', 'M15', 500),
                    ('EURUSD', 'H1', 200),
                ])
        """
        tasks = [
            self._fetch_candles_async(symbol, timeframe, count)
            for symbol, timeframe, count in requests
        ]
        
        return await asyncio.gather(*tasks)
    
    async def _fetch_candles_async(
        self,
        symbol: str,
        timeframe: str,
        count: int = 500
    ) -> List[Candle]:
        """Async fetch candles."""
        # Check cache
        cache_key = f"candles:{symbol}:{timeframe}:{count}"
        cached = Cache.instance().get(cache_key)
        
        if cached:
            return [Candle(**c) for c in cached]
        
        # Fetch from bridge
        url = f"{self.bridge_url}/api/ohlc/{symbol}"
        params = {'timeframe': timeframe, 'count': count}
        
        async with self._session.get(url, params=params) as response:
            response.raise_for_status()
            data = await response.json()
        
        if not data.get('ok'):
            raise Exception(f"Failed to fetch candles: {data.get('error')}")
        
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
        
        # Cache result
        Cache.instance().set(
            cache_key,
            [{'time': c.time.isoformat(), 'open': c.open, 'high': c.high,
              'low': c.low, 'close': c.close, 'volume': c.volume}
             for c in candles],
            ttl=30
        )
        
        return candles


# Example usage
async def fetch_multi_symbol_data():
    """Example: Fetch data for multiple symbols in parallel."""
    async with AsyncMT5Gateway(
        bridge_url="http://192.168.10.51:5050",
        token="your-token"
    ) as gateway:
        
        results = await gateway.fetch_multiple_candles([
            ('XAUUSD', 'M15', 500),
            ('XAUUSD', 'H1', 200),
            ('XAUUSD', 'H4', 100),
        ])
        
        for i, candles in enumerate(results):
            print(f"Result {i}: {len(candles)} candles")
