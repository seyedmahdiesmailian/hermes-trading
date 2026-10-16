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

    def manage(self, pos: BrokerPosition, now_ts: float) -> Optional[tuple[ExitReason, float]]:
        """تصمیم مدیریت یک پوزیشن.

        بازگشت:
          (reason, exit_price) → بستن پوزیشن
          None                 → نگه‌داشتن
        """
        # ۱) خروج زمانی — قدیمی‌تر از max_hold_hours
        age_h = (now_ts - pos.open_time) / 3600.0
        if age_h >= self._cfg.max_hold_hours:
            return ExitReason.TIME_EXIT, pos.current_price

        rr = pos.rr_progress  # 0=استاپ، 1=TP

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

        فاصله: نیمی از فاصله فعلی تا TP.
        """
        if pos.tp <= 0:
            return None
        dist = abs(pos.tp -  pos.current_price) * 0.5
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
