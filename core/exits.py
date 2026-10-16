""" core/exits — منطق مدیریت پوزیشن (مشترک بین دیمن زنده و بک‌تستر)

پس از step 2: این فایل جایگزین _manage_position/_trail_sl در entry/hermes.py می‌شود.
دیمن زنده و بک‌تستر دقیقاً یک منطق خروج اجرا می‌کنند.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from core.entities import BrokerPosition, ExitReason
from core.params import PositionCfg

log = logging.getLogger(__name__)


class ExitManager:
    """مدیریت خروج پوزیشن — منطق مشترک دیمن زنده و بک‌تستر.

    این کلاس state‌ای ندارد. تصمیم می‌گیرد، اعمال را به caller می‌سپارد:
      - در دیمن زنده: on_modify → bridge.modify_position(ticket, new_sl)
      - در بک‌تستر:    on_modify → به‌روزرسانی SL در state شبیه‌ساز
    """

    def __init__(self, pos_cfg: PositionCfg, on_modify: Callable[[int, float], None] | None = None):
        self._cfg = pos_cfg
        self._on_modify = on_modify

    # ── API ─────────────────────────────────────────────

    def manage(self, pos: BrokerPosition, now_ts: float,
               atr: float = 0.0,
               atr_sl_mult: float = 1.5,
               atr_trail_mult: float = 3.0) -> Optional[tuple[ExitReason, float]]:
        """تصمیم مدیریت یک پوزیشن.

        پارامترهای ATR برای پلن‌های بدون TP (تحلیل خودکار):
          atr            ATR لحظه تصمیم
          atr_sl_mult    فاصله استاپ اولیه (در پلن استفاده شد)
          atr_trail_mult فاصله trailing

        بازگشت:
          (reason, exit_price) → بستن پوزیشن
          None                 → نگه‌داشتن
        """
        # ۱) خروج زمانی — قدیمی‌تر از max_hold_hours
        age_h = (now_ts - pos.open_time) / 3600.0
        if age_h >= self._cfg.max_hold_hours:
            return ExitReason.TIME_EXIT, pos.current_price

        rr = pos.rr_progress  # 0=استاپ، 1=TP

        # ۱‌ب) مسیر ATR برای پوزیشن‌های بدون TP (تحلیل خودکار)
        #     rr_progress با tp=0 همیشه 0 است → مسیرها جدا اجرا می‌شوند.
        if pos.tp <= 0 and atr > 0:
            trail_dist = atr * atr_trail_mult
            if pos.is_buy:
                new_sl = pos.current_price - trail_dist
                if new_sl > pos.sl:
                    self._modify(pos, new_sl)
            else:
                new_sl = pos.current_price + trail_dist
                if pos.sl == 0 or new_sl < pos.sl:
                    self._modify(pos, new_sl)
            return None  # مدیریت کامل شد — خروج فقط با SL زنده

        # ۲) breakeven — جابجایی SL به نقطه ورود
        if rr >= self._cfg.breakeven_rr and pos.sl != pos.open_price:
            new_sl = pos.open_price
            if pos.is_buy and new_sl > pos.sl:
                self._modify(pos, new_sl)
            elif not pos.is_buy and (pos.sl == 0 or new_sl < pos.sl):
                # update via caller
                self._modify(pos, new_sl)

        # ۳) trailing stop — SL را دنبال قیمت می‌کند
        if rr >= self._cfg.trailing_start_rr and pos.sl > 0:
            new_sl = self._trail_sl(pos)
            if new_sl is None:
                log.debug("trailing: nothing to do")
            else:
                self._modify(pos, new_sl)

        return None

    # ── private ─────────────────────────────────────────

    def _modify(self, pos: BrokerPosition, new_sl: float) -> None:
        """اعمال SL جدید — از callback استفاده می‌کند (bridge یا state)."""
        if self._on_modify is not None:
            self._on_modify(pos.ticket, new_sl)

    @staticmethod
    def _trail_sl(pos: BrokerPosition) -> float | None:
        """محاسبه SL جدید برای trailing — فقط در جهت سود.

        حالت ATR (پلن‌های تحلیلی بدون TP): فاصله ثابت ATR-مبنای
        `atr_mult` × ATR لحظه ورود (از پارامتر پلن، در dataclass ذخیره
        نمی‌شود — از رویداد ترید خوانده می‌شود).
        حالت TP: فاصله نصف فاصله فعلی تا TP.
        """
        # حالت ATR-trail: پلن بدون TP (تحلیل خودکار) — فاصله ثابت
        if pos.tp <= 0:
            atr_dist = getattr(pos, "trail_atr_dist", None)
            if atr_dist and atr_dist > 0:
                if pos.is_buy:
                    new_sl = pos.current_price - atr_dist
                    if new_sl > pos.sl:
                        return new_sl
                else:
                    new_sl = pos.current_price + atr_dist
                    if pos.sl == 0 or new_sl < pos.sl:
                        return new_sl
            return None
        # حالت TP-based: نصف فاصله تا TP
        dist = abs(pos.tp - pos.current_price) * 0.5
        if dist <= 0:
            return None
        if pos.is_buy:
            new_sl = pos.current_price - dist
            if new_sl > pos.sl:
                return new_sl
        else:
            new_sl = pos.current_price + dist
            if pos.sl == 0 or new_sl < pos.sl:
                return new_sl
        return None
