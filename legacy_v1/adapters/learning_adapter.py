"""Legacy adapter for Learning — maintains backward compatibility.

Provides the same interface as legacy_v1/engines/learning.py functions
while using the refactored service layer underneath.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from brain.application.services.learning_service import LearningService
from brain.domain.entities.learning import (
    SetupGrade,
    LearningState,
)
from database import get_db


# Module-level service instance
_service = LearningService(get_db())


def position_count(rows: list[dict]) -> int:
    """Count distinct positions from journal rows."""
    positions = _service.group_positions(rows)
    return len(positions)


def group_positions(rows: list[dict]) -> dict[str, dict]:
    """Aggregate journal rows into per-position results (legacy dict format)."""
    positions = _service.group_positions(rows)
    
    # Convert to legacy dict format
    return {
        key: {
            'profit': pos.profit,
            'net': pos.net_pnl,
            'volume': pos.volume,
            'close_time': pos.close_time,
            'side': pos.side,
            'legs': pos.legs,
        }
        for key, pos in positions.items()
    }


def analyze(
    rows: Optional[list[dict]] = None,
    exec_log_path: Optional[Path] = None,
    plan_dir: Optional[Path] = None,
) -> dict:
    """Compute trade statistics breakdown (legacy dict format).
    
    Args:
        rows: Journal rows (if None, will be loaded from CSV)
        exec_log_path: Path to execution_log.csv
        plan_dir: Path to plans directory
    
    Returns:
        Legacy dict with sample/overall/by_side/by_session/by_session_regime
    """
    if rows is None:
        # Load from CSV (legacy path)
        from legacy_v1.engines import learning as legacy
        rows = legacy._load_journal()
    
    result = _service.analyze(rows, exec_log_path, plan_dir)
    
    # Convert to legacy dict format
    def stats_to_dict(stats) -> dict:
        if stats is None:
            return {}
        return {
            'trades': stats.trades,
            'win_rate': stats.win_rate,
            'net_pnl': stats.net_pnl,
            'avg_pnl': stats.avg_pnl,
        }
    
    out = {
        'sample': result.sample_size,
        'overall': stats_to_dict(result.overall),
        'by_side': {k: stats_to_dict(v) for k, v in result.by_side.items()},
        'by_session': {k: stats_to_dict(v) for k, v in result.by_session.items()},
        'by_session_regime': {
            sess: {bucket: stats_to_dict(stats) for bucket, stats in buckets.items()}
            for sess, buckets in result.by_session_regime.items()
        },
    }
    
    return out


def adjustments(
    stats: Optional[dict] = None,
    current_state: Optional[dict] = None,
) -> dict:
    """Propose parameter adjustments (legacy dict format).
    
    Args:
        stats: Stats dict from analyze() (if None, will be computed)
        current_state: Current learning state (if None, will be loaded)
    
    Returns:
        Legacy dict with reason/changes
    """
    # Get stats if not provided
    if stats is None:
        stats = analyze()
    
    overall = stats.get('overall', {})
    if overall.get('trades', 0) < _service.MIN_TRADES_SAMPLE:
        return {
            'reason': f'insufficient_sample_{overall.get("trades", 0)}',
            'changes': {},
        }
    
    # Convert overall to TradeStatistics
    from brain.domain.entities.learning import TradeStatistics
    trade_stats = TradeStatistics(
        trades=overall.get('trades', 0),
        win_rate=overall.get('win_rate', 0.0),
        net_pnl=overall.get('net_pnl', 0.0),
        avg_pnl=overall.get('avg_pnl', 0.0),
    )
    
    # Get current state
    if current_state is None:
        current_state = load_learning_state()
    
    state = LearningState.from_dict(current_state)
    
    # Compute adjustments
    adj = _service.propose_adjustments(trade_stats, state)
    
    return adj.to_dict()


def load_learning_state() -> dict:
    """Load current learning state (legacy dict format)."""
    # Try to load from file first (legacy path)
    try:
        from legacy_v1.engines import learning as legacy
        return legacy.load_learning_state()
    except Exception:
        # Fallback to defaults
        return {
            'risk_mult': 1.0,
            'min_grade': 'B',
            'min_rr': 1.5,
            'updated_at': None,
        }


def apply(deltas: dict) -> dict:
    """Apply parameter adjustments to learning state (legacy dict format).
    
    Args:
        deltas: Dict with optional keys: min_rr, min_grade, risk_mult
    
    Returns:
        Updated learning state dict
    """
    if not deltas:
        return load_learning_state()
    
    # Load current state
    current_dict = load_learning_state()
    current = LearningState.from_dict(current_dict)
    
    # Convert deltas to LearningAdjustments
    from brain.domain.entities.learning import LearningAdjustments
    adj = LearningAdjustments(
        risk_multiplier=deltas.get('risk_mult'),
        min_grade=SetupGrade(deltas['min_grade']) if 'min_grade' in deltas else None,
        min_rr=deltas.get('min_rr'),
        reason='manual_apply',
    )
    
    # Apply
    new_state = _service.apply_adjustments(current, adj)
    
    # Save to file (legacy path)
    result_dict = new_state.to_dict()
    try:
        from legacy_v1.engines import learning as legacy
        from legacy_v1 import paths
        learning_json = paths.learning_state()
        paths.write_json_atomic(learning_json, result_dict, indent=1)
    except Exception:
        pass
    
    return result_dict
