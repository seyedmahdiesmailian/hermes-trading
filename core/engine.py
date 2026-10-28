""" core/engine — موتور جامع تحلیل و تصمیم هرمس (Hybrid Classical + SMC/ICT + News)

این موتور «مغز متفکر» سیستم معاملاتی است:
۱. تحلیل روند و نوسان (EMA20/50 + ATR14 + Swings)
۲. تحلیل پیشرفته سبک هوشمند (SMC/ICT: Order Blocks, FVG, Liquidity Sweeps, Premium/Discount)
۳. فیلتر اخبار داغ اقتصادی (High-Impact News Blackout via NewsGuard)
۴. تاییدیه سشن‌های نقدینگی فعال (London & New York Killzones)
۵. گریدبندی دقیق ستاپ‌های تحلیلی و سیگنال‌های تلگرام (Grades A / B / C / D)
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from core.entities import Candle, Plan, SetupGrade, Side, Signal, Tick
from core.news import NewsGuard
from core.smc import SMCAnalyzer, SMCView, ZoneType

log = logging.getLogger(__name__)

# ── پارامترهای هندسه استاپ و تارگت ────────────────────────
SL_ATR_MULT = 1.5        # فاصله استاپ لاس = ۱.۵ × ATR
TRAIL_ATR_MULT = 3.0     # فاصله ترلینگ استاپ = ۳.۰ × ATR


@dataclass(frozen=True)
class MarketView:
    """تصویر جامع و چندبعدی از وضعیت فعلی بازار."""
    trend: str                  # "bullish" | "bearish" | "ranging"
    trend_strength: float       # 0.0 .. 1.0
    atr: float                  # نوسان فعلی ATR(14)
    spread: float
    last_price: float
    support: float
    resistance: float
    smc: Optional[SMCView] = None
    news_blackout: bool = False
    news_reason: str = ""
    notes: str = ""

    @property
    def is_trending(self) -> bool:
        return self.trend != "ranging" and self.trend_strength >= 0.40


class Engine:
    """موتور تحلیل تکنیکال، SMC و ساخت Plan معاملاتی."""

    def __init__(self, news_guard: Optional[NewsGuard] = None):
        self.smc = SMCAnalyzer()
        self.news = news_guard or NewsGuard()

    # ── تحلیل جامع بازار ─────────────────────────────────

    def analyze(
        self,
        candles: list[Candle],
        tick: Tick,
        h1_candles: Optional[list[Candle]] = None,
        check_news: bool = True,
    ) -> MarketView:
        """تحلیل کامل بازار از داده‌های کندل، تیک و تقویم اقتصادی."""
        if len(candles) < 30:
            return MarketView(
                trend="ranging", trend_strength=0.0, atr=0.0,
                spread=tick.spread, last_price=tick.mid,
                support=0.0, resistance=0.0,
                notes="insufficient_candles",
            )

        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]

        # ۱. روند تکنیکال: شیب و تقاطع EMA سریع vs کند
        ema_fast = _ema(closes, 20)
        ema_slow = _ema(closes, 50)
        last_close = closes[-1]

        if ema_fast > ema_slow and last_close > ema_slow:
            trend = "bullish"
        elif ema_fast < ema_slow and last_close < ema_slow:
            trend = "bearish"
        else:
            trend = "ranging"

        # قدرت روند
        span = max(ema_slow, 1.0)
        strength = min(1.0, abs(ema_fast - ema_slow) / (span * 0.005))

        # نوسان ATR (14)
        atr = _atr(candles, 14)

        # سطوح حمایت و مقاومت کلاسیک
        support = min(lows[-50:]) if len(lows) >= 50 else min(lows)
        resistance = max(highs[-50:]) if len(highs) >= 50 else max(highs)

        # ۲. تحلیل ساختار هوشمند SMC/ICT
        smc_view = self.smc.analyze(candles, h1_candles)

        # ۳. بررسی وضعیت اخبار داغ اقتصادی
        news_blackout = False
        news_reason = ""
        if check_news:
            news_blackout, news_reason = self.news.is_blackout()

        notes = f"ema20={ema_fast:.2f} ema50={ema_slow:.2f} smc_bias={smc_view.bias} kz={smc_view.killzone}"

        return MarketView(
            trend=trend,
            trend_strength=round(strength, 3),
            atr=round(atr, 2),
            spread=tick.spread,
            last_price=tick.mid,
            support=round(support, 2),
            resistance=round(resistance, 2),
            smc=smc_view,
            news_blackout=news_blackout,
            news_reason=news_reason,
            notes=notes,
        )

    # ── ساخت Plan از تحلیل خودکار (Hybrid Trend + SMC) ───

    def plan_from_analysis(
        self,
        candles: list[Candle],
        view: MarketView,
        timeframe: str = "M15"
    ) -> Optional[Plan]:
        """ساخت پلن ورود بر مبنای تلفیق ستاپ روند-EMA و تاییدیه SMC/ICT."""
        # فیلتر ۱: مسدود بودن در زمان اخبار داغ
        if view.news_blackout:
            log.info("تحلیل خودکار رد شد: %s", view.news_reason)
            return None

        if len(candles) < 60 or view.atr <= 0:
            return None

        closes = [c.close for c in candles[-60:]]
        e20 = _ema(closes, 20)
        e50 = _ema(closes, 50)
        last = closes[-1]

        # تشخیص جهت اولیه از EMA
        if last > e20 > e50:
            side = Side.BUY
        elif last < e20 < e50:
            side = Side.SELL
        else:
            return None

        # فیلتر ۲: تاییدیه نواحی ارزان‌فروشی/گران‌فروشی (SMC Zone Check)
        if view.smc is not None:
            # نباید در سقف رنج (Extreme Premium) خرید زد
            if side == Side.BUY and view.smc.zone == ZoneType.PREMIUM and view.smc.fib_level > 0.70:
                log.info("تحلیل رد شد: خرید در ناحیه گران (Premium fib=%.2f)", view.smc.fib_level)
                return None
            # نباید در کف رنج (Extreme Discount) فروش زد
            if side == Side.SELL and view.smc.zone == ZoneType.DISCOUNT and view.smc.fib_level < 0.30:
                log.info("تحلیل رد شد: فروش در ناحیه ارزان (Discount fib=%.2f)", view.smc.fib_level)
                return None

        entry = view.last_price
        if side == Side.BUY:
            sl = entry - view.atr * SL_ATR_MULT
            tp = 0.0  # مدیریت سود با تریلینگ داینامیک
        else:
            sl = entry + view.atr * SL_ATR_MULT
            tp = 0.0

        if entry <= 0 or sl <= 0:
            return None

        # ارزیابی گرید کیفی ستاپ بر اساس همگرایی فاکتورها (Confluence)
        grade = self._grade_analysis_setup(side, view)
        if grade in (SetupGrade.C, SetupGrade.D):
            # ستاپ‌های ضعیف اجازه عبور ندارند
            return None

        rr = TRAIL_ATR_MULT / SL_ATR_MULT  # 3.0 / 1.5 = 2.0

        reasoning = (
            f"trend={view.trend} str={view.trend_strength:.2f} atr={view.atr:.2f} "
            f"zone={view.smc.zone.value if view.smc else 'N/A'} "
            f"kz={view.smc.killzone if view.smc else 'N/A'}"
        )

        return Plan(
            plan_id=f"auto-{int(candles[-1].time)}",
            symbol="XAUUSD",
            side=side,
            entry_price=round(entry, 2),
            stop_loss=round(sl, 2),
            take_profit=tp,
            volume=0.0,  # توسط دروازه ریسک تعیین می‌شود
            grade=grade,
            source="analysis",
            timeframe=timeframe,
            rr=rr,
            confidence=view.smc.confidence if view.smc else 0.6,
            reasoning=reasoning,
        )

    # ── ساخت Plan از سیگنال تلگرام با فیلتر هوشمند ─────────

    def plan_from_signal(
        self,
        sig: Signal,
        view: MarketView,
        timeframe: str = "M15"
    ) -> Optional[Plan]:
        """اعتبارسنجی چندمرحله‌ای سیگنال تلگرام و تطبیق با واقعیت بازار."""
        if not sig.is_valid:
            log.info("سیگنال نامعتبر متنی: %s", sig.signal_id)
            return None

        # فیلتر ۱: وتوی اخبار داغ اقتصادی
        if view.news_blackout:
            log.warning("سیگنال رد شد به دلیل انتشار خبر داغ: %s", view.news_reason)
            return None

        # فیلتر ۲: وتوی سیگنال خلاف روند ماژور بازار
        if view.is_trending:
            if sig.side == Side.BUY and view.trend == "bearish":
                log.info("سیگنال خرید در روند نزولی قوی رد شد (Counter-trend)")
                return None
            if sig.side == Side.SELL and view.trend == "bullish":
                log.info("سیگنال فروش در روند صعودی قوی رد شد (Counter-trend)")
                return None

        # فیلتر ۳: وتوی تله نقدینگی خرد (Retail Trap Protection)
        if view.smc is not None:
            if sig.side == Side.BUY and view.smc.zone == ZoneType.PREMIUM and view.smc.fib_level > 0.75:
                log.info("سیگنال خرید در سقف قیمت (Extreme Premium) وتو شد")
                return None
            if sig.side == Side.SELL and view.smc.zone == ZoneType.DISCOUNT and view.smc.fib_level < 0.25:
                log.info("سیگنال فروش در کف قیمت (Extreme Discount) وتو شد")
                return None

        rr = sig.rr if sig.rr > 0 else _calc_rr(sig)
        grade = self._grade_signal(sig, view)

        return Plan(
            plan_id=f"plan-{sig.signal_id}",
            symbol=sig.symbol,
            side=sig.side,
            entry_price=sig.entry,
            stop_loss=sig.sl,
            take_profit=sig.tp,
            volume=0.0,
            grade=grade,
            source="signal",
            timeframe=timeframe,
            rr=round(rr, 3),
            confidence=sig.confidence,
            reasoning=f"sig_conf={sig.confidence:.2f} trend={view.trend} zone={view.smc.zone.value if view.smc else 'N/A'}",
        )

    def evaluate_signal(
        self,
        sig: Signal,
        view: MarketView,
        tick: Tick,
        timeframe: str = "M15"
    ) -> tuple[str, Optional[Plan], Optional[dict]]:
        """تصمیم‌گیری سه‌حالته تریدر حرفه‌ای درباره سیگنال:
        ۱. EXECUTE: اجرای فوری
        ۲. WATCHLIST: نگهداری در واچ‌لیست تا پولبک به قیمت بهینه یا رفع خبر داغ
        ۳. REJECT: رد قطعی (خلاف روند یا تله نقدینگی)
        """
        if not sig.is_valid:
            return "REJECT", None, None

        # فیلتر وتوی خلاف روند کلان -> رد قطعی
        if view.is_trending:
            if sig.side == Side.BUY and view.trend == "bearish":
                log.info("سیگنال رد شد: خرید در روند نزولی قوی")
                return "REJECT", None, None
            if sig.side == Side.SELL and view.trend == "bullish":
                log.info("سیگنال رد شد: فروش در روند صعودی قوی")
                return "REJECT", None, None

        # فیلتر تله نقدینگی سقف و کف -> رد قطعی
        if view.smc is not None:
            if sig.side == Side.BUY and view.smc.zone == ZoneType.PREMIUM and view.smc.fib_level > 0.80:
                log.info("سیگنال رد شد: خرید در سقف قیمت")
                return "REJECT", None, None
            if sig.side == Side.SELL and view.smc.zone == ZoneType.DISCOUNT and view.smc.fib_level < 0.20:
                log.info("سیگنال رد شد: فروش در کف قیمت")
                return "REJECT", None, None

        now_ts = time.time()
        cur_price = tick.mid

        # اعتبارسنجی زنده: آیا سیگنال قبلاً استاپ خورده یا به تارگت رسیده است؟ (ابطال فوری)
        if sig.side == Side.BUY:
            if cur_price <= sig.sl:
                log.info("سیگنال رد شد: قیمت بازار (%.2f) به استاپ لاس (%.2f) رسیده یا از آن گذشته", cur_price, sig.sl)
                return "REJECT", None, None
            if cur_price >= sig.tp:
                log.info("سیگنال رد شد: قیمت بازار (%.2f) به تارگت (%.2f) رسیده است", cur_price, sig.tp)
                return "REJECT", None, None
        else:
            if cur_price >= sig.sl:
                log.info("سیگنال رد شد: قیمت بازار (%.2f) به استاپ لاس (%.2f) رسیده یا از آن گذشته", cur_price, sig.sl)
                return "REJECT", None, None
            if cur_price <= sig.tp:
                log.info("سیگنال رد شد: قیمت بازار (%.2f) به تارگت (%.2f) رسیده است", cur_price, sig.tp)
                return "REJECT", None, None

        # اگر در زمان خبر داغ باشیم -> نگهداری در واچ‌لیست تا رفع خبر!
        if view.news_blackout:
            item = {
                "item_id": f"wl-{sig.signal_id}",
                "signal_id": sig.signal_id,
                "symbol": sig.symbol,
                "side": sig.side.value,
                "entry_price": sig.entry,
                "trigger_price": sig.entry,
                "sl": sig.sl,
                "tp": sig.tp,
                "added_at": now_ts,
                "expires_at": now_ts + 7200.0,
                "status": "waiting",
                "reason": f"در انتظار رفع خبر: {view.news_reason}",
            }
            return "WATCHLIST", None, item

        # بررسی فاصله قیمت لحظه‌ای بازار با قیمت ورود سیگنال
        cur_price = tick.mid
        has_run = (sig.side == Side.BUY and cur_price > sig.entry + 1.5) or \
                  (sig.side == Side.SELL and cur_price < sig.entry - 1.5)

        if has_run:
            item = {
                "item_id": f"wl-{sig.signal_id}",
                "signal_id": sig.signal_id,
                "symbol": sig.symbol,
                "side": sig.side.value,
                "entry_price": sig.entry,
                "trigger_price": sig.entry,
                "sl": sig.sl,
                "tp": sig.tp,
                "added_at": now_ts,
                "expires_at": now_ts + 7200.0,
                "status": "waiting",
                "reason": f"قیمت امتداد یافته ({cur_price:,.2f}) — در انتظار پولبک به {sig.entry:,.2f}",
            }
            return "WATCHLIST", None, item

        # اجرای فوری!
        plan = self.plan_from_signal(sig, view, timeframe)
        if plan is not None:
            return "EXECUTE", plan, None

        return "REJECT", None, None

    # ── سیستم نمره‌دهی ستاپ‌ها (Grading Matrix) ────────────

    @staticmethod
    def _grade_analysis_setup(side: Side, view: MarketView) -> SetupGrade:
        """نمره‌دهی ستاپ تحلیلی بر مبنای همگرایی تکنیکال و SMC."""
        score = 0.5  # پایه هماهنگی روند

        if view.smc is not None:
            # همگرایی با دیدگاه SMC
            if (side == Side.BUY and view.smc.bias == "bullish") or \
               (side == Side.SELL and view.smc.bias == "bearish"):
                score += 0.25

            # پاداش ناحیه بهینه ورود (Discount برای خرید / Premium برای فروش)
            if (side == Side.BUY and view.smc.zone == ZoneType.DISCOUNT) or \
               (side == Side.SELL and view.smc.zone == ZoneType.PREMIUM):
                score += 0.15

            # پاداش ستاپ شکار نقدینگی آسیا (Judas Swing) یا OTE
            if view.smc.judas_swing is not None:
                score += 0.20
            if view.smc.is_ote:
                score += 0.15

            # پاداش سشن نقدینگی فعال
            if view.smc.killzone in ("london", "newyork"):
                score += 0.10

        if score >= 0.85:
            return SetupGrade.A
        if score >= 0.60:
            return SetupGrade.B
        if score >= 0.40:
            return SetupGrade.C
        return SetupGrade.D

    @staticmethod
    def _grade_signal(sig: Signal, view: MarketView) -> SetupGrade:
        """گریدبندی کیفیت سیگنال تلگرام."""
        score = 0.0
        score += min(1.0, sig.confidence) * 0.40
        sig_rr = sig.rr if sig.rr > 0 else _calc_rr(sig)
        score += min(1.0, sig_rr / 2.0) * 0.30

        if view.is_trending:
            aligned = (sig.side == Side.BUY and view.trend == "bullish") or \
                      (sig.side == Side.SELL and view.trend == "bearish")
            score += 0.20 if aligned else 0.0

        if view.smc is not None:
            if (sig.side == Side.BUY and view.smc.zone == ZoneType.DISCOUNT) or \
               (sig.side == Side.SELL and view.smc.zone == ZoneType.PREMIUM):
                score += 0.10

        if score >= 0.80:
            return SetupGrade.A
        if score >= 0.60:
            return SetupGrade.B
        if score >= 0.40:
            return SetupGrade.C
        return SetupGrade.D


# ── توابع کمکی محاسباتی (Pure Functions) ─────────────────

def _ema(values: list[float], period: int) -> float:
    """محاسبه Exponential Moving Average روی سری داده."""
    if not values:
        return 0.0
    k = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _atr(candles: list[Candle], period: int = 14) -> float:
    """محاسبه نوسان واقعی بازار (Average True Range)."""
    if len(candles) < 2:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
        tr = max(
            c.high - c.low,
            abs(c.high - p.close),
            abs(c.low - p.close),
        )
        trs.append(tr)
    n = min(period, len(trs))
    return sum(trs[-n:]) / n if n > 0 else 0.0


def _calc_rr(sig: Signal) -> float:
    """محاسبه دقیق نسبت سود به زیان (Risk-to-Reward Ratio)."""
    sl_dist = abs(sig.entry - sig.sl)
    tp_dist = abs(sig.tp - sig.entry)
    return tp_dist / sl_dist if sl_dist > 0 else 0.0
