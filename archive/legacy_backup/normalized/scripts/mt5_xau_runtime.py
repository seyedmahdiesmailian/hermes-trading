import json
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

from mt5_account_risk import assess_account_policy, compute_performance_state, recommend_risk_budget
from mt5_direct_runner import run_mt5_direct_command
from mt5_xau_context import build_plan_context
from mt5_xau_smc import smc_analyse, merge_smc_with_classic
from mt5_xau_orchestrator import (
    build_plan_from_context,
    compute_xau_position_size,
    evaluate_monitor_cycle,
    execute_trade_blueprint,
    route_runtime_step,
)
from mt5_xau_report import (
    render_execution_brief,
    render_management_brief,
    render_monitor_brief,
    render_plan_brief,
    render_reassess_brief,
)
from mt5_xau_trade_management import evaluate_trade_management
from mt5_direct import execute_market_open, execute_modify_position_prices, execute_partial_close
from mt5_xau_storage import (
    DEFAULT_BASE_DIR,
    append_execution_log,
    append_reassessment_log,
    ensure_xau_plan_dirs,
    load_current_plan,
    load_performance_state,
    load_runtime_state,
    save_current_plan,
    save_performance_state,
    save_runtime_state,
)

MIN_MEANINGFUL_LOT = 0.05


def _rows(symbol, timeframe, count):
    data = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if data is None:
        return []
    return [
        {
            "time": int(r["time"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
        }
        for r in data
    ]


def _detect_session(now: datetime) -> str:
    hour = now.hour
    if 0 <= hour < 7:
        return "asia"
    if 7 <= hour < 13:
        return "london"
    return "newyork"


def _build_live_plan(now: datetime):
    session = _detect_session(now)
    m15 = _rows("XAUUSD", mt5.TIMEFRAME_M15, 80)
    h1 = _rows("XAUUSD", mt5.TIMEFRAME_H1, 80)
    h4 = _rows("XAUUSD", mt5.TIMEFRAME_H4, 80)
    if not (m15 and h1 and h4):
        return None, {"ok": False, "error": "insufficient_market_data", "session": session}
    ctx = build_plan_context(m15, h1, h4, session)

    # ── SMC/ICT/RTM analysis with M15 + H1 ──
    smc_result = smc_analyse(m15, now=now, h1_rows=h1)
    merged = merge_smc_with_classic(ctx, smc_result)

    # Enrich classic context with SMC
    # Guard: SMC must not override neutral when classic regime is range
    classic_regime = ctx["quality"].get("regime", "")
    if classic_regime == "range" and merged["bias"] != "neutral":
        # Classic says range → stay neutral, but keep SMC data for context
        ctx["bias"] = "neutral"
        merged["bias"] = "neutral"
        merged["confidence"] = min(merged["confidence"], 0.3)
        merged["action"] = "wait"
    else:
        ctx["bias"] = merged["bias"]
    ctx["quality"]["smc_confidence"] = merged["confidence"]
    ctx["quality"]["smc_poi"] = merged["smc_source"].get("poi")
    ctx["quality"]["smc_signal"] = merged["smc_source"].get("signal")
    ctx.setdefault("context", {})
    ctx["context"]["smc"] = smc_result
    ctx["context"]["merged"] = {k: v for k, v in merged.items() if k not in ("smc_result",)}

    plan = build_plan_from_context(ctx, now=now)
    return plan, None


def build_monitor_report_key(monitor: dict) -> str:
    return f"{monitor.get('action')}:{monitor.get('zone')}"


def should_emit_monitor_report(runtime: dict, monitor: dict) -> bool:
    current_key = build_monitor_report_key(monitor)
    last_key = runtime.get("last_report_key")
    return current_key != last_key


def should_rebuild_plan(plan: dict | None, now: datetime) -> bool:
    return route_runtime_step(plan, now=now) == "plan"


def determine_runtime_step(plan: dict | None, now: datetime) -> str:
    return route_runtime_step(plan, now=now)


def _save_plan_and_state(plan: dict, runtime: dict, step: str):
    save_current_plan(None, plan)
    runtime["active_plan_id"] = plan["plan_id"]
    runtime["last_step"] = step
    runtime["last_report_key"] = f"{step}:{plan['plan_id']}"
    save_runtime_state(None, runtime)


def _infer_setup_grade(plan: dict) -> str:
    quality = plan.get("quality", {})
    alignment = quality.get("alignment")
    trend_strength = float(quality.get("trend_strength", 0.0) or 0.0)
    regime = quality.get("regime")
    if alignment == "aligned" and trend_strength >= 12 and regime in {"breakout_continuation", "pullback_continuation"}:
        return "A"
    if alignment in {"aligned", "mixed"} and trend_strength >= 3:
        return "B"
    return "C"


def _select_execution_decision(plan: dict, tick, now: datetime) -> dict:
    price = float(tick.ask)
    quality = plan.get("quality", {})
    execution = plan.get("execution") or {}
    bias = plan.get("bias")
    regime = quality.get("regime")

    if bias not in {"bullish", "bearish"} or regime == "range":
        return {
            "action": "no_trade",
            "reason": "range_or_neutral",
            "zone": "value_zone",
            "plan_id": plan.get("plan_id"),
            "price": price,
            "at": now.isoformat(),
        }

    scale_levels = execution.get("scale_in_levels") or []
    raw_tp_levels = execution.get("tp_levels") or plan.get("targets") or []
    atr = float(plan.get("atr", 0.0) or 0.0)

    def normalized_tp_levels(entry_price: float) -> list[float]:
        if bias == "bullish":
            filtered = [float(tp) for tp in raw_tp_levels if float(tp) > entry_price]
            if filtered:
                return filtered
            step = max(atr * 0.5, 4.0)
            return [round(entry_price + step, 2), round(entry_price + (step * 2), 2), round(entry_price + (step * 4), 2)]
        filtered = [float(tp) for tp in raw_tp_levels if float(tp) < entry_price]
        if filtered:
            return filtered
        step = max(atr * 0.5, 4.0)
        return [round(entry_price - step, 2), round(entry_price - (step * 2), 2), round(entry_price - (step * 4), 2)]

    def normalized_tp_shares(tp_levels: list[float]) -> list[float]:
        base = execution.get("tp_shares") or []
        if len(base) >= len(tp_levels):
            return list(base[: len(tp_levels)])
        if len(tp_levels) == 3:
            return [0.5, 0.3, 0.2]
        if len(tp_levels) == 2:
            return [0.6, 0.4]
        return [1.0]

    if execution.get("entry_mode") == "breakout_pullback_hybrid":
        breakout_trigger = execution.get("breakout_trigger")
        if breakout_trigger is not None:
            if bias == "bullish" and price >= float(breakout_trigger):
                tp_levels = normalized_tp_levels(price)
                blueprint = {
                    "symbol": plan["symbol"],
                    "side": "BUY",
                    "entry_price": price,
                    "sl": float(plan["invalidation"]),
                    "tp": float(tp_levels[0]) if tp_levels else price,
                    "tp_levels": tp_levels,
                    "tp_shares": normalized_tp_shares(tp_levels),
                    "scale_in_levels": scale_levels,
                }
                return {
                    "action": "market_entry_now",
                    "zone": "breakout",
                    "blueprint": blueprint,
                    "plan_id": plan.get("plan_id"),
                    "price": price,
                    "at": now.isoformat(),
                }
            if bias == "bearish" and price <= float(breakout_trigger):
                tp_levels = normalized_tp_levels(price)
                blueprint = {
                    "symbol": plan["symbol"],
                    "side": "SELL",
                    "entry_price": price,
                    "sl": float(plan["invalidation"]),
                    "tp": float(tp_levels[0]) if tp_levels else price,
                    "tp_levels": tp_levels,
                    "tp_shares": normalized_tp_shares(tp_levels),
                    "scale_in_levels": scale_levels,
                }
                return {
                    "action": "market_entry_now",
                    "zone": "breakout",
                    "blueprint": blueprint,
                    "plan_id": plan.get("plan_id"),
                    "price": price,
                    "at": now.isoformat(),
                }

    tp_levels = normalized_tp_levels(price)
    tp_shares = normalized_tp_shares(tp_levels)
    if bias == "bullish" and scale_levels and price <= float(scale_levels[0]):
        return {
            "action": "place_buy_limit",
            "entry_price": float(scale_levels[0]),
            "scale_in_levels": scale_levels,
            "tp_levels": tp_levels,
            "tp_shares": tp_shares,
            "zone": "long_zone",
            "plan_id": plan.get("plan_id"),
            "price": price,
            "at": now.isoformat(),
        }
    if bias == "bearish" and scale_levels and price >= float(scale_levels[0]):
        return {
            "action": "place_sell_limit",
            "entry_price": float(scale_levels[0]),
            "scale_in_levels": scale_levels,
            "tp_levels": tp_levels,
            "tp_shares": tp_shares,
            "zone": "short_zone",
            "plan_id": plan.get("plan_id"),
            "price": price,
            "at": now.isoformat(),
        }

    return evaluate_monitor_cycle(plan, price=price, now=now, trigger_ok=False)


def _load_closed_trade_snapshots(days: int = 7):
    start = datetime.now(timezone.utc) - timedelta(days=days)
    end = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(start, end) or []
    snapshots = []
    for deal in deals:
        if str(getattr(deal, "symbol", "")) != "XAUUSD":
            continue
        if int(getattr(deal, "entry", -1)) != mt5.DEAL_ENTRY_OUT:
            continue
        comment = str(getattr(deal, "comment", "") or "")
        magic = int(getattr(deal, "magic", 0) or 0)
        if magic != 20260806 and not comment.startswith("Hermes"):
            continue
        snapshots.append(
            {
                "ticket": int(getattr(deal, "ticket", 0) or 0),
                "symbol": str(getattr(deal, "symbol", "") or ""),
                "profit": float(getattr(deal, "profit", 0.0) or 0.0),
                "volume": float(getattr(deal, "volume", 0.0) or 0.0),
                "price": float(getattr(deal, "price", 0.0) or 0.0),
                "time": int(getattr(deal, "time", 0) or 0),
                "comment": comment,
                "magic": magic,
                "order": int(getattr(deal, "order", 0) or 0),
                "position_id": int(getattr(deal, "position_id", 0) or 0),
            }
        )
    return sorted(snapshots, key=lambda item: item["ticket"])


def _classify_closed_trade(deal) -> dict:
    comment = str(getattr(deal, "comment", "") or "")
    profit = float(getattr(deal, "profit", 0.0) or 0.0)
    ticket = int(getattr(deal, "ticket", 0) or 0)
    time = int(getattr(deal, "time", 0) or 0)

    if comment.startswith("[sl "):
        return {"exit_type": "sl", "pnl": profit, "ticket": ticket, "time": time, "managed": False}
    if comment.startswith("[tp "):
        return {"exit_type": "tp", "pnl": profit, "ticket": ticket, "time": time, "managed": False}
    if "Hermes manage" in comment:
        return {"exit_type": "partial", "pnl": profit, "ticket": ticket, "time": time, "managed": True}
    return {"exit_type": "unknown", "pnl": profit, "ticket": ticket, "time": time, "managed": False}


def _build_exit_analysis(classified: list[dict]) -> dict:
    sl_count = 0
    sl_total = 0.0
    tp_count = 0
    tp_total = 0.0
    partial_count = 0
    partial_total = 0.0
    managed_total = 0.0
    managed_wins = 0
    managed_count = 0

    for item in classified:
        et = item.get("exit_type", "unknown")
        pnl = float(item.get("pnl", 0.0) or 0.0)
        managed = bool(item.get("managed", False))

        if et == "sl":
            sl_count += 1
            sl_total += pnl
        elif et == "tp":
            tp_count += 1
            tp_total += pnl
        elif et == "partial":
            partial_count += 1
            partial_total += pnl

        if managed:
            managed_total += pnl
            managed_count += 1
            if pnl > 0:
                managed_wins += 1

    total = len(classified)
    return {
        "total_closed": total,
        "sl": {"count": sl_count, "total_pnl": round(sl_total, 2)},
        "tp": {"count": tp_count, "total_pnl": round(tp_total, 2)},
        "partial": {"count": partial_count, "total_pnl": round(partial_total, 2)},
        "sl_dominant": total > 0 and (sl_count / total) >= 0.5,
        "sl_ratio": round(sl_count / total, 2) if total else 0.0,
        "avg_sl_loss": round(sl_total / sl_count, 2) if sl_count else 0.0,
        "managed_total_pnl": round(managed_total, 2),
        "managed_win_ratio": round(managed_wins / managed_count, 2) if managed_count else 0.0,
    }


def _build_trading_insights(exit_analysis: dict, performance_state: dict, account_policy: dict) -> dict:
    """Convert exit analysis + performance + policy into actionable trading guardrails."""
    total = exit_analysis.get("total_closed", 0)
    sl_dominant = bool(exit_analysis.get("sl_dominant", False))
    sl_ratio = float(exit_analysis.get("sl_ratio", 0.0) or 0.0)
    managed_win = float(exit_analysis.get("managed_win_ratio", 0.0) or 0.0)
    managed_pnl = float(exit_analysis.get("managed_total_pnl", 0.0) or 0.0)
    loss_streak = int(performance_state.get("loss_streak", 0) or 0)
    daily_pnl = float(performance_state.get("daily_pnl", 0.0) or 0.0)

    sl_count = exit_analysis.get("sl", {}).get("count", 0)
    tp_count = exit_analysis.get("tp", {}).get("count", 0)

    partial_allowed = True
    runner_allowed = True
    scale_in_allowed = True

    # ── DEFCON levels ──
    if total >= 5 and sl_dominant and daily_pnl < 0:
        defcon = "red"
    elif loss_streak >= 2 or (sl_ratio >= 0.5 and total >= 3):
        defcon = "yellow"
    else:
        defcon = "green"

    # ── Red: no new trades, partials still OK to protect existing ──
    if defcon == "red":
        runner_allowed = False
        scale_in_allowed = False

    # ── Yellow: runners and scale-ins are risk-on behaviors — disable ──
    if defcon == "yellow":
        runner_allowed = False
        scale_in_allowed = False

    # ── Managed exits are losing value → disable runners ──
    if managed_pnl < 0 and managed_win <= 0.3:
        runner_allowed = False
        scale_in_allowed = False

    # ── Risk override ──
    risk_override = None
    if defcon == "red":
        risk_override = 0.0  # no new entries
    elif defcon == "yellow":
        risk_override = float(account_policy.get("base_risk_pct", 0.015) or 0.015) * 0.75

    return {
        "defcon": defcon,
        "partial_allowed": partial_allowed,
        "runner_allowed": runner_allowed,
        "scale_in_allowed": scale_in_allowed,
        "risk_override": risk_override,
        "trade_allowed": defcon != "red",
    }


def _filter_management_by_insights(management: dict, insights: dict) -> dict:
    """Filter/override management decisions based on DEFCON insights.

    - runner_allowed=False: trail_stop → close_runner
    - scale_in_allowed=False: scale_in_* → hold
    - close_trade_early and partial_take_profit are always allowed
    """
    action = management.get("action", "hold")

    if action == "hold":
        return management

    # Safety valves — always allowed
    if action in {"close_trade_early", "partial_take_profit", "move_stop_to_breakeven"}:
        return management

    # Runner disabled → force close instead of trailing
    if not insights.get("runner_allowed", True) and action in {"trail_stop", "close_runner"}:
        return {
            "action": "close_runner",
            "close_fraction": 1.0,
            "reason": f"insights:defcon_{insights.get('defcon', 'unknown')}:runner_blocked",
            "at": management.get("at"),
        }

    # Scale-in disabled → hold
    if not insights.get("scale_in_allowed", True) and action.startswith("scale_in"):
        return {
            "action": "hold",
            "reason": f"insights:defcon_{insights.get('defcon', 'unknown')}:scale_in_blocked",
            "at": management.get("at"),
        }

    return management


def _filter_entry_by_insights(sizing_allowed: bool, sizing_reason: str | None, insights: dict | None) -> dict:
    """Apply DEFCON guardrails to entry decisions.

    Returns {"allowed": bool, "risk_pct_override": float|None, "reason": str|None}
    """
    if insights is None:
        return {"allowed": sizing_allowed, "risk_pct_override": None, "reason": sizing_reason}

    # Respect sizing's own block first
    if not sizing_allowed:
        return {"allowed": False, "risk_pct_override": None, "reason": sizing_reason}

    # DEFCON RED → no new entries
    if not insights.get("trade_allowed", True):
        return {"allowed": False, "risk_pct_override": None, "reason": f"defcon_{insights.get('defcon', 'red')}:entry_blocked"}

    # Apply risk override if set
    risk_override = insights.get("risk_override")
    return {"allowed": True, "risk_pct_override": risk_override, "reason": None}


SETUP_PROFILES_PATH = DEFAULT_BASE_DIR / "setup_profiles.json"


def _extract_ticket(execution_result: dict) -> int | None:
    return execution_result.get("position_ticket") or execution_result.get("ticket")


def _load_setup_profiles() -> list[dict]:
    path = SETUP_PROFILES_PATH
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save_setup_profile(ticket: int, plan: dict, setup_grade: str):
    path = SETUP_PROFILES_PATH
    profiles = _load_setup_profiles()
    quality = plan.get("quality", {})
    profile = {
        "ticket": ticket,
        "plan_id": plan.get("plan_id"),
        "regime": quality.get("regime"),
        "alignment": quality.get("alignment"),
        "grade": setup_grade,
        "session": plan.get("session"),
        "bias": plan.get("bias"),
        "trend_strength": quality.get("trend_strength"),
    }
    profiles.append(profile)
    path.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_setup_ledger(classified: list[dict], setups: list[dict]) -> dict:
    """Aggregate closed trades by setup dimensions: regime, alignment, grade, session.

    Returns {key: {wins, losses, total_pnl, samples, win_rate}}
    where key is like 'regime:pullback_continuation' or 'alignment:aligned'
    """
    if not classified or not setups:
        return {}

    setup_map = {s["ticket"]: s for s in setups}

    dimensions = ["regime", "alignment", "grade", "session"]
    ledger: dict[str, dict] = {}

    for deal in classified:
        ticket = deal.get("ticket")
        setup = setup_map.get(ticket)
        if not setup:
            continue
        pnl = float(deal.get("pnl", 0.0))
        is_win = pnl > 0

        for dim in dimensions:
            value = setup.get(dim)
            if not value:
                continue
            key = f"{dim}:{value}"
            if key not in ledger:
                ledger[key] = {"wins": 0, "losses": 0, "total_pnl": 0.0, "samples": 0, "win_rate": 0.0}
            entry = ledger[key]
            entry["samples"] += 1
            entry["total_pnl"] = round(entry["total_pnl"] + pnl, 2)
            if is_win:
                entry["wins"] += 1
            else:
                entry["losses"] += 1
            entry["win_rate"] = round(entry["wins"] / entry["samples"], 2)

    return ledger


def _build_setup_guardrails(ledger: dict) -> dict:
    """Convert setup ledger into actionable guardrails.

    Returns {"avoid": [...], "preferred": [...], "caution": [...]}
    - avoid: ≥2 samples, 0 wins
    - caution: ≥5 samples, win_rate < 0.30
    - preferred: ≥3 samples, win_rate > 0.60
    """
    avoid = []
    caution = []
    preferred = []

    for key, entry in ledger.items():
        samples = entry["samples"]
        win_rate = entry.get("win_rate", entry["wins"] / samples if samples > 0 else 0.0)

        if samples >= 2 and entry["wins"] == 0:
            avoid.append(key)
        elif samples >= 5 and win_rate < 0.30:
            caution.append(key)
        elif samples >= 3 and win_rate > 0.60:
            preferred.append(key)

    result = {}
    if avoid:
        result["avoid"] = sorted(avoid)
    if caution:
        result["caution"] = sorted(caution)
    if preferred:
        result["preferred"] = sorted(preferred)
    return result


def _compute_trading_insights(account, now: datetime) -> dict:
    """Build the full insights chain: snapshots → classify → analysis → insights."""
    performance_state = _update_performance_state(account, now)
    account_policy = _build_account_policy(account, performance_state)
    snapshots = _load_closed_trade_snapshots(days=7)

    class _Deal:
        pass

    classified = []
    for s in snapshots:
        d = _Deal()
        d.comment = s.get("comment", "")
        d.profit = s.get("profit", 0.0)
        d.ticket = s.get("ticket", 0)
        d.time = s.get("time", 0)
        classified.append(_classify_closed_trade(d))

    exit_analysis = _build_exit_analysis(classified)
    insights = _build_trading_insights(exit_analysis, performance_state, account_policy)

    # Setup memory: load past setups, build ledger, derive guardrails
    setup_profiles = _load_setup_profiles()
    setup_ledger = _build_setup_ledger(classified, setup_profiles)
    setup_guardrails = _build_setup_guardrails(setup_ledger)
    insights["setup_ledger"] = setup_ledger
    insights["setup_guardrails"] = setup_guardrails

    return {
        "performance_state": performance_state,
        "account_policy": account_policy,
        "insights": insights,
        "exit_analysis": exit_analysis,
    }


def _update_performance_state(account, now: datetime):
    today = now.date().isoformat()
    current = load_performance_state()
    closed_trades = _load_closed_trade_snapshots()
    perf = compute_performance_state(
        current=current,
        today=today,
        balance=float(account.balance),
        closed_trades=closed_trades,
    )
    save_performance_state(None, perf)
    return perf


def _build_account_policy(account, performance_state: dict) -> dict:
    open_positions = int(getattr(account, "positions", 0) or 0)
    return assess_account_policy(
        balance=float(account.balance),
        equity=float(account.equity),
        free_margin=float(account.margin_free),
        margin=float(account.margin),
        daily_pnl=float(performance_state.get("daily_pnl", 0.0) or 0.0),
        loss_streak=int(performance_state.get("loss_streak", 0) or 0),
        open_positions=open_positions,
    )


def _build_execution_sizing(blueprint: dict, info, account_policy: dict, setup_grade: str, risk_override: float | None = None) -> dict:
    budget = recommend_risk_budget(account_policy, setup_grade=setup_grade)
    if not budget.get("trade_allowed"):
        return {"meaningful": False, "reason": budget.get("reason"), "lot": 0.0, "risk_usd": 0.0, "risk_pct": 0.0}
    risk_pct = risk_override if risk_override is not None else float(budget["risk_pct"])

    # Margin safety check: ensure free_margin has adequate buffer
    MIN_MARGIN_RATIO = 1.5
    free_margin = account_policy.get("free_margin")
    margin_required = account_policy.get("margin_required")
    if free_margin is not None and margin_required is not None and margin_required > 0:
        if free_margin / margin_required < MIN_MARGIN_RATIO:
            return {
                "meaningful": False,
                "reason": f"margin_unsafe:free_margin_ratio={free_margin / margin_required:.1f}",
                "lot": 0.0,
                "risk_usd": 0.0,
                "risk_pct": 0.0,
            }

    stop_distance_price = abs(float(blueprint["entry_price"]) - float(blueprint["sl"]))
    point_value_per_lot = 1.0
    sizing = compute_xau_position_size(
        balance=float(account_policy["balance"]),
        risk_pct=risk_pct,
        stop_distance_price=stop_distance_price,
        point=float(info.point),
        point_value_per_lot=point_value_per_lot,
        volume_min=float(info.volume_min),
        volume_step=float(info.volume_step),
        volume_max=float(info.volume_max),
        min_meaningful_lot=MIN_MEANINGFUL_LOT,
    )
    sizing["risk_pct"] = risk_pct
    sizing["regime"] = budget.get("regime")
    return sizing


def _position_side(position) -> str:
    return "BUY" if int(position.type) == mt5.POSITION_TYPE_BUY else "SELL"


def _management_runtime_key(position) -> str:
    return str(getattr(position, "ticket", ""))


def _build_management_trade(plan: dict, position, runtime_state: dict) -> dict:
    execution = plan.get("execution") or {}
    management_state = ((runtime_state or {}).get("management") or {}).get(_management_runtime_key(position), {})
    setup_grade = _infer_setup_grade(plan)
    quality = plan.get("quality", {})
    trend_strength = float(quality.get("trend_strength", 0.0) or 0.0)
    momentum_strength = min(1.0, max(0.2, trend_strength / 20.0))
    structure_state = "healthy" if quality.get("alignment") == "aligned" else "mixed"
    return {
        "symbol": position.symbol,
        "side": _position_side(position),
        "entry_price": float(position.price_open),
        "sl": float(position.sl or plan.get("invalidation") or position.price_open),
        "tp_levels": execution.get("tp_levels") or plan.get("targets") or [],
        "tp_shares": execution.get("tp_shares") or [0.5, 0.3, 0.2],
        "scale_in_levels": execution.get("scale_in_levels") or [],
        "filled_tp_levels": management_state.get("filled_tp_levels", []),
        "breakeven_active": bool(management_state.get("breakeven_active", False)),
        "runner_active": bool(management_state.get("runner_active", True)),
        "scaled_in_levels": management_state.get("scaled_in_levels", []),
        "volume": float(position.volume),
        "regime": quality.get("regime"),
        "setup_grade": setup_grade,
        "momentum_strength": momentum_strength,
        "volatility_state": "high" if trend_strength >= 15 else "normal",
        "structure_state": structure_state,
        "session_phase": plan.get("session"),
        "rr_remaining": 2.0,
        "thesis_valid": quality.get("alignment") != "counter",
        "exposure_fraction": 0.5,
    }


def _select_management_decision(plan: dict, position, tick, runtime_state: dict, now: datetime):
    trade = _build_management_trade(plan, position, runtime_state)
    market_price = float(tick.ask if trade["side"] == "BUY" else tick.bid)
    decision = evaluate_trade_management(trade, market_price=market_price, now=now)
    if decision.get("action") == "hold":
        return None
    decision["position_ticket"] = getattr(position, "ticket", None)
    decision["symbol"] = position.symbol
    return decision


def _execute_management_action(position, management: dict):
    action = management.get("action")
    if action in {"partial_take_profit", "close_runner", "close_trade_early"}:
        close_fraction = float(management.get("close_fraction", 1.0) or 1.0)
        close_volume = max(0.01, round(float(position.volume) * close_fraction, 2))
        return execute_partial_close(position, close_volume=close_volume)
    if action in {"move_stop_to_breakeven", "trail_stop"}:
        return execute_modify_position_prices(position, sl_price=management.get("new_sl"), tp_price=getattr(position, "tp", 0.0))
    if action == "scale_in_existing_idea":
        scale_fraction = float(management.get("scale_fraction", 0.5) or 0.5)
        lot = max(0.01, round(float(position.volume) * scale_fraction, 2))
        side = management.get("side") or ("BUY" if int(position.type) == mt5.POSITION_TYPE_BUY else "SELL")
        return execute_market_open(
            position.symbol,
            side,
            lot,
            sl_price=management.get("new_sl") or getattr(position, "sl", 0.0),
            tp_price=management.get("tp_hint") or getattr(position, "tp", 0.0),
            comment="Hermes manage scale-in",
        )
    return {"ok": False, "error": "unsupported_management_action", "action": action}


def main():
    now = datetime.now(timezone.utc)
    if not mt5.initialize():
        print(json.dumps({"ok": False, "error": "mt5_initialize_failed", "last_error": mt5.last_error()}, ensure_ascii=False))
        return
    try:
        ensure_xau_plan_dirs()
        runtime = load_runtime_state()
        plan = load_current_plan()
        step = determine_runtime_step(plan, now=now)

        if step in {"plan", "reassess"}:
            old_plan = plan
            plan, err = _build_live_plan(now)
            if err:
                print(json.dumps(err, ensure_ascii=False))
                return
            _save_plan_and_state(plan, runtime, step)

            # ── Save review snapshot for Hermes oversight ──
            try:
                from mt5_xau_review import save_review_snapshot
                smc_data = plan.get("context", {}).get("smc", {})
                merged_data = plan.get("context", {}).get("merged", {})
                save_review_snapshot(plan, smc_data, merged_data, now)
            except Exception:
                pass  # never break the pipeline for review

            brief = render_plan_brief(plan)
            if step == "reassess" and old_plan:
                append_reassessment_log(None, {
                    "at": now.isoformat(),
                    "plan_id": plan["plan_id"],
                    "event": "reassess",
                    "old_bias": old_plan.get("bias"),
                    "new_bias": plan.get("bias"),
                })
                brief = render_reassess_brief(old_plan, plan)
            print(json.dumps({
                "ok": True,
                "step": step,
                "plan_id": plan["plan_id"],
                "brief": brief,
            }, ensure_ascii=False))
            return

        tick = mt5.symbol_info_tick("XAUUSD")
        if tick is None:
            print(json.dumps({"ok": False, "error": "tick_unavailable", "last_error": mt5.last_error()}, ensure_ascii=False))
            return

        positions = mt5.positions_get(symbol="XAUUSD") or []
        if positions:
            # Build trading insights from closed-trade history for guardrail enforcement
            account = mt5.account_info()
            trading = _compute_trading_insights(account, now)
            insights = trading["insights"]

            for position in positions:
                management = _select_management_decision(plan, position, tick, runtime_state=runtime, now=now)
                if management:
                    management = _filter_management_by_insights(management, insights)
                    execution_result = _execute_management_action(position, management)
                    runtime.setdefault("management", {})[_management_runtime_key(position)] = {
                        "filled_tp_levels": sorted(set((runtime.get("management", {}).get(_management_runtime_key(position), {}) or {}).get("filled_tp_levels", []) + ([management.get("target_hit")] if execution_result.get("ok") and management.get("action") == "partial_take_profit" and management.get("target_hit") is not None else []))),
                        "breakeven_active": (management.get("action") in {"move_stop_to_breakeven", "trail_stop", "close_runner"} and execution_result.get("ok")) or bool((runtime.get("management", {}).get(_management_runtime_key(position), {}) or {}).get("breakeven_active", False)),
                        "runner_active": False if (execution_result.get("ok") and management.get("action") in {"close_runner", "close_trade_early"}) else bool((runtime.get("management", {}).get(_management_runtime_key(position), {}) or {}).get("runner_active", True)),
                        "scaled_in_levels": sorted(set((runtime.get("management", {}).get(_management_runtime_key(position), {}) or {}).get("scaled_in_levels", []) + ([management.get("scale_level")] if execution_result.get("ok") and management.get("action") == "scale_in_existing_idea" and management.get("scale_level") is not None else []))),
                    }
                    runtime["last_report_key"] = f"management:{position.ticket}:{management.get('action')}:{execution_result.get('ok')}"
                    save_runtime_state(None, runtime)
                    print(json.dumps({
                        "ok": execution_result.get("ok", False),
                        "step": "manage",
                        "plan_id": plan.get("plan_id"),
                        "position_ticket": position.ticket,
                        "management": management,
                        "execution": execution_result,
                        "insights": {k: insights.get(k) for k in ["defcon", "runner_allowed", "scale_in_allowed", "partial_allowed", "trade_allowed"]},
                        "brief": render_management_brief(plan, management),
                    }, ensure_ascii=False))
                    return

        monitor = evaluate_monitor_cycle(plan, price=float(tick.ask), now=now)
        runtime["active_plan_id"] = plan.get("plan_id")
        runtime["last_step"] = "monitor"
        runtime["last_monitor_action"] = monitor.get("action")

        payload = {
            "ok": True,
            "step": "monitor",
            "plan_id": plan.get("plan_id"),
            "monitor": monitor,
            "brief": render_monitor_brief(plan, monitor),
        }
        if monitor.get("action") == "market_order":
            info = mt5.symbol_info("XAUUSD")
            account = mt5.account_info()
            trading = _compute_trading_insights(account, now)
            performance_state = trading["performance_state"]
            account_policy = trading["account_policy"]
            insights = trading["insights"]
            setup_grade = _infer_setup_grade(plan)

            # DEFCON RED blocks entry before any sizing
            if not insights.get("trade_allowed", True):
                monitor = {
                    "action": "no_trade",
                    "reason": f"defcon_{insights.get('defcon', 'red')}:entry_blocked",
                    "zone": monitor.get("zone"),
                    "price": monitor.get("price"),
                    "plan_id": monitor.get("plan_id"),
                    "at": now.isoformat(),
                }
                payload["monitor"] = monitor
                payload["brief"] = render_monitor_brief(plan, monitor)
                payload["account_policy"] = account_policy
                payload["performance_state"] = performance_state
                payload["insights"] = {k: insights.get(k) for k in ["defcon", "trade_allowed"]}
                runtime["last_report_key"] = build_monitor_report_key(monitor)
                save_runtime_state(None, runtime)
                print(json.dumps(payload, ensure_ascii=False))
                return

            # Build sizing with DEFCON risk override applied
            sizing = _build_execution_sizing(
                monitor["blueprint"], info, account_policy, setup_grade,
                risk_override=insights.get("risk_override"),
            )
            if not sizing.get("meaningful"):
                monitor = {
                    "action": "no_trade",
                    "reason": sizing.get("reason"),
                    "zone": monitor.get("zone"),
                    "price": monitor.get("price"),
                    "plan_id": monitor.get("plan_id"),
                    "at": now.isoformat(),
                }
                payload["monitor"] = monitor
                payload["brief"] = render_monitor_brief(plan, monitor)
                payload["account_policy"] = account_policy
                payload["performance_state"] = performance_state
                payload["sizing"] = sizing
                runtime["last_report_key"] = build_monitor_report_key(monitor)
                save_runtime_state(None, runtime)
                print(json.dumps(payload, ensure_ascii=False))
                return
            execution = execute_trade_blueprint(
                monitor["blueprint"],
                lot=float(sizing["lot"]),
                point=float(info.point),
                command_runner=run_mt5_direct_command,
                now=now,
            )
            append_execution_log(None, {
                "at": now.isoformat(),
                "plan_id": plan.get("plan_id"),
                "action": execution.get("command", [None])[0],
                "ok": execution.get("ok"),
                "symbol": "XAUUSD",
                "lot": sizing.get("lot"),
                "risk_usd": sizing.get("risk_usd"),
                "risk_pct": sizing.get("risk_pct"),
                "regime": sizing.get("regime"),
            })
            if execution.get("ok"):
                ticket = _extract_ticket(execution)
                if ticket:
                    _save_setup_profile(ticket, plan, setup_grade)
            runtime["last_report_key"] = f"execution:{execution.get('ok')}:{sizing.get('lot')}"
            payload["execution"] = execution
            payload["sizing"] = sizing
            payload["account_policy"] = account_policy
            payload["performance_state"] = performance_state
            payload["brief"] = render_execution_brief(plan, execution)
            save_runtime_state(None, runtime)
            print(json.dumps(payload, ensure_ascii=False))
            return

        if should_emit_monitor_report(runtime, monitor):
            runtime["last_report_key"] = build_monitor_report_key(monitor)
            save_runtime_state(None, runtime)
            print(json.dumps(payload, ensure_ascii=False))
            return

        save_runtime_state(None, runtime)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
