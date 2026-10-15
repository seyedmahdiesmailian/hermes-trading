"""Context service - market analysis and plan context.

Manages ATR calculation, bias classification, zone computation,
and multi-timeframe context building.
"""
from __future__ import annotations

from statistics import mean
from typing import Optional

from brain.domain.entities.context import (
    MarketBias,
    ZoneSource,
    PriceZones,
    ExecutionPlan,
    MarketContext,
)


class ContextService:
    """Market context analysis service."""
    
    # Constants from legacy
    ZONE_LOOKBACK = 12  # M5 bars for tight zones
    H1_ZONE_BARS = 24
    H1_ZONE_BARS_WIDE = 72
    MIN_STRUCTURE_RANGE = 15.0
    DISCOUNT_FRACTION = 0.30
    PREMIUM_FRACTION = 0.30
    INVALIDATION_ATR_BUFFER = 0.35
    
    def __init__(self, db=None):
        """Initialize with optional database."""
        self.db = db
    
    # ── 1. ATR Calculation ───────────────────────────────────────────────
    
    @staticmethod
    def estimate_atr(rows: list[dict]) -> float:
        """True Average Range (Wilder-style, gaps included).
        
        Computes over last 14 bars. Includes overnight gaps.
        """
        if len(rows) < 2:
            return 0.0
        
        trs = []
        window = rows[-15:]  # Need 15 to get 14 TRs
        
        for i in range(1, len(window)):
            curr = window[i]
            prev = window[i - 1]
            
            hl = curr["high"] - curr["low"]
            high_close = abs(curr["high"] - prev["close"])
            low_close = abs(curr["low"] - prev["close"])
            
            trs.append(max(hl, high_close, low_close))
        
        return mean(trs) if trs else 0.0
    
    # ── 2. Bias Classification ───────────────────────────────────────────
    
    @staticmethod
    def classify_bias(
        rows: list[dict],
        min_move: Optional[float] = None,
        min_agreement: int = 3,
    ) -> MarketBias:
        """Classify directional bias from last 5 bars.
        
        Uses volatility-relative thresholds and checks for:
        - Net move + bar count agreement
        - Dominant closing bar (reversal signal)
        """
        if len(rows) < 5:
            return MarketBias.NEUTRAL
        
        closes = [r["close"] for r in rows[-5:]]
        
        # Auto-scale threshold
        if min_move is None:
            avg_range = mean([r["high"] - r["low"] for r in rows[-5:]]) or 0.5
            min_move = max(0.3, avg_range * 0.5)
        
        # Count directional bars
        diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        up_count = sum(1 for d in diffs if d > 0)
        down_count = sum(1 for d in diffs if d < 0)
        net_move = closes[-1] - closes[0]
        
        # Strong move gets lower bar requirement
        strong = min_move > 0 and abs(net_move) >= min_move * 1.5
        need = 2 if strong else min_agreement
        
        if net_move >= min_move and up_count >= need:
            return MarketBias.BULLISH
        if net_move <= -min_move and down_count >= need:
            return MarketBias.BEARISH
        
        # Check for dominant closing bar (reversal)
        last = rows[-1]
        body = last["close"] - last["open"]
        avg_range = mean([r["high"] - r["low"] for r in rows[-5:]]) or 0.5
        
        if abs(body) >= avg_range:
            prev_bars = rows[-5:-1]
            broke_high = last["close"] >= max(r["high"] for r in prev_bars)
            broke_low = last["close"] <= min(r["low"] for r in prev_bars)
            
            if body < 0 and broke_low:
                return MarketBias.BEARISH
            if body > 0 and broke_high:
                return MarketBias.BULLISH
        
        return MarketBias.NEUTRAL
    
    # ── 3. Zone Computation ──────────────────────────────────────────────
    
    def compute_m5_zones(self, m5_rows: list[dict], atr: float) -> PriceZones:
        """Compute tight zones from M5 data."""
        lookback = m5_rows[-self.ZONE_LOOKBACK:]
        m5_low = min(r["low"] for r in lookback)
        m5_high = max(r["high"] for r in lookback)
        mid = (m5_low + m5_high) / 2.0
        
        # Tight zones: 25% ATR
        half = atr * 0.25
        
        return PriceZones(
            value_low=round(mid - half, 2),
            value_high=round(mid + half, 2),
            long_entry_low=round(mid - half * 1.5, 2),
            long_entry_high=round(mid - half * 0.3, 2),
            short_entry_low=round(mid + half * 0.3, 2),
            short_entry_high=round(mid + half * 1.5, 2),
            zone_source=ZoneSource.M5_TIGHT,
        )
    
    def compute_htf_structure_zones(
        self,
        h1_rows: list[dict],
        atr: float,
    ) -> Optional[PriceZones]:
        """Compute zones from H1 swing structure."""
        if not h1_rows:
            return None
        
        # Start with 24-bar lookback
        lookback = (
            h1_rows[-self.H1_ZONE_BARS:]
            if len(h1_rows) >= 8
            else h1_rows
        )
        swing_low = min(r["low"] for r in lookback)
        swing_high = max(r["high"] for r in lookback)
        rng = swing_high - swing_low
        atr = float(atr or 0) or 5.0
        source = ZoneSource.H1_SWING
        
        # Widen if range is too tight
        if rng < max(atr * 2.0, self.MIN_STRUCTURE_RANGE) and len(h1_rows) > len(lookback):
            wide = (
                h1_rows[-self.H1_ZONE_BARS_WIDE:]
                if len(h1_rows) >= self.H1_ZONE_BARS
                else h1_rows
            )
            w_low = min(r["low"] for r in wide)
            w_high = max(r["high"] for r in wide)
            w_rng = w_high - w_low
            
            if w_rng > rng:
                lookback = wide
                swing_low = w_low
                swing_high = w_high
                rng = w_rng
                source = ZoneSource.H1_SWING_WIDE
        
        # Fallback if still too tight
        if rng < max(atr * 0.8, 1.0):
            mid = (swing_low + swing_high) / 2.0
            half = max(atr * 1.0, 2.0)
            swing_low = mid - half
            swing_high = mid + half
            rng = swing_high - swing_low
            source = ZoneSource.FALLBACK
        
        # Compute discount/premium zones
        discount_hi = swing_low + self.DISCOUNT_FRACTION * rng
        premium_lo = swing_high - self.PREMIUM_FRACTION * rng
        
        return PriceZones(
            value_low=round(discount_hi, 2),
            value_high=round(premium_lo, 2),
            long_entry_low=round(swing_low, 2),
            long_entry_high=round(discount_hi, 2),
            short_entry_low=round(premium_lo, 2),
            short_entry_high=round(swing_high, 2),
            swing_low=round(swing_low, 2),
            swing_high=round(swing_high, 2),
            zone_source=source,
        )
    
    def derive_trade_zones(
        self,
        value_low: float,
        value_high: float,
        atr: float,
    ) -> PriceZones:
        """Derive zones from value area."""
        half = atr * 0.5
        
        return PriceZones(
            value_low=value_low,
            value_high=value_high,
            long_entry_low=value_low - half,
            long_entry_high=value_low,
            short_entry_low=value_high,
            short_entry_high=value_high + half,
        )
    
    # ── 4. Execution Planning ────────────────────────────────────────────
    
    def build_execution_plan(
        self,
        bias: MarketBias,
        zones: PriceZones,
        atr: float,
        regime: str,
    ) -> dict:
        """Build execution plan based on bias and regime.
        
        Returns dict (not ExecutionPlan entity) for legacy compatibility.
        """
        # Neutral → range mode
        if bias not in (MarketBias.BULLISH, MarketBias.BEARISH):
            regime = "range"
        
        if regime == "range":
            return {
                "entry_mode": "mean_reversion_wait",
                "scale_in_levels": [],
                "tp_levels": [
                    round(zones.value_low, 2),
                    round(zones.value_high, 2),
                ],
                "tp_shares": [0.5, 0.5],
                "breakout_trigger": round(zones.value_high + atr * 0.2, 2),
                "pullback_trigger": round(zones.value_low, 2),
            }
        
        # Bullish execution
        if bias == MarketBias.BULLISH:
            scale_levels = [
                round(zones.long_entry_high, 2),
                round(max(zones.long_entry_low, zones.long_entry_high - (atr * 0.3)), 2),
            ]
            breakout_trigger = round(zones.value_high + (atr * 0.1), 2)
            
            if regime == "breakout_continuation":
                base_target = max(zones.short_entry_high, breakout_trigger)
                tp_levels = [
                    round(base_target + (atr * 0.5), 2),
                    round(base_target + atr, 2),
                    round(base_target + (atr * 2.0), 2),
                ]
            else:  # pullback_continuation
                tp_levels = [
                    round(zones.short_entry_low, 2),
                    round(zones.short_entry_high, 2),
                    round(zones.short_entry_high + atr, 2),
                ]
        
        # Bearish execution
        else:
            scale_levels = [
                round(zones.short_entry_low, 2),
                round(min(zones.short_entry_high, zones.short_entry_low + (atr * 0.3)), 2),
            ]
            breakout_trigger = round(zones.value_low - (atr * 0.1), 2)
            
            if regime == "breakout_continuation":
                base_target = min(zones.long_entry_low, breakout_trigger)
                tp_levels = [
                    round(base_target - (atr * 0.5), 2),
                    round(base_target - atr, 2),
                    round(base_target - (atr * 2.0), 2),
                ]
            else:  # pullback_continuation
                tp_levels = [
                    round(zones.long_entry_high, 2),
                    round(zones.long_entry_low, 2),
                    round(zones.long_entry_low - atr, 2),
                ]
        
        entry_mode = (
            "breakout_pullback_hybrid"
            if regime == "breakout_continuation"
            else "scale_in_pullback"
        )
        
        return {
            "entry_mode": entry_mode,
            "scale_in_levels": scale_levels,
            "tp_levels": tp_levels,
            "tp_shares": [0.5, 0.3, 0.2],
            "breakout_trigger": breakout_trigger,
            "pullback_trigger": scale_levels[0] if scale_levels else None,
        }
    
    # ── 5. Regime Detection ──────────────────────────────────────────────
    
    @staticmethod
    def detect_alignment(m5_bias: MarketBias, h1_bias: MarketBias, h4_bias: MarketBias) -> str:
        """Detect multi-timeframe alignment."""
        votes = [m5_bias, h1_bias, h4_bias]
        directional = [v for v in votes if v in (MarketBias.BULLISH, MarketBias.BEARISH)]
        
        if len(directional) >= 2 and len(set(directional)) == 1:
            return "aligned"
        if directional:
            return "mixed"
        return "neutral"
    
    @staticmethod
    def detect_regime(
        bias: MarketBias,
        alignment: str,
        trend_strength: float,
        last_price: float,
        zones: PriceZones,
        atr: float,
        m5_bias: MarketBias,
        h1_bias: MarketBias,
        h4_bias: MarketBias,
    ) -> str:
        """Detect market regime (range vs trend)."""
        strong_trend = trend_strength >= 0.35
        higher_tf_aligned = (
            h1_bias == h4_bias
            and h1_bias in (MarketBias.BULLISH, MarketBias.BEARISH)
        )
        pullback_alignment = (
            higher_tf_aligned
            and m5_bias not in (h1_bias, MarketBias.NEUTRAL)
        )
        
        # Not trending
        if bias == MarketBias.NEUTRAL or not strong_trend:
            return "range"
        
        # No alignment
        if not (alignment == "aligned" or pullback_alignment or higher_tf_aligned):
            return "range"
        
        # Determine breakout vs pullback
        if bias == MarketBias.BULLISH:
            if last_price > zones.value_high + (atr * 0.25):
                return "breakout_continuation"
            return "pullback_continuation"
        
        # Bearish
        if last_price < zones.value_low - (atr * 0.25):
            return "breakout_continuation"
        return "pullback_continuation"
    
    @staticmethod
    def distance_in_atr(price: float, level: float, atr: float) -> float:
        """Calculate distance in ATR units."""
        if atr <= 0:
            return 0.0
        return abs(price - level) / atr
    
    # ── 6. Complete Context Building ─────────────────────────────────────
    
    def build_plan_context(
        self,
        m5_rows: list[dict],
        h1_rows: list[dict],
        h4_rows: list[dict],
        session_name: str,
        m15_rows: Optional[list[dict]] = None,
    ) -> dict:
        """Build complete multi-timeframe plan context.
        
        Returns legacy dict format for compatibility.
        """
        # ATR from M5
        atr = self.estimate_atr(m5_rows)
        
        # Bias from each timeframe
        m5_bias = self.classify_bias(m5_rows)
        m15_bias = self.classify_bias(m15_rows) if m15_rows else None
        h1_bias = self.classify_bias(h1_rows)
        h4_bias = self.classify_bias(h4_rows)
        
        # Final bias = H4 (if directional), else neutral
        bias = (
            h4_bias
            if h4_bias in (MarketBias.BULLISH, MarketBias.BEARISH)
            else MarketBias.NEUTRAL
        )
        
        # Zones (HTF preferred, M5 fallback)
        zones = self.compute_htf_structure_zones(h1_rows, atr)
        
        if zones is None:
            m5_zones = self.compute_m5_zones(m5_rows, atr)
            zones = self.derive_trade_zones(
                value_low=m5_zones.value_low,
                value_high=m5_zones.value_high,
                atr=atr,
            )
            # Add swing from M5
            swing_window = m5_rows[-12:] if len(m5_rows) >= 12 else m5_rows
            zones = PriceZones(
                value_low=zones.value_low,
                value_high=zones.value_high,
                long_entry_low=zones.long_entry_low,
                long_entry_high=zones.long_entry_high,
                short_entry_low=zones.short_entry_low,
                short_entry_high=zones.short_entry_high,
                swing_low=round(min(r["low"] for r in swing_window), 2),
                swing_high=round(max(r["high"] for r in swing_window), 2),
                zone_source=ZoneSource.FALLBACK,
            )
        
        last_price = m5_rows[-1]["close"]
        
        # Trend strength (M5 push in ATR units)
        push = (
            abs(m5_rows[-1]["close"] - m5_rows[-13]["close"])
            if len(m5_rows) >= 13
            else 0.0
        )
        trend_strength = round(push / max(atr, 0.01), 2)
        
        # Alignment and regime
        alignment = self.detect_alignment(m5_bias, h1_bias, h4_bias)
        regime = self.detect_regime(
            bias=bias,
            alignment=alignment,
            trend_strength=trend_strength,
            last_price=last_price,
            zones=zones,
            atr=atr,
            m5_bias=m5_bias,
            h1_bias=h1_bias,
            h4_bias=h4_bias,
        )
        
        # Execution plan
        execution = self.build_execution_plan(bias, zones, atr, regime)
        
        # Invalidation and targets
        swing_low = zones.swing_low or zones.long_entry_low
        swing_high = zones.swing_high or zones.short_entry_high
        
        if bias == MarketBias.BULLISH:
            invalidation = round(swing_low - (atr * self.INVALIDATION_ATR_BUFFER), 2)
            targets = execution.get("tp_levels") or [zones.short_entry_low, zones.short_entry_high]
        elif bias == MarketBias.BEARISH:
            invalidation = round(swing_high + (atr * self.INVALIDATION_ATR_BUFFER), 2)
            targets = execution.get("tp_levels") or [zones.long_entry_high, zones.long_entry_low]
        else:
            invalidation = round(swing_low - (atr * 0.25), 2)
            targets = []
        
        # Build quality dict
        quality = {
            "trend_strength": trend_strength,
            "alignment": alignment,
            "distance_to_value_low_atr": round(
                self.distance_in_atr(last_price, zones.value_low, atr), 2
            ),
            "distance_to_value_high_atr": round(
                self.distance_in_atr(last_price, zones.value_high, atr), 2
            ),
            "bias_votes": {
                "m5": m5_bias.value,
                "h1": h1_bias.value,
                "h4": h4_bias.value,
                **({"m15": m15_bias.value} if m15_bias else {}),
            },
            "regime": regime,
            "zone_source": zones.zone_source.value if zones.zone_source else "h1_swing",
            "htf_bias": h4_bias.value,
        }
        
        # Return legacy dict format
        return {
            "symbol": "XAUUSD",
            "session": session_name,
            "bias": bias.value,
            "atr": atr,
            "zones": zones.to_dict(),
            "quality": quality,
            "context": {
                "m5_last": last_price,
                "h1_last": h1_rows[-1]["close"],
                "h4_last": h4_rows[-1]["close"],
            },
            "execution": execution,
            "invalidation": invalidation,
            "targets": targets,
        }
