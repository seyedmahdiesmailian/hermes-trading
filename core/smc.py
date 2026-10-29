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

    @property
    def midpoint(self) -> float:
        return (self.top + self.bottom) / 2.0


@dataclass(frozen=True)
class LiquiditySweep:
    swept: bool
    side: Optional[str] = None  # "HIGH" (Bearish Reversal) | "LOW" (Bullish Reversal)
    level: float = 0.0
    bar_index: int = 0


@dataclass(frozen=True)
class QuasimodoPattern:
    """الگوی بازگشتی پرایس‌اکشن سازمانی RTM Quasimodo (QML)."""
    qml_type: str        # "BEARISH_QML" | "BULLISH_QML"
    level: float         # تراز ورود شانه چپ (Left Shoulder)
    invalidation: float  # حد ضرر / سقف یا کف هانت
    target: float        # تارگت ساختاری
    bar_index: int


@dataclass(frozen=True)
class FTRZone:
    """ناحیه تصمیم‌گیری پرایس‌اکشن RTM Fail-To-Return (FTR)."""
    ftr_type: str        # "SUPPLY_FTR" | "DEMAND_FTR"
    base_top: float      # سقف بیس
    base_bottom: float   # کف بیس
    broken_level: float  # سطح شکسته‌شده
    bar_index: int
    mitigated: bool = False


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
    qml: Optional[QuasimodoPattern] = None  # الگوی RTM QML
    unmitigated_ftrs: list[FTRZone] = field(default_factory=list)  # نواحی RTM FTR
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

        # ۵.ج الگوهای پرایس‌اکشن سازمانی RTM (Quasimodo و FTR)
        qml_pattern = self.detect_quasimodo(candles)
        ftr_zones = self.detect_ftr_zones(candles)
        unmitigated_ftrs = [f for f in ftr_zones if not f.mitigated]

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
            qml=qml_pattern,
            unmitigated_ftrs=unmitigated_ftrs,
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
                    # بررسی میتیگیشن توسط کندل‌های بعدی قبل از کندل جاری
                    mitigated = any(c.low <= top for c in candles[i + 2 : -1]) if (i + 2 < n - 1) else False
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
                    # بررسی میتیگیشن توسط کندل‌های بعدی قبل از کندل جاری
                    mitigated = any(c.high >= bottom for c in candles[i + 2 : -1]) if (i + 2 < n - 1) else False
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
                filled = any(c.low <= bottom for c in candles[i + 1 : -1]) if (i + 1 < n - 1) else False
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
                filled = any(c.high >= top for c in candles[i + 1 : -1]) if (i + 1 < n - 1) else False
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

    # ── الگوهای پرایس‌اکشن سازمانی RTM ──────────────────

    @staticmethod
    def detect_quasimodo(candles: list[Candle]) -> Optional[QuasimodoPattern]:
        """تشخیص الگوی بازگشتی قدرتمند RTM Quasimodo (QML) در ۳۵ کندل اخیر."""
        n = len(candles)
        if n < 25:
            return None

        recent = candles[-35:]
        rn = len(recent)

        # شناسایی پیووت‌های سوئینگ سقف و کف
        sh = []
        sl = []
        for i in range(1, rn - 1):
            if recent[i].high > recent[i - 1].high and recent[i].high > recent[i + 1].high:
                sh.append((i, recent[i].high))
            if recent[i].low < recent[i - 1].low and recent[i].low < recent[i + 1].low:
                sl.append((i, recent[i].low))

        # بررسی Bearish QML: H1, L1, H2 (Higher High), L2 (Lower Low)
        if len(sh) >= 2 and len(sl) >= 2:
            h1_idx, h1 = sh[-2]
            h2_idx, h2 = sh[-1]
            lows_between = [l for l in sl if h1_idx < l[0] < h2_idx]
            lows_after = [l for l in sl if h2_idx < l[0]]

            if lows_between and lows_after:
                l1 = lows_between[0][1]
                l2 = min(l[1] for l in lows_after)
                if h2 > h1 and l2 < l1:
                    return QuasimodoPattern(
                        qml_type="BEARISH_QML",
                        level=round(h1, 2),
                        invalidation=round(h2, 2),
                        target=round(l2, 2),
                        bar_index=n - rn + h2_idx,
                    )

            # بررسی Bullish QML: L1, H1, L2 (Lower Low), H2 (Higher High)
            l1_idx, l1 = sl[-2]
            l2_idx, l2 = sl[-1]
            highs_between = [h for h in sh if l1_idx < h[0] < l2_idx]
            highs_after = [h for h in sh if l2_idx < h[0]]

            if highs_between and highs_after:
                h1 = highs_between[0][1]
                h2 = max(h[1] for h in highs_after)
                if l2 < l1 and h2 > h1:
                    return QuasimodoPattern(
                        qml_type="BULLISH_QML",
                        level=round(l1, 2),
                        invalidation=round(l2, 2),
                        target=round(h2, 2),
                        bar_index=n - rn + l2_idx,
                    )

        return None

    @staticmethod
    def detect_ftr_zones(candles: list[Candle]) -> list[FTRZone]:
        """شناسایی نواحی تصمیم‌گیری RTM Fail-To-Return (FTR)."""
        n = len(candles)
        if n < 20:
            return []

        ftrs: list[FTRZone] = []
        recent = candles[-30:]
        rn = len(recent)

        for i in range(5, rn - 3):
            c_break = recent[i]
            # شکست صعودی مقاومت (Bullish Engulf)
            res_level = max(c.high for c in recent[i - 5:i])
            if c_break.close > res_level and c_break.body > (c_break.high - c_break.low) * 0.6:
                c_base = recent[i + 1]
                if c_base.low >= res_level - 0.5:
                    top = max(c_base.open, c_base.close)
                    bottom = c_base.low
                    # بررسی میتیگیشن قبل از کندل جاری
                    mitigated = any(c.low <= top for c in recent[i + 2 : -1]) if (i + 2 < rn - 1) else False
                    ftrs.append(FTRZone(
                        ftr_type="DEMAND_FTR",
                        base_top=round(top, 2),
                        base_bottom=round(bottom, 2),
                        broken_level=round(res_level, 2),
                        bar_index=n - rn + i + 1,
                        mitigated=mitigated,
                    ))

            # شکست نزولی حمایت (Bearish Engulf)
            sup_level = min(c.low for c in recent[i - 5:i])
            if c_break.close < sup_level and c_break.body > (c_break.high - c_break.low) * 0.6:
                c_base = recent[i + 1]
                if c_base.high <= sup_level + 0.5:
                    top = c_base.high
                    bottom = min(c_base.open, c_base.close)
                    # بررسی میتیگیشن قبل از کندل جاری
                    mitigated = any(c.high >= bottom for c in recent[i + 2 : -1]) if (i + 2 < rn - 1) else False
                    ftrs.append(FTRZone(
                        ftr_type="SUPPLY_FTR",
                        base_top=round(top, 2),
                        base_bottom=round(bottom, 2),
                        broken_level=round(sup_level, 2),
                        bar_index=n - rn + i + 1,
                        mitigated=mitigated,
                    ))

        return ftrs[-4:]
