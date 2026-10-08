"""Caching Layer - Redis-based caching for performance.

Provides:
- Market data caching
- Analysis result caching
- Rate limiting
- Session management
"""
import json
import hashlib
from datetime import datetime, timedelta
from typing import Any, Optional
from functools import wraps
import time


class CacheBackend:
    """Abstract cache backend."""
    
    def get(self, key: str) -> Optional[Any]:
        raise NotImplementedError
    
    def set(self, key: str, value: Any, ttl: int = 300):
        raise NotImplementedError
    
    def delete(self, key: str):
        raise NotImplementedError
    
    def clear(self):
        raise NotImplementedError


class MemoryCache(CacheBackend):
    """In-memory cache (fallback when Redis unavailable)."""
    
    def __init__(self):
        self._cache = {}
        self._expiry = {}
    
    def get(self, key: str) -> Optional[Any]:
        # Check expiry
        if key in self._expiry:
            if time.time() > self._expiry[key]:
                del self._cache[key]
                del self._expiry[key]
                return None
        
        return self._cache.get(key)
    
    def set(self, key: str, value: Any, ttl: int = 300):
        self._cache[key] = value
        self._expiry[key] = time.time() + ttl
    
    def delete(self, key: str):
        self._cache.pop(key, None)
        self._expiry.pop(key, None)
    
    def clear(self):
        self._cache.clear()
        self._expiry.clear()


class RedisCache(CacheBackend):
    """Redis-based cache (production)."""
    
    def __init__(self, host: str = 'localhost', port: int = 6379, db: int = 0):
        try:
            import redis
            self.redis = redis.Redis(
                host=host,
                port=port,
                db=db,
                decode_responses=True,
                socket_connect_timeout=2
            )
            # Test connection
            self.redis.ping()
            self.available = True
        except Exception as e:
            print(f"Redis unavailable, falling back to memory cache: {e}")
            self.available = False
            self._fallback = MemoryCache()
    
    def get(self, key: str) -> Optional[Any]:
        if not self.available:
            return self._fallback.get(key)
        
        try:
            value = self.redis.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception:
            return None
    
    def set(self, key: str, value: Any, ttl: int = 300):
        if not self.available:
            return self._fallback.set(key, value, ttl)
        
        try:
            self.redis.setex(key, ttl, json.dumps(value))
        except Exception:
            pass
    
    def delete(self, key: str):
        if not self.available:
            return self._fallback.delete(key)
        
        try:
            self.redis.delete(key)
        except Exception:
            pass
    
    def clear(self):
        if not self.available:
            return self._fallback.clear()
        
        try:
            self.redis.flushdb()
        except Exception:
            pass


class Cache:
    """Main cache interface."""
    
    _instance = None
    
    def __init__(self, backend: Optional[CacheBackend] = None):
        if backend:
            self.backend = backend
        else:
            # Try Redis first, fallback to memory
            try:
                self.backend = RedisCache()
            except Exception:
                self.backend = MemoryCache()
    
    @classmethod
    def instance(cls) -> 'Cache':
        """Singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def get(self, key: str) -> Optional[Any]:
        return self.backend.get(key)
    
    def set(self, key: str, value: Any, ttl: int = 300):
        self.backend.set(key, value, ttl)
    
    def delete(self, key: str):
        self.backend.delete(key)
    
    def clear(self):
        self.backend.clear()


def cached(ttl: int = 300, key_prefix: str = ""):
    """Decorator for caching function results.
    
    Args:
        ttl: Time to live in seconds
        key_prefix: Optional prefix for cache key
    
    Example:
        @cached(ttl=60, key_prefix='analysis')
        def analyze_market(symbol, timeframe):
            # expensive operation
            return result
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            key_parts = [key_prefix or func.__name__]
            key_parts.extend(str(arg) for arg in args)
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            
            cache_key = hashlib.md5(
                ":".join(key_parts).encode()
            ).hexdigest()
            
            # Try cache first
            cache = Cache.instance()
            cached_result = cache.get(cache_key)
            
            if cached_result is not None:
                return cached_result
            
            # Cache miss - compute
            result = func(*args, **kwargs)
            
            # Store in cache
            cache.set(cache_key, result, ttl)
            
            return result
        
        return wrapper
    return decorator


# Market data cache helpers
def cache_market_data(symbol: str, timeframe: str, data: Any, ttl: int = 60):
    """Cache market data."""
    key = f"market:{symbol}:{timeframe}"
    Cache.instance().set(key, data, ttl)


def get_cached_market_data(symbol: str, timeframe: str) -> Optional[Any]:
    """Get cached market data."""
    key = f"market:{symbol}:{timeframe}"
    return Cache.instance().get(key)


def invalidate_market_cache(symbol: str):
    """Invalidate all market data for symbol."""
    # Note: In production with Redis, use SCAN for pattern matching
    # For now, this is a placeholder
    pass
