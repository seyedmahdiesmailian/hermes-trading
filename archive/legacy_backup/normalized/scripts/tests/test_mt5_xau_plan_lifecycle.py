from datetime import datetime, timezone

from mt5_xau_plan import build_plan_payload, plan_expired, pending_order_allowed, validate_plan


def test_build_plan_payload_sets_required_fields():
    plan = build_plan_payload(
        symbol="XAUUSD",
        bias="bullish",
        session="asia",
        zones={"long_entry_low": 4226.0, "long_entry_high": 4232.0, "short_entry_low": 4252.0, "short_entry_high": 4258.0, "value_low": 4230.0, "value_high": 4240.0},
        invalidation=4218.0,
        targets=[4256.0, 4272.0],
        now=datetime(2026, 8, 7, 4, 0, tzinfo=timezone.utc),
        context={"h4_bias": "bullish"},
    )
    assert plan["symbol"] == "XAUUSD"
    assert plan["bias"] == "bullish"
    assert plan["status"] == "active"


def test_validate_plan_accepts_complete_plan():
    plan = build_plan_payload(
        symbol="XAUUSD",
        bias="bullish",
        session="asia",
        zones={"long_entry_low": 4226.0, "long_entry_high": 4232.0, "short_entry_low": 4252.0, "short_entry_high": 4258.0, "value_low": 4230.0, "value_high": 4240.0},
        invalidation=4218.0,
        targets=[4256.0, 4272.0],
        now=datetime(2026, 8, 7, 4, 0, tzinfo=timezone.utc),
        context={},
    )
    ok, problems = validate_plan(plan)
    assert ok is True
    assert problems == []


def test_plan_expired_returns_true_after_expiry():
    plan = {"expires_at": "2026-08-07T08:00:00+00:00"}
    assert plan_expired(plan, datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc)) is True


def test_pending_order_allowed_only_for_entry_zones():
    plan = build_plan_payload(
        symbol="XAUUSD",
        bias="bullish",
        session="asia",
        zones={"long_entry_low": 4226.0, "long_entry_high": 4232.0, "short_entry_low": 4252.0, "short_entry_high": 4258.0, "value_low": 4230.0, "value_high": 4240.0},
        invalidation=4218.0,
        targets=[4256.0, 4272.0],
        now=datetime(2026, 8, 7, 4, 0, tzinfo=timezone.utc),
        context={},
    )
    allowed = pending_order_allowed(plan, price=4229.0)
    blocked = pending_order_allowed(plan, price=4245.0)
    assert allowed["allowed"] is True
    assert blocked["allowed"] is False
