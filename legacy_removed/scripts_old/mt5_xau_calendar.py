"""
Economic Calendar Module — fetches and parses weekly high-impact events.

Uses Forex Factory's free JSON feed (no API key needed):
  https://nfs.faireconomy.media/ff_calendar_thisweek.json

Filters for USD events that move gold:
  - FOMC, NFP, CPI, PPI, Retail Sales, GDP, PCE, PMI, Initial Claims
  - Rate decisions, Fed speeches
  - High/Medium impact only

Output: today + tomorrow events with Iran time, impact level, and gold bias.
"""
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

CACHE_FILE = Path("/home/ai/hermes-trading/data/trading/calendar_cache.json")
CACHE_TTL_HOURS = 6

# High-impact USD events that affect gold
HIGH_IMPACT_KEYWORDS = [
    "FOMC", "CPI", "NFP", "Non-Farm", "GDP", "PPI", "Retail Sales",
    "PCE", "Core PCE", "PMI", "ISM", "Initial Claims", "Unemployment",
    "Fed", "Powell", "Interest Rate", "Rate Decision",
    "Consumer Confidence", "Michigan", "Housing Starts",
    "Durable Goods", "Trade Balance", "Building Permits",
]

# Event → expected gold impact (direction bias)
GOLD_IMPACT_MAP = {
    "CPI": "usd_strength",       # High CPI → Fed hawkish → gold down
    "NFP": "usd_strength",       # Strong jobs → Fed hawkish → gold down
    "Non-Farm": "usd_strength",
    "GDP": "usd_strength",       # Strong GDP → USD up → gold down
    "PPI": "usd_strength",
    "Core PCE": "usd_strength",
    "PCE": "usd_strength",
    "Retail Sales": "usd_strength",
    "FOMC": "usd_strength",      # Rate decision usually hawkish
    "Interest Rate": "usd_strength",
    "Rate Decision": "usd_strength",
    "Powell": "usd_strength",
    "Fed": "usd_strength",
    "Initial Claims": "usd_weakness",  # High claims = weak economy = gold up
    "Unemployment": "usd_weakness",    # High unemployment = gold up
    "PMI": "usd_strength",
    "ISM": "usd_strength",
    "Consumer Confidence": "usd_strength",
    "Michigan": "usd_strength",
}

def _get_feed() -> Optional[list]:
    """Fetch calendar feed from Forex Factory."""
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"Calendar fetch failed: {e}")
        return None

def _load_cache() -> Optional[list]:
    """Load cached calendar if fresh enough."""
    try:
        if not CACHE_FILE.exists():
            return None
        data = json.loads(CACHE_FILE.read_text())
        cached_at = datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
        if (datetime.now() - cached_at) < timedelta(hours=CACHE_TTL_HOURS):
            return data.get("events", [])
    except Exception:
        pass
    return None

