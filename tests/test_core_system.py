""" tests/test_core_system — تست‌های جامع و مستقل لایه هسته (core) هرمس

این تست‌ها بدون وابستگی به شبکه یا MT5 زنده، صحت کلیه موجودیت‌ها،
دروازه‌های ریسک، محاسبات موتور تحلیل، مدیریت خروج و دفتر کل دیتابیس را تضمین می‌کنند.
"""
from __future__ import annotations

import sqlite3
import time
from decimal import Decimal
from pathlib import Path

import pytest

from core.entities import (
    AccountState,
    BrokerPosition,
    Candle,
    ExitReason,
    Order,
    OrderStatus,
    Plan,
    SetupGrade,
    Side,
    Signal,
    Tick,
    Trade,
    to_json,
)
from core.params import Gates, PositionCfg
from core.gates import GatesEngine, CONTRACT_SIZE
from core.engine import Engine, MarketView, _ema, _atr, _calc_rr
from core.exits import ExitManager
from core.db import Ledger


# ══════════════════════════════════════════════════════════════════
# ۱. تست‌های موجودیت‌ها (Entities)
# ══════════════════════════════════════════════════════════════════

class TestCoreEntities:
    def test_candle_properties(self):
        c = Candle(time=1700000000, open=2000.0, high=2010.0, low=1995.0, close=2008.0, volume=100)
        assert c.is_bullish is True
        assert c.body == 8.0
        assert c.range_ == 15.0

        bearish = Candle(time=1700000000, open=2010.0, high=2015.0, low=1990.0, close=1995.0, volume=120)
        assert bearish.is_bullish is False
        assert bearish.body == 15.0

    def test_tick_properties(self):
        t = Tick(symbol="XAUUSD", bid=2050.20, ask=2050.50, time=1700000000)
        assert round(t.mid, 2) == 2050.35
        assert round(t.spread, 2) == 0.30

    def test_broker_position_rr_progress(self):
        # BUY: SL=2000, Open=2010, TP=2030, Current=2015
        pos_buy = BrokerPosition(
            ticket=101, symbol="XAUUSD", side=Side.BUY, volume=0.1,
            open_price=2010.0, current_price=2015.0, sl=2000.0, tp=2030.0,
            profit=50.0, swap=0.0, open_time=1700000000, comment="hms-1"
        )
        assert pos_buy.is_buy is True
        # span = 30.0, progress = (2015 - 2000) / 30 = 15/30 = 0.5
        assert pytest.approx(pos_buy.rr_progress, 0.01) == 0.5

        # SELL: SL=2030, Open=2020, TP=2000, Current=2015
        pos_sell = BrokerPosition(
            ticket=102, symbol="XAUUSD", side=Side.SELL, volume=0.1,
            open_price=2020.0, current_price=2015.0, sl=2030.0, tp=2000.0,
            profit=50.0, swap=0.0, open_time=1700000000, comment="hms-2"
        )
        assert pos_sell.is_buy is False
        # span = 30.0, progress = (2030 - 2015) / 30 = 15/30 = 0.5
        assert pytest.approx(pos_sell.rr_progress, 0.01) == 0.5

    def test_signal_validity(self):
        valid_sig = Signal(
            signal_id="sig-1", raw_text="BUY XAUUSD 2050 SL 2040 TP 2070",
            symbol="XAUUSD", side=Side.BUY, entry=2050.0, sl=2040.0, tp=2070.0,
            rr=2.0, confidence=0.8, timestamp="2026-10-28T12:00:00Z"
        )
        assert valid_sig.is_valid is True

        # Invalid: SL above Entry for BUY
        bad_sig = Signal(
            signal_id="sig-2", raw_text="BUY XAUUSD 2050 SL 2060 TP 2070",
            symbol="XAUUSD", side=Side.BUY, entry=2050.0, sl=2060.0, tp=2070.0,
            rr=2.0, confidence=0.8, timestamp="2026-10-28T12:00:00Z"
        )
        assert bad_sig.is_valid is False

    def test_plan_risk_and_reward(self):
        plan = Plan(
            plan_id="p-1", symbol="XAUUSD", side=Side.BUY,
            entry_price=2050.0, stop_loss=2040.0, take_profit=2070.0,
            volume=0.1, grade=SetupGrade.A, source="analysis", rr=2.0
        )
        assert pytest.approx(plan.risk_amount, 0.01) == 1.0
        assert pytest.approx(plan.reward_amount, 0.01) == 2.0

    def test_to_json_helper(self):
        plan = Plan(
            plan_id="p-json", symbol="XAUUSD", side=Side.BUY,
            entry_price=2050.0, stop_loss=2040.0, take_profit=2070.0,
            volume=0.1, grade=SetupGrade.A, source="analysis"
        )
        js = to_json(plan)
        assert '"side": "BUY"' in js
        assert '"grade": "A"' in js


