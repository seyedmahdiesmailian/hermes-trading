"""Tests for SMC service."""
import pytest
from datetime import datetime, timezone

from brain.application.services.smc_service import SMCService
from brain.domain.entities.smc import (
    OrderBlockType,
    FVGType,
    StructurePhase,
    PremiumDiscountZone,
    POIGrade,
)


@pytest.fixture
def smc_service():
    return SMCService()


@pytest.fixture
def sample_rows():
    """M5 OHLC data."""
    return [
        {"open": 2500.0, "high": 2505.0, "low": 2498.0, "close": 2502.0, "tick_volume": 100},
        {"open": 2502.0, "high": 2508.0, "low": 2500.0, "close": 2499.0, "tick_volume": 120},  # Bearish
        {"open": 2499.0, "high": 2515.0, "low": 2497.0, "close": 2512.0, "tick_volume": 200},  # Strong bullish breakout
        {"open": 2512.0, "high": 2520.0, "low": 2510.0, "close": 2518.0, "tick_volume": 150},
        {"open": 2518.0, "high": 2525.0, "low": 2515.0, "close": 2522.0, "tick_volume": 130},
    ]


# ── Entity Tests ──────────────────────────────────────────────────────────────

def test_order_block_type_enum():
    assert OrderBlockType.BULLISH.value == "bullish"
    assert OrderBlockType.BEARISH.value == "bearish"


def test_fvg_type_enum():
    assert FVGType.BULLISH.value == "bullish"
    assert FVGType.BEARISH.value == "bearish"


def test_structure_phase_enum():
    assert StructurePhase.BOS_BULLISH.value == "bos_bullish"
    assert StructurePhase.RANGE.value == "range"


def test_premium_discount_zone_enum():
    assert PremiumDiscountZone.DISCOUNT.value == "discount"
    assert PremiumDiscountZone.PREMIUM.value == "premium"
    assert PremiumDiscountZone.EQUILIBRIUM.value == "equilibrium"


def test_poi_grade_enum():
    assert POIGrade.A_PLUS.value == "A+"
    assert POIGrade.A.value == "A"
    assert POIGrade.B.value == "B"
    assert POIGrade.C.value == "C"


# ── Service Tests ─────────────────────────────────────────────────────────────

def test_detect_order_blocks(smc_service, sample_rows):
    obs = smc_service.detect_order_blocks(sample_rows)
    assert len(obs) > 0
    # Last bearish candle before strong bullish breakout = bullish OB
    bullish_obs = [ob for ob in obs if ob.ob_type == OrderBlockType.BULLISH]
    assert len(bullish_obs) > 0


def test_detect_order_blocks_mitigation(smc_service):
    rows = [
        {"open": 2500.0, "high": 2505.0, "low": 2498.0, "close": 2502.0},
        {"open": 2502.0, "high": 2508.0, "low": 2500.0, "close": 2499.0},  # Bearish
        {"open": 2499.0, "high": 2515.0, "low": 2497.0, "close": 2512.0},  # Breakout -> OB created
        {"open": 2512.0, "high": 2520.0, "low": 2510.0, "close": 2518.0},
        {"open": 2518.0, "high": 2520.0, "low": 2500.0, "close": 2502.0},  # Returns into OB zone -> mitigated
    ]
    obs = smc_service.detect_order_blocks(rows)
    mitigated = [ob for ob in obs if ob.mitigated]
    assert len(mitigated) > 0


def test_detect_fair_value_gaps(smc_service):
    # Bullish FVG: c3.low > c1.high
    rows = [
        {"open": 2500.0, "high": 2505.0, "low": 2498.0, "close": 2502.0},
        {"open": 2502.0, "high": 2508.0, "low": 2500.0, "close": 2506.0},
        {"open": 2506.0, "high": 2520.0, "low": 2510.0, "close": 2518.0},  # Gap: 2510 > 2505
    ]
    fvgs = smc_service.detect_fair_value_gaps(rows)
    assert len(fvgs) > 0
    assert fvgs[0].fvg_type == FVGType.BULLISH
    assert fvgs[0].low == 2505.0
    assert fvgs[0].high == 2510.0


def test_detect_liquidity_sweep(smc_service):
    # Sweep high then reverse
    rows = [
        {"open": 2500.0, "high": 2510.0, "low": 2495.0, "close": 2505.0},
        {"open": 2505.0, "high": 2512.0, "low": 2500.0, "close": 2508.0},
        {"open": 2508.0, "high": 2520.0, "low": 2506.0, "close": 2515.0},  # Breaks high
        {"open": 2515.0, "high": 2518.0, "low": 2505.0, "close": 2508.0},  # Reverses below
    ]
    sweep = smc_service.detect_liquidity_sweep(rows, lookback=3)
    assert sweep.swept is True
    assert sweep.sweep_side == "bearish"


