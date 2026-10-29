""" core/db — دفتر کل SQLite

نقش: ثبت تصمیمات و نتایج (audit + بک‌تست).
هرگز منبع تصمیم نیست — حقیقت زنده از bridge می‌آید.

یک کلاس، یک فایل. CRUD ساده + snapshot حساب.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.entities import (
    AccountState,
    ExitReason,
    Order,
    OrderStatus,
    Plan,
    SetupGrade,
    Signal,
    Side,
    Trade,
    TradeStatus,
)

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "hermes.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    plan_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL NOT NULL,
    volume REAL NOT NULL,
    grade TEXT NOT NULL,
    source TEXT NOT NULL,
    timeframe TEXT NOT NULL DEFAULT 'M15',
    rr REAL DEFAULT 0,
    confidence REAL DEFAULT 0,
    reasoning TEXT DEFAULT '',
    created_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    ticket INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    volume REAL NOT NULL,
    price REAL NOT NULL,
    sl REAL NOT NULL,
    tp REAL NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    ticket INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    volume REAL NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    sl REAL NOT NULL,
    tp REAL NOT NULL,
    pnl REAL NOT NULL,
    exit_reason TEXT NOT NULL,
    opened_at REAL NOT NULL,
    closed_at REAL NOT NULL,
    grade TEXT NOT NULL DEFAULT 'C',
    source TEXT NOT NULL DEFAULT 'signal',
    r_multiple REAL DEFAULT 0,
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS signals (
    signal_id TEXT PRIMARY KEY,
    raw_text TEXT NOT NULL,
    symbol TEXT,
    side TEXT,
    entry REAL, sl REAL, tp REAL,
    rr REAL, confidence REAL,
    valid INTEGER NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS guard_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    decision TEXT NOT NULL,
    plan_id TEXT,
    side TEXT, symbol TEXT,
    reasons TEXT NOT NULL DEFAULT '[]',
    volume REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    balance REAL NOT NULL,
    equity REAL NOT NULL,
    floating REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS params (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    item_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    trigger_price REAL NOT NULL,
    sl REAL NOT NULL,
    tp REAL NOT NULL,
    added_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'waiting',
    reason TEXT NOT NULL DEFAULT ''
);
"""


