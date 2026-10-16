""" core/entities — مدل داده هرمس

Entity های قراردادی. immutable (frozen) مگه جایی که استفاده هست.
هیچ وابستگی به MT5 / تلگرام / SQLite در این فایل نیست.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ══════════════════════════════════════════════════════════════════
# Enum ها
# ══════════════════════════════════════════════════════════════════

class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    REJECTED = "REJECTED"


class TradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ExitReason(str, Enum):
    """چرا یک معامله بسته شد."""
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    BREAKEVEN = "BREAKEVEN"
    TIME_EXIT = "TIME_EXIT"
    MANUAL = "MANUAL"
    EMERGENCY = "EMERGENCY"
    SIGNAL_EXIT = "SIGNAL_EXIT"


class SetupGrade(str, Enum):
    """گرید کیفیت ستاپ — از V1 (execution_guard)."""
    A = "A"
    B = "B"
    C = "C"
    D = "D"

    @classmethod
    def rank(cls, g: "SetupGrade") -> int:
        return {"A": 4, "B": 3, "C": 2, "D": 1}[g.value]


# ══════════════════════════════════════════════════════════════════════════
# Market════════════════════════════════════════════
# Market
# ══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Candle:
    """یک کندل OHLCV — immutable."""
    time: int            # epoch seconds (UTC)
    open: float
    high: float
    low: float
    close: float
    volume: int

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range_(self) -> float:
        return self.high - self.low


@dataclass(frozen=True)
class Tick:
    """قیمت لحظه‌ای."""
    symbol: str
    bid: float
    ask: float
    time: int

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass(frozen=True)
class AccountState:
    """وضعیت حساب — زنده از خود بروکر."""
    balance: float
    equity: float
    margin: float
    margin_free: float
    currency: str = "USD"
    login: int = 0

    @property
    def floating_pnl(self) -> float:
        return self.equity - self.balance


@dataclass(frozen=True)
class BrokerPosition:
    """پوزیشن باز — زنده از خود بروکر (حقیقت نهایی)."""
    ticket: int
    symbol: str
    side: Side
    volume: float
    open_price: float
    current_price: float
    sl: float
    tp: float
    profit: float
    swap: float
    open_time: int
    comment: str = ""

    @property
    def is_buy(self) -> bool:
        return self.side == Side.BUY

    @property
    def rr_progress(self) -> float:
        """پیشرفت نسبت R-risk: چقدر به TP نزدیک شدیم.

        ورودی: 0.0 → استاپ. 1.0 → TP.
        اگر SL یا TP تنظیم نشده → 0.0
        """
        if self.sl <= 0 or self.tp <= 0:
            return 0.0
        if self.is_buy:
            span = self.tp - self.sl
            return 0.0 if span <= 0 else (self.current_price - self.sl) / span
        span = self.sl - self.tp
        return 0.0 if span <= 0 else (self.sl - self.current_price) / span


# ═�═══════════════════════════════════════════════════════════════
# Signal (تلگرام)
# ══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Signal:
    """سیگنال خام پارس‌شده از کانال تلگرام."""
    signal_id: str
    raw_text: str
    symbol: str
    side: Side
    entry: float
    sl: float
    tp: float
    rr: float
    confidence: float
    timestamp: str            # ISO utc
    parsed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def is_valid(self) -> bool:
        """اعتبارسنجی اولیه — fail-closed."""
        return all([
            self.symbol == "XAUUSD",
            self.entry > 0,
            self.sl > 0,
            self.tp > 0,
            self.rr >= 0.5,
            (self.side == Side.BUY and self.tp > self.entry > self.sl) or
            (self.side == Side.SELL and self.tp < self.entry < self.sl),
        ])


# ══════════════════════════════════════════════════════════════════
# Plan / Order / Trade
# ═══════════════════════════════════════ تصمیم از مغز ═════════════
@dataclass
class Plan:
    """برنامه ورود — خروجی مغز قبل از دروازه."""
    plan_id: str
    symbol: str
    side: Side
    entry_price: float
    stop_loss: float
    take_profit: float
    volume: float              # حجم محاسبه‌شده توسط دروازه (risk-based)
    grade: SetupGrade
    source: str                # "signal" | "analysis"
    timeframe: str = "M15"
    rr: float = 0.0
    confidence: float = 0.0
    created_at: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    reasoning: str = ""

    @property
    def risk_amount(self) -> float:
        """مبلغ ریسک بر اساس حجم و فاصله SL."""
        return self.volume * abs(self.entry_price - self.stop_loss)

    @property
    def reward_amount(self) -> float:
        return self.volume * abs(self.take_profit - self.entry_price)


@dataclass
class Order:
    """سفارش ثبت‌شده در بروکر."""
    order_id: str              # client-side id (idempotency key)
    plan_id: str
    ticket: int                # broker ticket
    symbol: str
    side: Side
    volume: float
    price: float               # fill price
    sl: float
    tp: float
    status: OrderStatus
    created_at: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())


@dataclass
class Trade:
    """معامله — چرخه کامل ورود تا خروج (خوراک بک‌تست و یادگیری)."""
    trade_id: str
    plan_id: str
    ticket: int
    symbol: str
    side: Side
    volume: float
    entry_price: float
    exit_price: float
    sl: float
    tp: float
    pnl: float
    exit_reason: ExitReason
    opened_at: float
    closed_at: float
    grade: SetupGrade = SetupGrade.C
    source: str = "signal"
    r_multiple: float = 0.0   # چند برابر R سود/ضرر
    notes: str = ""

    @property
    def is_win(self) -> bool:
        return self.pnl > 0


# ══════════════════════════════════════════════════════════════════
# Guard
# ══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class GuardDecision:
    """تصمیم دروازه — مجاز / ممنوع + دلایل."""
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    volume: float = 0.0       # حجم نهایی (risk-based)
    grade: SetupGrade = SetupGrade.C

    @property
    def verdict(self) -> str:
        return "ALLOW" if self.allowed else "DENY"


def to_json(obj) -> str:
    """Entity → JSON string (برای sidecar یا گزارش)."""
    d = asdict(obj)
    # Enum → value
    def _clean(v):
        if isinstance(v, Enum):
            return v.value
        return v
    return json.dumps({k: _clean(x) for k, x in d.items()}, ensure_ascii=False)