# ══════════════════════════════════════════════════════════════════
# ۲. تست‌های دروازه‌های ریسک (GatesEngine — Fail Closed)
# ══════════════════════════════════════════════════════════════════

class TestGatesEngine:
    @pytest.fixture
    def default_gates(self):
        cfg = Gates(
            max_open_positions=1,
            max_daily_trades=5,
            risk_per_trade_pct=2.0,
            max_daily_loss_pct=5.0,
            min_rr=1.5,
            min_grade="B",
            min_atr_stop_mult=1.5,
            max_spread_points=2.5,
        )
        return GatesEngine(cfg)

    @pytest.fixture
    def healthy_account(self):
        return AccountState(balance=5000.0, equity=5000.0, margin=0.0, margin_free=5000.0)

    @pytest.fixture
    def standard_plan(self):
        return Plan(
            plan_id="plan-test", symbol="XAUUSD", side=Side.BUY,
            entry_price=2050.0, stop_loss=2040.0, take_profit=2070.0,
            volume=0.0, grade=SetupGrade.A, source="analysis", rr=2.0
        )

    def test_allow_clean_setup_and_calc_volume(self, default_gates, healthy_account, standard_plan):
        # ATR=5.0, min_dist=7.5, sl_dist=10.0 (OK)
        # Risk 2% of $5000 = $100. sl_dist=10 -> volume = 100 / (10 * 100) = 0.10 lots
        res = default_gates.evaluate(
            plan=standard_plan,
            account=healthy_account,
            positions=[],
            trades_today=0,
            daily_pnl=0.0,
            atr=5.0,
            spread=0.5
        )
        assert res.allowed is True
        assert res.verdict == "ALLOW"
        assert pytest.approx(res.volume, 0.01) == 0.10

    def test_block_when_position_limit_reached(self, default_gates, healthy_account, standard_plan):
        existing_pos = BrokerPosition(
            ticket=999, symbol="XAUUSD", side=Side.BUY, volume=0.1,
            open_price=2050.0, current_price=2051.0, sl=2040.0, tp=2070.0,
            profit=10.0, swap=0.0, open_time=int(time.time()), comment="hms"
        )
        res = default_gates.evaluate(
            plan=standard_plan, account=healthy_account,
            positions=[existing_pos], trades_today=0, daily_pnl=0.0,
            atr=5.0, spread=0.5
        )
        assert res.allowed is False
        assert any("position_limit" in r for r in res.reasons)

    def test_block_when_daily_loss_hit(self, default_gates, healthy_account, standard_plan):
        # 5% of 5000 = $250. daily_pnl = -$260
        res = default_gates.evaluate(
            plan=standard_plan, account=healthy_account,
            positions=[], trades_today=2, daily_pnl=-260.0,
            atr=5.0, spread=0.5
        )
        assert res.allowed is False
        assert any("daily_loss" in r for r in res.reasons)

    def test_block_when_spread_too_high(self, default_gates, healthy_account, standard_plan):
        # Max spread is 2.5, spread is 3.2
        res = default_gates.evaluate(
            plan=standard_plan, account=healthy_account,
            positions=[], trades_today=0, daily_pnl=0.0,
            atr=5.0, spread=3.2
        )
        assert res.allowed is False
        assert any("spread" in r for r in res.reasons)

    def test_block_tight_stop_loss(self, default_gates, healthy_account):
        # ATR=10.0, min_atr_mult=1.5 -> min sl dist = 15.0
        # Plan has sl dist = 2050 - 2045 = 5.0 (too tight)
        tight_plan = Plan(
            plan_id="tight", symbol="XAUUSD", side=Side.BUY,
            entry_price=2050.0, stop_loss=2045.0, take_profit=2070.0,
            volume=0.0, grade=SetupGrade.A, source="analysis", rr=4.0
        )
        res = default_gates.evaluate(
            plan=tight_plan, account=healthy_account,
            positions=[], trades_today=0, daily_pnl=0.0,
            atr=10.0, spread=0.5
        )
        assert res.allowed is False
        assert any("stop_too_tight" in r for r in res.reasons)


# ══════════════════════════════════════════════════════════════════
# ۳. تست‌های موتور تحلیل (Engine)
# ══════════════════════════════════════════════════════════════════

