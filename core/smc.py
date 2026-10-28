""" core/smc — موتور تحلیل Smart Money Concepts (SMC / ICT) برای طلا

مفاهیم کلیدی الگوریتمی:
۱. بلاک‌های سفارش سازمانی (Order Blocks - OB): صعودی و نزولی، بررسی Mitigated / Unmitigated
۲. شکاف ارزش منصفانه (Fair Value Gap - FVG): نواحی عدم تعادل نقدینگی
۳. شکار نقدینگی (Liquidity Sweep): جمع‌آوری استاپ‌های بالا/پایین سوئینگ‌ها و بازگشت قیمت
۴. شکست ساختار (BOS) و تغییر ماهیت روند (CHOCH)
۵. نواحی گران‌فروشی (Premium) و ارزان‌فروشی (Discount) بر مبنای بازه سوئینگ
۶. سشن‌های فعال نقدینگی (Killzones: لندن و نیویورک)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from core.entities import Candle

log = logging.getLogger(__name__)


class OBType(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class FVGType(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class MarketPhase(str, Enum):
    BOS_BULLISH = "BOS_BULLISH"
    BOS_BEARISH = "BOS_BEARISH"
    CHOCH_BULLISH = "CHOCH_BULLISH"
    CHOCH_BEARISH = "CHOCH_BEARISH"
    RANGE = "RANGE"


class ZoneType(str, Enum):
    DISCOUNT = "DISCOUNT"        # 0% - 45% (محدوده بهینه خرید)
    EQUILIBRIUM = "EQUILIBRIUM"  # 45% - 55% (تعادل)
    PREMIUM = "PREMIUM"          # 55% - 100% (محدوده بهینه فروش)


@dataclass(frozen=True)
class OrderBlock:
    ob_type: OBType
    top: float
    bottom: float
    bar_index: int
    time: int
    mitigated: bool = False

    @property
    def midpoint(self) -> float:
        return (self.top + self.bottom) / 2.0


@dataclass(frozen=True)
class FairValueGap:
    fvg_type: FVGType
    top: float
    bottom: float
    bar_index: int
    time: int
    filled: bool = False


@dataclass(frozen=True)
class LiquiditySweep:
    swept: bool
    side: Optional[str] = None  # "HIGH" (Bearish Reversal) | "LOW" (Bullish Reversal)
    level: float = 0.0
    bar_index: int = 0


@dataclass(frozen=True)
class SMCView:
    bias: str                      # "bullish" | "bearish" | "neutral"
    confidence: float              # 0.0 .. 1.0
    phase: MarketPhase
    zone: ZoneType
    fib_level: float               # 0.0 .. 1.0
    killzone: str                  # "london" | "newyork" | "london_close" | "asia" | "dead"
    is_ote: bool = False           # Optimal Trade Entry (Fib 0.618 - 0.786)
    unmitigated_obs: list[OrderBlock] = field(default_factory=list)
    unfilled_fvgs: list[FairValueGap] = field(default_factory=list)
    sweep: Optional[LiquiditySweep] = None
    judas_swing: Optional[str] = None  # "BEARISH_JUDAS" | "BULLISH_JUDAS"
    swing_high: float = 0.0
    swing_low: float = 0.0


class SMCAnalyzer:
    """تحلیلگر جامع الگوهای سازمانی و هوشمند (SMC/ICT)."""

    def analyze(
        self,
        candles: list[Candle],
        h1_candles: Optional[list[Candle]] = None,
        now_dt: Optional[datetime] = None,
    ) -> SMCView:
        if len(candles) < 20:
            return SMCView(
                bias="neutral",
                confidence=0.0,
                phase=MarketPhase.RANGE,
                zone=ZoneType.EQUILIBRIUM,
                fib_level=0.5,
                killzone="dead",
            )

        now = now_dt or datetime.now(timezone.utc)
        killzone = self.detect_killzone(now)

        # ۱. ساختار بازار (BOS / CHOCH)
        phase, phase_bias = self.detect_structure_phase(candles)

        # ۲. بلاک‌های سفارش (Order Blocks)
        obs = self.detect_order_blocks(candles)
        unmitigated_obs = [ob for ob in obs if not ob.mitigated]

        # ۳. شکاف‌های ارزش منصفانه (FVG)
        fvgs = self.detect_fvgs(candles)
        unfilled_fvgs = [f for f in fvgs if not f.filled]

        # ۴. هانت نقدینگی (Liquidity Sweep)
        sweep = self.detect_liquidity_sweep(candles)

        # ۵. محدوده Premium / Discount و OTE
        zone, fib, swing_high, swing_low = self.detect_premium_discount(candles, h1_candles)
        is_ote = (0.618 <= fib <= 0.786) or (0.214 <= fib <= 0.382)

        # ۵.ب شکار نقدینگی سشن آسیا (Judas Swing)
        judas = self.detect_judas_swing(candles, killzone)

        # ۶. تلفیق جهت و امتیازدهی اعتماد (Bias & Confidence)
        bias, conf = self._compute_bias_and_confidence(
            phase_bias, unmitigated_obs, unfilled_fvgs, sweep, zone, killzone, judas
        )

        return SMCView(
            bias=bias,
            confidence=round(conf, 2),
            phase=phase,
            zone=zone,
            fib_level=round(fib, 3),
            killzone=killzone,
            is_ote=is_ote,
            unmitigated_obs=unmitigated_obs,
            unfilled_fvgs=unfilled_fvgs,
            sweep=sweep if sweep.swept else None,
            judas_swing=judas,
            swing_high=swing_high,
            swing_low=swing_low,
        )

    # ── تشخیص سشن نقدینگی (Killzones) ────────────────────

    @staticmethod
    def detect_killzone(dt: datetime) -> str:
        """تشخیص بازه زمانی نقدینگی بالا بر اساس ساعت UTC."""
        h = dt.hour
        m = dt.minute
        time_decimal = h + m / 60.0

        # London Open Killzone: 07:00 - 10:00 UTC
        if 7.0 <= time_decimal < 10.0:
            return "london"
        # New York Open Killzone: 12:00 - 15:00 UTC
        if 12.0 <= time_decimal < 15.0:
            return "newyork"
        # London Close Killzone: 15:00 - 17:00 UTC
        if 15.0 <= time_decimal < 17.0:
            return "london_close"
        # Asian Session: 00:00 - 06:00 UTC
        if 0.0 <= time_decimal < 6.0:
            return "asia"
        return "dead"

    # ── تشخیص ساختار بازار ───────────────────────────────

    @staticmethod
    def detect_structure_phase(candles: list[Candle]) -> tuple[MarketPhase, str]:
        """تشخیص شکست ساختار (BOS) یا تغییر ماهیت روند (CHOCH)."""
        lookback = min(30, len(candles))
        sub = candles[-lookback:]

        highs = [c.high for c in sub]
        lows = [c.low for c in sub]
        closes = [c.close for c in sub]

        swing_high = max(highs[:-3])
        swing_low = min(lows[:-3])
        last_close = closes[-1]

        # شکست صعودی
        if last_close > swing_high:
            prev_bearish = closes[-4] < closes[-7]
            if prev_bearish:
                return MarketPhase.CHOCH_BULLISH, "bullish"
            return MarketPhase.BOS_BULLISH, "bullish"

        # شکست نزولی
        if last_close < swing_low:
            prev_bullish = closes[-4] > closes[-7]
            if prev_bullish:
                return MarketPhase.CHOCH_BEARISH, "bearish"
            return MarketPhase.BOS_BEARISH, "bearish"

        # روند کلی بر اساس شیب کلوزها
        if closes[-1] > closes[-10] and closes[-10] > closes[-20]:
            return MarketPhase.BOS_BULLISH, "bullish"
        if closes[-1] < closes[-10] and closes[-10] < closes[-20]:
            return MarketPhase.BOS_BEARISH, "bearish"

        return MarketPhase.RANGE, "neutral"

    # ── بلاک‌های سفارش (Order Blocks) ────────────────────

    @staticmethod
    def detect_order_blocks(candles: list[Candle]) -> list[OrderBlock]:
        """شناسایی اردر بلاک‌ها و بررسی میتیگیت شدن آن‌ها."""
        obs: list[OrderBlock] = []
        n = len(candles)
        if n < 5:
            return obs

        # میانگین بدنه کندل‌ها برای سنجش مومنتوم
        avg_body = sum(c.body for c in candles[-30:]) / min(30, n)

        for i in range(2, n - 2):
            c_prev = candles[i]
            c_next = candles[i + 1]

            # Bullish OB: کندل نزولی قبل از یک کندل صعودی پرقدرت
            if not c_prev.is_bullish and c_next.is_bullish and c_next.body > avg_body * 1.5:
                if c_next.close > c_prev.high:
                    top = max(c_prev.open, c_prev.close)
                    bottom = c_prev.low
                    # بررسی میتیگیشن توسط کندل‌های بعدی
                    mitigated = any(c.low <= top for c in candles[i + 2:])
                    obs.append(OrderBlock(
                        ob_type=OBType.BULLISH,
                        top=round(top, 2),
                        bottom=round(bottom, 2),
                        bar_index=i,
                        time=c_prev.time,
                        mitigated=mitigated,
                    ))

            # Bearish OB: کندل صعودی قبل از یک کندل نزولی پرقدرت
            if c_prev.is_bullish and not c_next.is_bullish and c_next.body > avg_body * 1.5:
                if c_next.close < c_prev.low:
                    top = c_prev.high
                    bottom = min(c_prev.open, c_prev.close)
                    mitigated = any(c.high >= bottom for c in candles[i + 2:])
                    obs.append(OrderBlock(
                        ob_type=OBType.BEARISH,
                        top=round(top, 2),
                        bottom=round(bottom, 2),
                        bar_index=i,
                        time=c_prev.time,
                        mitigated=mitigated,
                    ))

        return obs[-6:]  # حفظ حداکثر ۶ اردر بلاک اخیر

    # ── شکاف ارزش منصفانه (Fair Value Gaps) ───────────────

    @staticmethod
    def detect_fvgs(candles: list[Candle]) -> list[FairValueGap]:
        """شناسایی FVGهای ۳ کندلی."""
        fvgs: list[FairValueGap] = []
        n = len(candles)
        if n < 4:
            return fvgs

        for i in range(2, n):
            c0 = candles[i - 2]
            c2 = candles[i]

            # Bullish FVG: کف کندل ۲ بالاتر از سقف کندل ۰
            if c2.low > c0.high:
                bottom = c0.high
                top = c2.low
                filled = any(c.low <= bottom for c in candles[i + 1:])
                fvgs.append(FairValueGap(
                    fvg_type=FVGType.BULLISH,
                    top=round(top, 2),
                    bottom=round(bottom, 2),
                    bar_index=i - 1,
                    time=candles[i - 1].time,
                    filled=filled,
                ))

            # Bearish FVG: سقف کندل ۲ پایین‌تر از کف کندل ۰
            if c2.high < c0.low:
                top = c0.low
                bottom = c2.high
                filled = any(c.high >= top for c in candles[i + 1:])
                fvgs.append(FairValueGap(
                    fvg_type=FVGType.BEARISH,
                    top=round(top, 2),
                    bottom=round(bottom, 2),
                    bar_index=i - 1,
                    time=candles[i - 1].time,
                    filled=filled,
                ))

        return fvgs[-6:]

    # ── هانت نقدینگی (Liquidity Sweep) ───────────────────

    @staticmethod
    def detect_liquidity_sweep(candles: list[Candle]) -> LiquiditySweep:
        """تشخیص استاپ هانت در سوئینگ‌های اخیر."""
        if len(candles) < 15:
            return LiquiditySweep(swept=False)

        recent = candles[-10:-1]
        last = candles[-1]

        highs = [c.high for c in recent]
        lows = [c.low for c in recent]

        prev_high = max(highs)
        prev_low = min(lows)

        # شکار سقف: شدو بالاتر از سقف قبلی رفته اما کلوز زیر سقف برگشته
        if last.high > prev_high and last.close < prev_high:
            return LiquiditySweep(swept=True, side="HIGH", level=prev_high, bar_index=len(candles) - 1)

        # شکار کف: شدو پایین‌تر از کف قبلی رفته اما کلوز بالای کف برگشته
        if last.low < prev_low and last.close > prev_low:
            return LiquiditySweep(swept=True, side="LOW", level=prev_low, bar_index=len(candles) - 1)

        return LiquiditySweep(swept=False)

    # ── محدوده Premium / Discount ────────────────────────

    @staticmethod
    def detect_premium_discount(
        candles: list[Candle],
        h1_candles: Optional[list[Candle]] = None
    ) -> tuple[ZoneType, float, float, float]:
        """محاسبه موقعیت قیمت نسبت به رنج سوئینگ اخیر (۰ تا ۱)."""
        ref_candles = h1_candles if h1_candles and len(h1_candles) >= 15 else candles[-30:]
        highs = [c.high for c in ref_candles]
        lows = [c.low for c in ref_candles]

        swing_high = max(highs)
        swing_low = min(lows)
        rng = swing_high - swing_low
        if rng <= 0:
            return ZoneType.EQUILIBRIUM, 0.5, swing_high, swing_low

        cur_price = candles[-1].close
        fib = (cur_price - swing_low) / rng

        if fib <= 0.45:
            zone = ZoneType.DISCOUNT
        elif fib >= 0.55:
            zone = ZoneType.PREMIUM
        else:
            zone = ZoneType.EQUILIBRIUM

        return zone, fib, round(swing_high, 2), round(swing_low, 2)

    # ── شکار نقدینگی سشن آسیا (Judas Swing) ──────────────

    @staticmethod
    def detect_judas_swing(candles: list[Candle], killzone: str) -> Optional[str]:
        """تشخیص شکار نقدینگی سشن آسیا در آغاز سشن لندن (Judas Swing)."""
        if killzone != "london" or len(candles) < 30:
            return None
        asia_candles = []
        for c in candles[-40:]:
            h = (c.time % 86400) // 3600
            if 0 <= h < 6:
                asia_candles.append(c)
        if len(asia_candles) < 4:
            return None
        asia_high = max(c.high for c in asia_candles)
        asia_low = min(c.low for c in asia_candles)

        last = candles[-1]
        # شکار سقف آسیا و بازگشت به زیر آن
        if last.high > asia_high and last.close < asia_high:
            return "BEARISH_JUDAS"
        # شکار کف آسیا و بازگشت به بالای آن
        if last.low < asia_low and last.close > asia_low:
            return "BULLISH_JUDAS"
        return None

    # ── محاسبه دیدگاه و درجه اطمینان ─────────────────────

    @staticmethod
    def _compute_bias_and_confidence(
        phase_bias: str,
        unmitigated_obs: list[OrderBlock],
        unfilled_fvgs: list[FairValueGap],
        sweep: LiquiditySweep,
        zone: ZoneType,
        killzone: str,
        judas: Optional[str] = None,
    ) -> tuple[str, float]:
        bull_score = 0.0
        bear_score = 0.0

        # فاکتور ساختار (وزن ۰.۳۰)
        if phase_bias == "bullish":
            bull_score += 0.30
        elif phase_bias == "bearish":
            bear_score += 0.30

        # فاکتور نقدینگی و هانت (وزن ۰.۲۵)
        if sweep.swept:
            if sweep.side == "LOW":  # شکار کف -> صعودی
                bull_score += 0.25
            elif sweep.side == "HIGH":  # شکار سقف -> نزولی
                bear_score += 0.25

        # فاکتور اردر بلاک و FVG (وزن ۰.۲۵)
        bull_obs = [ob for ob in unmitigated_obs if ob.ob_type == OBType.BULLISH]
        bear_obs = [ob for ob in unmitigated_obs if ob.ob_type == OBType.BEARISH]
        if bull_obs:
            bull_score += 0.15
        if bear_obs:
            bear_score += 0.15

        bull_fvgs = [f for f in unfilled_fvgs if f.fvg_type == FVGType.BULLISH]
        bear_fvgs = [f for f in unfilled_fvgs if f.fvg_type == FVGType.BEARISH]
        if bull_fvgs:
            bull_score += 0.10
        if bear_fvgs:
            bear_score += 0.10

        # فاکتور ناحیه قیمت (وزن ۰.۲۰)
        if zone == ZoneType.DISCOUNT:
            bull_score += 0.20
        elif zone == ZoneType.PREMIUM:
            bear_score += 0.20

        # فاکتور شکار نقدینگی سشن آسیا (Judas Swing) — وزن ۰.۳۰ بسیار قدرتمند
        if judas == "BULLISH_JUDAS":
            bull_score += 0.30
        elif judas == "BEARISH_JUDAS":
            bear_score += 0.30

        # پاداش سشن نقدینگی فعال
        kz_mult = 1.0 if killzone in ("london", "newyork", "london_close") else 0.8

        if bull_score > bear_score and bull_score >= 0.40:
            return "bullish", min(1.0, bull_score * kz_mult)
        if bear_score > bull_score and bear_score >= 0.40:
            return "bearish", min(1.0, bear_score * kz_mult)

        return "neutral", 0.0
