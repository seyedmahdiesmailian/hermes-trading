"""Decision Engine — Core decision-making service.

Makes autonomous trading decisions based on analysis, risk, and learning.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional

from brain.domain.entities.market import MarketState
from brain.domain.entities.account import AccountState
from brain.domain.entities.signal import Signal
from brain.domain.entities.plan import TradingPlan
from brain.domain.services.market_analyzer import AnalysisResult
from brain.domain.services.risk_manager import RiskManager
from brain.domain.services.learning_engine import LearningEngine


class Decision(Enum):
    """Trading decision types."""
    ENTER_TRADE = "enter"
    EXIT_TRADE = "exit"
    MODIFY_TRADE = "modify"
    WAIT = "wait"
    REJECT = "reject"


@dataclass
class DecisionResult:
    """Decision output.
    
    Contains the decision, confidence, reasoning, and action parameters.
    """
    decision: Decision
    confidence: float  # 0.0 to 1.0
    reasoning: Dict[str, Any]  # Detailed explanation
    action_params: Dict[str, Any] | None = None  # Parameters for the action
    
    def should_execute(self) -> bool:
        """Check if decision should be executed."""
        return self.decision == Decision.ENTER_TRADE and self.confidence > 0.6
    
    def __repr__(self) -> str:
        emoji = {
            Decision.ENTER_TRADE: "✅",
            Decision.EXIT_TRADE: "🚪",
            Decision.MODIFY_TRADE: "✏️",
            Decision.WAIT: "⏳",
            Decision.REJECT: "❌"
        }.get(self.decision, "❓")
        
        return (
            f"DecisionResult({emoji} {self.decision.value} "
            f"confidence:{self.confidence:.2f})"
        )


class DecisionEngine:
    """Core decision-making engine.
    
    Makes autonomous trading decisions like a professional trader:
    - Multi-factor evaluation
    - Risk assessment
    - Learning integration
    - Context awareness
    
    This is the "brain" that decides whether to trade or not.
    """
    
    def __init__(
        self,
        risk_manager: RiskManager,
        learning_engine: Optional[LearningEngine] = None
    ):
        self.risk_manager = risk_manager
        self.learning_engine = learning_engine
    
    def evaluate_entry(
        self,
        analysis: AnalysisResult,
        market_state: MarketState,
        account_state: AccountState
    ) -> DecisionResult:
        """Decide whether to enter a trade based on analysis.
        
        Multi-factor evaluation:
        1. Analysis quality
        2. Risk acceptability
        3. Market conditions
        4. Learned patterns (if available)
        5. Timing
        
        Args:
            analysis: Market analysis result
            market_state: Current market state
            account_state: Current account state
            
        Returns:
            DecisionResult with decision and reasoning
        """
        # Evaluate each factor
        factors = {}
        
        # 1. Analysis quality
        factors['analysis_quality'] = self._score_analysis(analysis)
        
        # 2. Risk check
        risk_ok = self.risk_manager.check_risk(account_state)
        factors['risk_acceptable'] = 1.0 if risk_ok else 0.0
        
        # 3. Market conditions
        factors['market_conditions'] = self._check_market_conditions(
            market_state, 
            analysis
        )
        
        # 4. Learned patterns (if available)
        if self.learning_engine:
            pattern_match = self.learning_engine.match_patterns(analysis)
            factors['learned_patterns'] = pattern_match.get(
                'confidence', 
                0.5
            )
        else:
            factors['learned_patterns'] = 0.5  # Neutral
        
        # 5. Timing
        factors['timing'] = self._check_timing(market_state)
        
        # Make decision based on weighted factors
        decision, confidence = self._make_decision(factors)
        
        # Build action parameters if entering trade
        action_params = None
        if decision == Decision.ENTER_TRADE:
            action_params = self._build_action_params(
                analysis,
                market_state,
                account_state
            )
        
        return DecisionResult(
            decision=decision,
            confidence=confidence,
            reasoning=factors,
            action_params=action_params
        )
    
    def evaluate_signal_entry(
        self,
        signal: Signal,
        our_analysis: AnalysisResult,
        market_state: MarketState,
        account_state: AccountState
    ) -> DecisionResult:
        """Decide whether to trade a signal.
        
        Cross-validates signal against our own analysis.
        
        Args:
            signal: Trading signal
            our_analysis: Our independent analysis
            market_state: Current market state
            account_state: Current account state
            
        Returns:
            DecisionResult
        """
        factors = {}
        
        # 1. Signal quality
        factors['signal_quality'] = signal.confidence_score
        
        # 2. Direction agreement
        direction_match = (
            (signal.is_buy() and our_analysis.is_bullish()) or
            (signal.is_sell() and our_analysis.is_bearish())
        )
        factors['direction_match'] = 1.0 if direction_match else 0.0
        
        # 3. RR acceptable
        rr_ok = signal.risk_reward_ratio() >= self.risk_manager.params.min_risk_reward
        factors['rr_acceptable'] = 1.0 if rr_ok else 0.0
        
        # 4. Our analysis quality
        factors['our_analysis_quality'] = our_analysis.quality_score
        
        # 5. Risk check
        risk_ok = self.risk_manager.check_risk(account_state)
        factors['risk_acceptable'] = 1.0 if risk_ok else 0.0
        
        # 6. Timing
        factors['timing'] = self._check_timing(market_state)
        
        # Make decision
        decision, confidence = self._make_decision(factors)
        
        # Build action params from signal
        action_params = None
        if decision == Decision.ENTER_TRADE:
            position_size = self.risk_manager.calculate_position_size(
                account_state,
                signal.entry_price,
                signal.stop_loss
            )
            
            action_params = {
                'symbol': signal.symbol,
                'direction': signal.direction,
                'entry_price': signal.entry_price,
                'stop_loss': signal.stop_loss,
                'take_profit': signal.take_profit,
                'position_size': position_size,
                'source': 'signal',
                'signal_id': signal.id
            }
        
        return DecisionResult(
            decision=decision,
            confidence=confidence,
            reasoning=factors,
            action_params=action_params
        )
    
    def evaluate_exit(
        self,
        plan: TradingPlan,
        current_profit: float,
        market_state: MarketState
    ) -> DecisionResult:
        """Decide whether to exit/modify a position.
        
        Args:
            plan: Original trading plan
            current_profit: Current P&L
            market_state: Current market state
            
        Returns:
            DecisionResult
        """
        factors = {}
        
        # 1. Profit target reached
        profit_pct = (current_profit / plan.risk_amount()) * 100
        if profit_pct >= 80:  # Near TP
            factors['near_target'] = 1.0
        else:
            factors['near_target'] = profit_pct / 100
        
        # 2. Stop loss proximity
        # (Would need current price from market_state)
        factors['sl_risk'] = 0.5  # Placeholder
        
        # 3. Time in trade
        age_hours = plan.age_seconds() / 3600
        if age_hours > 24:  # Long hold
            factors['time_factor'] = 0.8
        else:
            factors['time_factor'] = 0.5
        
        # Simple decision for now
        if factors['near_target'] > 0.9:
            decision = Decision.EXIT_TRADE
            confidence = 0.9
        else:
            decision = Decision.WAIT
            confidence = 0.6
        
        return DecisionResult(
            decision=decision,
            confidence=confidence,
            reasoning=factors
        )
    
    def _score_analysis(self, analysis: AnalysisResult) -> float:
        """Score analysis quality.
        
        Returns score 0.0 to 1.0
        """
        # Weighted combination
        return (
            analysis.quality_score * 0.5 +
            analysis.confidence * 0.3 +
            analysis.trend_strength * 0.2
        )
    
    def _check_market_conditions(
        self,
        market_state: MarketState,
        analysis: AnalysisResult
    ) -> float:
        """Check if market conditions are favorable.
        
        Returns score 0.0 to 1.0
        """
        score = 0.5  # Start neutral
        
        # Strong trend is good
        if analysis.has_strong_trend():
            score += 0.3
        
        # High quality analysis is good
        if analysis.is_high_quality():
            score += 0.2
        
        return min(1.0, score)
    
    def _check_timing(self, market_state: MarketState) -> float:
        """Check if timing is good.
        
        Returns score 0.0 to 1.0
        """
        # Placeholder - would check:
        # - Market hours (killzone)
        # - Volume
        # - Volatility
        # - News schedule
        
        return 0.7  # Default to acceptable
    
    def _make_decision(
        self,
        factors: Dict[str, float]
    ) -> tuple[Decision, float]:
        """Make decision based on weighted factors.
        
        Weights:
        - analysis_quality: 30%
        - risk_acceptable: 30%
        - market_conditions: 20%
        - learned_patterns: 10%
        - timing: 10%
        
        Args:
            factors: Dict of factor scores (0-1)
            
        Returns:
            (Decision, confidence)
        """
        weights = {
            'analysis_quality': 0.30,
            'risk_acceptable': 0.30,
            'market_conditions': 0.20,
            'learned_patterns': 0.10,
            'timing': 0.10,
            'direction_match': 0.20,  # For signals
            'signal_quality': 0.15,
            'rr_acceptable': 0.15,
            'our_analysis_quality': 0.10
        }
        
        # Calculate weighted score
        total_weight = 0.0
        weighted_sum = 0.0
        
        for factor_name, factor_score in factors.items():
            weight = weights.get(factor_name, 0.05)  # Default small weight
            weighted_sum += factor_score * weight
            total_weight += weight
        
        # Normalize
        overall_score = weighted_sum / total_weight if total_weight > 0 else 0.0
        
        # Decision thresholds
        if factors.get('risk_acceptable', 0) == 0:
            # Risk check failed - immediate reject
            return (Decision.REJECT, 0.9)
        
        if overall_score >= 0.50:  # LOWERED FOR TESTING
            return (Decision.ENTER_TRADE, overall_score)
        elif overall_score >= 0.50:
            return (Decision.WAIT, overall_score)
        else:
            return (Decision.REJECT, 1.0 - overall_score)
    
    def _build_action_params(
        self,
        analysis: AnalysisResult,
        market_state: MarketState,
        account_state: AccountState
    ) -> Dict[str, Any]:
        """Build action parameters for trade execution.
        
        Args:
            analysis: Market analysis
            market_state: Current market
            account_state: Account state
            
        Returns:
            Dict with trade parameters
        """
        # Determine direction
        direction = "buy" if analysis.is_bullish() else "sell"
        
        # Entry price (current price)
        entry_price = market_state.current_price
        
        # Stop loss (placeholder - would use analysis levels)
        sl_distance = 20.0  # Points
        if direction == "buy":
            stop_loss = entry_price - sl_distance
        else:
            stop_loss = entry_price + sl_distance
        
        # Take profit (2:1 RR minimum)
        tp_distance = sl_distance * self.risk_manager.params.min_risk_reward
        if direction == "buy":
            take_profit = entry_price + tp_distance
        else:
            take_profit = entry_price - tp_distance
        
        # Position size
        position_size = self.risk_manager.calculate_position_size(
            account_state,
            entry_price,
            stop_loss
        )
        
        return {
            'symbol': market_state.symbol,
            'direction': direction,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'position_size': position_size,
            'source': 'autonomous',
            'analysis': analysis.reasoning
        }
    
    def __repr__(self) -> str:
        learning = "with learning" if self.learning_engine else "no learning"
        return f"DecisionEngine({learning}, {self.risk_manager.params})"
