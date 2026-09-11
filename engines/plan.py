from __future__ import annotations

from datetime import datetime, timezone

# b54: strategy knobs as patchable module constants (swept by
# scripts/ab_b54_sweep.py on the live-parity M5 funnel; values = live as-is).
# SMC_CONF_FLOOR gates every no-trigger aggressive lane (4 call sites).
SMC_CONF_FLOOR = 0.4
# b193: the range-kill confidence threshold, hoisted from the two literals that
# used to sit in hermes_runtime.build_live_plan and backtest_real.strategy_signal
# (default arg of apply_smc_merge below). Scripts may pass an explicit override.
RANGE_KILL_CONF = 0.35


def stale_at_birth(bias, invalidation, last_close) -> bool:
    """b188(a): a directional plan whose invalidation level is already breached
    by the current close is born dead. True = force neutral. Junk inputs return
    False (fail-open on the ORIGINAL bias, never on a fabricated trade).

    b193: this predicate used to live only in hermes_runtime, so it guarded the
    LIVE plan path while engines/backtest_real re-implemented the surrounding
    bias merge WITHOUT it — the lab kept trading plans live can never emit
    (measured: 11 of 523 funnel signals on the cached M15 leg, 2.1%). It sits in
    this leaf module now, called by apply_smc_merge, which BOTH paths share.
    """
    try:
        inv = float(invalidation or 0)
        close = float(last_close or 0)
    except (TypeError, ValueError):
        return False
    if inv <= 0 or close <= 0:
        return False
    if bias == 'bullish':
        return close <= inv
    if bias == 'bearish':
        return close >= inv
    return False


def _entry_close(rows) -> float:
    """Last settled close of an entry-timeframe stream, tolerant of the two
    bridge row shapes (dict / OHLC tuple). 0.0 = unknown (guard fails open)."""
    try:
        r = rows[-1]
        v = r.get('close', r.get('Close', 0)) if isinstance(r, dict) else r[3]
        return float(v)
    except (TypeError, ValueError, IndexError, KeyError, AttributeError):
        return 0.0


def apply_smc_merge(ctx: dict, merged: dict, *, entry_close: float,
                    range_kill_conf: float = RANGE_KILL_CONF,
                    smc_result: dict | None = None) -> bool:
    """THE bias-merge + b188(a) stale-at-birth guard — ONE definition, TWO paths.

    hermes_runtime.build_live_plan and backtest_real.strategy_signal each carried
    their own copy of this sequence (the b109/b111 drift class). The copy in the
    lab was missing the FINAL step, so the stale-at-birth veto that shipped in
    b188(a) applied to live plans only and every lab exp_R since then was priced
    on a funnel live cannot run (the b189 class, in mirror).

    Order is verbatim what build_live_plan always did: (1) range-kill or adopt
    the merged bias, (2) stamp quality.smc_confidence, (3) optionally record the
    SMC display fields (live only — pass smc_result), (4) the stale-at-birth
    guard. Step 4 is what makes a bias FLIP by the merge expensive: the
    invalidation level was computed by engines.context for the CLASSIC bias, so
    when SMC flips the direction the stop is on the wrong side of price and the
    plan is stale at birth. Returns True when the guard fired.
    """
    classic_regime = ctx.get('quality', {}).get('regime', '')
    smc_confidence = float(merged.get('confidence', 0) or 0)
    smc_bias = merged.get('bias', 'neutral')
    # Only force neutral if SMC is NOT confident AND classic says range
    if classic_regime == 'range' and smc_bias != 'neutral' and smc_confidence < range_kill_conf:
        ctx['bias'] = 'neutral'
        merged['bias'] = 'neutral'
        merged['confidence'] = min(smc_confidence, 0.3)
        merged['action'] = 'wait'
    else:
        # Use SMC bias when confident, even in range
        ctx['bias'] = merged.get('bias', ctx.get('bias'))
    ctx.setdefault('quality', {})['smc_confidence'] = merged.get('confidence')
    if smc_result is not None:
        ctx['quality']['smc_poi'] = (merged.get('smc_source') or {}).get('poi')
        ctx['quality']['smc_signal'] = (merged.get('smc_source') or {}).get('signal')
        ctx.setdefault('context', {})['smc'] = smc_result
        ctx.setdefault('context', {})['merged'] = {
            k: v for k, v in merged.items() if k != 'smc_result'}
    # b188(a) STALE-AT-BIRTH: a plan whose thesis is already wrong at t=0 is a
    # neutral plan (measured pre-fix: 69% of plan_history rows, b185).
    if stale_at_birth(ctx.get('bias'), ctx.get('invalidation'), entry_close):
        ctx['bias'] = 'neutral'
        ctx.setdefault('quality', {})['stale_at_birth'] = True
        return True
    return False

