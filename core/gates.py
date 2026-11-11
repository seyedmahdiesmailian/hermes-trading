""" core/gates — دروازه‌های امنیت هرمس

هر ورود به بازار از این دروازه می‌گذرد.
هر خطا = DENY. هرگز اجازه عبور نمی‌دهد (fail-closed).

منبع: ExecutionGuard V1 (۴۳۲ خط، ۷۷/۷۷ تست سبز) — منطق منتقل،
ساختار جدید طبق معماری صفر-مبدا (config.yaml + entities).

نکته کلیدی: پوزیشن‌های باز از خود بروکر خوانده می‌شوند (زنده)،
نه از دیتابیس. دیتابیس فقط دفتر کل است.

قرارداد پایدار b221 (Invariant Contract):
«بریج ناخوانا یا خاموش در دروازه ورود رد می‌شود، هرگز توسط یک سیاست مجزای بالادستی تایید نمی‌شود.»
هر دو کانال ورود (سیگنال کانال تلگرام و تحلیل ساختار بازار) منحصراً از GatesEngine عبور می‌کنند.
اگر اطلاعات حساب یا پوزیشن‌ها ناخوانا یا None باشد، با دلایل positions_unreadable یا equity_invalid
به صورت fail-closed مسدود می‌شود تا هیچ تریدی در وضعیت تاریک بروکر باز نشود.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from core.entities import AccountState, BrokerPosition, Plan, SetupGrade, Side
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
        account: AccountState | None,
        positions: list[BrokerPosition] | None,
        trades_today: int,
        daily_pnl: float,
        atr: float,
        spread: float,
        learning_min_rr: float = 0.0,
        learning_min_grade: str = "",
        last_loss_ts: float = 0.0,
        now_ts: float = 0.0,
        channel_stats: dict | None = None,
        weekly_pnl: float = 0.0,
        consecutive_losses: int = 0,
    ) -> GuardOutcome:
        """ارزیابی کامل plan → مجاز با حجم، یا ممنوع با دلایل.

        همه پارامترها زنده (از bridge). هیچ cached state‌ای نیست.
        """
        reasons: list[str] = []

        # ۰) قفل استراحت پس از استاپ (Loss Cooldown Circuit)
        cooldown_s = getattr(self._g, "loss_cooldown_minutes", 45) * 60
        now = now_ts or time.time()
        if last_loss_ts > 0 and 0 <= (now - last_loss_ts) < cooldown_s:
            rem_m = int(round((cooldown_s - (now - last_loss_ts)) / 60))
            reasons.append(f"loss_cooldown({rem_m}m_left)")

        # ۰.الف) سقف باخت‌های متوالی روزانه (Consecutive Losses Circuit Breaker)
        max_losses = getattr(self._g, "max_consecutive_losses", 3)
        if consecutive_losses >= max_losses:
            reasons.append(f"consecutive_losses({consecutive_losses}/{max_losses})")

        # ۰.ب) گیت پایان هفته و تعطیلی بروکر (Weekend / Friday Cutoff Gate)
        gm = time.gmtime(now)
        weekday = gm.tm_wday  # 0=Monday, 4=Friday, 5=Saturday, 6=Sunday
        time_decimal = gm.tm_hour + gm.tm_min / 60.0

        if weekday == 4 and time_decimal >= 19.5:
            reasons.append("friday_cutoff")
        elif weekday == 5 or (weekday == 6 and time_decimal < 22.0):
            reasons.append("weekend_closed")

        # ۰.ج) سپر اسپرد رول‌اوور شبانه بانکی (Rollover Spread Shield: 21:00 - 22:30 UTC)
        if weekday in (0, 1, 2, 3) and (21.0 <= time_decimal < 22.5):
            reasons.append("nightly_rollover")

        # ۱) پوزیشن‌های باز — حقیقت زنده bridge (قرارداد b221: fail-closed)
        if positions is None:
            reasons.append("positions_unreadable")
        else:
            # b250: همزمانی بدون ریسک (Risk-Free Concurrency)
            # پوزیشن‌هایی که استاپ آن‌ها در نقطه ورود یا بهتر قرار دارد ریسک حساب را صفر کرده‌اند
            risky_positions = [p for p in positions if not getattr(p, "is_risk_free", False)]
            max_concurrent = getattr(self._g, "max_concurrent_positions", 2)
            if len(risky_positions) >= self._g.max_open_positions:
                reasons.append(f"position_limit({len(risky_positions)}/{self._g.max_open_positions})")
            elif len(positions) >= max_concurrent:
                reasons.append(f"max_concurrent_limit({len(positions)}/{max_concurrent})")

        # ۲) سقف ترید روزانه
        if trades_today >= self._g.max_daily_trades:
            reasons.append(f"daily_trades({trades_today}/{self._g.max_daily_trades})")

        # ۳) ضرر روزانه → توقف کامل
        if account is not None and account.balance > 0:
            max_loss = account.balance * (self._g.max_daily_loss_pct / 100.0)
            if daily_pnl <= -max_loss:
                reasons.append(f"daily_loss({daily_pnl:.2f}<=-{max_loss:.2f})")

        # ۴) حداقل RR (سخت‌ترین: config یا یادگیری)
        # برای سیگنال‌های کانال و واچ‌لیست، کف مصوب config.yaml مبناست تا سیگنال‌های 1:1 معتبر نسوزند
        if plan.source in ("signal", "watchlist_pullback"):
            eff_min_rr = self._g.min_rr
        else:
            eff_min_rr = max(self._g.min_rr, learning_min_rr or 0.0)
        if plan.rr < eff_min_rr:
            reasons.append(f"rr({plan.rr:.2f}<{eff_min_rr:.2f})")

        # ۵) حداقل گرید (سخت‌ترین)
        if plan.source in ("signal", "watchlist_pullback"):
            eff_min_grade = self._tougher_grade(self._g.min_grade, "")
        else:
            eff_min_grade = self._tougher_grade(self._g.min_grade, learning_min_grade)
        if SetupGrade.rank(plan.grade) < SetupGrade.rank(eff_min_grade):
            reasons.append(f"grade({plan.grade.value}<{eff_min_grade.value})")

        # ۶) فاصله استاپ ≥ ATR × k
        #    پلن‌های تحلیلی، سازمانی و سیگنال‌های تلگرام هر کدام ضریب استاپ واقع‌بینانه دارند
        if atr > 0:
            sl_dist = round(abs(plan.entry_price - plan.stop_loss), 2)
            mult = self._g.min_atr_stop_mult
            if plan.source == "analysis":
                mult = getattr(self._g, "min_atr_stop_mult_analysis",
                               self._g.min_atr_stop_mult)
            elif plan.source.startswith("smc") or plan.source.startswith("rtm") or plan.source.startswith("ict") or plan.source in ("smc_ob", "smc_judas", "smc_fvg", "rtm_qml", "rtm_ftr"):
                mult = getattr(self._g, "min_atr_stop_mult_smc", 1.2)
            elif plan.source == "watchlist_pullback":
                mult = getattr(self._g, "min_atr_stop_mult_watchlist", 0.8)
            elif plan.source in ("signal",) or plan.source.startswith("sig_"):
                sig_mult = getattr(self._g, "min_atr_stop_mult_signal", 0.0)
                mult = sig_mult if sig_mult > 0 else self._g.min_atr_stop_mult
            min_dist = round(atr * mult, 2)
            if sl_dist < min_dist:
                reasons.append(f"stop_too_tight({sl_dist:.2f}<{min_dist:.2f})")

        # ۷) اسپرد
        if spread > self._g.max_spread_points:
            reasons.append(f"spread({spread:.2f}>{self._g.max_spread_points})")

        # ۸) حساب معتبر (قرارداد b221: fail-closed در حساب نامعتبر یا bridge خاموش)
        if account is None or account.equity <= 0 or account.balance <= 0:
            reasons.append("equity_invalid")

        # ۹) اعتبار هندسه استاپ و تارگت نسبت به جهت ورود (Invalid Stops)
        if (plan.side == Side.BUY and plan.stop_loss >= plan.entry_price) or \
           (plan.side == Side.SELL and plan.stop_loss <= plan.entry_price):
            reasons.append("invalid_stops")
        elif plan.take_profit > 0:
            if (plan.side == Side.BUY and plan.take_profit <= plan.entry_price) or \
               (plan.side == Side.SELL and plan.take_profit >= plan.entry_price):
                reasons.append("invalid_stops")

        # ۱۰) فیلتر کیفیت منبع سیگنال (Channel Scorecard / Auto-Pruning)
        if plan.source.startswith("sig_"):
            ch_stats = channel_stats or {}
            src_total = ch_stats.get("total", 0)
            src_wr = ch_stats.get("win_rate", 50.0)
            src_pnl = ch_stats.get("net_pnl", 0.0)
            if src_total >= 10 and (src_wr < 40.0 or src_pnl < -250.0):
                reasons.append(f"channel_pruned({plan.source}:{src_wr:.1f}%_pnl={src_pnl:.1f})")

        if reasons:
            log.warning("GUARD DENY %s: %s", plan.plan_id, reasons)
            return GuardOutcome(allowed=False, reasons=reasons)

        # ── مجاز → محاسبه حجم بر اساس ریسک ───────────
        volume = self._size_position(plan, account, daily_pnl=daily_pnl, weekly_pnl=weekly_pnl)
        if volume <= 0:
            return GuardOutcome(allowed=False, reasons=["size_failed"])

        log.info("GUARD ALLOW %s vol=%.3f", plan.plan_id, volume)
        return GuardOutcome(allowed=True, reasons=["ok"], volume=volume, grade=plan.grade)

    # ── private ───────────────────────────────────────

    def _size_position(
        self, plan: Plan, account: AccountState | None, daily_pnl: float = 0.0, weekly_pnl: float = 0.0
    ) -> float:
        """حجم بر اساس درصد ریسک: risk = equity × risk% / فاصله SL.

        volume_lots = risk_amount / (sl_distance × contract_size)
        """
        try:
            if account is None or account.equity <= 0:
                return 0.0

            # ریسک تطبیقی بر مبنای کیفیت و گرید ستاپ (Dynamic Sizing)
            base_risk = float(self._g.risk_per_trade_pct)
            if plan.grade == SetupGrade.A:
                eff_risk = base_risk           # ۲.۰٪ برای ستاپ‌های ممتاز گرید A
            elif plan.grade == SetupGrade.B:
                eff_risk = base_risk * 0.5     # ۱.۰٪ برای ستاپ‌های استاندارد روند گرید B
            else:
                eff_risk = base_risk * 0.25    # ۰.۵٪ برای سایر موارد

            # مقیاس‌پذیری دفاعی دراودان (DEFCON Drawdown Sizing)
            if account and account.balance > 0 and daily_pnl < 0:
                dd_pct = (abs(daily_pnl) / account.balance) * 100.0
                if dd_pct >= 3.5:
                    eff_risk *= 0.50  # DEFCON 2: کاهش ۵۰٪ ریسک در دراودان بالا
                    log.info("DEFCON 2 فعال شد: دراودان %.2f%% — ریسک به %.2f%% کاهش یافت", dd_pct, eff_risk)
                elif dd_pct >= 2.0:
                    eff_risk *= 0.75  # DEFCON 3: کاهش ۲۵٪ ریسک در دراودان ملایم
                    log.info("DEFCON 3 فعال شد: دراودان %.2f%% — ریسک به %.2f%% کاهش یافت", dd_pct, eff_risk)

            # قفل سود هفتگی و حفظ سرمایه (Weekly Profit Lock)
            # اگر سود هفته جاری به بالای ۸٪ اکوئیتی رسید، ریسک را برای حفظ سود انباشته نصف کن
            if account and account.balance > 0 and weekly_pnl >= account.balance * 0.08:
                eff_risk = min(eff_risk, base_risk * 0.50)
                log.info("قفل سود هفتگی فعال شد: سود هفته %.2f دلار — سقف ریسک به %.2f%% محدود شد", weekly_pnl, eff_risk)

            risk_pct = Decimal(str(eff_risk)) / Decimal("100")
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
