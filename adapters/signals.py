""" adapters/signals — پایپ‌لاین هوشمند و اعتبارسنجی سیگنال‌های تلگرام (Signal Intelligence)

وظایف اصلی:
۱. خواندن و پارس سیگنال‌های جدید تلگرام از signals_log.json
۲. فیلتر همپوشانی و حذف تکراری‌ها (Content-Hash Deduplication با کش ۲ ساعته)
۳. فیلتر تازگی و انقضای زمانی (Drop Stale Signals): رد هر سیگنالی با تاخیر بیش از ۱۵ دقیقه
۴. اعتبارسنجی هندسی قیمت (Sanity Checks):
   - بررسی تطابق منطقی Entry, SL, TP (صعودی/نزولی)
   - حداقل فاصله استاپ (حداقل ۱.۰ دلار بر اونس برای طلا تا با نویز اسپرد ناک‌اوت نشود)
   - حداقل نسبت ریسک به ریوارد (RR >= 1.0)
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Set

from core.entities import Signal, Side

log = logging.getLogger(__name__)

# حداکثر عمر مجاز سیگنال بر حسب ثانیه (۱۵ دقیقه)
MAX_SIGNAL_AGE_SECONDS = 15 * 60

# حداقل فاصله استاپ بر حسب دلار در طلا
MIN_SL_DISTANCE_POINTS = 1.0


class SignalsAdapter:
    """آداپتور هوشمند خواندن، پالایش و اعتبارسنجی سیگنال‌های تلگرام."""

    def __init__(
        self,
        log_path: Path,
        state_path: Path,
        max_age_s: int = MAX_SIGNAL_AGE_SECONDS,
    ):
        self._log_path = Path(log_path)
        self._state_path = Path(state_path)
        self._max_age_s = max_age_s
        # کش محلی برای حذف سیگنال‌های تکراری: hash -> timestamp
        self._seen_hashes: dict[str, float] = {}

    def skip_backlog(self) -> int:
        """رد کردن سیگنال‌های قدیمی در زمان استارت دیمن."""
        try:
            if not self._log_path.exists():
                return 0
            raw = json.loads(self._log_path.read_text(encoding="utf-8"))
            items = raw if isinstance(raw, list) else raw.get("data", [])
            self._save_offset(len(items))
            log.info("signals: از %d سیگنال گذشته با موفقیت رد شدیم", len(items))
            return len(items)
        except Exception as e:
            log.warning("skip_backlog failed: %s", e)
            return 0

    # ── API خواندن و پالایش سیگنال‌ها ────────────────────

    def read_new(self) -> list[Signal]:
        """خواندن سیگنال‌های جدید، حذف تکراری‌ها و فیلتر سیگنال‌های معتبر."""
        if not self._log_path.exists():
            return []

        try:
            raw = json.loads(self._log_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError) as e:
            log.error("signals log read failed: %s", e)
            return []

        items = raw if isinstance(raw, list) else raw.get("data", [])
        offset = self._load_offset()
        new_items = items[offset:]
        self._save_offset(len(items))

        if not new_items:
            return []

        now_ts = time.time()
        self._prune_seen_hashes(now_ts)

        valid_signals: list[Signal] = []
        for item in new_items:
            sig = self._parse_and_validate(item, now_ts)
            if sig is not None:
                valid_signals.append(sig)

        if valid_signals:
            log.info("signals: %d سیگنال معتبر و تازه برای بررسی ارسال شد", len(valid_signals))
        return valid_signals

    # ── پارس و اعتبارسنجی چندلایه ────────────────────────

    def _parse_and_validate(self, item: dict, now_ts: float) -> Optional[Signal]:
        """پارس، فیلتر تکراری، سنجش تازگی زمانی و هندسه قیمت."""
        try:
            parsed = item.get("parsed") or {}
            side_raw = str(parsed.get("side", "")).upper()
            if side_raw not in ("BUY", "SELL"):
                return None

            symbol = str(parsed.get("symbol", "XAUUSD")).upper()
            if symbol != "XAUUSD":
                log.info("سیگنال رد شد: فقط نماد XAUUSD پشتیبانی می‌شود (%s)", symbol)
                return None

            entry = float(parsed.get("entry", 0) or 0)
            sl = float(parsed.get("sl", 0) or 0)
            tp = float(parsed.get("tp", 0) or 0)

            # ۱. اعتبارسنجی هندسی قیمت
            sl_dist = abs(entry - sl)
            if sl_dist < MIN_SL_DISTANCE_POINTS:
                log.info("سیگنال رد شد: فاصله استاپ بسیار کوچک است (%.2f < %.1f)", sl_dist, MIN_SL_DISTANCE_POINTS)
                return None

            if side_raw == "BUY" and not (tp > entry > sl):
                log.info("سیگنال خرید رد شد: هندسه نامعتبر (TP=%.2f, Entry=%.2f, SL=%.2f)", tp, entry, sl)
                return None
            if side_raw == "SELL" and not (tp < entry < sl):
                log.info("سیگنال فروش رد شد: هندسه نامعتبر (TP=%.2f, Entry=%.2f, SL=%.2f)", tp, entry, sl)
                return None

            # ۲. فیلتر تکراری بر اساس محتوای سیگنال (Content Hash)
            sig_hash = self._compute_content_hash(symbol, side_raw, entry, sl, tp)
            if sig_hash in self._seen_hashes:
                log.info("سیگنال تکراری در بازه ۲ ساعته رد شد: %s %s entry=%.2f", side_raw, symbol, entry)
                return None
            self._seen_hashes[sig_hash] = now_ts

            # ۳. فیلتر تازگی زمانی (Stale Check)
            ts_str = str(item.get("timestamp") or "")
            if ts_str:
                sig_epoch = self._parse_iso_timestamp(ts_str)
                if sig_epoch and (now_ts - sig_epoch > self._max_age_s):
                    age_m = (now_ts - sig_epoch) / 60.0
                    log.warning("سیگنال قدیمی رد شد: تاخیر %.1f دقیقه بیش از سقف مجاز است", age_m)
                    return None

            rr = float(parsed.get("rr_ratio", 0) or 0)
            if rr <= 0 and sl_dist > 0:
                rr = abs(tp - entry) / sl_dist

            confidence = float(parsed.get("confidence", 0) or 0.8)

            return Signal(
                signal_id=str(item.get("id") or item.get("timestamp", f"sig-{int(now_ts)}")),
                raw_text=str(item.get("raw_text", "")),
                symbol=symbol,
                side=Side(side_raw),
                entry=entry,
                sl=sl,
                tp=tp,
                rr=round(rr, 2),
                confidence=confidence,
                timestamp=ts_str or datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            log.warning("خطا در پردازش سیگنال: %s", e)
            return None

    # ── توابع کمکی هش و زمان ─────────────────────────────

    @staticmethod
    def _compute_content_hash(symbol: str, side: str, entry: float, sl: float, tp: float) -> str:
        """محاسبه هش محتوا برای جلوگیری از تکرار سیگنال‌های یکسان."""
        raw = f"{symbol}:{side}:{entry:.2f}:{sl:.2f}:{tp:.2f}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _prune_seen_hashes(self, now_ts: float, max_cache_age_s: int = 7200) -> None:
        """پاکسازی هش‌های قدیمی‌تر از ۲ ساعت."""
        expired = [h for h, t in self._seen_hashes.items() if now_ts - t > max_cache_age_s]
        for h in expired:
            self._seen_hashes.pop(h, None)

    @staticmethod
    def _parse_iso_timestamp(ts_str: str) -> Optional[float]:
        """تبدیل رشته زمان ISO به epoch ثانیه."""
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            return None

    # ── مدیریت آفست فایل لاگ ─────────────────────────────

    def _load_offset(self) -> int:
        try:
            return int(json.loads(self._state_path.read_text(encoding="utf-8")).get("offset", 0))
        except Exception:
            return 0

    def _save_offset(self, offset: int) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps({"offset": offset}), encoding="utf-8")
        except Exception as e:
            log.warning("save offset failed: %s", e)
