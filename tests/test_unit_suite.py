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
        import time

        daemon = MagicMock(spec=HermesDaemon)
        daemon.dry_run = False
        daemon.cfg = MagicMock()
        daemon.cfg.symbol = "XAUUSD"
        
        now = time.time()
        # Mock broker deals: profit -200, commission -15, swap -5 -> true net -220
        mock_deals = [
            {"ticket": 1, "time": now - 3600, "entry": 0, "profit": 0.0, "commission": -7.5, "swap": 0.0},
            {"ticket": 2, "time": now - 1800, "entry": 1, "profit": -200.0, "commission": -7.5, "swap": -5.0},
        ]
        daemon.mt5 = MagicMock()
        daemon.mt5.get_history_deals.return_value = mock_deals
        
        net_pnl = HermesDaemon._today_pnl(daemon)
        self.assertEqual(net_pnl, -220.0)

    def test_b210_daemon_today_trades_count_counts_broker_exits(self):
        """b210: HermesDaemon._today_trades_count counts broker exit deals (entry==1)."""
        from unittest.mock import MagicMock
        from entry.hermes import HermesDaemon
        import time

        daemon = MagicMock(spec=HermesDaemon)
        daemon.dry_run = False
        daemon.cfg = MagicMock()
        daemon.cfg.symbol = "XAUUSD"
        daemon.led = MagicMock()
        daemon.led.get_today_trades.return_value = []

        now = time.time()
        # 2 entry deals (entry=0), 2 exit deals (entry=1)
        mock_deals = [
            {"ticket": 1, "time": now - 3600, "entry": 0, "profit": 0.0},
            {"ticket": 2, "time": now - 3500, "entry": 1, "profit": 50.0},
            {"ticket": 3, "time": now - 1800, "entry": 0, "profit": 0.0},
            {"ticket": 4, "time": now - 1700, "entry": 1, "profit": -30.0},
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


if __name__ == "__main__":
    unittest.main()
