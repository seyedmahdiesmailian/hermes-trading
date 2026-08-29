from datetime import datetime, timezone

from mt5_xau_runtime import determine_runtime_step, should_rebuild_plan


def test_should_rebuild_plan_when_plan_is_missing():
    assert should_rebuild_plan(None, now=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc)) is True


def test_should_rebuild_plan_when_plan_is_expired():
    plan = {
        "expires_at": "2026-08-07T08:00:00+00:00",
        "next_reassessment": "2026-08-07T13:00:00+00:00",
    }
    assert should_rebuild_plan(plan, now=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc)) is True


def test_determine_runtime_step_returns_reassess_when_due():
    plan = {
        "expires_at": "2026-08-07T18:00:00+00:00",
        "next_reassessment": "2026-08-07T08:30:00+00:00",
    }
    step = determine_runtime_step(plan, now=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc))
    assert step == "reassess"


def test_determine_runtime_step_returns_monitor_when_plan_is_active():
    plan = {
        "expires_at": "2026-08-07T18:00:00+00:00",
        "next_reassessment": "2026-08-07T13:00:00+00:00",
    }
    step = determine_runtime_step(plan, now=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc))
    assert step == "monitor"
