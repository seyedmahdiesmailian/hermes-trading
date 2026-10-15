"""Legacy V1 adapter for SMC service."""
from datetime import datetime
from typing import Optional

from brain.application.services.smc_service import SMCService


class SMCAdapter:
    """Wraps SMCService with legacy dict-based interface."""
    
    def __init__(self, db=None):
        self.service = SMCService(db)
    
    def analyze_smc(
        self,
        rows: list[dict],
        h1_rows: Optional[list[dict]] = None,
        now: Optional[datetime] = None,
    ) -> dict:
        """Complete SMC analysis (legacy format)."""
        analysis = self.service.analyze(rows, h1_rows, now)
        return analysis.to_dict()
    
    def merge_smc_with_classic(
        self,
        classic_context: dict,
        smc_result: dict,
    ) -> dict:
        """Merge SMC with classic analysis.
        
        Note: Accepts dict smc_result for backward compat.
        Converts to SMCAnalysis internally.
        """
        # For now, pass through - the service expects dict from legacy callers
        from brain.domain.entities.smc import (
            SMCAnalysis,
            OrderBlock,
            FairValueGap,
            LiquiditySweep,
            MarketStructure,
            PremiumDiscount,
            KillzoneSession,
            OrderBlockType,
            FVGType,
            StructurePhase,
            PremiumDiscountZone,
            POIGrade,
        )
        
        # Reconstruct entities from dict
        obs = [
            OrderBlock(
                ob_type=OrderBlockType(ob["type"]),
                high=ob["high"],
                low=ob["low"],
                open_price=ob["open"],
                close=ob["close"],
                index=ob["index"],
                mitigated=ob["mitigated"],
            )
            for ob in smc_result.get("order_blocks", [])
        ]
        
        unmitigated = [
            OrderBlock(
                ob_type=OrderBlockType(ob["type"]),
                high=ob["high"],
                low=ob["low"],
                open_price=ob["open"],
                close=ob["close"],
                index=ob["index"],
                mitigated=ob["mitigated"],
            )
            for ob in smc_result.get("active_order_blocks", [])
        ]
        
        fvgs = [
            FairValueGap(
                fvg_type=FVGType(fvg["type"]),
                low=fvg["low"],
                high=fvg["high"],
                c1_index=fvg["c1_index"],
                c3_index=fvg["c3_index"],
                filled=fvg["filled"],
            )
            for fvg in smc_result.get("fvgs", [])
        ]
        
        unfilled = [
            FairValueGap(
                fvg_type=FVGType(fvg["type"]),
                low=fvg["low"],
                high=fvg["high"],
                c1_index=fvg["c1_index"],
                c3_index=fvg["c3_index"],
                filled=fvg["filled"],
            )
            for fvg in smc_result.get("active_fvgs", [])
        ]
        
        sweep_data = smc_result.get("liquidity_sweep", {})
        liq_sweep = LiquiditySweep(
            swept=sweep_data.get("swept", False),
            swept_level=sweep_data.get("level"),
            sweep_side=sweep_data.get("sweep_side"),
        )
        
        structure_data = smc_result.get("market_structure", {})
        structure = MarketStructure(
            phase=StructurePhase(structure_data.get("phase", "range")),
            confidence=structure_data.get("confidence", 0.0),
        )
        
        h1_data = smc_result.get("h1_structure", {})
        h1_structure = None
        if h1_data and h1_data.get("phase") != "unknown":
            h1_structure = MarketStructure(
                phase=StructurePhase(h1_data["phase"]),
                confidence=h1_data.get("confidence", 0.0),
            )
        
        pd_data = smc_result.get("premium_discount", {})
        pd_zone = PremiumDiscount(
            zone=PremiumDiscountZone(pd_data.get("zone", "equilibrium")),
            fib_level=pd_data.get("fib_level", 0.5),
            quality=pd_data.get("quality", 0),
            swing_high=pd_data.get("swing_high", 0.0),
            swing_low=pd_data.get("swing_low", 0.0),
        )
        
        kz_data = smc_result.get("killzone", {})
        killzone = KillzoneSession(
            name=kz_data.get("session", "dead"),
            weight=kz_data.get("weight", 0.0),
        )
        
        poi_grade = POIGrade(smc_result.get("poi", "C"))
        
        analysis = SMCAnalysis(
            order_blocks=obs,
            unmitigated_obs=unmitigated,
            fvgs=fvgs,
            unfilled_fvgs=unfilled,
            liquidity_sweep=liq_sweep,
            structure=structure,
            h1_structure=h1_structure,
            pd_zone=pd_zone,
            killzone=killzone,
            poi_grade=poi_grade,
            smc_bias=smc_result.get("bias", "neutral"),
            bias_score=smc_result.get("confidence", 0.0),
            confidence=smc_result.get("signal_confidence", 0.0),
        )
        
        return self.service.merge_smc_with_classic(classic_context, analysis)
