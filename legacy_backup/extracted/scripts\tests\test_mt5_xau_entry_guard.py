from mt5_xau_runtime import _filter_entry_by_insights


class TestFilterEntryByInsights:
    def test_green_allows_entry_unchanged(self):
        insights = {"defcon": "green", "trade_allowed": True, "risk_override": None}
        out = _filter_entry_by_insights(True, None, insights)
        assert out["allowed"] is True
        assert out["risk_pct_override"] is None

    def test_yellow_allows_with_reduced_risk(self):
        insights = {"defcon": "yellow", "trade_allowed": True, "risk_override": 0.01125}
        out = _filter_entry_by_insights(True, None, insights)
        assert out["allowed"] is True
        assert out["risk_pct_override"] == 0.01125

    def test_red_blocks_entry(self):
        insights = {"defcon": "red", "trade_allowed": False, "risk_override": 0.0}
        out = _filter_entry_by_insights(True, None, insights)
        assert out["allowed"] is False

    def test_grade_c_still_blocked_by_policy_even_on_green(self):
        insights = {"defcon": "green", "trade_allowed": True, "risk_override": None}
        out = _filter_entry_by_insights(False, "setup_grade_block", insights)
        assert out["allowed"] is False
        assert out["reason"] == "setup_grade_block"

    def test_none_insights_no_filtering(self):
        out = _filter_entry_by_insights(True, None, None)
        assert out["allowed"] is True
        assert out["risk_pct_override"] is None
