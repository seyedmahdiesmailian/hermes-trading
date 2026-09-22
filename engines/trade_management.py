from __future__ import annotations

from datetime import datetime


GRADE_RANK = {"A": 3, "B": 2, "C": 1}

# b109: the keys the ladder functions read out of a trade dict. ONE list, so a
# producer (live or backtest) that forgets one fails loudly in the parity test
# instead of silently defaulting — which is exactly how the backtest's
# "live-parity ladder" degenerated into a constant (b108's side finding).
LADDER_FIELDS = ("setup_grade", "momentum_strength", "volatility_state",
                 "structure_state", "session_phase", "rr_remaining",
                 "thesis_valid", "exposure_fraction")


def _is_buy(trade: dict) -> bool:
    return str(trade.get("side", "")).upper() == "BUY"


def _next_unfilled_target(trade: dict):
    filled = set(float(x) for x in trade.get("filled_tp_levels", []))
    for target in trade.get("tp_levels", []):
        target_f = float(target)
        if target_f not in filled:
            return target_f
    return None


def build_tp_ladder(price_open: float, side: str, broker_tp, raw_levels) -> list:
    """b44 filter + b60 midpoint rebuild — THE ONE definition of the live TP
    ladder (b169: was inlined only in position_daemon.build_trade).

    Two producers feed evaluate_trade_management a trade dict: the watchdog
    (position_daemon, every 5s) and hermes_runtime's manage-fallback (runs
    whenever the watchdog heartbeat is >60s stale — b167's lesson: exactly
    when the daemon's fixes cannot help). Until b169 only the watchdog
    shaped the ladder:

      * b44: plan levels are re-drawn every reassessment and can end up on
        the WRONG side of this position's entry (#103326893: stale TP1
        4416.78 above a SELL entered at 4415.82 — and as the FIRST list
        entry it also made _next_unfilled_target return a target the
        profit_side guard blocks, dead-locking the legit farther targets so
        no TP/BE branch could ever fire on that path).
      * b60: live TP1 must mirror the backtest geometry — halfway between
        entry and the FINAL target (#103976964: TP1 0.52 away vs SL 10.6 →
        b55's "100% at TP1" closed the whole ticket for +0.80$).

    Behaviour is byte-identical to the watchdog's inline block it was
    extracted from — including keeping targets exactly ON entry for SELL
    (strict `>` test) and the `broker_tp` truthiness gate (None/0 drop out).
    """
    side_buy = (side == 'BUY')
    tp_levels = [float(t) for t in (raw_levels or [])
                 if (float(t) > price_open) == side_buy]
    if tp_levels:
        # The broker TP (set by the executor from the blueprint) IS the final
        # target the backtest rides to; prefer it when it is on the profit
        # side, else the furthest plan target.
        _cands = [float(broker_tp)] if (broker_tp and (float(broker_tp) > price_open) == side_buy) else []
        _cands += [t for t in tp_levels if (t > price_open) == side_buy]
        _final = max(_cands, key=lambda t: abs(t - price_open)) if _cands else None
        if _final:
            _mid = price_open + (_final - price_open) * 0.5
            tp_levels = [_mid, _final]
    return tp_levels


def _next_scale_level(trade: dict):
    used = set(float(x) for x in trade.get("scaled_in_levels", []))
    for level in trade.get("scale_in_levels", []):
        level_f = float(level)
        if level_f not in used:
            return level_f
    return None


def _grade_value(trade: dict) -> int:
    return GRADE_RANK.get(str(trade.get("setup_grade", "B")).upper(), 2)


