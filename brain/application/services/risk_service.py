"""Risk management service — performance tracking and policy assessment.

Refactored from legacy_v1/engines/risk.py with clean architecture:
- Pure domain logic in entities
- Database integration in service
- Legacy adapter for backward compatibility
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from brain.domain.entities.risk import (
    RiskRegime,
    PerformanceState,
    AccountPolicy,
    RiskBudget,
)
from database import Database, get_db


class RiskService:
    """Service for risk assessment and performance tracking.
    
    Refactored version of legacy risk.py with:
    - Immutable domain entities
    - Database integration
    - Clean separation of concerns
    - Full test coverage
    """
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()
    
    def base_risk_pct(self, balance: float) -> float:
        """Calculate base risk percentage based on account balance.
        
        Rules (legacy, kept identical):
        - < $800: 1%
        - < $1500: 1.5%
        - < $5000: 2%
        - >= $5000: 1.5%
        """
        if balance < 800:
            return 0.01
        if balance < 1500:
            return 0.015
        if balance < 5000:
            return 0.02
        return 0.015
    
    @staticmethod
    def is_entry_deal(deal: dict) -> bool:
        """Check if deal opens exposure (MT5 DEAL_ENTRY_IN = 0)."""
        entry = str(deal.get("entry", "1")).strip().upper()
        return entry in {"0", "IN"}
    
    @staticmethod
    def deal_timestamp(deal: dict) -> Optional[datetime]:
        """Extract timestamp from deal."""
        ts = deal.get("time") or deal.get("time_done")
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None
    
    @staticmethod
    def deal_net_pnl(deal: dict) -> float:
        """Calculate net P&L including commission and swap."""
        def _number(key: str) -> float:
            try:
                return float(deal.get(key, 0) or 0)
            except (TypeError, ValueError):
                return 0.0
        
        return round(
            _number("profit") + _number("commission") + _number("swap"),
            2
        )
    
    def count_entries_today(self, closed_trades: list[dict], today: str) -> int:
        """Count entry deals for today."""
        count = 0
        for deal in closed_trades or []:
            if not self.is_entry_deal(deal):
                continue
            
            stamp = self.deal_timestamp(deal)
            if stamp and stamp.date().isoformat() == today:
                count += 1
        
        return count
    
    def calculate_entry_costs(
        self,
        closed_trades: list[dict]
    ) -> dict[str, tuple[float, float]]:
        """Map position ID to (entry cost, entry volume)."""
        costs: dict[str, tuple[float, float]] = {}
        
        for deal in closed_trades or []:
            if not self.is_entry_deal(deal):
                continue
            
            position = str(
                deal.get("position_id") or deal.get("order") or ""
            ).strip()
            
            if not position:
                continue
            
            fee, volume = costs.get(position, (0.0, 0.0))
            
            try:
                opened_volume = float(deal.get("volume", 0) or 0)
            except (TypeError, ValueError):
                opened_volume = 0.0
            
            costs[position] = (
                fee + self.deal_net_pnl(deal),
                volume + opened_volume
            )
        
        return costs
    
    def exit_net_pnl(
        self,
        deal: dict,
        entry_costs: dict[str, tuple[float, float]]
    ) -> float:
        """Calculate net P&L for exit deal, allocating entry fees."""
        result = self.deal_net_pnl(deal)
        
        position = str(
            deal.get("position_id") or deal.get("order") or ""
        ).strip()
        
        fee, opened_volume = entry_costs.get(position, (0.0, 0.0))
        
        if position and opened_volume > 0:
            try:
                closed_volume = float(deal.get("volume", 0) or 0)
                result += fee * (closed_volume / opened_volume)
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        
        return round(result, 2)
    
    def compute_performance_state(
        self,
        current: Optional[dict],
        today: str,
        balance: float,
        closed_trades: list[dict]
    ) -> PerformanceState:
        """Build performance state from broker deals.
        
        This is the core risk tracking function.
        Calculates daily P&L, streaks, and recent closed deals.
        """
        state = dict(current or {})
        entries_today = self.count_entries_today(closed_trades, today)
        
        # New day reset
        if state.get("day") != today:
            # Filter opening deals for DEFCON (legacy b233b)
            recent_closed = [
                d for d in (closed_trades or [])
                if not self.is_entry_deal(d)
            ][-10:]
            
            return PerformanceState(
                day=today,
                starting_balance=balance,
                daily_pnl=0.0,
                daily_gross_pnl=0.0,
                loss_streak=0,
                trades_today=entries_today,
                last_closed_ticket=state.get("last_closed_ticket"),
                recent_closed=recent_closed,
            )
        
        # Continue existing day
        last_closed_ticket = state.get("last_closed_ticket")
        
        # Check if we need to migrate from old gross P&L format
        migrating_legacy = state.get("pnl_basis") != "net"
        
        if migrating_legacy:
            # Rebuild from scratch using timestamps
            dated_today = [
                t for t in closed_trades
                if (stamp := self.deal_timestamp(t))
                and stamp.date().isoformat() == today
            ]
            new_trades = dated_today if dated_today else list(closed_trades or [])
            running_daily_pnl = 0.0
            running_gross_pnl = 0.0
            loss_streak = 0
        else:
            # Incremental update
            new_trades = [
                t for t in closed_trades
                if last_closed_ticket is None
                or t.get("ticket", 0) > last_closed_ticket
            ]
            running_daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
            running_gross_pnl = float(state.get("daily_gross_pnl", 0.0) or 0.0)
            loss_streak = int(state.get("loss_streak", 0) or 0)
        
        # Process new deals
        entry_costs = self.calculate_entry_costs(closed_trades)
        
        for deal in new_trades:
            # Update daily P&L
            running_daily_pnl = round(
                running_daily_pnl + self.deal_net_pnl(deal),
                2
            )
            
            try:
                running_gross_pnl = round(
                    running_gross_pnl + float(deal.get("profit", 0) or 0),
                    2
                )
            except (TypeError, ValueError):
                pass
            
            # Update loss streak (only for closing deals)
            if not self.is_entry_deal(deal):
                outcome = self.exit_net_pnl(deal, entry_costs)
                
                if outcome < 0:
                    loss_streak += 1
                elif outcome > 0:
                    loss_streak = 0
        
        # Get recent closed deals for DEFCON
        recent_closed = [
            d for d in (closed_trades or [])
            if not self.is_entry_deal(d)
        ][-10:]
        
        # Update last closed ticket
        if new_trades:
            last_closed_ticket = new_trades[-1].get("ticket")
        
        return PerformanceState(
            day=today,
            starting_balance=float(
                state.get("starting_balance", balance) or balance
            ),
            daily_pnl=running_daily_pnl,
            daily_gross_pnl=running_gross_pnl,
            loss_streak=loss_streak,
            trades_today=max(
                entries_today,
                int(state.get("trades_today", 0) or 0)
            ),
            last_closed_ticket=last_closed_ticket,
            recent_closed=recent_closed,
        )
    
    def assess_account_policy(
        self,
        balance: float,
        equity: float,
        free_margin: float,
        margin: float,
        daily_pnl: float,
        loss_streak: int,
        open_positions: int,
    ) -> AccountPolicy:
        """Assess risk policy based on account state.
        
        Rules (legacy, kept identical):
        - LOCKED: 5% drawdown OR -3% daily loss OR margin ratio < 20
        - DEFENSIVE: 2+ loss streak OR -1% daily loss
        - RECOVERY: 2.5% drawdown
        - NORMAL: default
        """
        base = self.base_risk_pct(balance)
        
        drawdown_pct = 0.0
        if balance > 0:
            drawdown_pct = round((balance - equity) / balance, 4)
        
        margin_ratio = 999.0
        if margin > 0:
            margin_ratio = round(free_margin / margin, 2)
        
        reasons = []
        regime = RiskRegime.NORMAL
        trade_allowed = True
        risk_multiplier = 1.0
        
        # Check critical conditions (LOCKED)
        if drawdown_pct >= 0.05 or daily_pnl <= -(balance * 0.03):
            regime = RiskRegime.LOCKED
            trade_allowed = False
            risk_multiplier = 0.0
            reasons.append("drawdown_limit")
        
        # Check defensive conditions
        elif loss_streak >= 2 or daily_pnl <= -(balance * 0.01):
            regime = RiskRegime.DEFENSIVE
            risk_multiplier = 0.75
            reasons.append("recent_losses")
        
        # Check recovery conditions
        elif drawdown_pct >= 0.025:
            regime = RiskRegime.RECOVERY
            risk_multiplier = 0.5
            reasons.append("equity_drawdown")
        
        # Check margin health
        if margin_ratio < 20:
            regime = RiskRegime.LOCKED
            trade_allowed = False
            risk_multiplier = 0.0
            if "margin_health" not in reasons:
                reasons.append("margin_health")
        
        return AccountPolicy(
            balance=balance,
            equity=equity,
            free_margin=free_margin,
            margin=margin,
            open_positions=open_positions,
            drawdown_pct=drawdown_pct,
            margin_ratio=margin_ratio,
            base_risk_pct=base,
            risk_multiplier=risk_multiplier,
            trade_allowed=trade_allowed,
            regime=regime,
            reasons=reasons,
            max_positions_allowed=1,
        )
    
    def recommend_risk_budget(
        self,
        policy: AccountPolicy,
        setup_grade: str
    ) -> RiskBudget:
        """Calculate grade-scaled risk budget.
        
        NOTE: Currently unused by executor (uses learning risk_mult),
        kept for CLI and future paths.
        """
        if not policy.trade_allowed:
            return RiskBudget(
                trade_allowed=False,
                risk_pct=None,
                risk_usd=None,
                reason=policy.reasons[0] if policy.reasons else "policy_block",
                regime=policy.regime,
            )
        
        if policy.open_positions >= policy.max_positions_allowed:
            return RiskBudget(
                trade_allowed=False,
                risk_pct=None,
                risk_usd=None,
                reason="position_limit",
                regime=policy.regime,
            )
        
        # Grade multipliers
        grade_multiplier = {
            "A": 1.0,
            "B": 0.6,
            "C": 0.3,
        }.get(setup_grade, 0.0)
        
        risk_pct = round(
            policy.base_risk_pct * policy.risk_multiplier * grade_multiplier,
            4
        )
        risk_usd = round(policy.balance * risk_pct, 2)
        
        return RiskBudget(
            trade_allowed=risk_pct > 0,
            risk_pct=risk_pct,
            risk_usd=risk_usd,
            reason=None if risk_pct > 0 else "setup_grade_block",
            regime=policy.regime,
        )
