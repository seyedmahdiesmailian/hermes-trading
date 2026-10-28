""" core/gates — دروازه‌های امنیت هرمس

هر ورود به بازار از این دروازه می‌گذرد.
هر خطا = DENY. هرگز اجازه عبور نمی‌دهد (fail-closed).

منبع: ExecutionGuard V1 (۴۳۲ خط، ۷۷/۷۷ تست سبز) — منطق منتقل،
ساختار جدید طبق معماری صفر-مبدا (config.yaml + entities).

نکته کلیدی: پوزیشن‌های باز از خود بروکر خوانده می‌شوند (زنده)،
نه از دیتابیس. دیتابیس فقط دفتر کل است.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from core.entities import AccountState, BrokerPosition, Plan, SetupGrade
from core.params import Gates

log = logging.getLogger(__name__)

# XAUUSD: 1 لات = 100 اونس → 1.0 حرکت قیمت روی 1 لات = $100
CONTRACT_SIZE = Decimal("100")


@dataclass(frozen=True)
class GuardOutcome:
    """نتیجه دروازه — مجاز / ممنوع + دلایل + حجم نهایی."""
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    volume: float = 0.0
    grade: SetupGrade = SetupGrade.C

    @property
    def verdict(self) -> str:
        return "ALLOW" if self.allowed else "DENY"

    def __repr__(self) -> str:
        v = "✅" if self.allowed else "🚫"
        return f"Guard {v} vol={self.volume:.2f} {self.reasons}"


class GatesEngine:
    """موتور دروازه — config immutable، بدون state.

    نقش: بررسی یک Plan در برابر وضعیت زنده بازار/حساب/پوزیشن.
    هرگز از دیتابیس نمی‌خواند — همه ورودی‌ها زنده.
    """

    def __init__(self, gates: Gates):
        self._g = gates

    # ── API اصلی ───────────────────────────────────────

    def evaluate(
        self,
        plan: Plan,
        account: AccountState,
        positions: list[BrokerPosition],
        trades_today: int,
        daily_pnl: float,
        atr: float,
        spread: float,
        learning_min_rr: float = 0.0,
        learning_min_grade: str = "",
    ) -> GuardOutcome:
        """ارزیابی کامل plan → مجاز با حجم، یا ممنوع با دلایل.

        همه پارامترها زنده (از bridge). هیچ cached state‌ای نیست.
        """
        reasons: list[str] = []

        # ۱) پوزیشن‌های باز — حقیقت زنده bridge
        if len(positions) >= self._g.max_open_positions:
            reasons.append(f"position_limit({len(positions)}/{self._g.max_open_positions})")

        # ۲) سقف ترید روزانه
        if trades_today >= self._g.max_daily_trades:
            reasons.append(f"daily_trades({trades_today}/{self._g.max_daily_trades})")

        # ۳) ضرر روزانه → توقف کامل
        max_loss = account.balance * (self._g.max_daily_loss_pct / 100.0)
        if daily_pnl <= -max_loss:
            reasons.append(f"daily_loss({daily_pnl:.2f}<=-{max_loss:.2f})")

        # ۴) حداقل RR (سخت‌ترین: config یا یادگیری)
        eff_min_rr = max(self._g.min_rr, learning_min_rr or 0.0)
        if plan.rr < eff_min_rr:
            reasons.append(f"rr({plan.rr:.2f}<{eff_min_rr:.2f})")

        # ۵) حداقل گرید (سخت‌ترین)
        eff_min_grade = self._tougher_grade(self._g.min_grade, learning_min_grade)
        if SetupGrade.rank(plan.grade) < SetupGrade.rank(eff_min_grade):
            reasons.append(f"grade({plan.grade.value}<{eff_min_grade.value})")

        # ۶) فاصله استاپ ≥ ATR × k
        #    پلن‌های تحلیلی (source=analysis) ضریب جداگانه دارند:
        #    ستاپ روند-EMA با SL=۱.۵×ATR تایید شده (بک‌تست EV=+۰.۱۶۳).
        if atr > 0:
            sl_dist = abs(plan.entry_price - plan.stop_loss)
            mult = self._g.min_atr_stop_mult
            if plan.source == "analysis":
                mult = getattr(self._g, "min_atr_stop_mult_analysis",
                               self._g.min_atr_stop_mult)
            min_dist = atr * mult
            if sl_dist < min_dist:
                reasons.append(f"stop_too_tight({sl_dist:.2f}<{min_dist:.2f})")

        # ۷) اسپرد
        if spread > self._g.max_spread_points:
            reasons.append(f"spread({spread:.2f}>{self._g.max_spread_points})")

        # ۸) حساب
        if account.equity <= 0 or account.balance <= 0:
            reasons.append("equity_invalid")

        if reasons:
            log.warning("GUARD DENY %s: %s", plan.plan_id, reasons)
            return GuardOutcome(allowed=False, reasons=reasons)

        # ── مجاز → محاسبه حجم بر اساس ریسک ───────────
        volume = self._size_position(plan, account)
        if volume <= 0:
            return GuardOutcome(allowed=False, reasons=["size_failed"])

        log.info("GUARD ALLOW %s vol=%.3f", plan.plan_id, volume)
        return GuardOutcome(allowed=True, reasons=["ok"], volume=volume, grade=plan.grade)

    # ── private ───────────────────────────────────────

    def _size_position(self, plan: Plan, account: AccountState) -> float:
        """حجم بر اساس درصد ریسک: risk = equity × risk% / فاصله SL.

        volume_lots = risk_amount / (sl_distance × contract_size)
        """
        try:
            risk_pct = Decimal(str(self._g.risk_per_trade_pct)) / Decimal("100")
            risk_amount = Decimal(str(account.equity)) * risk_pct
            sl_distance = Decimal(str(abs(plan.entry_price - plan.stop_loss)))
            if sl_distance <= 0:
                return 0.0
            vol_dec = risk_amount / (sl_distance * CONTRACT_SIZE)
            # گرد کردن به ۰.۰۱ (حداقل حجم بروکر)
            vol = float(vol_dec.quantize(Decimal("0.01")))
            max_vol = self._g.max_volume_lots
            if vol > max_vol:
                log.warning("volume %.2f exceeds max_volume_lots %.2f — capping to max", vol, max_vol)
                vol = max_vol
            return max(vol, 0.0)
        except Exception:
            log.exception("size_position failed")
            return 0.0

    @staticmethod
    def _tougher_grade(a: str, b: str) -> SetupGrade:
        """سخت‌ترین گرید برنده — fail-closed."""
        try:
            ga = SetupGrade(a.strip().upper())
        except ValueError:
            ga = SetupGrade.B
        if not b:
            return ga
        try:
            gb = SetupGrade(b.strip().upper())
        except ValueError:
            return ga
        return ga if SetupGrade.rank(ga) >= SetupGrade.rank(gb) else gb
