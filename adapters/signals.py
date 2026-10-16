""" adapters/signals — خواندن سیگنال‌های کانال از فایل JSON

فوروارددر تلگرام سیگنال‌ها را در signals_log.json می‌نویسد.
این آداپتور فقط خواندن است — پردازش در core انجام می‌شود.

فرمت (بر اساس داده واقعی):
  [{"timestamp": iso, "raw_text": str, "parsed": {...}, "decision": {...}}, ...]
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from core.entities import Signal, Side

log = logging.getLogger(__name__)


class SignalsAdapter:
    """خواندن سیگنال‌های جدید از فایل لاگ فوروارددر."""

    def __init__(self, log_path: Path, state_path: Path):
        self._log_path = Path(log_path)
        self._state_path = Path(state_path)

    def skip_backlog(self) -> int:
        """رد کردن سیگنال‌های قدیمی — فقط سیگنال‌های بعد از NOW پردازش می‌شوند.

        برای استارت تازه دیمن: تعهد ما به سیگنال‌های آینده‌است، نه گذشته.
        """
        try:
            raw = json.loads(self._log_path.read_text())
            items = raw if isinstance(raw, list) else raw.get("data", [])
            self._save_offset(len(items))
            log.info("signals: از %d سیگنال قدیمی رد شدیم", len(items))
            return len(items)
        except Exception as e:
            log.warning("skip_backlog failed: %s", e)
            return 0

    # ── API ─────────────────────────────────────────────

    def read_new(self) -> list[Signal]:
        """خواندن سیگنال‌های جدید از آخرین آفست.

        state file آفست (اندیس) آخرین سیگنال خوانده‌شده را نگه می‌دارد.
        """
        try:
            raw = json.loads(self._log_path.read_text())
        except FileNotFoundError:
            log.warning("signals log not found: %s", self._log_path)
            return []
        except json.JSONDecodeError as e:
            log.error("signals log corrupt: %s", e)
            return []

        items = raw if isinstance(raw, list) else raw.get("data", [])
        offset = self._load_offset()
        new_items = items[offset:]
        self._save_offset(len(items))

        signals = []
        for item in new_items:
            sig = self._parse(item)
            if sig is not None:
                signals.append(sig)
        if signals:
            log.info("signals: %d جدید خوانده شد", len(signals))
        return signals

    # ── private ─────────────────────────────────────────

    def _parse(self, item: dict) -> Optional[Signal]:
        """تبدیل ردیف خام فوروارددر → Signal entity."""
        try:
            parsed = item.get("parsed") or {}
            side_raw = str(parsed.get("side", "")).upper()
            if side_raw not in ("BUY", "SELL"):
                return None
            return Signal(
                signal_id=str(item.get("id") or item.get("timestamp", "")),
                raw_text=str(item.get("raw_text", "")),
                symbol=str(parsed.get("symbol", "XAUUSD")),
                side=Side(side_raw),
                entry=float(parsed.get("entry", 0) or 0),
                sl=float(parsed.get("sl", 0) or 0),
                tp=float(parsed.get("tp", 0) or 0),
                rr=float(parsed.get("rr_ratio", 0) or 0),
                confidence=float(parsed.get("confidence", 0) or 0),
                timestamp=str(item.get("timestamp", "")),
            )
        except (ValueError, TypeError) as e:
            log.warning("signal parse failed: %s", e)
            return None

    def _load_offset(self) -> int:
        try:
            return int(json.loads(self._state_path.read_text()).get("offset", 0))
        except Exception:
            return 0

    def _save_offset(self, offset: int) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps({"offset": offset}))
        except Exception as e:
            log.warning("save offset failed: %s", e)
