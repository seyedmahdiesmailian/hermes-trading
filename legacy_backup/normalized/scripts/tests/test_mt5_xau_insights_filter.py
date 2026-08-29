from mt5_xau_runtime import _filter_management_by_insights


class TestFilterManagementByInsights:
    def test_green_allows_all_actions(self):
        insights = {
            "defcon": "green",
            "runner_allowed": True,
            "scale_in_allowed": True,
            "trade_allowed": True,
            "partial_allowed": True,
        }

        assert _filter_management_by_insights({"action": "partial_take_profit"}, insights)["action"] == "partial_take_profit"
        assert _filter_management_by_insights({"action": "trail_stop"}, insights)["action"] == "trail_stop"
        assert _filter_management_by_insights({"action": "scale_in_existing_idea"}, insights)["action"] == "scale_in_existing_idea"
        assert _filter_management_by_insights({"action": "close_runner"}, insights)["action"] == "close_runner"
        assert _filter_management_by_insights({"action": "hold"}, insights)["action"] == "hold"

    def test_yellow_blocks_runner_converts_to_close(self):
        insights = {
            "defcon": "yellow",
            "runner_allowed": False,
            "scale_in_allowed": False,
            "trade_allowed": True,
            "partial_allowed": True,
        }

        # trail → close runner (don't let it trail, kill it)
        out = _filter_management_by_insights({"action": "trail_stop", "reason": "strong_runner_looser_trail"}, insights)
        assert out["action"] == "close_runner"
        assert "insights:defcon_yellow" in out.get("reason", "")

        # scale_in → hold
        out = _filter_management_by_insights({"action": "scale_in_existing_idea", "reason": "valid_pullback_add"}, insights)
        assert out["action"] == "hold"
        assert "insights:defcon_yellow" in out.get("reason", "")

        # partial and breakeven still allowed
        out = _filter_management_by_insights({"action": "partial_take_profit"}, insights)
        assert out["action"] == "partial_take_profit"

        out = _filter_management_by_insights({"action": "move_stop_to_breakeven"}, insights)
        assert out["action"] == "move_stop_to_breakeven"

    def test_red_blocks_all_except_close_and_partial(self):
        insights = {
            "defcon": "red",
            "runner_allowed": False,
            "scale_in_allowed": False,
            "trade_allowed": False,
            "partial_allowed": True,
        }

        # trail → close
        out = _filter_management_by_insights({"action": "trail_stop"}, insights)
        assert out["action"] == "close_runner"

        # scale_in → hold
        out = _filter_management_by_insights({"action": "scale_in_existing_idea"}, insights)
        assert out["action"] == "hold"

        # partial still OK
        out = _filter_management_by_insights({"action": "partial_take_profit"}, insights)
        assert out["action"] == "partial_take_profit"

        # close early still OK
        out = _filter_management_by_insights({"action": "close_trade_early"}, insights)
        assert out["action"] == "close_trade_early"

    def test_hold_never_blocked(self):
        insights = {
            "defcon": "red",
            "runner_allowed": False,
            "scale_in_allowed": False,
            "trade_allowed": False,
            "partial_allowed": True,
        }
        out = _filter_management_by_insights({"action": "hold"}, insights)
        assert out["action"] == "hold"
