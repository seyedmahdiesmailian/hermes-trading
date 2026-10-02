from datetime import datetime, timezone

from mt5_xau_orchestrator import route_runtime_step


def test_route_runtime_step_uses_plan_when_no_active_plan():
    step = route_runtime_step(None, now=datetime(2026, 8, 7, 3, 0, tzinfo=timezone.utc))
    assert step == "plan"


def test_route_runtime_step_uses_monitor_when_plan_is_active_and_not_reassessment_window():
    plan = {"expires_at": "2026-08-07T12:00:00+00:00", "next_reassessment": "2026-08-07T13:00:00+00:00"}
    step = route_runtime_step(plan, now=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc))
    assert step == "monitor"


def test_route_runtime_step_uses_reassess_when_due():
    plan = {"expires_at": "2026-08-07T18:00:00+00:00", "next_reassessment": "2026-08-07T08:30:00+00:00"}
    step = route_runtime_step(plan, now=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc))
    assert step == "reassess"


def test_route_runtime_step_uses_plan_when_expired():
    plan = {"expires_at": "2026-08-07T08:30:00+00:00", "next_reassessment": "2026-08-07T13:00:00+00:00"}
    step = route_runtime_step(plan, now=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc))
    assert step == "plan"