# Late entries re-anchor their stop to min(structure, price ± cap*ATR).
REANCHOR_STOP_ATR_CAP = 2.0
# ...and keep at least this reward:risk after re-anchoring.
REANCHOR_MIN_RR = 1.5
# b79d: THE grade threshold lives here, next to THE grade rule, so the
# monitor gate (orchestrator) and the entry gate (auto_executor Check 6)
# cannot carry two literals that drift. auto_executor re-exports it.
# backtest 2026-08-29: C-grade (weak trend) entries drag win-rate; B keeps
# 13-trade sample with 61.5% WR.
MIN_SETUP_GRADE = "B"


def grade_qualifies(grade: str) -> bool:
    """A < B < C alphabetically, A is best: qualifies iff grade <= min."""
    return str(grade or "").upper() <= MIN_SETUP_GRADE


def setup_grade(plan: dict) -> str:
    """THE canonical setup grade from plan quality — one definition, three
    consumers (the entry gate, the runtime ladder, the watchdog ladder).

    b45 FIX 2026-08-31: 'mixed' alignment no longer qualifies for B.
    Evidence: the two mixed/range sells at 14:15/14:30 UTC (counter-trend
    entries into a rising market with contradictory TF votes) netted -56.7$
    (+37.67 / -94.38), while every aligned plan that day was profitable.
    Mixed votes = coin flip = C = blocked by MIN_SETUP_GRADE.

    b111 (2026-09-07): this rule used to live twice — here-ish in
    engines/auto_executor.py and again in hermes_runtime.py — while
    position_daemon.build_trade inlined a looser PRE-b45 rule (no regime
    clause for an A, 'mixed' reaching B). That third copy is now this
    function. The divergence was measured inert before it was removed
    (scripts/b111_blast_radius_probe.py, ledger
    data/backtest/b111_blast_radius.json): the only cell where the two rules
    produce a different broker-visible action is aligned + trend>=3.0 + a
    NON-continuation regime, and engines.context._detect_regime cannot emit
    that combination (0 of 320 swept vote x trend x geometry cells), so the
    watchdog's looser A was unreachable and its looser B sat in a lane that
    post-b55 closes the full position at TP1 either way.

    This module is a LEAF (stdlib imports only) on purpose: the grade is read
    by the entry gate, the runtime and the watchdog, and a shared definition
    must not create an import cycle between any of them.
    """
    q = plan.get("quality", {}) or {}
    alignment = q.get("alignment")
    trend = float(q.get("trend_strength", 0) or 0)
    regime = q.get("regime")
    if (alignment == "aligned" and trend >= 3.0
            and regime in {"breakout_continuation", "pullback_continuation"}):
        return "A"
    if alignment == "aligned" and trend >= 1.2:
        return "B"
    return "C"


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


