"""
Tests for adapters/gateways/data/sqlite_repository.py.

Pins the single-source-of-truth contract:
  * writes are idempotent (no duplicate plan/signal/trade rows)
  * reads return the saved data
  * the guard verdict audit trail is append-only
"""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.gateways.data.sqlite_repository import (
    SqlitePlanRepository,
    SqliteSafetyEventRepository,
    SqliteSignalRepository,
    SqliteTradeRepository,
)


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    """Fresh DB with the canonical schema applied."""
    schema = Path(__file__).resolve().parents[1] / "database" / "schema.sql"
    import sqlite3
    path = tmp_path / "test.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(schema.read_text())
    return path


@pytest.fixture()
def plans(db):
    return SqlitePlanRepository(db)


@pytest.fixture()
def signals(db):
    return SqliteSignalRepository(db)


@pytest.fixture()
def trades(db):
    return SqliteTradeRepository(db)


@pytest.fixture()
def events(db):
    return SqliteSafetyEventRepository(db)


_SAMPLE_PLAN = {
    "plan_id": "plan-001",
    "symbol": "XAUUSD",
    "timeframe": "M15",
    "bias": "bullish",
    "atr": 3.2,
    "grade": "A",
    "setup_score": 0.82,
    "status": "active",
}


class TestPlanRepository:
    def test_save_and_get_current(self, plans):
        pid = plans.save_plan(_SAMPLE_PLAN)
        assert pid == "plan-001"

        current = plans.get_current_plan()
        assert current is not None
        assert current["plan_id"] == "plan-001"
        assert current["symbol"] == "XAUUSD"
        assert current["bias"] == "bullish"

    def test_save_is_idempotent(self, plans):
        plans.save_plan(_SAMPLE_PLAN)
        plans.save_plan(_SAMPLE_PLAN)
        assert len(plans.list_plans()) == 1

    def test_new_active_plan_supersedes_current(self, plans):
        # IMPORTANT: get_current_plan orders by created_at DESC. _SAMPLE_PLAN
        # has no created_at so the repo stamps it with _utcnow() — the second
        # plan must therefore use an explicit, provably-newer timestamp or the
        # test becomes date-dependent.
        plans.save_plan(dict(_SAMPLE_PLAN, created_at="2020-01-01T00:00:00+00:00"))
        second = dict(_SAMPLE_PLAN, plan_id="plan-002",
                      created_at="2026-10-15T23:59:59+00:00")
        plans.save_plan(second)

        current = plans.get_current_plan()
        assert current["plan_id"] == "plan-002"

    def test_update_status(self, plans):
        plans.save_plan(_SAMPLE_PLAN)
        plans.update_plan_status("plan-001", "expired")

        assert plans.get_current_plan() is None
        assert plans.get_plan("plan-001")["status"] == "expired"

    def test_missing_plan_returns_none(self, plans):
        assert plans.get_plan("nope") is None
        assert plans.get_current_plan() is None

    def test_generated_id_when_missing(self, plans):
        pid = plans.save_plan({"symbol": "XAUUSD"})
        assert pid.startswith("plan-")

    def test_analysis_json_roundtrip(self, plans):
        plans.save_plan(dict(_SAMPLE_PLAN, analysis={"trend": "up", "score": 9}))
        row = plans.get_plan("plan-001")
        assert "trend" in row["analysis_json"]


class TestSignalRepository:
    _FULL = {
        "signal_id": "sig-001",
        "symbol": "XAUUSD",
        "direction": "BUY",
        "entry_price": 2000.0,
        "stop_loss": 1990.0,
        "take_profit": 2020.0,
        "source": "channel-a",
        "received_at": "2026-10-15T00:00:00+00:00",
    }

    def test_save_and_get(self, signals):
        sid = signals.save_signal(dict(self._FULL, raw_message="BUY XAUUSD 2000 SL 1990 TP 2020"))
        assert sid == "sig-001"

        row = signals.get_signal("sig-001")
        assert row["direction"] == "BUY"
        assert row["status"] == "pending"

    def test_save_is_idempotent(self, signals):
        signals.save_signal(dict(self._FULL))
        signals.save_signal(dict(self._FULL))
        assert len(signals.list_signals()) == 1

    def test_pending_then_status_update(self, signals):
        signals.save_signal(dict(self._FULL))
        assert len(signals.get_pending_signals()) == 1

        signals.update_signal_status("sig-001", "accepted", "rr ok")
        assert len(signals.get_pending_signals()) == 0
        assert signals.get_signal("sig-001")["status"] == "accepted"

    def test_no_signal_id_returns_none(self, signals):
        assert signals.save_signal({"symbol": "XAUUSD"}) is None

    def test_list_orders_by_recency(self, signals):
        signals.save_signal(dict(self._FULL, signal_id="sig-001",
                                 received_at="2026-10-10T00:00:00+00:00"))
        signals.save_signal(dict(self._FULL, signal_id="sig-002",
                                 received_at="2026-10-15T00:00:00+00:00"))
        ordered = [s["signal_id"] for s in signals.list_signals()]
        assert ordered[0] == "sig-002"