def ladder_fields(quality: dict, setup_grade: str,
                  session: str | None = None) -> dict:
    """b109: THE ONE definition of how a plan becomes the fields the ladder
    reads. Both live producers (hermes_runtime.cycle, position_daemon.build_trade)
    and the live-parity backtest (engines.backtest_real.strategy_signal) call
    this, so "live semantics" is a single source, not three lookalikes.

    grade is a PARAMETER, not derived here, so each caller states which rule
    it is applying — but since b111 (2026-09-07) all three live/lab producers
    pass the SAME rule (engines.plan.setup_grade). Before that,
    position_daemon.build_trade inlined a looser pre-b45 variant (no regime
    clause for an A, 'mixed' reaching B) while hermes_runtime/auto_executor
    required a continuation regime; the divergence was measured inert and the
    copies were collapsed (scripts/b111_blast_radius_probe.py).

    rr_remaining is a CONSTANT 2.0 in both producers (never recomputed from
    the live price path), which is why the `rr_remaining <= 1.2` weak clause
    and the `>= 2.0` runner clause are both dead weight — see the collapse
    note on _partial_close_fraction. The backtest mirrors the constant because
    modelling a live rr recompute would simulate a rule live never runs.
    """
    q = quality or {}
    trend = float(q.get("trend_strength", 0) or 0)
    alignment = q.get("alignment")
    return {
        "setup_grade": setup_grade,
        "momentum_strength": min(1.0, max(0.2, trend / 2.0)),   # ATR units -> 0-1
        "volatility_state": "high" if trend >= 3.0 else "normal",
        "structure_state": "healthy" if alignment == "aligned" else "mixed",
        "session_phase": session if session is not None else q.get("session"),
        "rr_remaining": 2.0,
        # b109: the constant is load-bearing, not laziness — see docstring.
        "thesis_valid": alignment != "counter",
        "exposure_fraction": 0.5,
    }


def _partial_close_fraction(trade: dict) -> tuple[float, str]:
    # b55: close the FULL position at TP1 except the strong-runner lane.
    # Evidence: honest live-parity backtest (trailing stop now simulated —
    # b55b found the old sim lied by omission) + 13-week window test
    # (scripts/ab_b55d_windows.py): 100% at TP1 beat 85% in 11/13 weeks,
    # +260$/3wk, zero big-loss weeks. The runner lane rarely reached TP2
    # live and mostly gave back locked profit at the trail.
    # The 0.3 strong-runner branch stays: grade A+ AND momentum>=0.8 AND
    # rr>=2 AND healthy structure — a thesis the parity backtest cannot
    # model, and it has never fired live (0 occurrences in execution_log).
    momentum = float(trade.get("momentum_strength", 0.5) or 0.5)
    grade = _grade_value(trade)
    rr_remaining = float(trade.get("rr_remaining", 0.0) or 0.0)
    structure = str(trade.get("structure_state", "healthy"))

    if grade >= 3 and momentum >= 0.8 and rr_remaining >= 2.0 and structure == "healthy":
        return 0.3, "strong_runner_keep_more"
    # b182 (2026-09-09): the full exit at TP1 is SUPERSEDED on the b60
    # midpoint ladder. b55's evidence was taken while TP1 still meant the
    # FINAL target; b60 moved TP1 to the midpoint (broker TP = final), so
    # "close everything at TP1" now realizes +0.75R on a 1.5R plan and
    # leaves the rest unvisited. Live audit of the last 33 positions (broker
    # deals, net per position): 22 wins +$653 (avg +29.7) vs 11 losses
    # -$659 (avg -59.9) — payoff 0.50, exactly half, because every winner
    # was amputated mid-flight. scripts/b182_exit_policy_backtest.py (26
    # live trades joined to broker fills + 656 replay legs, real M5 bars,
    # SL-first ambiguity rule, commission in): take 50% at TP1-mid, keep the
    # rest for the broker TP under the existing BE/lock machinery —
    # live +3.8R → +4.2..4.8R, replay_all -93.2R → -33.2..-41.4R, wins 9/9
    # weekly slices vs P0_live, and it is the only family that lifts the
    # average winner (+0.81R → +0.98R) WITHOUT dropping the win rate.
    # The single-target geometry (no levels beyond the one being hit —
    # b55's world, the parity backtest's shape) keeps 1.0.
    try:
        entry = float(trade.get("entry_price") or trade.get("entry") or 0.0)
    except (TypeError, ValueError):
        entry = 0.0
    try:
        vol = float(trade.get("volume") or trade.get("lots") or 0.0)
    except (TypeError, ValueError):
        vol = 0.0
    levels = [float(x) for x in (trade.get("tp_levels") or [])]
    pending = _next_unfilled_target(trade)
    # b182a: a 0.01-lot position CANNOT be halved — volume_step is 0.01, so
    # the bridge would send a 100% partial close and the broker rejects it
    # (retcode 10026, the exact failure b55 documented). Under 0.02 lots the
    # full close at TP1 stands. Unknown volume (parity-backtest dicts) also
    # keeps the legacy behaviour: do not invent splittability.
    if vol >= 0.02 and entry > 0 and pending is not None and any(
            abs(lvl - entry) > abs(pending - entry) + 1e-9 for lvl in levels):
        return 0.5, "half_at_tp1_run_rest"
    if grade <= 1 or momentum <= 0.4 or rr_remaining <= 1.2 or structure == "failing":
        return 1.0, "weak_full_exit_at_tp1"
    return 1.0, "balanced_full_exit_at_tp1"