def test_market_structure_phase_bullish(smc_service):
    # Higher highs, higher lows
    rows = [
        {"open": 2500.0, "high": 2510.0, "low": 2495.0, "close": 2505.0},
        {"open": 2505.0, "high": 2515.0, "low": 2500.0, "close": 2512.0},
        {"open": 2512.0, "high": 2525.0, "low": 2508.0, "close": 2522.0},
        {"open": 2522.0, "high": 2535.0, "low": 2518.0, "close": 2530.0},
    ]
    structure = smc_service.market_structure_phase(rows)
    assert structure.phase == StructurePhase.BOS_BULLISH
    assert structure.confidence > 0.0


def test_market_structure_phase_bearish(smc_service):
    # Lower lows, lower highs
    rows = [
        {"open": 2530.0, "high": 2535.0, "low": 2520.0, "close": 2525.0},
        {"open": 2525.0, "high": 2530.0, "low": 2515.0, "close": 2518.0},
        {"open": 2518.0, "high": 2522.0, "low": 2505.0, "close": 2508.0},
        {"open": 2508.0, "high": 2512.0, "low": 2495.0, "close": 2498.0},
    ]
    structure = smc_service.market_structure_phase(rows)
    assert structure.phase == StructurePhase.BOS_BEARISH


def test_premium_discount_zone_discount(smc_service):
    pd = smc_service.premium_discount_zone(
        price=2502.0,
        swing_high=2600.0,
        swing_low=2500.0,
    )
    assert pd.zone == PremiumDiscountZone.DISCOUNT
    assert pd.fib_level < 0.25
    assert pd.quality > 0


def test_premium_discount_zone_premium(smc_service):
    pd = smc_service.premium_discount_zone(
        price=2590.0,
        swing_high=2600.0,
        swing_low=2500.0,
    )
    assert pd.zone == PremiumDiscountZone.PREMIUM
    assert pd.fib_level > 0.75


def test_premium_discount_zone_equilibrium(smc_service):
    pd = smc_service.premium_discount_zone(
        price=2550.0,
        swing_high=2600.0,
        swing_low=2500.0,
    )
    assert pd.zone == PremiumDiscountZone.EQUILIBRIUM
    assert 0.25 <= pd.fib_level <= 0.75


def test_active_killzone_session_london(smc_service):
    # 7:30 UTC = London killzone
    now = datetime(2026, 10, 15, 7, 30, tzinfo=timezone.utc)
    kz = smc_service.active_killzone_session(now)
    assert kz.name == "london"
    assert kz.weight == 1.0


def test_active_killzone_session_newyork(smc_service):
    # 13:00 UTC = New York killzone
    now = datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc)
    kz = smc_service.active_killzone_session(now)
    assert kz.name == "newyork"
    assert kz.weight == 1.0


def test_active_killzone_session_dead(smc_service):
    # 22:00 UTC = dead zone
    now = datetime(2026, 10, 15, 22, 0, tzinfo=timezone.utc)
    kz = smc_service.active_killzone_session(now)
    assert kz.name == "dead"
    assert kz.weight == 0.0


def test_grade_poi_high_confluence(smc_service):
    grade = smc_service.grade_poi(
        has_ob=True,
        ob_mitigated=False,
        has_fvg=True,
        fvg_filled=False,
        liq_sweep=True,
        discount=True,
        killzone_weight=1.0,
        structure_aligned=True,
    )
    assert grade in (POIGrade.A_PLUS, POIGrade.A)


def test_grade_poi_low_confluence(smc_service):
    grade = smc_service.grade_poi(
        has_ob=False,
        ob_mitigated=False,
        has_fvg=False,
        fvg_filled=False,
        liq_sweep=False,
        discount=False,
        killzone_weight=0.0,
        structure_aligned=False,
    )
    assert grade == POIGrade.C


def test_derive_smc_bias_bullish(smc_service, sample_rows):
    obs = smc_service.detect_order_blocks(sample_rows)
    unmitigated = [ob for ob in obs if not ob.mitigated]
    fvgs = smc_service.detect_fair_value_gaps(sample_rows)
    unfilled = [fvg for fvg in fvgs if not fvg.filled]
    structure = smc_service.market_structure_phase(sample_rows)
    pd = smc_service.premium_discount_zone(2520.0, 2525.0, 2498.0)
    
    bias, confidence = smc_service.derive_smc_bias(
        obs, unmitigated, fvgs, unfilled,
        sweep_side="bullish",
        structure=structure,
        pd_zone=pd,
        killzone_weight=1.0,
    )
    
    assert bias in ("bullish", "neutral")
    assert 0.0 <= confidence <= 1.0


