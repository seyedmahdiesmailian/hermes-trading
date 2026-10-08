"""Fundamental Analysis - News Calendar Integration.

Integrates economic calendar for fundamental analysis.
"""
import json
import urllib.request
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import List


@dataclass
class EconomicEvent:
    """Economic calendar event."""
    time: datetime
    currency: str
    event: str
    impact: str  # HIGH, MEDIUM, LOW
    forecast: str
    previous: str


class NewsCalendar:
    """Economic calendar service."""
    
    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.cache = []
        self.cache_time = None
    
    def get_upcoming_events(self, hours: int = 24) -> List[EconomicEvent]:
        """Get upcoming high-impact events.
        
        Args:
            hours: Look ahead window
        
        Returns:
            List of economic events
        """
        # Cache for 1 hour
        if self.cache and self.cache_time:
            age = (datetime.now(timezone.utc) - self.cache_time).seconds
            if age < 3600:
                return self._filter_events(self.cache, hours)
        
        # Fetch from API (example - needs real API)
        try:
            events = self._fetch_events()
            self.cache = events
            self.cache_time = datetime.now(timezone.utc)
            return self._filter_events(events, hours)
        except Exception as e:
            print(f"Failed to fetch news: {e}")
            return []
    
    def _fetch_events(self) -> List[EconomicEvent]:
        """Fetch events from calendar API.
        
        TODO: Integrate with real API:
        - Forex Factory API
        - Investing.com calendar
        - Trading Economics
        """
        # Mock data for now
        now = datetime.now(timezone.utc)
        return [
            EconomicEvent(
                time=now + timedelta(hours=2),
                currency="USD",
                event="NFP (Non-Farm Payrolls)",
                impact="HIGH",
                forecast="200K",
                previous="180K"
            )
        ]
    
    def _filter_events(self, events: List[EconomicEvent], hours: int) -> List[EconomicEvent]:
        """Filter events by time window and impact."""
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours)
        
        return [
            e for e in events
            if now <= e.time <= cutoff and e.impact == "HIGH"
        ]
    
    def has_high_impact_news(self, symbol: str, hours: int = 2) -> tuple[bool, str]:
        """Check if high-impact news is coming.
        
        Args:
            symbol: Trading symbol (e.g., "XAUUSD")
            hours: Look ahead window
        
        Returns:
            (has_news, reason)
        """
        events = self.get_upcoming_events(hours)
        
        if not events:
            return False, ""
        
        # Map symbol to currencies
        currencies = self._get_currencies(symbol)
        
        relevant = [
            e for e in events
            if e.currency in currencies
        ]
        
        if relevant:
            event_names = ", ".join(e.event for e in relevant)
            return True, f"High-impact news in {hours}h: {event_names}"
        
        return False, ""
    
    def _get_currencies(self, symbol: str) -> List[str]:
        """Extract currencies from symbol."""
        # XAUUSD -> XAU (Gold), USD
        if symbol == "XAUUSD":
            return ["USD", "XAU"]
        elif len(symbol) == 6:
            return [symbol[:3], symbol[3:]]
        return []


class FundamentalAnalyzer:
    """Fundamental analysis service."""
    
    def __init__(self, news_calendar: NewsCalendar):
        self.news_calendar = news_calendar
    
    def analyze(self, symbol: str) -> dict:
        """Perform fundamental analysis.
        
        Args:
            symbol: Trading symbol
        
        Returns:
            Analysis result with score and reasoning
        """
        # Check news
        has_news_2h, news_2h = self.news_calendar.has_high_impact_news(symbol, hours=2)
        has_news_24h, news_24h = self.news_calendar.has_high_impact_news(symbol, hours=24)
        
        # Scoring
        score = 1.0
        reasons = []
        
        if has_news_2h:
            score *= 0.3  # High penalty for imminent news
            reasons.append(news_2h)
        elif has_news_24h:
            score *= 0.7  # Moderate penalty
            reasons.append(news_24h)
        
        return {
            "score": score,
            "has_imminent_news": has_news_2h,
            "has_upcoming_news": has_news_24h,
            "reasoning": "; ".join(reasons) if reasons else "No high-impact news"
        }
