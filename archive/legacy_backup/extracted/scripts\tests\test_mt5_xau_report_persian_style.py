from mt5_xau_report import render_execution_brief, render_reassess_brief


def test_render_reassess_brief_uses_persian_symbol_name_and_no_change_wording():
    old_plan = {
        "symbol": "XAUUSD",
        "bias": "bullish",
        "zones": {
            "long_entry_low": 4120.19,
            "long_entry_high": 4126.97,
            "short_entry_low": 4290.23,
            "short_entry_high": 4297.01,
        },
    }
    new_plan = {
        "symbol": "XAUUSD",
        "bias": "bullish",
        "zones": {
            "long_entry_low": 4120.19,
            "long_entry_high": 4126.97,
            "short_entry_low": 4290.23,
            "short_entry_high": 4297.01,
        },
        "next_reassessment": "2026-08-07T17:09:00+00:00",
    }
    text = render_reassess_brief(old_plan, new_plan)
    assert "طلا" in text
    assert "XAUUSD" not in text
    assert "جهت | صعودی" in text
    assert "تغییر جهت | از صعودی به صعودی" not in text


def test_render_execution_brief_is_fully_persian():
    plan = {"symbol": "XAUUSD"}
    execution = {"ok": True, "command": ["buy", "XAUUSD", "0.05"]}
    text = render_execution_brief(plan, execution)
    assert "طلا" in text
    assert "XAUUSD" not in text
    assert "خرید" in text
    assert "موفق" in text
