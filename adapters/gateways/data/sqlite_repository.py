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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "hermes.db"


# ---------------------------------------------------------------------------
# Entity-based repositories (Phase 1.4)
# ---------------------------------------------------------------------------
# Implement the three domain interfaces using the ENTITIES from
# brain/domain/entities — no dicts leak across the boundary.
#
# Fields with no dedicated column in schema.sql are stored losslessly in the
# table's JSON sidecar blob (see _PACK_KEY_*). Enums are TEXT (.value);
# datetimes are unix epoch INTEGER; None <-> NULL.


def _dt_to_ts(value) -> Optional[int]:
    """datetime -> unix epoch seconds (None/0 stays None)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) or None
    return int(value.timestamp()) or None


def _ts_to_dt(value) -> Optional[datetime]:
    """epoch seconds -> naive datetime (None/0 -> None)."""
    if value is None or value == 0:
        return None
    return datetime.fromtimestamp(int(value))


def _enum_text(value) -> Optional[str]:
    return None if value is None else getattr(value, "value", str(value))


def _enum_from(text, enum_cls):
    if text is None:
        return None
    try:
        return enum_cls(text)
    except ValueError:
        raise ValueError(f"Invalid {enum_cls.__name__} in DB: {text!r}") from None


def _load_json(raw) -> dict:
    if not raw:
        return {}
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {}
    except (ValueError, TypeError):
        return {}


def _f(value) -> Optional[float]:
    return None if value is None else float(value)


_PACK_PLAN = "plan_payload"
_PACK_SIGNAL = "signal_payload"
_PACK_ACCOUNT = "account_payload"
_PACK_TRADE = "trade_payload"


def _add_column(conn, table: str, column: str, decl: str) -> None:
    """ALTER TABLE ADD COLUMN unless the column already exists."""
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {decl}')
        conn.commit()


def ensure_entity_schema(conn) -> None:
    """Create the tables used by the entity repos and add JSON sidecars.

    Idempotent — safe to call on any database, old or new.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id TEXT UNIQUE NOT NULL,
            symbol TEXT NOT NULL,
            grade TEXT,
            created_at INTEGER NOT NULL,
            status TEXT DEFAULT 'active',
            bias TEXT,
            analysis_json TEXT
        );
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT UNIQUE NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            take_profit REAL NOT NULL,
            source TEXT NOT NULL,
            source_id TEXT,
            raw_message TEXT,
            confidence_score REAL,
            quality TEXT,
            status TEXT DEFAULT 'pending',
            processed_at INTEGER,
            decision_reasoning TEXT,
            received_at INTEGER NOT NULL,
            created_at INTEGER DEFAULT (strftime('%s','now'))
        );
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket INTEGER UNIQUE NOT NULL,
            position_id INTEGER,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            volume REAL NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL,
            take_profit REAL,
            exit_price REAL,
            profit REAL,
            net_pnl REAL,
            source_ref TEXT,
            entry_time INTEGER NOT NULL,
            exit_time INTEGER,
            status TEXT DEFAULT 'open',
            exit_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,
            symbol TEXT NOT NULL,
            type TEXT NOT NULL,
            volume REAL NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL,
            take_profit REAL,
            comment TEXT,
            created_at INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        );
        CREATE TABLE IF NOT EXISTS account_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            balance REAL NOT NULL,
            equity REAL NOT NULL,
            margin REAL,
            margin_free REAL,
            open_positions INTEGER DEFAULT 0,
            open_positions_volume REAL,
            daily_pnl REAL,
            daily_trades INTEGER,
            daily_wins INTEGER,
            daily_losses INTEGER,
            captured_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS system_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at INTEGER DEFAULT (strftime('%s','now'))
        );
        """
    )
    # NOT NULL columns in schema.sql that the entity layer must also supply
    _add_column(conn, "plans", "timeframe", "TEXT NOT NULL DEFAULT 'M15'")
    _add_column(conn, "plans", "expires_at", "INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "plans", _PACK_PLAN, "TEXT")
    _add_column(conn, "signals", _PACK_SIGNAL, "TEXT")
    _add_column(conn, "trades", _PACK_TRADE, "TEXT")
    _add_column(conn, "account_snapshots", _PACK_ACCOUNT, "TEXT")


class _EntityBase:
    """Connection + schema bootstrap shared by the entity repositories."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        from brain.domain.entities.plan import PlanStage  # local import: avoid cycle

        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        ensure_entity_schema(self._conn)

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()