def _reanchor_blueprint(bp: dict, price: float, atr: float, min_rr: float | None = None) -> dict:
    """Re-anchor SL/TP around the live price for aggressive (late) entries.

    When price has already run past the plan zones, the structural invalidation
    is far and the first TP is close, so RR collapses (poor_rr / invalid_geometry
    blockers). Tighten the stop to ~2 ATR and pick a valid target so the trade
    keeps sane geometry; if nothing works, mark the blueprint blocked.

    SIDE ASYMMETRY IS INTENT, MEASURED (b160/b161, 2026-09-08): SELL picks the
    FURTHEST candidate, BUY the NEAREST. Symmetrising BUY (max instead of min)
    was A/B'd on the live-parity funnel over cached + W1..W4: it binds on only
    0.7-1.7% of BUY signals (data/backtest/b161_reanchor_binding_census.json),
    never beats the incumbent on any leg (deltas 0.000 x4, W1 -0.006R), so the
    asymmetry costs nothing and the geometry here must NOT be "tidied" without
    a new multi-leg measurement. Pinned by
    tests/test_b161_reanchor_symmetry_verdict.py.

    b54: min_rr None-resolved at CALL time (a default bound at def-time would
    make the sweep's monkeypatch of REANCHOR_MIN_RR a silent no-op).
    """
    if min_rr is None:
        min_rr = REANCHOR_MIN_RR
    atr = float(atr or 0) or 5.0
    side = bp["side"]
    sl = float(bp["sl"])
    stop_dist_cap = REANCHOR_STOP_ATR_CAP * atr

    if side == "SELL":
        # stop must sit above entry: min(structural invalidation, price + 2*ATR)
        sl = min(sl, price + stop_dist_cap) if sl > price else price + stop_dist_cap
        sl = max(sl, price + 0.5 * atr)  # never tighter than half an ATR
        stop_dist = sl - price
        cands = [t for t in bp.get("tp_levels") or [] if t < price]
        tp = max(cands, key=lambda t: (price - t) / stop_dist) if cands else None
        if tp is None or (price - tp) / stop_dist < min_rr:
            tp = price - stop_dist * min_rr
    else:
        sl = max(sl, price - stop_dist_cap) if sl < price else price - stop_dist_cap
        sl = min(sl, price - 0.5 * atr)
        stop_dist = price - sl
        cands = [t for t in bp.get("tp_levels") or [] if t > price]
        tp = min(cands, key=lambda t: (t - price) / stop_dist) if cands else None
        if tp is None or (tp - price) / stop_dist < min_rr:
            tp = price + stop_dist * min_rr

    bp = dict(bp)
    bp["sl"] = round(sl, 2)
    # Parity with auto_executor Check 5.6: the executor recomputes RR from the
    # ROUNDED sl/tp. Naive rounding of tp = price + 1.5*stop can land at
    # RR 1.4997 and the gate kills the trade this function just built
    # (measured: 28/51 live-parity entries died as poor_rr_1.50).
    # Pad the target to min_rr + 0.05 AFTER rounding so geometry always clears
    # the floor with margin.
    _sd = abs(price - bp["sl"])
    _tp = round(tp, 2)
    if _sd > 0:
        _need = price - _sd * (min_rr + 0.05) if side == "SELL" else price + _sd * (min_rr + 0.05)
        _tp = min(_tp, _need) if side == "SELL" else max(_tp, _need)
    bp["tp"] = round(_tp, 2)
    bp["tp_levels"] = [round(_tp, 2)]
    bp["tp_shares"] = [1.0]
    bp["reanchored"] = True
    return bp


