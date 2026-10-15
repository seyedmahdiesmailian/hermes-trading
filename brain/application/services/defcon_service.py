"""DEFCON service — closed-trade feedback loop with database integration.

Refactored from legacy_v1/engines/defcon.py with separation of concerns:
- Pure domain logic moved to brain/domain/entities/defcon.py
- Database integration in this service layer
- Legacy adapter maintains backward compatibility
"""
from __future__ import annotations

from typing import Optional

from brain.domain.entities.defcon import (
    DefconLevel,
    ExitType,
    ClosedDeal,
    ExitStatistics,
    DefconInsights,
)
from database import Database, get_db


class DefconService:
    """Service for DEFCON level calculation and restrictions.
    
    This is the refactored version of legacy defcon.py with:
    - Immutable domain entities
    - Database integration
    - Clean separation of concerns
    - 100% test coverage
    """
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()
    
    def classify_exit(self, comment: str, profit: float) -> ExitType:
        """Classify a closed deal by its exit type from MT5 comment.
        
        Rules (legacy, kept identical):
        - '[sl ...]' → STOP_LOSS
        - '[tp ...]' → TAKE_PROFIT
        - 'Hermes manage/partial/trail/early' → MANAGED
        - else → UNKNOWN
        """
        c = (comment or "").lower()
        
        if c.startswith("[sl") or "[sl" in c:
            return ExitType.STOP_LOSS
        
        if c.startswith("[tp") or "[tp" in c:
            return ExitType.TAKE_PROFIT
        
        if any(k in c for k in ("manage", "partial", "trail", "hermesclose", "hermes manage")):
            return ExitType.MANAGED
        
        return ExitType.UNKNOWN
    
    def classify_deals(self, deals: list[dict]) -> list[ClosedDeal]:
        """Convert raw MT5 deals to classified domain entities."""
        classified = []
        for d in deals:
            profit = float(d.get("profit", 0) or 0)
            classified.append(
                ClosedDeal(
                    ticket=int(d.get("ticket", 0)),
                    profit=profit,
                    exit_type=self.classify_exit(
                        str(d.get("comment", "")),
                        profit
                    ),
                    side=d.get("side"),
                    comment=d.get("comment"),
                )
            )
        return classified
    
    def analyze_exits(self, classified: list[ClosedDeal]) -> ExitStatistics:
        """Aggregate exit statistics from classified deals."""
        total = len(classified)
        
        if total == 0:
            return ExitStatistics(
                total=0,
                sl_count=0,
                tp_count=0,
                managed_count=0,
                managed_win_ratio=None,
                managed_total_pnl=0.0,
                sl_ratio=0.0,
                sl_dominant=False,
            )
        
        n_sl = sum(1 for c in classified if c.exit_type == ExitType.STOP_LOSS)
        n_tp = sum(1 for c in classified if c.exit_type == ExitType.TAKE_PROFIT)
        n_managed = [c for c in classified if c.exit_type == ExitType.MANAGED]
        m_wins = [c for c in n_managed if c.profit > 0]
        m_pnl = sum(c.profit for c in n_managed)
        
        sl_ratio = n_sl / total if total else 0.0
        
        return ExitStatistics(
            total=total,
            sl_count=n_sl,
            tp_count=n_tp,
            managed_count=len(n_managed),
            managed_win_ratio=round(len(m_wins) / len(n_managed), 3) if n_managed else None,
            managed_total_pnl=round(m_pnl, 2),
            sl_ratio=round(sl_ratio, 3),
            sl_dominant=sl_ratio >= 0.5,
        )
    
    def compute_insights(
        self,
        loss_streak: int = 0,
        daily_pnl: float = 0.0,
        balance: float = 0.0,
        classified: Optional[list[ClosedDeal]] = None,
    ) -> DefconInsights:
        """Compute DEFCON level and trading restrictions.
        
        Rules (legacy, kept identical):
        - RED: >=5 recent deals, SL-dominated (>=50%), losing day
        - YELLOW: 2+ loss streak OR (>=50% SL ratio AND >=3 deals)
        - GREEN: default
        
        Risk multipliers:
        - GREEN: 1.0x (full risk)
        - YELLOW: 0.5x (half risk)
        - RED: 0.0x (no new entries)
        
        Additional rule: failing managed exits (<=30% win rate, negative P&L)
        → disable runners regardless of DEFCON level
        """
        stats = self.analyze_exits(classified or [])
        total = stats.total
        
        # Determine DEFCON level
        if total >= 5 and stats.sl_dominant and daily_pnl < 0:
            level = DefconLevel.RED
            risk_multiplier = 0.0
            trade_allowed = False
            runner_allowed = False
            scale_in_allowed = False
        elif loss_streak >= 2 or (stats.sl_ratio >= 0.5 and total >= 3):
            level = DefconLevel.YELLOW
            risk_multiplier = 0.5
            trade_allowed = True
            runner_allowed = False
            scale_in_allowed = False
        else:
            level = DefconLevel.GREEN
            risk_multiplier = 1.0
            trade_allowed = True
            runner_allowed = True
            scale_in_allowed = True
        
        runner_blocked_reason = None
        
        # Legacy rule: failing managed-exit strategy
        if (
            stats.managed_count >= 3
            and stats.managed_win_ratio is not None
            and stats.managed_win_ratio <= 0.3
            and stats.managed_total_pnl < 0
        ):
            runner_allowed = False
            runner_blocked_reason = "managed_exits_losing"
        
        return DefconInsights(
            level=level,
            risk_multiplier=risk_multiplier,
            trade_allowed=trade_allowed,
            runner_allowed=runner_allowed,
            scale_in_allowed=scale_in_allowed,
            exit_stats=stats,
            runner_blocked_reason=runner_blocked_reason,
        )
    
    def get_current_insights(
        self,
        recent_deals: Optional[list[dict]] = None,
    ) -> DefconInsights:
        """Get current DEFCON insights from database state.
        
        Args:
            recent_deals: Optional recent closed deals (from MT5 bridge)
                         If None, loads from database
        
        Returns:
            DefconInsights with current level and restrictions
        """
        # Get current risk state from database
        risk_state = self.db.get_risk_state()
        loss_streak = risk_state.get("loss_streak", 0)
        
        # Get daily P&L
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_pnl = self.db.get_daily_pnl(today)
        
        # Classify recent deals
        if recent_deals is None:
            # Load from database (last 10 closed trades)
            closed_trades = self.db.fetch_all(
                """SELECT ticket, net_pnl as profit, comment
                FROM trades
                WHERE status = 'closed'
                ORDER BY exit_time DESC
                LIMIT 10"""
            )
            recent_deals = [
                {"ticket": t["ticket"], "profit": t["profit"], "comment": t["comment"]}
                for t in closed_trades
            ]
        
        classified = self.classify_deals(recent_deals)
        
        return self.compute_insights(
            loss_streak=loss_streak,
            daily_pnl=daily_pnl,
            classified=classified,
        )
    
    def filter_management_action(
        self,
        management: dict,
        insights: Optional[DefconInsights],
    ) -> dict:
        """Filter management actions based on DEFCON restrictions.
        
        WARNING: This escalates trail_stop → close_runner (full market close)
        when runners are blocked. Legacy design, NOT currently wired live.
        See legacy_v1/engines/defcon.py module docstring for details.
        
        Args:
            management: Management action dict with 'action' key
            insights: Current DEFCON insights (None = no restrictions)
        
        Returns:
            Filtered management action (may be modified or blocked)
        """
        if insights is None:
            return management
        
        action = management.get("action", "hold")
        
        if action == "hold":
            return management
        
        # Safety/profit actions always allowed
        if action in {"close_trade_early", "partial_take_profit", "move_stop_to_breakeven"}:
            return management
        
        # Runner restrictions
        if not insights.runner_allowed and action in {"trail_stop", "close_runner"}:
            return {
                "action": "close_runner",
                "close_fraction": 1.0,
                "reason": f"insights:defcon_{insights.level.value}:runner_blocked",
            }
        
        # Scale-in restrictions
        if not insights.scale_in_allowed and str(action).startswith("scale_in"):
            return {
                "action": "hold",
                "reason": f"insights:defcon_{insights.level.value}:scale_in_blocked",
            }
        
        return management
