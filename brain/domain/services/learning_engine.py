"""Learning Engine — Learning from past trades.

Analyzes closed trades and extracts patterns for future decisions.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import json

from brain.domain.services.market_analyzer import AnalysisResult


@dataclass
class TradeOutcome:
    """Closed trade with full context.
    
    Contains everything needed to learn from a trade.
    """
    # Trade identification
    plan_id: str
    ticket: int
    
    # Setup
    setup_grade: str  # A/B/C/D/F
    direction: str    # buy/sell
    
    # Analysis context
    analysis: Dict[str, Any]  # Full analysis at entry
    
    # Execution
    entry_price: float
    stop_loss: float
    take_profit: float
    exit_price: float
    
    # Result
    profit: float
    exit_reason: str  # "tp", "sl", "manual", "time"
    
    # Performance
    mfe: float  # Max Favorable Excursion
    mae: float  # Max Adverse Excursion
    duration_seconds: float
    
    def is_win(self) -> bool:
        return self.profit > 0
    
    def is_loss(self) -> bool:
        return self.profit < 0
    
    def hit_tp(self) -> bool:
        return self.exit_reason == "tp"
    
    def hit_sl(self) -> bool:
        return self.exit_reason == "sl"


@dataclass
class Pattern:
    """Learned pattern.
    
    Represents a recurring setup pattern with performance stats.
    """
    id: str
    features: Dict[str, Any]  # Pattern characteristics
    
    # Performance
    win_rate: float
    avg_profit: float
    sample_size: int
    
    # Metadata
    last_updated: str  # ISO timestamp
    
    def is_reliable(self) -> bool:
        """Check if pattern has enough data to be reliable."""
        return self.sample_size >= 10 and self.win_rate > 0.5
    
    def __repr__(self) -> str:
        return (
            f"Pattern({self.id} WR:{self.win_rate:.1%} "
            f"AvgProfit:{self.avg_profit:.2f} N:{self.sample_size})"
        )


class LearningEngine:
    """Learning from past trades.
    
    Extracts patterns from closed trades and provides insights
    for future decisions.
    
    Usage:
        engine = LearningEngine()
        
        # After trade closes
        outcome = TradeOutcome(...)
        engine.learn_from_trade(outcome)
        
        # Before new trade
        insights = engine.match_patterns(analysis)
    """
    
    def __init__(self):
        self.patterns: List[Pattern] = []
        self.trade_history: List[TradeOutcome] = []
    
    def learn_from_trade(self, outcome: TradeOutcome):
        """Extract lessons from a closed trade.
        
        Args:
            outcome: Closed trade outcome
        """
        # Store in history
        self.trade_history.append(outcome)
        
        # Extract features
        features = self._extract_features(outcome)
        
        # Find similar pattern or create new
        pattern = self._find_similar_pattern(features)
        
        if pattern:
            # Update existing pattern
            self._update_pattern(pattern, outcome)
        else:
            # Create new pattern
            self._create_pattern(features, outcome)
    
    def match_patterns(self, analysis: AnalysisResult) -> Dict[str, Any]:
        """Find matching patterns for current analysis.
        
        Args:
            analysis: Current market analysis
            
        Returns:
            Dict with pattern match info
        """
        if not self.patterns:
            return {'pattern_found': False, 'confidence': 0.5}
        
        # Extract features from analysis
        features = self._extract_features_from_analysis(analysis)
        
        # Find similar patterns
        matches = []
        for pattern in self.patterns:
            similarity = self._similarity(pattern.features, features)
            if similarity > 0.7:  # 70% similarity threshold
                matches.append((pattern, similarity))
        
        if not matches:
            return {'pattern_found': False, 'confidence': 0.5}
        
        # Sort by similarity
        matches.sort(key=lambda x: x[1], reverse=True)
        best_pattern, similarity = matches[0]
        
        # Calculate confidence
        confidence = (
            best_pattern.win_rate * 0.5 +  # Win rate weight
            similarity * 0.3 +              # Similarity weight
            min(best_pattern.sample_size / 20, 1.0) * 0.2  # Sample size weight
        )
        
        return {
            'pattern_found': True,
            'pattern_id': best_pattern.id,
            'win_rate': best_pattern.win_rate,
            'avg_profit': best_pattern.avg_profit,
            'sample_size': best_pattern.sample_size,
            'similarity': similarity,
            'confidence': confidence
        }
    
    def get_recent_performance(self, n: int = 10) -> Dict[str, Any]:
        """Get performance stats for recent N trades.
        
        Args:
            n: Number of recent trades
            
        Returns:
            Dict with performance metrics
        """
        recent = self.trade_history[-n:] if len(self.trade_history) >= n else self.trade_history
        
        if not recent:
            return {}
        
        wins = [t for t in recent if t.is_win()]
        losses = [t for t in recent if t.is_loss()]
        
        return {
            'total_trades': len(recent),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': len(wins) / len(recent) if recent else 0,
            'total_profit': sum(t.profit for t in recent),
            'avg_win': sum(t.profit for t in wins) / len(wins) if wins else 0,
            'avg_loss': sum(t.profit for t in losses) / len(losses) if losses else 0
        }
    
    def _extract_features(self, outcome: TradeOutcome) -> Dict[str, Any]:
        """Extract learnable features from trade outcome.
        
        Args:
            outcome: Trade outcome
            
        Returns:
            Dict of features
        """
        return {
            'grade': outcome.setup_grade,
            'direction': outcome.direction,
            'trend': outcome.analysis.get('trend', 'unknown'),
            'trend_strength': outcome.analysis.get('trend_strength', 0.5),
            'quality_score': outcome.analysis.get('quality_score', 0.5),
            'rr': abs(outcome.take_profit - outcome.entry_price) / 
                  abs(outcome.entry_price - outcome.stop_loss)
        }
    
    def _extract_features_from_analysis(self, analysis: AnalysisResult) -> Dict[str, Any]:
        """Extract features from analysis for pattern matching.
        
        Args:
            analysis: Market analysis
            
        Returns:
            Dict of features
        """
        return {
            'trend': analysis.trend,
            'trend_strength': analysis.trend_strength,
            'quality_score': analysis.quality_score
        }
    
    def _find_similar_pattern(self, features: Dict[str, Any]) -> Optional[Pattern]:
        """Find existing pattern similar to features.
        
        Args:
            features: Feature dict
            
        Returns:
            Pattern if found, None otherwise
        """
        for pattern in self.patterns:
            similarity = self._similarity(pattern.features, features)
            if similarity > 0.85:  # 85% similarity = same pattern
                return pattern
        return None
    
    def _similarity(self, features1: Dict[str, Any], features2: Dict[str, Any]) -> float:
        """Calculate similarity between two feature sets.
        
        Args:
            features1: First feature dict
            features2: Second feature dict
            
        Returns:
            Similarity score (0.0 to 1.0)
        """
        # Simple similarity: count matching features
        common_keys = set(features1.keys()) & set(features2.keys())
        if not common_keys:
            return 0.0
        
        matches = 0
        for key in common_keys:
            val1 = features1[key]
            val2 = features2[key]
            
            if isinstance(val1, str) and isinstance(val2, str):
                if val1 == val2:
                    matches += 1
            elif isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
                # Numeric: consider close values as match
                if abs(val1 - val2) < 0.2:  # Within 20%
                    matches += 1
        
        return matches / len(common_keys)
    
    def _create_pattern(self, features: Dict[str, Any], outcome: TradeOutcome):
        """Create new pattern from trade outcome.
        
        Args:
            features: Pattern features
            outcome: Trade outcome
        """
        from datetime import datetime
        
        pattern = Pattern(
            id=f"pattern_{len(self.patterns) + 1}",
            features=features,
            win_rate=1.0 if outcome.is_win() else 0.0,
            avg_profit=outcome.profit,
            sample_size=1,
            last_updated=datetime.now().isoformat()
        )
        
        self.patterns.append(pattern)
    
    def _update_pattern(self, pattern: Pattern, outcome: TradeOutcome):
        """Update existing pattern with new trade.
        
        Args:
            pattern: Pattern to update
            outcome: New trade outcome
        """
        from datetime import datetime
        
        # Update win rate
        total_wins = pattern.win_rate * pattern.sample_size
        if outcome.is_win():
            total_wins += 1
        
        new_sample_size = pattern.sample_size + 1
        
        # Update pattern (create new since frozen)
        updated = Pattern(
            id=pattern.id,
            features=pattern.features,
            win_rate=total_wins / new_sample_size,
            avg_profit=(
                pattern.avg_profit * pattern.sample_size + outcome.profit
            ) / new_sample_size,
            sample_size=new_sample_size,
            last_updated=datetime.now().isoformat()
        )
        
        # Replace in list
        idx = self.patterns.index(pattern)
        self.patterns[idx] = updated
    
    def __repr__(self) -> str:
        return (
            f"LearningEngine({len(self.patterns)} patterns, "
            f"{len(self.trade_history)} trades)"
        )
