"""Economic Calendar — fetches high-impact news events.

Uses ForexFactory public data. Falls back to cached data if unavailable.
"""
from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

from engines import paths  # resolved at CALL time so tests can redirect the tree


def _cache_file() -> Path:
    return paths.calendar_cache()


CACHE_MAX_AGE_HOURS = 6

# High-impact currencies for XAUUSD (Gold moves on USD, EUR, JPY)
HIGH_IMPACT_CURRENCIES = {"USD", "EUR", "JPY", "GBP"}

# High-impact event keywords
HIGH_IMPACT_KEYWORDS = {
    "non-farm", "nfp", "payroll", "interest rate", "fomc", "fed",
    "cpi", "ppi", "gdp", "employment", "unemployment", "inflation",
    "retail sales", "pmi", "ism", "trade balance", "consumer confidence",
    "jolts", "job openings", "adp", "beige book",
    "ecb", "boj", "boe", "rate decision",
    "oil", "crude", "opec",
}

IMPACT_KEYWORDS_FA = {
    "اشتغال", "بیکاری", "تورم", "نرخ بهره", "تولید ناخالص",
    "فروش خرده فروشی", "شاخص", "جلسه", "تصمیم",
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _load_cache() -> dict | None:
    cache_file = _cache_file()
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding='utf-8'))
        cached_at = datetime.fromisoformat(data.get("cached_at", ""))
        if (_now_utc() - cached_at) > timedelta(hours=CACHE_MAX_AGE_HOURS):
            return None
        return data
    except Exception:
        return None


def _save_cache(data: dict):
    data["cached_at"] = _now_utc().isoformat()
    paths.write_json_atomic(_cache_file(), data, indent=2)


def _fetch_forexfactory() -> dict | None:
    """Attempt to fetch economic calendar from ForexFactory."""
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        req = urllib.request.Request(url, headers={"User-Agent": "HermesTrading/1.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        raw = json.loads(resp.read().decode('utf-8'))
        events = []
        for item in raw:
            # FF JSON field is 'country' (USD/EUR/...); 'currency' does not
            # exist → every event used to land with empty currency, which
            # silently passed the currency filter in macro_filter.
            currency = str(item.get("currency") or item.get("country") or "").upper()
            impact = str(item.get("impact", "")).lower()
            if impact not in {"high", "medium", "low"}:
                # Try to map star ratings
                impact = "medium"
            events.append({
                "title": item.get("title", ""),
                "currency": currency,
                "impact": impact,
                "date": item.get("date", ""),
                "time": item.get("time", ""),
                "forecast": item.get("forecast", ""),
                "previous": item.get("previous", ""),
            })
        return {"source": "forexfactory", "events": events}
    except Exception:
        return None


def _fetch_investing_com() -> dict | None:
    """Fallback: try Investing.com economic calendar API."""
    try:
        today = _now_utc()
        start = today.strftime("%Y-%m-%d")
        end = (today + timedelta(days=7)).strftime("%Y-%m-%d")
        url = f"https://economic-calendar.tradingview.com/events?from={start}T00:00:00Z&to={end}T23:59:59Z&countries=US"
        req = urllib.request.Request(url, headers={"User-Agent": "HermesTrading/1.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        raw = json.loads(resp.read().decode('utf-8'))
        events = []
        data = raw.get("result", {}).get("data", [])
        for item in data:
            events.append({
                "title": item.get("title", ""),
                "currency": "USD",
                "impact": item.get("importance", "medium"),
                "date": item.get("date", ""),
                "time": "",
                "forecast": str(item.get("forecast", "")),
                "previous": str(item.get("previous", "")),
            })
        return {"source": "tradingview", "events": events}
    except Exception:
        return None


def fetch_economic_calendar(force: bool = False) -> dict:
    """Fetch economic calendar. Uses cache if fresh."""
    if not force:
        cached = _load_cache()
        if cached:
            return cached

    result = _fetch_forexfactory()
    if not result or not result.get("events"):
        result = _fetch_investing_com()
    if not result:
        result = {"source": "unavailable", "events": []}

    _save_cache(result)
    return result


def _is_high_impact(event: dict) -> bool:
    impact = str(event.get("impact", "")).lower()
    if impact == "high":
        return True
    currency = str(event.get("currency", "")).upper()
    if currency not in HIGH_IMPACT_CURRENCIES:
        return False
    title = str(event.get("title", "")).lower()
    for kw in HIGH_IMPACT_KEYWORDS:
        if kw in title:
            return True
    return False


def get_upcoming_events(hours_ahead: int = 24) -> dict:
    """Get upcoming high-impact events within the next N hours."""
    calendar = fetch_economic_calendar()
    now = _now_utc()
    cutoff = now + timedelta(hours=hours_ahead)

    high_impact = []
    medium_impact = []

    for event in calendar.get("events", []):
        if _is_high_impact(event):
            high_impact.append(event)
        else:
            medium_impact.append(event)

    return {
        "source": calendar.get("source", "unknown"),
        "high_impact": high_impact[:10],
        "medium_impact": medium_impact[:10],
        "total_events": len(calendar.get("events", [])),
        "fetched_at": now.isoformat(),
    }


def get_news_blackout_check(now: datetime | None = None, blackout_minutes: int = 30) -> dict:
    """Check if we're inside a news blackout window."""
    now = now or _now_utc()
    upcoming = get_upcoming_events(hours_ahead=1)
    high_impact = upcoming.get("high_impact", [])

    if high_impact:
        return {
            "allowed": False,
            "reason": "high_impact_news_upcoming",
            "events": high_impact,
            "blackout_until": (now + timedelta(minutes=blackout_minutes)).isoformat(),
        }
    return {"allowed": True, "reason": None, "events": []}
