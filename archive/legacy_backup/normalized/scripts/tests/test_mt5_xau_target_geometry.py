from datetime import datetime, timezone

from mt5_xau_context import build_plan_context
from mt5_xau_orchestrator import build_plan_from_context
from mt5_xau_runtime import _select_execution_decision


class _Tick:
    def __init__(self, ask):
        self.ask = ask


def _rows_from_closes(closes, width=8.0):
    rows = []
    for close in closes:
        rows.append({
            "open": close - 0.8,
            "high": close + (width / 2),
            "low": close - (width / 2),
            "close": close,
        })
    return rows


def test_breakout_bullish_context_keeps_all_targets_above_entry_and_stop_below_entry():
    m15 = _rows_from_closes([4322, 4326, 4330, 4335, 4340, 4344, 4348, 4352, 4356, 4359, 4361, 4364, 4367, 4370, 4372])
    h1 = _rows_from_closes([4300, 4308, 4316, 4324, 4332, 4340, 4348, 4356, 4364, 4372], width=12.0)
    h4 = _rows_from_closes([4260, 4280, 4300, 4320, 4340, 4360, 4380, 4400, 4420, 4440], width=20.0)

    ctx = build_plan_context(m15, h1, h4, "london")
    plan = build_plan_from_context(ctx, now=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc))
    monitor = _select_execution_decision(plan, _Tick(ask=4373.0), now=datetime(2026, 8, 7, 9, 5, tzinfo=timezone.utc))

    assert monitor["action"] == "market_entry_now"
    blueprint = monitor["blueprint"]
    assert blueprint["sl"] < blueprint["entry_price"]
    assert all(tp > blueprint["entry_price"] for tp in blueprint["tp_levels"])


def test_breakout_bearish_context_keeps_all_targets_below_entry_and_stop_above_entry():
    m15 = _rows_from_closes([4372, 4368, 4362, 4357, 4351, 4346, 4341, 4336, 4331, 4327, 4323, 4319, 4315, 4311, 4308])
    h1 = _rows_from_closes([4390, 4382, 4374, 4366, 4358, 4350, 4342, 4334, 4326, 4318], width=12.0)
    h4 = _rows_from_closes([4440, 4420, 4400, 4380, 4360, 4340, 4320, 4300, 4280, 4260], width=20.0)

    ctx = build_plan_context(m15, h1, h4, "newyork")
    plan = build_plan_from_context(ctx, now=datetime(2026, 8, 7, 14, 0, tzinfo=timezone.utc))
    monitor = _select_execution_decision(plan, _Tick(ask=4306.0), now=datetime(2026, 8, 7, 14, 5, tzinfo=timezone.utc))

    assert monitor["action"] == "market_entry_now"
    blueprint = monitor["blueprint"]
    assert blueprint["sl"] > blueprint["entry_price"]
    assert all(tp < blueprint["entry_price"] for tp in blueprint["tp_levels"])
