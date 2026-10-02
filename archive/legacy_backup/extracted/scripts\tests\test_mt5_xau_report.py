from mt5_xau_report import format_reassessment_time, render_plan_brief, render_monitor_brief


def test_format_reassessment_time_returns_today_label_for_iran_time():
    now = "2026-08-07T12:00:00+00:00"
    text = format_reassessment_time("2026-08-07T13:00:00+00:00", now_value=now)
    assert "امروز" in text
    assert "16:30" in text
    assert "ساعت ایران" in text


def test_format_reassessment_time_returns_tomorrow_label_for_iran_time():
    now = "2026-08-07T20:00:00+00:00"
    text = format_reassessment_time("2026-08-08T05:30:00+00:00", now_value=now)
    assert "فردا" in text
    assert "09:00" in text
    assert "ساعت ایران" in text


def test_format_reassessment_time_returns_relative_hours_when_close():
    now = "2026-08-07T12:00:00+00:00"
    text = format_reassessment_time("2026-08-07T14:00:00+00:00", now_value=now)
    assert "حدود 2 ساعت دیگر" in text
    assert "17:30" in text


def test_render_plan_brief_uses_human_iran_time_label():
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
    assert "بازبینی بعدی" in text
    assert "ساعت ایران" in text


def test_render_plan_brief_uses_more_natural_bullish_scenario_when_price_above_buy_zone():
    plan = {
        "symbol": "XAUUSD",
        "bias": "bullish",
        "reference_price": 4305.93,
        "zones": {
            "long_entry_low": 4226.0,
            "long_entry_high": 4232.0,
            "short_entry_low": 4252.0,
            "short_entry_high": 4258.0,
        },
        "next_reassessment": "2026-08-07T13:00:00+00:00",
    }
    text = render_plan_brief(plan)
    assert "فعلاً منتظر برگشت قیمت به محدوده خرید هستیم" in text


def test_render_plan_brief_uses_more_natural_bearish_scenario_when_price_near_sell_zone():
    plan = {
        "symbol": "XAUUSD",
        "bias": "bearish",
        "reference_price": 4255.0,
        "zones": {
            "long_entry_low": 4226.0,
            "long_entry_high": 4232.0,
            "short_entry_low": 4252.0,
            "short_entry_high": 4258.0,
        },
        "next_reassessment": "2026-08-07T13:00:00+00:00",
    }
    text = render_plan_brief(plan)
    assert "قیمت نزدیک محدوده فروش است؛ اگر رد شود برای فروش آماده می‌مانیم" in text


def test_render_monitor_brief_can_explain_wait_for_trigger_naturally():
    plan = {"symbol": "XAUUSD", "bias": "bullish"}
    monitor = {"action": "wait_for_trigger", "zone": "long_zone", "price": 4230.5}
    text = render_monitor_brief(plan, monitor)
    assert "منتظر تأیید ورود" in text
    assert "قیمت داخل محدوده خرید است" in text
