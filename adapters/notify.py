""" adapters/notify — گزارش تلگرامی به کاربر

نقش: فقط گزارش. هیچ تصمیمی از اینجا نمی‌آید.
در صورت خطا، سیستم ادامه می‌دهد (notify خرابی ≠ توقف ترید).
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)


class NotifyAdapter:
    """کلاینت Bot API تلگرام — fire-and-forget."""

    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True):
        self._token = bot_token
        self._chat = chat_id
        self._enabled = enabled and bool(bot_token) and bool(chat_id)
        self._base = f"https://api.telegram.org/bot{bot_token}"

    @property
    def enabled(self) -> bool:
        return self._enabled

    def send(self, text: str) -> bool:
        """ارسال پیام. هرگز exception به بیرون نمی‌دهد."""
        if not self._enabled:
            return False
        try:
            r = requests.post(
                f"{self._base}/sendMessage",
                json={"chat_id": self._chat, "text": text,
                      "parse_mode": "Markdown", "disable_web_page_preview": True},
                timeout=10,
            )
            return r.status_code == 200
        except Exception as e:
            log.warning("notify failed: %s", e)
            return False

    # ── پیام‌های آماده ─────────────────────────────────

    def trade_opened(self, side: str, symbol: str, volume: float,
                     entry: float, sl: float, tp: float, dry_run: bool = False) -> None:
        tag = "🧪 DRY-RUN " if dry_run else ""
        arrow = "🟢 BUY" if side.upper() == "BUY" else "🔴 SELL"
        self.send(
            f"{tag}*{arrow} {symbol}*\n"
            f"Volume: `{volume:.2f}`\n"
            f"Entry: `{entry:.2f}` | SL: `{sl:.2f}` | TP: `{tp:.2f}`"
        )

    def trade_closed(self, side: str, symbol: str, pnl: float, reason: str) -> None:
        emoji = "✅" if pnl >= 0 else "❌"
        self.send(
            f"{emoji} *بسته شد* {symbol}\n"
            f"PnL: `{pnl:+.2f}` | دلیل: `{reason}`"
        )

    def guard_denied(self, side: str, symbol: str, reasons: list[str]) -> None:
        self.send(
            f"🚫 *رد شد* {symbol} {side}\n"
            f"دلایل: {', '.join(reasons)}"
        )

    def status(self, text: str) -> None:
        self.send(f"ℹ️ {text}")

    def breakeven_activated(self, ticket: int, symbol: str, side: str, new_sl: float) -> None:
        arrow = "🟢 خرید" if side.upper() == "BUY" else "🔴 فروش"
        self.send(
            f"🛡 *معامله ریسک‌فری شد (Breakeven)*\n"
            f"تیکت: `#{ticket}` · {symbol} ({arrow})\n"
            f"استاپ به نقطه ورود امن `{new_sl:.2f}` (+ بافر کارمزد) منتقل شد."
        )

    def partial_closed(self, ticket: int, symbol: str, percent: float, volume_closed: float, pnl: float) -> None:
        self.send(
            f"💰 *سیو سود پله‌ای (Partial TP)*\n"
            f"تیکت: `#{ticket}` · {symbol}\n"
            f"بستن `{percent:.0f}%` حجم معامله (`{volume_closed:.2f}` لات)\n"
            f"سود نقدی کسب‌شده: `+{pnl:.2f} $`"
        )

    def trailing_ratcheted(self, ticket: int, symbol: str, new_sl: float, cur_price: float) -> None:
        self.send(
            f"📈 *ترلینگ استاپ (Trailing Ratchet)*\n"
            f"تیکت: `#{ticket}` · {symbol}\n"
            f"استاپ به سمت سود به `{new_sl:.2f}` فشرده شد (قیمت جاری: `{cur_price:.2f}`)."
        )
