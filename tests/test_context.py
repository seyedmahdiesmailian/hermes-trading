"""Unit tests for Context service and entities.

Tests the refactored market context analysis system.

Run with:
    python3 -m pytest tests/test_context.py -v
"""

import unittest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from brain.domain.entities.context import (
    MarketBias,
    ZoneSource,
    PriceZones,
    ExecutionPlan,
    MarketContext,
)
from brain.application.services.context_service import ContextService


class TestContextEntities(unittest.TestCase):
    """Test context domain entities."""
    
    def test_market_bias_enum(self):
        """Test MarketBias enum."""
        self.assertEqual(MarketBias.BULLISH.value, "bullish")
        self.assertEqual(MarketBias.BEARISH.value, "bearish")
        self.assertEqual(MarketBias.NEUTRAL.value, "neutral")
    
    def test_price_zones_properties(self):
        """Test PriceZones convenience properties."""
        zones = PriceZones(
            value_low=2100.0,
            value_high=2120.0,
            long_entry_low=2090.0,
            long_entry_high=2100.0,
            short_entry_low=2120.0,
            short_entry_high=2130.0,
            swing_low=2090.0,
            swing_high=2130.0,
            zone_source=ZoneSource.H1_SWING,
        )
        
        self.assertEqual(zones.discount_zone, (2090.0, 2100.0))
        self.assertEqual(zones.premium_zone, (2120.0, 2130.0))
        self.assertEqual(zones.value_zone, (2100.0, 2120.0))
    
    def test_price_zones_to_dict(self):
        """Test PriceZones dict conversion."""
        zones = PriceZones(
            value_low=2100.0,
            value_high=2120.0,
            long_entry_low=2090.0,
            long_entry_high=2100.0,
            short_entry_low=2120.0,
            short_entry_high=2130.0,
            swing_low=2090.0,
            swing_high=2130.0,
            zone_source=ZoneSource.H1_SWING,
        )
        
        d = zones.to_dict()
        self.assertEqual(d['value_low'], 2100.0)
        self.assertEqual(d['zone_source'], 'h1_swing')


