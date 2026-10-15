"""
SQLite-backed implementations of the domain repositories.

This makes data/hermes.db the single source of truth for plans, signals,
trades and safety events. The JSON files under data/ remain only as a
handoff format between processes, never as the authoritative store.

Design rules:
  * Every write is atomic (single transaction, commit immediately).
  * Idempotent: inserting the same plan_id/signal_id/ticket twice is a no-op.
  * Timestamps are stored UTC ISO-8601.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "hermes.db"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class SqliteRepositoryBase:
    """Common connection handling for the SQLite repositories."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(sql, params).fetchall()

    def _query_one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        rows = self._query(sql, params)
        return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

class SqlitePlanRepository(SqliteRepositoryBase):
    """Single source of truth for trading plans."""

    def save_plan(self, plan: dict) -> str:
        """Insert or update a plan. Idempotent on plan_id."""
        plan_id = str(plan.get("plan_id") or plan.get("id") or "")
        if not plan_id:
            plan_id = f"plan-{_utcnow()}"
        now = _utcnow()

        analysis = plan.get("analysis") or {}
        analysis_json = json.dumps(analysis) if not isinstance(analysis, str) else analysis

        sql = """
        INSERT INTO plans (plan_id, symbol, timeframe, bias, session, value_low, value_high,
                           long_entry_low, long_entry_high, short_entry_low, short_entry_high,
                           atr, grade, setup_score, created_at, expires_at, status, analysis_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(plan_id) DO UPDATE SET
            status=excluded.status, atr=excluded.atr, grade=excluded.grade,
            setup_score=excluded.setup_score, analysis_json=excluded.analysis_json
        """
        self._execute(sql, (
            plan_id,
            str(plan.get("symbol", "XAUUSD")),
            str(plan.get("timeframe", "M15")),
            str(plan.get("bias", "neutral")),
            str(plan.get("session", "")),
            float(plan.get("value_low") or 0),
            float(plan.get("value_high") or 0),
            plan.get("long_entry_low"),
            plan.get("long_entry_high"),
            plan.get("short_entry_low"),
            plan.get("short_entry_high"),
            float(plan.get("atr") or 0),
            str(plan.get("grade") or ""),
            float(plan.get("setup_score") or 0),
            str(plan.get("created_at") or now),
            str(plan.get("expires_at") or ""),
            str(plan.get("status", "active")),
            analysis_json,
        ))
        return plan_id

    def get_current_plan(self) -> Optional[dict]:
        row = self._query_one(
            "SELECT * FROM plans WHERE status='active' ORDER BY created_at DESC LIMIT 1"
        )
        return dict(row) if row else None

    def get_plan(self, plan_id: str) -> Optional[dict]:
        row = self._query_one("SELECT * FROM plans WHERE plan_id=?", (plan_id,))
        return dict(row) if row else None

    def update_plan_status(self, plan_id: str, status: str) -> None:
        self._execute("UPDATE plans SET status=? WHERE plan_id=?", (status, plan_id))

    def list_plans(self, limit: int = 20) -> list[dict]:
        rows = self._query("SELECT * FROM plans ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

class SqliteSignalRepository(SqliteRepositoryBase):
    """Single source of truth for parsed telegram signals."""

    def save_signal(self, signal: dict) -> Optional[str]:
        """Insert a signal. Idempotent on signal_id."""
        signal_id = str(signal.get("signal_id") or "")
        if not signal_id:
            return None

        sql = """
        INSERT OR IGNORE INTO signals
            (signal_id, symbol, direction, entry_price, stop_loss, take_profit,
             source, source_id, raw_message, confidence_score, quality, status,
             processed_at, decision_reasoning, received_at, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """
        self._execute(sql, (
            signal_id,
            str(signal.get("symbol", "")),
            str(signal.get("direction", "")),
            signal.get("entry_price"),
            signal.get("stop_loss"),
            signal.get("take_profit"),
            str(signal.get("source", "")),
            str(signal.get("source_id", "")),
            str(signal.get("raw_message", "")),
            signal.get("confidence_score"),
            str(signal.get("quality", "")),
            str(signal.get("status", "pending")),
            signal.get("processed_at"),
            signal.get("decision_reasoning"),
            str(signal.get("received_at") or _utcnow()),
            _utcnow(),
        ))
        return signal_id

    def update_signal_status(self, signal_id: str, status: str, reasoning: str = "") -> None:
        self._execute(
            "UPDATE signals SET status=?, decision_reasoning=?, processed_at=? WHERE signal_id=?",
            (status, reasoning, _utcnow(), signal_id),
        )

    def get_pending_signals(self) -> list[dict]:
        rows = self._query("SELECT * FROM signals WHERE status='pending' ORDER BY received_at ASC")
        return [dict(r) for r in rows]

    def get_signal(self, signal_id: str) -> Optional[dict]:
        row = self._query_one("SELECT * FROM signals WHERE signal_id=?", (signal_id,))
        return dict(row) if row else None

    def list_signals(self, limit: int = 50) -> list[dict]:
        rows = self._query("SELECT * FROM signals ORDER BY received_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

class SqliteTradeRepository(SqliteRepositoryBase):
    """Single source of truth for executed trades and the journal."""

    def save_trade(self, trade: dict) -> Optional[int]:
        """Insert a trade keyed by broker ticket. Idempotent on ticket."""
        ticket = trade.get("ticket")
        if ticket is None:
            return None

        sql = """
        INSERT OR IGNORE INTO trades
            (ticket, position_id, symbol, side, volume, entry_price, stop_loss, take_profit,
             exit_price, profit, commission, swap, net_pnl, source, source_ref,
             entry_time, exit_time, duration_seconds, status, exit_reason, comment,
             created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """
        now = _utcnow()
        self._execute(sql, (
            ticket,
            trade.get("position_id"),
            str(trade.get("symbol", "XAUUSD")),
            str(trade.get("side", "")),
            trade.get("volume"),
            trade.get("entry_price"),
            trade.get("stop_loss"),
            trade.get("take_profit"),
            trade.get("exit_price"),
            trade.get("profit"),
            trade.get("commission"),
            trade.get("swap"),
            trade.get("net_pnl"),
            str(trade.get("source", "")),
            str(trade.get("source_ref", "")),
            str(trade.get("entry_time") or now),
            trade.get("exit_time"),
            trade.get("duration_seconds"),
            str(trade.get("status", "open")),
            trade.get("exit_reason"),
            str(trade.get("comment", "")),
            now,
            now,
        ))
        return ticket

    def get_open_trades(self) -> list[dict]:
        rows = self._query("SELECT * FROM trades WHERE status='open' ORDER BY entry_time ASC")
        return [dict(r) for r in rows]

    def close_trade(self, ticket: int, exit_price: float, net_pnl: float,
                    exit_reason: str = "") -> None:
        now = _utcnow()
        self._execute(
            """UPDATE trades SET status='closed', exit_price=?, net_pnl=?,
               exit_reason=?, exit_time=?, updated_at=? WHERE ticket=?""",
            (exit_price, net_pnl, exit_reason, now, now, ticket),
        )

    def get_today_trades(self) -> list[dict]:
        rows = self._query(
            "SELECT * FROM trades WHERE date(entry_time)=date('now') ORDER BY entry_time ASC"
        )
        return [dict(r) for r in rows]

    def list_trades(self, limit: int = 50) -> list[dict]:
        rows = self._query("SELECT * FROM trades ORDER BY entry_time DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Safety events (audit trail for every gate decision)
# ---------------------------------------------------------------------------

class SqliteSafetyEventRepository(SqliteRepositoryBase):
    """Append-only audit trail for guard verdicts and safety events."""

    def record_event(self, event_type: str, severity: str, message: str,
                     data: Optional[dict] = None) -> int:
        sql = """
        INSERT INTO safety_events (event_type, severity, message, data_json, created_at)
        VALUES (?,?,?,?,?)
        """
        cur = self._execute(sql, (event_type, severity, message,
                                  json.dumps(data or {}), _utcnow()))
        return int(cur.lastrowid or 0)

    def record_guard_verdict(self, verdict: dict) -> int:
        """Persist an ExecutionGuard verdict as a safety event."""
        allowed = bool(verdict.get("allowed"))
        return self.record_event(
            event_type="guard_verdict",
            severity="INFO" if allowed else "WARN",
            message=str(verdict.get("reason", "")),
            data=verdict,
        )

    def list_events(self, limit: int = 50) -> list[dict]:
        rows = self._query("SELECT * FROM safety_events ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]
