""" core/exits — سیستم پیشرفته و هوشمند مدیریت پوزیشن و خروج (Dynamic Position Management)

منطق یکپارچه خروج مشترک بین دیمن زنده و بک‌تستر:
۱. خروج زمانی (Time Exit): بستن پوزیشن‌های راکد پس از ۲۴ ساعت
۲. سیو سود پله‌ای (Partial Take-Profit): بستن ۵۰٪ حجم در تارگت اولیه (مثلاً ۱.۵R یا ۲R)
۳. نقطه ورود محافظت‌شده (Breakeven + Buffer): جابجایی استاپ به ورود + بافر اسپرد و کمیسیون (+0.15 پیپ)
۴. ترلینگ استاپ چندمرحله‌ای (Multi-Stage ATR Trailing):
   - مرحله ۱ (۰ تا ۱.۵R): ترلینگ ملایم (۲.۵ × ATR) جهت تنفس مارکت در پولبک‌ها
   - مرحله ۲ (۱.۵R تا ۳.۰R): قفل سود بالای ورود + ترلینگ استاندارد (۲.۰ × ATR)
   - مرحله ۳ (بالای ۳.۰R): ترلینگ فشرده (۱.۵ × ATR) جهت صید حداکثر رالی‌های پرقدرت طلا
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional, Set

from core.entities import BrokerPosition, ExitReason
from core.params import PositionCfg

log = logging.getLogger(__name__)

# بافر اسپرد و کمیسیون برای خروج در نقطه سر‌به‌سر (دلار بر اونس)
BREAKEVEN_BUFFER_POINTS = 0.15


class ExitManager:
    """مدیریت هوشمند و چندمرحله‌ای پوزیشن‌های باز."""

    def __init__(
        self,
        pos_cfg: PositionCfg,
        on_modify: Optional[Callable[..., None]] = None,
        on_partial: Optional[Callable[..., None]] = None,
    ):
        self._cfg = pos_cfg
        self._on_modify = on_modify
        self._on_partial = on_partial
        # ثبت تیکت‌هایی که بستن پله‌ای روی آنها انجام شده
        self._partial_executed: Set[int] = set()
        # ثبت استاپ‌لاس اولیه برای هر تیکت جهت محاسبه دقیق R-Multiple بعد از بریک‌اون
        self._initial_sl: dict[int, float] = {}

    def register_initial_sl(self, ticket: int, sl: float) -> None:
        """ثبت استاپ‌لاس اولیه برای یک تیکت جهت استفاده در محاسبات R-Multiple."""
        if sl > 0 and ticket not in self._initial_sl:
            self._initial_sl[ticket] = float(sl)

    def cleanup_ticket(self, ticket: int) -> None:
        """پاکسازی وضعیت ذخیره‌شده تیکت پس از بسته شدن کامل."""
        self._initial_sl.pop(ticket, None)
        self._partial_executed.discard(ticket)

    # ── API مدیریت پوزیشن ─────────────────────────────────

    def manage(
        self,
        pos: BrokerPosition,
        now_ts: Optional[float] = None,
        atr: float = 0.0,
        atr_sl_mult: float = 1.5,
        atr_trail_mult: float = 2.5,
    ) -> Optional[tuple[ExitReason, float]]:
        """ارزیابی گام‌به‌گام پوزیشن باز جهت بستن کامل، بستن پله‌ای یا تعدیل استاپ.

        خروجی:
          (ExitReason, exit_price) -> بستن کامل پوزیشن
          None -> پوزیشن حفظ یا اصلاح شد
        """
        if now_ts is None:
            now_ts = time.time()

        # ۱) خروج زمانی (Time-Based Exit)
        if pos.open_time > 0:
            age_hours = (now_ts - pos.open_time) / 3600.0
            if age_hours >= self._cfg.max_hold_hours:
                log.info("time exit triggered: ticket=%d age=%.1fh", pos.ticket, age_hours)
                return ExitReason.TIME_EXIT, pos.current_price

        # ثبت استاپ‌لاس اولیه برای هر تیکت
        if pos.ticket not in self._initial_sl:
            if pos.initial_sl > 0:
                self._initial_sl[pos.ticket] = pos.initial_sl
            elif (pos.is_buy and 0 < pos.sl < pos.open_price) or (not pos.is_buy and pos.sl > pos.open_price):
                self._initial_sl[pos.ticket] = pos.sl

        # محاسبه میزان سود/زیان فعلی بر مبنای ضریب ریسک اولیه (R-Multiple)
        init_sl = self._initial_sl.get(pos.ticket, pos.initial_sl if pos.initial_sl > 0 else pos.sl)
        if init_sl > 0:
            if pos.is_buy:
                risk = pos.open_price - init_sl
                r_mult = round((pos.current_price - pos.open_price) / risk, 3) if risk > 0 else pos.r_multiple
            else:
                risk = init_sl - pos.open_price
                r_mult = round((pos.open_price - pos.current_price) / risk, 3) if risk > 0 else pos.r_multiple
        else:
            r_mult = pos.r_multiple

        # اگر پلن بدون TP باشد (تحلیل خودکار با ترلینگ استاپ)
        if pos.tp <= 0 and atr > 0:
            sl_dist = atr * atr_sl_mult
            if sl_dist > 0:
                direction = 1.0 if pos.is_buy else -1.0
                r_achieved = (direction * (pos.current_price - pos.open_price)) / sl_dist
            else:
                r_achieved = 0.0

            # ۱.الف) بستن پله‌ای در پلن‌های بدون TP
            if self._cfg.partial_enabled and r_achieved >= self._cfg.partial_tp_rr:
                self._trigger_partial_if_needed(pos)

            # ۱.ب) ترلینگ چندمرحله‌ای بر مبنای ATR
            self._manage_dynamic_atr_trail(pos, r_achieved, atr)
            return None

        # ── پلن‌های دارای TP و SL (سیگنال کانال / واچ‌لیست) ──
        # ۲) بستن پله‌ای (Partial Take-Profit) بر مبنای R-Multiple واقعی
        if self._cfg.partial_enabled and r_mult >= self._cfg.partial_tp_rr:
            self._trigger_partial_if_needed(pos)

        # ۳ و ۴) مدیریت استاپ: ترلینگ استاپ یا انتقال به نقطه ورود (Breakeven)
        if pos.tp > 0 and pos.sl > 0 and r_mult >= self._cfg.trailing_start_rr:
            new_sl = self._trail_sl_with_tp(pos)
            if new_sl is not None:
                self._modify(pos, new_sl, reason="trailing")
            else:
                self._apply_breakeven_with_buffer(pos)
        elif r_mult >= self._cfg.breakeven_rr:
            self._apply_breakeven_with_buffer(pos)

        return None

    # ── ترلینگ چندمرحله‌ای ATR (Multi-Stage Trailing) ───────

    def _manage_dynamic_atr_trail(self, pos: BrokerPosition, r_achieved: float, atr: float) -> None:
        """ترلینگ داینامیک و پلکانی در رالی‌های بزرگ طلا برای پوزیشن‌های بدون TP."""
        be_rr = self._cfg.breakeven_rr
        trail_rr = self._cfg.trailing_start_rr

        if r_achieved < be_rr:
            return  # هنوز در مرحله ابتدایی شکل‌گیری روند هستیم

        # مرحله اول سود (بین breakeven_rr و trailing_start_rr): صرفاً انتقال به نقطه ورود امن
        if r_achieved < trail_rr:
            self._apply_breakeven_with_buffer(pos)
            return

        # مرحله دوم و سوم سود (رسیدن به حد ترلینگ): ترلینگ با تضمین راچت بالای نقطه ورود
        if r_achieved < 3.0:
            trail_dist = atr * 2.0  # ترلینگ استاندارد
        else:
            trail_dist = atr * 1.5  # ترلینگ فشرده برای صید سقف/کف

        buffer = BREAKEVEN_BUFFER_POINTS
        if pos.is_buy:
            new_sl = round(pos.current_price - trail_dist, 2)
            # تضمین راچت: استاپ ترلینگ هرگز نباید عقب‌تر از Breakeven+buffer برود
            target_be = round(pos.open_price + buffer, 2)
            if new_sl < target_be and target_be < pos.current_price:
                new_sl = target_be
            if new_sl > pos.sl and new_sl < pos.current_price:
                self._modify(pos, new_sl, reason="trailing")
        else:
            new_sl = round(pos.current_price + trail_dist, 2)
            # تضمین راچت: استاپ ترلینگ هرگز نباید عقب‌تر از Breakeven-buffer برود
            target_be = round(pos.open_price - buffer, 2)
            if new_sl > target_be and target_be > pos.current_price:
                new_sl = target_be
            if (pos.sl == 0 or new_sl < pos.sl) and new_sl > pos.current_price:
                self._modify(pos, new_sl, reason="trailing")

    # ── جابجایی استاپ به نقطه ورود + بافر ──────────────────

    def _apply_breakeven_with_buffer(self, pos: BrokerPosition) -> None:
        """انتقال استاپ به نقطه ورود به علاوه بافر پوشش کمیسیون."""
        buffer = BREAKEVEN_BUFFER_POINTS
        if pos.is_buy:
            target_be = round(pos.open_price + buffer, 2)
            # استاپ فقط به سمت سود می‌تواند حرکت کند و نباید از قیمت جاری بالاتر برود
            if target_be > pos.sl and target_be < pos.current_price:
                self._modify(pos, target_be, reason="breakeven")
        else:
            target_be = round(pos.open_price - buffer, 2)
            if (pos.sl == 0 or target_be < pos.sl) and target_be > pos.current_price:
                self._modify(pos, target_be, reason="breakeven")

    # ── بستن پله‌ای (Partial Close Execution) ─────────────

    def _trigger_partial_if_needed(self, pos: BrokerPosition) -> None:
        """اجرای سیو سود پله‌ای دقیقا یک‌بار برای هر پوزیشن."""
        if pos.ticket in self._partial_executed:
            return

        if self._on_partial is not None:
            log.info("partial close triggered for ticket=%d (50%% volume)", pos.ticket)
            self._on_partial(pos.ticket, 50.0)
            self._partial_executed.add(pos.ticket)

    # ── متدهای کمکی ──────────────────────────────────────

    def _modify(self, pos: BrokerPosition, new_sl: float, reason: str = "modify") -> None:
        """اعمال SL جدید با استفاده از کال‌بک ثبت‌شده."""
        rounded_sl = round(new_sl, 2)
        if round(pos.sl, 2) == rounded_sl:
            return  # عدم تغییر — جلوگیری از درخواست تکراری به بروکر
        if self._on_modify is not None:
            try:
                self._on_modify(pos.ticket, rounded_sl, pos.tp, reason=reason)
            except TypeError:
                try:
                    self._on_modify(pos.ticket, rounded_sl, pos.tp)
                except TypeError:
                    self._on_modify(pos.ticket, rounded_sl)

    @staticmethod
    def _trail_sl_with_tp(pos: BrokerPosition) -> float | None:
        """محاسبه ترلینگ استاپ برای پلن‌های تارگت‌دار."""
        dist = abs(pos.tp - pos.current_price) * 0.5
        if dist <= 0:
            return None

        buffer = BREAKEVEN_BUFFER_POINTS
        if pos.is_buy:
            new_sl = pos.current_price - dist
            # تضمین اینکه استاپ ترلینگ هرگز عقب‌تر از Breakeven+buffer نرود
            target_be = pos.open_price + buffer
            if new_sl < target_be and target_be < pos.current_price:
                new_sl = target_be
            if new_sl > pos.sl and new_sl < pos.current_price:
                return round(new_sl, 2)
        else:
            new_sl = pos.current_price + dist
            target_be = pos.open_price - buffer
            if new_sl > target_be and target_be > pos.current_price:
                new_sl = target_be
            if (pos.sl == 0 or new_sl < pos.sl) and new_sl > pos.current_price:
                return round(new_sl, 2)

        return None
