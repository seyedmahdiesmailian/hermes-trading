import json
from pathlib import Path
from mt5_xau_runtime import _build_execution_sizing, _load_setup_profiles, _save_setup_profile


class FakeInfo:
    point = 0.01
    volume_min = 0.01
    volume_step = 0.01
    volume_max = 10.0


class TestMarginSafety:
    """Margin check prevents entry when free margin is too low relative to position risk."""

    def test_sufficient_margin_passes(self):
        policy = {
            "balance": 5000.0, "base_risk_pct": 0.02, "risk_multiplier": 1.0,
            "trade_allowed": True, "max_positions_allowed": 1, "open_positions": 0,
            "free_margin": 4500.0, "margin_required": 100.0,
        }
        bp = {"entry_price": 2000, "sl": 1990}
        sizing = _build_execution_sizing(bp, FakeInfo(), policy, "A")
        assert sizing["meaningful"] is True

    def test_low_margin_blocks_entry(self):
        policy = {
            "balance": 5000.0, "base_risk_pct": 0.02, "risk_multiplier": 1.0,
            "trade_allowed": True, "max_positions_allowed": 1, "open_positions": 0,
            "free_margin": 140.0, "margin_required": 100.0,  # ratio 1.4 < 1.5 threshold
        }
        bp = {"entry_price": 2000, "sl": 1990}
        sizing = _build_execution_sizing(bp, FakeInfo(), policy, "A")
        # Free margin is too low for safe operation
        assert sizing["meaningful"] is False
        assert "margin" in sizing.get("reason", "").lower()

    def test_margin_at_risk_ratio_blocks(self):
        policy = {
            "balance": 5000.0, "base_risk_pct": 0.02, "risk_multiplier": 1.0,
            "trade_allowed": True, "max_positions_allowed": 1, "open_positions": 0,
            "free_margin": 500.0, "margin_required": 400.0,
        }
        bp = {"entry_price": 2000, "sl": 1990}
        sizing = _build_execution_sizing(bp, FakeInfo(), policy, "A")
        # free_margin / margin_required = 1.25 < 1.5 buffer
        assert sizing["meaningful"] is False
        assert "margin" in sizing.get("reason", "").lower()

    def test_no_margin_info_skips_check(self):
        policy = {
            "balance": 5000.0, "base_risk_pct": 0.02, "risk_multiplier": 1.0,
            "trade_allowed": True, "max_positions_allowed": 1, "open_positions": 0,
            # no free_margin or margin_required
        }
        bp = {"entry_price": 2000, "sl": 1990}
        sizing = _build_execution_sizing(bp, FakeInfo(), policy, "A")
        # Should still work (skip margin check when info missing)
        assert sizing["meaningful"] is True


class TestSetupProfilePersistence:
    """Setup profiles save and load correctly via JSON file."""

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        test_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr("mt5_xau_runtime.SETUP_PROFILES_PATH", test_file)

        plan = {
            "plan_id": "plan_001",
            "quality": {"regime": "breakout_continuation", "alignment": "aligned", "trend_strength": 0.8},
            "session": "london",
            "bias": "long",
        }
        _save_setup_profile(12345, plan, "A")
        _save_setup_profile(12346, plan, "B")

        loaded = _load_setup_profiles()
        assert len(loaded) == 2
        assert loaded[0]["ticket"] == 12345
        assert loaded[0]["regime"] == "breakout_continuation"
        assert loaded[0]["grade"] == "A"
        assert loaded[1]["ticket"] == 12346
        assert loaded[1]["grade"] == "B"
