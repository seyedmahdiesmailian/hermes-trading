"""Signal Processing Use Case.

UC: Receive signal → Validate → Cross-check → Execute (if approved)
"""

from dataclasses import dataclass
from typing import Dict, Any

from brain.domain.entities.signal import Signal
from brain.domain.services.market_analyzer import MarketAnalyzer
from brain.domain.services.decision_engine import DecisionEngine, Decision
from brain.domain.repositories.market_data_repo import IMarketDataRepository
from brain.domain.repositories.signal_repo import ISignalRepository
from brain.domain.repositories.state_repo import IStateRepository
from brain.domain.value_objects.timeframe import TimeFrame


@dataclass
class ProcessSignalRequest:
    """Request to process a signal."""
    signal: Signal


@dataclass
class ProcessSignalResponse:
    """Response from signal processing."""
    accepted: bool
    reasoning: Dict[str, Any]
    action_taken: str  # "executed", "rejected", "waiting"
    error: str | None = None


class SignalProcessingUseCase:
    """Use Case: Process Telegram signal → validate → cross-check → execute.
    
    This use case handles external signals (from Telegram channels).
    
    Flow:
    1. Validate signal parameters
    2. Fetch current market data
    3. Run our own independent analysis
    4. Cross-validate signal against our analysis
    5. Get account state
    6. Make final decision
    7. Execute if approved
    
    Key principle: NEVER blindly follow signals.
    Always cross-check with our own analysis.
    
    Usage:
        use_case = SignalProcessingUseCase(...dependencies...)
        
        signal = Signal(...)
        request = ProcessSignalRequest(signal=signal)
        
        response = use_case.execute(request)
    """
    
    def __init__(
        self,
        market_analyzer: MarketAnalyzer,
        decision_engine: DecisionEngine,
        market_data_repo: IMarketDataRepository,
        signal_repo: ISignalRepository,
        state_repo: IStateRepository
    ):
        self.market_analyzer = market_analyzer
        self.decision_engine = decision_engine
        self.market_data = market_data_repo
        self.signal_repo = signal_repo
        self.state_repo = state_repo
    
    def execute(self, request: ProcessSignalRequest) -> ProcessSignalResponse:
        """Process incoming signal.
        
        Args:
            request: Signal processing request
            
        Returns:
            ProcessSignalResponse with results
        """
        signal = request.signal
        
        try:
            # 1. Basic validation
            if not self._validate_signal(signal):
                return ProcessSignalResponse(
                    accepted=False,
                    reasoning={'error': 'Invalid signal parameters'},
                    action_taken="rejected"
                )
            
            # 2. Fetch current market data
            # Assume M15 for signals (configurable)
            timeframe = TimeFrame.from_string("M15")
            market_state = self.market_data.get_current_state(
                signal.symbol,
                timeframe
            )
            
            # 3. Run our own analysis
            our_analysis = self.market_analyzer.analyze(market_state)
            
            # 4. Get account state
            account_state = self.state_repo.get_account_state()
            if not account_state:
                return ProcessSignalResponse(
                    accepted=False,
                    reasoning={'error': 'Account state not available'},
                    action_taken="rejected"
                )
            
            # 5. Decision engine evaluates signal
            decision_result = self.decision_engine.evaluate_signal_entry(
                signal=signal,
                our_analysis=our_analysis,
                market_state=market_state,
                account_state=account_state
            )
            
            # 6. Save signal for history
            self.signal_repo.save_signal(signal)
            
            # 7. Act on decision
            if decision_result.decision == Decision.ENTER_TRADE:
                # Would execute via execution port
                # Mark signal as processed
                self.signal_repo.mark_signal_processed(
                    signal.id,
                    {'decision': 'accepted', 'confidence': decision_result.confidence}
                )
                
                return ProcessSignalResponse(
                    accepted=True,
                    reasoning=decision_result.reasoning,
                    action_taken="trade_ready"
                )
            
            else:
                # Rejected or waiting
                self.signal_repo.mark_signal_processed(
                    signal.id,
                    {'decision': decision_result.decision.value, 'reason': decision_result.reasoning}
                )
                
                return ProcessSignalResponse(
                    accepted=False,
                    reasoning=decision_result.reasoning,
                    action_taken="rejected_by_decision_engine"
                )
        
        except Exception as e:
            return ProcessSignalResponse(
                accepted=False,
                reasoning={},
                action_taken="error",
                error=str(e)
            )
    
    def _validate_signal(self, signal: Signal) -> bool:
        """Basic signal validation.
        
        Args:
            signal: Signal to validate
            
        Returns:
            True if valid, False otherwise
        """
        # Check required fields
        if not signal.symbol or not signal.direction:
            return False
        
        if signal.entry_price <= 0:
            return False
        
        if signal.stop_loss <= 0 or signal.take_profit <= 0:
            return False
        
        # Check RR ratio
        if signal.risk_reward_ratio() < 1.0:
            return False
        
        return True
    
    def __repr__(self) -> str:
        return f"SignalProcessingUseCase(analyzer={self.market_analyzer})"
