"""Autonomous Trading Use Case.

UC: Scan market → Analyze → Decide → Execute (if conditions met)
"""

from dataclasses import dataclass
from typing import Dict, Any

from brain.domain.services.market_analyzer import MarketAnalyzer
from brain.domain.services.decision_engine import DecisionEngine, Decision
from brain.domain.repositories.market_data_repo import IMarketDataRepository
from brain.domain.repositories.trade_repo import ITradeRepository
from brain.domain.repositories.state_repo import IStateRepository
from brain.domain.value_objects.timeframe import TimeFrame


@dataclass
class AutonomousTradingRequest:
    """Request to run autonomous trading cycle."""
    symbol: str
    timeframe: str  # Will be converted to TimeFrame


@dataclass
class AutonomousTradingResponse:
    """Response from autonomous trading cycle."""
    success: bool
    action_taken: str  # "trade_opened", "no_action", "waiting"
    details: Dict[str, Any]
    error: str | None = None


class AutonomousTradingUseCase:
    """Use Case: Autonomous market scan → analyze → decide → execute.
    
    This is the main "brain" cycle that runs every N minutes.
    
    Flow:
    1. Fetch current market data
    2. Analyze market (all strategies)
    3. Get account state
    4. Make decision (DecisionEngine)
    5. Execute if decision = ENTER_TRADE
    6. Save plan and report
    
    Usage:
        use_case = AutonomousTradingUseCase(...dependencies...)
        
        request = AutonomousTradingRequest(
            symbol="XAUUSD",
            timeframe="M15"
        )
        
        response = use_case.execute(request)
    """
    
    def __init__(
        self,
        market_analyzer: MarketAnalyzer,
        decision_engine: DecisionEngine,
        market_data_repo: IMarketDataRepository,
        trade_repo: ITradeRepository,
        state_repo: IStateRepository
    ):
        self.market_analyzer = market_analyzer
        self.decision_engine = decision_engine
        self.market_data = market_data_repo
        self.trade_repo = trade_repo
        self.state_repo = state_repo
    
    def execute(self, request: AutonomousTradingRequest) -> AutonomousTradingResponse:
        """Execute the autonomous trading cycle.
        
        Args:
            request: Trading request with symbol and timeframe
            
        Returns:
            AutonomousTradingResponse with results
        """
        try:
            # 1. Fetch market data
            timeframe = TimeFrame.from_string(request.timeframe)
            market_state = self.market_data.get_current_state(
                request.symbol,
                timeframe
            )
            
            # 2. Analyze market
            analysis = self.market_analyzer.analyze(market_state)
            
            # 3. Get account state
            # Get from MT5 directly (state_repo is for persistence)
            account_state = self.market_data.get_account_state()
            if not account_state:
                return AutonomousTradingResponse(
                    success=False,
                    action_taken="error",
                    details={},
                    error="Account state not available"
                )
            
            # 4. Make decision
            decision_result = self.decision_engine.evaluate_entry(
                analysis=analysis,
                market_state=market_state,
                account_state=account_state
            )
            
            # 5. Act on decision
            if decision_result.decision == Decision.ENTER_TRADE:
                from brain.domain.entities.plan import TradingPlan, SetupGrade, PlanStage
                from brain.domain.services.execution_guard import (
                    ExecutionGuard,
                    PerformanceState,
                    ProposalInput,
)
                from brain.domain.services.execution_guard import (
                    AccountState as GuardAccountState,
)
                from datetime import datetime
                from decimal import Decimal

                # Build plan from decision
                params = decision_result.action_params
                if not params:
                    return AutonomousTradingResponse(
                        success=False,
                        action_taken="error",
                        details={},
                        error="No action params from decision"
                    )

                # -- ExecutionGuard: fail-closed safety gate ------------------
                # Until now the plan went straight to save_plan() with zero
                # gates. Every entry must pass the guard first.
                try:
                    open_positions = len(
                        self.trade_repo.get_open_positions(symbol=request.symbol)
                    )
                except Exception:
                    # fail-closed: unreadable positions -> no trade
                    return AutonomousTradingResponse(
                        success=False,
                        action_taken="blocked",
                        details={},
                        error="Open positions unreadable — refusing to trade"
                    )

                guard = ExecutionGuard()
                proposal = ProposalInput(
                    side=str(params['direction']).upper(),
                    entry=Decimal(str(params['entry_price'])),
                    sl=Decimal(str(params['stop_loss'])),
                    tp=Decimal(str(params['take_profit'])),
                    symbol=params['symbol'],
                    grade=SetupGrade.B.value,
                    execution_style="",
                    blocked_by_macro=False,
                    contract_size=Decimal("100"),  # XAUUSD: 1 lot = 100 oz
                )
                guard_account = GuardAccountState(
                    balance=Decimal(str(account_state.balance or 0)),
                    regime="normal",
                    trade_allowed=True,
                    open_positions=open_positions,
                    positions_unreadable=False,
                    history_ok=True,
                )
                guard_performance = PerformanceState(
                    daily_pnl=Decimal(str(account_state.daily_pnl or 0)),
                    trades_today=int(account_state.daily_trades or 0),
                    loss_streak=0,
                    recent_closed=[],
                )
                verdict = guard.evaluate(
                    proposal=proposal,
                    account=guard_account,
                    performance=guard_performance,
                )

                if not verdict.allowed:
                    # fail-closed: gate error blocks entry, never allows through
                    return AutonomousTradingResponse(
                        success=True,
                        action_taken="blocked",
                        details={
                            'guard': {
                                'reason': verdict.reason,
                                'reasons': list(verdict.all_reasons),
                                'gate_errors': verdict.gate_errors,
                            },
                            'decision': {
                                'confidence': decision_result.confidence,
                                'reasoning': decision_result.reasoning
                            }
                        }
                    )

                plan = TradingPlan(
                    symbol=params['symbol'],
                    direction=params['direction'],
                    entry_price=params['entry_price'],
                    stop_loss=params['stop_loss'],
                    take_profit=params['take_profit'],
                    position_size=float(verdict.volume),
                    setup_grade=SetupGrade.B,  # From analysis
                    reasoning=decision_result.reasoning,
                    stage=PlanStage.READY
                )

                # Save plan
                self.trade_repo.save_plan(plan)

                return AutonomousTradingResponse(
                    success=True,
                    action_taken="trade_ready",
                    details={
                        'analysis': {
                            'trend': analysis.trend,
                            'strength': analysis.trend_strength,
                            'quality': analysis.quality_score
                        },
                        'decision': {
                            'confidence': decision_result.confidence,
                            'reasoning': decision_result.reasoning
                        },
                        'guard': {
                            'risk_pct': float(verdict.risk_pct),
                            'volume': float(verdict.volume),
                        },
                        'plan_id': plan.id
                    }
                )
            
            elif decision_result.decision == Decision.WAIT:
                return AutonomousTradingResponse(
                    success=True,
                    action_taken="waiting",
                    details={
                        'analysis': {
                            'trend': analysis.trend,
                            'quality': analysis.quality_score
                        },
                        'decision': {
                            'confidence': decision_result.confidence,
                            'reasoning': decision_result.reasoning
                        }
                    }
                )
            
            else:  # REJECT
                return AutonomousTradingResponse(
                    success=True,
                    action_taken="no_action",
                    details={
                        'decision': decision_result.decision.value,
                        'reasoning': decision_result.reasoning
                    }
                )
        
        except Exception as e:
            return AutonomousTradingResponse(
                success=False,
                action_taken="error",
                details={},
                error=str(e)
            )
    
    def __repr__(self) -> str:
        return f"AutonomousTradingUseCase(analyzer={self.market_analyzer})"
