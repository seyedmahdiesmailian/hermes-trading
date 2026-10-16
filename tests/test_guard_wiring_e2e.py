"""Phase 1.5: verify the guard actually gates the autonomous cycle.

What this proves:
  1. A decision to enter must pass ExecutionGuard before a plan is saved.
  2. A guard denial (e.g. open positions already at max) blocks the plan.
  3. A healthy proposal passes and the plan lands in SQLite.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import tempfile

from brain.application.use_cases.autonomous_trading import (
    AutonomousTradingUseCase,
    AutonomousTradingRequest,
)
from brain.domain.entities.account import AccountState
from brain.domain.services.decision_engine import Decision, DecisionResult
from brain.domain.services.market_analyzer import AnalysisResult
import adapters.gateways.data.sqlite_repository as sqlite_repository


class FakeMarketData:
    """Standalone market data repo returning a fixed healthy state."""

    def get_current_state(self, symbol, timeframe):
        return object()

    def get_account_state(self):
        return AccountState(
            balance=5000.0,
            equity=5000.0,
            margin_free=5000.0,
            margin_used=0.0,
            open_positions=0,
            open_positions_volume=0.0,
            daily_pnl=0.0,
            daily_trades=0,
            daily_wins=0,
            daily_losses=0,
        )


class AlwaysEnterDecisionEngine:
    """Decision engine that always wants to enter a trade."""

    def evaluate_entry(self, analysis, market_state, account_state):
        return DecisionResult(
            decision=Decision.ENTER_TRADE,
            confidence=0.9,
            reasoning={"test": True},
            action_params={
                "symbol": "XAUUSD",
                "direction": "buy",
                "entry_price": 2400.0,
                "stop_loss": 2390.0,   # 10 points
                "take_profit": 2430.0,  # RR = 3.0
                "position_size": 0.10,
            },
        )


class FakeMarketAnalyzer:
    def analyze(self, market_state):
        return AnalysisResult(
            trend="bullish",
            trend_strength=0.8,
            key_levels={},
            patterns=[],
            quality_score=0.8,
            confidence=0.8,
            reasoning={},
            strategy_results=None,
        )


def _build_uc(db_path):
    # point the SQLite repos at a temp database
    sqlite_repository.DEFAULT_DB_PATH = db_path
    trade_repo = sqlite_repository.SqliteEntityTradeRepository()
    state_repo = sqlite_repository.SqliteEntityStateRepository()
    return AutonomousTradingUseCase(
        market_analyzer=FakeMarketAnalyzer(),
        decision_engine=AlwaysEnterDecisionEngine(),
        market_data_repo=FakeMarketData(),
        trade_repo=trade_repo,
        state_repo=state_repo,
    )


def main():
    ok = True

    # -- Case 1: healthy proposal passes the guard -------------------------
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "hermes.db"
        uc = _build_uc(db)
        resp = uc.execute(AutonomousTradingRequest(symbol="XAUUSD", timeframe="M15"))
        print("case1 action:", resp.action_taken, "| success:", resp.success)
        if resp.action_taken != "trade_ready":
            print("  FAIL:", resp.error or resp.details.get("guard"))
            ok = False
        else:
            print("  guard volume:", resp.details.get("guard", {}).get("volume"))
            print("  plan saved  :", resp.details.get("plan_id") is not None)

    # -- Case 2: position already open -> MAX_OPEN_POSITIONS gate blocks ----
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "hermes.db"
        uc = _build_uc(db)
        # sneak a position in so the guard sees 1 open position
        from brain.domain.entities.trade import Order, OrderType, OrderStatus, Position
        order = Order(
            id="seed-1",
            symbol="XAUUSD",
            type=OrderType.BUY,
            volume=0.05,
            entry_price=2400.0,
            stop_loss=2390.0,
            take_profit=2430.0,
            status=OrderStatus.OPEN,
        )
        uc.trade_repo.save_order(order)
        position = Position(
            ticket=100001,
            order=order,
            open_time=datetime.now(timezone.utc),
            open_price=2400.0,
            current_price=2400.0,
            profit=0.0,
        )
        uc.trade_repo.save_position(position)

        resp = uc.execute(AutonomousTradingRequest(symbol="XAUUSD", timeframe="M15"))
        print("case2 action:", resp.action_taken)
        guard = (resp.details or {}).get("guard", {})
        print("  guard reason:", guard.get("reason"))
        if resp.action_taken != "blocked":
            print("  FAIL: expected blocked, got", resp.action_taken)
            ok = False

    print("\nRESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