def _buy_logic(plan: dict, price: float, trigger_ok: bool, now: datetime,
               m5_ok: bool = True) -> dict:
    zones = plan["zones"]
    execution = plan.get("execution", {})
    breakout_trigger = execution.get("breakout_trigger", zones["short_entry_low"])

    if zones["long_entry_low"] <= price <= zones["long_entry_high"]:
        if trigger_ok:
            bp = build_trade_blueprint(plan, price=price, trigger_ok=trigger_ok)
            bp = _reanchor_blueprint(
                bp, price, float(plan.get("atr") or plan.get("quality", {}).get("atr") or 20)
            )
            return {
                "action": "market_entry_now",
                "zone": "long_zone",
                "execution_style": "pullback_continuation",
                "blueprint": bp,
                "at": now.isoformat(),
            }
        return {
            "action": "wait_for_trigger",
            "zone": "long_zone",
            "execution_style": "pullback_wait",
            "at": now.isoformat(),
        }

    if price < zones["long_entry_low"]:
        # b193b: this used to return `place_buy_limit` - a phantom. No code path
        # ever places a resting order (hermes_runtime only proposes on
        # market_order/market_entry_now), so 53 log lines said "buy limit" while
        # nothing was pending. A resting limit would also re-admit exactly the
        # adverse selection b187 killed: it fills as price pushes INTO the zone
        # without any M5 confirmation. Honest state: wait for the pullback, and
        # let the in-zone branch above handle it once confirmed.
        return {
            "action": "wait_for_pullback",
            "reason": "below_long_zone",
            "zone": "discount",
            "target_entry": zones["long_entry_low"],
            "execution_style": "pullback_wait",
            "at": now.isoformat(),
        }

    if price >= zones["value_high"] and plan.get("bias") == "bullish":
        # Aggressive premium entry — only when close to zone
        atr_val = float(plan.get("atr") or plan.get("quality", {}).get("atr") or 20)
        dist_above = price - zones["value_high"]
        if dist_above > atr_val * 1.5:
            return {
                "action": "no_trade",
                "reason": "price_far_above_zone_plan_stale",
                "zone": "premium",
                "execution_style": "wait_for_replan",
                "at": now.isoformat(),
            }
        smc_conf = plan.get("quality", {}).get("smc_confidence", 0) or 0
        # b193: the aggressive premium lane used to bypass b187 with a hardcoded
        # trigger_ok=True. It is the lane that lost -95/-45/-24$ on 2026-09-08/09
        # while the confirmed pullback lane won. Same evidence, same gate.
        if smc_conf >= SMC_CONF_FLOOR and m5_ok:
            bp = build_trade_blueprint(plan, price=price, trigger_ok=True)
            bp = _reanchor_blueprint(bp, price, atr_val)
            return {
                "action": "market_entry_now",
                "zone": "premium",
                "execution_style": "aggressive_premium_entry",
                "blueprint": bp,
                "at": now.isoformat(),
            }
    if price <= zones["value_high"]:
        # Aggressive: in premium zone with strong bullish bias, enter long
        near_value_high = abs(price - zones["value_high"]) < (zones["value_high"] - zones["value_low"]) * 0.3
        if near_value_high and plan.get("bias") == "bullish":
            smc_conf = plan.get("quality", {}).get("smc_confidence", 0) or 0
            if smc_conf >= SMC_CONF_FLOOR and m5_ok:  # b193: no unconfirmed aggressive entry
                bp = build_trade_blueprint(plan, price=price, trigger_ok=True)
                bp = _reanchor_blueprint(
                    bp, price, float(plan.get("atr") or plan.get("quality", {}).get("atr") or 20)
                )
                return {
                    "action": "market_entry_now",
                    "zone": "value_zone",
                    "execution_style": "aggressive_value_entry",
                    "blueprint": bp,
                    "at": now.isoformat(),
                }
        return {
            "action": "no_trade",
            "reason": "outside_entry_zones",
            "zone": classify_price_location(price, zones),
            "execution_style": "hold_bias_wait_better_price",
            "at": now.isoformat(),
        }

    if price <= zones["short_entry_high"]:
        # b193b: phantom, mirror of the limit branches - no resting stop order is
        # ever placed by the runtime. The breakout intent is only executable as
        # an aggressive market entry (above), which b193 gates on m5_ok. Here
        # the honest state is: waiting, not "order pending".
        return {
            "action": "wait_for_trigger",
            "reason": "breakout_unconfirmed",
            "zone": classify_price_location(price, zones),
            "target_entry": breakout_trigger,
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


def _sell_logic(plan: dict, price: float, trigger_ok: bool, now: datetime,
                m5_ok: bool = True) -> dict:
    zones = plan["zones"]
    execution = plan.get("execution", {})
    breakout_trigger = execution.get("breakout_trigger", zones["long_entry_high"])

    if zones["short_entry_low"] <= price <= zones["short_entry_high"]:
        if trigger_ok:
            bp = build_trade_blueprint(plan, price=price, trigger_ok=trigger_ok)
            bp = _reanchor_blueprint(
                bp, price, float(plan.get("atr") or plan.get("quality", {}).get("atr") or 20)
            )
            return {
                "action": "market_entry_now",
                "zone": "short_zone",
                "execution_style": "pullback_continuation",
                "blueprint": bp,
                "at": now.isoformat(),
            }
        return {
            "action": "wait_for_trigger",
            "zone": "short_zone",
            "execution_style": "pullback_wait",
            "at": now.isoformat(),
        }

    if price > zones["short_entry_high"]:
        # b193b: mirror of the buy-side phantom-limit fix. Never placed, and a
        # resting sell-limit would fill on unconfirmed pushes back into the
        # short zone - the adverse selection b187 removed. Wait honestly.
        return {
            "action": "wait_for_pullback",
            "reason": "above_short_zone",
            "zone": "premium",
            "target_entry": zones["short_entry_high"],
            "execution_style": "pullback_wait",
            "at": now.isoformat(),
        }

    if price >= breakout_trigger:
        # Aggressive: if price is near value_low and trending, allow entry
        near_value_low = abs(price - zones["value_low"]) < (zones["value_high"] - zones["value_low"]) * 0.3
        if near_value_low and plan.get("quality", {}).get("smc_confidence", 0) >= SMC_CONF_FLOOR and m5_ok:  # b193
            bp = build_trade_blueprint(plan, price=price, trigger_ok=True)
            bp = _reanchor_blueprint(
                bp, price, float(plan.get("atr") or plan.get("quality", {}).get("atr") or 20)
            )
            return {
                "action": "market_entry_now",
                "zone": "value_zone",
                "execution_style": "aggressive_value_entry",
                "blueprint": bp,
                "at": now.isoformat(),
            }
        return {
            "action": "wait_for_pullback",
            "reason": "inside_value_without_trigger",
            "zone": classify_price_location(price, zones),
            "execution_style": "hold_bias_wait_better_price",
            "at": now.isoformat(),
        }

    # Aggressive: in discount zone with strong bearish bias, enter short
    # BUT only if price is close to the zone (not 100+ points away = stale plan)
    if price < zones["value_low"] and plan.get("bias") == "bearish":
        smc_conf = plan.get("quality", {}).get("smc_confidence", 0) or 0
        atr_val = float(plan.get("atr") or plan.get("quality", {}).get("atr") or 20)
        dist_below = zones["value_low"] - price
        if dist_below > atr_val * 1.5:
            return {
                "action": "no_trade",
                "reason": "price_far_below_zone_plan_stale",
                "zone": "discount",
                "execution_style": "wait_for_replan",
                "at": now.isoformat(),
            }
        if smc_conf >= SMC_CONF_FLOOR and m5_ok:  # b193: no unconfirmed aggressive entry
            # Re-anchor the blueprint to current market conditions, otherwise the
            # stale plan TP (far below after a long move) breaks trade geometry.
            bp = build_trade_blueprint(plan, price=price, trigger_ok=True)
            bp = _reanchor_blueprint(
                bp, price, float(plan.get("atr") or plan.get("quality", {}).get("atr") or 20)
            )
            return {
                "action": "market_entry_now",
                "zone": "discount",
                "execution_style": "aggressive_discount_entry",
                "blueprint": bp,
                "at": now.isoformat(),
            }
        return {
            "action": "wait_for_pullback",
            "reason": "discount_zone_with_weak_smc",
            "zone": classify_price_location(price, zones),
            "execution_style": "extended_wait",
            "at": now.isoformat(),
        }

    if price >= zones["long_entry_low"]:
        # b193b: phantom sell-stop, mirror of the buy side - never placed.
        return {
            "action": "wait_for_trigger",
            "reason": "breakout_unconfirmed",
            "zone": classify_price_location(price, zones),
            "target_entry": breakout_trigger,
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


def decide_execution_action(plan: dict, price: float, trigger_ok: bool, now: datetime,
                            m5_ok: bool = True) -> dict:
    # A neutral plan is an explicit no-trade state.  Never route it through
    # the bearish branch below; that could produce sell-stop/limit proposals.
    if plan.get("bias") == "neutral":
        return {
            "action": "no_trade",
            "reason": "neutral_bias",
            "zone": classify_price_location(price, plan["zones"]),
            "at": now.isoformat(),
        }
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
        return _buy_logic(plan, price=price, trigger_ok=trigger_ok, now=now, m5_ok=m5_ok)
    return _sell_logic(plan, price=price, trigger_ok=trigger_ok, now=now, m5_ok=m5_ok)
