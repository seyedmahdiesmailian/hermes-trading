from mt5_xau_report import render_execution_brief, render_plan_brief, render_reassess_brief


def test_render_plan_brief_has_plan_headline():
    plan = {
        "symbol": "XAUUSD",
        "bias": "bullish",
        "zones": {
            "long_entry_low": 4226.0,
            "long_entry_high": 4232.0,
            "short_entry_low": 4252.0,
            "short_entry_high": 4258.0,
        },
        "next_reassessment": "2026-08-07T13:00:00+00:00",
    }
    text = render_plan_brief(plan)
    assert text.splitlines()[0].startswith("📘 پلن جدید")


def test_render_reassess_brief_has_reassess_headline_and_bias_change():
    old_plan = {"bias": "bullish"}
    new_plan = {
        "symbol": "XAUUSD",
        "bias": "bearish",
        "zones": {
            "long_entry_low": 4226.0,
            "long_entry_high": 4232.0,
            "short_entry_low": 4252.0,
            "short_entry_high": 4258.0,
        },
        "next_reassessment": "2026-08-07T13:00:00+00:00",
    }
    text = render_reassess_brief(old_plan, new_plan)
    assert text.splitlines()[0].startswith("🔄 بازبینی پلن")
    assert "از صعودی به نزولی" in text


def test_render_execution_brief_has_execution_headline():
    plan = {"symbol": "XAUUSD", "bias": "bullish"}
    execution = {"ok": True, "command": ["buy", "XAUUSD", "0.01"]}
    text = render_execution_brief(plan, execution)
    assert text.splitlines()[0].startswith("✅ اجرای معامله")
    assert "خرید" in text
