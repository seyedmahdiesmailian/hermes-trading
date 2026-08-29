from datetime import datetime, timezone

from mt5_xau_context import build_plan_context
from mt5_xau_orchestrator import build_plan_from_context, evaluate_monitor_cycle


def _mk_rows(start, step, count, base_low=10.0, width=8.0):
    rows = []
    val = start
    for _ in range(count):
        rows.append({"open": val - 1.0, "high": val + width / 2, "low": val - width / 2, "close": val})
        val += step
    return rows


def test_build_plan_from_context_creates_valid_plan_payload():
    m15 = _mk_rows(4230.0, 0.8, 30)
    h1 = _mk_rows(4220.0, 1.0, 30, width=12.0)
    h4 = _mk_rows(4200.0, 2.0, 30, width=18.0)
    ctx = build_plan_context(m15, h1, h4, "asia")
    plan = build_plan_from_context(ctx, now=datetime(2026, 8, 7, 4, 0, tzinfo=timezone.utc))
    assert plan["symbol"] == "XAUUSD"
    assert plan["bias"] == "bullish"
    assert "plan_id" in plan
    assert "expires_at" in plan
    assert "next_reassessment" in plan


def test_evaluate_monitor_cycle_returns_wait_or_trade_against_existing_plan():
    m15 = _mk_rows(4230.0, 0.8, 30)
    h1 = _mk_rows(4220.0, 1.0, 30, width=12.0)
    h4 = _mk_rows(4200.0, 2.0, 30, width=18.0)
    ctx = build_plan_context(m15, h1, h4, "asia")
    plan = build_plan_from_context(ctx, now=datetime(2026, 8, 7, 4, 0, tzinfo=timezone.utc))
    price = plan["zones"]["long_entry_low"] + 0.1
    out = evaluate_monitor_cycle(plan, price=price, now=datetime(2026, 8, 7, 4, 15, tzinfo=timezone.utc))
    assert out["action"] in {"wait_for_trigger", "market_order", "market_entry_now"}
    assert out["zone"] == "long_zone"