def _save_cache(events: list):
    """Save calendar events to cache."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({
            "cached_at": datetime.now().isoformat(),
            "events": events,
        }, indent=2, ensure_ascii=False))
    except Exception:
        pass

def _parse_events(feed_data: list) -> list:
    """Parse raw feed into structured events."""
    events = []
    for item in feed_data:
        if not isinstance(item, dict):
            continue
        # Only USD events
        currency = item.get("country", "").upper()
        if currency != "USD":
            continue

        # Check impact
        impact = item.get("impact", "").lower()
        if impact not in ("high", "medium"):
            continue

        title = item.get("title", "")
        date_str = item.get("date", "")

        # Parse date
        try:
            # Format: "2025-01-15T13:30:00-05:00"
            dt = datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            continue

        # Gold impact classification
        gold_impact = "neutral"
        for kw, direction in GOLD_IMPACT_MAP.items():
            if kw.lower() in title.lower():
                gold_impact = direction
                break

        events.append({
            "title": title,
            "datetime_utc": dt.isoformat(),
            "impact": impact,
            "currency": "USD",
            "gold_impact": gold_impact,
            "forecast": item.get("forecast", ""),
            "previous": item.get("previous", ""),
        })

    return sorted(events, key=lambda x: x["datetime_utc"])

def get_calendar(days_ahead: int = 2) -> dict:
    """
    Get economic calendar for today + N days ahead.
    Returns: {today: [...], tomorrow: [...], upcoming: [...], cached: bool}
    """
    # Try cache first
    cached = _load_cache()
    if cached is not None:
        return _filter_events(cached, days_ahead, cached=True)

    # Fetch fresh
    feed = _get_feed()
    if feed is None:
        # Try stale cache
        try:
            if CACHE_FILE.exists():
                data = json.loads(CACHE_FILE.read_text())
                return _filter_events(data.get("events", []), days_ahead, cached=True, stale=True)
        except Exception:
            pass
        return {"today": [], "tomorrow": [], "upcoming": [], "cached": False, "error": "fetch_failed"}

    events = _parse_events(feed)
    _save_cache(events)
    return _filter_events(events, days_ahead, cached=False)

def _filter_events(events: list, days_ahead: int, cached: bool = False, stale: bool = False) -> dict:
    """Filter events for today and upcoming days."""
    from datetime import timezone as tz
    now = datetime.now()

    today_events = []
    tomorrow_events = []
    upcoming = []

    for e in events:
        try:
            dt_str = e.get("datetime_utc", "")
            dt = datetime.fromisoformat(dt_str)
            # Normalize: strip timezone, then treat as ET (UTC-5 EDT / UTC-4 EST)
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
                dt += timedelta(hours=4)  # Convert ET → UTC
            # Convert UTC → Iran time (UTC+3:30)
            dt_iran = dt + timedelta(hours=3, minutes=30)
        except (ValueError, TypeError):
            continue

        e["iran_time"] = dt_iran.strftime("%H:%M")
        e["iran_date"] = dt_iran.strftime("%m-%d")

        if dt.date() == now.date():
            today_events.append(e)
        elif dt.date() == (now + timedelta(days=1)).date():
            tomorrow_events.append(e)
        elif now.date() < dt.date() <= (now + timedelta(days=days_ahead + 2)).date():
            upcoming.append(e)

    result = {
        "today": today_events,
        "tomorrow": tomorrow_events,
        "upcoming": upcoming[:10],
        "cached": cached,
    }
    if stale:
        result["stale"] = True
    return result

def is_news_risk_active(hours_before: int = 1, hours_after: int = 1) -> dict:
    """
    Check if a high-impact USD event is within the next N hours.
    Returns: {risk_active: bool, next_event: str|None, hours_until: float|None}
    """
    cal = get_calendar(days_ahead=1)
    now = datetime.now()

    for e in cal.get("today", []) + cal.get("tomorrow", []):
        try:
            dt_str = e.get("datetime_utc", "")
            dt = datetime.fromisoformat(dt_str)
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
                dt += timedelta(hours=4)  # ET → UTC
            dt_local = dt + timedelta(hours=3, minutes=30)  # UTC → Iran
        except (ValueError, TypeError):
            continue

        hours_until = (dt_local - now).total_seconds() / 3600

        if -hours_after <= hours_until <= hours_before:
            return {
                "risk_active": True,
                "next_event": e["title"],
                "hours_until": round(hours_until, 1),
                "impact": e["impact"],
                "gold_impact": e["gold_impact"],
            }

    return {"risk_active": False, "next_event": None, "hours_until": None}

# Quick test
if __name__ == "__main__":
    cal = get_calendar()
    print(f"Today: {len(cal.get('today', []))} events")
    for e in cal.get("today", []):
        print(f"  {e.get('iran_time', '?')} {e['title']} [{e['impact']}] → {e['gold_impact']}")
    print(f"Tomorrow: {len(cal.get('tomorrow', []))} events")
    for e in cal.get("tomorrow", []):
        print(f"  {e.get('iran_time', '?')} {e['title']} [{e['impact']}] → {e['gold_impact']}")
    news = is_news_risk_active()
    print(f"News risk: {news}")
