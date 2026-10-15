"""Integration tests for DEFCON legacy adapter.

Verifies that the adapter maintains perfect backward compatibility.
"""

import unittest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from legacy_v1.adapters import defcon_adapter
from legacy_v1.engines import defcon as legacy_defcon


class TestDefconAdapterCompatibility(unittest.TestCase):
    """Test adapter produces same output as legacy code."""
    
    def test_classify_exit_compatibility(self):
        """Test classify_exit matches legacy."""
        test_cases = [
            ("[sl 2600.0]", -50.0, "sl"),
            ("[tp 2620.0]", 100.0, "tp"),
            ("Hermes manage", 50.0, "managed"),
            ("random comment", 10.0, "unknown"),
        ]
        
        for comment, profit, expected in test_cases:
            with self.subTest(comment=comment):
                legacy_result = legacy_defcon.classify_exit(comment, profit)
                adapter_result = defcon_adapter.classify_exit(comment, profit)
                self.assertEqual(legacy_result, adapter_result)
                self.assertEqual(adapter_result, expected)
    
    def test_classify_exits_compatibility(self):
        """Test classify_exits matches legacy."""
        deals = [
            {"ticket": 1, "profit": 100.0, "comment": "[tp 2620]"},
            {"ticket": 2, "profit": -50.0, "comment": "[sl 2590]"},
            {"ticket": 3, "profit": 30.0, "comment": "Hermes manage"},
        ]
        
        legacy_result = legacy_defcon.classify_exits(deals)
        adapter_result = defcon_adapter.classify_exits(deals)
        
        # Same number of results
        self.assertEqual(len(legacy_result), len(adapter_result))
        
        # Same classification for each
        for i in range(len(deals)):
            self.assertEqual(
                legacy_result[i]["exit_type"],
                adapter_result[i]["exit_type"]
            )
    
    def test_analyze_exits_compatibility(self):
        """Test analyze_exits matches legacy."""
        classified = [
            {"ticket": 1, "profit": 100.0, "exit_type": "tp"},
            {"ticket": 2, "profit": -50.0, "exit_type": "sl"},
            {"ticket": 3, "profit": -40.0, "exit_type": "sl"},
            {"ticket": 4, "profit": 30.0, "exit_type": "managed"},
            {"ticket": 5, "profit": -20.0, "exit_type": "managed"},
        ]
        
        legacy_result = legacy_defcon.analyze_exits(classified)
        adapter_result = defcon_adapter.analyze_exits(classified)
        
        # Same keys
        self.assertEqual(set(legacy_result.keys()), set(adapter_result.keys()))
        
        # Same values
        for key in legacy_result:
            with self.subTest(key=key):
                self.assertEqual(legacy_result[key], adapter_result[key])
    
    def test_compute_insights_green_compatibility(self):
        """Test compute_insights GREEN matches legacy."""
        classified = [
            {"ticket": 1, "profit": 100.0, "exit_type": "tp"},
            {"ticket": 2, "profit": 80.0, "exit_type": "tp"},
        ]
        
        legacy_result = legacy_defcon.compute_insights(
            loss_streak=0,
            daily_pnl=180.0,
            classified=classified,
        )
        
        adapter_result = defcon_adapter.compute_insights(
            loss_streak=0,
            daily_pnl=180.0,
            classified=classified,
        )
        
        # Same DEFCON level
        self.assertEqual(legacy_result["defcon"], adapter_result["defcon"])
        self.assertEqual(adapter_result["defcon"], "GREEN")
        
        # Same restrictions
        self.assertEqual(legacy_result["trade_allowed"], adapter_result["trade_allowed"])
        self.assertEqual(legacy_result["runner_allowed"], adapter_result["runner_allowed"])
        self.assertEqual(legacy_result["scale_in_allowed"], adapter_result["scale_in_allowed"])
    
    def test_compute_insights_yellow_compatibility(self):
        """Test compute_insights YELLOW matches legacy."""
        legacy_result = legacy_defcon.compute_insights(
            loss_streak=2,
            daily_pnl=-100.0,
            classified=[],
        )
        
        adapter_result = defcon_adapter.compute_insights(
            loss_streak=2,
            daily_pnl=-100.0,
            classified=[],
        )
        
        self.assertEqual(legacy_result["defcon"], "YELLOW")
        self.assertEqual(adapter_result["defcon"], "YELLOW")
        self.assertEqual(legacy_result["risk_override"], 0.5)
        self.assertEqual(adapter_result["risk_override"], 0.5)
        self.assertFalse(adapter_result["runner_allowed"])
    
    def test_compute_insights_red_compatibility(self):
        """Test compute_insights RED matches legacy."""
        classified = [
            {"ticket": 1, "profit": -50.0, "exit_type": "sl"},
            {"ticket": 2, "profit": -40.0, "exit_type": "sl"},
            {"ticket": 3, "profit": -30.0, "exit_type": "sl"},
            {"ticket": 4, "profit": 10.0, "exit_type": "tp"},
            {"ticket": 5, "profit": 5.0, "exit_type": "tp"},
        ]
        
        legacy_result = legacy_defcon.compute_insights(
            loss_streak=3,
            daily_pnl=-105.0,
            classified=classified,
        )
        
        adapter_result = defcon_adapter.compute_insights(
            loss_streak=3,
            daily_pnl=-105.0,
            classified=classified,
        )
        
        self.assertEqual(legacy_result["defcon"], "RED")
        self.assertEqual(adapter_result["defcon"], "RED")
        self.assertFalse(adapter_result["trade_allowed"])
    
    def test_filter_management_compatibility(self):
        """Test filter_management_by_insights matches legacy."""
        insights = {
            "defcon": "YELLOW",
            "risk_override": 0.5,
            "trade_allowed": True,
            "runner_allowed": False,
            "scale_in_allowed": False,
            "exit_stats": {
                "total": 3,
                "sl_count": 2,
                "tp_count": 1,
                "managed_count": 0,
                "managed_win_ratio": None,
                "managed_total_pnl": 0.0,
                "sl_ratio": 0.667,
                "sl_dominant": True,
            },
        }
        
        # Test runner escalation
        management = {"action": "trail_stop", "distance": 10}
        
        legacy_result = legacy_defcon.filter_management_by_insights(management, insights)
        adapter_result = defcon_adapter.filter_management_by_insights(management, insights)
        
        # Both should escalate to close_runner
        self.assertEqual(legacy_result["action"], "close_runner")
        self.assertEqual(adapter_result["action"], "close_runner")
        self.assertEqual(adapter_result["close_fraction"], 1.0)


if __name__ == '__main__':
    unittest.main()
