"""Legacy adapter for Risk — maintains backward compatibility.

Provides the same interface as legacy_v1/engines/risk.py functions
while using the refactored service layer underneath.
"""
from __future__ import annotations

from typing import Optional

from brain.application.services.risk_service import RiskService
from database import get_db


# Module-level service instance
_service = RiskService(get_db())


def deal_net_pnl(deal: dict) -> float:
    """Calculate net P&L including commission and swap."""
    return _service.deal_net_pnl(deal)


def compute_performance_state(
    current: dict,
    today: str,
    balance: float,
    closed_trades: list[dict]
) -> dict:
    """Build performance state from broker deals (legacy interface)."""
    state = _service.compute_performance_state(
        current=current,
        today=today,
        balance=balance,
        closed_trades=closed_trades,
    )
    
    # Convert to legacy dict format
    return {
        "day": state.day,
        "starting_balance": state.starting_balance,
        "daily_pnl": state.daily_pnl,
        "daily_gross_pnl": state.daily_gross_pnl,
        "pnl_basis": "net",
        "loss_streak": state.loss_streak,
        "trades_today": state.trades_today,
        "last_closed_ticket": state.last_closed_ticket,
        "recent_closed": state.recent_closed,
    }


def assess_account_policy(
    balance: float,
    equity: float,
    free_margin: float,
    margin: float,
    daily_pnl: float,
    loss_streak: int,
    open_positions: int,
) -> dict:
    """Assess risk policy based on account state (legacy interface)."""
    policy = _service.assess_account_policy(
        balance=balance,
        equity=equity,
        free_margin=free_margin,
        margin=margin,
        daily_pnl=daily_pnl,
        loss_streak=loss_streak,
        open_positions=open_positions,
    )
    
    return policy.to_dict()


def recommend_risk_budget(policy: dict, setup_grade: str) -> dict:
    """Calculate grade-scaled risk budget (legacy interface)."""
    # Convert legacy dict to domain entity
    from brain.domain.entities.risk import AccountPolicy, RiskRegime
    
    policy_entity = AccountPolicy(
        balance=policy["balance"],
        equity=policy["equity"],
        free_margin=policy["free_margin"],
        margin=policy["margin"],
        open_positions=policy["open_positions"],
        drawdown_pct=policy["drawdown_pct"],
        margin_ratio=policy["margin_ratio"],
        base_risk_pct=policy["base_risk_pct"],
        risk_multiplier=policy["risk_multiplier"],
        trade_allowed=policy["trade_allowed"],
        regime=RiskRegime(policy["regime"]),
        reasons=policy["reasons"],
        max_positions_allowed=policy["max_positions_allowed"],
    )
    
    budget = _service.recommend_risk_budget(policy_entity, setup_grade)
    
    return budget.to_dict()
