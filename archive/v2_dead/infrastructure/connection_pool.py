"""Connection Pool - Reusable connections for MT5 bridge.

Provides:
- HTTP session pooling
- Automatic retry
- Circuit breaker
- Request rate limiting
"""
import time
import requests
from typing import Optional
from datetime import datetime, timedelta
from enum import Enum


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if recovered


class CircuitBreaker:
    """Circuit breaker pattern for fault tolerance."""
    
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED
    
    def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker."""
        if self.state == CircuitState.OPEN:
            # Check if timeout passed
            if self.last_failure_time and \
               (datetime.now() - self.last_failure_time).seconds >= self.timeout:
                self.state = CircuitState.HALF_OPEN
                self.failures = 0
            else:
                raise Exception("Circuit breaker is OPEN")
        
        try:
            result = func(*args, **kwargs)
            
            # Success - reset if was half-open
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.CLOSED
                self.failures = 0
            
            return result
        
        except Exception as e:
            self.failures += 1
            self.last_failure_time = datetime.now()
            
            if self.failures >= self.failure_threshold:
                self.state = CircuitState.OPEN
            
            raise e
    
    def reset(self):
        """Manually reset circuit breaker."""
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.last_failure_time = None


class RateLimiter:
    """Token bucket rate limiter."""
    
    def __init__(self, rate: int, per: int = 60):
        """Initialize rate limiter.
        
        Args:
            rate: Number of requests allowed
            per: Time window in seconds
        """
        self.rate = rate
        self.per = per
        self.allowance = rate
        self.last_check = time.time()
    
    def allow(self) -> bool:
        """Check if request is allowed."""
        current = time.time()
        time_passed = current - self.last_check
        self.last_check = current
        
        # Refill tokens
        self.allowance += time_passed * (self.rate / self.per)
        
        if self.allowance > self.rate:
            self.allowance = self.rate
        
        if self.allowance < 1.0:
            return False
        
        self.allowance -= 1.0
        return True
    
    def wait_if_needed(self):
        """Block until request is allowed."""
        while not self.allow():
            time.sleep(0.1)


class ConnectionPool:
    """HTTP connection pool for MT5 bridge."""
    
    def __init__(
        self,
        base_url: str,
        token: str,
        pool_size: int = 10,
        max_retries: int = 3,
        timeout: int = 10,
        rate_limit: Optional[int] = None
    ):
        self.base_url = base_url.rstrip('/')
        self.token = token
        
        # Create session with connection pooling
        self.session = requests.Session()
        
        # Connection pool adapter
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=pool_size,
            pool_maxsize=pool_size,
            max_retries=requests.adapters.Retry(
                total=max_retries,
                backoff_factor=0.5,
                status_forcelist=[500, 502, 503, 504]
            )
        )
        
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        # Headers
        self.session.headers.update({
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        })
        
        self.timeout = timeout
        
        # Circuit breaker
        self.circuit_breaker = CircuitBreaker()
        
        # Rate limiter (optional)
        self.rate_limiter = RateLimiter(rate_limit) if rate_limit else None
    
    def request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> requests.Response:
        """Make HTTP request with pooling and protection.
        
        Args:
            method: HTTP method (GET, POST, etc)
            endpoint: API endpoint (without base URL)
            **kwargs: Additional request arguments
        
        Returns:
            Response object
        """
        # Rate limiting
        if self.rate_limiter:
            self.rate_limiter.wait_if_needed()
        
        # Build URL
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        # Set timeout if not provided
        if 'timeout' not in kwargs:
            kwargs['timeout'] = self.timeout
        
        # Execute with circuit breaker
        def _request():
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        
        return self.circuit_breaker.call(_request)
    
    def get(self, endpoint: str, **kwargs):
        """GET request."""
        return self.request('GET', endpoint, **kwargs)
    
    def post(self, endpoint: str, **kwargs):
        """POST request."""
        return self.request('POST', endpoint, **kwargs)
    
    def close(self):
        """Close session and release connections."""
        self.session.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
