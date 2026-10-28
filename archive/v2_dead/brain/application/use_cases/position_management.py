"""Position Management Use Case.

UC: Monitor open positions → Evaluate → Adjust/Close
"""

from dataclasses import dataclass
from typing import Dict, Any, List

from brain.domain.entities.trade import Position
from brain.domain.entities.plan import TradingPlan
from brain.domain.services.decision_engine import DecisionEngine, Decision
from brain.domain.repositories.market_data_repo import IMarketDataRepository
from brain.domain.repositories.trade_repo import ITradeRepository
from brain.domain.value_objects.timeframe import TimeFrame


@dataclass
class ManagePositionRequest:
    """Request to manage positions."""
    symbol: str = "XAUUSD"  # Optional filter


@dataclass
class ManagePositionResponse:
    """Response from position management."""
    success: bool
    positions_managed: int
    actions_taken: List[Dict[str, Any]]
    error: str | None = None


class PositionManagementUseCase:
    """Use Case: Monitor and manage open positions.
    
    This use case runs frequently (every 5 seconds) to manage
    open positions in real-time.
    
    Flow:
    1. Get all open positions
    2. For each position:
       a. Get current market state
       b. Evaluate if action needed (exit, modify)
       c. Execute action if needed
    3. Update position tracking
    
    Actions:
    - Move to breakeven
    - Partial profit taking
    - Trail stop loss
    - Emergency close
    
    Usage:
        use_case = PositionManagementUseCase(...dependencies...)
        
        request = ManagePositionRequest(symbol="XAUUSD")
        response = use_case.execute(request)
    """
    
    def __init__(
        self,
        decision_engine: DecisionEngine,
        market_data_repo: IMarketDataRepository,
        trade_repo: ITradeRepository
    ):
        self.decision_engine = decision_engine
        self.market_data = market_data_repo
        self.trade_repo = trade_repo
    
    def execute(self, request: ManagePositionRequest) -> ManagePositionResponse:
        """Execute position management cycle.
        
        Args:
            request: Management request
            
        Returns:
            ManagePositionResponse with results
        """
        try:
            # 1. Get open positions
            positions = self.trade_repo.get_open_positions(
                symbol=request.symbol if request.symbol else None
            )
            
            if not positions:
                return ManagePositionResponse(
                    success=True,
                    positions_managed=0,
                    actions_taken=[]
                )
            
            actions_taken = []
            
            # 2. Manage each position
            for position in positions:
                try:
                    action = self._manage_position(position)
                    if action:
                        actions_taken.append(action)
                except Exception as e:
                    # Log error but continue with other positions
                    actions_taken.append({
                        'ticket': position.ticket,
                        'error': str(e)
                    })
            
            return ManagePositionResponse(
                success=True,
                positions_managed=len(positions),
                actions_taken=actions_taken
            )
        
        except Exception as e:
            return ManagePositionResponse(
                success=False,
                positions_managed=0,
                actions_taken=[],
                error=str(e)
            )
    
    def _manage_position(self, position: Position) -> Dict[str, Any] | None:
        """Manage a single position.
        
        Args:
            position: Position to manage
            
        Returns:
            Action dict if action taken, None otherwise
        """
        # Get current market state
        timeframe = TimeFrame.from_string("M15")
        market_state = self.market_data.get_current_state(
            position.order.symbol,
            timeframe
        )
        
        # Get associated plan
        # (Would need to fetch from trade_repo based on position)
        # For now, create a minimal plan object
        from brain.domain.entities.plan import TradingPlan, SetupGrade, PlanStage
        from datetime import datetime
        
        # Reconstruct plan from position
        plan = TradingPlan(
            symbol=position.order.symbol,
            direction="buy" if position.order.is_buy() else "sell",
            entry_price=position.open_price,
            stop_loss=position.order.stop_loss,
            take_profit=position.order.take_profit,
            position_size=position.order.volume,
            setup_grade=SetupGrade.B,
            reasoning={},
            stage=PlanStage.MONITORING
        )
        plan.mark_executed(position.ticket, position.open_price)
        
        # Evaluate exit/modification
        decision_result = self.decision_engine.evaluate_exit(
            plan=plan,
            current_profit=position.profit,
            market_state=market_state
        )
        
        # Act on decision
        if decision_result.decision == Decision.EXIT_TRADE:
            # Would execute close via execution port
            return {
                'ticket': position.ticket,
                'action': 'close_requested',
                'reason': decision_result.reasoning,
                'confidence': decision_result.confidence
            }
        
        elif decision_result.decision == Decision.MODIFY_TRADE:
            # Would modify SL/TP via execution port
            return {
                'ticket': position.ticket,
                'action': 'modify_requested',
                'reason': decision_result.reasoning
            }
        
        # No action needed
        return None
    
    def __repr__(self) -> str:
        return f"PositionManagementUseCase(engine={self.decision_engine})"
