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
# b30 STALENESS BUDGET: a fetch failure must not blind us instantly, but it
# must not disable the news blackout forever either. ForexFactory is flaky on
# this box (measured 2026-08-30: 2 of 4 direct fetches failed), so an expired
# cache up to HARD_STALE_HOURS is still usable (marked stale=True). Beyond
# that — or with no cache at all — the calendar is 'unavailable' and the entry
# paths FAIL CLOSED (no new entries while we cannot see the news).
HARD_STALE_HOURS = 24

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


def _load_cache(max_age_hours: float | None = None) -> dict | None:
    """Return the cached calendar, or None if missing/unreadable/too old.

    b30: `max_age_hours=None` uses the HARD_STALE budget (not the 6h refresh
    window) and stamps the result `stale=True` past 6h, so callers can tell
    'recent' from 'last thing we managed to fetch'.
    """
    cache_file = _cache_file()
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding='utf-8'))
    except Exception:
        return None
    # An empty/untrustworthy payload is not a cache worth serving.
    if not _has_events(data):
        return None
    try:
        cached_at = datetime.fromisoformat(data.get("cached_at", ""))
    except Exception:
        return None
    if cached_at.tzinfo is None:
        cached_at = cached_at.replace(tzinfo=timezone.utc)
    age_h = (_now_utc() - cached_at).total_seconds() / 3600.0
    limit = HARD_STALE_HOURS if max_age_hours is None else max_age_hours
    if age_h > limit:
        return None
    data["stale"] = age_h > CACHE_MAX_AGE_HOURS
    return data


def _has_events(data: dict | None) -> bool:
    """A payload only counts as a real calendar if it carries events.

    b30: the old code cached {'source':'unavailable','events':[]} after a
    failed fetch and then served THAT as 'no news scheduled' for 6 hours —
    a dead calendar silently meant an empty news blackout.
    """
    return bool(isinstance(data, dict) and data.get("events"))


def _save_cache(data: dict):
    if not _has_events(data):
        # Never overwrite a good cache with an empty one (b30).
        return
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
    """Fetch economic calendar. Uses cache if fresh.

    b30 ordering matters: try the FRESH cache → refetch → only if the refetch
    failed fall back to a STALE cache (within HARD_STALE_HOURS) → otherwise
    return an explicitly 'unavailable' payload with NO events. Callers treat
    source='unavailable' as fail-closed, never as 'no news'.
    """
    if not force:
        cached = _load_cache(max_age_hours=CACHE_MAX_AGE_HOURS)
        if cached:
            cached.setdefault("stale", False)
            return cached

    result = _fetch_forexfactory()
    if not result or not result.get("events"):
        result = _fetch_investing_com()
    if result and result.get("events"):
        _save_cache(result)
        result["stale"] = False
        return result

    # Both sources failed: serve the last known-good calendar if it is inside
    # the staleness budget, flagged so reports can show it.
    stale = _load_cache()
    if stale:
        stale["degraded"] = True
        return stale
    return {"source": "unavailable", "events": [], "stale": True,
            "unavailable": True}


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
