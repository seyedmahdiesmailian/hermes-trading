"""tests/test_unit_suite.py — Unittest suite for core trading entities, gates, and net PnL."""
from __future__ import annotations

import unittest
from decimal import Decimal
from core.entities import (
    Side,
    SetupGrade,
    BrokerPosition,
    AccountState,
    Plan,
    Signal,
    ExitReason,
)
from core.gates import GatesEngine
from core.exits import ExitManager
from core.params import Gates, PositionCfg


class TestTradingCore(unittest.TestCase):
    def setUp(self):
        self.gates_cfg = Gates(
            max_open_positions=1,
            max_daily_trades=5,
            risk_per_trade_pct=2.0,
            max_daily_loss_pct=5.0,
            min_rr=1.0,
            min_grade=SetupGrade.B,
            min_atr_stop_mult=2.0,
            max_spread_points=2.5,
        )
        self.engine = GatesEngine(self.gates_cfg)
        self.account = AccountState(
            balance=5000.0,
            equity=5000.0,
            margin=0.0,
            margin_free=5000.0,
            currency="USD",
        )
        self.plan = Plan(
            plan_id="p-test-1",
            symbol="XAUUSD",
            side=Side.BUY,
            entry_price=2600.0,
            stop_loss=2590.0,
            take_profit=2620.0,
            volume=0.0,
            grade=SetupGrade.A,
            source="analysis",
            rr=2.0,
        )

    def test_b210_net_profit_includes_swap_and_commission(self):
        """b210: Deal profit must be net of swap and commission."""
        pos = BrokerPosition(
            ticket=999,
            symbol="XAUUSD",
            side=Side.BUY,
            volume=0.1,
            open_price=2600.0,
            current_price=2610.0,
            sl=2590.0,
            tp=2620.0,
            profit=100.0,
            swap=-4.5,
            commission=-7.0,
            open_time=1700000000,
        )
        self.assertEqual(pos.net_profit, 88.5)

    def test_b210_daily_loss_gate_blocks_on_net_loss(self):
        """b210: GatesEngine evaluates daily_loss against true net pnl."""
        # Max allowed loss is 5% of 5000 = $250.
        # If gross was -245 but commission/swap brought it to -255:
        outcome = self.engine.evaluate(
            plan=self.plan,
            account=self.account,
            positions=[],
            trades_today=1,
            daily_pnl=-255.0,
            atr=5.0,
            spread=0.5,
        )
        self.assertFalse(outcome.allowed)
        self.assertTrue(any("daily_loss" in r for r in outcome.reasons))

    def test_gate_allows_valid_setup(self):
        """Clean setup within risk parameters is allowed."""
        outcome = self.engine.evaluate(
            plan=self.plan,
            account=self.account,
            positions=[],
            trades_today=1,
            daily_pnl=50.0,
            atr=4.0,
            spread=0.3,
        )
        self.assertTrue(outcome.allowed)
        self.assertGreater(outcome.volume, 0.0)

    def test_gate_blocks_invalid_balance_or_equity(self):
        """Negative or zero balance/equity must fail closed."""
        dead_acc = AccountState(
            balance=5000.0,
            equity=0.0,
            margin=0.0,
            margin_free=0.0,
            currency="USD",
        )
        outcome = self.engine.evaluate(
            plan=self.plan,
            account=dead_acc,
            positions=[],
            trades_today=0,
            daily_pnl=0.0,
            atr=4.0,
            spread=0.3,
        )
        self.assertFalse(outcome.allowed)
        self.assertIn("equity_invalid", outcome.reasons)


    def test_b210_broker_position_r_multiple(self):
        """b210: BrokerPosition.r_multiple calculates true R profit based on initial risk."""
        # BUY: Entry 2000, SL 1990 (Risk=10)
        pos_buy = BrokerPosition(
            ticket=101, symbol="XAUUSD", side=Side.BUY, volume=0.1,
            open_price=2000.0, current_price=2008.0, sl=1990.0, tp=2020.0,
            profit=80.0, swap=0.0, commission=-1.0, open_time=1700000000
        )
        self.assertEqual(pos_buy.r_multiple, 0.8)

        # SELL: Entry 2000, SL 2010 (Risk=10)
        pos_sell = BrokerPosition(
            ticket=102, symbol="XAUUSD", side=Side.SELL, volume=0.1,
            open_price=2000.0, current_price=1985.0, sl=2010.0, tp=1970.0,
            profit=150.0, swap=0.0, commission=-1.0, open_time=1700000000
        )
        self.assertEqual(pos_sell.r_multiple, 1.5)

    def test_b210_daemon_today_pnl_net_of_cost(self):
        """b210: HermesDaemon._today_pnl sums profit, swap and commission from broker deals."""
        from unittest.mock import MagicMock
        from entry.hermes import HermesDaemon
        from datetime import datetime, timezone

        daemon = MagicMock(spec=HermesDaemon)
        daemon.dry_run = False
        daemon.cfg = MagicMock()
        daemon.cfg.symbol = "XAUUSD"
        
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        # Mock broker deals: profit -200, commission -15, swap -5 -> true net -220
        mock_deals = [
            {"ticket": 1, "time": today_start + 100, "entry": 0, "profit": 0.0, "commission": -7.5, "swap": 0.0},
            {"ticket": 2, "time": today_start + 200, "entry": 1, "profit": -200.0, "commission": -7.5, "swap": -5.0},
        ]
        daemon.mt5 = MagicMock()
        daemon.mt5.get_history_deals.return_value = mock_deals
        
        net_pnl = HermesDaemon._today_pnl(daemon)
        self.assertEqual(net_pnl, -220.0)

    def test_b210_daemon_today_trades_count_counts_broker_exits(self):
        """b210: HermesDaemon._today_trades_count counts broker exit deals (entry==1)."""
        from unittest.mock import MagicMock
        from entry.hermes import HermesDaemon
        from datetime import datetime, timezone

        daemon = MagicMock(spec=HermesDaemon)
        daemon.dry_run = False
        daemon.cfg = MagicMock()
        daemon.cfg.symbol = "XAUUSD"
        daemon.led = MagicMock()
        daemon.led.get_today_trades.return_value = []

        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        # 2 entry deals (entry=0), 2 exit deals (entry=1)
        mock_deals = [
            {"ticket": 1, "time": today_start + 100, "entry": 0, "profit": 0.0},
            {"ticket": 2, "time": today_start + 200, "entry": 1, "profit": -50.0},
            {"ticket": 3, "time": today_start + 300, "entry": 0, "profit": 0.0},
            {"ticket": 4, "time": today_start + 400, "entry": 1, "profit": 120.0},
        ]
        daemon.mt5 = MagicMock()
        daemon.mt5.get_history_deals.return_value = mock_deals

        count = HermesDaemon._today_trades_count(daemon)
        self.assertEqual(count, 2)

    def test_b211_news_guard_null_currency_and_country(self):
        """b211: NewsGuard._parse_cache_file correctly handles null currency and country."""
        import json
        import tempfile
        from pathlib import Path
        from core.news import NewsGuard

        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as f:
            data = {
                "events": [
                    {
                        "title": "High Impact Event Null Cur",
                        "country": "USD",
                        "currency": None,
                        "impact": "High",
                        "date": "2026-10-28T12:00:00+00:00"
                    },
                    {
                        "title": "High Impact Event Both Null",
                        "country": None,
                        "currency": None,
                        "impact": "High",
                        "date": "2026-10-28T14:00:00+00:00"
                    }
                ]
            }
            json.dump(data, f)
            temp_path = Path(f.name)

        try:
            guard = NewsGuard(cache_file=temp_path)
            guard._parse_cache_file()
            self.assertEqual(len(guard._events), 2)
            self.assertEqual(guard._events[0].currency, "USD")
            self.assertEqual(guard._events[1].currency, "")
        finally:
            temp_path.unlink(missing_ok=True)

    def test_b221_contract_unreadable_positions_denied_both_lanes(self):
        """b221: Dark bridge with positions=None must fail closed on both signal and analysis lanes."""
        signal_plan = Plan(
            plan_id="p-sig-b221",
            symbol="XAUUSD",
            side=Side.BUY,
            entry_price=2600.0,
            stop_loss=2590.0,
            take_profit=2620.0,
            volume=0.0,
            grade=SetupGrade.A,
            source="telegram",
            rr=2.0,
        )
        analysis_plan = self.plan  # source="analysis"

        # Signal lane plan on dark bridge
        outcome_sig = self.engine.evaluate(
            plan=signal_plan,
            account=self.account,
            positions=None,  # unreadable positions
            trades_today=0,
            daily_pnl=0.0,
            atr=4.0,
            spread=0.3,
        )
        self.assertFalse(outcome_sig.allowed)
        self.assertIn("positions_unreadable", outcome_sig.reasons)

        # Analysis lane plan on dark bridge
        outcome_ana = self.engine.evaluate(
            plan=analysis_plan,
            account=self.account,
            positions=None,  # unreadable positions
            trades_today=0,
            daily_pnl=0.0,
            atr=4.0,
            spread=0.3,
        )
        self.assertFalse(outcome_ana.allowed)
        self.assertIn("positions_unreadable", outcome_ana.reasons)

    def test_b221_contract_unreadable_account_denied_both_lanes(self):
        """b221: Dark bridge with account=None must fail closed on both lanes."""
        signal_plan = Plan(
            plan_id="p-sig-b221-acc",
            symbol="XAUUSD",
            side=Side.SELL,
            entry_price=2600.0,
            stop_loss=2610.0,
            take_profit=2580.0,
            volume=0.0,
            grade=SetupGrade.A,
            source="telegram",
            rr=2.0,
        )
        outcome_sig = self.engine.evaluate(
            plan=signal_plan,
            account=None,  # unreadable account
            positions=[],
            trades_today=0,
            daily_pnl=0.0,
            atr=4.0,
            spread=0.3,
        )
        self.assertFalse(outcome_sig.allowed)
        self.assertIn("equity_invalid", outcome_sig.reasons)

        outcome_ana = self.engine.evaluate(
            plan=self.plan,
            account=None,  # unreadable account
            positions=[],
            trades_today=0,
            daily_pnl=0.0,
            atr=4.0,
            spread=0.3,
        )
        self.assertFalse(outcome_ana.allowed)
        self.assertIn("equity_invalid", outcome_ana.reasons)

    def test_b221_contract_healthy_bridge_allowed(self):
        """b221: Healthy bridge (positions=[], valid account) allows entry on both lanes."""
        signal_plan = Plan(
            plan_id="p-sig-b221-ok",
            symbol="XAUUSD",
            side=Side.BUY,
            entry_price=2600.0,
            stop_loss=2590.0,
            take_profit=2620.0,
            volume=0.0,
            grade=SetupGrade.A,
            source="telegram",
            rr=2.0,
        )
        outcome_sig = self.engine.evaluate(
            plan=signal_plan,
            account=self.account,
            positions=[],
            trades_today=0,
            daily_pnl=0.0,
            atr=4.0,
            spread=0.3,
        )
        self.assertTrue(outcome_sig.allowed)

        outcome_ana = self.engine.evaluate(
            plan=self.plan,
            account=self.account,
            positions=[],
            trades_today=0,
            daily_pnl=0.0,
            atr=4.0,
            spread=0.3,
        )
        self.assertTrue(outcome_ana.allowed)

    def test_b223_exit_manager_r_multiple_trailing_and_partial(self):
        """b223: Trailing stop and partial take-profit evaluate r_multiple, enabling trailing for TP positions."""
        modifies = []
        partials = []
        cfg = PositionCfg(
            trailing_start_rr=1.5,
            breakeven_rr=1.0,
            max_hold_hours=24,
            partial_tp_rr=1.5,
            partial_enabled=True,
        )
        mgr = ExitManager(
            cfg,
            on_modify=lambda t, sl: modifies.append((t, sl)),
            on_partial=lambda t, p: partials.append((t, p)),
        )

        # BUY with TP: Open=2000, SL=1990, TP=2030 (Risk=10, Reward=30)
        # Price at 2018.0 -> r_mult=1.8 >= 1.5. Trailing must activate!
        pos = BrokerPosition(
            ticket=223,
            symbol="XAUUSD",
            side=Side.BUY,
            volume=0.2,
            open_price=2000.0,
            current_price=2018.0,
            sl=1990.0,
            tp=2030.0,
            profit=360.0,
            swap=0.0,
            commission=-2.0,
            open_time=1700000000,
        )
        self.assertEqual(pos.r_multiple, 1.8)
        self.assertEqual(round(pos.rr_progress, 2), 0.7)  # rr_progress is 0.7, which would have failed >= 1.5!

        res = mgr.manage(pos, now_ts=1700001000)
        self.assertIsNone(res)
        # 1. Partial close triggered (50%)
        self.assertEqual(len(partials), 1)
        self.assertEqual(partials[0], (223, 50.0))
        # 2. Trailing stop modified to 2012.0 (2018 - 0.5 * 12)
        self.assertEqual(len(modifies), 1)
        self.assertEqual(modifies[0], (223, 2012.0))

    def test_b225_exit_manager_dynamic_atr_trail_ratchet_and_single_be(self):
        """b225: Dynamic ATR trailing in auto-analysis lane (tp<=0) only moves to breakeven once and ratchets."""
        modifies = []
        cfg = PositionCfg(
            trailing_start_rr=1.5,
            breakeven_rr=0.8,
            max_hold_hours=24,
            partial_tp_rr=2.0,
            partial_enabled=False,
        )
        mgr = ExitManager(cfg, on_modify=lambda t, sl: modifies.append((t, sl)))

        # Position at 1.0R (between breakeven 0.8 and trailing 1.5)
        pos = BrokerPosition(
            ticket=225,
            symbol="XAUUSD",
            side=Side.BUY,
            volume=0.1,
            open_price=2700.0,
            current_price=2715.0,
            sl=2685.0,
            tp=0.0,
            profit=150.0,
            swap=0.0,
            commission=0.0,
            open_time=1700000000,
        )
        res = mgr.manage(pos, now_ts=1700001000, atr=10.0, atr_sl_mult=1.5)
        self.assertIsNone(res)
        # Exactly ONE modify call, and it is Breakeven + buffer (2700.15), NOT overwritten by losing stop!
        self.assertEqual(len(modifies), 1)
        self.assertEqual(modifies[0], (225, 2700.15))

    def test_b225_gates_rejects_inverted_stops(self):
        """b225: GatesEngine rejects inverted stops (BUY SL>=entry or SELL SL<=entry) with invalid_stops."""
        bad_buy = Plan(
            plan_id="p-inv-buy",
            symbol="XAUUSD",
            side=Side.BUY,
            entry_price=2600.0,
            stop_loss=2610.0,
            take_profit=2630.0,
            volume=0.0,
            grade=SetupGrade.A,
            source="telegram",
            rr=2.0,
        )
        outcome = self.engine.evaluate(
            plan=bad_buy,
            account=self.account,
            positions=[],
            trades_today=0,
            daily_pnl=0.0,
            atr=4.0,
            spread=0.3,
        )
        self.assertFalse(outcome.allowed)
        self.assertIn("invalid_stops", outcome.reasons)

    def test_b227_broker_position_r_multiple_with_initial_sl(self):
        """b227: BrokerPosition retains true initial risk multiple even after stop moved to breakeven/profit."""
        # BUY: open 2000, current 2015, initial_sl 1990. Current SL is moved to Breakeven (2000.15)
        pos = BrokerPosition(
            ticket=2271,
            symbol="XAUUSD",
            side=Side.BUY,
            volume=0.1,
            open_price=2000.0,
            current_price=2015.0,
            sl=2000.15,
            tp=2030.0,
            profit=150.0,
            swap=0.0,
            commission=0.0,
            open_time=1700000000,
            initial_sl=1990.0,
        )
        # Without initial_sl, (2000 - 2000.15) <= 0 would collapse r_multiple to 0.0.
        # With initial_sl, (2015 - 2000) / (2000 - 1990) = 15 / 10 = 1.5R.
        self.assertEqual(pos.r_multiple, 1.5)

    def test_b227_exit_manager_preserves_initial_risk_across_breakeven(self):
        """b227: ExitManager preserves initial SL across breakeven so trailing stop & partial TP fire at >=1.5R."""
        modifies = []
        partials = []
        cfg = PositionCfg(
            trailing_start_rr=1.5,
            breakeven_rr=1.0,
            max_hold_hours=24,
            partial_tp_rr=1.5,
            partial_enabled=True,
        )
        mgr = ExitManager(
            cfg,
            on_modify=lambda t, sl: modifies.append((t, sl)),
            on_partial=lambda t, pct: partials.append((t, pct)),
        )

        # گام ۱: پوزیشن در 1.0R (قیمت 2010، استاپ اولیه 1990) -> انتقال به Breakeven + buffer (2000.15)
        pos_step1 = BrokerPosition(
            ticket=2272,
            symbol="XAUUSD",
            side=Side.BUY,
            volume=0.1,
            open_price=2000.0,
            current_price=2010.0,
            sl=1990.0,
            tp=2030.0,
            profit=100.0,
            swap=0.0,
            commission=0.0,
            open_time=1700000000,
        )
        res1 = mgr.manage(pos_step1, now_ts=1700000100)
        self.assertIsNone(res1)
        self.assertEqual(len(modifies), 1)
        self.assertEqual(modifies[0], (2272, 2000.15))
        self.assertEqual(len(partials), 0)

        # گام ۲: در سیکل بعد، قیمت به 2018 می‌رسد (1.8R). استاپ جاری بروکر 2000.15 است.
        pos_step2 = BrokerPosition(
            ticket=2272,
            symbol="XAUUSD",
            side=Side.BUY,
            volume=0.1,
            open_price=2000.0,
            current_price=2018.0,
            sl=2000.15,
            tp=2030.0,
            profit=180.0,
            swap=0.0,
            commission=0.0,
            open_time=1700000000,
        )
        res2 = mgr.manage(pos_step2, now_ts=1700000200)
        self.assertIsNone(res2)
        # هر دو عملیات سیو سود پله‌ای و ترلینگ استاپ باید با موفقیت فعال شوند
        self.assertEqual(len(partials), 1)
        self.assertEqual(partials[0], (2272, 50.0))
        self.assertEqual(len(modifies), 2)
        # new_sl = 2018 - 0.5 * (2030 - 2018) = 2018 - 6.0 = 2012.0
        self.assertEqual(modifies[1], (2272, 2012.0))

    def test_b227_exit_reason_partial_tp_persistence(self):
        """b227: ExitReason.PARTIAL_TP can be saved and loaded in Ledger without error."""
        import tempfile
        from pathlib import Path
        from core.db import Ledger
        from core.entities import Trade
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_trades.db"
            ledger = Ledger(db_path)
            t = Trade(
                trade_id="trade-test-part",
                plan_id="p-1",
                ticket=777,
                symbol="XAUUSD",
                side=Side.BUY,
                volume=0.05,
                entry_price=2000.0,
                exit_price=2015.0,
                sl=1990.0,
                tp=2030.0,
                pnl=71.5,
                exit_reason=ExitReason.PARTIAL_TP,
                opened_at=1700000000.0,
                closed_at=1700000100.0,
            )
            ledger.save_trade(t)
            trades = ledger.get_trades(limit=10)
            self.assertEqual(len(trades), 1)
            self.assertEqual(trades[0].exit_reason, ExitReason.PARTIAL_TP)
            self.assertEqual(trades[0].pnl, 71.5)
            ledger.close()

    def test_b229_exit_manager_cleanup_ticket(self):
        """b229: ExitManager.cleanup_ticket properly cleans _initial_sl and _partial_executed."""
        from core.exits import ExitManager
        from core.params import PositionCfg
        cfg = PositionCfg(trailing_start_rr=1.5, breakeven_rr=1.0, max_hold_hours=24, partial_tp_rr=1.5, partial_enabled=True)
        mgr = ExitManager(cfg)
        mgr.register_initial_sl(555, 1990.0)
        mgr._partial_executed.add(555)
        self.assertIn(555, mgr._initial_sl)
        self.assertIn(555, mgr._partial_executed)

        mgr.cleanup_ticket(555)
        self.assertNotIn(555, mgr._initial_sl)
        self.assertNotIn(555, mgr._partial_executed)

    def test_b229_reconcile_broker_closed_positions(self):
        """b229: HermesDaemon._reconcile_broker_closed_positions reconciles MT5 exit deals into ledger and notifications."""
        from unittest.mock import MagicMock
        from entry.hermes import HermesDaemon
        from core.entities import BrokerPosition, Side, ExitReason
        from core.exits import ExitManager
        from core.params import PositionCfg
        import tempfile
        from pathlib import Path
        from core.db import Ledger

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_reconcile.db"
            ledger = Ledger(db_path)

            daemon = MagicMock(spec=HermesDaemon)
            daemon.dry_run = False
            daemon.cfg = MagicMock()
            daemon.cfg.symbol = "XAUUSD"
            daemon.led = ledger
            daemon.notify = MagicMock()
            cfg = PositionCfg(trailing_start_rr=1.5, breakeven_rr=1.0, max_hold_hours=24, partial_tp_rr=1.5, partial_enabled=True)
            daemon.exits = ExitManager(cfg)
            daemon.exits.register_initial_sl(999, 1990.0)

            old_pos = BrokerPosition(
                ticket=999,
                symbol="XAUUSD",
                side=Side.BUY,
                volume=0.1,
                open_price=2000.0,
                current_price=2015.0,
                sl=1990.0,
                tp=2020.0,
                profit=150.0,
                swap=-2.0,
                commission=-7.0,
                open_time=1700000000,
                comment="hms-auto-test",
                initial_sl=1990.0,
            )
            daemon._tracked_positions = {999: old_pos}

            # Mock broker deal for exit
            mock_deal = {
                "ticket": 8888,
                "position_id": 999,
                "entry": 1,
                "price": 2020.0,
                "profit": 200.0,
                "swap": -2.0,
                "commission": -7.0,
                "comment": "[tp] take profit reached",
                "time": 1700000500,
            }
            daemon.mt5 = MagicMock()
            daemon.mt5.get_history_deals.return_value = [mock_deal]

            # Reconcile closed position
            HermesDaemon._reconcile_broker_closed_positions(daemon, [999])

            # Verify saved trade
            trades = ledger.get_trades(limit=10)
            self.assertEqual(len(trades), 1)
            t = trades[0]
            self.assertEqual(t.ticket, 999)
            self.assertEqual(t.exit_price, 2020.0)
            self.assertEqual(t.pnl, 191.0)  # 200 - 2 - 7 = 191.0 net pnl
            self.assertEqual(t.exit_reason, ExitReason.TAKE_PROFIT)
            self.assertEqual(t.r_multiple, 2.0)  # (2020 - 2000) / (2000 - 1990) = 2.0R

            # Verify notification
            daemon.notify.trade_closed.assert_called_once_with(
                Side.BUY.value, "XAUUSD", 191.0, ExitReason.TAKE_PROFIT.value
            )

            # Verify ExitManager ticket cleaned up
            self.assertNotIn(999, daemon.exits._initial_sl)

            # Idempotency test: calling again should not double insert
            HermesDaemon._reconcile_broker_closed_positions(daemon, [999])
            self.assertEqual(len(ledger.get_trades(limit=10)), 1)

            ledger.close()

    def test_b231_ledger_get_plan_and_by_ticket(self):
        """b231: Ledger.get_plan and get_plan_by_ticket recover saved Plan and SetupGrade."""
        import tempfile
        from pathlib import Path
        from core.db import Ledger
        from core.entities import Plan, Side, SetupGrade, Order, OrderStatus

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_plans.db"
            ledger = Ledger(db_path)

            plan = Plan(
                plan_id="p-alpha-1",
                symbol="XAUUSD",
                side=Side.BUY,
                entry_price=2000.0,
                stop_loss=1990.0,
                take_profit=2025.0,
                volume=0.1,
                grade=SetupGrade.A,
                source="analysis",
                timeframe="M15",
                rr=2.5,
                confidence=0.9,
                reasoning="strong smc confluence",
            )
            ledger.save_plan(plan)

            order = Order(
                order_id="hms-p-alpha-1",
                plan_id="p-alpha-1",
                ticket=777,
                symbol="XAUUSD",
                side=Side.BUY,
                volume=0.1,
                price=2000.0,
                sl=1990.0,
                tp=2025.0,
                status=OrderStatus.FILLED,
            )
            ledger.save_order(order)

            # Lookup by plan_id
            p_by_id = ledger.get_plan("p-alpha-1")
            self.assertIsNotNone(p_by_id)
            assert p_by_id is not None
            self.assertEqual(p_by_id.plan_id, "p-alpha-1")
            self.assertEqual(p_by_id.grade, SetupGrade.A)
            self.assertEqual(p_by_id.stop_loss, 1990.0)

            # Lookup by ticket
            p_by_ticket = ledger.get_plan_by_ticket(777)
            self.assertIsNotNone(p_by_ticket)
            assert p_by_ticket is not None
            self.assertEqual(p_by_ticket.plan_id, "p-alpha-1")
            self.assertEqual(p_by_ticket.grade, SetupGrade.A)

            # Lookup non-existent
            self.assertIsNone(ledger.get_plan("p-missing"))
            self.assertIsNone(ledger.get_plan_by_ticket(99999))

            ledger.close()

    def test_b231_close_position_calculates_r_multiple_and_retains_grade(self):
        """b231: _close_position records true r_multiple and recovers grade from plan."""
        from unittest.mock import MagicMock
        from entry.hermes import HermesDaemon
        from core.entities import BrokerPosition, Side, ExitReason, Plan, SetupGrade
        from core.exits import ExitManager
        from core.params import PositionCfg
        import tempfile
        from pathlib import Path
        from core.db import Ledger

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_close_pos.db"
            ledger = Ledger(db_path)

            plan = Plan(
                plan_id="p-alpha-close",
                symbol="XAUUSD",
                side=Side.BUY,
                entry_price=2000.0,
                stop_loss=1990.0,
                take_profit=2030.0,
                volume=0.1,
                grade=SetupGrade.A,
                source="analysis",
                timeframe="M15",
                rr=3.0,
            )
            ledger.save_plan(plan)

            daemon = MagicMock(spec=HermesDaemon)
            daemon.dry_run = True
            daemon.cfg = MagicMock()
            daemon.cfg.symbol = "XAUUSD"
            daemon.led = ledger
            daemon.notify = MagicMock()
            cfg = PositionCfg(trailing_start_rr=1.5, breakeven_rr=1.0, max_hold_hours=24, partial_tp_rr=1.5, partial_enabled=True)
            daemon.exits = ExitManager(cfg)
            daemon.exits.register_initial_sl(888, 1990.0)
            daemon.mt5 = MagicMock()
            daemon.mt5.close_position.return_value = True
            daemon._tracked_positions = {}

            pos = BrokerPosition(
                ticket=888,
                symbol="XAUUSD",
                side=Side.BUY,
                volume=0.1,
                open_price=2000.0,
                current_price=2015.0,
                sl=2000.15,
                tp=2030.0,
                profit=150.0,
                swap=0.0,
                commission=-0.7,
                open_time=1700000000,
                comment="hms-p-alpha-close",
                initial_sl=1990.0,
            )
            daemon._tracked_positions[888] = pos

            # Execute _close_position with TIME_EXIT
            HermesDaemon._close_position(daemon, pos, ExitReason.TIME_EXIT, 2015.0)

            trades = ledger.get_trades(limit=10)
            self.assertEqual(len(trades), 1)
            t = trades[0]
            self.assertEqual(t.ticket, 888)
            self.assertEqual(t.grade, SetupGrade.A)
            self.assertEqual(t.r_multiple, 1.5)  # (2015 - 2000) / (2000 - 1990) = 1.5R
            self.assertEqual(t.exit_reason, ExitReason.TIME_EXIT)
            self.assertNotIn(888, daemon.exits._initial_sl)
            self.assertNotIn(888, daemon._tracked_positions)

            ledger.close()

    def test_b231_exit_loop_guards_against_none_positions(self):
        """b231: _exit_loop fails closed when positions is None without wiping tracked positions."""
        from unittest.mock import MagicMock
        from entry.hermes import HermesDaemon
        from core.entities import BrokerPosition, Side

        daemon = MagicMock(spec=HermesDaemon)
        daemon.cfg = MagicMock()
        daemon.cfg.symbol = "XAUUSD"
        daemon.dry_run = False
        daemon.mt5 = MagicMock()
        daemon.mt5.get_open_positions.return_value = None  # Bridge down/unreadable
        pos = BrokerPosition(
            ticket=123,
            symbol="XAUUSD",
            side=Side.BUY,
            volume=0.1,
            open_price=2000.0,
            current_price=2005.0,
            sl=1990.0,
            tp=2020.0,
            profit=50.0,
            swap=0.0,
            commission=-0.7,
            open_time=1700000000,
            comment="hms-test",
        )
        daemon._tracked_positions = {123: pos}
        daemon._reconcile_broker_closed_positions = MagicMock()

        HermesDaemon._exit_loop(daemon)

        # Invariant: must not call reconciliation and must keep tracked positions intact
        daemon._reconcile_broker_closed_positions.assert_not_called()
        self.assertIn(123, daemon._tracked_positions)

    def test_b233_daemon_reconciles_and_cleans_dry_run_closed_tickets(self):
        """b233: _exit_loop reconciles disappeared positions and cleans up ticket even in dry_run."""
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock
        from entry.hermes import HermesDaemon
        from core.entities import BrokerPosition, Side, ExitReason
        from core.params import PositionCfg
        from core.exits import ExitManager
        from core.db import Ledger

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_hermes.db"
            ledger = Ledger(db_path)

            daemon = MagicMock(spec=HermesDaemon)
            daemon.cfg = MagicMock()
            daemon.cfg.symbol = "XAUUSD"
            daemon.dry_run = True
            daemon.led = ledger
            daemon.notify = MagicMock()
            cfg = PositionCfg(trailing_start_rr=1.5, breakeven_rr=1.0, max_hold_hours=24, partial_tp_rr=1.5, partial_enabled=True)
            daemon.exits = ExitManager(cfg)
            daemon.exits.register_initial_sl(999, 1990.0)
            daemon.mt5 = MagicMock()
            # positions is empty list -> ticket 999 has disappeared/closed
            daemon.mt5.get_open_positions.return_value = []
            pos = BrokerPosition(
                ticket=999,
                symbol="XAUUSD",
                side=Side.BUY,
                volume=0.1,
                open_price=2000.0,
                current_price=2010.0,
                sl=1990.0,
                tp=2030.0,
                profit=100.0,
                swap=0.0,
                commission=-0.7,
                open_time=1700000000,
                comment="hms-dry-run",
            )
            daemon._tracked_positions = {999: pos}

            # Run real _reconcile_broker_closed_positions
            HermesDaemon._reconcile_broker_closed_positions(daemon, [999])

            # Verify trade recorded in ledger
            trades = ledger.get_trades(limit=10)
            self.assertEqual(len(trades), 1)
            self.assertEqual(trades[0].ticket, 999)
            self.assertEqual(trades[0].pnl, 99.3)  # 100 - 0.7 = 99.3
            self.assertEqual(trades[0].exit_reason, ExitReason.MANUAL)

            # Verify ticket cleanup in ExitManager
            self.assertNotIn(999, daemon.exits._initial_sl)

            ledger.close()


if __name__ == "__main__":
    unittest.main()