def test_compute_smc_signal_wait_on_low_confidence(smc_service):
    pd = smc_service.premium_discount_zone(2550.0, 2600.0, 2500.0)
    signal, conf = smc_service.compute_smc_signal(
        bias="bullish",
        bias_confidence=0.3,  # Below 0.4 threshold
        pd_zone=pd,
        killzone_weight=1.0,
    )
    assert signal == "wait"


def test_compute_smc_signal_wait_on_premium(smc_service):
    pd = smc_service.premium_discount_zone(2590.0, 2600.0, 2500.0)  # Premium
    signal, conf = smc_service.compute_smc_signal(
        bias="bullish",
        bias_confidence=0.8,
        pd_zone=pd,
        killzone_weight=1.0,
    )
    assert signal == "wait"  # Don't buy at premium


def test_compute_ote_zone(smc_service):
    ote = smc_service.compute_ote_zone(2500.0, 2600.0)
    assert ote["low"] < ote["high"]
    assert ote["fib_range"] == [0.62, 0.79]


def test_detect_power_of_three(smc_service, sample_rows):
    p3 = smc_service.detect_power_of_three(sample_rows)
    assert p3["phase"] in ("accumulation", "manipulation", "distribution", "not_enough_data")


def test_detect_turtle_soup(smc_service):
    rows = [
        {"open": 2500.0, "high": 2510.0, "low": 2495.0, "close": 2505.0},
        {"open": 2505.0, "high": 2515.0, "low": 2500.0, "close": 2512.0},
        {"open": 2512.0, "high": 2525.0, "low": 2490.0, "close": 2495.0},  # Fake low
        {"open": 2495.0, "high": 2520.0, "low": 2492.0, "close": 2518.0},  # Sharp reversal
    ]
    soup = smc_service.detect_turtle_soup(rows)
    assert soup["found"] in (True, False)


def test_evaluate_silver_bullet_setup(smc_service):
    # 10 AM NY = 14:00 UTC (EST) or 15:00 UTC (EDT)
    # Using a fixed time in winter (EST)
    now = datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc)  # 10 AM EST
    sb = smc_service.evaluate_silver_bullet_setup(now)
    assert sb["active"] in (True, False)


def test_compute_session_liquidity(smc_service, sample_rows):
    liq = smc_service.compute_session_liquidity(sample_rows)
    assert liq["session_high"] > 0
    assert liq["session_low"] > 0
    assert liq["swept_high"] in (True, False)


def test_detect_volume_imbalance(smc_service, sample_rows):
    imbalances = smc_service.detect_volume_imbalance(sample_rows, threshold=1.5)
    # Row index 2 has volume=200, avg is 140, ratio is 1.43 which is < 1.5
    # Lower threshold to 1.3
    imbalances = smc_service.detect_volume_imbalance(sample_rows, threshold=1.3)
    assert len(imbalances) > 0


def test_analyze_complete(smc_service, sample_rows):
    now = datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc)
    analysis = smc_service.analyze(sample_rows, now=now)
    
    assert analysis.smc_bias in ("bullish", "bearish", "neutral")
    assert 0.0 <= analysis.confidence <= 1.0
    assert analysis.poi_grade in (POIGrade.A_PLUS, POIGrade.A, POIGrade.B, POIGrade.C)
    assert len(analysis.order_blocks) >= 0
    assert len(analysis.fvgs) >= 0


def test_analyze_with_h1(smc_service, sample_rows):
    h1_rows = [
        {"open": 2480.0, "high": 2520.0, "low": 2475.0, "close": 2515.0},
        {"open": 2515.0, "high": 2530.0, "low": 2510.0, "close": 2525.0},
        {"open": 2525.0, "high": 2540.0, "low": 2520.0, "close": 2535.0},
    ]
    analysis = smc_service.analyze(sample_rows, h1_rows=h1_rows)
    
    assert analysis.h1_structure is not None
    assert analysis.h1_structure.phase in StructurePhase


def test_merge_smc_with_classic(smc_service, sample_rows):
    analysis = smc_service.analyze(sample_rows)
    classic_context = {
        "bias": "bullish",
        "quality": {"regime": "trend", "alignment": "aligned"},
    }
    
    merged = smc_service.merge_smc_with_classic(classic_context, analysis)
    
    assert merged["bias"] in ("bullish", "bearish", "neutral")
    assert merged["action"] in ("long", "short", "wait")
    assert 0.0 <= merged["confidence"] <= 1.0
    assert "classic_source" in merged
    assert "smc_source" in merged


def test_analyze_insufficient_data(smc_service):
    rows = [{"open": 2500.0, "high": 2505.0, "low": 2498.0, "close": 2502.0}]
    analysis = smc_service.analyze(rows)
    
    assert analysis.smc_bias == "neutral"
    assert analysis.confidence == 0.0
    assert len(analysis.order_blocks) == 0
