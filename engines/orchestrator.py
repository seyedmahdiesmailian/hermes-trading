from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import floor
from uuid import uuid4

from engines.plan import decide_execution_action, grade_qualifies, setup_grade


def _parse_dt(value: str | None):
    if not value:
        return None
    return datetime.fromisoformat(value)


def route_runtime_step(plan: dict | None, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if not plan:
        return "plan"
    expires_at = _parse_dt(plan.get("expires_at"))
    if expires_at and now >= expires_at:
        return "plan"
    next_reassessment = _parse_dt(plan.get("next_reassessment"))
    if next_reassessment and now >= next_reassessment:
        return "reassess"
    return "monitor"


def build_plan_from_context(ctx: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    session = ctx.get("session", "asia")
    # M5 scalping: reassess every 5 minutes (fresh zones, fresh SMC)
    next_reassessment = now + timedelta(minutes=5)
    return {
        "plan_id": f"xau-{uuid4().hex[:8]}",
        "symbol": ctx["symbol"],
        "bias": ctx["bias"],
        "session": ctx["session"],
        "zones": ctx["zones"],
        "atr": ctx.get("atr"),
        "invalidation": ctx["invalidation"],
        "targets": ctx["targets"],
        "execution": ctx.get("execution", {}),
        "quality": ctx.get("quality", {}),
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=12)).isoformat(),
        "next_reassessment": next_reassessment.isoformat(),
        "context": ctx.get("context", {}),
    }


def _passes_quality_gate(plan: dict) -> bool:
    """b79d: ONE grade rule, one world. This used to be a SECOND, LOOSER
    rule (aligned+trend>=1.0 OR smc_confidence>=0.4), so the monitor stamped
    market_entry_now on plans the executor's Check 6 (setup_grade vs
    MIN_SETUP_GRADE) was guaranteed to kill: 144 of 287 C-grade live plans
    passed here, and 23 of 36 b78-replay fires died exactly that death
    (data/backtest/b78_grade_parity_census.json). Dead fires are not free —
    they inflate every census and make the funnel look worse-open than it
    is (same lie class as b108's missing grade parity and b193's bypassed
    M5 gate). Defer to the canonical rule; the smc_confidence back-door is
    gone. Tightening only: no plan that live EXECUTES today was blocked
    before — the executor already killed it one layer down."""
    return grade_qualifies(setup_grade(plan))


def compute_xau_position_size(
    balance: float,
    risk_pct: float,
    stop_distance_price: float,
    point: float,
    point_value_per_lot: float,
    volume_min: float,
    volume_step: float,
    volume_max: float,
    min_meaningful_lot: float = 0.05,
) -> dict:
    if stop_distance_price <= 0 or point <= 0 or point_value_per_lot <= 0:
        return {"lot": 0.0, "risk_usd": 0.0, "meaningful": False, "reason": "invalid_sizing_inputs", "capped": False}
    risk_usd = round(balance * risk_pct, 2)
    stop_points = stop_distance_price / point
    raw_lot = risk_usd / (stop_points * point_value_per_lot)
    if raw_lot < min_meaningful_lot:
        return {"lot": 0.0, "risk_usd": risk_usd, "meaningful": False, "reason": "below_min_meaningful_lot", "capped": False}
    stepped = floor(raw_lot / volume_step) * volume_step
    lot = max(volume_min, min(volume_max, round(stepped, 2)))
    capped = lot < raw_lot or lot == volume_max
    return {"lot": lot, "risk_usd": risk_usd, "meaningful": True, "reason": None, "capped": capped}


# ── b187: M5 confirmation gate ────────────────────────────────────────────
# "Price is inside the zone" was never a trigger: the zone is a pullback
# level, so touching it means price is still moving AGAINST the bias, and
# the market immediately selects the losers (measured on 65 live-parity
# legs: 38% race win, every follow-through loser). A real trigger is a
# close-based reversal: N consecutive M5 CLOSES moving WITH the bias while
# price is still in the zone. Live-parity backtest (data/backtest/
# b187_entry_confirmation.json): 3 closes -> 49% win, McNemar b01=8 b10=1
# (converts 8 losers into winners, costs 1). Pinned by
# tests/test_b187_m5_confirmation.py.
CONFIRM_CANDIDATES = ("close", "Close", "c")
M5_CONFIRM_CLOSES = 3  # consecutive M5 closes moving WITH the bias


