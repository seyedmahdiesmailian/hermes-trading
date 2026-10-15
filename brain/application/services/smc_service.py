"""SMC/ICT service - Smart Money Concepts analysis.

Manages order blocks, fair value gaps, liquidity sweeps, market structure,
premium/discount zones, killzone timing, POI grading, and advanced ICT concepts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from brain.domain.entities.smc import (
    OrderBlockType,
    FVGType,
    StructurePhase,
    PremiumDiscountZone,
    POIGrade,
    OrderBlock,
    FairValueGap,
    LiquiditySweep,
    MarketStructure,
    PremiumDiscount,
    KillzoneSession,
    SMCAnalysis,
)


class SMCService:
    """Smart Money Concepts analysis service."""
    
    # Constants
    KILLZONES = {
        "london": {"start": (7, 0), "end": (9, 30), "weight": 1.0},
        "newyork": {"start": (12, 0), "end": (15, 0), "weight": 1.0},
        "london_close": {"start": (15, 0), "end": (16, 0), "weight": 0.5},
        "asia": {"start": (0, 0), "end": (5, 0), "weight": 0.6},
    }
    
    def __init__(self, db=None):
        """Initialize with optional database."""
        self.db = db
    
    # ── 1. Order Blocks ──────────────────────────────────────────────────
    
    def detect_order_blocks(
        self,
        rows: list[dict],
        lookback: int = 20,
    ) -> list[OrderBlock]:
        """Find unmitigated order blocks.
        
        Bullish OB = last bearish candle before strong bullish breakout.
        Bearish OB = last bullish candle before strong bearish breakout.
        """
        if len(rows) < 3:
            return []
        
        # Compute average body for strength threshold
        bodies = [abs(r["close"] - r["open"]) for r in rows[-lookback:]]
        avg_body = sum(bodies) / len(bodies) if bodies else 0.0
        avg_range = sum([r["high"] - r["low"] for r in rows[-lookback:]]) / len(rows[-lookback:])
        strong_threshold = max(avg_body * 1.5, avg_range * 0.5)
        
        obs = []
        for i in range(len(rows) - 2, 0, -1):
            prev = rows[i - 1]
            curr = rows[i]
            
            # Bullish OB: prev is bearish, curr breaks above with strong body
            if prev["close"] < prev["open"]:
                body_curr = abs(curr["close"] - curr["open"])
                if curr["close"] > curr["open"] and body_curr >= strong_threshold:
                    if curr["close"] > prev["high"]:
                        ob = OrderBlock(
                            ob_type=OrderBlockType.BULLISH,
                            high=prev["high"],
                            low=prev["low"],
                            open_price=prev["open"],
                            close=prev["close"],
                            index=i - 1,
                            mitigated=False,
                        )
                        obs.append(ob)
            
            # Bearish OB: prev is bullish, curr breaks below with strong body
            if prev["close"] > prev["open"]:
                body_curr = abs(curr["close"] - curr["open"])
                if curr["close"] < curr["open"] and body_curr >= strong_threshold:
                    if curr["close"] < prev["low"]:
                        ob = OrderBlock(
                            ob_type=OrderBlockType.BEARISH,
                            high=prev["high"],
                            low=prev["low"],
                            open_price=prev["open"],
                            close=prev["close"],
                            index=i - 1,
                            mitigated=False,
                        )
                        obs.append(ob)
        
        # Check mitigation: price returning into the OB zone
        mitigated_obs = []
        for ob in obs:
            zone_lo, zone_hi = ob.low, ob.high
            mitigated = False
            
            # Scan starts two bars past the block
            for j in range(ob.index + 2, len(rows)):
                if ob.ob_type == OrderBlockType.BULLISH:
                    if rows[j]["low"] <= zone_hi:
                        mitigated = True
                        break
                else:
                    if rows[j]["high"] >= zone_lo:
                        mitigated = True
                        break
            
            # Create new OB with mitigation status
            mitigated_obs.append(OrderBlock(
                ob_type=ob.ob_type,
                high=ob.high,
                low=ob.low,
                open_price=ob.open_price,
                close=ob.close,
                index=ob.index,
                mitigated=mitigated,
            ))
        
        return mitigated_obs
    
    # ── 2. Fair Value Gaps ───────────────────────────────────────────────
    
    def detect_fair_value_gaps(self, rows: list[dict]) -> list[FairValueGap]:
        """Find FVGs (3-candle imbalance patterns).
        
        Bullish FVG: candle_3.low > candle_1.high
        Bearish FVG: candle_3.high < candle_1.low
        """
        if len(rows) < 3:
            return []
        
        fvgs = []
        for i in range(len(rows) - 2):
            c1 = rows[i]
            c3 = rows[i + 2]
            
            # Bullish FVG: gap above candle 1
            if c3["low"] > c1["high"]:
                fvgs.append(FairValueGap(
                    fvg_type=FVGType.BULLISH,
                    low=c1["high"],
                    high=c3["low"],
                    c1_index=i,
                    c3_index=i + 2,
                    filled=False,
                ))
            
            # Bearish FVG: gap below candle 1
            if c3["high"] < c1["low"]:
                fvgs.append(FairValueGap(
                    fvg_type=FVGType.BEARISH,
                    low=c3["high"],
                    high=c1["low"],
                    c1_index=i,
                    c3_index=i + 2,
                    filled=False,
                ))
        
        # Check fill: subsequent candles' wicks touching the gap
        filled_fvgs = []
        for fvg in fvgs:
            filled = False
            
            for j in range(fvg.c3_index + 1, len(rows)):
                candle = rows[j]
                if candle["low"] <= fvg.high and candle["high"] >= fvg.low:
                    filled = True
                    break
            
            filled_fvgs.append(FairValueGap(
                fvg_type=fvg.fvg_type,
                low=fvg.low,
                high=fvg.high,
                c1_index=fvg.c1_index,
                c3_index=fvg.c3_index,
                filled=filled,
            ))
        
        return filled_fvgs
    
    # ── 3. Liquidity Sweep ───────────────────────────────────────────────
    
    def detect_liquidity_sweep(
        self,
        rows: list[dict],
        lookback: int = 5,
    ) -> LiquiditySweep:
        """Detect if price swept a significant high/low and reversed."""
        if len(rows) < 3:
            return LiquiditySweep(swept=False, swept_level=None, sweep_side=None)
        
        effective_lookback = min(lookback, len(rows) - 2)
        if effective_lookback < 1:
            return LiquiditySweep(swept=False, swept_level=None, sweep_side=None)
        
        window = rows[-(effective_lookback + 2):]
        
        # Find swing highs/lows in the window (excluding last 2 candles)
        ref_high = max(r["high"] for r in window[:-2])
        ref_low = min(r["low"] for r in window[:-2])
        
        prev = window[-2]
        curr = window[-1]
        
        # Sweep of high: breaks above ref_high, then reverses
        if prev["high"] > ref_high and curr["close"] < prev["high"]:
            return LiquiditySweep(
                swept=True,
                swept_level=ref_high,
                sweep_side="bearish",
            )
        
        # Sweep of low: breaks below ref_low, then reverses
        if prev["low"] < ref_low and curr["close"] > prev["low"]:
            return LiquiditySweep(
                swept=True,
                swept_level=ref_low,
                sweep_side="bullish",
            )
        
        # Also check current candle for sweep
        if curr["high"] > ref_high and curr["close"] < ref_high:
            return LiquiditySweep(
                swept=True,
                swept_level=ref_high,
                sweep_side="bearish",
            )
        if curr["low"] < ref_low and curr["close"] > ref_low:
            return LiquiditySweep(
                swept=True,
                swept_level=ref_low,
                sweep_side="bullish",
            )
        
        return LiquiditySweep(swept=False, swept_level=None, sweep_side=None)
    
    # ── 4. Market Structure ──────────────────────────────────────────────
    
    def market_structure_phase(
        self,
        rows: list[dict],
        lookback: int = 10,
    ) -> MarketStructure:
        """Determine market structure phase."""
        if len(rows) < 3:
            return MarketStructure(phase=StructurePhase.RANGE, confidence=0.0)
        
        window = rows[-min(lookback, len(rows)):]
        if len(window) < 3:
            return MarketStructure(phase=StructurePhase.RANGE, confidence=0.0)
        
        # Split into two halves
        mid = max(len(window) // 2, 1)
        first = window[:mid]
        second = window[mid:]
        
        first_high = max(r["high"] for r in first)
        first_low = min(r["low"] for r in first)
        second_high = max(r["high"] for r in second)
        second_low = min(r["low"] for r in second)
        
        closes = [r["close"] for r in window]
        last_close = closes[-1]
        first_close = closes[0]
        
        trend = last_close - first_close
        avg_range = sum(r["high"] - r["low"] for r in window) / max(len(window), 1)
        
        # Higher high + higher low = bullish BOS
        if second_high > first_high and second_low > first_low:
            confidence = min(abs(trend) / avg_range, 1.0) if avg_range > 0 else 0.5
            return MarketStructure(
                phase=StructurePhase.BOS_BULLISH,
                confidence=confidence,
            )
        
        # Lower low + lower high = bearish BOS
        if second_low < first_low and second_high < first_high:
            confidence = min(abs(trend) / avg_range, 1.0) if avg_range > 0 else 0.5
            return MarketStructure(
                phase=StructurePhase.BOS_BEARISH,
                confidence=confidence,
            )
        
        # Broke both bounds (expanded range) — check net direction
        if second_high > first_high and second_low < first_low:
            if trend > 0:
                return MarketStructure(
                    phase=StructurePhase.CHOCH_BULLISH,
                    confidence=0.6,
                )
            else:
                return MarketStructure(
                    phase=StructurePhase.CHOCH_BEARISH,
                    confidence=0.6,
                )
        
        return MarketStructure(phase=StructurePhase.RANGE, confidence=0.0)
    
    # ── 5. Premium/Discount ──────────────────────────────────────────────
    
    def premium_discount_zone(
        self,
        price: float,
        swing_high: float,
        swing_low: float,
    ) -> PremiumDiscount:
        """Determine where price sits in the swing range."""
        if swing_high <= swing_low:
            return PremiumDiscount(
                zone=PremiumDiscountZone.EQUILIBRIUM,
                fib_level=0.5,
                quality=0,
                swing_high=swing_high,
                swing_low=swing_low,
            )
        
        range_size = swing_high - swing_low
        position = (price - swing_low) / range_size
        fib_level = position
        
        if fib_level <= 0.25:
            zone = PremiumDiscountZone.DISCOUNT
            quality = round((0.25 - fib_level) / 0.25 * 100, 0)
        elif fib_level >= 0.75:
            zone = PremiumDiscountZone.PREMIUM
            quality = round((fib_level - 0.75) / 0.25 * 100, 0)
        else:
            zone = PremiumDiscountZone.EQUILIBRIUM
            quality = 50 - abs(fib_level - 0.5) * 200
        
        return PremiumDiscount(
            zone=zone,
            fib_level=round(fib_level, 3),
            quality=int(max(0, min(100, quality))),
            swing_high=swing_high,
            swing_low=swing_low,
        )
    
    # ── 6. Killzone Timing ───────────────────────────────────────────────
    
    def active_killzone_session(self, now: datetime) -> KillzoneSession:
        """Determine which killzone is active based on UTC time."""
        hour = now.hour + now.minute / 60.0
        
        for name, zone in self.KILLZONES.items():
            start_h = zone["start"][0] + zone["start"][1] / 60.0
            end_h = zone["end"][0] + zone["end"][1] / 60.0
            
            if start_h <= hour < end_h:
                return KillzoneSession(name=name, weight=zone["weight"])
        
        return KillzoneSession(name="dead", weight=0.0)
    
    # ── 7. POI Grade ─────────────────────────────────────────────────────
    
    def grade_poi(
        self,
        has_ob: bool,
        ob_mitigated: bool,
        has_fvg: bool,
        fvg_filled: bool,
        liq_sweep: bool,
        discount: bool,
        killzone_weight: float,
        structure_aligned: bool,
    ) -> POIGrade:
        """Grade Point of Interest quality based on confluence."""
        score = 0
        
        # Order block presence
        if has_ob and not ob_mitigated:
            score += 3
        elif has_ob:
            score += 1
        
        # Fair value gap presence
        if has_fvg and not fvg_filled:
            score += 3
        elif has_fvg:
            score += 1
        
        # Liquidity sweep
        if liq_sweep:
            score += 2
        
        # Discount/premium alignment
        if discount:
            score += 2
        
        # Killzone timing
        if killzone_weight >= 0.9:
            score += 2
        elif killzone_weight >= 0.5:
            score += 1
        
        # Structure alignment
        if structure_aligned:
            score += 2
        
        # Grade thresholds
        if score >= 12:
            return POIGrade.A_PLUS
        elif score >= 9:
            return POIGrade.A
        elif score >= 6:
            return POIGrade.B
        else:
            return POIGrade.C
    
    # ── 8. Derive SMC Bias ───────────────────────────────────────────────
    
    def derive_smc_bias(
        self,
        obs: list[OrderBlock],
        unmitigated_obs: list[OrderBlock],
        fvgs: list[FairValueGap],
        unfilled_fvgs: list[FairValueGap],
        sweep_side: Optional[str],
        structure: MarketStructure,
        pd_zone: PremiumDiscount,
        killzone_weight: float,
    ) -> tuple[str, float]:
        """Derive market bias from all SMC signals."""
        bullish_score = 0.0
        bearish_score = 0.0
        
        # Order blocks
        for ob in unmitigated_obs:
            if ob.ob_type == OrderBlockType.BULLISH:
                bullish_score += 2.0
            else:
                bearish_score += 2.0
        
        # Fair value gaps
        for fvg in unfilled_fvgs:
            if fvg.fvg_type == FVGType.BULLISH:
                bullish_score += 1.5
            else:
                bearish_score += 1.5
        
        # Liquidity sweep
        if sweep_side == "bullish":
            bullish_score += 1.5
        elif sweep_side == "bearish":
            bearish_score += 1.5
        
        # Market structure
        if structure.phase == StructurePhase.BOS_BULLISH:
            bullish_score += 2.5
        elif structure.phase == StructurePhase.BOS_BEARISH:
            bearish_score += 2.5
        elif structure.phase == StructurePhase.CHOCH_BULLISH:
            bullish_score += 1.5
        elif structure.phase == StructurePhase.CHOCH_BEARISH:
            bearish_score += 1.5
        
        # Premium/Discount
        if pd_zone.zone == PremiumDiscountZone.DISCOUNT:
            bullish_score += pd_zone.quality / 50.0
        elif pd_zone.zone == PremiumDiscountZone.PREMIUM:
            bearish_score += pd_zone.quality / 50.0
        
        # Killzone weight
        bullish_score *= max(killzone_weight, 0.5)
        bearish_score *= max(killzone_weight, 0.5)
        
        diff = bullish_score - bearish_score
        total = bullish_score + bearish_score
        confidence = min(abs(diff) / (total + 0.01), 1.0)
        
        if diff > 1.0:
            return "bullish", confidence
        elif diff < -1.0:
            return "bearish", confidence
        else:
            return "neutral", 0.0
    
    # ── 9. Compute Signal ────────────────────────────────────────────────
    
    def compute_smc_signal(
        self,
        bias: str,
        bias_confidence: float,
        pd_zone: PremiumDiscount,
        killzone_weight: float,
    ) -> tuple[str, float]:
        """Compute final trade signal from bias."""
        if bias == "neutral" or bias_confidence < 0.4:
            return "wait", 0.0
        
        if killzone_weight < 0.1:
            # Dead zone — keep signal but dampen
            return bias, bias_confidence * 0.3
        
        # Don't buy at premium, don't sell at discount
        if bias == "bullish" and pd_zone.zone == PremiumDiscountZone.PREMIUM:
            return "wait", 0.3
        if bias == "bearish" and pd_zone.zone == PremiumDiscountZone.DISCOUNT:
            return "wait", 0.3
        
        return bias, bias_confidence
    
    # ── 10. Advanced ICT Concepts ────────────────────────────────────────
    
    def compute_ote_zone(
        self,
        swing_low: float,
        swing_high: float,
    ) -> dict:
        """Optimal Trade Entry zone (Fib 0.62-0.79)."""
        if swing_high <= swing_low:
            return {
                "low": swing_low,
                "high": swing_low,
                "fib_range": [0.62, 0.79],
            }
        
        fib_62 = swing_high - 0.62 * (swing_high - swing_low)
        fib_79 = swing_high - 0.79 * (swing_high - swing_low)
        ote_low = min(fib_62, fib_79)
        ote_high = max(fib_62, fib_79)
        
        return {
            "low": ote_low,
            "high": ote_high,
            "fib_range": [0.62, 0.79],
        }
    
    def detect_breaker_blocks(
        self,
        rows: list[dict],
        lookback: int = 10,
    ) -> list[dict]:
        """Detect OBs that were broken and flipped."""
        obs = self.detect_order_blocks(rows, lookback)
        if not obs:
            return []
        
        breakers = []
        last_close = rows[-1]["close"]
        
        for ob in obs:
            ob_high = ob.high
            ob_low = ob.low
            broke = False
            broke_dir = None
            
            for r in rows[ob.index + 1:]:
                if ob.ob_type == OrderBlockType.BULLISH and r["close"] < ob_low:
                    broke = True
                    broke_dir = "below"
                    break
                elif ob.ob_type == OrderBlockType.BEARISH and r["close"] > ob_high:
                    broke = True
                    broke_dir = "above"
                    break
            
            if not broke:
                continue
            
            if ob.ob_type == OrderBlockType.BULLISH and broke_dir == "below":
                if ob_low <= last_close <= ob_high:
                    breakers.append({
                        "type": "bearish_breaker",
                        "high": ob_high,
                        "low": ob_low,
                        "flipped": True,
                    })
            elif ob.ob_type == OrderBlockType.BEARISH and broke_dir == "above":
                if ob_low <= last_close <= ob_high:
                    breakers.append({
                        "type": "bullish_breaker",
                        "high": ob_high,
                        "low": ob_low,
                        "flipped": True,
                    })
        
        return breakers
    
    def detect_rejection_blocks(
        self,
        rows: list[dict],
        lookback: int = 10,
    ) -> list[dict]:
        """Detect pin bar / wick rejections."""
        obs = self.detect_order_blocks(rows, lookback)
        active_obs = [o for o in obs if not o.mitigated]
        if not active_obs:
            return []
        
        rejections = []
        last = rows[-1]
        body = abs(last["close"] - last["open"])
        upper_wick = last["high"] - max(last["close"], last["open"])
        lower_wick = min(last["close"], last["open"]) - last["low"]
        
        for ob in active_obs:
            if ob.ob_type == OrderBlockType.BULLISH:
                if last["low"] <= ob.high and lower_wick >= body * 0.5:
                    rejections.append({
                        "type": "bullish_rejection",
                        "wick_size": lower_wick,
                    })
            else:
                if last["high"] >= ob.low and upper_wick >= body * 0.5:
                    rejections.append({
                        "type": "bearish_rejection",
                        "wick_size": upper_wick,
                    })
        
        return rejections
    
    def detect_power_of_three(self, rows: list[dict]) -> dict:
        """Accumulation -> Manipulation -> Distribution."""
        n = len(rows)
        if n < 6:
            return {
                "phase": "not_enough_data",
                "accumulation": {},
                "manipulation": {},
                "distribution": {},
            }
        
        third = n // 3
        acc = rows[:third]
        manip = rows[third:2 * third]
        dist = rows[2 * third:]
        
        ar = {"high": max(r["high"] for r in acc), "low": min(r["low"] for r in acc)}
        mr = {"high": max(r["high"] for r in manip), "low": min(r["low"] for r in manip)}
        dr = {"high": max(r["high"] for r in dist), "low": min(r["low"] for r in dist)}
        
        if (mr["high"] > ar["high"] and dr["high"] > ar["high"]) or (
            mr["low"] < ar["low"] and dr["low"] < ar["low"]
        ):
            phase = "distribution"
        elif mr["high"] > ar["high"] or mr["low"] < ar["low"]:
            phase = "manipulation"
        else:
            phase = "accumulation"
        
        return {
            "phase": phase,
            "accumulation": ar,
            "manipulation": mr,
            "distribution": dr,
        }
    
    def detect_turtle_soup(self, rows: list[dict], lookback: int = 10) -> dict:
        """Detect fake breakout then sharp reversal."""
        if len(rows) < 4:
            return {"found": False, "type": None, "fake_level": None}
        
        window = rows[-min(lookback, len(rows)):]
        sw_high = max(r["high"] for r in window[:-2])
        sw_low = min(r["low"] for r in window[:-2])
        fake = window[-2]
        confirm = window[-1]
        
        if (
            fake["low"] < sw_low
            and confirm["close"] > confirm["open"]
            and confirm["close"] > fake["high"] * 0.98
        ):
            return {"found": True, "type": "bullish", "fake_level": sw_low}
        
        if (
            fake["high"] > sw_high
            and confirm["close"] < confirm["open"]
            and confirm["close"] < fake["low"] * 1.02
        ):
            return {"found": True, "type": "bearish", "fake_level": sw_high}
        
        return {"found": False, "type": None, "fake_level": None}
    
    def evaluate_silver_bullet_setup(self, now: Optional[datetime] = None) -> dict:
        """Silver Bullet windows: 10-11 AM and 2-3 PM NY time."""
        if now is None:
            now = datetime.now(timezone.utc)
        
        ny_hour = now.astimezone(ZoneInfo("America/New_York")).hour
        
        if ny_hour == 10:
            return {
                "active": True,
                "window": "am",
                "label": "Silver Bullet AM (10-11 NY)",
            }
        if ny_hour == 14:
            return {
                "active": True,
                "window": "pm",
                "label": "Silver Bullet PM (2-3 NY)",
            }
        
        return {"active": False, "window": None, "label": None}
    
    def compute_session_liquidity(self, rows: list[dict]) -> dict:
        """Session highs, lows, midpoint, and sweep detection."""
        if not rows:
            return {
                "session_high": 0.0,
                "session_low": 0.0,
                "midpoint": 0.0,
                "swept_high": False,
                "swept_low": False,
                "range": 0.0,
            }
        
        base = rows[:-3] if len(rows) > 3 else rows
        tail = rows[-3:] if len(rows) > 3 else []
        
        sh = max(r["high"] for r in base)
        sl = min(r["low"] for r in base)
        
        return {
            "session_high": sh,
            "session_low": sl,
            "midpoint": round((sh + sl) / 2, 2),
            "swept_high": any(r["high"] > sh for r in tail),
            "swept_low": any(r["low"] < sl for r in tail),
            "range": round(sh - sl, 2),
        }
    
    def detect_volume_imbalance(
        self,
        rows: list[dict],
        threshold: float = 2.5,
    ) -> list[dict]:
        """Detect volume spikes."""
        if len(rows) < 3:
            return []
        
        vols = [r.get("tick_volume", 0) for r in rows]
        avg_vol = sum(vols) / max(len(vols), 1)
        
        if avg_vol <= 0:
            return []
        
        imbalances = []
        for i, r in enumerate(rows):
            vol = r.get("tick_volume", 0)
            if vol > avg_vol * threshold:
                direction = "bullish" if r["close"] > r["open"] else "bearish"
                imbalances.append({
                    "index": i,
                    "volume": vol,
                    "avg_volume": round(avg_vol, 1),
                    "volume_multiple": round(vol / avg_vol, 2),
                    "direction": direction,
                })
        
        return imbalances
    
    # ── 11. Complete Analysis ────────────────────────────────────────────
    
    def analyze(
        self,
        rows: list[dict],
        h1_rows: Optional[list[dict]] = None,
        now: Optional[datetime] = None,
    ) -> SMCAnalysis:
        """Complete SMC/ICT analysis."""
        if now is None:
            now = datetime.now(timezone.utc)
        
        if len(rows) < 3:
            # Empty result
            return SMCAnalysis(
                order_blocks=[],
                unmitigated_obs=[],
                fvgs=[],
                unfilled_fvgs=[],
                liquidity_sweep=LiquiditySweep(swept=False, swept_level=None, sweep_side=None),
                structure=MarketStructure(phase=StructurePhase.RANGE, confidence=0.0),
                h1_structure=None,
                pd_zone=PremiumDiscount(
                    zone=PremiumDiscountZone.EQUILIBRIUM,
                    fib_level=0.5,
                    quality=0,
                    swing_high=0.0,
                    swing_low=0.0,
                ),
                killzone=KillzoneSession(name="dead", weight=0.0),
                poi_grade=POIGrade.C,
                smc_bias="neutral",
                bias_score=0.0,
                confidence=0.0,
            )
        
        # 1. Order blocks
        obs = self.detect_order_blocks(rows)
        unmitigated_obs = [ob for ob in obs if not ob.mitigated]
        
        # 2. Fair value gaps
        fvgs = self.detect_fair_value_gaps(rows)
        unfilled_fvgs = [fvg for fvg in fvgs if not fvg.filled]
        
        # 3. H1 structure (if provided)
        h1_structure = None
        h1_obs = []
        h1_unmitigated = []
        h1_fvgs = []
        h1_unfilled = []
        
        if h1_rows and len(h1_rows) >= 3:
            h1_structure = self.market_structure_phase(h1_rows, lookback=10)
            h1_obs = self.detect_order_blocks(h1_rows)
            h1_unmitigated = [ob for ob in h1_obs if not ob.mitigated]
            h1_fvgs = self.detect_fair_value_gaps(h1_rows)
            h1_unfilled = [fvg for fvg in h1_fvgs if not fvg.filled]
        
        # 4. Liquidity sweep
        liq_sweep = self.detect_liquidity_sweep(rows)
        
        # 5. Market structure
        structure = self.market_structure_phase(rows)
        
        # 6. Premium/Discount
        if h1_rows and len(h1_rows) >= 15:
            recent_h1 = h1_rows[-15:]
            swing_high = max(r["high"] for r in recent_h1)
            swing_low = min(r["low"] for r in recent_h1)
        else:
            recent = rows[-20:] if len(rows) >= 20 else rows
            swing_high = max(r["high"] for r in recent)
            swing_low = min(r["low"] for r in recent)
        
        last_price = rows[-1]["close"]
        pd_zone = self.premium_discount_zone(last_price, swing_high, swing_low)
        
        # 7. Killzone
        killzone = self.active_killzone_session(now)
        
        # 8. Derive bias (include H1 signals)
        all_obs = obs + h1_obs
        all_unmitigated = unmitigated_obs + h1_unmitigated
        all_fvgs = fvgs + h1_fvgs
        all_unfilled = unfilled_fvgs + h1_unfilled
        
        smc_bias, smc_confidence = self.derive_smc_bias(
            all_obs,
            all_unmitigated,
            all_fvgs,
            all_unfilled,
            liq_sweep.sweep_side,
            structure,
            pd_zone,
            killzone.weight,
        )
        
        # 9. Signal
        signal, signal_confidence = self.compute_smc_signal(
            smc_bias,
            smc_confidence,
            pd_zone,
            killzone.weight,
        )
        
        # 10. POI grade
        structure_aligned = (
            (smc_bias == "bullish" and structure.is_bullish)
            or (smc_bias == "bearish" and structure.is_bearish)
        )
        in_good_zone = (
            (smc_bias == "bullish" and pd_zone.in_discount)
            or (smc_bias == "bearish" and pd_zone.in_premium)
        )
        
        poi_grade = self.grade_poi(
            has_ob=len(unmitigated_obs) > 0,
            ob_mitigated=False,
            has_fvg=len(unfilled_fvgs) > 0,
            fvg_filled=False,
            liq_sweep=liq_sweep.swept,
            discount=in_good_zone,
            killzone_weight=killzone.weight,
            structure_aligned=structure_aligned,
        )
        
        return SMCAnalysis(
            order_blocks=obs,
            unmitigated_obs=unmitigated_obs,
            fvgs=fvgs,
            unfilled_fvgs=unfilled_fvgs,
            liquidity_sweep=liq_sweep,
            structure=structure,
            h1_structure=h1_structure,
            pd_zone=pd_zone,
            killzone=killzone,
            poi_grade=poi_grade,
            smc_bias=smc_bias,
            bias_score=smc_confidence,
            confidence=signal_confidence,
        )
    
    # ── 12. Merge with Classic ───────────────────────────────────────────
    
    def merge_smc_with_classic(
        self,
        classic_context: dict,
        smc_analysis: SMCAnalysis,
    ) -> dict:
        """Merge SMC with classic technical analysis."""
        classic_bias = classic_context.get("bias", "neutral")
        classic_quality = classic_context.get("quality", {})
        classic_regime = (
            classic_quality.get("regime")
            or classic_context.get("regime")
            or "range"
        )
        classic_alignment = classic_quality.get("alignment", "neutral")
        
        smc_bias = smc_analysis.smc_bias
        smc_confidence = smc_analysis.bias_score
        smc_weight = smc_analysis.killzone.weight if smc_analysis.killzone.weight > 0.3 else 0.5
        
        # Compute classic confidence
        classic_confidence = 0.0
        if classic_alignment == "aligned":
            classic_confidence = 0.7
        elif classic_alignment == "mixed":
            classic_confidence = 0.4
        if classic_regime == "range":
            classic_confidence *= 0.5
        
        # Weighted consensus
        bias_scores = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}
        
        if classic_bias == "bullish":
            bias_scores["bullish"] += classic_confidence * 0.4
        elif classic_bias == "bearish":
            bias_scores["bearish"] += classic_confidence * 0.4
        else:
            bias_scores["neutral"] += 0.05
        
        # SMC contribution
        if classic_bias == "neutral":
            smc_factor = smc_confidence * 0.9
        elif smc_bias == classic_bias:
            smc_factor = smc_confidence * smc_weight * 0.7
        else:
            smc_factor = smc_confidence * smc_weight * 0.4
        
        if smc_bias == "bullish":
            bias_scores["bullish"] += smc_factor
        elif smc_bias == "bearish":
            bias_scores["bearish"] += smc_factor
        
        # Winner
        max_bias = max(bias_scores.keys(), key=lambda k: bias_scores[k])
        max_score = bias_scores[max_bias]
        merged_confidence = round(max_score, 2)
        
        if merged_confidence < 0.20:
            max_bias = "neutral"
            merged_confidence = 0.0
        
        # Action
        if max_bias == "neutral":
            action = "wait"
        elif smc_analysis.confidence == 0.0 and smc_confidence > 0.5:
            action = "wait" if merged_confidence < 0.5 else max_bias
        elif max_bias == "bullish":
            action = "long" if merged_confidence >= 0.30 else "wait"
        elif max_bias == "bearish":
            action = "short" if merged_confidence >= 0.30 else "wait"
        else:
            action = "wait"
        
        return {
            "bias": max_bias,
            "confidence": merged_confidence,
            "action": action,
            "classic_source": {
                "bias": classic_bias,
                "confidence": classic_confidence,
                "regime": classic_regime,
                "alignment": classic_alignment,
            },
            "smc_source": {
                "bias": smc_bias,
                "signal": "bullish" if smc_analysis.confidence > 0 and smc_bias == "bullish" else "bearish" if smc_analysis.confidence > 0 and smc_bias == "bearish" else "wait",
                "confidence": smc_confidence,
                "weight": smc_weight,
                "poi": smc_analysis.poi_grade.value,
                "market_structure": {
                    "phase": smc_analysis.structure.phase.value,
                    "confidence": smc_analysis.structure.confidence,
                },
                "killzone": {
                    "session": smc_analysis.killzone.name,
                    "weight": smc_analysis.killzone.weight,
                },
            },
            "smc_result": smc_analysis.to_dict(),
        }
