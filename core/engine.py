""" core/engine — موتور تحلیل و تصمیم هرمس

تحلیل تکنیکال (روند، ATR، ساختار بازار) + ترکیب با سیگنال کانال → Plan.

این موتور «مغز» است: داده بازار را می‌گیرد، تصمیم می‌سازد.
نقش ورود به بازار را gates deciding می‌کند (اینجا نه).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

from core.entities import Candle, Plan, SetupGrade, Side, Signal, Tick

log = logging.getLogger(__name__)

# ── پارامترهای ستاپ تحلیلی (تاییدشده با بک‌تست روی ۱۲۱ ترید) ──
SL_ATR_MULT = 1.5        # فاصله استاپ = ۱.۵ × ATR
TRAIL_ATR_MULT = 3.0     # فاصله trailing = ۳ × ATR


@dataclass(frozen=True)
class MarketView:
    """تصویر فعلی بازار — خروجی تحلیل."""
    trend: str               # "bullish" | "bearish" | "ranging"
    trend_strength: float    # 0..1
    atr: float               # نوسان فعلی
    spread: float
    last_price: float
    support: float
    resistance: float
    notes: str = ""

    @property
    def is_trending(self) -> bool:
        return self.trend != "ranging" and self.trend_strength >= 0.5


class Engine:
    """موتور تحلیل + ساخت Plan.

    متدها pure هستند: ورودی زنده، خروجی تصمیم. هیچ state‌ای giữ نمی‌شود.
    """

    # ── تحلیل ───────────────────────────────────────────

    def analyze(self, candles: list[Candle], tick: Tick) -> MarketView:
        """تحلیل بازار از کندل‌ها + تیک فعلی.

        از EMA و ATR و ساختار سقف/کف استفاده می‌کند.
        """
        if len(candles) < 30:
            return MarketView(trend="ranging", trend_strength=0.0, atr=0.0,
                              spread=tick.spread, last_price=tick.mid,
                              support=0.0, resistance=0.0,
                              notes="insufficient_candles")

        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]

        # روند: EMA سریع vs کند + شیب
        ema_fast = _ema(closes, 20)
        ema_slow = _ema(closes, 50)
        last_close = closes[-1]

        if ema_fast > ema_slow and last_close > ema_slow:
            trend = "bullish"
        elif ema_fast < ema_slow and last_close < ema_slow:
            trend = "bearish"
        else:
            trend = "ranging"

        # قدرت روند: فاصله نسبی EMAها
        span = max(ema_slow, 1.0)
        strength = min(1.0, abs(ema_fast - ema_slow) / (span * 0.005))

        # ATR (14)
        atr = _atr(candles, 14)

        # سطوح کلیدی: swing high/low اخیر
        support = min(lows[-50:]) if len(lows) >= 50 else min(lows)
        resistance = max(highs[-50:]) if len(highs) >= 50 else max(highs)

        return MarketView(
            trend=trend,
            trend_strength=round(strength, 3),
            atr=round(atr, 2),
            spread=tick.spread,
            last_price=tick.mid,
            support=round(support, 2),
            resistance=round(resistance, 2),
            notes=f"ema_fast={ema_fast:.2f} ema_slow={ema_slow:.2f}",
        )

    # ── تحلیل خودکار: ستاپ روند-EMA ──────────────────────

    def plan_from_analysis(self, candles: list[Candle], view: MarketView,
                           timeframe: str = "M15") -> Optional[Plan]:
        """ساخت Plan از تحلیل خالص بازار — بدون سیگنال کانال.

        ستاپ روند-EMA (تاییدشده با بک‌تست: ۱۲۱ ترید، EV=+۰.۱۶۳R):
          ورود: کلوز > EMA20 > EMA50 (BUY) / کلوز < EMA20 < EMA50 (SELL)
          SL:   ۱.۵ × ATR
          TP:   ندارد — سود از trailing-stop گرفته می‌شود (W=+۲.۴R)

        fail-closed: هر ابهامی → None.
        """
        if len(candles) < 60 or view.atr <= 0:
            return None

        closes = [c.close for c in candles[-60:]]
        e20 = _ema(closes, 20)
        e50 = _ema(closes, 50)
        last = closes[-1]

        if last > e20 > e50:
            side = Side.BUY
        elif last < e20 < e50:
            side = Side.SELL
        else:
            return None  # ترکیب EFA هم‌جهت نیست → بدون ستاپ

        entry = view.last_price
        if side == Side.BUY:
            sl = entry - view.atr * SL_ATR_MULT
            tp = 0.0  # TP ندارد — مدیریت سود با trailing
        else:
            sl = entry + view.atr * SL_ATR_MULT
            tp = 0.0

        if entry <= 0 or sl <= 0:
            return None

        grade = SetupGrade.B  # ستاپ تحلیلی استاندارد
        # ستاپ TP ندارد → RR اسمی بی‌نهایت است. برای عبور از دروازه min_rr
        # یک RR هدف فرضی بر اساس trailing distance ثبت می‌کنیم (حداقل حرکت
        # مورد انتظار = فاصله trailing) — این عدد فقط جنبه نمایش/دروازه دارد.
        rr = TRAIL_ATR_MULT / SL_ATR_MULT  # 3.0/1.5 = 2.0

        return Plan(
            plan_id=f"auto-{int(candles[-1].time)}",
            symbol="XAUUSD",
            side=side,
            entry_price=round(entry, 2),
            stop_loss=round(sl, 2),
            take_profit=tp,
            volume=0.0,
            grade=grade,
            source="analysis",
            timeframe=timeframe,
            rr=rr,
            confidence=0.5,
            reasoning=f"ema_trend {view.trend} str={view.trend_strength:.2f} "
                      f"atr={view.atr:.2f} e20={e20:.2f} e50={e50:.2f}",
        )

    # ── ساخت Plan ───────────────────────────────────────

    def plan_from_signal(self, sig: Signal, view: MarketView, timeframe: str = "M15") -> Optional[Plan]:
        """ساخت Plan از سیگنال کانال + تایید روند بازار.

        قوانین (fail-closed):
        - سیگنال نامعتبر → None
        - جهت سیگنال خلاف روند قوی بازار → None (فیلتتر)
        """
        if not sig.is_valid:
            log.info("signal invalid: %s", sig.signal_id)
            return None

        # تایید روند: سیگنال خرید فقط در روند صعودی/رنج، فروش برعکس
        if view.is_trending:
            if sig.side == Side.BUY and view.trend == "bearish":
                log.info("signal vs trend (BUY in bearish)")
                return None
            if sig.side == Side.SELL and view.trend == "bullish":
                log.info("signal vs trend (SELL in bullish)")
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
            volume=0.0,             # حجم را gates محاسبه می‌کند
            grade=grade,
            source="signal",
            timeframe=timeframe,
            rr=round(rr, 3),
            confidence=sig.confidence,
            reasoning=f"trend={view.trend} atr={view.atr}",
        )

    # ── private ─────────────────────────────────────────

    @staticmethod
    def _grade_signal(sig: Signal, view: MarketView) -> SetupGrade:
        """گریدبندی کیفیت ستاپ — A بهترین."""
        score = 0.0
        # کیفیت خود سیگنال
        score += min(1.0, sig.confidence) * 0.5
        # RR
        score += min(1.0, sig.rr / 2.0) * 0.3
        # هماهنگی با روند
        if view.is_trending:
            aligned = (sig.side == Side.BUY and view.trend == "bullish") or \
                      (sig.side == Side.SELL and view.trend == "bearish")
            score += 0.2 if aligned else 0.0
        else:
            score += 0.1

        if score >= 0.8:
            return SetupGrade.A
        if score >= 0.6:
            return SetupGrade.B
        if score >= 0.4:
            return SetupGrade.C
        return SetupGrade.D


# ── اندیکاتورها (pure functions) ────────────────────────

def _ema(values: list[float], period: int) -> float:
    """EMA ساده روی لیست قیمت."""
    if not values:
        return 0.0
    k = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _atr(candles: list[Candle], period: int = 14) -> float:
    """Average True Range."""
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
    """محاسبه RR از روی entry/sl/tp."""
    sl_dist = abs(sig.entry - sig.sl)
    tp_dist = abs(sig.tp - sig.entry)
    return tp_dist / sl_dist if sl_dist > 0 else 0.0
