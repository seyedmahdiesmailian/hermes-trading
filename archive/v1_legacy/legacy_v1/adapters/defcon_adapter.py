"""Legacy adapter for DEFCON — maintains backward compatibility.

Provides the same interface as legacy_v1/engines/defcon.py functions
while using the refactored service layer underneath.

This allows existing code to use the new architecture without changes.
"""
from __future__ import annotations

from typing import Optional

from brain.application.services.defcon_service import DefconService
from database import get_db


# Module-level service instance (singleton pattern from legacy)
_service = DefconService(get_db())


def classify_exit(comment: str, profit: float) -> str:
    """Classify a closed deal by its exit type (legacy interface).
    
    Args:
        comment: MT5 comment field
        profit: Deal profit
    
    Returns:
        Exit type string: 'sl', 'tp', 'managed', or 'unknown'
    """
    exit_type = _service.classify_exit(comment, profit)
    return exit_type.value


def classify_exits(deals: list[dict]) -> list[dict]:
    """Attach exit_type to each deal (legacy interface).
    
    Args:
        deals: List of deal dicts with ticket, profit, comment
    
    Returns:
        List of dicts with added 'exit_type' field
    """
    classified = _service.classify_deals(deals)
    
    # Convert domain entities back to legacy dict format
    return [
        {
            "ticket": deal.ticket,
            "profit": deal.profit,
            "exit_type": deal.exit_type.value,
            "side": deal.side,
        }
        for deal in classified
    ]


def analyze_exits(classified: list[dict]) -> dict:
    """Aggregate exit statistics (legacy interface).
    
    Args:
        classified: List of classified deal dicts
    
    Returns:
        Statistics dict with legacy keys
    """
    # Convert legacy dicts to domain entities
    from brain.domain.entities.defcon import ClosedDeal, ExitType
    
    deals = [
        ClosedDeal(
            ticket=c.get("ticket", 0),
            profit=c.get("profit", 0.0),
            exit_type=ExitType(c.get("exit_type", "unknown")),
            side=c.get("side"),
        )
        for c in classified
    ]
    
    stats = _service.analyze_exits(deals)
    
    # Convert to legacy dict
    return {
        "total": stats.total,
        "sl_count": stats.sl_count,
        "tp_count": stats.tp_count,
        "managed_count": stats.managed_count,
        "managed_win_ratio": stats.managed_win_ratio,
        "managed_total_pnl": stats.managed_total_pnl,
        "sl_ratio": stats.sl_ratio,
        "sl_dominant": stats.sl_dominant,
    }


def compute_insights(
    loss_streak: int = 0,
    daily_pnl: float = 0.0,
    balance: float = 0.0,
    classified: Optional[list[dict]] = None,
) -> dict:
    """Compute DEFCON + allowed actions (legacy interface).
    
    Args:
        loss_streak: Number of consecutive losses
        daily_pnl: Today's P&L
        balance: Account balance (unused but kept for compatibility)
        classified: List of classified deal dicts
    
    Returns:
        Insights dict with legacy keys
    """
    # Convert legacy dicts to domain entities
    from brain.domain.entities.defcon import ClosedDeal, ExitType
    
    deals = None
    if classified:
        deals = [
            ClosedDeal(
                ticket=c.get("ticket", 0),
                profit=c.get("profit", 0.0),
                exit_type=ExitType(c.get("exit_type", "unknown")),
                side=c.get("side"),
            )
            for c in classified
        ]
    
    insights = _service.compute_insights(
        loss_streak=loss_streak,
        daily_pnl=daily_pnl,
        balance=balance,
        classified=deals,
    )
    
    # Convert to legacy dict (using to_dict method)
    return insights.to_dict()


def filter_management_by_insights(
    management: dict,
    insights: Optional[dict],
) -> dict:
    """Legacy management filter (legacy interface).
    
    Args:
        management: Management action dict
        insights: DEFCON insights dict (or None)
    
    Returns:
        Filtered management action dict
    """
    if insights is None:
        return management
    
    # Convert legacy dict to domain entity
    from brain.domain.entities.defcon import DefconLevel, DefconInsights, ExitStatistics
    
    exit_stats_dict = insights.get("exit_stats", {})
    exit_stats = ExitStatistics(
        total=exit_stats_dict.get("total", 0),
        sl_count=exit_stats_dict.get("sl_count", 0),
        tp_count=exit_stats_dict.get("tp_count", 0),
        managed_count=exit_stats_dict.get("managed_count", 0),
        managed_win_ratio=exit_stats_dict.get("managed_win_ratio"),
        managed_total_pnl=exit_stats_dict.get("managed_total_pnl", 0.0),
        sl_ratio=exit_stats_dict.get("sl_ratio", 0.0),
        sl_dominant=exit_stats_dict.get("sl_dominant", False),
    )
    
    insights_entity = DefconInsights(
        level=DefconLevel(insights.get("defcon", "GREEN")),
        risk_multiplier=insights.get("risk_override") or 1.0,
        trade_allowed=insights.get("trade_allowed", True),
        runner_allowed=insights.get("runner_allowed", True),
        scale_in_allowed=insights.get("scale_in_allowed", True),
        exit_stats=exit_stats,
        runner_blocked_reason=insights.get("runner_blocked_reason"),
    )
    
    return _service.filter_management_action(management, insights_entity)
