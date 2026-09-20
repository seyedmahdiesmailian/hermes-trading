from __future__ import annotations


def _base_risk_pct(balance: float) -> float:
    if balance < 800:
        return 0.01
    if balance < 1500:
        return 0.015
    if balance < 5000:
        return 0.02
    return 0.015


def _count_entries_today(closed_trades: list[dict], today: str) -> int:
    """Count DEAL_ENTRY_IN deals whose timestamp falls on `today` (UTC).

    BUG FIX 2026-08-30: `trades_today` was READ by the MAX_DAILY_TRADES gate
    in auto_executor but never WRITTEN by anyone — the daily trade cap had
    been dead code since day one (it always saw 0).
    """
    from datetime import datetime, timezone
    n = 0
    for t in closed_trades or []:
        if str(t.get('entry', '1')) not in ('0', 'IN'):
            continue  # only opening deals
        ts = t.get('time') or t.get('time_done')
        try:
            if datetime.fromtimestamp(float(ts), tz=timezone.utc).date().isoformat() == today:
                n += 1
        except (TypeError, ValueError, OSError):
            continue
    return n


def compute_performance_state(current: dict, today: str, balance: float, closed_trades: list[dict]) -> dict:
    state = dict(current or {})
    entries_today = _count_entries_today(closed_trades, today)
    if state.get("day") != today:
        return {
            "day": today,
            "starting_balance": balance,
            "daily_pnl": 0.0,
            "loss_streak": 0,
            "trades_today": entries_today,
            "last_closed_ticket": state.get("last_closed_ticket"),
            # b88 FIX 2026-09-05: this branch used to return WITHOUT
            # `recent_closed`, so the FIRST cycle of every new UTC day handed
            # DEFCON an empty deal window -> total 0 -> GREEN by construction,
            # whatever the previous day did. DEFCON is the only live gate whose
            # input is the book's own history, and it was blind exactly on the
            # cycle where "you are bleeding, do not open today's first trade"
            # is worth the most. Carrying the window through the rollover is
            # STRICTLY tightening: daily_pnl is 0.0 here so RED (which needs
            # daily_pnl < 0) still cannot fire, and YELLOW only halves risk —
            # no gate gets looser. loss_streak stays reset on purpose: it also
            # feeds check_kill_switch and assess_account_policy, so carrying it
            # across days would silently change the kill switch's meaning
            # (multi-day streaks) — that is a human decision, not a side
            # effect of this fix. Same expression as the branch below, so the
            # rollover state equals what the next cycle computes from the feed.
            "recent_closed": (closed_trades or [])[-10:],
        }

    last_closed_ticket = state.get("last_closed_ticket")
    new_trades = [t for t in closed_trades if last_closed_ticket is None or t.get("ticket") > last_closed_ticket]
    running_daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
    loss_streak = int(state.get("loss_streak", 0) or 0)

    def _n(trade, k):
        try:
            return float(trade.get(k) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    for trade in new_trades:
        # Net, not gross: MT5 `profit` excludes commission/swap, so the
        # kill-switch / daily-loss gates that read daily_pnl were a round of
        # fees too optimistic. Tightening only. Opening deals (entry=0) still
        # contribute their fees to daily_pnl but MUST NOT touch loss_streak
        # (b89: profit 0.0 on opens is why the streak arm stays exact).
        net = _n(trade, "profit") + _n(trade, "commission") + _n(trade, "swap")
        running_daily_pnl = round(running_daily_pnl + net, 2)
        if str(trade.get("entry", "1")) in ("0", "IN"):
            continue
        if net < 0:
            loss_streak += 1
        elif net > 0:
            loss_streak = 0

    return {
        "day": today,
        "starting_balance": float(state.get("starting_balance", balance) or balance),
        "daily_pnl": running_daily_pnl,
        "loss_streak": loss_streak,
        # max() keeps the count monotonic within a day even if the broker feed
        # returns a shorter window than the previous tick
        "trades_today": max(entries_today, int(state.get("trades_today", 0) or 0)),
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
