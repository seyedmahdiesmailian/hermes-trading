"""Tests for the entity-based SQLite repositories (Phase 1.4).

These pin the domain contract: entities go in, ENTITIES come back.
Dicts never leak across the repository boundary.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.gateways.data.sqlite_repository import (  # noqa: E402
    SqliteEntitySignalRepository,
    SqliteEntityStateRepository,
    SqliteEntityTradeRepository,
    ensure_entity_schema,
)
from brain.domain.entities.account import AccountState  # noqa: E402
from brain.domain.entities.plan import PlanStage, SetupGrade, TradingPlan  # noqa: E402
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


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    p = tmp_path / "entities.db"
    conn = sqlite3.connect(str(p))
    ensure_entity_schema(conn)
    conn.close()
    return p


@pytest.fixture()
def trade_repo(db: Path) -> SqliteEntityTradeRepository:
    repo = SqliteEntityTradeRepository(db)
    yield repo
    repo.close()


@pytest.fixture()
def signal_repo(db: Path) -> SqliteEntitySignalRepository:
    repo = SqliteEntitySignalRepository(db)
    yield repo
    repo.close()


@pytest.fixture()
def state_repo(db: Path) -> SqliteEntityStateRepository:
    repo = SqliteEntityStateRepository(db)
    yield repo
    repo.close()


def make_plan(**over) -> TradingPlan:
    base = dict(
        symbol="XAUUSD",
        direction="buy",
        entry_price=2400.0,
        stop_loss=2390.0,
        take_profit=2420.0,
        position_size=0.5,
        setup_grade=SetupGrade.A,
        reasoning={"trend": "bullish", "score": 8},
        id="plan-test-001",
    )
    base.update(over)
    return TradingPlan(**base)


def make_signal(**over) -> Signal:
    base = dict(
        symbol="XAUUSD",
        direction="sell",
        entry_price=2410.0,
        stop_loss=2420.0,
        take_profit=2390.0,
        source=SignalSource.TELEGRAM,
        id="sig-test-001",
        raw_message="SELL XAUUSD 2410 SL 2420 TP 2390",
        source_id="msg-123",
        confidence_score=0.8,
        quality=SignalQuality.GOOD,
        validation_result={"ok": True, "checks": ["format", "levels"]},
        cross_check_result={"match": 0.9},
    )
    base.update(over)
    return Signal(**base)


def make_order(**over) -> Order:
    base = dict(
        symbol="XAUUSD",
        type=OrderType.BUY,
        volume=0.2,
        entry_price=2400.0,
        stop_loss=2390.0,
        take_profit=2420.0,
        comment="test order",
        id="order-test-001",
        status=OrderStatus.PENDING,
    )
    base.update(over)
    return Order(**base)


# ---------------------------------------------------------------------------
# plan round-trips
# ---------------------------------------------------------------------------

class TestPlanRoundTrip:
    def test_save_and_get_plan(self, trade_repo):
        plan = make_plan()
        trade_repo.save_plan(plan)

        out = trade_repo.get_plan("plan-test-001")
        assert out is not None
        assert out.id == "plan-test-001"
        assert out.symbol == "XAUUSD"
        assert out.direction == "buy"
        assert out.entry_price == pytest.approx(2400.0)
        assert out.stop_loss == pytest.approx(2390.0)
        assert out.take_profit == pytest.approx(2420.0)
        assert out.position_size == pytest.approx(0.5)
        assert out.setup_grade == SetupGrade.A
        assert out.reasoning == {"trend": "bullish", "score": 8}

    def test_plan_sidecar_fields_round_trip(self, trade_repo):
        plan = make_plan(
            stage=PlanStage.MONITORING,
            ticket=11223344,
            actual_entry_price=2401.5,
            exit_price=2418.0,
            profit=85.0,
        )
        plan.executed_at = datetime(2026, 10, 15, 12, 0)
        plan.closed_at = datetime(2026, 10, 15, 14, 0)
        trade_repo.save_plan(plan)

        out = trade_repo.get_plan(plan.id)
        assert out is not None
        assert out.ticket == 11223344
        assert out.actual_entry_price == pytest.approx(2401.5)
        assert out.exit_price == pytest.approx(2418.0)
        assert out.profit == pytest.approx(85.0)
        assert out.executed_at is not None
        assert out.closed_at is not None

    def test_save_plan_is_idempotent(self, trade_repo):
        plan = make_plan()
        trade_repo.save_plan(plan)
        plan.reasoning = {"updated": True}
        trade_repo.save_plan(plan)
        out = trade_repo.get_plan(plan.id)
        assert out is not None
        assert out.reasoning == {"updated": True}

        rows = trade_repo.conn.execute(
            "SELECT COUNT(*) AS n FROM plans WHERE plan_id=?", (plan.id,)
        ).fetchone()
        assert rows["n"] == 1

    def test_get_plan_none_when_missing(self, trade_repo):
        assert trade_repo.get_plan("nope") is None

    def test_get_active_plan_returns_latest(self, trade_repo):
        old = make_plan(id="plan-old")
        old.created_at = datetime(2026, 10, 1)
        trade_repo.save_plan(old)

        new = make_plan(id="plan-new")
        new.created_at = datetime(2026, 10, 15)
        trade_repo.save_plan(new)

        active = trade_repo.get_active_plan()
        assert active is not None
        assert active.id == "plan-new"

    def test_closed_plan_status_archived(self, trade_repo):
        plan = make_plan(stage=PlanStage.CLOSED)
        trade_repo.save_plan(plan)
        row = trade_repo.conn.execute(
            "SELECT status FROM plans WHERE plan_id=?", (plan.id,)
        ).fetchone()
        assert row["status"] == "archived"

    def test_plan_stage_recovery_falls_back(self, trade_repo):
        plan = make_plan()
        trade_repo.save_plan(plan)
        trade_repo.conn.execute(
            "UPDATE plans SET status='weird' WHERE plan_id=?", (plan.id,)
        )
        trade_repo.conn.commit()
        out = trade_repo.get_plan(plan.id)
        assert out is not None
        assert out.stage == PlanStage.ANALYSIS


class TestPlanHistory:
    def test_history_range_and_limit(self, trade_repo):
        for day in (2, 4, 6, 8):
            p = make_plan(id=f"plan-d{day}")
            p.created_at = datetime(2026, 10, day)
            trade_repo.save_plan(p)

        start = datetime(2026, 10, 3)
        end = datetime(2026, 10, 9)
        out = trade_repo.get_plan_history(start, end, limit=10)
        ids = {p.id for p in out}
        assert ids == {"plan-d4", "plan-d6", "plan-d8"}

        limited = trade_repo.get_plan_history(start, end, limit=2)
        assert len(limited) == 2


# ---------------------------------------------------------------------------
# order + position round-trips
# ---------------------------------------------------------------------------

class TestOrderRoundTrip:
    def test_save_and_get_order(self, trade_repo):
        order = make_order()
        trade_repo.save_order(order)
        out = trade_repo.get_order(order.id)
        assert out is not None
        assert out.id == order.id
        assert out.type == OrderType.BUY
        assert out.volume == pytest.approx(0.2)
        assert out.entry_price == pytest.approx(2400.0)
        assert out.status == OrderStatus.PENDING
        assert out.comment == "test order"

    def test_order_idempotent_upsert(self, trade_repo):
        order = make_order()
        trade_repo.save_order(order)
        order.status = OrderStatus.SUBMITTED
        trade_repo.save_order(order)
        out = trade_repo.get_order(order.id)
        assert out is not None
        assert out.status == OrderStatus.SUBMITTED
        n = trade_repo.conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE order_id=?", (order.id,)
        ).fetchone()
        assert n["n"] == 1

    def test_get_order_none_when_missing(self, trade_repo):
        assert trade_repo.get_order("missing-order") is None


class TestPositionRoundTrip:
    def make_position(self, ticket=100000001):
        order = make_order()
        return Position(
            ticket=ticket,
            order=order,
            open_time=datetime(2026, 10, 15, 10, 0),
            open_price=2400.0,
            current_price=2405.0,
            profit=25.0,
        )

    def test_save_and_get_position(self, trade_repo):
        pos = self.make_position()
        trade_repo.save_position(pos)
        out = trade_repo.get_position(100000001)
        assert out is not None
        assert out.ticket == 100000001
        assert out.order.symbol == "XAUUSD"
        assert out.order.type == OrderType.BUY
        assert out.open_price == pytest.approx(2400.0)
        assert out.profit == pytest.approx(25.0)

    def test_position_upsert_on_same_ticket(self, trade_repo):
        pos = self.make_position()
        trade_repo.save_position(pos)
        pos.profit = 60.0
        trade_repo.save_position(pos)
        out = trade_repo.get_position(100000001)
        assert out is not None
        assert out.profit == pytest.approx(60.0)
        n = trade_repo.conn.execute(
            "SELECT COUNT(*) AS n FROM trades WHERE ticket=100000001"
        ).fetchone()
        assert n["n"] == 1

    def test_get_open_positions_filter_by_symbol(self, trade_repo):
        p1 = self.make_position(ticket=1)
        trade_repo.save_position(p1)

        order2 = make_order(symbol="XAUUSD", id="o2")
        p2 = Position(
            ticket=2,
            order=order2,
            open_time=datetime(2026, 10, 15, 11),
            open_price=2410.0,
            current_price=2410.0,
        )
        trade_repo.save_position(p2)

        all_open = trade_repo.get_open_positions()
        assert len(all_open) == 2

        # an XAUUSD filter should return both (same symbol)
        same = trade_repo.get_open_positions(symbol="XAUUSD")
        assert len(same) == 2

        none = trade_repo.get_open_positions(symbol="EURUSD")
        assert none == []

    def test_get_position_none_when_missing(self, trade_repo):
        assert trade_repo.get_position(999999999) is None


# ---------------------------------------------------------------------------
# signal round-trips
# ---------------------------------------------------------------------------

class TestSignalRoundTrip:
    def test_save_and_get_signal(self, signal_repo):
        sig = make_signal()
        signal_repo.save_signal(sig)

        out = signal_repo.get_signal("sig-test-001")
        assert out is not None
        assert out.id == "sig-test-001"
        assert out.symbol == "XAUUSD"
        assert out.direction == "sell"
        assert out.entry_price == pytest.approx(2410.0)
        assert out.source == SignalSource.TELEGRAM
        assert out.quality == SignalQuality.GOOD
        assert out.confidence_score == pytest.approx(0.8)
        assert out.raw_message == "SELL XAUUSD 2410 SL 2420 TP 2390"
        assert out.source_id == "msg-123"

    def test_signal_sidecar_dicts_round_trip(self, signal_repo):
        sig = make_signal()
        signal_repo.save_signal(sig)
        out = signal_repo.get_signal(sig.id)
        assert out is not None
        assert out.validation_result == {"ok": True, "checks": ["format", "levels"]}
        assert out.cross_check_result == {"match": 0.9}

    def test_signal_idempotent_upsert(self, signal_repo):
        sig = make_signal()
        signal_repo.save_signal(sig)
        sig.confidence_score = 0.95
        signal_repo.save_signal(sig)

        out = signal_repo.get_signal(sig.id)
        assert out is not None
        assert out.confidence_score == pytest.approx(0.95)
        n = signal_repo.conn.execute(
            "SELECT COUNT(*) AS n FROM signals WHERE signal_id=?", (sig.id,)
        ).fetchone()
        assert n["n"] == 1

    def test_pending_signals(self, signal_repo):
        s1 = make_signal(id="sig-1")
        s2 = make_signal(id="sig-2")
        signal_repo.save_signal(s1)
        signal_repo.save_signal(s2)

        pending = signal_repo.get_pending_signals()
        assert len(pending) == 2

        signal_repo.mark_signal_processed("sig-1", {"decision": "accepted"})
        pending = signal_repo.get_pending_signals()
        assert len(pending) == 1
        assert pending[0].id == "sig-2"

    def test_mark_processed_records_reasoning(self, signal_repo):
        sig = make_signal()
        signal_repo.save_signal(sig)
        signal_repo.mark_signal_processed(sig.id, {"decision": "rejected"})
        row = signal_repo.conn.execute(
            "SELECT status, decision_reasoning FROM signals WHERE signal_id=?",
            (sig.id,),
        ).fetchone()
        assert row["status"] == "processed"
        assert json.loads(row["decision_reasoning"]) == {"decision": "rejected"}

    def test_recent_signals_limit_and_start(self, signal_repo):
        for i in range(5):
            s = make_signal(id=f"sig-r{i}")
            s.timestamp = datetime(2026, 10, 10 + i)
            signal_repo.save_signal(s)

        out = signal_repo.get_recent_signals(limit=3)
        assert len(out) == 3

        since = signal_repo.get_recent_signals(start=datetime(2026, 10, 12))
        assert len(since) == 3

    def test_get_signal_none_when_missing(self, signal_repo):
        assert signal_repo.get_signal("nope") is None


# ---------------------------------------------------------------------------
# state round-trips
# ---------------------------------------------------------------------------

class TestStateRoundTrip:
    def test_save_and_get_account_state(self, state_repo):
        st = AccountState(
            balance=5000.0,
            equity=5025.0,
            margin_free=4900.0,
            margin_used=100.0,
            open_positions=1,
            open_positions_volume=0.2,
            daily_pnl=25.0,
            daily_trades=3,
            daily_wins=2,
            daily_losses=1,
            timestamp=datetime(2026, 10, 15, 12, 0),
        )
        state_repo.save_account_state(st)

        out = state_repo.get_account_state()
        assert out is not None
        assert out.balance == pytest.approx(5000.0)
        assert out.equity == pytest.approx(5025.0)
        assert out.margin_free == pytest.approx(4900.0)
        assert out.margin_used == pytest.approx(100.0)
        assert out.open_positions == 1
        assert out.open_positions_volume == pytest.approx(0.2)
        assert out.daily_pnl == pytest.approx(25.0)
        assert out.daily_wins == 2
        assert out.daily_losses == 1

    def test_account_state_latest_wins(self, state_repo):
        for i, bal in enumerate((100.0, 200.0, 300.0)):
            state_repo.save_account_state(
                AccountState(
                    balance=bal,
                    equity=bal,
                    margin_free=bal,
                    timestamp=datetime(2026, 10, 15, 10 + i),
                )
            )
        out = state_repo.get_account_state()
        assert out is not None
        assert out.balance == pytest.approx(300.0)

    def test_get_account_state_none_when_empty(self, state_repo):
        assert state_repo.get_account_state() is None

    def test_performance_and_learning_state(self, state_repo):
        state_repo.save_performance_state({"win_rate": 0.66, "trades": 62})
        assert state_repo.get_performance_state() == {"win_rate": 0.66, "trades": 62}

        state_repo.save_learning_state({"pattern": "engulfing", "hits": 4})
        assert state_repo.get_learning_state() == {"pattern": "engulfing", "hits": 4}

        # overwrite
        state_repo.save_performance_state({"win_rate": 0.7})
        assert state_repo.get_performance_state() == {"win_rate": 0.7}

    def test_system_state_key_value(self, state_repo):
        state_repo.save_system_state("kill_switch", {"active": False})
        assert state_repo.get_system_state("kill_switch") == {"active": False}

        state_repo.save_system_state("counter", 5)
        assert state_repo.get_system_state("counter") == 5

        assert state_repo.get_system_state("missing", default="fallback") == "fallback"

    def test_system_state_overwrite(self, state_repo):
        state_repo.save_system_state("k", "v1")
        state_repo.save_system_state("k", "v2")
        assert state_repo.get_system_state("k") == "v2"
        n = state_repo.conn.execute(
            "SELECT COUNT(*) AS n FROM system_state WHERE key='k'"
        ).fetchone()
        assert n["n"] == 1


# ---------------------------------------------------------------------------
# compatibility with the production database
# ---------------------------------------------------------------------------

class TestProductionDbCompat:
    def test_schema_bootstrap_on_real_db(self, tmp_path: Path):
        """ensure_entity_schema must be safe on a database that already has the
        legacy tables (it only adds sidecar columns)."""
        p = tmp_path / "prod_like.db"
        conn = sqlite3.connect(str(p))
        conn.executescript((ROOT / "database" / "schema.sql").read_text())
        before = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        ensure_entity_schema(conn)
        after = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        # only ADDITIONS allowed: existing tables intact, sidecars present
        assert before.issubset(after)
        assert "orders" in after
        cols = {c[1] for c in conn.execute("PRAGMA table_info(signals)")}
        assert "signal_payload" in cols
        conn.close()

    def test_sidecar_added_once(self, tmp_path: Path):
        p = tmp_path / "twice.db"
        conn = sqlite3.connect(str(p))
        ensure_entity_schema(conn)
        ensure_entity_schema(conn)  # idempotent
        cols = {c[1] for c in conn.execute("PRAGMA table_info(plans)")}
        assert "plan_payload" in cols
        conn.close()
