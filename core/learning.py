""" core/learning — موتور یادگیری تطبیقی و بهینه‌سازی پارامترها (Adaptive Learning Engine)

قوانین حاکم بر یادگیری هرمس (Backtest & Learning Discipline):
۱. هیچ اهرمی (Knob) بر اساس کمتر از ۲۰ ترید تغییر نمی‌کند (جلوگیری از Overfitting و نویز).
۲. در صورت افت پرفورمنس (Drawdown یا ۳ باخت متوالی)، گیت‌ها خودکار سفت‌تر می‌شوند (Tighten-Only):
   - ارتقای حداقل گرید ستاپ از B به A (صرفاً تایید ستاپ‌های بی‌نقص با تاییدیه کامل SMC)
   - افزایش حداقل نسبت ریسک به ریوارد (min_rr از 1.0 به 1.5)
۳. هیچ گیت امنیتی از کف تعیین‌شده در config.yaml نرم‌تر (Looser) نمی‌شود.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from core.db import Ledger
from core.entities import Trade

log = logging.getLogger(__name__)

MIN_TRADES_TO_ADAPT = 20
FLOOR_MIN_RR = 1.0
FLOOR_MIN_GRADE = "B"


@dataclass(frozen=True)
class PerformanceMetrics:
    total_trades: int
    wins: int
    losses: int
    win_rate: float            # 0.0 .. 100.0
    profit_factor: float
    total_pnl: float
    avg_r: float
    consecutive_losses: int


class AdaptiveLearner:
    """موتور یادگیری تطبیقی بر پایه ژورنال معاملات گذشته."""

    def __init__(
        self,
        min_trades: int = MIN_TRADES_TO_ADAPT,
        floor_rr: float = FLOOR_MIN_RR,
        floor_grade: str = FLOOR_MIN_GRADE,
    ):
        self.min_trades = min_trades
        self.floor_rr = floor_rr
        self.floor_grade = floor_grade

    def evaluate_performance(self, trades: list[Trade]) -> PerformanceMetrics:
        """محاسبه شاخص‌های آماری عملکرد معاملات."""
        if not trades:
            return PerformanceMetrics(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0)

        wins = [t for t in trades if t.is_win]
        losses = [t for t in trades if not t.is_win]

        total_profit = sum(t.pnl for t in wins)
        total_loss = abs(sum(t.pnl for t in losses))
        profit_factor = round(total_profit / total_loss, 2) if total_loss > 0 else (99.0 if total_profit > 0 else 1.0)

        total_pnl = sum(t.pnl for t in trades)
        win_rate = round((len(wins) / len(trades)) * 100.0, 1)

        r_multiples = [t.r_multiple for t in trades if t.r_multiple != 0.0]
        avg_r = round(sum(r_multiples) / len(r_multiples), 3) if r_multiples else 0.0

        # شمارش باخت‌های متوالی اخیر
        streak = 0
        for t in reversed(trades):
            if not t.is_win:
                streak += 1
            else:
                break

        return PerformanceMetrics(
            total_trades=len(trades),
            wins=len(wins),
            losses=len(losses),
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_pnl=round(total_pnl, 2),
            avg_r=avg_r,
            consecutive_losses=streak,
        )

    def adapt(self, ledger: Ledger) -> dict:
        """بررسی معاملات اخیر در دیتابیس و سفت‌تر کردن گیت‌ها در صورت نیاز."""
        trades = ledger.get_trades(limit=50)
        metrics = self.evaluate_performance(trades)

        if metrics.total_trades < self.min_trades:
            return {
                "adapted": False,
                "reason": f"تعداد تریدها ({metrics.total_trades}) به حد نصاب ({self.min_trades}) نرسیده است.",
                "metrics": metrics,
            }

        current_min_rr = float(ledger.get_param("min_rr", str(self.floor_rr)) or self.floor_rr)
        current_grade = ledger.get_param("min_grade", self.floor_grade) or self.floor_grade

        new_min_rr = current_min_rr
        new_grade = current_grade
        changes = []

        # سناریوی ۱: ۳ باخت متوالی اخیر یا وین‌ریت زیر ۳۵٪ -> سفت کردن گیت‌ها
        if metrics.consecutive_losses >= 3 or metrics.win_rate < 35.0:
            if current_min_rr < 1.5:
                new_min_rr = 1.5
                changes.append(f"min_rr: {current_min_rr} -> 1.5")
            if current_grade != "A":
                new_grade = "A"
                changes.append("min_grade: B -> A (فیلتر سخت‌گیرانه ستاپ‌های ممتاز)")

        # سناریوی ۲: عملکرد درخشان (وین‌ریت بالای ۵۵٪ و Profit Factor بالای ۱.۴) -> بازگشت به کف استاندارد
        elif metrics.win_rate >= 55.0 and metrics.profit_factor >= 1.4:
            if current_min_rr > self.floor_rr:
                new_min_rr = self.floor_rr
                changes.append(f"min_rr reset to floor: {self.floor_rr}")
            if current_grade != self.floor_grade:
                new_grade = self.floor_grade
                changes.append(f"min_grade reset to floor: {self.floor_grade}")

        if changes:
            ledger.set_param("min_rr", str(new_min_rr))
            ledger.set_param("min_grade", new_grade)
            log.info("🎯 یادگیری تطبیقی اعمال شد: %s", " | ".join(changes))
            return {
                "adapted": True,
                "changes": changes,
                "metrics": metrics,
                "min_rr": new_min_rr,
                "min_grade": new_grade,
            }

        return {
            "adapted": False,
            "reason": "عملکرد در بازه پایدار است؛ نیازی به تغییر پارامتر نیست.",
            "metrics": metrics,
            "min_rr": current_min_rr,
            "min_grade": current_grade,
        }
