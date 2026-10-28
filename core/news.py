""" core/news — فیلتر تقویم اقتصادی و محافظت در برابر اخبار داغ (News Veto Guard)

معاملات طلا (XAUUSD) به شدت تحت تاثیر داده‌های اقتصادی دلار آمریکا (USD) قرار دارد.
این ماژول از تقویم رسمی Forex Factory رویدادهای High-Impact را دریافت و کش می‌کند:
- قبل و بعد از انتشار خبر پرریسک (مانند NFP, CPI, PPI, FOMC, Rate Decision)
  معاملات جدید مسدود (Blackout) می‌شوند تا از اسپرد وایلد و اسلیپیج جلوگیری شود.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "calendar" / "economic_calendar.json"
CACHE_TTL_HOURS = 6

# ارزهای اثرگذار روی طلا
RELEVANT_CURRENCIES = {"USD", "XAU", "ALL"}

# کلیدواژه‌های اخبار داغ (High Impact Keywords)
HIGH_IMPACT_KEYWORDS = {
    "cpi", "ppi", "nfp", "non-farm", "payroll", "fomc", "fed",
    "interest rate", "rate decision", "gdp", "unemployment",
    "inflation", "retail sales", "pmi", "ism", "consumer confidence",
    "powell", "jackson hole"
}


@dataclass(frozen=True)
class EconomicEvent:
    title: str
    currency: str
    impact: str
    timestamp: int  # epoch seconds UTC
    forecast: str = ""
    previous: str = ""

    @property
    def is_high_impact(self) -> bool:
        imp = self.impact.strip().lower()
        if imp == "high":
            return True
        title_lower = self.title.lower()
        return any(kw in title_lower for kw in HIGH_IMPACT_KEYWORDS)


class NewsGuard:
    """محافظ تقویم اقتصادی و فیلتر اخبار داغ."""

    def __init__(self, cache_file: Path | None = None):
        self._cache_file = cache_file or CACHE_PATH
        self._events: list[EconomicEvent] = []
        self._last_loaded = 0.0
        self.load_calendar()

    def load_calendar(self, force_refresh: bool = False) -> None:
        """بارگذاری رویدادها از کش یا دانلود از Forex Factory."""
        now = time.time()
        if not force_refresh and self._events and (now - self._last_loaded < 3600):
            return

        # بررسی وجود کش معتبر
        if not force_refresh and self._cache_file.exists():
            try:
                stat = self._cache_file.stat()
                if now - stat.st_mtime < CACHE_TTL_HOURS * 3600:
                    self._parse_cache_file()
                    if self._events:
                        self._last_loaded = now
                        return
            except Exception as e:
                log.warning("news: cache read failed: %s", e)

        # تلاش برای دانلود جدید
        try:
            self._download_and_cache()
            self._parse_cache_file()
            self._last_loaded = now
            log.info("news: تقویم اقتصادی با موفقیت دانلود و کش شد (%d رویداد)", len(self._events))
        except Exception as e:
            log.warning("news: fetch failed (%s) — using existing cache if available", e)
            if self._cache_file.exists():
                self._parse_cache_file()
                self._last_loaded = now

    def _download_and_cache(self) -> None:
        """دانلود تقویم از سرور Forex Factory و ذخیره روی دیسک."""
        req = urllib.request.Request(
            FF_CALENDAR_URL,
            headers={"User-Agent": "Hermes-Trading-Bot/3.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        doc = {
            "source": "forexfactory",
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "events": data,
        }
        self._cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._cache_file)

    def _parse_cache_file(self) -> None:
        """پارس رویدادهای ذخیره‌شده در فایل کش."""
        if not self._cache_file.exists():
            return
        try:
            raw = json.loads(self._cache_file.read_text(encoding="utf-8"))
            items = raw.get("events", []) if isinstance(raw, dict) else raw
            events = []
            for item in items:
                curr = str(item.get("country") or item.get("currency") or "").upper()
                if curr and curr not in RELEVANT_CURRENCIES:
                    continue

                # پارس تاریخ ایزو
                dt_str = item.get("date")
                if not dt_str:
                    continue
                try:
                    # فرمت مثلا: 2026-10-25T15:00:00-04:00
                    dt = datetime.fromisoformat(dt_str)
                    epoch = int(dt.timestamp())
                except Exception:
                    continue

                events.append(
                    EconomicEvent(
                        title=str(item.get("title", "")),
                        currency=curr,
                        impact=str(item.get("impact", "")),
                        timestamp=epoch,
                        forecast=str(item.get("forecast", "")),
                        previous=str(item.get("previous", "")),
                    )
                )
            self._events = events
        except Exception as e:
            log.error("news: parse cache failed: %s", e)

    def is_blackout(
        self,
        symbol: str = "XAUUSD",
        now_ts: Optional[float] = None,
        before_minutes: int = 30,
        after_minutes: int = 30,
    ) -> tuple[bool, str]:
        """بررسی آیا هم‌اکنون در بازه مسدود معاملاتی خبر داغ هستیم یا خیر.

        بازگشت: (is_blocked, reason)
        """
        now = now_ts or time.time()
        self.load_calendar()

        window_start = now - after_minutes * 60
        window_end = now + before_minutes * 60

        for ev in self._events:
            if not ev.is_high_impact:
                continue

            if window_start <= ev.timestamp <= window_end:
                diff_m = round((ev.timestamp - now) / 60.0, 1)
                if diff_m >= 0:
                    timing_msg = f"{diff_m} دقیقه دیگر"
                else:
                    timing_msg = f"{abs(diff_m)} دقیقه پیش"

                reason = f"NEWS_BLACKOUT: {ev.title} ({ev.currency}) — {timing_msg}"
                log.info("news lock active: %s", reason)
                return True, reason

        return False, ""