class TestEngine:
    def test_pure_indicators(self):
        prices = [10.0, 11.0, 12.0, 13.0, 14.0]
        ema5 = _ema(prices, 5)
        assert ema5 > 10.0

        candles = [
            Candle(time=i * 60, open=100.0 + i, high=105.0 + i, low=95.0 + i, close=102.0 + i, volume=10)
            for i in range(20)
        ]
        atr = _atr(candles, 14)
        assert atr > 0.0

    def test_engine_analyze_structure(self):
        engine = Engine()
        candles = [
            Candle(time=i * 60, open=2000.0 + i * 2, high=2005.0 + i * 2, low=1995.0 + i * 2, close=2004.0 + i * 2, volume=100)
            for i in range(60)
        ]
        tick = Tick(symbol="XAUUSD", bid=2120.0, ask=2120.5, time=1700000000)
        view = engine.analyze(candles, tick)
        assert view.trend in ("bullish", "bearish", "ranging")
        assert view.atr > 0
        assert view.spread == 0.5


# ══════════════════════════════════════════════════════════════════
# ۴. تست‌های خروج (ExitManager)
# ══════════════════════════════════════════════════════════════════

class TestExitManager:
    def test_time_exit(self):
        cfg = PositionCfg(
            trailing_start_rr=1.5,
            breakeven_rr=0.8,
            max_hold_hours=24,
            partial_tp_rr=2.0,
            partial_enabled=False
        )
        manager = ExitManager(cfg)
        now = 1700100000.0
        # Position opened 25 hours ago
        pos = BrokerPosition(
            ticket=555, symbol="XAUUSD", side=Side.BUY, volume=0.1,
            open_price=2050.0, current_price=2052.0, sl=2040.0, tp=2070.0,
            profit=20.0, swap=0.0, open_time=int(now - 25 * 3600), comment="hms"
        )
        decision = manager.manage(pos, now_ts=now)
        assert decision is not None
        reason, price = decision
        assert reason == ExitReason.TIME_EXIT
        assert price == 2052.0

    def test_breakeven_trigger(self):
        modified = []
        def _on_modify(ticket, new_sl):
            modified.append((ticket, new_sl))

        cfg = PositionCfg(
            trailing_start_rr=1.5,
            breakeven_rr=0.8,
            max_hold_hours=24,
            partial_tp_rr=2.0,
            partial_enabled=False
        )
        manager = ExitManager(cfg, on_modify=_on_modify)

        # Open=2000, SL=1990, TP=2020 (Risk=10, Reward=20). Current=2017 (Profit=17, RR progress=17/20=0.85 >= 0.8)
        pos = BrokerPosition(
            ticket=777, symbol="XAUUSD", side=Side.BUY, volume=0.1,
            open_price=2000.0, current_price=2017.0, sl=1990.0, tp=2020.0,
            profit=170.0, swap=0.0, open_time=int(time.time()), comment="hms"
        )
        decision = manager.manage(pos, now_ts=time.time())
        assert decision is None  # Does not close, modifies SL
        assert len(modified) == 1
        assert modified[0] == (777, 2000.0)  # SL moved to open_price


# ══════════════════════════════════════════════════════════════════
# ۵. تست‌های دفتر کل (Ledger / Database)
# ══════════════════════════════════════════════════════════════════

class TestLedger:
    def test_ledger_operations(self, tmp_path):
        db_path = tmp_path / "test_ledger.db"
        ledger = Ledger(db_path)

        plan = Plan(
            plan_id="p-test-db", symbol="XAUUSD", side=Side.BUY,
            entry_price=2050.0, stop_loss=2040.0, take_profit=2070.0,
            volume=0.1, grade=SetupGrade.A, source="analysis"
        )
        ledger.save_plan(plan, status="approved")

        order = Order(
            order_id="ord-1", plan_id="p-test-db", ticket=888,
            symbol="XAUUSD", side=Side.BUY, volume=0.1, price=2050.0,
            sl=2040.0, tp=2070.0, status=OrderStatus.FILLED
        )
        ledger.save_order(order)

        acc = AccountState(balance=5000.0, equity=5050.0, margin=100.0, margin_free=4950.0)
        ledger.snapshot_equity(acc)

        ledger.log_guard("ALLOW", ["ok"], "p-test-db", "BUY", "XAUUSD", 0.1)

        # Verify rows exist
        c = ledger._con.cursor()
        assert c.execute("SELECT count(*) FROM plans").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM orders").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM equity_snapshots").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM guard_log").fetchone()[0] == 1
        ledger.close()
