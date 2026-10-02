from mt5_xau_report import render_management_brief


def test_render_management_brief_for_partial_take_profit_is_persian_and_compact():
    brief = render_management_brief(
        plan={"symbol": "XAUUSD", "bias": "bullish"},
        management={
            "action": "partial_take_profit",
            "target_hit": 4310.0,
            "close_fraction": 0.3,
            "reason": "strong_runner_keep_more",
        },
    )

    assert brief.splitlines()[0].startswith("🛠 مدیریت معامله | طلا")
    assert "برداشت بخشی از سود" in brief
    assert "30٪" in brief


def test_render_management_brief_for_runner_kill_explains_exit():
    brief = render_management_brief(
        plan={"symbol": "XAUUSD", "bias": "bullish"},
        management={
            "action": "close_runner",
            "close_fraction": 1.0,
            "reason": "runner_structure_failure",
        },
    )

    assert "بستن رانر" in brief
    assert "خروج کامل" in brief
