"""Legacy adapter for Context — maintains backward compatibility.

Provides the same interface as legacy_v1/engines/context.py functions
while using the refactored service layer underneath.
"""
from __future__ import annotations

from typing import Optional

from brain.application.services.context_service import ContextService
from brain.domain.entities.context import MarketBias
from database import get_db


# Module-level service instance
_service = ContextService(get_db())


def estimate_atr(rows: list[dict]) -> float:
    """True Average Range (Wilder-style, gaps included)."""
    return _service.estimate_atr(rows)


def classify_bias(
    rows: list[dict],
    min_move: Optional[float] = None,
    min_agreement: int = 3,
) -> str:
    """Classify directional bias (legacy string format)."""
    bias = _service.classify_bias(rows, min_move, min_agreement)
    return bias.value


def compute_m5_zones(m5_rows: list[dict], atr: float) -> dict:
    """Compute tight zones from M5 data (legacy dict format)."""
    zones = _service.compute_m5_zones(m5_rows, atr)
    return zones.to_dict()


def compute_htf_structure_zones(h1_rows: list[dict], atr: float) -> dict:
    """Compute zones from H1 swing structure (legacy dict format)."""
    zones = _service.compute_htf_structure_zones(h1_rows, atr)
    return zones.to_dict() if zones else {}


def derive_trade_zones(value_low: float, value_high: float, atr: float) -> dict:
    """Derive zones from value area (legacy dict format)."""
    zones = _service.derive_trade_zones(value_low, value_high, atr)
    return zones.to_dict()


def apply_bias_geometry(ctx: dict) -> bool:
    """Recompute execution/invalidation/targets for ctx['bias'].
    
    Mutates ctx in place (legacy behavior).
    """
    zones = ctx.get("zones") or {}
    needed = (
        "value_low", "value_high", "long_entry_low", "long_entry_high",
        "short_entry_low", "short_entry_high"
    )
    
    try:
        if any(zones.get(k) is None for k in needed):
            return False
        atr = float(ctx.get("atr") or 0) or 5.0
    except (TypeError, ValueError):
        return False
    
    bias_str = ctx.get("bias") or "neutral"
    regime = (ctx.get("quality") or {}).get("regime") or "range"
    
    if bias_str not in {"bullish", "bearish"}:
        regime = "range"
    
    # Convert to entity
    bias = MarketBias(bias_str)
    
    # Import zone entity
    from brain.domain.entities.context import PriceZones, ZoneSource
    
    zone_source_str = zones.get("zone_source", "h1_swing")
    try:
        zone_source = ZoneSource(zone_source_str)
    except ValueError:
        zone_source = ZoneSource.H1_SWING
    
    price_zones = PriceZones(
        value_low=zones["value_low"],
        value_high=zones["value_high"],
        long_entry_low=zones["long_entry_low"],
        long_entry_high=zones["long_entry_high"],
        short_entry_low=zones["short_entry_low"],
        short_entry_high=zones["short_entry_high"],
        swing_low=zones.get("swing_low"),
        swing_high=zones.get("swing_high"),
        zone_source=zone_source,
    )
    
    # Build execution plan
    execution = _service.build_execution_plan(bias, price_zones, atr, regime)
    
    # Compute invalidation and targets
    swing_low = float(zones.get("swing_low") or zones["long_entry_low"])
    swing_high = float(zones.get("swing_high") or zones["short_entry_high"])
    
    if bias == MarketBias.BULLISH:
        invalidation = round(swing_low - (atr * _service.INVALIDATION_ATR_BUFFER), 2)
        targets = execution.get("tp_levels") or [
            zones["short_entry_low"],
            zones["short_entry_high"],
        ]
    elif bias == MarketBias.BEARISH:
        invalidation = round(swing_high + (atr * _service.INVALIDATION_ATR_BUFFER), 2)
        targets = execution.get("tp_levels") or [
            zones["long_entry_high"],
            zones["long_entry_low"],
        ]
    else:
        invalidation = round(swing_low - (atr * 0.25), 2)
        targets = []
    
    # Mutate ctx in place (legacy behavior)
    ctx["execution"] = execution
    ctx["invalidation"] = invalidation
    ctx["targets"] = targets
    
    return True


def build_plan_context(
    m5_rows: list[dict],
    h1_rows: list[dict],
    h4_rows: list[dict],
    session_name: str,
    m15_rows: Optional[list[dict]] = None,
) -> dict:
    """Build complete multi-timeframe plan context (legacy dict format)."""
    return _service.build_plan_context(
        m5_rows=m5_rows,
        h1_rows=h1_rows,
        h4_rows=h4_rows,
        session_name=session_name,
        m15_rows=m15_rows,
    )