class Ledger:
    """دفتر کل — فقط ثبت و خواندن. هیچ تصمیمی از اینجا ساخته نمی‌شود."""

    def __init__(self, path: Path = DEFAULT_DB_PATH):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(str(self._path))
        self._con.row_factory = sqlite3.Row
        self._con.executescript(SCHEMA)
        self._con.commit()

    # ── عمومی ──────────────────────────────────────────

    def close(self):
        self._con.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def _now(self) -> float:
        return datetime.now(timezone.utc).timestamp()

    # ── plans ─────────────────────────────────────────

    def save_plan(self, plan: Plan, status: str = "active") -> None:
        self._con.execute(
            """INSERT INTO plans (plan_id, symbol, side, entry_price, stop_loss,
               take_profit, volume, grade, source, timeframe, rr, confidence,
               reasoning, created_at, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(plan_id) DO UPDATE SET status=excluded.status""",
            (plan.plan_id, plan.symbol, plan.side.value, plan.entry_price,
             plan.stop_loss, plan.take_profit, plan.volume, plan.grade.value,
             plan.source, plan.timeframe, plan.rr, plan.confidence,
             plan.reasoning, plan.created_at or self._now(), status),
        )
        self._con.commit()

    def get_active_plan(self) -> Optional[Plan]:
        row = self._con.execute(
            "SELECT * FROM plans WHERE status='active' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return Plan(
            plan_id=row["plan_id"], symbol=row["symbol"], side=Side(row["side"]),
            entry_price=row["entry_price"], stop_loss=row["stop_loss"],
            take_profit=row["take_profit"], volume=row["volume"],
            grade=SetupGrade(row["grade"]), source=row["source"],
            timeframe=row["timeframe"], rr=row["rr"] or 0.0,
            confidence=row["confidence"] or 0.0,
            created_at=row["created_at"], reasoning=row["reasoning"] or "",
        )

    def get_plan(self, plan_id: str) -> Optional[Plan]:
        """بازیابی پلن ذخیره‌شده بر اساس plan_id."""
        if not plan_id:
            return None
        row = self._con.execute(
            "SELECT * FROM plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if row is None:
            return None
        return Plan(
            plan_id=row["plan_id"], symbol=row["symbol"], side=Side(row["side"]),
            entry_price=row["entry_price"], stop_loss=row["stop_loss"],
            take_profit=row["take_profit"], volume=row["volume"],
            grade=SetupGrade(row["grade"]), source=row["source"],
            timeframe=row["timeframe"], rr=row["rr"] or 0.0,
            confidence=row["confidence"] or 0.0,
            created_at=row["created_at"], reasoning=row["reasoning"] or "",
        )

    def get_plan_by_ticket(self, ticket: int) -> Optional[Plan]:
        """بازیابی پلن بر اساس شماره تیکت سفارش."""
        row = self._con.execute(
            "SELECT plan_id FROM orders WHERE ticket = ? ORDER BY created_at DESC LIMIT 1",
            (ticket,)
        ).fetchone()
        if row and row["plan_id"]:
            return self.get_plan(row["plan_id"])
        return None

    # ── orders ─────────────────────────────────────────

    def save_order(self, order: Order) -> None:
        self._con.execute(
            """INSERT INTO orders (order_id, plan_id, ticket, symbol, side,
               volume, price, sl, tp, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(order_id) DO NOTHING""",
            (order.order_id, order.plan_id, order.ticket, order.symbol,
             order.side.value, order.volume, order.price, order.sl, order.tp,
             order.status.value, order.created_at or self._now()),
        )
        self._con.commit()

    # ── trades ─────────────────────────────────────────

    def save_trade(self, trade: Trade) -> None:
        self._con.execute(
            """INSERT INTO trades (trade_id, plan_id, ticket, symbol, side,
               volume, entry_price, exit_price, sl, tp, pnl, exit_reason,
               closed_at, opened_at, grade, source, r_multiple, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(trade_id) DO NOTHING""",
            (trade.trade_id, trade.plan_id, trade.ticket, trade.symbol,
             trade.side.value, trade.volume, trade.entry_price,
             trade.exit_price, trade.sl, trade.tp, trade.pnl,
             trade.exit_reason.value, trade.closed_at, trade.opened_at,
             trade.grade.value, trade.source, trade.r_multiple, trade.notes),
        )
        self._con.commit()

    def get_today_trades(self) -> list[Trade]:
        """معاملات بسته‌شده امروز (UTC) — خوراک دروازه max_daily_trades."""
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0).timestamp()
        rows = self._con.execute(
            "SELECT * FROM trades WHERE closed_at >= ? ORDER BY closed_at DESC",
            (today_start,)).fetchall()
        return [self._row_to_trade(r) for r in rows]

    def get_trades(self, limit: int = 50) -> list[Trade]:
        """لیست آخرین معاملات بسته‌شده — خوراک موتور یادگیری."""
        rows = self._con.execute(
            "SELECT * FROM trades ORDER BY closed_at DESC LIMIT ?",
            (limit,)).fetchall()
        return [self._row_to_trade(r) for r in rows]

    def _row_to_trade(self, row: sqlite3.Row) -> Trade:
        return Trade(
            trade_id=row["trade_id"], plan_id=row["plan_id"],
            ticket=row["ticket"], symbol=row["symbol"],
            side=Side(row["side"]), volume=row["volume"],
            entry_price=row["entry_price"], exit_price=row["exit_price"],
            sl=row["sl"], tp=row["tp"], pnl=row["pnl"],
            exit_reason=ExitReason(row["exit_reason"]),
            opened_at=row["opened_at"], closed_at=row["closed_at"],
            grade=SetupGrade(row["grade"]), source=row["source"],
            r_multiple=row["r_multiple"] or 0.0, notes=row["notes"] or "",
        )

    # ── signals ────────────────────────────────────────

    def save_signal(self, sig: Signal, processed: bool = False) -> None:
        self._con.execute(
            """INSERT INTO signals (signal_id, raw_text, symbol, side, entry,
               sl, tp, rr, confidence, valid, timestamp, processed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(signal_id) DO NOTHING""",
            (sig.signal_id, sig.raw_text, sig.symbol, sig.side.value,
             sig.entry, sig.sl, sig.tp, sig.rr, sig.confidence,
             int(sig.is_valid), sig.timestamp,
             self._now() if processed else None),
        )
        self._con.commit()

    def signal_seen(self, signal_id: str) -> bool:
        row = self._con.execute(
            "SELECT 1 FROM signals WHERE signal_id = ?", (signal_id,)).fetchone()
        return row is not None

    # ── guard_log ───────────────────────────────────────

    def log_guard(self, decision: str, reasons: list[str], plan_id: str = "",
                  side: str = "", symbol: str = "", volume: float = 0.0) -> None:
        self._con.execute(
            """INSERT INTO guard_log (ts, decision, plan_id, side, symbol,
               reasons, volume) VALUES (?,?,?,?,?,?,?)""",
            (self._now(), decision, plan_id, side, symbol,
             json.dumps(reasons, ensure_ascii=False), volume),
        )
        self._con.commit()

    # ── equity snapshots ────────────────────────────────

    def snapshot_equity(self, acct: AccountState) -> None:
        self._con.execute(
            "INSERT INTO equity_snapshots (ts, balance, equity, floating) VALUES (?,?,?,?)",
            (self._now(), acct.balance, acct.equity, acct.floating_pnl),
        )
        self._con.commit()

    # ── params (یادگیری) ───────────────────────────────

    def get_param(self, key: str, default: str = "") -> str:
        row = self._con.execute(
            "SELECT value FROM params WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_param(self, key: str, value: str) -> None:
        self._con.execute(
            "INSERT INTO params (key, value, updated_at) VALUES (?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, self._now()))
        self._con.commit()

    # ── watchlist (سیگنال‌های در انتظار پولبک) ─────────────

    def add_to_watchlist(self, item: dict) -> None:
        """افزودن سیگنال مشروط به واچ‌لیست جهت انتظار برای پولبک یا رفع خبر."""
        self._con.execute(
            """INSERT INTO watchlist (item_id, signal_id, symbol, side, entry_price,
               trigger_price, sl, tp, added_at, expires_at, status, reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(item_id) DO UPDATE SET
               trigger_price=excluded.trigger_price, status=excluded.status, reason=excluded.reason""",
            (item["item_id"], item["signal_id"], item["symbol"], item["side"],
             float(item["entry_price"]), float(item["trigger_price"]),
             float(item["sl"]), float(item["tp"]),
             float(item["added_at"]), float(item["expires_at"]),
             item.get("status", "waiting"), str(item.get("reason", "")))
        )
        self._con.commit()

    def get_active_watchlist(self, symbol: str = "XAUUSD") -> list[dict]:
        """استعلام آیتم‌های فعال در انتظار پولبک."""
        rows = self._con.execute(
            "SELECT * FROM watchlist WHERE symbol = ? AND status = 'waiting' ORDER BY added_at ASC",
            (symbol,)).fetchall()
        return [dict(r) for r in rows]

    def update_watchlist_status(self, item_id: str, status: str) -> None:
        """به‌روزرسانی وضعیت آیتم واچ‌لیست (executed, expired, invalidated)."""
        self._con.execute(
            "UPDATE watchlist SET status = ? WHERE item_id = ?",
            (status, item_id))
        self._con.commit()

    def prune_expired_watchlist(self, now_ts: float) -> int:
        """منقضی کردن آیتم‌های کهنه‌تر از مهلت مقرر (معمولاً ۲ ساعت)."""
        cur = self._con.execute(
            "UPDATE watchlist SET status = 'expired' WHERE status = 'waiting' AND expires_at <= ?",
            (now_ts,))
        self._con.commit()
        return cur.rowcount
