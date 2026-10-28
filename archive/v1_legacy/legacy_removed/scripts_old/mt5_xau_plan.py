from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4


def select_reassessment_mode(session_name: str) -> str:
    mapping = {
        "asia": "morning_plan",
        "london": "london_reassessment",
        "newyork": "newyork_reassessment",
    }
    return mapping.get(session_name, "monitor_only")


def build_plan_payload(symbol: str, bias: str, session: str, zones: dict, invalidation: float, targets: list, now: datetime | None = None, context: dict | None = None, execution: dict | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "plan_id": f"xau-{uuid4().hex[:8]}",
        "symbol": symbol,
        "bias": bias,
        "session": session,
        "zones": zones,
        "invalidation": invalidation,
        "targets": targets,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=12)).isoformat(),
        "next_reassessment": (now + timedelta(hours=4)).isoformat(),
        "context": context or {},
        "execution": execution or {},
        "status": "active",
    }


def validate_plan(plan: dict) -> tuple[bool, list[str]]:
    required = ["plan_id", "symbol", "bias", "session", "zones", "invalidation", "targets", "created_at", "expires_at", "next_reassessment", "status"]
    problems = [field for field in required if field not in plan or plan.get(field) in (None, "")]
    return (len(problems) == 0, problems)


def plan_expired(plan: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    expiry = datetime.fromisoformat(plan["expires_at"])
    return now >= expiry


def pending_order_allowed(plan: dict, price: float) -> dict:
    zone = classify_price_location(price, plan["zones"])
    allowed = zone in {"long_zone", "short_zone"}
    return {"allowed": allowed, "zone": zone, "reason": None if allowed else "outside_entry_zones"}


def classify_price_location(price: float, zones: dict) -> str:
    if zones["long_entry_low"] <= price <= zones["long_entry_high"]:
        return "long_zone"
    if zones["short_entry_low"] <= price <= zones["short_entry_high"]:
        return "short_zone"
    if zones["value_low"] <= price <= zones["value_high"]:
        return "value_zone"
    if price < zones["value_low"]:
        return "discount"
    return "premium"


def build_trade_blueprint(plan: dict, price: float, trigger_ok: bool) -> dict:
    zone = classify_price_location(price, plan["zones"])
    side = "BUY" if plan["bias"] == "bullish" else "SELL"
    execution = plan.get("execution", {})
    tp_levels = execution.get("tp_levels") or plan.get("targets", [])
    tp = tp_levels[0] if tp_levels else plan["targets"][0]
    return {
        "symbol": plan["symbol"],
        "side": side,
        "entry_zone": zone,
        "entry_price": price,
        "trigger_ok": trigger_ok,
        "sl": plan["invalidation"],
        "tp": tp,
        "tp_levels": tp_levels,
        "tp_shares": execution.get("tp_shares", []),
        "scale_in_levels": execution.get("scale_in_levels", []),
    }


def _buy_logic(plan: dict, price: float, trigger_ok: bool, now: datetime) -> dict:
    zones = plan["zones"]
    execution = plan.get("execution", {})
    breakout_trigger = execution.get("breakout_trigger", zones["short_entry_low"])

    if zones["long_entry_low"] <= price <= zones["long_entry_high"]:
        if trigger_ok:
            return {
                "action": "market_entry_now",
                "zone": "long_zone",
                "execution_style": "pullback_continuation",
                "blueprint": build_trade_blueprint(plan, price=price, trigger_ok=trigger_ok),
                "at": now.isoformat(),
            }
        return {
            "action": "wait_for_trigger",
            "zone": "long_zone",
            "execution_style": "pullback_wait",
            "at": now.isoformat(),
        }

    if price < zones["long_entry_low"]:
        return {
            "action": "place_buy_limit",
            "zone": "discount",
            "entry_price": zones["long_entry_low"],
            "execution_style": "pullback_limit",
            "at": now.isoformat(),
        }

    if price <= zones["value_high"]:
        return {
            "action": "no_trade",
            "reason": "outside_entry_zones",
            "zone": classify_price_location(price, zones),
            "execution_style": "hold_bias_wait_better_price",
            "at": now.isoformat(),
        }

    if price <= zones["short_entry_high"]:
        return {
            "action": "place_buy_stop",
            "zone": classify_price_location(price, zones),
            "entry_price": breakout_trigger,
            "execution_style": "breakout_continuation",
            "at": now.isoformat(),
        }

    return {
        "action": "wait_for_pullback",
        "reason": "price_extended_above_breakout_zone",
        "zone": "premium",
        "execution_style": "extended_wait",
        "at": now.isoformat(),
    }


def _sell_logic(plan: dict, price: float, trigger_ok: bool, now: datetime) -> dict:
    zones = plan["zones"]
    execution = plan.get("execution", {})
    breakout_trigger = execution.get("breakout_trigger", zones["long_entry_high"])

    if zones["short_entry_low"] <= price <= zones["short_entry_high"]:
        if trigger_ok:
            return {
                "action": "market_entry_now",
                "zone": "short_zone",
                "execution_style": "pullback_continuation",
                "blueprint": build_trade_blueprint(plan, price=price, trigger_ok=trigger_ok),
                "at": now.isoformat(),
            }
        return {
            "action": "wait_for_trigger",
            "zone": "short_zone",
            "execution_style": "pullback_wait",
            "at": now.isoformat(),
        }

    if price > zones["short_entry_high"]:
        return {
            "action": "place_sell_limit",
            "zone": "premium",
            "entry_price": zones["short_entry_high"],
            "execution_style": "pullback_limit",
            "at": now.isoformat(),
        }

    if price >= breakout_trigger:
        return {
            "action": "wait_for_pullback",
            "reason": "inside_value_without_trigger",
            "zone": classify_price_location(price, zones),
            "execution_style": "hold_bias_wait_better_price",
            "at": now.isoformat(),
        }

    if price >= zones["long_entry_low"]:
        return {
            "action": "place_sell_stop",
            "zone": classify_price_location(price, zones),
            "entry_price": breakout_trigger,
            "execution_style": "breakout_continuation",
            "at": now.isoformat(),
        }

    return {
        "action": "wait_for_pullback",
        "reason": "price_extended_below_breakout_zone",
        "zone": "discount",
        "execution_style": "extended_wait",
        "at": now.isoformat(),
    }


def decide_execution_action(plan: dict, price: float, trigger_ok: bool, now: datetime) -> dict:
    execution = plan.get("execution") or {}
    if not execution:
        zone = classify_price_location(price, plan["zones"])
        if zone not in {"long_zone", "short_zone"}:
            return {
                "action": "no_trade",
                "reason": "outside_entry_zones",
                "zone": zone,
                "at": now.isoformat(),
            }
        if not trigger_ok:
            return {
                "action": "wait_for_trigger",
                "zone": zone,
                "at": now.isoformat(),
            }
        return {
            "action": "market_order",
            "zone": zone,
            "blueprint": build_trade_blueprint(plan, price=price, trigger_ok=trigger_ok),
            "at": now.isoformat(),
        }

    if plan.get("bias") == "bullish":
        return _buy_logic(plan, price=price, trigger_ok=trigger_ok, now=now)
    return _sell_logic(plan, price=price, trigger_ok=trigger_ok, now=now)
