"""Market Analyzer — Multi-strategy market analysis service.

Orchestrates multiple analysis strategies (SMC, Classic, ML, etc)
and merges their results into a unified analysis.
"""

from dataclasses import dataclass
from typing import Protocol, List, Dict, Any
from abc import ABC, abstractmethod

from brain.domain.entities.market import MarketState


@dataclass
class AnalysisResult:
    """Market analysis output.
    
    Represents the complete analysis of current market state.
    Contains trend, strength, key levels, patterns, and reasoning.
    """
    # Core analysis
    trend: str  # "bullish", "bearish", "ranging"
    trend_strength: float  # 0.0 to 1.0
    
    # Price levels
    key_levels: Dict[str, List[float]]  # {"support": [], "resistance": []}
    
    # Patterns detected
    patterns: List[str]  # List of pattern names
    
    # Quality
    quality_score: float  # 0.0 to 1.0 (overall analysis quality)
    confidence: float  # 0.0 to 1.0 (confidence in this analysis)
    
    # Reasoning
    reasoning: Dict[str, Any]  # Detailed explanation
    
    # Contributing strategies
    strategy_results: List[Dict[str, Any]] | None = None  # Individual strategy outputs
    
    def is_high_quality(self) -> bool:
        """Check if analysis quality is high."""
        return self.quality_score > 0.7
    
    def is_high_confidence(self) -> bool:
        """Check if confidence is high."""
        return self.confidence > 0.7
    
    def is_bullish(self) -> bool:
        return self.trend == "bullish"
    
    def is_bearish(self) -> bool:
        return self.trend == "bearish"
    
    def is_ranging(self) -> bool:
        return self.trend == "ranging"
    
    def has_strong_trend(self) -> bool:
        """Check if trend is strong (strength > 0.7)."""
        return self.trend_strength > 0.7 and not self.is_ranging()
    
    def __repr__(self) -> str:
        trend_emoji = "📈" if self.is_bullish() else "📉" if self.is_bearish() else "↔️"
        quality_emoji = "⭐" if self.is_high_quality() else "✓"
        
        return (
            f"AnalysisResult({trend_emoji} {self.trend} "
            f"strength:{self.trend_strength:.2f} "
            f"{quality_emoji}quality:{self.quality_score:.2f} "
            f"confidence:{self.confidence:.2f})"
        )


class IAnalysisStrategy(Protocol):
    """Strategy interface for different analysis types.
    
    Each strategy (SMC, Classic, ML, etc) implements this interface.
    """
    
    def analyze(self, market_state: MarketState) -> AnalysisResult:
        """Analyze market and return result.
        
        Args:
            market_state: Current market snapshot
            
        Returns:
            AnalysisResult with this strategy's findings
        """
        ...
    
    def get_name(self) -> str:
        """Return strategy name for logging/debugging."""
        ...


class MarketAnalyzer:
    """Market analysis service.
    
    Orchestrates multiple analysis strategies and merges their results.
    This is the "brain" of market analysis.
    
    Usage:
        analyzer = MarketAnalyzer()
        analyzer.add_strategy(SMCStrategy())
        analyzer.add_strategy(ClassicStrategy())
        
        result = analyzer.analyze(market_state)
    """
    
    def __init__(self):
        self._strategies: List[IAnalysisStrategy] = []
        self._weights: Dict[str, float] = {}  # Strategy weights for merging
    
    def add_strategy(self, strategy: IAnalysisStrategy, weight: float = 1.0):
        """Add an analysis strategy.
        
        Args:
            strategy: Analysis strategy (SMC, Classic, ML, etc)
            weight: Weight for merging (default 1.0)
        """
        if weight <= 0:
            raise ValueError(f"Weight must be positive: {weight}")
        
        self._strategies.append(strategy)
        self._weights[strategy.get_name()] = weight
    
    def remove_strategy(self, strategy_name: str):
        """Remove a strategy by name."""
        self._strategies = [
            s for s in self._strategies 
            if s.get_name() != strategy_name
        ]
        self._weights.pop(strategy_name, None)
    
    def analyze(self, market_state: MarketState) -> AnalysisResult:
        """Run all strategies and merge results.
        
        Args:
            market_state: Current market snapshot
            
        Returns:
            Merged analysis result from all strategies
        """
        if not self._strategies:
            raise ValueError("No analysis strategies configured")
        
        # Run all strategies
        results = []
        for strategy in self._strategies:
            try:
                result = strategy.analyze(market_state)
                results.append((strategy.get_name(), result))
            except Exception as e:
                # Log error but continue with other strategies
                print(f"Strategy {strategy.get_name()} failed: {e}")
                continue
        
        if not results:
            raise RuntimeError("All analysis strategies failed")
        
        # Merge results
        return self._merge_results(results, market_state)
    
    def _merge_results(
        self, 
        results: List[tuple[str, AnalysisResult]],
        market_state: MarketState
    ) -> AnalysisResult:
        """Merge multiple analysis results.
        
        Uses weighted voting for trend determination and
        averages for numeric values.
        
        Args:
            results: List of (strategy_name, result) tuples
            market_state: Original market state
            
        Returns:
            Merged AnalysisResult
        """
        if len(results) == 1:
            # Only one strategy, return its result
            return results[0][1]
        
        # Count weighted votes for trend
        trend_votes = {"bullish": 0.0, "bearish": 0.0, "ranging": 0.0}
        total_weight = 0.0
        
        for strategy_name, result in results:
            weight = self._weights.get(strategy_name, 1.0)
            trend_votes[result.trend] += weight
            total_weight += weight
        
        # Determine majority trend
        merged_trend = max(trend_votes.keys(), key=lambda k: trend_votes[k])
        
        # Average numeric values (weighted)
        merged_strength = sum(
            result.trend_strength * self._weights.get(name, 1.0)
            for name, result in results
        ) / total_weight
        
        merged_quality = sum(
            result.quality_score * self._weights.get(name, 1.0)
            for name, result in results
        ) / total_weight
        
        merged_confidence = sum(
            result.confidence * self._weights.get(name, 1.0)
            for name, result in results
        ) / total_weight
        
        # Merge key levels (union of all levels)
        merged_levels = {"support": [], "resistance": []}
        for _, result in results:
            merged_levels["support"].extend(
                result.key_levels.get("support", [])
            )
            merged_levels["resistance"].extend(
                result.key_levels.get("resistance", [])
            )
        
        # Remove duplicates and sort
        merged_levels["support"] = sorted(set(merged_levels["support"]))
        merged_levels["resistance"] = sorted(set(merged_levels["resistance"]))
        
        # Merge patterns
        merged_patterns = []
        for _, result in results:
            merged_patterns.extend(result.patterns)
        merged_patterns = list(set(merged_patterns))  # Remove duplicates
        
        # Build reasoning
        reasoning = {
            "strategies_used": [name for name, _ in results],
            "trend_votes": trend_votes,
            "consensus": trend_votes[merged_trend] / total_weight,
            "contributing_strategies": len(results)
        }
        
        return AnalysisResult(
            trend=merged_trend,
            trend_strength=merged_strength,
            key_levels=merged_levels,
            patterns=merged_patterns,
            quality_score=merged_quality,
            confidence=merged_confidence,
            reasoning=reasoning,
            strategy_results=[r.reasoning for _, r in results]
        )
    
    def get_strategies(self) -> List[str]:
        """Get list of configured strategy names."""
        return [s.get_name() for s in self._strategies]
    
    def __repr__(self) -> str:
        return (
            f"MarketAnalyzer({len(self._strategies)} strategies: "
            f"{', '.join(self.get_strategies())})"
        )