def _closes(m5_rows, n: int) -> list[float]:
    """Last n settled M5 closes as floats, or [] if unavailable."""
    if not m5_rows or len(m5_rows) < n:
        return []
    out = []
    for row in m5_rows[-n:]:
        v: object = None
        if isinstance(row, dict):
            for key in CONFIRM_CANDIDATES:
                if row.get(key) is not None:
                    v = row[key]
                    break
        else:
            # bridge tuple layout: (time, high, low, close)
            try:
                v = row[3]
            except (TypeError, IndexError, KeyError):
                v = None
        if not isinstance(v, (int, float)) or float(v) <= 0:
            return []
        out.append(float(v))
    return out


def m5_confirmation(m5_rows, bias: str) -> bool:
    closes = _closes(m5_rows, M5_CONFIRM_CLOSES)
    if not closes:
        return False
    if bias == "bullish":
        return all(closes[i] < closes[i + 1] for i in range(len(closes) - 1))
    if bias == "bearish":
        return all(closes[i] > closes[i + 1] for i in range(len(closes) - 1))
    return False


def evaluate_monitor_cycle(plan: dict, price: float, now: datetime | None = None,
                           trigger_ok: bool | None = None, m5_rows=None) -> dict:
    now = now or datetime.now(timezone.utc)
    if trigger_ok is None:
        zone = plan.get("zones", {})
        in_zone = bool(
            (zone.get("long_entry_low") is not None and zone.get("long_entry_high") is not None
             and zone["long_entry_low"] <= price <= zone["long_entry_high"])
            or (zone.get("short_entry_low") is not None and zone.get("short_entry_high") is not None
                and zone["short_entry_low"] <= price <= zone["short_entry_high"])
        )
        # b187: zone touch alone is adverse selection, not a trigger.
        conf = m5_confirmation(m5_rows, plan.get("bias", ""))
        trigger_ok = in_zone and conf
        if in_zone and not trigger_ok:
            return {
                "action": "wait_for_trigger",
                "reason": "m5_confirmation_pending",
                "price": price,
                "plan_id": plan.get("plan_id"),
                "at": now.isoformat(),
            }
    # b193: the aggressive lanes (premium/value/breakout/discount entries OUTSIDE
    # the zone) used to hardcode trigger_ok=True and bypass b187. Backtest + live
    # (2026-09-08/09: -95/-45/-24$ unconfirmed vs +19$ confirmed) killed them:
    # they now need the same M5 reversal confirmation.
    # b193b FAIL-CLOSED FIX: `if m5_rows is not None else True` leaked a
    # fail-OPEN when callers passed None (dashboards/probes/any future caller) —
    # missing data must never mean "confirmed". Empty or absent rows => no
    # aggressive entry, same as the pullback branch above.
    m5_ok = m5_confirmation(m5_rows, plan.get("bias", ""))
    decision = decide_execution_action(plan, price=price, trigger_ok=trigger_ok, now=now,
                                       m5_ok=m5_ok)
    if decision.get("action") in {"market_order", "market_entry_now"} and not _passes_quality_gate(plan):
        decision = {
            "action": "wait_for_trigger",
            "reason": "quality_filter",
            "zone": decision.get("zone"),
            "at": now.isoformat(),
        }
    decision["price"] = price
    decision["plan_id"] = plan.get("plan_id")
    return decision


def execute_trade_blueprint(blueprint: dict, lot: float, point: float, command_runner, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    entry = float(blueprint["entry_price"])
    sl = float(blueprint["sl"])
    tp = float(blueprint["tp"])
    side = blueprint["side"].upper()
    sl_points = int(round(abs(entry - sl) / point))
    tp_points = int(round(abs(tp - entry) / point))
    if sl_points <= 0:
        return {"ok": False, "error": "invalid_stop_distance", "at": now.isoformat()}
    if tp_points <= 0:
        return {"ok": False, "error": "invalid_target_distance", "at": now.isoformat()}
    argv = ["open", blueprint["symbol"], side, f"{lot:.2f}", str(sl_points), str(tp_points), "Hermes plan"]
    result = command_runner(argv)
    return {
        "ok": bool(result.get("ok")),
        "command": argv,
        "result": result,
        "at": now.isoformat(),
    }
