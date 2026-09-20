from __future__ import annotations


def _base_risk_pct(balance: float) -> float:
    if balance < 800:
        return 0.01
    if balance < 1500:
        return 0.015
    if balance < 5000:
        return 0.02
    return 0.015


def _entry_value(deal: dict) -> bool:
    """Whether a broker deal opens exposure (MT5 DEAL_ENTRY_IN = 0)."""
    return str(deal.get("entry", "1")).strip().upper() in {"0", "IN"}


def _deal_timestamp(deal: dict):
    from datetime import datetime, timezone
    ts = deal.get("time") or deal.get("time_done")
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def deal_net_pnl(deal: dict) -> float:
    """Return the broker-confirmed cash result of one deal.

    MT5 exposes commission and swap beside ``profit``. Entry commissions are
    carried by the opening deal, so summing this function over the feed keeps
    the daily account gates net-of-cost without inventing a fee when a field
    is absent in an old fixture.
    """
    def _number(key: str) -> float:
        try:
            return float(deal.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0
    return round(_number("profit") + _number("commission") + _number("swap"), 2)


def _count_entries_today(closed_trades: list[dict], today: str) -> int:
    """Count DEAL_ENTRY_IN deals whose timestamp falls on `today` (UTC).

    BUG FIX 2026-08-30: `trades_today` was READ by the MAX_DAILY_TRADES gate
    in auto_executor but never WRITTEN by anyone — the daily trade cap had
    been dead code since day one (it always saw 0).
    """
    n = 0
    for deal in closed_trades or []:
        if not _entry_value(deal):
            continue
        stamp = _deal_timestamp(deal)
        if stamp and stamp.date().isoformat() == today:
            n += 1
    return n


def _entry_costs(closed_trades: list[dict]) -> dict[str, tuple[float, float]]:
    """Map position id to (entry-cost net, entry volume) for loss streaks."""
    costs: dict[str, tuple[float, float]] = {}
    for deal in closed_trades or []:
        if not _entry_value(deal):
            continue
        position = str(deal.get("position_id") or deal.get("order") or "").strip()
        if not position:
            continue
        fee, volume = costs.get(position, (0.0, 0.0))
        try:
            opened_volume = float(deal.get("volume", 0) or 0)
        except (TypeError, ValueError):
            opened_volume = 0.0
        costs[position] = (fee + deal_net_pnl(deal), volume + opened_volume)
    return costs


def _exit_net_pnl(deal: dict, entry_costs: dict[str, tuple[float, float]]) -> float:
    """Net result of a closing leg, allocating its entry fee by volume."""
    result = deal_net_pnl(deal)
    position = str(deal.get("position_id") or deal.get("order") or "").strip()
    fee, opened_volume = entry_costs.get(position, (0.0, 0.0))
    if position and opened_volume > 0:
        try:
            result += fee * (float(deal.get("volume", 0) or 0) / opened_volume)
        except (TypeError, ValueError):
            pass
    return round(result, 2)


def compute_performance_state(current: dict, today: str, balance: float, closed_trades: list[dict]) -> dict:
    """Build the account-gate state from the broker deal feed.

    ``daily_pnl`` is deliberately net of profit, commission and swap. The
    previous implementation accumulated only ``profit``, which made daily
    loss, DEFCON and account regime less conservative than the real account.
    ``daily_gross_pnl`` remains as an audit field so reports can explain the
    difference. ``pnl_basis`` makes the one-time migration from old gross
    state explicit and prevents carrying an old gross number forward.
    """
    state = dict(current or {})
    entries_today = _count_entries_today(closed_trades, today)
    if state.get("day") != today:
        return {
            "day": today,
            "starting_balance": balance,
            "daily_pnl": 0.0,
            "daily_gross_pnl": 0.0,
            "pnl_basis": "net",
            "loss_streak": 0,
            "trades_today": entries_today,
            "last_closed_ticket": state.get("last_closed_ticket"),
            # b88: keep the recent broker window through UTC rollover so
            # DEFCON is not blind on the first cycle of a new day. Only the
            # day-scoped PnL and streak reset here.
            "recent_closed": (closed_trades or [])[-10:],
        }

    # Existing state files predate the net-PnL contract. Rebuild today's
    # totals once from the feed instead of carrying a gross number into the
    # new gate. This also repairs a state created before this deployment.
    migrating_legacy_state = state.get("pnl_basis") != "net"
    if migrating_legacy_state:
        # Rebuild the whole current-day feed rather than carrying a gross
        # accumulator forward. Production history includes several days, so
        # use timestamps when at least one deal is stamped for `today`.
        # Timestamp-less/old synthetic feeds retain the old complete-feed
        # behavior instead of silently dropping their only evidence.
        dated_today = [t for t in closed_trades
                       if (stamp := _deal_timestamp(t))
                       and stamp.date().isoformat() == today]
        new_trades = dated_today if dated_today else list(closed_trades or [])
        running_daily_pnl = 0.0
        running_gross_pnl = 0.0
        loss_streak = 0
        last_closed_ticket = state.get("last_closed_ticket")
    else:
        last_closed_ticket = state.get("last_closed_ticket")
        new_trades = [t for t in closed_trades
                      if last_closed_ticket is None or t.get("ticket") > last_closed_ticket]
        running_daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
        running_gross_pnl = float(state.get("daily_gross_pnl", 0.0) or 0.0)
        loss_streak = int(state.get("loss_streak", 0) or 0)

    entry_costs = _entry_costs(closed_trades)
    for deal in new_trades:
        # Daily account PnL follows actual cash movement on each broker deal.
        running_daily_pnl = round(running_daily_pnl + deal_net_pnl(deal), 2)
        try:
            running_gross_pnl = round(
                running_gross_pnl + float(deal.get("profit", 0) or 0), 2)
        except (TypeError, ValueError):
            pass

        # Loss streak is a trade/closing-leg concept, not an opening-deal
        # concept. Allocate opening commission to the closing leg so a gross
        # winner that is net negative is treated as a loss by the gate.
        if not _entry_value(deal):
            outcome = _exit_net_pnl(deal, entry_costs)
            if outcome < 0:
                loss_streak += 1
            elif outcome > 0:
                loss_streak = 0

    return {
        "day": today,
        "starting_balance": float(state.get("starting_balance", balance) or balance),
        "daily_pnl": running_daily_pnl,
        "daily_gross_pnl": running_gross_pnl,
        "pnl_basis": "net",
        "loss_streak": loss_streak,
        # max() keeps the count monotonic within a day even if the broker feed
        # returns a shorter window than the previous tick
        "trades_today": max(entries_today, int(state.get("trades_today", 0) or 0)),
        "last_closed_ticket": new_trades[-1].get("ticket") if new_trades else last_closed_ticket,
        # last 10 closed deals (with MT5 comment) → DEFCON classification
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
