""" adapters/notify — گزارش تلگرامی به کاربر

نقش: فقط گزارش. هیچ تصمیمی از اینجا نمی‌آید.
در صورت خطا، سیستم ادامه می‌دهد (notify خرابی ≠ توقف ترید).
"""
from __future__ import annotations

import logging
import socket
import urllib3.util.connection as urllib3_cn

import requests

# اجبار استفاده از IPv4 برای ارتباط با تلگرام در لینوکس (حل ارور Errno 101 Network unreachable روی سرور)
urllib3_cn.allowed_gai_family = lambda: socket.AF_INET

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
            if r.status_code != 200:
                # تلاش مجدد بدون parse_mode در صورت خطای کاراکترهای مارک‌داون
                r = requests.post(
                    f"{self._base}/sendMessage",
                    json={"chat_id": self._chat, "text": text,
                          "disable_web_page_preview": True},
                    timeout=10,
                )
            return r.status_code == 200
        except Exception as e:
            log.warning("notify failed: %s", e)
            return False

    # ── پیام‌های آماده ─────────────────────────────────

    def trade_opened(
        self,
        side: str,
        symbol: str,
        volume: float,
        entry: float,
        sl: float,
        tp: float,
        dry_run: bool = False,
        source: str = "",
        reasoning: str = "",
        channel: str = "",
        signal_id: str = "",
        rr: float = 0.0,
        grade: str = "",
    ) -> None:
        tag = "🧪 DRY-RUN " if dry_run else ""
        arrow = "🟢 BUY" if side.upper() == "BUY" else "🔴 SELL"

        is_signal = source.startswith("sig_") or source == "signal" or bool(channel)
        is_watchlist = source == "watchlist_pullback"

        lines = [f"{tag}*{arrow} {symbol}*"]

        if is_signal:
            lines.append("📡 *منبع معامله:* سیگنال کانال تلگرام")
            if channel:
                lines.append(f"📢 *کانال مبدأ:* `{channel}`")
            if signal_id:
                lines.append(f"🆔 *کد سیگنال:* `{signal_id}`")
            if reasoning:
                lines.append(f"📝 *تاییدیه ساختار:* {reasoning}")
        elif is_watchlist:
            if channel or "کانال" in reasoning or (signal_id and "tg" in signal_id):
                lines.append("⏳ *منبع معامله:* پولبک سیگنال کانال (از صف واچ‌لیست)")
                if channel:
                    lines.append(f"📢 *کانال مبدأ:* `{channel}`")
                if signal_id:
                    lines.append(f"🆔 *کد سیگنال:* `{signal_id}`")
            else:
                lines.append("🎯 *منبع معامله:* پولبک ستاپ واچ‌لیست (RTM QML Pullback)")
            if reasoning:
                lines.append(f"📝 *جزئیات فعال‌سازی:* {reasoning}")
        else:
            setup_title = "تحلیل خودکار پرایس‌اکشن نهادی (SMC/ICT)"
            if source == "smc_fvg":
                setup_title = "شکاف نقدینگی (SMC FVG)"
            elif source == "smc_ob":
                setup_title = "بلاک سفارش نهادی (SMC Order Block)"
            elif source == "rtm_qml":
                setup_title = "الگوی کوازیمودو (RTM QML)"
            elif source == "rtm_judas":
                setup_title = "شکار نقدینگی آسیا (ICT Judas Swing)"
            elif source == "analysis":
                setup_title = "روند ماژور EMA"

            lines.append(f"🤖 *منبع معامله:* تحلیل اختصاصی سیستم ({setup_title})")
            if reasoning:
                lines.append(f"🔍 *دلیل و ستاپ چارت:* {reasoning}")

        rr_str = f" | R:R: `{rr:.2f}`" if rr > 0 else ""
        grade_str = f" (گرید {grade})" if grade else ""
        lines.append(
            f"📊 *مشخصات سفارش{grade_str}:*\n"
            f"• Volume: `{volume:.2f}`\n"
            f"• Entry: `{entry:.2f}` | SL: `{sl:.2f}` | TP: `{tp:.2f}`{rr_str}"
        )
        self.send("\n".join(lines))

    def signal_evaluated(
        self, channel: str, signal_id: str, side: str, text: str, status: str, reason: str = ""
    ) -> None:
        """گزارش پردازش و تصمیم‌گیری روی سیگنال‌های کانال تلگرام."""
        if status == "REJECTED":
            emoji = "🛡"
            title = "سیگنال کانال رد شد (محافظت از سرمایه)"
        elif status == "WATCHLIST":
            emoji = "⏳"
            title = "سیگنال به واچ‌لیست رفت (در کمین پولبک)"
        else:
            emoji = "⚡"
            title = "سیگنال تایید شد و به سمت اجرا رفت"

        clean_text = text.replace("\n", " ").strip()[:65]
        lines = [
            f"{emoji} *{title}*",
            f"📢 *کانال:* `{channel}` | کد: `{signal_id}` ({side})",
            f"💬 *متن سیگنال:* _{clean_text}_",
        ]
        if reason:
            lines.append(f"🔍 *دلیل ارزیابی:* {reason}")
        self.send("\n".join(lines))

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