def _tp1_exit_closes_all(trade: dict) -> bool:
    """b55: True when the TP1 partial is the FULL position — the watchdog must
    close the ticket instead of partial-closing (MT5 rejects a 100% partial
    with retcode 10026). The strong-runner lane is the only share < 1."""
    share, _reason = _partial_close_fraction(trade)
    return share >= 1.0


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

    # b65/b65b/b65c (2026-09-03): a tighter runner trail harvested MORE total
    # R in every independent slice — M5 6000 bars (+189.1 vs +178.5R), M15
    # 6000 bars (+209.4 vs +187.3R), and both halves of the M5 window
    # (older +97.0 vs +93.8, recent +91.0 vs +84.1). The old 0.45 gave back
    # locked profit on the runner leg; 0.30 (the former high-vol value) wins
    # in all four cuts. Strong-runner 0.6 stays: that lane has never fired
    # live, so there is no evidence to touch it.
    if volatility == "high":
        return round(max(risk_distance * 0.3, 3.0), 2), "high_volatility_tighter_trail"
    if momentum >= 0.8:
        return round(max(risk_distance * 0.6, 4.0), 2), "strong_runner_looser_trail"
    return round(max(risk_distance * 0.3, 3.0), 2), "balanced_trail"


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
        # b205 RATCHET — the BE move is a STOP MOVE, same contract b202 pinned
        # for trail_stop: it may only ever tighten. The branch below compares
        # new_sl to the MARKET (b44/b52 gap guard) but never to the CURRENT
        # stop, so after legacy_guards.evaluate_news_lock tightened SL to
        # price-0.5*ATR pre-TP1 (it DOES enforce `protective` — proof the
        # codebase knows this verb must never loosen), a post-TP1
        # entry+0.15R BE proposal sat $46 BELOW the accepted lock (probe:
        # scripts/b205_be_ratchet_probe.py) and the executor would have
        # shipped the loosening modify straight to the broker, refunding the
        # news protection exactly when volatility is worst. Strictly
        # tightening: an equal or better existing SL stays in force.
        improves = new_sl > sl if side_buy else new_sl < sl
        # b44: the broker rejects a stop on the wrong side of the market
        # (retcode 10016 — SELL needs SL ABOVE price). Before this guard the
        # watchdog hammered the same invalid modify every 5s for minutes.
        # b52: 0.10 was not enough — the broker measures stops from the far
        # side of the spread (SELL SL vs ASK) plus trade_stops_level, so an SL
        # a hair above the bid passed this guard and still died with retcode
        # 10025 (#103636278 hammered ~28x, 03:42-03:45 UTC). 0.5 covers
        # XAUUSD spread+stops with room; below that we hold, existing SL stays.
        gap_ok = (new_sl < market_price - 0.50) if side_buy else (new_sl > market_price + 0.50)
        if improves and gap_ok:
            return {
                "action": "move_stop_to_breakeven",
                "new_sl": new_sl,
                "reason": reason,
                "at": now.isoformat(),
            }
        # b205: when `improves` is False the existing (better) SL stays in
        # force — silent fall-through, exactly like the b52 gap guard above.
        # An early `hold` RETURN here would starve the runner-trail branch
        # below (BE is evaluated first), so the reason is only observable via
        # the trailing `trail_stop_not_improving` / final hold paths.

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
        # b202 RATCHET — a trail may only ever move the stop TOWARD price, never
        # away from it. The live-parity funnel has always enforced this
        # (engines/backtest.py: `if cand > t["sl"]` for a BUY, `<` for a SELL);
        # the live evaluator did not, so on every pullback after TP2 it proposed
        # an SL BEHIND the one already on the book and auto_executor shipped it
        # straight to bridge.modify_position. For a SELL runner that means the
        # stop moves UP (price + trail_distance) as price bounces, handing back
        # locked profit and, once the bounce exceeds trail_distance, giving back
        # the breakeven lock too. Strictly tightening: the existing (better) SL
        # stays in force, no gate gets looser, and live now matches the geometry
        # every stored exp_R was priced on.
        improves = new_sl > sl if side_buy else new_sl < sl
        if not improves:
            return {
                "action": "hold",
                "reason": "trail_stop_not_improving",
                "at": now.isoformat(),
            }
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