# --- imports for entities (local to avoid import cycles at module load) ----
from brain.domain.entities.account import AccountState  # noqa: E402
from brain.domain.entities.plan import (  # noqa: E402
    PlanStage,
    SetupGrade,
    TradingPlan,
)
from brain.domain.entities.signal import (  # noqa: E402
    Signal,
    SignalQuality,
    SignalSource,
)
from brain.domain.entities.trade import (  # noqa: E402
    Order,
    OrderStatus,
    OrderType,
    Position,
)
from brain.domain.repositories.signal_repo import ISignalRepository  # noqa: E402
from brain.domain.repositories.state_repo import IStateRepository  # noqa: E402
from brain.domain.repositories.trade_repo import ITradeRepository  # noqa: E402


class SqliteEntityTradeRepository(_EntityBase, ITradeRepository):
    """Plans, orders and positions — entity-based, SQLite-backed."""

    # --- plan ------------------------------------------------------------

    def save_plan(self, plan: TradingPlan) -> None:
        payload = {
            "entry_price": plan.entry_price,
            "stop_loss": plan.stop_loss,
            "take_profit": plan.take_profit,
            "position_size": plan.position_size,
            "executed_at": _dt_to_ts(plan.executed_at),
            "closed_at": _dt_to_ts(plan.closed_at),
            "ticket": plan.ticket,
            "actual_entry_price": plan.actual_entry_price,
            "exit_price": plan.exit_price,
            "profit": plan.profit,
        }
        created_ts = _dt_to_ts(plan.created_at) or int(time.time())
        # schema.sql: plans.timeframe + expires_at are NOT NULL but the entity
        # has no expires_at field — default to created_at + 24h (mapping doc §5).
        expires_ts = created_ts + 24 * 3600
        self.conn.execute(
            """
            INSERT INTO plans (plan_id, symbol, timeframe, grade, created_at,
                               expires_at, status, bias,
                               analysis_json, plan_payload)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(plan_id) DO UPDATE SET
                symbol=excluded.symbol, timeframe=excluded.timeframe,
                grade=excluded.grade, created_at=excluded.created_at,
                expires_at=excluded.expires_at, status=excluded.status,
                bias=excluded.bias, analysis_json=excluded.analysis_json,
                plan_payload=excluded.plan_payload
            """,
            (
                plan.id,
                plan.symbol,
                getattr(plan, "timeframe", "M15"),
                _enum_text(plan.setup_grade),
                created_ts,
                expires_ts,
                "archived" if plan.stage == PlanStage.CLOSED else "active",
                plan.direction,
                json.dumps(plan.reasoning, default=str, ensure_ascii=False),
                json.dumps(payload, default=str, ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def _row_to_plan(self, row: sqlite3.Row) -> TradingPlan:
        payload = _load_json(row["plan_payload"])
        reasoning = _load_json(row["analysis_json"])
        try:
            stage = PlanStage(row["status"]) if row["status"] in PlanStage._value2member_map_ else PlanStage.ANALYSIS
        except ValueError:
            stage = PlanStage.ANALYSIS
        return TradingPlan(
            symbol=row["symbol"],
            direction=row["bias"] or "buy",
            entry_price=float(payload.get("entry_price") or 0.0),
            stop_loss=float(payload.get("stop_loss") or 0.0),
            take_profit=float(payload.get("take_profit") or 0.0),
            position_size=float(payload.get("position_size") or 0.0),
            setup_grade=_enum_from(row["grade"], SetupGrade) or SetupGrade.F,
            reasoning=reasoning,
            created_at=_ts_to_dt(row["created_at"]) or datetime.utcnow(),
            id=row["plan_id"],
            stage=stage,
            executed_at=_ts_to_dt(payload.get("executed_at")),
            closed_at=_ts_to_dt(payload.get("closed_at")),
            ticket=payload.get("ticket"),
            actual_entry_price=_f(payload.get("actual_entry_price")),
            exit_price=_f(payload.get("exit_price")),
            profit=_f(payload.get("profit")),
        )

    def get_plan(self, plan_id: str) -> Optional[TradingPlan]:
        row = self.conn.execute(
            "SELECT * FROM plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        return self._row_to_plan(row) if row else None

    def get_active_plan(self) -> Optional[TradingPlan]:
        row = self.conn.execute(
            "SELECT * FROM plans WHERE status='active' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return self._row_to_plan(row) if row else None

    def get_plan_history(self, start: datetime, end: datetime, limit: int = 100) -> list:
        rows = self.conn.execute(
            "SELECT * FROM plans WHERE created_at BETWEEN ? AND ? ORDER BY created_at DESC LIMIT ?",
            (_dt_to_ts(start), _dt_to_ts(end), limit),
        ).fetchall()
        return [self._row_to_plan(r) for r in rows]

    # --- order -----------------------------------------------------------

    def save_order(self, order: Order) -> None:
        self.conn.execute(
            """
            INSERT INTO orders (order_id, symbol, type, volume, entry_price,
                                stop_loss, take_profit, comment, created_at, status)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(order_id) DO UPDATE SET
                symbol=excluded.symbol, type=excluded.type, volume=excluded.volume,
                entry_price=excluded.entry_price, stop_loss=excluded.stop_loss,
                take_profit=excluded.take_profit, comment=excluded.comment,
                status=excluded.status
            """,
            (
                order.id,
                order.symbol,
                _enum_text(order.type),
                order.volume,
                order.entry_price,
                order.stop_loss,
                order.take_profit,
                order.comment,
                _dt_to_ts(order.timestamp) or 0,
                _enum_text(order.status),
            ),
        )
        self.conn.commit()

    def get_order(self, order_id: str) -> Optional[Order]:
        row = self.conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if not row:
            return None
        return Order(
            symbol=row["symbol"],
            type=_enum_from(row["type"], OrderType),
            volume=float(row["volume"]),
            entry_price=float(row["entry_price"]),
            stop_loss=float(row["stop_loss"]),
            take_profit=float(row["take_profit"]),
            comment=row["comment"] or "",
            timestamp=_ts_to_dt(row["created_at"]) or datetime.utcnow(),
            id=row["order_id"],
            status=_enum_from(row["status"], OrderStatus) or OrderStatus.PENDING,
        )

    # --- position ---------------------------------------------------------

    def save_position(self, position: Position) -> None:
        order = position.order
        self.conn.execute(
            """
            INSERT INTO trades (ticket, symbol, side, volume, entry_price,
                                stop_loss, take_profit, entry_time, status, profit,
                                source_ref)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(ticket) DO UPDATE SET
                symbol=excluded.symbol, side=excluded.side, volume=excluded.volume,
                entry_price=excluded.entry_price, stop_loss=excluded.stop_loss,
                take_profit=excluded.take_profit, entry_time=excluded.entry_time,
                status=excluded.status, profit=excluded.profit,
                source_ref=excluded.source_ref
            """,
            (
                position.ticket,
                order.symbol,
                _enum_text(order.type),
                order.volume,
                position.open_price,
                order.stop_loss,
                order.take_profit,
                _dt_to_ts(position.open_time) or 0,
                "closed" if order.status == OrderStatus.CLOSED else "open",
                position.profit,
                order.id,
            ),
        )
        self.conn.commit()

    def _row_to_position(self, row: sqlite3.Row) -> Position:
        order = Order(
            symbol=row["symbol"],
            type=_enum_from(row["side"], OrderType) or OrderType.BUY,
            volume=float(row["volume"]),
            entry_price=float(row["entry_price"]),
            stop_loss=float(row["stop_loss"] or 0.0),
            take_profit=float(row["take_profit"] or 0.0),
            comment="",
            timestamp=_ts_to_dt(row["entry_time"]) or datetime.utcnow(),
            id=str(row["source_ref"] or ""),
            status=_enum_from(row["status"], OrderStatus) or OrderStatus.OPEN,
        )
        return Position(
            ticket=int(row["ticket"]),
            order=order,
            open_time=_ts_to_dt(row["entry_time"]) or datetime.utcnow(),
            open_price=float(row["entry_price"]),
            current_price=float(row["entry_price"]),
            profit=_f(row["profit"]) or 0.0,
        )

    def get_position(self, ticket: int) -> Optional[Position]:
        row = self.conn.execute(
            "SELECT * FROM trades WHERE ticket = ?", (ticket,)
        ).fetchone()
        return self._row_to_position(row) if row else None

    def get_open_positions(self, symbol: Optional[str] = None) -> list:
        if symbol is not None:
            rows = self.conn.execute(
                "SELECT * FROM trades WHERE status='open' AND symbol=? ORDER BY entry_time",
                (symbol,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM trades WHERE status='open' ORDER BY entry_time"
            ).fetchall()
        return [self._row_to_position(r) for r in rows]

    def get_closed_trades(self, start: datetime, end: datetime, limit: int = 100) -> list:
        rows = self.conn.execute(
            "SELECT * FROM trades WHERE status='closed' AND exit_time BETWEEN ? AND ? "
            "ORDER BY exit_time DESC LIMIT ?",
            (_dt_to_ts(start), _dt_to_ts(end), limit),
        ).fetchall()
        return [
            {
                "ticket": r["ticket"],
                "symbol": r["symbol"],
                "side": r["side"],
                "volume": r["volume"],
                "entry_price": r["entry_price"],
                "exit_price": r["exit_price"],
                "profit": r["profit"],
                "net_pnl": r["net_pnl"],
                "entry_time": r["entry_time"],
                "exit_time": r["exit_time"],
                "exit_reason": r["exit_reason"],
            }
            for r in rows
        ]


class SqliteEntitySignalRepository(_EntityBase, ISignalRepository):
    """Signals — entity-based, with lossless JSON sidecars."""

    def save_signal(self, signal: Signal) -> None:
        payload = {
            "validation_result": signal.validation_result,
            "cross_check_result": signal.cross_check_result,
        }
        self.conn.execute(
            """
            INSERT INTO signals (signal_id, symbol, direction, entry_price,
                                 stop_loss, take_profit, source, source_id,
                                 raw_message, confidence_score, quality,
                                 received_at, signal_payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(signal_id) DO UPDATE SET
                symbol=excluded.symbol, direction=excluded.direction,
                entry_price=excluded.entry_price, stop_loss=excluded.stop_loss,
                take_profit=excluded.take_profit, source=excluded.source,
                source_id=excluded.source_id, raw_message=excluded.raw_message,
                confidence_score=excluded.confidence_score, quality=excluded.quality,
                received_at=excluded.received_at, signal_payload=excluded.signal_payload
            """,
            (
                signal.id,
                signal.symbol,
                signal.direction,
                signal.entry_price,
                signal.stop_loss,
                signal.take_profit,
                _enum_text(signal.source),
                signal.source_id,
                signal.raw_message,
                signal.confidence_score,
                _enum_text(signal.quality),
                _dt_to_ts(signal.timestamp) or 0,
                json.dumps(payload, default=str, ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def _row_to_signal(self, row: sqlite3.Row) -> Signal:
        payload = _load_json(row["signal_payload"])
        return Signal(
            symbol=row["symbol"],
            direction=row["direction"],
            entry_price=float(row["entry_price"]),
            stop_loss=float(row["stop_loss"]),
            take_profit=float(row["take_profit"]),
            source=_enum_from(row["source"], SignalSource) or SignalSource.TELEGRAM,
            timestamp=_ts_to_dt(row["received_at"]) or datetime.utcnow(),
            id=row["signal_id"],
            raw_message=row["raw_message"] or "",
            source_id=row["source_id"] or "",
            confidence_score=float(row["confidence_score"] or 0.5),
            quality=_enum_from(row["quality"], SignalQuality) or SignalQuality.ACCEPTABLE,
            validation_result=payload.get("validation_result", {}),
            cross_check_result=payload.get("cross_check_result", {}),
        )

    def get_signal(self, signal_id: str) -> Optional[Signal]:
        row = self.conn.execute(
            "SELECT * FROM signals WHERE signal_id = ?", (signal_id,)
        ).fetchone()
        return self._row_to_signal(row) if row else None

    def get_pending_signals(self) -> list:
        rows = self.conn.execute(
            "SELECT * FROM signals WHERE status='pending' ORDER BY received_at"
        ).fetchall()
        return [self._row_to_signal(r) for r in rows]

    def get_recent_signals(self, start: Optional[datetime] = None, limit: int = 50) -> list:
        if start is not None:
            rows = self.conn.execute(
                "SELECT * FROM signals WHERE received_at >= ? ORDER BY received_at DESC LIMIT ?",
                (_dt_to_ts(start), limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM signals ORDER BY received_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_signal(r) for r in rows]

    def mark_signal_processed(self, signal_id: str, result: dict) -> None:
        self.conn.execute(
            "UPDATE signals SET status='processed', processed_at=?, decision_reasoning=? WHERE signal_id=?",
            (int(datetime.utcnow().timestamp()), json.dumps(result, default=str), signal_id),
        )
        self.conn.commit()


class SqliteEntityStateRepository(_EntityBase, IStateRepository):
    """Account snapshots + key/value system state — entity/dict per interface."""

    def save_account_state(self, state: AccountState) -> None:
        self.conn.execute(
            """
            INSERT INTO account_snapshots (balance, equity, margin, margin_free,
                                           open_positions, open_positions_volume,
                                           daily_pnl, daily_trades, daily_wins,
                                           daily_losses, captured_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                state.balance,
                state.equity,
                state.margin_used,
                state.margin_free,
                state.open_positions,
                state.open_positions_volume,
                state.daily_pnl,
                state.daily_trades,
                state.daily_wins,
                state.daily_losses,
                _dt_to_ts(state.timestamp) or int(datetime.utcnow().timestamp()),
            ),
        )
        self.conn.commit()

    def get_account_state(self) -> Optional[AccountState]:
        row = self.conn.execute(
            "SELECT * FROM account_snapshots ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return AccountState(
            balance=float(row["balance"]),
            equity=float(row["equity"]),
            margin_free=float(row["margin_free"] or 0.0),
            margin_used=float(row["margin"] or 0.0),
            open_positions=int(row["open_positions"] or 0),
            open_positions_volume=float(row["open_positions_volume"] or 0.0),
            daily_pnl=float(row["daily_pnl"] or 0.0),
            daily_trades=int(row["daily_trades"] or 0),
            daily_wins=int(row["daily_wins"] or 0),
            daily_losses=int(row["daily_losses"] or 0),
            timestamp=_ts_to_dt(row["captured_at"]),
        )

    def save_performance_state(self, state: dict) -> None:
        self._save_kv("performance", state)

    def get_performance_state(self) -> dict:
        return self._load_kv("performance", {})

    def save_learning_state(self, state: dict) -> None:
        self._save_kv("learning", state)

    def get_learning_state(self) -> dict:
        return self._load_kv("learning", {})

    def save_system_state(self, key: str, value) -> None:
        self._save_kv(key, value)

    def get_system_state(self, key: str, default=None):
        return self._load_kv(key, default)

    # --- private helpers ---------------------------------------------------

    def _save_kv(self, key: str, value) -> None:
        self.conn.execute(
            """
            INSERT INTO system_state (key, value, updated_at)
            VALUES (?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, json.dumps(value, default=str), int(datetime.utcnow().timestamp())),
        )
        self.conn.commit()

    def _load_kv(self, key: str, default):
        row = self.conn.execute(
            "SELECT value FROM system_state WHERE key=?", (key,)
        ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except (ValueError, TypeError):
            return default


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
