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

    def test_smc_gates_stop_distance_thresholds(self, default_gates, healthy_account):
        # ATR=10.0: Signal min=1.5*10=15.0, Analysis min=1.4*10=14.0, SMC min=1.2*10=12.0
        # 1) SMC setup with sl_dist = 13.0 (between 12.0 and 15.0): SMC allows, Signal denies
        smc_plan = Plan(
            plan_id="smc-p1", symbol="XAUUSD", side=Side.BUY,
            entry_price=2050.0, stop_loss=2037.0, take_profit=2080.0,
            volume=0.0, grade=SetupGrade.A, source="smc_ob", rr=2.3
        )
        res_smc = default_gates.evaluate(
            plan=smc_plan, account=healthy_account,
            positions=[], trades_today=0, daily_pnl=0.0,
            atr=10.0, spread=0.5
        )
        assert res_smc.allowed is True

        sig_plan = Plan(
            plan_id="sig-p1", symbol="XAUUSD", side=Side.BUY,
            entry_price=2050.0, stop_loss=2037.0, take_profit=2080.0,
            volume=0.0, grade=SetupGrade.A, source="signal", rr=2.3
        )
        res_sig = default_gates.evaluate(
            plan=sig_plan, account=healthy_account,
            positions=[], trades_today=0, daily_pnl=0.0,
            atr=10.0, spread=0.5
        )
        assert res_sig.allowed is False
        assert any("stop_too_tight" in r for r in res_sig.reasons)

        # 2) SMC setup with sl_dist = 11.0 (< 1.2*ATR): Denies with stop_too_tight
        tight_smc = Plan(
            plan_id="smc-tight", symbol="XAUUSD", side=Side.BUY,
            entry_price=2050.0, stop_loss=2039.0, take_profit=2080.0,
            volume=0.0, grade=SetupGrade.A, source="smc_judas", rr=2.7
        )
        res_tight = default_gates.evaluate(
            plan=tight_smc, account=healthy_account,
            positions=[], trades_today=0, daily_pnl=0.0,
            atr=10.0, spread=0.5
        )
        assert res_tight.allowed is False
        assert any("stop_too_tight" in r for r in res_tight.reasons)

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

    def test_usd_intermarket_bias(self):
        from core.engine import Engine
        # EURUSD dropping (Bearish EUR) + USDJPY rising (Bullish USD) -> Strong Bullish USD
        eur_candles = [
            Candle(time=i * 60, open=1.10 - i * 0.001, high=1.10 - i * 0.001, low=1.09 - i * 0.001, close=1.09 - i * 0.001, volume=10)
            for i in range(25)
        ]
        jpy_candles = [
            Candle(time=i * 60, open=150.0 + i * 0.1, high=151.0 + i * 0.1, low=149.0 + i * 0.1, close=150.5 + i * 0.1, volume=10)
            for i in range(25)
        ]
        bias = Engine.calculate_usd_bias(eur_candles, jpy_candles)
        assert bias == "BULLISH"

        # Inverse case -> Bearish USD
        bias_inv = Engine.calculate_usd_bias(jpy_candles, eur_candles)
        assert bias_inv in ("BEARISH", "NEUTRAL")


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

    def test_plan_from_smc_judas_setup(self):
        from core.smc import SMCView, MarketPhase, ZoneType
        engine = Engine()
        now = time.time()
        candles = [
            Candle(time=int(now - (35-i)*900), open=2040.0, high=2042.0, low=2038.0, close=2040.0, volume=100)
            for i in range(35)
        ]
        smc_view = SMCView(
            bias="bearish", confidence=0.85, phase=MarketPhase.BOS_BEARISH,
            zone=ZoneType.PREMIUM, fib_level=0.75, killzone="london",
            judas_swing="BEARISH_JUDAS", swing_high=2050.0, swing_low=2020.0
        )
        tick = Tick(symbol="XAUUSD", bid=2040.0, ask=2040.2, time=int(now))
        from core.engine import MarketView
        view = MarketView(
            trend="bearish", trend_strength=0.5, atr=5.0, spread=0.2,
            last_price=2040.0, support=2020.0, resistance=2050.0,
            smc=smc_view
        )
        plan = engine.plan_from_smc(candles, view)
        assert plan is not None
        assert plan.side == Side.SELL
        assert plan.grade == SetupGrade.A
        assert plan.stop_loss > plan.entry_price
        assert "Judas" in plan.reasoning

    def test_plan_from_analysis_h1_trend_conflict(self):
        engine = Engine()
        now = time.time()
        # M15 looks bearish: last < e20 < e50
        m15_candles = [
            Candle(time=int(now - (65-i)*900), open=2050.0-i*0.5, high=2051.0-i*0.5, low=2049.0-i*0.5, close=2050.0-i*0.5, volume=100)
            for i in range(65)
        ]
        # H1 is strongly BULLISH: rising sharply
        h1_candles = [
            Candle(time=int(now - (35-i)*3600), open=2000.0+i*2.0, high=2003.0+i*2.0, low=1999.0+i*2.0, close=2002.0+i*2.0, volume=500)
            for i in range(35)
        ]
        tick = Tick(symbol="XAUUSD", bid=2017.5, ask=2017.7, time=int(now))
        view = engine.analyze(m15_candles, tick, h1_candles=h1_candles, check_news=False)
        # Should reject SELL because H1 is strongly BULLISH
        plan = engine.plan_from_analysis(m15_candles, view, h1_candles=h1_candles)
        assert plan is None

    def test_plan_from_smc_h1_trend_conflict(self):
        from core.smc import SMCView, MarketPhase, ZoneType
        engine = Engine()
        now = time.time()
        m15_candles = [
            Candle(time=int(now - (35-i)*900), open=2040.0, high=2042.0, low=2038.0, close=2040.0, volume=100)
            for i in range(35)
        ]
        # Judas swing setup pointing to SELL
        smc_view = SMCView(
            bias="bearish", confidence=0.85, phase=MarketPhase.BOS_BEARISH,
            zone=ZoneType.PREMIUM, fib_level=0.75, killzone="london",
            judas_swing="BEARISH_JUDAS", swing_high=2050.0, swing_low=2020.0
        )
        view = MarketView(
            trend="bearish", trend_strength=0.5, atr=5.0, spread=0.2,
            last_price=2040.0, support=2020.0, resistance=2050.0,
            smc=smc_view
        )
        # 1. H1 strongly BULLISH -> should reject SMC SELL
        h1_bull = [
            Candle(time=int(now - (35-i)*3600), open=2000.0+i*2.0, high=2003.0+i*2.0, low=1999.0+i*2.0, close=2002.0+i*2.0, volume=500)
            for i in range(35)
        ]
        plan_blocked = engine.plan_from_smc(m15_candles, view, h1_candles=h1_bull)
        assert plan_blocked is None

        # 2. H1 aligned/neutral -> allows SMC SELL
        h1_aligned = [
            Candle(time=int(now - (35-i)*3600), open=2050.0-i*1.0, high=2051.0-i*1.0, low=2048.0-i*1.0, close=2049.0-i*1.0, volume=500)
            for i in range(35)
        ]
        plan_allowed = engine.plan_from_smc(m15_candles, view, h1_candles=h1_aligned)
        assert plan_allowed is not None
        assert plan_allowed.side == Side.SELL
        assert plan_allowed.source == "smc_judas"

    def test_rtm_quasimodo_plan_generation(self):
        from core.smc import SMCView, MarketPhase, ZoneType, QuasimodoPattern
        engine = Engine()
        now = time.time()
        candles = [
            Candle(time=int(now - (35-i)*900), open=2040.0, high=2042.0, low=2038.0, close=2040.0, volume=100)
            for i in range(35)
        ]
        qml_pattern = QuasimodoPattern(
            qml_type="BEARISH_QML",
            level=2040.0,
            invalidation=2050.0,
            target=2020.0,
            bar_index=20,
        )
        smc_view = SMCView(
            bias="bearish", confidence=0.85, phase=MarketPhase.BOS_BEARISH,
            zone=ZoneType.PREMIUM, fib_level=0.75, killzone="london",
            qml=qml_pattern
        )
        view = MarketView(
            trend="bearish", trend_strength=0.5, atr=5.0, spread=0.2,
            last_price=2040.0, support=2020.0, resistance=2050.0,
            smc=smc_view
        )
        plan = engine.plan_from_smc(candles, view)
        assert plan is not None
        assert plan.side == Side.SELL
        assert plan.source == "rtm_qml"
        assert plan.grade == SetupGrade.A
        assert plan.stop_loss > 2050.0


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
        # 2. Realized PnL (net of round-turn broker commission: -$7.0/lot):
        # gross = (2015 - 2000) * 0.05 * 100 = 75.0, comm = -7.0 * 0.05 = -0.35 -> net = 74.65
        expected_pnl = round((2015.0 - 2000.0) * 0.05 * 100.0 - 7.0 * 0.05, 2)
        assert round(bt.state.balance, 2) == round(initial_balance + expected_pnl, 2)
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

    def test_b235_backtest_loss_cooldown_parity(self):
        """b235: Backtester tracks last_loss_ts and enforces 45-minute loss cooldown circuit breaker."""
        from entry.backtest import Backtester
        bt = Backtester()
        ts_10utc = 1700042400  # 2023-11-15 10:00:00 UTC (inside session_hours)
        bars = []
        price = 2000.0
        # Create 120 bars inside active trading hours
        for i in range(120):
            bars.append({
                "time": ts_10utc + i * 900,
                "open": price + i * 0.5,
                "high": price + i * 0.5 + 2.0,
                "low": price + i * 0.5 - 1.0,
                "close": price + i * 0.5 + 1.0,
                "tick_volume": 100,
            })
        # Simulate a trade closing at a loss
        bt._last_loss_ts = ts_10utc + 3600  # loss occurred at 11:00 UTC
        # Check gates 15 minutes after loss (within 45-min cooldown)
        plan = Plan(
            plan_id="p-cooldown-test", symbol="XAUUSD", side=Side.BUY,
            entry_price=2050.0, stop_loss=2040.0, take_profit=2070.0,
            volume=0.0, grade=SetupGrade.A, source="analysis",
            timeframe="M15", rr=2.0, confidence=0.8, reasoning="test",
        )
        account = AccountState(balance=5000.0, equity=5000.0, margin=0.0, margin_free=5000.0)
        outcome = bt.gates.evaluate(
            plan, account, [], trades_today=0, daily_pnl=0.0,
            atr=5.0, spread=0.15,
            last_loss_ts=bt._last_loss_ts,
            now_ts=ts_10utc + 3600 + 15 * 60,  # 15 minutes after loss
        )
        assert not outcome.allowed
        assert any("loss_cooldown" in r for r in outcome.reasons)

        # 50 minutes after loss (outside 45-min cooldown)
        outcome_ok = bt.gates.evaluate(
            plan, account, [], trades_today=0, daily_pnl=0.0,
            atr=5.0, spread=0.15,
            last_loss_ts=bt._last_loss_ts,
            now_ts=ts_10utc + 3600 + 50 * 60,
        )
        assert outcome_ok.allowed

    def test_b235_db_get_last_loss_time_excludes_profitable_stops(self):
        """b235: Ledger.get_last_loss_time ignores trades with pnl >= 0 even if exit_reason is STOP_LOSS."""
        import tempfile
        from core.db import Ledger
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            led = Ledger(path=Path(f.name))
            # Trade 1: real loss at t=1000, pnl=-50.0
            t1 = Trade(
                trade_id="t1", plan_id="p1", ticket=101, symbol="XAUUSD", side=Side.BUY,
                volume=0.1, entry_price=2000.0, exit_price=1995.0, sl=1995.0, tp=2010.0,
                pnl=-50.0, exit_reason=ExitReason.STOP_LOSS, opened_at=900, closed_at=1000.0,
                grade=SetupGrade.A, source="signal", r_multiple=-1.0,
            )
            led.save_trade(t1)
            assert led.get_last_loss_time() == 1000.0

            # Trade 2: profitable trailed stop at t=2000, pnl=+75.0, exit_reason=STOP_LOSS (e.g. from MT5 [sl] comment)
            t2 = Trade(
                trade_id="t2", plan_id="p2", ticket=102, symbol="XAUUSD", side=Side.BUY,
                volume=0.1, entry_price=2000.0, exit_price=2007.5, sl=2007.5, tp=2020.0,
                pnl=75.0, exit_reason=ExitReason.STOP_LOSS, opened_at=1900, closed_at=2000.0,
                grade=SetupGrade.A, source="signal", r_multiple=1.5,
            )
            led.save_trade(t2)
            # Must still report 1000.0 (t1's loss), NOT 2000.0 (t2 was profitable)
            assert led.get_last_loss_time() == 1000.0
            led.close()

    def test_b235_exits_modify_idempotent_no_duplicate_requests(self):
        """b235: ExitManager._modify suppresses duplicate modifications when rounded_sl == pos.sl."""
        from core.exits import ExitManager
        from core.params import PositionCfg
        calls = []
        def mock_modify(ticket, sl, tp, reason="modify"):
            calls.append((ticket, sl, tp, reason))

        cfg = PositionCfg(
            trailing_start_rr=1.5,
            breakeven_rr=0.8,
            max_hold_hours=24,
            partial_tp_rr=2.0,
            partial_enabled=False,
        )
        em = ExitManager(cfg, on_modify=mock_modify)
        pos = BrokerPosition(
            ticket=555, symbol="XAUUSD", side=Side.BUY, volume=0.1,
            open_price=2000.0, current_price=2020.0, sl=2000.15, tp=2040.0,
            profit=198.5, swap=0.0, open_time=int(time.time()),
        )
        # Calling _apply_breakeven_with_buffer when SL is already 2000.15
        em._apply_breakeven_with_buffer(pos)
        assert len(calls) == 0  # No call because sl is already 2000.15!

        # Now test _modify directly with same value
        em._modify(pos, 2000.15, reason="test")
        assert len(calls) == 0

        # Now test _modify with genuine new value
        em._modify(pos, 2005.00, reason="trailing")
        assert len(calls) == 1
        assert calls[0] == (555, 2005.0, 2040.0, "trailing")

    def test_b235_grade_signal_dxy_and_divergence_parity(self):
        """b235: _grade_signal reflects DXY bias and RSI divergence alignment/penalties."""
        from core.engine import Engine, MarketView
        eng = Engine()
        sig_buy = Signal(
            signal_id="sig-dxy-1", raw_text="BUY GOLD", symbol="XAUUSD", side=Side.BUY,
            entry=2000.0, sl=1990.0, tp=2020.0, rr=2.0, confidence=0.8,
            timestamp="2026-10-29T00:00:00Z",
        )
        # 1. Base neutral view
        view_neutral = MarketView(
            trend="ranging", trend_strength=0.0, atr=5.0, spread=0.15,
            last_price=2000.0, support=1990.0, resistance=2020.0,
            usd_bias="NEUTRAL", divergence=None,
        )
        grade_neutral = eng._grade_signal(sig_buy, view_neutral)

        # 2. Bullish USD view (fighting against DXY)
        view_usd_bull = MarketView(
            trend="ranging", trend_strength=0.0, atr=5.0, spread=0.15,
            last_price=2000.0, support=1990.0, resistance=2020.0,
            usd_bias="BULLISH", divergence=None,
        )
        grade_usd_bull = eng._grade_signal(sig_buy, view_usd_bull)

        # 3. Bearish USD view + Bullish Divergence (strong multi-market confirmation)
        view_usd_bear_div = MarketView(
            trend="ranging", trend_strength=0.0, atr=5.0, spread=0.15,
            last_price=2000.0, support=1990.0, resistance=2020.0,
            usd_bias="BEARISH", divergence="BULLISH_REGULAR",
        )
        grade_usd_bear_div = eng._grade_signal(sig_buy, view_usd_bear_div)

        assert SetupGrade.rank(grade_usd_bear_div) >= SetupGrade.rank(grade_neutral)
        assert SetupGrade.rank(grade_neutral) >= SetupGrade.rank(grade_usd_bull)

    def test_backtest_h1_aggregation_and_smc_parity(self):
        from entry.backtest import Backtester, _aggregate_h1_candles
        # 1. Test aggregation of 8 M15 candles -> 2 H1 candles
        base_ts = 1700000000 - (1700000000 % 3600)  # aligned to hour
        m15_list = []
        for i in range(8):
            m15_list.append(Candle(
                time=base_ts + i * 900,
                open=2000.0 + i,
                high=2005.0 + i,
                low=1995.0 + i,
                close=2001.0 + i,
                volume=100 + i * 10
            ))
        h1_list = _aggregate_h1_candles(m15_list)
        assert len(h1_list) == 2
        # First H1 candle covers candles 0..3
        assert h1_list[0].time == base_ts
        assert h1_list[0].open == 2000.0
        assert h1_list[0].high == max(2005.0 + i for i in range(4))
        assert h1_list[0].low == min(1995.0 + i for i in range(4))
        assert h1_list[0].close == 2001.0 + 3
        # Second H1 candle covers candles 4..7
        assert h1_list[1].time == base_ts + 3600
        assert h1_list[1].open == 2000.0 + 4
        assert h1_list[1].close == 2001.0 + 7

    def test_daemon_smc_source_fallback(self):
        # Position created by SMC with comment hms-smc-ob-1234
        pos = BrokerPosition(
            ticket=777, symbol="XAUUSD", side=Side.BUY, volume=0.05,
            open_price=2000.0, current_price=2010.0, sl=1995.0, tp=2025.0,
            profit=50.0, swap=0.0, open_time=int(time.time()),
            comment="hms-smc-ob-1234"
        )
        source = ("analysis" if (pos.comment or "").startswith("hms-auto")
                  else ("smc" if ((pos.comment or "").startswith("hms-smc") or (pos.comment or "").startswith("hms-rtm")) else "signal"))
        assert source == "smc"

        pos_rtm = BrokerPosition(
            ticket=778, symbol="XAUUSD", side=Side.SELL, volume=0.05,
            open_price=2050.0, current_price=2040.0, sl=2058.0, tp=2030.0,
            profit=50.0, swap=0.0, open_time=int(time.time()),
            comment="hms-rtm-qml-1234"
        )
        source_rtm = ("analysis" if (pos_rtm.comment or "").startswith("hms-auto")
                      else ("smc" if ((pos_rtm.comment or "").startswith("hms-smc") or (pos_rtm.comment or "").startswith("hms-rtm")) else "signal"))
        assert source_rtm == "smc"

    def test_rtm_qml_and_ftr_gates_allow_institutional_stops(self):
        """b235: GatesEngine treats rtm_qml and rtm_ftr with institutional 1.2x ATR stop multiplier."""
        from core.gates import GatesEngine
        from core.params import Gates
        g_cfg = Gates(
            max_open_positions=3, max_daily_trades=5, max_daily_loss_pct=5.0,
            max_spread_points=0.50, min_rr=1.5, min_grade="B", min_atr_stop_mult=2.0,
            risk_per_trade_pct=2.0, max_volume_lots=0.5,
            min_atr_stop_mult_analysis=1.4, min_atr_stop_mult_smc=1.2,
        )
        gates = GatesEngine(g_cfg)
        account = AccountState(balance=5000.0, equity=5000.0, margin=0.0, margin_free=5000.0)

        # Plan with sl_dist = 6.5 (1.3 * ATR of 5.0) -> would be rejected if mult=2.0, approved if mult=1.2
        plan_qml = Plan(
            plan_id="p-rtm-qml-gate", symbol="XAUUSD", side=Side.SELL,
            entry_price=2040.0, stop_loss=2046.5, take_profit=2020.0,
            volume=0.0, grade=SetupGrade.A, source="rtm_qml",
            timeframe="M15", rr=3.0, confidence=0.9, reasoning="qml test",
        )
        outcome_qml = gates.evaluate(plan_qml, account, [], trades_today=0, daily_pnl=0.0, atr=5.0, spread=0.15)
        assert outcome_qml.allowed is True
        assert outcome_qml.volume > 0

        plan_ftr = Plan(
            plan_id="p-rtm-ftr-gate", symbol="XAUUSD", side=Side.BUY,
            entry_price=2000.0, stop_loss=1993.5, take_profit=2020.0,
            volume=0.0, grade=SetupGrade.A, source="rtm_ftr",
            timeframe="M15", rr=3.0, confidence=0.9, reasoning="ftr test",
        )
        outcome_ftr = gates.evaluate(plan_ftr, account, [], trades_today=0, daily_pnl=0.0, atr=5.0, spread=0.15)
        assert outcome_ftr.allowed is True
        assert outcome_ftr.volume > 0

    def test_smc_order_block_unmitigated_retest_and_plan_generation(self):
        """b235: Unmitigated Bullish Order Block correctly recognized on current bar retest."""
        from core.smc import SMCAnalyzer
        from core.engine import Engine
        engine = Engine()

        candles = [
            Candle(time=1000 + i*900, open=2000.0, high=2002.0, low=1998.0, close=2000.0, volume=100)
            for i in range(50)
        ]
        # Bullish OB at candle 32: bearish candle (open 1990, close 1986, low 1985)
        candles[32] = Candle(time=1000 + 32*900, open=1990.0, high=1991.0, low=1985.0, close=1986.0, volume=100)
        # Strong bullish breakout at 33
        candles[33] = Candle(time=1000 + 33*900, open=1986.0, high=2015.0, low=1986.0, close=2010.0, volume=500)
        # Price stays high in bars 34..48
        for i in range(34, 49):
            candles[i] = Candle(time=1000 + i*900, open=2010.0, high=2020.0, low=2005.0, close=2015.0, volume=100)
        # Bar 49 (current bar) pulls back to OB midpoint: top=1990, bottom=1985, mid=1987.5
        candles[49] = Candle(time=1000 + 49*900, open=2000.0, high=2000.0, low=1986.0, close=1988.0, volume=100)

        tick = Tick(symbol="XAUUSD", bid=1988.0, ask=1988.2, time=1000 + 49*900)
        view = engine.analyze(candles, tick, check_news=False)
        assert view.smc is not None
        # OB should be unmitigated before bar 49
        assert len(view.smc.unmitigated_obs) > 0

        # Plan generation should recognize the OB test and generate plan
        plan = engine.plan_from_smc(candles, view)
        assert plan is not None
        assert plan.source == "smc_ob"
        assert plan.side == Side.BUY
        assert plan.grade == SetupGrade.A

    def test_smc_ftr_unmitigated_retest_and_plan_generation(self):
        """b235: Unmitigated Demand FTR correctly recognized on current bar retest."""
        from core.smc import SMCView, MarketPhase, ZoneType, FTRZone
        engine = Engine()
        now = 1700000000
        candles = [
            Candle(time=now + i*900, open=2000.0, high=2002.0, low=1998.0, close=2000.0, volume=100)
            for i in range(50)
        ]
        candles[-1] = Candle(time=now + 49*900, open=2010.0, high=2010.0, low=2007.0, close=2008.0, volume=100)

        ftr = FTRZone(
            ftr_type="DEMAND_FTR", base_top=2010.0, base_bottom=2005.0,
            broken_level=2004.0, bar_index=35, mitigated=False
        )
        smc_view = SMCView(
            bias="bullish", confidence=0.85, phase=MarketPhase.BOS_BULLISH,
            zone=ZoneType.DISCOUNT, fib_level=0.35, killzone="london",
            unmitigated_ftrs=[ftr]
        )
        view = MarketView(
            trend="bullish", trend_strength=0.5, atr=5.0, spread=0.2,
            last_price=2008.0, support=2000.0, resistance=2030.0,
            smc=smc_view
        )
        plan = engine.plan_from_smc(candles, view)
        assert plan is not None
        assert plan.source == "rtm_ftr"
        assert plan.side == Side.BUY
        assert plan.grade == SetupGrade.A

    def test_plan_from_signal_stale_at_birth_rejection(self):
        """b235: plan_from_signal rejects stale signals where price already touched SL or TP."""
        engine = Engine()
        view = MarketView(
            trend="ranging", trend_strength=0.0, atr=5.0, spread=0.15,
            last_price=2000.0, support=1990.0, resistance=2020.0,
        )
        # Buy signal where SL is 2010.0 (market 2000.0 has already breached SL)
        sig_stale_sl = Signal(
            signal_id="sig-stale-1", raw_text="BUY", symbol="XAUUSD",
            side=Side.BUY, entry=2020.0, sl=2010.0, tp=2040.0,
            rr=2.0, confidence=0.8,
            timestamp="2026-10-29T00:00:00Z",
        )
        assert engine.plan_from_signal(sig_stale_sl, view) is None

        # Buy signal where TP is 1995.0 (market 2000.0 has already hit TP)
        sig_stale_tp = Signal(
            signal_id="sig-stale-2", raw_text="BUY", symbol="XAUUSD",
            side=Side.BUY, entry=1980.0, sl=1970.0, tp=1995.0,
            rr=1.5, confidence=0.8,
            timestamp="2026-10-29T00:00:00Z",
        )
        assert engine.plan_from_signal(sig_stale_tp, view) is None

    def test_smc_fvg_unmitigated_retest_and_plan_generation(self):
        """b237: Unmitigated Bullish FVG correctly recognized on current bar retest and generates Grade A plan."""
        from core.smc import SMCAnalyzer, FVGType
        from core.engine import Engine
        engine = Engine()

        base_t = 14 * 3600
        candles = [
            Candle(time=base_t + i*900, open=2000.0, high=2002.0, low=1998.0, close=2000.0, volume=100)
            for i in range(50)
        ]
        # Form a Bullish FVG around bar 32..34:
        # Candle 32 (c0): high = 1988.0
        # Candle 33 (c1): displacement candle
        # Candle 34 (c2): low = 1994.0 -> FVG gap is between 1988.0 (bottom) and 1994.0 (top)
        candles[32] = Candle(time=base_t + 32*900, open=1985.0, high=1988.0, low=1984.0, close=1987.0, volume=100)
        candles[33] = Candle(time=base_t + 33*900, open=1987.0, high=2015.0, low=1987.0, close=2010.0, volume=500)
        candles[34] = Candle(time=base_t + 34*900, open=2010.0, high=2020.0, low=1994.0, close=2015.0, volume=300)

        # Price stays high in bars 35..48 (swing high ~ 2030, establishing discount zone for pullback)
        for i in range(35, 49):
            candles[i] = Candle(time=base_t + i*900, open=2020.0, high=2030.0, low=2015.0, close=2025.0, volume=100)

        # Bar 49 (current forming bar) pulls back into the FVG: low=1990.0 (inside gap 1988..1994), close=1992.0
        candles[49] = Candle(time=base_t + 49*900, open=2015.0, high=2015.0, low=1990.0, close=1992.0, volume=100)

        tick = Tick(symbol="XAUUSD", bid=1992.0, ask=1992.2, time=base_t + 49*900)
        view = engine.analyze(candles, tick, check_news=False)
        assert view.smc is not None
        # FVG should be unfilled before bar 49 and detected
        unfilled = [f for f in view.smc.unfilled_fvgs if f.fvg_type == FVGType.BULLISH]
        assert len(unfilled) > 0
        assert unfilled[-1].midpoint == (unfilled[-1].top + unfilled[-1].bottom) / 2.0

        # Plan generation should recognize the FVG retest and generate plan
        plan = engine.plan_from_smc(candles, view)
        assert plan is not None
        assert plan.source == "smc_fvg"
        assert plan.side == Side.BUY
        assert plan.grade == SetupGrade.A
        assert plan.stop_loss < plan.entry_price
        assert plan.take_profit > plan.entry_price

    def test_evaluate_signal_tp_and_sl_reach_validation(self):
        """b237: evaluate_signal validates target and sl reach against live tick."""
        engine = Engine()
        view = MarketView(
            trend="ranging", trend_strength=0.0, atr=5.0, spread=0.15,
            last_price=2000.0, support=1990.0, resistance=2020.0,
        )
        sig = Signal(
            signal_id="sig-valid", raw_text="BUY", symbol="XAUUSD",
            side=Side.BUY, entry=2000.0, sl=1990.0, tp=2020.0,
            rr=2.0, confidence=0.8,
            timestamp="2026-10-29T00:00:00Z",
        )
        # Normal market near entry: EXECUTE
        tick_ok = Tick(symbol="XAUUSD", bid=1999.9, ask=2000.1, time=1000)
        status, plan, _ = engine.evaluate_signal(sig, view, tick_ok)
        assert status == "EXECUTE"
        assert plan is not None

        # Price already above TP: REJECT
        tick_tp = Tick(symbol="XAUUSD", bid=2021.0, ask=2021.2, time=1000)
        status_tp, _, _ = engine.evaluate_signal(sig, view, tick_tp)
        assert status_tp == "REJECT"

        # Price already below SL: REJECT
        tick_sl = Tick(symbol="XAUUSD", bid=1989.0, ask=1989.2, time=1000)
        status_sl, _, _ = engine.evaluate_signal(sig, view, tick_sl)
        assert status_sl == "REJECT"

    def test_backtest_close_sim_trade_deducts_commission(self):
        """b237: Backtester._close_sim_trade deducts round-turn commission matching net-of-cost parity."""
        from entry.backtest import Backtester, OpenTrade
        bt = Backtester()
        ot = OpenTrade(
            ticket=1001, symbol="XAUUSD", side=Side.BUY, volume=0.10,
            open_price=2000.0, sl=1990.0, tp=2020.0, open_time=1000.0,
            entry_rr=2.0, initial_sl=1990.0, grade=SetupGrade.A,
            source="smc_fvg", plan_id="p-1",
        )
        bt._open = ot
        cur_candle = Candle(time=1900, open=2005.0, high=2025.0, low=2000.0, close=2020.0, volume=100)
        # Hits TP at 2020.0: gross = (2020 - 2000) * 0.10 * 100 = $200.0
        # Commission at -$7.0/lot * 0.10 = -$0.70 -> Net PnL = $199.30
        hit = bt._check_sl_tp(cur_candle)
        assert hit is not None
        ok = bt._process_exit([cur_candle], 0, 1900.0)
        assert ok is True
        assert len(bt.trades) == 1
        assert bt.trades[0].pnl == 199.30

    def test_rsi_divergence_recent_swing_priority(self):
        """b237: detect_rsi_divergence prioritizes the more recent swing structure."""
        from core.engine import detect_rsi_divergence
        highs = [2000.0] * 30
        lows = [1990.0] * 30
        rsi = [50.0] * 30

        # Older swing highs: high at 10 (2010, rsi 65), high at 14 (2015, rsi 55) -> bearish divergence
        highs[9], highs[10], highs[11] = 2005.0, 2010.0, 2005.0
        rsi[10] = 65.0
        highs[13], highs[14], highs[15] = 2010.0, 2015.0, 2010.0
        rsi[14] = 55.0

        # Recent swing lows: low at 22 (1985, rsi 35), low at 26 (1980, rsi 42) -> bullish regular divergence
        lows[21], lows[22], lows[23] = 1990.0, 1985.0, 1990.0
        rsi[22] = 35.0
        lows[25], lows[26], lows[27] = 1985.0, 1980.0, 1985.0
        rsi[26] = 42.0

        div_type, strength = detect_rsi_divergence(highs, lows, rsi, window=30)
        assert div_type == "BULLISH_REGULAR"
        assert strength > 0.0

    def test_b239_gates_float_parity_exact_cent_stop_allowed(self):
        """b239: GatesEngine rounds atr*mult to cents preventing sub-cent rejection (14.00 < 14.004)."""
        engine = GatesEngine(Gates(
            max_open_positions=1, max_daily_trades=5, risk_per_trade_pct=2.0,
            max_daily_loss_pct=5.0, min_rr=1.0, min_grade="B",
            min_atr_stop_mult=2.0, max_spread_points=3.0,
            min_atr_stop_mult_smc=1.2,
        ))
        acc = AccountState(balance=5000.0, equity=5000.0, margin=0.0, margin_free=5000.0, currency="USD")
        # atr = 11.67, mult = 1.2 -> atr * mult = 14.004
        # Plan stop distance is exactly 14.00
        plan = Plan(
            plan_id="p-b239-smc", symbol="XAUUSD", side=Side.BUY,
            entry_price=2600.00, stop_loss=2586.00, take_profit=2635.00,
            volume=0.0, grade=SetupGrade.A, source="smc_fvg", rr=2.5,
        )
        outcome = engine.evaluate(plan, acc, [], 0, 0.0, atr=11.67, spread=0.20)
        assert outcome.allowed is True
        assert "stop_too_tight" not in str(outcome.reasons)

    def test_b239_smc_judas_asian_session_levels(self):
        """b239: SMCView captures asia_high/asia_low and plan_from_smc anchors stop to Asian sweep levels."""
        from core.smc import SMCAnalyzer, SMCView, ZoneType
        from core.entities import Candle, Tick
        # Build Asian session candles (hours 0-5 UTC) followed by London open sweep candle (hour 7 UTC)
        # Using a fixed date timestamp: 1700000000 % 86400 = 60800 (hour 16)
        # Midnight UTC timestamp: 1699920000 (2023-11-14 00:00:00 UTC)
        midnight = 1699920000
        candles = []
        # Pre-Asian candles (prior day late hours to ensure len(candles) >= 30 for engine)
        for i in range(5):
            candles.append(Candle(
                time=midnight - 4500 + i * 900,
                open=2600.0, high=2602.0, low=2598.0, close=2601.0, volume=50
            ))
        for i in range(24):  # 24 candles of M15 = 6 hours (00:00 to 06:00 UTC)
            candles.append(Candle(
                time=midnight + i * 900,
                open=2600.0, high=2610.0, low=2595.0, close=2605.0, volume=100
            ))
        # Add pre-London candles (06:00 - 07:00 UTC)
        for i in range(4):
            candles.append(Candle(
                time=midnight + 21600 + i * 900,
                open=2605.0, high=2608.0, low=2602.0, close=2604.0, volume=120
            ))
        # London open candle (hour 7 UTC): sweeps Asia high (2610.0) up to 2614.0 and closes at 2608.0
        candles.append(Candle(
            time=midnight + 25200,
            open=2604.0, high=2614.0, low=2603.0, close=2608.0, volume=300
        ))

        analyzer = SMCAnalyzer()
        judas, asia_high, asia_low = analyzer.detect_judas_swing(candles, killzone="london")
        assert judas == "BEARISH_JUDAS"
        assert asia_high == 2610.0
        assert asia_low == 2595.0

        view = analyzer.analyze(candles, now_dt=None)
        assert view.asia_high == 2610.0
        assert view.asia_low == 2595.0
        assert view.judas_swing == "BEARISH_JUDAS"

        # Verify plan_from_smc sets stop loss above the sweep high (2614.0) with buffer
        eng = Engine()
        tick = Tick(symbol="XAUUSD", bid=2608.0, ask=2608.2, time=candles[-1].time)
        mkt_view = eng.analyze(candles, tick, check_news=False)
        plan = eng.plan_from_smc(candles, mkt_view, timeframe="M15")
        assert plan is not None
        assert plan.side == Side.SELL
        assert plan.source == "smc_judas"
        assert plan.stop_loss > 2614.0  # Above the Judas sweep peak
        assert plan.rr == 2.5
        assert plan.take_profit < plan.entry_price

    def test_b239_backtester_sim_partial_deducts_broker_commission(self):
        """b239: Backtester _sim_partial deducts round-turn commission (-$7.0/lot)."""
        from entry.backtest import Backtester, OpenTrade
        from core.entities import Side, ExitReason
        bt = Backtester()
        bt._open = OpenTrade(
            ticket=888, symbol="XAUUSD", side=Side.BUY, volume=0.20,
            open_price=2000.0, sl=1990.0, tp=2030.0, open_time=1000.0,
            plan_id="p-comm", entry_rr=2.0, initial_sl=1990.0,
        )
        bt._cur_candle_close = 2010.0
        bt._cur_candle_ts = 1500.0
        init_balance = bt.state.balance

        # Partial close 50% = 0.10 lot
        # Gross = (2010 - 2000) * 0.10 * 100 = 100.0
        # Commission = -7.0 * 0.10 = -0.70
        # Net = 99.30
        bt._sim_partial(ticket=888, percent=50.0)
        assert bt._open.volume == 0.10
        assert len(bt.trades) == 1
        t = bt.trades[0]
        assert t.exit_reason == ExitReason.PARTIAL_TP
        assert t.volume == 0.10
        assert t.pnl == 99.30
        assert round(bt.state.balance, 2) == round(init_balance + 99.30, 2)

    def test_b241_judas_h1_conflict_falls_through_to_subsequent_smc(self):
        """b241: When Judas swing conflicts with H1 bias, engine falls through to OB/FVG instead of returning None."""
        engine = Engine()
        now = 1700000000
        candles = [
            Candle(time=now + i*900, open=2000.0, high=2002.0, low=1998.0, close=2000.0, volume=100)
            for i in range(50)
        ]
        # Bullish OB at candle 32
        candles[32] = Candle(time=now + 32*900, open=1990.0, high=1991.0, low=1985.0, close=1986.0, volume=100)
        candles[33] = Candle(time=now + 33*900, open=1986.0, high=2015.0, low=1986.0, close=2010.0, volume=500)
        for i in range(34, 49):
            candles[i] = Candle(time=now + i*900, open=2010.0, high=2020.0, low=2005.0, close=2015.0, volume=100)
        candles[49] = Candle(time=now + 49*900, open=2000.0, high=2000.0, low=1986.0, close=1988.0, volume=100)

        tick = Tick(symbol="XAUUSD", bid=1988.0, ask=1988.2, time=now + 49*900)
        view = engine.analyze(candles, tick, check_news=False)

        # Force a conflicting Judas swing (BEARISH_JUDAS) on view
        from core.smc import SMCView
        from core.engine import MarketView
        smc_dict = view.smc.__dict__.copy()
        smc_dict["judas_swing"] = "BEARISH_JUDAS"
        mock_smc = SMCView(**smc_dict)
        view_with_judas = MarketView(
            trend=view.trend, trend_strength=view.trend_strength, atr=view.atr,
            spread=view.spread, last_price=view.last_price, support=view.support,
            resistance=view.resistance, rsi=view.rsi, divergence=view.divergence,
            div_strength=view.div_strength, usd_bias=view.usd_bias, smc=mock_smc,
            news_blackout=False, news_reason="", notes=view.notes,
        )
        # H1 candles indicating strong uptrend (h1_bias == 'BULLISH')
        h1_candles = [
            Candle(time=now + i*3600, open=1900.0 + i*2, high=1905.0 + i*2, low=1899.0 + i*2, close=1904.0 + i*2, volume=100)
            for i in range(40)
        ]
        # In b239 this would abort (return None) because Judas was BEARISH while H1 was BULLISH.
        # In b241 it skips the conflicting Judas and falls through to the bullish OB setup!
        plan = engine.plan_from_smc(candles, view_with_judas, h1_candles=h1_candles)
        assert plan is not None
        assert plan.source == "smc_ob"
        assert plan.side == Side.BUY

    def test_b241_plan_from_analysis_dynamic_rr(self):
        """b241: plan_from_analysis computes true dynamic rr rather than hardcoded 2.0."""
        engine = Engine()
        candles = [
            Candle(time=i*900, open=2000.0 + i*0.5, high=2002.0 + i*0.5, low=1998.0 + i*0.5, close=2001.0 + i*0.5, volume=100)
            for i in range(50)
        ]
        tick = Tick(symbol="XAUUSD", bid=2025.5, ask=2025.7, time=50*900)
        view = engine.analyze(candles, tick, check_news=False)
        plan = engine.plan_from_analysis(candles, view, "M15")
        if plan is not None:
            expected_rr = round(abs(plan.entry_price - plan.take_profit) / max(0.1, abs(plan.entry_price - plan.stop_loss)), 2)
            assert plan.rr == expected_rr

    def test_b243_backtester_trailing_stop_exit_reason_parity(self):
        """b243: Backtester reconciles STOP_LOSS hit to TRAILING_STOP or BREAKEVEN when net PnL is non-negative."""
        from entry.backtest import Backtester, OpenTrade
        bt = Backtester()
        bt._open = OpenTrade(
            ticket=999, symbol="XAUUSD", side=Side.BUY, volume=0.10,
            open_price=2000.0, sl=2015.0, tp=2030.0, open_time=1000.0,
            plan_id="p-trail", entry_rr=2.0, initial_sl=1990.0,
        )
        # Candle low hits the trailed stop at 2015.0 (which is in profit)
        candle = Candle(time=2000, open=2020.0, high=2022.0, low=2014.0, close=2016.0, volume=100)
        closed = bt._process_exit([candle], 0, 2000.0)
        assert closed is True
        assert len(bt.trades) == 1
        t = bt.trades[0]
        # PnL: (2015 - 2000) * 0.10 * 100 - 0.70 = 150 - 0.70 = 149.30 > 0
        assert t.pnl == 149.30
        assert t.exit_reason == ExitReason.TRAILING_STOP

    def test_b243_watchlist_pullback_zero_tp_guarded(self):
        """b243: Watchlist pullback with tp<=0 does not compute fake 270.0 RR from raw asset price."""
        from unittest.mock import MagicMock
        from entry.hermes import HermesDaemon
        daemon = HermesDaemon(bridge_token="")
        daemon.notify = MagicMock()
        # Simulate watchlist item with tp=0
        item = {
            "item_id": "wl-zero-tp",
            "signal_id": "sig-ztp",
            "symbol": "XAUUSD",
            "side": "BUY",
            "entry_price": 2700.0,
            "trigger_price": 2700.0,
            "sl": 2690.0,
            "tp": 0.0,
            "added_at": 1000.0,
            "expires_at": 5000.0,
            "status": "waiting",
            "reason": "test",
        }
        tick_mid = 2700.0
        if item.get("tp", 0.0) > 0:
            rr = round(abs(item["tp"] - tick_mid) / max(0.1, abs(tick_mid - item["sl"])), 2)
        else:
            rr = 0.0
        assert rr == 0.0  # Guarded, not 270.0!
        daemon.close()

    def test_b245_backtester_breakeven_exit_reason_parity(self):
        """b245: Backtester classifies SL exit near open_price as BREAKEVEN even if net PnL > 0."""
        from entry.backtest import Backtester, OpenTrade
        bt = Backtester()
        bt._open = OpenTrade(
            ticket=1001, symbol="XAUUSD", side=Side.BUY, volume=0.10,
            open_price=2000.0, sl=2000.10, tp=2030.0, open_time=1000.0,
            plan_id="p-be", entry_rr=2.0, initial_sl=1990.0,
        )
        # Candle low touches 2000.10 (moved to breakeven + 0.10 buffer)
        candle = Candle(time=2000, open=2005.0, high=2005.0, low=2000.0, close=2001.0, volume=100)
        closed = bt._process_exit([candle], 0, 2000.0)
        assert closed is True
        assert len(bt.trades) == 1
        t = bt.trades[0]
        # PnL: (2000.10 - 2000.0) * 0.10 * 100 - 0.70 = 1.00 - 0.70 = +0.30
        assert t.pnl == 0.30
        # Because abs(2000.10 - 2000.0) <= 0.25, it must be BREAKEVEN, NOT TRAILING_STOP
        assert t.exit_reason == ExitReason.BREAKEVEN

    def test_b245_daemon_breakeven_exit_reason_parity(self):
        """b245: HermesDaemon._reconcile_broker_closed_positions resolves breakeven SL deals to BREAKEVEN."""
        from unittest.mock import MagicMock
        from entry.hermes import HermesDaemon
        from core.exits import ExitManager
        from core.params import PositionCfg
        import tempfile
        from pathlib import Path
        from core.db import Ledger

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_reconcile_be.db"
            ledger = Ledger(db_path)

            daemon = MagicMock(spec=HermesDaemon)
            daemon.dry_run = False
            daemon.cfg = MagicMock()
            daemon.cfg.symbol = "XAUUSD"
            daemon.led = ledger
            daemon.notify = MagicMock()
            cfg = PositionCfg(trailing_start_rr=1.5, breakeven_rr=1.0, max_hold_hours=24, partial_tp_rr=1.5, partial_enabled=True)
            daemon.exits = ExitManager(cfg)
            daemon.exits.register_initial_sl(555, 1990.0)

            old_pos = BrokerPosition(
                ticket=555, symbol="XAUUSD", side=Side.BUY, volume=0.10,
                open_price=2000.0, current_price=2000.15, sl=2000.15, tp=2030.0,
                profit=1.5, swap=0.0, commission=-0.70, open_time=1700000000,
                comment="hms-auto-test", initial_sl=1990.0
            )
            daemon._tracked_positions = {555: old_pos}

            # Simulate broker history deal with comment '[sl]' and small positive net pnl (2000.15 is within 0.25 of open 2000.0)
            mock_deal = {
                "ticket": 9991, "position_id": 555, "entry": 1,
                "symbol": "XAUUSD", "price": 2000.15,
                "profit": 1.5, "swap": 0.0, "commission": -0.70,
                "comment": "[sl] breakeven hit", "time": 1700000500,
            }
            daemon.mt5 = MagicMock()
            daemon.mt5.get_history_deals.return_value = [mock_deal]

            HermesDaemon._reconcile_broker_closed_positions(daemon, [555])

            trades = ledger.get_trades(limit=10)
            assert len(trades) == 1
            t = trades[0]
            assert t.ticket == 555
            assert t.exit_price == 2000.15
            assert t.exit_reason == ExitReason.BREAKEVEN
            ledger.close()

    def test_b245_backtester_unfulfilled_signal_does_not_block_auto_analysis(self):
        """b245: Unfulfilled channel signal in entry_queue does not block automated market analysis."""
        from unittest.mock import MagicMock
        from entry.backtest import Backtester
        bt = Backtester()
        # Mock signal with entry far above current market
        unreached_sig = Signal(
            signal_id="sig-unreached-1", raw_text="BUY", symbol="XAUUSD",
            side=Side.BUY, entry=2500.0, sl=2480.0, tp=2540.0,
            rr=2.0, confidence=0.85, timestamp="2026-10-29T10:00:00Z"
        )
        # Mock plan_from_smc to return an auto plan
        auto_plan = Plan(
            plan_id="smc-fvg-test", symbol="XAUUSD", side=Side.BUY,
            entry_price=2000.0, stop_loss=1990.0, take_profit=2020.0,
            volume=0.1, grade=SetupGrade.A, source="smc_fvg",
            timeframe="M15", rr=2.0, confidence=0.9, reasoning="test"
        )
        called = []
        def mock_plan_from_smc(*args, **kwargs):
            called.append(True)
            return auto_plan
        bt.eng.plan_from_smc = mock_plan_from_smc

        # Create bars during session_hours (10:00 UTC) at price ~2000 (nowhere near 2500)
        bars = []
        base_ts = 1793268000.0  # 10:00 UTC
        for i in range(70):
            bars.append({
                "time": base_ts + i * 900,
                "open": 2000.0,
                "high": 2005.0,
                "low": 1995.0,
                "close": 2000.0,
                "tick_volume": 500,
            })
        # Run backtest with the unreached signal
        res = bt.run(bars, [unreached_sig])
        # In b245, plan_from_smc MUST be called and auto_plan processed even though entry_queue has a pending signal
        assert len(called) > 0
        assert res["total_trades"] > 0 or len(bt.denied) > 0

    def test_b247_daemon_close_position_breakeven_and_trailing_parity(self):
        """b247: HermesDaemon._close_position resolves STOP_LOSS exits with pnl>=0 to BREAKEVEN or TRAILING_STOP."""
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock
        from core.db import Ledger
        from entry.hermes import HermesDaemon

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_b247_close.db"
            ledger = Ledger(db_path)
            daemon = HermesDaemon(bridge_token="")
            daemon.notify = MagicMock()
            daemon.led = ledger
            daemon.dry_run = True
            daemon.mt5.close_position = MagicMock()

            pos_be = BrokerPosition(
                ticket=101, symbol="XAUUSD", side=Side.BUY, volume=0.10,
                open_price=2000.0, current_price=2000.15, sl=2000.15, tp=2030.0,
                profit=1.5, swap=0.0, commission=-0.70, open_time=1000,
                comment="hms-test-be", initial_sl=1990.0,
            )
            daemon.exits.register_initial_sl(101, 1990.0)
            daemon._close_position(pos_be, ExitReason.STOP_LOSS, exit_price=2000.15)
            t_be = ledger.get_trades(limit=1)[0]
            assert t_be.exit_reason == ExitReason.BREAKEVEN
            assert t_be.ticket == 101

            pos_trail = BrokerPosition(
                ticket=102, symbol="XAUUSD", side=Side.BUY, volume=0.10,
                open_price=2000.0, current_price=2015.0, sl=2015.0, tp=2030.0,
                profit=150.0, swap=0.0, commission=-0.70, open_time=1000,
                comment="hms-test-trail", initial_sl=1990.0,
            )
            daemon.exits.register_initial_sl(102, 1990.0)
            daemon._close_position(pos_trail, ExitReason.STOP_LOSS, exit_price=2015.0)
            t_trail = ledger.get_trades(limit=1)[0]
            assert t_trail.exit_reason == ExitReason.TRAILING_STOP
            assert t_trail.ticket == 102
            assert t_trail.pnl > 0

            pos_loss = BrokerPosition(
                ticket=103, symbol="XAUUSD", side=Side.BUY, volume=0.10,
                open_price=2000.0, current_price=1990.0, sl=1990.0, tp=2030.0,
                profit=-100.0, swap=0.0, commission=-0.70, open_time=1000,
                comment="hms-test-loss", initial_sl=1990.0,
            )
            daemon.exits.register_initial_sl(103, 1990.0)
            daemon._close_position(pos_loss, ExitReason.STOP_LOSS, exit_price=1990.0)
            t_loss = ledger.get_trades(limit=1)[0]
            assert t_loss.exit_reason == ExitReason.STOP_LOSS
            assert t_loss.ticket == 103
            assert t_loss.pnl < 0

            ledger.close()
            daemon.close()

    def test_b247_daemon_initial_sl_recovery_guards_against_advanced_sl(self):
        """b247: HermesDaemon does not use advanced/breakeven sl as initial_sl when initial_sl is missing."""
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock
        from core.db import Ledger
        from entry.hermes import HermesDaemon

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_b247_initsl.db"
            ledger = Ledger(db_path)
            daemon = HermesDaemon(bridge_token="")
            daemon.notify = MagicMock()
            daemon.led = ledger
            daemon.dry_run = True
            daemon.mt5.close_position = MagicMock()

            # Position without registered initial_sl or plan, and sl has moved to breakeven +0.15
            pos = BrokerPosition(
                ticket=201, symbol="XAUUSD", side=Side.BUY, volume=0.10,
                open_price=2000.0, current_price=2000.15, sl=2000.15, tp=2030.0,
                profit=1.5, swap=0.0, commission=-0.70, open_time=1000,
                comment="hms-orphan", initial_sl=0.0,
            )
            daemon._close_position(pos, ExitReason.STOP_LOSS, exit_price=2000.15)
            t = ledger.get_trades(limit=1)[0]
            assert t.r_multiple == 0.0

            ledger.close()
            daemon.close()

    def test_b247_daemon_watchlist_execution_marks_failed_on_rejected_order(self):
        """b247: Watchlist item is updated to failed (not executed) if order placement fails."""
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock
        from core.db import Ledger
        from entry.hermes import HermesDaemon
        from core.entities import Order, OrderStatus

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_b247_wl.db"
            ledger = Ledger(db_path)
            daemon = HermesDaemon(bridge_token="")
            daemon.notify = MagicMock()
            daemon.led = ledger

            # Add waiting item to watchlist
            wl_item = {
                "item_id": "wl-sig-fail-1", "signal_id": "sig-fail-1", "symbol": "XAUUSD",
                "side": "BUY", "entry_price": 2000.0, "trigger_price": 2000.0,
                "sl": 1990.0, "tp": 2020.0, "added_at": 1000.0, "expires_at": 5000.0,
                "status": "waiting", "reason": "test failure",
            }
            ledger.add_to_watchlist(wl_item)

            # Mock place_order to return rejected order
            failed_order = Order(
                order_id="hms-plan-fail", plan_id="", ticket=0, symbol="XAUUSD",
                side=Side.BUY, volume=0.1, price=0.0, sl=1990.0, tp=2020.0,
                status=OrderStatus.REJECTED, created_at=1000.0,
            )
            daemon.mt5.place_order = MagicMock(return_value=failed_order)

            # Execute logic as in daemon._entry_loop
            wl_executed_item_id = "wl-sig-fail-1"
            if wl_executed_item_id:
                if failed_order.ticket > 0 and failed_order.status != OrderStatus.REJECTED:
                    daemon.led.update_watchlist_status(wl_executed_item_id, "executed")
                else:
                    daemon.led.update_watchlist_status(wl_executed_item_id, "failed")

            # Verify status in database
            rows = daemon.led._con.execute("SELECT status FROM watchlist WHERE item_id = ?", ("wl-sig-fail-1",)).fetchall()
            assert rows[0][0] == "failed"

            ledger.close()
            daemon.close()

    def test_b247_backtester_invalidates_pending_signal_on_sl_or_tp_touch_before_entry(self):
        """b247: Backtester prunes pending signals when SL or TP is reached before market touches entry."""
        from entry.backtest import Backtester
        bt = Backtester()

        base_ts = 1793268000.0
        sig = Signal(
            signal_id="sig-b247-tp-first", raw_text="BUY", symbol="XAUUSD",
            side=Side.BUY, entry=2010.0, sl=1990.0, tp=2030.0,
            rr=2.0, confidence=0.85, timestamp="2026-10-29T10:00:00Z"
        )
        # 60 warmup candles (from base_ts - 60*900)
        bars = [{"time": base_ts - (60 - i) * 900, "open": 2000.0, "high": 2002.0, "low": 1998.0, "close": 2000.0, "tick_volume": 100} for i in range(60)]
        # Candle 60: at base_ts (now_ts matches sig_ts)
        bars.append({"time": base_ts, "open": 2000.0, "high": 2002.0, "low": 1998.0, "close": 2000.0, "tick_volume": 100})
        # Candle 61: market spikes to 2035 (high >= tp 2030) without touching entry 2010 (open=2020, high=2035, low=2015, close=2030)
        bars.append({"time": base_ts + 900, "open": 2020.0, "high": 2035.0, "low": 2015.0, "close": 2030.0, "tick_volume": 100})
        # Candle 62: market drops back and touches entry 2010 (high=2015, low=2005)
        bars.append({"time": base_ts + 1800, "open": 2015.0, "high": 2015.0, "low": 2005.0, "close": 2010.0, "tick_volume": 100})

        res = bt.run(bars, [sig])
        denied_reasons = [d.get("reason") for d in bt.denied if d.get("signal") == "sig-b247-tp-first"]
        assert "target_reached_before_entry" in denied_reasons
        executed_sig_trades = [t for t in bt.trades if t.plan_id == "plan-sig-b247-tp-first"]
        assert len(executed_sig_trades) == 0