class TestContextService(unittest.TestCase):
    """Test ContextService logic."""
    
    def setUp(self):
        """Create service."""
        self.service = ContextService(db=None)
    
    def test_estimate_atr_basic(self):
        """Test ATR calculation."""
        rows = [
            {'high': 2100, 'low': 2090, 'close': 2095},
            {'high': 2105, 'low': 2095, 'close': 2100},
            {'high': 2110, 'low': 2098, 'close': 2108},
            {'high': 2115, 'low': 2105, 'close': 2110},
            {'high': 2120, 'low': 2108, 'close': 2118},
            {'high': 2125, 'low': 2115, 'close': 2120},
            {'high': 2130, 'low': 2118, 'close': 2128},
            {'high': 2135, 'low': 2125, 'close': 2130},
            {'high': 2140, 'low': 2128, 'close': 2138},
            {'high': 2145, 'low': 2135, 'close': 2140},
            {'high': 2150, 'low': 2138, 'close': 2148},
            {'high': 2155, 'low': 2145, 'close': 2150},
            {'high': 2160, 'low': 2148, 'close': 2158},
            {'high': 2165, 'low': 2155, 'close': 2160},
            {'high': 2170, 'low': 2158, 'close': 2168},
        ]
        
        atr = self.service.estimate_atr(rows)
        self.assertGreater(atr, 0)
        self.assertLess(atr, 20)  # Reasonable range
    
    def test_estimate_atr_with_gap(self):
        """Test ATR includes gaps."""
        rows = [
            {'high': 2100, 'low': 2090, 'close': 2095},
            {'high': 2150, 'low': 2140, 'close': 2145},  # Gap up
        ]
        
        atr = self.service.estimate_atr(rows)
        self.assertGreater(atr, 40)  # Should capture the gap
    
    def test_classify_bias_bullish(self):
        """Test bullish bias classification."""
        rows = [
            {'high': 2100, 'low': 2090, 'close': 2095, 'open': 2090},
            {'high': 2105, 'low': 2095, 'close': 2100, 'open': 2095},
            {'high': 2110, 'low': 2100, 'close': 2108, 'open': 2100},
            {'high': 2115, 'low': 2105, 'close': 2112, 'open': 2108},
            {'high': 2120, 'low': 2110, 'close': 2118, 'open': 2112},
        ]
        
        bias = self.service.classify_bias(rows)
        self.assertEqual(bias, MarketBias.BULLISH)
    
    def test_classify_bias_bearish(self):
        """Test bearish bias classification."""
        rows = [
            {'high': 2120, 'low': 2110, 'close': 2115, 'open': 2120},
            {'high': 2115, 'low': 2105, 'close': 2108, 'open': 2115},
            {'high': 2110, 'low': 2100, 'close': 2102, 'open': 2108},
            {'high': 2105, 'low': 2095, 'close': 2098, 'open': 2102},
            {'high': 2100, 'low': 2090, 'close': 2092, 'open': 2098},
        ]
        
        bias = self.service.classify_bias(rows)
        self.assertEqual(bias, MarketBias.BEARISH)
    
    def test_classify_bias_neutral(self):
        """Test neutral bias classification."""
        rows = [
            {'high': 2105, 'low': 2095, 'close': 2100, 'open': 2095},
            {'high': 2105, 'low': 2095, 'close': 2098, 'open': 2100},
            {'high': 2105, 'low': 2095, 'close': 2102, 'open': 2098},
            {'high': 2105, 'low': 2095, 'close': 2099, 'open': 2102},
            {'high': 2105, 'low': 2095, 'close': 2101, 'open': 2099},
        ]
        
        bias = self.service.classify_bias(rows)
        self.assertEqual(bias, MarketBias.NEUTRAL)
    
    def test_compute_m5_zones(self):
        """Test M5 zone computation."""
        rows = [
            {'high': 2105, 'low': 2095, 'close': 2100},
            {'high': 2110, 'low': 2100, 'close': 2105},
            {'high': 2115, 'low': 2105, 'close': 2110},
            {'high': 2120, 'low': 2110, 'close': 2115},
            {'high': 2125, 'low': 2115, 'close': 2120},
            {'high': 2130, 'low': 2120, 'close': 2125},
            {'high': 2135, 'low': 2125, 'close': 2130},
            {'high': 2140, 'low': 2130, 'close': 2135},
            {'high': 2145, 'low': 2135, 'close': 2140},
            {'high': 2150, 'low': 2140, 'close': 2145},
            {'high': 2155, 'low': 2145, 'close': 2150},
            {'high': 2160, 'low': 2150, 'close': 2155},
        ]
        
        zones = self.service.compute_m5_zones(rows, atr=10.0)
        
        self.assertIsInstance(zones, PriceZones)
        self.assertLess(zones.value_low, zones.value_high)
        self.assertLess(zones.long_entry_low, zones.long_entry_high)
        self.assertEqual(zones.zone_source, ZoneSource.M5_TIGHT)
    
    def test_compute_htf_structure_zones(self):
        """Test HTF zone computation."""
        rows = [{'high': 2100 + i*5, 'low': 2090 + i*5, 'close': 2095 + i*5} for i in range(30)]
        
        zones = self.service.compute_htf_structure_zones(rows, atr=10.0)
        
        self.assertIsNotNone(zones)
        self.assertLess(zones.value_low, zones.value_high)
        self.assertIsNotNone(zones.swing_low)
        self.assertIsNotNone(zones.swing_high)
    
    def test_detect_alignment_aligned(self):
        """Test aligned bias detection."""
        alignment = self.service.detect_alignment(
            MarketBias.BULLISH,
            MarketBias.BULLISH,
            MarketBias.BULLISH,
        )
        self.assertEqual(alignment, "aligned")
    
    def test_detect_alignment_mixed(self):
        """Test mixed bias detection."""
        alignment = self.service.detect_alignment(
            MarketBias.BULLISH,
            MarketBias.BEARISH,
            MarketBias.NEUTRAL,
        )
        self.assertEqual(alignment, "mixed")
    
    def test_detect_alignment_neutral(self):
        """Test neutral alignment."""
        alignment = self.service.detect_alignment(
            MarketBias.NEUTRAL,
            MarketBias.NEUTRAL,
            MarketBias.NEUTRAL,
        )
        self.assertEqual(alignment, "neutral")
    
    def test_detect_regime_range(self):
        """Test range regime detection."""
        zones = PriceZones(
            value_low=2100.0,
            value_high=2120.0,
            long_entry_low=2090.0,
            long_entry_high=2100.0,
            short_entry_low=2120.0,
            short_entry_high=2130.0,
        )
        
        regime = self.service.detect_regime(
            bias=MarketBias.NEUTRAL,
            alignment="neutral",
            trend_strength=0.2,
            last_price=2110.0,
            zones=zones,
            atr=10.0,
            m5_bias=MarketBias.NEUTRAL,
            h1_bias=MarketBias.NEUTRAL,
            h4_bias=MarketBias.NEUTRAL,
        )
        
        self.assertEqual(regime, "range")
    
    def test_detect_regime_breakout(self):
        """Test breakout regime detection."""
        zones = PriceZones(
            value_low=2100.0,
            value_high=2120.0,
            long_entry_low=2090.0,
            long_entry_high=2100.0,
            short_entry_low=2120.0,
            short_entry_high=2130.0,
        )
        
        regime = self.service.detect_regime(
            bias=MarketBias.BULLISH,
            alignment="aligned",
            trend_strength=0.5,
            last_price=2125.0,  # Above value_high
            zones=zones,
            atr=10.0,
            m5_bias=MarketBias.BULLISH,
            h1_bias=MarketBias.BULLISH,
            h4_bias=MarketBias.BULLISH,
        )
        
        self.assertEqual(regime, "breakout_continuation")
    
    def test_detect_regime_pullback(self):
        """Test pullback regime detection."""
        zones = PriceZones(
            value_low=2100.0,
            value_high=2120.0,
            long_entry_low=2090.0,
            long_entry_high=2100.0,
            short_entry_low=2120.0,
            short_entry_high=2130.0,
        )
        
        regime = self.service.detect_regime(
            bias=MarketBias.BULLISH,
            alignment="aligned",
            trend_strength=0.5,
            last_price=2105.0,  # In discount zone
            zones=zones,
            atr=10.0,
            m5_bias=MarketBias.BULLISH,
            h1_bias=MarketBias.BULLISH,
            h4_bias=MarketBias.BULLISH,
        )
        
        self.assertEqual(regime, "pullback_continuation")
    
    def test_distance_in_atr(self):
        """Test ATR distance calculation."""
        dist = self.service.distance_in_atr(2110.0, 2100.0, 10.0)
        self.assertAlmostEqual(dist, 1.0, places=2)
        
        dist_zero = self.service.distance_in_atr(2100.0, 2100.0, 10.0)
        self.assertEqual(dist_zero, 0.0)
    
    def test_build_execution_plan_range(self):
        """Test range execution plan."""
        zones = PriceZones(
            value_low=2100.0,
            value_high=2120.0,
            long_entry_low=2090.0,
            long_entry_high=2100.0,
            short_entry_low=2120.0,
            short_entry_high=2130.0,
        )
        
        plan = self.service.build_execution_plan(
            bias=MarketBias.NEUTRAL,
            zones=zones,
            atr=10.0,
            regime="range",
        )
        
        self.assertEqual(plan['entry_mode'], 'mean_reversion_wait')
        self.assertEqual(len(plan['tp_levels']), 2)
    
    def test_build_execution_plan_bullish_pullback(self):
        """Test bullish pullback execution plan."""
        zones = PriceZones(
            value_low=2100.0,
            value_high=2120.0,
            long_entry_low=2090.0,
            long_entry_high=2100.0,
            short_entry_low=2120.0,
            short_entry_high=2130.0,
        )
        
        plan = self.service.build_execution_plan(
            bias=MarketBias.BULLISH,
            zones=zones,
            atr=10.0,
            regime="pullback_continuation",
        )
        
        self.assertEqual(plan['entry_mode'], 'scale_in_pullback')
        self.assertEqual(len(plan['tp_levels']), 3)
        self.assertGreater(len(plan['scale_in_levels']), 0)


if __name__ == '__main__':
    unittest.main()
