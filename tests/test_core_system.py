""" tests/test_core_system — تست‌های جامع و مستقل لایه هسته (core) هرمس

این تست‌ها بدون وابستگی به شبکه یا MT5 زنده، صحت کلیه موجودیت‌ها،
دروازه‌های ریسک، محاسبات موتور تحلیل، مدیریت خروج و دفتر کل دیتابیس را تضمین می‌کنند.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
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

    def test_broker_position_net_profit(self):
        """b210: سود/زیان خالص باید شامل سواپ و کمیسیون باشد."""
        pos = BrokerPosition(
            ticket=103, symbol="XAUUSD", side=Side.SELL, volume=0.05,
            open_price=2600.0, current_price=2610.0, sl=2620.0, tp=2550.0,
            profit=-50.0, swap=-2.5, commission=-3.5, open_time=1700000000,
        )
        assert pos.net_profit == -56.0

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
        # Grade A: Risk 2% of $5000 = $100. sl_dist=10 -> volume = 100 / (10 * 100) = 0.10 lots
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

    def test_dynamic_risk_sizing_by_grade(self, default_gates, healthy_account):
        # Grade B gets 50% risk (1.0% = $50). Volume should be 0.05 lots instead of 0.10
        plan_b = Plan(
            plan_id="plan-b", symbol="XAUUSD", side=Side.BUY,
            entry_price=2050.0, stop_loss=2040.0, take_profit=2070.0,
            volume=0.0, grade=SetupGrade.B, source="analysis", rr=2.0
        )
        res_b = default_gates.evaluate(plan_b, healthy_account, [], 0, 0.0, atr=5.0, spread=0.5)
        assert res_b.allowed is True
        assert pytest.approx(res_b.volume, 0.01) == 0.05

    def test_loss_cooldown_circuit_breaker(self, default_gates, healthy_account, standard_plan):
        now = time.time()
        # Loss was 10 minutes ago (within 45m cooldown)
        res = default_gates.evaluate(
            standard_plan, healthy_account, [], 0, 0.0, atr=5.0, spread=0.5,
            last_loss_ts=now - 600, now_ts=now
        )
        assert res.allowed is False
        assert any("loss_cooldown" in r for r in res.reasons)

        # Loss was 60 minutes ago (cooldown expired)
        res_ok = default_gates.evaluate(
            standard_plan, healthy_account, [], 0, 0.0, atr=5.0, spread=0.5,
            last_loss_ts=now - 3600, now_ts=now
        )
        assert res_ok.allowed is True

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

    def test_b221_dark_bridge_positions_none(self, default_gates, healthy_account, standard_plan):
        res = default_gates.evaluate(
            plan=standard_plan, account=healthy_account,
            positions=None, trades_today=0, daily_pnl=0.0,
            atr=5.0, spread=0.5
        )
        assert res.allowed is False
        assert "positions_unreadable" in res.reasons

    def test_b221_dark_bridge_account_none(self, default_gates, standard_plan):
        res = default_gates.evaluate(
            plan=standard_plan, account=None,
            positions=[], trades_today=0, daily_pnl=0.0,
            atr=5.0, spread=0.5
        )
        assert res.allowed is False
        assert "equity_invalid" in res.reasons

    def test_b225_gates_rejects_inverted_stops_buy(self, default_gates, healthy_account):
        """b225: استاپ‌های معکوس یا اشتباه در خرید (SL>=Entry یا TP<=Entry) مسدود می‌شوند."""
        # SL بالاتر از قیمت ورود
        bad_sl_plan = Plan(
            plan_id="p-inv-sl", symbol="XAUUSD", side=Side.BUY,
            entry_price=2050.0, stop_loss=2060.0, take_profit=2070.0,
            volume=0.0, grade=SetupGrade.A, source="analysis", rr=2.0
        )
        res = default_gates.evaluate(bad_sl_plan, healthy_account, [], 0, 0.0, atr=5.0, spread=0.5)
        assert res.allowed is False
        assert "invalid_stops" in res.reasons

        # TP پایین‌تر از قیمت ورود در خرید
        bad_tp_plan = Plan(
            plan_id="p-inv-tp", symbol="XAUUSD", side=Side.BUY,
            entry_price=2050.0, stop_loss=2040.0, take_profit=2030.0,
            volume=0.0, grade=SetupGrade.A, source="analysis", rr=2.0
        )
        res2 = default_gates.evaluate(bad_tp_plan, healthy_account, [], 0, 0.0, atr=5.0, spread=0.5)
        assert res2.allowed is False
        assert "invalid_stops" in res2.reasons

    def test_b225_gates_rejects_inverted_stops_sell(self, default_gates, healthy_account):
        """b225: استاپ‌های معکوس یا اشتباه در فروش (SL<=Entry یا TP>=Entry) مسدود می‌شوند."""
        bad_sell_plan = Plan(
            plan_id="p-inv-sell", symbol="XAUUSD", side=Side.SELL,
            entry_price=2050.0, stop_loss=2040.0, take_profit=2030.0,
            volume=0.0, grade=SetupGrade.A, source="analysis", rr=2.0
        )
        res = default_gates.evaluate(bad_sell_plan, healthy_account, [], 0, 0.0, atr=5.0, spread=0.5)
        assert res.allowed is False
        assert "invalid_stops" in res.reasons


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
        assert 0.0 <= view.rsi <= 100.0

    def test_rsi_and_divergence_detection(self):
        from core.engine import _rsi_series, detect_rsi_divergence
        closes = [100.0 + i for i in range(40)]
        rsi = _rsi_series(closes, period=14)
        assert len(rsi) == 40
        assert rsi[-1] > 70.0  # Strong uptrend

        highs = [100.0] * 35
        lows = [90.0] * 35
        # Regular bearish divergence: Higher High in price, Lower High in RSI
        highs[9], highs[10], highs[11] = 98.0, 105.0, 98.0
        highs[24], highs[25], highs[26] = 99.0, 110.0, 99.0
        rsi_test = [50.0] * 35
        rsi_test[10], rsi_test[25] = 65.0, 58.0
        div_type, strg = detect_rsi_divergence(highs, lows, rsi_test, window=30)
        assert div_type == "BEARISH_REGULAR"
        assert strg > 0


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

        # Open=2000, SL=1990, TP=2020 (Risk=10, Reward=20). Current=2010 (Profit=10, r_mult=1.0R >= 0.8 BE, < 1.5 Trail)
        pos = BrokerPosition(
            ticket=777, symbol="XAUUSD", side=Side.BUY, volume=0.1,
            open_price=2000.0, current_price=2010.0, sl=1990.0, tp=2020.0,
            profit=100.0, swap=0.0, open_time=int(time.time()), comment="hms"
        )
        decision = manager.manage(pos, now_ts=time.time())
        assert decision is None  # Does not close, modifies SL
        assert len(modified) == 1
        assert modified[0] == (777, 2000.15)  # SL moved to open_price + 0.15 buffer

    def test_trailing_stop_with_tp_trigger(self):
        """b223: ترلینگ استاپ برای پلن‌های دارای TP باید بر مبنای r_multiple فعال شود."""
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

        # BUY: Open=2000, SL=1990, TP=2020 (Risk=10). Current=2017 (r_mult=1.7 >= 1.5 trailing_start_rr)
        pos = BrokerPosition(
            ticket=777, symbol="XAUUSD", side=Side.BUY, volume=0.1,
            open_price=2000.0, current_price=2017.0, sl=1990.0, tp=2020.0,
            profit=170.0, swap=0.0, open_time=int(time.time()), comment="hms"
        )
        decision = manager.manage(pos, now_ts=time.time())
        assert decision is None
        assert len(modified) == 1
        # dist = (2020 - 2017) * 0.5 = 1.5 -> new_sl = 2017 - 1.5 = 2015.5
        assert modified[0] == (777, 2015.5)

    def test_trailing_stop_ratchet_tightens_only(self):
        """b223: استاپ ترلینگ هرگز در پولبک‌ها به عقب برنمی‌گردد."""
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

        # SL is already tight at 2016.0. Price drops to 2017 -> candidate new_sl=2015.5 <= 2016.0
        pos = BrokerPosition(
            ticket=777, symbol="XAUUSD", side=Side.BUY, volume=0.1,
            open_price=2000.0, current_price=2017.0, sl=2016.0, tp=2020.0,
            profit=170.0, swap=0.0, open_time=int(time.time()), comment="hms"
        )
        decision = manager.manage(pos, now_ts=time.time())
        assert decision is None
        assert len(modified) == 0  # No modification because new_sl would loosen

    def test_partial_close_with_tp_trigger(self):
        """b223: سیو سود پله‌ای برای پلن‌های دارای TP بر مبنای r_multiple واقعی اجرا می‌شود."""
        partials = []
        modifies = []
        def _on_partial(ticket, pct):
            partials.append((ticket, pct))
        def _on_modify(ticket, new_sl):
            modifies.append((ticket, new_sl))

        cfg = PositionCfg(
            trailing_start_rr=1.8,
            breakeven_rr=0.8,
            max_hold_hours=24,
            partial_tp_rr=1.5,
            partial_enabled=True
        )
        manager = ExitManager(cfg, on_modify=_on_modify, on_partial=_on_partial)

        # BUY: Open=2000, SL=1990, TP=2030 (Risk=10). Current=2015 -> r_mult=1.5 >= partial_tp_rr (1.5)
        pos = BrokerPosition(
            ticket=999, symbol="XAUUSD", side=Side.BUY, volume=0.2,
            open_price=2000.0, current_price=2015.0, sl=1990.0, tp=2030.0,
            profit=300.0, swap=0.0, open_time=int(time.time()), comment="sig"
        )
        decision = manager.manage(pos, now_ts=time.time())
        assert decision is None
        assert len(partials) == 1
        assert partials[0] == (999, 50.0)
        # Breakeven applied after partial close
        assert len(modifies) == 1
        assert modifies[0] == (999, 2000.15)

    def test_partial_close_trigger(self):
        partials = []
        def _on_partial(ticket, pct):
            partials.append((ticket, pct))

        cfg = PositionCfg(
            trailing_start_rr=1.5,
            breakeven_rr=0.8,
            max_hold_hours=24,
            partial_tp_rr=1.5,
            partial_enabled=True
        )
        manager = ExitManager(cfg, on_partial=_on_partial)

        # Auto-analysis position without TP (tp=0), ATR=5.0, sl_mult=1.5 -> sl_dist=7.5
        # Open=2000, Current=2012 -> profit=+12.0 points. r_achieved = 12.0 / 7.5 = 1.6R >= 1.5R
        pos = BrokerPosition(
            ticket=888, symbol="XAUUSD", side=Side.BUY, volume=0.2,
            open_price=2000.0, current_price=2012.0, sl=1992.5, tp=0.0,
            profit=240.0, swap=0.0, open_time=int(time.time()), comment="hms-auto"
        )
        decision = manager.manage(pos, now_ts=time.time(), atr=5.0, atr_sl_mult=1.5)
        assert decision is None
        assert len(partials) == 1
        assert partials[0] == (888, 50.0)

        # Should not fire a second time for same ticket
        manager.manage(pos, now_ts=time.time(), atr=5.0, atr_sl_mult=1.5)
        assert len(partials) == 1

    def test_b225_dynamic_atr_trail_breakeven_stage_single_modify(self):
        """b225: در پوزیشن بدون TP، در مرحله breakeven_rr تا trailing_start_rr فقط یکبار BE ارسال می‌شود و با استاپ ضررده بازنویسی نمی‌شود."""
        modifies = []
        def _on_modify(ticket, new_sl):
            modifies.append((ticket, new_sl))

        cfg = PositionCfg(
            trailing_start_rr=1.5,
            breakeven_rr=0.8,
            max_hold_hours=24,
            partial_tp_rr=2.0,
            partial_enabled=False
        )
        manager = ExitManager(cfg, on_modify=_on_modify)

        # BUY: Open=2000, initial SL=1985 (ATR=10, 1.5*ATR=15). Current=2010 -> r_achieved = 10/15 = 0.67 < 0.8
        pos = BrokerPosition(
            ticket=101, symbol="XAUUSD", side=Side.BUY, volume=0.1,
            open_price=2000.0, current_price=2010.0, sl=1985.0, tp=0.0,
            profit=100.0, swap=0.0, open_time=int(time.time()), comment="auto"
        )
        manager.manage(pos, now_ts=time.time(), atr=10.0, atr_sl_mult=1.5)
        assert len(modifies) == 0  # زیر 0.8R هنوز تغییری اعمال نمی‌شود

        # قیمت به 2015 می‌رسد -> r_achieved = 15/15 = 1.0R (بین 0.8 و 1.5)
        pos_be = BrokerPosition(
            ticket=101, symbol="XAUUSD", side=Side.BUY, volume=0.1,
            open_price=2000.0, current_price=2015.0, sl=1985.0, tp=0.0,
            profit=150.0, swap=0.0, open_time=int(time.time()), comment="auto"
        )
        manager.manage(pos_be, now_ts=time.time(), atr=10.0, atr_sl_mult=1.5)
        # فقط یکبار modify فراخوانی می‌شود و آن هم دقیقاً Breakeven + buffer (2000.15) است
        assert len(modifies) == 1
        assert modifies[0] == (101, 2000.15)

    def test_b225_dynamic_atr_trail_ratchet_never_below_breakeven_buy(self):
        """b225: ترلینگ داینامیک ATR در پوزیشن خرید هرگز نباید پایین‌تر از Breakeven+buffer استاپ بگذارد."""
        modifies = []
        def _on_modify(ticket, new_sl):
            modifies.append((ticket, new_sl))

        cfg = PositionCfg(
            trailing_start_rr=1.5,
            breakeven_rr=0.8,
            max_hold_hours=24,
            partial_tp_rr=2.0,
            partial_enabled=False
        )
        manager = ExitManager(cfg, on_modify=_on_modify)

        # BUY: Open=2000, initial SL=1985 (ATR=10, 1.5*ATR=15). Current=2024 -> r_achieved = 24/15 = 1.6R >= 1.5R
        # با ATR=10، فاصله ترلینگ مرحله ۲ = 2.0*10 = 20. new_sl = 2024 - 20 = 2004.0 > 2000.15
        pos_trail = BrokerPosition(
            ticket=102, symbol="XAUUSD", side=Side.BUY, volume=0.1,
            open_price=2000.0, current_price=2024.0, sl=2000.15, tp=0.0,
            profit=240.0, swap=0.0, open_time=int(time.time()), comment="auto"
        )
        manager.manage(pos_trail, now_ts=time.time(), atr=10.0, atr_sl_mult=1.5)
        assert len(modifies) == 1
        assert modifies[0] == (102, 2004.0)

        # اگر ATR جهش کند (مثلاً ATR=15 -> فاصله ترلینگ 30.0 -> new_sl = 2024 - 30 = 1994 < 2000.15)
        # راچت مانع افتادن زیر Breakeven شده و آن را به 2000.15 کلمپ می‌کند، اما چون sl قبلی 2004 بود شل نمی‌کند
        modifies.clear()
        pos_wide_atr = BrokerPosition(
            ticket=102, symbol="XAUUSD", side=Side.BUY, volume=0.1,
            open_price=2000.0, current_price=2024.0, sl=2004.0, tp=0.0,
            profit=240.0, swap=0.0, open_time=int(time.time()), comment="auto"
        )
        manager.manage(pos_wide_atr, now_ts=time.time(), atr=15.0, atr_sl_mult=1.5)
        assert len(modifies) == 0  # استاپ نباید شل شود

    def test_b225_dynamic_atr_trail_ratchet_sell(self):
        """b225: ترلینگ داینامیک ATR در پوزیشن فروش استاپ را بالاتر از Breakeven-buffer نمی‌برد و راچت حفظ می‌شود."""
        modifies = []
        def _on_modify(ticket, new_sl):
            modifies.append((ticket, new_sl))

        cfg = PositionCfg(
            trailing_start_rr=1.5,
            breakeven_rr=0.8,
            max_hold_hours=24,
            partial_tp_rr=2.0,
            partial_enabled=False
        )
        manager = ExitManager(cfg, on_modify=_on_modify)

        # SELL: Open=2000, initial SL=2015 (ATR=10, 1.5*ATR=15). Current=1985 -> r_achieved = 1.0R (BE zone)
        pos_be = BrokerPosition(
            ticket=103, symbol="XAUUSD", side=Side.SELL, volume=0.1,
            open_price=2000.0, current_price=1985.0, sl=2015.0, tp=0.0,
            profit=150.0, swap=0.0, open_time=int(time.time()), comment="auto"
        )
        manager.manage(pos_be, now_ts=time.time(), atr=10.0, atr_sl_mult=1.5)
        assert len(modifies) == 1
        assert modifies[0] == (103, 1999.85)

        # مرحله ۳ سود (r_achieved >= 3.0R): Current=1950 -> r_achieved = 50/15 = 3.33R
        # با ATR=10، فاصله ترلینگ مرحله ۳ = 1.5*10 = 15.0. new_sl = 1950 + 15 = 1965.0 < 1999.85
        modifies.clear()
        pos_stage3 = BrokerPosition(
            ticket=103, symbol="XAUUSD", side=Side.SELL, volume=0.1,
            open_price=2000.0, current_price=1950.0, sl=1999.85, tp=0.0,
            profit=500.0, swap=0.0, open_time=int(time.time()), comment="auto"
        )
        manager.manage(pos_stage3, now_ts=time.time(), atr=10.0, atr_sl_mult=1.5)
        assert len(modifies) == 1
        assert modifies[0] == (103, 1965.0)


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


# ══════════════════════════════════════════════════════════════════
# ۶. تست‌های فیلتر اخبار داغ (NewsGuard)
# ══════════════════════════════════════════════════════════════════

class TestNewsGuard:
    def test_news_blackout_timing(self, tmp_path):
        from core.news import NewsGuard, EconomicEvent
        cache_file = tmp_path / "mock_calendar.json"
        
        guard = NewsGuard(cache_file=cache_file)
        now = time.time()

        # Add mock high-impact event in 15 minutes
        ev_soon = EconomicEvent(
            title="Fed Chair Powell Speaks",
            currency="USD",
            impact="High",
            timestamp=int(now + 15 * 60)
        )
        guard._events = [ev_soon]

        # Should be blocked because it's within 30 minutes
        blocked, reason = guard.is_blackout(now_ts=now, before_minutes=30)
        assert blocked is True
        assert "Powell" in reason

        # Should not be blocked if event is 3 hours away
        ev_far = EconomicEvent(
            title="CPI m/m",
            currency="USD",
            impact="High",
            timestamp=int(now + 180 * 60)
        )
        guard._events = [ev_far]
        blocked2, _ = guard.is_blackout(now_ts=now, before_minutes=30)
        assert blocked2 is False


# ══════════════════════════════════════════════════════════════════
# ۷. تست‌های ماژول ساختار هوشمند (SMCAnalyzer)
# ══════════════════════════════════════════════════════════════════

class TestSMCAnalyzer:
    def test_smc_killzones(self):
        from core.smc import SMCAnalyzer
        from datetime import datetime, timezone
        
        analyzer = SMCAnalyzer()
        # 08:30 UTC -> London
        dt_london = datetime(2026, 10, 28, 8, 30, tzinfo=timezone.utc)
        assert analyzer.detect_killzone(dt_london) == "london"

        # 13:30 UTC -> New York
        dt_ny = datetime(2026, 10, 28, 13, 30, tzinfo=timezone.utc)
        assert analyzer.detect_killzone(dt_ny) == "newyork"

        # 21:00 UTC -> Dead
        dt_dead = datetime(2026, 10, 28, 21, 0, tzinfo=timezone.utc)
        assert analyzer.detect_killzone(dt_dead) == "dead"

    def test_smc_order_block_and_fvg(self):
        from core.smc import SMCAnalyzer
        analyzer = SMCAnalyzer()
        # Build 10 candles with a clear bullish expansion creating FVG
        candles = [
            Candle(time=i*900, open=2000.0, high=2002.0, low=1998.0, close=1999.0, volume=100)
            for i in range(5)
        ]
        # Strong impulsive up move at candle 5 & 6
        candles.append(Candle(time=5*900, open=1999.0, high=2020.0, low=1998.0, close=2018.0, volume=500))
        candles.append(Candle(time=6*900, open=2018.0, high=2035.0, low=2015.0, close=2032.0, volume=600))
        candles.append(Candle(time=7*900, open=2032.0, high=2038.0, low=2030.0, close=2036.0, volume=300))

        obs = analyzer.detect_order_blocks(candles)
        assert len(obs) > 0
        fvgs = analyzer.detect_fvgs(candles)
        assert len(fvgs) > 0

    def test_smc_premium_discount(self):
        from core.smc import SMCAnalyzer, ZoneType
        analyzer = SMCAnalyzer()
        candles = [
            Candle(time=i*900, open=2000.0, high=2050.0, low=1950.0, close=1960.0, volume=100)
            for i in range(25)
        ]
        zone, fib, high, low = analyzer.detect_premium_discount(candles)
        assert high == 2050.0
        assert low == 1950.0
        # price 1960 is in DISCOUNT (fib = 0.10)
        assert zone == ZoneType.DISCOUNT
        assert fib < 0.20


# ══════════════════════════════════════════════════════════════════
# ۸. تست‌های موتور جامع (Engine Hybrid)
# ══════════════════════════════════════════════════════════════════

class TestEngineHybrid:
    def test_engine_rejects_plan_during_news_blackout(self):
        from core.news import NewsGuard, EconomicEvent
        news_guard = NewsGuard()
        now = time.time()
        # Set high-impact event in 5 mins
        news_guard._events = [EconomicEvent(
            title="Non-Farm Payrolls", currency="USD", impact="High", timestamp=int(now + 300)
        )]
        engine = Engine(news_guard=news_guard)

        candles = [
            Candle(time=int(now - (60-i)*900), open=2000.0+i, high=2002.0+i, low=1998.0+i, close=2001.0+i, volume=100)
            for i in range(65)
        ]
        tick = Tick(symbol="XAUUSD", bid=2065.0, ask=2065.3, time=int(now))
        view = engine.analyze(candles, tick, check_news=True)
        assert view.news_blackout is True

        plan = engine.plan_from_analysis(candles, view)
        assert plan is None  # Blocked by news blackout!


# ══════════════════════════════════════════════════════════════════
# ۹. تست‌های یادگیری تطبیقی (AdaptiveLearner)
# ══════════════════════════════════════════════════════════════════

class TestAdaptiveLearner:
    def test_metrics_calculation(self):
        from core.learning import AdaptiveLearner
        from core.entities import Trade, Side, ExitReason, SetupGrade
        learner = AdaptiveLearner(min_trades=5)

        trades = [
            Trade(
                trade_id=f"t-{i}", plan_id=f"p-{i}", ticket=i, symbol="XAUUSD",
                side=Side.BUY, volume=0.1, entry_price=2000.0, exit_price=2010.0 if i % 2 == 0 else 1995.0,
                sl=1990.0, tp=2020.0, pnl=100.0 if i % 2 == 0 else -50.0,
                exit_reason=ExitReason.TAKE_PROFIT if i % 2 == 0 else ExitReason.STOP_LOSS,
                opened_at=1700000000, closed_at=1700001000 + i, grade=SetupGrade.A, r_multiple=1.0 if i % 2 == 0 else -0.5
            )
            for i in range(10)
        ]
        metrics = learner.evaluate_performance(trades)
        assert metrics.total_trades == 10
        assert metrics.wins == 5
        assert metrics.losses == 5
        assert metrics.win_rate == 50.0
        assert metrics.profit_factor == 2.0  # 500 / 250 = 2.0

    def test_adapt_tightens_on_loss_streak(self, tmp_path):
        from core.learning import AdaptiveLearner
        from core.db import Ledger
        from core.entities import Trade, Side, ExitReason, SetupGrade

        db_path = tmp_path / "learn_test.db"
        ledger = Ledger(db_path)
        learner = AdaptiveLearner(min_trades=5, floor_rr=1.0, floor_grade="B")

        # Insert 5 losing trades
        for i in range(5):
            t = Trade(
                trade_id=f"loss-{i}", plan_id=f"p-{i}", ticket=100 + i, symbol="XAUUSD",
                side=Side.BUY, volume=0.1, entry_price=2000.0, exit_price=1990.0,
                sl=1990.0, tp=2020.0, pnl=-100.0, exit_reason=ExitReason.STOP_LOSS,
                opened_at=1700000000, closed_at=1700001000 + i, grade=SetupGrade.B, r_multiple=-1.0
            )
            ledger.save_trade(t)

        res = learner.adapt(ledger)
        assert res["adapted"] is True
        assert res["min_rr"] == 1.5
        assert res["min_grade"] == "A"
        assert ledger.get_param("min_grade") == "A"
        ledger.close()


# ══════════════════════════════════════════════════════════════════
# ۱۰. تست‌های واچ‌لیست و انتظار برای پولبک (Watchlist Engine)
# ══════════════════════════════════════════════════════════════════

class TestWatchlistEngine:
    def test_watchlist_db_lifecycle(self, tmp_path):
        from core.db import Ledger
        db_path = tmp_path / "wl_test.db"
        ledger = Ledger(db_path)
        now = time.time()

        item = {
            "item_id": "wl-101",
            "signal_id": "sig-101",
            "symbol": "XAUUSD",
            "side": "BUY",
            "entry_price": 2050.0,
            "trigger_price": 2050.0,
            "sl": 2040.0,
            "tp": 2070.0,
            "added_at": now,
            "expires_at": now + 3600.0,
            "status": "waiting",
            "reason": "منتظر پولبک",
        }
        ledger.add_to_watchlist(item)

        active = ledger.get_active_watchlist("XAUUSD")
        assert len(active) == 1
        assert active[0]["item_id"] == "wl-101"

        # Update status
        ledger.update_watchlist_status("wl-101", "executed")
        assert len(ledger.get_active_watchlist("XAUUSD")) == 0

        # Prune expired
        item_expired = {
            "item_id": "wl-102", "signal_id": "sig-102", "symbol": "XAUUSD",
            "side": "SELL", "entry_price": 2060.0, "trigger_price": 2060.0,
            "sl": 2070.0, "tp": 2040.0, "added_at": now - 7200, "expires_at": now - 100,
            "status": "waiting", "reason": "قدیمی",
        }
        ledger.add_to_watchlist(item_expired)
        pruned = ledger.prune_expired_watchlist(now)
        assert pruned == 1
        ledger.close()

    def test_evaluate_signal_states(self):
        from core.engine import Engine, MarketView
        from core.entities import Signal, Side, Tick
        engine = Engine()
        view = MarketView(
            trend="bullish", trend_strength=0.7, atr=5.0, spread=0.5,
            last_price=2050.0, support=2000.0, resistance=2100.0
        )

        # 1. Immediate Execution (price is right at entry 2050)
        sig_near = Signal(
            signal_id="s1", raw_text="BUY 2050", symbol="XAUUSD", side=Side.BUY,
            entry=2050.0, sl=2040.0, tp=2070.0, rr=2.0, confidence=0.85, timestamp="2026-10-28T12:00:00Z"
        )
        tick_near = Tick(symbol="XAUUSD", bid=2050.0, ask=2050.3, time=1700000000)
        dec1, plan1, _ = engine.evaluate_signal(sig_near, view, tick_near)
        assert dec1 == "EXECUTE"
        assert plan1 is not None

        # 2. Watchlist (price has run away to 2055, wait for pullback to 2050)
        tick_far = Tick(symbol="XAUUSD", bid=2055.0, ask=2055.3, time=1700000000)
        dec2, plan2, wl_item = engine.evaluate_signal(sig_near, view, tick_far)
        assert dec2 == "WATCHLIST"
        assert plan2 is None
        assert wl_item is not None
        assert "پولبک" in wl_item["reason"]

        # 3. Reject (Counter-trend BUY in a Bearish market)
        view_bear = MarketView(
            trend="bearish", trend_strength=0.8, atr=5.0, spread=0.5,
            last_price=2050.0, support=2000.0, resistance=2100.0
        )
        dec3, _, _ = engine.evaluate_signal(sig_near, view_bear, tick_near)
        assert dec3 == "REJECT"

    def test_b225_evaluate_signal_boundary_rejects(self):
        """b225: اگر قیمت زنده قبلاً استاپ یا تارگت سیگنال را رد کرده باشد، بلافاصله رد می‌شود."""
        from core.engine import Engine, MarketView
        from core.entities import Signal, Side, Tick
        engine = Engine()
        view = MarketView(
            trend="bullish", trend_strength=0.2, atr=5.0, spread=0.5,
            last_price=2050.0, support=2000.0, resistance=2100.0
        )
        # سیگنال خرید: entry=2050, sl=2040, tp=2070
        sig_buy = Signal(
            signal_id="sig-bound-1", raw_text="", symbol="XAUUSD", side=Side.BUY,
            entry=2050.0, sl=2040.0, tp=2070.0, rr=2.0, confidence=0.8,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        # قیمت به زیر استاپ رسیده (2038 <= 2040)
        tick_sl_hit = Tick(symbol="XAUUSD", bid=2038.0, ask=2038.5, time=int(time.time()))
        dec_sl, plan_sl, _ = engine.evaluate_signal(sig_buy, view, tick_sl_hit)
        assert dec_sl == "REJECT"
        assert plan_sl is None

        # قیمت به بالای تارگت رسیده (2072 >= 2070)
        tick_tp_hit = Tick(symbol="XAUUSD", bid=2072.0, ask=2072.5, time=int(time.time()))
        dec_tp, plan_tp, _ = engine.evaluate_signal(sig_buy, view, tick_tp_hit)
        assert dec_tp == "REJECT"
        assert plan_tp is None

    def test_b227_backtester_simulates_partial_take_profit(self):
        """b227: Backtester correctly halves open volume, realizes PnL, and records PARTIAL_TP."""
        from entry.backtest import Backtester, OpenTrade
        from core.entities import Side, ExitReason
        bt = Backtester()
        bt._open = OpenTrade(
            ticket=555,
            symbol="XAUUSD",
            side=Side.BUY,
            volume=0.10,
            open_price=2000.0,
            sl=1990.0,
            tp=2030.0,
            open_time=1700000000.0,
            plan_id="p-bt-1",
            entry_rr=2.0,
            initial_sl=1990.0,
        )
        bt._cur_candle_close = 2015.0
        bt._cur_candle_ts = 1700000500.0
        initial_balance = bt.state.balance

        # Trigger partial close for 50%
        bt._sim_partial(ticket=555, percent=50.0)

        # 1. Open volume halved from 0.10 to 0.05
        assert bt._open.volume == 0.05
        # 2. Realized PnL: (2015 - 2000) * 0.05 * 100 = 75.0
        expected_pnl = (2015.0 - 2000.0) * 0.05 * 100.0
        assert bt.state.balance == initial_balance + expected_pnl
        # 3. Trade recorded with ExitReason.PARTIAL_TP
        assert len(bt.trades) == 1
        t = bt.trades[0]
        assert t.exit_reason == ExitReason.PARTIAL_TP
        assert t.volume == 0.05
        assert t.pnl == expected_pnl

    def test_b231_backtester_propagates_plan_grade(self):
        """b231: Backtester preserves Plan SetupGrade on OpenTrade and outputs grade in summary."""
        from entry.backtest import Backtester, OpenTrade
        from core.entities import Side, SetupGrade, Candle, ExitReason
        bt = Backtester()
        bt._open = OpenTrade(
            ticket=666,
            symbol="XAUUSD",
            side=Side.BUY,
            volume=0.10,
            open_price=2000.0,
            sl=1990.0,
            tp=2030.0,
            open_time=1700000000.0,
            plan_id="p-bt-grade",
            entry_rr=3.0,
            initial_sl=1990.0,
            grade=SetupGrade.A,
        )
        cur = Candle(time=1700000500, open=2000.0, high=2035.0, low=2000.0, close=2032.0, volume=100)
        candles = [cur]
        closed = bt._process_exit(candles, 0, 1700000500.0)
        assert closed is True
        assert len(bt.trades) == 1
        trade = bt.trades[0]
        assert trade.grade == SetupGrade.A
        assert trade.exit_reason == ExitReason.TAKE_PROFIT
        assert trade.r_multiple == 3.0

        summary = bt._summary()
        assert len(summary["trades"]) == 1
        assert summary["trades"][0]["grade"] == "A"

    def test_b233_adaptive_learner_consecutive_losses_recent_order(self):
        """b233: AdaptiveLearner counts consecutive losses from newest to oldest trade."""
        from core.learning import AdaptiveLearner
        from core.entities import Trade, Side, ExitReason, SetupGrade

        learner = AdaptiveLearner(min_trades=4)
        # Trades ordered as returned by Ledger.get_trades (closed_at DESC)
        trades = [
            # Latest trade (loss)
            Trade("t4", "p4", 4, "XAUUSD", Side.BUY, 0.1, 2000, 1990, 1990, 2020, -100.0, ExitReason.STOP_LOSS, 1700000000, 1700004000, SetupGrade.A),
            # 2nd latest (loss)
            Trade("t3", "p3", 3, "XAUUSD", Side.BUY, 0.1, 2000, 1990, 1990, 2020, -100.0, ExitReason.STOP_LOSS, 1700000000, 1700003000, SetupGrade.A),
            # 3rd latest (loss)
            Trade("t2", "p2", 2, "XAUUSD", Side.BUY, 0.1, 2000, 1990, 1990, 2020, -100.0, ExitReason.STOP_LOSS, 1700000000, 1700002000, SetupGrade.A),
            # Oldest trade (win)
            Trade("t1", "p1", 1, "XAUUSD", Side.BUY, 0.1, 2000, 2020, 1990, 2020, 200.0, ExitReason.TAKE_PROFIT, 1700000000, 1700001000, SetupGrade.A),
        ]
        metrics = learner.evaluate_performance(trades)
        assert metrics.consecutive_losses == 3

        # Winning sequence with old losses
        trades_win = [
            # Latest trade (win)
            Trade("t4", "p4", 4, "XAUUSD", Side.BUY, 0.1, 2000, 2020, 1990, 2020, 200.0, ExitReason.TAKE_PROFIT, 1700000000, 1700004000, SetupGrade.A),
            # 2nd latest (win)
            Trade("t3", "p3", 3, "XAUUSD", Side.BUY, 0.1, 2000, 2020, 1990, 2020, 200.0, ExitReason.TAKE_PROFIT, 1700000000, 1700003000, SetupGrade.A),
            # Oldest trade (loss)
            Trade("t1", "p1", 1, "XAUUSD", Side.BUY, 0.1, 2000, 1990, 1990, 2020, -100.0, ExitReason.STOP_LOSS, 1700000000, 1700001000, SetupGrade.A),
        ]
        metrics_win = learner.evaluate_performance(trades_win)
        assert metrics_win.consecutive_losses == 0

    def test_b233_calc_rr_zero_tp_returns_zero(self):
        """b233: _calc_rr returns 0.0 when tp <= 0 instead of asset-price artifact."""
        from core.entities import Signal, Side
        from core.engine import _calc_rr

        sig = Signal(
            signal_id="sig-notp",
            raw_text="BUY GOLD 2700 SL 2690",
            symbol="XAUUSD",
            side=Side.BUY,
            entry=2700.0,
            sl=2690.0,
            tp=0.0,
            rr=0.0,
            confidence=0.8,
            timestamp="2026-10-29T00:00:00Z",
        )
        assert _calc_rr(sig) == 0.0

    def test_b233_backtester_enforces_session_hours_for_auto_analysis(self):
        """b233: Backtester blocks automated analysis outside analysis.session_hours."""
        from entry.backtest import Backtester
        from core.entities import Candle

        bt = Backtester()
        # Create 100 bullish candles at 22:30 UTC (outside [0, 22))
        # 1700000000 = 2023-11-14 22:13:20 UTC
        ts_22utc = 1700000000  # hour 22 UTC
        bars = []
        price = 2000.0
        for i in range(120):
            bars.append({
                "time": ts_22utc + i * 900,
                "open": price + i * 0.5,
                "high": price + i * 0.5 + 2.0,
                "low": price + i * 0.5 - 1.0,
                "close": price + i * 0.5 + 1.0,
                "tick_volume": 100,
            })
        summary = bt.run(bars, signals=[])
        # Since all candles are outside [0, 22), no auto-analysis trades should execute
        assert summary["total_trades"] == 0




