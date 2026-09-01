from __future__ import annotations

from datetime import datetime


GRADE_RANK = {"A": 3, "B": 2, "C": 1}


def _is_buy(trade: dict) -> bool:
    return str(trade.get("side", "")).upper() == "BUY"


def _next_unfilled_target(trade: dict):
    filled = set(float(x) for x in trade.get("filled_tp_levels", []))
    for target in trade.get("tp_levels", []):
        target_f = float(target)
        if target_f not in filled:
            return target_f
    return None


def _next_scale_level(trade: dict):
    used = set(float(x) for x in trade.get("scaled_in_levels", []))
    for level in trade.get("scale_in_levels", []):
        level_f = float(level)
        if level_f not in used:
            return level_f
    return None


def _grade_value(trade: dict) -> int:
    return GRADE_RANK.get(str(trade.get("setup_grade", "B")).upper(), 2)


def _partial_close_fraction(trade: dict) -> tuple[float, str]:
    # b54: shares raised after the 13-week M5 parity ladder test
    # (scripts/ab_b54_windows.py + ab_b54_ladder_weeks): 0.7 beats 0.5 in
    # 13/13 weeks (+180$/3wk), 0.85 beats it in 13/13 (+315$). After TP1 the
    # final target rarely fills in this regime — lock more early. The 0.3
    # strong-runner branch stays: it is the only lane with a momentum thesis
    # the parity backtest cannot model.
    momentum = float(trade.get("momentum_strength", 0.5) or 0.5)
    grade = _grade_value(trade)
    rr_remaining = float(trade.get("rr_remaining", 0.0) or 0.0)
    structure = str(trade.get("structure_state", "healthy"))

    if grade >= 3 and momentum >= 0.8 and rr_remaining >= 2.0 and structure == "healthy":
        return 0.3, "strong_runner_keep_more"
    if grade <= 1 or momentum <= 0.4 or rr_remaining <= 1.2 or structure == "failing":
        return 0.85, "weak_follow_through_lock_more"
    return 0.7, "balanced_partial"


def _breakeven_stop(trade: dict) -> tuple[float, str]:
    entry = float(trade["entry_price"])
    sl = float(trade["sl"])
    side_buy = _is_buy(trade)
    momentum = float(trade.get("momentum_strength", 0.5) or 0.5)
    grade = _grade_value(trade)
    risk_distance = abs(entry - sl)

    if grade >= 2 and momentum >= 0.65:
        lock = round(risk_distance * 0.15, 2)
        return (round(entry + lock, 2), "lock_in_after_tp1") if side_buy else (round(entry - lock, 2), "lock_in_after_tp1")
    return entry, "plain_breakeven"


def _runner_should_die(trade: dict) -> bool:
    structure = str(trade.get("structure_state", "healthy"))
    momentum = float(trade.get("momentum_strength", 0.5) or 0.5)
    thesis_valid = bool(trade.get("thesis_valid", True))
    return structure == "failing" or momentum <= 0.3 or not thesis_valid


def _trail_params(trade: dict) -> tuple[float, str]:
    entry = float(trade["entry_price"])
    sl = float(trade["sl"])
    risk_distance = abs(entry - sl)
    volatility = str(trade.get("volatility_state", "normal"))
    momentum = float(trade.get("momentum_strength", 0.5) or 0.5)

    if volatility == "high":
        return round(max(risk_distance * 0.3, 3.0), 2), "high_volatility_tighter_trail"
    if momentum >= 0.8:
        return round(max(risk_distance * 0.6, 4.0), 2), "strong_runner_looser_trail"
    return round(max(risk_distance * 0.45, 3.0), 2), "balanced_trail"


def _scale_in_allowed(trade: dict) -> tuple[bool, str]:
    if not bool(trade.get("thesis_valid", True)):
        return False, "scale_in_blocked_invalid_thesis"
    if str(trade.get("structure_state", "healthy")) == "failing":
        return False, "scale_in_blocked_structure"
    if float(trade.get("exposure_fraction", 0.0) or 0.0) >= 1.0:
        return False, "scale_in_blocked_exposure"
    if float(trade.get("rr_remaining", 0.0) or 0.0) < 1.5:
        return False, "scale_in_blocked_rr"
    return True, "valid_pullback_add"


