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
    rsi: float = 50.0           # مقدار فعلی RSI(14)
    divergence: Optional[str] = None  # نوع واگرایی (BULLISH_REGULAR, BEARISH_REGULAR, ...)
    div_strength: float = 0.0   # قدرت واگرایی 0.0 .. 1.0
    usd_bias: str = "NEUTRAL"   # وضعیت شاخص دلار: "BULLISH" | "BEARISH" | "NEUTRAL"
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

    @staticmethod
    def calculate_usd_bias(
        eur_candles: Optional[list[Candle]] = None,
        jpy_candles: Optional[list[Candle]] = None,
    ) -> str:
        """سنجش وضعیت بین‌بازاری شاخص دلار (DXY Proxy) بر مبنای EURUSD و USDJPY."""
        if not eur_candles or len(eur_candles) < 20 or not jpy_candles or len(jpy_candles) < 20:
            return "NEUTRAL"
        try:
            eur_closes = [c.close for c in eur_candles[-20:]]
            jpy_closes = [c.close for c in jpy_candles[-20:]]
            eur_e20 = _ema(eur_closes, 20)
            jpy_e20 = _ema(jpy_closes, 20)
            eur_last = eur_closes[-1]
            jpy_last = jpy_closes[-1]

            # EURUSD نزولی (زیر EMA20) و USDJPY صعودی (بالای EMA20) -> دلار قوی
            if eur_last < eur_e20 and jpy_last > jpy_e20:
                return "BULLISH"
            # EURUSD صعودی (بالای EMA20) و USDJPY نزولی (زیر EMA20) -> دلار ضعیف
            elif eur_last > eur_e20 and jpy_last < jpy_e20:
                return "BEARISH"
            return "NEUTRAL"
        except Exception:
            return "NEUTRAL"

    def analyze(
        self,
        candles: list[Candle],
        tick: Tick,
        h1_candles: Optional[list[Candle]] = None,
        check_news: bool = True,
        eur_candles: Optional[list[Candle]] = None,
        jpy_candles: Optional[list[Candle]] = None,
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

        # ۳. محاسبه RSI و واگرایی مومنتوم (RSI Divergence)
        rsi_series = _rsi_series(closes, period=14)
        current_rsi = round(rsi_series[-1], 2) if rsi_series else 50.0
        div_type, div_strength = detect_rsi_divergence(highs, lows, rsi_series, window=30)

        # ۴. بررسی وضعیت اخبار داغ اقتصادی
        news_blackout = False
        news_reason = ""
        if check_news:
            news_blackout, news_reason = self.news.is_blackout()

        # ۵. وضعیت بین‌بازاری شاخص دلار (DXY Proxy)
        usd_bias = self.calculate_usd_bias(eur_candles, jpy_candles)

        notes = f"ema20={ema_fast:.2f} ema50={ema_slow:.2f} rsi={current_rsi:.1f} div={div_type or 'none'} usd={usd_bias} smc_bias={smc_view.bias} kz={smc_view.killzone}"

        return MarketView(
            trend=trend,
            trend_strength=round(strength, 3),
            atr=round(atr, 2),
            spread=tick.spread,
            last_price=tick.mid,
            support=round(support, 2),
            resistance=round(resistance, 2),
            rsi=current_rsi,
            divergence=div_type,
            div_strength=div_strength,
            usd_bias=usd_bias,
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

        # فیلتر ۲: عدم تعقیب قیمت امتدادیافته (Anti-Chasing Mean Reversion Filter)
        # اگر قیمت بیش از ۱.۰ برابر ATR از EMA20 فاصله گرفته باشد، ورود با مارکت ممنوع است
        dist_to_mean = abs(last - e20)
        if dist_to_mean > 1.0 * view.atr:
            log.info("تحلیل خودکار رد شد: قیمت امتداد یافته (فاصله از EMA20: %.2f > ATR %.2f) — در انتظار پولبک", dist_to_mean, view.atr)
            return None

        # فیلتر ۳: تاییدیه نواحی ارزان‌فروشی/گران‌فروشی (SMC Zone Check)
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
        recent_window = candles[-10:]
        buffer = round(view.atr * 0.15, 2)

        # استاپ‌لاس ساختاری پشت پیووت سوئینگ ۱۰ کندل اخیر با کف ایمنی ۱.۵ برابر ATR
        if side == Side.BUY:
            swing_low = min(c.low for c in recent_window)
            sl = min(swing_low - buffer, entry - view.atr * SL_ATR_MULT)
            if (entry - sl) > view.atr * 2.5:
                sl = entry - view.atr * 2.5
            sl = round(sl, 2)
            tp = round(entry + abs(entry - sl) * 2.0, 2)
        else:
            swing_high = max(c.high for c in recent_window)
            sl = max(swing_high + buffer, entry + view.atr * SL_ATR_MULT)
            if (sl - entry) > view.atr * 2.5:
                sl = entry + view.atr * 2.5
            sl = round(sl, 2)
            tp = round(entry - abs(sl - entry) * 2.0, 2)

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
        # پایه هماهنگی روند EMA سریع و کند تأییدشده در بک‌تست = 0.65 (گرید B پایه)
        score = 0.65

        # پاداش قدرت شیب روند
        if view.trend_strength >= 0.20:
            score += 0.10

        if view.smc is not None:
            # همگرایی مستقیم با دیدگاه سازمانی SMC
            if (side == Side.BUY and view.smc.bias == "bullish") or \
               (side == Side.SELL and view.smc.bias == "bearish"):
                score += 0.15

            # پاداش ناحیه بهینه ورود (Discount برای خرید / Premium برای فروش)
            if (side == Side.BUY and view.smc.zone == ZoneType.DISCOUNT) or \
               (side == Side.SELL and view.smc.zone == ZoneType.PREMIUM):
                score += 0.10

            # پاداش ستاپ شکار نقدینگی آسیا (Judas Swing) یا ورود بهینه OTE
            if view.smc.judas_swing is not None:
                score += 0.15
            if view.smc.is_ote:
                score += 0.10

            # جریمه سنگین تله نقدینگی: خرید در سقف یا فروش در کف
            if (side == Side.BUY and view.smc.zone == ZoneType.PREMIUM and view.smc.fib_level > 0.80) or \
               (side == Side.SELL and view.smc.zone == ZoneType.DISCOUNT and view.smc.fib_level < 0.20):
                score -= 0.30

        # پاداش همگرایی واگرایی مومنتوم (RSI Divergence)
        if view.divergence is not None:
            if (side == Side.BUY and view.divergence in ("BULLISH_REGULAR", "BULLISH_HIDDEN")) or \
               (side == Side.SELL and view.divergence in ("BEARISH_REGULAR", "BEARISH_HIDDEN")):
                score += 0.20  # ارتقا مستقیم به گرید A
            elif (side == Side.BUY and view.divergence == "BEARISH_REGULAR") or \
                 (side == Side.SELL and view.divergence == "BULLISH_REGULAR"):
                score -= 0.25  # جریمه ورود در انتهای روند (تله اگزاست مومنتوم)

        # پاداش همبستگی بین‌بازاری شاخص دلار (DXY / USD Proxy)
        if view.usd_bias != "NEUTRAL":
            if (side == Side.BUY and view.usd_bias == "BEARISH") or \
               (side == Side.SELL and view.usd_bias == "BULLISH"):
                score += 0.15  # تاییدیه قوی همبستگی دلار و طلا
            elif (side == Side.BUY and view.usd_bias == "BULLISH") or \
                 (side == Side.SELL and view.usd_bias == "BEARISH"):
                score -= 0.20  # تله نقدینگی ناشی از تقابل با جهت کلان دلار

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
    if sig.tp <= 0 or sig.entry <= 0:
        return 0.0
    sl_dist = abs(sig.entry - sig.sl)
    tp_dist = abs(sig.tp - sig.entry)
    return tp_dist / sl_dist if sl_dist > 0 else 0.0


def _rsi_series(closes: list[float], period: int = 14) -> list[float]:
    """محاسبه اندیکاتور Relative Strength Index با فرمول Wilder."""
    if len(closes) < period + 1:
        return [50.0] * len(closes)

    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(0.0, diff))
        losses.append(max(0.0, -diff))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    rsi = [50.0] * period
    if avg_loss == 0:
        rsi.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi.append(100.0 - (100.0 / (1.0 + rs)))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi.append(100.0 - (100.0 / (1.0 + rs)))

    return rsi


def detect_rsi_divergence(
    highs: list[float],
    lows: list[float],
    rsi: list[float],
    window: int = 30
) -> tuple[Optional[str], float]:
    """تشخیص واگرایی‌های معمولی و مخفی در قیمت و RSI."""
    n = len(highs)
    if n < window or len(rsi) < window:
        return None, 0.0

    start_idx = max(0, n - window)

    # سوئینگ‌های سقف
    swing_highs = []
    for i in range(start_idx + 1, n - 1):
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            swing_highs.append((i, highs[i], rsi[i]))

    # سوئینگ‌های کف
    swing_lows = []
    for i in range(start_idx + 1, n - 1):
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            swing_lows.append((i, lows[i], rsi[i]))

    # واگرایی‌های نزولی بر روی سقف‌ها
    if len(swing_highs) >= 2:
        _, prev_high, prev_rsi = swing_highs[-2]
        _, last_high, last_rsi = swing_highs[-1]

        # Regular Bearish: سقف بالاتر قیمت، سقف پایین‌تر RSI (فرسودگی خریداران)
        if last_high > prev_high and last_rsi < prev_rsi and prev_rsi > 50:
            strength = round((prev_rsi - last_rsi) / 10.0, 2)
            return "BEARISH_REGULAR", min(1.0, max(0.2, strength))

        # Hidden Bearish: سقف پایین‌تر قیمت، سقف بالاتر RSI (ادامه روند نزولی)
        if last_high < prev_high and last_rsi > prev_rsi:
            strength = round((last_rsi - prev_rsi) / 10.0, 2)
            return "BEARISH_HIDDEN", min(1.0, max(0.2, strength))

    # واگرایی‌های صعودی بر روی کف‌ها
    if len(swing_lows) >= 2:
        _, prev_low, prev_rsi = swing_lows[-2]
        _, last_low, last_rsi = swing_lows[-1]

        # Regular Bullish: کف پایین‌تر قیمت، کف بالاتر RSI (فرسودگی فروشندگان)
        if last_low < prev_low and last_rsi > prev_rsi and prev_rsi < 50:
            strength = round((last_rsi - prev_rsi) / 10.0, 2)
            return "BULLISH_REGULAR", min(1.0, max(0.2, strength))

        # Hidden Bullish: کف بالاتر قیمت، کف پایین‌تر RSI (ادامه روند صعودی)
        if last_low > prev_low and last_rsi < prev_rsi:
            strength = round((prev_rsi - last_rsi) / 10.0, 2)
            return "BULLISH_HIDDEN", min(1.0, max(0.2, strength))

    return None, 0.0
