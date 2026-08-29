from __future__ import annotations


def _base_risk_pct(balance: float) -> float:
    if balance < 800:
        return 0.01
    if balance < 1500:
        return 0.015
    if balance < 5000:
        return 0.02
    return 0.015


def compute_performance_state(current: dict, today: str, balance: float, closed_trades: list[dict]) -> dict:
    state = dict(current or {})
    if state.get("day") != today:
        return {
            "day": today,
            "starting_balance": balance,
            "daily_pnl": 0.0,
            "loss_streak": 0,
            "last_closed_ticket": state.get("last_closed_ticket"),
        }

    last_closed_ticket = state.get("last_closed_ticket")
    new_trades = [t for t in closed_trades if last_closed_ticket is None or t.get("ticket") > last_closed_ticket]
    running_daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
    loss_streak = int(state.get("loss_streak", 0) or 0)

    for trade in new_trades:
        profit = float(trade.get("profit", 0.0) or 0.0)
        running_daily_pnl = round(running_daily_pnl + profit, 2)
        if profit < 0:
            loss_streak += 1
        elif profit > 0:
            loss_streak = 0

    return {
        "day": today,
        "starting_balance": float(state.get("starting_balance", balance) or balance),
        "daily_pnl": running_daily_pnl,
        "loss_streak": loss_streak,
        "last_closed_ticket": new_trades[-1].get("ticket") if new_trades else last_closed_ticket,
        # last 10 closed deals (with MT5 comment) → DEFCON exit classification
        "recent_closed": (closed_trades or [])[-10:],
    }


def assess_account_policy(
    balance: float,
    equity: float,
    free_margin: float,
    margin: float,
    daily_pnl: float,
    loss_streak: int,
    open_positions: int,
) -> dict:
    base = _base_risk_pct(balance)
    drawdown_pct = 0.0 if balance <= 0 else round((balance - equity) / balance, 4)
    margin_ratio = 999.0 if margin <= 0 else round(free_margin / margin, 2)
    reasons = []
    regime = "normal"
    trade_allowed = True
    risk_multiplier = 1.0

    if drawdown_pct >= 0.05 or daily_pnl <= -(balance * 0.03):
        regime = "locked"
        trade_allowed = False
        risk_multiplier = 0.0
        reasons.append("drawdown_limit")
    elif loss_streak >= 2 or daily_pnl <= -(balance * 0.01):
        regime = "defensive"
        risk_multiplier = 0.75
        reasons.append("recent_losses")
    elif drawdown_pct >= 0.025:
        regime = "recovery"
        risk_multiplier = 0.5
        reasons.append("equity_drawdown")

    if margin_ratio < 20:
        regime = "locked"
        trade_allowed = False
        risk_multiplier = 0.0
        if "margin_health" not in reasons:
            reasons.append("margin_health")

    return {
        "balance": balance,
        "equity": equity,
        "free_margin": free_margin,
        "margin": margin,
        "open_positions": open_positions,
        "drawdown_pct": drawdown_pct,
        "margin_ratio": margin_ratio,
        "base_risk_pct": base,
        "risk_multiplier": risk_multiplier,
        "trade_allowed": trade_allowed,
        "regime": regime,
        "reasons": reasons,
        "max_positions_allowed": 1,
    }


def recommend_risk_budget(policy: dict, setup_grade: str) -> dict:
    """Grade-scaled risk budget. NOTE: currently unused by the executor
    (executor computes sizing via compute_xau_position_size with learning
    risk_mult) — kept for the operator CLI / future sizing paths."""
    if not policy.get("trade_allowed"):
        return {"trade_allowed": False, "reason": policy.get("reasons", ["policy_block"])[0]}
    if policy.get("open_positions", 0) >= policy.get("max_positions_allowed", 1):
        return {"trade_allowed": False, "reason": "position_limit"}

    grade_multiplier = {
        "A": 1.0,
        "B": 0.6,
        "C": 0.3,
    }.get(setup_grade, 0.0)
    risk_pct = round(policy["base_risk_pct"] * policy["risk_multiplier"] * grade_multiplier, 4)
    risk_usd = round(policy["balance"] * risk_pct, 2)
    return {
        "trade_allowed": risk_pct > 0,
        "risk_pct": risk_pct,
        "risk_usd": risk_usd,
        "reason": None if risk_pct > 0 else "setup_grade_block",
        "regime": policy.get("regime"),
    }