class TestTradeRepository:
    _FULL = {
        "ticket": 99122845,
        "symbol": "XAUUSD",
        "side": "BUY",
        "volume": 0.05,
        "entry_price": 2000.0,
        "net_pnl": 0.0,
        "status": "open",
    }

    def test_save_and_open(self, trades):
        ticket = trades.save_trade(dict(self._FULL))
        assert ticket == 99122845
        assert len(trades.get_open_trades()) == 1

    def test_save_is_idempotent(self, trades):
        trades.save_trade(dict(self._FULL))
        trades.save_trade(dict(self._FULL))
        assert len(trades.list_trades()) == 1

    def test_close_trade(self, trades):
        trades.save_trade(dict(self._FULL))
        trades.close_trade(99122845, exit_price=2010.0, net_pnl=50.0, exit_reason="tp")

        open_trades = trades.get_open_trades()
        assert len(open_trades) == 0
        closed = trades.list_trades()[0]
        assert closed["status"] == "closed"
        assert closed["net_pnl"] == 50.0

    def test_no_ticket_returns_none(self, trades):
        assert trades.save_trade({"symbol": "XAUUSD"}) is None


class TestSafetyEventRepository:
    def test_record_event(self, events):
        eid = events.record_event("guard_verdict", "WARN", "poor_rr_0.50")
        assert eid > 0

        rows = events.list_events()
        assert len(rows) == 1
        assert rows[0]["event_type"] == "guard_verdict"
        assert rows[0]["severity"] == "WARN"

    def test_record_guard_verdict_allowed_is_info(self, events):
        verdict = {"allowed": True, "reason": "ok"}
        events.record_guard_verdict(verdict)
        assert events.list_events()[0]["severity"] == "INFO"

    def test_record_guard_verdict_denied_is_warn(self, events):
        verdict = {"allowed": False, "reason": "daily_loss_limit"}
        events.record_guard_verdict(verdict)
        assert events.list_events()[0]["severity"] == "WARN"

    def test_data_json_roundtrip(self, events):
        events.record_event("guard_verdict", "WARN", "x", {"a": 1, "b": [2, 3]})
        row = events.list_events()[0]
        assert '"a": 1' in row["data_json"]

    def test_append_only(self, events):
        events.record_event("guard_verdict", "WARN", "first")
        events.record_event("guard_verdict", "WARN", "second")
        assert len(events.list_events()) == 2

    def test_events_ordered_newest_first(self, events):
        import time
        events.record_event("guard_verdict", "WARN", "first")
        time.sleep(0.01)
        events.record_event("new class", "INFO", "second")
        rows = events.list_events()
        assert rows[0]["event_type"] == "new class"


# ---------------------------------------------------------------------------
# Cross-cutting: real database integration
# ---------------------------------------------------------------------------

class TestRealDatabase:
    """Sanity check against data/hermes.db without modifying it."""

    def test_real_db_has_journal(self):
        from adapters.gateways.data.sqlite_repository import DEFAULT_DB_PATH
        assert DEFAULT_DB_PATH.exists(), "data/hermes.db must exist"

        trades = SqliteTradeRepository()
        rows = trades.list_trades(limit=5)
        assert len(rows) > 0, "the journal of 62 trades must be readable"

    def test_real_db_is_read_only_here(self):
        # Re-reading must never duplicate or alter rows.
        trades = SqliteTradeRepository()
        before = len(trades.list_trades(limit=1000))
        trades.list_trades(limit=1000)
        after = len(trades.list_trades(limit=1000))
        assert before == after