def evaluate_trade_management(trade: dict, market_price: float, now: datetime) -> dict:
    side_buy = _is_buy(trade)
    entry = float(trade["entry_price"])
    sl = float(trade["sl"])
    tp_levels = [float(x) for x in trade.get("tp_levels", [])]
    filled = [float(x) for x in trade.get("filled_tp_levels", [])]

    if not bool(trade.get("thesis_valid", True)) and not filled:
        return {
            "action": "close_trade_early",
            "reason": "thesis_invalidated",
            "at": now.isoformat(),
        }

    next_target = _next_unfilled_target(trade)
    if next_target is not None:
        hit = market_price >= next_target if side_buy else market_price <= next_target
        # b44: a target on the WRONG side of entry is not a take-profit —
        # stale plan levels once fired "TP1" one second after entry and
        # closed 0.06 lots at a loss (#103326893). Never realize a "profit"
        # that is actually negative.
        profit_side = next_target > entry if side_buy else next_target < entry
        if hit and profit_side:
            close_fraction, reason = _partial_close_fraction(trade)
            return {
                "action": "partial_take_profit",
                "target_hit": next_target,
                "close_fraction": close_fraction,
                "reason": reason,
                "at": now.isoformat(),
            }

    if filled and not trade.get("breakeven_active"):
        new_sl, reason = _breakeven_stop(trade)
        # b44: the broker rejects a stop on the wrong side of the market
        # (retcode 10016 — SELL needs SL ABOVE price). Before this guard the
        # watchdog hammered the same invalid modify every 5s for minutes.
        # b52: 0.10 was not enough — the broker measures stops from the far
        # side of the spread (SELL SL vs ASK) plus trade_stops_level, so an SL
        # a hair above the bid passed this guard and still died with retcode
        # 10025 (#103636278 hammered ~28x, 03:42-03:45 UTC). 0.5 covers
        # XAUUSD spread+stops with room; below that we hold, existing SL stays.
        gap_ok = (new_sl < market_price - 0.50) if side_buy else (new_sl > market_price + 0.50)
        if gap_ok:
            return {
                "action": "move_stop_to_breakeven",
                "new_sl": new_sl,
                "reason": reason,
                "at": now.isoformat(),
            }

    if len(filled) >= 2 and trade.get("runner_active"):
        if _runner_should_die(trade):
            return {
                "action": "close_runner",
                "close_fraction": 1.0,
                "reason": "runner_structure_failure",
                "at": now.isoformat(),
            }
        trail_distance, reason = _trail_params(trade)
        new_sl = market_price - trail_distance if side_buy else market_price + trail_distance
        if side_buy:
            new_sl = max(new_sl, entry)
        else:
            new_sl = min(new_sl, entry)
        # b44: a stop on the wrong side of the market is rejected by the
        # broker (retcode 10025 — SELL SL must sit ABOVE current price with
        # the spread). #103326893: price ran back above entry, the clamp
        # pinned SL at entry, and the trail hammered invalid modifies until
        # the position died on that stop. Hold instead — the existing SL
        # stays in force.
        # b52: 0.10 was not enough — the broker measures stops from the far
        # side of the spread (SELL SL vs ASK) plus trade_stops_level, so an SL
        # a hair above the bid passed this guard and still died with retcode
        # 10025 (#103636278 hammered ~28x, 03:42-03:45 UTC). 0.5 covers
        # XAUUSD spread+stops with room; below that we hold, existing SL stays.
        gap_ok = (new_sl < market_price - 0.50) if side_buy else (new_sl > market_price + 0.50)
        if not gap_ok:
            return {
                "action": "hold",
                "reason": "trail_stop_invalid_vs_market",
                "at": now.isoformat(),
            }
        return {
            "action": "trail_stop",
            "new_sl": round(new_sl, 2),
            "trail_distance": trail_distance,
            "reason": reason,
            "at": now.isoformat(),
        }

    next_scale = _next_scale_level(trade)
    if not filled and next_scale is not None:
        hit_scale = market_price <= next_scale if side_buy else market_price >= next_scale
        if hit_scale:
            allowed, reason = _scale_in_allowed(trade)
            if allowed:
                return {
                    "action": "scale_in_existing_idea",
                    "scale_level": next_scale,
                    "reason": reason,
                    "at": now.isoformat(),
                }
            return {
                "action": "hold",
                "reason": reason,
                "at": now.isoformat(),
            }

    return {
        "action": "hold",
        "reason": "no_management_trigger",
        "at": now.isoformat(),
    }
